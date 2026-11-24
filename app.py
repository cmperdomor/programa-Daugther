from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
import math
import time as time_module

import pandas as pd
import streamlit as st
import extra_streamlit_components as stx
from cryptography.fernet import Fernet, InvalidToken
from supabase import create_client

st.set_page_config(
    page_title="Daughter Lift",
    page_icon="🏋️",
    layout="centered",
)

SUPABASE_URL = st.secrets["SUPABASE_URL"].strip()
SUPABASE_KEY = st.secrets["SUPABASE_PUBLISHABLE_KEY"].strip()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Persistent browser login. The refresh token is encrypted before it is stored
# in a browser cookie. SESSION_COOKIE_SECRET must be a Fernet-compatible key.
try:
    SESSION_COOKIE_SECRET = st.secrets["SESSION_COOKIE_SECRET"].strip()
except Exception:
    SESSION_COOKIE_SECRET = ""

SESSION_COOKIE_NAME = "daughter_lift_session_v1"
SESSION_COOKIE_DAYS = 30
try:
    SESSION_FERNET = Fernet(SESSION_COOKIE_SECRET.encode()) if SESSION_COOKIE_SECRET else None
except Exception:
    SESSION_FERNET = None

cookie_manager = stx.CookieManager(key="daughter_lift_cookie_manager")

AUTH_KEYS = ["access_token", "refresh_token", "user_id", "user_email"]
WORKOUT_STATE_KEYS = [
    "current_exercise_instance_id",
    "current_exercise_id",
    "current_exercise_name",
    "current_equipment",
    "current_movement_type",
    "current_variant_key",
    "current_implement_count",
]

PAGE_HOME = "🏠 Home"
PAGE_WORKOUT = "🏋️ Workout"
PAGE_PROGRESS = "📈 Progress"
PAGE_HISTORY = "📚 History"
PAGE_PROFILE = "👤 Profile"
PAGE_HELP = "How to use"
PAGE_ADMIN = "🛡️ Admin"


# ============================================================
# AUTH
# ============================================================

def _cookie_key(action):
    seq = int(st.session_state.get("_cookie_seq", 0)) + 1
    st.session_state["_cookie_seq"] = seq
    return f"{action}_{seq}"


def _encrypt_refresh_token(refresh_token):
    if not SESSION_FERNET or not refresh_token:
        return None
    return SESSION_FERNET.encrypt(refresh_token.encode()).decode()


def _decrypt_refresh_token(value):
    if not SESSION_FERNET or not value:
        return None
    try:
        return SESSION_FERNET.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return None


def persist_refresh_token(refresh_token):
    encrypted = _encrypt_refresh_token(refresh_token)
    if not encrypted:
        return False
    try:
        current_url = str(getattr(st.context, "url", "") or "")
        cookie_manager.set(
            SESSION_COOKIE_NAME,
            encrypted,
            key=_cookie_key("set_auth_cookie"),
            path="/",
            expires_at=datetime.now() + timedelta(days=SESSION_COOKIE_DAYS),
            secure=current_url.startswith("https://"),
            same_site="lax",
        )
        return True
    except Exception:
        return False


def remove_persistent_login():
    try:
        cookie_manager.delete(
            SESSION_COOKIE_NAME,
            key=_cookie_key("delete_auth_cookie"),
        )
    except Exception:
        pass


def clear_auth_state():
    for key in AUTH_KEYS + ["nav_page"] + WORKOUT_STATE_KEYS:
        st.session_state.pop(key, None)


def save_auth_session(auth_response, persist=True):
    if auth_response is None or auth_response.session is None:
        return False

    previous_refresh = st.session_state.get("refresh_token")
    session = auth_response.session
    user = auth_response.user or session.user

    st.session_state["access_token"] = session.access_token
    st.session_state["refresh_token"] = session.refresh_token
    st.session_state["user_id"] = user.id
    st.session_state["user_email"] = user.email

    # Supabase rotates refresh tokens. Update the encrypted browser cookie only
    # when a new refresh token is issued.
    if persist and session.refresh_token and session.refresh_token != previous_refresh:
        persist_refresh_token(session.refresh_token)
    return True


def restore_auth_session():
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")

    # Normal Streamlit rerun: restore the session into the new Supabase client.
    if access_token and refresh_token:
        try:
            response = supabase.auth.set_session(access_token, refresh_token)
            if save_auth_session(response, persist=True):
                return True
        except Exception:
            clear_auth_state()

    # New Streamlit session / browser reload / app wake-up: restore from the
    # encrypted refresh-token cookie.
    if SESSION_FERNET:
        try:
            encrypted = cookie_manager.get(SESSION_COOKIE_NAME)
        except Exception:
            encrypted = None

        stored_refresh = _decrypt_refresh_token(encrypted)
        if stored_refresh:
            try:
                response = supabase.auth.refresh_session(stored_refresh)
                if save_auth_session(response, persist=True):
                    return True
            except Exception:
                remove_persistent_login()

    clear_auth_state()
    return False


def logout():
    try:
        # Default Supabase sign-out may revoke the session. The local browser
        # cookie is removed as well so this device stays signed out.
        supabase.auth.sign_out()
    except Exception:
        pass
    remove_persistent_login()
    clear_auth_state()


def go_to(page_name):
    st.session_state["nav_page"] = page_name


# ============================================================
# PROFILE / BODY WEIGHT
# ============================================================

def get_profile(user_id):
    response = (
        supabase.table("profiles")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def update_profile(user_id, display_name, age, height_cm):
    return (
        supabase.table("profiles")
        .update(
            {
                "display_name": display_name.strip(),
                "age": int(age),
                "height_cm": float(height_cm),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("user_id", user_id)
        .execute()
    )


def get_last_weight(user_id):
    response = (
        supabase.table("body_measurements")
        .select("id, measured_at, weight_kg")
        .eq("user_id", user_id)
        .order("measured_at", desc=True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def save_body_weight(user_id, weight_kg, measurement_date):
    measured_at = datetime.combine(
        measurement_date, time(12, 0), tzinfo=timezone.utc
    )
    return (
        supabase.table("body_measurements")
        .insert(
            {
                "user_id": user_id,
                "weight_kg": float(weight_kg),
                "measured_at": measured_at.isoformat(),
            }
        )
        .execute()
    )


def get_weight_history(user_id, limit=100):
    response = (
        supabase.table("body_measurements")
        .select("id, measured_at, weight_kg")
        .eq("user_id", user_id)
        .order("measured_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


def parse_ts(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def has_completed_workout(user_id):
    response = (
        supabase.table("workouts")
        .select("id")
        .eq("user_id", user_id)
        .eq("status", "completed")
        .limit(1)
        .execute()
    )
    return bool(response.data)


def render_how_to_use():
    st.markdown("""
### Getting started

**1. Start a workout**  
Choose Lower Body, Upper Body, or Core.

**2. Choose an exercise and the equipment you are actually using**  
The same exercise on different equipment is tracked as a different setup so the progress comparison stays meaningful.

**3. Record every working set**  
Enter the load, repetitions, and optionally RIR. Press **Add set** after each set.

**4. Rest before the next set**  
The rest timer starts automatically after a set is saved. You can choose the rest duration, add 30 seconds, or skip it.

**5. Continue or correct mistakes**  
Use **Edit set** if you entered the wrong weight, repetitions, or RIR. Use **Next exercise** when you are finished with the current exercise.

**6. Finish the workout**  
Press **Finish workout** so the session becomes part of your Progress and History.

### Key terms

**Reps (repetitions):** how many complete repetitions you performed.  
**RIR (Reps In Reserve):** how many additional good repetitions you think you could have performed. RIR 0 means no more good reps were possible.  
**1RM (One-Repetition Maximum):** the maximum load you can actually lift once.  
**e1RM (Estimated One-Repetition Maximum):** a calculated estimate, not a directly measured maximum.

### How Daughter Lift measures progress

The main comparison is **the same exercise + the same equipment/setup over time**. Progress can mean lifting more weight, doing more repetitions at the same weight, or both.

Machine and cable loads are compared only within the same exercise/setup because different machines can have different mechanical characteristics.
""")


# ============================================================
# REST TIMER
# ============================================================

def clear_rest_timer():
    for key in ["rest_timer_end", "rest_timer_finished"]:
        st.session_state.pop(key, None)


def start_rest_timer(seconds):
    seconds = max(15, int(seconds))
    st.session_state["rest_timer_end"] = time_module.time() + seconds
    st.session_state["rest_timer_finished"] = False


@st.fragment(run_every=1)
def render_rest_timer_fragment():
    end = st.session_state.get("rest_timer_end")
    if not end:
        return

    remaining = max(0, int(math.ceil(float(end) - time_module.time())))
    if remaining <= 0:
        st.session_state.pop("rest_timer_end", None)
        st.session_state["rest_timer_finished"] = True
        st.rerun()
        return

    minutes, seconds = divmod(remaining, 60)
    st.metric("Rest timer", f"{minutes:02d}:{seconds:02d}")
    add_col, skip_col = st.columns(2)
    with add_col:
        if st.button("+30 sec", key="rest_timer_plus_30", use_container_width=True):
            st.session_state["rest_timer_end"] = float(end) + 30
            st.rerun(scope="fragment")
    with skip_col:
        if st.button("Skip rest", key="rest_timer_skip", use_container_width=True):
            clear_rest_timer()
            st.rerun()


# ============================================================
# WORKOUT DATA
# ============================================================

def clear_current_exercise():
    for key in WORKOUT_STATE_KEYS:
        st.session_state.pop(key, None)


def get_active_workout(user_id):
    response = (
        supabase.table("workouts")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "active")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def create_workout(user_id, workout_type):
    # Extra guard in the app. RLS remains the real security boundary.
    existing = get_active_workout(user_id)
    if existing:
        return existing

    response = (
        supabase.table("workouts")
        .insert(
            {
                "user_id": user_id,
                "workout_date": date.today().isoformat(),
                "workout_type": workout_type,
                "status": "active",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .execute()
    )
    return response.data[0]


def finish_workout(workout_id, user_id):
    clear_current_exercise()
    return (
        supabase.table("workouts")
        .update(
            {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", workout_id)
        .eq("user_id", user_id)
        .execute()
    )


def update_workout_type(workout_id, user_id, workout_type):
    return (
        supabase.table("workouts")
        .update(
            {
                "workout_type": workout_type,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", workout_id)
        .eq("user_id", user_id)
        .execute()
    )


def cancel_workout(workout_id, user_id):
    clear_current_exercise()
    return (
        supabase.table("workouts")
        .update(
            {
                "status": "cancelled",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", workout_id)
        .eq("user_id", user_id)
        .execute()
    )


def delete_exercise_instance(exercise_instance_id, user_id):
    # Delete child rows first so this works even without ON DELETE CASCADE.
    (
        supabase.table("sets")
        .delete()
        .eq("exercise_instance_id", exercise_instance_id)
        .eq("user_id", user_id)
        .execute()
    )
    return (
        supabase.table("exercise_instances")
        .delete()
        .eq("id", exercise_instance_id)
        .eq("user_id", user_id)
        .execute()
    )


def update_exercise_instance_setup(
    exercise_instance_id,
    user_id,
    equipment,
    movement_type,
    variant_key,
):
    return (
        supabase.table("exercise_instances")
        .update(
            {
                "equipment": equipment,
                "movement_type": movement_type,
                "variant_key": variant_key,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", exercise_instance_id)
        .eq("user_id", user_id)
        .execute()
    )


def get_exercise_instances(workout_id, user_id):
    response = (
        supabase.table("exercise_instances")
        .select("*")
        .eq("workout_id", workout_id)
        .eq("user_id", user_id)
        .order("exercise_number")
        .execute()
    )
    return response.data or []


def create_exercise_instance(
    user_id,
    workout_id,
    exercise_number,
    exercise_id,
    exercise_name,
    equipment,
    movement_type,
    variant_key,
):
    response = (
        supabase.table("exercise_instances")
        .insert(
            {
                "user_id": user_id,
                "workout_id": workout_id,
                "exercise_number": int(exercise_number),
                "exercise_id": exercise_id,
                "exercise_name": exercise_name,
                "equipment": equipment,
                "movement_type": movement_type,
                "tracking_type": "weight_reps",
                "variant_key": variant_key,
                "bodyweight_mode": None,
            }
        )
        .execute()
    )
    return response.data[0]


def get_sets(exercise_instance_id, user_id):
    response = (
        supabase.table("sets")
        .select("*")
        .eq("exercise_instance_id", exercise_instance_id)
        .eq("user_id", user_id)
        .order("set_num")
        .order("side")
        .execute()
    )
    return response.data or []


def _to_kg(value, unit):
    value = float(value)
    return value * 0.45359237 if unit == "lb" else value


def _rir_value(rir):
    return None if rir == "Not recorded" else float(rir)


def build_set_payload(
    user_id,
    workout_id,
    exercise_instance_id,
    set_num,
    side,
    weight,
    unit,
    total_load,
    reps,
    rir,
    implement_count=None,
):
    return {
        "user_id": user_id,
        "workout_id": workout_id,
        "exercise_instance_id": exercise_instance_id,
        "set_num": int(set_num),
        "side": side,
        # For Dumbbells this is weight PER dumbbell. For barbell/machine it is
        # the entered/displayed load. This is the value used for exercise progress.
        "weight_original": float(weight),
        "original_unit": unit,
        "weight_kg": _to_kg(weight, unit),
        "total_load_original": float(total_load),
        "total_load_kg": _to_kg(total_load, unit),
        "reps": int(reps),
        "rir": _rir_value(rir),
        "implement_count": int(implement_count) if implement_count else None,
    }


def add_bilateral_set(**kwargs):
    payload = build_set_payload(side="Bilateral", **kwargs)
    return supabase.table("sets").insert(payload).execute()


def add_unilateral_set_pair(
    *,
    user_id,
    workout_id,
    exercise_instance_id,
    set_num,
    weight,
    unit,
    total_load,
    reps_left,
    reps_right,
    rir_left,
    rir_right,
    implement_count=None,
):
    # One PostgREST insert containing both rows. This prevents the common case
    # where Left is saved and Right is lost after a connection error.
    rows = [
        build_set_payload(
            user_id=user_id,
            workout_id=workout_id,
            exercise_instance_id=exercise_instance_id,
            set_num=set_num,
            side="Left",
            weight=weight,
            unit=unit,
            total_load=total_load,
            reps=reps_left,
            rir=rir_left,
            implement_count=implement_count,
        ),
        build_set_payload(
            user_id=user_id,
            workout_id=workout_id,
            exercise_instance_id=exercise_instance_id,
            set_num=set_num,
            side="Right",
            weight=weight,
            unit=unit,
            total_load=total_load,
            reps=reps_right,
            rir=rir_right,
            implement_count=implement_count,
        ),
    ]
    return supabase.table("sets").insert(rows).execute()


def delete_logical_set(exercise_instance_id, set_num, user_id):
    # Bilateral = one DB row; unilateral = Left + Right rows. Both are deleted
    # together because the user thinks of them as one set.
    return (
        supabase.table("sets")
        .delete()
        .eq("exercise_instance_id", exercise_instance_id)
        .eq("set_num", int(set_num))
        .eq("user_id", user_id)
        .execute()
    )


def update_bilateral_set(
    *,
    exercise_instance_id,
    set_num,
    user_id,
    weight,
    unit,
    total_load,
    reps,
    rir,
    implement_count=None,
):
    payload = build_set_payload(
        user_id=user_id,
        workout_id="placeholder",
        exercise_instance_id=exercise_instance_id,
        set_num=set_num,
        side="Bilateral",
        weight=weight,
        unit=unit,
        total_load=total_load,
        reps=reps,
        rir=rir,
        implement_count=implement_count,
    )
    update_values = {
        k: v
        for k, v in payload.items()
        if k not in {"user_id", "workout_id", "exercise_instance_id", "set_num", "side"}
    }
    return (
        supabase.table("sets")
        .update(update_values)
        .eq("exercise_instance_id", exercise_instance_id)
        .eq("set_num", int(set_num))
        .eq("side", "Bilateral")
        .eq("user_id", user_id)
        .execute()
    )


def update_unilateral_set_pair(
    *,
    exercise_instance_id,
    set_num,
    user_id,
    weight,
    unit,
    total_load,
    reps_left,
    reps_right,
    rir_left,
    rir_right,
    implement_count=None,
):
    common = {
        "weight_original": float(weight),
        "original_unit": unit,
        "weight_kg": _to_kg(weight, unit),
        "total_load_original": float(total_load),
        "total_load_kg": _to_kg(total_load, unit),
        "implement_count": int(implement_count) if implement_count else None,
    }
    left_values = {**common, "reps": int(reps_left), "rir": _rir_value(rir_left)}
    right_values = {**common, "reps": int(reps_right), "rir": _rir_value(rir_right)}

    (
        supabase.table("sets")
        .update(left_values)
        .eq("exercise_instance_id", exercise_instance_id)
        .eq("set_num", int(set_num))
        .eq("side", "Left")
        .eq("user_id", user_id)
        .execute()
    )
    return (
        supabase.table("sets")
        .update(right_values)
        .eq("exercise_instance_id", exercise_instance_id)
        .eq("set_num", int(set_num))
        .eq("side", "Right")
        .eq("user_id", user_id)
        .execute()
    )


def get_custom_exercises(user_id, workout_type):
    response = (
        supabase.table("custom_exercises")
        .select("id, user_id, exercise_id, name, workout_type")
        .eq("user_id", user_id)
        .eq("workout_type", workout_type)
        .order("name")
        .execute()
    )
    return response.data or []


def save_custom_exercise(user_id, name, workout_type):
    clean_name = " ".join(name.strip().split())
    existing = get_custom_exercises(user_id, workout_type)
    if any(x.get("name", "").strip().lower() == clean_name.lower() for x in existing):
        raise ValueError("You already have a custom exercise with that name.")

    exercise_id = f"custom_{uuid4().hex}"
    response = (
        supabase.table("custom_exercises")
        .insert(
            {
                "user_id": user_id,
                "exercise_id": exercise_id,
                "name": clean_name,
                "workout_type": workout_type,
            }
        )
        .execute()
    )
    return response.data[0]


def get_strength_data(user_id):
    """Return normalized set-level strength data for completed workouts only."""
    workouts = (
        supabase.table("workouts")
        .select("id, workout_date, started_at, status, workout_type")
        .eq("user_id", user_id)
        .eq("status", "completed")
        .order("workout_date")
        .execute()
    ).data or []

    instances = (
        supabase.table("exercise_instances")
        .select(
            "id, workout_id, exercise_id, exercise_name, equipment, "
            "movement_type, tracking_type, variant_key"
        )
        .eq("user_id", user_id)
        .eq("tracking_type", "weight_reps")
        .execute()
    ).data or []

    sets = (
        supabase.table("sets")
        .select(
            "id, workout_id, exercise_instance_id, set_num, side, "
            "weight_original, original_unit, weight_kg, total_load_original, "
            "total_load_kg, reps, rir, implement_count"
        )
        .eq("user_id", user_id)
        .execute()
    ).data or []

    if not workouts or not instances or not sets:
        return pd.DataFrame()

    w = pd.DataFrame(workouts).rename(columns={"id": "workout_id"})
    e = pd.DataFrame(instances).rename(columns={"id": "exercise_instance_id"})
    s = pd.DataFrame(sets)

    df = s.merge(e, on=["exercise_instance_id", "workout_id"], how="inner")
    df = df.merge(w[["workout_id", "workout_date", "started_at", "status"]], on="workout_id", how="inner")

    df["weight_kg"] = pd.to_numeric(df["weight_kg"], errors="coerce")
    df["reps"] = pd.to_numeric(df["reps"], errors="coerce")
    df["set_num"] = pd.to_numeric(df["set_num"], errors="coerce")
    df["workout_date"] = pd.to_datetime(df["workout_date"], errors="coerce")
    df = df.dropna(subset=["weight_kg", "reps", "workout_date"])
    return df


def collapse_unilateral_sets(df):
    """One logical set per set_num. For unilateral work use the weaker-side reps.

    Estimated 1RM (e1RM) is secondary. When RIR is available, Epley uses
    reps + RIR as an estimate of reps-to-failure.
    """
    if df.empty:
        return df

    group_cols = [
        "workout_id",
        "workout_date",
        "exercise_instance_id",
        "exercise_id",
        "exercise_name",
        "equipment",
        "movement_type",
        "variant_key",
        "set_num",
    ]

    rows = []
    for _, group in df.groupby(group_cols, dropna=False):
        first = group.iloc[0]

        if str(first.get("movement_type")) == "Unilateral":
            min_reps = group["reps"].min()
            weaker_rows = group[group["reps"] == min_reps]
            chosen = weaker_rows.iloc[0]
            reps = float(min_reps)
            rir = chosen.get("rir")
        else:
            chosen = first
            reps = float(first["reps"])
            rir = first.get("rir")

        weight_kg = float(chosen["weight_kg"])
        rir_num = pd.to_numeric(pd.Series([rir]), errors="coerce").iloc[0]
        effective_reps = reps + (float(rir_num) if pd.notna(rir_num) else 0.0)

        e1rm = None
        if 1 <= reps <= 10 and 1 <= effective_reps <= 12 and pd.notna(weight_kg):
            e1rm = weight_kg * (1 + effective_reps / 30.0)

        rows.append(
            {
                "workout_id": first["workout_id"],
                "workout_date": first["workout_date"],
                "exercise_instance_id": first["exercise_instance_id"],
                "exercise_id": first["exercise_id"],
                "exercise_name": first["exercise_name"],
                "equipment": first["equipment"],
                "movement_type": first["movement_type"],
                "variant_key": first["variant_key"],
                "set_num": int(first["set_num"]),
                "weight_kg": weight_kg,
                "reps": int(reps),
                "rir": None if pd.isna(rir_num) else float(rir_num),
                "e1rm": e1rm,
                "implement_count": first.get("implement_count"),
            }
        )

    return pd.DataFrame(rows)


# ============================================================
# EXERCISE CATALOG
# Focused on weight + reps progression.
# ============================================================

EXERCISE_CATALOG = {
    "Lower Body": [
        {
            "id": "hip_thrust",
            "name": "Hip Thrust",
            "equipment": ["Barbell", "Smith Machine", "Plate-loaded Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "bulgarian_split_squat",
            "name": "Bulgarian Split Squat",
            "equipment": ["Dumbbells", "Barbell", "Smith Machine"],
            "movement_type": "Unilateral",
        },
        {
            "id": "leg_press",
            "name": "Leg Press",
            "equipment": ["Plate-loaded Machine", "Selectorized Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "romanian_deadlift",
            "name": "Romanian Deadlift",
            "equipment": ["Barbell", "Dumbbells", "Smith Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "squat",
            "name": "Squat",
            "equipment": ["Barbell", "Dumbbells", "Smith Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "leg_extension",
            "name": "Leg Extension",
            "equipment": ["Selectorized Machine", "Plate-loaded Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "leg_curl",
            "name": "Leg Curl",
            "equipment": ["Selectorized Machine", "Plate-loaded Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "cable_kickback",
            "name": "Cable Kickback",
            "equipment": ["Cable"],
            "movement_type": "Unilateral",
        },
        {
            "id": "step_up",
            "name": "Step Up",
            "equipment": ["Dumbbells", "Barbell", "Cable", "Smith Machine"],
            "movement_type": "Unilateral",
        },
    ],
    "Upper Body": [
        {
            "id": "bench_press",
            "name": "Bench Press",
            "equipment": ["Barbell", "Dumbbells", "Smith Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "lat_pulldown",
            "name": "Lat Pulldown",
            "equipment": ["Cable", "Selectorized Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "seated_row",
            "name": "Seated Row",
            "equipment": ["Cable", "Selectorized Machine", "Plate-loaded Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "shoulder_press",
            "name": "Shoulder Press",
            "equipment": ["Dumbbells", "Barbell", "Smith Machine", "Selectorized Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "lateral_raise",
            "name": "Lateral Raise",
            "equipment": ["Dumbbells", "Cable", "Selectorized Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "dumbbell_front_raise",
            "name": "Dumbbell Front Raise",
            "equipment": ["Dumbbells"],
            # Can be performed with both arms together or one side at a time.
            "movement_type": None,
        },
        {
            "id": "pec_deck_fly",
            "name": "Pec Deck Fly",
            "equipment": ["Selectorized Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "reverse_pec_deck",
            "name": "Reverse Pec Deck",
            "equipment": ["Selectorized Machine"],
            "movement_type": "Bilateral",
        },
        {
            "id": "biceps_curl",
            "name": "Biceps Curl",
            "equipment": [
                "Dumbbells",
                "Barbell",
                "Cable",
                "Selectorized Machine",
                "Plate-loaded Machine",
            ],
            # Biceps curls can be performed with both arms together or one side at a time,
            # depending on the cable, dumbbells, or machine being used.
            "movement_type": None,
        },
        {
            "id": "triceps_pushdown",
            "name": "Triceps Pushdown",
            "equipment": ["Cable"],
            "movement_type": "Bilateral",
        },
    ],
    "Core": [
        {
            "id": "cable_crunch",
            "name": "Cable Crunch",
            "equipment": ["Cable"],
            "movement_type": "Bilateral",
        },
    ],
}

ALL_EQUIPMENT = [
    "Barbell",
    "Dumbbells",
    "Smith Machine",
    "Cable",
    "Plate-loaded Machine",
    "Selectorized Machine",
    "Other",
]


def combined_catalog(user_id, workout_type):
    built_in = [dict(x, custom=False) for x in EXERCISE_CATALOG.get(workout_type, [])]
    custom = []
    try:
        for row in get_custom_exercises(user_id, workout_type):
            custom.append(
                {
                    "id": row["exercise_id"],
                    "name": row["name"],
                    "equipment": ALL_EQUIPMENT,
                    "movement_type": None,
                    "custom": True,
                }
            )
    except Exception:
        pass
    return built_in + custom


# ============================================================
# HEADER + AUTH SCREENS
# ============================================================

st.title("🏋️ Daughter Lift")
st.caption("Train. Track. Progress.")

logged_in = restore_auth_session()

if not logged_in:
    st.subheader("Welcome")
    sign_in_tab, create_tab, reset_tab = st.tabs(
        ["Sign in", "Create account", "Forgot password?"]
    )

    with sign_in_tab:
        with st.form("sign_in_form"):
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)

        if submitted:
            if not email.strip() or not password:
                st.warning("Enter your email and password.")
            else:
                try:
                    response = supabase.auth.sign_in_with_password(
                        {"email": email.strip(), "password": password}
                    )
                    if save_auth_session(response, persist=True):
                        # Give the browser component a moment to write the encrypted
                        # refresh-token cookie before the full rerun.
                        time_module.sleep(0.25)
                        st.rerun()
                    else:
                        st.error("Login did not create a session.")
                except Exception:
                    st.error("Could not sign in. Check your email and password.")

    with create_tab:
        with st.form("create_account_form"):
            display_name = st.text_input("Name or alias", placeholder="Claudia")
            new_email = st.text_input("Email", key="signup_email")
            new_password = st.text_input(
                "Create password", type="password", key="signup_password"
            )
            repeat_password = st.text_input("Repeat password", type="password")
            consent = st.checkbox(
                "I agree to the Privacy Policy and consent to the processing of "
                "my fitness and body-measurement data."
            )
            create = st.form_submit_button("Create account", use_container_width=True)

        if create:
            if not display_name.strip():
                st.warning("Enter a name or alias.")
            elif not new_email.strip():
                st.warning("Enter an email.")
            elif len(new_password) < 8:
                st.warning("Use at least 8 characters.")
            elif new_password != repeat_password:
                st.warning("Passwords do not match.")
            elif not consent:
                st.warning("Consent is required.")
            else:
                try:
                    response = supabase.auth.sign_up(
                        {
                            "email": new_email.strip(),
                            "password": new_password,
                            "options": {
                                "data": {
                                    "display_name": display_name.strip(),
                                    "fitness_data_consent": True,
                                    "consent_version": "2026-10-03",
                                }
                            },
                        }
                    )
                    if save_auth_session(response, persist=True):
                        time_module.sleep(0.25)
                        st.rerun()
                    else:
                        st.success(
                            "Account created. Check your email to confirm it, then sign in."
                        )
                except Exception:
                    st.error("Could not create account.")

    with reset_tab:
        reset_email = st.session_state.get("password_reset_email", "")

        with st.form("password_reset_request_form"):
            recovery_email = st.text_input(
                "Email",
                value=reset_email,
                key="password_reset_request_email",
            )
            send_recovery = st.form_submit_button(
                "Send recovery code",
                use_container_width=True,
            )

        if send_recovery:
            if not recovery_email.strip():
                st.warning("Enter your email address.")
            else:
                try:
                    supabase.auth.reset_password_for_email(recovery_email.strip())
                    st.session_state["password_reset_email"] = recovery_email.strip()
                    st.session_state["password_reset_requested"] = True
                    st.success(
                        "If an account exists for this email, a recovery message has been sent. "
                        "Return here and enter the recovery code from the email."
                    )
                except Exception:
                    # Keep the message neutral so the app does not reveal whether
                    # an email is registered.
                    st.info(
                        "If an account exists for this email, a recovery message will be sent."
                    )

        if st.session_state.get("password_reset_requested") or reset_email:
            st.caption("Use the recovery code from the Daughter Lift password-reset email.")
            with st.form("password_reset_finish_form"):
                recovery_code = st.text_input(
                    "Recovery code",
                    placeholder="6-digit code",
                    key="password_reset_code",
                )
                reset_new_password = st.text_input(
                    "New password",
                    type="password",
                    key="password_reset_new_password",
                )
                reset_repeat_password = st.text_input(
                    "Repeat new password",
                    type="password",
                    key="password_reset_repeat_password",
                )
                finish_reset = st.form_submit_button(
                    "Set new password",
                    use_container_width=True,
                )

            if finish_reset:
                email_for_reset = st.session_state.get("password_reset_email", "").strip()
                if not email_for_reset:
                    st.warning("Enter your email and request a recovery code first.")
                elif not recovery_code.strip():
                    st.warning("Enter the recovery code from the email.")
                elif len(reset_new_password) < 8:
                    st.warning("Use at least 8 characters for the new password.")
                elif reset_new_password != reset_repeat_password:
                    st.warning("The new passwords do not match.")
                else:
                    try:
                        verified = supabase.auth.verify_otp(
                            {
                                "email": email_for_reset,
                                "token": recovery_code.strip(),
                                "type": "recovery",
                            }
                        )
                        if not save_auth_session(verified, persist=True):
                            raise RuntimeError("Recovery code did not create a session.")
                        supabase.auth.update_user({"password": reset_new_password})
                        st.session_state.pop("password_reset_email", None)
                        st.session_state.pop("password_reset_requested", None)
                        st.session_state["password_reset_success"] = True
                        time_module.sleep(0.25)
                        st.rerun()
                    except Exception:
                        st.error(
                            "The recovery code is invalid or expired. Request a new code and try again."
                        )

    if not SESSION_FERNET:
        st.caption(
            "Persistent login is not configured yet. Add SESSION_COOKIE_SECRET to Streamlit Secrets."
        )

    st.stop()


# ============================================================
# LOGGED IN SHELL
# ============================================================

user_id = st.session_state["user_id"]
user_email = st.session_state.get("user_email", "")

try:
    profile = get_profile(user_id)
except Exception as exc:
    st.error("Connected to Supabase, but could not load your profile.")
    st.caption(str(exc))
    st.stop()

if profile is None:
    st.error("Your login exists, but your profile row was not found.")
    st.stop()

display_name = profile.get("display_name") or "Athlete"
role = profile.get("role") or "user"
age = profile.get("age")
height_cm = profile.get("height_cm")

page_options = [PAGE_HOME, PAGE_WORKOUT, PAGE_PROGRESS, PAGE_HISTORY, PAGE_PROFILE, PAGE_HELP]
if role == "admin":
    page_options.append(PAGE_ADMIN)

if st.session_state.get("nav_page") not in page_options:
    st.session_state["nav_page"] = PAGE_HOME

if st.session_state.pop("password_reset_success", False):
    st.success("Password updated successfully. You are signed in.")

st.sidebar.markdown(f"### 👤 {display_name}")
st.sidebar.caption(user_email)
page = st.sidebar.radio("Navigation", page_options, key="nav_page")
st.sidebar.divider()

if st.sidebar.button("Sign out", use_container_width=True):
    logout()
    st.rerun()

profile_incomplete = age is None or height_cm is None
if profile_incomplete and page != PAGE_PROFILE:
    st.info("Complete your profile once. You will not need to enter it during workouts.")
    st.button("Complete profile", on_click=go_to, args=(PAGE_PROFILE,))


# ============================================================
# HOME
# ============================================================

if page == PAGE_HOME:
    st.header(f"Hi, {display_name} 👋")

    try:
        new_to_app = not has_completed_workout(user_id)
    except Exception:
        new_to_app = False

    if new_to_app:
        with st.expander("How to use Daughter Lift", expanded=True):
            render_how_to_use()

    st.subheader("Body weight")
    try:
        last_weight = get_last_weight(user_id)
    except Exception as exc:
        last_weight = None
        st.warning("Could not load your last weight.")
        st.caption(str(exc))

    if last_weight:
        measured = parse_ts(last_weight["measured_at"])
        st.metric("Last recorded", f"{float(last_weight['weight_kg']):.1f} kg")
        st.caption(measured.strftime("%d %b %Y"))
    else:
        st.write("No body-weight measurement recorded yet.")

    with st.expander("➕ Record body weight", expanded=False):
        with st.form("weight_form"):
            measurement_date = st.date_input("Date", value=date.today())
            weight = st.number_input(
                "Weight (kg)", min_value=20.0, max_value=300.0,
                value=None, step=0.1, placeholder="Example: 68.4"
            )
            save_weight = st.form_submit_button("Save weight", use_container_width=True)

        if save_weight:
            if weight is None:
                st.warning("Enter your weight.")
            else:
                try:
                    save_body_weight(user_id, weight, measurement_date)
                    st.success("Weight saved ✅")
                    st.rerun()
                except Exception as exc:
                    st.error("⚠️ The weight was NOT saved.")
                    st.caption(str(exc))

    st.divider()
    st.subheader("Today")
    st.write("Ready to train?")
    st.button(
        "▶ Start workout",
        use_container_width=True,
        on_click=go_to,
        args=(PAGE_WORKOUT,),
    )


# ============================================================
# WORKOUT
# ============================================================

elif page == PAGE_WORKOUT:
    st.header("🏋️ Workout")

    try:
        active_workout = get_active_workout(user_id)
    except Exception as exc:
        st.error("Could not load your workout.")
        st.caption(str(exc))
        st.stop()

    if active_workout is None:
        clear_current_exercise()
        st.subheader("Start workout")
        workout_type = st.selectbox(
            "Workout type",
            ["Lower Body", "Upper Body", "Core"],
            help="Choose the main focus of this workout. You can change it before logging exercises.",
        )
        if st.button("▶ Start workout", use_container_width=True, type="primary"):
            try:
                create_workout(user_id, workout_type)
                st.rerun()
            except Exception as exc:
                st.error("Workout could not be started.")
                st.caption(str(exc))

    else:
        workout_id = active_workout["id"]
        workout_type = active_workout["workout_type"]
        st.success(f"Active workout · {workout_type}")

        try:
            exercise_instances = get_exercise_instances(workout_id, user_id)
        except Exception as exc:
            st.error("Could not load exercises.")
            st.caption(str(exc))
            st.stop()

        # Workout settings: easy correction if Upper/Lower/Core was tapped by mistake.
        with st.expander("⚙️ Workout settings"):
            workout_types = ["Lower Body", "Upper Body", "Core"]
            selected_type = st.selectbox(
                "Workout type",
                workout_types,
                index=workout_types.index(workout_type) if workout_type in workout_types else 0,
                key="active_workout_type",
                help="If you chose the wrong workout type, correct it here.",
            )

            if not exercise_instances:
                if st.button("Save workout type", use_container_width=True):
                    try:
                        update_workout_type(workout_id, user_id, selected_type)
                        clear_current_exercise()
                        st.rerun()
                    except Exception as exc:
                        st.error("Workout type could not be changed.")
                        st.caption(str(exc))
            else:
                st.caption(
                    "Workout type is locked after exercises are added so Upper and Lower exercises "
                    "are not mixed accidentally. Delete the exercises first, or cancel this workout and start again."
                )

            confirm_cancel = st.checkbox(
                "I want to cancel this active workout",
                key="confirm_cancel_workout",
            )
            if st.button(
                "Cancel workout",
                use_container_width=True,
                disabled=not confirm_cancel,
            ):
                try:
                    cancel_workout(workout_id, user_id)
                    st.rerun()
                except Exception as exc:
                    st.error("Workout could not be cancelled.")
                    st.caption(str(exc))

        # Current exercise is session-state convenience only. The active workout itself
        # is always recovered from Supabase. After a browser refresh, use Resume.
        current_instance_id = st.session_state.get("current_exercise_instance_id")
        current_instance = next(
            (x for x in exercise_instances if x["id"] == current_instance_id),
            None,
        )
        if current_instance_id and current_instance is None:
            clear_current_exercise()
            current_instance_id = None

        # ----------------------------
        # Workout so far
        # ----------------------------
        if exercise_instances:
            st.subheader("Workout so far")

            for ex in exercise_instances:
                sets_done = get_sets(ex["id"], user_id)
                logical_count = len({int(x["set_num"]) for x in sets_done}) if sets_done else 0
                marker = "🟢" if ex["id"] == current_instance_id else "✅"

                col_info, col_resume, col_edit, col_delete = st.columns([5, 1.4, 1, 1])
                with col_info:
                    st.write(
                        f"{marker} **{ex['exercise_number']}. {ex['exercise_name']}** — "
                        f"{logical_count} set{'s' if logical_count != 1 else ''}"
                    )
                with col_resume:
                    if st.button(
                        "Resume",
                        key=f"resume_ex_{ex['id']}",
                        help="Open this exercise again and keep adding or correcting sets.",
                    ):
                        clear_current_exercise()
                        st.session_state["current_exercise_instance_id"] = ex["id"]
                        st.session_state["current_exercise_id"] = ex["exercise_id"]
                        st.session_state["current_exercise_name"] = ex["exercise_name"]
                        st.session_state["current_equipment"] = ex["equipment"]
                        st.session_state["current_movement_type"] = ex["movement_type"]
                        st.session_state["current_variant_key"] = ex.get("variant_key")
                        variant = ex.get("variant_key") or ""
                        if variant.endswith("|db1"):
                            st.session_state["current_implement_count"] = 1
                        elif variant.endswith("|db2"):
                            st.session_state["current_implement_count"] = 2
                        st.rerun()

                with col_edit:
                    if st.button(
                        "✏️",
                        key=f"edit_ex_{ex['id']}",
                        help="Correct the equipment or movement setup before sets are recorded.",
                    ):
                        st.session_state["edit_exercise_id"] = ex["id"]
                        st.rerun()

                with col_delete:
                    if st.button(
                        "🗑️",
                        key=f"delete_ex_{ex['id']}",
                        help="Delete this exercise and all of its sets.",
                    ):
                        try:
                            delete_exercise_instance(ex["id"], user_id)
                            if current_instance_id == ex["id"]:
                                clear_current_exercise()
                            st.session_state.pop("edit_exercise_id", None)
                            st.rerun()
                        except Exception as exc:
                            st.error("The exercise could not be deleted.")
                            st.caption(str(exc))

                if st.session_state.get("edit_exercise_id") == ex["id"]:
                    with st.expander("Edit exercise setup", expanded=True):
                        if sets_done:
                            st.info(
                                "This exercise already has recorded sets. To protect your progress history, "
                                "delete those sets first if the equipment or movement was entered incorrectly."
                            )
                            if st.button(
                                "Close",
                                key=f"close_edit_{ex['id']}",
                                use_container_width=True,
                            ):
                                st.session_state.pop("edit_exercise_id", None)
                                st.rerun()
                        else:
                            equipment_options = list(ALL_EQUIPMENT)
                            if ex.get("equipment") not in equipment_options:
                                equipment_options.append(ex.get("equipment"))

                            edited_equipment = st.selectbox(
                                "Equipment",
                                equipment_options,
                                index=equipment_options.index(ex.get("equipment")),
                                key=f"edit_equipment_{ex['id']}",
                                help="Progress is compared using the same exercise and setup, so equipment matters.",
                            )

                            movement_labels = {
                                "Both sides together": "Bilateral",
                                "One side at a time": "Unilateral",
                            }
                            current_label = (
                                "One side at a time"
                                if ex.get("movement_type") == "Unilateral"
                                else "Both sides together"
                            )
                            edited_label = st.radio(
                                "How are you performing it?",
                                list(movement_labels.keys()),
                                index=list(movement_labels.keys()).index(current_label),
                                horizontal=True,
                                key=f"edit_movement_{ex['id']}",
                                help=(
                                    "Both sides together: both arms or legs work at the same time. "
                                    "One side at a time: left and right are tracked separately."
                                ),
                            )
                            edited_movement = movement_labels[edited_label]

                            edited_count = None
                            if edited_equipment == "Dumbbells":
                                variant = ex.get("variant_key") or ""
                                default_count = 1 if variant.endswith("|db1") else 2
                                edited_count = st.radio(
                                    "How many dumbbells?",
                                    [1, 2],
                                    index=0 if default_count == 1 else 1,
                                    horizontal=True,
                                    key=f"edit_db_count_{ex['id']}",
                                    help="Example: two 14 kg dumbbells = select 2 and later enter 14 kg per dumbbell.",
                                )

                            edited_variant = f"{ex['exercise_id']}|{edited_equipment}|{edited_movement}"
                            if edited_equipment == "Dumbbells":
                                edited_variant += f"|db{edited_count}"

                            c_save, c_cancel = st.columns(2)
                            with c_save:
                                if st.button(
                                    "Save changes",
                                    key=f"save_edit_{ex['id']}",
                                    use_container_width=True,
                                ):
                                    try:
                                        update_exercise_instance_setup(
                                            ex["id"],
                                            user_id,
                                            edited_equipment,
                                            edited_movement,
                                            edited_variant,
                                        )
                                        if current_instance_id == ex["id"]:
                                            st.session_state["current_equipment"] = edited_equipment
                                            st.session_state["current_movement_type"] = edited_movement
                                            st.session_state["current_variant_key"] = edited_variant
                                            st.session_state["current_implement_count"] = edited_count
                                        st.session_state.pop("edit_exercise_id", None)
                                        st.rerun()
                                    except Exception as exc:
                                        st.error("Changes could not be saved.")
                                        st.caption(str(exc))
                            with c_cancel:
                                if st.button(
                                    "Cancel",
                                    key=f"cancel_edit_{ex['id']}",
                                    use_container_width=True,
                                ):
                                    st.session_state.pop("edit_exercise_id", None)
                                    st.rerun()

        # ----------------------------
        # Pick / create current exercise
        # ----------------------------
        if current_instance is None:
            next_exercise_number = max(
                [int(x["exercise_number"]) for x in exercise_instances],
                default=0,
            ) + 1
            st.subheader(f"Exercise {next_exercise_number}")

            catalog = combined_catalog(user_id, workout_type)
            names = [x["name"] for x in catalog] + ["➕ Add custom exercise"]

            pending_selection = st.session_state.pop("pending_exercise_selection", None)
            if pending_selection in names:
                st.session_state["exercise_picker"] = pending_selection

            selected_name = st.selectbox("Exercise", names, key="exercise_picker")

            if selected_name == "➕ Add custom exercise":
                with st.form("custom_exercise_form"):
                    custom_name = st.text_input(
                        "Exercise name",
                        placeholder="Example: Hack Squat",
                        help="Create an exercise that is not already in the Daughter Lift catalog.",
                    )
                    save_custom = st.form_submit_button(
                        "Save custom exercise",
                        use_container_width=True,
                    )
                if save_custom:
                    if not custom_name.strip():
                        st.warning("Enter an exercise name.")
                    else:
                        try:
                            saved_custom = save_custom_exercise(user_id, custom_name, workout_type)
                            st.session_state["pending_exercise_selection"] = saved_custom["name"]
                            st.success("Custom exercise saved.")
                            st.rerun()
                        except ValueError as exc:
                            st.info(str(exc))
                        except Exception:
                            st.error("Custom exercise could not be saved.")
            else:
                selected = next(x for x in catalog if x["name"] == selected_name)

                equipment = st.selectbox(
                    "Equipment",
                    selected["equipment"],
                    key="new_exercise_equipment",
                    help="The same exercise on different equipment is tracked as a different setup.",
                )

                movement_labels = {
                    "Both sides together": "Bilateral",
                    "One side at a time": "Unilateral",
                }
                if selected["custom"] or selected.get("movement_type") is None:
                    movement_label = st.radio(
                        "How are you performing it?",
                        list(movement_labels.keys()),
                        horizontal=True,
                        key="new_exercise_movement",
                        help=(
                            "Both sides together: both arms or legs work at the same time. "
                            "One side at a time: left and right are recorded separately."
                        ),
                    )
                    movement_type = movement_labels[movement_label]
                else:
                    movement_type = selected["movement_type"]
                    readable = (
                        "Both sides together"
                        if movement_type == "Bilateral"
                        else "One side at a time"
                    )
                    st.caption(f"Movement: {readable}")

                implement_count = None
                if equipment == "Dumbbells":
                    implement_count = st.radio(
                        "How many dumbbells?",
                        [1, 2],
                        horizontal=True,
                        key="new_exercise_db_count",
                        help="Example: two 14 kg dumbbells = select 2 and enter 14 kg per dumbbell.",
                    )

                variant_key = f"{selected['id']}|{equipment}|{movement_type}"
                if equipment == "Dumbbells":
                    variant_key += f"|db{implement_count}"

                try:
                    strength_df = collapse_unilateral_sets(get_strength_data(user_id))
                    previous = strength_df[strength_df["variant_key"] == variant_key]
                    if not previous.empty:
                        last_date = previous["workout_date"].max()
                        last = previous[previous["workout_date"] == last_date].sort_values("set_num")
                        text_sets = [
                            f"{r.weight_kg:g} kg × {int(r.reps)}"
                            for r in last.itertuples()
                        ]
                        st.caption("Last time: " + " · ".join(text_sets))
                except Exception:
                    pass

                if st.button("Start this exercise", use_container_width=True, type="primary"):
                    try:
                        instance = create_exercise_instance(
                            user_id=user_id,
                            workout_id=workout_id,
                            exercise_number=next_exercise_number,
                            exercise_id=selected["id"],
                            exercise_name=selected["name"],
                            equipment=equipment,
                            movement_type=movement_type,
                            variant_key=variant_key,
                        )
                        st.session_state["current_exercise_instance_id"] = instance["id"]
                        st.session_state["current_exercise_id"] = selected["id"]
                        st.session_state["current_exercise_name"] = selected["name"]
                        st.session_state["current_equipment"] = equipment
                        st.session_state["current_movement_type"] = movement_type
                        st.session_state["current_variant_key"] = variant_key
                        st.session_state["current_implement_count"] = implement_count
                        st.rerun()
                    except Exception as exc:
                        st.error("Exercise could not be started.")
                        st.caption(str(exc))

        # ----------------------------
        # Add / correct multiple sets
        # ----------------------------
        else:
            exercise_name = current_instance["exercise_name"]
            equipment = current_instance["equipment"]
            movement_type = current_instance["movement_type"]
            implement_count = st.session_state.get("current_implement_count")

            if equipment == "Dumbbells" and not implement_count:
                variant_key = current_instance.get("variant_key") or ""
                if variant_key.endswith("|db1"):
                    implement_count = 1
                elif variant_key.endswith("|db2"):
                    implement_count = 2
                else:
                    implement_count = 2

            st.subheader(exercise_name)
            readable_movement = (
                "Both sides together"
                if movement_type == "Bilateral"
                else "One side at a time"
            )
            st.caption(f"{equipment} · {readable_movement}")

            with st.expander("Rest timer settings", expanded=False):
                timer_options = {
                    "Off": 0,
                    "60 seconds": 60,
                    "90 seconds": 90,
                    "2 minutes": 120,
                    "3 minutes": 180,
                    "Custom": None,
                }
                timer_choice = st.selectbox(
                    "Rest duration",
                    list(timer_options.keys()),
                    index=2,
                    key="rest_timer_choice",
                    help="The timer starts automatically after a set is saved.",
                )
                if timer_choice == "Custom":
                    rest_seconds = int(
                        st.number_input(
                            "Custom rest time (seconds)",
                            min_value=15,
                            max_value=900,
                            value=int(st.session_state.get("rest_timer_custom_seconds", 90)),
                            step=15,
                            key="rest_timer_custom_seconds",
                        )
                    )
                else:
                    rest_seconds = int(timer_options[timer_choice])
                st.caption("The timer is a visual aid. Phone/browser background behavior can vary.")

            existing_sets = get_sets(current_instance["id"], user_id)
            logical_numbers = sorted({int(x["set_num"]) for x in existing_sets})

            if existing_sets:
                st.markdown("**Sets recorded**")
                for n in logical_numbers:
                    group = [x for x in existing_sets if int(x["set_num"]) == n]
                    first = group[0]
                    load = float(first.get("weight_original") or 0)
                    unit_saved = first.get("original_unit") or "kg"
                    count = first.get("implement_count")

                    if equipment == "Dumbbells" and count:
                        load_text = f"{int(count)} × {load:g} {unit_saved}"
                    else:
                        load_text = f"{load:g} {unit_saved}"

                    if movement_type == "Unilateral":
                        left = next((x for x in group if x.get("side") == "Left"), None)
                        right = next((x for x in group if x.get("side") == "Right"), None)
                        left_text = f"L {int(left['reps'])}" if left else "L —"
                        right_text = f"R {int(right['reps'])}" if right else "R —"
                        st.write(f"Set {n}: **{load_text}** · {left_text} · {right_text}")
                    else:
                        st.write(f"Set {n}: **{load_text} × {int(first['reps'])}**")

                    edit_col, delete_col = st.columns(2)
                    with edit_col:
                        if st.button(
                            f"✏️ Edit set {n}",
                            key=f"edit_set_{current_instance['id']}_{n}",
                            use_container_width=True,
                            help="Correct the weight, repetitions, or RIR if you tapped the wrong value.",
                        ):
                            st.session_state["edit_set_number"] = n
                            st.rerun()
                    with delete_col:
                        if st.button(
                            f"🗑 Delete set {n}",
                            key=f"delete_set_{current_instance['id']}_{n}",
                            use_container_width=True,
                        ):
                            try:
                                delete_logical_set(current_instance["id"], n, user_id)
                                if st.session_state.get("edit_set_number") == n:
                                    st.session_state.pop("edit_set_number", None)
                                st.rerun()
                            except Exception as exc:
                                st.error("The set could not be deleted.")
                                st.caption(str(exc))

                    if st.session_state.get("edit_set_number") == n:
                        with st.expander(f"Edit set {n}", expanded=True):
                            edit_unit = st.radio(
                                "Unit",
                                ["kg", "lb"],
                                index=0 if unit_saved == "kg" else 1,
                                horizontal=True,
                                key=f"edit_unit_{n}",
                            )
                            edit_weight = st.number_input(
                                "Weight per dumbbell" if equipment == "Dumbbells" else (
                                    "Total barbell weight" if equipment == "Barbell" else "Load shown"
                                ),
                                min_value=0.0,
                                value=float(load),
                                step=0.5,
                                key=f"edit_weight_{n}",
                                help="Enter the load exactly as you used or saw it on the equipment.",
                            )
                            edit_total = (
                                float(edit_weight) * int(implement_count)
                                if equipment == "Dumbbells"
                                else float(edit_weight)
                            )

                            if movement_type == "Bilateral":
                                edit_reps = st.number_input(
                                    "Repetitions (reps)",
                                    min_value=1,
                                    value=int(first["reps"]),
                                    step=1,
                                    key=f"edit_reps_{n}",
                                    help="Reps means repetitions: how many complete repetitions you performed.",
                                )
                                old_rir = first.get("rir")
                                rir_options = ["Not recorded", 0, 1, 2, 3, 4]
                                old_rir_value = "Not recorded" if old_rir is None else int(float(old_rir))
                                edit_rir = st.selectbox(
                                    "RIR (Reps In Reserve)",
                                    rir_options,
                                    index=rir_options.index(old_rir_value),
                                    key=f"edit_rir_{n}",
                                    help=(
                                        "RIR means Reps In Reserve: how many more good repetitions you think you "
                                        "could have completed before failure. RIR 0 = no more reps possible."
                                    ),
                                )
                            else:
                                left = next((x for x in group if x.get("side") == "Left"), None)
                                right = next((x for x in group if x.get("side") == "Right"), None)
                                ec1, ec2 = st.columns(2)
                                with ec1:
                                    edit_left_reps = st.number_input(
                                        "Left reps",
                                        min_value=1,
                                        value=int(left["reps"]) if left else 1,
                                        step=1,
                                        key=f"edit_left_reps_{n}",
                                    )
                                    left_old_rir = left.get("rir") if left else None
                                    left_old = "Not recorded" if left_old_rir is None else int(float(left_old_rir))
                                    edit_left_rir = st.selectbox(
                                        "Left RIR (Reps In Reserve)",
                                        ["Not recorded", 0, 1, 2, 3, 4],
                                        index=["Not recorded", 0, 1, 2, 3, 4].index(left_old),
                                        key=f"edit_left_rir_{n}",
                                        help="RIR = Reps In Reserve. RIR 0 means you could not complete another good rep.",
                                    )
                                with ec2:
                                    edit_right_reps = st.number_input(
                                        "Right reps",
                                        min_value=1,
                                        value=int(right["reps"]) if right else 1,
                                        step=1,
                                        key=f"edit_right_reps_{n}",
                                    )
                                    right_old_rir = right.get("rir") if right else None
                                    right_old = "Not recorded" if right_old_rir is None else int(float(right_old_rir))
                                    edit_right_rir = st.selectbox(
                                        "Right RIR (Reps In Reserve)",
                                        ["Not recorded", 0, 1, 2, 3, 4],
                                        index=["Not recorded", 0, 1, 2, 3, 4].index(right_old),
                                        key=f"edit_right_rir_{n}",
                                        help="RIR = Reps In Reserve. RIR 0 means you could not complete another good rep.",
                                    )

                            save_edit_col, cancel_edit_col = st.columns(2)
                            with save_edit_col:
                                if st.button(
                                    "Save corrected set",
                                    key=f"save_corrected_set_{n}",
                                    use_container_width=True,
                                ):
                                    if edit_weight <= 0:
                                        st.warning("Enter a load greater than 0.")
                                    else:
                                        try:
                                            if movement_type == "Bilateral":
                                                update_bilateral_set(
                                                    exercise_instance_id=current_instance["id"],
                                                    set_num=n,
                                                    user_id=user_id,
                                                    weight=edit_weight,
                                                    unit=edit_unit,
                                                    total_load=edit_total,
                                                    reps=edit_reps,
                                                    rir=edit_rir,
                                                    implement_count=implement_count,
                                                )
                                            else:
                                                update_unilateral_set_pair(
                                                    exercise_instance_id=current_instance["id"],
                                                    set_num=n,
                                                    user_id=user_id,
                                                    weight=edit_weight,
                                                    unit=edit_unit,
                                                    total_load=edit_total,
                                                    reps_left=edit_left_reps,
                                                    reps_right=edit_right_reps,
                                                    rir_left=edit_left_rir,
                                                    rir_right=edit_right_rir,
                                                    implement_count=implement_count,
                                                )
                                            st.session_state.pop("edit_set_number", None)
                                            st.rerun()
                                        except Exception as exc:
                                            st.error("The corrected set could not be saved.")
                                            st.caption(str(exc))
                            with cancel_edit_col:
                                if st.button(
                                    "Cancel edit",
                                    key=f"cancel_corrected_set_{n}",
                                    use_container_width=True,
                                ):
                                    st.session_state.pop("edit_set_number", None)
                                    st.rerun()

            next_set_num = max(logical_numbers, default=0) + 1
            st.markdown(f"### Set {next_set_num}")

            unit = st.radio(
                "Unit",
                ["kg", "lb"],
                horizontal=True,
                key="set_unit",
                help="kg = kilograms. lb = pounds.",
            )

            if equipment == "Dumbbells":
                st.caption(f"Using {implement_count} dumbbell{'s' if implement_count == 2 else ''}")
                weight = st.number_input(
                    f"Weight per dumbbell ({unit})",
                    min_value=0.0,
                    step=0.5,
                    key="set_weight",
                    help="Enter the weight of ONE dumbbell. Daughter Lift also stores the total external load.",
                )
                total_load = float(weight) * int(implement_count)
                st.caption(f"Total external load: {total_load:g} {unit}")
            elif equipment == "Barbell":
                weight = st.number_input(
                    f"Total barbell weight ({unit})",
                    min_value=0.0,
                    step=0.5,
                    key="set_weight",
                    help="Enter the total weight of the barbell, including the bar and plates.",
                )
                total_load = float(weight)
            else:
                weight = st.number_input(
                    f"Load shown ({unit})",
                    min_value=0.0,
                    step=0.5,
                    key="set_weight",
                    help=(
                        "Enter the load shown on this machine or cable. Progress is compared using the same "
                        "exercise and setup because machines can differ."
                    ),
                )
                total_load = float(weight)

            # Keep the live rest timer beside the active set inputs so the user
            # does not need to scroll back to the top during a workout.
            if st.session_state.get("rest_timer_end"):
                render_rest_timer_fragment()
            elif st.session_state.get("rest_timer_finished"):
                st.success("Rest complete. Ready for the next set.")
                if st.button(
                    "Dismiss timer",
                    key="dismiss_rest_timer_near_active_set",
                    use_container_width=True,
                ):
                    clear_rest_timer()
                    st.rerun()

            if movement_type == "Bilateral":
                reps = st.number_input(
                    "Repetitions (reps)",
                    min_value=1,
                    step=1,
                    key="set_reps",
                    help="Reps means repetitions: the number of complete repetitions performed in this set.",
                )
                rir = st.selectbox(
                    "RIR (Reps In Reserve)",
                    ["Not recorded", 0, 1, 2, 3, 4],
                    key="set_rir",
                    help=(
                        "RIR means Reps In Reserve: how many more good repetitions you think you could have "
                        "completed before failure. RIR 0 = no more reps possible; RIR 1 = about 1 rep left."
                    ),
                )
                if st.button("➕ Add set", use_container_width=True):
                    if weight <= 0:
                        st.warning("Enter a load greater than 0.")
                    else:
                        try:
                            add_bilateral_set(
                                user_id=user_id,
                                workout_id=workout_id,
                                exercise_instance_id=current_instance["id"],
                                set_num=next_set_num,
                                weight=weight,
                                unit=unit,
                                total_load=total_load,
                                reps=reps,
                                rir=rir,
                                implement_count=implement_count,
                            )
                            if rest_seconds > 0:
                                start_rest_timer(rest_seconds)
                            else:
                                clear_rest_timer()
                            st.rerun()
                        except Exception as exc:
                            st.error("⚠️ The set was NOT saved.")
                            st.caption(str(exc))
            else:
                left_col, right_col = st.columns(2)
                with left_col:
                    st.markdown("**Left**")
                    reps_left = st.number_input(
                        "Left repetitions (reps)",
                        min_value=1,
                        step=1,
                        key="left_reps",
                        help="Number of complete repetitions performed on the left side.",
                    )
                    rir_left = st.selectbox(
                        "Left RIR (Reps In Reserve)",
                        ["Not recorded", 0, 1, 2, 3, 4],
                        key="left_rir",
                        help="RIR = Reps In Reserve. RIR 0 means no more good reps were possible.",
                    )
                with right_col:
                    st.markdown("**Right**")
                    reps_right = st.number_input(
                        "Right repetitions (reps)",
                        min_value=1,
                        step=1,
                        key="right_reps",
                        help="Number of complete repetitions performed on the right side.",
                    )
                    rir_right = st.selectbox(
                        "Right RIR (Reps In Reserve)",
                        ["Not recorded", 0, 1, 2, 3, 4],
                        key="right_rir",
                        help="RIR = Reps In Reserve. RIR 0 means no more good reps were possible.",
                    )

                if st.button("➕ Add set", use_container_width=True):
                    if weight <= 0:
                        st.warning("Enter a load greater than 0.")
                    else:
                        try:
                            add_unilateral_set_pair(
                                user_id=user_id,
                                workout_id=workout_id,
                                exercise_instance_id=current_instance["id"],
                                set_num=next_set_num,
                                weight=weight,
                                unit=unit,
                                total_load=total_load,
                                reps_left=reps_left,
                                reps_right=reps_right,
                                rir_left=rir_left,
                                rir_right=rir_right,
                                implement_count=implement_count,
                            )
                            if rest_seconds > 0:
                                start_rest_timer(rest_seconds)
                            else:
                                clear_rest_timer()
                            st.rerun()
                        except Exception as exc:
                            st.error("⚠️ The set was NOT saved.")
                            st.caption(str(exc))

            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Next exercise ➜", use_container_width=True):
                    clear_rest_timer()
                    clear_current_exercise()
                    st.rerun()
            with col2:
                if st.button("🏁 Finish workout", use_container_width=True, type="primary"):
                    try:
                        clear_rest_timer()
                        finish_workout(workout_id, user_id)
                        st.rerun()
                    except Exception as exc:
                        st.error("Workout could not be finished.")
                        st.caption(str(exc))

        if current_instance is None and exercise_instances:
            st.divider()
            if st.button("🏁 Finish workout", use_container_width=True):
                try:
                    clear_rest_timer()
                    finish_workout(workout_id, user_id)
                    st.rerun()
                except Exception as exc:
                    st.error("Workout could not be finished.")
                    st.caption(str(exc))


# ============================================================
# PROGRESS - CORE OF DAUGHTER LIFT
# ============================================================

elif page == PAGE_PROGRESS:
    st.header("📈 Strength progress")
    st.caption("Track how much weight you lift and how many repetitions (reps) you can do at that load.")

    with st.expander("ℹ️ What do the terms mean?"):
        st.markdown(
            "**Reps = Repetitions:** how many complete repetitions you perform.  "
            "\n\n**RIR = Reps In Reserve:** how many more good repetitions you think you could do before failure. "
            "RIR 0 means no more good reps were possible.  "
            "\n\n**1RM = One-Repetition Maximum:** the maximum load you can actually lift once.  "
            "\n\n**e1RM = Estimated One-Repetition Maximum:** a mathematical estimate of 1RM from the load, reps, "
            "and RIR when available. It is an estimate, not a measured maximum."
        )

    try:
        raw_strength = get_strength_data(user_id)
        strength = collapse_unilateral_sets(raw_strength)
    except Exception as exc:
        st.error("Could not load strength data.")
        st.caption(str(exc))
        strength = pd.DataFrame()

    if strength.empty:
        st.info("Complete a workout with at least one weighted set to see progress here.")
    else:
        exercise_options = sorted(strength["exercise_name"].dropna().unique().tolist())
        selected_exercise_name = st.selectbox("Exercise", exercise_options)

        exercise_df = strength[strength["exercise_name"] == selected_exercise_name].copy()

        variant_labels = {}
        for variant_key, group in exercise_df.groupby("variant_key"):
            row = group.iloc[0]
            label = str(row["equipment"])
            if str(row["equipment"]) == "Dumbbells":
                counts = group["implement_count"].dropna().unique().tolist()
                if counts:
                    label += f" · {int(counts[0])} dumbbell{'s' if int(counts[0]) == 2 else ''}"
            label += f" · {row['movement_type']}"
            variant_labels[variant_key] = label

        selected_variant = st.selectbox(
            "Setup",
            list(variant_labels.keys()),
            format_func=lambda x: variant_labels[x],
        )

        df = exercise_df[exercise_df["variant_key"] == selected_variant].copy()

        # Session summary: choose highest load. If several sets use that load,
        # use the highest reps achieved at that exact load.
        session_rows = []
        for (workout_id, workout_date), group in df.groupby(["workout_id", "workout_date"]):
            max_load = group["weight_kg"].max()
            at_top_load = group[group["weight_kg"].sub(max_load).abs() < 1e-9]
            best_reps_at_top = int(at_top_load["reps"].max())

            valid_e1rm = group[group["e1rm"].notna()]
            best_e1rm = float(valid_e1rm["e1rm"].max()) if not valid_e1rm.empty else None

            all_sets = " · ".join(
                f"{r.weight_kg:g}×{int(r.reps)}"
                for r in group.sort_values("set_num").itertuples()
            )

            session_rows.append(
                {
                    "workout_id": workout_id,
                    "date": pd.Timestamp(workout_date),
                    "best_load_kg": float(max_load),
                    "reps_at_best_load": best_reps_at_top,
                    "estimated_strength_kg": best_e1rm,
                    "sets": all_sets,
                }
            )

        sessions = pd.DataFrame(session_rows).sort_values("date")

        first = sessions.iloc[0]
        latest = sessions.iloc[-1]

        c1, c2, c3 = st.columns(3)
        c1.metric("Latest top load", f"{latest['best_load_kg']:.1f} kg")
        c2.metric("Reps at that load", f"{int(latest['reps_at_best_load'])}")
        load_change = latest["best_load_kg"] - first["best_load_kg"]
        c3.metric("Load change", f"{load_change:+.1f} kg")

        st.subheader("Load progression")
        st.caption("Highest load used in each completed session for this exact exercise/setup.")
        load_chart = sessions[["date", "best_load_kg"]].set_index("date")
        st.line_chart(load_chart, y="best_load_kg")

        # Repetition progression must be compared at the SAME load. Using all
        # logical sets (not only the top set of each session) avoids hiding a
        # rep PR that happened at a lower working load.
        st.subheader("Repetition progression at the same load")
        available_loads = sorted(df["weight_kg"].dropna().unique().tolist(), reverse=True)
        selected_load = st.selectbox(
            "Load to compare",
            available_loads,
            format_func=lambda x: f"{x:g} kg",
        )

        same_load = df[df["weight_kg"].sub(float(selected_load)).abs() < 1e-9].copy()
        reps_by_date = (
            same_load.groupby("workout_date", as_index=False)["reps"]
            .max()
            .sort_values("workout_date")
        )

        if not reps_by_date.empty:
            first_reps = int(reps_by_date.iloc[0]["reps"])
            latest_reps = int(reps_by_date.iloc[-1]["reps"])
            rep_delta = latest_reps - first_reps
            st.metric(
                f"Best reps at {selected_load:g} kg",
                f"{latest_reps} reps",
                delta=f"{rep_delta:+d} reps vs first time",
            )
            st.line_chart(
                reps_by_date.set_index("workout_date")[["reps"]],
                y="reps",
            )

        if sessions["estimated_strength_kg"].notna().sum() >= 2:
            st.subheader("Estimated 1RM (e1RM) trend")
            st.caption("e1RM = Estimated One-Repetition Maximum. Secondary estimate only; uses sets of 10 reps or fewer and RIR when available.")
            estimate_chart = (
                sessions.dropna(subset=["estimated_strength_kg"])
                [["date", "estimated_strength_kg"]]
                .set_index("date")
            )
            st.line_chart(estimate_chart, y="estimated_strength_kg")

        st.subheader("Sessions")
        session_display = sessions.copy().sort_values("date", ascending=False)
        session_display["Date"] = session_display["date"].dt.strftime("%d %b %Y")
        session_display["Top load"] = session_display["best_load_kg"].map(lambda x: f"{x:g} kg")
        session_display["Reps at top load"] = session_display["reps_at_best_load"].astype(int)
        session_display["All sets"] = session_display["sets"]
        st.dataframe(
            session_display[["Date", "Top load", "Reps at top load", "All sets"]],
            hide_index=True,
            use_container_width=True,
        )

    st.divider()
    with st.expander("⚖️ Body-weight trend", expanded=False):
        try:
            weights = get_weight_history(user_id, limit=100)
        except Exception as exc:
            weights = []
            st.warning("Could not load body-weight data.")
            st.caption(str(exc))

        if not weights:
            st.write("No body-weight data yet.")
        else:
            weight_df = pd.DataFrame(weights)
            weight_df["measured_at"] = pd.to_datetime(weight_df["measured_at"], errors="coerce")
            weight_df["weight_kg"] = pd.to_numeric(weight_df["weight_kg"], errors="coerce")
            weight_df = weight_df.dropna(subset=["measured_at", "weight_kg"]).sort_values("measured_at")
            st.line_chart(weight_df.set_index("measured_at")[["weight_kg"]])


# ============================================================
# HISTORY
# ============================================================

elif page == PAGE_HISTORY:
    st.header("📚 History")
    try:
        workouts = (
            supabase.table("workouts")
            .select("id, workout_date, workout_type, status, started_at, completed_at")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .order("workout_date", desc=True)
            .limit(50)
            .execute()
        ).data or []
    except Exception as exc:
        workouts = []
        st.error("Could not load workout history.")
        st.caption(str(exc))

    if not workouts:
        st.info("No completed workouts yet.")
    else:
        for workout in workouts:
            with st.expander(f"{workout['workout_date']} · {workout['workout_type']}"):
                instances = get_exercise_instances(workout["id"], user_id)
                for ex in instances:
                    st.markdown(f"**{ex['exercise_name']} · {ex['equipment']}**")
                    sets_done = get_sets(ex["id"], user_id)
                    for n in sorted({int(x["set_num"]) for x in sets_done}):
                        group = [x for x in sets_done if int(x["set_num"]) == n]
                        first = group[0]
                        load = float(first.get("weight_original") or 0)
                        unit = first.get("original_unit") or "kg"
                        count = first.get("implement_count")
                        load_text = (
                            f"{int(count)} × {load:g} {unit}"
                            if ex["equipment"] == "Dumbbells" and count
                            else f"{load:g} {unit}"
                        )
                        if ex["movement_type"] == "Unilateral":
                            left = next((x for x in group if x.get("side") == "Left"), None)
                            right = next((x for x in group if x.get("side") == "Right"), None)
                            l = int(left["reps"]) if left else "—"
                            r = int(right["reps"]) if right else "—"
                            st.write(f"Set {n}: {load_text} · L {l} · R {r}")
                        else:
                            st.write(f"Set {n}: {load_text} × {int(first['reps'])}")


# ============================================================
# PROFILE
# ============================================================

elif page == PAGE_PROFILE:
    st.header("👤 Profile")
    with st.form("profile_form"):
        profile_name = st.text_input("Name or alias", value=display_name)
        profile_age = st.number_input(
            "Age", min_value=10, max_value=100,
            value=int(age) if age is not None else None, step=1
        )
        profile_height = st.number_input(
            "Height (cm)", min_value=100.0, max_value=230.0,
            value=float(height_cm) if height_cm is not None else None, step=0.5
        )
        save_profile_button = st.form_submit_button("Save profile", use_container_width=True)

    if save_profile_button:
        if not profile_name.strip():
            st.warning("Enter a name or alias.")
        elif profile_age is None or profile_height is None:
            st.warning("Enter age and height.")
        else:
            try:
                update_profile(user_id, profile_name, profile_age, profile_height)
                st.success("Profile saved ✅")
                st.rerun()
            except Exception as exc:
                st.error("The profile could not be saved.")
                st.caption(str(exc))


# ============================================================
# HOW TO USE
# ============================================================

elif page == PAGE_HELP:
    st.header("How to use Daughter Lift")
    render_how_to_use()


# ============================================================
# ADMIN
# ============================================================

elif page == PAGE_ADMIN:
    if role != "admin":
        st.error("You do not have access to the admin area.")
    else:
        st.header("🛡️ Admin")
        st.info("Admin tools will be added after the normal-user workflow is stable.")