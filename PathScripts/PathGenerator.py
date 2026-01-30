from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from Player import Player
from Map import Map


# Normalize GRID timestamps into timezone-aware datetime objects for consistent math.
def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# Yield each event entry from a JSONL record to keep the main loop simple.
def _iter_events(record: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    record_time = record.get("occurredAt")
    for event in record.get("events", []):
        if record_time and "occurredAt" not in event:
            event["occurredAt"] = record_time
        yield event



# Locate a player's position inside any known event state payloads.
def _find_player_position(event: Dict[str, Any], player_key: str) -> Optional[Tuple[float, float]]:
    candidates = [
        event.get("seriesState"),
        event.get("seriesStateDelta"),
        event.get("actor", {}).get("state"),
        event.get("actor", {}).get("stateDelta"),
        event.get("target", {}).get("state"),
        event.get("target", {}).get("stateDelta"),
    ]
    # Walk all possible state containers to find the requested player's position.
    for state in candidates:
        if not state:
            continue
        for game in state.get("games", []) or []:
            for team in game.get("teams", []) or []:
                for player in team.get("players", []) or []:
                    pid = str(player.get("id", ""))
                    pname = (player.get("name") or player.get("nickname") or "").lower()
                    # Match by ID or by lowercased name.
                    if player_key == pid or player_key == pname:
                        pos = player.get("position")
                        # Only return when x/y are present to avoid corrupt samples.
                        if pos and pos.get("x") is not None and pos.get("y") is not None:
                            return float(pos["x"]), float(pos["y"])
    return None


# Locate the active map name from any available event state payloads.
def _find_map_name(event: Dict[str, Any]) -> Optional[str]:
    candidates = [
        event.get("seriesState"),
        event.get("seriesStateDelta"),
        event.get("actor", {}).get("state"),
        event.get("actor", {}).get("stateDelta"),
        event.get("target", {}).get("state"),
        event.get("target", {}).get("stateDelta"),
    ]
    for state in candidates:
        if not state:
            continue
        for game in state.get("games", []) or []:
            map_name = game.get("map", {}).get("name")
            if map_name:
                return str(map_name)
    return None


# Build per-round movement paths for a player within a fixed time window (default 5s).
def _iter_jsonl_records(jsonl_path: str) -> Iterable[Dict[str, Any]]:
    with open(jsonl_path, "r", encoding="utf-8") as file_handle:
        for line in file_handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _resolve_map_json(map_name: str) -> Optional[Path]:
    direct = Path("MapData") / map_name / f"{map_name}.json"
    if direct.exists():
        return direct
    map_root = Path("MapData")
    if not map_root.exists():
        return None
    target = map_name.lower()
    for folder in map_root.iterdir():
        if not folder.is_dir():
            continue
        if folder.name.lower() == target:
            candidate = folder / f"{folder.name}.json"
            if candidate.exists():
                return candidate
    return None


def _process_event(
    event: Dict[str, Any],
    player: Player,
    player_key: str,
    round_id: int,
    round_start: Optional[datetime],
    seconds_limit: float,
) -> Tuple[int, Optional[datetime]]:
    event_type = event.get("type")
    occurred_at = event.get("occurredAt")
    if not occurred_at:
        return round_id, round_start
    event_time = _parse_time(occurred_at)

    if event_type in {"game-started-round", "round-started-freezetime", "round-started"}:
        round_id += 1
        round_start = event_time
        player.start_round(round_id)

    if round_start is None:
        return round_id, round_start

    elapsed = (event_time - round_start).total_seconds()
    if elapsed < 0:
        return round_id, round_start

    pos = _find_player_position(event, player_key)
    if pos:
        gx, gy = pos
        player.record_position(round_id, elapsed, gx, gy, max_time=seconds_limit)

    return round_id, round_start


def _build_output(
    player: Player,
    map_info: Optional[Map],
    seconds_limit: float,
    map_name: Optional[str],
) -> Dict[str, Any]:
    output: Dict[str, Any] = {
        "player": player.name,
        "seconds_limit": seconds_limit,
        "map": map_name,
        "rounds": {},
    }

    for rid, path in player.paths.items():
        samples = []
        for sample in path:
            entry = {"t": sample.t, "gx": sample.gx, "gy": sample.gy}
            if map_info is not None:
                ix, iy = sample.to_image(map_info)
                entry["ix"] = ix
                entry["iy"] = iy
            samples.append(entry)
        output["rounds"][str(rid)] = samples

    return output


def _write_output(output_path: Path, output: Dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as out_handle:
        json.dump(output, out_handle, indent=2, ensure_ascii=False)


def _should_mark_game_end(event_type: Optional[str]) -> bool:
    # Treat these events as the end-of-game signal for map switching.
    return event_type in {"series-ended-game", "team-won-game"}


def _track_seen_map(
    detected_map: Optional[str],
    seen_maps: Dict[str, int],
) -> None:
    # Count map names that appear in the feed for debugging and validation.
    if detected_map:
        seen_maps[detected_map] = seen_maps.get(detected_map, 0) + 1


def _update_current_map(
    detected_map: Optional[str],
    current_map_name: Optional[str],
    game_ended: bool,
) -> Tuple[Optional[str], bool]:
    # Switch the active map when a new map appears after a game end.
    if detected_map and (current_map_name is None or (game_ended and detected_map != current_map_name)):
        return detected_map, False
    return current_map_name, game_ended


def _select_active_map(
    detected_map: Optional[str],
    current_map_name: Optional[str],
) -> Optional[str]:
    # Prefer the map detected in the current event, otherwise use the last known map.
    return detected_map or current_map_name


def _map_matches_filter(active_map: Optional[str], normalized_filter: str) -> bool:
    # Only process events that match the requested map filter.
    return bool(active_map) and (not normalized_filter or active_map.lower() == normalized_filter)


def _ensure_map_state(
    active_map: str,
    map_states: Dict[str, Dict[str, Any]],
    map_cache: Dict[str, Optional[Map]],
    player_id_or_name: str,
) -> Dict[str, Any]:
    # Lazily create per-map tracking state and cache map conversion data.
    if active_map not in map_states:
        map_json = _resolve_map_json(active_map)
        map_obj = Map.from_map_json(str(map_json)) if map_json else None
        map_cache[active_map] = map_obj
        map_states[active_map] = {
            "player": Player(player_id=player_id_or_name, name=player_id_or_name),
            "round_id": 0,
            "round_start": None,
        }
    return map_states[active_map]


def _process_event_for_player(
    event: Dict[str, Any],
    state: Dict[str, Any],
    player_key: str,
    seconds_limit: float,
) -> None:
    # Update round state and capture positions for the selected player.
    round_id, round_start = _process_event(
        event,
        state["player"],
        player_key,
        state["round_id"],
        state["round_start"],
        seconds_limit,
    )
    state["round_id"] = round_id
    state["round_start"] = round_start


def _finalize_outputs(
    map_states: Dict[str, Dict[str, Any]],
    map_cache: Dict[str, Optional[Map]],
    seconds_limit: float,
) -> Dict[str, Any]:
    # Build JSON outputs per map and write them to PlayerData/<player>/<map>/.
    outputs: Dict[str, Any] = {}
    for map_name, state in map_states.items():
        map_obj = map_cache.get(map_name)
        output = _build_output(state["player"], map_obj, seconds_limit, map_name)
        outputs[map_name] = output

        filename = f"{state['player'].name}_paths.json"
        output_path_obj = (
            Path("PlayerData") / state["player"].name / map_name / filename
        )
        _write_output(output_path_obj, output)

    return outputs


def _dump_seen_maps(
    debug_map_dump: Optional[Path],
    seen_maps: Dict[str, int],
) -> None:
    # Persist the map counts for debugging when a dump path is provided.
    if debug_map_dump is None:
        return
    debug_map_dump.parent.mkdir(parents=True, exist_ok=True)
    with open(debug_map_dump, "w", encoding="utf-8") as out_handle:
        json.dump(seen_maps, out_handle, indent=2, ensure_ascii=False)


def build_player_round_paths(
    jsonl_path: str,
    player_id_or_name: str,
    map_name: str,
    seconds_limit: float = 5.0,
    debug_map_dump: Optional[Path] = None,
) -> Dict[str, Any]:
    player_key = player_id_or_name.lower()
    normalized_filter = map_name.lower()
    map_states: Dict[str, Dict[str, Any]] = {}
    map_cache: Dict[str, Optional[Map]] = {}
    current_map_name: Optional[str] = None
    game_ended = False
    seen_maps: Dict[str, int] = {}

    for record in _iter_jsonl_records(jsonl_path):
        for event in _iter_events(record):
            # Check for end-of-game events so map switching only happens after a game finishes.
            event_type = event.get("type")
            if _should_mark_game_end(event_type):
                game_ended = True

            # Detect the map from the current event and keep a running count for debugging.
            detected_map = _find_map_name(event)
            _track_seen_map(detected_map, seen_maps)
            current_map_name, game_ended = _update_current_map(
                detected_map, current_map_name, game_ended
            )

            # Choose the active map and skip events that do not match the requested map filter.
            active_map = _select_active_map(detected_map, current_map_name)
            if not _map_matches_filter(active_map, normalized_filter):
                continue

            # Ensure per-map tracking state exists, then update round/path data for this event.
            state = _ensure_map_state(
                active_map,
                map_states,
                map_cache,
                player_id_or_name,
            )
            _process_event_for_player(event, state, player_key, seconds_limit)

    outputs = _finalize_outputs(map_states, map_cache, seconds_limit)
    _dump_seen_maps(debug_map_dump, seen_maps)
    return outputs
