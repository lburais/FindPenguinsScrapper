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
from fp_utils import login, create_browser_page, load_page
from fp_parsers import parse_profile, parse_trips, parse_trip
from fp_writers import build_trip_gpx, build_user_xml

# ##############################################################################################
# scrapper
# ##############################################################################################


def scrapper(args):
    """! @brief Run end-to-end scraping workflow for one profile.
    @param args Parsed CLI arguments (id, credentials, output options).
    @return None
    @exception RuntimeError Raised when requested single trip slug is not found.
    """

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

                # Preserve route track points by seeding target GPX from downloaded trip GPX.
                downloaded_trip_gpx = os.path.join(trip_dir, trip["slug"] + ".gpx")
                if os.path.exists(downloaded_trip_gpx):
                    shutil.copyfile(downloaded_trip_gpx, trip_gpx)

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
