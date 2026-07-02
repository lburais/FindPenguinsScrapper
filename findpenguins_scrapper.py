#!/usr/bin/env python3
"""
Complete FindPenguins profile scraper: userBox, companions, trips, footprints, photos.
Parses profile HTML, follows trip links, downloads photos (no _l/_m_s/_t_s suffixes).
"""

import os
import re
import unicodedata
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import argparse
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

# === CONFIG ===

BASE_URL = "https://findpenguins.com"
LOGIN_PAGE = "https://findpenguins.com/login"
LOGIN_POST = "https://findpenguins.com/login/exec"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FP-Scraper/1.0)"}
GPX_NS = "http://www.topografix.com/GPX/1/1"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


def gpx_tag(name):
    """Return a GPX namespaced tag name."""
    return f"{{{GPX_NS}}}{name}"


def add_text_element(parent, name, value, namespace=GPX_NS):
    """Append a text element when a value is available."""
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None

    tag = gpx_tag(name) if namespace else name
    child = ET.SubElement(parent, tag)
    child.text = value
    return child


def format_tree(tree):
    """Apply consistent 2-space indentation to an XML tree."""
    ET.indent(tree, space="  ", level=0)
    return tree


def requests_cookies_to_playwright(session):
    """Convert requests session cookies to Playwright cookie objects."""
    cookies = []
    for cookie in session.cookies:
        cookie_data = {
            "name": cookie.name,
            "value": cookie.value,
            "path": cookie.path or "/",
        }
        domain = (cookie.domain or "").lstrip(".")
        if domain:
            cookie_data["domain"] = domain
        else:
            cookie_data["url"] = BASE_URL
        if cookie.expires:
            cookie_data["expires"] = cookie.expires
        cookies.append(cookie_data)
    return cookies


def create_browser_page(session):
    """Create a headless Playwright page preloaded with authenticated cookies."""
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(user_agent=HEADERS["User-Agent"])
    cookies = requests_cookies_to_playwright(session)
    if cookies:
        context.add_cookies(cookies)
    page = context.new_page()
    return playwright, browser, page


def click_load_more_until_done(page):
    """Click the trip page load-more button until no more footprints are added."""
    footprint_selector = "ul.FootprintList li.footprint"
    load_more_selector = "#footprintListLoadMore"

    while True:
        load_more = page.locator(load_more_selector)
        if load_more.count() == 0:
            break

        button = load_more.first
        try:
            if not button.is_visible():
                break
        except Exception:
            break

        before_count = page.locator(footprint_selector).count()
        button.click()
        try:
            page.wait_for_function(
                """(beforeCount) => {
                    const current = document.querySelectorAll('ul.FootprintList li.footprint').length;
                    const loadMore = document.querySelector('#footprintListLoadMore');
                    return current > beforeCount || !loadMore || loadMore.offsetParent === null;
                }""",
                arg=before_count,
                timeout=15000,
            )
        except PlaywrightTimeoutError:
            break


def click_footprint_menu(page):
    """Open the 3-dots popup, extract available entries, then close it."""
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

# ##############################################################################################
# login
# ##############################################################################################

def login(username, password):
    """Authenticate with FindPenguins and return an authenticated requests session."""

    print("Logging ...")

    session = requests.Session()

    # 1) Load login page to get cookies and hidden fields (e.g. CSRF token)
    resp = session.get(LOGIN_PAGE)
    soup = BeautifulSoup(resp.text, "html.parser")

    csrf = soup.find("input", {"name": "_csrf_token"})["value"]  # adapt to real name

    # 2) Build payload with your email / password + hidden fields
    payload = {
        "_username": username,
        "_password": password,
        "_csrf_token": csrf,  # adapt field names
        "_remember_me": "on",
        "exec-login": "",

    }

    # 3) POST to the real login endpoint (check dev tools -> Network)
    resp = session.post(LOGIN_POST, data=payload)

    if resp.ok and "logout" in resp.text.lower():
        print("  Logged in!")

    return session

# ##############################################################################################
# load_page
# ##############################################################################################

def load_page(page, page_url, outputdir, save_html=True):
    """Navigate with Playwright, apply dynamic clicks, optionally save HTML, and return soup."""

    parts = urlparse(page_url)
    dirname, filename = os.path.split(parts.path)

    print(f"  - Getting page [{page_url}] ...")
    page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

    if "/trip/" in parts.path:
        click_load_more_until_done(page)

    soup = BeautifulSoup(page.content(), "html.parser")

    file_stem = filename
    if "/trip/" in parts.path:
        title_el = soup.select_one("h1.headline")
        title = " ".join(title_el.get_text().split()) if title_el else ""
        if title:
            ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
            slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_title).strip("-").lower()
            if slug:
                file_stem = slug

    if save_html:
        page_html = os.path.join(outputdir, file_stem + ".html")
        with open(page_html, "w", encoding="utf-8") as f:
            f.write(soup.prettify())

    return soup

# ##############################################################################################
# clean_text
# ##############################################################################################

def clean_text(t):
    """Normalize whitespace in a text value."""
    return re.sub(r"\s+", " ", (t or "")).strip()

# ##############################################################################################
# extract_park4night
# ##############################################################################################

def extract_park4night(text):
    """Extract first park4night URL from text and return cleaned text + URL."""
    if not text:
        return "", ""

    url_pattern = re.compile(r"https?://[^\s]+", flags=re.IGNORECASE)
    park4night_url = ""

    def _replace(match):
        nonlocal park4night_url
        url = match.group(0)
        if "park4night" in url.lower():
            if not park4night_url:
                park4night_url = url
            return ""
        return url

    cleaned = url_pattern.sub(_replace, text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, park4night_url

# ##############################################################################################
# extract_private_links
# ##############################################################################################

def extract_private_links(text):
    """Extract park4night and wikipedia URLs, returning cleaned text and links."""
    if not text:
        return "", "", []

    url_pattern = re.compile(r"https?://[^\s]+", flags=re.IGNORECASE)
    park4night_url = ""
    wikipedia_urls = []

    def _replace(match):
        nonlocal park4night_url
        url = match.group(0)
        lowered = url.lower()

        if "park4night" in lowered:
            if not park4night_url:
                park4night_url = url
            return ""

        if "wikipedia.org" in lowered:
            if url not in wikipedia_urls:
                wikipedia_urls.append(url)
            return ""

        return url

    cleaned = url_pattern.sub(_replace, text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, park4night_url, wikipedia_urls

# ##############################################################################################
# extract_expandable_text
# ##############################################################################################


def extract_expandable_text(node):
    """Extract readable text from expandable content blocks in footprint HTML."""
    if not node:
        return ""

    parsed = BeautifulSoup(str(node), "html.parser")
    root = parsed.find()
    if not root:
        return ""

    def strip_scheme(url):
        """Return URL without scheme and leading protocol-relative slashes."""
        if not url:
            return ""
        cleaned = url.strip()
        cleaned = re.sub(r"^//", "", cleaned)
        return re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE)

    def to_https_url(url):
        """Normalize URL to an explicit https:// URL when possible."""
        body = strip_scheme(url)
        if not body:
            return ""
        return "https://" + body

    # Merge split links split by a dots/rest pattern using href values.
    # Example: https://A + https://B => https://AB and visible text "https://AB".
    for dots in root.select(".dots"):
        prev_a = dots.find_previous("a")
        next_a = dots.find_next("a")
        if not prev_a or not next_a:
            continue
        prev_href = prev_a.get("href", "")
        next_href = next_a.get("href", "")
        prev_body = strip_scheme(prev_href)
        next_body = strip_scheme(next_href)
        if not (prev_body and next_body):
            continue
        merged_body = prev_body + next_body
        merged_url = "https://" + merged_body
        prev_a["href"] = merged_url
        prev_a.string = merged_url
        next_a.decompose()

    # Force link text to full https URL so output is not based on truncated UI labels.
    for a in root.select("a[href]"):
        href = a.get("href", "")
        if re.match(r"^(https?://|//)", href.strip(), flags=re.IGNORECASE):
            normalized = to_https_url(href)
            if normalized:
                a.string = normalized

    # Remove UI-only elements while keeping hidden continuation text (.rest.hide).
    for tag in root.select(".readMore, .dots, i.icon-font"):
        tag.decompose()

    # Keep explicit line break semantics from footprint markup.
    for br in root.find_all("br"):
        br.replace_with("\n")
    for dbl in root.select(".double-break"):
        dbl.replace_with("\n\n")

    # separator="" ensures href fragments split only by .dots are re-joined.
    text = root.get_text(separator="", strip=False)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

# ##############################################################################################
# normalize_photo_url
# ##############################################################################################

def normalize_photo_url(img_url: str) -> str:
    """Promote thumbnail image suffixes to large image suffixes."""
    parsed = urlparse(img_url)
    dirname, filename = os.path.split(parsed.path)
    new_filename = re.sub(r'(_m_s|_t_s)(\.[A-Za-z0-9]+)$', r'_l\2', filename)
    new_path = os.path.join(dirname, new_filename)
    return parsed._replace(path=new_path).geturl()

# ##############################################################################################
# download_image
# ##############################################################################################

def download_image(img_url, dest_folder, prefix="img"):
    """Download an image URL and store it in the destination folder."""

    os.makedirs(dest_folder, exist_ok=True)
    if img_url.startswith("//"):
        img_url = "https:" + img_url
    elif img_url.startswith("/"):
        img_url = urljoin(BASE_URL, img_url)
    img_url = normalize_photo_url(img_url)

    parsed = urlparse(img_url)
    filename = os.path.basename(parsed.path) or "image.jpg"
    local_name = f"{prefix}_{filename}"
    local_path = os.path.join(dest_folder, local_name)

    resp = requests.get(img_url, headers=HEADERS, stream=True, timeout=20)
    resp.raise_for_status()
    with open(local_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    return local_path

# ##############################################################################################
# parse_profile
# ##############################################################################################

def parse_profile(soup):
    """Extract core profile fields from the profile page."""
    user_box = soup.find("div", class_="userBox")
    if not user_box:
        raise RuntimeError("userBox not found")

    # Core user info
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
    # ADD DOWNLOAD PICTURE

    return {
        "name": name,
        "bio": bio,
        "location": location,
        "website": website,
        "picture": picture,
    }

# ##############################################################################################
# parse_trips
# ##############################################################################################

def parse_trips(soup, tripid):
    """Extract trip cards metadata from a profile page."""

    trips = []
    for box in soup.select(".tripList .tripPreviewBox"):
        link_el = box.select_one("a[href*='/trip/']")
        if not link_el:
            continue
        href = link_el.get("href", "")
        trip_url = urljoin(BASE_URL, href)

        # skip if not the tripid
        path_parts = urlparse(trip_url).path.strip("/").split("/")
        # path_parts = ['<tripid>', 'trip', '<slug>']
        if not path_parts or path_parts[0] != tripid:
            continue
        slug = path_parts[-1]

        title_el = link_el.select_one(".content .title h2")
        title = clean_text(title_el.get_text()) if title_el else ""

        # Stats: [0]=period(year+month text), [1]=days, [2]=km (optional), last=privacy icon
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

        # Trip-specific companions
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

        trips.append({
            "slug": slug,
            "title": title,
            "period": period,
            "days": days,
            "km": km,
            "is_current": str(is_current),
            "url": trip_url,
            "companions": companions,
        })
    return trips

# ##############################################################################################
# parse_footprints
# ##############################################################################################

def parse_footprints(soup):
    """Extract footprint IDs and URLs from a trip page."""

    footprints = []
    for fp in soup.select("ul.FootprintList li.footprint"):
        fp_id = fp.get("data-id", "")

        link_el = fp.select_one(".title h2.headline a[href]")
        href = link_el.get("href", "") if link_el else ""
        fp_url = urljoin(BASE_URL, href) if href else ""

        footprints.append({
            "id": fp_id,
            "url": fp_url,
        })
    return footprints

# ##############################################################################################
# parse_trip
# ##############################################################################################

def parse_trip(page, session, soup, trip_dir, photos_dir, save_html=True):
    """Parse trip details, download GPX/photos, and return parsed footprints."""

    # Download GPX from trip internal ID found in div.tripBox[data-trip-id]
    trip_box = soup.select_one("div.tripBox[data-trip-id]")
    if trip_box:
        trip_internal_id = trip_box.get("data-trip-id", "")
        if trip_internal_id:
            gpx_url = urljoin(
                BASE_URL,
                f"/account/trips/{trip_internal_id}/travel-route.gpx",
            )
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

        # Save each footprint page in the current trip folder.
        fp_soup = load_page(page, fp_url, trip_dir, save_html=save_html)
        popup_data = click_footprint_menu(page)
        fp = fp_soup.select_one(f"li.footprint[data-id='{fp_id}']")
        if not fp:
            fp = fp_soup.select_one("ul.FootprintList li.footprint")
        if not fp:
            continue

        # Coordinates from MapSingleFootprintController.initMap(lat, lon)
        lat, lon = "", ""
        for script in fp_soup.find_all("script"):
            m = re.search(
                r"MapSingleFootprintController\.initMap\(([\d.+-]+),([\d.+-]+)\)",
                script.get_text(),
            )
            if m:
                lat, lon = m.group(1), m.group(2)
                break

        # Title: h1.headline > a (fallback to h2 for older pages)
        title_el = fp.select_one(".title h1.headline a") or fp.select_one(".title h2.headline a")
        title = clean_text(title_el.get_text()) if title_el else ""

        # Date: ISO value in content attr; weather follows ⋅ in the same span text
        date = ""
        weather = ""
        date_span = fp.select_one(".title .date .desc")
        if date_span:
            date = date_span.get("content", "")  # ISO date e.g. "2025-06-02"
            desc_text = clean_text(date_span.get_text())
            if "\u22c5" in desc_text:  # ⋅ dot separator
                weather = desc_text.split("\u22c5", 1)[1].strip()

        # Text body
        text_el = fp.select_one(".content-container .text:not(.text-private)")
        text = extract_expandable_text(text_el)

        text_private_el = fp.select_one(".content-container .text-private")
        text_private = extract_expandable_text(text_private_el)
        text_private, park4night, wikipedia_links = extract_private_links(text_private)

        # Photos: a.image.photo[data-url] already carries _l URLs — no normalization needed
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

        if popup_data:
            if popup_data.get("weather"):
                weather = popup_data["weather"]

            popup_place = popup_data.get("places", [{}])[0] if popup_data.get("places") else {}
            
            # if popup_place.get("latitude"):
            #     latitude = popup_place["latitude"]
            # if popup_place.get("longitude"):
            #     longitude = popup_place["longitude"]

        footprints.append({
            "title": title,
            "date": date,
            "weather": weather,
            "temperature": popup_data.get("temperature", "") if popup_data else "",
            "altitude": popup_data.get("altitude", "") if popup_data else "",
            "overnights": popup_data.get("overnights", "") if popup_data else "",
            "flag": (popup_data.get("places", [{}])[0].get("flag", "") if popup_data and popup_data.get("places") else ""),
            "country": (popup_data.get("places", [{}])[0].get("country", "") if popup_data and popup_data.get("places") else ""),
            "city": (popup_data.get("places", [{}])[0].get("city", "") if popup_data and popup_data.get("places") else ""),
            "lat": lat,
            "lon": lon,
            "text": text,
            "text-private": text_private,
            "park4night": park4night,
            "wikipedia": wikipedia_links,
            "photos": photos,
        })
    return footprints

# ##############################################################################################
# footprint_to_waypoint
# ##############################################################################################

def footprint_to_waypoint(footprint):
    """Map one footprint dictionary to a GPX waypoint element."""

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

# ##############################################################################################
# build_trip_gpx
# ##############################################################################################


def build_trip_gpx(gpx_path, user_data, trip, footprints):
    """Update a trip GPX file with metadata extensions and footprint waypoints."""

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

    author = metadata.find(gpx_tag("author"))
    if author is None:
        author = ET.SubElement(metadata, gpx_tag("author"))
    author_name = author.find(gpx_tag("name"))
    if author_name is None:
        add_text_element(author, "name", user_data.get("name", ""))
    else:
        author_name.text = user_data.get("name", "")
    if user_data.get("website", ""):
        link = author.find(gpx_tag("link"))
        if link is None:
            ET.SubElement(author, gpx_tag("link"), href=user_data["website"])
        else:
            link.set("href", user_data["website"])

    trip_meta = metadata.find(gpx_tag("extensions"))
    if trip_meta is None:
        trip_meta = ET.SubElement(metadata, gpx_tag("extensions"))

    for key, value in trip.items():
        if key in ["companions", "footprints", "gpx"]:
            continue
        print(f"    - trip[{key}] : {value}")
        add_text_element(trip_meta, key, value, namespace=None)

    for companion in trip.get("companions", []):
        companion_ext = ET.SubElement(trip_meta, "companion")
        for key, value in companion.items():
            print(f"    - companion[{key}] : {value}")
            add_text_element(companion_ext, key, value, namespace=None)

    # Waypoints must precede track data in the serialized GPX.
    waypoints = []
    for footprint in footprints:
        print("")
        waypoint = footprint_to_waypoint(footprint)
        if waypoint is None:
            continue

        print(f"    - waypoint[{footprint.get('title', '')}] : {footprint.get('lat', '')}, {footprint.get('lon', '')}")
        waypoints.append(waypoint)

    track_elements = list(root.findall(gpx_tag("trk")))
    for track_element in track_elements:
        root.remove(track_element)

    for waypoint in waypoints:
        root.append(waypoint)

    for track_element in track_elements:
        root.append(track_element)

    format_tree(tree)
    tree.write(gpx_path, encoding="utf-8", xml_declaration=True)

# ##############################################################################################
# build_user_xml
# ##############################################################################################


def build_user_xml(user_data, trips):
    """Build a user-level XML index that references trip GPX files."""

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
            if key in ["companions", "footprints", "gpx"]:
                continue
            print(f"    - trip[{key}] : {value}")
            add_text_element(trip_el, key, value, namespace=None)

        gpx_ref = ET.SubElement(trip_el, "gpx")
        gpx_ref.text = trip.get("gpx", "")

        for companion in trip.get("companions", []):
            companion_el = ET.SubElement(trip_el, "companion")
            for key, value in companion.items():
                print(f"    - companion[{key}] : {value}")
                add_text_element(companion_el, key, value, namespace=None)

    tree = ET.ElementTree(root)
    return format_tree(tree)

# ##############################################################################################
# scrapper
# ##############################################################################################


def scrapper(args):
    """Run end-to-end scraping workflow and write user XML plus trip GPX files."""

    session = login(args.username, args.password)
    playwright, browser, page = create_browser_page(session)

    output_dir = os.path.join("output", args.id)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Parse profile
        print(f"Parsing profile [{args.id}] ...")

        soup = load_page(page, urljoin(BASE_URL, args.id), output_dir, save_html=args.save_html)

        user_data = parse_profile(soup)
        trips = parse_trips(soup, args.id)

        if args.trip:
            trips = [trip for trip in trips if trip["slug"] == args.trip]
            if not trips:
                raise RuntimeError(f'Trip not found: {args.trip}')

        # Process each trip
        print(f"Fetching {len(trips)} trip(s) ...")
        for idx, trip in enumerate(trips):
            print(f"Trip #{idx+1}: {trip['title']}")
            try:
                trip_dir = os.path.join(output_dir, trip['slug'])
                os.makedirs(trip_dir, exist_ok=True)

                soup = load_page(page, trip["url"], trip_dir, save_html=args.save_html)

                photos_dir = trip_dir
                footprints = parse_trip(page, session, soup, trip_dir, photos_dir, save_html=args.save_html)
                trip["footprints"] = footprints
                trip_gpx = os.path.join(output_dir, trip["slug"] + ".gpx")
                trip["gpx"] = os.path.relpath(trip_gpx, output_dir)

                build_trip_gpx(trip_gpx, user_data, trip, footprints)

                old_trip_gpx = os.path.join(trip_dir, trip["slug"] + ".gpx")
                if old_trip_gpx != trip_gpx and os.path.exists(old_trip_gpx):
                    os.remove(old_trip_gpx)

            except Exception as e:
                print(f"  ERROR: {e}")
                trip["footprints"] = []
                trip["gpx"] = os.path.relpath(os.path.join(output_dir, trip["slug"] + ".gpx"), output_dir)

            # Build and save user XML
            xml_tree = build_user_xml(user_data, trips)
            output_xml = os.path.join(output_dir, args.id + ".xml")
            xml_tree.write(output_xml, encoding="utf-8", xml_declaration=True)

            print(f"✅ Complete! XML: {output_xml}")
        print(f"✅ User: {user_data['name']}")
        print(f"✅ Trips: {len(trips)}")

        # ET.indent(xml_tree.getroot(), space="  ", level=0)
        # print( ET.tostring(xml_tree.getroot(), encoding="unicode", method="xml" ))
    finally:
        browser.close()
        playwright.stop()

# ##############################################################################################
# __main__
# ##############################################################################################


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
                prog='FindPenguins scrapper',
                description='Scrap FindPenguins profile')

    parser.add_argument("-i", "--id", required=True, help="Profile id")
    parser.add_argument("-u", "--username", default=None, help="Username")
    parser.add_argument("-p", "--password", default=None, help="Password")
    parser.add_argument("-o", "--output", default="output", help="Output folder")
    parser.add_argument("-t", "--trip", default=None, help="Trip slug to parse only")
    parser.add_argument("--save-html", action="store_true", help="Save fetched HTML files")

    arguments = parser.parse_args()

    scrapper(arguments)
