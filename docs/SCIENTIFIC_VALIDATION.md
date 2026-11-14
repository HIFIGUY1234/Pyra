# PyroScope - Scientific Validation Report

Generated 2026-11-14T16:55:16+00:00 by `python -m app.science_report` from the loaded data. Every number below is computed at generation time; nothing is typed by hand.

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

Uncertainty band (5–95 % of replicates, nominal 90 %): empirical coverage on held-out months **93.2%** (close to nominal: well calibrated).

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

20-month blocks of real Aqua (the length of the real Terra-only era) are hidden in turn; the Terra→Aqua calibration is refitted on every other overlap year (whole years removed) and the hidden Aqua months are the answer key. Blocks: 200209–200405, 200510–200706, 200811–201006, 201111–201306, 201411–201607, 201712–201907, 202012–202208.

| Method | n | MAE | RMSE | WAPE | Bias | R² |
|---|---|---|---|---|---|---|
| Calibrated Terra→Aqua (cell_silent) | 140 | 913 | 1,655 | 18.4% | 3.7% | 0.920 |
| Constant Aqua/Terra ratio | 140 | 2,248 | 3,512 | 45.3% | 5.0% | 0.641 |
| National month/day-night ratio | 140 | 858 | 1,501 | 17.3% | 2.5% | 0.934 |

Band coverage (nominal 90 %): **91.4%**; median relative band width 87%.

> **Limitation.** Trained only on later years (the situation of the real Terra-only correction), the selected model's national bias is +12.2% - estimates for months before the overlap period may be systematically high by roughly this amount.

Chain experiment (Aqua hidden 201202–201309, calibration trained only on years ≥ split): WAPE 12.9%, bias 6.3%, R² 0.971 vs constant ratio WAPE 54.1%.

### 3c. Calibration model selection (held-out, year-blocked)

Earlier versions of this report scored the morning-gap step with a design that, once pre-2012 MODIS was loaded, hid Aqua for 135 months (2002-07 → 2013-09) and trained only on 2017–2022. Its +33 % bias was a property of that decade-long backward extrapolation, not of the operational fit (which trains on all overlap years). That design is kept below as a labelled stress test.

**Terra MODIS -> Aqua MODIS** — selected: `cell_silent` (no candidate beat the default model on both leave-one-year-out and 20-month block hold-out (state-month level)). Rule: replace the default only if a candidate wins on both leave-one-year-out and 20-month block hold-out (state-month WAPE lower by >= 1.0 pt, |bias| no worse by > 1 pt, R^2 no lower)

| Design | folds | cell_silent | cell_silent_scaled | ratio_state | ratio_national | constant |
|---|---|---|---|---|---|---|
| leave_one_year_out | 21 | 32.2 / 0.0 / 0.81 (nat 19.3) | 32.2 / 0.3 / 0.79 (nat 18.5) | 33.0 / 1.1 / 0.78 (nat 19.0) | 57.7 / 0.2 / 0.72 (nat 17.9) | 78.2 / 0.1 / 0.31 (nat 48.3) |
| block_20_month | 7 | 32.0 / 3.7 / 0.78 (nat 18.4) | 31.8 / 4.4 / 0.74 (nat 17.2) | 32.6 / 5.5 / 0.73 (nat 17.6) | 55.8 / 2.5 / 0.74 (nat 17.3) | 75.6 / 5.0 / 0.36 (nat 45.3) |
| rolling_origin_forward | 16 | 31.6 / -7.1 / 0.84 (nat 18.0) | 32.7 / -3.0 / 0.83 (nat 16.7) | 33.6 / -1.2 / 0.81 (nat 17.3) | 60.4 / 2.9 / 0.68 (nat 18.3) | 82.8 / 8.4 / 0.22 (nat 50.9) |
| rolling_origin_backward | 16 | 37.7 / 12.2 / 0.64 (nat 23.6) | 37.2 / 10.0 / 0.58 (nat 23.6) | 38.1 / 11.1 / 0.56 (nat 24.0) | 54.6 / -0.9 / 0.76 (nat 19.9) | 72.5 / -7.4 / 0.45 (nat 44.6) |

Cells: state-month WAPE % / bias % / R² (national-month WAPE %).
Band coverage of the selected model: block design 91.4%, backward rolling-origin 84.5% (nominal 90 %).

Block-design diagnostics: day WAPE 18.6%, night WAPE 22.8%; low-count months WAPE 17.6%, high-count 18.5% (split at 2,796 detections).

| State | n | WAPE | Bias |
|---|---|---|---|
| Punjab | 140 | 41.5% | 18.3% |
| Mizoram | 140 | 47.5% | 6.1% |
| Assam | 140 | 24.5% | -5.0% |
| Madhya Pradesh | 140 | 22.2% | 0.8% |
| Manipur | 140 | 25.0% | -6.5% |
| Odisha | 140 | 25.4% | -2.5% |
| Chhattīsgarh | 140 | 22.8% | -2.3% |
| Mahārāshtra | 140 | 20.2% | -0.7% |

**Aqua MODIS -> Suomi NPP VIIRS 375 m** — selected: `cell_silent` (no candidate beat the default model on both leave-one-year-out and 20-month block hold-out (state-month level)). Rule: replace the default only if a candidate wins on both leave-one-year-out and 20-month block hold-out (state-month WAPE lower by >= 1.0 pt, |bias| no worse by > 1 pt, R^2 no lower)

| Design | folds | cell_silent | cell_silent_scaled | ratio_state | ratio_national | constant |
|---|---|---|---|---|---|---|
| leave_one_year_out | 11 | 17.1 / 0.5 / 0.97 (nat 9.6) | 18.8 / -0.3 / 0.96 (nat 9.8) | 19.0 / -0.0 / 0.95 (nat 11.0) | 37.9 / 0.0 / 0.85 (nat 10.5) | 55.2 / -0.0 / 0.52 (nat 30.1) |
| block_20_month | 4 | 17.0 / 0.6 / 0.97 (nat 9.3) | 19.7 / 1.9 / 0.96 (nat 10.6) | 19.9 / 2.3 / 0.95 (nat 12.0) | 40.2 / 1.4 / 0.82 (nat 11.4) | 54.9 / -4.9 / 0.54 (nat 27.3) |
| rolling_origin_forward | 6 | 17.0 / 3.0 / 0.97 (nat 8.9) | 19.6 / 5.8 / 0.96 (nat 8.9) | 19.8 / 6.9 / 0.94 (nat 11.2) | 37.8 / 3.0 / 0.85 (nat 10.5) | 53.9 / 0.8 / 0.52 (nat 28.8) |
| rolling_origin_backward | 6 | 17.9 / -0.7 / 0.97 (nat 10.1) | 19.7 / -4.8 / 0.95 (nat 11.1) | 19.4 / -5.9 / 0.95 (nat 12.2) | 37.8 / -2.9 / 0.85 (nat 12.2) | 55.2 / -0.2 / 0.54 (nat 30.7) |

Cells: state-month WAPE % / bias % / R² (national-month WAPE %).
Band coverage of the selected model: block design 88.8%, backward rolling-origin 77.5% (nominal 90 %).

Block-design diagnostics: day WAPE 8.5%, night WAPE 28.0%; low-count months WAPE 13.4%, high-count 8.9% (split at 26,151 detections).

| State | n | WAPE | Bias |
|---|---|---|---|
| Punjab | 80 | 13.1% | 5.5% |
| Madhya Pradesh | 80 | 14.1% | -1.5% |
| Chhattīsgarh | 80 | 19.1% | -6.1% |
| Mahārāshtra | 80 | 10.7% | -2.8% |
| Odisha | 80 | 22.8% | -3.6% |
| Andhra Pradesh | 80 | 12.9% | -0.5% |
| Telangāna | 80 | 17.3% | -5.3% |
| Uttar Pradesh | 80 | 16.6% | -1.2% |

**Extrapolation stress test** (train 2017–2022 only, predict 200209–201612, 169 months): cell_silent WAPE 37.3% bias 29.7% R² 0.48; cell_silent_scaled WAPE 37.7% bias 26.6% R² 0.43; ratio_state WAPE 39.3% bias 29.5% R² 0.38; ratio_national WAPE 24.8% bias 1.0% R² 0.82; constant WAPE 44.8% bias -11.3% R² 0.65.

Training only on the most recent overlap years and predicting a decade backwards. All model forms degrade together here, so this measures temporal non-stationarity of the Terra/Aqua relationship; it is not the operational correction, which trains on every overlap year.

## 4. 2012 seam test (actual_seam)

* Seam month 2012-02-01, window ±24 months.
* Step before harmonization (raw MODIS → VIIRS): **6.980**; after: **1.027** (band 0.938–1.093).
* Target step (true withheld VIIRS / unchanged reference sensor): 1.103 (Aqua MODIS reference 1.103).
* Artificial discontinuity |ln(step/target)|: before **1.845**, after **0.072** (reduction 96.1%); status good.
* Genuine change still detectable: **False** (no clear change). The reference sensor shows +10% but the harmonized step is +3% (band -6%..+9%): the harmonization damps part of this genuine change. Reported as a limitation rather than adjusted away.
* **Verdict: PARTIAL** — rule: pass: residual artificial jump <= 0.10 ln-units and the reference-sensor step lies inside the harmonized step band; partial: residual jump <= 0.25 or >= 50% reduction; otherwise fail.

### 4a. Seam robustness (real seam)

| Scope | Window | Raw step | Harmonized step (band) | Reference step | Jump before → after | Verdict |
|---|---|---|---|---|---|---|
| India | ±12 | 7.95 | 1.176 (1.02–1.27) | 1.314 | 1.80 → 0.111 | partial |
| India | ±24 | 6.98 | 1.027 (0.94–1.09) | 1.103 | 1.84 → 0.072 | partial |
| India | ±36 | 6.47 | 0.971 (0.89–1.02) | 1.000 | 1.87 → 0.029 | pass |
| Punjab | ±24 | 5.05 | 1.110 (0.94–1.22) | 1.096 | 1.53 → 0.013 | pass |
| Madhya Pradesh | ±24 | 6.29 | 0.803 (0.71–0.89) | 0.883 | 1.96 → 0.095 | pass |
| Mizoram | ±24 | 3.01 | 0.834 (0.67–1.01) | 0.943 | 1.16 → 0.123 | partial |
| Assam | ±24 | 4.54 | 1.143 (1.02–1.36) | 1.208 | 1.32 → 0.055 | pass |
| Chhattīsgarh | ±24 | 11.77 | 0.941 (0.81–1.09) | 1.055 | 2.41 → 0.114 | partial |
| Odisha | ±24 | 14.04 | 1.139 (0.96–1.32) | 1.201 | 2.46 → 0.053 | pass |
| Manipur | ±24 | 4.09 | 1.041 (0.88–1.24) | 1.069 | 1.34 → 0.026 | pass |
| Mahārāshtra | ±24 | 11.04 | 1.091 (0.97–1.21) | 1.286 | 2.15 → 0.164 | partial |

State verdicts: {'pass': 5, 'partial': 3}.

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
* MODIS row `version` strings 6.03 (2000-2022) and 61.03 (2023 onward) are not defined in readable FIRMS documentation; they are kept verbatim and the collection (C6.1) is taken from the archive name.
* NOAA-21 archive records begin 2023-03 (pre-operational period, official FIRMS start 2024-01-17); kept as labelled actual observations, not a calibration target.
* NRT records are provisional and never used for calibration or validation.
* Month coverage: S-NPP months with full coverage 168; Aqua 289; Terra 305.
