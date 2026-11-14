# Forecast model comparison

Generated from `data/processed/models/forecast_comparison.json` (`python -m app.pipeline --compare-forecast`, or `forecast_eval.compare()`). API: `GET /api/forecast/comparison`. UI: Forecast page → *Forecast model comparison*.

## Target

P(>= 1 S-NPP VIIRS 375 m presumed-vegetation detection in the 0.25 deg cell within 7 days). This is the probability that the satellite *detects* at least one hotspot — not a verified ignition or wildfire probability.

## Design

* Same 600,000 training rows (seeded subsample), same calibration and test rows for every model.
* Train label windows ending ≤ 2021-12-31; isotonic calibration ≤ 2023-12-31; test ≥ 2024-01-01.
* Rows: train available 1,161,776, used 600,000; calibration 468,384; test 629,104.
* Leakage controls (all inherited from ``forecast.build_dataset``):
    * every feature at issue date t uses data up to and including t only (cumulative windows end at t);
    * weather features are POWER observations up to t (no forecast weather, no future values);
    * labels are the following 7 days; weeks overlapping an S-NPP data gap are unknown and dropped;
    * the split is on label-window end dates, so no training label window reaches the calibration years;
    * the climatology feature uses earlier years only.

* Selection rule: A candidate replaces XGBoost only if it improves test Brier by >= 2 % relative AND ROC-AUC by >= 0.005 on the main split AND is not worse in Brier on any rolling origin.

**Decision: XGBoost retained: hist_gradient_boosting (best alternative) does not meet the rule.**

## Main split (test 2024 → latest)

| Model | Brier | BSS | ROC-AUC | PR-AUC | ECE | Precision@0.6 | Recall@0.6 | Specificity | FPR | Missed-event rate |
|---|---|---|---|---|---|---|---|---|---|---|
| climatology | 0.10673 | 0.0000 | 0.9021 | 0.7738 | 0.0144 | 0.816 | 0.521 | 0.957 | 0.0432 | 0.479 |
| logistic | 0.10078 | 0.0557 | 0.9122 | 0.8097 | 0.0039 | 0.815 | 0.598 | 0.950 | 0.0497 | 0.402 |
| random_forest | 0.09801 | 0.0817 | 0.9186 | 0.8198 | 0.0053 | 0.829 | 0.587 | 0.956 | 0.0443 | 0.413 |
| hist_gradient_boosting | 0.09756 | 0.0859 | 0.9197 | 0.8216 | 0.0061 | 0.833 | 0.584 | 0.957 | 0.0429 | 0.416 |
| xgboost | 0.09726 | 0.0887 | 0.9201 | 0.8226 | 0.0058 | 0.834 | 0.582 | 0.958 | 0.0424 | 0.418 |

Confusion matrices at 0.6 (tp / fp / fn / tn):

* climatology: 87,840 / 19,874 / 80,801 / 440,589
* logistic: 100,900 / 22,869 / 67,741 / 437,594
* random_forest: 98,904 / 20,386 / 69,737 / 440,077
* hist_gradient_boosting: 98,422 / 19,761 / 70,219 / 440,702
* xgboost: 98,194 / 19,516 / 70,447 / 440,947

## Rolling origins (Brier)

| Test year ending | climatology | logistic | random_forest | hist_gradient_boosting | xgboost |
|---|---|---|---|---|---|
| 2021-12-31 | 0.10345 | 0.08989 | 0.08747 | 0.08674 | 0.08672 |
| 2022-12-31 | 0.10683 | 0.09912 | 0.09597 | 0.09505 | 0.09507 |
| 2023-12-31 | 0.11353 | 0.10706 | 0.10445 | 0.10303 | 0.10302 |

XGBoost and HistGradientBoosting are effectively tied on every origin (differences ≤ 0.00003); neither clears the replacement rule.

## Reliability (XGBoost, test)

| Bin | n | Mean predicted | Observed |
|---|---|---|---|
| 0.0–0.1 | 304,316 | 0.025 | 0.026 |
| 0.1–0.2 | 78,873 | 0.149 | 0.153 |
| 0.2–0.3 | 42,258 | 0.260 | 0.268 |
| 0.3–0.4 | 31,567 | 0.356 | 0.362 |
| 0.4–0.5 | 27,871 | 0.448 | 0.460 |
| 0.5–0.6 | 26,509 | 0.547 | 0.564 |
| 0.6–0.7 | 24,681 | 0.650 | 0.659 |
| 0.7–0.8 | 28,838 | 0.751 | 0.773 |
| 0.8–0.9 | 24,549 | 0.853 | 0.874 |
| 0.9–1.0 | 39,642 | 0.952 | 0.963 |

## Breakdowns

Available in the JSON for: state, month, season, land_use, activity_last_30d, observation_coverage. Groups with too few positives are flagged `reliable: false` and must not be read as skill.

* States: 34; unreliable (small samples): Dādra and Nagar Haveli and Damān and Diu, Delhi, Ladākh.
* Day/night: Not applicable: the target counts day and night detections together within a 7-day window.

## Model cards

| Model | Algorithm | Features | Fit (s) | Version |
|---|---|---|---|---|
| climatology | Seasonal recurrence (same weeks in earlier years) mapped to probability by isotonic regression | 1 | 0.2 | compare-1 |
| logistic | L2 logistic regression (lbfgs, C=1) on standardised features + missing-value indicators | 38 | 2.9 | compare-1 |
| random_forest | Random forest (200 trees, max_depth 14, min_samples_leaf 50) | 19 | 48.7 | compare-1 |
| hist_gradient_boosting | scikit-learn HistGradientBoosting (300 iterations, lr 0.08, max_leaf_nodes 63) | 35 | 24.4 | compare-1 |
| xgboost | XGBoost gbtree hist, depth 6, eta 0.08, 300 rounds (production configuration) | 35 | 13.3 | compare-1 |

Feature provenance (all models): FIRMS S-NPP VIIRS + MODIS detections (repository archives), NASA POWER daily weather, MCD12Q1 land cover; all windows end at the issue date.

## Not included

* lightgbm: Not installed and not added: it is the same histogram gradient-boosting family as XGBoost and HistGradientBoosting, so it would add a dependency without testing a different idea.

## Limitations

* The S-NPP reference stream stopped delivering science data on 2026-11-02; new labels for retraining must come from another sensor.
* Grid cells are 0.25°; scores say nothing about sub-cell location.
* A high probability reflects recurring detectable burning (mostly agricultural residue), not wildfire danger alone.
