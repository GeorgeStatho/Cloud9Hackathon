from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from AttackDefenseParser import parse_attack_defense_rounds
from PathScripts.PathGenerator import build_team_round_paths_one_pass


def _load_team_players(team_name: str) -> Dict[str, str]:
    # Read Data/<Team>/<Team>_players.json and return nickname->id mapping.
    safe_team = team_name.replace(" ", "_")
    players_path = Path("Data") / safe_team / f"{safe_team}_players.json"
    if not players_path.exists():
        raise FileNotFoundError(f"Team players file not found: {players_path}")
    with open(players_path, "r", encoding="utf-8") as file_handle:
        data = json.load(file_handle)
    return {str(name): str(pid) for name, pid in data.items()}


def _series_files(team_name: str) -> Iterable[Tuple[str, Path, Path]]:
    # Yield (series_id, end_state_path, jsonl_path) for each series in Data/<Team>/series.
    safe_team = team_name.replace(" ", "_")
    series_dir = Path("Data") / safe_team / "series"
    if not series_dir.exists():
        raise FileNotFoundError(f"Series folder not found: {series_dir}")

    end_state_pattern = re.compile(r"end_state_(\d+)_grid\.json$", re.IGNORECASE)
    for end_state_path in sorted(series_dir.glob("end_state_*_grid.json")):
        match = end_state_pattern.search(end_state_path.name)
        if not match:
            continue
        series_id = match.group(1)
        jsonl_path = series_dir / f"events_{series_id}_grid.jsonl"
        if not jsonl_path.exists():
            jsonl_path = series_dir / f"events_{series_id}_grid.jsonl.zip"
        if not jsonl_path.exists():
            continue
        yield series_id, end_state_path, jsonl_path


def _maps_from_end_state(end_state_path: Path) -> List[str]:
    # Extract unique map names from the end_state JSON.
    with open(end_state_path, "r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)
    games = payload.get("seriesState", {}).get("games", []) or []
    map_names: List[str] = []
    for game in games:
        map_name = game.get("map", {}).get("name")
        if map_name and map_name not in map_names:
            map_names.append(map_name)
    return map_names


def _maps_from_jsonl(jsonl_path: Path) -> List[str]:
    # Read the JSONL (or zip) and return the map names actually present in the feed.
    parsed = parse_attack_defense_rounds(str(jsonl_path))
    maps: List[str] = []
    for game in parsed.get("games", {}).values():
        map_name = game.get("map")
        if map_name and map_name not in maps:
            maps.append(map_name)
    return maps


def generateTeamPaths(
    team_name: str,
    seconds_limit: float = 5.0,
) -> None:
    players = _load_team_players(team_name)

    # Iterate each series for this team
    for series_id, end_state_path, jsonl_path in _series_files(team_name):
        # Decide which maps to generate for this series
        map_names = _maps_from_end_state(end_state_path)
        jsonl_maps = _maps_from_jsonl(jsonl_path)
        map_names = [m for m in map_names if m in jsonl_maps]

        print(
            f"[team paths] team={team_name} series={series_id} "
            f"players={len(players)} maps={map_names}"
        )

        # ONE PASS per series (level 3 optimization)
        build_team_round_paths_one_pass(
            jsonl_path=str(jsonl_path),
            player_names_or_ids=list(players.keys()),
            seconds_limit=seconds_limit,
            allowed_maps=map_names,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate player path JSONs for all players in a team across series."
    )
    parser.add_argument("team", help="Team name (matches Data/<Team> folder).")
    parser.add_argument(
        "--seconds",
        type=float,
        default=5.0,
        help="Seconds from round start to include in the path (default: 5).",
    )
    args = parser.parse_args()
    generateTeamPaths(args.team, seconds_limit=args.seconds)
