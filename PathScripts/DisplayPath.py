from __future__ import annotations

import json
import numpy as np
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from array import array
from PIL import Image, ImageDraw, ImageFilter

from Map import Map


# Read the paths JSON file and return the round->samples mapping.
def _load_paths(
    paths_json_path: str,
    side: str,
) -> Dict[str, List[Dict[str, float]]]:
    with open(paths_json_path, "r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)
    if side == "attack":
        return payload.get("attack_rounds", {})
    if side == "defense":
        return payload.get("defense_rounds", {})
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
    max_jump = 200  # pixels
    total_rounds = max(len(rounds), 1)

    # How far we are willing to "snap" a point that lands in black background
    snap_radius = 10  # pixels; try 4..10
    black_thresh = 10  # background threshold

    def is_black(xi: int, yi: int) -> bool:
        px = base_image.getpixel((xi, yi))
        return px[0] < black_thresh and px[1] < black_thresh and px[2] < black_thresh

    def snap_to_map(x: float, y: float) -> tuple[float, float] | None:
        """
        If (x,y) lands on black background, search nearby pixels to find the closest
        non-black pixel and return that as the snapped point. If none found, return None.
        """
        xi = int(x)
        yi = int(y)

        # Must be inside image to even try snapping
        if not (0 <= xi < w and 0 <= yi < h):
            return None

        # Already on-map
        if not is_black(xi, yi):
            return x, y

        # Search a small square around the point for the nearest non-black pixel
        best = None
        best_d2 = None
        for dy in range(-snap_radius, snap_radius + 1):
            yy = yi + dy
            if yy < 0 or yy >= h:
                continue
            for dx in range(-snap_radius, snap_radius + 1):
                xx = xi + dx
                if xx < 0 or xx >= w:
                    continue
                if is_black(xx, yy):
                    continue
                d2 = dx * dx + dy * dy
                if best_d2 is None or d2 < best_d2:
                    best_d2 = d2
                    best = (float(xx), float(yy))

        return best

    for index, samples in enumerate(rounds.values()):
        raw_points = list(_iter_round_points(samples, map_info))
        if len(raw_points) < 2:
            continue

        color = _round_color(index, total_rounds)
        segment: list[tuple[float, float]] = []
        prev: tuple[float, float] | None = None

        for (x, y) in raw_points:
            # 1) If point is near-map, snap it; if far off-map, break.
            snapped = snap_to_map(x, y)
            if snapped is None:
                if len(segment) >= 2:
                    draw.line(segment, fill=color, width=line_width)
                segment = []
                prev = None
                continue

            x2, y2 = snapped

            # 2) teleport / bad-sample jump filter
            if prev is not None:
                dx = x2 - prev[0]
                dy = y2 - prev[1]
                if (dx * dx + dy * dy) ** 0.5 > max_jump:
                    if len(segment) >= 2:
                        draw.line(segment, fill=color, width=line_width)
                    segment = []

            segment.append((x2, y2))
            prev = (x2, y2)

        if len(segment) >= 2:
            draw.line(segment, fill=color, width=line_width)

    return Image.alpha_composite(base_image, overlay)

def render_route_clusters_overlay(
    paths_json_path: str,
    map_png_path: str,
    output_png_path: str,
    map_info: Map | None = None,
    side: str = "all",
    blur_radius: float = 3.0,
    percentile: float = 90.5,
    min_cluster_pixels: int = 60,
) -> None:
    rounds = _load_paths(paths_json_path, side)
    if not rounds:
        raise ValueError("No round data found in the paths JSON file.")

    base = Image.open(map_png_path).convert("RGBA")
    w, h = base.size

    counts = _build_density_counts(rounds, map_info, w, h)
    if _max_count(counts) == 0:
        raise ValueError("No in-bounds points found for clustering.")

    density_l = _counts_to_grayscale_image(counts, w, h)
    blurred = _blur_density(density_l, blur_radius)

    thr = _threshold_from_percentile(blurred, percentile)
    mask = _mask_from_threshold(blurred, thr)

    clusters = _connected_components(mask, w, h, min_cluster_pixels=min_cluster_pixels)
    if not clusters:
        raise ValueError("No clusters found. Try lowering percentile or min_cluster_pixels.")

    overlay = _render_clusters_overlay(w, h, clusters)
    out = Image.alpha_composite(base, overlay)

    output_path = _resolve_output_path(paths_json_path, output_png_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(output_path)


# -------------------------
# Step 1: Density (counts)
# -------------------------

def _build_density_counts(
    rounds: Dict[str, List[Dict[str, float]]],
    map_info: Map | None,
    w: int,
    h: int,
) -> array:
    """Return flat array counts[y*w + x] = number of samples landing on that pixel."""
    n = w * h
    counts = array("I", [0]) * n

    for samples in rounds.values():
        for (x, y) in _iter_round_points(samples, map_info):
            xi = int(x)
            yi = int(y)
            if 0 <= xi < w and 0 <= yi < h:
                counts[yi * w + xi] += 1

    return counts


def _max_count(counts: array) -> int:
    return max(counts) if counts else 0


# -------------------------
# Step 2: Counts -> Image
# -------------------------

def _counts_to_grayscale_image(counts: array, w: int, h: int) -> Image.Image:
    """
    Convert integer counts into an 8-bit grayscale image (L), scaled to 0..255.
    """
    max_c = _max_count(counts)
    density = Image.new("L", (w, h), 0)
    pix = density.load()

    if max_c <= 0:
        return density

    scale = 255.0 / float(max_c)
    for yi in range(h):
        row = yi * w
        for xi in range(w):
            c = counts[row + xi]
            if c:
                v = int(c * scale)
                if v > 255:
                    v = 255
                pix[xi, yi] = v

    return density


# -------------------------
# Step 3: Blur
# -------------------------

def _blur_density(density_l: Image.Image, blur_radius: float) -> Image.Image:
    return density_l.filter(ImageFilter.GaussianBlur(radius=blur_radius))


# -------------------------
# Step 4: Threshold
# -------------------------

def _threshold_from_percentile(blurred_l: Image.Image, percentile: float) -> int:
    """
    Compute an intensity threshold so that 'percentile'% of NONZERO pixels are <= thr.
    We'll keep pixels >= thr (top tail).
    """
    hist = blurred_l.histogram()  # 256 bins
    nonzero = sum(hist[1:])
    if nonzero == 0:
        return 255

    target = nonzero * (percentile / 100.0)
    cum = 0
    for v in range(1, 256):
        cum += hist[v]
        if cum >= target:
            return v
    return 255


def _mask_from_threshold(blurred_l: Image.Image, thr: int) -> bytearray:
    """
    Return a flat mask bytearray of length w*h (1 where blurred>=thr, else 0).
    """
    bdata = blurred_l.tobytes()
    mask = bytearray(len(bdata))
    for i, v in enumerate(bdata):
        if v >= thr:
            mask[i] = 1
    return mask


# -------------------------
# Step 5: Connected comps
# -------------------------

def _connected_components(mask: bytearray, w: int, h: int, min_cluster_pixels: int) -> List[List[int]]:
    """
    4-neighborhood connected components on flat mask.
    Returns list of components as lists of pixel indices.
    """
    n = w * h
    visited = bytearray(n)
    clusters: List[List[int]] = []

    def neighbors(idx: int):
        x = idx % w
        y = idx // w
        if x > 0:      yield idx - 1
        if x < w - 1:  yield idx + 1
        if y > 0:      yield idx - w
        if y < h - 1:  yield idx + w

    for i in range(n):
        if not mask[i] or visited[i]:
            continue

        q = deque([i])
        visited[i] = 1
        comp: List[int] = []

        while q:
            cur = q.pop()
            comp.append(cur)
            for nb in neighbors(cur):
                if mask[nb] and not visited[nb]:
                    visited[nb] = 1
                    q.append(nb)

        if len(comp) >= min_cluster_pixels:
            clusters.append(comp)

    return clusters


# -------------------------
# Step 6: Render overlay
# -------------------------

def _render_clusters_overlay(w: int, h: int, clusters: List[List[int]]) -> Image.Image:
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    opix = overlay.load()

    palette = [
        (255, 0, 0, 170),
        (0, 255, 0, 170),
        (0, 128, 255, 170),
        (255, 255, 0, 170),
        (255, 0, 255, 170),
        (0, 255, 255, 170),
        (255, 128, 0, 170),
        (128, 255, 0, 170),
    ]

    for ci, comp in enumerate(clusters):
        color = palette[ci % len(palette)]
        for idx in comp:
            x = idx % w
            y = idx // w
            opix[x, y] = color

    return overlay


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
    side: str = "all",
) -> None:
    # Load per-round path samples from JSON.
    rounds = _load_paths(paths_json_path, side)
    if not rounds:
        raise ValueError("No round data found in the paths JSON file.")

    # Load the base map image and draw all round paths on top.
    base_image = Image.open(map_png_path).convert("RGBA")
    combined = _draw_round_paths(base_image, rounds, map_info, line_width)

    # Write the composite image to disk.
    output_path = _resolve_output_path(paths_json_path, output_png_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.save(output_path)
