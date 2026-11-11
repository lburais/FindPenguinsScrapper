"""GPX and XML writers for FindPenguins archives and route maps."""

from datetime import date
from io import BytesIO
import os
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from math import radians, sin, cos, sqrt, atan2, isfinite

from common_config import GPX_NS, XSI_NS
from common_utils import gpx_tag, add_text_element, format_tree, to_webp
from findpenguins_elevation import fetch_elevations

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


