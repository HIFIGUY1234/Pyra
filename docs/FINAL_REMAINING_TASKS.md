# Remaining tasks and how to unblock them

Each item below is blocked by something outside this repository, such as credentials, a container runtime or a decision. The software side is finished unless the row says otherwise.

| # | Task | Blocked by | Exact steps to finish |
|---|---|---|---|
| 1 | **VIIRS 750 m authentic data** (VNP14 / VJ114 / VJ214 v002) | Earthdata Login | 1. Create an Earthdata account and approve the LP DAAC application. 2. Generate a user token and put it in the backend environment as `EARTHDATA_TOKEN` (never in git). 3. Run `python -m app.pipeline --viirs750 2025-11-01 2025-11-07` to download a small set. 4. Check the converter's output against the granule metadata: pixel counts per granule and the fire-mask class histogram. 5. Extend the period, then run `python -m app.pipeline --only-new`, which fits the separate 750 m calibration. 6. Regenerate the science report. |
| 2 | **Real notification delivery** | SMTP / webhook provider credentials, plus verified authority contacts | 1. Set `PYROSCOPE_NOTIFY_PROVIDER=smtp` (or `webhook`) and the matching `SMTP_*` or `PYROSCOPE_WEBHOOK_*` variables. 2. Call `GET /api/notifications/check` as admin to test the connection without sending. 3. An administrator registers and verifies a controlled test contact. 4. Call `POST /api/notifications/test/{contact_id}`. 5. Only then approve a real advisory. SMS is not implemented. |
| 3 | **Docker build verification** | No Docker on the development machine | The CI `docker` job builds both images, starts compose, smoke-tests through nginx and checks that no credentials are baked into the images. Its result on GitHub is the evidence. Locally: `cp .env.example .env && docker compose up --build`. |
| 4 | **Pull request** | No `gh` CLI or token in this environment | Open https://github.com/HIFIGUY1234/Pyra/compare/main...feature/pyroscope-complete-final and create the PR. |
| 5 | **Manual data-integration workflow** | `workflow_dispatch` needs a repository token | In GitHub, go to Actions → *Data integration* → Run workflow. It pulls the LFS archives and validates checksums, CSV members, coverage, harmonization and the seam. |
| 6 | **Forecast after S-NPP end of science delivery (2026-11-02)** | Science decision | Retarget the label to NOAA-20 (`forecast.py` target sensor). Re-run `--retrain --compare-forecast` and document the change of target. |
| 7 | **Linear infrastructure** (roads, railways, transmission lines) and settlements | Design work, not data access | Needs distance-to-line logic and much larger Overpass extracts. Until then these are reported as *not loaded*, never as zero. |
| 8 | **Remaining lint warnings** (178, all `no-explicit-any`) | Time | Type the remaining API payloads in `ops.tsx`, `science.tsx` and `App.tsx`. The rule stays a warning. |
| 9 | **Moderate npm advisories** (react-router ≤ 7.17, 2 moderate) | Breaking upgrade | The fix needs react-router-dom 7.x, which is a breaking major. Plan the migration. The CI gate is high/critical, and it passes. |
| 10 | **Python 3.11 local test run on this Windows machine** | Windows Application Control blocks the pandas DLLs in the 3.11 venv | CI runs the full suite on 3.11. pip-audit on 3.11 found no known vulnerabilities. |

Credentials still needed, all supplied through the environment only:
* `EARTHDATA_TOKEN`
* SMTP host, user and password, or a webhook URL, allow-listed host and token
* `PYROSCOPE_ADMIN_PASSWORD` for a production admin
* `FIRMS_MAP_KEY` (optional, for live NRT refresh)
