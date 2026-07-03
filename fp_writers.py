"""! @file fp_writers.py
@brief Serialization helpers for trip GPX files and global user XML index.

Writers in this module preserve user-requested schema semantics including
metadata extensions, waypoint ordering, and indentation style.
"""

import os
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from math import radians, sin, cos, sqrt, atan2

from fp_config import GPX_NS, XSI_NS
from fp_utils import gpx_tag, add_text_element, format_tree
from elevation import fetch_elevations


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

    extensions_data = {
        "date": footprint.get("date", ""),
        "weather": footprint.get("weather", ""),
        "temperature": footprint.get("temperature", ""),
        "overnights": footprint.get("overnights", ""),
        "flag": footprint.get("flag", ""),
        "country": footprint.get("country", ""),
        "city": footprint.get("city", ""),
        "text-private": footprint.get("text-private", ""),
        "park4night": footprint.get("park4night", ""),
    }

    if any(value for value in extensions_data.values()) or footprint.get("wikipedia") or footprint.get("photos"):
        extensions = ET.SubElement(waypoint, gpx_tag("extensions"))

        for key, value in extensions_data.items():
            add_text_element(extensions, key, value, namespace=None)

        if footprint.get("wikipedia"):
            for wiki in footprint.get("wikipedia", []):
                add_text_element(extensions, "wikipedia", wiki, namespace=None)

        if footprint.get("photos"):
            for photo in footprint.get("photos", []):
                add_text_element(extensions, "photo", photo, namespace=None)

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

    # Replace legacy GPX author node with a flat uid metadata element.
    for author in list(metadata.findall(gpx_tag("author"))):
        metadata.remove(author)
    for uid in list(metadata.findall("uid")):
        metadata.remove(uid)
    add_text_element(metadata, "uid", author_uid, namespace=None)

    trip_meta = metadata.find(gpx_tag("extensions"))
    if trip_meta is None:
        trip_meta = ET.SubElement(metadata, gpx_tag("extensions"))

    for key, value in trip.items():
        if key in ["companions", "footprints", "gpx", "period", "days", "km", "is_current"]:
            continue
        print(f"    - trip[{key}] : {value}")
        add_text_element(trip_meta, key, value, namespace=None)

    for companion in trip.get("companions", []):
        companion_uid = str(companion.get("uid", "")).strip()
        if not companion_uid:
            continue
        print(f"    - companion[uid] : {companion_uid}")
        companion_ext = ET.SubElement(trip_meta, "companion")
        companion_ext.text = companion_uid

    waypoints = []
    for footprint in footprints:
        print("")
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
                elevation = point.get("ele")
                if elevation is None:
                    continue
                ele_node = track_point.find(gpx_tag("ele"))
                if ele_node is None:
                    ele_node = ET.SubElement(track_point, gpx_tag("ele"))
                ele_node.text = str(elevation)
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
            "trkpt",
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

    user_el = ET.SubElement(root, "user")
    for key, value in user_data.items():
        print(f"    - user[{key}] : {value}")
        add_text_element(user_el, key, value, namespace=None)

    trips_el = ET.SubElement(root, "trips")
    for trip in trips:
        trip_el = ET.SubElement(trips_el, "trip")
        for key, value in trip.items():
            if key in ["companions", "footprints", "gpx", "period", "days", "km", "is_current"]:
                continue
            print(f"    - trip[{key}] : {value}")
            add_text_element(trip_el, key, value, namespace=None)

        gpx_ref = ET.SubElement(trip_el, "gpx")
        gpx_ref.text = trip.get("gpx", "")

        for companion in trip.get("companions", []):
            companion_el = ET.SubElement(trip_el, "companion")
            companion_uid = str(companion.get("uid", "")).strip()
            print(f"    - companion[uid] : {companion_uid}")
            companion_el.text = companion_uid

    tree = ET.ElementTree(root)
    return format_tree(tree)
