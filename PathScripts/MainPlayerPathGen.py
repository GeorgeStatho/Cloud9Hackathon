# This file generates per-player path JSON files under a team-specific Data folder.
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PathScripts.PathGenerator import build_player_round_paths


def _resolve_series_jsonl(team_name: str, series_filename: str) -> Path:
    # Build the expected path under Data/<Team>/series/ and validate it exists.
    safe_team = team_name.replace(" ", "_")
    series_path = Path("Data") / safe_team / "series" / series_filename
    if not series_path.exists():
        raise FileNotFoundError(f"Series JSONL not found: {series_path}")
    return series_path


def _write_player_paths(
    team_name: str,
    player_name: str,
    map_name: str,
    output: Dict[str, Any],
) -> Path:
    # Write the output JSON into Data/<Team>/Players/<Player>/<Player>_<Map>_paths.json.
    safe_team = team_name.replace(" ", "_")
    safe_player = player_name.replace(" ", "_")
    output_dir = Path("Data") / safe_team / "Players" / safe_player
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_player}_{map_name}_paths.json"
    with open(output_path, "w", encoding="utf-8") as file_handle:
        json.dump(output, file_handle, indent=2, ensure_ascii=False)
    return output_path


def generatePlayerPaths(
    team_name: str,
    player_name: str,
    series_filename: str,
    map_name: str,
    seconds_limit: float = 5.0,
) -> Optional[Path]:
    # Resolve the JSONL path under the team's Data folder and build paths for the selected map.
    jsonl_path = _resolve_series_jsonl(team_name, series_filename)
    outputs = build_player_round_paths(
        jsonl_path=str(jsonl_path),
        player_id_or_name=player_name,
        map_name=map_name,
        seconds_limit=seconds_limit,
    )

    # Pull the map-specific output and write it into the team/Players folder.
    for key, value in outputs.items():
        if key.lower() == map_name.lower():
            return _write_player_paths(team_name, player_name, key, value)

    return None
