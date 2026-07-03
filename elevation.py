import requests
import time
from math import radians, sin, cos, sqrt, atan2

OPENTOPODATA_URL = "https://api.opentopodata.org/v1/srtm90m"
COPERNICUS_URL = "https://api.open-meteo.com/v1/elevation"


# ---------------------------------------------------------
# Distance
# ---------------------------------------------------------

def haversine(lat1, lon1, lat2, lon2):

    R = 6371000

    dlat = radians(lat2-lat1)
    dlon = radians(lon2-lon1)

    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2

    return 2*R*atan2(sqrt(a), sqrt(1-a))


# ---------------------------------------------------------
# Elevation API
# ---------------------------------------------------------

def fetch_elevations(points, source="opentopodata"):

    print("Downloading elevations...")

    batch = 100
    max_retries = 5
    provider = (source or "opentopodata").strip().lower()

    if provider not in ("opentopodata", "copernicus"):
        raise ValueError(f"Unsupported elevation source: {source}")

    for i in range(0, len(points), batch):

        subset = points[i:i+batch]

        locations = "|".join(f"{p['lat']},{p['lon']}" for p in subset)
        latitudes = ",".join(str(p["lat"]) for p in subset)
        longitudes = ",".join(str(p["lon"]) for p in subset)

        print(f"  - Retrieving {len(subset)} points at {i}...")

        data = None
        for retry in range(max_retries):
            if provider == "opentopodata":
                r = requests.get(
                    OPENTOPODATA_URL,
                    params={"locations": locations},
                    timeout=30,
                )
            else:
                r = requests.get(
                    COPERNICUS_URL,
                    params={"latitude": latitudes, "longitude": longitudes},
                    timeout=30,
                )

            if r.status_code == 429:
                if retry == max_retries - 1:
                    r.raise_for_status()
                wait_seconds = 2 ** retry
                print(f"Rate limited by elevation API, retrying in {wait_seconds}s ...")
                time.sleep(wait_seconds)
                continue

            r.raise_for_status()
            if provider == "opentopodata":
                data = r.json()["results"]
            else:
                elevations = r.json().get("elevation", [])
                data = [{"elevation": ele} for ele in elevations]
            break

        if data is None:
            raise RuntimeError("Unable to retrieve elevations after retries")

        for p, e in zip(subset, data):
            p["ele"] = e["elevation"]


# ---------------------------------------------------------
# Smooth elevations
# ---------------------------------------------------------

def smooth(points):

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

    gain = 0
    loss = 0

    for p1, p2 in zip(points[:-1], points[1:]):

        d = p2["ele"] - p1["ele"]

        if d > 0:
            gain += d
        else:
            loss -= d

    return gain, loss


# ---------------------------------------------------------
# Distance
# ---------------------------------------------------------

def total_distance(points):

    d = 0

    for p1, p2 in zip(points[:-1], points[1:]):

        d += haversine(
            p1["lat"],
            p1["lon"],
            p2["lat"],
            p2["lon"]
        )

    return d


