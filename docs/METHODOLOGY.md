# PyroScope scientific methodology

Code: `backend/app/harmonize.py` (harmonization, uncertainty, validation, seam), `forecast.py`,
`alerts.py`, `store.py` (coverage / missing data), `ingest.py` (standardisation).
Measured results: [SCIENTIFIC_VALIDATION.md](SCIENTIFIC_VALIDATION.md).

## 1. Standardisation and provenance

* Every FIRMS record that passes structural checks is kept, one row per detection, in Parquet
  (`data/processed/hotspots/<source>/`). Rows are dropped only for invalid coordinates, an unparseable
  date/time or an unidentifiable sensor; exact duplicates are removed **within** one source only.
  Detections from different sensors are never merged, however close.
* Schema: lat/lon, date, time, UTC timestamp, satellite, instrument, product type (`1km`, `375m`, `750m`),
  original confidence (MODIS 0–100 or VIIRS l/n/h), confidence class, an ordinal standardised score
  (display/filter convention, *not* an equivalence), FRP (MW), day/night, scan, track,
  `pixel_area_km2 = scan·track`, FIRMS `type`, brightness, version, NRT/archive, source file, grid cell.
* Aggregation streams: satellite name for its default product; `"<sat> 750m"` for VIIRS 750 m, so the
  two VIIRS products can never be summed together.
* FRP is aggregated separately from counts (sum, n, max).

## 2. Missing data is not zero

Per satellite the data span is taken from the records. Runs of whole-domain zero-detection days
(≥5 days MODIS, ≥3 days VIIRS) are classed as **sensor gaps** (missing). Months are weighted by the
fraction of observed days; partial months are scaled up and their uncertainty inflated by
1/√coverage. Days outside a sensor's record are `null`, shown as "outside record" in the calendar.
NRT months are provisional and never used for calibration.

## 3. Calibration model (both steps)

For region *r*, month *t*, day/night *d*:

    y_hat = F[state, month-of-year, d] · X  +  a[state, month-of-year, d] · N_silent

* `X` predictor-sensor detections (presumed vegetation fires, FIRMS type 0, plus untyped NRT rows);
* `N_silent` grid cells (0.25°) where the predictor saw nothing — the target can still see small fires there;
* `F` ratio of target to predictor detections in co-active cells; `a` mean target detections per silent cell.

State parameters are shrunk to the national value (pseudo-counts K=50 detections for F, 200 cell-months
for a). The model is linear in cell sums, so it aggregates consistently to any cell set (state, district,
bounding box, drawn polygon). Calendar months with fewer than 200 national predictor detections fall back
to the pooled ratio and are flagged **unreliable**.

* **Morning-Gap Fixer** — Terra (≈10:30/22:30) → Aqua (≈13:30/01:30), learned on fully covered,
  standard-processing overlap months. Day and night are separate (night Aqua sees far fewer fires than
  night Terra; monsoon-month day Aqua can be below Terra). Applied to months with Terra but no Aqua.
  FIRMS' Terra-only era is **1 Nov 2000 – 3 Jul 2002**.
* **Orbit drift** — mean day-time local solar time of detections is measured per satellite-year from the
  records; years drifting more than 0.25 h from the early baseline are excluded from calibration.
* **Sensor Harmonizer** — Aqua (actual, or morning-gap estimate) → VIIRS reference stream
  (default S-NPP 375 m; any loaded 750 m stream gets its own separate calibration via `product=750m`).
  NOAA-20/21 remain separate actual observations and are not pooled into the reference.
* **Continuous record** — provenance per month: `actual_viirs` (passed through unchanged),
  `sensor_calibrated` (from actual Aqua), `morning_gap_sensor` (from Terra only), `no_data`.
  MODIS and VIIRS counts are never added.

## 4. Uncertainty

Year-block bootstrap (200 resamples): calibration years are resampled whole, both steps are refitted.
Each replicate also draws an out-of-sample (leave-one-year-out) log residual matched to the estimate's
size, so the band reflects month-to-month scatter, not only parameter noise. Chained for Terra-only months.
Band = 5th–95th percentile — a resampling range, not a formal confidence interval. Its empirical coverage
on held-out months is reported (nominal 90 %).

## 5. Validation

* **Actual chronological hold-out.** Default split leaves ~35 % of fully overlapping years as the unseen
  early period; calibration trains only on months ≥ split. Metrics against the real withheld VIIRS
  record: MAE, RMSE, WAPE, MAPE (≥10 detections), bias, R², by stage, month, year and day/night, plus
  band coverage. Baselines: raw MODIS and a single constant ratio.
* **Simulated morning-gap experiment (20-month blocks).** Blocks of 20 overlap months (the FIRMS
  Terra-only length) are hidden in turn, every 36 overlap months. Terra→Aqua is refitted on all *other*
  overlap years (whole years removed) and the hidden Aqua is the answer key. Labelled *simulated*: it
  tests the method, not the 2000–2002 correction, which has no ground truth.
* **Chain experiment.** Inside the actual hold-out, Aqua is also hidden for the first 20 VIIRS months, so
  VIIRS must be reached from Terra through both steps. (Before this branch, the mask hid Aqua for *every*
  earlier month: 135 months once 2000–2011 MODIS was loaded. That is now fixed.)
* **Model selection.** Candidate forms are the default `F·x + a·N_silent`, an activity-scaled silent
  term, a state ratio, a national ratio and a constant. They are compared with leave-one-year-out,
  20-month blocks and forward/backward rolling origin, all year-blocked. The default is replaced only if
  a candidate wins on both leave-one-year-out and blocks at state-month level: WAPE lower by ≥ 1 point,
  |bias| no worse, R² no lower. Diagnostics are reported by month, day/night, state, low/high activity
  and year. Band coverage is reported for the block and backward designs. `GET /api/validation/model-selection`.
* **Extrapolation stress test.** The old design (train on recent years only, predict a decade back) is
  kept and labelled. It measures temporal non-stationarity: the national seasonal ratio stays unbiased
  while state-level detail drifts.
* **Terra-only structural sensitivity.** The 2000–02 Aqua-equivalent total under each model form
  (`GET /api/morning-gap/sensitivity`).
* **Status rule (PyroScope convention).** good: WAPE ≤ 20 % and |bias| ≤ 10 %; moderate: WAPE ≤ 40 %.

## 6. Seam test

Step = mean activity in the *w* months after the seam ÷ mean in the *w* months before (same calendar
months). The target is **not** 1.0: it is the step seen by a sensor that did not change (Aqua, else Terra),
or in simulated mode the withheld real VIIRS. Artificial jump = |ln(step / target)|, before vs after
harmonization; the bootstrap gives a band on the harmonized step. *Genuine change detectable* = the band
excludes 1.0 and agrees in direction with the reference step.
**Real seam** (first full S-NPP month, Feb 2012) uses the loaded 2000–2011 MODIS record. A simulated seam
is used only when fewer than 12 earlier MODIS months exist.
**Declared verdict:** *pass* when the residual jump is ≤ 0.10 ln-units and the reference step lies inside
the harmonized band; *partial* when the residual jump is ≤ 0.25 or reduced by ≥ 50 %; otherwise *fail*.
When a genuine change is not detectable, the report says whether that is a resolution limit (reference
change within the band) or damping (reference outside the band). Robustness: ±12/24/36-month windows
nationally and the most active states (`GET /api/validation/seam-robustness`).

## 7. Seven-day forecast

Target: P(≥1 S-NPP VIIRS 375 m presumed-vegetation detection in the 0.25° cell in the next 7 days) —
a **detectable hotspot** probability, not ignition. XGBoost (5-member year-block ensemble for spread),
isotonic calibration on separate years, chronological train ≤ 2021 / calibrate 2022–23 / test ≥ 2024.
Weeks overlapping S-NPP gaps have unknown labels and are dropped. Features: recent and neighbouring
detections, FRP, recurrence, season, land cover, NASA POWER weather, observation gaps.
Regional probability: `1 − ∏(1 − p_cell)^α` with α fitted on held-out regional outcomes (never an average).

**Model comparison** (`forecast_eval.py`, [MODEL_COMPARISON.md](MODEL_COMPARISON.md)): climatology, logistic regression,
random forest, HistGradientBoosting and XGBoost are trained on the same 600,000-row training subsample, calibrated with
isotonic regression on the same years and scored on the same test rows, plus three rolling origins (test 2021, 2022, 2023).
A candidate replaces XGBoost only if Brier improves ≥ 2 % relative and ROC-AUC ≥ 0.005 and it is not worse on any origin.
Result: XGBoost retained (Brier 0.0973 vs climatology 0.1067; best alternative HistGradientBoosting 0.0976).

**Reference-stream risk:** S-NPP VIIRS science-data delivery ceased on 2026-11-02 (CMR metadata). The forecast target
was S-NPP-based. Separate NOAA-20 and NOAA-21 models are now trained on each sensor's own labels (no pooling, no
calibrator transfer) and an operational reference is chosen by criteria C1–C6; S-NPP remains the historical reference.
See [OPERATIONAL_SENSOR_TRANSITION.md](OPERATIONAL_SENSOR_TRANSITION.md).

## 7a. NOAA-21 cross-calibration study

`noaa21.py`. NOAA-21 → S-NPP on matched days in the operational period only (≥ 2024-01-17); pre-operational records
are scored separately, never used to fit. Candidates: identity, national day/night ratio, state ratio, state × season ratio.
Forward (train 2024-01→2025-07, test 2025-08→2026-07) and backward splits, 200-replicate month-block bootstrap.
Declared rule: adopt only if better than identity and national ratio by ≥ 1 WAPE point on both splits, |bias| ≤ 5 %,
band coverage ≥ 80 %, ≥ 12 test months and ≥ 10,000 reference detections. **No candidate met it** (forward state-month
WAPE identity 7.01 %, best 6.69 %; band coverage 17–33 %), so NOAA-21 stays a separate actual stream.

## 7b. Overpass prediction

`orbits.py`. SGP4 propagation of current CelesTrak TLEs, TEME→ECEF by GMST rotation, topocentric elevation for the
location. A pass is the interval where elevation exceeds the swath-edge elevation implied by the scan half-angle
(MODIS 55°, VIIRS 56.28°). Validated against 400 recent actual detections per satellite: mean |acq_time − predicted
closest approach| 0.82–0.90 min, 95th percentile 1.8–2.2 min, 100 % within 10 min ([ORBIT_PREDICTION.md](ORBIT_PREDICTION.md)).
Predictions say when a sensor can observe, never that a fire will be detected.

## 8. Alerts

Five configurable tiers (0.20 / 0.40 / 0.60 / 0.80), three-condition trigger (calibrated probability,
supporting evidence count, resolved jurisdiction), deterministic IDs, cooldown, supersede/downgrade with
history, separate unverified-detection alerts. Routing to role templates; delivery only to verified
contacts and only after human approval. Four classes are never conflated: predicted advisory,
unverified detection, verified incident, official public warning (never issued by PyroScope).

## 9. Geography

India ADM1/ADM2 (geoBoundaries), NASA MCD12Q1 IGBP land-cover fractions per cell. Forest / Agricultural /
Municipal-Urban / Other follow a prototype rule on those fractions. Residential/Village and Industrial
come only from administrator-supplied jurisdiction layers (`POST /api/jurisdictions/layers`, provenance
required). Population and infrastructure exposure enter the critical-region score only when a layer is
loaded (`POST /api/geo/exposure`); otherwise they are reported unavailable (weight 0, not zero exposure).

**Exposure.** Population: WorldPop 2020 1 km UN-adjusted, pixel-centre assignment to 0.25° and 0.05° cells
([POPULATION_EXPOSURE.md](POPULATION_EXPOSURE.md)). Infrastructure: 11 OpenStreetMap categories
([INFRASTRUCTURE_EXPOSURE.md](INFRASTRUCTURE_EXPOSURE.md)). Hotspot exposure de-duplicates detections to ~375 m locations,
then counts people (fine-grid cells whose centre is within the radius) and facilities (haversine via a KD-tree) within
5/10/25 km. These are proximity counts — not predictions of harm — and are uncertain by roughly one fine cell (~5 km) at the radius edge.

## Extended products (2026-11)

The methods below are documented separately and never feed back into the harmonized record:
[fire events](FIRE_EVENT_DELINEATION.md) - [burned area](BURNED_AREA_METHODOLOGY.md) - [emissions](EMISSIONS_METHODOLOGY.md) -
[smoke / PM2.5](SMOKE_PM25_METHODOLOGY.md) - [geostationary fusion](GEOSTATIONARY_FUSION.md) -
[independent validation](INDEPENDENT_VALIDATION.md). The 2012 seam verdict remains PARTIAL (recomputed 2026-11-15).
