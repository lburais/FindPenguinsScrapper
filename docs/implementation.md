# FindPenguinsScrapper Implementation Guide

This document explains the end-to-end implementation flow in the current codebase.

## Entry Point and CLI

Main script: `findpenguins_scrapper.py`

Arguments:

- `--id`: FindPenguins profile id (required).
- `--username`: account login username/email.
- `--password`: account password.
- `--output`: output folder (default is `output`, currently workflow writes to `output/<id>` directly).
- `--trip`: optional trip slug filter.
- `--save-html`: store fetched HTML pages locally for debugging.

## Step-by-Step Flow

1. Authenticate

- `login(username, password)` in `fp_utils.py`:
  - GET login page to retrieve CSRF token.
  - POST credentials and CSRF token.
  - Keep authenticated cookies in requests session.

2. Create browser context

- `create_browser_page(session)`:
  - Starts Playwright Chromium (headless).
  - Injects requests cookies into browser context.
  - Uses same authenticated state for dynamic pages.

3. Parse profile page

- Load `https://findpenguins.com/<id>` with `load_page(...)`.
- `parse_profile(soup)` extracts user fields:
  - name, bio, location, website, picture
- Profile picture is downloaded to local output directory when present.

4. Parse trip list

- `parse_trips(soup, tripid)` extracts trip metadata:
  - slug, title, period, days, km, current flag, url, companions
- If `--trip` is set, list is filtered to one slug.

5. Process each trip

For each trip:

- Create trip working directory: `output/<uid>/<trip-slug>/`.
- Load trip page using Playwright + BeautifulSoup.
- `parse_trip(...)` does:
  - download official travel-route GPX endpoint using internal trip id
  - parse all footprint URLs/ids
  - open each footprint page
  - extract title, date, text, private text, links, weather, location, coordinates
  - download footprint photos
- The downloaded GPX is copied to `output/<uid>/<trip-slug>.gpx` when available.

6. Build enriched trip GPX

- `build_trip_gpx(gpx_path, user_data, trip, footprints)`:
  - parses existing GPX file if present, otherwise creates new GPX root
  - ensures metadata section and author/link fields
  - writes trip metadata extensions
  - clears old waypoints and rebuilds from footprints
  - preserves original `trk` elements and re-appends them after `wpt`
  - enriches `trkpt` elevations via `fetch_elevations(...)`
  - computes nearest `trkpt` for each `wpt` and copies:
    - `time` to waypoint
    - matched point as custom `<trkpt lat="..." lon="..."/>` inside waypoint extensions

7. Build user XML index

- `build_user_xml(user_data, trips)`:
  - writes profile root fields
  - writes all trips with URL, slug, title, companion IDs, and relative GPX filename

8. Persist outputs

- User XML: `output/<uid>/<uid>.xml`
- Trip GPX files: `output/<uid>/<trip-slug>.gpx`

## Parsing Details Worth Knowing

- Dynamic footprint loading uses repeated click on `#footprintListLoadMore`.
- Popup metadata (weather, overnights, altitude, places) is parsed from menu modal HTML.
- Coordinates can come from JavaScript (`initMap(lat,lon)`) and from place coordinate tags.
- Private text processing extracts special links:
  - Park4Night URL to dedicated field
  - Wikipedia links to repeated list

## GPX Writer Behavior

- Namespace: GPX 1.1 (`http://www.topografix.com/GPX/1/1`).
- GPX extensions for footprint-specific fields are written as non-namespaced child tags under namespaced `<extensions>`.
- Existing track geometry is kept; only waypoints are regenerated.
- Metadata author is always refreshed from current profile data.

## Operational Notes

- The script continues when one trip fails and still emits XML.
- Missing fields are omitted (writer skips empty values).
- Elevation enrichment failures are logged as warnings and do not block output generation.
