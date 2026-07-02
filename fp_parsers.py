"""! @file fp_parsers.py
@brief Parsers for profile, trip, and footprint data extraction.

This module converts HTML and popup UI fragments into normalized Python
dictionaries used by the writer layer.
"""

import os
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from fp_config import BASE_URL, HEADERS
from fp_utils import clean_text, extract_expandable_text, extract_private_links, download_image, load_page


def click_footprint_menu(page):
    """! @brief Extract weather/location metadata from the footprint popup menu.
    @param page Active Playwright page positioned on a footprint page.
    @return Dictionary with popup-derived fields, or empty dict when unavailable.
    """
    menu = page.locator("a.menu[role='button']")
    if menu.count() == 0:
        return {}

    try:
        menu.first.click(timeout=5000)
    except Exception:
        return {}

    modal = page.locator("#_fpMenuPopup, div._pup._modal, div._pup._modal._white, div._pup")
    try:
        modal.first.wait_for(state="visible", timeout=5000)
        page.wait_for_selector("#_fpMenuPopup ._fpMenu", timeout=7000)
    except Exception:
        return {}

    popup_data = {
        "overnights": "",
        "weather": "",
        "temperature": "",
        "altitude": "",
        "places": [],
    }

    try:
        modal_html = page.locator("#_fpMenuPopup ._fpMenu").first.inner_html()
        modal_soup = BeautifulSoup(modal_html, "html.parser")

        overnights_icon = modal_soup.select_one(
            "li i.overnights, li .icon-font.overnights, li i[class*='overnight'], li i[class*='nights']"
        )
        if overnights_icon and overnights_icon.parent:
            raw_overnights = clean_text(overnights_icon.parent.get_text(" ", strip=True))
            overnights_match = re.search(r"(\d+)", raw_overnights)
            popup_data["overnights"] = overnights_match.group(1) if overnights_match else ""

        temp_icon = modal_soup.select_one("li .icon-font.temperature")
        if temp_icon and temp_icon.parent:
            raw_temp = clean_text(temp_icon.parent.get_text(" ", strip=True))
            weather_match = re.search(r"^\s*(\S+)", raw_temp)
            popup_data["weather"] = weather_match.group(1) if weather_match else ""
            temp_match = re.search(r"(-?\d+(?:[.,]\d+)?)", raw_temp)
            popup_data["temperature"] = temp_match.group(1).replace(",", ".") if temp_match else ""

        alt_icon = modal_soup.select_one("li .icon-font.altitude")
        if alt_icon and alt_icon.parent:
            raw_alt = clean_text(alt_icon.parent.get_text(" ", strip=True))
            alt_match = re.search(r"(-?\d+(?:[.,]\d+)?)", raw_alt)
            popup_data["altitude"] = alt_match.group(1).replace(",", ".") if alt_match else ""

        def dms_to_decimal(coord_text):
            """! @brief Convert DMS coordinates text into decimal latitude/longitude.
            @param coord_text Coordinate string potentially containing N/S/E/W values.
            @return Tuple (lat, lon) where values may be None when missing.
            """
            matches = re.findall(
                r"(\d+(?:\.\d+)?)\D+(\d+(?:\.\d+)?)\D+(\d+(?:\.\d+)?)?\D*([NSEW])",
                (coord_text or "").upper(),
            )
            values = {}
            for deg, minute, second, hemi in matches:
                d = float(deg)
                m = float(minute)
                s = float(second) if second else 0.0
                val = d + (m / 60.0) + (s / 3600.0)
                if hemi in ("S", "W"):
                    val = -val
                values[hemi] = val

            lat = values.get("N") if "N" in values else values.get("S")
            lon = values.get("E") if "E" in values else values.get("W")
            return lat, lon

        place_block = modal_soup.select_one(".fpMenuPlacesList")
        if place_block:
            flag = ""
            country = ""
            city = ""
            lat = ""
            lon = ""

            for tag in place_block.select("a.tag"):
                classes = tag.get("class", [])
                label = clean_text(tag.get_text(" ", strip=True).replace("\xa0", " "))
                href = clean_text(tag.get("href", ""))

                if "coordAction" in classes:
                    text_area = tag.select_one("textarea")
                    coord_text = clean_text(text_area.get_text(" ", strip=True)) if text_area else label
                    dms_lat, dms_lon = dms_to_decimal(coord_text)
                    if dms_lat is not None:
                        lat = f"{dms_lat:.6f}"
                    if dms_lon is not None:
                        lon = f"{dms_lon:.6f}"
                    continue

                if href.startswith("/explore/"):
                    city = label
                    bbox = re.search(r"/explore/[^/]+/([\-\d.]+),([\-\d.]+),([\-\d.]+),([\-\d.]+)", href)
                    if bbox and (not lat or not lon):
                        lat_min = float(bbox.group(1))
                        lon_min = float(bbox.group(2))
                        lat_max = float(bbox.group(3))
                        lon_max = float(bbox.group(4))
                        lat = f"{((lat_min + lat_max) / 2.0):.6f}"
                        lon = f"{((lon_min + lon_max) / 2.0):.6f}"
                    continue

                if href.startswith("/") and not href.startswith("/explore/"):
                    flag_img = tag.select_one("img.flag-icon, img.flag-sm")
                    if flag_img:
                        src = clean_text(flag_img.get("src", ""))
                        m_code = re.search(r"/flags-png/([a-z]{2})\.png", src, flags=re.IGNORECASE)
                        if m_code:
                            cc = m_code.group(1).upper()
                            if len(cc) == 2 and cc.isalpha():
                                flag = chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))

                    country_match = re.match(r"^\s*(\S+)\s+(.+?)\s*$", label)
                    if country_match and not re.search(r"[A-Za-z]", country_match.group(1)):
                        flag = country_match.group(1)
                        country = clean_text(country_match.group(2))
                    else:
                        country = label

            if country or city or lat or lon:
                popup_data["places"].append(
                    {
                        "flag": flag,
                        "country": country,
                        "city": city,
                        "latitude": lat,
                        "longitude": lon,
                    }
                )
    except Exception:
        popup_data = {
            "overnights": "",
            "weather": "",
            "temperature": "",
            "altitude": "",
            "places": [],
        }

    try:
        close_btn = modal.first.locator(
            "a.closeBtn, a[aria-label='Close'], button[aria-label='Close'], .closeBtn, .icon-font.close"
        )
        if close_btn.count() > 0:
            close_btn.first.click(timeout=3000)
        else:
            page.keyboard.press("Escape")
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    try:
        modal.first.wait_for(state="hidden", timeout=3000)
    except Exception:
        pass

    if (
        not popup_data["overnights"]
        and not popup_data["weather"]
        and not popup_data["temperature"]
        and not popup_data["altitude"]
        and not popup_data["places"]
    ):
        return {}
    return popup_data


def parse_profile(soup):
    """! @brief Parse user profile fields from the profile page HTML.
    @param soup BeautifulSoup object for profile page.
    @return Dictionary containing normalized user fields.
    @exception RuntimeError Raised when expected user container is missing.
    """
    user_box = soup.find("div", class_="userBox")
    if not user_box:
        raise RuntimeError("userBox not found")

    name_el = user_box.select_one(".nameBox h1 a")
    name = clean_text(name_el.get_text()) if name_el else ""

    bio_el = user_box.select_one(".detailBox #clampedBox span")
    bio = clean_text(bio_el.get_text()) if bio_el else ""

    loc_el = user_box.select_one(".detailBox .extras a[href*='explore?q=']")
    location = clean_text(loc_el.get_text()) if loc_el else ""

    web_el = user_box.select_one(".detailBox .extras a.website")
    website = web_el["href"] if web_el and web_el.has_attr("href") else ""

    pic_el = user_box.select_one(".pictureBox .pp img")
    picture = pic_el["src"] if pic_el and pic_el.has_attr("src") else ""
    if picture.startswith("//"):
        picture = "https:" + picture

    return {
        "name": name,
        "bio": bio,
        "location": location,
        "website": website,
        "picture": picture,
    }


def parse_trips(soup, tripid):
    """! @brief Parse trip cards shown on a user profile page.
    @param soup BeautifulSoup object for profile page.
    @param tripid FindPenguins profile identifier used to filter valid trip URLs.
    @return List of trip dictionaries with metadata and companion previews.
    """

    trips = []
    for box in soup.select(".tripList .tripPreviewBox"):
        link_el = box.select_one("a[href*='/trip/']")
        if not link_el:
            continue
        href = link_el.get("href", "")
        trip_url = urljoin(BASE_URL, href)

        path_parts = urlparse(trip_url).path.strip("/").split("/")
        if not path_parts or path_parts[0] != tripid:
            continue
        slug = path_parts[-1]

        title_el = link_el.select_one(".content .title h2")
        title = clean_text(title_el.get_text()) if title_el else ""

        stats = link_el.select(".content .stats li")
        period = clean_text(stats[0].get_text()) if stats else ""
        days_b = stats[1].find("b") if len(stats) > 1 else None
        days = days_b.get_text(strip=True) if days_b else ""
        km = ""
        if len(stats) > 2:
            km_text = clean_text(stats[2].get_text())
            if "kilometer" in km_text.lower():
                km_b = stats[2].find("b")
                km = km_b.get_text(strip=True) if km_b else ""

        is_current = box.select_one(".badge.current") is not None

        companions = []
        for span in box.select(".userIconBar span.item"):
            uid = span.get("data-id", "")
            img = span.find("img")
            if not img:
                continue
            avatar = img.get("src", "")
            if avatar.startswith("//"):
                avatar = "https:" + avatar
            elif avatar.startswith("/"):
                avatar = urljoin(BASE_URL, avatar)
            companions.append({"uid": uid, "name": clean_text(img.get("alt", "")), "avatar": avatar})

        trips.append(
            {
                "slug": slug,
                "title": title,
                "period": period,
                "days": days,
                "km": km,
                "is_current": str(is_current),
                "url": trip_url,
                "companions": companions,
            }
        )
    return trips


def parse_footprints(soup):
    """! @brief Parse footprint identifiers and URLs from a trip page.
    @param soup BeautifulSoup object for a trip page.
    @return List of dictionaries with footprint id and URL.
    """

    footprints = []
    for fp in soup.select("ul.FootprintList li.footprint"):
        fp_id = fp.get("data-id", "")

        link_el = fp.select_one(".title h2.headline a[href]")
        href = link_el.get("href", "") if link_el else ""
        fp_url = urljoin(BASE_URL, href) if href else ""

        footprints.append({"id": fp_id, "url": fp_url})
    return footprints


def parse_trip(page, session, soup, trip_dir, photos_dir, save_html=True):
    """! @brief Parse one trip in detail and collect enriched footprint data.
    @param page Active Playwright page.
    @param session Authenticated requests session used for GPX download.
    @param soup BeautifulSoup object for the trip page.
    @param trip_dir Directory where trip artifacts are stored.
    @param photos_dir Directory where downloaded photos are stored.
    @param save_html When true, save fetched footprint pages as HTML snapshots.
    @return List of normalized footprint dictionaries.
    """

    trip_box = soup.select_one("div.tripBox[data-trip-id]")
    if trip_box:
        trip_internal_id = trip_box.get("data-trip-id", "")
        if trip_internal_id:
            gpx_url = urljoin(BASE_URL, f"/account/trips/{trip_internal_id}/travel-route.gpx")
            gpx_path = os.path.join(trip_dir, os.path.basename(trip_dir) + ".gpx")
            print(f"  - Downloading GPX [{gpx_url}] ...")
            try:
                resp = session.get(gpx_url, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                with open(gpx_path, "wb") as f:
                    f.write(resp.content)
            except Exception as e:
                print(f"  GPX download failed: {e}")

    footprints = []
    for footprint_ref in parse_footprints(soup):
        fp_id = footprint_ref.get("id", "")
        fp_url = footprint_ref.get("url", "")

        if not fp_url:
            continue

        fp_soup = load_page(page, fp_url, trip_dir, save_html=save_html)
        popup_data = click_footprint_menu(page)
        fp = fp_soup.select_one(f"li.footprint[data-id='{fp_id}']")
        if not fp:
            fp = fp_soup.select_one("ul.FootprintList li.footprint")
        if not fp:
            continue

        lat, lon = "", ""
        for script in fp_soup.find_all("script"):
            m = re.search(
                r"MapSingleFootprintController\.initMap\(([\d.+-]+),([\d.+-]+)\)",
                script.get_text(),
            )
            if m:
                lat, lon = m.group(1), m.group(2)
                break

        title_el = fp.select_one(".title h1.headline a") or fp.select_one(".title h2.headline a")
        title = clean_text(title_el.get_text()) if title_el else ""

        date = ""
        weather = ""
        date_span = fp.select_one(".title .date .desc")
        if date_span:
            date = date_span.get("content", "")
            desc_text = clean_text(date_span.get_text())
            if "\u22c5" in desc_text:
                weather = desc_text.split("\u22c5", 1)[1].strip()

        text_el = fp.select_one(".content-container .text:not(.text-private)")
        text = extract_expandable_text(text_el)

        text_private_el = fp.select_one(".content-container .text-private")
        text_private = extract_expandable_text(text_private_el)
        text_private, park4night, wikipedia_links = extract_private_links(text_private)

        photos = []
        for anchor in fp.select("a.image.photo[data-url]"):
            img_url = anchor.get("data-url", "")
            if not img_url:
                continue
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            try:
                local_path = download_image(img_url, photos_dir, prefix=f"{fp_id}_")
                photos.append(local_path)
            except Exception as e:
                print(f"Photo download failed: {img_url} -> {e}")

        if popup_data and popup_data.get("weather"):
            weather = popup_data["weather"]

        footprints.append(
            {
                "title": title,
                "date": date,
                "weather": weather,
                "temperature": popup_data.get("temperature", "") if popup_data else "",
                "altitude": popup_data.get("altitude", "") if popup_data else "",
                "overnights": popup_data.get("overnights", "") if popup_data else "",
                "flag": (
                    popup_data.get("places", [{}])[0].get("flag", "")
                    if popup_data and popup_data.get("places")
                    else ""
                ),
                "country": (
                    popup_data.get("places", [{}])[0].get("country", "")
                    if popup_data and popup_data.get("places")
                    else ""
                ),
                "city": (
                    popup_data.get("places", [{}])[0].get("city", "")
                    if popup_data and popup_data.get("places")
                    else ""
                ),
                "lat": lat,
                "lon": lon,
                "text": text,
                "text-private": text_private,
                "park4night": park4night,
                "wikipedia": wikipedia_links,
                "photos": photos,
            }
        )
    return footprints
