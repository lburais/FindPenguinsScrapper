#!/usr/bin/env python3
"""
Create a Relive-like animated route video from a GPX file.

Example:
    python relive_like.py sortie.gpx --photos ./photos --output sortie.mp4

Dependencies:
    pip install pillow imageio imageio-ffmpeg requests
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TILE_SIZE = 256
USER_AGENT = "relive-like-python/1.0"

imageio = None
requests = None
Image = None
ImageDraw = None
ImageFont = None
ImageOps = None
np = None


def ensure_dependencies() -> None:
    global imageio, requests, Image, ImageDraw, ImageFont, ImageOps, np
    try:
        import imageio.v2 as imageio_module
        import numpy as numpy_module
        import requests as requests_module
        from PIL import Image as pil_image
        from PIL import ImageDraw as pil_image_draw
        from PIL import ImageFont as pil_image_font
        from PIL import ImageOps as pil_image_ops
    except ImportError as exc:
        missing = str(exc).split("No module named ")[-1].strip("'")
        raise SystemExit(
            f"Missing dependency: {missing}\n"
            "Install dependencies with:\n"
            "  pip install pillow imageio imageio-ffmpeg requests numpy"
        ) from exc

    imageio = imageio_module
    np = numpy_module
    requests = requests_module
    Image = pil_image
    ImageDraw = pil_image_draw
    ImageFont = pil_image_font
    ImageOps = pil_image_ops


@dataclass
class Point:
    lat: float
    lon: float
    ele: float | None
    when: dt.datetime | None
    distance_m: float = 0.0


@dataclass
class Photo:
    path: Path
    image: Image.Image
    when: dt.datetime | None
    lat: float | None
    lon: float | None


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_gpx(path: Path) -> list[Point]:
    tree = ET.parse(path)
    root = tree.getroot()
    points: list[Point] = []

    for node in root.iter():
        if not node.tag.endswith("trkpt") and not node.tag.endswith("rtept"):
            continue
        lat = float(node.attrib["lat"])
        lon = float(node.attrib["lon"])
        ele = None
        when = None
        for child in node:
            tag = child.tag.split("}", 1)[-1]
            if tag == "ele" and child.text:
                try:
                    ele = float(child.text)
                except ValueError:
                    ele = None
            elif tag == "time":
                when = parse_time(child.text)
        points.append(Point(lat=lat, lon=lon, ele=ele, when=when))

    if len(points) < 2:
        raise ValueError("The GPX file must contain at least two track points.")

    total = 0.0
    for idx in range(1, len(points)):
        total += haversine(points[idx - 1], points[idx])
        points[idx].distance_m = total
    return points


def haversine(a: Point, b: Point) -> float:
    radius = 6_371_000.0
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def elevation_gain(points: list[Point]) -> float:
    gain = 0.0
    last = None
    for point in points:
        if point.ele is None:
            continue
        if last is not None and point.ele > last:
            gain += point.ele - last
        last = point.ele
    return gain


def lonlat_to_world(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    scale = TILE_SIZE * (2**zoom)
    x = (lon + 180.0) / 360.0 * scale
    sin_lat = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * scale
    return x, y


def choose_zoom(points: list[Point], width: int, height: int, margin: int) -> int:
    usable_w = width - 2 * margin
    usable_h = height - 2 * margin - 120
    for zoom in range(17, 7, -1):
        coords = [lonlat_to_world(p.lon, p.lat, zoom) for p in points]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        if max(xs) - min(xs) <= usable_w and max(ys) - min(ys) <= usable_h:
            return zoom
    return 8


def fetch_tile(x: int, y: int, z: int, cache_dir: Path) -> Image.Image:
    max_tile = 2**z
    if y < 0 or y >= max_tile:
        return Image.new("RGB", (TILE_SIZE, TILE_SIZE), "#eef2f0")
    x = x % max_tile
    target = cache_dir / str(z) / str(x) / f"{y}.png"
    if target.exists():
        return Image.open(target).convert("RGB")

    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    response.raise_for_status()
    target.write_bytes(response.content)
    time.sleep(0.05)
    return Image.open(target).convert("RGB")


def build_map(
    points: list[Point],
    width: int,
    height: int,
    zoom: int,
    cache_dir: Path,
    margin: int,
) -> tuple[Image.Image, list[tuple[int, int]]]:
    coords = [lonlat_to_world(p.lon, p.lat, zoom) for p in points]
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    route_w = max_x - min_x
    route_h = max_y - min_y
    map_area_h = height - 120
    offset_x = min_x - (width - route_w) / 2
    offset_y = min_y - (map_area_h - route_h) / 2

    tile_x0 = math.floor(offset_x / TILE_SIZE)
    tile_y0 = math.floor(offset_y / TILE_SIZE)
    tile_x1 = math.floor((offset_x + width) / TILE_SIZE)
    tile_y1 = math.floor((offset_y + map_area_h) / TILE_SIZE)

    base = Image.new("RGB", (width, height), "#eef2f0")
    for tile_x in range(tile_x0, tile_x1 + 1):
        for tile_y in range(tile_y0, tile_y1 + 1):
            tile = fetch_tile(tile_x, tile_y, zoom, cache_dir)
            px = int(tile_x * TILE_SIZE - offset_x)
            py = int(tile_y * TILE_SIZE - offset_y)
            base.paste(tile, (px, py))

    overlay = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle((0, height - 120, width, height), fill=(16, 22, 30, 235))
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

    pixels = [(int(x - offset_x), int(y - offset_y)) for x, y in coords]
    return base, pixels


def default_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s"


def interpolate_index(points: list[Point], progress: float) -> int:
    target = points[-1].distance_m * progress
    lo, hi = 0, len(points) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if points[mid].distance_m < target:
            lo = mid + 1
        else:
            hi = mid
    return max(1, lo)


def exif_time(image: Image.Image) -> dt.datetime | None:
    try:
        exif = image.getexif()
    except Exception:
        return None
    for tag in (36867, 306):
        raw = exif.get(tag)
        if not raw:
            continue
        try:
            return dt.datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
        except ValueError:
            pass
    return None


def load_photos(folder: Path | None, max_side: int = 320) -> list[Photo]:
    if not folder or not folder.exists():
        return []
    photos: list[Photo] = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        try:
            image = Image.open(path)
            image = ImageOps.exif_transpose(image).convert("RGB")
            when = exif_time(image)
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            photos.append(Photo(path=path, image=image.copy(), when=when, lat=None, lon=None))
        except Exception as exc:
            print(f"Skipping photo {path}: {exc}", file=sys.stderr)
    return photos


def selected_photo(photos: list[Photo], current_time: dt.datetime | None, frame: int, fps: int) -> Photo | None:
    if not photos:
        return None
    if current_time:
        timed = [p for p in photos if p.when is not None]
        for photo in timed:
            start = photo.when
            if start and start <= current_time <= start + dt.timedelta(seconds=5):
                return photo
    seconds = frame / fps
    if int(seconds) % 12 < 5:
        return photos[(int(seconds) // 12) % len(photos)]
    return None


def draw_photo(frame: Image.Image, photo: Photo) -> None:
    draw = ImageDraw.Draw(frame)
    pad = 16
    img = photo.image
    x = frame.width - img.width - 28
    y = 28
    draw.rounded_rectangle((x - pad, y - pad, x + img.width + pad, y + img.height + pad), radius=18, fill=(255, 255, 255, 238))
    frame.paste(img, (x, y))


def render_video(
    points: list[Point],
    base: Image.Image,
    route_pixels: list[tuple[int, int]],
    photos: list[Photo],
    output: Path,
    title: str,
    fps: int,
    duration: int,
) -> None:
    width, height = base.size
    frames = fps * duration
    font_big = default_font(38, bold=True)
    font_mid = default_font(25, bold=True)
    font_small = default_font(21)
    total_km = points[-1].distance_m / 1000
    gain_m = elevation_gain(points)
    start_time = points[0].when
    end_time = points[-1].when
    total_seconds = (end_time - start_time).total_seconds() if start_time and end_time else duration

    output.parent.mkdir(parents=True, exist_ok=True)
    with imageio.get_writer(output, fps=fps, codec="libx264", quality=8, macro_block_size=8) as writer:
        for frame_no in range(frames):
            progress = frame_no / max(1, frames - 1)
            eased = 1 - (1 - progress) ** 2
            idx = interpolate_index(points, eased)
            frame = base.copy().convert("RGBA")
            draw = ImageDraw.Draw(frame)

            if len(route_pixels) > 1:
                draw.line(route_pixels, fill=(25, 38, 52, 150), width=8, joint="curve")
                draw.line(route_pixels[: idx + 1], fill=(255, 95, 54, 255), width=9, joint="curve")
                draw.line(route_pixels[: idx + 1], fill=(255, 230, 90, 255), width=3, joint="curve")

            marker = route_pixels[idx]
            draw.ellipse((marker[0] - 13, marker[1] - 13, marker[0] + 13, marker[1] + 13), fill=(255, 255, 255, 255))
            draw.ellipse((marker[0] - 8, marker[1] - 8, marker[0] + 8, marker[1] + 8), fill=(255, 95, 54, 255))

            current_time = None
            if start_time and end_time:
                current_time = start_time + dt.timedelta(seconds=total_seconds * eased)

            photo = selected_photo(photos, current_time, frame_no, fps)
            if photo:
                draw_photo(frame, photo)

            bottom_y = height - 104
            draw.text((28, bottom_y), title, font=font_big, fill=(255, 255, 255, 255))

            km = points[idx].distance_m / 1000
            elapsed = total_seconds * eased
            speed = (km / (elapsed / 3600)) if elapsed > 1 else 0.0
            stats = [
                (f"{km:0.1f} km", "distance"),
                (format_duration(elapsed), "temps"),
                (f"{speed:0.1f} km/h", "vitesse"),
                (f"{gain_m:0.0f} m+", "denivele"),
            ]
            stat_x = 28
            stat_y = height - 52
            for value, label in stats:
                draw.text((stat_x, stat_y), value, font=font_mid, fill=(255, 255, 255, 255))
                draw.text((stat_x, stat_y + 30), label, font=font_small, fill=(183, 199, 214, 255))
                stat_x += 190

            progress_w = int((width - 56) * eased)
            draw.rounded_rectangle((28, height - 10, width - 28, height - 4), radius=3, fill=(80, 92, 107, 255))
            draw.rounded_rectangle((28, height - 10, 28 + progress_w, height - 4), radius=3, fill=(255, 95, 54, 255))
            writer.append_data(np.asarray(frame.convert("RGB"), dtype=np.uint8))


def slug_from_path(path: Path) -> str:
    name = path.stem.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return name or "route"


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a Relive-like video from a GPX track.")
    parser.add_argument("gpx", type=Path, help="GPX track file")
    parser.add_argument("--output", "-o", type=Path, help="Output MP4 path")
    parser.add_argument("--photos", type=Path, help="Optional folder containing photos")
    parser.add_argument("--title", help="Video title")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--duration", type=int, default=45, help="Video duration in seconds")
    parser.add_argument("--zoom", type=int, help="Map zoom level, auto by default")
    parser.add_argument("--tile-cache", type=Path, default=Path(".tile-cache"))
    args = parser.parse_args(argv)

    ensure_dependencies()

    points = parse_gpx(args.gpx)
    zoom = args.zoom or choose_zoom(points, args.width, args.height, margin=60)
    title = args.title or args.gpx.stem.replace("_", " ").replace("-", " ").title()
    output = args.output or Path(f"{slug_from_path(args.gpx)}.mp4")
    photos = load_photos(args.photos)

    print(f"Loaded {len(points)} GPX points, zoom {zoom}, {len(photos)} photos.")
    base, route_pixels = build_map(points, args.width, args.height, zoom, args.tile_cache, margin=60)
    render_video(points, base, route_pixels, photos, output, title, args.fps, args.duration)
    print(f"Video created: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
