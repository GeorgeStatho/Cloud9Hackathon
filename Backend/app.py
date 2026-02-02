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
    rounds_count = len(rounds)
    net_worths: List[float] = []
    loadouts: List[float] = []
    for samples in rounds.values():
        if not samples:
            continue
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
    nearsite_rel = None
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

    return {
        "overall": stats_overall,
        "attack": stats_attack,
        "defense": stats_defense,
        "signature_zone": sig_all,
        "signature_zone_attack": sig_attack,
        "signature_zone_defense": sig_defense,
        "paths_rel": str(paths_path.relative_to(ROOT_DIR)).replace("\\", "/"),
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
    }


def _top_n_with_percent(counts: Dict[str, int], n: int = 3) -> List[Dict[str, Any]]:
    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:n]
    output: List[Dict[str, Any]] = []
    for name, count in ranked:
        percent = round((count / total) * 100.0, 2) if total else None
        output.append({"name": name, "count": count, "percent": percent})
    return output


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


def _aggregate_player_overall(maps: Dict[str, Any]) -> Dict[str, Any]:
    total_kills = 0
    total_deaths = 0
    kill_distances: List[float] = []
    agent_counts: Dict[str, int] = {}
    weapon_counts: Dict[str, int] = {}
    headshots = 0
    bodyshots = 0
    total_games = 0

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

    return {
        "total_kills": total_kills,
        "total_deaths": total_deaths,
        "kd_ratio": kd_ratio,
        "headshot_rate": headshot_rate,
        "avg_kill_distance": avg_kill_distance,
        "top_agents": _top_n_with_percent(agent_counts, 3),
        "top_weapons": _top_n_with_percent(weapon_counts, 3),
        "total_games": total_games,
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
    return render_template("results.html", team_name=team_name, stats=stats)


if __name__ == "__main__":
    app.run(debug=True)
