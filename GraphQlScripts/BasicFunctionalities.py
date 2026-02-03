import json
import os
from typing import Any, Dict

from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport


def _atomic_json_dump(path: str, payload: dict) -> None:
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as out_handle:
        json.dump(payload, out_handle, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)

def writeToJSON(result: Dict[str, Any], filename: str) -> None:
    data_dir = "Data"
    os.makedirs(data_dir, exist_ok=True)
    output_path = os.path.join(data_dir, filename)
    _atomic_json_dump(output_path, result)
    print(f"Results written to {output_path}")
