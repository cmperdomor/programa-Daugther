# Daughter Lift

Daughter Lift is a web application designed to record strength-training workouts and track progress over time.

The main objective is to evaluate whether a user is improving in a specific exercise by comparing the weight lifted and the number of repetitions performed under the same exercise and equipment setup.

## Purpose

The application helps users answer questions such as:

**Am I lifting more weight than before?**

**Can I perform more repetitions with the same weight?**

**What was my previous performance in this exercise?**

**How has my strength changed over time?**

Daughter Lift focuses on actual training performance instead of combining unrelated exercises into a single strength score.

For example:

60 kg x 8 repetitions

60 kg x 10 repetitions

65 kg x 8 repetitions

Progress can therefore occur by increasing the weight, increasing the repetitions at the same weight, or both.

## Main Features

### Workout Tracking

Users can create and record different types of workouts, including:

Upper Body

Lower Body

Core

Each workout can contain several exercises and multiple sets.

### Set Recording

For each set, users can record:

Weight

Kilograms or pounds

Repetitions

RIR

RIR means Reps In Reserve and represents approximately how many additional repetitions the user believes they could have completed with good technique.

RIR 0 means no additional good repetitions were possible.

RIR 1 means approximately one repetition remained.

RIR 2 means approximately two repetitions remained.

Recording RIR is optional.

### Bilateral and Unilateral Exercises

Daughter Lift supports exercises performed with both sides of the body together and exercises performed one side at a time.

For unilateral exercises, the application can record the left and right sides separately.

### Equipment Tracking

The application distinguishes between different equipment because loads from different machines or setups should not automatically be considered equivalent.

Examples include:

Barbell

Dumbbells

Cable

Smith Machine

Selectorized Machine

Plate Loaded Machine

Other equipment

Dumbbell exercises can also distinguish between configurations such as one 28 kg dumbbell and two 14 kg dumbbells.

### Custom Exercises

Users can create custom exercises when an exercise is not already included in the application.

This allows Daughter Lift to adapt to different gyms, training programs and equipment.

### Progress Tracking

The Progress section compares performance for the same exercise and setup across different training sessions.

The main indicators are:

Weight lifted

Repetitions completed

Best load

Performance at the same load

Training history

Personal bests

The application can also calculate an Estimated One Repetition Maximum, or e1RM, as a secondary indicator of strength.

The estimated value is not considered equivalent to an actual tested one repetition maximum.

### Workout History

Completed workouts are stored so users can review previous training sessions, exercises, loads, repetitions and sets.

### Body Weight

Users can also record their body weight and observe its evolution over time.

Body weight is considered a secondary metric because the primary purpose of Daughter Lift is to analyze strength-training performance.

## Technologies Used

### Python

Python is the main programming language used to develop the application and implement its workout tracking and data processing logic.

### Streamlit

Streamlit is used to build the web interface.

It manages the forms, buttons, exercise selection, workout registration, navigation, charts and progress visualization.

### Supabase

Supabase provides the backend infrastructure for the application.

It is used for user authentication, database management and storage of workout information.

### PostgreSQL

Training data is stored in a PostgreSQL database through Supabase.

The database includes information related to users, workouts, exercises, sets, custom exercises and body measurements.

### Pandas

Pandas is used for data processing and analysis, including workout history, progress calculations and preparation of data for visualization.

### Git

Git is used for version control and to maintain a history of changes made to the project.

### GitHub

GitHub is used to store and manage the source code of the application.

### Streamlit Community Cloud

The application is deployed through Streamlit Community Cloud, allowing users to access Daughter Lift through a web browser without installing Python or development software.

## Application Structure

The application follows this general structure:

User

Streamlit web application

Python application logic

Supabase authentication and PostgreSQL database

The development and deployment workflow is:

Local development

Git

GitHub

Streamlit Community Cloud

## Security

Sensitive Supabase credentials are not stored directly in the public source code.

Local credentials are stored in the `.streamlit/secrets.toml` file.

This file is excluded from GitHub through `.gitignore`.

Deployment credentials are stored separately in Streamlit Community Cloud.

Supabase Row Level Security is used to control access to user data.

## Mobile Access

Daughter Lift can be accessed from desktop computers, tablets and mobile phones.

Users only need the application URL and a web browser.

No software installation is required.

## Project Status

Daughter Lift is currently in beta.

The application is functional and is being tested with real users.

Current development priorities include expanding the exercise catalog, improving the mobile experience, improving long-term session persistence and refining progress visualization.

## Design Approach

The main principle behind Daughter Lift is that strength progression should be evaluated under comparable conditions.

The application therefore focuses on:

Same exercise

Same equipment or setup

Performance over time

The primary indicators remain the actual weight lifted and the repetitions completed.

Calculated metrics are treated as supplementary information rather than replacements for actual training performance.

## Author

Developed by Claudia Perdomo.

Daughter Lift is a personal software and data project combining strength training, Python development, database design, data analysis and web application development.
