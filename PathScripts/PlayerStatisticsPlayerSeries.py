from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterable, Optional, List, Tuple
import json
import bisect
import math
# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PathScripts.PlayerStatisticsParser import compute_team_player_event_stats
from PathScripts.SeriesRoster import collect_team_players


def _load_team_players(team_name: str) -> Dict[str, str]:
    return collect_team_players(team_name)


def _avg(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 2)

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
        return paths_json_path.parent.name
    return parts[-2]


def _agent_counts(game_agents: Dict[str, str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for agent in game_agents.values():
        if not agent:
            continue
        counts[agent] = counts.get(agent, 0) + 1
    return counts


def _load_paths_payload(paths_json: Path) -> Dict[str, Any]:
    with open(paths_json, "r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def _coerce_game_rounds(
    payload: Dict[str, Any],
    side: str = "all",
) -> Dict[str, Dict[str, List[Dict[str, float]]]]:
    if side == "attack":
        game_rounds = payload.get("attack_game_rounds")
        if game_rounds:
            return game_rounds
        rounds = payload.get("attack_rounds", {}) or {}
    elif side == "defense":
        game_rounds = payload.get("defense_game_rounds")
        if game_rounds:
            return game_rounds
        rounds = payload.get("defense_rounds", {}) or {}
    else:
        game_rounds = payload.get("game_rounds")
        if game_rounds:
            return game_rounds
        rounds = payload.get("rounds", {}) or {}

    # Fallback for older files: treat all rounds as a single synthetic game.
    return {"unknown": rounds}


def _round_samples_to_series(
    samples: List[Dict[str, float]]
) -> Tuple[List[float], List[Tuple[float, float]]]:
    times: List[float] = []
    points: List[Tuple[float, float]] = []
    for sample in samples:
        t = sample.get("t")
        gx = sample.get("gx")
        gy = sample.get("gy")
        if t is None or gx is None or gy is None:
            continue
        times.append(float(t))
        points.append((float(gx), float(gy)))
    return times, points


def _nearest_point(
    times: List[float],
    points: List[Tuple[float, float]],
    t: float,
) -> Optional[Tuple[float, float]]:
    if not times:
        return None
    idx = bisect.bisect_left(times, t)
    if idx <= 0:
        return points[0]
    if idx >= len(times):
        return points[-1]
    before = times[idx - 1]
    after = times[idx]
    if abs(t - before) <= abs(after - t):
        return points[idx - 1]
    return points[idx]


def _avg_teammate_distance_for_map(
    team_name: str,
    player_name: str,
    map_name: str,
    side: str = "all",
) -> Optional[float]:
    safe_team = team_name.replace(" ", "_")
    safe_player = player_name.replace(" ", "_")
    base_dir = Path("Data") / safe_team / "Players"
    if not base_dir.exists():
        return None

    player_paths = list(
        (base_dir / safe_player).glob(f"**/{map_name}/*_paths.json")
    )
    if not player_paths:
        return None
    player_payload = _load_paths_payload(player_paths[0])
    player_game_rounds = _coerce_game_rounds(player_payload, side=side)

    teammate_payloads: Dict[str, Dict[str, Any]] = {}
    for teammate_dir in base_dir.iterdir():
        if not teammate_dir.is_dir():
            continue
        if teammate_dir.name == safe_player:
            continue
        teammate_paths = list(teammate_dir.glob(f"**/{map_name}/*_paths.json"))
        if not teammate_paths:
            continue
        teammate_payloads[teammate_dir.name] = _load_paths_payload(teammate_paths[0])

    if not teammate_payloads:
        return None

    total_distance = 0.0
    total_samples = 0

    for game_id, rounds in player_game_rounds.items():
        if not rounds:
            continue
        for round_id, samples in rounds.items():
            times, points = _round_samples_to_series(samples)
            if not times:
                continue

            teammate_series: List[Tuple[List[float], List[Tuple[float, float]]]] = []
            for teammate_payload in teammate_payloads.values():
                teammate_game_rounds = _coerce_game_rounds(teammate_payload, side="all")
                teammate_rounds = teammate_game_rounds.get(str(game_id))
                if not teammate_rounds:
                    continue
                teammate_samples = teammate_rounds.get(str(round_id))
                if not teammate_samples:
                    continue
                teammate_series.append(_round_samples_to_series(teammate_samples))

            if not teammate_series:
                continue

            for idx, t in enumerate(times):
                gx, gy = points[idx]
                per_sample_sum = 0.0
                per_sample_count = 0
                for teammate_times, teammate_points in teammate_series:
                    nearest = _nearest_point(teammate_times, teammate_points, t)
                    if nearest is None:
                        continue
                    tx, ty = nearest
                    per_sample_sum += math.hypot(gx - tx, gy - ty)
                    per_sample_count += 1
                if per_sample_count:
                    total_distance += per_sample_sum / per_sample_count
                    total_samples += 1

    if total_samples == 0:
        return None
    return round(total_distance / total_samples, 2)


def generate_player_statistics_for_player(
    team_name: str,
    player_name: str,
    player_id: str | None,
    event_stats: Dict[str, Dict[str, Dict[str, List[float] | int | float]]],
) -> Dict[str, Optional[Path]]:
    player_stats_by_map = (
        event_stats.get(str(player_id), {}) if player_id else {}
    )
    outputs: Dict[str, Optional[Path]] = {}
    for paths_json in _player_paths(team_name, player_name):
        map_name = _infer_map_name(paths_json)
        with open(paths_json, "r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
        attack_rounds = payload.get("attack_rounds", {}) or {}
        defense_rounds = payload.get("defense_rounds", {}) or {}
        round_sides: Dict[str, str] = {}
        for round_id, samples in attack_rounds.items():
            if samples:
                round_sides[str(round_id)] = "attack"
        for round_id, samples in defense_rounds.items():
            if samples:
                round_sides[str(round_id)] = "defense"

        map_key = map_name.lower()
        map_stats = player_stats_by_map.get(
            map_key,
            {
                "kill_count": 0,
                "kill_distances": [],
                "avg_kill_distance": 0.0,
                "death_count": 0,
                "plant_count": 0,
                "defuse_count": 0,
                "game_agents": {},
                "round_shots": {},
            },
        )
        avg_teammate_distance = {
            "overall": _avg_teammate_distance_for_map(
                team_name, player_name, map_name, side="all"
            ),
            "attack": _avg_teammate_distance_for_map(
                team_name, player_name, map_name, side="attack"
            ),
            "defense": _avg_teammate_distance_for_map(
                team_name, player_name, map_name, side="defense"
            ),
        }
        game_agents = map_stats.get("game_agents", {}) or {}
        round_shots = map_stats.get("round_shots", {}) or {}
        for game_rounds in round_shots.values():
            for round_id, payload in (game_rounds or {}).items():
                side = round_sides.get(str(round_id))
                if side:
                    payload["side"] = side

        stats = {
            "team": team_name,
            "player": player_name,
            "map": map_name,
            "games": len(game_agents),
            "game_agents": game_agents,
            "agent_counts": _agent_counts(game_agents),
            "kill_count": map_stats["kill_count"],
            "kill_distances": map_stats["kill_distances"],
            "avg_kill_distance": map_stats["avg_kill_distance"] if map_stats["kill_count"] else None,
            "death_count": map_stats["death_count"],
            "plant_count": map_stats["plant_count"],
            "defuse_count": map_stats["defuse_count"],
            "round_shots": round_shots,
            "avg_teammate_distance": avg_teammate_distance,
        }

        output_path = paths_json.with_name(f"{paths_json.stem}_playerstatistics.json")
        with open(output_path, "w", encoding="utf-8") as file_handle:
            json.dump(stats, file_handle, indent=2, ensure_ascii=False)
        outputs[map_name] = output_path
    return outputs


def generate_player_statistics(
    team_name: str,
    player_name: str,
) -> Dict[str, Optional[Path]]:
    players = _load_team_players(team_name)
    player_id = players.get(player_name)
    if player_id is None:
        # Case-insensitive fallback to match folder names like "ethan" vs "Ethan".
        lookup = {name.lower(): pid for name, pid in players.items()}
        player_id = lookup.get(player_name.lower())
    event_stats = compute_team_player_event_stats(team_name)
    return generate_player_statistics_for_player(
        team_name, player_name, player_id, event_stats
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build per-map player statistics (agent per game) from paths JSONs."
    )
    parser.add_argument("team", help="Team name (matches Data/<Team> folder).")
    parser.add_argument("player", help="Player name (matches Players/<Player> folder).")
    args = parser.parse_args()

    generate_player_statistics(args.team, args.player)
