Cloud9 Hackathon Project: Automated Scouting Report Generator

This project generates scouting reports from GRID series data, then serves them in a Flask web app.

Quick start
1) Create and activate a Python 3.10+ environment.
2) Install dependencies:
   pip install -r requirements.txt
3) Run the web app:
   python Backend/app.py
4) Open the site at:
   http://127.0.0.1:5000

Web app usage
- Enter your GRID API key and team name.
- Set:
  - seconds limit (path sample duration per round)
  - time threshold (NearSite analysis time)
- Click "Run Pipeline".

Optional: run the pipeline from CLI
python main.py <TEAM_NAME> <GRID_API_KEY> --seconds <PATH_SECONDS> --time-threshold <NEARSITE_SECONDS>

Notes
- Map overlays require MapData to be present.
- Generated files are written under Data/<TeamName>/...


Troubleshooting
- If you get 401/403 errors, verify the API key and that the series is accessible.
- If a run is slow, it is usually scanning large JSONL/zip files.
- If a Timeout error occurs delete the team's series folder and run the pipeline again