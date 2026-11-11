"""Write portable FindPenguins archive manifests."""

import copy
import json
import os
import tempfile

def _write_json(path, value):
    """! @brief Atomically write `value` as indented UTF-8 JSON (temp file then rename).
    @param path Destination file; parent directories are created.
    @param value JSON-serializable object.
    @return None
    """
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
    """! @brief Write `profile.json` (version 1) with the user and image sizes.
    @param profile_dir Profile directory in the archive.
    @param user User dictionary as returned by the profile parser.
    @param settings Run settings providing `small_size` and `large_size`.
    @return None
    """
    _write_json(os.path.join(profile_dir, "profile.json"), {
        "version": 1,
        "user": user,
        "sizes": {"small": settings["small_size"], "large": settings["large_size"]},
    })


def write_trip(output, trip_dir, trip):
    """! @brief Write `trip.json` with media paths made relative to the archive root.
    @param output Archive root directory.
    @param trip_dir Trip directory receiving the manifest.
    @param trip Trip dictionary; it is deep-copied, the argument is not modified.
    @return None
    @throws ValueError When a photo, video, GPX or PDF path lies outside the archive.
    """
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


