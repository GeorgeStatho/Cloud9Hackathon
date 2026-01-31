from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PathScripts.MainPlayerPathDisplay import render_player_paths


def _player_paths(team_name: str) -> Iterable[Path]:
    # Yield all <Player>_<map>_paths.json files under Data/<Team>/Players.
    safe_team = team_name.replace(" ", "_")
    base_dir = Path("Data") / safe_team / "Players"
    if not base_dir.exists():
        return []
    return base_dir.glob("*/**/*_paths.json")


def render_team_paths(team_name: str, side: str = "all") -> None:
    # Render overlays for every player's paths JSON in the team folder.
    for paths_json in _player_paths(team_name):
        player_name = paths_json.parent.name
        if side == "both":
            render_player_paths(team_name, player_name, paths_json, side="attack")
            render_player_paths(team_name, player_name, paths_json, side="defense")
        else:
            render_player_paths(team_name, player_name, paths_json, side=side)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Render all player path JSONs for a team into overlay PNGs."
    )
    parser.add_argument("team", help="Team name (matches Data/<Team> folder).")
    parser.add_argument(
        "--side",
        choices=["all", "attack", "defense", "both"],
        default="all",
        help="Which side to render (default: all).",
    )
    args = parser.parse_args()
    render_team_paths(args.team, side=args.side)
