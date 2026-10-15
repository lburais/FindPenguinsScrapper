#!/usr/bin/env python3
"""! @file findpenguins_scrapper.py
@brief CLI entrypoint and orchestration for FindPenguins scraping/export.

This script coordinates authentication, parsing, and serialization modules to
produce one user XML index plus one GPX file per trip.
"""

import argparse
import json
import os
import shutil
import sys
from urllib.parse import urljoin

from fp_config import BASE_URL
from fp_utils import login, create_browser_page, load_page, download_image
from fp_parsers import parse_profile, parse_trips, parse_trip, parse_trip_insights, parse_trip_image
from fp_writers import (
    build_trip_gpx,
    build_user_xml,
    build_merged_xml,
    build_trip_html,
    build_user_html,
    build_global_html,
    build_trip_rst,
    build_user_rst,
)

# ##############################################################################################
# process_profile
# ##############################################################################################


def process_profile(profile_id, username, password, output, trip_slug, elevation, save_html):
    """! @brief Run end-to-end scraping workflow for one profile.
    @param profile_id Profile ID to scrape.
    @param username Username for authentication.
    @param password Password for authentication.
    @param output Root output directory.
    @param trip_slug Optional slug of the only trip to scrape.
    @param elevation Whether to adjust track elevations.
    @param save_html Whether to save downloaded HTML for debugging.
    @return Tuple containing profile data and its scraped trips.
    @exception RuntimeError Raised when requested single trip slug is not found.
    """

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

                build_trip_gpx(trip_gpx, user_data, trip, footprints, elevation)

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

def scrapper(profile, profile_name, credentials, output, trip_slug, elevation, save_html):
    """! @brief Run scraping workflow for one or more profiles.
    @param profile Profile triplets supplied directly on the command line.
    @param profile_name Optional credential profile names to scrape.
    @param credentials JSON credentials file path.
    @param output Root output directory.
    @param trip_slug Optional slug of the only trip to scrape.
    @param elevation Whether to adjust track elevations.
    @param save_html Whether to save downloaded HTML for debugging.
    @return List of (user_data, trips) tuples for successfully scraped profiles.
    """
    # Parse profile triplets (id, username, password)
    profiles = list(profile or [])

    # Profiles from the credentials file: selected by name, or all when no name is given
    if profile_name or not profiles:
        with open(credentials, encoding="utf-8") as f:
            known = json.load(f)
        names = profile_name or list(known)
        for name in names:
            if name not in known:
                print(f"ERROR: Unknown profile name '{name}' in {credentials}")
                return []
            entry = known[name]
            profiles.append((entry["id"], entry["username"], entry.get("password", "")))

    if not profiles:
        print("ERROR: No profile given (use --profile, --profile-name or a credentials file)")
        return []
    
    # Process each profile, collecting results for merged XML
    collected = []
    for idx, (profile_id, username, password) in enumerate(profiles):
        print(f"\n{'='*60}")
        print(f"Processing profile {idx + 1}/{len(profiles)}: {profile_id}")
        print(f"{'='*60}\n")
        
        try:
            result = process_profile(
                profile_id,
                username,
                password,
                output,
                trip_slug,
                elevation,
                save_html,
            )
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
        merged_xml = os.path.join(output, "profiles.xml")
        os.makedirs(output, exist_ok=True)
        merged_tree.write(merged_xml, encoding="utf-8", xml_declaration=True)
        print(f"✅ Merged XML: {merged_xml}")
    return collected


# ##############################################################################################
# generate_html_outputs
# ##############################################################################################

def generate_html_outputs(output, profiles_data, html_output=None):
    """! @brief Generate HTML outputs after all scraping completes.
    @param output Root output directory.
    @param profiles_data List of (user_data, trips) tuples returned by scrapper.
    @param html_output Optional root directory for generated HTML pages.
    @return None
    """

    if not profiles_data:
        return

    html_output = html_output or output
    print("\nGenerating HTML output(s)...")
    for user_data, trips in profiles_data:
        output_dir = os.path.join(html_output, user_data["uid"])
        asset_dir = os.path.join(output, user_data["uid"])
        for trip in trips:
            trip_dir = os.path.join(output_dir, trip["slug"])
            footprints = trip.get("footprints", [])
            build_trip_html(trip_dir, trip, footprints)

        build_user_html(output_dir, user_data, trips, asset_dir=asset_dir)

    if len(profiles_data) > 1:
        build_global_html(html_output, profiles_data, assets_dir=output)


def generate_rst_outputs(content_dir, output, profiles_data):
    """! @brief Generate Pelican-compatible reStructuredText after scraping.
    @param content_dir Pelican pages source directory.
    @param output Root directory containing scraped profile assets.
    @param profiles_data List of (user_data, trips) tuples returned by scrapper.
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

        build_user_rst(content_dir, profile_dir, user_data, trips)


def prompt_for_profile_names(credentials):
    """! @brief Prompt for one or more named profiles from a credentials file.
    @param credentials JSON credentials file path.
    @return Selected profile names, or all names when the selection is empty.
    """
    with open(credentials, encoding="utf-8") as f:
        known_profiles = json.load(f)

    if not isinstance(known_profiles, dict) or not known_profiles:
        raise ValueError(f"No profiles found in {credentials}")

    profile_names = list(known_profiles)
    print("Available profiles:")
    for name in profile_names:
        print(f"  - {name}")

    while True:
        selection = input("Profile name(s), comma-separated (Enter for all): ").strip()
        if not selection:
            return profile_names

        selected_names = [name.strip() for name in selection.split(",") if name.strip()]
        unknown_names = [name for name in selected_names if name not in known_profiles]
        if unknown_names:
            print(f"Unknown profile(s): {', '.join(unknown_names)}")
            continue
        if selected_names:
            return selected_names


# ##############################################################################################
# __main__
# ##############################################################################################


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
                prog='FindPenguins scrapper',
                description='Scrap one or more FindPenguins profiles')

    parser.add_argument("--profile", action='append', nargs=3, metavar=('ID', 'USERNAME', 'PASSWORD'),
                        help="Profile triplet: id username password (can be used multiple times)")
    app_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    parser.add_argument("--credentials", default=os.path.join(app_dir, "profiles.json"),
                        help="JSON file mapping profile names to {id, username, password}")
    parser.add_argument("--profile-name", action='append', metavar='NAME',
                        help="Profile name from the credentials file (can be used multiple times; default: all)")
    parser.add_argument("-o", "--output", default="output", help="Output folder")
    parser.add_argument("-t", "--trip", default=None, help="Trip slug to parse only")
    parser.add_argument("--no-elevation", dest="elevation", action="store_false", default=True, help="Skip track elevation adjustment (enabled by default)")
    parser.add_argument("--save-html", action="store_true", help="Save fetched HTML files")
    parser.add_argument("--html", metavar="PATH", help="Generate HTML travel book pages under PATH (default: --output)")
    parser.add_argument("--rst", metavar="PATH", help="Generate Pelican reStructuredText pages under PATH")

    arguments = parser.parse_args()

    if not arguments.profile and not arguments.profile_name:
        if not sys.stdin.isatty():
            parser.error("provide --profile/--profile-name or run without them in an interactive terminal")
        try:
            arguments.profile_name = prompt_for_profile_names(arguments.credentials)
        except FileNotFoundError:
            parser.error(
                f"credentials file not found: {arguments.credentials}; provide --credentials or use --profile"
            )
        except ValueError as exc:
            parser.error(str(exc))

    profiles_data = scrapper(
        arguments.profile,
        arguments.profile_name,
        arguments.credentials,
        arguments.output,
        arguments.trip,
        arguments.elevation,
        arguments.save_html,
    )
    if arguments.html is not None:
        generate_html_outputs(arguments.output, profiles_data, arguments.html)
    if arguments.rst:
        generate_rst_outputs(arguments.rst, arguments.output, profiles_data)
