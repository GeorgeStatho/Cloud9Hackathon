from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PathScripts.PlayerStatisticsPlayerSeries import generate_player_statistics_for_player
from PathScripts.PlayerStatisticsParser import compute_team_player_event_stats


def _load_team_players(team_name: str) -> Dict[str, str]:
    safe_team = team_name.replace(" ", "_")
    players_path = Path("Data") / safe_team / f"{safe_team}_players.json"
    if not players_path.exists():
        raise FileNotFoundError(f"Team players file not found: {players_path}")
    with open(players_path, "r", encoding="utf-8") as file_handle:
        data = json.load(file_handle)
    return {str(name): str(pid) for name, pid in data.items()}


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
