from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PositionalObjects.JsonlEventReader import JsonlEventReader


KILL_EVENT_TYPES = {
    "player-killed-player",
    "game-killed-player",
}

DEATH_EVENT_TYPES = {
    "player-killed-player",
    "game-killed-player",
    "player-selfkilled-player",
    "player-teamkilled-player",
}

PLANT_EVENT_TYPES = {
    "player-completed-plantBomb",
}

DEFUSE_EVENT_TYPES = {
    "player-completed-defuseBomb",
    "player-completed-beginDefuseBomb",
    "player-completed-reachDefuseBombCheckpoint",
    "player-completed-stopDefuseBomb",
}


def _series_jsonl_files(team_name: str) -> List[Path]:
    safe_team = team_name.replace(" ", "_")
    series_dir = Path("Data") / safe_team / "series"
    series_ids: List[str] = []

    if series_dir.exists():
        direct_files = list(series_dir.glob("events_*_grid.jsonl")) + list(
            series_dir.glob("events_*_grid.jsonl.zip")
        )
        if direct_files:
            return sorted(direct_files)

        for end_state in series_dir.glob("end_state_*_grid.json"):
            parts = end_state.stem.split("_")
            if len(parts) >= 3:
                series_ids.append(parts[2])

    files: List[Path] = []
    for series_id in series_ids:
        candidate = series_dir / f"events_{series_id}_grid.jsonl"
        if not candidate.exists():
            candidate = series_dir / f"events_{series_id}_grid.jsonl.zip"
        if candidate.exists():
            files.append(candidate)
            continue

        fallback = Path("SeriesData") / f"events_{series_id}_grid.jsonl"
        if not fallback.exists():
            fallback = Path("SeriesData") / f"events_{series_id}_grid.jsonl.zip"
        if fallback.exists():
            files.append(fallback)

    if files:
        return sorted(files)

    series_data = Path("SeriesData")
    if series_data.exists():
        files.extend(series_data.glob("events_*_grid.jsonl"))
        files.extend(series_data.glob("events_*_grid.jsonl.zip"))
    return sorted(files)


def _event_player_id(event: dict, key: str) -> Optional[str]:
    node = event.get(key, {}) or {}
    if node.get("id") is not None:
        return str(node.get("id"))
    state = node.get("state") or {}
    if state.get("id") is not None:
        return str(state.get("id"))
    return None


def _map_from_record(reader: JsonlEventReader, record: dict) -> Optional[str]:
    for event in reader.iter_events(record):
        detected_map = reader.find_map_name(event)
        if detected_map:
            return detected_map
    return None


def compute_team_player_event_stats(team_name: str) -> Dict[str, Dict[str, Dict[str, List[float] | int | float]]]:
    """
    Returns {player_id: {map_name: stats}} where stats include:
      - kill_count
      - kill_distances
      - avg_kill_distance
      - death_count
      - plant_count
      - defuse_count
    """
    stats: Dict[str, Dict[str, Dict[str, List[float] | int | float]]] = {}
    for jsonl_path in _series_jsonl_files(team_name):
        reader = JsonlEventReader(str(jsonl_path))
        current_map: Optional[str] = None
        for record in reader.iter_records():
            record_map = _map_from_record(reader, record)
            if record_map:
                current_map = record_map
            for event in reader.iter_events(record):
                detected_map = reader.find_map_name(event)
                if detected_map:
                    current_map = detected_map

                event_type = event.get("type")
                if event_type not in (KILL_EVENT_TYPES | DEATH_EVENT_TYPES | PLANT_EVENT_TYPES | DEFUSE_EVENT_TYPES):
                    continue

                map_name = detected_map or current_map
                if not map_name:
                    continue
                map_key = map_name.lower()

                actor_id = _event_player_id(event, "actor")
                target_id = _event_player_id(event, "target")

                if event_type in KILL_EVENT_TYPES and actor_id and target_id:
                    killer = reader.find_player_snapshot(event, str(actor_id))
                    victim = reader.find_player_snapshot(event, str(target_id))
                    if killer and victim:
                        dx = killer["gx"] - victim["gx"]
                        dy = killer["gy"] - victim["gy"]
                        dist = math.sqrt(dx * dx + dy * dy)

                        player_maps = stats.setdefault(str(actor_id), {})
                        entry = player_maps.setdefault(
                            map_key,
                            {
                                "kill_count": 0,
                                "kill_distances": [],
                                "avg_kill_distance": 0.0,
                                "death_count": 0,
                                "plant_count": 0,
                                "defuse_count": 0,
                            },
                        )
                        entry["kill_count"] += 1
                        entry["kill_distances"].append(float(dist))
                        entry["avg_kill_distance"] = round(
                            sum(entry["kill_distances"]) / entry["kill_count"], 2
                        )

                if event_type in DEATH_EVENT_TYPES and target_id:
                    player_maps = stats.setdefault(str(target_id), {})
                    entry = player_maps.setdefault(
                        map_key,
                        {
                            "kill_count": 0,
                            "kill_distances": [],
                            "avg_kill_distance": 0.0,
                            "death_count": 0,
                            "plant_count": 0,
                            "defuse_count": 0,
                        },
                    )
                    entry["death_count"] += 1

                if event_type in PLANT_EVENT_TYPES and actor_id:
                    player_maps = stats.setdefault(str(actor_id), {})
                    entry = player_maps.setdefault(
                        map_key,
                        {
                            "kill_count": 0,
                            "kill_distances": [],
                            "avg_kill_distance": 0.0,
                            "death_count": 0,
                            "plant_count": 0,
                            "defuse_count": 0,
                        },
                    )
                    entry["plant_count"] += 1

                if event_type in DEFUSE_EVENT_TYPES and actor_id:
                    player_maps = stats.setdefault(str(actor_id), {})
                    entry = player_maps.setdefault(
                        map_key,
                        {
                            "kill_count": 0,
                            "kill_distances": [],
                            "avg_kill_distance": 0.0,
                            "death_count": 0,
                            "plant_count": 0,
                            "defuse_count": 0,
                        },
                    )
                    entry["defuse_count"] += 1

    return stats


def debug_player_kills(team_name: str, player_id: str, max_events: int = 5) -> None:
    """
    Print a small sample of kill events for the given player_id so we can verify matching.
    """
    seen = 0
    total = 0
    for jsonl_path in _series_jsonl_files(team_name):
        reader = JsonlEventReader(str(jsonl_path))
        current_map: Optional[str] = None
        for record in reader.iter_records():
            record_map = _map_from_record(reader, record)
            if record_map:
                current_map = record_map
            for event in reader.iter_events(record):
                detected_map = reader.find_map_name(event)
                if detected_map:
                    current_map = detected_map
                if event.get("type") not in KILL_EVENT_TYPES:
                    continue
                killer_id = _event_player_id(event, "actor")
                if not killer_id or str(killer_id) != str(player_id):
                    continue
                total += 1
                map_name = detected_map or current_map
                killer = reader.find_player_snapshot(event, str(killer_id))
                victim_id = _event_player_id(event, "target")
                victim = reader.find_player_snapshot(event, str(victim_id)) if victim_id else None
                print(
                    {
                        "map": map_name,
                        "killer_id": killer_id,
                        "victim_id": victim_id,
                        "killer_pos": (killer or {}).get("gx"),
                        "victim_pos": (victim or {}).get("gx"),
                        "occurredAt": event.get("occurredAt"),
                    }
                )
                seen += 1
                if seen >= max_events:
                    break
            if seen >= max_events:
                break
        if seen >= max_events:
            break
    print(f"total kill events matched for player {player_id}: {total}")
