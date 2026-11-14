# Operational sensor transition (Suomi NPP → NOAA-21 / NOAA-20)

## Why

NOAA NESDIS and NASA Earthdata announced that delivery of new Suomi NPP science data, including VIIRS,
ended on **2 November 2026**; users should move to **NOAA-21 (primary)** and **NOAA-20 (secondary)**.
PyroScope used S-NPP for two different jobs, so it now separates them:

| Concept | Platform | Purpose | Changes? |
|---|---|---|---|
| Historical harmonization reference (`config.HISTORICAL_REFERENCE`) | Suomi NPP | Defines the VIIRS-equivalent scale of the 2000–2026 harmonized record | **No.** The S-NPP archive stays valid; the record is reproducible |
| Operational reference (`app/operational.py`) | Chosen from NOAA-21, NOAA-20 by evidence | Live 7-day forecasting target | Yes, only through the selector |

S-NPP is never an operational candidate. Its legacy forecast model is still served on request but labelled
`STALE_RETIRED_SENSOR` with an explanation, so retired data are never presented as live.

## Platform evaluation (per sensor, nothing pooled)

`operational.evaluate(sensor)` (API `GET /api/reference/platform/{sensor}`) reports, from that sensor's own records:
coverage (first / last / last science-quality day), NRT days, missing days and share, detections per year,
confidence classes, day/night counts, seasonal distribution, overlap with the other VIIRS platforms, data age,
and the metrics of the sensor's own forecast model.

## Acceptance criteria (declared before evaluation)

| | Criterion |
|---|---|
| C1 | Platform officially operational |
| C2 | Last observation within 14 days of the newest loaded observation of any sensor |
| C3 | ≥ 24 months of science-quality archive inside the operational period |
| C4 | Missing-day share ≤ 5 % |
| C5 | An independent forecast model trained on this sensor exists |
| C6 | That model on its own test period: ≥ 50,000 rows, Brier skill > 0 vs its own climatology, ROC-AUC ≥ 0.80, ECE ≤ 0.05 |

Selection: among passing candidates, follow NOAA's order (NOAA-21, then NOAA-20). An administrator may choose
another **passing** candidate (`PUT /api/reference/operational`, audited, reason required). A stored choice that
later fails is ignored and flagged. If none passes, the operational reference is `UNAVAILABLE`, the reason is
shown, forecasts fall back to nothing new (the stale S-NPP model stays labelled), and NOAA-20/NOAA-21
observations are still shown as independent actual streams.

Current result with the repository data: both candidates pass; **NOAA-21 is the evidence default**.
Numbers: `docs/SCIENTIFIC_VALIDATION.md` §5f.

## Independent forecast models

`forecast.train(sensor=...)`, one per sensor, stored in `data/processed/models/sensors/<sensor>/`:

* own label: at least one presumed-vegetation 375 m detection **from that satellite** in the cell within 7 days;
* own features (that sensor's recent detections, FRP, recurrence, gaps) plus shared MODIS and weather context;
* labels unknown (dropped, never negative) when the window touches a data gap of that sensor, extends into its
  NRT period, or (NOAA-21) precedes the operational start 2024-01-17;
* own chronological splits, declared in `SENSOR_CONFIG` before training:
  NOAA-20 train ≤ 2022-12 | calibrate ≤ 2024-06 | test from 2024-07;
  NOAA-21 train ≤ 2025-03 | calibrate ≤ 2025-09 | test from 2025-10;
* own isotonic calibrator (never transferred), own ensemble spread, own model card with `model_version`
  (hash of the booster), `trained_at`, target definition and reference sensor.

Every forecast output carries a `reference` block (sensor, product, model version, serving status). API callers
can pick a model explicitly with `?sensor=` on forecast, alert-evaluation, critical-region and report routes;
an unknown sensor is a 400, never a silent fallback.

## Bridge calibrations

`app/bridge.py` studies NOAA-20 → S-NPP, NOAA-21 → S-NPP and NOAA-21 → NOAA-20 on matched archive days, with
forward and backward 12-month tests and four candidates (identity, national day/night ratio, state ratio,
state × season ratio). A bridge is adopted only if it beats identity by ≥ 1 WAPE point on **both** splits with
|bias| ≤ 5 % and ≥ 80 % bootstrap band coverage. The original `noaa21._accept` has a looser fallback for the
national ratio (first split only, no coverage check); bridges apply the full rule to every candidate.

Result: all three bridges are **NOT CALIBRATED**. The raw sensors already agree closely (NOAA-20 vs S-NPP
state-month WAPE ≈ 5.5 %, bias ≈ +0.7 %), and the ratio candidates do not improve on identity by the required
margin with adequate uncertainty coverage. Consequently **no S-NPP-equivalent continuation past the last
science-quality S-NPP day is produced**. Successor observations are displayed as their own actual streams.

## Transition report

`GET /api/reference/transition` (UI: *Historical & Operational Reference*): last S-NPP science-quality day,
successor coverage, the S-NPP/successor monthly ratio over the final 12 overlap months and its p05–p95 spread
(how large a sensor-only step can look), bridge status, and calibrated discontinuity (not computed when no bridge
passed). A genuine change in burning must appear in both platforms.
