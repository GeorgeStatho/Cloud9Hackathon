from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterable, Optional,List
import json
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
