"""Generate Pelican RST articles and country maps from FindPenguins archives."""

from datetime import date, timedelta
import os
import re
import shutil
from urllib.parse import quote
from functools import lru_cache
from math import isfinite

from common_utils import make_variant, shrink_image, strip_leading_flag, to_webp

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


