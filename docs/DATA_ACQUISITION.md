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

## 4. VIIRS 750 m (continuity product)

* Product: **VNP14** (S-NPP) / **VJ114** (NOAA-20), *Thermal Anomalies/Fire 6-Min L2 Swath 750 m*,
  the MODIS C6 algorithm on VIIRS M-bands — NASA's continuity product for the MODIS 1 km record.
* Not distributed by FIRMS as CSV. Download Level-2 granules (NetCDF) from LAADS DAAC
  (https://ladsweb.modaps.eosdis.nasa.gov/, Earthdata Login) for the AOI and period.
* Convert fire-pixel tables (`FP_latitude`, `FP_longitude`, `FP_power`, `FP_confidence`, `FP_day`):

```bash
pip install h5py
python -m app.acquire vnp14 /path/to/granules --satellite "Suomi NPP"
python -m app.pipeline --only-new
```

Rows are tagged `product_type=750m`, aggregated as stream `"Suomi NPP 750m"`, and calibrated separately
(`/api/validation?product=750m`, `/api/sensor-harmonizer/calibration?product=750m`). Until data exist those
endpoints return a clear "not loaded" message. CSV uploads can also be marked 750 m in Data Management.

## 5. Uploads

Data Management → Upload CSV (or `POST /api/data/upload`, admin): choose satellite and, for VIIRS, the
product (375 m / 750 m). The header and a 2 000-row sample are validated before the file is accepted
(1.5 GB limit, `.csv` only, filename sanitised). Then `POST /api/data/process` ingests only new sources.

## 6. Weather (NASA POWER)

Fetched automatically by the pipeline (`weather.py`) when network access exists; cached in
`data/processed/weather.parquet`. Offline, the forecast trains without weather and says so.
