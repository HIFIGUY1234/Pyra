# PyroScope — completion report (branch `feature/pyroscope-final-completion`)

Every metric below is copied from [SCIENTIFIC_VALIDATION.md](SCIENTIFIC_VALIDATION.md), which
`python -m app.science_report` generates from the loaded records. Nothing is typed by hand there.

Checks run on the final commit (Windows 11, Python 3.10 venv, Node 24):

| Check | Result |
|---|---|
| `python -m pytest tests -q` (backend) | **109 passed** (baseline before this branch: 89) |
| Same suite with every archive replaced by a 133-byte LFS pointer (the CI checkout) | 107 passed (run before the last 2 tests were added) |
| `npm test` (Vitest, frontend) | **16 passed** (no frontend runner existed before) |
| `npm run typecheck` / `npm run build` | OK. No chunk is larger than 500 kB any more (vendor split). |
| `npm run lint` | 0 errors, **233 warnings**, all `no-explicit-any` (down from 240) |
| `python -m app.pipeline --only-new --skip-weather --skip-train` | OK, 54 s, every step logged in `data/processed/pipeline_state.json` |
| `python -m app.pipeline --validate-only` | 0 archive problems; hold-out good; seam verdict partial |
| Live API journey (uvicorn, 21 GET endpoints) | All returned 200. Slowest cold call 4.2 s (first calibration fit); warm calls ≤ 0.33 s |
| `pip-audit` | Pillow 12.x has CVEs → requirement raised to ≥ 13 on Python ≥ 3.11. Python 3.10 cannot install Pillow 13. |
| `npm audit --omit=dev --audit-level=high` | passes (2 moderate) |
| Docker build / GitHub Actions run | **not executed**: no Docker on this machine, and the workflows have not run on GitHub yet |

## A. Status

Statuses: DONE AND TESTED · IMPLEMENTED BUT NOT FULLY VALIDATED · PARTIAL · BLOCKED BY EXTERNAL DATA OR CREDENTIALS · NOT IMPLEMENTED.

| Requirement | Implementation status | Validation status | Evidence |
|---|---|---|---|
| Historical MODIS | DONE AND TESTED | Re-inventoried from the archives | `DL_FIRE_M-C61_848456.zip`: Terra 212,573 and Aqua 470,786 rows, 2000-11-01 → 2011-12-31. ZIP CRC passes; SHA-256 recorded. The collection (C6.1) comes from the archive name, per the FIRMS Readme. The row `version` values `6.03` and `61.03` are kept verbatim and flagged *undocumented*, because readable FIRMS docs do not define them. |
| Terra/Aqua correction | DONE AND TESTED | 20-month block hold-out (simulated) | Real correction covers 2000-11 → 2002-06 (19 months), labelled as estimates. Block test: WAPE 18.4 %, bias +3.7 %, R² 0.920 vs constant ratio 45.3 % / +5.0 % / 0.641. Band coverage 91.4 % (nominal 90). Backward rolling origin bias is +12.2 %, reported as a limitation. |
| Sensor harmonization | DONE AND TESTED | Actual chronological hold-out | Trained on 2017–22, tested on 2012-02 → 2016-12: WAPE 13.0 %, bias −0.3 %, R² 0.960. Constant ratio scores 32.0 % and raw MODIS 85.1 %. |
| NOAA-20 | DONE AND TESTED | Separate stream | 5,109,832 archive rows and 34,176 NRT rows; never pooled. A separate Aqua→NOAA-20 calibration pathway exists (orbit-stable overlap 2018–2022). |
| NOAA-21 | IMPLEMENTED BUT NOT FULLY VALIDATED | Labelled observations only | Records start 2023-03, before the official 2024-01-17 start, and are flagged *pre-operational*. All its Aqua overlap falls in Aqua orbit-drift years (2023+), so a defensible Aqua→NOAA-21 calibration is not possible with this data. |
| S-NPP | DONE AND TESTED | Reference stream | 8,726,813 archive rows; actual values pass through unchanged (test `test_harmonized_never_adds_counts_and_actual_viirs_unchanged`). |
| VIIRS 750 m | BLOCKED BY EXTERNAL DATA OR CREDENTIALS | — | The separate stream, calibration and converter exist. No VNP14/VJ114 granules are loaded: they need Earthdata login and LAADS DAAC download. The converter has not been checked against real granules. |
| Bootstrap uncertainty | DONE AND TESTED | Empirical coverage reported | Year-block bootstrap (200 replicates) refits both stages and draws matched LOYO residuals. Coverage: 93.2 % on the actual hold-out, 91.4 % on Terra→Aqua blocks, 84.5 % on backward rolling origin (below nominal, reported). |
| Real seam test | DONE AND TESTED | Declared verdict | Seam 2012-02, ±24 months. Raw step 6.980 → harmonized 1.027; reference (Aqua) 1.103. Jump falls 1.845 → 0.072 (−96.1 %). **Verdict PARTIAL**: the reference step lies just outside the band, so part of the genuine +10 % is damped. Robustness: ±36 months **pass**; 5 states pass, 3 partial. |
| Held-out validation | DONE AND TESTED | LOYO, 20-month block, forward/backward rolling origin | `harmonize.model_selection`. Five candidate forms compared under a declared acceptance rule; no candidate beat the default, so it was kept. Results are broken down by month, day/night, state, activity level and year. |
| Burning Activity Calendar | IMPLEMENTED BUT NOT FULLY VALIDATED | Existing API tests pass | Not changed on this branch. The UI was not re-verified in a browser this session. |
| Historical trends | IMPLEMENTED BUT NOT FULLY VALIDATED | Existing API tests pass | Not changed on this branch. |
| Anomaly detection | IMPLEMENTED BUT NOT FULLY VALIDATED | Existing API tests pass | Not changed. |
| Forecast | PARTIAL | Chronological test | Test 2024-01 → 2026-11: Brier 0.0971 (climatology 0.1067), ROC-AUC 0.920, PR-AUC 0.823. The extra candidate models in Part 11.3 (LR / RF / LightGBM) were not compared, and results are not broken down by state or month. |
| Population exposure | BLOCKED BY EXTERNAL DATA OR CREDENTIALS | Upload path tested | No population grid is bundled. Upload uses `POST /api/geo/exposure` with source and licence; the layer reports "unavailable", not zero. |
| Infrastructure exposure | BLOCKED BY EXTERNAL DATA OR CREDENTIALS | Upload path tested | Same as population. |
| Critical regions | PARTIAL | Existing tests | Weights are transparent. Exposure components stay unavailable until layers are loaded. |
| Observation intelligence | PARTIAL | Existing tests | Coverage and gaps work (gap periods now in the inventory). No orbit-based overpass prediction: measured local-time histograms only, as stated in the UI. |
| Authentication | DONE AND TESTED | Backend + frontend tests | PBKDF2 hashes, hashed expiring tokens, revocation, lockout, production mode ignores `X-User`. The frontend login/logout/revocation workflow is tested. |
| Government dashboard | IMPLEMENTED BUT NOT FULLY VALIDATED | API tests | UI not re-verified this session. |
| Organisation dashboard | IMPLEMENTED BUT NOT FULLY VALIDATED | Isolation tested (backend) | `test_org_users_cannot_see_other_organisations`. |
| Alert lifecycle | DONE AND TESTED | Backend tests | Generation, acknowledgement, approval, escalation and audit history. Delivery happens only after approval and only to verified contacts. |
| Actual notifications | BLOCKED BY EXTERNAL DATA OR CREDENTIALS | Simulated + mocked webhook | No provider credentials or verified authority contacts. Nothing was sent. |
| PDF/CSV reporting | DONE AND TESTED | Backend tests + frontend download test | — |
| Frontend tests | PARTIAL | 16 Vitest workflow tests | Covered: auth, production gate, API client, downloads, region filter, model selection, seam, inventory with admin recovery. Not covered: map, calendar, alerts UI, Playwright E2E. |
| Backend tests | DONE AND TESTED | 109 passed | — |
| CI/CD | IMPLEMENTED BUT NOT FULLY VALIDATED | Steps run locally | `.github/workflows/ci.yml` and `data-integration.yml`. Not yet run on GitHub. |
| Deployment | IMPLEMENTED BUT NOT FULLY VALIDATED | Not built | Dockerfiles, compose, nginx and [DEPLOYMENT.md](DEPLOYMENT.md). No Docker available to build them. |

## B. Main scientific finding of this branch

The scientific report used to show a "simulated morning-gap" result of WAPE 42.1 %, bias +33.4 %, R² 0.424, which was worse than a constant ratio. That came from a design flaw, not the model. Once the 2000–2011 archive was loaded, the experiment hid Aqua for **135 months (2002-07 → 2013-09)** and trained only on 2017–2022, so it measured a ten-year backward extrapolation.

* It is replaced by a held-out comparison: leave-one-year-out, 20-month blocks (the length of the real Terra-only era), and forward/backward rolling origin, all year-blocked.
* The old design is kept as a labelled *extrapolation stress test*. In it the state-level model degrades (bias +29.7 %), while a national seasonal ratio stays unbiased (+1.0 %). That shows regional detail learned from recent years transfers poorly a decade back.
* For the real 2000–2002 correction, the five model forms give Aqua-equivalent totals that differ by **9.0 %**, consistent with the +12 % backward bias. Both numbers appear in the report and in the API (`/api/morning-gap/sensitivity`).

## C. Files

* **Added:** `backend/tests/test_final.py`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `docker-compose.yml`, `.dockerignore`, `.github/workflows/{ci,data-integration}.yml`, `frontend/src/validation_extra.tsx`, `frontend/vitest.config.ts`, `frontend/tests/*`, `data/processed/archive_checksums.json`, `docs/{FINAL_PROJECT_REPORT,NASA_DEMO_SCRIPT,DEPLOYMENT,SECURITY}.md`.
* **Modified:** `backend/app/{harmonize,acquire,pipeline,science_report,main,db_sync}.py`, `backend/tests/conftest.py`, `backend/requirements.txt`, `frontend/src/{science,completion,lib}.tsx`, `frontend/{package.json,package-lock.json,vite.config.ts}`, `.env.example` (one line), `.gitignore`, `README.md`, `docs/*`.
* **Removed:** none.
* **Database migrations:** none needed (no schema change).
* **New dependencies:** frontend dev only (`vitest`, `jsdom`, `@testing-library/{react,dom,user-event,jest-dom}`). Backend Pillow floor raised.

## D. Remaining blockers and how to clear them

| Blocker | Resolution |
|---|---|
| VIIRS 750 m | Earthdata account → download VNP14/VJ114 granules for the AOI from LAADS DAAC → `python -m app.acquire vnp14 <dir> --satellite "Suomi NPP"` → validate the converter on those granules → pipeline |
| Population / infrastructure | Choose a licensed grid (e.g. WorldPop or GHSL) and OSM extracts; upload through `/api/geo/exposure` with provenance |
| Real notifications | Set `PYROSCOPE_NOTIFY_PROVIDER` and provider secrets; an administrator registers verified authority contacts; test against a controlled endpoint first |
| Orbital overpass prediction | Needs a verified TLE source and an SGP4 dependency, plus validation against observed overpass times; not implemented |
| CI / Docker verification | Push the branch (Actions runs automatically); run `docker compose up --build` on a host with Docker |
| Python 3.10 Pillow CVEs | Run production on Python ≥ 3.11 (Dockerfile uses 3.11) |
| 233 lint warnings | Type the remaining API payloads in `App.tsx` / `ops.tsx` / `science.tsx` incrementally; the rule is kept as a warning, not silenced |
