from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PathScripts.NearSitePlayerSeries import generate_player_nearsite_series
from PathScripts.SeriesRoster import collect_team_players


def _load_team_players(team_name: str) -> Dict[str, str]:
    players = collect_team_players(team_name)
    if not players:
        raise FileNotFoundError(
            f"No end_state roster found for team '{team_name}'."
        )
    return players


def generate_team_nearsite_series(
    team_name: str,
    time_seconds: float,
    side: str = "all",
) -> None:
    players = _load_team_players(team_name)
    for player_name in players.keys():
        generate_player_nearsite_series(
            team_name=team_name,
            player_name=player_name,
            time_seconds=time_seconds,
            side=side,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Compute nearest callouts for all team members across all maps."
    )
    parser.add_argument("team", help="Team name (matches Data/<Team> folder).")
    parser.add_argument("time", type=float, help="Time in seconds from round start.")
    parser.add_argument(
        "--side",
        choices=["all", "attack", "defense"],
        default="all",
        help="Which side's rounds to analyze (default: all).",
    )
    args = parser.parse_args()

    generate_team_nearsite_series(args.team, args.time, side=args.side)
