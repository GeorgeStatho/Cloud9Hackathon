from BasicFunctionalities import *

from Keys import API_KEY

import os
import requests

API_URL = "https://api.grid.gg/file-download/list/{seriesId}"
GAME_ID = "6"  # Valorant game ID. Don't want LOL Data

headers = {
    "Accept": "application/json",
    "x-api-key": API_KEY,
}

SERIES_DATA_DIR = "SeriesData"
os.makedirs(SERIES_DATA_DIR, exist_ok=True)


def download_series_files(series_id: str):
    url = API_URL.format(seriesId=series_id)
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()
print(download_series_files("2629390"))

def download_file(full_url: str, output_filename: str):
    output_path = os.path.join(SERIES_DATA_DIR, output_filename)
    with requests.get(full_url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

files = download_series_files("2629390")["files"]
first_file = files[0]
download_file(first_file["fullURL"], first_file["fileName"])
