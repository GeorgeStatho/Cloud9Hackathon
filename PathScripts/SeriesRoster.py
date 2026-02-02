from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def iter_series_files(team_name: str) -> Iterable[Tuple[str, Path]]:
    # Yield (series_id, end_state_path) for each series in Data/<Team>/series.
    safe_team = team_name.replace(" ", "_")
    series_dir = Path("Data") / safe_team / "series"
    if not series_dir.exists():
        return []

    end_state_pattern = re.compile(r"end_state_(\d+)_grid\.json$", re.IGNORECASE)
    for end_state_path in sorted(series_dir.glob("end_state_*_grid.json")):
        match = end_state_pattern.search(end_state_path.name)
        if not match:
            continue
        series_id = match.group(1)
        yield series_id, end_state_path


def load_end_state(end_state_path: Path) -> Dict[str, Any]:
    with open(end_state_path, "r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def players_from_end_state(payload: Dict[str, Any], team_name: str) -> Dict[str, str]:
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


def collect_team_players(team_name: str) -> Dict[str, str]:
    # Aggregate unique nickname->id mappings across all end_state files.
    combined: Dict[str, str] = {}
    for _, end_state_path in iter_series_files(team_name):
        payload = load_end_state(end_state_path)
        players = players_from_end_state(payload, team_name)
        for name, pid in players.items():
            if name in combined:
                continue
            combined[name] = pid
    return combined
