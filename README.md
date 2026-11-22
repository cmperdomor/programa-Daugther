Git & GitHub

Git is used for version control.

GitHub is used to store and manage the source code and keep a history of application changes.

Streamlit Community Cloud

The application is deployed using Streamlit Community Cloud, allowing users to access Daughter Lift through a web link without installing Python or any development software.

Application Architecture

The application follows a simple web architecture:

User
  ↓
Streamlit web application
  ↓
Python application logic
  ↓
Supabase
  ├── Authentication
  └── PostgreSQL database

Source code is maintained through:

Local development
      ↓
     Git
      ↓
    GitHub
      ↓
Streamlit Community Cloud

Security

Sensitive Supabase credentials are not stored directly in the public source code.

Local credentials are stored in:

.streamlit/secrets.toml

This file is excluded from Git using .gitignore.

Deployment credentials are stored separately using Streamlit Cloud's Secrets configuration.

Mobile Access

Daughter Lift is a web application and can be accessed from:

Desktop computers

Tablets

Android phones

iPhones

No installation is required.

Users can open the application's URL directly in their browser and may add it to their phone's home screen for easier access.

Project Status

Current status: Beta

Daughter Lift is functional and available for real-world testing.

Current development priorities include:

Expanding the exercise catalog

Improving the mobile user experience

Improving long-term login/session persistence

Refining progress visualization

Improving usability based on user feedback

Design

Daughter Lift avoids creating misleading strength scores by combining unrelated exercises.

Progress is evaluated within comparable conditions:

same exercise + same equipment/setup + performance over time

The primary data remain the values actually performed in training:

weight + repetitions

Derived metrics such as estimated strength are considered supplementary information rather than replacements for actual training performance.

 Author

Developed by Claudia Perdomo as a personal data and software project combining:

Strength training

Data tracking

Python development

Database design

Data analysis

Web application development
