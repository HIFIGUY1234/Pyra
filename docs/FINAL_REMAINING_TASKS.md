# Remaining tasks and how to unblock them

Updated 2026-11-15 (branch `feature/pyroscope-ultimate-completion`). Full matrix:
[ULTIMATE_FINAL_COMPLETION_REPORT.md](ULTIMATE_FINAL_COMPLETION_REPORT.md). Step-by-step setup: [FINAL_MANUAL_SETUP.md](FINAL_MANUAL_SETUP.md).

| # | Task | Blocked by | Exact unblock |
|---|---|---|---|
| 1 | VIIRS 750 m authentic granules (VNP14 / VJ114 / VJ214 v002) | Earthdata account approvals (token is present and valid) | Accept the LAADS licence + authorise LP DAAC in Earthdata Login; run `python -m app.pipeline --viirs750 2025-11-01 2025-11-07`; fit the separate 750 m calibration |
| 2 | Burned area (MCD64A1 061 / VNP64A1 002) | same approvals | Queue job `burned_area` (year, month) |
| 3 | Burned-area emission method | authoritative fuel-consumption table | add `data/auxiliary/emissions/fuel_consumption.csv` with source |
| 4 | Geostationary observations (INSAT / Meteosat-IODC) | MOSDAC / LSA SAF registration | import an authorised export on Geostationary & Diurnal |
| 5 | Event validation vs official incidents | no public incident register | obtain a register with permission; import CSV on External Validation |
| 6 | PM2.5 concentration forecast | no dispersion model installed (HYSPLIT) | install HYSPLIT + ARL meteorology; add a runner in `smoke.py` |
| 7 | Smoke / PM2.5 validation | ground monitor API key | `OPENAQ_API_KEY` or `DATA_GOV_IN_API_KEY` |
| 8 | Leave-region-out harmonization refit | not implemented (temporal hold-out per state exists) | software task |
| 9 | Supabase project, Vercel project, backend host, DNS | your accounts | FINAL_MANUAL_SETUP.md §4-§8 |
| 10 | Real notification delivery | SMTP / webhook credentials + verified contacts | FINAL_MANUAL_SETUP.md §7 |

Resolved in this branch: E2E selector failure, WorldPop authentic area-weighted rebuild, fire-event delineation, durable
job queue + worker, object storage, PostgreSQL/Supabase migrations with RLS (tested on PostgreSQL 16), Vercel config,
emissions (FRP method), smoke trajectories (experimental), geostationary import/registry, external validation framework.
