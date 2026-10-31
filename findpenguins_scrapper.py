#!/usr/bin/env python3
"""! @file findpenguins_scrapper.py
@brief Entrypoint and orchestration for FindPenguins scraping/export.

Usage: python findpenguins_scrapper.py PROFILES.json [--output DIR] [--content DIR] [--trip SLUG] [--save-html]

The profiles file maps profile names to {id, username, password}. An optional
"settings" entry configures the remaining options (see DEFAULT_SETTINGS). For every profile the
script produces one user XML index, one GPX file per trip and Pelican articles
(reStructuredText) for each trip and footprint.
"""

from urllib.parse import urljoin

import argparse
import json
import os
import shutil
import xml.etree.ElementTree as ET
import requests

from fp_config import BASE_URL
from fp_utils import login, create_browser_page, load_page, download_image
from fp_parsers import parse_profile, parse_trips, parse_trip, parse_trip_insights, parse_trip_image
from fp_writers import (
    build_trip_gpx,
    save_trip_route_map,
    build_user_xml,
    build_merged_xml,
    build_trip_rst,
)

## Default run settings; override them with a "settings" entry in the profiles file.
DEFAULT_SETTINGS = {
    "map_background": "transparent",
    "footprint_bubbles": False,
}

# ##############################################################################################
# process_profile
# ##############################################################################################


def process_profile(
    profile_id,
    username,
    password,
    settings,
):
    """! @brief Run end-to-end scraping workflow for one profile.
    @param profile_id Profile ID to scrape.
    @param username Username for authentication.
    @param password Password for authentication.
    @param settings Run settings (see DEFAULT_SETTINGS).
    @return Tuple containing profile data and its scraped trips.
    @exception RuntimeError Raised when requested single trip slug is not found.
    """

    output = settings["output"]
    save_html = settings["save_html"]
    trip_slug = settings["trip"]
    map_background = settings["map_background"]
    show_footprint_bubbles = settings["footprint_bubbles"]

    session = login(username, password)
    playwright, browser, page = create_browser_page(session)

    output_dir = os.path.join(output, profile_id)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Parse profile
        print(f"Parsing profile [{profile_id}] ...")

        soup = load_page(page, urljoin(BASE_URL, profile_id), output_dir, save_html=save_html)

        user_data = parse_profile(soup)
        user_data["uid"] = profile_id
        user_data["email"] = username or ""
        profile_picture_url = str(user_data.get("picture", "")).strip()
        if profile_picture_url:
            try:
                local_picture = download_image(profile_picture_url, output_dir, prefix=f"{profile_id}_profile")
                user_data["picture"] = os.path.relpath(local_picture, output_dir)
            except Exception as e:
                print(f"  WARNING: profile picture download failed: {e}")

        trips = parse_trips(soup, profile_id)

        if trip_slug:
            trips = [trip for trip in trips if trip["slug"] == trip_slug]
            if not trips:
                raise RuntimeError(f'Trip not found: {trip_slug}')

        # Process each trip
        print(f"Fetching {len(trips)} trip(s) ...")
        for idx, trip in enumerate(trips):
            print(f"Trip #{idx+1}: {trip['title']}")
            try:
                trip_dir = os.path.join(output_dir, trip['slug'])
                os.makedirs(trip_dir, exist_ok=True)

                soup = load_page(page, trip["url"], trip_dir, save_html=save_html)

                image_url = parse_trip_image(soup)
                if image_url:
                    try:
                        local_image = download_image(image_url, trip_dir, prefix="cover")
                        trip["image"] = os.path.relpath(local_image, output_dir)
                    except Exception as e:
                        print(f"  WARNING: trip image download failed: {e}")

                photos_dir = trip_dir
                footprints = parse_trip(page, session, soup, trip_dir, photos_dir, save_html=save_html)
                trip["footprints"] = footprints
                insights, insights_companions = parse_trip_insights(
                    page, trip["url"], trip_dir, save_html=save_html
                )
                trip.update(insights)
                if insights_companions:
                    for companion in insights_companions:
                        try:
                            local_avatar = download_image(
                                companion["avatar"], trip_dir, prefix=f"companion_{companion['uid']}"
                            )
                            companion["picture"] = os.path.relpath(local_avatar, output_dir)
                        except Exception as e:
                            print(f"  WARNING: companion picture download failed: {e}")
                    trip["companions"] = insights_companions
                trip_gpx = os.path.join(output_dir, trip["slug"] + ".gpx")
                trip["gpx"] = os.path.relpath(trip_gpx, output_dir)

                # Preserve route track points by seeding target GPX from downloaded trip GPX.
                downloaded_trip_gpx = os.path.join(trip_dir, trip["slug"] + ".gpx")
                if os.path.exists(downloaded_trip_gpx):
                    shutil.copyfile(downloaded_trip_gpx, trip_gpx)

                build_trip_gpx(trip_gpx, user_data, trip, footprints)
                route_map = os.path.join(trip_dir, "map_trip.png")
                try:
                    route_map = save_trip_route_map(
                        trip_gpx,
                        footprints,
                        route_map,
                        background=map_background,
                        show_footprint_bubbles=show_footprint_bubbles,
                    )
                    if route_map:
                        trip["route_map"] = os.path.relpath(route_map, output_dir)
                except (OSError, ET.ParseError, ValueError, requests.RequestException) as exc:
                    print(f"  - WARNING: unable to create satellite route map for {trip['title']}: {exc}")

                old_trip_gpx = os.path.join(trip_dir, trip["slug"] + ".gpx")
                if old_trip_gpx != trip_gpx and os.path.exists(old_trip_gpx):
                    os.remove(old_trip_gpx)

            except Exception as e:
                print(f"  ERROR: {e}")
                trip["footprints"] = []
                trip["gpx"] = os.path.relpath(os.path.join(output_dir, trip["slug"] + ".gpx"), output_dir)

            # Build and save user XML
            xml_tree = build_user_xml(user_data, trips)
            output_xml = os.path.join(output_dir, profile_id + ".xml")
            xml_tree.write(output_xml, encoding="utf-8", xml_declaration=True)

            print(f"✅ Complete! XML: {output_xml}")
        print(f"✅ User: {user_data['name']}")
        print(f"✅ Trips: {len(trips)}")

        # ET.indent(xml_tree.getroot(), space="  ", level=0)
        # print( ET.tostring(xml_tree.getroot(), encoding="unicode", method="xml" ))
        return user_data, trips
    finally:
        browser.close()
        playwright.stop()


# ##############################################################################################
# scrapper
# ##############################################################################################

def load_profiles(profiles_file):
    """! @brief Read the profiles file.
    @param profiles_file JSON file mapping names to {id, username, password}, plus optional "settings".
    @return Tuple (list of (id, username, password), settings from the "settings" entry over DEFAULT_SETTINGS).
    @exception ValueError Raised when the file has no usable profile.
    """
    with open(profiles_file, encoding="utf-8") as f:
        known = json.load(f)
    if not isinstance(known, dict):
        raise ValueError(f"{profiles_file} must contain a JSON object")

    settings = {**DEFAULT_SETTINGS, **known.pop("settings", {})}

    profiles = [
        (entry["id"], entry["username"], entry.get("password", ""))
        for entry in known.values()
    ]
    if not profiles:
        raise ValueError(f"No profile found in {profiles_file}")
    return profiles, settings


def scrapper(profiles_file, output, content, trip=None, save_html=False):
    """! @brief Scrape every profile of the profiles file and generate the Pelican articles.
    @param profiles_file JSON profiles file path.
    @param output Archive directory for XML, GPX and downloaded media.
    @param content Pelican articles directory.
    @param trip Optional slug of the only trip to scrape.
    @param save_html Whether to save downloaded HTML for debugging.
    @return List of (user_data, trips) tuples for successfully scraped profiles.
    """
    profiles, settings = load_profiles(profiles_file)
    settings.update(output=output, trip=trip, save_html=save_html)

    # Process each profile, collecting results for merged XML
    collected = []
    for idx, (profile_id, username, password) in enumerate(profiles):
        print(f"\n{'='*60}")
        print(f"Processing profile {idx + 1}/{len(profiles)}: {profile_id}")
        print(f"{'='*60}\n")

        try:
            collected.append(process_profile(profile_id, username, password, settings))
        except Exception as e:
            print(f"\n❌ ERROR processing profile {profile_id}: {e}\n")

    # Write merged XML when multiple profiles were processed
    if len(collected) > 1:
        print(f"\n{'='*60}")
        print("Building merged XML for all profiles...")
        print(f"{'='*60}\n")
        merged_tree = build_merged_xml(collected)
        merged_xml = os.path.join(output, "profiles.xml")
        os.makedirs(output, exist_ok=True)
        merged_tree.write(merged_xml, encoding="utf-8", xml_declaration=True)
        print(f"✅ Merged XML: {merged_xml}")

    generate_rst_outputs(content, output, collected)
    return collected


def generate_rst_outputs(content_dir, output, profiles_data):
    """! @brief Generate Pelican articles (reStructuredText) after scraping.
    @param content_dir Pelican articles source directory.
    @param output Root directory containing scraped profile assets.
    @param profiles_data List of (user_data, trips) tuples returned by process_profile.
    @return None
    """
    if not profiles_data:
        return
    print("\nGenerating reStructuredText output(s)...")
    for user_data, trips in profiles_data:
        profile_dir = os.path.join(output, user_data["uid"])
        for trip in trips:
            trip_dir = os.path.join(profile_dir, trip["slug"])
            build_trip_rst(content_dir, trip_dir, user_data, trip, trip.get("footprints", []))


# ##############################################################################################
# __main__
# ##############################################################################################


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="FindPenguins scrapper",
        description="Scrape the FindPenguins profiles of a profiles file",
    )
    parser.add_argument(
        "profiles", 
        help="JSON file mapping profile names to {id, username, password}")
    parser.add_argument(
        "--output", 
        default="output", 
        help="Archive folder for XML, GPX and media (default: output)")
    parser.add_argument(
        "--content",
        default="../website/content/articles/findpenguins",
        help="Pelican articles folder (default: ../website/content/articles/findpenguins)",
    )
    parser.add_argument(
        "-t", "--trip",
        default=None,
        help="Trip slug to scrape only (default: all trips)")
    parser.add_argument(
        "--save-html", 
        action="store_true", 
        help="Save fetched HTML files")
    arguments = parser.parse_args()
    scrapper(arguments.profiles, arguments.output, arguments.content, arguments.trip, arguments.save_html)
