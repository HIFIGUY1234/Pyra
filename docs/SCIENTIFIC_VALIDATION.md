# PyroScope - Scientific Validation Report

Generated 2026-11-14T23:10:22+00:00 by `python -m app.science_report` from the loaded data. Every number below is computed at generation time; nothing is typed by hand.

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

Under long backward extrapolation the selected state-level model (cell_silent) degrades to national WAPE 37.3% / bias +29.7%, while 'ratio_national' stays at 24.8% / +1.0%: regional structure learned from recent years transfers poorly to a decade earlier, whereas the national seasonal ratio is stable. The operational fit trains on every overlap year, so this stress test bounds, but does not measure, the operational error; national totals far outside the overlap period should be read with this bias in mind.

**Real Terra-only era (200011–200206, 19 months) — model-structure sensitivity.** Actual Terra detections 30,872; Aqua-equivalent estimate totals by model form (all fitted on every overlap year): cell_silent 82,384, cell_silent_scaled 79,435, ratio_state 79,857, ratio_national 75,004, constant 80,407. Spread 9.0% of the selected model's total. Estimates only - there is no Aqua ground truth before July 2002. Partial-coverage scaling used in the operational series is not applied here, so totals can differ slightly from the Morning-Gap page.

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

* Target: At least one NOAA-21 VIIRS 375 m presumed-vegetation detection in the 0.25 deg cell within 7 days of the issue date — probability of a detectable satellite hotspot (NOT a verified ground ignition).
* Split: train ≤ 2025-03-31, isotonic calibration ≤ 2025-09-30, test 2025-10-01 → 2026-07-25.
* Test rows 194,661; base rate 0.341.

| Metric | Calibrated model | Climatology baseline |
|---|---|---|
| Brier | 0.1223 | 0.1477 |
| ROC-AUC | 0.895 | 0.851 |
| PR-AUC | 0.830 | 0.735 |

Brier skill vs climatology: 0.172.

| Threshold | Precision | Recall | False-alarm rate | Missed-event rate |
|---|---|---|---|---|
| 60 % (HIGH) | 0.859 | 0.553 | 0.0471 | 0.447 |
| 80 % (VERY HIGH) | 0.949 | 0.300 | 0.0084 | 0.700 |

Regional aggregation: `P(any detection in region) = 1 - prod(1 - p_cell) ** alpha` with α = 0.68 (fitted on calibration years).

### 5a. Forecast candidate-model comparison

* Equal footing: 600,000 training rows (same subsample for every model), isotonic calibration ≤ 2023-12-31, test ≥ 2024-01-01 (629,104 rows).
* Rule: A candidate replaces XGBoost only if it improves test Brier by >= 2 % relative AND ROC-AUC by >= 0.005 on the main split AND is not worse in Brier on any rolling origin.
* Decision: **XGBoost retained: hist_gradient_boosting (best alternative) does not meet the rule**.

| Model | Brier | BSS | ROC-AUC | PR-AUC | ECE | Precision@0.6 | Recall@0.6 | Specificity |
|---|---|---|---|---|---|---|---|---|
| climatology | 0.10673 | 0.0000 | 0.9021 | 0.7738 | 0.0144 | 0.816 | 0.521 | 0.957 |
| logistic | 0.10078 | 0.0557 | 0.9122 | 0.8097 | 0.0039 | 0.815 | 0.598 | 0.950 |
| random_forest | 0.09801 | 0.0817 | 0.9186 | 0.8198 | 0.0053 | 0.829 | 0.587 | 0.956 |
| hist_gradient_boosting | 0.09756 | 0.0859 | 0.9197 | 0.8216 | 0.0061 | 0.833 | 0.584 | 0.957 |
| xgboost | 0.09726 | 0.0887 | 0.9201 | 0.8226 | 0.0058 | 0.834 | 0.582 | 0.958 |

Rolling-origin Brier (train → calibrate → test year):

| Test year ends | climatology | logistic | random_forest | hist_gradient_boosting | xgboost |
|---|---|---|---|---|---|
| 2021-12-31 | 0.1035 | 0.0899 | 0.0875 | 0.0867 | 0.0867 |
| 2022-12-31 | 0.1068 | 0.0991 | 0.0960 | 0.0950 | 0.0951 |
| 2023-12-31 | 0.1135 | 0.1071 | 0.1045 | 0.1030 | 0.1030 |

Not included: lightgbm: Not installed and not added: it is the same histogram gradient-boosting family as XGBoost and HistGradientBoosting, so it would add a dependency without testing a different idea.

### 5b. NOAA-21 → S-NPP cross-calibration study (operational period only)

* Matched days 1,211; operational start 2024-01-17. Operational S-NPP/NOAA-21 count ratio: {'D': 1.0502, 'N': 1.0216}.
* Acceptance rule: adopt only if better than identity AND national ratio by >= 1 WAPE point on both splits, |bias| <= 5 %, national band coverage >= 80 %, test >= 12 months and >= 10,000 reference detections.
* Result: **not_calibrated** — no candidate met the declared criteria.

| Split | Train | Test | identity WAPE / bias | national ratio | state ratio | state×season ratio |
|---|---|---|---|---|---|---|
| forward | 2024-01–2025-07 | 2025-08–2026-07 | 7.01 % / -1.73 % | 7.15 % / +4.20 % | 7.44 % / +4.16 % | 6.69 % / +3.74 % |
| backward | 2025-08–2026-07 | 2024-08–2025-07 | 7.93 % / -5.28 % | 7.29 % / -3.65 % | 7.63 % / -3.46 % | 7.36 % / -3.21 % |

(state-month WAPE / bias against S-NPP.) NOAA-21 therefore remains a separate actual stream, not a calibrated S-NPP substitute.

### 5c. SGP4 overpass prediction checked against actual detections

| Satellite | TLE epoch | n | Mean abs residual (min) | 95th pct (min) | Within 10 min |
|---|---|---|---|---|---|
| Terra | 2026-11-14T06:19 | 400 | 0.83 | 1.83 | 100.0 % |
| Aqua | 2026-11-14T06:27 | 400 | 0.82 | 1.83 | 100.0 % |
| Suomi NPP | 2026-11-14T06:18 | 400 | 0.9 | 2.0 | 100.0 % |
| NOAA-20 | 2026-11-14T06:38 | 400 | 0.85 | 2.17 | 100.0 % |
| NOAA-21 | 2026-11-14T05:41 | 400 | 0.86 | 1.84 | 100.0 % |

Residual = recorded FIRMS acq_time − predicted closest approach; recorded times have minute / granule resolution.

### 5d. Exposure layers

* Population: WorldPop Global 2000-2020 1 km UN-adjusted population counts, India, 2020 (CC BY 4.0 (WorldPop, www.worldpop.org; doi:10.5258/SOTON/WP00671)); total in AOI 1,380,004,385; 4,885 0.25° cells; raster grid aligned to 30″: False (pixel-centre assignment, each pixel counted once).
* Infrastructure (OpenStreetMap, ODbL): hospital 55,454, clinic 22,581, fire_station 727, police 4,466, school 37,707, power_substation 17,140, power_plant 4,431, railway_station 9,013, water_works 2,018, communications 2,705, industrial_site 5,710.
* Not loaded (reported missing, never zero): roads, railways, transmission_lines, residential_settlements.
* A nearby population or facility count describes proximity to detected heat, not a prediction that people or assets will burn.

## 5f. Operational sensor transition (S-NPP science data ended 2026-11-02)

* Historical harmonization reference: **Suomi NPP** (unchanged; its archive defines the VIIRS-equivalent scale).
* Operational candidates: NOAA-21 (NOAA primary successor), NOAA-20 (secondary). Criteria declared in `app/operational.py`.

* Operational reference: **NOAA-21** (APPROVED, evidence_default).

| Criterion | NOAA-21 | NOAA-20 |
|---|---|---|
| C1 Platform officially operational | pass | pass |
| C2 Last observation within 14 days of the newest loaded observation | pass | pass |
| C3 >= 24 months of science-quality archive | pass | pass |
| C4 Missing-day share <= 5% | pass | pass |
| C5 Independent forecast model trained on this sensor exists | pass | pass |
| C6 Own test period: >= 50,000 rows, Brier skill > 0 vs climatology, ROC-AUC >= 0.8, ECE <= 0.05 | pass | pass |

#### Independent per-sensor forecast models (each on its own chronological test period)

| Sensor | Model | Train ≤ | Calibrate ≤ | Test | Test rows | Brier | BSS vs climatology | ROC-AUC | PR-AUC | ECE | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Suomi NPP | suomi-npp-xgb-legacy | 2021-12-31 | 2023-12-31 | 2024-01-01 → 2026-11-07 | 629,104 | 0.0971 | 0.090 | 0.920 | 0.823 | – | STALE_RETIRED_SENSOR |
| NOAA-20 | noaa-20-xgb-349f66348d | 2022-12-31 | 2024-06-30 | 2024-07-01 → 2026-07-25 | 493,884 | 0.0926 | 0.097 | 0.926 | 0.836 | 0.0078 | CURRENT |
| NOAA-21 | noaa-21-xgb-092cc21714 | 2025-03-31 | 2025-09-30 | 2025-10-01 → 2026-07-25 | 194,661 | 0.1223 | 0.172 | 0.895 | 0.830 | 0.0344 | CURRENT |

Metrics come from different test periods and base rates; compare each model with its own climatology baseline (BSS), not with each other.

#### Bridge calibrations (successor → reference scale)

| Pair | Overlap | Raw reference/target ratio (D / N) | Status | Reason |
|---|---|---|---|---|
| NOAA-20 → Suomi NPP | 2018-04-01 → 2026-07-31 | 0.993 / 0.980 | not_calibrated | no candidate met the declared criteria: state_season_ratio: forward: WAPE 5.35 not >= 1 point better than identity 5.49; forward: not >= 1 point better than national ratio; forward: band coverage 33.3 % < 80 % | state_ra |
| NOAA-21 → Suomi NPP | 2024-01-17 → 2026-07-31 | 1.050 / 1.022 | not_calibrated | no candidate met the declared criteria: state_season_ratio: forward: WAPE 7.52 not >= 1 point better than identity 7.93; forward: not >= 1 point better than national ratio; forward: band coverage 66.7 % < 80 % | state_ra |
| NOAA-21 → NOAA-20 | 2024-01-17 → 2026-07-31 | 1.061 / 1.056 | not_calibrated | no candidate met the declared criteria: state_season_ratio: forward: not >= 1 point better than national ratio; forward: band coverage 41.7 % < 80 %; backward: not >= 1 point better than national ratio | state_ratio: for |

Transition verdict: **NOT_BRIDGED**. Month-to-month S-NPP/successor ratios measure the sensor difference during simultaneous observation; the spread (p05-p95) shows how much of an apparent step can be sensor noise. Genuine burning changes must appear in BOTH platforms. No continuation of the S-NPP-equivalent record past 2026-07-31 is produced unless a bridge passes its acceptance rule.

* NOAA-21: window 2025-08 → 2026-07, S-NPP/NOAA-21 ratio 0.963 (monthly p05–p95 0.738 – 1.048); calibrated discontinuity: not computed: no bridge calibration passed its acceptance rule, so no calibrated continuation is produced.
* NOAA-20: window 2025-08 → 2026-07, S-NPP/NOAA-20 ratio 0.923 (monthly p05–p95 0.715 – 1.014); calibrated discontinuity: not computed: no bridge calibration passed its acceptance rule, so no calibrated continuation is produced.

#### 2012 seam: why PARTIAL, and seasonal sensitivity

* PARTIAL because the unchanged reference-sensor step 1.103 lies outside the harmonized step band 0.938-1.093. The jump was still reduced by 96 %. Thresholds are fixed in advance and are not tuned to obtain a pass.
* Genuine change: The reference sensor shows +10% but the harmonized step is +3% (band -6%..+9%): the harmonization damps part of this genuine change. Reported as a limitation rather than adjusted away.

| Season | Months each side | Raw step | Harmonized step | Aqua reference step | Jump before | Jump after |
|---|---|---|---|---|---|---|
| winter | 6 | 8.600 | 1.244 | 1.444 | 1.784 | 0.149 |
| pre-monsoon | 6 | 7.195 | 0.964 | 1.008 | 1.966 | 0.044 |
| monsoon | 8 | 14.200 | 1.273 | 1.818 | 2.055 | 0.356 |
| post-monsoon | 4 | 5.211 | 1.065 | 1.121 | 1.536 | 0.052 |

Monsoon months carry the largest residual jump (few detections, cloud), which is where the harmonized step under-reads the Aqua reference.

## 6. Data limitations

* Real Terra-only morning-gap correction is applied to the loaded Terra-only months; there is no ground truth for those months, so its skill is measured only by the simulated withheld-Aqua experiment (3b).
* Real 2012 seam test uses the loaded pre-2012 MODIS record.
* NOAA-20: loaded; NOAA-21 loaded. Neither is the default calibration target (kept as separate actual observations).
* VIIRS 750 m (VNP14/VJ114/VJ214 v002, LP DAAC): granule search works without credentials, but download needs Earthdata Login, which is not configured here; no 750 m records are loaded and the 750 m calibration is not run.
* S-NPP VIIRS science-data delivery ceased 2026-11-02 (NOAA NESDIS / NASA Earthdata): S-NPP stays the historical reference; live forecasts use an independently trained, criteria-approved operational platform (section 5f). The legacy S-NPP forecast is labelled STALE_RETIRED_SENSOR.
* MODIS orbit drift years excluded from calibration: MODIS orbit drift detected in the loaded records (mean day-time local overpass time moved more than 0.25 h from its early baseline): Terra [2023, 2024, 2025, 2026], Aqua [2023, 2024, 2025, 2026]. Those years are excluded from calibration because their diurnal sampling differs from the historical MODIS era.
* Administrative intelligence (states, districts, land use) covers India only.
* MODIS row `version` strings 6.03 (2000-2022) and 61.03 (2023 onward) are not defined in readable FIRMS documentation; they are kept verbatim and the collection (C6.1) is taken from the archive name.
* NOAA-21 archive records begin 2023-03 (pre-operational period, official FIRMS start 2024-01-17); kept as labelled actual observations, excluded from NOAA-21 forecast labels, and not a calibration target.
* NRT records are provisional and never used for calibration or validation.
* Month coverage: S-NPP months with full coverage 168; Aqua 289; Terra 305.
