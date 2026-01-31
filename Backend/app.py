from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Tuple

from flask import Flask, render_template, request

ROOT_DIR = Path(__file__).resolve().parent.parent
GRAPHQL_DIR = ROOT_DIR / "GraphQlScripts"
PATHS_DIR = ROOT_DIR / "PathScripts"

for path in (str(ROOT_DIR), str(GRAPHQL_DIR), str(PATHS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


app = Flask(__name__)


def _collect_files(team_name: str) -> dict:
    safe_team = team_name.replace(" ", "_")
    team_dir = ROOT_DIR / "Data" / safe_team
    outputs = {
        "team_dir": str(team_dir),
        "team_files": [],
        "team_data_files": [],
        "player_files": [],
        "nearsite_files": [],
    }
    if not team_dir.exists():
        return outputs

    outputs["team_files"] = sorted(
        [str(p.relative_to(ROOT_DIR)) for p in team_dir.glob("**/*") if p.is_file()]
    )

    team_data_dir = team_dir / "TeamData"
    if team_data_dir.exists():
        outputs["team_data_files"] = sorted(
            [str(p.relative_to(ROOT_DIR)) for p in team_data_dir.glob("**/*") if p.is_file()]
        )

    players_dir = team_dir / "Players"
    if players_dir.exists():
        for p in players_dir.glob("**/*"):
            if not p.is_file():
                continue
            rel = str(p.relative_to(ROOT_DIR))
            outputs["player_files"].append(rel)
            if rel.endswith("_nearsite.json"):
                outputs["nearsite_files"].append(rel)

    outputs["player_files"].sort()
    outputs["nearsite_files"].sort()
    return outputs


def _run_pipeline(api_key: str, team_name: str, seconds_limit: float = 120.0, time_threshold: float = 30.0) -> List[str]:
    logs: List[str] = []
    os.environ["GRID_API_KEY"] = api_key

    from GraphQlScripts.GraphQlmain import generatePlayersFromTeamName, generateTeamSeriesFiles
    from GraphQlScripts.CentralData import getTeamId
    from GraphQlScripts.StaticFeed import GetTeamStats
    from PathScripts.MainTeamPathGen import generateTeamPaths
    from PathScripts.MainTeamPathDisplay import render_team_paths
    from PathScripts.NearSiteTeamSeries import generate_team_nearsite_series

    logs.append("Generating team player list...")
    generatePlayersFromTeamName(team_name)

    logs.append("Downloading series files...")
    generateTeamSeriesFiles(team_name)

    logs.append("Generating path JSONs...")
    generateTeamPaths(team_name, seconds_limit=seconds_limit)

    logs.append("Rendering player/team overlays...")
    render_team_paths(team_name, side="both")

    logs.append("Generating NearSite summaries...")
    generate_team_nearsite_series(team_name, time_threshold, side="all")

    logs.append("Fetching team stats...")
    team_id = getTeamId(team_name)
    GetTeamStats(team_id)

    logs.append("Done.")
    return logs


@app.route("/", methods=["GET", "POST"])
def index():
    logs: List[str] = []
    outputs = None
    error = None
    api_key = ""
    team_name = ""

    if request.method == "POST":
        api_key = request.form.get("api_key", "").strip()
        team_name = request.form.get("team_name", "").strip()
        if not api_key or not team_name:
            error = "Please provide both API key and team name."
        else:
            try:
                logs = _run_pipeline(api_key, team_name)
                outputs = _collect_files(team_name)
            except Exception as exc:
                error = str(exc)

    return render_template(
        "index.html",
        logs=logs,
        outputs=outputs,
        error=error,
        api_key=api_key,
        team_name=team_name,
    )


if __name__ == "__main__":
    app.run(debug=True)
