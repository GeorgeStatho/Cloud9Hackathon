from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Map import Map
from PathScripts.DisplayPath import render_paths_overlay


def _infer_map_name(paths_json_path: Path) -> str:
    # Infer the map name from the filename pattern: <player>_<map>_paths.json
    stem = paths_json_path.stem
    parts = stem.split("_")
    if len(parts) < 3:
        raise ValueError(f"Cannot infer map name from filename: {paths_json_path.name}")
    return parts[-2]


def render_player_paths(
    team_name: str,
    player_name: str,
    paths_json_path: Path,
    side: str = "all",
) -> Optional[Path]:
    # Render a single player's paths JSON into an overlay PNG.
    map_name = _infer_map_name(paths_json_path)
    map_json = Path("MapData") / map_name / f"{map_name}.json"
    if not map_json.exists():
        return None
    map_info = Map.from_map_json(str(map_json))

    output_path = paths_json_path.with_name(
        f"{player_name}_{map_name}_{side}_paths_overlay.png"
    )
    render_paths_overlay(
        paths_json_path=str(paths_json_path),
        map_png_path=map_info.img_path,
        output_png_path=str(output_path),
        map_info=map_info,
        side=side,
    )
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Render a single player's path JSON into an overlay PNG."
    )
    parser.add_argument("team", help="Team name (matches Data/<Team> folder).")
    parser.add_argument("player", help="Player name.")
    parser.add_argument("paths_json", help="Path to the player's paths JSON.")
    parser.add_argument(
        "--side",
        choices=["all", "attack", "defense", "both"],
        default="all",
        help="Which side to render (default: all).",
    )
    args = parser.parse_args()

    paths_path = Path(args.paths_json)
    if args.side == "both":
        render_player_paths(args.team, args.player, paths_path, side="attack")
        render_player_paths(args.team, args.player, paths_path, side="defense")
    else:
        render_player_paths(args.team, args.player, paths_path, side=args.side)
