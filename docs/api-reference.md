# scrapers API reference

Every function and class of the project, grouped by module. Functions prefixed with `_` are
module-private helpers. Full parameter and return documentation is in the Doxygen-style
docstrings of each function (`! @brief`, `@param`, `@return`).

## `findpenguins.py` — scraper CLI

| Function | Purpose |
|---|---|
| `download_trip_flags(output, trip, footprints)` | Download country/footprint flags once per URL into `<output>/flags/` and store archive-relative paths. |
| `process_profile(profile_id, username, password, settings)` | End-to-end scrape of one profile: login, trips, footprints, GPX, maps, XML and manifests. |
| `load_profiles(profiles_file)` | Read the profiles JSON file and split profiles from the optional `settings` entry. |
| `clear_folders(output, profiles, trip=None)` | Clear the archive, or only the selected trip of each profile (`--force`); validates paths via `output_safety`. |
| `scrapper(profiles_file, output, trip=None, force=False, skip=False)` | Scrape all profiles into the archive without generating Pelican articles. |
| `main()` | Parse CLI arguments and call `scrapper`. |

## `aventures2rst.py` — archive to Pelican

| Function | Purpose |
|---|---|
| `convert(output, content, trip_slug=None)` | Rebuild trip and footprint RST articles from `profile.json` / `trip.json` manifests. |
| `main()` | Parse CLI arguments and call `convert`. |

## `reminder.py` / `reminders2rst.py` — Apple Reminders

| Function | Purpose |
|---|---|
| `reminder.export_reminders(output, list_name, all_reminders=False, force=False)` | Prepare the output directory and print the `rem export` command (direct invocation currently disabled). |
| `reminder.main()` | Parse CLI arguments and call `export_reminders`. |
| `reminders2rst._metadata(value)` | Collapse whitespace so a value fits on one RST metadata line. |
| `reminders2rst.convert(output, content)` | Write one stable-named RST article per reminder from `reminders.json`. |
| `reminders2rst.main()` | Parse CLI arguments and call `convert`. |

## `output_safety.py` — destructive-operation guards

| Function | Purpose |
|---|---|
| `validate_clear_directory(directory)` | Reject symlinks, filesystem root, cwd, the project directory and the home directory. |
| `validate_component(value)` | Reject empty values, `.`/`..` and anything containing path separators. |

## `fp_archive.py` — portable JSON manifests

| Function | Purpose |
|---|---|
| `_write_json(path, value)` | Atomic JSON write (temporary file then rename). |
| `write_profile(profile_dir, user, settings)` | Write `profile.json` (user and image sizes). |
| `write_trip(output, trip_dir, trip)` | Write `trip.json` with media paths relative to the archive; rejects media outside it. |
| `read_json(path)` | Load a manifest and check it is a version 1 object. |
| `read_trip(output, path)` | Load `trip.json` and resolve media paths against the (possibly moved) archive root. |

## `fp_config.py` — constants

`BASE_URL`, `LOGIN_PAGE`, `LOGIN_POST`, `HEADERS`, `GPX_NS`, `XSI_NS`. No functions.

## `fp_elevation.py` — elevations

| Function | Purpose |
|---|---|
| `fetch_elevations(points, source="opentopodata")` | Fill `ele` for points (batches of 100, exponential backoff on HTTP 429). |
| `smooth(points)` | Savitzky-Golay smoothing of `ele` in place (skipped under 11 points). |
| `gain_loss(points)` | Cumulative `(gain, loss)` along a track. |

## `fp_parsers.py` — page parsing

| Function | Purpose |
|---|---|
| `apply_gpx_coordinates(footprints, gpx_path)` | Overwrite footprint coordinates with the matching GPX waypoints. |
| `apply_day_numbers(footprints)` | Set each footprint's `day` relative to the first footprint date. |
| `click_footprint_menu(page)` | Read weather/location metadata from the footprint popup menu. |
| `parse_profile(soup)` | Parse the user profile page. |
| `parse_trips(soup, tripid)` | Parse trip cards from a profile page. |
| `parse_footprints(soup)` | Parse footprint ids and URLs from a trip page. |
| `parse_trip_insights(page, trip_url, trip_dir, skip=False)` | Parse the Insights subpage (description, countries, distance, transports). |
| `parse_trip_image(soup)` | Extract the trip cover image URL. |
| `parse_trip(page, session, soup, trip_dir, photos_dir, skip=False)` | Parse a trip in depth and collect enriched footprints and media. |

## `fp_utils.py` — shared helpers

| Function | Purpose |
|---|---|
| `gpx_tag(name)` | Namespaced GPX tag name. |
| `add_text_element(parent, name, value, namespace=GPX_NS)` | Append a text child only when the value is non-empty. |
| `format_tree(tree)` | Indent an ElementTree with two spaces. |
| `clean_text(t)` | Normalize whitespace. |
| `strip_leading_flag(text)` | Remove a leading flag emoji. |
| `extract_private_references(text)` | Extract URL references from private notes. |
| `extract_expandable_text(node)` | Extract normalized text of expandable blocks. |
| `normalize_photo_url(img_url)` | Promote thumbnail URLs to large images. |
| `to_webp(path)` | Convert an image to lossless WebP and remove the source. |
| `variant_path(path, suffix)` | Path of a size variant (`a.webp` → `a_large.webp`). |
| `make_variant(path, suffix, max_size)` | Create a downscaled lossless WebP copy. |
| `shrink_image(path, max_size)` | Downscale a WebP in place. |
| `download_image(img_url, dest_folder, prefix="img", filename=None, refresh=False)` | Download an image. |
| `download_video(video_url, dest_folder, prefix="vid")` | Download a video (skipped if present). |
| `download_file(file_url, dest_folder, prefix="file", default_ext="")` | Download an attachment such as GPX or PDF. |
| `requests_cookies_to_playwright(session)` | Convert requests cookies to Playwright cookies. |
| `create_browser_page(session)` | Headless Chromium page seeded with the session cookies. |
| `click_load_more_until_done(page)` | Expand the footprint list until exhausted. |
| `login(username, password)` | Form-based FindPenguins login returning a session. |
| `SnapshotError` | Raised when a required saved HTML snapshot is missing or unusable. |
| `snapshot_path(page_url, outputdir, suffix="html")` | URL-hash-based snapshot path. |
| `_snapshot_slug(text)` | ASCII slug used to find legacy title-based snapshots. |
| `load_page(page, page_url, outputdir, skip=False, title="", footprint_id="")` | Load (or read from snapshot) a page and return BeautifulSoup. |
| `get_emoji_flag(code)` | Emoji flag for a country or subdivision code. |

## `fp_writers.py` — XML, GPX, maps and RST

| Function | Purpose |
|---|---|
| `_add_companion(parent, companion)` | Append a `<companion>` XML element. |
| `_add_trip_details(parent, trip)` | Append countries, distance and transports elements. |
| `distance_meters(lat1, lon1, lat2, lon2)` | Great-circle distance in meters. |
| `find_closest_trackpoint(waypoint, track_points)` | Nearest track point to a waypoint. |
| `footprint_to_waypoint(footprint)` | Footprint to GPX `<wpt>` element. |
| `build_trip_gpx(gpx_path, user_data, trip, footprints)` | Build/update the enriched trip GPX. |
| `build_user_xml(user_data, trips)` | Build the per-profile XML index. |
| `build_merged_xml(profiles_data)` | Build the XML index merging several profiles. |
| `_write_rst(path, content)` | Write an RST file, creating folders. |
| `_references_by_search(references)` | Case-insensitive lookup of reference labels. |
| `_encode_url(url)` | Percent-encode unsafe URL characters. |
| `_copy_media(media_paths, destination_dir)` | Copy media beside an article, returning relative paths. |
| `_copy_image(image_path, destination_dir, sizes, variants)` | Copy an image and create its variants. |
| `_load_country_boundaries()` | Load and cache Natural Earth boundaries. |
| `save_full_country_map(lat, lon, padding_ratio=0.1, output_image="map_country.png")` | Render the country/region map of a footprint. |
| `_mercator_coordinates(lon, lat)` | Project to Web Mercator meters. |
| `save_trip_route_map(gpx_path, footprints, output_image, background="transparent", show_footprint_bubbles=False)` | Render the 1200×800 route map. |
| `_footprint_gpx_fields(footprint, footprint_dir, sizes, trip_days="")` | Footprint fields used as Pelican metadata. |
| `_rst_text(value)` | Escape text for RST. |
| `_rst_metadata(**fields)` | Format Pelican metadata fields. |
| `_rst_heading(text, underline="=")` | Format an RST heading. |
| `_text_with_rst_references(text, references)` | Replace reference labels with RST links. |
| `_trip_date_range(footprints)` | ISO start/end dates of a trip. |
| `build_trip_rst(content_dir, trip_dir, user_data, trip, footprints, sizes)` | Generate trip and footprint RST articles. |
