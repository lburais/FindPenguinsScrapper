# FindPenguinsScrapper Implementation Guide

This guide documents the current CLI, scraping pipeline and output behavior.

## Entry Point and CLI

Main script: `findpenguins_scrapper.py`.

Usage: `python findpenguins_scrapper.py profiles.json [--output DIR] [--content DIR] [-t SLUG] [--save-html] [--force]`.
It maps profile names to objects with `id`, `username`, and optional `password`; every profile is
scraped. `--output` (default `output`) is the archive directory for XML, GPX and downloaded media,
`--content` (default `../website/content/articles/findpenguins`) the Pelican articles directory,
`-t`/`--trip SLUG` scrapes only the matching trip slug (default: all trips), `--save-html` saves
fetched source HTML for debugging, and `--force` clears the output and content folders first (only
the selected trip's folders and GPX when `--trip` is given). An optional `settings` entry configures the rest:

| Setting | Behavior |
|---------|----------|
| `small_size` | Max side in px of profile/companion pictures (stored in place of the original); default `128`. |
| `large_size` | Max side in px of maps, the `_large` trip cover and `_thumb` photos; default `1600`. |
| `map_background` | Route-map background: `transparent` (default), `satellite`, or `street`. |
| `footprint_bubbles` | Draw numbered footprint locations on the route map; default `false`. |

## Scraping and Serialization Flow

1. `login(username, password)` in `fp_utils.py` logs in with a `requests.Session`.
2. `create_browser_page(session)` starts Playwright Chromium and transfers the session cookies.
3. `parse_profile` and `parse_trips` load profile metadata and the selected trip list.
4. For each trip, `parse_trip` loads all footprint pages and downloads route GPX and media.
   `parse_trip_insights` extracts trip description, countries, distances, transports and current
   trip companions; `parse_trip_image` finds the trip cover image.
5. `build_trip_gpx` preserves the downloaded track, rebuilds coordinate-bearing waypoints, writes
   trip and footprint extensions, and enriches track-point elevations.
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
- OpenTopoData SRTM90m elevation enrichment is always performed.

See [`xml-gpx-structure.md`](./xml-gpx-structure.md) for the serialized structure and
[`data-fields.md`](./data-fields.md) for field provenance.

## Pelican Article Export

Originals are kept and resized lossless WebP variants (never upscaled) are created next to them.
Companions are represented by their profile picture (`<uid>/<uid>_profile_*.webp`, downloaded once
and shared by all trips), shrunk in place to `small_size`. `TripImage` uses `_large`; `TripMap` (`map_trip.webp`) and `map_country.webp` are shrunk in place to `large_size`. Footprint photos keep the original in `Photo`; the theme derives the `_thumb` variant (`large_size`) from each name for thumbnails and the carousel.

The scraper always generates, under `--content`:

- `<content>/<uid>/<trip-slug>/trip.rst` with trip index metadata, copied cover/map images and
  companion metadata.
- `<content>/<uid>/<trip-slug>/footprint_N/footprint.rst` for each footprint, with copied photos,
  videos and attachments. Each geolocated footprint also gets a `map_country.webp`.

The RST export does not generate a user/profile page or a global FindPenguins index. A consuming
Pelican site can build its own index from trip pages using their `Category: findpenguins` and trip metadata (`Date`, `EndDate`, `Transport`).
The `TripMap` is generated as `map_trip.webp` from the GPX track after the GPX is finalized.

Trip maps are 1200×800 WebP images with a white 4px route line. Their background defaults to transparent;
`map_background: satellite` or `street` requests an Esri map image. These backgrounds require
network access. Footprint bubbles are omitted by default and enabled with
`footprint_bubbles`. When no valid route exists, no map is generated.

Trip RST metadata retains values used by an index (including period, duration, distance,
countries, description, cover, route map and companions). It has no body sections for insights or
footprint links. Country names are individual tags; transport mode distances are combined into the
`Transport` field.

## Operational Notes

- Playwright requires an installed Chromium browser; install it with
  `python -m playwright install chromium` in the same Python environment as the project.
- Missing optional fields are omitted from output.
- A failed media download is logged and that media item is skipped.
- Do not commit credential files such as `profiles.json`.
