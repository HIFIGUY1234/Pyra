# Fire-event delineation

Module: `backend/app/events.py` · API: `/api/events*` · UI: **Fire Events** (`/events`, `/events/:id`) · Job: `fire_events`

Status: **IMPLEMENTED BUT NOT FULLY VALIDATED** — runs on the authentic FIRMS archive; no official incident records are
available to measure precision/recall (see [INDEPENDENT_VALIDATION.md](INDEPENDENT_VALIDATION.md)).

## What an event is (and is not)

One FIRMS hotspot is one thermal-anomaly detection in one pixel on one overpass. It is **not** a fire. An event is a
connected component of a space-time graph of detections from all five platforms (Terra, Aqua, Suomi NPP, NOAA-20,
NOAA-21; MODIS 1 km and VIIRS 375 m; VIIRS 750 m if loaded). Raw detections are never modified or deleted: each event
links to its original records through a stable `obs_key` (SHA-1 of platform, product, position, acquisition minute).

The event footprint is the convex hull of the **detected pixel extents** — an *observation footprint*. It is not a
fire perimeter and not a burned area.

## Method (chosen from the data)

DBSCAN/HDBSCAN need one global density threshold and chain dense agricultural regions (Punjab/Haryana in October hold
thousands of field burns within a few km). The chosen method is **graph linking with sensor-aware distances and
land-cover persistence**:

* Two detections are linked when their pixel footprints touch: ground distance ≤ r_i + r_j, with
  r = ½·√(scan² + track²) km from the FIRMS along-scan/along-track pixel size (≈0.27 km VIIRS 375 m at nadir,
  ≈0.71 km MODIS at nadir, larger off-nadir). Distances use 3-D chord geometry (no lat/lon distortion).
* …and they are no more than *persistence* days apart: cropland and urban cells 1 day (short field burns are not chained
  across days), forest/savanna/other 3 days (multi-day understorey fires). Land cover comes from the grid cell
  (ESA WorldCover-derived classes already used by PyroScope).
* Static/industrial (FIRMS type 2), volcano (1) and offshore (3) detections are excluded. NRT duplicates of archive
  rows are dropped (archive wins).
* Implementation: per day, KD-tree pair search against the trailing persistence window, then
  `scipy.sparse.csgraph.connected_components`.

Real-data behaviour (Punjab, 25 Oct–5 Nov 2025): 7,826 detections → 5,183 events; largest 31 detections over ~3×6 km
across 4 sensors in 4 days; no region-scale chaining.

## Attributes

ID, first/last detection, earliest plausible start (first detection − 12 h revisit), latest plausible end (only for
ENDED), detections, days, platforms and counts, sensor families, centre, bbox, footprint (pixel-extent hull and
pixel-centre hull as lower/upper bounds), peak FRP, sum of FRP (*instantaneous MW summed over detections — not energy*),
FRE bracket (experimental, below), confidence counts and mean, evidence class (single/multi-sensor, single/multi-day),
multi-sensor day share, dominant land cover / state / district, day/night counts, daily timeline, growth summary
(apparent movement and bearing of the daily centroid, cumulative footprint growth km²/day), gap since last detection,
sensor-days of data since, status and end basis.

FRE bracket: per-overpass FRP totals are integrated over time (passes ≤24 h apart joined trapezoidally). An isolated pass
is credited 0.5 h (low) or 6 h (high) of unobserved burning per side. The bracket is carried into the emission estimate.

## Status

| Status | Rule |
|---|---|
| DETECTED | last detection ≤1 day before the latest data, single day, ≤2 detections |
| ACTIVE | last detection ≤1 day before the latest data otherwise |
| POSSIBLY_INACTIVE | quiet for >1 day but not ENDED |
| ENDED | quiet > persistence + 2 days **and** ≥6 sensor-days of data since the last detection; `end_basis` records the evidence and that FIRMS has no cloud mask |
| UNVERIFIED | DETECTED/ACTIVE, every detection low confidence, single sensor family |
| MERGED / SPLIT | identity reconciliation (below) |

There is no CONTAINED status: containment requires official incident data.

## Identity across runs

Event IDs are `FE-<first-detection date>-<8 hex of the first obs_key>`. Each run reconciles components against the stored
`obs_key → event_id` associations: continuation keeps the ID; a component holding several earlier events keeps the
earliest and records MERGED (`merged_into`) for the others; an earlier event spread over several components keeps its
ID for the largest part and the others get new IDs with SPLIT history (`split_from`). Re-running identical data
produces no history entries (tested). History: `fire_event_history`.

## Storage

Event summaries and history: database tables `fire_events`, `fire_event_history`. Observation associations:
`data/processed/events/associations.parquet` (raw records stay in the hotspot Parquet archive).

## Results on authentic data

| Window | Detections | Events | Multi-sensor | Single-detection | Runtime |
|---|---|---|---|---|---|
| India, 25–31 Oct 2026 (stored in the repository DB) | 31,837 | 8,948 | 1,328 | 6,312 | 25.6 s |
| India, 1–31 Oct 2026 (benchmark, scratch DB) | 76,533 | 27,666 | 3,871 | 20,263 | 102 s |

Status counts for the stored window: ENDED 6,002 · POSSIBLY_INACTIVE 1,877 · DETECTED 845 · ACTIVE 200 · UNVERIFIED 24.
A month of India events takes ≈47 MB in SQLite (~1.7 KB/event), so the committed demo DB holds one week; longer periods
belong in PostgreSQL/Supabase.

## Limitations

* No cloud mask in FIRMS: quiet periods can be cloud-obscured; ENDED is evidence-based but not proof.
* Footprint growth is detection geometry; scan-angle pixel growth inflates off-nadir footprints.
* Adjacent separate fields burning on consecutive days can still link in cropland (1-day window).
* Parameters are literature-informed defaults, not tuned against incident data (none available).
