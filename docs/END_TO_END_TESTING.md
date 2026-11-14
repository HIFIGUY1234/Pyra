# End-to-end browser tests (Playwright)

`frontend/e2e/journeys.spec.ts`, configured in `frontend/playwright.config.ts`.

## What runs

The tests drive Chromium against the **real** FastAPI backend and the **loaded** data. Nothing is mocked.

* Playwright starts two servers:
  * the backend (`uvicorn app.main:app` on :8000), using a throw-away copy of the database (`data/e2e.db`, git-ignored);
  * the Vite dev server on :5173.
* The working `data/pyroscope.db` is never touched.
* An admin password (`E2e-Admin-Passw0rd`) is set only for this run, through `PYROSCOPE_ADMIN_PASSWORD`. It is a test fixture, not a credential.
* Reports go to `data/e2e_reports/` (git-ignored).

| Journey | Persona | Checks |
|---|---|---|
| A — historical fire researcher | analyst | Dashboard; data inventory lists the real archive names; live map renders; morning-gap estimates; harmonization page shows 375 m / 750 m streams and the 750 m *unavailable/loaded* state; validation page shows the seam verdict, model selection and NOAA-21 study result; calendar for Punjab; anomalies; reports |
| B — forest officer | gov_officer | Government dashboard exposure panel waits until the real hotspot exposure is computed; forecast comparison panel shows the retention decision and the "not a verified ignition" wording; critical-regions state table loads (Punjab row); alert rules evaluated, an alert acknowledged and approved through the UI; API check that the alert is APPROVED/ESCALATED and that **no delivery has status SENT** (simulated provider) |
| C — organisation | org.user | Registers an organisation, adds a facility, sees it; switches to analyst and gets "Organisation persona required" (isolation) |
| D — administrator | password login | Wrong password is rejected; correct password signs in with a session token; LFS recovery button visible; thresholds page; SGP4 overpass panel with "Prediction - not a hotspot" and validation against actual Suomi NPP detections; `/api/health` database ok; logout |
| Mobile | — | 390 × 844 viewport: navigation menu shows, no horizontal overflow |

Screenshots are written to `frontend/test-results/screens/*.png`. CI uploads them as evidence; they are not committed.

## Run locally

```bash
cd frontend
npm ci
npx playwright install chromium
npm run e2e                                  # = playwright test
PYROSCOPE_E2E_PYTHON=/path/to/python npm run e2e   # if the backend venv is elsewhere
```

By default the config uses `backend/.venv/Scripts/python.exe` on Windows when it exists, and `python` otherwise.
If an earlier run was interrupted, stop any leftover process on :8000 / :5173 first. The config refuses to reuse a running server on purpose, so it never tests the wrong database.

## Results (2026-11-15, Windows 11, Chromium headless shell 1.49)

* All 5 tests passed in 1.9 min (cold server; the first calibration fit dominates).
* Journey B re-run after the exposure assertions were strengthened: passed in 37 s.

Screens checked by eye: government exposure table (17,798 detections at 14,150 locations, last 7 days), critical-regions state table, forecast comparison, SGP4 pass table for Suomi NPP, NOAA-21 study, 750 m availability.

## CI

The `e2e` job in `.github/workflows/ci.yml` runs after the backend and frontend jobs. It uses Python 3.11 and Node 20, installs Chromium with its system dependencies, and sets `PYROSCOPE_E2E_PYTHON=python`.

It works on the LFS-pointer checkout, because the committed Parquet summaries and auxiliary layers are enough for every journey.

## Not covered

* Real external notification delivery: there are no provider credentials. The SMTP path is covered by a backend test against a real local SMTP server.
* Production auth mode end-to-end. The tests run with `PYROSCOPE_AUTH_MODE=dev`, plus a real password login for the admin. Production mode is covered by backend tests.
* Firefox and WebKit. Only Chromium is installed.
