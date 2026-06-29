#!/usr/bin/env python3
"""
Complete FindPenguins profile scraper: userBox, companions, trips, footprints, photos.
Parses profile HTML, follows trip links, downloads photos (no _l/_m_s/_t_s suffixes).
"""

import os
import sys
import re
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import argparse

# === CONFIG ===

BASE_URL = "https://findpenguins.com"
LOGIN_PAGE = "https://findpenguins.com/login"
LOGIN_POST = "https://findpenguins.com/login/exec" 

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FP-Scraper/1.0)"}

# ##############################################################################################
# login
# ##############################################################################################

def login( username, password ):

    print( f"Logging ..." )

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

def load_page( session, page_url, dir ):

    parts = urlparse(page_url)
    dirname, filename = os.path.split(parts.path)

    page_html = os.path.join(dir, filename + ".html")
        
    print(f"Getting page [{page_url}] ...")
    resp = session.get(page_url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    with open(page_html, "w", encoding=resp.encoding or "utf-8") as f:
        f.write(soup.prettify() )

    return soup

# ##############################################################################################
# clean_text
# ##############################################################################################

def clean_text(t):
    return re.sub(r"\s+", " ", (t or "")).strip()


def extract_expandable_text(node):
    if not node:
        return ""

    parsed = BeautifulSoup(str(node), "html.parser")
    root = parsed.find()
    if not root:
        return ""

    def strip_scheme(url):
        if not url:
            return ""
        cleaned = url.strip()
        cleaned = re.sub(r"^//", "", cleaned)
        return re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE)

    def to_https_url(url):
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
# normalize_phot_url
# ##############################################################################################

def normalize_photo_url(img_url: str) -> str:
    parsed = urlparse(img_url)
    dirname, filename = os.path.split(parsed.path)
    new_filename = re.sub(r'(_m_s|_t_s)(\.[A-Za-z0-9]+)$', r'_l\2', filename)
    new_path = os.path.join(dirname, new_filename)
    return parsed._replace(path=new_path).geturl()

# ##############################################################################################
# download_image
# ##############################################################################################

def download_image(img_url, dest_folder, prefix="img"):

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
    # todo: download picture

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

def parse_trips(soup, id):

    trips = []
    for box in soup.select(".tripList .tripPreviewBox"):
        link_el = box.select_one("a[href*='/trip/']") 
        if not link_el:
            continue
        href = link_el.get("href", "")
        trip_url = urljoin(BASE_URL, href)

        # skip if not the id
        path_parts = urlparse(trip_url).path.strip("/").split("/")
        # path_parts = ['<id>', 'trip', '<slug>']
        if not path_parts or path_parts[0] != id:
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
            companions.append({"id": uid, "name": clean_text(img.get("alt", "")), "avatar": avatar})

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
# parse_trip
# ##############################################################################################

def parse_trip(soup, photos_dir):

    footprints = []
    for fp in soup.select("ul.FootprintList li.footprint"):
        fp_id = fp.get("data-id", "")

        # Title: h2.headline > a
        title_el = fp.select_one(".title h2.headline a")
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

        footprints.append({
            "title": title,
            "date": date,
            "weather": weather,
            "text": text,
            "text-private": text_private,
            "photos": photos,
        })
    return footprints

# ##############################################################################################
# build_xml
# ##############################################################################################

def build_xml(user_data, trips):
    root = ET.Element("profile")

    # User
    user_el = ET.SubElement(root, "user")
    for key, value in user_data.items():
        print( f"user[{key}] : {value}")
        ET.SubElement(user_el, key).text = value

    # Trips
    trips_el = ET.SubElement(root, "trips")
    for t_idx, trip in enumerate(trips):
        trip_el = ET.SubElement(trips_el, "trip")
        for key, value in trip.items():
            if key not in ['companions', 'footprints']:
                print( f"trip[{key}] : {value}")
                ET.SubElement(trip_el, key).text = value

        # Trip companions
        tcomps_el = ET.SubElement(trip_el, "companions")
        for c in trip.get("companions", []):
            ce = ET.SubElement(tcomps_el, "companion")
            for key, value in c.items():
                print( f"companion[{key}] : {value}")
                ET.SubElement(ce, key).text = value

        # Footprints
        fps_el = ET.SubElement(trip_el, "footprints")
        for fp in trip.get("footprints", []):
            fp_el = ET.SubElement(fps_el, "footprint")
            for key, value in fp.items():
                if key not in ["photos"]:
                    print( f"footprint[{key}] : {value}")
                    ET.SubElement(fp_el, key).text = value

            photos_el = ET.SubElement(fp_el, "photos")
            for p in fp["photos"]:
                ET.SubElement(photos_el, "photo").text = p

    # Pretty print
    def indent(elem, level=0):
        i = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            for child in elem:
                indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = i
        elif level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i
    indent(root)
    return ET.ElementTree(root)

# ##############################################################################################
# scrapper
# ##############################################################################################

def scrapper( args ):

    session = login( args.username, args.password )

    output_dir = os.path.join("output", args.id)
    os.makedirs( output_dir, exist_ok=True )

    # Parse profile
    print(f"Parsing profile [{args.id}] ...")

    soup = load_page( session, urljoin(BASE_URL, args.id), output_dir  )

    user_data = parse_profile(soup)
    trips = parse_trips(soup, args.id)

    if args.trip:
        trips = [trip for trip in trips if trip["slug"] == args.trip]
        if not trips:
            raise RuntimeError(f'Trip not found: {args.trip}')

    # Process each trip
    print(f"Fetching {len(trips)} trips ...")
    for idx, trip in enumerate(trips):
        print(f"  Trip #{idx+1}: {trip['title']}")
        try:
            soup = load_page( session, trip["url"], output_dir )

            photos_dir = os.path.join( output_dir, trip['slug'])
            footprints = parse_trip(soup, photos_dir)
            trip["footprints"] = footprints

        except Exception as e:
            print(f"  ERROR: {e}")
            trip["footprints"] = []

    # Build and save XML
    print("Building XML...")
    xml_tree = build_xml(user_data, trips)
    output_xml = os.path.join( output_dir, args.id + ".xml")
    xml_tree.write(output_xml, encoding="utf-8", xml_declaration=True)

    print(f"✅ Complete! XML: {output_xml}")
    print(f"✅ User: {user_data['name']}")
    print(f"✅ Trips: {len(trips)}")

    ET.indent(xml_tree.getroot(), space="  ", level=0)
    print( ET.tostring(xml_tree.getroot(), encoding="unicode", method="xml" ))

# ##############################################################################################
# __main__
# ##############################################################################################

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
                prog='FindPenguins scrapper',
                description='Scrap FindPenguins profile')

    parser.add_argument( "-i", "--id", required=True, help="Profile id" )
    parser.add_argument( "-u", "--username", default=None, help="Username" )
    parser.add_argument( "-p", "--password", default=None, help="Password" )
    parser.add_argument( "-o", "--output", default="output", help="Output folder" )
    parser.add_argument( "-t", "--trip", default=None, help="Trip slug to parse only" )

    args = parser.parse_args()

    scrapper( args )
