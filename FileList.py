from __future__ import annotations

import os
import sys

from GraphQlScripts import Keys
from GraphQlScripts.FileDownload import _request_with_backoff, download_file


def _get_headers() -> dict:
    api_key = "XEusO28JLPaduqTpVpT21ACFYHYOHWVsUOD3dE8z"
    if not api_key:
        raise ValueError("GRID API key is not set. Provide it via Keys.setkey() or GRID_API_KEY.")
    return {
        "Accept": "application/json",
        "x-api-key": api_key,
    }


def request_file_list(series_id: str) -> dict:
    url = f"https://api.grid.gg/file-download/list/{series_id}"
    response = _request_with_backoff(url, timeout=30, max_retries=3)
    response.raise_for_status()
    return response.json()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python FileList.py <series_id> [api_key]")
    series_id = sys.argv[1]
    if len(sys.argv) >= 3:
        Keys.setkey(sys.argv[2])
    payload = request_file_list(series_id)
    print(payload)

    files = payload.get("files", []) if isinstance(payload, dict) else []
    if len(files) < 2:
        raise SystemExit("File list has fewer than 2 files.")
    second = files[1]
    full_url = second.get("fullURL") or second.get("fullUrl")
    file_name = second.get("fileName") or second.get("filename")
    if not full_url or not file_name:
        raise SystemExit("Second file entry missing fullURL or fileName.")
    download_file(full_url, file_name, output_path=None)
    print(f"Downloaded: SeriesData/{file_name}")


if __name__ == "__main__":
    main()
