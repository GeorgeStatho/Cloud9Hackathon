import json
import os
from pathlib import Path


def _atomic_json_dump(path, payload) -> None:
    path = Path(path) if not isinstance(path, Path) else path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + '.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as out_handle:
        json.dump(payload, out_handle, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)

import requests


MAPS_JSON_PATH = Path("MapData/MapUuids/maps.json")
OUTPUT_ROOT = Path("MapData")


def sanitize_name(name: str) -> str:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in (" ", "-", "_")).strip()
    return safe.replace(" ", "_") or "Unknown_Map"


def select_map_image(map_data: dict) -> tuple[str | None, str | None]:
    for key in ("displayIcon", "listViewIcon", "splash", "stylizedBackgroundImage"):
        url = map_data.get(key)
        if url:
            return url, key
    return None, None


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(dest, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file_handle.write(chunk)


def main() -> None:
    if not MAPS_JSON_PATH.exists():
        raise FileNotFoundError(f"Missing maps.json at {MAPS_JSON_PATH}")

    with open(MAPS_JSON_PATH, "r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)

    maps = payload.get("data", [])
    for map_data in maps:
        display_name = map_data.get("displayName") or "Unknown Map"
        map_uuid = map_data.get("uuid") or "unknown_uuid"
        folder_name = sanitize_name(display_name)
        map_dir = OUTPUT_ROOT / folder_name
        map_dir.mkdir(parents=True, exist_ok=True)

        json_path = map_dir / f"{folder_name}.json"
        _atomic_json_dump(json_path, map_data)

        image_url, image_key = select_map_image(map_data)
        if image_url:
            image_path = map_dir / f"{folder_name}_{image_key}.png"
            download_file(image_url, image_path)


if __name__ == "__main__":
    main()
