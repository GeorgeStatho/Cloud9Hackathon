from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PathScripts.PlayerStatisticsPlayerSeries import generate_player_statistics_for_player
from PathScripts.PlayerStatisticsParser import compute_team_player_event_stats
from PathScripts.SeriesRoster import collect_team_players


def _load_team_players(team_name: str) -> Dict[str, str]:
    players = collect_team_players(team_name)
    if not players:
        raise FileNotFoundError(
            f"No end_state roster found for team '{team_name}'."
        )
    return players


def generate_team_player_statistics(team_name: str) -> None:
    players = _load_team_players(team_name)
    event_stats = compute_team_player_event_stats(team_name)
    for player_name, player_id in players.items():
        generate_player_statistics_for_player(
            team_name, player_name, player_id, event_stats
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build per-map player statistics (agent per game) for all team members."
    )
    parser.add_argument("team", help="Team name (matches Data/<Team> folder).")
    args = parser.parse_args()

    generate_team_player_statistics(args.team)
