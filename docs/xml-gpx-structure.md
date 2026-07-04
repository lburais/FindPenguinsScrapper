# XML and GPX Structure Reference

This document describes the generated file structures currently emitted by FindPenguinsScrapper.

## 1) Profile XML Structure

Generated file:

- `output/<uid>/<uid>.xml`

Root element:

- `<profile>`

Current top-level children (when values exist):

- `<uid>`: FindPenguins profile id
- `<name>`
- `<bio>`
- `<location>`
- `<website>`
- `<picture>`: local profile image filename
- additional user keys (for example `<email>`) can also appear
- `<trips>` container

Trip entry shape:

```xml
<trips>
  <trip>
    <slug>italie-2026</slug>
    <title>Italy 2026</title>
    <url>https://findpenguins.com/<uid>/trip/<slug></url>
    <gpx>italie-2026.gpx</gpx>
    <companion>51xfd5fd05zj2</companion>
    <companion>1zmijwhfvwknl</companion>
  </trip>
</trips>
```

Trip fields intentionally excluded from XML (internal processing only):

- `footprints`
- `period`
- `days`
- `km`
- `is_current`

## 2) GPX Structure

Generated file:

- `output/<uid>/<trip-slug>.gpx`

GPX root:

```xml
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="FindPenguins">
```

## 2.1 Metadata Block

`<metadata>` contains:

- `<name>`: trip title
- `<desc>`: trip period/description (when present)
- `<author>`
  - `<name>`: profile name
  - `<email>`: login email when provided
  - `<link href="..."/>`: website when provided
- `<link href="https://findpenguins.com/<uid>/trip/<slug>"/>`
- `<extensions>` (trip-scoped custom metadata)
  - `<slug>`
  - `<title>`
  - `<uid>`
  - repeated `<companion>` for companion ids

## 2.2 Waypoints (`wpt`)

One waypoint is generated per parsed footprint that has coordinates.

Standard GPX waypoint fields written when available:

- `@lat`, `@lon`
- `<name>`: footprint title
- `<desc>`: footprint text
- `<ele>`: altitude from popup metadata (not track elevation)
- `<link href="...">`: footprint URL
- `<time>`: nearest trackpoint time if a route track exists

Waypoint extensions (`<wpt><extensions>`) may include:

- `<date>`
- `<weather>`
- `<temperature>`
- `<overnights>`
- `<flag>`
- `<country>`
- `<city>`
- `<text-private>`
- `<park4night>`
- repeated `<wikipedia>`
- repeated `<photo>` with local file path
- `<point lat="..." lon="..."/>` (nearest route point, custom extension)

## 2.3 Track Elements (`trk`)

Behavior:

- If an official travel-route GPX is downloaded, its track data is preserved.
- Existing `trk` nodes are temporarily removed during waypoint rebuild and appended back unchanged (except optional elevation enrichment).
- `trkpt` may receive or update `<ele>` based on external elevation API results.

## 3) Ordering Rules in GPX

Current writer ordering:

1. `<metadata>`
2. all `<wpt>` (newly generated)
3. original `<trk>` elements (re-appended)

This ordering keeps narrative waypoints clearly visible while preserving route geometry.

## 4) Optional and Repeated Fields

- Most tags are optional: empty values are skipped.
- Repeated fields:
  - XML: `<trip><companion>`
  - GPX metadata extensions: `<companion>`
  - GPX waypoint extensions: `<wikipedia>`, `<photo>`

## 5) Compatibility Notes

- GPX core elements are namespaced (GPX 1.1).
- Custom extension children are plain tags under `<extensions>`.
- Consumers that ignore unknown extension tags still parse core GPX successfully.
