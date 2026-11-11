"""! @file fp_elevation.py
@brief Elevation download, smoothing and gain/loss helpers for GPX track points.

Points are dictionaries with `lat`, `lon` and (once fetched) `ele` keys.
"""

import requests
import time
from math import radians, sin, cos, sqrt, atan2

OPENTOPODATA_URL = "https://api.opentopodata.org/v1/srtm90m"
COPERNICUS_URL = "https://api.open-meteo.com/v1/elevation"


# ---------------------------------------------------------
# Elevation API
# ---------------------------------------------------------

def fetch_elevations(points, source="opentopodata"):
    """! @brief Fill `ele` on each point from an elevation API, 100 points per request.

    HTTP 429 responses are retried up to 5 times with exponential backoff.
    @param points List of dicts with `lat`/`lon`; `ele` is set in place.
    @param source Elevation provider name; only "opentopodata" is supported.
    @return None
    @throws ValueError When the provider is unsupported.
    @throws RuntimeError When no data could be retrieved after retries.
    """

    print("Downloading elevations...")

    batch = 100
    max_retries = 5
    provider = (source or "opentopodata").strip().lower()

    if provider not in ("opentopodata"):
        raise ValueError(f"Unsupported elevation source: {source}")

    for i in range(0, len(points), batch):

        subset = points[i:i+batch]

        locations = "|".join(f"{p['lat']},{p['lon']}" for p in subset)
        latitudes = ",".join(str(p["lat"]) for p in subset)
        longitudes = ",".join(str(p["lon"]) for p in subset)

        data = None
        for retry in range(max_retries):
            if provider == "opentopodata":
                r = requests.get(
                    OPENTOPODATA_URL,
                    params={"locations": locations},
                    timeout=30,
                )

            if r.status_code == 429:
                if retry == max_retries - 1:
                    r.raise_for_status()
                wait_seconds = 2 ** retry
                if (wait_seconds > 1):
                    print(f"Rate limited by elevation API, retrying in {wait_seconds}s ...")
                time.sleep(wait_seconds)
                continue

            r.raise_for_status()
            if provider == "opentopodata":
                data = r.json()["results"]
            break

        if data is None:
            raise RuntimeError("Unable to retrieve elevations after retries")

        for p, e in zip(subset, data):
            p["ele"] = e["elevation"]


# ---------------------------------------------------------
# Smooth elevations
# ---------------------------------------------------------

def smooth(points):
    """! @brief Smooth `ele` values in place with a Savitzky-Golay filter (order 2, window <= 31).
    @param points List of dicts with `ele`; left untouched when fewer than 11 points.
    @return None
    """

    import numpy as np
    from scipy.signal import savgol_filter

    values = np.array([p["ele"] for p in points])

    if len(values) < 11:
        return

    window = min(31, len(values))

    if window % 2 == 0:
        window -= 1

    values = savgol_filter(values, window, 2)

    for p, v in zip(points, values):
        p["ele"] = float(v)


# ---------------------------------------------------------
# Gain/Loss
# ---------------------------------------------------------

def gain_loss(points):
    """! @brief Compute cumulative elevation gain and loss along a track.
    @param points Ordered list of dicts with `ele`.
    @return Tuple `(gain, loss)`, both non-negative.
    """

    gain = 0
    loss = 0

    for p1, p2 in zip(points[:-1], points[1:]):

        d = p2["ele"] - p1["ele"]

        if d > 0:
            gain += d
        else:
            loss -= d

    return gain, loss