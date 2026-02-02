from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PositionalObjects.JsonlEventReader import JsonlEventReader
from PathScripts.SeriesRoster import collect_team_players

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _load_player_paths(team_name: str, player_name: str, map_name: str) -> Dict[str, Any]:
    # Read Data/<Team>/Players/<Player>/<Map>/<Player>_<Map>_paths.json.
    # Resolve player/map directories case-insensitively so lowercase folders work.
    safe_team = team_name.replace(" ", "_")
    safe_player = player_name.replace(" ", "_")
    safe_map = map_name.replace(" ", "_")

    players_root = Path("Data") / safe_team / "Players"
    if not players_root.exists():
        raise FileNotFoundError(f"Team players folder not found: {players_root}")

    player_dir = None
    for entry in players_root.iterdir():
        if entry.is_dir() and entry.name.lower() == safe_player.lower():
            player_dir = entry
            break
    if player_dir is None:
        player_dir = players_root / safe_player

    map_dir = None
    if player_dir.exists():
        for entry in player_dir.iterdir():
            if entry.is_dir() and entry.name.lower() == safe_map.lower():
                map_dir = entry
                break
    if map_dir is None:
        map_dir = player_dir / safe_map

    paths_path = map_dir / f"{safe_player}_{safe_map}_paths.json"
    if not paths_path.exists():
        fallback_path = map_dir / f"{safe_player}_paths.json"
        if fallback_path.exists():
            paths_path = fallback_path
    if not paths_path.exists():
        raise FileNotFoundError(f"Paths JSON not found: {paths_path}")
    with open(paths_path, "r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def _select_rounds(payload: Dict[str, Any], side: str) -> Dict[str, List[Dict[str, Any]]]:
    # Choose which round set to analyze based on side selection.
    if side == "attack":
        return payload.get("attack_rounds", {}) or {}
    if side == "defense":
        return payload.get("defense_rounds", {}) or {}
    return payload.get("rounds", {}) or {}


def _round_side(
    round_id: str,
    attack_rounds: Dict[str, List[Dict[str, Any]]],
    defense_rounds: Dict[str, List[Dict[str, Any]]],
) -> str:
    # Infer side for a round by checking which side-specific bucket contains it.
    if round_id in attack_rounds and attack_rounds.get(round_id):
        return "attack"
    if round_id in defense_rounds and defense_rounds.get(round_id):
        return "defense"
    return "unknown"


def _load_map_callouts(map_name: str) -> List[Dict[str, Any]]:
    # Read MapData/<Map>/<Map>.json and return callouts.
    map_path = Path("MapData") / map_name / f"{map_name}.json"
    if not map_path.exists():
        raise FileNotFoundError(f"Map JSON not found: {map_path}")
    with open(map_path, "r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)
    return payload.get("callouts", []) or []


def _closest_callout(callouts: List[Dict[str, Any]], gx: float, gy: float) -> Optional[Dict[str, Any]]:
    # Find the nearest callout by 2D distance.
    best = None
    best_d2 = None
    for callout in callouts:
        loc = callout.get("location") or {}
        cx = loc.get("x")
        cy = loc.get("y")
        if cx is None or cy is None:
            continue
        dx = float(cx) - gx
        dy = float(cy) - gy
        d2 = dx * dx + dy * dy
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best = {
                "regionName": callout.get("regionName"),
                "superRegionName": callout.get("superRegionName"),
                "distance": math.sqrt(d2),
            }
    return best


def _series_jsonl_files(team_name: str) -> Iterable[Path]:
    safe_team = team_name.replace(" ", "_")
    series_dir = Path("Data") / safe_team / "series"
    if not series_dir.exists():
        return []
    jsonl_files = list(series_dir.glob("events_*_grid.jsonl")) + list(
        series_dir.glob("events_*_grid.jsonl.zip")
    )
    return sorted(jsonl_files)


def _event_actor_id(event: Dict[str, Any]) -> Optional[str]:
    actor = event.get("actor", {}) or {}
    if actor.get("id") is not None:
        return str(actor.get("id"))
    state = actor.get("state") or {}
    if state.get("id") is not None:
        return str(state.get("id"))
    return None


def _ability_name(event: Dict[str, Any]) -> Optional[str]:
    target = event.get("target", {}) or {}
    if target.get("id"):
        return str(target.get("id"))
    if target.get("name"):
        return str(target.get("name"))
    return None


def _ability_usage_near_callouts(
    team_name: str,
    player_name: str,
    map_name: str,
    callouts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    players = collect_team_players(team_name)
    player_id = players.get(player_name)
    if player_id is None:
        lookup = {name.lower(): pid for name, pid in players.items()}
        player_id = lookup.get(player_name.lower())
    if not player_id:
        return []

    results: List[Dict[str, Any]] = []
    counts: Dict[Tuple[str, str], int] = {}
    wanted = {str(player_id).lower()}
    for jsonl_path in _series_jsonl_files(team_name):
        reader = JsonlEventReader(str(jsonl_path))
        for record in reader.iter_records():
            for event in reader.iter_events(record):
                if event.get("type") != "player-used-ability":
                    continue
                actor_id = _event_actor_id(event)
                if not actor_id or str(actor_id) != str(player_id):
                    continue
                snapshots = reader.extract_player_snapshots(event, wanted)
                snapshot = snapshots.get(str(player_id).lower())
                if not snapshot:
                    continue
                event_map = snapshot.get("map_name")
                if not event_map or str(event_map).lower() != map_name.lower():
                    continue
                gx = snapshot.get("gx")
                gy = snapshot.get("gy")
                if gx is None or gy is None:
                    continue
                closest = _closest_callout(callouts, float(gx), float(gy))
                if not closest:
                    continue
                key = (
                    closest.get("regionName") or "",
                    closest.get("superRegionName") or "",
                )
                counts[key] = counts.get(key, 0) + 1
                results.append(
                    {
                        "occurredAt": event.get("occurredAt"),
                        "ability": _ability_name(event),
                        "gx": gx,
                        "gy": gy,
                        "regionName": closest.get("regionName"),
                        "superRegionName": closest.get("superRegionName"),
                        "distance": closest.get("distance"),
                    }
                )
    total = sum(counts.values())
    percentages: Dict[str, float] = {}
    if total > 0:
        for (region, super_region), count in counts.items():
            key = f"{region}|{super_region}"
            percentages[key] = round((count / total) * 100.0, 2)

    return {
        "events": results,
        "total_samples": total,
        "counts": {
            f"{region}|{super_region}": count
            for (region, super_region), count in counts.items()
        },
        "percentages": percentages,
    }


def _sample_at_time(
    round_samples: List[Dict[str, Any]], time_seconds: float
) -> Optional[Dict[str, Any]]:
    # Return the sample closest to the requested time.
    best = None
    best_dt = None
    for sample in round_samples:
        t = sample.get("t")
        if t is None:
            continue
        dt = abs(float(t) - time_seconds)
        if best_dt is None or dt < best_dt:
            best_dt = dt
            best = sample
    return best


def nearest_regions_for_time(
    team_name: str,
    player_name: str,
    map_name: str,
    time_seconds: float,
    side: str = "all",
) -> Dict[str, Any]:
    """
    For each round, find the closest callout to the player's position at time_seconds.
    Returns per-round counts plus overall frequency percentages.
    """
    paths = _load_player_paths(team_name, player_name, map_name)
    callouts = _load_map_callouts(map_name)

    rounds = _select_rounds(paths, side)
    attack_rounds = paths.get("attack_rounds", {}) or {}
    defense_rounds = paths.get("defense_rounds", {}) or {}
    per_round: Dict[str, Any] = {}
    counts: Dict[Tuple[str, str], int] = {}
    counts_attack: Dict[Tuple[str, str], int] = {}
    counts_defense: Dict[Tuple[str, str], int] = {}
    total_samples = 0
    total_attack = 0
    total_defense = 0

    for round_id, samples in rounds.items():
        sample = _sample_at_time(samples, time_seconds)
        if not sample:
            continue
        gx = sample.get("gx")
        gy = sample.get("gy")
        if gx is None or gy is None:
            continue
        closest = _closest_callout(callouts, float(gx), float(gy))
        if not closest:
            continue
        key = (closest.get("regionName") or "", closest.get("superRegionName") or "")
        round_side = _round_side(round_id, attack_rounds, defense_rounds)
        counts[key] = counts.get(key, 0) + 1
        total_samples += 1
        if round_side == "attack":
            counts_attack[key] = counts_attack.get(key, 0) + 1
            total_attack += 1
        elif round_side == "defense":
            counts_defense[key] = counts_defense.get(key, 0) + 1
            total_defense += 1

        per_round[round_id] = {
            "side": _round_side(round_id, attack_rounds, defense_rounds),
            "t": sample.get("t"),
            "gx": gx,
            "gy": gy,
            "regionName": closest.get("regionName"),
            "superRegionName": closest.get("superRegionName"),
            "distance": closest.get("distance"),
        }

    percentages = {}
    percentages_attack = {}
    percentages_defense = {}
    if total_samples > 0:
        for (region, super_region), count in counts.items():
            key = f"{region}|{super_region}"
            percentages[key] = round((count / total_samples) * 100.0, 2)
    if total_attack > 0:
        for (region, super_region), count in counts_attack.items():
            key = f"{region}|{super_region}"
            percentages_attack[key] = round((count / total_attack) * 100.0, 2)
    if total_defense > 0:
        for (region, super_region), count in counts_defense.items():
            key = f"{region}|{super_region}"
            percentages_defense[key] = round((count / total_defense) * 100.0, 2)

    ability_usage = _ability_usage_near_callouts(
        team_name=team_name,
        player_name=player_name,
        map_name=map_name,
        callouts=callouts,
    )

    return {
        "team": team_name,
        "player": player_name,
        "map": map_name,
        "time_seconds": time_seconds,
        "side": side,
        "total_samples": total_samples,
        "total_attack_samples": total_attack,
        "total_defense_samples": total_defense,
        "counts": {
            f"{region}|{super_region}": count
            for (region, super_region), count in counts.items()
        },
        "counts_attack": {
            f"{region}|{super_region}": count
            for (region, super_region), count in counts_attack.items()
        },
        "counts_defense": {
            f"{region}|{super_region}": count
            for (region, super_region), count in counts_defense.items()
        },
        "percentages": percentages,
        "percentages_attack": percentages_attack,
        "percentages_defense": percentages_defense,
        "ability_usage": ability_usage,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Find the nearest callout for a player at a given time in each round."
    )
    parser.add_argument("team", help="Team name (matches Data/<Team> folder).")
    parser.add_argument("player", help="Player name (matches Players/<Player> folder).")
    parser.add_argument("map", help="Map name (matches MapData/<Map> folder).")
    parser.add_argument("time", type=float, help="Time in seconds from round start.")
    parser.add_argument(
        "--side",
        choices=["all", "attack", "defense"],
        default="all",
        help="Which side's rounds to analyze (default: all).",
    )
    args = parser.parse_args()

    result = nearest_regions_for_time(
        args.team, args.player, args.map, args.time, side=args.side
    )
    print(json.dumps(result, indent=2))
