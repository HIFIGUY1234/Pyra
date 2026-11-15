# PyroScope — Ultimate final completion report

Branch `feature/pyroscope-ultimate-completion` (from `main` @ `ed07de1`, which was the latest `origin/main` on
2026-11-15). Commits: `b006785` E2E fix · `6c27c45` frontend · `92846c4` backend + platform · `e1ff836` data ·
`9f2a822` attributes · docs commit. No force-push; `main` untouched; `.env` never read for values or written.

Status vocabulary: DONE AND TESTED · IMPLEMENTED BUT NOT FULLY VALIDATED · PARTIAL · BLOCKED BY CREDENTIALS ·
BLOCKED BY EXTERNAL DATA · BLOCKED BY DATA LICENCE OR ACCESS · NOT IMPLEMENTED.

Credentials present in `.env` (checked by name only): `EARTHDATA_TOKEN` (valid to 2027-01-13), `FIRMS_MAP_KEY`,
`PYROSCOPE_ADMIN_PASSWORD`. Integration ladder per item: implemented → authenticated → connected → data retrieved →
processed → validated.

## Core harmonization

| Item | Status | Evidence |
|---|---|---|
| MODIS historical data | DONE AND TESTED | Terra 2000-11-01 → 2026-10-31 (9,102 detection days), Aqua 2002-07-04 → 2026-10-31; archives unchanged (LFS) |
| Terra/Aqua morning-gap correction | DONE AND TESTED | unchanged; 20-month Aqua-withheld block validation |
| Aqua → VIIRS calibration | DONE AND TESTED | hold-out (59 real S-NPP months, 2012-02…2016-12): WAPE 13.0 %, bias −0.3 %, 90 % band coverage 93.2 % |
| NOAA-20 | DONE AND TESTED | 2018-04-01 → 2026-10-31, separate calibration / model |
| NOAA-21 | DONE AND TESTED | 2023-03-01 → 2026-10-31; operational reference **NOAA-21 APPROVED** by PyroScope's criteria (C1–C6 pass; NOAA-20 also passes) — S-NPP stays historical reference (science data ended 2026-11-02) |
| VIIRS 375 m | DONE AND TESTED | default VIIRS stream |
| VIIRS 750 m | BLOCKED BY CREDENTIALS | token authenticates, but LAADS needs licence acceptance and LP DAAC needs app authorisation (download redirects verified); products VNP14/VJ114/VJ214 v002 verified in CMR; not marked AVAILABLE |
| Uncertainty | DONE AND TESTED | year-block bootstrap bands; empirical coverage reported |
| 2012 seam | PARTIAL (verdict preserved) | recomputed 2026-11-15: `verdict: partial` |

## Advanced fusion

| Item | Status | Evidence |
|---|---|---|
| INSAT (MOSDAC 3DIMG/3RIMG/3SIMG_L2P_FIR, SMK) | BLOCKED BY DATA LICENCE OR ACCESS | registration required; KML import implemented, parser untested on an authentic file |
| Other geostationary | BLOCKED BY DATA LICENCE OR ACCESS (Meteosat-IODC FRP demo) / NOT USED (Himawari, geometry) / NOT APPLICABLE (GOES) / NOT EVALUATED (FY-4) | `GEOSTATIONARY_FUSION.md` |
| Diurnal reconstruction | PARTIAL | real polar local-time sampling by sensor and missing hours; hourly estimate NOT AVAILABLE without geo data (by design, no interpolation) |
| Multi-sensor confidence | IMPLEMENTED BUT NOT FULLY VALIDATED | agreement classes; all events POLAR_ONLY until geo data are imported |

## Fire intelligence

| Item | Status | Evidence |
|---|---|---|
| Individual events | IMPLEMENTED BUT NOT FULLY VALIDATED | India 25–31 Oct 2026: 31,837 detections → 8,948 events (1,328 multi-sensor); India Oct 2026 benchmark 76,533 → 27,666 in 102 s |
| Event matching (cross-sensor) | IMPLEMENTED BUT NOT FULLY VALIDATED | footprint-based linking across MODIS/VIIRS; raw records retained via `obs_key` |
| Event history (continuation/merge/split) | DONE AND TESTED | unit tests; identical re-run → 0 history entries on real data |
| Event growth | IMPLEMENTED BUT NOT FULLY VALIDATED | footprint/centroid growth, labelled observation geometry |
| Event API | DONE AND TESTED | `/api/events`, `/{id}`, `/timeline`, `/observations`, `/nearby-exposure`, `/region/{id}`; p50 33–180 ms |
| Event visualisation | DONE AND TESTED | `/events`, `/events/:id`; Playwright journey F |

## Environmental analysis

| Item | Status | Evidence |
|---|---|---|
| Burned area | BLOCKED BY CREDENTIALS | pipeline tested on synthetic HDF4; LAADS licence blocker reported verbatim by the job |
| Biomass (dry matter) | IMPLEMENTED BUT NOT FULLY VALIDATED | FRP/FRE: 536 kt (90 %: 317–1,153 kt), 25–31 Oct 2026 |
| Emissions | IMPLEMENTED BUT NOT FULLY VALIDATED | PM2.5 3.5 kt (2.1–7.5), CO 51 kt, CO₂ 860 kt, CH₄ 2.7 kt; burned-area method BLOCKED BY EXTERNAL DATA (fuel table) |
| Smoke | IMPLEMENTED BUT NOT FULLY VALIDATED (EXPERIMENTAL) | GFS trajectories, 20 trajectories / 6.7 s; HYSPLIT NOT IMPLEMENTED (not installed) |
| PM2.5 | NOT IMPLEMENTED | no dispersion model; validation BLOCKED BY CREDENTIALS |
| Population exposure | DONE AND TESTED | authentic WorldPop area-weighted rebuild (1,380,004,385; conservation 1.7e-16); smoke-corridor exposure without double counting |
| Infrastructure exposure | PARTIAL | OSM points (hospitals, schools, substations, …) loaded; Geofabrik India PBF downloaded (1.72 GB); linear layer build **in progress at report time** (see addendum) |

## External validation

| Item | Status | Evidence |
|---|---|---|
| Official incidents | BLOCKED BY EXTERNAL DATA | import + matching implemented and tested (synthetic, labelled) |
| Burned-area references | BLOCKED BY CREDENTIALS | corroboration only (not independent) |
| Geostationary comparisons | BLOCKED BY DATA LICENCE OR ACCESS | |
| Ground PM2.5 | BLOCKED BY CREDENTIALS | |
| Held-out regions | PARTIAL | per-state temporal hold-out with national calibration; leave-region-out refit NOT IMPLEMENTED |
| Independent baseline comparisons | DONE AND TESTED | raw MODIS 85.1 % · naive sum 14.9 % (+14.9 % bias) · constant ratio 32.0 % · PyroScope 13.0 % WAPE |

## Deployment

| Item | Status | Evidence |
|---|---|---|
| Vercel | IMPLEMENTED BUT NOT FULLY VALIDATED | `vercel.json`, `VITE_API_BASE_URL`; local build with external origin OK, no secret names in bundle; not deployed (no project / approval) |
| Supabase PostgreSQL | IMPLEMENTED BUT NOT FULLY VALIDATED | migrations tested on PostgreSQL 16 locally (and CI job); no Supabase project connected |
| Supabase Storage | IMPLEMENTED BUT NOT FULLY VALIDATED | REST + TUS client tested against a fake endpoint (resume path exercised); not connected |
| RLS | DONE AND TESTED (PostgreSQL) | all 37 tables RLS-on, anon denied |
| Background worker | DONE AND TESTED | leases, retry/backoff, idempotency, lease-expiry recovery, atomic claim (SQLite + PostgreSQL) |
| Backend service | IMPLEMENTED BUT NOT FULLY VALIDATED | Docker image + compose api/worker; no host deployed |
| Persistent files | IMPLEMENTED | local object store / Supabase buckets; Parquet stays out of PostgreSQL |

## Engineering

| Item | Status | Evidence |
|---|---|---|
| Backend tests | DONE AND TESTED | 220 passed, 1 skipped (PostgreSQL test; passes with `PYROSCOPE_TEST_PG_URL`, run locally: 2 passed) |
| Frontend tests | DONE AND TESTED | Vitest 31 passed; typecheck + lint 0 errors |
| Playwright | DONE AND TESTED | 7/7 journeys (A, B, C, mobile, F in one run; D, E with credentials masked as in CI — locally E differs only because `.env` has a real Earthdata token) |
| CI | PENDING CONFIRMATION | branch pushed; CI result recorded below |
| Security | DONE AND TESTED | pip-audit: no known vulnerabilities; npm audit: 0; secret scan: real token/key/password values absent from tree and DB; guard test for DB credentials |
| Docker | IMPLEMENTED (CI job) | Docker not installed locally; compose gained a worker service |
| Performance | DONE | events 25.6 s / 31,837 detections; emissions MC 2.0 s; API 21–180 ms; external-validation summary 822 ms; bundle: index 324 kB, charts 568 kB, map 153 kB |
| Documentation | DONE | all requested docs created/updated |

## Incident during the work (resolved)

Running backend scripts against the default database let `init_db` bootstrap the admin account from the real
`.env` password into the tracked `data/pyroscope.db`. It was detected before any commit (Playwright admin login
failed), the admin row was restored to the committed state, the DB was VACUUMed (no `pbkdf2` bytes remain), and a test
now fails if the tracked DB ever contains a password hash or session.

## Remaining manual blockers

See [FINAL_MANUAL_SETUP.md](FINAL_MANUAL_SETUP.md): Earthdata LAADS licence + LP DAAC authorisation; MOSDAC / LSA SAF
registration; incident registers; OpenAQ / data.gov.in key; HYSPLIT install; fuel-consumption table; Supabase, Vercel,
backend host, DNS; SMTP/webhook and verified contacts.

## Addendum

(linear GIS build result and CI run are appended here when available)
