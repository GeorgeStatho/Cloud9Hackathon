import argparse
import sys
from pathlib import Path

# Allow running as a script from the repo root by ensuring the root is on sys.path.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PathScripts.DisplayPath import render_paths_overlay, render_route_clusters_overlay
from Map import Map
from PathScripts.PathGenerator import build_player_round_paths


def _resolve_map_json(map_name: str) -> Path | None:
    direct = Path("MapData") / map_name / f"{map_name}.json"
    if direct.exists():
        return direct
    map_root = Path("MapData")
    if not map_root.exists():
        return None
    target = map_name.lower()
    for folder in map_root.iterdir():
        if folder.is_dir() and folder.name.lower() == target:
            candidate = folder / f"{folder.name}.json"
            if candidate.exists():
                return candidate
    return None


def main() -> None:
    # Parse CLI arguments so the script can be reused for different series/player/map inputs.
    parser = argparse.ArgumentParser(
        description="Generate player paths from a series JSONL and render an overlay PNG."
    )
    parser.add_argument("jsonl_path", help="Path to the series JSONL file.")
    parser.add_argument("player", help="Player ID or player name to track.")
    parser.add_argument(
        "--map-json",
        default=None,
        help="Optional path to the map JSON file (e.g. MapData/Ascent/Ascent.json).",
    )
    parser.add_argument(
        "--map-png",
        default=None,
        help="Optional path to the map PNG. If omitted, it will be auto-detected.",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=5.0,
        help="Seconds from round start to include in the path (default: 5).",
    )
    parser.add_argument(
        "--map",
        default=None,
        help="Optional map name to restrict output (e.g. Ascent).",
    )
    parser.add_argument(
        "--debug-maps",
        default=None,
        help="Optional JSON output to dump map names seen in the JSONL.",
    )
    parser.add_argument(
        "--side",
        choices=["all", "attack", "defense", "both"],
        default="all",
        help="Which side to render (default: all).",
    )
    args = parser.parse_args()

    # Validate the JSONL path early to avoid silent failures later.
    jsonl_path = Path(args.jsonl_path)
    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL file not found: {jsonl_path}")

    # Normalize player name for filesystem-safe folder and file names.
    safe_player = args.player.replace(" ", "_")

    # Build path JSONs from the series feed and return map-scoped outputs.
    # If --map wasn't provided, infer it from the map JSON filename.
    if args.map is None and args.map_json is None:
        raise ValueError("Provide --map or --map-json to select a map.")
    inferred_map = args.map or Path(args.map_json).stem

    outputs = build_player_round_paths(
        jsonl_path=str(jsonl_path),
        player_id_or_name=args.player,
        map_name=inferred_map,
        seconds_limit=args.seconds,
        debug_map_dump=Path(args.debug_maps) if args.debug_maps else None,
    )

    # Render overlays for the requested map if a path file was produced.
    if isinstance(outputs, dict) and outputs:
        selected_map = None
        for key in outputs.keys():
            if key.lower() == inferred_map.lower():
                selected_map = key
                break
        if selected_map:
            if args.map_json:
                map_info = Map.from_map_json(args.map_json, args.map_png)
            else:
                map_json = _resolve_map_json(selected_map)
                if map_json is None:
                    raise FileNotFoundError(
                        f"Map JSON not found for map '{selected_map}'."
                    )
                map_info = Map.from_map_json(str(map_json), args.map_png)

            map_folder = Path("PlayerData") / safe_player / selected_map
            paths_json = map_folder / f"{safe_player}_paths.json"
            if paths_json.exists():
                sides = ["attack", "defense"] if args.side == "both" else [args.side]
                for side in sides:
                    overlay_png = map_folder / f"{safe_player}_{selected_map}_{side}_paths_overlay.png"
                    try:
                        render_paths_overlay(
                            paths_json_path=str(paths_json),
                            map_png_path=map_info.img_path,
                            output_png_path=str(overlay_png),
                            map_info=map_info,
                            side=side,
                        )
                    except ValueError as exc:
                        print(f"Skipping {side} overlay: {exc}")

                # ✅ generate ONE cluster image after overlays (runs once)
                cluster_png = map_folder / f"{safe_player}_{selected_map}_route_clusters.png"
                print(f"[clusters] writing: {cluster_png}")  # <-- add this line temporarily
                try:
                    render_route_clusters_overlay(
                        paths_json_path=str(paths_json),
                        map_png_path=map_info.img_path,
                        output_png_path=str(cluster_png),
                        map_info=map_info,
                        side="all",
                    )
                except ValueError as exc:
                    print(f"Skipping route clusters: {exc}")

            # Print the file names for quick CLI feedback.
            print(f"Paths JSON: {paths_json}")
            if args.side == "both":
                print(f"Overlay PNG: {map_folder / f'{safe_player}_{selected_map}_attack_paths_overlay.png'}")
                print(f"Overlay PNG: {map_folder / f'{safe_player}_{selected_map}_defense_paths_overlay.png'}")
            else:
                print(f"Overlay PNG: {map_folder / f'{safe_player}_{selected_map}_{args.side}_paths_overlay.png'}")


if __name__ == "__main__":
    # Entry point for CLI usage.
    main()
