import json
import os
from typing import Any, Dict

from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport

def writeToJSON(result: Dict[str, Any], filename: str) -> None:
    data_dir = "Data"
    os.makedirs(data_dir, exist_ok=True)
    output_path = os.path.join(data_dir, filename)
    with open(output_path, "w", encoding="utf-8") as team_file:
        json.dump(result, team_file, indent=2, ensure_ascii=False)
    print(f"Results written to {output_path}")
