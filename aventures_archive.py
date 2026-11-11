"""Read and resolve manifests for aventures2rst conversion."""

import json
import os

def read_json(path):
    """! @brief Load a manifest and check it is a version 1 JSON object.
    @param path Manifest file path.
    @return Parsed dictionary.
    @throws ValueError When the manifest is not an object with `version` equal to 1.
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError(f"Unsupported manifest: {path}")
    return data


def read_trip(output, path):
    """! @brief Load a trip manifest and resolve its relative media paths to absolute ones.
    @param output Archive root directory (it may have been moved since the scrape).
    @param path Path of the `trip.json` file.
    @return Trip dictionary with absolute media paths.
    @throws ValueError When the manifest is invalid or a media path escapes the archive.
    """
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


