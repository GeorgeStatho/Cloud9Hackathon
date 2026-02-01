from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path for imports.
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PathScripts.MainTeamPathGen import generateTeamPaths
from PathScripts.MainTeamPathDisplay import render_team_paths
from PathScripts.NearSiteTeamSeries import generate_team_nearsite_series
from PathScripts.PlayerStatisticsTeamSeries import generate_team_player_statistics

from GraphQlScripts.GraphQlmain import generatePlayersFromTeamName,generateTeamSeriesFiles

def run_pipeline(team_name: str, api_key: str, seconds_limit: float, time_threshold: float) -> None:
    # Store the API key for any downstream scripts that read from env.
    os.environ["GRID_API_KEY"] = api_key

    print(f"[pipeline] Generating Player Files for team: {team_name}")
    generatePlayersFromTeamName(team_name)

    print(f"[pipeline] Generating Series Files for team: {team_name}")
    generateTeamSeriesFiles(team_name)

    print(f"[pipeline] Generating path JSONs for team: {team_name}")
    generateTeamPaths(team_name, seconds_limit=seconds_limit)

    print(f"[pipeline] Rendering team overlays for team: {team_name}")
    render_team_paths(team_name, side="both")

    print(f"[pipeline] Generating NearSite summaries for team: {team_name}")
    generate_team_nearsite_series(team_name, time_threshold, side="all")

    print(f"[pipeline] Generating player statistics for team: {team_name}")
    generate_team_player_statistics(team_name)

    print("[pipeline] Done.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the full path + display + NearSite pipeline for a team."
    )
    parser.add_argument("team", help="Team name (matches Data/<Team> folder).")
    parser.add_argument("api_key", help="GRID API key.")
    parser.add_argument(
        "--seconds",
        type=float,
        default=120.0,
        help="Seconds from round start to include in path data (default: 120).",
    )
    parser.add_argument(
        "--time-threshold",
        type=float,
        default=30.0,
        help="Time in seconds to evaluate NearSite callouts (default: 30).",
    )
    args = parser.parse_args()

    run_pipeline(args.team, args.api_key, args.seconds, args.time_threshold)
    
