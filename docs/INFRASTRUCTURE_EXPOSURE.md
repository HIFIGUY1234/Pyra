# Infrastructure exposure

`backend/app/infrastructure.py`, `backend/app/exposure.py`. API: `GET /api/gis/infrastructure`, `GET /api/exposure/*`.
UI: Critical Regions and Government Dashboard (layer banner, hotspot table, state comparison).

## Source

OpenStreetMap via the Overpass API, India country area. © OpenStreetMap contributors, **ODbL 1.0**.
OSM is volunteer-mapped. Completeness varies by region and category, and it is not an official register. A facility that does not appear has **not been mapped**, which does not mean it is absent.
No official government facility register with a reusable licence was found that covers all of India for these categories.

## Categories loaded (download 2026-11-14 UTC)

| Category | Overpass selector | Raw features | Kept | Downloaded |
|---|---|---|---|---|
| hospital | `nwr["amenity"="hospital"]` | 55,746 | 55,454 | 2026-11-14T18:51 |
| clinic | `nwr["amenity"="clinic"]` | 22,635 | 22,581 | 2026-11-14T18:59 |
| fire_station | `nwr["amenity"="fire_station"]` | 737 | 727 | 2026-11-14T19:00 |
| police | `nwr["amenity"="police"]` | 4,534 | 4,466 | 2026-11-14T19:02 |
| school | `nwr["amenity"="school"]` | 38,063 | 37,707 | 2026-11-14T19:03 |
| power_substation | `nwr["power"="substation"]` | 17,145 | 17,140 | 2026-11-14T19:11 |
| power_plant | `nwr["power"="plant"]` | 4,431 | 4,431 | 2026-11-14T19:12 |
| railway_station | `node["railway"="station"]` | 9,033 | 9,013 | 2026-11-14T19:13 |
| water_works | `nwr["man_made"="water_works"]; nwr["man_made"="wastewater_plant"]` | 2,021 | 2,018 | 2026-11-14T19:14 |
| communications | `nwr["man_made"="mast"]["tower:type"="communication"]; nwr["man_made"="tower"]["tower:type"="communication"]` | 2,706 | 2,705 | 2026-11-14T19:20 |
| industrial_site | `nwr["landuse"="industrial"]["name"]` | 5,717 | 5,710 | 2026-11-14T19:22 |

Cleaning:
* Input 162,768.
* Outside the AOI or invalid: 0.
* Duplicate `(osm_id, category)`: 0.
* Same name, same category within ~50 m: 816. This is typically a node plus a building outline for one facility.
* **Kept 161,952.**

One object may legitimately sit in two categories, for example a hospital that is also tagged as a clinic, so de-duplication is per category. An earlier key on `osm_id` alone wrongly dropped 743 such objects. It was fixed and the data were re-downloaded.
Ways and relations are represented by their Overpass centre point. `osm_id` (`n`/`w`/`r` + id), name and category are preserved.

## Not loaded (reported missing, never zero)

* **roads**: linear network; needs a Geofabrik extract
* **railways**: linear network; needs a Geofabrik extract
* **transmission_lines**: linear network; needs a Geofabrik extract
* **residential_settlements**: use the WorldPop population layer instead of OSM polygons

## Exposure calculation

* Per category, a KD-tree is built on 3-D unit vectors. The chord radius is converted from great-circle km, so distances are geodesic and not degree-based.
* *Facilities near a hotspot* counts facilities within the radius (default 5 km) of each de-duplicated actual detection location.
* *Facilities per state* counts facilities whose point falls in a 0.25° cell of that state, from the cell lookup.
* These are **proximity counts**. They do not say a facility is threatened, and they do not infer industry from fire detections. Industrial sites come only from named OSM `landuse=industrial` areas (selector column).
* A missing layer or category gives *unavailable*. It never contributes zero to a critical-region score.

## Refresh

```bash
cd backend && python -m app.infrastructure     # ~30 min; public Overpass mirrors return 502/504 under load and are retried
python -m app.pipeline --refresh-exposure
```
