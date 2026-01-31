from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import zipfile


# Yield each record from a JSONL file as a parsed dict.
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
                    if line:
                        yield json.loads(line)
        return
    with open(jsonl_path, "r", encoding="utf-8") as file_handle:
        for line in file_handle:
            line = line.strip()
            if line:
                yield json.loads(line)


# Yield each event inside a record, inheriting occurredAt when the event doesn't have it.
def _iter_events(record: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    record_time = record.get("occurredAt")
    for event in record.get("events", []):
        if record_time and "occurredAt" not in event:
            event["occurredAt"] = record_time
        yield event


# Collect candidate state payloads that may contain game/team side data.
def _state_candidates(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        event.get("seriesState"),
        event.get("seriesStateDelta"),
        event.get("actor", {}).get("state"),
        event.get("actor", {}).get("stateDelta"),
        event.get("target", {}).get("state"),
        event.get("target", {}).get("stateDelta"),
    ]


# Return the game id referenced directly by this event, if present.
def _event_game_id(event: Dict[str, Any]) -> Optional[str]:
    for container in ("actor", "target"):
        payload = event.get(container, {})
        if payload.get("type") == "game" and payload.get("id"):
            return str(payload["id"])
    return None


# Find the most relevant game for this event given the candidate state payloads.
def _select_game(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    wanted_id = _event_game_id(event)
    for state in _state_candidates(event):
        if not state:
            continue
        for game in state.get("games", []) or []:
            if wanted_id and str(game.get("id")) == wanted_id:
                return game
    for state in _state_candidates(event):
        if not state:
            continue
        for game in state.get("games", []) or []:
            if game.get("started") and not game.get("finished"):
                return game
    return None


# Extract team side data from a game payload.
def _extract_team_sides(game: Dict[str, Any]) -> List[Dict[str, Any]]:
    teams = []
    for team in game.get("teams", []) or []:
        teams.append(
            {
                "id": team.get("id"),
                "name": team.get("name"),
                "side": team.get("side"),
            }
        )
    return teams


# Try to read the round segment data and determine which team won.
def _find_round_winner(game: Dict[str, Any], round_number: int) -> Optional[Dict[str, Any]]:
    segments = game.get("segments", []) or []
    for segment in segments:
        if segment.get("type") != "round":
            continue
        if segment.get("sequenceNumber") != round_number:
            continue
        for team in segment.get("teams", []) or []:
            if team.get("won") is True:
                return {
                    "id": team.get("id"),
                    "name": team.get("name"),
                    "side": team.get("side"),
                }
    return None


# Decide whether this event indicates the start of a new round.
def _is_round_start(event_type: Optional[str]) -> bool:
    return event_type in {"game-started-round", "round-started-freezetime", "round-started"}


def parse_attack_defense_rounds(
    jsonl_path: str,
    output_path: str | None = None,
) -> Dict[str, Any]:
    # Track per-game round counters so each round gets an incrementing index.
    rounds_by_game: Dict[str, int] = {}
    output: Dict[str, Any] = {"games": {}}

    for record in _iter_jsonl_records(jsonl_path):
        series_id = record.get("seriesId")
        if series_id and "seriesId" not in output:
            output["seriesId"] = series_id

        for event in _iter_events(record):
            event_type = event.get("type")
            if not _is_round_start(event_type):
                continue

            game = _select_game(event)
            if not game:
                continue

            game_id = str(game.get("id"))
            if not game_id:
                continue

            rounds_by_game[game_id] = rounds_by_game.get(game_id, 0) + 1
            round_number = rounds_by_game[game_id]

            game_entry = output["games"].setdefault(
                game_id,
                {
                    "map": game.get("map", {}).get("name"),
                    "rounds": {},
                },
            )

            game_entry["rounds"][str(round_number)] = {
                "occurredAt": event.get("occurredAt"),
                "teams": _extract_team_sides(game),
                "winner": _find_round_winner(game, round_number),
            }

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as file_handle:
            json.dump(output, file_handle, indent=2, ensure_ascii=False)

    return output


if __name__ == "__main__":
    # Example usage: prints a small summary when run directly.
    import sys

    if len(sys.argv) < 2:
        raise SystemExit("Usage: python AttackDefenseParser.py <series.jsonl> [output.json]")
    jsonl = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    result = parse_attack_defense_rounds(jsonl, out)
    print(f"Parsed {len(result.get('games', {}))} games from {jsonl}")
