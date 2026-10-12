"""! @file fp_writers.py
@brief Serialization helpers for trip GPX files and global user XML index.

Writers in this module preserve user-requested schema semantics including
metadata extensions, waypoint ordering, and indentation style.
"""

import os
import html
import json
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, unquote
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
    waypoint_url = str(footprint.get("url", "")).strip()
    if waypoint_url:
        ET.SubElement(waypoint, gpx_tag("link"), href=waypoint_url)

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

    if any(value for value in extensions_data.values()) or footprint.get("wikipedia") or footprint.get("photos") or footprint.get("videos"):
        extensions = ET.SubElement(waypoint, gpx_tag("extensions"))

        for key, value in extensions_data.items():
            add_text_element(extensions, key, value, namespace=None)

        if footprint.get("wikipedia"):
            for wiki in footprint.get("wikipedia", []):
                add_text_element(extensions, "wikipedia", wiki, namespace=None)

        if footprint.get("photos"):
            for photo in footprint.get("photos", []):
                add_text_element(extensions, "photo", photo, namespace=None)

        for video in footprint.get("videos", []):
            add_text_element(extensions, "video", video, namespace=None)

    return waypoint


def build_trip_gpx(gpx_path, user_data, trip, footprints, elevation):
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

    for key, value in trip.items():
        if key in ["companions", "footprints", "gpx", "period", "days", "km", "is_current", "url"]:
            continue
        print(f"    - trip[{key}] : {value}")
        add_text_element(trip_meta, key, value, namespace=None)

    add_text_element(trip_meta, "uid", author_uid, namespace=None)

    for companion in trip.get("companions", []):
        companion_uid = str(companion.get("uid", "")).strip()
        if not companion_uid:
            continue
        print(f"    - companion[uid] : {companion_uid}")
        companion_ext = ET.SubElement(trip_meta, "companion")
        companion_ext.text = companion_uid

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

    if track_points and elevation:
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


def _esc(value):
    """! @brief HTML-escape any value as text."""
    return html.escape(str(value or ""))


def _write_html(path, content):
    """! @brief Write an HTML document, creating parent folders."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def build_trip_html(trip_dir, trip, footprints):
    """! @brief Build a trip book: index.html plus one etape_N.html per footprint.
    @param trip_dir Trip output folder (photos are linked relative to it).
    @param trip Dictionary describing one trip.
    @param footprints List of trip footprint dictionaries.
    @return None
    """

    print(f"  - Building trip HTML [{trip_dir}]...")

    trip_title = _esc(trip.get("title") or trip.get("slug", ""))
    period = _esc(trip.get("period", ""))

    index_html = (
        f'<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>{trip_title}</title>'
        f"<style>{HTML_CSS}</style></head>\n"
        f'<body><div class="container"><header><a href="../index.html">← Retour</a>'
        f'<h1 style="font-size: 3rem;">{trip_title}</h1><div class="meta-badge-container">'
        f'{"<div class=\'badge\'>📅 " + period + "</div>" if period else ""}</div></header>'
        f'<h2>Chapitres</h2><ol style="line-height: 2;">\n'
    )
    markers = []

    total = len(footprints)
    for i, fp in enumerate(footprints):
        title = _esc(fp.get("title") or f"Étape {i + 1}")
        date = _esc(fp.get("date", ""))
        city = fp.get("city", "")
        country = fp.get("country", "")
        location_name = _esc(", ".join(part for part in (city, country) if part))
        lat = str(fp.get("lat", "")).strip()
        lon = str(fp.get("lon", "")).strip()
        weather = _esc(fp.get("weather", ""))
        temperature = _esc(fp.get("temperature", ""))
        altitude = _esc(fp.get("altitude", ""))

        file_name = f"etape_{i + 1}.html"
        index_html += f'<li><a href="{file_name}">{title}'
        if location_name:
            index_html += f" - <small>{location_name}</small>"
        index_html += "</a></li>\n"

        try:
            markers.append({"lat": float(lat), "lon": float(lon), "title": fp.get("title") or f"Étape {i + 1}", "href": file_name})
        except ValueError:
            pass

        prev_title = _esc(footprints[i - 1].get("title") or f"Étape {i}") if i > 0 else ""
        next_title = _esc(footprints[i + 1].get("title") or f"Étape {i + 2}") if i < total - 1 else ""
        prev_link = f'<a href="etape_{i}.html">← {prev_title}</a>' if i > 0 else "<span></span>"
        next_link = f'<a href="etape_{i + 2}.html">{next_title} →</a>' if i < total - 1 else "<span></span>"

        photo_html = ""
        for photo in fp.get("photos", []):
            src = html.escape(os.path.relpath(photo, trip_dir).replace(os.sep, "/"), quote=True)
            photo_html += f'<div class="photo-card"><img src="{src}" alt="Photo"></div>\n'

        video_html = "".join(
            '<div class="video-container"><video controls preload="metadata" '
            f'src="{html.escape(os.path.relpath(video, trip_dir).replace(os.sep, "/"), quote=True)}"></video></div>'
            for video in fp.get("videos", [])
        )

        map_div_html = map_script_html = ""
        try:
            float(lat)
            float(lon)
            has_coords = True
        except ValueError:
            has_coords = False
        if has_coords:
            popup = title.replace("\\", "\\\\")
            map_div_html = '<div id="map" class="map-container"></div>'
            map_script_html = f"""
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <script>
                document.addEventListener("DOMContentLoaded", function() {{
                    var map = L.map('map').setView([{lat}, {lon}], 12);
                    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{attribution: '© OpenStreetMap'}}).addTo(map);
                    L.marker([{lat}, {lon}]).addTo(map).bindPopup("<b>{popup}</b>").openPopup();
                }});
            </script>"""

        badges = ""
        if location_name:
            badges += f'<div class="badge">📍 {location_name}</div>'
        if date:
            badges += f'<div class="badge">📅 {date}</div>'
        if weather or temperature:
            badges += f'<div class="badge">☀️ {weather} {temperature}</div>'
        if altitude:
            badges += f'<div class="badge">⛰️ {altitude} m</div>'

        link_badges = ""
        park4night_url = str(fp.get("park4night", "")).strip()
        if park4night_url.startswith(("http://", "https://")):
            link_badges += f'<a class="badge" href="{html.escape(park4night_url, quote=True)}" target="_blank" rel="noopener">🅿️ park4night</a>'
        for wiki_url in fp.get("wikipedia", []):
            wiki_url = str(wiki_url).strip()
            if not wiki_url.startswith(("http://", "https://")):
                continue
            wiki_name = unquote(urlparse(wiki_url).path.rsplit("/", 1)[-1]).replace("_", " ")
            link_badges += f'<a class="badge" href="{html.escape(wiki_url, quote=True)}" target="_blank" rel="noopener">📖 Wikipedia{" · " + _esc(wiki_name) if wiki_name else ""}</a>'

        step_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"><title>{title}</title>
    <style>{HTML_CSS}</style>
    {map_script_html}
</head>
<body>
    <div class="container">
        <header>
            <div class="nav-links" style="margin-top:0; padding-top:0; border-top:none;">{prev_link}<a href="index.html">{trip_title}</a>{next_link}</div>
            <div class="step-number" style="margin-top:30px;">Étape {i + 1}</div>
            <h1 style="margin-top:5px; margin-bottom:10px;">{title}</h1>
            <div class="meta-badge-container">{badges}</div>
            {'<div class="meta-badge-container">' + link_badges + '</div>' if link_badges else ""}
        </header>
        {map_div_html}
        <div class="story-text">{_esc(fp.get("text", ""))}</div>
        {'<div class="meta-badge-container">' + link_badges + '</div>' if link_badges else ""}
        <div class="photo-grid">{photo_html}</div>
    </div>
</body>
</html>"""
        _write_html(os.path.join(trip_dir, file_name), step_html)

    if markers:
        # "<" is escaped so titles cannot close the script element.
        markers_json = json.dumps(markers).replace("<", "\\u003c")
        trip_map = f"""<div id="trip-map" class="map-container" style="height: 420px;"></div>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
document.addEventListener("DOMContentLoaded", function() {{
    var markers = {markers_json};
    var map = L.map('trip-map');
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{attribution: '© OpenStreetMap'}}).addTo(map);
    var bounds = [];
    markers.forEach(function(m) {{
        var link = document.createElement('a');
        link.href = m.href;
        link.textContent = m.title;
        L.marker([m.lat, m.lon]).addTo(map).bindPopup(link);
        bounds.push([m.lat, m.lon]);
    }});
    map.fitBounds(bounds, {{padding: [30, 30], maxZoom: 12}});
}});
</script>
"""
        index_html = index_html.replace("<h2>Chapitres</h2>", trip_map + "<h2>Chapitres</h2>", 1)
    index_html += "</ol></div></body></html>"
    _write_html(os.path.join(trip_dir, "index.html"), index_html)


def build_user_html(output_dir, user_data, trips):
    """! @brief Build the user landing page listing every trip book.
    @param output_dir Profile output folder (trip books live in <output_dir>/<slug>/).
    @param user_data Dictionary of profile-level fields.
    @param trips List of trip dictionaries.
    @return None
    """

    print(f"  - Building user HTML [{output_dir}]...")

    name = _esc(user_data.get("name") or user_data.get("uid", ""))
    picture = str(user_data.get("picture", "")).strip()
    avatar = f'<img class="avatar" src="{html.escape(picture, quote=True)}" alt="">' if picture else ""
    bio = _esc(user_data.get("bio", ""))
    location = _esc(user_data.get("location", ""))

    page = (
        f'<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>{name}</title>'
        f"<style>{HTML_CSS}</style></head>\n"
        f'<body><div class="container"><header><a href="../index.html">← FindPenguins</a><br>{avatar}<h1>{name}</h1>'
        f'{"<div class=\'meta-badge-container\'><div class=\'badge\'>📍 " + location + "</div></div>" if location else ""}'
        f'{"<p>" + bio + "</p>" if bio else ""}</header><ul>\n'
    )

    for trip in trips:
        slug = trip.get("slug", "")
        if not slug:
            continue
        count = len(trip.get("footprints", []))
        title = _esc(trip.get("title") or slug)
        period = _esc(trip.get("period", ""))
        page += (
            f'<li><a href="{html.escape(slug, quote=True)}/index.html"><strong>{title}</strong></a>'
            f'{" <small>" + period + "</small>" if period else ""} ({count} étapes)</li>\n'
        )

    page += "</ul></div></body></html>"
    _write_html(os.path.join(output_dir, "index.html"), page)


def build_global_html(output_dir, profiles_data):
    """! @brief Build one landing page listing every profile and its trips.
    @param output_dir Root output folder (profiles live in <output_dir>/<uid>/).
    @param profiles_data List of (user_data, trips) tuples, one per profile.
    @return None
    """

    print(f"  - Building global HTML [{output_dir}]...")

    page = (
        f'<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>FindPenguins</title>'
        f'<style>{HTML_CSS}</style></head>\n<body><div class="container">'
        f'<header><h1>FindPenguins</h1></header>\n'
    )

    for user_data, trips in profiles_data:
        uid = str(user_data.get("uid", ""))
        if not uid:
            continue
        base = html.escape(uid, quote=True)
        name = _esc(user_data.get("name") or uid)
        picture = str(user_data.get("picture", "")).strip()
        avatar = f'<img class="avatar" src="{base}/{html.escape(picture, quote=True)}" alt=""> ' if picture else ""
        page += f'<h2>{avatar}<a href="{base}/index.html">{name}</a></h2><ul>\n'
        for trip in trips:
            slug = trip.get("slug", "")
            if not slug:
                continue
            title = _esc(trip.get("title") or slug)
            period = _esc(trip.get("period", ""))
            count = len(trip.get("footprints", []))
            page += (
                f'<li><a href="{base}/{html.escape(slug, quote=True)}/index.html"><strong>{title}</strong></a>'
                f'{" <small>" + period + "</small>" if period else ""} ({count} étapes)</li>\n'
            )
        page += "</ul>\n"

    page += "</div></body></html>"
    _write_html(os.path.join(output_dir, "index.html"), page)


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
                if key in ["companions", "footprints", "gpx", "period", "days", "km", "is_current"]:
                    continue
                add_text_element(trip_el, key, value, namespace=None)

            gpx_ref = ET.SubElement(trip_el, "gpx")
            gpx_ref.text = trip.get("gpx", "")

            for companion in trip.get("companions", []):
                companion_el = ET.SubElement(trip_el, "companion")
                companion_el.text = str(companion.get("uid", "")).strip()

    tree = ET.ElementTree(root)
    return format_tree(tree)
