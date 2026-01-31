from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PathScripts.MainPlayerPathDisplay import render_player_paths, _infer_map_name
from PathScripts.DisplayPath import render_team_paths_overlay, render_team_clusters_overlay
from Map import Map


def _player_paths(team_name: str) -> Iterable[Path]:
    # Yield all <Player>_<map>_paths.json files under Data/<Team>/Players.
    safe_team = team_name.replace(" ", "_")
    base_dir = Path("Data") / safe_team / "Players"
    if not base_dir.exists():
        return []
    return base_dir.glob("*/**/*_paths.json")


def render_team_paths(team_name: str, side: str = "all") -> None:
    # Render overlays for every player's paths JSON in the team folder.
    team_paths_by_map: dict[str, list[Path]] = {}
    for paths_json in _player_paths(team_name):
        player_name = paths_json.parent.name
        map_name = _infer_map_name(paths_json)
        team_paths_by_map.setdefault(map_name, []).append(paths_json)

        if side == "both":
            render_player_paths(team_name, player_name, paths_json, side="attack")
            render_player_paths(team_name, player_name, paths_json, side="defense")
        else:
            render_player_paths(team_name, player_name, paths_json, side=side)

    safe_team = team_name.replace(" ", "_")
    team_output_dir = Path("Data") / safe_team / "TeamData"
    team_output_dir.mkdir(parents=True, exist_ok=True)

    for map_name, paths_list in team_paths_by_map.items():
        map_json = Path("MapData") / map_name / f"{map_name}.json"
        if not map_json.exists():
            continue
        map_info = Map.from_map_json(str(map_json))

        sides = ["attack", "defense"] if side == "both" else [side]
        for side_name in sides:
            overlay_path = team_output_dir / f"{safe_team}_{map_name}_{side_name}_paths_overlay.png"
            cluster_path = team_output_dir / f"{safe_team}_{map_name}_{side_name}_cluster.png"
            render_team_paths_overlay(
                paths_json_paths=[str(p) for p in paths_list],
                map_png_path=map_info.img_path,
                output_png_path=str(overlay_path),
                map_info=map_info,
                side=side_name,
            )
            render_team_clusters_overlay(
                paths_json_paths=[str(p) for p in paths_list],
                map_png_path=map_info.img_path,
                output_png_path=str(cluster_path),
                map_info=map_info,
                side=side_name,
            )


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
