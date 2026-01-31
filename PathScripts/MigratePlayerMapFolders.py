from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, Tuple

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _iter_player_files(team_name: str) -> Iterable[Path]:
    safe_team = team_name.replace(" ", "_")
    base_dir = Path("Data") / safe_team / "Players"
    if not base_dir.exists():
        return []
    return base_dir.glob("*/**/*")


def _infer_map_from_name(filename: str) -> str | None:
    # Match <player>_<map>_paths*.json or *_paths*_overlay.png
    match = re.match(r".+_([^_]+)_paths.*\.(json|png)$", filename, re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def migrate_team_players(team_name: str) -> None:
    safe_team = team_name.replace(" ", "_")
    base_dir = Path("Data") / safe_team / "Players"
    if not base_dir.exists():
        raise FileNotFoundError(f"Players folder not found: {base_dir}")

    moved = 0
    for path in _iter_player_files(team_name):
        if not path.is_file():
            continue
        map_name = _infer_map_from_name(path.name)
        if not map_name:
            continue
        player_dir = path.parent
        # Already in a map subfolder?
        if player_dir.name.lower() == map_name.lower():
            continue
        target_dir = player_dir / map_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / path.name
        if target_path.exists():
            continue
        path.rename(target_path)
        moved += 1
    print(f"Moved {moved} files into map subfolders.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="One-time migration of player files into per-map subfolders."
    )
    parser.add_argument("team", help="Team name (matches Data/<Team> folder).")
    args = parser.parse_args()
    migrate_team_players(args.team)
 