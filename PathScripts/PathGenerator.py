from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple
import zipfile

from Player import Player
from Map import Map
from AttackDefenseParser import parse_attack_defense_rounds
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict

@dataclass
class PlayerRoundState:
    player_key: str
    player_all: Player
    player_attack: Player
    player_defense: Player

    round_id: int = 0
    round_in_game: int = 0
    round_start: Optional[datetime] = None

    game_id: Optional[str] = None
    player_team_id: Optional[str] = None
    current_side: Optional[str] = None


@dataclass
class MapState:
    map_name: str
    map_obj: Optional[Map]
    players: Dict[str, PlayerRoundState]
print("USING PathGenerator:", __file__)

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



# Check whether a player's inventory contains the spike (or bomb).
def _player_has_spike(player: Dict[str, Any]) -> bool:
    inventory = player.get("inventory", {}) or {}
    items = inventory.get("items", []) or []
    for item in items:
        item_id = str(item.get("id", "")).lower()
        item_name = str(item.get("name", "")).lower()
        if "spike" in item_id or "spike" in item_name:
            return True
        if "bomb" in item_id or "bomb" in item_name:
            return True
    return False


# Locate a player's position and stat snapshot inside any known event state payloads.
def _find_player_snapshot(
    event: Dict[str, Any],
    player_key: str,
) -> Optional[Dict[str, Any]]:
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
                            net_worth = player.get("netWorth")
                            loadout_value = player.get("loadoutValue")
                            return {
                                "gx": float(pos["x"]),
                                "gy": float(pos["y"]),
                                "net_worth": float(net_worth) if net_worth is not None else None,
                                "loadout_value": float(loadout_value) if loadout_value is not None else None,
                                "has_spike": _player_has_spike(player),
                            }
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
    path = Path(jsonl_path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zip_handle:
            jsonl_names = [name for name in zip_handle.namelist() if name.endswith(".jsonl")]
            if not jsonl_names:
                raise FileNotFoundError(f"No .jsonl file found inside {jsonl_path}")
            with zip_handle.open(jsonl_names[0], "r") as file_handle:
                for raw_line in file_handle:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    yield json.loads(line)
        return
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

    snapshot = _find_player_snapshot(event, player_key)
    if snapshot:
        player.record_position(
            round_id,
            elapsed,
            snapshot["gx"],
            snapshot["gy"],
            max_time=seconds_limit,
            net_worth=snapshot.get("net_worth"),
            loadout_value=snapshot.get("loadout_value"),
            has_spike=snapshot.get("has_spike"),
        )

    return round_id, round_start


def _is_round_start(event_type: Optional[str]) -> bool:
    # Identify events that begin a new round and reset the round timer.
    return event_type in {"game-started-round", "round-started-freezetime", "round-started"}


def _find_player_team_id(event: Dict[str, Any], player_key: str) -> Tuple[Optional[str], Optional[str]]:
    # Find the player's team (and game id) from any available state payload.
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
            game_id = game.get("id")
            for team in game.get("teams", []) or []:
                for player in team.get("players", []) or []:
                    pid = str(player.get("id", ""))
                    pname = (player.get("name") or player.get("nickname") or "").lower()
                    if player_key == pid or player_key == pname:
                        return str(team.get("id")) if team.get("id") is not None else None, (
                            str(game_id) if game_id is not None else None
                        )
    return None, None


def _find_player_agent(event: Dict[str, Any], player_key: str) -> Tuple[Optional[str], Optional[str]]:
    # Find the player's agent/character name and game id from any available state payload.
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
            game_id = game.get("id")
            for team in game.get("teams", []) or []:
                for player in team.get("players", []) or []:
                    pid = str(player.get("id", ""))
                    pname = (player.get("name") or player.get("nickname") or "").lower()
                    if player_key == pid or player_key == pname:
                        character = player.get("character", {}) or {}
                        agent = character.get("name") or character.get("id")
                        if agent:
                            return str(agent), (str(game_id) if game_id is not None else None)
    return None, None


def _lookup_player_side(
    side_data: Dict[str, Any],
    game_id: Optional[str],
    round_id: int,
    team_id: Optional[str],
) -> Optional[str]:
    # Match the player's team to the side recorded by the attack/defense parser.
    if not side_data or not game_id or not team_id:
        return None
    game_entry = side_data.get("games", {}).get(str(game_id))
    if not game_entry:
        return None
    round_entry = game_entry.get("rounds", {}).get(str(round_id))
    if not round_entry:
        return None
    for team in round_entry.get("teams", []):
        if str(team.get("id")) == str(team_id):
            return team.get("side")
    return None


def _build_output(
    player: Player,
    map_info: Optional[Map],
    seconds_limit: float,
    map_name: Optional[str],
    game_agents: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    output: Dict[str, Any] = {
        "player": player.name,
        "seconds_limit": seconds_limit,
        "map": map_name,
        "rounds": {},
    }
    if game_agents:
        output["game_agents"] = game_agents
        output["agents"] = [game_agents[key] for key in sorted(game_agents.keys())]

    for rid, path in player.paths.items():
        samples = []
        for sample in path:
            entry = {"t": sample.t, "gx": sample.gx, "gy": sample.gy}
            if sample.net_worth is not None:
                entry["netWorth"] = sample.net_worth
            if sample.loadout_value is not None:
                entry["loadoutValue"] = sample.loadout_value
            if sample.has_spike is not None:
                entry["hasSpike"] = sample.has_spike
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
            "map_obj": map_obj,
            "player_all": Player(player_id=player_id_or_name, name=player_id_or_name),
            "player_attack": Player(player_id=player_id_or_name, name=player_id_or_name),
            "player_defense": Player(player_id=player_id_or_name, name=player_id_or_name),
            "round_id": 0,
            "round_in_game": 0,
            "round_start": None,
            "player_team_id": None,
            "game_id": None,
            "current_side": None,
            "game_agents": {},
        }
    return map_states[active_map]

def _extract_player_snapshots(
    event: Dict[str, Any],
    wanted: set[str],
) -> Dict[str, Dict[str, Any]]:
    out = {}

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
            game_id = game.get("id")
            map_name = (game.get("map") or {}).get("name")

            for team in game.get("teams", []) or []:
                team_id = team.get("id")

                for player in team.get("players", []) or []:
                    pid = str(player.get("id") or "").lower()
                    pname = (player.get("name") or player.get("nickname") or "").lower()

                    key = pid if pid in wanted else (pname if pname in wanted else None)
                    if not key:
                        continue

                    payload = {
                        "team_id": str(team_id) if team_id else None,
                        "game_id": str(game_id) if game_id else None,
                        "map_name": map_name.lower() if map_name else None,
                    }

                    pos = player.get("position") or {}
                    if pos.get("x") is not None and pos.get("y") is not None:
                        payload["gx"] = float(pos["x"])
                        payload["gy"] = float(pos["y"])

                    out[key] = payload

    return out

def _process_event_for_player(
    event: Dict[str, Any],
    state: Dict[str, Any],
    player_key: str,
    seconds_limit: float,
    side_data: Dict[str, Any],
) -> None:
    event_type = event.get("type")
    occurred_at = event.get("occurredAt")
    if not occurred_at:
        return
    event_time = _parse_time(occurred_at)

    if _is_round_start(event_type):
        # bump global round id (unique across whole run)
        state["round_id"] += 1
        state["round_start"] = event_time

        state["player_all"].start_round(state["round_id"])
        state["player_attack"].start_round(state["round_id"])
        state["player_defense"].start_round(state["round_id"])

        team_id, new_game_id = _find_player_team_id(event, player_key)
        if team_id:
            state["player_team_id"] = team_id

        # reset per-game round counter on new game
        if new_game_id and new_game_id != state.get("game_id"):
            state["game_id"] = new_game_id
            state["round_in_game"] = 0
            agent_name, agent_game_id = _find_player_agent(event, player_key)
            if agent_name and agent_game_id:
                state["game_agents"][str(agent_game_id)] = agent_name

        state["round_in_game"] += 1

        state["current_side"] = _lookup_player_side(
            side_data,
            state["game_id"],
            state["round_in_game"],
            state["player_team_id"],
        )

    if state["round_start"] is None:
        return

    elapsed = (event_time - state["round_start"]).total_seconds()
    if elapsed < 0:
        return

    snapshot = _find_player_snapshot(event, player_key)
    if not snapshot:
        return

    gx = snapshot["gx"]
    gy = snapshot["gy"]
    net_worth = snapshot.get("net_worth")
    loadout_value = snapshot.get("loadout_value")

    # ---- Keep data, drop only obvious junk ----
    # Common "staging" / invalid patterns:
    # - exact (-1000, 0) (you saw this)
    # - extremely large magnitudes
    if (abs(gx) > 20000 or abs(gy) > 20000) or (abs(gx + 1000.0022) < 1e-3 and abs(gy) < 1e-3):
        return

    # Soft clamp if game_to_image lands slightly outside bounds.
    # This avoids deleting good edge points because of rounding / slight transform mismatch.
    map_obj = state.get("map_obj")
    if map_obj is not None:
        ix, iy = map_obj.game_to_image(gx, gy)

        w = map_obj.image_width
        h = map_obj.image_height
        tol = 25  # pixels of tolerance outside bounds before we consider it "really wrong"

        # If it's wildly off, it's probably junk -> drop
        if ix < -tol or ix > w + tol or iy < -tol or iy > h + tol:
            return

        # Otherwise accept it (DisplayPath will mask black background / split jumps).
        # NOTE: we do not clamp gx/gy here because we store game coords.
        # Clamping should be done in DisplayPath after conversion if needed.

    # Always record "all"
    side = (state["current_side"] or "").lower()
    has_spike = snapshot.get("has_spike") if side in {"attacker", "attack", "attacking"} else None

    state["player_all"].record_position(
        state["round_id"],
        elapsed,
        gx,
        gy,
        max_time=seconds_limit,
        net_worth=net_worth,
        loadout_value=loadout_value,
        has_spike=has_spike,
    )

    if side in {"attacker", "attack", "attacking"}:
        state["player_attack"].record_position(
            state["round_id"],
            elapsed,
            gx,
            gy,
            max_time=seconds_limit,
            net_worth=net_worth,
            loadout_value=loadout_value,
            has_spike=has_spike,
        )
    elif side in {"defender", "defense", "defending"}:
        state["player_defense"].record_position(
            state["round_id"],
            elapsed,
            gx,
            gy,
            max_time=seconds_limit,
            net_worth=net_worth,
            loadout_value=loadout_value,
            has_spike=None,
        )

def _finalize_outputs(
    map_states: Dict[str, Dict[str, Any]],
    map_cache: Dict[str, Optional[Map]],
    seconds_limit: float,
) -> Dict[str, Any]:
    # Build JSON outputs per map and write them to PlayerData/<player>/<map>/.
    outputs: Dict[str, Any] = {}
    for map_name, state in map_states.items():
        map_obj = map_cache.get(map_name)
        output = _build_output(
            state["player_all"],
            map_obj,
            seconds_limit,
            map_name,
            game_agents=state.get("game_agents"),
        )
        output["attack_rounds"] = _build_output(
            state["player_attack"], map_obj, seconds_limit, map_name
        )["rounds"]
        output["defense_rounds"] = _build_output(
            state["player_defense"], map_obj, seconds_limit, map_name
        )["rounds"]
        outputs[map_name] = output

        filename = f"{state['player_all'].name}_paths.json"
        output_path_obj = (
            Path("PlayerData") / state["player_all"].name / map_name / filename
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


def build_team_round_paths_one_pass(
    jsonl_path: str,
    player_names_or_ids: list[str],
    seconds_limit: float = 5.0,
    allowed_maps: Optional[list[str]] = None,
    debug_map_dump: Optional[Path] = None,
) -> Dict[str, Any]:
    side_data = parse_attack_defense_rounds(jsonl_path)

    wanted = {p.lower() for p in player_names_or_ids}
    allowed = {m.lower() for m in allowed_maps} if allowed_maps else None

    map_states: Dict[str, Dict[str, Any]] = {}
    map_cache: Dict[str, Optional[Map]] = {}

    current_map_name: Optional[str] = None
    game_ended = False
    seen_maps: Dict[str, int] = {}

    for record in _iter_jsonl_records(jsonl_path):
        for event in _iter_events(record):
            event_type = event.get("type")
            if _should_mark_game_end(event_type):
                game_ended = True

            # Detect the map from the current event and keep a running count for debugging.
            detected_map = _find_map_name(event)
            _track_seen_map(detected_map, seen_maps)
            current_map_name, game_ended = _update_current_map(
                detected_map, current_map_name, game_ended
            )

            active_map = _select_active_map(detected_map, current_map_name)
            if not active_map:
                continue

            active_map_l = active_map.lower()
            if allowed is not None and active_map_l not in allowed:
                continue

            # 🔑 Extract ALL players in one pass
            snapshots = _extract_player_snapshots(event, wanted)

            for player_key, ctx in snapshots.items():
                state = _ensure_map_state(
                    active_map_l,
                    map_states,
                    map_cache,
                    player_key,
                )

                _process_event_for_player(
                    event,
                    state,
                    player_key,
                    seconds_limit,
                    side_data,
                )

    outputs = _finalize_outputs(map_states, map_cache, seconds_limit)
    _dump_seen_maps(debug_map_dump, seen_maps)
    return outputs
