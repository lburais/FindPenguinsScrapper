"""! @file fp_writers.py
@brief Serialization helpers for trip GPX files and global user XML index.

Writers in this module preserve user-requested schema semantics including
metadata extensions, waypoint ordering, and indentation style.
"""

from datetime import date, timedelta
from io import BytesIO
import os
import re
import requests
import shutil
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlparse
from functools import lru_cache
from math import radians, sin, cos, sqrt, atan2, isfinite

from fp_config import GPX_NS, XSI_NS
from fp_utils import gpx_tag, add_text_element, format_tree, to_webp, make_variant, shrink_image, strip_leading_flag
from fp_elevation import fetch_elevations


def _add_companion(parent, companion):
    """! @brief Append a `<companion>` element with `uid`, `name` and `picture` sub-elements.
    @param parent Parent XML element.
    @param companion Companion dictionary.
    @return None
    """
    companion_el = ET.SubElement(parent, "companion")
    for key in ("uid", "name", "picture"):
        add_text_element(companion_el, key, companion.get(key, ""), namespace=None)


TRIP_DETAIL_KEYS = ["description", "countries", "distance", "transports"]


def _add_trip_details(parent, trip):
    """! @brief Append countries, distance and transports elements of a trip.
    @param parent Parent XML element.
    @param trip Trip dictionary (missing fields are skipped).
    @return None
    """
    countries = trip.get("countries") or []
    if countries:
        countries_el = ET.SubElement(parent, "countries")
        for country in countries:
            country_el = ET.SubElement(countries_el, "country")
            for key in ("name", "flag"):
                add_text_element(country_el, key, country.get(key, ""), namespace=None)
    add_text_element(parent, "distance", trip.get("distance", ""), namespace=None)
    transports = trip.get("transports") or []
    if transports:
        transports_el = ET.SubElement(parent, "transports")
        for transport in transports:
            transport_el = ET.SubElement(transports_el, "transport")
            add_text_element(transport_el, "name", transport.get("name", ""), namespace=None)
            add_text_element(transport_el, "distance", transport.get("distance", ""), namespace=None)


def distance_meters(lat1, lon1, lat2, lon2):
    """! @brief Compute great-circle distance between two coordinates in meters.
    @param lat1 First latitude.
    @param lon1 First longitude.
    @param lat2 Second latitude.
    @param lon2 Second longitude.
    @return Distance in meters.
    """
    earth_radius = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * earth_radius * atan2(sqrt(a), sqrt(1 - a))


def find_closest_trackpoint(waypoint, track_points):
    """! @brief Find nearest track point for one waypoint.
    @param waypoint GPX waypoint element.
    @param track_points Track point dictionaries with lat/lon/time.
    @return Closest track point dictionary or None when unavailable.
    """
    if not track_points:
        return None

    lat = waypoint.get("lat")
    lon = waypoint.get("lon")
    if lat is None or lon is None:
        return None

    try:
        wlat = float(lat)
        wlon = float(lon)
    except ValueError:
        return None

    closest = None
    min_distance = float("inf")
    for point in track_points:
        distance = distance_meters(wlat, wlon, point["lat"], point["lon"])
        if distance < min_distance:
            min_distance = distance
            closest = point

    return closest


def footprint_to_waypoint(footprint):
    """! @brief Convert one footprint dictionary into a GPX waypoint element.
    @param footprint Normalized footprint data.
    @return GPX wpt element or None when coordinates are missing.
    """

    lat = str(footprint.get("lat", "")).strip()
    lon = str(footprint.get("lon", "")).strip()
    if not lat or not lon:
        return None

    waypoint = ET.Element(gpx_tag("wpt"), lat=lat, lon=lon)
    add_text_element(waypoint, "name", footprint.get("title", ""))
    add_text_element(waypoint, "desc", footprint.get("text", ""))
    add_text_element(waypoint, "ele", footprint.get("altitude", ""))
    waypoint_url = str(footprint.get("url", "")).strip()
    if waypoint_url:
        ET.SubElement(waypoint, gpx_tag("link"), href=waypoint_url)

    extensions_data = {
        "date": footprint.get("date", ""),
        "day": footprint.get("day", ""),
        "weather": footprint.get("weather", ""),
        "temperature": footprint.get("temperature", ""),
        "overnights": footprint.get("overnights", ""),
        "flag": footprint.get("flag", ""),
        "country": footprint.get("country", ""),
        "city": footprint.get("city", ""),
        "text-private": footprint.get("text-private", ""),
    }

    if any(value for value in extensions_data.values()) or footprint.get("references") or footprint.get("photos") or footprint.get("videos") or footprint.get("gpx") or footprint.get("pdf"):
        extensions = ET.SubElement(waypoint, gpx_tag("extensions"))

        for key, value in extensions_data.items():
            add_text_element(extensions, key, value, namespace=None)

        for search_text, url in footprint.get("references", []):
            reference = ET.SubElement(extensions, "reference")
            add_text_element(reference, "search", search_text, namespace=None)
            add_text_element(reference, "url", url, namespace=None)

        if footprint.get("photos"):
            for photo in footprint.get("photos", []):
                add_text_element(extensions, "photo", photo, namespace=None)

        for video in footprint.get("videos", []):
            add_text_element(extensions, "video", video, namespace=None)

        for gpx_file in footprint.get("gpx", []):
            add_text_element(extensions, "gpx", gpx_file, namespace=None)

        for pdf_file in footprint.get("pdf", []):
            add_text_element(extensions, "pdf", pdf_file, namespace=None)

    return waypoint


def build_trip_gpx(gpx_path, user_data, trip, footprints):
    """! @brief Build or update one trip GPX with metadata and footprint waypoints.
    @param gpx_path Output GPX file path.
    @param user_data Dictionary of profile-level fields.
    @param trip Dictionary describing one trip.
    @param footprints List of trip footprint dictionaries.
    @return None
    """

    print(f"  - Building GPX [{gpx_path}]...")

    ET.register_namespace("", GPX_NS)
    ET.register_namespace("xsi", XSI_NS)

    if os.path.exists(gpx_path):
        tree = ET.parse(gpx_path)
        root = tree.getroot()
    else:
        root = ET.Element(
            gpx_tag("gpx"),
            attrib={
                "version": "1.1",
                "creator": "FindPenguins",
                f"{{{XSI_NS}}}schemaLocation": f"{GPX_NS} {GPX_NS}/gpx.xsd",
            },
        )
        tree = ET.ElementTree(root)

    metadata = root.find(gpx_tag("metadata"))
    if metadata is None:
        metadata = ET.Element(gpx_tag("metadata"))
        root.insert(0, metadata)
    else:
        for child in list(metadata.findall(gpx_tag("extensions"))):
            metadata.remove(child)

    for waypoint in list(root.findall(gpx_tag("wpt"))):
        root.remove(waypoint)

    if not os.path.exists(gpx_path):
        add_text_element(metadata, "name", trip.get("title", ""))
        add_text_element(metadata, "desc", trip.get("period", ""))

    trip_url = trip.get("url", "")
    path_parts = urlparse(trip_url).path.strip("/").split("/") if trip_url else []
    author_uid = path_parts[0] if path_parts else user_data.get("name", "")

    # Ensure metadata author section contains profile name/email/website.
    for author in list(metadata.findall(gpx_tag("author"))):
        metadata.remove(author)
    author = ET.SubElement(metadata, gpx_tag("author"))
    add_text_element(author, "name", user_data.get("name", ""))
    add_text_element(author, "email", user_data.get("email", ""))
    if user_data.get("website", ""):
        ET.SubElement(author, gpx_tag("link"), href=user_data["website"])

    # Keep uid only in metadata extensions and trip url as metadata link.
    for uid in list(metadata.findall("uid")):
        metadata.remove(uid)

    metadata_link = metadata.find(gpx_tag("link"))
    if trip_url:
        if metadata_link is None:
            metadata_link = ET.SubElement(metadata, gpx_tag("link"))
        metadata_link.set("href", trip_url)
    elif metadata_link is not None:
        metadata.remove(metadata_link)

    trip_meta = metadata.find(gpx_tag("extensions"))
    if trip_meta is None:
        trip_meta = ET.SubElement(metadata, gpx_tag("extensions"))

    trip_dates = []
    for footprint in footprints:
        try:
            trip_dates.append(date.fromisoformat(str(footprint.get("date", "")).strip()[:10]))
        except ValueError:
            continue
    start_date = min(trip_dates).isoformat() if trip_dates else ""
    if start_date:
        add_text_element(trip_meta, "start_date", start_date, namespace=None)

    for key, value in trip.items():
        if key in [
            "title",
            "companions",
            "footprints",
            "gpx",
            "period",
            "km",
            "is_current",
            "url",
            "route_map",
            "satellite_map",
        ] + TRIP_DETAIL_KEYS:
            continue
        print(f"    - trip[{key}] : {value}")
        add_text_element(trip_meta, key, value, namespace=None)

    add_text_element(trip_meta, "uid", author_uid, namespace=None)
    _add_trip_details(trip_meta, trip)

    for companion in trip.get("companions", []):
        if not str(companion.get("uid", "")).strip():
            continue
        print(f"    - companion[uid] : {companion.get('uid')}")
        _add_companion(trip_meta, companion)

    waypoints = []
    for footprint in footprints:
        waypoint = footprint_to_waypoint(footprint)
        if waypoint is None:
            continue

        print(f"    - waypoint[{footprint.get('title', '')}] : {footprint.get('lat', '')}, {footprint.get('lon', '')}")
        waypoints.append(waypoint)

    track_elements = list(root.findall(gpx_tag("trk")))

    track_points = []
    track_point_elements = []
    for track_element in track_elements:
        for track_point in track_element.findall(f".//{gpx_tag('trkpt')}"):
            lat = track_point.get("lat")
            lon = track_point.get("lon")
            if lat is None or lon is None:
                continue
            try:
                point = {
                    "lat": float(lat),
                    "lon": float(lon),
                    "time": (track_point.findtext(gpx_tag("time")) or "").strip(),
                    "ele": None,
                }
            except ValueError:
                continue
            track_points.append(point)
            track_point_elements.append(track_point)

    if track_points:
        try:
            fetch_elevations(track_points)
            for point, track_point in zip(track_points, track_point_elements):
                track_elevation = point.get("ele")
                if track_elevation is None:
                    continue
                ele_node = track_point.find(gpx_tag("ele"))
                if ele_node is None:
                    ele_node = ET.SubElement(track_point, gpx_tag("ele"))
                ele_node.text = str(track_elevation)
        except Exception as exc:
            print(f"  - WARNING: unable to enrich trkpt elevations: {exc}")

    for waypoint in waypoints:
        closest = find_closest_trackpoint(waypoint, track_points)
        if not closest:
            continue

        if closest.get("time"):
            waypoint_time = waypoint.find(gpx_tag("time"))
            if waypoint_time is None:
                waypoint_time = ET.SubElement(waypoint, gpx_tag("time"))
            waypoint_time.text = closest["time"]

        waypoint_extensions = waypoint.find(gpx_tag("extensions"))
        if waypoint_extensions is None:
            waypoint_extensions = ET.SubElement(waypoint, gpx_tag("extensions"))

        ET.SubElement(
            waypoint_extensions,
            "point",
            lat=f"{closest['lat']:.6f}",
            lon=f"{closest['lon']:.6f}",
        )

    for track_element in track_elements:
        root.remove(track_element)

    for waypoint in waypoints:
        root.append(waypoint)

    for track_element in track_elements:
        root.append(track_element)

    format_tree(tree)
    tree.write(gpx_path, encoding="utf-8", xml_declaration=True)


def build_user_xml(user_data, trips):
    """! @brief Build user-level XML index with per-trip GPX references.
    @param user_data Dictionary of profile-level fields.
    @param trips List of trip dictionaries.
    @return Formatted ElementTree ready for writing.
    """

    print("  - Building user XML...")

    root = ET.Element("profile")

    # Flatten user fields directly under profile.
    user_order = ["uid", "name", "bio", "location", "website", "picture"]
    for key in user_order:
        if key in user_data:
            value = user_data.get(key, "")
            print(f"    - user[{key}] : {value}")
            add_text_element(root, key, value, namespace=None)

    for key, value in user_data.items():
        if key in user_order:
            continue
        print(f"    - user[{key}] : {value}")
        add_text_element(root, key, value, namespace=None)

    trips_el = ET.SubElement(root, "trips")
    for trip in trips:
        trip_el = ET.SubElement(trips_el, "trip")
        for key, value in trip.items():
            if key in ["companions", "footprints", "gpx", "period", "km", "is_current", "route_map", "satellite_map"] + TRIP_DETAIL_KEYS:
                continue
            print(f"    - trip[{key}] : {value}")
            add_text_element(trip_el, key, value, namespace=None)

        gpx_ref = ET.SubElement(trip_el, "gpx")
        gpx_ref.text = trip.get("gpx", "")

        for companion in trip.get("companions", []):
            print(f"    - companion[uid] : {companion.get('uid', '')}")
            _add_companion(trip_el, companion)

    tree = ET.ElementTree(root)
    return format_tree(tree)


HTML_CSS = """
:root { --bg-color: #fcfbf9; --text-color: #2c2c2c; --primary-color: #1a365d; --meta-color: #718096; --border-color: #e2e8f0; }
body { font-family: 'Georgia', serif; background-color: var(--bg-color); color: var(--text-color); line-height: 1.7; margin: 0; padding: 0; }
.container { max-width: 800px; margin: 0 auto; padding: 40px 20px; }
header { border-bottom: 1px solid var(--border-color); padding-bottom: 20px; margin-bottom: 30px; }
h1, h2, h3 { font-family: 'Helvetica Neue', Arial, sans-serif; color: var(--primary-color); font-weight: 300; }
.meta-badge-container { display: flex; gap: 15px; font-family: Arial, sans-serif; font-size: 0.85rem; color: var(--meta-color); margin-bottom: 20px; flex-wrap: wrap; }
.badge { background: #edf2f7; padding: 4px 10px; border-radius: 4px; }
.map-container { width: 100%; height: 300px; margin-bottom: 30px; border-radius: 6px; border: 1px solid var(--border-color); }
.story-text { font-size: 1.15rem; text-align: justify; margin-bottom: 30px; white-space: pre-wrap; }
.video-container { margin: 30px 0; text-align: center; }
.video-container video { width: 100%; max-height: 450px; border-radius: 4px; background: #000; }
.photo-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-top: 30px; }
.photo-card img { width: 100%; height: auto; border-radius: 2px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
.nav-links { margin-top: 50px; padding-top: 20px; border-top: 1px solid var(--border-color); display: flex; justify-content: space-between; font-family: Arial, sans-serif; }
.step-number { font-family: Arial; font-weight: bold; text-transform: uppercase; color: var(--meta-color); font-size: 0.9rem; }
.avatar { width: 96px; height: 96px; border-radius: 50%; object-fit: cover; }
a { color: var(--primary-color); text-decoration: none; }
a:hover { text-decoration: underline; }
"""


def _write_rst(path, content):
    """! @brief Write a reStructuredText document, creating parent folders."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _references_by_search(references):
    """! @brief Return case-insensitive search text keys mapped to labels and URLs."""
    result = {}
    for search_text, url in references:
        search_text = str(search_text or "")
        url = str(url or "").strip()
        if search_text and url.lower().startswith(("http://", "https://")):
            result.setdefault(search_text.casefold(), (search_text, url))
    return result


def _encode_url(url):
    """Encode URL characters that are not safe in an ASCII URL."""
    return quote(str(url or ""), safe=":/?#[]@!$&()*+,;=%").replace("_", "%5F")


def _copy_media(media_paths, destination_dir):
    """! @brief Copy media into a document folder and return relative paths."""
    os.makedirs(destination_dir, exist_ok=True)
    copied_paths = []
    for media_path in media_paths:
        destination_path = os.path.join(destination_dir, os.path.basename(media_path))
        shutil.copy2(media_path, destination_path)
        copied_paths.append(os.path.basename(destination_path).replace(" ", "%20"))
    return copied_paths


def _copy_image(image_path, destination_dir, sizes, variants):
    """! @brief Copy an image and create its size variants next to the copy.
    @param image_path Source image path.
    @param destination_dir Destination folder.
    @param sizes Mapping of size name ("small", "large") to maximum pixel size.
    @param variants Mapping of variant suffix to the size name it uses.
    @return Tuple (original file name, {suffix: variant file name}).
    """
    name = _copy_media([image_path], destination_dir)[0]
    copied_path = os.path.join(destination_dir, os.path.basename(image_path))
    created = {
        suffix: os.path.basename(make_variant(copied_path, suffix, sizes[size])).replace(" ", "%20")
        for suffix, size in variants.items()
    }
    return name, created


@lru_cache(maxsize=1)
def _load_country_boundaries():
    """! @brief Load and cache Natural Earth country boundaries."""
    import geopandas as gpd

    return gpd.read_file(
        "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
    )


def save_full_country_map(lat, lon, padding_ratio=0.1, output_image="map_country.png"):
    """! @brief Save a static map of the country or region containing a footprint.
    @param lat Footprint latitude.
    @param lon Footprint longitude.
    @param padding_ratio Proportional margin around the country bounds.
    @param output_image Destination image path.
    @return Destination image path, or None if the coordinates are not in a country.
    """
    import geopandas as gpd
    import matplotlib.pyplot as plt
    from shapely.geometry import Point

    lat = float(lat)
    lon = float(lon)
    padding_ratio = float(padding_ratio)
    if not isfinite(lat) or not isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError(f"Invalid coordinates for country map: ({lat}, {lon})")
    if not isfinite(padding_ratio) or padding_ratio < 0:
        raise ValueError("padding_ratio must be non-negative")

    target_point = Point(lon, lat)
    world = _load_country_boundaries()
    if world.crs is None:
        raise ValueError("Country boundary dataset has no coordinate reference system")

    point_in_world_crs = gpd.GeoSeries(
        [target_point], crs="EPSG:4326"
    ).to_crs(world.crs).iloc[0]
    matches = world.loc[world.geometry.contains(point_in_world_crs)]
    if matches.empty:
        projected_world = world.to_crs(epsg=3857)
        projected_point = gpd.GeoSeries(
            [target_point], crs="EPSG:4326"
        ).to_crs(epsg=3857).iloc[0]
        distances = projected_world.geometry.distance(projected_point)
        nearest_index = distances.idxmin()
        if distances.loc[nearest_index] > 10_000:
            print(f"  - WARNING: no country found for footprint coordinates ({lat}, {lon})")
            return None
        matches = world.loc[[nearest_index]]

    country = matches.iloc[[0]].copy()
    country_geometry = country.geometry.iloc[0]
    if country_geometry.geom_type == "MultiPolygon":
        polygons = list(country_geometry.geoms)
        selected_polygon = next(
            (polygon for polygon in polygons if polygon.contains(point_in_world_crs)),
            None,
        )
        if selected_polygon is None:
            selected_polygon = min(
                polygons, key=lambda polygon: polygon.distance(point_in_world_crs)
            )
        country = country.set_geometry(
            gpd.GeoSeries(
                [selected_polygon], index=country.index, crs=world.crs
            )
        )

    country_mercator = country.to_crs(epsg=3857)
    point_mercator = gpd.GeoSeries(
        [target_point], crs="EPSG:4326"
    ).to_crs(epsg=3857).iloc[0]
    xmin, ymin, xmax, ymax = country_mercator.total_bounds
    padding_x = (xmax - xmin) * padding_ratio
    padding_y = (ymax - ymin) * padding_ratio

    output_dir = os.path.dirname(os.path.abspath(output_image))
    os.makedirs(output_dir, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 10), facecolor="none")
    try:
        ax.set_facecolor("none")
        country_mercator.plot(
            ax=ax,
            edgecolor="#404040",
            facecolor="#d3d3d3",
            linewidth=1.2,
            zorder=2,
        )
        ax.scatter(
            point_mercator.x,
            point_mercator.y,
            facecolor="white",
            edgecolor="#0098d8",
            linewidth=4,
            s=1350,
            zorder=5,
        )
        ax.scatter(
            point_mercator.x,
            point_mercator.y,
            facecolor="#0098d8",
            edgecolor="white",
            linewidth=2,
            s=500,
            zorder=6,
        )
        ax.set_xlim(xmin - padding_x, xmax + padding_x)
        ax.set_ylim(ymin - padding_y, ymax + padding_y)
        ax.set_axis_off()
        fig.savefig(
            output_image,
            bbox_inches="tight",
            dpi=300,
            pad_inches=0.1,
            transparent=True,
        )
    finally:
        plt.close(fig)

    country_name = next(
        (
            str(country.iloc[0][column])
            for column in ("NAME", "ADMIN", "NAME_EN")
            if column in country.columns and country.iloc[0][column]
        ),
        "unknown",
    )
    output_image = to_webp(output_image)
    print(f"  - Saved country map for {country_name}: {output_image}")
    return output_image


def _mercator_coordinates(lon, lat):
    """! @brief Project longitude/latitude to Web Mercator meters."""
    import math

    lat = max(min(float(lat), 85.05112878), -85.05112878)
    x = 6378137.0 * math.radians(float(lon))
    y = 6378137.0 * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def save_trip_route_map(
    gpx_path,
    footprints,
    output_image,
    background="transparent",
    show_footprint_bubbles=False,
):
    """! @brief Save a route map with an optional background and footprint bubbles.
    @param gpx_path GPX containing the trip route track.
    @param footprints Footprints to mark on the map.
    @param output_image Destination image path.
    @param background Map background: transparent, satellite, or street.
    @param show_footprint_bubbles Whether to draw numbered footprint markers.
    @return Destination image path, or None when no route track/footprints exist.
    """
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    if background not in {"transparent", "satellite", "street"}:
        raise ValueError(
            "background must be one of: transparent, satellite, street"
        )
    if os.path.splitext(output_image)[1].lower() != ".png":
        raise ValueError("trip route maps must be saved as PNG images")

    if not os.path.isfile(gpx_path):
        print(f"  - WARNING: route map skipped; GPX file not found: {gpx_path}")
        return None

    root = ET.parse(gpx_path).getroot()
    track_segments = []
    for track in root.findall(gpx_tag("trk")):
        for segment in track.findall(gpx_tag("trkseg")):
            points = []
            for track_point in segment.findall(gpx_tag("trkpt")):
                try:
                    lat = float(track_point.get("lat", ""))
                    lon = float(track_point.get("lon", ""))
                except ValueError:
                    continue
                if isfinite(lat) and isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                    points.append((lon, lat))
            if points:
                track_segments.append(points)

    if not track_segments:
        print(f"  - WARNING: route map skipped; GPX has no valid track points: {gpx_path}")
        return None

    footprint_points = []
    for index, footprint in enumerate(footprints, start=1):
        try:
            lat = float(footprint.get("lat", ""))
            lon = float(footprint.get("lon", ""))
        except (TypeError, ValueError):
            continue
        if isfinite(lat) and isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            footprint_points.append((index, lon, lat))

    all_points = [point for segment in track_segments for point in segment]
    if show_footprint_bubbles:
        all_points.extend((lon, lat) for _, lon, lat in footprint_points)
    projected = [_mercator_coordinates(lon, lat) for lon, lat in all_points]
    xs, ys = zip(*projected)
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    width = max(xmax - xmin, 500)
    height = max(ymax - ymin, 500)
    padding_x = width * 0.08
    padding_y = height * 0.08
    xmin, xmax = xmin - padding_x, xmax + padding_x
    ymin, ymax = ymin - padding_y, ymax + padding_y

    image_width, image_height = 1200, 800
    target_aspect = image_width / image_height
    bounds_aspect = (xmax - xmin) / (ymax - ymin)
    if bounds_aspect < target_aspect:
        extra_width = (ymax - ymin) * target_aspect - (xmax - xmin)
        xmin -= extra_width / 2
        xmax += extra_width / 2
    else:
        extra_height = (xmax - xmin) / target_aspect - (ymax - ymin)
        ymin -= extra_height / 2
        ymax += extra_height / 2

    map_image = None
    if background != "transparent":
        service = (
            "World_Imagery" if background == "satellite" else "World_Street_Map"
        )
        response = requests.get(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            f"{service}/MapServer/export",
            params={
                "bbox": f"{xmin},{ymin},{xmax},{ymax}",
                "bboxSR": 3857,
                "imageSR": 3857,
                "size": f"{image_width},{image_height}",
                "format": "png32",
                "transparent": "false",
                "f": "image",
            },
            timeout=45,
        )
        response.raise_for_status()
        map_image = mpimg.imread(BytesIO(response.content), format="png")

    output_dir = os.path.dirname(os.path.abspath(output_image))
    os.makedirs(output_dir, exist_ok=True)
    transparent = background == "transparent"
    fig, ax = plt.subplots(figsize=(12, 8), dpi=100, facecolor="none" if transparent else "white")
    try:
        ax.set_facecolor("none" if transparent else "white")
        if map_image is not None:
            ax.imshow(
                map_image,
                extent=(xmin, xmax, ymin, ymax),
                origin="upper",
                aspect="auto",
                zorder=0,
            )
        for segment in track_segments:
            route_x, route_y = zip(*(_mercator_coordinates(lon, lat) for lon, lat in segment))
            ax.plot(route_x, route_y, color="white", linewidth=4, zorder=3)

        if show_footprint_bubbles:
            for number, lon, lat in footprint_points:
                x, y = _mercator_coordinates(lon, lat)
                ax.scatter(
                    x,
                    y,
                    s=260,
                    marker="o",
                    facecolor="#f8fbff",
                    edgecolor="#073b70",
                    linewidth=2.5,
                    zorder=4,
                )
                ax.annotate(
                    str(number),
                    (x, y),
                    ha="center",
                    va="center",
                    color="#073b70",
                    fontsize=8,
                    fontweight="bold",
                    zorder=5,
                )

        if background != "transparent":
            attribution = (
                "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community"
                if background == "satellite"
                else "Map data © Esri"
            )
            ax.text(
                0.99,
                0.015,
                attribution,
                transform=ax.transAxes,
                ha="right",
                va="bottom",
                color="white" if background == "satellite" else "#333",
                fontsize=6,
                bbox={
                    "facecolor": "black" if background == "satellite" else "white",
                    "alpha": 0.6,
                    "pad": 3,
                    "edgecolor": "none",
                },
                zorder=6,
            )
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_axis_off()
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        fig.savefig(
            output_image,
            dpi=100,
            bbox_inches=None,
            pad_inches=0,
            transparent=transparent,
            pil_kwargs={"optimize": True},
        )
    finally:
        plt.close(fig)

    stale_marker_path = os.path.splitext(output_image)[0] + ".json"
    if os.path.isfile(stale_marker_path):
        os.remove(stale_marker_path)

    output_image = to_webp(output_image)
    print(f"  - Saved {background} route map: {output_image}")
    return output_image


def _footprint_gpx_fields(footprint, footprint_dir, sizes, trip_days=""):
    """! @brief Map a footprint to the GPX waypoint fields used as Pelican metadata.
    Every exported metadata field except `desc` (the footprint text, used as page body)
    is returned. The map image is saved in the footprint directory.
    Media are copied into the footprint folder and listed by file name.
    @param footprint Normalized footprint data.
    @param footprint_dir Destination folder of the generated page.
    @param sizes Maximum pixel size of the "small" and "large" image variants.
    @return Dictionary of metadata name -> value.
    """
    references = ", ".join(
        f"{search_text}|{_encode_url(url)}" if search_text else _encode_url(url)
        for search_text, url in footprint.get("references", [])
    )
    lat = str(footprint.get("lat", "")).strip()
    lon = str(footprint.get("lon", "")).strip()
    if lat and lon:
        country_map = save_full_country_map(
            lat,
            lon,
            output_image=os.path.join(footprint_dir, "map_country.png"),
        )
        shrink_image(country_map, sizes["large"])

    photos = []
    for photo in footprint.get("photos", []):
        name, _ = _copy_image(photo, footprint_dir, sizes, {"thumb": "large"})
        photos.append(name)

    return {
        "Lat": footprint.get("lat", ""),
        "Lon": footprint.get("lon", ""),
        "Ele": footprint.get("altitude", ""),
        "Link": footprint.get("url", ""),
        "Day": footprint.get("day", ""),
        "Days": trip_days,
        "Weather": footprint.get("weather", ""),
        "Temperature": footprint.get("temperature", ""),
        "Overnights": footprint.get("overnights", ""),
        "Flag": footprint.get("flag", ""),
        "Country": footprint.get("country", ""),
        "City": footprint.get("city", ""),
        "Text-private": footprint.get("text-private", ""),
        "Reference": references,
        "Photo": ", ".join(photos),
        "Video": ", ".join(_copy_media(footprint.get("videos", []), footprint_dir)),
        "Gpx": ", ".join(_copy_media(footprint.get("gpx", []), footprint_dir)),
        "Pdf": ", ".join(_copy_media(footprint.get("pdf", []), footprint_dir)),
    }


def _rst_text(value):
    """! @brief Escape plain text for reStructuredText."""
    return re.sub(r"([\\`*_|])", r"\\\1", str(value or ""))


def _rst_metadata(**fields):
    """! @brief Format Pelican metadata as a reStructuredText field list."""
    return "\n".join(
        f":{name}: {' '.join(str(value or '').split())}"
        for name, value in fields.items()
        if value not in (None, "")
    )


def _rst_heading(text, underline="="):
    """! @brief Format a reStructuredText section heading."""
    title = _rst_text(text)
    return f"{title}\n{underline * max(len(title), 1)}"


def _text_with_rst_references(text, references):
    """! @brief Replace reference labels case-insensitively with RST links."""
    text = str(text or "")
    references_by_search = _references_by_search(references)
    if not references_by_search:
        return _rst_text(text)

    labels = [
        label
        for label, _ in sorted(
            references_by_search.values(), key=lambda item: len(item[0]), reverse=True
        )
    ]
    pattern = re.compile(
        "|".join(re.escape(label) for label in labels), flags=re.IGNORECASE
    )
    parts = []
    last_end = 0
    for match in pattern.finditer(text):
        parts.append(_rst_text(text[last_end:match.start()]))
        search_text, url = references_by_search[match.group(0).casefold()]
        escaped_url = _encode_url(url).replace(">", "%3E")
        parts.append(f"`{_rst_text(search_text)} <{escaped_url}>`_")
        last_end = match.end()
    parts.append(_rst_text(text[last_end:]))
    return "".join(parts)


def _trip_date_range(footprints):
    """! @brief Return ISO start and end dates of a trip from its footprints.
    The end date is the latest footprint date plus its overnights. Empty strings
    are returned when no footprint has a valid date.
    """
    starts, ends = [], []
    for footprint in footprints:
        try:
            day = date.fromisoformat(str(footprint.get("date", "")).strip()[:10])
        except ValueError:
            continue
        try:
            nights = int(footprint.get("overnights") or 0)
        except (TypeError, ValueError):
            nights = 0
        starts.append(day)
        ends.append(day + timedelta(days=max(nights, 0)))
    if not starts:
        return "", ""
    return min(starts).isoformat(), max(ends).isoformat()


def build_trip_rst(content_dir, trip_dir, user_data, trip, footprints, sizes):
    """! @brief Build Pelican articles (reStructuredText) for a trip and its footprints.
    @param content_dir Pelican articles source directory.
    @param sizes Maximum pixel size of the "small" and "large" image variants.
    Originals are copied next to their variants; the metadata references the variants
    (`_thumb` for photos). Companion pictures, the trip cover, trip maps and country maps are shrunk in place
    (the cover keeps its name, without any `_large` suffix).
    """
    uid = str(user_data.get("uid", "")).strip()
    trip_slug = str(trip.get("slug", "")).strip()
    trip_title = strip_leading_flag(trip.get("title") or trip_slug)
    rst_trip_dir = os.path.join(content_dir, uid, trip_slug)
    print(f"  - Building trip reStructuredText [{rst_trip_dir}]...")

    profile_dir = os.path.dirname(trip_dir)
    trip_image = ""
    if trip.get("image"):
        image_path = str(trip["image"])
        if not image_path.startswith(("http://", "https://")):
            image_path = os.path.join(profile_dir, image_path)
            trip_image = _copy_media([image_path], rst_trip_dir)[0]
            shrink_image(os.path.join(rst_trip_dir, os.path.basename(image_path)), sizes["large"])
        else:
            trip_image = image_path

    maps = {}
    for key in ("route_map", "satellite_map"):
        map_path = str(trip.get(key) or "").strip()
        if map_path:
            if not os.path.isabs(map_path):
                map_path = os.path.join(profile_dir, map_path)
            maps[key] = _copy_media([map_path], rst_trip_dir)[0]
            shrink_image(os.path.join(rst_trip_dir, os.path.basename(map_path)), sizes["large"])

    companion_images = []
    for companion in trip.get("companions") or []:
        picture = str(companion.get("picture") or companion.get("avatar") or "").strip()
        if not picture:
            continue
        if not picture.startswith(("http://", "https://")):
            # The companion is represented by its profile picture, stored once under its profile folder.
            companion_dir = os.path.join(content_dir, str(companion.get("uid") or uid).strip())
            picture_path = os.path.normpath(os.path.join(profile_dir, picture))
            name_on_disk = _copy_media([picture_path], companion_dir)[0].replace("%20", " ")
            small_path = shrink_image(os.path.join(companion_dir, name_on_disk), sizes["small"])
            picture = os.path.relpath(small_path, rst_trip_dir).replace(os.sep, "/").replace(" ", "%20")
        name = str(companion.get("name") or companion.get("uid") or "").strip()
        companion_images.append(f"{name}|{picture}")

    countries = ", ".join(str(country.get("name", "")).strip() for country in trip.get("countries") or [])
    country_flags = ";".join(
        f"{str(country.get('name', '')).strip()}|{str(country.get('flag', '')).strip()}"
        for country in trip.get("countries") or []
    )
    flags = {country.get("flag", "") for country in trip.get("countries") or []}
    flags.update(footprint.get("flag", "") for footprint in footprints)
    for flag in flags:
        if flag and flag.startswith("flags/"):
            flag_path = os.path.join(os.path.dirname(profile_dir), flag)
            _copy_media([flag_path], os.path.join(content_dir, "flags"))
    trip_tags = ["findpenguins", "trip"]
    known_tags = {tag.casefold() for tag in trip_tags}
    insight_tags = [
        str(country.get("name", "")).strip()
        for country in trip.get("countries") or []
    ]
    transport_details = []
    for transport in trip.get("transports") or []:
        name = str(transport.get("name", "")).strip()
        distance = str(transport.get("distance", "")).strip()
        detail = f"{name} {distance} km".strip() if distance else name
        if detail:
            transport_details.append(detail)
    for tag in insight_tags:
        if tag and tag.casefold() not in known_tags:
            trip_tags.append(tag)
            known_tags.add(tag.casefold())
    start_date, end_date = _trip_date_range(footprints)
    chapters = [
        _rst_metadata(
            Title=trip_title,
            Date=start_date,
            EndDate=end_date,
            Slug=f"{uid}-{trip_slug}",
            Category="findpenguins",
            Template="findpenguins_trip",
            Tags=", ".join(trip_tags),
            Transport="; ".join(transport_details),
            Summary=trip.get("description") or trip.get("period", ""),
            Days=trip.get("days", ""),
            Period=trip.get("period", ""),
            Distance=trip.get("distance") or trip.get("km", ""),
            Countries=countries,
            CountryFlags=country_flags,
            Description=trip.get("description", ""),
            Owner=user_data.get("name") or uid,
            TripImage=trip_image,
            TripMap=maps.get("route_map", ""),
            TripSatelliteMap=maps.get("satellite_map", ""),
            Companions=";".join(companion_images),
        ),
    ]
    _write_rst(os.path.join(rst_trip_dir, "trip.rst"), "\n".join(chapters))

    for index, footprint in enumerate(footprints, start=1):
        footprint_dir = os.path.join(rst_trip_dir, f"footprint_{index}")
        title = str(footprint.get("title") or f"Étape {index}").strip()
        city = str(footprint.get("city", "")).strip()
        country = str(footprint.get("country", "")).strip()
        location = ", ".join(part for part in (city, country) if part)
        text = str(footprint.get("text", "")).strip()
        content = [
            _rst_metadata(
                Title=title,
                Date=footprint.get("date", ""),
                Slug=f"{uid}-{trip_slug}-etape-{index}",
                Category="footprint",
                Tags=", ".join(part for part in ("findpenguins", "footprint", country) if part),
                Summary=location or footprint.get("weather", ""),
                **_footprint_gpx_fields(footprint, footprint_dir, sizes, trip.get("days", "")),
            ),
            "",
            _text_with_rst_references(text, footprint.get("references", [])),
            "",
        ]
        _write_rst(os.path.join(footprint_dir, "footprint.rst"), "\n".join(content))


def build_merged_xml(profiles_data):
    """! @brief Build a merged XML index combining multiple user profiles.
    @param profiles_data List of (user_data, trips) tuples, one per profile.
    @return Formatted ElementTree with all profiles under a root <profiles> element.
    """
    print("  - Building merged XML...")

    root = ET.Element("profiles")

    for user_data, trips in profiles_data:
        profile_el = ET.SubElement(root, "profile")

        user_order = ["uid", "name", "bio", "location", "website", "picture"]
        for key in user_order:
            if key in user_data:
                add_text_element(profile_el, key, user_data[key], namespace=None)

        for key, value in user_data.items():
            if key in user_order:
                continue
            add_text_element(profile_el, key, value, namespace=None)

        trips_el = ET.SubElement(profile_el, "trips")
        for trip in trips:
            trip_el = ET.SubElement(trips_el, "trip")
            for key, value in trip.items():
                if key in ["companions", "footprints", "gpx", "period", "km", "is_current", "route_map", "satellite_map"] + TRIP_DETAIL_KEYS:
                    continue
                add_text_element(trip_el, key, value, namespace=None)

            gpx_ref = ET.SubElement(trip_el, "gpx")
            gpx_ref.text = trip.get("gpx", "")

            for companion in trip.get("companions", []):
                _add_companion(trip_el, companion)

    tree = ET.ElementTree(root)
    return format_tree(tree)
