#!/usr/bin/env python3
"""Generate Pelican trip and footprint articles from a FindPenguins archive."""

from pathlib import Path

from fp_archive import read_json, read_trip
from fp_writers import build_trip_rst


def convert(output, content, trip_slug=None):
    """! @brief Regenerate Pelican RST articles from the manifests of an archive.
    @param output Archive directory containing `*/profile.json` and `*/*/trip.json`.
    @param content Pelican articles destination directory.
    @param trip_slug Optional trip slug; when given only that trip is converted.
    @return None
    @throws ValueError When no profile manifest exists or the requested slug is not found.
    """
    root = Path(output)
    profiles = sorted(root.glob("*/profile.json"))
    if not profiles:
        raise ValueError(f"No profile manifests found in {root}; scrape again to create them")
    count = 0
    for profile_path in profiles:
        profile = read_json(profile_path)
        for trip_path in sorted(profile_path.parent.glob("*/trip.json")):
            trip = read_trip(root, trip_path)
            if trip_slug and trip.get("slug") != trip_slug:
                continue
            build_trip_rst(str(content), str(trip_path.parent), profile["user"], trip,
                           trip.get("footprints", []), profile["sizes"])
            count += 1
    if trip_slug and not count:
        raise ValueError(f"No archived trip found with slug: {trip_slug}")
    print(f"Generated articles for {count} trip(s)")
