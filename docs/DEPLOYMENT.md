# PyroScope — setup, deployment and operations

PyroScope is tied to no cloud provider. It runs as two processes: a FastAPI backend and a static
React build. State lives in `data/`: archives, Parquet summaries, the SQLite database and reports.

## 1. Local setup

```bash
# Python 3.11 (pinned in .python-version, Dockerfile and CI). 3.10 runs but cannot install the patched Pillow 13.
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env                         # optional for local evaluation
python -m app.migrate                              # additive schema upgrade; SQLite is backed up first
python -m app.pipeline --recover-lfs               # first full run; afterwards use --only-new
uvicorn app.main:app --port 8000

cd ../frontend
npm ci
npm run dev                                        # http://localhost:5173, proxies /api to :8000
```

### Pipeline commands

| Command | Effect |
|---|---|
| `python -m app.pipeline --dry-run --only-new` | Prints archives, pointer stubs and the sources that would be ingested. Changes nothing. |
| `python -m app.pipeline --validate-only` | Checks archive integrity (ZIP CRC, SHA-256), the hold-out metrics and the seam verdict, then prints JSON. |
| `python -m app.pipeline --only-new` | Incremental ingest. Each source is checkpointed in `data/processed/datasets.json`. |
| `--skip-ingest`, `--skip-weather`, `--skip-train` / `--retrain`, `--rebuild-geo`, `--recover-lfs`, `--skip-report` | As named. Unknown flags are rejected. |
| `--refresh-exposure` | Downloads WorldPop 2020 (India, 1 km) and OpenStreetMap infrastructure, rebuilds exposure layers. |
| `--refresh-tle` | Fetches current CelesTrak TLEs and re-validates SGP4 overpass prediction against recent detections. |
| `--compare-forecast` | Runs the forecast candidate-model comparison (≈10–15 min). |
| `--viirs750 START END` | Searches, downloads (needs `EARTHDATA_TOKEN` or `~/.netrc`) and converts VIIRS 750 m granules; skipped with a logged reason when credentials are absent. |

Each step's outcome and duration is appended to `data/processed/pipeline_state.json` (git-ignored).

### Tests

```bash
cd backend && python -m pytest tests -q
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
cd frontend && npx playwright install chromium && npm run e2e   # browser journeys, see END_TO_END_TESTING.md
```

Tests run on a temporary copy of `data/pyroscope.db` (set in `tests/conftest.py`); the working database is never modified.

## 2. Containers

```bash
cp .env.example .env          # set PYROSCOPE_AUTH_MODE=production and PYROSCOPE_ADMIN_PASSWORD
docker compose up --build     # UI + API on http://localhost:8080
```

* `backend/Dockerfile`: Python 3.11-slim, non-root user, health check on `/api/health` (the database must be reachable).
* `frontend/Dockerfile`: Node build stage, then nginx. `frontend/nginx.conf` proxies `/api` to the backend and sets basic security headers.
* `./data` is mounted as a volume, so the database, Parquet files and reports survive rebuilds. The archives are mounted read-only.
* No credentials are baked into the images. Secrets come from `.env` or the orchestrator's secret store.

> These files have **not** been built on the development machine (Docker was unavailable). Build them once before relying on them.

## 3. Production configuration

| Topic | Setting |
|---|---|
| Authentication | `PYROSCOPE_AUTH_MODE=production`: only Bearer sessions; the `X-User` header is ignored. Create the admin via `PYROSCOPE_ADMIN_PASSWORD`, then accounts via `POST /api/users`. |
| Database | Default is SQLite. For PostgreSQL set `DATABASE_URL=postgresql+psycopg://…` and install `psycopg[binary]`. Large observation tables stay in Parquet by design. |
| CORS | `PYROSCOPE_CORS_ORIGINS`: the exact public origin(s) only. |
| Reverse proxy / HTTPS | Terminate TLS in front of nginx (or another proxy). Forward `X-Forwarded-*`; uvicorn runs with `--proxy-headers`. |
| Secrets | `.env` is git-ignored. In production use the platform's secret store. In CI use GitHub Actions secrets, never workflow literals. |
| Notifications | `PYROSCOPE_NOTIFY_PROVIDER=simulated` by default. For `webhook` or `smtp`, set the provider variables, register verified contacts and test against a controlled endpoint first. |
| Logging | uvicorn access and error logs go to stdout; collect them with the container runtime. |
| Monitoring | Poll `GET /api/health`: `status`, `database.ok`, `storage.free_gb`, `storage.low` (< 2 GB). Pipeline failures appear in `pipeline_state.json` under `last_failure`. |

## 4. Backup and recovery

| Asset | Backup | Recovery |
|---|---|---|
| `data/pyroscope.db` (users, alerts, audit and notification logs) | `sqlite3 data/pyroscope.db ".backup data/backups/pyroscope-$(date +%F).db"`. `python -m app.migrate` also backs up before any schema change. | Stop the API, copy the backup over `data/pyroscope.db`, start the API, check `/api/health`. |
| PostgreSQL | `pg_dump -Fc` | `pg_restore` |
| FIRMS archives (`*.zip`) | Git LFS (SHA-256 in `data/processed/archive_checksums.json`) | `python -m app.pipeline --recover-lfs`. The download is accepted only if size and SHA-256 match the pointer. |
| Parquet summaries, forecast model | Derived data | `python -m app.pipeline --skip-weather` (add `--retrain` for the model) |
| Reports | `data/reports/` | Regenerate from the UI or `POST /api/reports/generate` |

`data/backups/` is git-ignored.

## 5. Performance (measured on the development machine, live uvicorn)

| Endpoint | Cold | Warm |
|---|---|---|
| `/api/validation` | 0.24 s | 0.25 s |
| `/api/calendar?region=state:Punjab` | 0.54 s | 0.33 s |
| `/api/morning-gap/analysis` | 4.2 s (first calibration fit and model selection, then cached) | — |
| `/api/anomalies?region=state:Punjab` | 2.0 s | — |
| `/api/hotspots` (one month, 2,000 points) | 0.23 s | — |
| Full downstream pipeline (no new ingest) | 54 s | — |

The map never asks for all observations at once: hotspots are filtered and capped server-side, and the grid-cell layer is aggregated.
