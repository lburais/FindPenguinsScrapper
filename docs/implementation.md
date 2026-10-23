# FindPenguinsScrapper Implementation Guide

This guide documents the current CLI, scraping pipeline and output behavior.

## Entry Point and CLI

Main script: `findpenguins_scrapper.py`.

Profiles are selected in one of three ways:

- `--profile ID USERNAME PASSWORD` supplies credentials directly; repeat it for multiple profiles.
- `--profile-name NAME` selects a name from the credentials JSON; repeat it to select several.
- With neither option, an interactive prompt lists credential names and accepts comma-separated
  selections. Pressing Enter selects all profiles. This requires an interactive terminal.

The credentials JSON maps profile names to objects with `id`, `username`, and optional `password`
fields. `--credentials PATH` selects the file; its default is `profiles.json` beside the script.

Other options:

| Option | Behavior |
|--------|----------|
| `-o`, `--output PATH` | Archive directory for XML, GPX and downloaded media; default `output`. |
| `-t`, `--trip SLUG` | Scrape only the matching trip slug per selected profile. |
| `--no-elevation` | Skip default OpenTopoData enrichment of track-point elevations. |
| `--save-html` | Save fetched source HTML for debugging. |
| `--trip-map-background` | Route-map background: `transparent` (default), `satellite`, or `street`. |
| `--trip-map-footprint-bubbles` | Draw numbered footprint locations on the route map. |
| `--html PATH` | Generate the standalone HTML travel book under `PATH`. |
| `--rst PATH` | Generate Pelican-compatible trip and footprint sources under `PATH`. |

Without `--html` or `--rst`, the scraper generates XML/GPX and the archive media only.

## Scraping and Serialization Flow

1. `login(username, password)` in `fp_utils.py` logs in with a `requests.Session`.
2. `create_browser_page(session)` starts Playwright Chromium and transfers the session cookies.
3. `parse_profile` and `parse_trips` load profile metadata and the selected trip list.
4. For each trip, `parse_trip` loads all footprint pages and downloads route GPX and media.
   `parse_trip_insights` extracts trip description, countries, distances, transports and current
   trip companions; `parse_trip_image` finds the trip cover image.
5. `build_trip_gpx` preserves the downloaded track, rebuilds coordinate-bearing waypoints, writes
   trip and footprint extensions, and optionally enriches track-point elevations.
6. A route-map PNG is generated after the final GPX update when it contains a valid track.
7. The profile XML index is updated with the trip and companion data.
8. Optional HTML or RST outputs are generated after scraping completes.

Trip-level errors are logged and processing continues to later trips. Elevation and route-map
failures are reported as warnings and do not invalidate an otherwise successful GPX.

## XML and GPX

- One profile XML file is written to `<output>/<uid>/<uid>.xml`; multiple selected profiles also
  produce `<output>/profiles.xml`.
- One enriched GPX is written to `<output>/<uid>/<trip-slug>.gpx`.
- Track elements from the downloaded GPX are preserved. Existing waypoints are replaced with
  coordinate-bearing footprints.
- The closest track point supplies a footprint waypoint's time and custom matched-point extension.
- OpenTopoData SRTM90m elevation enrichment is enabled by default and can be disabled with
  `--no-elevation`.

See [`xml-gpx-structure.md`](./xml-gpx-structure.md) for the serialized structure and
[`data-fields.md`](./data-fields.md) for field provenance.

## Standalone HTML Export

`--html PATH` generates a profile landing page, one trip index per trip, and one HTML page per
footprint. With multiple profiles it also generates a global index. Trip maps and footprint links
are interactive Leaflet maps using OpenStreetMap tiles; Leaflet and tiles are loaded from external
services and therefore require network access.

Reference labels found in footprint text are rendered as external links. Downloaded photos are
included in the standalone travel book; downloaded videos remain in the archive and are copied
with the Pelican footprint sources.

## Pelican Source Export

`--rst PATH` generates:

- `<PATH>/<uid>/<trip-slug>/trip.rst` with trip index metadata, copied cover/map images and
  companion metadata.
- `<PATH>/<uid>/<trip-slug>/footprint_N/footprint.rst` for each footprint, with copied photos,
  videos and attachments. Each geolocated footprint also gets a `map_country.png`.

The RST export does not generate a user/profile page or a global FindPenguins index. A consuming
Pelican site can build its own index from trip pages using their `Category: Trips` and trip metadata.
The `TripMap` is generated as `map_trip.png` from the GPX track after the GPX is finalized.

Trip maps are 1200×800 PNGs with a white 4px route line. Their background defaults to transparent;
`--trip-map-background satellite` or `street` requests an Esri map image. These backgrounds require
network access. Footprint bubbles are omitted by default and enabled with
`--trip-map-footprint-bubbles`. When no valid route exists, no map is generated.

Trip RST metadata retains values used by an index (including period, duration, distance,
countries, description, cover, route map and companions). It has no body sections for insights or
footprint links. Country names are individual tags; transport mode distances are combined into one
`transport` tag.

## Operational Notes

- Playwright requires an installed Chromium browser; install it with
  `python -m playwright install chromium` in the same Python environment as the project.
- Missing optional fields are omitted from output.
- A failed media download is logged and that media item is skipped.
- Do not commit credential files such as `profiles.json`.
