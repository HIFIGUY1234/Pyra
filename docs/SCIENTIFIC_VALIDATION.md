# PyroScope - Scientific Validation Report

Generated 2026-11-14T14:50:59+00:00 by `python -m app.science_report` from the loaded data. Every number below is computed at generation time; nothing is typed by hand.

## 1. Sensor coverage actually loaded

| Satellite | Status | Science-quality archive | NRT | FIRMS availability starts |
|---|---|---|---|---|
| Terra | partial | 2012-01-01 → 2026-08-31 | 2026-09-01 → 2026-10-31 | 2000-11-01 |
| Aqua | partial | 2012-01-01 → 2026-08-30 | 2026-09-01 → 2026-10-31 | 2002-07-04 |
| Suomi NPP | complete_from_firms_start | 2012-01-20 → 2026-07-31 | 2026-08-01 → 2026-10-31 | 2012-01-20 |
| NOAA-20 | complete_from_firms_start | 2018-04-01 → 2026-07-31 | 2026-08-01 → 2026-10-31 | 2018-04-01 |
| NOAA-21 | complete_from_firms_start | 2023-03-01 → 2026-07-31 | 2026-08-01 → 2026-10-31 | 2024-01-17 |

Capabilities with this data: **terra_only_era_loaded**: False; **pre_viirs_modis_loaded**: False; **real_morning_gap_correction**: blocked: no Terra-only (Nov 2000 - Jun 2002) records loaded; **real_2012_seam_test**: blocked: fewer than 12 months of MODIS records precede the first VIIRS record; **viirs_750m**: unavailable; **noaa20**: loaded

## 2. Calibration design

* Model (both steps): `y = F[state, month, day/night] · x + a[state, month, day/night] · N_silent`, with state values shrunk to the national value.
* Morning-Gap Fixer: Terra → Aqua. Sensor Harmonizer: Aqua → S-NPP VIIRS 375 m (only VIIRS product loaded; 750 m unavailable).
* Training months: both sensors 100 % covered, standard-processing (not NRT), orbit-stable years only.
* Morning-gap training years: [2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022]. Sensor training years (operational fit): [2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023].
* Notes: MODIS orbit drift detected in the loaded records (mean day-time local overpass time moved more than 0.25 h from its early baseline): Terra [2023, 2024, 2025, 2026], Aqua [2024, 2025, 2026]. Those years are excluded from calibration because their diurnal sampling differs from the historical MODIS era.

### 2a. Learned national ratios (operational fit, central value and 5–95 % year-block bootstrap range)

| Month | Aqua→VIIRS day | Aqua→VIIRS night | Terra→Aqua day | Terra→Aqua night | reliable |
|---|---|---|---|---|---|
| Jan | 4.69 (4.52–4.85) | 11.78 (10.16–13.77) | 1.23 (1.07–1.37) | 0.04 (0.03–0.05) | yes |
| Feb | 5.78 (5.45–6.08) | 22.42 (17.70–25.94) | 1.73 (1.51–1.99) | 0.10 (0.08–0.13) | yes |
| Mar | 6.41 (6.01–6.79) | 36.11 (29.69–40.93) | 3.36 (3.19–3.56) | 0.21 (0.17–0.23) | yes |
| Apr | 8.06 (7.64–8.46) | 32.97 (30.24–35.57) | 1.54 (1.40–1.69) | 0.23 (0.21–0.25) | yes |
| May | 11.15 (10.39–12.07) | 24.05 (20.10–26.61) | 0.87 (0.81–0.92) | 0.24 (0.18–0.28) | yes |
| Jun | 8.01 (6.92–9.01) | 17.98 (13.87–21.87) | 0.55 (0.43–0.67) | 0.33 (0.27–0.38) | yes |
| Jul | 1.47 (1.10–1.82) | 29.50 (26.84–32.09) | 0.23 (0.18–0.27) | 0.20 (0.17–0.22) | NO |
| Aug | 0.72 (0.40–1.11) | 29.50 (26.84–32.09) | 0.25 (0.21–0.29) | 0.20 (0.17–0.22) | NO |
| Sep | 3.08 (2.42–3.48) | 29.50 (26.84–32.09) | 0.48 (0.36–0.67) | 0.20 (0.17–0.22) | NO |
| Oct | 4.78 (4.65–4.91) | 29.50 (26.62–32.09) | 6.70 (6.23–7.28) | 0.20 (0.17–0.32) | NO |
| Nov | 5.36 (5.12–5.66) | 29.50 (9.96–32.05) | 7.54 (6.98–8.08) | 0.07 (0.05–0.10) | NO |
| Dec | 5.53 (5.39–5.67) | 14.00 (10.16–17.94) | 1.54 (1.39–1.67) | 0.06 (0.04–0.08) | yes |

Night-time Terra→Aqua ratios below 1 show that the afternoon/early-morning pass does not always see more fire: the relationship is learned, not assumed.

## 3. Chronological held-out validation (actual)

* Validation kind: **actual_holdout**. Split 201701: train on 2017–2023, test on real VIIRS months 201202–201612 never seen in training.
* Status (PyroScope rule: good: WAPE <= 20% and |bias| <= 10%; moderate: WAPE <= 40%; otherwise poor (PyroScope convention, not an external standard).): **good**

| Method | n months | MAE | RMSE | WAPE | Bias | R² |
|---|---|---|---|---|---|---|
| PyroScope calibrated harmonization | 59 | 5,812 | 9,450 | 13.6% | 0.5% | 0.958 |
| Constant VIIRS/Aqua ratio baseline | 59 | 13,728 | 20,619 | 32.2% | 2.0% | 0.799 |
| Raw MODIS (Terra+Aqua, uncorrected) | 59 | 36,327 | 53,848 | 85.1% | -85.1% | -0.371 |
| · day-time detections | 59 | 4,775 | 7,938 | 14.0% | -0.6% | 0.948 |
| · night-time detections | 59 | 2,674 | 4,553 | 31.2% | 4.9% | 0.873 |
| · stage morning_gap_sensor | 20 | 7,879 | 11,395 | 18.1% | 11.5% | 0.944 |
| · stage sensor_calibrated | 39 | 4,752 | 8,277 | 11.2% | -5.3% | 0.966 |

Uncertainty band (5–95 % of replicates, nominal 90 %): empirical coverage on held-out months **98.3%** (above nominal = conservative / wide band).

### 3a. Monthly performance (held-out)

| Month | n | WAPE | Bias |
|---|---|---|---|
| Jan | 4 | 11.9% | 5.6% |
| Feb | 5 | 25.2% | -10.4% |
| Mar | 5 | 8.5% | -0.7% |
| Apr | 5 | 14.4% | -1.4% |
| May | 5 | 16.7% | 12.1% |
| Jun | 5 | 31.7% | -0.7% |
| Jul | 5 | 39.8% | 19.8% |
| Aug | 5 | 39.7% | 21.9% |
| Sep | 5 | 11.5% | 11.5% |
| Oct | 5 | 12.3% | 10.7% |
| Nov | 5 | 11.6% | -7.2% |
| Dec | 5 | 10.3% | 8.3% |

### 3b. Morning-gap step (SIMULATED experiment, not the real 2000–2002 correction)

Real Aqua months 201201–201309 hidden; Terra used to estimate them.

| Method | n | MAE | RMSE | WAPE | Bias | R² |
|---|---|---|---|---|---|---|
| Calibrated Terra→Aqua | 21 | 582 | 939 | 12.7% | 6.1% | 0.972 |
| Constant Aqua/Terra ratio | 21 | 2,440 | 3,816 | 53.4% | 3.7% | 0.534 |

Band coverage: 100.0%.

## 4. 2012 seam test (simulated_seam)

> The loaded MODIS record starts in the same month as the VIIRS record, so the real 2012 seam cannot be tested with this data. Upload MODIS C6.1 data for 2000-2011 to test it. Shown instead: a simulated seam where real VIIRS data before the seam month was withheld from calibration and used only as the answer key.

* Seam month 2017-01-01, window ±24 months.
* Step before harmonization (raw MODIS → VIIRS): **7.523**; after: **1.132** (band 1.003–1.228).
* Target step (true withheld VIIRS / unchanged reference sensor): 1.060 (Aqua MODIS reference 1.067).
* Artificial discontinuity |ln(step/target)|: before **1.959**, after **0.066** (reduction 96.6%); status good.
* Genuine change still detectable: **True** (increase).

## 5. Seven-day hotspot-probability forecast

* Target: At least one Suomi NPP VIIRS 375 m presumed-vegetation detection in the 0.25 deg cell within 7 days of the issue date — probability of a detectable satellite hotspot (NOT a verified ground ignition).
* Split: train ≤ 2021-12-31, isotonic calibration ≤ 2023-12-31, test 2024-01-01 → 2026-11-07.
* Test rows 629,104; base rate 0.268.

| Metric | Calibrated model | Climatology baseline |
|---|---|---|
| Brier | 0.0971 | 0.1067 |
| ROC-AUC | 0.920 | 0.902 |
| PR-AUC | 0.823 | 0.776 |

Brier skill vs climatology: 0.090.

| Threshold | Precision | Recall | False-alarm rate | Missed-event rate |
|---|---|---|---|---|
| 60 % (HIGH) | 0.836 | 0.581 | 0.0419 | 0.419 |
| 80 % (VERY HIGH) | 0.925 | 0.367 | 0.0109 | 0.633 |

Regional aggregation: `P(any detection in region) = 1 - prod(1 - p_cell) ** alpha` with α = 0.73 (fitted on calibration years).

## 6. Data limitations

* No MODIS records before 2012-01-01 are loaded (FIRMS C6.1 starts 2000-11-01). The real Terra-only morning-gap correction (Nov 2000 – Jun 2002) and the real 2012 MODIS→VIIRS seam test therefore cannot be run on this data; the code runs them automatically once those records are ingested.
* NOAA-20 (2018-04 →) and NOAA-21 (2023-03 →) are loaded as separate actual observations; neither is the default calibration target.
* VIIRS 750 m (VNP14/VJ114) is not distributed by FIRMS; a separate 750 m calibration pathway exists but has no data.
* MODIS orbit drift years excluded from calibration: MODIS orbit drift detected in the loaded records (mean day-time local overpass time moved more than 0.25 h from its early baseline): Terra [2023, 2024, 2025, 2026], Aqua [2024, 2025, 2026]. Those years are excluded from calibration because their diurnal sampling differs from the historical MODIS era.
* Administrative intelligence (states, districts, land use) covers India only.
* Month coverage: S-NPP months with full coverage 168; Aqua 177; Terra 176.
