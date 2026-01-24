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
    for box in soup.select(".tripList .box"):
        link_el = box.select_one("a.trip-preview")
        href = link_el["href"] if link_el and link_el.has_attr("href") else ""
        trip_url = urljoin(BASE_URL, href)

        # skip if not the id
        parts = urlparse(trip_url)
        dirname, filename = os.path.split(parts.path)
        if id != dirname.lstrip("/").split("/", 1)[0]:
            continue

        title_el = box.select_one(".content .title h2")
        title = clean_text(title_el.get_text()) if title_el else ""

        period_el = box.select_one(".content .title .subline")
        period = clean_text(period_el.get_text()) if period_el else ""

        stats = box.select(".content .stats li")
        countries = stats[0].b.get_text(strip=True) if len(stats) > 0 and stats[0].b else ""
        footprints_count = stats[1].b.get_text(strip=True) if len(stats) > 1 and stats[1].b else ""
        days = stats[2].b.get_text(strip=True) if len(stats) > 2 and stats[2].b else ""

        parts = urlparse(href)
        dirname, filename = os.path.split(parts.path)
        slug = filename

        # Trip-specific companions
        companions = []
        user_icon_bar = box.select_one(".userIconBar")
        if user_icon_bar:
            for span in user_icon_bar.select("span.item"):
                uid = span.get("data-id", "")
                img = span.find("img")
                avatar = img.get("src", "") if img else ""
                name_alt = img.get("alt", "") if img else ""
                if avatar.startswith("//"):
                    avatar = "https:" + avatar
                elif avatar.startswith("/"):
                    avatar = urljoin(BASE_URL, avatar)

                # todo: download avatar

                companions.append({"id": uid, "name": clean_text(name_alt), "avatar": avatar})

        trips.append({
            "slug": slug,
            "title": title,
            "period": period,
            "countries": countries,
            "footprints_count": footprints_count,
            "days": days,
            "url": trip_url,
            "companions": companions,
        })
    return trips

# ##############################################################################################
# parse_trip
# ##############################################################################################

def parse_trip(soup, photos_dir):

    footprints = []
    for fp_idx, fp in enumerate(soup.select(".footprint, li.footprint, .Footprint, .footprint-item")):
        title_el = fp.select_one("h2, h3, .title, .footprint-title")
        date_el = fp.select_one("time, .date")
        text_el = fp.select_one(".text, .body, .description, .footprint-text, p")
        # todo: merge with .text-private
        # todo: date is desc
        # todo: weather is .date after in France
        # todo: title is h2

        title = clean_text(title_el.get_text()) if title_el else ""
        date = clean_text(date_el.get_text()) if date_el else ""
        text = clean_text(text_el.get_text()) if text_el else ""

        # need to better address the date and get weather and the br in text

        photos = []
        for img in fp.select("img"):
            src = img.get("src") or img.get("data-src", "")
            if not src or "avatar" in src.lower() or src.endswith(".svg"):
                continue
            try:
                local_path = download_image(
                    src,
                    photos_dir,
                    prefix=f"fp{fp_idx}_",
                )
                photos.append(local_path)
            except Exception as e:
                print(f"Photo download failed: {src} -> {e}")

        footprints.append({
            "title": title, 
            "date": date, 
            "weather": "",
            "text": text, 
            "photos": photos})
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
                    ET.SubElement(fps_el, key).text = value

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

    args = parser.parse_args()

    scrapper( args )
