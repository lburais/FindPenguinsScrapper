from __future__ import annotations

import datetime as dt
import math
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import requests as requests_module

import numpy as numpy_module

import imageio
import imageio.v2 as imageio_module
from PIL import Image as pil_image
from PIL import ImageDraw as pil_image_draw
from PIL import ImageFont as pil_image_font
from PIL import ImageOps as pil_image_ops

TILE_SIZE = 256
USER_AGENT = "relive-like-python/1.0"

imageio = imageio_module
np = numpy_module
requests = requests_module
Image = pil_image
ImageDraw = pil_image_draw
ImageFont = pil_image_font
ImageOps = pil_image_ops

# ##############################################################################################
# dataclass
# ##############################################################################################

@dataclass
class Waypoint:
    """Waypoint event with name, description, and associated photos.
    
    Attributes:
        name: Event name or waypoint title.
        description: Event description or notes.
        displayed: Whether this event has been shown in the video.
        photos: List of Photo objects associated with this event.
    """
    name: str
    description: str
    displayed: bool
    lat: float
    lon: float
    when: dt.datetime | None
    photos: list[Photo]


@dataclass
class Point:
    """Geographic point along the route.
    
    Attributes:
        lat: Latitude coordinate.
        lon: Longitude coordinate.
        ele: Elevation in meters or None if not available.
        when: Timestamp or None if not available.
        distance_m: Cumulative distance from start in meters (default 0.0).
    """
    lat: float
    lon: float
    ele: float | None
    when: dt.datetime | None
    distance_m: float = 0.0


@dataclass
class Photo:
    """Photo associated with a waypoint event.
    
    Attributes:
        path: File path to the original image.
        image: Processed PIL Image object (RGB, resized).
        caption: Photo caption text or None.
    """
    path: Path
    image: Image.Image
    caption: str | None = None


# ##############################################################################################
# slug_from_path
# ##############################################################################################

def slug_from_path(path: Path) -> str:
    """Create URL-safe slug from file path.
    
    Args:
        path: File path.
        
    Returns:
        Lowercase slug with non-alphanumeric chars replaced by hyphens.
    """
    name = path.stem.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return name or "route"


# ##############################################################################################
# parse_time
# ##############################################################################################

def parse_time(value: str | None) -> dt.datetime | None:
    """Parse ISO format datetime string, handling Z timezone suffix.
    
    Args:
        value: ISO format datetime string or None.
        
    Returns:
        Parsed datetime object or None if parsing fails.
    """
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


# ##############################################################################################
# parse_point_node
# ##############################################################################################

def parse_point_node(node: ET.Element) -> Point:
    """Parse a GPX point/waypoint node into a Point object.
    
    Args:
        node: XML element containing lat, lon attributes and optional ele, time children.
        
    Returns:
        Point object with parsed coordinates, elevation, and timestamp.
    """
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


# ##############################################################################################
# resolve_photo_path
# ##############################################################################################

def resolve_photo_path(raw_path: str, gpx_path: Path, photos_dir: Path | None) -> Path | None:
    """Resolve a photo path from multiple possible locations.
    
    Attempts to find the photo file in: absolute path, relative to GPX file, or in photos_dir.
    
    Args:
        raw_path: Raw photo path from GPX file.
        gpx_path: Path to the GPX file for relative resolution.
        photos_dir: Optional directory to search for photos.
        
    Returns:
        Resolved Path object or None if file not found.
    """
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


# ##############################################################################################
# load_event_photo
# ##############################################################################################

def load_event_photo(path: Path, caption: str | None = None) -> Photo | None:
    """Load and prepare a photo for display in event card.
    
    Loads image, applies EXIF rotation.
    
    Args:
        path: Path to image file.
        caption: Optional photo caption text.
        
    Returns:
        Photo object with processed image or None if loading fails.
    """
    try:
        image = Image.open(path)
        image = ImageOps.exif_transpose(image).convert("RGB")
        return Photo(path=path, image=image.copy(), caption=caption)
    except Exception as exc:
        print(f"Skipping event photo {path}: {exc}", file=sys.stderr)
        return None


# ##############################################################################################
# haversine
# ##############################################################################################

def haversine(a: Point, b: Point) -> float:
    """Calculate great-circle distance between two points on Earth.
    
    Args:
        a: First point.
        b: Second point.
        
    Returns:
        Distance in meters.
    """
    radius = 6_371_000.0
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


# ##############################################################################################
# lonlat_to_world
# ##############################################################################################

def lonlat_to_world(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """Convert geographic coordinates to Web Mercator tile coordinates.
    
    Args:
        lon: Longitude.
        lat: Latitude.
        zoom: Zoom level.
        
    Returns:
        Tuple of (x, y) pixel coordinates at given zoom level.
    """
    lat = max(min(lat, 85.05112878), -85.05112878)
    scale = TILE_SIZE * (2**zoom)
    x = (lon + 180.0) / 360.0 * scale
    sin_lat = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * scale
    return x, y


# ##############################################################################################
# choose_zoom
# ##############################################################################################

def choose_zoom(points: list[Point], width: int, height: int, margin: int) -> int:
    """Choose optimal zoom level to fit all points with margin.
    
    Args:
        points: List of points to fit.
        width: Frame width in pixels.
        height: Frame height in pixels.
        margin: Margin around points in pixels.
        
    Returns:
        Zoom level (6-17).
    """
    usable_w = width - 2 * margin
    usable_h = height - 2 * margin - 120
    for zoom in range(17, 7, -1):
        coords = [lonlat_to_world(p.lon, p.lat, zoom) for p in points]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        if max(xs) - min(xs) <= usable_w and max(ys) - min(ys) <= usable_h:
            return zoom
    return 6


# ##############################################################################################
# fetch_tile
# ##############################################################################################

def fetch_tile(x: int, y: int, z: int, cache_dir: Path) -> Image.Image:
    """Fetch and cache a map tile from OpenStreetMap.
    
    Args:
        x: Tile X coordinate.
        y: Tile Y coordinate.
        z: Zoom level.
        cache_dir: Directory to cache tiles.
        
    Returns:
        PIL Image object with tile data.
    """
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


# ##############################################################################################
# default_font
# ##############################################################################################

def default_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Load a system font with fallback chain.
    
    Args:
        size: Font size in points.
        bold: Load bold variant if True.
        
    Returns:
        PIL ImageFont object.
    """
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


# ##############################################################################################
# format_duration
# ##############################################################################################

def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration string.
    
    Args:
        seconds: Duration in seconds.
        
    Returns:
        Formatted string like '1h 05m' or '3m 42s'.
    """
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s"


# ##############################################################################################
# wrap_text_line
# ##############################################################################################

def wrap_text_lines(text: str, max_chars: int) -> list[str]:
    """Wrap text into lines with maximum character width.
    
    Args:
        text: Text to wrap.
        max_chars: Maximum characters per line.
        
    Returns:
        List of text lines.
    """
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


# ##############################################################################################
# render_video
# ##############################################################################################

def render_video(
    points: list[Point],
    base: Image.Image,
    route_pixels: list[tuple[int, int]],
    waypoints: list[Waypoint],
    output: Path,
    title: str,
    fps: int,
    duration: int,
    photo_delay_seconds: float = 2.0,
    waypoint_pixels: list[tuple[int, int]] | None = None,
) -> None:
    """Render animated video with route and waypoint events.
    
    Generates MP4 video showing route animation with progress statistics
    and waypoint event cards with photos. Events are triggered when nearest
    waypoint is reached and all photos are displayed sequentially.
    
    Args:
        points: Route points with distance data.
        base: Base map image.
        route_pixels: Pixel coordinates for route points.
        waypoints: List of waypoint events.
        output: Output MP4 file path.
        title: Video title.
        fps: Frames per second.
        duration: Video duration in seconds.
        photo_delay_seconds: Seconds to display each photo (default 2.0).
        waypoint_pixels: Pixel coordinates for waypoints (default None).
    """
    if waypoint_pixels is None:
        waypoint_pixels = []

    width, height = base.size
    # frames = fps * duration
    font_big = default_font(38, bold=True)
    font_mid = default_font(25, bold=True)
    font_small = default_font(21)
    start_time = points[0].when
    end_time = points[-1].when
    total_seconds = (end_time - start_time).total_seconds() if start_time and end_time else duration
    total_photos = sum(max(1, len(wpt.photos)) for wpt in waypoints)
    route_frames = fps * duration
    frames = route_frames + int(fps * photo_delay_seconds) * total_photos
    route_frame_no = 0
    idx = 1
    eased = 0.0
    active_waypoint: Waypoint | None = None
    active_photo_idx = 0
    frames_left_for_photo = 0

    print(f"Frames: {route_frames} - Total Frames: {frames} - Total Photos: {total_photos}")


    def find_waypoint(point: Point, previous_point: Point) -> Waypoint | None:
        """Find the waypoint to the given point."""
        for waypoint in waypoints:
            if point.when >= waypoint.when and previous_point.when < waypoint.when and not waypoint.displayed:
                return waypoint
        return None

    output.parent.mkdir(parents=True, exist_ok=True)
    with imageio.get_writer(output, fps=fps, codec="libx264", quality=8, macro_block_size=8) as writer:

        for frame_no in range(frames):
            # Only advance route when not currently displaying a waypoint
            if frames_left_for_photo <= 0:
                progress = route_frame_no / max(1, route_frames - 1)
                eased = 1 - (1 - progress) ** 2

                # Find route point index at given progress (0.0-1.0)
                target = points[-1].distance_m * eased
                lo, hi = 0, len(points) - 1
                while lo < hi:
                    mid = (lo + hi) // 2
                    if points[mid].distance_m < target:
                        lo = mid + 1
                    else:
                        hi = mid
                new_idx = max(1, lo)


                waypoint = find_waypoint(points[new_idx], points[idx])
                if waypoint is not None:
                    active_waypoint = waypoint
                    active_photo_idx = 0
                    frames_left_for_photo = int(fps * photo_delay_seconds * max(1, len(waypoint.photos)))

                idx = new_idx
                route_frame_no = min(route_frame_no + 1, route_frames - 1)

            frame = base.copy().convert("RGBA")
            draw = ImageDraw.Draw(frame)
            if len(route_pixels) > 1:
                draw.line(route_pixels[: idx + 1], fill=(255, 95, 54, 255), width=3, joint="curve")
                draw.line(route_pixels[: idx + 1], fill=(255, 230, 90, 255), width=1, joint="curve")
            # Draw waypoint ellipses for reached waypoints
            for wp_idx, waypoint in enumerate(waypoints):
                if waypoint.displayed and wp_idx < len(waypoint_pixels):
                    wp_marker = waypoint_pixels[wp_idx]
                    draw.ellipse((wp_marker[0] - 10, wp_marker[1] - 10, wp_marker[0] + 10, wp_marker[1] + 10), fill=(255, 255, 255, 255))
                    draw.ellipse((wp_marker[0] - 6, wp_marker[1] - 6, wp_marker[0] + 6, wp_marker[1] + 6), fill=(100, 200, 100, 255))

            marker = route_pixels[idx]
            draw.ellipse((marker[0] - 13, marker[1] - 13, marker[0] + 13, marker[1] + 13), fill=(255, 255, 255, 255))
            draw.ellipse((marker[0] - 8, marker[1] - 8, marker[0] + 8, marker[1] + 8), fill=(255, 95, 54, 255))

            if active_waypoint is not None and frames_left_for_photo > 0:

                # Draw active waypoint with current photo
                frames_per_photo = int(fps * photo_delay_seconds)
                active_photo_idx = (int(fps * photo_delay_seconds * len(active_waypoint.photos)) - frames_left_for_photo) // frames_per_photo

                # Draw event card
                draw = ImageDraw.Draw(frame)
                title_font = default_font(24, bold=True)
                body_font = default_font(18)

                title_text = active_waypoint.name or "Etape"
                description = active_waypoint.description.strip() if active_waypoint.description else ""
                lines = []
                if description:
                    lines = wrap_text_lines(description, max_chars=72)[:6]

                card_x = 20
                card_y = 20
                description_y = card_y + 52 + 26 * len(lines) + card_y
                card_w = min(640, frame.width - 40)
                card_h = min(description_y, frame.height - 170)

                print(f"Event: {title_text} {card_w}x{card_h} {len(lines)} lines")

                draw.rounded_rectangle(
                    (card_x, card_y, card_x + card_w, card_y + card_h),
                    radius=16,
                    fill=(8, 12, 18, 215),
                )

                draw.text((card_x + 16, card_y + 14), title_text, font=title_font, fill=(255, 255, 255, 255))

                if description:
                    y = card_y + 52
                    for line in lines:
                        draw.text((card_x + 16, y), line, font=body_font, fill=(218, 226, 235, 255))
                        y += 26

                # Draw current photo
                if active_waypoint.photos:
                    photo = active_waypoint.photos[active_photo_idx % len(active_waypoint.photos)]
                    draw = ImageDraw.Draw(frame)
                    pad = 16
                    img = photo.image
                    img.thumbnail((frame.height - 170, frame.height - 170), Image.Resampling.LANCZOS)

                    x = frame.width - img.width - 28
                    y = 28

                    print(f"  - Image: {img.width}x{img.height}")

                    draw.rounded_rectangle((x - pad, y - pad, x + img.width + pad, y + img.height + pad), radius=18, fill=(255, 255, 255, 238))
                    frame.paste(img, (x, y))

                frames_left_for_photo -= 1
                if frames_left_for_photo <= 0:
                    active_waypoint.displayed = True
                    active_waypoint = None
            else:
                # No active waypoint — route is advancing, already handled above
                pass

            draw.text((28, height - 104), title, font=font_big, fill=(255, 255, 255, 255))
            km = points[idx].distance_m / 1000
            elapsed = total_seconds * eased
            stats = [
                (f"{km:0.1f} km", "distance"),
                (format_duration(elapsed), "temps"),
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


# ##############################################################################################
# build_map
# ##############################################################################################

def build_map(
    route_points: list[Point],
    width: int,
    height: int,
    zoom: int,
    cache_dir: Path,
    margin: int,
) -> tuple[Image.Image, list[tuple[int, int]], float, float]:
    """Build base map with route points, fetching tiles and compositing.
    
    Args:
        route_points: Points along the route.
        width: Frame width in pixels.
        height: Frame height in pixels.
        zoom: Zoom level.
        cache_dir: Directory for tile caching.
        margin: Margin around route.
        
    Returns:
        Tuple of (base_image, route_pixel_coords, offset_x, offset_y).
    """

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

    return base, pixels, offset_x, offset_y


# ##############################################################################################
# parse_gpx
# ##############################################################################################

def parse_gpx(path: Path, photos_dir: Path | None = None) -> tuple[list[Point], list[Waypoint]]:
    """Parse GPX file and extract route points and waypoint events.
    
    Args:
        path: Path to GPX file.
        photos_dir: Optional directory to search for event photos.
        
    Returns:
        Tuple of (route_points, events_by_coord_dict).
    """
    tree = ET.parse(path)
    root = tree.getroot()

    # Points

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

    # Waypoints

    waypoints: list[Waypoint] = []

    for wpt in wpt_nodes:
        try:
            wpt_lat = float(wpt.attrib["lat"])
            wpt_lon = float(wpt.attrib["lon"])
        except Exception:
            continue

        name = ""
        description = ""
        when = None
        photo_paths: list[Path] = []

        for child in wpt:
            tag = child.tag.split("}", 1)[-1]
            text = (child.text or "").strip()
            if tag == "time":
                when = parse_time(text)
            elif tag == "name":
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
            loaded = load_event_photo(photo_path, caption=None)
            if loaded is not None:
                event_photos.append(loaded)

        waypoint = Waypoint(name=name, description=description, lat=wpt_lat, lon=wpt_lon, when=when, displayed=False, photos=event_photos)

        waypoints.append(waypoint)

    return points, waypoints


# ##############################################################################################
# relive
# ##############################################################################################

def relive(
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
    photo_delay: float = 2.0,
) -> Path:
    """Build a Relive-like animated video from a GPX track.
    
    Main entry point for creating animated route videos with waypoint events.
    
    Args:
        gpx: Path to GPX file.
        output: Output MP4 file path (default: gpx_stem.mp4).
        photos: Directory containing waypoint photos.
        title: Video title (default: GPX file stem).
        width: Video width in pixels (default 800).
        height: Video height in pixels (default 800).
        fps: Frames per second (default 24).
        duration: Video duration in seconds (default 45).
        zoom: Map zoom level (default: auto).
        tile_cache: Directory for caching map tiles (default: .tile-cache).
        photo_delay: Seconds to display each photo (default 2.0).
        
    Returns:
        Path to created MP4 file.
    """

    # ensure_dependencies()

    gpx_path = Path(gpx)
    output_path = Path(output) if output is not None else Path(f"{slug_from_path(gpx_path)}.mp4")
    photos_path = Path(photos) if photos is not None else None
    tile_cache_path = Path(tile_cache)

    points, waypoints = parse_gpx(gpx_path, photos_dir=photos_path)
    zoom_level = zoom or choose_zoom(points, width, height, margin=60)
    video_title = title or gpx_path.stem.replace("_", " ").replace("-", " ").title()

    print(f"Loaded {len(points)} route points, zoom {zoom_level}, {len(waypoints)} waypoint(s).")
    base, route_pixels, offset_x, offset_y = build_map(points, width, height, zoom_level, tile_cache_path, margin=60)

    # Calculate waypoint pixel coordinates
    waypoint_pixels = []
    for waypoint in waypoints:
        wp_x, wp_y = lonlat_to_world(waypoint.lon, waypoint.lat, zoom_level)
        waypoint_pixels.append((int(wp_x - offset_x), int(wp_y - offset_y)))

    render_video(points, base, route_pixels, waypoints, output_path, video_title, fps, duration, photo_delay_seconds=photo_delay, waypoint_pixels=waypoint_pixels)
    print(f"Video created: {output_path}")
    return output_path
