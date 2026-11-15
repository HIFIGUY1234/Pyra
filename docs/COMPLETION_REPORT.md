# PyroScope — completion report

> **Latest:** branch `feature/pyroscope-software-final` (2026-11-15) adds the operational sensor transition, linear GIS,
> area-weighted population, versioned critical scoring, production config validation, background jobs and frontend
> screens. Current counts: backend **193 passed**, Vitest **24 passed**, lint 0 errors, npm audit 0 vulnerabilities.
> The authoritative status matrix is now [SOFTWARE_COMPLETION_BEFORE_CREDENTIALS.md](SOFTWARE_COMPLETION_BEFORE_CREDENTIALS.md).
> The report below is the earlier `feature/pyroscope-complete-final` snapshot and is kept for history; rows it marks
> NOT IMPLEMENTED for linear infrastructure and the NOAA-20 retarget are superseded.


Base: `main` at 7d9ee06. Every metric comes from a generated file: [SCIENTIFIC_VALIDATION.md](SCIENTIFIC_VALIDATION.md) (`python -m app.science_report`), `data/processed/models/forecast_comparison.json`, `data/processed/noaa21_calibration.json`, `data/auxiliary/tle/validation.json` or the exposure manifests. No number was typed in from memory.

## Checks

| Check | Result |
|---|---|
| Backend `python -m pytest tests -q` (local, Python 3.10) | **136 passed** (109 before + 27 new). 2 third-party deprecation warnings (starlette/httpx, rasterio Affine) |
| Backend tests on Python 3.11 (GitHub Actions, run 43630313262) | **success** |
| Test isolation | Fixed: the suite used to write to `data/pyroscope.db`, because `app.config` was imported before `test_api` redirected `DATABASE_URL`. `conftest.py` now points tests at a temporary copy. The working DB is unchanged after a full run |
| `pip-audit -r backend/requirements.txt` (Python 3.11.9, with sgp4/rasterio/h5py) | **No known vulnerabilities**. Pillow 13.0.0 installs |
| Frontend typecheck / Vitest / build | clean / **16 passed** / OK |
| Frontend lint | 0 errors, **178 warnings** (all `no-explicit-any`; down from 233) |
| `npm audit --omit=dev --audit-level=high` | passes. 2 moderate (react-router; fix is a breaking major) |
| Playwright E2E (local, Chromium) | **5 / 5 passed** (1.9 min) on a throw-away DB copy with real API and data |
| Playwright E2E (GitHub Actions) | **success** |
| Docker images build + compose health + nginx smoke test + no baked credentials (GitHub Actions) | **success**. Not run locally: Docker is not installed |
| CI run 43630313262 (`2e4ef4a`): backend, backend audit, frontend, e2e, docker | **all 6 jobs success** |
| `python -m app.pipeline --validate-only` | 0 archive problems; seam verdict *partial*; NOAA-21 *not_calibrated*; exposure layers loaded; orbit mean residuals 0.82–0.90 min |

## Status matrix

Statuses: DONE AND TESTED · IMPLEMENTED BUT NOT FULLY VALIDATED · PARTIAL · BLOCKED BY EXTERNAL DATA OR CREDENTIALS · NOT IMPLEMENTED.

| Requirement | Status | Evidence |
|---|---|---|
| CI (all required jobs) | DONE AND TESTED | Run 43630313262: 6/6 green, including new e2e and docker jobs. CI now also runs on `feature/**` pushes |
| Python 3.11 standardisation + Pillow fix | DONE AND TESTED | `.python-version` 3.11, Dockerfile 3.11, CI 3.11; pip-audit clean. The local Windows 3.11 venv cannot run pandas (Application Control), so tests run locally on 3.10 and on 3.11 in CI |
| Docker / compose | DONE AND TESTED | Built and health-checked in CI (`docker` job). Not run on the development machine |
| Historical MODIS, harmonization, morning gap, seam, bootstrap | DONE AND TESTED | Unchanged; metrics identical after regeneration (hold-out WAPE 13.0 %, seam *partial*) |
| VIIRS 750 m acquisition (search/download/manifest) | IMPLEMENTED BUT NOT FULLY VALIDATED | CMR search works live (15 NOAA-21 granules for 2025-11-01). Download is tested for resume, corruption and de-duplication on local files. Never run against LP DAAC |
| VIIRS 750 m authentic data + calibration | BLOCKED BY EXTERNAL DATA OR CREDENTIALS | Earthdata Login not configured. Converter rewritten to the LAADS filespec and tested only on synthetic HDF5. UI says *unavailable* |
| NOAA-21 calibration | DONE AND TESTED | The study was run; under the declared rule the result is **not calibrated**. Forward test state-month WAPE: identity 7.01 %, best candidate 6.69 %; band coverage 17–33 %. NOAA-21 stays a separate actual stream |
| Population exposure | DONE AND TESTED | WorldPop 2020 1 km (CC BY 4.0, SHA-256 recorded). 1,380,004,385 people, 4,885 cells. Totals test on a synthetic raster. Raster is off the 30″ lattice (documented) |
| Infrastructure exposure (point facilities) | DONE AND TESTED | OSM, 11 categories, **161,952** facilities after cleaning (816 co-located duplicates removed, 0 cross-category losses after the fix). Retry, clean and nearby tests |
| Infrastructure exposure (roads, railways, transmission, settlements) | NOT IMPLEMENTED | Reported *not loaded*, never zero |
| Critical-region scoring with exposure | IMPLEMENTED BUT NOT FULLY VALIDATED | State comparison: population, detections, forecast, facilities. Missing layers give *unavailable*. Weights were not re-tuned |
| Forecast model comparison | DONE AND TESTED | 5 models on equal footing plus 3 rolling origins. XGBoost Brier 0.09726 (BSS 0.089, AUC 0.920, PR-AUC 0.823, ECE 0.006) vs climatology 0.10673. HGB 0.09756 fails the rule, so **XGBoost retained**. Breakdowns by state (3 of 34 unreliable), month, season, land use, activity, coverage. Model cards written. LightGBM excluded, with reason |
| Forecast day/night breakdown | NOT IMPLEMENTED | Not applicable: the target pools day and night detections in a 7-day window (stated in the JSON) |
| SGP4 orbit prediction | DONE AND TESTED | Live CelesTrak TLEs (epoch 2026-11-14). Validated on 400 actual detections per satellite: mean abs residual 0.82–0.90 min, 95th percentile ≤ 2.2 min, 100 % within 10 min |
| Notifications: logic (approval gate, verified contacts, retry, SSRF, no redirect, TLS, dedupe) | DONE AND TESTED | Wire-level tests against a real local SMTP server (success, transient retry, unreachable) and webhook SSRF/redirect tests |
| Notifications: real external delivery | BLOCKED BY EXTERNAL DATA OR CREDENTIALS | No provider credentials or verified authority contacts. Nothing was sent. SMS is not implemented |
| Rate limiting | DONE AND TESTED | In-process buckets (login 429 test) plus nginx `limit_req` |
| Audit retention | DONE AND TESTED | Archive, verify, then prune. Routine actions only; decisions are never deleted (test) |
| Alert lifecycle, auth, org isolation, reports | DONE AND TESTED | Backend tests plus E2E journeys B, C and D |
| Calendar, trends, anomalies, map, data management | DONE AND TESTED | Rendered and asserted in E2E journey A (previously only API-tested) |
| Frontend tests | DONE AND TESTED | 16 Vitest + 5 Playwright journeys, desktop and mobile |
| Pull request | BLOCKED BY EXTERNAL DATA OR CREDENTIALS | Branch pushed. No `gh`/token here. Open via compare URL |
| Manual data-integration workflow run | BLOCKED BY EXTERNAL DATA OR CREDENTIALS | `workflow_dispatch` needs a token or the GitHub UI |

## Scientific findings this branch

* **NOAA-21:** on the operational period, leaving NOAA-21 counts unchanged is as good as any ratio adjustment. No candidate beat identity and the national ratio by ≥ 1 WAPE point on both splits. Bootstrap bands are far too narrow (17–33 % coverage), so a calibration would overstate certainty.
* **Forecast:** gradient-boosted trees, XGBoost and HGB, tie to within 0.0003 Brier on the main split and on every rolling origin. The gain over climatology is real but modest (BSS 0.089). Most skill comes from recent detections and seasonal recurrence.
* **Reference risk:** NASA CMR metadata states that S-NPP VIIRS science-data delivery ceased on 2026-11-02. The forecast label and the harmonization reference are S-NPP, so they need a NOAA-20 retarget for future updates.
* **Exposure:** in the 7 days to 2026-10-31 there were 17,798 actual detections at 14,150 locations; median 23,398 people within 5 km. This reflects agricultural burning near villages. It is a proximity count, not harm.

## Files

* **Added:**
  * backend: `backend/app/{orbits,noaa21,forecast_eval,population,infrastructure,viirs750,exposure,retention}.py`, `backend/tests/test_complete.py`
  * frontend: `frontend/src/completion_final.tsx`, `frontend/e2e/journeys.spec.ts`, `frontend/playwright.config.ts`
  * config: `.python-version`
  * data: `data/auxiliary/{population,infrastructure,exposure,tle}/*` (derived files and manifests), `data/processed/noaa21_calibration.json`, `data/processed/models/forecast_comparison.json`
  * docs: `docs/{MODEL_COMPARISON,POPULATION_EXPOSURE,INFRASTRUCTURE_EXPOSURE,ORBIT_PREDICTION,END_TO_END_TESTING,FINAL_REMAINING_TASKS}.md`
* **Modified:**
  * backend: `backend/app/{main,notify,security,acquire,pipeline,science_report}.py`, `backend/requirements.txt`, `backend/tests/conftest.py`
  * frontend: `frontend/src/{App,charts,completion,map,ops,science}.tsx`, `frontend/package*.json`, `frontend/nginx.conf`
  * deployment and config: `docker-compose.yml`, `.github/workflows/ci.yml`, `.env.example` (lines appended, no values), `.gitignore`, `.dockerignore`
  * docs: README, `docs/*`
* **Not committed:** WorldPop GeoTIFF (git-ignored; SHA-256 in manifest), `backend/.venv*`, `data/e2e.db`, Playwright output. `data/pyroscope.db` is unchanged.
* **New dependencies:** backend `sgp4`, `rasterio`, `h5py`; frontend dev `@playwright/test`.

## Credentials still needed (environment only, never in git)

`EARTHDATA_TOKEN` (750 m) · SMTP or webhook provider settings + verified contacts (real delivery) · production `PYROSCOPE_ADMIN_PASSWORD` · optional `FIRMS_MAP_KEY`.

Remaining work and exact unblock steps: [FINAL_REMAINING_TASKS.md](FINAL_REMAINING_TASKS.md).

## 2026-11-15 update: fire intelligence and Vercel/Supabase readiness

Superseding status for everything added on branch `feature/pyroscope-ultimate-completion` is in
[ULTIMATE_FINAL_COMPLETION_REPORT.md](ULTIMATE_FINAL_COMPLETION_REPORT.md): fire events (8,948 India events, 25-31 Oct 2026),
FRP/FRE emission estimates, experimental smoke trajectories, burned-area pipeline (blocked by the LAADS licence),
geostationary registry/import, independent-validation framework (PyroScope 13.0% WAPE vs constant ratio 32.0%),
authentic WorldPop area-weighted rebuild, durable job queue + worker, object storage, PostgreSQL/Supabase migrations
with RLS and a Vercel frontend configuration. Core harmonization results and the PARTIAL seam verdict are unchanged.
