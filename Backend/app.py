from __future__ import annotations

import os
import sys
import subprocess
import threading
import queue
import json
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

from flask import Flask, render_template, request, jsonify, abort, send_file

ROOT_DIR = Path(__file__).resolve().parent.parent
GRAPHQL_DIR = ROOT_DIR / "GraphQlScripts"
PATHS_DIR = ROOT_DIR / "PathScripts"

for path in (str(ROOT_DIR), str(GRAPHQL_DIR), str(PATHS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


app = Flask(__name__)

_log_queue: "queue.Queue[str]" = queue.Queue()
_run_lock = threading.Lock()


def _collect_files(team_name: str) -> dict:
    safe_team = team_name.replace(" ", "_")
    team_dir = ROOT_DIR / "Data" / safe_team
    outputs = {
        "team_dir": str(team_dir),
        "team_files": [],
        "team_data_files": [],
        "player_files": [],
        "nearsite_files": [],
    }
    if not team_dir.exists():
        return outputs

    outputs["team_files"] = sorted(
        [str(p.relative_to(ROOT_DIR)) for p in team_dir.glob("**/*") if p.is_file()]
    )

    team_data_dir = team_dir / "TeamData"
    if team_data_dir.exists():
        outputs["team_data_files"] = sorted(
            [str(p.relative_to(ROOT_DIR)) for p in team_data_dir.glob("**/*") if p.is_file()]
        )

    players_dir = team_dir / "Players"
    if players_dir.exists():
        for p in players_dir.glob("**/*"):
            if not p.is_file():
                continue
            rel = str(p.relative_to(ROOT_DIR))
            outputs["player_files"].append(rel)
            if rel.endswith("_nearsite.json"):
                outputs["nearsite_files"].append(rel)

    outputs["player_files"].sort()
    outputs["nearsite_files"].sort()
    return outputs


def _safe_repo_path(root: Path, rel: str) -> Path:
    rel = rel.lstrip("/").lstrip("\\")
    p = (root / rel).resolve()
    if not str(p).startswith(str(root)):
        raise ValueError("Invalid path.")
    return p


def _map_callouts(map_name: str) -> List[Dict[str, Any]]:
    map_path = ROOT_DIR / "MapData" / map_name / f"{map_name}.json"
    if not map_path.exists():
        return []
    with open(map_path, "r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)
    return payload.get("callouts", []) or []


def _map_image_rel(map_name: str) -> Optional[str]:
    map_dir = ROOT_DIR / "MapData" / map_name
    if not map_dir.exists():
        return None
    candidates = sorted(map_dir.glob(f"{map_name}_*.png"))
    if not candidates:
        return None
    return str(candidates[0].relative_to(ROOT_DIR)).replace("\\", "/")


def _signature_from_nearsite(payload: Dict[str, Any], key: str) -> Dict[str, Any]:
    data = payload.get(key, {}) or {}
    if not data:
        return {"zone": None, "percent": None}
    best_key = max(data, key=lambda k: data[k])
    return {"zone": best_key, "percent": data[best_key]}


def _rounds_stats(rounds: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    rounds_count = 0
    net_worths: List[float] = []
    loadouts: List[float] = []
    for samples in rounds.values():
        if not samples:
            continue
        rounds_count += 1
        sample = samples[0]
        if sample.get("netWorth") is not None:
            net_worths.append(float(sample["netWorth"]))
        if sample.get("loadoutValue") is not None:
            loadouts.append(float(sample["loadoutValue"]))
    avg_net = round(sum(net_worths) / len(net_worths), 2) if net_worths else None
    avg_loadout = round(sum(loadouts) / len(loadouts), 2) if loadouts else None
    return {
        "rounds": rounds_count,
        "avg_net_worth": avg_net,
        "avg_loadout_value": avg_loadout,
    }


def _round_count_from_round_shots(round_shots: Dict[str, Any], side: Optional[str] = None) -> int:
    count = 0
    for rounds in round_shots.values():
        for payload in (rounds or {}).values():
            if side and payload.get("side") != side:
                continue
            count += 1
    return count


def _spike_rate_attack(attack_rounds: Dict[str, List[Dict[str, Any]]]) -> Optional[float]:
    if not attack_rounds:
        return None
    total = 0
    spike_rounds = 0
    for samples in attack_rounds.values():
        if not samples:
            continue
        total += 1
        if any(sample.get("hasSpike") for sample in samples):
            spike_rounds += 1
    if total == 0:
        return None
    return round((spike_rounds / total) * 100.0, 2)


def _build_tendencies(
    *,
    rounds: int,
    signature: Dict[str, Any],
    avg_teammate_distance: Optional[float],
    spike_rate: Optional[float],
    headshot_rate: Optional[float],
    avg_kill_distance: Optional[float],
    top_weapon: Optional[Dict[str, Any]],
    side: str,
) -> List[str]:
    tendencies: List[str] = []
    if rounds <= 0:
        return tendencies

    zone = signature.get("zone")
    percent = signature.get("percent")
    if zone and percent is not None and percent >= 45:
        tendencies.append(f"{side} signature zone: {zone} ({percent}%).")

    # teammate spacing tendency is applied later using team-relative thresholds

    if spike_rate is not None and spike_rate >= 35:
        tendencies.append(f"Often carries spike ({spike_rate}%).")

    if headshot_rate is not None:
        if headshot_rate >= 30:
            tendencies.append(f"High headshot rate ({headshot_rate}%).")
        elif headshot_rate <= 15:
            tendencies.append(f"Low headshot rate ({headshot_rate}%).")

    if avg_kill_distance is not None:
        if avg_kill_distance < 900:
            tendencies.append("Takes short-range fights.")
        elif avg_kill_distance > 1600:
            tendencies.append("Takes long-range fights.")

    if top_weapon and top_weapon.get("percent") is not None:
        if top_weapon["percent"] >= 40:
            tendencies.append(
                f"Weapon-heavy on {top_weapon['name']} ({top_weapon['percent']}%)."
            )

    return tendencies


def _build_player_map_summary(paths_path: Path, map_name: str) -> Dict[str, Any]:
    with open(paths_path, "r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)

    rounds = payload.get("rounds", {}) or {}
    attack_rounds = payload.get("attack_rounds", {}) or {}
    defense_rounds = payload.get("defense_rounds", {}) or {}

    stats_overall = _rounds_stats(rounds)
    stats_attack = _rounds_stats(attack_rounds)
    stats_defense = _rounds_stats(defense_rounds)
    stats_attack["spike_rate_attack"] = _spike_rate_attack(attack_rounds)

    nearsite_path = paths_path.with_name(f"{paths_path.stem}_all_nearsite.json")
    display_path = paths_path.with_name(f"{paths_path.stem}_display.json")
    nearsite_rel = None
    display_rel = None
    sig_all = {"zone": None, "percent": None}
    sig_attack = {"zone": None, "percent": None}
    sig_defense = {"zone": None, "percent": None}
    if nearsite_path.exists():
        nearsite_rel = str(nearsite_path.relative_to(ROOT_DIR)).replace("\\", "/")
        with open(nearsite_path, "r", encoding="utf-8") as file_handle:
            nearsite = json.load(file_handle)
        sig_all = _signature_from_nearsite(nearsite, "percentages")
        sig_attack = _signature_from_nearsite(nearsite, "percentages_attack")
        sig_defense = _signature_from_nearsite(nearsite, "percentages_defense")

    if display_path.exists():
        display_rel = str(display_path.relative_to(ROOT_DIR)).replace("\\", "/")

    stats_path = paths_path.with_name(f"{paths_path.stem}_playerstatistics.json")
    player_stats: Dict[str, Any] = {}
    if stats_path.exists():
        with open(stats_path, "r", encoding="utf-8") as file_handle:
            player_stats = json.load(file_handle)

    map_kills = int(player_stats.get("kill_count", 0) or 0)
    map_deaths = int(player_stats.get("death_count", 0) or 0)
    map_kd = (
        round(map_kills / map_deaths, 2)
        if map_deaths
        else (round(float(map_kills), 2) if map_kills else None)
    )
    round_shots = player_stats.get("round_shots", {}) or {}
    map_headshots, map_bodyshots = _shot_totals_from_round_shots(round_shots)
    map_shot_total = map_headshots + map_bodyshots
    map_headshot_rate = (
        round((map_headshots / map_shot_total) * 100.0, 2) if map_shot_total else None
    )
    map_weapon_counts = _weapon_counts_from_round_shots(round_shots)
    map_top_weapons = _top_n_with_percent(map_weapon_counts, 3)

    # Build per-round weapon rates by aggregating counts across games for the same round key.
    per_round_weapon_counts: Dict[str, Dict[str, int]] = {}
    for rounds in round_shots.values():
        for round_key, round_payload in (rounds or {}).items():
            weapons = round_payload.get("weapons", {}) or {}
            bucket = per_round_weapon_counts.setdefault(str(round_key), {})
            for weapon, count in weapons.items():
                bucket[weapon] = bucket.get(weapon, 0) + int(count or 0)

    per_round_weapon_rates: Dict[str, List[Dict[str, Any]]] = {}
    for round_key, weapon_counts in per_round_weapon_counts.items():
        per_round_weapon_rates[round_key] = _top_n_with_percent(weapon_counts, 5)

    attack_round_shots = _filter_round_shots_by_side(round_shots, "attack")
    defense_round_shots = _filter_round_shots_by_side(round_shots, "defense")

    # Use player statistics round data (not path samples) for round counts.
    stats_overall["rounds"] = _round_count_from_round_shots(round_shots)
    stats_attack["rounds"] = _round_count_from_round_shots(round_shots, side="attack")
    stats_defense["rounds"] = _round_count_from_round_shots(round_shots, side="defense")

    attack_headshots, attack_bodyshots = _shot_totals_from_round_shots(attack_round_shots)
    attack_shot_total = attack_headshots + attack_bodyshots
    attack_headshot_rate = (
        round((attack_headshots / attack_shot_total) * 100.0, 2) if attack_shot_total else None
    )
    defense_headshots, defense_bodyshots = _shot_totals_from_round_shots(defense_round_shots)
    defense_shot_total = defense_headshots + defense_bodyshots
    defense_headshot_rate = (
        round((defense_headshots / defense_shot_total) * 100.0, 2) if defense_shot_total else None
    )

    attack_weapon_counts = _weapon_counts_from_round_shots(attack_round_shots)
    defense_weapon_counts = _weapon_counts_from_round_shots(defense_round_shots)
    attack_top_weapons = _top_n_with_percent(attack_weapon_counts, 3)
    defense_top_weapons = _top_n_with_percent(defense_weapon_counts, 3)

    attack_round_weapon_rates: Dict[str, List[Dict[str, Any]]] = {}
    for rounds in attack_round_shots.values():
        for round_key, round_payload in (rounds or {}).items():
            weapons = round_payload.get("weapons", {}) or {}
            bucket = attack_round_weapon_rates.setdefault(str(round_key), {})
            for weapon, count in weapons.items():
                bucket[weapon] = bucket.get(weapon, 0) + int(count or 0)
    attack_round_weapon_rates = {
        rk: _top_n_with_percent(counts, 5) for rk, counts in attack_round_weapon_rates.items()
    }

    defense_round_weapon_rates: Dict[str, List[Dict[str, Any]]] = {}
    for rounds in defense_round_shots.values():
        for round_key, round_payload in (rounds or {}).items():
            weapons = round_payload.get("weapons", {}) or {}
            bucket = defense_round_weapon_rates.setdefault(str(round_key), {})
            for weapon, count in weapons.items():
                bucket[weapon] = bucket.get(weapon, 0) + int(count or 0)
    defense_round_weapon_rates = {
        rk: _top_n_with_percent(counts, 5) for rk, counts in defense_round_weapon_rates.items()
    }

    tendencies_overall = _build_tendencies(
        rounds=stats_overall["rounds"],
        signature=sig_all,
        avg_teammate_distance=(player_stats.get("avg_teammate_distance") or {}).get("overall"),
        spike_rate=None,
        headshot_rate=map_headshot_rate,
        avg_kill_distance=player_stats.get("avg_kill_distance"),
        top_weapon=map_top_weapons[0] if map_top_weapons else None,
        side="Overall",
    )
    tendencies_attack = _build_tendencies(
        rounds=stats_attack["rounds"],
        signature=sig_attack,
        avg_teammate_distance=(player_stats.get("avg_teammate_distance") or {}).get("attack"),
        spike_rate=stats_attack.get("spike_rate_attack"),
        headshot_rate=attack_headshot_rate,
        avg_kill_distance=player_stats.get("avg_kill_distance"),
        top_weapon=attack_top_weapons[0] if attack_top_weapons else None,
        side="Attack",
    )
    tendencies_defense = _build_tendencies(
        rounds=stats_defense["rounds"],
        signature=sig_defense,
        avg_teammate_distance=(player_stats.get("avg_teammate_distance") or {}).get("defense"),
        spike_rate=None,
        headshot_rate=defense_headshot_rate,
        avg_kill_distance=player_stats.get("avg_kill_distance"),
        top_weapon=defense_top_weapons[0] if defense_top_weapons else None,
        side="Defense",
    )

    return {
        "overall": stats_overall,
        "attack": stats_attack,
        "defense": stats_defense,
        "signature_zone": sig_all,
        "signature_zone_attack": sig_attack,
        "signature_zone_defense": sig_defense,
        "paths_rel": str(paths_path.relative_to(ROOT_DIR)).replace("\\", "/"),
        "paths_display_rel": display_rel,
        "map_image_rel": _map_image_rel(map_name),
        "nearsite_rel": nearsite_rel,
        "player_stats": player_stats,
        "map_stats": {
            "kill_count": map_kills,
            "death_count": map_deaths,
            "kd_ratio": map_kd,
            "headshot_rate": map_headshot_rate,
            "top_weapons": map_top_weapons,
            "weapon_rates_by_round": per_round_weapon_rates,
        },
        "map_stats_attack": {
            "headshot_rate": attack_headshot_rate,
            "top_weapons": attack_top_weapons,
            "weapon_rates_by_round": attack_round_weapon_rates,
        },
        "map_stats_defense": {
            "headshot_rate": defense_headshot_rate,
            "top_weapons": defense_top_weapons,
            "weapon_rates_by_round": defense_round_weapon_rates,
        },
        "tendencies": {
            "overall": tendencies_overall,
            "attack": tendencies_attack,
            "defense": tendencies_defense,
        },
    }


def _top_n_with_percent(counts: Dict[str, int], n: int = 3) -> List[Dict[str, Any]]:
    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:n]
    output: List[Dict[str, Any]] = []
    for name, count in ranked:
        percent = round((count / total) * 100.0, 2) if total else None
        output.append({"name": name, "count": count, "percent": percent})
    return output


def _top_tendencies(items: List[str], max_items: int = 5) -> List[str]:
    if not items:
        return []
    counts: Dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [item for item, _ in ranked[:max_items]]


def _weapon_counts_from_round_shots(round_shots: Dict[str, Any]) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for rounds in round_shots.values():
        for round_payload in (rounds or {}).values():
            weapons = round_payload.get("weapons", {}) or {}
            for weapon, count in weapons.items():
                totals[weapon] = totals.get(weapon, 0) + int(count or 0)
    return totals


def _shot_totals_from_round_shots(round_shots: Dict[str, Any]) -> Tuple[int, int]:
    headshots = 0
    bodyshots = 0
    for rounds in round_shots.values():
        for round_payload in (rounds or {}).values():
            headshots += int(round_payload.get("headshots", 0) or 0)
            bodyshots += int(round_payload.get("bodyshots", 0) or 0)
    return headshots, bodyshots


def _filter_round_shots_by_round_keys(
    round_shots: Dict[str, Any],
    round_keys: set[str],
) -> Dict[str, Any]:
    filtered: Dict[str, Any] = {}
    for game_id, rounds in round_shots.items():
        for round_key, payload in (rounds or {}).items():
            if str(round_key) not in round_keys:
                continue
            game_bucket = filtered.setdefault(str(game_id), {})
            game_bucket[str(round_key)] = payload
    return filtered


def _filter_round_shots_by_side(
    round_shots: Dict[str, Any],
    side: str,
) -> Dict[str, Any]:
    filtered: Dict[str, Any] = {}
    for game_id, rounds in round_shots.items():
        for round_key, payload in (rounds or {}).items():
            if payload.get("side") != side:
                continue
            game_bucket = filtered.setdefault(str(game_id), {})
            game_bucket[str(round_key)] = payload
    return filtered


def _compute_team_avg_teammate_distance(
    stats: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Optional[float]]]:
    team_avgs: Dict[str, Dict[str, Optional[float]]] = {}
    sums: Dict[str, Dict[str, float]] = {}
    weights: Dict[str, Dict[str, float]] = {}

    for player_maps in stats.values():
        for map_name, summary in player_maps.items():
            if map_name == "__overall__":
                continue
            player_stats = summary.get("player_stats", {}) or {}
            distances = player_stats.get("avg_teammate_distance", {}) or {}
            for side in ("overall", "attack", "defense"):
                value = distances.get(side)
                if value is None:
                    continue
                rounds = summary.get(side, {}).get("rounds") or 0
                weight = float(rounds) if rounds else 1.0
                sums.setdefault(map_name, {}).setdefault(side, 0.0)
                weights.setdefault(map_name, {}).setdefault(side, 0.0)
                sums[map_name][side] += float(value) * weight
                weights[map_name][side] += weight

    for map_name, side_weights in weights.items():
        team_avgs.setdefault(map_name, {})
        for side, weight in side_weights.items():
            if not weight:
                team_avgs[map_name][side] = None
                continue
            team_avgs[map_name][side] = round(sums[map_name][side] / weight, 2)

    return team_avgs


def _apply_team_spacing_tendencies(
    stats: Dict[str, Dict[str, Any]],
    team_avgs: Dict[str, Dict[str, Optional[float]]],
) -> None:
    for player_maps in stats.values():
        for map_name, summary in player_maps.items():
            if map_name == "__overall__":
                continue
            player_stats = summary.get("player_stats", {}) or {}
            distances = player_stats.get("avg_teammate_distance", {}) or {}
            tendencies = summary.get("tendencies", {}) or {}
            for side in ("overall", "attack", "defense"):
                team_avg = (team_avgs.get(map_name) or {}).get(side)
                player_avg = distances.get(side)
                if team_avg is None or player_avg is None:
                    continue
                items = tendencies.get(side, [])
                filtered = [
                    item
                    for item in items
                    if not (
                        item.startswith("Plays spread out")
                        or item.startswith("Plays grouped")
                    )
                ]
                delta = float(player_avg) - float(team_avg)
                if delta >= 300:
                    filtered.append("Plays spread out.")
                elif delta <= -200:
                    filtered.append("Plays grouped.")
                tendencies[side] = filtered
            summary["tendencies"] = tendencies


def _compute_team_avg_kill_distance(
    stats: Dict[str, Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    totals: Dict[str, Tuple[float, int]] = {}
    for player_maps in stats.values():
        for map_name, summary in player_maps.items():
            if map_name == "__overall__":
                continue
            player_stats = summary.get("player_stats", {}) or {}
            avg_kill_distance = player_stats.get("avg_kill_distance")
            if avg_kill_distance is None:
                continue
            kills = int(player_stats.get("kill_count", 0) or 0)
            weight = kills if kills > 0 else 1
            current_total, current_weight = totals.get(map_name, (0.0, 0))
            totals[map_name] = (
                current_total + float(avg_kill_distance) * weight,
                current_weight + weight,
            )

    averages: Dict[str, Optional[float]] = {}
    for map_name, (total, weight) in totals.items():
        averages[map_name] = round(total / weight, 2) if weight else None
    return averages


def _apply_team_kill_distance_tendencies(
    stats: Dict[str, Dict[str, Any]],
    team_avgs: Dict[str, Optional[float]],
) -> None:
    for player_maps in stats.values():
        for map_name, summary in player_maps.items():
            if map_name == "__overall__":
                continue
            team_avg = team_avgs.get(map_name)
            player_stats = summary.get("player_stats", {}) or {}
            player_avg = player_stats.get("avg_kill_distance")
            if team_avg is None or player_avg is None:
                continue
            tendencies = summary.get("tendencies", {}) or {}
            delta = float(player_avg) - float(team_avg)
            for side in ("overall", "attack", "defense"):
                items = tendencies.get(side, [])
                filtered = [
                    item
                    for item in items
                    if item not in ("Takes short-range fights.", "Takes long-range fights.")
                ]
                if delta <= -200:
                    filtered.append("Takes short-range fights.")
                elif delta >= 300:
                    filtered.append("Takes long-range fights.")
                tendencies[side] = filtered
            summary["tendencies"] = tendencies


def _aggregate_player_overall(maps: Dict[str, Any]) -> Dict[str, Any]:
    total_kills = 0
    total_deaths = 0
    kill_distances: List[float] = []
    agent_counts: Dict[str, int] = {}
    weapon_counts: Dict[str, int] = {}
    headshots = 0
    bodyshots = 0
    total_games = 0
    teammate_distance_weighted: List[Tuple[float, float]] = []

    for map_summary in maps.values():
        player_stats = map_summary.get("player_stats", {}) or {}
        total_kills += int(player_stats.get("kill_count", 0) or 0)
        total_deaths += int(player_stats.get("death_count", 0) or 0)
        kill_distances.extend(player_stats.get("kill_distances", []) or [])

        agents = player_stats.get("agent_counts", {}) or {}
        for agent, count in agents.items():
            agent_counts[agent] = agent_counts.get(agent, 0) + int(count or 0)
        total_games += int(player_stats.get("games", 0) or 0)

        round_shots = player_stats.get("round_shots", {}) or {}
        hs, bs = _shot_totals_from_round_shots(round_shots)
        headshots += hs
        bodyshots += bs
        for weapon, count in _weapon_counts_from_round_shots(round_shots).items():
            weapon_counts[weapon] = weapon_counts.get(weapon, 0) + count

        avg_team_dist = (player_stats.get("avg_teammate_distance") or {}).get("overall")
        if avg_team_dist is not None:
            rounds = map_summary.get("overall", {}).get("rounds") or 0
            weight = float(rounds) if rounds else 1.0
            teammate_distance_weighted.append((float(avg_team_dist), weight))

    avg_kill_distance = (
        round(sum(kill_distances) / len(kill_distances), 2) if kill_distances else None
    )
    kd_ratio = (
        round(total_kills / total_deaths, 2)
        if total_deaths
        else (round(float(total_kills), 2) if total_kills else None)
    )
    shot_total = headshots + bodyshots
    headshot_rate = round((headshots / shot_total) * 100.0, 2) if shot_total else None
    if teammate_distance_weighted:
        weighted_sum = sum(value * weight for value, weight in teammate_distance_weighted)
        total_weight = sum(weight for _, weight in teammate_distance_weighted)
        avg_teammate_distance = round(weighted_sum / total_weight, 2) if total_weight else None
    else:
        avg_teammate_distance = None

    return {
        "total_kills": total_kills,
        "total_deaths": total_deaths,
        "kd_ratio": kd_ratio,
        "headshot_rate": headshot_rate,
        "avg_kill_distance": avg_kill_distance,
        "avg_teammate_distance": avg_teammate_distance,
        "top_agents": _top_n_with_percent(agent_counts, 3),
        "top_weapons": _top_n_with_percent(weapon_counts, 3),
        "total_games": total_games,
    }


def _aggregate_player_side_overall(maps: Dict[str, Any], side: str) -> Dict[str, Any]:
    rounds_total = 0
    net_total = 0.0
    loadout_total = 0.0
    net_weight = 0
    loadout_weight = 0
    headshot_weighted: List[Tuple[float, float]] = []
    teammate_weighted: List[Tuple[float, float]] = []

    for map_summary in maps.values():
        side_summary = map_summary.get(side, {}) or {}
        rounds = int(side_summary.get("rounds", 0) or 0)
        if rounds <= 0:
            continue
        rounds_total += rounds

        avg_net = side_summary.get("avg_net_worth")
        if avg_net is not None:
            net_total += float(avg_net) * rounds
            net_weight += rounds
        avg_loadout = side_summary.get("avg_loadout_value")
        if avg_loadout is not None:
            loadout_total += float(avg_loadout) * rounds
            loadout_weight += rounds

        headshot_rate = None
        if side == "attack":
            headshot_rate = (map_summary.get("map_stats_attack") or {}).get("headshot_rate")
        elif side == "defense":
            headshot_rate = (map_summary.get("map_stats_defense") or {}).get("headshot_rate")
        if headshot_rate is not None:
            headshot_weighted.append((float(headshot_rate), rounds))

        avg_team_dist = (map_summary.get("player_stats") or {}).get(
            "avg_teammate_distance", {}
        ).get(side)
        if avg_team_dist is not None:
            teammate_weighted.append((float(avg_team_dist), rounds))

    avg_net = round(net_total / net_weight, 2) if net_weight else None
    avg_loadout = round(loadout_total / loadout_weight, 2) if loadout_weight else None
    if headshot_weighted:
        weighted_sum = sum(value * weight for value, weight in headshot_weighted)
        total_weight = sum(weight for _, weight in headshot_weighted)
        headshot_rate = round(weighted_sum / total_weight, 2) if total_weight else None
    else:
        headshot_rate = None
    if teammate_weighted:
        weighted_sum = sum(value * weight for value, weight in teammate_weighted)
        total_weight = sum(weight for _, weight in teammate_weighted)
        avg_teammate_distance = round(weighted_sum / total_weight, 2) if total_weight else None
    else:
        avg_teammate_distance = None

    return {
        "rounds": rounds_total,
        "avg_net_worth": avg_net,
        "avg_loadout_value": avg_loadout,
        "headshot_rate": headshot_rate,
        "avg_teammate_distance": avg_teammate_distance,
    }


def _collect_player_map_stats(team_name: str) -> Dict[str, Dict[str, Any]]:
    safe_team = team_name.replace(" ", "_")
    players_root = ROOT_DIR / "Data" / safe_team / "Players"
    results: Dict[str, Dict[str, Any]] = {}
    if not players_root.exists():
        return results

    for player_dir in players_root.iterdir():
        if not player_dir.is_dir():
            continue
        player_name = player_dir.name
        results[player_name] = {}
        for map_dir in player_dir.iterdir():
            if not map_dir.is_dir():
                continue
            paths_candidates = list(map_dir.glob("*_paths.json"))
            if not paths_candidates:
                continue
            paths_path = paths_candidates[0]
            map_name = map_dir.name
            results[player_name][map_name] = _build_player_map_summary(paths_path, map_name)

        if results[player_name]:
            results[player_name]["__overall__"] = {
                "overall_player": _aggregate_player_overall(results[player_name]),
                "player_name": player_name,
            }
        else:
            results.pop(player_name, None)

    return results


def _collect_team_map_stats(stats: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    team_overall: List[Dict[str, Any]] = []
    map_names: List[str] = []
    maps: Dict[str, Dict[str, Any]] = {}
    team_tendencies_overall: Dict[str, List[str]] = {"overall": [], "attack": [], "defense": []}
    team_tendencies_by_map: Dict[str, Dict[str, List[str]]] = {}

    team_avgs = _compute_team_avg_teammate_distance(stats)
    _apply_team_spacing_tendencies(stats, team_avgs)
    team_kill_avgs = _compute_team_avg_kill_distance(stats)
    _apply_team_kill_distance_tendencies(stats, team_kill_avgs)

    for player_name, player_maps in stats.items():
        overall = player_maps.get("__overall__", {}).get("overall_player")
        if overall:
            team_overall.append(
                {
                    "name": player_name,
                    "overall": overall,
                    "attack": _aggregate_player_side_overall(player_maps, "attack"),
                    "defense": _aggregate_player_side_overall(player_maps, "defense"),
                }
            )

        for map_name, summary in player_maps.items():
            if map_name == "__overall__":
                continue
            if map_name not in maps:
                maps[map_name] = {
                    "map_name": map_name,
                    "map_image_rel": summary.get("map_image_rel"),
                    "players": [],
                    "paths": [],
                }
                map_names.append(map_name)
                team_tendencies_by_map[map_name] = {
                    "overall": [],
                    "attack": [],
                    "defense": [],
                }
            maps[map_name]["players"].append({"name": player_name, "summary": summary})
            maps[map_name]["paths"].append(
                {
                    "name": player_name,
                    "paths_rel": summary.get("paths_rel"),
                    "paths_display_rel": summary.get("paths_display_rel"),
                }
            )

            tendencies = summary.get("tendencies") or {}
            for scope in ("overall", "attack", "defense"):
                team_tendencies_by_map[map_name][scope].extend(tendencies.get(scope, []))

    map_names.sort()
    team_overall.sort(key=lambda item: item["name"].lower())
    for map_name in map_names:
        maps[map_name]["players"].sort(key=lambda item: item["name"].lower())
        maps[map_name]["paths"].sort(key=lambda item: item["name"].lower())
        team_tendencies_by_map[map_name] = {
            scope: _top_tendencies(team_tendencies_by_map[map_name][scope])
            for scope in ("overall", "attack", "defense")
        }

    for scope in ("overall", "attack", "defense"):
        team_tendencies_overall[scope] = _top_tendencies(
            [item for map_t in team_tendencies_by_map.values() for item in map_t[scope]]
        )

    return {
        "overall": team_overall,
        "map_names": map_names,
        "maps": maps,
        "team_tendencies": team_tendencies_overall,
        "team_tendencies_by_map": team_tendencies_by_map,
    }


def _enqueue(line: str) -> None:
    _log_queue.put(line)


def _run_pipeline(
    api_key: str,
    team_name: str,
    seconds_limit: float = 120.0,
    time_threshold: float = 30.0,
) -> List[str]:
    logs: List[str] = []
    env = os.environ.copy()
    env["GRID_API_KEY"] = api_key

    cmd = [
        sys.executable,
        str(ROOT_DIR / "main.py"),
        team_name,
        api_key,
        "--seconds",
        str(seconds_limit),
        "--time-threshold",
        str(time_threshold),
    ]
    logs.append(f"Running: {' '.join(cmd)}")
    _enqueue(logs[-1])

    process = subprocess.Popen(
        cmd,
        cwd=str(ROOT_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if not line:
            continue
        logs.append(line)
        _enqueue(line)

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"main.py failed with exit code {return_code}")

    return logs


@app.route("/", methods=["GET"])
def index():
    logs: List[str] = []
    outputs = None
    error = None
    api_key = ""
    team_name = ""
    seconds_limit = 120.0
    time_threshold = 30.0

    return render_template(
        "index.html",
        logs=logs,
        outputs=outputs,
        error=error,
        api_key=api_key,
        team_name=team_name,
        seconds_limit=seconds_limit,
        time_threshold=time_threshold,
    )


@app.route("/api/run", methods=["POST"])
def api_run():
    body = request.get_json(silent=True) or {}
    api_key = (body.get("api_key") or "").strip()
    team_name = (body.get("team_name") or "").strip()
    seconds_limit = float(body.get("seconds_limit", 120.0) or 120.0)
    time_threshold = float(body.get("time_threshold", 30.0) or 30.0)

    if not api_key or not team_name:
        return {"ok": False, "error": "Please provide both API key and team name."}, 400

    if not _run_lock.acquire(blocking=False):
        return {"ok": False, "error": "Pipeline already running."}, 409

    def _runner() -> None:
        try:
            _run_pipeline(
                api_key,
                team_name,
                seconds_limit=seconds_limit,
                time_threshold=time_threshold,
            )
        except Exception as exc:
            _enqueue(f"ERROR: {exc}")
        finally:
            _enqueue("__PIPELINE_DONE__")
            _run_lock.release()

    threading.Thread(target=_runner, daemon=True).start()
    return {"ok": True}


@app.route("/api/stream")
def api_stream():
    def stream():
        while True:
            line = _log_queue.get()
            yield f"data: {line}\n\n"
            if line == "__PIPELINE_DONE__":
                break

    return app.response_class(stream(), mimetype="text/event-stream")


@app.route("/api/file")
def api_file():
    rel = (request.args.get("path") or "").strip()
    if not rel:
        abort(400)
    try:
        p = _safe_repo_path(ROOT_DIR, rel)
    except Exception:
        abort(400)
    if not p.exists() or not p.is_file():
        abort(404)
    if p.suffix.lower() not in (".json", ".jsonl"):
        abort(400)
    with open(p, "r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)
    return jsonify(payload)


@app.route("/api/map/<map_name>")
def api_map(map_name: str):
    callouts = _map_callouts(map_name)
    return jsonify({"map": map_name, "callouts": callouts})


@app.route("/files/<path:relpath>")
def serve_file(relpath: str):
    try:
        p = _safe_repo_path(ROOT_DIR, relpath)
    except Exception:
        abort(400)
    if not p.exists() or not p.is_file():
        abort(404)
    return send_file(p)


@app.route("/results/<team_name>", methods=["GET"])
def results(team_name: str):
    stats = _collect_player_map_stats(team_name)
    team_stats = _collect_team_map_stats(stats)
    return render_template(
        "results.html",
        team_name=team_name,
        stats=stats,
        team_stats=team_stats,
    )


if __name__ == "__main__":
    app.run(debug=True)
