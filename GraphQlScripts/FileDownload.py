from BasicFunctionalities import *

from Keys import API_KEY

import os
import time
import requests

API_URL = "https://api.grid.gg/file-download/list/{seriesId}"
GAME_ID = "6"  # Valorant game ID. Don't want LOL Data

headers = {
    "Accept": "application/json",
    "x-api-key": API_KEY,
}

SERIES_DATA_DIR = "SeriesData"
os.makedirs(SERIES_DATA_DIR, exist_ok=True)




def _request_with_backoff(url: str, stream: bool = False, timeout: int = 30, max_retries: int = 5):
    delay = 2
    for attempt in range(max_retries):
        response = requests.get(url, headers=headers, stream=stream, timeout=timeout)
        if response.status_code != 429:
            return response
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            sleep_time = int(retry_after)
        else:
            sleep_time = delay
        time.sleep(sleep_time)
        delay = min(delay * 2, 30)
    response.raise_for_status()
    return response


def download_series_files(series_id: str):
    url = API_URL.format(seriesId=series_id)
    response = _request_with_backoff(url, timeout=30, max_retries=6)
    response.raise_for_status()
    return response.json()
print(download_series_files("2629390"))

def download_file(full_url: str, output_filename: str, output_path: str | None = None):
    if output_path is None:
        output_path = os.path.join(SERIES_DATA_DIR, output_filename)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.exists(output_path):
        return
    with _request_with_backoff(full_url, stream=True, timeout=60, max_retries=6) as r:
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)


#first_file = files[0]
#download_file(first_file["fullURL"], first_file["fileName"])
