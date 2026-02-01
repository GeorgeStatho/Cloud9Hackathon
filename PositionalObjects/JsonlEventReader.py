from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


class JsonlEventReader:
    def __init__(self, jsonl_path: str) -> None:
        self.jsonl_path = jsonl_path

    def iter_records(self) -> Iterable[Dict[str, Any]]:
        path = Path(self.jsonl_path)
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path, "r") as zip_handle:
                jsonl_names = [name for name in zip_handle.namelist() if name.endswith(".jsonl")]
                if not jsonl_names:
                    raise FileNotFoundError(f"No .jsonl file found inside {self.jsonl_path}")
                with zip_handle.open(jsonl_names[0], "r") as file_handle:
                    for raw_line in file_handle:
                        line = raw_line.decode("utf-8").strip()
                        if not line:
                            continue
                        yield json.loads(line)
            return

        with open(self.jsonl_path, "r", encoding="utf-8") as file_handle:
            for line in file_handle:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)

    def iter_events(self, record: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        record_time = record.get("occurredAt")
        for event in record.get("events", []):
            if record_time and "occurredAt" not in event:
                event["occurredAt"] = record_time
            yield event

    def find_map_name(self, event: Dict[str, Any]) -> Optional[str]:
        for state in self._candidate_states(event):
            for game in state.get("games", []) or []:
                map_name = game.get("map", {}).get("name")
                if map_name:
                    return str(map_name)
        return None

    def find_player_snapshot(self, event: Dict[str, Any], player_key: str) -> Optional[Dict[str, Any]]:
        for state in self._candidate_states(event):
            for game in state.get("games", []) or []:
                for team in game.get("teams", []) or []:
                    for player in team.get("players", []) or []:
                        pid = str(player.get("id", ""))
                        pname = (player.get("name") or player.get("nickname") or "").lower()
                        if player_key == pid or player_key == pname:
                            pos = player.get("position")
                            if pos and pos.get("x") is not None and pos.get("y") is not None:
                                net_worth = player.get("netWorth")
                                loadout_value = player.get("loadoutValue")
                                return {
                                    "gx": float(pos["x"]),
                                    "gy": float(pos["y"]),
                                    "net_worth": float(net_worth) if net_worth is not None else None,
                                    "loadout_value": float(loadout_value) if loadout_value is not None else None,
                                    "has_spike": self.player_has_spike(player),
                                }
        return None

    def find_player_team_id(
        self, event: Dict[str, Any], player_key: str
    ) -> Tuple[Optional[str], Optional[str]]:
        for state in self._candidate_states(event):
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

    def find_player_agent(
        self, event: Dict[str, Any], player_key: str
    ) -> Tuple[Optional[str], Optional[str]]:
        for state in self._candidate_states(event):
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

    def find_player_start_weapon(self, event: Dict[str, Any], player_key: str) -> Optional[str]:
        for state in self._candidate_states(event):
            for game in state.get("games", []) or []:
                for team in game.get("teams", []) or []:
                    for player in team.get("players", []) or []:
                        pid = str(player.get("id", ""))
                        pname = (player.get("name") or player.get("nickname") or "").lower()
                        if player_key == pid or player_key == pname:
                            return self.player_start_weapon(player)
        return None

    def extract_player_snapshots(
        self, event: Dict[str, Any], wanted: set[str]
    ) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for state in self._candidate_states(event):
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

    @staticmethod
    def player_has_spike(player: Dict[str, Any]) -> bool:
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

    @staticmethod
    def player_start_weapon(player: Dict[str, Any]) -> Optional[str]:
        inventory = player.get("inventory", {}) or {}
        items = inventory.get("items", []) or []
        if not items:
            return None

        def is_weapon(item: Dict[str, Any]) -> bool:
            item_id = str(item.get("id", "")).lower()
            item_name = str(item.get("name", "")).lower()
            if "melee" in item_id or "knife" in item_id:
                return False
            if "spike" in item_id or "spike" in item_name:
                return False
            return True

        equipped = [i for i in items if i.get("equipped") and is_weapon(i)]
        if equipped:
            return str(equipped[0].get("name") or equipped[0].get("id"))

        any_weapon = [i for i in items if is_weapon(i)]
        if any_weapon:
            return str(any_weapon[0].get("name") or any_weapon[0].get("id"))

        return None

    @staticmethod
    def _candidate_states(event: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        candidates = [
            event.get("seriesState"),
            event.get("seriesStateDelta"),
            event.get("actor", {}).get("state"),
            event.get("actor", {}).get("stateDelta"),
            event.get("target", {}).get("state"),
            event.get("target", {}).get("stateDelta"),
        ]
        for state in candidates:
            if state:
                yield state
