# Remaining tasks and how to unblock them

Updated 2026-11-15 (branch `feature/pyroscope-software-final`). All software that does not need your credentials or
external data access is finished; see [SOFTWARE_COMPLETION_BEFORE_CREDENTIALS.md](SOFTWARE_COMPLETION_BEFORE_CREDENTIALS.md).
Every item below is blocked by something outside the repository. Step-by-step setup: [MANUAL_SETUP_AFTER_CODE_COMPLETION.md](MANUAL_SETUP_AFTER_CODE_COMPLETION.md).

| # | Task | Blocked by | Exact steps to finish |
|---|---|---|---|
| 1 | **VIIRS 750 m authentic data** (VNP14 / VJ114 / VJ214 v002) | Earthdata Login | 1. Create an Earthdata account and approve LP DAAC. 2. Put `EARTHDATA_TOKEN` in `.env` (or a `~/.netrc` entry for `urs.earthdata.nasa.gov`). 3. Check `GET /api/viirs750/credentials` shows *configured*. 4. Run `python -m app.pipeline --viirs750 2025-11-01 2025-11-07`. 5. `validate_granule` checks name, collection 002, date, platform attribute and FP array lengths; confirm `real_data_verification` turns from BLOCKED_BY_CREDENTIALS to verified. 6. Extend the period and fit the separate 750 m calibration. |
| 2 | **Real notification delivery** | SMTP / webhook credentials and verified authority contacts | 1. Set `PYROSCOPE_NOTIFY_PROVIDER` and the `SMTP_*` or `PYROSCOPE_WEBHOOK_*` variables. 2. `python -m app.system_config` must exit 0. 3. As admin: `GET /api/notifications/checklist`, then `GET /api/notifications/check` (no send). 4. Register and verify a controlled test contact you own. 5. `POST /api/notifications/test/{contact_id}`. SMS is not implemented. |
| 3 | **Linear GIS extract** (roads, rail, power, settlements) | Geofabrik not reachable from the development sandbox | Run Actions → *Data integration* with `linear_gis: true`, or locally `cd backend && python -m app.linear_gis fetch && python -m app.linear_gis build`. Code and tests are done; until built, the layer reads *not loaded*. |
| 4 | **Area-weighted population rebuild on the real raster** | WorldPop not reachable from the sandbox | Run *Data integration* with `population: true`, or `python -m app.pipeline --population <tif>`. Method and sensitivity are implemented and tested. |
| 5 | **Production admin and deployment** | Your password, domain and host | Set `PYROSCOPE_AUTH_MODE=production`, `PYROSCOPE_ADMIN_PASSWORD`, exact `PYROSCOPE_CORS_ORIGINS`; then `docker compose up --build`. No paid service is deployed by this repository. |
| 6 | **Live NRT refresh** (optional) | `FIRMS_MAP_KEY` | Free key from FIRMS; set in `.env`. NRT rows are never used as forecast labels. |

Resolved in this branch (no longer blocked): forecast retarget after S-NPP (per-sensor NOAA-20 / NOAA-21 models and an
operational selector), linear-infrastructure design, `no-explicit-any` warnings (0), moderate npm advisories (0),
Docker verification (CI `docker` job), PR tooling (`gh` available).
