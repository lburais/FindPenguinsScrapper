"""Portable manifests for converting FindPenguins archives independently."""

import copy
import json
import os
import tempfile


def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".manifest-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def write_profile(profile_dir, user, settings):
    _write_json(os.path.join(profile_dir, "profile.json"), {
        "version": 1,
        "user": user,
        "sizes": {"small": settings["small_size"], "large": settings["large_size"]},
    })


def write_trip(output, trip_dir, trip):
    portable = copy.deepcopy(trip)
    root = os.path.abspath(output)
    for footprint in portable.get("footprints", []):
        for field in ("photos", "videos", "gpx", "pdf"):
            paths = []
            for path in footprint.get(field, []):
                absolute = os.path.abspath(path)
                if os.path.commonpath((root, absolute)) != root:
                    raise ValueError(f"Media outside archive: {path}")
                paths.append(os.path.relpath(absolute, root))
            footprint[field] = paths
    _write_json(os.path.join(trip_dir, "trip.json"), {"version": 1, "trip": portable})


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError(f"Unsupported manifest: {path}")
    return data


def read_trip(output, path):
    trip = read_json(path)["trip"]
    root = os.path.realpath(output)
    for footprint in trip.get("footprints", []):
        for field in ("photos", "videos", "gpx", "pdf"):
            paths = []
            for path_value in footprint.get(field, []):
                path = os.path.realpath(os.path.join(root, path_value))
                if os.path.commonpath((root, path)) != root:
                    raise ValueError(f"Media outside archive: {path_value}")
                paths.append(path)
            footprint[field] = paths
    return trip
