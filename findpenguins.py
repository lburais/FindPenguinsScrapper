from urllib.parse import urljoin, urlparse

import argparse
import hashlib
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
import requests

from fp_config import BASE_URL
from fp_utils import login, create_browser_page, load_page, download_image, SnapshotError
from fp_parsers import parse_profile, parse_trips, parse_trip, parse_trip_insights, parse_trip_image
from fp_writers import (
    build_trip_gpx,
    save_trip_route_map,
    build_user_xml,
    build_merged_xml,
)
from fp_archive import write_profile, write_trip
from output_safety import validate_clear_directory, validate_component

## Default run settings; override them with a "settings" entry in the profiles file.
DEFAULT_SETTINGS = {
    "small_size": 128,
    "large_size": 1600,
    "map_background": "transparent",
    "footprint_bubbles": False,
}

# ##############################################################################################
# process_profile
# ##############################################################################################

def download_trip_flags(output, trip, footprints):
    """Download flags once per source URL and store archive-root-relative paths."""
    for entry in [*(trip.get("countries") or []), *footprints]:
        flag_url = str(entry.get("flag") or "").strip()
        if not flag_url:
            continue
        try:
            parsed = urlparse(flag_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("flag URL must be an absolute HTTP(S) URL")
            stem = os.path.splitext(os.path.basename(parsed.path))[0]
            stem = re.sub(r"[^a-z0-9-]+", "-", stem.lower()).strip("-") or "flag"
            digest = hashlib.sha256(flag_url.encode("utf-8")).hexdigest()[:16]
            path = download_image(flag_url, os.path.join(output, "flags"), filename=f"{stem}-{digest}")
            entry["flag"] = os.path.relpath(path, output).replace(os.sep, "/")
        except (OSError, ValueError, requests.RequestException) as exc:
            print(f"  WARNING: flag download failed for {flag_url}: {exc}")
            entry["flag"] = ""


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
    skip = settings.get("skip", False)
    trip_slug = settings["trip"]
    map_background = settings["map_background"]
    show_footprint_bubbles = settings["footprint_bubbles"]

    if skip:
        session = page = playwright = browser = None
    else:
        session = login(username, password)
        playwright, browser, page = create_browser_page(session)

    output_dir = os.path.join(output, profile_id)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Parse profile
        print(f"Parsing profile [{profile_id}] ...")

        soup = load_page(page, urljoin(BASE_URL, profile_id), output_dir, skip=skip)

        user_data = parse_profile(soup)
        user_data["uid"] = profile_id
        user_data["email"] = username or ""
        profile_picture_url = str(user_data.get("picture", "")).strip()
        if profile_picture_url:
            try:
                local_picture = download_image(profile_picture_url, output_dir, prefix=f"{profile_id}_profile")
                user_data["picture"] = os.path.relpath(local_picture, output_dir)
            except SnapshotError:
                raise
            except Exception as e:
                print(f"  WARNING: profile picture download failed: {e}")

        trips = parse_trips(soup, profile_id)
        write_profile(output_dir, user_data, settings)

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

                soup = load_page(page, trip["url"], trip_dir, skip=skip, title=trip["title"])

                image_url = parse_trip_image(soup)
                if image_url:
                    try:
                        local_image = download_image(image_url, trip_dir, filename="cover_trip", refresh=not skip)
                        trip["image"] = os.path.relpath(local_image, output_dir)
                    except Exception as e:
                        print(f"  WARNING: trip image download failed: {e}")

                photos_dir = trip_dir
                footprints = parse_trip(page, session, soup, trip_dir, photos_dir, skip=skip)
                trip["footprints"] = footprints
                insights, insights_companions = parse_trip_insights(
                    page, trip["url"], trip_dir, skip=skip
                )
                trip.update(insights)
                download_trip_flags(output, trip, footprints)
                if insights_companions:
                    for companion in insights_companions:
                        try:
                            # A companion is represented by its profile picture, shared by all trips.
                            local_avatar = download_image(
                                companion["avatar"],
                                os.path.join(output, companion["uid"]),
                                prefix=f"{companion['uid']}_profile",
                            )
                            companion["picture"] = os.path.relpath(local_avatar, output_dir)
                        except SnapshotError:
                            raise
                        except Exception as e:
                            print(f"  WARNING: companion picture download failed: {e}")
                    trip["companions"] = insights_companions
                trip_gpx = os.path.join(output_dir, trip["slug"] + ".gpx")
                trip["gpx"] = os.path.relpath(trip_gpx, output_dir)

                # Preserve route track points by seeding target GPX from downloaded trip GPX.
                downloaded_trip_gpx = os.path.join(trip_dir, trip["slug"] + ".gpx")
                if not skip and os.path.exists(downloaded_trip_gpx):
                    shutil.copyfile(downloaded_trip_gpx, trip_gpx)
                elif skip and not os.path.isfile(trip_gpx):
                    print(f"  WARNING: no saved trip GPX at {trip_gpx}; route track cannot be reused")

                build_trip_gpx(trip_gpx, user_data, trip, footprints)
                for key, filename, background, bubbles in (
                    ("route_map", "map_trip.png", map_background, show_footprint_bubbles),
                    ("satellite_map", "satellite_trip.png", "satellite", True),
                ):
                    try:
                        route_map = save_trip_route_map(
                            trip_gpx,
                            footprints,
                            os.path.join(trip_dir, filename),
                            background=background,
                            show_footprint_bubbles=bubbles,
                        )
                        if route_map:
                            trip[key] = os.path.relpath(route_map, output_dir)
                    except (OSError, ET.ParseError, ValueError, requests.RequestException) as exc:
                        print(f"  - WARNING: unable to create {filename} for {trip['title']}: {exc}")

                old_trip_gpx = os.path.join(trip_dir, trip["slug"] + ".gpx")
                if not skip and old_trip_gpx != trip_gpx and os.path.exists(old_trip_gpx):
                    os.remove(old_trip_gpx)

                write_trip(output, trip_dir, trip)
            except SnapshotError:
                raise
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
        if browser:
            browser.close()
        if playwright:
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


def clear_folders(output, profiles, trip=None):
    """Clear the archive, or the selected trip for each profile."""
    validate_clear_directory(output)

    if not trip:
        for folder in (output,):
            if os.path.isdir(folder):
                print(f"Clearing {folder}")
                shutil.rmtree(folder)
        return

    validate_component(trip)
    for profile_id, _, _ in profiles:
        validate_component(profile_id)
        for path in (
            os.path.join(output, profile_id, trip),
        ):
            if os.path.isdir(path):
                print(f"Clearing {path}")
                shutil.rmtree(path)
        gpx = os.path.join(output, profile_id, trip + ".gpx")
        if os.path.isfile(gpx):
            os.remove(gpx)


def scrapper(profiles_file, output, trip=None, force=False, skip=False):
    """Scrape profiles into the archive without generating Pelican articles."""
    profiles, settings = load_profiles(profiles_file)
    if force and skip:
        print("  --skip disables --force to preserve saved snapshots")
    if force and not skip:
        clear_folders(output, profiles, trip)
    settings.update(output=output, trip=trip, skip=skip)

    # Process each profile, collecting results for merged XML
    collected = []
    for idx, (profile_id, username, password) in enumerate(profiles):
        print(f"\n{'='*60}")
        print(f"Processing profile {idx + 1}/{len(profiles)}: {profile_id}")
        print(f"{'='*60}\n")

        try:
            collected.append(process_profile(profile_id, username, password, settings))
        except SnapshotError:
            raise
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
# __main__
# ##############################################################################################


def main():
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
        "-t", "--trip",
        default=None,
        help="Trip slug to scrape only (default: all trips)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Clear the output folder before scraping (only the --trip trip when given)")
    parser.add_argument(
        "--skip",
        action="store_true",
        help="Use saved HTML snapshots without navigating; disables --force")
    arguments = parser.parse_args()
    scrapper(arguments.profiles, arguments.output, arguments.trip, arguments.force, arguments.skip)


if __name__ == "__main__":
    main()
