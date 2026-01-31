from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PathScripts.NearSite import nearest_regions_for_time


def _player_paths(team_name: str, player_name: str) -> Iterable[Path]:
    safe_team = team_name.replace(" ", "_")
    safe_player = player_name.replace(" ", "_")
    base_dir = Path("Data") / safe_team / "Players" / safe_player
    if not base_dir.exists():
        return []
    return base_dir.glob("**/*_paths.json")


def _infer_map_name(paths_json_path: Path) -> str:
    stem = paths_json_path.stem
    parts = stem.split("_")
    if len(parts) < 3:
        raise ValueError(f"Cannot infer map name from filename: {paths_json_path.name}")
    return parts[-2]


def generate_player_nearsite_series(
    team_name: str,
    player_name: str,
    time_seconds: float,
    side: str = "all",
) -> Dict[str, Optional[Path]]:
    outputs: Dict[str, Optional[Path]] = {}
    for paths_json in _player_paths(team_name, player_name):
        map_name = _infer_map_name(paths_json)
        result = nearest_regions_for_time(
            team_name=team_name,
            player_name=player_name,
            map_name=map_name,
            time_seconds=time_seconds,
            side=side,
        )
        output_path = paths_json.with_name(
            f"{paths_json.stem}_{side}_nearsite.json"
        )
        with open(output_path, "w", encoding="utf-8") as file_handle:
            json.dump(result, file_handle, indent=2, ensure_ascii=False)
        outputs[map_name] = output_path
    return outputs


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Compute nearest callouts for a player across all maps in their paths."
    )
    parser.add_argument("team", help="Team name (matches Data/<Team> folder).")
    parser.add_argument("player", help="Player name (matches Players/<Player> folder).")
    parser.add_argument("time", type=float, help="Time in seconds from round start.")
    parser.add_argument(
        "--side",
        choices=["all", "attack", "defense"],
        default="all",
        help="Which side's rounds to analyze (default: all).",
    )
    args = parser.parse_args()

    generate_player_nearsite_series(
        team_name=args.team,
        player_name=args.player,
        time_seconds=args.time,
        side=args.side,
    )
