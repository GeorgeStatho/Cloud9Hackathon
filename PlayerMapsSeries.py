import json
import argparse
from collections import Counter

STATE_CONTAINERS = [
    ("seriesState",),
    ("seriesStateDelta",),
    ("actor", "state"),
    ("actor", "stateDelta"),
    ("target", "state"),
    ("target", "stateDelta"),
]

def norm(s: str) -> str:
    return (s or "").strip().lower()

def get_nested(d, path):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur

def iter_records(jsonl_path: str):
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)

def iter_events(record):
    for ev in (record.get("events", []) or []):
        yield ev

def player_id_name_nick(p: dict):
    pid = norm(str(p.get("id", "")))
    pname = norm(p.get("name") or "")
    pnick = norm(p.get("nickname") or "")
    return pid, pname, pnick

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl_path")
    ap.add_argument("player")
    ap.add_argument("--examples", type=int, default=10)
    args = ap.parse_args()

    q = norm(args.player)

    any_match = Counter()
    with_pos = Counter()
    examples_with_pos = []

    events_scanned = 0
    matched_events = 0
    matched_with_pos = 0

    for rec in iter_records(args.jsonl_path):
        for ev in iter_events(rec):
            events_scanned += 1
            ev_type = ev.get("type")

            for path in STATE_CONTAINERS:
                state = get_nested(ev, path)
                if not state:
                    continue

                for game in (state.get("games", []) or []):
                    game_id = str(game.get("id", "") or "")
                    map_name = norm((game.get("map") or {}).get("name") or "") or "<unknown>"

                    for team in (game.get("teams", []) or []):
                        for p in (team.get("players", []) or []):
                            pid, pname, pnick = player_id_name_nick(p)
                            if q in {pid, pname, pnick}:
                                matched_events += 1
                                any_match[map_name] += 1

                                pos = p.get("position") or {}
                                if pos.get("x") is not None and pos.get("y") is not None:
                                    matched_with_pos += 1
                                    with_pos[map_name] += 1
                                    if len(examples_with_pos) < args.examples:
                                        examples_with_pos.append(
                                            (map_name, game_id, ev_type, float(pos["x"]), float(pos["y"]))
                                        )
                                break
                        else:
                            continue
                        break

    print("Player query:", args.player)
    print("Events scanned:", events_scanned)
    print("Matched events:", matched_events)
    print("Matched events WITH position:", matched_with_pos)

    print("\nMap counts (any match):")
    for k, v in any_match.most_common():
        print(f"  {k}: {v}")

    print("\nMap counts (WITH position):")
    for k, v in with_pos.most_common():
        print(f"  {k}: {v}")

    print("\nExamples WITH position (map, game_id, event_type, x, y):")
    for item in examples_with_pos:
        print(" ", item)

if __name__ == "__main__":
    main()

