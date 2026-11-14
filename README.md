# PyroScope — MODIS–VIIRS Hot-Spot Harmonization & Early-Warning Platform

NASA Space Apps Challenge 2026 — *Harmonization of MODIS and VIIRS Hot Spots*.

PyroScope turns the split MODIS / VIIRS active-fire record into one continuous, uncertainty-aware
**VIIRS-equivalent** burning-activity record, validates it chronologically, and connects it to a burning
activity calendar, historical analysis, anomaly detection and a calibrated 7-day **hotspot-detection**
probability with a human-in-the-loop authority alert workflow (India focus).

| Doc | What |
|---|---|
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | Scientific method: morning-gap fixer, sensor harmonizer, uncertainty, validation, seam test, forecast |
| [docs/SCIENTIFIC_VALIDATION.md](docs/SCIENTIFIC_VALIDATION.md) | Metrics computed from the loaded data (regenerate with `python -m app.science_report`) |
| [docs/DATA_ACQUISITION.md](docs/DATA_ACQUISITION.md) | Git LFS recovery, FIRMS API / archive download, VIIRS 750 m, uploads |
| [docs/COMPLETION_REPORT.md](docs/COMPLETION_REPORT.md) | Requirement status table, test results, blockers |
| [docs/FINAL_PROJECT_REPORT.md](docs/FINAL_PROJECT_REPORT.md) | Problem, method, data, results, limitations, reproducibility |
| [docs/NASA_DEMO_SCRIPT.md](docs/NASA_DEMO_SCRIPT.md) | 6-minute demo with the screens and real numbers |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Setup, Docker, production configuration, backup / recovery, performance |
| [docs/SECURITY.md](docs/SECURITY.md) | Authentication, input handling, notifications, dependency audit, known gaps |
| [docs/MODEL_COMPARISON.md](docs/MODEL_COMPARISON.md) | Forecast candidate models on equal footing, rolling origins, model cards |
| [docs/POPULATION_EXPOSURE.md](docs/POPULATION_EXPOSURE.md) / [docs/INFRASTRUCTURE_EXPOSURE.md](docs/INFRASTRUCTURE_EXPOSURE.md) | WorldPop 2020 and OpenStreetMap exposure layers |
| [docs/ORBIT_PREDICTION.md](docs/ORBIT_PREDICTION.md) | SGP4 overpass prediction and its validation against actual detections |
| [docs/END_TO_END_TESTING.md](docs/END_TO_END_TESTING.md) | Playwright browser journeys |
| [docs/FINAL_REMAINING_TASKS.md](docs/FINAL_REMAINING_TASKS.md) | What is still blocked and exactly how to unblock it |
| `data/processed/ingestion_report.md` | Generated inventory: what is loaded, what is missing |

## Datasets in this repository (Git LFS)

| File | Sensor | Content |
|---|---|---|
| `DL_FIRE_M-C61_848456.zip` | MODIS Terra + Aqua, C6.1 | archive Terra 2000-11-01 / Aqua 2002-07-04 → 2011-12-31 |
| `DL_FIRE_M-C61_846937.zip` | MODIS Terra + Aqua, C6.1 | archive 2012-01 → 2026-08, NRT 2026-09 → 10 |
| `DL_FIRE_SV-C2_846940.zip` | Suomi NPP VIIRS 375 m, C2 | archive 2012-01-20 → 2026-07, NRT → 2026-10 |
| `DL_FIRE_J1V-C2_846938.zip` | NOAA-20 VIIRS 375 m, C2 | archive 2018-04-01 → 2026-07, NRT → 2026-10 |
| `DL_FIRE_J2V-C2_846939.zip` | NOAA-21 VIIRS 375 m, C2 | archive 2023-03 → 2026-07, NRT → 2026-10 |

Area: bounding box 68–98° E, 6–36° N (India). **Not included:** VIIRS 750 m (VNP14/VJ114/VJ214 v002 — searchable, but download needs Earthdata Login, not configured). See the ingestion report and `docs/DATA_ACQUISITION.md`.

Auxiliary layers (committed as derived files with manifests): WorldPop 2020 1 km population (CC BY 4.0), OpenStreetMap facilities in 11 categories (ODbL), CelesTrak TLEs for the five satellites.

The archives are LFS objects. A plain clone gives 133-byte pointer files; PyroScope detects them and says so.

```bash
git lfs install && git lfs pull            # or, without git-lfs:
cd backend && python -m app.acquire lfs    # downloads + verifies SHA-256 against the pointer
```

## Quick start

```bash
# backend (Python 3.11+)
cd backend
python -m pip install -r requirements.txt
cp ../.env.example ../.env                 # optional; defaults work for local evaluation
python -m app.migrate                      # additive schema upgrade (backs up SQLite first)
python -m app.pipeline --recover-lfs       # ingest -> summaries -> weather -> forecast -> DB (first run ~10-20 min)
uvicorn app.main:app --port 8000

# frontend
cd ../frontend
npm ci
npm run dev                                # http://localhost:5173 (proxies /api to :8000)
```

Processed Parquet summaries and a trained model are committed, so the API works immediately after
`pip install` even before the pipeline is re-run.

Pipeline flags: `--only-new` (incremental: only unseen sources), `--skip-ingest`, `--skip-weather`,
`--skip-train` / `--retrain`, `--rebuild-geo`, `--recover-lfs`, `--skip-report`, `--refresh-exposure`, `--refresh-tle`,
`--compare-forecast`, `--viirs750 START END`, `--dry-run` (show the plan,
change nothing) and `--validate-only` (integrity + hold-out + seam as JSON). Unknown flags are rejected.
The forecast is retrained only when new data were ingested. Step outcomes go to `data/processed/pipeline_state.json`.

Containers: `cp .env.example .env && docker compose up --build` serves UI + API on :8080 (see `docs/DEPLOYMENT.md`).

## Tests & checks

```bash
cd backend && python -m pytest tests -q     # 136 tests, on a temp copy of the DB (API, science, LFS, auth, alerts, GIS, orbits, exposure, SMTP/webhook, rate limits)
cd frontend && npm run typecheck && npm run lint && npm test && npm run build   # 16 Vitest workflow tests
cd frontend && npx playwright install chromium && npm run e2e                    # 5 browser journeys against the real API
```

CI (`.github/workflows/ci.yml`) runs these on every push and PR, with the archives left as LFS pointers,
plus `pip-audit`, `npm audit` and the Playwright journeys. `data-integration.yml` (manual) pulls the real archives and validates them.

## Authentication

* `PYROSCOPE_AUTH_MODE=dev` (default): demo personas via the `X-User` header for zero-config judging;
  Bearer tokens are honoured too. The UI marks this as **DEV PERSONA**.
* `PYROSCOPE_AUTH_MODE=production`: every `/api` route except health/meta/login needs a Bearer session.
  Bootstrap the admin with `PYROSCOPE_ADMIN_PASSWORD`, then create accounts with `POST /api/users`.
  Passwords: PBKDF2-SHA256; sessions: random tokens stored only as SHA-256, expiring, revoked on logout;
  5 failed logins lock an account for 15 minutes.

## Notifications

Default is **simulated** (in-app queue, clearly labelled). Optional providers (`webhook`, `smtp`) are
enabled by environment variables and deliver **only** to administrator-verified authority contacts,
**only** after an officer approves the alert. Transient failures are retried with backoff; webhooks are https-only,
allow-listed, SSRF-guarded and never follow redirects; SMTP supports STARTTLS/SSL. Every attempt is logged
(`/api/notifications/log`). No real provider has been exercised from this repository yet (no credentials).
PyroScope never issues public emergency warnings or dispatches emergency services.

## Scientific ground rules

MODIS and VIIRS counts are never added; actual VIIRS observations pass through unchanged; 375 m and
750 m are never pooled; FRP is kept separate from counts; missing observations are never zero;
validation is chronological; the seam is not forced smooth; hotspot probability is not ignition
probability; land use decides who responds, not why it burned.

Data: NASA FIRMS (MODIS C6.1, VIIRS C2), NASA POWER, NASA MCD12Q1 via GIBS, geoBoundaries, WorldPop (CC BY 4.0),
© OpenStreetMap contributors (ODbL), CelesTrak.
