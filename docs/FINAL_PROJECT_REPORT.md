# PyroScope — final project report

NASA Space Apps Challenge 2026, *Harmonization of MODIS and VIIRS Hot Spots*. Area: India (bounding box 68–98° E, 6–36° N).
Every metric is from [SCIENTIFIC_VALIDATION.md](SCIENTIFIC_VALIDATION.md), generated from the loaded records.

## 1. Problem

MODIS (Terra 2000–, Aqua 2002–, 1 km) and VIIRS (S-NPP 2012–, NOAA-20 2018–, NOAA-21 2023–, 375 m) detect fire with different
resolution, sensitivity and overpass times. Because of that, the long-term active-fire count over India jumps by a factor of ~7 when VIIRS
begins (raw step 6.98 at the 2012 seam). Terra's morning overpass also sees different fires from the afternoon passes that every later sensor shares.

## 2. Objective

1. A continuous, uncertainty-aware **VIIRS-equivalent** monthly record from 2000-11 onward, built from actual observations, with provenance on every value.
2. A **Burning Activity Calendar** and analysis tools on top of it, plus a seven-day hotspot-probability forecast and a human-in-the-loop alert workflow.

## 3. Data

| Source | Records loaded | Period |
|---|---|---|
| FIRMS MODIS C6.1 (Terra) | 595,991 | 2000-11-01 → 2026-10-31 (NRT from 2026-09) |
| FIRMS MODIS C6.1 (Aqua) | 1,325,256 | 2002-07-04 → 2026-10-31 |
| FIRMS VIIRS C2 375 m (S-NPP) | 8,756,886 | 2012-01-20 → 2026-10-31 |
| FIRMS VIIRS C2 375 m (NOAA-20) | 5,144,008 | 2018-04-01 → 2026-10-31 |
| FIRMS VIIRS C2 375 m (NOAA-21) | 2,166,009 | 2023-03-01 (pre-operational) → 2026-10-31 |
| NASA POWER daily weather, MCD12Q1 land cover (GIBS), geoBoundaries | auxiliary | — |
| WorldPop 2020 1 km UN-adjusted (CC BY 4.0) | 1,380,004,385 people in 4,885 cells | reference year 2020 |
| OpenStreetMap facilities, 11 categories (ODbL) | see [INFRASTRUCTURE_EXPOSURE.md](INFRASTRUCTURE_EXPOSURE.md) | downloaded 2026-11-14/15 |
| CelesTrak TLEs, 5 satellites | current element sets | epoch 2026-11-14 |

All five archives pass the ZIP CRC check and their SHA-256 is recorded. Ingestion dropped 0 rows for invalid coordinates or timestamps and removed 0 duplicates.
NRT rows are provisional and never used for calibration. No VIIRS 750 m records are loaded (Earthdata Login not configured); the 750 m stream reports *unavailable*. Linear infrastructure (roads, railways, power lines) and settlements are not loaded and are reported missing, not zero.

## 4. Architecture

FastAPI backend (`backend/app`). Archives are stored as standardised Parquet, assigned to a 0.25° grid, and summarised daily and monthly (`store.py`).
`harmonize.py` holds the calibration, bootstrap, validation and seam test; `forecast.py` holds XGBoost with isotonic calibration. SQLite or PostgreSQL holds users, alerts,
audit and notification logs. The React/TypeScript frontend (Argon theme, Leaflet, Recharts) has 19 pages. `python -m app.pipeline` runs the whole chain restartably,
with per-source checkpoints and a step log.

## 5. Method

**Calibration form, used for both steps (x → y):** `ŷ = F[state, month, day/night]·x + a[state, month, day/night]·N_silent`.
F is the target/predictor ratio in cells where the predictor saw fire. a is the target rate in predictor-silent cells. Both are shrunk toward national values according to how much data each state has.
The model is linear in cell sums, so it aggregates consistently to any region.

* **Morning-Gap Fixer:** Terra → Aqua, trained on 2002–2022. Orbit-drift years (2023+) are excluded because the mean overpass moved more than 0.25 h.
* **Sensor Harmonizer:** Aqua → S-NPP VIIRS 375 m, trained on 2012–2022. NOAA-20 has its own pathway. 375 m and 750 m are never pooled.
* **Actual VIIRS** passes through unchanged. MODIS and VIIRS counts are never added. FRP is kept separate from counts.
* **Uncertainty:** a 200-replicate whole-year block bootstrap refits both stages each time. Each replicate also draws an out-of-sample (leave-one-year-out) log-residual matched to the estimate's size.
  The 5–95 % band is a *resampling/prediction band*, not a formal confidence interval.

## 6. Validation and results

| Test | Result |
|---|---|
| Actual chronological hold-out (train 2017–22, test real VIIRS 2012-02 → 2016-12, 59 months) | WAPE 13.0 %, bias −0.3 %, R² 0.960. Constant ratio: 32.0 %; raw MODIS: 85.1 %. Band coverage 93.2 % (nominal 90). |
| Morning-gap, 20-month Aqua blocks hidden (7 blocks, 140 months) | WAPE 18.4 %, bias +3.7 %, R² 0.920. Constant ratio: 45.3 %, R² 0.641. Coverage 91.4 %. |
| Model selection (leave-one-year-out, block, forward/backward rolling origin) | No candidate (activity-scaled silent term, state ratio, national ratio, constant) beat the default on both primary designs, so the default was kept. |
| Backward rolling origin (the analogue of the real 2000–02 correction) | National bias +12.2 %, band coverage 84.5 %. Reported as a limitation. |
| Terra-only era structural sensitivity | The five model forms differ by 9.0 % in total Aqua-equivalent activity for 2000-11 → 2002-06. |
| Real 2012 seam (±24 months) | Step ×6.98 → ×1.03 against the unchanged-Aqua reference ×1.10. Artificial jump 1.845 → 0.072 (−96.1 %). **Verdict: partial**: part of the genuine +10 % is damped. ±36 months: pass. States: 5 pass, 3 partial. |
| Forecast (test 2024-01 → 2026-11, 629,104 cell-weeks) | Brier 0.0971 (climatology 0.1067), ROC-AUC 0.920, PR-AUC 0.823. At the 60 % threshold: precision 0.836, recall 0.581. |

**Correction made on this branch.** The previously published morning-gap test (+33 % bias, R² 0.42) hid Aqua for 135 months and trained on 2017–22 only,
which tests a decade of backward extrapolation, not the method. It is kept as a labelled stress test. There, a national seasonal ratio stays unbiased (+1.0 %)
while the state-level model drifts (+29.7 %).

## 7. Burning Activity Calendar and analysis

Daily, monthly and annual calendars per sensor or on the VIIRS-equivalent scale, by detection count or FRP, for a state, district, bounding box or drawn polygon.
Missing days are drawn hatched and never as zero. Historical trends, seasonal-baseline anomalies (high activity is kept separate from incomplete coverage) and critical-region ranking with transparent weights complete the toolset.

## 8. Forecasting

The target is *at least one S-NPP VIIRS presumed-vegetation detection in the 0.25° cell within 7 days*: a detectable hotspot, not a verified ignition.
Data are split chronologically: training up to 2021, isotonic calibration on 2022–23, test from 2024. Regional probability is `1 − Π(1 − p)^α`, with α = 0.73 fitted on the calibration years.

Five candidates (climatology, logistic regression, random forest, HistGradientBoosting, XGBoost) were compared on the same 600,000 training rows, the same calibration and the same 629,104 test rows, plus three rolling origins. XGBoost: Brier 0.0973, BSS 0.089, ROC-AUC 0.920, PR-AUC 0.823, ECE 0.006. HistGradientBoosting ties it (0.0976) but does not meet the declared replacement rule, so XGBoost is retained ([MODEL_COMPARISON.md](MODEL_COMPARISON.md)). Results are broken down by state (34, 3 flagged unreliable), month, season, land use, recent activity and observation coverage.

## 9. GIS

State, district, land-use and jurisdiction layers cover **India only**, and the API says so (`global: false`). Industrial and residential classes come only from administrator-supplied jurisdiction layers.
Land cover is never used to infer why something burned. Population (WorldPop 2020) and OpenStreetMap facility layers are loaded with manifests; exposure near actual hotspots and per-state comparisons are proximity counts, not harm predictions ([POPULATION_EXPOSURE.md](POPULATION_EXPOSURE.md), [INFRASTRUCTURE_EXPOSURE.md](INFRASTRUCTURE_EXPOSURE.md)).
SGP4 overpass prediction from current TLEs agrees with recorded acquisition times to 0.8–0.9 min on average (95th percentile ≤ 2.2 min) for all five satellites ([ORBIT_PREDICTION.md](ORBIT_PREDICTION.md)).

## 10. Alerts and operations

Five configurable tiers (LOW … VERY HIGH) and four alert classes. A predicted advisory is never turned into a verified incident automatically.
The lifecycle covers duplicate and cooldown checks, acknowledgement, approval or rejection, escalation and an audit trail. Notifications are simulated by default. Real webhook or SMTP delivery happens only after approval, only to verified contacts, with retries on transient errors, SSRF protection and duplicate prevention; every attempt is logged. The SMTP path is tested against a real local SMTP server; no external provider has been used (no credentials).
Organisations see only their own data. Security details: [SECURITY.md](SECURITY.md).

## 11. Limitations

* The morning-gap estimates for 2000-11 → 2002-06 have no ground truth. Backward-extrapolation tests suggest they may be about 10 % high nationally.
* The 2012 seam verdict is *partial*: a genuine ~10 % increase is partly damped at the ±24-month window.
* There is no orbit-stable Aqua overlap with NOAA-21 (Aqua drift from 2023). A direct NOAA-21 → S-NPP study on the operational period found no adjustment that beats leaving counts unchanged under the declared rule, so NOAA-21 stays a separate actual stream. Its archive includes pre-operational 2023 records.
* S-NPP VIIRS science-data delivery ceased on 2026-11-02; the forecast reference stream will not receive new labels.
* Night-time calibration is weaker than day-time (hold-out night WAPE 31 % vs 13.5 % day).
* No VIIRS 750 m data (Earthdata credentials needed); the converter is tested only on synthetic files built to the specification.
* No real notification provider configured; no Docker build executed here (Docker not installed).
* The population raster is not aligned to the 30″ lattice; infrastructure comes from volunteer-mapped OSM and excludes linear networks.
* The MODIS row-version strings `6.03` and `61.03` are not defined in readable FIRMS documentation.

## 12. Future work

1. Run the implemented Earthdata acquisition on real VNP14/VJ114/VJ214 granules, verify the converter on them, and fit the separate 750 m calibration.
2. Retarget the forecast to NOAA-20 after the S-NPP end of science delivery.
3. A hierarchical (partially pooled) Terra→Aqua model that keeps state detail but borrows the national ratio's temporal stability, chosen by the existing selection framework.
4. Linear infrastructure (roads, rail, transmission) with line-distance exposure; official facility registers where licensed.
5. Typing of the remaining API payloads (lint warnings).

## 13. Reproducibility

```bash
git lfs pull                                    # or: python -m app.pipeline --recover-lfs
cd backend && pip install -r requirements.txt
python -m app.pipeline --only-new --skip-weather --skip-train   # rebuild summaries, DB, inventory and science report
python -m app.pipeline --validate-only          # integrity + hold-out + seam as JSON
python -m pytest tests -q                       # 136 tests
python -m app.pipeline --skip-ingest --skip-weather --skip-train --refresh-exposure --refresh-tle --compare-forecast
cd ../frontend && npm ci && npm test && npm run build && npm run e2e
```

Fixed random seed (`RNG_SEED = 20261114`). Archive SHA-256s are in `data/processed/archive_checksums.json`, and every number in the science report is computed when the report is generated.
