import os

API_KEY = os.environ.get("GRID_API_KEY", "")


def setkey(key: str) -> None:
    global API_KEY
    API_KEY = key
