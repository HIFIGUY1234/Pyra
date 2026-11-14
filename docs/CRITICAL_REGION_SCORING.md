# Critical-region scoring methodology

Code: `backend/app/critical_scoring.py`, `analytics.district_table`, `analytics.critical_regions`.
API: `GET /api/critical-regions`, `GET /api/critical-regions/sensitivity`, `GET|PUT|DELETE /api/critical-regions/weights`.

## What it is

A **deterministic, transparent decision-support ranking of districts** for monitoring attention. It is not a
ground-truth risk score and not a learned model: there is no independent record of which districts "needed
attention", so a learned ranking would have nothing honest to learn from.

## Components (each normalised to [0, 1])

| Component | Source | Normalisation | Kind |
|---|---|---|---|
| forecast | highest calibrated 7-day hotspot probability among the district's cells | already a probability | hazard |
| recent | 30-day detections per cell | percentile rank | hazard |
| recurrence | share of earlier years with a detection in these weeks | as is | hazard |
| frp | mean FRP per detection (≥ 5 detections) | percentile rank | hazard |
| anomaly | robust seasonal z-score (leave-one-year-out) | clip(z, 0, 3) / 3 | hazard |
| land_cover | forest + savanna/woodland share | as is | fuel context |
| population | people in the district's cells (WorldPop 2020) | percentile rank | exposure |
| infrastructure | mapped facilities + (major road + rail + power-line km) / 10 | percentile rank | exposure |
| observation_gap | share of the last 30 days the target sensor did not observe | as is | monitoring need |
| uncertainty | mean model-spread band width | percentile rank | monitoring need |

Percentile ranks stop one enormous count (e.g. a stubble-burning district) from dominating every other signal.

## Missing inputs

A component that is unavailable for a district is **dropped for that district** and the remaining weights are
renormalised; the item lists `missing_components` and the available weight share. Missing never means zero:
a district without a population layer is not scored as "no people".

## Weights and versions

| Profile | Use |
|---|---|
| `v2-balanced` (default) | hazard ≈ 72 %, exposure 20 %, monitoring need 8 % |
| `hazard-led` | no exposure; for pure fire-activity screening |
| `exposure-led` | emphasises population and infrastructure |
| `v1-legacy` | the original weights (for comparison) |

Administrators can store a custom profile (`PUT /api/critical-regions/weights`); it is normalised, versioned
(`custom-1`, `custom-2`, … with the previous version recorded) and audited. `DELETE` reverts to the default.
Every response states `weights_version`, per-item `contributions` (which sum to the score), and the hazard vs
exposure parts.

## Sensitivity and evaluation

`GET /api/critical-regions/sensitivity` reports:
* Spearman correlation and top-20 overlap of each profile with the active one;
* ±20 % single-weight perturbations (minimum top-20 overlap);
* historical alignment: for past forecast issues with verified 7-day outcomes, Spearman between score and the
  share of district cells that then had a detection, and the top-20 hit rate. The model with the most verified
  issues is used and named. This measures **hazard alignment only** — exposure-led profiles are not meant to
  maximise it.

## Interpretation rules

* Population and infrastructure proximity raise monitoring priority; they never raise any fire probability.
* A nearby road or power line does not mean it is damaged.
* Priority bands are score percentiles (top 5 % Critical, next 15 % High, next 30 % Elevated).
