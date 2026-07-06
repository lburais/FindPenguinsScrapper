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
from fp_writers import build_trip_gpx, build_user_xml
from relive import create_relive_video

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

    output_dir = os.path.join(args.output, args.id)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Parse profile
        print(f"Parsing profile [{args.id}] ...")

        soup = load_page(page, urljoin(BASE_URL, args.id), output_dir, save_html=args.save_html)

        user_data = parse_profile(soup)
        user_data["uid"] = args.id
        user_data["email"] = args.username or ""
        profile_picture_url = str(user_data.get("picture", "")).strip()
        if profile_picture_url:
            try:
                local_picture = download_image(profile_picture_url, output_dir, prefix=f"{args.id}_profile")
                user_data["picture"] = os.path.relpath(local_picture, output_dir)
            except Exception as e:
                print(f"  WARNING: profile picture download failed: {e}")

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

                build_trip_gpx(trip_gpx, user_data, trip, footprints, args.elevation)

                if args.relive:
                    relive_output = os.path.join(output_dir, trip["slug"] + ".mp4")
                    print(f"  - Building Relive video [{relive_output}] ...")
                    try:
                        create_relive_video(
                            gpx=trip_gpx,
                            photos=photos_dir,
                            title=trip.get("title", ""),
                            output=relive_output,
                            width=args.relive_width,
                            height=args.relive_height,
                            fps=args.relive_fps,
                            duration=args.relive_duration,
                            zoom=args.relive_zoom,
                            tile_cache=args.relive_tile_cache,
                        )
                    except Exception as e:
                        print(f"  WARNING: relive generation failed for [{trip['slug']}]: {e}")

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
    parser.add_argument("--elevation", action="store_true", help="Adjust tracks elevation")
    parser.add_argument("--save-html", action="store_true", help="Save fetched HTML files")
    parser.add_argument("--relive", action="store_true", help="Generate Relive-style MP4 for each processed trip")
    parser.add_argument("--relive-width", type=int, default=1280, help="Relive video width")
    parser.add_argument("--relive-height", type=int, default=720, help="Relive video height")
    parser.add_argument("--relive-fps", type=int, default=24, help="Relive video FPS")
    parser.add_argument("--relive-duration", type=int, default=45, help="Relive video duration in seconds")
    parser.add_argument("--relive-zoom", type=int, default=None, help="Relive map zoom level")
    parser.add_argument("--relive-tile-cache", default=".tile-cache", help="Relive tile cache directory")

    arguments = parser.parse_args()

    scrapper(arguments)
