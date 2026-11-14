# Software completion before credentials — final matrix

Branch `feature/pyroscope-software-final` (2026-11-15), fast-forwarded to `main` after CI passed.
Every number below comes from a generated file or a command run on this date. Nothing was typed in from memory.

Statuses: DONE AND TESTED · IMPLEMENTED BUT NOT FULLY VALIDATED · PARTIAL · BLOCKED BY EXTERNAL DATA ·
BLOCKED BY CREDENTIALS · BLOCKED BY MANUAL USER ACTION · NOT IMPLEMENTED.

## Final matrix

| Area | Status | Evidence |
|---|---|---|
| Historical vs operational reference separation | DONE AND TESTED | `app/operational.py`; `/api/reference/operational`, `/transition`, `/platform/{sensor}`; `tests/test_operational.py` |
| NOAA-20 independent model | DONE AND TESTED | Test period: Brier 0.0926, BSS 0.097, ROC-AUC 0.926, ECE 0.0078, 493,884 rows. Own labels only, no NRT, no pooling |
| NOAA-21 independent model | DONE AND TESTED | Test period: Brier 0.1223, BSS 0.172, ROC-AUC 0.895, ECE 0.0344, 194,661 rows. Labels from 2024-01-17 only |
| Operational selector (C1–C6) | DONE AND TESTED | Both successors pass; evidence default NOAA-21. Admin `PUT /api/reference/operational` accepts only candidates that pass; audited |
| No stale S-NPP as live | DONE AND TESTED | S-NPP served only with `?sensor=Suomi NPP` and flagged STALE_RETIRED_SENSOR; no silent fallback between sensors |
| Bridge studies | DONE AND TESTED | NOAA-20→S-NPP, NOAA-21→S-NPP, NOAA-21→NOAA-20: all *not calibrated* under the strict rule. Transition verdict NOT_BRIDGED |
| NOAA-21 not-calibrated conclusion | DONE AND TESTED | Unchanged (`noaa21_calibration.json`) |
| Seam diagnostics | PARTIAL | Verdict stays PARTIAL: Aqua step 1.103 is outside the harmonized band 0.938–1.093; jump reduced 96 %. Seasonal residual jumps: winter 0.149, pre-monsoon 0.044, monsoon 0.356, post-monsoon 0.052. Thresholds unchanged |
| Forecast metrics + model cards | DONE AND TESTED | BSS, ECE, specificity, breakdowns by month, season, state, land use, coverage, activity; `/api/forecast/models` |
| VIIRS 750 m code path (search, download, validate) | IMPLEMENTED BUT NOT FULLY VALIDATED | CMR search with Search-After paging; credential status without secrets; `validate_granule` tested on synthetic HDF5 |
| VIIRS 750 m authentic granules | BLOCKED BY CREDENTIALS | `real_data_verification: BLOCKED_BY_CREDENTIALS` until Earthdata Login is set |
| Linear GIS (roads, rail, power, settlements) | IMPLEMENTED BUT NOT FULLY VALIDATED | Osmium PBF parser, km lengths per cell, nearest / within; tested on a fixture PBF. No unrestricted Overpass queries |
| Linear GIS India extract | BLOCKED BY EXTERNAL DATA | Geofabrik not reachable from the sandbox; *Data integration* workflow (`linear_gis: true`) builds it |
| WorldPop area-weighted allocation + sensitivity | IMPLEMENTED BUT NOT FULLY VALIDATED | Exact spherical area shares; totals conserved on synthetic rasters; `compare_methods`. Real-raster rebuild needs the WorldPop download (workflow `population: true`) |
| Critical-region scoring (versioned) + sensitivity | DONE AND TESTED | Profiles v2-balanced (default), hazard-led, exposure-led, v1-legacy, custom-N. Hazard-led Spearman 0.954, top-20 overlap 0.55; minimum overlap 0.8 under ±20 % weight perturbation; v2 over 15 historical issues: Spearman 0.539, hit rate 0.90 |
| Orbit TLE refresh errors / stale warning | DONE AND TESTED | `last_refresh.json` records failures; `/api/orbits/status` exposes `last_refresh` and per-TLE `stale` + warning |
| `no-explicit-any` | DONE AND TESTED | 146 → 0; rule set to `error` (not disabled) |
| npm audit | DONE AND TESTED | 0 vulnerabilities at `--audit-level=moderate`; CI gate |
| Production config validation + startup guard | DONE AND TESTED | `python -m app.system_config`; API refuses to start in production on errors; CI step with test-only values |
| Admin bootstrap indicator | DONE AND TESTED | `/api/health` → `admin_bootstrap`, `auth_mode` |
| Notification readiness, fixtures, checklist | DONE AND TESTED | Local SMTP server fixture, webhook retry + redaction tests, `/api/notifications/checklist` |
| Real notification delivery | BLOCKED BY CREDENTIALS | No provider credentials and no verified authority contacts. No real notification was sent |
| Frontend screens (incl. reference, sensors, products, models, exposure, orbits, system) | DONE AND TESTED | Vitest 24 passed; Playwright journeys A–E in CI |
| Pipeline flags, migrations, background jobs | DONE AND TESTED | `--linear-gis`, `--sensor-models`; additive migrations with backup; jobs with cancel and one-per-kind |
| Docker images | DONE AND TESTED | CI `docker` job: build, compose health, nginx smoke, no baked credentials |
| Production deployment | BLOCKED BY MANUAL USER ACTION | Needs your host, domain, admin password. No paid service was deployed |

## A. Checks run (2026-11-15)

| Check | Result |
|---|---|
| `cd backend && python -m pytest tests -q` | **193 passed** before the final two tests were added; the last commit adds 2 more (orbit refresh failure, stored bridge studies) |
| `npm run typecheck` / `npm run lint` | clean / 0 errors, 32 warnings (`react-refresh/only-export-components`, file structure only) |
| `npx vitest run` | **24 passed** (6 files) |
| `npm run build` | OK |
| `npm audit --audit-level=moderate` | 0 vulnerabilities |
| `python -m app.pipeline --validate-only` | 0 archive problems; NOAA-21 *not_calibrated*; exposure layers loaded; orbit mean residuals 0.82–0.90 min |
| `python -m app.pipeline --dry-run --only-new` | plan printed, nothing changed |
| CI (GitHub Actions) | backend, backend audit, frontend, docker green on 27ce2dc; journey E failed on a cold 89 s bridge recomputation, fixed by serving the stored study. **f4c693c: all 6 jobs green** (run 43653638188), then fast-forwarded to `main` |

## B. What is blocked by credentials

* `EARTHDATA_TOKEN` (or `~/.netrc`): VIIRS 750 m authentic download and validation.
* SMTP or webhook credentials: real notification delivery.
* `PYROSCOPE_ADMIN_PASSWORD`: production admin bootstrap.
* `FIRMS_MAP_KEY` (optional): live NRT refresh.

## C. What is blocked by external data

* Geofabrik India PBF (linear GIS extract) and the WorldPop raster rebuild: unreachable from the development sandbox; the *Data integration* workflow runs both.

## D. What is blocked by manual user action

* Verified authority contacts (only you can confirm real recipients).
* Production host, domain and TLS.
* Choosing to override the evidence-default operational reference (admin action, optional).

## E. Manual setup

See [MANUAL_SETUP_AFTER_CODE_COMPLETION.md](MANUAL_SETUP_AFTER_CODE_COMPLETION.md) and [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).

## F. Not implemented

* SMS delivery.
* Day/night forecast split (the target pools day and night detections in a 7-day window, by design).
