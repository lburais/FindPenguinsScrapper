# scrapers Implementation Guide

This guide documents the current CLI, scraping pipeline and output behavior.

## Entry Point and CLI

Main scripts: `findpenguins.py` and `aventures2rst.py`.

After installation, use `findpenguins profiles.json [--output DIR] [-t SLUG] [--force] [--skip]`, followed by `aventures2rst --output DIR [--content DIR] [-t SLUG]`. The original `python findpenguins.py` and `python aventures2rst.py` invocations remain available from the checkout.
It maps profile names to objects with `id`, `username`, and optional `password`; every profile is
scraped. `--output` (default `output`) is the archive directory for XML, GPX and downloaded media,
the converter's `--content` (default `../website/content/articles/findpenguins`) the Pelican articles directory,
`-t`/`--trip SLUG` scrapes only the matching trip slug (default: all trips). Fetched source HTML
and footprint popup data are always saved, and `--force` clears the archive first (only
the selected trip's folder and GPX when `--trip` is given). The content directory is not cleared.

`--skip` reads previously saved profile, trip, footprint and insights HTML instead of
navigating, and overrides `--force`. Run a scrape first to save snapshots;
missing required snapshots stop the run without fetching them. Current snapshots are
named by URL, with support for older title-based HTML files. Footprint popup results
are saved separately as JSON; older snapshots without them produce a warning and
empty popup fields. The existing enriched trip GPX is reused. Skip does not prevent
network access for missing media, map imagery or elevation data.

An optional `settings` entry configures the rest:

| Setting | Behavior |
|---------|----------|
| `small_size` | Max side in px of profile/companion pictures (stored in place of the original); default `128`. |
| `large_size` | Max side in px of maps, the trip cover and `_thumb` photos; default `1600`. |
| `map_background` | Route-map background: `transparent` (default), `satellite`, or `street`. |
| `footprint_bubbles` | Draw numbered footprint locations on the route map; default `false`. |

## Scraping and Serialization Flow

1. `login(username, password)` in `fp_utils.py` logs in with a `requests.Session`.
2. `create_browser_page(session)` starts Playwright Chromium and transfers the session cookies.
3. `parse_profile` and `parse_trips` load profile metadata and the selected trip list.
4. For each trip, `parse_trip` loads all footprint pages and downloads route GPX and media.
   `parse_trip_insights` extracts trip description, countries, distances, transports and current
   trip companions; `parse_trip_image` finds the trip cover image. Country and footprint flag
   URLs are downloaded to `<output>/flags/`, cached by URL, and referenced relative to the output root.
5. `build_trip_gpx` preserves the downloaded track, rebuilds coordinate-bearing waypoints, writes
   trip and footprint extensions, and enriches track-point elevations.
6. Route maps are generated after the final GPX update when it contains a valid track.
7. The profile XML index is updated with the trip and companion data.
8. Profile and per-trip JSON manifests preserve the parsed fields and archive-relative media paths.
9. `aventures2rst.py` reads these manifests and generates RST independently. Older XML/GPX-only
   archives must be scraped again or rebuilt with saved snapshots.

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
and shared by all trips), shrunk in place to `small_size`. `TripImage` (`cover_trip.webp`),
`TripMap` (`map_trip.webp`), `TripSatelliteMap` (`satellite_trip.webp`) and `map_country.webp`
are shrunk in place to `large_size`. Footprint photos keep the original in `Photo`; the theme
derives the `_thumb` variant (`large_size`) from each name for thumbnails and the carousel.

The converter generates, under `--content`:

- `<content>/<uid>/<trip-slug>/trip.rst` with trip index metadata, copied cover/map images and
  companion metadata.
- `<content>/<uid>/<trip-slug>/footprint_N/footprint.rst` for each footprint, with copied photos,
  videos and attachments. Each geolocated footprint also gets a `map_country.webp`.
- `<content>/flags/` contains the shared flags used by all exported trips. The website publishes
  them under its output root `flags/`; failed flag downloads are reported and omitted.

The RST export does not generate a user/profile page or a global FindPenguins index. A consuming
Pelican site can build its own index from trip pages using their `Category: findpenguins` and trip metadata (`Date`, `EndDate`, `Transport`).
The `TripMap` is generated as `map_trip.webp` from the GPX track after the GPX is finalized.
The separate `TripSatelliteMap` is generated as `satellite_trip.webp`, always with an Esri
satellite background and numbered footprint bubbles. Each map is generated independently;
a satellite request failure is reported without discarding the main map.

Trip maps are 1200×800 WebP images with a white 4px route line. Their background defaults to transparent;
`map_background: satellite` or `street` requests an Esri map image. These backgrounds require
network access. Footprint bubbles are omitted by default and enabled with
`footprint_bubbles`. When no valid route exists, no map is generated.

Trip RST metadata retains values used by an index (including period, duration, distance,
countries, description, cover, route map and companions). It has no body sections for insights or
footprint links. Country names are individual tags; transport mode distances are combined into the
`Transport` field.

## Operational Notes

- `reminder.py --list NAME --output DIR [--all] [--force]` currently prepares the output directory
  (`--force` clears it after `output_safety.validate_clear_directory`) and prints the
  `rem export --list NAME --format json --incomplete > DIR/reminders.json` command to run in a
  terminal; the direct `rem` invocation is commented out in `export_reminders`, so `--all` has no
  effect for now. `reminders2rst.py --output DIR [--content DIR]` writes one stable-named
  article per reminder, category `reminder`. Neither converter deletes stale articles.

- Playwright requires an installed Chromium browser; install it with
  `python -m playwright install chromium` in the same Python environment as the project.
- Missing optional fields are omitted from output.
- A failed media download is logged and that media item is skipped.
- Do not commit credential files such as `profiles.json`.
