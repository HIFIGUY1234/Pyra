"""Forecast candidate-model comparison, rolling-origin evaluation, breakdowns and model cards.

Every candidate sees the same rows, features and chronological split as the production model
(train <= 2021 | isotonic calibration 2022-2023 | test >= 2024) and is calibrated the same way.
Production stays XGBoost unless a candidate wins on the declared rule (see ``SELECTION_RULE``).

Leakage controls (all inherited from ``forecast.build_dataset``):
  * every feature at issue date t uses data up to and including t only (cumulative windows end at t);
  * weather features are POWER observations up to t (no forecast weather, no future values);
  * labels are the following 7 days; weeks overlapping an S-NPP data gap are unknown and dropped;
  * the split is on label-window end dates, so no training label window reaches the calibration years;
  * the climatology feature uses earlier years only.
Spatial transfer is not claimed: cells appear in all periods; this design measures temporal skill.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import forecast as F
from . import store
from .config import MODELS, RNG_SEED

OUT = MODELS / "forecast_comparison.json"
TRAIN_ROWS = 600_000        # identical stratified-by-time subsample for every candidate (equal footing)
MIN_N, MIN_POS = 500, 30    # breakdown cells below this are reported but flagged unreliable
THRESHOLD = 0.6
SELECTION_RULE = ("A candidate replaces XGBoost only if it improves test Brier by >= 2 % relative AND ROC-AUC by >= 0.005 "
                  "on the main split AND is not worse in Brier on any rolling origin.")
SEASON = {12: "winter", 1: "winter", 2: "winter", 3: "pre-monsoon", 4: "pre-monsoon", 5: "pre-monsoon",
          6: "monsoon", 7: "monsoon", 8: "monsoon", 9: "monsoon", 10: "post-monsoon", 11: "post-monsoon"}

CARDS = {
    "climatology": {"algorithm": "Seasonal recurrence (same weeks in earlier years) mapped to probability by isotonic regression",
                    "features": ["clim"]},
    "logistic": {"algorithm": "L2 logistic regression (lbfgs, C=1) on standardised features + missing-value indicators",
                 "features": "all, median-imputed from training rows"},
    "random_forest": {"algorithm": "Random forest (200 trees, max_depth 14, min_samples_leaf 50)", "features": "all, median-imputed"},
    "hist_gradient_boosting": {"algorithm": "scikit-learn HistGradientBoosting (300 iterations, lr 0.08, max_leaf_nodes 63)",
                               "features": "all (native missing-value handling)"},
    "xgboost": {"algorithm": "XGBoost gbtree hist, depth 6, eta 0.08, 300 rounds (production configuration)",
                "features": "all (native missing-value handling)"},
}
NOT_INCLUDED = {"lightgbm": "Not installed and not added: it is the same histogram gradient-boosting family as XGBoost and "
                            "HistGradientBoosting, so it would add a dependency without testing a different idea."}


def _ece(y, p, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    b = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    return float(sum(abs(y[b == i].mean() - p[b == i].mean()) * (b == i).mean() for i in range(bins) if (b == i).any()))


def metrics(y, p, clim_brier=None, t=THRESHOLD) -> dict:
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    n, pos = len(y), int(y.sum())
    out = {"n": n, "positives": pos, "base_rate": round(float(y.mean()), 4) if n else None,
           "reliable": bool(n >= MIN_N and pos >= MIN_POS and n - pos >= MIN_POS)}
    if n == 0:
        return out
    pred = p >= t
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    fn, tn = int((~pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
    br = float(brier_score_loss(y, p))
    out.update(brier=round(br, 5),
               brier_skill=round(1 - br / clim_brier, 4) if clim_brier else None,
               roc_auc=round(float(roc_auc_score(y, p)), 4) if 0 < pos < n else None,
               pr_auc=round(float(average_precision_score(y, p)), 4) if pos else None,
               ece=round(_ece(y, p), 4), threshold=t,
               confusion={"tp": tp, "fp": fp, "fn": fn, "tn": tn},
               precision=round(tp / (tp + fp), 4) if tp + fp else None,
               recall=round(tp / (tp + fn), 4) if tp + fn else None,
               specificity=round(tn / (tn + fp), 4) if tn + fp else None,
               false_positive_rate=round(fp / (fp + tn), 4) if fp + tn else None,
               missed_event_rate=round(fn / (tp + fn), 4) if tp + fn else None)
    return out


def _candidates():
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    import xgboost as xgb

    def impute(Xtr):
        med = np.nanmedian(Xtr, axis=0)
        med = np.where(np.isnan(med), 0, med)

        def tf(X):
            miss = np.isnan(X)
            return np.hstack([np.where(miss, med, X), miss.astype("float32")])
        return tf

    def clim_fit(X, y):
        return lambda Z: Z[:, F.FEATURES.index("clim")]

    def logit_fit(X, y):
        tf = impute(X)
        Z = tf(X)
        mu, sd = Z.mean(0), Z.std(0) + 1e-6
        m = LogisticRegression(C=1.0, max_iter=400).fit((Z - mu) / sd, y)
        return lambda W: m.predict_proba((tf(W) - mu) / sd)[:, 1]

    def rf_fit(X, y):
        tf = impute(X)
        m = RandomForestClassifier(n_estimators=200, max_depth=14, min_samples_leaf=50, n_jobs=-1, random_state=RNG_SEED).fit(tf(X), y)
        return lambda W: m.predict_proba(tf(W))[:, 1]

    def hgb_fit(X, y):
        m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, max_leaf_nodes=63, random_state=RNG_SEED).fit(X, y)
        return lambda W: m.predict_proba(W)[:, 1]

    def xgb_fit(X, y):
        params = dict(objective="binary:logistic", tree_method="hist", max_depth=6, eta=0.08, subsample=0.8, colsample_bytree=0.8,
                      min_child_weight=20, max_bin=128, nthread=8, seed=RNG_SEED)
        b = xgb.train(params, xgb.QuantileDMatrix(X, label=y, max_bin=128), num_boost_round=300)
        return lambda W: b.inplace_predict(W)

    return {"climatology": clim_fit, "logistic": logit_fit, "random_forest": rf_fit, "hist_gradient_boosting": hgb_fit, "xgboost": xgb_fit}


def _split(dates, train_end, calib_end, test_end=None):
    end = dates + pd.Timedelta(days=F.H)
    seg = np.where(end <= pd.Timestamp(train_end), 0, np.where(end <= pd.Timestamp(calib_end), 1, 2))
    if test_end is not None:
        seg = np.where((seg == 2) & (end > pd.Timestamp(test_end)), 3, seg)
    return seg


def _run(Xf, y7, segf, known, models, log, label):
    from sklearn.isotonic import IsotonicRegression
    rng = np.random.default_rng(RNG_SEED)
    tr, ca, te = (np.where(known & (segf == k))[0] for k in (0, 1, 2))
    trs = np.sort(rng.choice(tr, size=min(len(tr), TRAIN_ROWS), replace=False))
    preds, timing = {}, {}
    for name, fit in models.items():
        t0 = time.time()
        f = fit(Xf[trs], y7[trs])
        rc = f(Xf[ca])
        okc = ~np.isnan(rc)
        iso = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(rc[okc], y7[ca][okc])
        rt = f(Xf[te])
        rt = np.where(np.isnan(rt), np.nanmean(rc), rt)
        preds[name] = iso.predict(rt)
        timing[name] = round(time.time() - t0, 1)
        log(f"[compare:{label}] {name} done in {timing[name]} s")
    return tr, ca, te, trs, preds, timing


def compare(log=print, rolling=True) -> dict:
    ds = F.build_dataset(log)
    X, Y, dates, ids = ds["X"], ds["Y"], ds["dates"], ds["cells"]
    I, C, Fn = X.shape
    Xf = X.reshape(I * C, Fn)
    y7 = Y[F.H - 1].reshape(-1)
    known = ~np.isnan(y7)
    models = _candidates()

    segf = np.repeat(_split(dates, F.TRAIN_END, F.CALIB_END), C)
    tr, ca, te, trs, preds, timing = _run(Xf, y7, segf, known, models, log, "main")
    yt = y7[te]
    cb = float(np.mean((preds["climatology"] - yt) ** 2))
    main = {k: metrics(yt, p, cb) for k, p in preds.items()}

    # breakdowns for every candidate (the UI shows the production model; others are in the file)
    cells = store.cells().loc[ids]
    di = np.repeat(np.arange(I), C)[te]
    ci = np.tile(np.arange(C), I)[te]
    mon = dates.month.to_numpy()[di]
    fv = {n: Xf[te, F.FEATURES.index(n)] for n in ("v30", "gap30")}
    groups = {
        "state": cells["state"].to_numpy()[ci],
        "month": mon.astype(str),
        "season": np.vectorize(SEASON.get)(mon),
        "land_use": cells["land_use"].fillna("unknown").to_numpy()[ci],
        "activity_last_30d": np.where(np.nan_to_num(fv["v30"]) == 0, "none", np.where(np.expm1(np.nan_to_num(fv["v30"])) <= 5, "1-5 detections", ">5 detections")),
        "observation_coverage": np.where(np.nan_to_num(fv["gap30"]) > 0, "S-NPP gap days in last 30", "complete last 30 days"),
    }
    breakdown = {}
    for g, lab in groups.items():
        breakdown[g] = {}
        for val in pd.unique(lab):
            m = lab == val
            breakdown[g][str(val)] = {k: metrics(yt[m], preds[k][m], float(np.mean((preds["climatology"][m] - yt[m]) ** 2)))
                                      for k in ("xgboost", "climatology")}
    rel = F._reliability(yt, preds["xgboost"])

    roll = []
    if rolling:
        for tr_end, ca_end, te_end in (("2018-12-31", "2020-12-31", "2021-12-31"), ("2019-12-31", "2021-12-31", "2022-12-31"),
                                       ("2020-12-31", "2022-12-31", "2023-12-31")):
            sg = np.repeat(_split(dates, tr_end, ca_end, te_end), C)
            _, _, te_r, _, pr, _ = _run(Xf, y7, sg, known, models, log, f"origin {tr_end[:4]}")
            yr = y7[te_r]
            cbr = float(np.mean((pr["climatology"] - yr) ** 2))
            roll.append({"train_until": tr_end, "calibrate_until": ca_end, "test_until": te_end,
                         "scores": {k: metrics(yr, p, cbr) for k, p in pr.items()}})

    best = min((k for k in main if k != "xgboost"), key=lambda k: main[k]["brier"])
    xb = main["xgboost"]
    wins = (main[best]["brier"] <= xb["brier"] * 0.98 and (main[best]["roc_auc"] or 0) >= (xb["roc_auc"] or 0) + 0.005
            and all(r["scores"][best]["brier"] <= r["scores"]["xgboost"]["brier"] for r in roll))
    split = {"train_until": F.TRAIN_END, "calibrate_until": F.CALIB_END, "test_from": str((pd.Timestamp(F.CALIB_END) + pd.Timedelta(days=1)).date())}
    trained = datetime.now(timezone.utc).isoformat()
    cards = {k: {**CARDS[k], "training_period": f"label windows ending <= {F.TRAIN_END}",
                 "calibration": f"isotonic regression on label windows ending {F.TRAIN_END[:4]}-12-31 < end <= {F.CALIB_END}",
                 "test_period": f"label windows ending after {F.CALIB_END}", "training_rows": int(len(trs)),
                 "feature_provenance": "FIRMS S-NPP VIIRS + MODIS detections (repository archives), NASA POWER daily weather, "
                                       "MCD12Q1 land cover; all windows end at the issue date",
                 "version": "compare-1", "trained_at": trained, "fit_seconds": timing[k], "metrics": main[k],
                 "limitations": ["Target is a detectable S-NPP hotspot within 7 days, not a verified ignition",
                                 "Cloud cover and data gaps hide fires; labels in gap weeks are dropped, not set to zero",
                                 "Temporal (not spatial) transfer is measured"]} for k in main}
    out = {"generated": trained, "target": "P(>= 1 S-NPP VIIRS 375 m presumed-vegetation detection in the 0.25 deg cell within 7 days)",
           "split": split, "rows": {"train_available": int(len(tr)), "train_used": int(len(trs)), "calibration": int(len(ca)), "test": int(len(te))},
           "equal_footing": f"Same {len(trs):,} training rows (seeded subsample), same calibration and test rows for every model",
           "selection_rule": SELECTION_RULE, "best_alternative": best, "alternative_wins": bool(wins),
           "production_model": "xgboost", "decision": (f"{best} meets the rule; consider switching" if wins else
                                                        f"XGBoost retained: {best} (best alternative) does not meet the rule"),
           "main": main, "rolling_origin": roll, "breakdown": breakdown, "reliability_xgboost": rel,
           "day_night": "Not applicable: the target counts day and night detections together within a 7-day window.",
           "model_cards": cards, "not_included": NOT_INCLUDED,
           "leakage_controls": __doc__.split("Leakage controls")[1].split("Spatial transfer")[0].strip()}
    OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    log(f"[compare] {out['decision']}")
    return out


def load() -> dict:
    return json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}


if __name__ == "__main__":
    r = compare()
    for k, v in r["main"].items():
        print(k, {m: v.get(m) for m in ("brier", "brier_skill", "roc_auc", "pr_auc", "ece", "precision", "recall")})
