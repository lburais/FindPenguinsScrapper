#!/usr/bin/env python3
"""! @file findpenguins_scrapper.py
@brief CLI entrypoint and orchestration for FindPenguins scraping/export.

This script coordinates authentication, parsing, and serialization modules to
produce one user XML index plus one GPX file per trip.
"""

import argparse
import os
import shutil
from urllib.parse import urljoin

from fp_config import BASE_URL
from fp_utils import login, create_browser_page, load_page, download_image
from fp_parsers import parse_profile, parse_trips, parse_trip
from fp_writers import build_trip_gpx, build_user_xml, build_merged_xml

# ##############################################################################################
# scrapper
# ##############################################################################################


def process_profile(profile_id, username, password, args):
    """! @brief Run end-to-end scraping workflow for one profile.
    @param profile_id Profile ID to scrape.
    @param username Username for authentication.
    @param password Password for authentication.
    @param args Parsed CLI arguments (output options, flags).
    @return None
    @exception RuntimeError Raised when requested single trip slug is not found.
    """

    session = login(username, password)
    playwright, browser, page = create_browser_page(session)

    output_dir = os.path.join(args.output, profile_id)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Parse profile
        print(f"Parsing profile [{profile_id}] ...")

        soup = load_page(page, urljoin(BASE_URL, profile_id), output_dir, save_html=args.save_html)

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

                # Preserve route track points by seeding target GPX from downloaded trip GPX.
                downloaded_trip_gpx = os.path.join(trip_dir, trip["slug"] + ".gpx")
                if os.path.exists(downloaded_trip_gpx):
                    shutil.copyfile(downloaded_trip_gpx, trip_gpx)

                build_trip_gpx(trip_gpx, user_data, trip, footprints, args.elevation)

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


def scrapper(args):
    """! @brief Run scraping workflow for one or more profiles.
    @param args Parsed CLI arguments (profiles triplets, output options).
    @return None
    """
    # Parse profile triplets (id, username, password)
    profiles = args.profile if args.profile else []
    
    if not profiles:
        print("ERROR: At least one --profile is required (format: --profile id username password)")
        return
    
    # Process each profile, collecting results for merged XML
    collected = []
    for idx, (profile_id, username, password) in enumerate(profiles):
        print(f"\n{'='*60}")
        print(f"Processing profile {idx + 1}/{len(profiles)}: {profile_id}")
        print(f"{'='*60}\n")
        
        try:
            result = process_profile(profile_id, username, password, args)
            if result is not None:
                collected.append(result)
        except Exception as e:
            print(f"\n❌ ERROR processing profile {profile_id}: {e}\n")

    # Write merged XML when multiple profiles were processed
    if len(collected) > 1:
        print(f"\n{'='*60}")
        print("Building merged XML for all profiles...")
        print(f"{'='*60}\n")
        merged_tree = build_merged_xml(collected)
        merged_xml = os.path.join(args.output, "profiles.xml")
        os.makedirs(args.output, exist_ok=True)
        merged_tree.write(merged_xml, encoding="utf-8", xml_declaration=True)
        print(f"✅ Merged XML: {merged_xml}")

# ##############################################################################################
# __main__
# ##############################################################################################


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
                prog='FindPenguins scrapper',
                description='Scrap one or more FindPenguins profiles')

    parser.add_argument("--profile", action='append', nargs=3, required=True, metavar=('ID', 'USERNAME', 'PASSWORD'),
                        help="Profile triplet: id username password (can be used multiple times)")
    parser.add_argument("-o", "--output", default="output", help="Output folder")
    parser.add_argument("-t", "--trip", default=None, help="Trip slug to parse only")
    parser.add_argument("--elevation", action="store_true", help="Adjust tracks elevation")
    parser.add_argument("--save-html", action="store_true", help="Save fetched HTML files")

    arguments = parser.parse_args()

    scrapper(arguments)
