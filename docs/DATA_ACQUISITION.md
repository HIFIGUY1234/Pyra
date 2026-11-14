# Data acquisition

All commands run from `backend/`. Inventory at any time: `python -m app.acquire` (writes
`data/processed/ingestion_report.{json,md}`; also `GET /api/data/inventory`).

## 1. Repository archives (Git LFS)

The five `DL_FIRE_*.zip` files are Git LFS objects. Without `git lfs pull` they are ~133-byte pointers.
Discovery reports them as `lfs_pointer` and never parses them as ZIPs.

Recovery (`acquire.recover_lfs`) reads the expected size and SHA-256 from each pointer and downloads to
`<name>.zip.part`. An interrupted transfer resumes with an HTTP Range request. Network errors, timeouts
and 5xx responses are retried with exponential back-off; a 404 is reported as `remote_missing` and not
retried. The archive is replaced only when **both size and SHA-256 match**, so a valid archive is never
overwritten. A JSON report goes to `data/processed/lfs_recovery_report.json`. Statuses:
`recovered`, `already_present`, `invalid_pointer`, `remote_missing`, `download_failed` (partial kept,
resumable), `checksum_mismatch` (partial deleted).

```bash
git lfs install && git lfs pull
# or without git-lfs (downloads from GitHub's LFS media host, verifies SHA-256 against the pointer oid):
python -m app.acquire lfs          # also: python -m app.pipeline --recover-lfs, or POST /api/data/recover-lfs (admin)
```

Full SHA-256 for every archive: `data/processed/archive_checksums.json` (also listed in the inventory).

### Collection and version labels

| Archive tag | Collection (from the name, per the FIRMS download Readme) | Row `version` values found | Meaning |
|---|---|---|---|
| `M-C61` | MODIS Collection 6.1 (MCD14ML) | `6.03` (2000-11 → 2022-12), `61.03` (2023-01 →), `6.1NRT` | `6.1NRT` is documented (C6.1 NRT). `6.03` and `61.03` are **not defined** in readable FIRMS documentation. They are kept verbatim and flagged *undocumented*, and are never relabelled. |
| `SV-C2`, `J1V-C2`, `J2V-C2` | VIIRS Collection 2, 375 m (VNP14IMGT / VJ114IMGT / VJ214IMGT) | `2`, `2.0NRT` | These follow the documented convention (collection = standard processing; `NRT` suffix = provisional). |

NOAA-21 archive rows start 2023-03-01, before the official FIRMS start of 2024-01-17. The inventory
flags them as *pre-operational records*.

## 2. Missing historical MODIS (needed for the real morning-gap correction and real 2012 seam)

FIRMS MODIS C6.1 coverage: Terra from **1 Nov 2000**, Aqua from **4 Jul 2002**. Needed here:
Terra 2000-11-01 → 2011-12-31 and Aqua 2002-07-04 → 2011-12-31 for bbox `68,6,98,36`.

**Option A — FIRMS Archive Download (recommended for multi-year requests).**
https://firms.modaps.eosdis.nasa.gov/download/ → Create new request → MODIS C6.1, CSV, custom area
`68,6,98,36` (or country IND), dates as above. Unzip the emailed archive into `data/raw/` (or upload via
Data Management, satellite = Terra/Aqua). Then:

```bash
python -m app.pipeline --only-new --retrain
```

**Option B — FIRMS API (scripted, restartable).** Get a free MAP_KEY at
https://firms.modaps.eosdis.nasa.gov/api/map_key/ and keep it in the environment only:

```bash
export FIRMS_MAP_KEY=...           # never commit it
python -m app.acquire firms MODIS_SP 2000-11-01 2011-12-31
python -m app.pipeline --only-new --retrain
```

The downloader requests 10-day windows (`/api/area/csv/{key}/{source}/{bbox}/{days}/{date}`), caches each
window under `data/raw/<tag>.parts/` so an interrupted run resumes, and writes one CSV to `data/raw/`.
FIRMS rate-limits keys (transactions per 10 minutes); long ranges take time — Option A is faster.

After ingestion the app switches automatically: Terra-only months get the real Morning-Gap correction
(provenance `morning_gap_sensor`), and the seam test runs in `real` mode at Jan 2012.

## 3. NOAA-20 VIIRS

FIRMS 375 m NOAA-20 coverage starts 1 Apr 2018. `python -m app.acquire firms VIIRS_NOAA20_SP 2018-04-01 <end>`
(or the archive tool, product "VIIRS NOAA-20 375m"). Ingested as a separate satellite; never pooled with S-NPP.

## 4. VIIRS 750 m (continuity product) — `backend/app/viirs750.py`

* Products (collection **002**, archived at **LP DAAC**, verified through NASA CMR on 2026-11-14):
  **VNP14** (Suomi NPP), **VJ114** (NOAA-20), **VJ214** (NOAA-21) — *VIIRS Active Fires 6-Min L2 Swath 750 m*,
  the MODIS C6 fire algorithm on VIIRS M-bands. HDF5/NetCDF4 granules, one per 6-minute swath. Not distributed by FIRMS as CSV.
* **Search** (`viirs750.search`) uses the public CMR API, bounded by the AOI and dates — no credentials needed.
  Live check: 15 NOAA-21 granules intersect the AOI on 2025-11-01.
* **Download** needs Earthdata Login (the data URL answers HTTP 302 to `urs.earthdata.nasa.gov`). Supply either
  `EARTHDATA_TOKEN` (a user token, environment only) or a `~/.netrc` entry for `urs.earthdata.nasa.gov`.
  Never put credentials in source, `.env.example`, workflows or images. Without credentials `download()` raises
  and `/api/viirs750/status` reports `credentials: not configured`.
* Download safeguards: retry with backoff, `.part` resumption, HDF5 signature and size check (corrupted files are
  deleted, not converted), SHA-256 per granule in `data/raw/viirs750/manifest.json`, duplicate granules skipped.
* **Converter** (`viirs750.granule_pixels`, written to the LAADS file specification — the earlier `vnp14_to_csv`
  assumed an `FP_day` variable that does not exist): reads `FP_latitude`, `FP_longitude`, `FP_power`, `FP_confidence`
  (uint8 %), `FP_SolZenAng` (day when < 85°), and the granule time / `DayNightFlag` attributes; fire-mask classes
  7/8/9 map to low/nominal/high. Fill values and missing arrays are skipped. Tested on synthetic HDF5 files built to the
  specification only — **it has not yet been run on a real granule**.

```bash
export EARTHDATA_TOKEN=...            # or ~/.netrc
cd backend
python -m app.pipeline --viirs750 2025-11-01 2025-11-07   # search → download → convert → ingest
```

Rows are tagged `product_type=750m`, aggregated as separate streams, and calibrated separately from the 375 m model.
Until real granules are ingested the UI and API say **unavailable**. **Status: blocked by Earthdata credentials.**

## 5. Uploads

Data Management → Upload CSV (or `POST /api/data/upload`, admin): choose satellite and, for VIIRS, the
product (375 m / 750 m). The header and a 2 000-row sample are validated before the file is accepted
(1.5 GB limit, `.csv` only, filename sanitised). Then `POST /api/data/process` ingests only new sources.

## 6. Weather (NASA POWER)

Fetched automatically by the pipeline (`weather.py`) when network access exists; cached in
`data/processed/weather.parquet`. Offline, the forecast trains without weather and says so.

## 7. Population — WorldPop 2020 (`backend/app/population.py`)

| Candidate | Resolution | Year | Licence | Decision |
|---|---|---|---|---|
| **WorldPop Global 2000–2020, 1 km, UN-adjusted** | 30″ (~1 km) | 2020 | CC BY 4.0 | **Selected**: single India file (18.3 MB), national total matches UN 2020 |
| GHSL GHS-POP R2023A | 3″–30″ | 2020/2025/2030 (modelled) | CC BY 4.0 | Global tiles, larger; kept as alternative |
| NASA SEDAC GPW v4.11 | 30″ | 2020 | CC BY 4.0 | Census-unit areal weighting, coarser input units |

* `python -m app.population` downloads (resumable) `ind_ppp_2020_1km_Aggregated_UNadj.tif`, records SHA-256
  (`27d08e3e…bec911`, 18,313,124 bytes), reads it in 256-row blocks (never the whole raster), drops NoData, and assigns
  each pixel by its centre to one 0.25° analysis cell and one 0.05° fine cell — every pixel is counted exactly once.
* Result: **1,380,004,385** people in the AOI, 4,885 cells (1,360 partially covered at the coast/border).
* The raster origin is not on the 30″ lattice (`grid_aligned: false`); pixel-centre assignment avoids double counting,
  but cell-edge totals carry up to ~½-pixel positional uncertainty.
* Reference year is 2020 throughout; no years are mixed. The GeoTIFF is git-ignored; derived parquet + manifest are committed.

## 8. Infrastructure — OpenStreetMap (`backend/app/infrastructure.py`)

* Source: OpenStreetMap via the Overpass API (three mirrors, retry with backoff), © OpenStreetMap contributors, **ODbL 1.0**.
  Download time is stored per category. OSM completeness varies by region; absence in OSM is not absence on the ground.
* Categories (11): hospital, clinic, fire_station, police, school, power_substation, power_plant, railway_station,
  water_works, communications, industrial_site. Ways/relations use their Overpass centre point.
* Cleaning: coordinates inside the AOI, duplicate `(osm_id, category)` removed, same-name same-category points within ~50 m merged.
  `osm_id`, tags and name are preserved.
* **Not loaded** (reported as missing, never zero): roads, railways and transmission lines (linear networks need
  line-distance logic), residential settlements (use the population grid instead).
* `python -m app.infrastructure` refreshes; or `python -m app.pipeline --refresh-exposure` for both layers.

## 9. Orbital elements — CelesTrak TLEs (`backend/app/orbits.py`)

* Current two-line element sets for Terra (25994), Aqua (27424), Suomi NPP (37849), NOAA-20 (43013), NOAA-21 (54234)
  from CelesTrak GP API; checksum and catalogue number verified; cached in `data/auxiliary/tle/`. TLEs older than 7 days are flagged stale.
* `python -m app.orbits refresh` / `validate`, or `python -m app.pipeline --refresh-tle`.

## 10. Linear infrastructure — Geofabrik PBF (`backend/app/linear_gis.py`)

Roads, railways, power lines and settlements come from the Geofabrik India extract (ODbL). `python -m app.linear_gis fetch`
downloads the PBF and verifies it against Geofabrik's published MD5; `python -m app.linear_gis build` parses it with osmium,
keeps lines as lines (GeoParquet, WKB + geo metadata), computes per-0.25°-cell lengths in km and writes a manifest.
No unrestricted Overpass queries are used. The sandbox cannot reach Geofabrik, so the extract is built by the
*Data integration* workflow (`linear_gis: true`), which uploads the result as an artifact. Until loaded, the layer is
reported *not loaded*, never zero.

## 11. Population allocation method

WorldPop pixels are now split across 0.25° cells by exact spherical area (`method="area_weighted"`); the earlier
pixel-centre method stays available and `population.compare_methods` reports the difference per cell (sensitivity).
Totals are conserved to float precision (tested on synthetic GeoTIFFs).

## 12. Per-sensor forecast labels

NOAA-20 and NOAA-21 forecast labels use only standard-processing rows from each sensor's operational start
(NOAA-20 2018-04-01, NOAA-21 2024-01-17); NRT rows are excluded. See [OPERATIONAL_SENSOR_TRANSITION.md](OPERATIONAL_SENSOR_TRANSITION.md).
