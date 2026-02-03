from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from AttackDefenseParser import parse_attack_defense_rounds
from PathScripts.PathGenerator import build_team_round_paths_one_pass

def _cleanup_tmp_files(root: Path) -> None:
    if not root.exists():
        return
    for tmp_path in root.rglob('*.tmp'):
        try:
            tmp_path.unlink()
        except OSError:
            pass
    for lock_path in root.rglob('*.lock'):
        try:
            lock_path.unlink()
        except OSError:
            pass


def _load_end_state(end_state_path: Path) -> Dict[str, Any]:
    # Load the end_state JSON so we can extract the series roster for this team.
    with open(end_state_path, "r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def _players_from_end_state(payload: Dict[str, Any], team_name: str) -> Dict[str, str]:
    # Extract nickname->id mapping for the requested team from seriesState.teams.
    series_state = payload.get("seriesState", {}) or {}
    teams = series_state.get("teams", []) or []
    target = team_name.strip().lower()
    chosen_team: Dict[str, Any] | None = None
    for team in teams:
        name = str(team.get("name") or "").strip().lower()
        if name and name == target:
            chosen_team = team
            break
    if chosen_team is None:
        return {}
    players = chosen_team.get("players", []) or []
    mapping: Dict[str, str] = {}
    for player in players:
        pid = player.get("id")
        if pid is None:
            continue
        pname = player.get("name") or player.get("nickname") or str(pid)
        mapping[str(pname)] = str(pid)
    return mapping


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


def _process_series(
    team_name: str,
    series_id: str,
    end_state_path: Path,
    jsonl_path: Path,
    seconds_limit: float,
) -> None:
    end_state_payload = _load_end_state(end_state_path)
    players = _players_from_end_state(end_state_payload, team_name)
    if not players:
        print(
            f"[team paths] team={team_name} series={series_id} "
            "no matching players found in end_state; skipping."
        )
        return
    map_names = _maps_from_end_state(end_state_path)
    jsonl_maps = _maps_from_jsonl(jsonl_path)
    map_names = [m for m in map_names if m in jsonl_maps]

    print(
        f"[team paths] team={team_name} series={series_id} "
        f"players={len(players)} maps={map_names}"
    )

    build_team_round_paths_one_pass(
        jsonl_path=str(jsonl_path),
        player_names_or_ids=list(players.keys()),
        seconds_limit=seconds_limit,
        allowed_maps=map_names,
        output_root=Path("Data") / team_name.replace(" ", "_") / "Players",
    )


def generateTeamPaths(
    team_name: str,
    seconds_limit: float = 5.0,
) -> None:
    # Iterate each series for this team
    team_players_root = Path('Data') / team_name.replace(' ', '_') / 'Players'
    _cleanup_tmp_files(team_players_root)
    series_list = list(_series_files(team_name))
    max_workers = min(4, os.cpu_count() or 2)
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                _process_series,
                team_name,
                series_id,
                end_state_path,
                jsonl_path,
                seconds_limit,
            )
            for series_id, end_state_path, jsonl_path in series_list
        ]
        for future in as_completed(futures):
            future.result()


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
