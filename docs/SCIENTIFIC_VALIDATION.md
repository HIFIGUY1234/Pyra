# PyroScope - Scientific Validation Report

Generated 2026-11-14T15:19:52+00:00 by `python -m app.science_report` from the loaded data. Every number below is computed at generation time; nothing is typed by hand.

## 1. Sensor coverage actually loaded

| Satellite | Status | Science-quality archive | NRT | FIRMS availability starts |
|---|---|---|---|---|
| Terra | complete_from_firms_start | 2000-11-01 → 2026-08-31 | 2026-09-01 → 2026-10-31 | 2000-11-01 |
| Aqua | complete_from_firms_start | 2002-07-04 → 2026-08-30 | 2026-09-01 → 2026-10-31 | 2002-07-04 |
| Suomi NPP | complete_from_firms_start | 2012-01-20 → 2026-07-31 | 2026-08-01 → 2026-10-31 | 2012-01-20 |
| NOAA-20 | complete_from_firms_start | 2018-04-01 → 2026-07-31 | 2026-08-01 → 2026-10-31 | 2018-04-01 |
| NOAA-21 | complete_from_firms_start | 2023-03-01 → 2026-07-31 | 2026-08-01 → 2026-10-31 | 2024-01-17 |

Capabilities with this data: **terra_only_era_loaded**: True; **pre_viirs_modis_loaded**: True; **real_morning_gap_correction**: possible; **real_2012_seam_test**: possible; **viirs_750m**: unavailable; **noaa20**: loaded

## 2. Calibration design

* Model (both steps): `y = F[state, month, day/night] · x + a[state, month, day/night] · N_silent`, with state values shrunk to the national value.
* Morning-Gap Fixer: Terra → Aqua. Sensor Harmonizer: Aqua → S-NPP VIIRS 375 m (only VIIRS product loaded; 750 m unavailable).
* Training months: both sensors 100 % covered, standard-processing (not NRT), orbit-stable years only.
* Morning-gap training years: [2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022]. Sensor training years (operational fit): [2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022].
* Notes: MODIS orbit drift detected in the loaded records (mean day-time local overpass time moved more than 0.25 h from its early baseline): Terra [2023, 2024, 2025, 2026], Aqua [2023, 2024, 2025, 2026]. Those years are excluded from calibration because their diurnal sampling differs from the historical MODIS era.

### 2a. Learned national ratios (operational fit, central value and 5–95 % year-block bootstrap range)

| Month | Aqua→VIIRS day | Aqua→VIIRS night | Terra→Aqua day | Terra→Aqua night | reliable |
|---|---|---|---|---|---|
| Jan | 4.68 (4.46–4.84) | 11.62 (10.20–29.57) | 1.24 (1.14–1.34) | 0.04 (0.03–0.05) | yes |
| Feb | 5.73 (5.38–6.04) | 22.62 (17.30–26.96) | 1.85 (1.64–2.07) | 0.11 (0.08–0.13) | yes |
| Mar | 6.39 (5.91–6.82) | 36.54 (28.95–41.51) | 3.58 (3.37–3.82) | 0.23 (0.20–0.26) | yes |
| Apr | 8.15 (7.71–8.67) | 33.02 (30.42–35.84) | 1.69 (1.54–1.86) | 0.23 (0.21–0.25) | yes |
| May | 10.89 (10.22–11.69) | 24.24 (19.54–26.85) | 0.85 (0.79–0.89) | 0.22 (0.18–0.25) | yes |
| Jun | 7.44 (6.22–8.05) | 18.35 (14.15–24.10) | 0.60 (0.48–0.70) | 0.34 (0.30–0.38) | yes |
| Jul | 1.41 (1.04–1.73) | 29.82 (27.05–32.77) | 0.23 (0.20–0.27) | 0.20 (0.18–0.22) | NO |
| Aug | 0.54 (0.33–0.77) | 29.82 (27.05–32.77) | 0.24 (0.20–0.27) | 0.20 (0.18–0.22) | NO |
| Sep | 3.09 (2.49–3.60) | 29.82 (27.05–32.77) | 0.61 (0.45–0.78) | 0.20 (0.15–0.22) | NO |
| Oct | 4.73 (4.60–4.86) | 29.82 (27.05–32.77) | 4.86 (4.30–5.44) | 0.19 (0.10–0.27) | NO |
| Nov | 5.48 (5.30–5.69) | 29.82 (26.19–32.77) | 6.90 (6.18–7.51) | 0.07 (0.05–0.09) | NO |
| Dec | 5.53 (5.37–5.66) | 13.56 (9.54–28.55) | 1.38 (1.25–1.49) | 0.06 (0.04–0.07) | yes |

Night-time Terra→Aqua ratios below 1 show that the afternoon/early-morning pass does not always see more fire: the relationship is learned, not assumed.

## 3. Chronological held-out validation (actual)

* Validation kind: **actual_holdout**. Split 201701: train on 2017–2022, test on real VIIRS months 201202–201612 never seen in training.
* Status (PyroScope rule: good: WAPE <= 20% and |bias| <= 10%; moderate: WAPE <= 40%; otherwise poor (PyroScope convention, not an external standard).): **good**

| Method | n months | MAE | RMSE | WAPE | Bias | R² |
|---|---|---|---|---|---|---|
| PyroScope calibrated harmonization | 59 | 5,559 | 9,241 | 13.0% | -0.3% | 0.960 |
| Constant VIIRS/Aqua ratio baseline | 59 | 13,655 | 20,568 | 32.0% | 1.4% | 0.800 |
| Raw MODIS (Terra+Aqua, uncorrected) | 59 | 36,327 | 53,848 | 85.1% | -85.1% | -0.371 |
| · day-time detections | 59 | 4,621 | 7,674 | 13.5% | -1.7% | 0.951 |
| · night-time detections | 59 | 2,681 | 4,618 | 31.3% | 5.4% | 0.870 |
| · stage morning_gap_sensor | 20 | 7,547 | 10,963 | 17.3% | 10.2% | 0.948 |
| · stage sensor_calibrated | 39 | 4,540 | 8,219 | 10.7% | -5.8% | 0.966 |

Uncertainty band (5–95 % of replicates, nominal 90 %): empirical coverage on held-out months **89.8%** (close to nominal: well calibrated).

### 3a. Monthly performance (held-out)

| Month | n | WAPE | Bias |
|---|---|---|---|
| Jan | 4 | 11.6% | 5.5% |
| Feb | 5 | 24.9% | -12.8% |
| Mar | 5 | 8.5% | -0.5% |
| Apr | 5 | 14.0% | -2.6% |
| May | 5 | 14.2% | 8.7% |
| Jun | 5 | 33.5% | -12.0% |
| Jul | 5 | 39.4% | 17.6% |
| Aug | 5 | 31.1% | -6.3% |
| Sep | 5 | 9.4% | 9.4% |
| Oct | 5 | 11.4% | 9.2% |
| Nov | 5 | 10.4% | -4.0% |
| Dec | 5 | 10.3% | 8.2% |

### 3b. Morning-gap step (SIMULATED experiment, not the real 2000–2002 correction)

Real Aqua months 200207–201309 hidden; Terra used to estimate them.

| Method | n | MAE | RMSE | WAPE | Bias | R² |
|---|---|---|---|---|---|---|
| Calibrated Terra→Aqua | 135 | 1,728 | 3,970 | 42.1% | 33.4% | 0.424 |
| Constant Aqua/Terra ratio | 135 | 1,754 | 2,842 | 42.7% | -8.9% | 0.705 |

Band coverage: 86.7%.

## 4. 2012 seam test (actual_seam)

* Seam month 2012-02-01, window ±24 months.
* Step before harmonization (raw MODIS → VIIRS): **6.980**; after: **1.027** (band 0.938–1.093).
* Target step (true withheld VIIRS / unchanged reference sensor): 1.103 (Aqua MODIS reference 1.103).
* Artificial discontinuity |ln(step/target)|: before **1.845**, after **0.072** (reduction 96.1%); status good.
* Genuine change still detectable: **False** (no clear change).

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

* Real Terra-only morning-gap correction is applied to the loaded Terra-only months; there is no ground truth for those months, so its skill is measured only by the simulated withheld-Aqua experiment (3b).
* Real 2012 seam test uses the loaded pre-2012 MODIS record.
* NOAA-20: loaded; NOAA-21 loaded. Neither is the default calibration target (kept as separate actual observations).
* VIIRS 750 m (VNP14/VJ114) is not distributed by FIRMS; a separate 750 m calibration pathway exists but has no data.
* MODIS orbit drift years excluded from calibration: MODIS orbit drift detected in the loaded records (mean day-time local overpass time moved more than 0.25 h from its early baseline): Terra [2023, 2024, 2025, 2026], Aqua [2023, 2024, 2025, 2026]. Those years are excluded from calibration because their diurnal sampling differs from the historical MODIS era.
* Administrative intelligence (states, districts, land use) covers India only.
* Month coverage: S-NPP months with full coverage 168; Aqua 289; Terra 305.
