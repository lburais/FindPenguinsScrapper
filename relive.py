#!/usr/bin/env python3
"""
Create a Relive-like animated route video from a GPX file.

Example:
    python relive_like.py sortie.gpx --photos ./photos --output sortie.mp4

Dependencies:
    pip install pillow imageio imageio-ffmpeg requests
"""

from __future__ import annotations

import datetime as dt
import math
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


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


@dataclass
class WaypointEvent:
    name: str
    description: str
    photos: list[Photo]


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


def coord_key(lat: float, lon: float) -> str:
    return f"{lat:.7f},{lon:.7f}"


def parse_point_node(node: ET.Element) -> Point:
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
    return Point(lat=lat, lon=lon, ele=ele, when=when)


def resolve_photo_path(raw_path: str, gpx_path: Path, photos_dir: Path | None) -> Path | None:
    if not raw_path:
        return None

    candidate = Path(raw_path.strip())
    if candidate.exists():
        return candidate

    rel_to_gpx = (gpx_path.parent / candidate).resolve()
    if rel_to_gpx.exists():
        return rel_to_gpx

    if photos_dir is not None:
        from_folder = (photos_dir / candidate.name).resolve()
        if from_folder.exists():
            return from_folder

    return None


def load_event_photo(path: Path, max_side: int = 320) -> Photo | None:
    try:
        image = Image.open(path)
        image = ImageOps.exif_transpose(image).convert("RGB")
        when = exif_time(image)
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        return Photo(path=path, image=image.copy(), when=when, lat=None, lon=None)
    except Exception as exc:
        print(f"Skipping event photo {path}: {exc}", file=sys.stderr)
        return None


def parse_gpx(path: Path, photos_dir: Path | None = None) -> tuple[list[Point], dict[str, list[WaypointEvent]], list[Point]]:
    tree = ET.parse(path)
    root = tree.getroot()

    trk_nodes = [node for node in root.iter() if node.tag.endswith("trkpt")]
    wpt_nodes = [node for node in root.iter() if node.tag.endswith("wpt")]

    if trk_nodes:
        source_nodes = trk_nodes
    else:
        source_nodes = wpt_nodes

    points = [parse_point_node(node) for node in source_nodes]

    if len(points) < 2:
        raise ValueError("The GPX file must contain at least two trkpt or wpt points.")

    total = 0.0
    for idx in range(1, len(points)):
        total += haversine(points[idx - 1], points[idx])
        points[idx].distance_m = total

    # View points are strictly GPX waypoints.
    view_points = [parse_point_node(node) for node in wpt_nodes]
    events_by_coord: dict[str, list[WaypointEvent]] = {}

    for wpt in wpt_nodes:
        try:
            wpt_lat = float(wpt.attrib["lat"])
            wpt_lon = float(wpt.attrib["lon"])
        except Exception:
            continue

        name = ""
        description = ""
        photo_paths: list[Path] = []

        for child in wpt:
            tag = child.tag.split("}", 1)[-1]
            text = (child.text or "").strip()
            if tag == "name":
                name = text
            elif tag == "desc":
                description = text
            elif tag == "extensions":
                for ext in child:
                    ext_tag = ext.tag.split("}", 1)[-1]
                    ext_text = (ext.text or "").strip()
                    if ext_tag == "photo" and ext_text:
                        resolved = resolve_photo_path(ext_text, path, photos_dir)
                        if resolved is not None:
                            photo_paths.append(resolved)

        event_photos: list[Photo] = []
        for photo_path in photo_paths:
            loaded = load_event_photo(photo_path)
            if loaded is not None:
                event_photos.append(loaded)

        event = WaypointEvent(name=name, description=description, photos=event_photos)

        key = coord_key(wpt_lat, wpt_lon)
        events_by_coord.setdefault(key, []).append(event)

    return points, events_by_coord, view_points


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
        print(f"w: {usable_w} h: {usable_h} max xs: {max(xs)} min xs: {min(xs)} max ys: {max(ys)} min ys: {min(ys)} x: {max(xs) - min(xs)} y: {max(ys) - min(ys)}")
    return 6


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
    route_points: list[Point],
    width: int,
    height: int,
    zoom: int,
    cache_dir: Path,
    margin: int,
) -> tuple[Image.Image, list[tuple[int, int]]]:
    route_coords = [lonlat_to_world(p.lon, p.lat, zoom) for p in route_points]

    xs = [c[0] for c in route_coords]
    ys = [c[1] for c in route_coords]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    route_w = max(1.0, max_x - min_x)
    route_h = max(1.0, max_y - min_y)
    map_area_h = height - 120
    offset_x = min_x - max(margin, (width - route_w) / 2)
    offset_y = min_y - max(margin, (map_area_h - route_h) / 2)

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

    pixels = [(int(x - offset_x), int(y - offset_y)) for x, y in route_coords]
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


def wrap_text_lines(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def draw_event_card(frame: Image.Image, event: WaypointEvent, photo_index: int = 0) -> None:
    draw = ImageDraw.Draw(frame)
    title_font = default_font(24, bold=True)
    body_font = default_font(18)

    card_x = 20
    card_y = 20
    card_w = min(640, frame.width - 40)
    card_h = min(240, frame.height - 170)

    draw.rounded_rectangle(
        (card_x, card_y, card_x + card_w, card_y + card_h),
        radius=16,
        fill=(8, 12, 18, 215),
    )

    title = event.name or "Etape"
    draw.text((card_x + 16, card_y + 14), title, font=title_font, fill=(255, 255, 255, 255))

    description = event.description.strip() if event.description else ""
    if description:
        lines = wrap_text_lines(description, max_chars=72)[:6]
        y = card_y + 52
        for line in lines:
            draw.text((card_x + 16, y), line, font=body_font, fill=(218, 226, 235, 255))
            y += 26

    if event.photos:
        draw_photo(frame, event.photos[photo_index % len(event.photos)])


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
    events_by_coord: dict[str, list[WaypointEvent]],
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
    gain_m = elevation_gain(points)
    start_time = points[0].when
    end_time = points[-1].when
    total_seconds = (end_time - start_time).total_seconds() if start_time and end_time else duration

    photo_delay_seconds = 2.0
    triggered_keys: set[str] = set()

    output.parent.mkdir(parents=True, exist_ok=True)
    with imageio.get_writer(output, fps=fps, codec="libx264", quality=8, macro_block_size=8) as writer:

        def write_frame(idx: int, eased: float, event: WaypointEvent | None = None, photo_index: int = 0) -> None:
            frame = base.copy().convert("RGBA")
            draw = ImageDraw.Draw(frame)
            if len(route_pixels) > 1:
                draw.line(route_pixels[: idx + 1], fill=(255, 95, 54, 255), width=9, joint="curve")
                draw.line(route_pixels[: idx + 1], fill=(255, 230, 90, 255), width=3, joint="curve")
            marker = route_pixels[idx]
            draw.ellipse((marker[0] - 13, marker[1] - 13, marker[0] + 13, marker[1] + 13), fill=(255, 255, 255, 255))
            draw.ellipse((marker[0] - 8, marker[1] - 8, marker[0] + 8, marker[1] + 8), fill=(255, 95, 54, 255))
            if event is not None:
                draw_event_card(frame, event, photo_index)
            draw.text((28, height - 104), title, font=font_big, fill=(255, 255, 255, 255))
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

        for frame_no in range(frames):
            progress = frame_no / max(1, frames - 1)
            eased = 1 - (1 - progress) ** 2
            idx = interpolate_index(points, eased)

            point_key = coord_key(points[idx].lat, points[idx].lon)
            matched_events = events_by_coord.get(point_key)
            if matched_events and point_key not in triggered_keys:
                triggered_keys.add(point_key)
                event = matched_events[0]
                num_photos = len(event.photos) if event.photos else 1
                photo_frames = int(fps * photo_delay_seconds)
                for photo_idx in range(num_photos):
                    for _ in range(photo_frames):
                        write_frame(idx, eased, event, photo_idx)

            write_frame(idx, eased)


def slug_from_path(path: Path) -> str:
    name = path.stem.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return name or "route"


def create_relive_video(
    gpx: Path | str,
    output: Path | str | None = None,
    photos: Path | str | None = None,
    title: str | None = None,
    width: int = 800,
    height: int = 800,
    fps: int = 24,
    duration: int = 45,
    zoom: int | None = None,
    tile_cache: Path | str = Path(".tile-cache"),
) -> Path:
    """Build a Relive-like MP4 from a GPX track using direct function args."""

    ensure_dependencies()

    gpx_path = Path(gpx)
    output_path = Path(output) if output is not None else Path(f"{slug_from_path(gpx_path)}.mp4")
    photos_path = Path(photos) if photos is not None else None
    tile_cache_path = Path(tile_cache)

    points, events_by_coord, view_points = parse_gpx(gpx_path, photos_dir=photos_path)
    zoom_level = zoom or choose_zoom(view_points, width, height, margin=60)
    video_title = title or gpx_path.stem.replace("_", " ").replace("-", " ").title()

    event_count = sum(len(v) for v in events_by_coord.values())
    print(f"Loaded {len(points)} route points, zoom {zoom_level}, {event_count} waypoint event(s).")
    # base, route_pixels = build_map(points, view_points, width, height, zoom_level, tile_cache_path, margin=60)
    base, route_pixels = build_map(points, width, height, zoom_level, tile_cache_path, margin=60)
    render_video(points, base, route_pixels, events_by_coord, output_path, video_title, fps, duration)
    print(f"Video created: {output_path}")
    return output_path


