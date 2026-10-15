# Data fields retrieved from FindPenguins

This document lists every field the scraper collects from FindPenguins and how each one is obtained.
Source files: [fp_utils.py](../fp_utils.py), [fp_parsers.py](../fp_parsers.py),
[findpenguins_scrapper.py](../findpenguins_scrapper.py), [fp_elevation.py](../fp_elevation.py).

## 1. Acquisition methods

| Method | Tool | Used for |
|--------|------|----------|
| Form login | `requests.Session` | Authentication ([`login`](../fp_utils.py)): GET `/login`, read the `_csrf_token` input, POST `_username`, `_password`, `_csrf_token`, `_remember_me` to `/login/exec`. Session cookies are reused. |
| Headless browser | Playwright (Chromium) seeded with the session cookies ([`create_browser_page`](../fp_utils.py)) | Rendering profile, trip and footprint pages ([`load_page`](../fp_utils.py)) and the footprint popup menu. |
| HTML parsing | BeautifulSoup on `page.content()` | Extracting fields via CSS selectors. |
| Direct HTTP download | `requests` | GPX route, photos, videos, profile picture. |
| Third-party API | OpenTopoData SRTM 90m | Optional track elevations (`--elevation`). |

Page flow: profile page → trip pages (`/<profile>/trip/<slug>`) → one page per footprint.
On trip pages, `click_load_more_until_done` clicks `#footprintListLoadMore` until the whole footprint list is loaded.

## 2. Login-related fields

| Field | Source |
|-------|--------|
| `uid` | Profile id given on the command line / `profiles.json` (`id`). It is also the first path segment of the profile URL. |
| `email` | Login username given on the command line / `profiles.json` (`username`). Not scraped. |

## 3. Profile (`parse_profile`)

Page: `https://findpenguins.com/<profile_id>`, container `div.userBox`.

| Field | CSS selector / source | Notes |
|-------|-----------------------|-------|
| `name` | `.nameBox h1 a` | Text, whitespace normalised. |
| `bio` | `.detailBox #clampedBox span` | Text. |
| `location` | `.detailBox .extras a[href*='explore?q=']` | Text. |
| `website` | `.detailBox .extras a.website` → `href` | |
| `picture` | `.pictureBox .pp img` → `src` | `//` prefixed URLs become `https:`. Downloaded to `<output>/<profile>/<profile>_profile_*`; the field is then replaced by the relative local path. |

A `RuntimeError("userBox not found")` is raised when the container is missing.

## 4. Trips (`parse_trips`)

Page: the profile page, elements `.tripList .tripPreviewBox`. Only boxes whose link (`a[href*='/trip/']`) belongs to the profile id are kept.

| Field | Source | Notes |
|-------|--------|-------|
| `url` | `a[href*='/trip/']` → `href`, made absolute with `BASE_URL` | |
| `slug` | Last segment of the trip URL path | Used as the output folder name. |
| `title` | `.content .title h2` | |
| `period` | First `.content .stats li` | Text, e.g. `2024Jul–Aug`. |
| `days` | Second `.stats li`, `<b>` text | Total number of trip days; written to the XML and GPX trip metadata. |
| `km` | Third `.stats li`, `<b>` text | Only when the text contains "kilometer". |
| `is_current` | Presence of `.badge.current` | Stored as the string `True`/`False`. |
| `companions[]` | `.userIconBar span.item` | See below. |
| `gpx` | Computed | Relative path of the generated `<slug>.gpx`. |
| `footprints` | Computed | List of footprints, see section 5. |

Companion fields:

| Field | Source |
|-------|--------|
| `uid` | `span.item` → `data-id` |
| `name` | `<img>` → `alt` |
| `avatar` | `<img>` → `src` (made absolute) |

Companions without an `<img>` are skipped.

### Trip GPX route (downloaded, not parsed from HTML)

The internal trip id is read from `div.tripBox[data-trip-id]` on the trip page.
The route is then downloaded with the authenticated session from
`/account/trips/<trip_id>/travel-route.gpx` (30 s timeout) and saved as `<trip_dir>/<slug>.gpx`.
It provides the `trk`/`trkpt` track points (`lat`, `lon`, `time`) used later.

### Trip insights (`parse_trip_insights`)

Insights are a trip subpage (`<trip_url>/insights`, e.g. `/<profile>/trip/<slug>/insights`), loaded
in Playwright after the footprints are parsed. A non-OK response yields no fields. The page HTML is
saved as `<trip_dir>/insights.html` to help tuning the extraction. The extracted fields are stored
directly on the trip dictionary (there is no `insights` level):

| Field | Source | Notes |
|-------|--------|-------|
| `description` | First paragraph `.tripInsights .tripInsightsSection p` | Trip description text. |
| `countries[].name` | `#countryBubbles li` | Country name. |
| `countries[].flag` | `img` `src` (`/flags-png/<cc>.png`) | Emoji flag built from the country code. |
| `distance` | `.statsSection .number` next to the "kilometers" label | Digits only (`2,436` → `2436`), km. |
| `transports[].name` | `.transportStats li .transport` | Lower-cased, e.g. `camper`, `flight`, `train`. |
| `transports[].distance` | `.transportStats li .value` | Digits only, km. |

XML/GPX output (trip metadata extensions):

```xml
<description>…</description>
<countries>
  <country><name>France</name><flag>🇫🇷</flag></country>
</countries>
<distance>2436</distance>
<transports>
  <transport><name>camper</name><distance>1419</distance></transport>
</transports>
```

`trip.rst` lists them under an `Insights` heading.

`parse_trip_insights` also returns the companions from "Travelers in this trip"
(`#FollowersList li.follower`): `uid` (link `href`), `name` (`.name`) and `avatar` (`.ppBox img` `src`, made
absolute). The avatar is downloaded to `<trip_dir>/companion_<uid>_*` and its relative path stored
as `picture`. When found, these replace the thumbnail-only companions of the profile list in
`trip["companions"]`. Each is written as
`<companion><uid>…</uid><name>…</name><picture>…</picture></companion>`.

### Trip main image (`parse_trip_image`)

On the trip page, the cover image is the `background-image: url(...)` of `#tripBox .titleBox`. It is
downloaded to `<trip_dir>/cover_*` and its relative path stored in `trip["image"]`. Trips using the
default placeholder (`trip_preview.png`) have no main image and the field stays empty.

## 5. Footprints (`parse_footprints` and `parse_trip`)

### 5.1 Footprint list (trip page)

| Field | Source |
|-------|--------|
| `id` | `ul.FootprintList li.footprint` → `data-id` |
| `url` | `.title h2.headline a[href]` → `href` (made absolute) |

Footprints without a URL are skipped.

### 5.2 Footprint page

Each footprint page is loaded in Playwright and the `li.footprint[data-id=<id>]` element is used
(fallback: first `ul.FootprintList li.footprint`).

| Field | Source | Notes |
|-------|--------|-------|
| `url` | From the list | |
| `title` | `.title h1.headline a` (fallback `.title h2.headline a`) | |
| `date` | `.title .date .desc` → `content` attribute | |
| `day` | Computed by `apply_day_numbers` | Days since the earliest footprint date of the trip, first day = 1. Empty if the date is missing/invalid. |
| `weather` | Text after `⋅` in `.title .date .desc` | Overridden by the popup value when available. |
| `lat`, `lon` | Inline script: regex `MapSingleFootprintController.initMap(<lat>,<lon>)` | Then overwritten by the GPX waypoint (see 5.5). |
| `text` | `.content-container .text:not(.text-private)` | Converted by `extract_expandable_text`. |
| `text-private` | `.content-container .text-private` | Same conversion, then URLs are extracted (see 5.4). |
| `references[]` | URL-only lines of the private text | List of `(search_text, url)`. |
| `photos[]` | `a.image.photo[data-url]` → `data-url` | Downloaded; local paths stored. |
| `videos[]` | `a.image.video[data-url]` → `data-url` | Downloaded; local paths stored. |
| `overnights`, `temperature`, `altitude`, `flag`, `country`, `city` | Popup menu | See 5.3. |

### 5.3 Popup menu (`click_footprint_menu`)

The menu button `a.menu[role='button']` is clicked, the popup `#_fpMenuPopup ._fpMenu` is awaited
(5–7 s timeouts) and its HTML is parsed. The popup is then closed (close button or Escape).
If the button or popup is not available, an empty dictionary is returned and the fields stay empty.

| Field | Selector | Extraction |
|-------|----------|------------|
| `overnights` | `li i.overnights` (or `.icon-font.overnights`, `i[class*='overnight']`, `i[class*='nights']`) → parent text | First integer. |
| `weather` | `li .icon-font.temperature` → parent text | First word of the text. |
| `temperature` | Same element | First number (`-?\d+([.,]\d+)?`), commas removed. |
| `altitude` | `li .icon-font.altitude` → parent text | First number, commas removed. |
| `country` | `.fpMenuPlacesList a.tag` with a link starting with `/` but not `/explore/` | Label text; a leading emoji flag is split from the name. |
| `flag` | Same tag, `img.flag-icon` / `img.flag-sm` `src` (`/flags-png/xx.png`) | Country code converted to a flag emoji (regional indicator characters); otherwise the emoji from the label. |
| `city` | `a.tag` with `href` starting `/explore/` | Label text. |
| popup `latitude` / `longitude` | `a.tag.coordAction` (textarea or label, DMS format) | Converted from degrees/minutes/seconds + N/S/E/W to decimal. When absent, the centre of the bounding box in the `/explore/<name>/<lat_min>,<lon_min>,<lat_max>,<lon_max>` link is used. |

> The popup `latitude`/`longitude` are collected but are **not** written to the footprint; the footprint
> `lat`/`lon` come from the map script and the GPX waypoints. Only the first place of the popup is used.

### 5.4 Text conversion (`extract_expandable_text`, `extract_private_references`)

- "Read more" content: `.readMore`, `.dots` and `i.icon-font` are removed. Links truncated around a `.dots` element are merged back into a single URL.
- Link texts are normalised to `https://…`.
- `<br>` becomes a newline and `.double-break` a blank line; whitespace is compacted.
- In `text-private`, a line that is a valid `http(s)` URL (optionally prefixed with `[search text]`) is removed from the text and stored in `references` as `(search_text, url)`.

### 5.5 Coordinates from GPX (`apply_gpx_coordinates`)

After all footprints of a trip are parsed, the downloaded GPX waypoints (`wpt`) are matched by title, in order
(duplicated titles consume successive waypoints). The matching waypoint `lat`/`lon` replace the values found in the page.
A warning is printed for footprints with no matching waypoint.

### 5.6 Media download

| Item | Behaviour |
|------|-----------|
| Photos | `download_image`: `//` and `/` URLs made absolute; thumbnail suffixes `_m_s` / `_t_s` are rewritten to the large `_l` variant; saved as `<trip_dir>/<footprint_id>__<filename>`. A failure is logged and the photo skipped. |
| Videos | `download_video`: streamed to a `.part` file and renamed when complete; skipped if the file already exists. |
| GPX / PDF attachments | `download_file`: every link (`href` or `data-url`) in the footprint ending in `.gpx` or `.pdf` is downloaded the same way as videos, into the trip folder, stored in `footprint["gpx"]` / `footprint["pdf"]`. |
| Profile picture | `download_image` into the profile folder. |

## 6. Derived data (not scraped)

Built in [fp_writers.py](../fp_writers.py) from the data above:

| Data | How |
|------|-----|
| Waypoint `time` | Time of the closest GPX track point to the waypoint (haversine distance). |
| Waypoint extension `point` | `lat`/`lon` of that closest track point. |
| Track point `ele` | OpenTopoData SRTM90m, batches of 100 points, retries with exponential back-off on HTTP 429. Only with `--elevation`. |
| Trip metadata `uid` | First segment of the trip URL, or the profile name. |

## 7. Where the fields end up

| Output | Fields |
|--------|--------|
| `<profile>.xml` | Profile fields (`uid`, `name`, `bio`, `location`, `website`, `picture`, `email`); per trip `slug`, `title`, `days`, `url`, `gpx`, `companion` uids. `period`, `km`, `is_current` and the companion details are not written. |
| `<slug>.gpx` | Waypoint: `lat`, `lon`, `name`=title, `desc`=text, `ele`=altitude, `link`=url; extensions `date`, `day`, `weather`, `temperature`, `overnights`, `flag`, `country`, `city`, `text-private`, `reference`, `photo`, `video`, `point`. Metadata: trip `title`, `period` (as `desc`, only for a new GPX), author name/email/website, trip link, `uid`, `companion`. |
| RST (Pelican) | Footprint pages: every GPX waypoint field is a Pelican metadata tag, except `desc`, which is the page body (the footprint text, with references turned into links). See below. |
| HTML | Rendered from the same dictionaries. |

### Pelican footprint metadata (`footprint.rst`)

| GPX field | Pelican tag |
|-----------|-------------|
| `name` | `Title` |
| `desc` | **Page body** (not a tag) |
| `lat`, `lon` | `Lat`, `Lon` |
| `ele` | `Ele` (altitude) |
| `link` | `Link` |
| `date`, `day`, `weather`, `temperature`, `overnights`, `flag`, `country`, `city` | `Date`, `Day`, `Weather`, `Temperature`, `Overnights`, `Flag`, `Country`, `City` |
| `text-private` | `Text-private` |
| `reference` | `Reference`: `search|url` entries separated by `, ` |
| `photo`, `video` | `Photo`, `Video`: copied file names separated by `, ` |
| `gpx`, `pdf` | `Gpx`, `Pdf`: copied file names separated by `, ` |

`Slug`, `Category`, `Tags`, `Summary` and `Template` are also set for Pelican itself.
`time` and `point` are only computed in the GPX and are not part of the pages.

See also [xml-gpx-structure.md](./xml-gpx-structure.md) for the exact XML layout.
