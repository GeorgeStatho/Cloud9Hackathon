from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from PIL import Image, ImageDraw

from Map import Map


# Read the paths JSON file and return the round->samples mapping.
def _load_paths(paths_json_path: str) -> Dict[str, List[Dict[str, float]]]:
    with open(paths_json_path, "r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)
    return payload.get("rounds", {})


# Yield (x, y) points in image space, converting from game coords if needed.
def _iter_round_points(
    round_data: List[Dict[str, float]],
    map_info: Map | None,
) -> Iterable[Tuple[float, float]]:
    for sample in round_data:
        if "ix" in sample and "iy" in sample:
            yield float(sample["ix"]), float(sample["iy"])
            continue
        if map_info is not None and "gx" in sample and "gy" in sample:
            ix, iy = map_info.game_to_image(float(sample["gx"]), float(sample["gy"]))
            yield ix, iy


def _round_color(index: int, total: int) -> tuple[int, int, int, int]:
    if total <= 1:
        return 255, 99, 71, 200
    hue = index / total
    r = int(255 * max(0, min(1, abs(hue * 6 - 3) - 1)))
    g = int(255 * max(0, min(1, 2 - abs(hue * 6 - 2))))
    b = int(255 * max(0, min(1, 2 - abs(hue * 6 - 4))))
    return r, g, b, 200


# Create a transparent overlay and draw each round path over the map image.
def _draw_round_paths(
    base_image: Image.Image,
    rounds: Dict[str, List[Dict[str, float]]],
    map_info: Map | None,
    line_width: int,
) -> Image.Image:
    overlay = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    w, h = base_image.size
    max_jump = 150  # pixels
    total_rounds = max(len(rounds), 1)

    for index, samples in enumerate(rounds.values()):
        raw_points = list(_iter_round_points(samples, map_info))
        if len(raw_points) < 2:
            continue

        color = _round_color(index, total_rounds)
        segment: list[tuple[float, float]] = []
        prev: tuple[float, float] | None = None

        for (x, y) in raw_points:
            # 1) strict bounds (required for getpixel)
            if not (0 <= x < w and 0 <= y < h):
                if len(segment) >= 2:
                    draw.line(segment, fill=color, width=line_width)
                segment = []
                prev = None
                continue

            xi = int(x)
            yi = int(y)

            # 2) black-background mask (outside map silhouette)
            px = base_image.getpixel((xi, yi))  # RGBA
            if px[0] < 10 and px[1] < 10 and px[2] < 10:
                if len(segment) >= 2:
                    draw.line(segment, fill=color, width=line_width)
                segment = []
                prev = None
                continue

            # 3) teleport / bad-sample jump filter
            if prev is not None:
                dx = x - prev[0]
                dy = y - prev[1]
                if (dx * dx + dy * dy) ** 0.5 > max_jump:
                    if len(segment) >= 2:
                        draw.line(segment, fill=color, width=line_width)
                    segment = []

            segment.append((x, y))
            prev = (x, y)

        if len(segment) >= 2:
            draw.line(segment, fill=color, width=line_width)

    return Image.alpha_composite(base_image, overlay)


# Resolve the output path to the same folder as the JSON when a bare filename is given.
def _resolve_output_path(paths_json_path: str, output_png_path: str) -> Path:
    output_path = Path(output_png_path)
    if output_path.parent == Path("."):
        return Path(paths_json_path).parent / output_path.name
    return output_path


def render_paths_overlay(
    paths_json_path: str,
    map_png_path: str,
    output_png_path: str,
    map_info: Map | None = None,
    line_width: int = 3,
) -> None:
    # Load per-round path samples from JSON.
    rounds = _load_paths(paths_json_path)
    if not rounds:
        raise ValueError("No round data found in the paths JSON file.")

    # Load the base map image and draw all round paths on top.
    base_image = Image.open(map_png_path).convert("RGBA")
    combined = _draw_round_paths(base_image, rounds, map_info, line_width)

    # Write the composite image to disk.
    output_path = _resolve_output_path(paths_json_path, output_png_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.save(output_path)
