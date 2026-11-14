"""Grid-cell 7-day probability of a detectable S-NPP VIIRS active-fire hotspot.

TARGET (what a probability means): P(at least one S-NPP VIIRS 375 m presumed-vegetation
detection in the 0.25 deg cell during the 7 days after the issue date). This is the
probability of *observing a satellite hotspot*, not of a ground-verified ignition.

Chronological design (no random split):  train <= 2021 | calibrate 2022-2023 | test >= 2024.
XGBoost scores are calibrated with isotonic regression fitted on the calibration years
only; all reported metrics come from the untouched test years.

Weeks whose target window overlaps an S-NPP data gap have an UNKNOWN label and are
dropped -- a missing observation is never used as a "no fire" example.
"""
from __future__ import annotations

import json
import pickle
from functools import lru_cache

import numpy as np
import pandas as pd

from . import grid, store, weather
from .config import FORECAST_HORIZON_DAYS, MODELS, PROCESSED, RNG_SEED, VIIRS_REFERENCE

H = FORECAST_HORIZON_DAYS
TRAIN_END, CALIB_END = "2021-12-31", "2023-12-31"
FC_PATH = PROCESSED / "forecast_cells.parquet"
CONTRIB_PATH = PROCESSED / "forecast_contrib.parquet"
META_PATH = MODELS / "forecast_meta.json"
MODEL_PATH = MODELS / "forecast_models.pkl"
N_ISSUES_KEPT = 16
ENSEMBLE = 5

FEATURE_LABELS = {
    "v7": "VIIRS detections, last 7 days", "v30": "VIIRS detections, last 30 days", "v90": "VIIRS detections, last 90 days",
    "act30": "Days with VIIRS detections, last 30", "since": "Days since last VIIRS detection", "m30": "MODIS detections, last 30 days",
    "frp30": "VIIRS FRP total, last 30 days", "nb7": "Neighbouring-cell VIIRS detections, last 7 days",
    "clim": "Seasonal recurrence (same weeks, earlier years)", "clim_n": "Years of history behind recurrence",
    "lag52": "Detected in same week last year", "doy_sin": "Season (sin day-of-year)", "doy_cos": "Season (cos day-of-year)",
    "lat": "Latitude", "lon": "Longitude", "lc_forest": "Forest fraction", "lc_savanna": "Savanna/woodland fraction",
    "lc_cropland": "Cropland fraction", "lc_urban": "Urban fraction", "static_share": "Static thermal source share",
    "t7": "Max temperature, 7-day mean", "t30": "Max temperature, 30-day mean", "p7": "Rainfall, last 7 days",
    "p30": "Rainfall, last 30 days", "p90": "Rainfall, last 90 days", "rh7": "Relative humidity, 7-day mean",
    "wind7": "Wind speed, 7-day mean", "soil7": "Surface soil wetness, 7-day mean", "gap30": "S-NPP data-gap days, last 30",
}
FEATURES = list(FEATURE_LABELS)
FACTOR_GROUPS = {
    "Recent satellite detections": ["v7", "v30", "v90", "act30", "since", "m30", "nb7"],
    "FRP trend": ["frp30"],
    "Historical seasonal recurrence": ["clim", "clim_n", "lag52", "doy_sin", "doy_cos"],
    "Temperature": ["t7", "t30"], "Rainfall deficit / dryness": ["p7", "p30", "p90", "soil7"],
    "Humidity": ["rh7"], "Wind": ["wind7"],
    "Vegetation & land cover": ["lc_forest", "lc_savanna", "lc_cropland", "lc_urban", "static_share", "lat", "lon"],
    "Observation coverage": ["gap30"],
}


def _dense(df, days, cell_pos, col):
    """Daily [D, C] float32 array for one column of the daily store."""
    out = np.zeros((len(days), len(cell_pos)), dtype="float32")
    di = ((df["acq_date"].to_numpy() - days[0].to_datetime64()) / np.timedelta64(1, "D")).astype(int)
    ci = cell_pos.reindex(df["cell_id"]).to_numpy()
    ok = ~np.isnan(ci) & (di >= 0) & (di < len(days))
    np.add.at(out, (di[ok], ci[ok].astype(int)), df[col].to_numpy(dtype="float32")[ok])
    return out


def _win(cs, idx, w):
    """Sum over the w days ending at each decision day (inclusive) from a cumulative array."""
    return cs[idx + 1] - cs[np.clip(idx + 1 - w, 0, None)]


def build_dataset(log=print):
    sp = store.spans()[VIIRS_REFERENCE]
    days = pd.date_range(sp["first"], sp["last"], freq="D")
    D = len(days)
    gap = np.isin(days.strftime("%Y-%m-%d"), sp["gap_days"])
    d = store.daily()
    cells = store.cells()
    v = d[d["satellite"] == VIIRS_REFERENCE].groupby(["acq_date", "cell_id"], observed=True).agg(n=("n_veg", "sum"), frp=("frp_sum", "sum")).reset_index()
    ids = np.array(sorted(set(v["cell_id"].unique()) & set(cells.index[cells["in_country"]])))
    cpos = pd.Series(np.arange(len(ids), dtype=float), index=ids)
    C = len(ids)
    last = D - 1
    # issue days anchored on the last data day; fortnightly in the training era, weekly afterwards
    idx_all = np.arange(last, 89, -7)[::-1]
    dates_all = days[idx_all]
    keep = (dates_all > pd.Timestamp(TRAIN_END) - pd.Timedelta(days=H)) | (np.arange(len(idx_all)) % 2 == (len(idx_all) - 1) % 2)
    idx, dates = idx_all[keep], dates_all[keep]
    I = len(idx)
    log(f"[forecast] cells={C} issue dates={I} rows={I * C:,}")
    X = np.full((I, C, len(FEATURES)), np.nan, dtype="float32")
    f = {n: k for k, n in enumerate(FEATURES)}

    V = _dense(v, days, cpos, "n")
    cs = np.vstack([np.zeros((1, C), "float32"), np.cumsum(V, 0, dtype="float32")])
    for w, nm in ((7, "v7"), (30, "v30"), (90, "v90")):
        X[:, :, f[nm]] = np.log1p(_win(cs, idx, w))
    # labels for horizons 1..H (NaN when the window is not fully observed)
    Y = np.full((H, I, C), np.nan, dtype="float32")
    gcs = np.concatenate([[0], np.cumsum(gap)])
    for h in range(1, H + 1):
        okw = (idx + h <= last)
        end = np.clip(idx + h, 0, last)
        ev = (cs[end + 1] - cs[idx + 1]) > 0
        gaps_in = gcs[end + 1] - gcs[idx + 1]
        Y[h - 1] = np.where((okw & (gaps_in == 0))[:, None], ev, np.nan)
    v7_raw = _win(cs, idx, 7)
    del cs
    act = (V > 0).astype("float32")
    cs = np.vstack([np.zeros((1, C), "float32"), np.cumsum(act, 0, dtype="float32")])
    X[:, :, f["act30"]] = _win(cs, idx, 30)
    del cs
    lastseen = np.where(act > 0, np.arange(D, dtype="float32")[:, None], -1.0)
    np.maximum.accumulate(lastseen, axis=0, out=lastseen)
    ls = lastseen[idx]
    X[:, :, f["since"]] = np.where(ls >= 0, np.minimum(idx[:, None] - ls, 400), np.nan)
    del lastseen, act, V
    Fp = _dense(v, days, cpos, "frp")
    cs = np.vstack([np.zeros((1, C), "float32"), np.cumsum(Fp, 0, dtype="float32")])
    X[:, :, f["frp30"]] = np.log1p(_win(cs, idx, 30))
    del cs, Fp, v
    m = d[d["satellite"].isin(["Terra", "Aqua"])].groupby(["acq_date", "cell_id"], observed=True).agg(n=("n_veg", "sum")).reset_index()
    Mo = _dense(m, days, cpos, "n")
    cs = np.vstack([np.zeros((1, C), "float32"), np.cumsum(Mo, 0, dtype="float32")])
    X[:, :, f["m30"]] = np.log1p(_win(cs, idx, 30))
    del cs, Mo, m

    # neighbours (8-connected) on the grid
    ix, iy = grid.cell_ixiy(ids)
    gx, gy = ix - ix.min() + 1, iy - iy.min() + 1
    img = np.zeros((I, gy.max() + 2, gx.max() + 2), "float32")
    img[:, gy, gx] = v7_raw
    nb = sum(np.roll(np.roll(img, a, 1), b, 2) for a in (-1, 0, 1) for b in (-1, 0, 1)) - img
    X[:, :, f["nb7"]] = np.log1p(nb[:, gy, gx])
    del img, nb

    # seasonal recurrence from EARLIER years only (expanding; no look-ahead)
    y7 = Y[H - 1]
    yr, bucket = dates.year.to_numpy(), ((dates.dayofyear.to_numpy() - 1) // 7)
    for i in range(I):
        prior = np.where((yr < yr[i]) & (np.minimum(np.abs(bucket - bucket[i]), 52 - np.abs(bucket - bucket[i])) <= 1))[0]
        if len(prior):
            with np.errstate(invalid="ignore"):
                X[i, :, f["clim"]] = np.nanmean(y7[prior], axis=0)
            X[i, :, f["clim_n"]] = len(np.unique(yr[prior]))
        lag = np.where(np.abs((dates[i] - dates).days - 364) <= 7)[0]
        if len(lag):
            X[i, :, f["lag52"]] = y7[lag[0]]
    doy = dates.dayofyear.to_numpy()
    X[:, :, f["doy_sin"]] = np.sin(2 * np.pi * doy / 365.25)[:, None]
    X[:, :, f["doy_cos"]] = np.cos(2 * np.pi * doy / 365.25)[:, None]
    cc = cells.loc[ids]
    X[:, :, f["lat"]], X[:, :, f["lon"]] = cc["lat"].to_numpy()[None], cc["lon"].to_numpy()[None]
    for nm in ("lc_forest", "lc_savanna", "lc_cropland", "lc_urban"):
        if nm in cc:
            X[:, :, f[nm]] = cc[nm].to_numpy()[None]
    X[:, :, f["static_share"]] = store.cell_static()["static_share"].reindex(ids).to_numpy(dtype="float32")[None]
    X[:, :, f["gap30"]] = (gcs[idx + 1] - gcs[np.clip(idx - 29, 0, None)])[:, None]

    has_weather = weather.WEATHER_PATH.exists()
    if has_weather:
        wx = pd.read_parquet(weather.WEATHER_PATH)
        nodes = np.array(sorted(wx["node"].unique()))
        npos = pd.Series(np.arange(len(nodes)), index=nodes)
        cnode = npos.reindex(weather.node_of(cc["lat"], cc["lon"])).to_numpy()
        okc = ~np.isnan(cnode)
        di = ((wx["date"].to_numpy() - days[0].to_datetime64()) / np.timedelta64(1, "D")).astype(int)
        okd = (di >= 0) & (di < D)
        ni = npos.reindex(wx["node"]).to_numpy()[okd]

        def wfeat(col, w, how):
            arr = np.full((D, len(nodes)), np.nan, "float32")
            arr[di[okd], ni] = wx[col].to_numpy()[okd]
            valid = ~np.isnan(arr)
            c1 = np.vstack([np.zeros((1, len(nodes))), np.cumsum(np.where(valid, arr, 0), 0)])
            c2 = np.vstack([np.zeros((1, len(nodes))), np.cumsum(valid, 0)])
            s_, n_ = _win(c1, idx, w), _win(c2, idx, w)
            out = np.where(n_ >= w * 0.7, s_ / np.maximum(n_, 1) * (w if how == "sum" else 1), np.nan)
            res = np.full((I, C), np.nan, "float32")
            res[:, okc] = out[:, cnode[okc].astype(int)]
            return res

        for nm, col, w, how in (("t7", "t2m_max", 7, "mean"), ("t30", "t2m_max", 30, "mean"), ("p7", "precip", 7, "sum"),
                                ("p30", "precip", 30, "sum"), ("p90", "precip", 90, "sum"), ("rh7", "rh", 7, "mean"),
                                ("wind7", "wind", 7, "mean"), ("soil7", "soil_wet", 7, "mean")):
            X[:, :, f[nm]] = wfeat(col, w, how)
        del wx
    return {"X": X, "Y": Y, "dates": dates, "cells": ids, "has_weather": has_weather}


def _clf_metrics(y, p, thresholds=(0.6, 0.8)):
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    out = {"n": int(len(y)), "base_rate": float(y.mean()), "brier": float(brier_score_loss(y, p)),
           "roc_auc": float(roc_auc_score(y, p)) if 0 < y.mean() < 1 else None,
           "pr_auc": float(average_precision_score(y, p)) if y.mean() > 0 else None, "confusion": {}}
    for t in thresholds:
        pred = p >= t
        tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
        fn, tn = int((~pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
        out["confusion"][f"{int(t * 100)}"] = {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "false_alarm_ratio": fp / (tp + fp) if tp + fp else None,   # share of alerts with no detection
            "false_alarm_rate": fp / (fp + tn) if fp + tn else None,    # share of quiet cell-weeks alerted
            "missed_event_rate": fn / (tp + fn) if tp + fn else None,
        }
    return out


def _reliability(y, p, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    b = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    return [{"bin_lo": float(edges[i]), "bin_hi": float(edges[i + 1]), "n": int((b == i).sum()),
             "mean_pred": float(p[b == i].mean()) if (b == i).any() else None,
             "observed": float(y[b == i].mean()) if (b == i).any() else None} for i in range(bins)]


def aggregate_region(p: np.ndarray, alpha: float) -> dict:
    """Regional summary from cell probabilities. Never a plain average.
    lower bound  = max cell probability (cells perfectly dependent)
    upper bound  = 1 - prod(1 - p_i)  (cells independent)
    central      = 1 - prod(1 - p_i) ** alpha, alpha in (0,1] fitted on calibration years to
                   account for spatial dependence between neighbouring cells."""
    p = np.clip(np.asarray(p, float), 0, 1 - 1e-9)
    p = p[~np.isnan(p)]
    if len(p) == 0:
        return {"n_cells": 0}
    s = np.log1p(-p).sum()
    top = np.sort(p)[::-1][: max(1, int(np.ceil(len(p) * 0.1)))]
    return {"n_cells": int(len(p)), "p_any": float(1 - np.exp(alpha * s)), "p_any_lower": float(p.max()),
            "p_any_upper": float(1 - np.exp(s)), "expected_cells_with_detection": float(p.sum()),
            "max_cell": float(p.max()), "p90_cell": float(np.percentile(p, 90)),
            "top_decile_any": float(1 - np.exp(alpha * np.log1p(-top).sum())), "alpha": float(alpha)}


def train(log=print) -> dict:
    import xgboost as xgb
    from sklearn.isotonic import IsotonicRegression

    ds = build_dataset(log)
    X, Y, dates, ids = ds["X"], ds["Y"], ds["dates"], ds["cells"]
    I, C, Fn = X.shape
    end = dates + pd.Timedelta(days=H)
    seg = np.where(end <= pd.Timestamp(TRAIN_END), 0, np.where(end <= pd.Timestamp(CALIB_END), 1, 2))
    Xf = X.reshape(I * C, Fn)
    segf = np.repeat(seg, C)
    yrf = np.repeat(dates.year.to_numpy(), C)
    params = dict(objective="binary:logistic", tree_method="hist", max_depth=6, eta=0.08, subsample=0.8,
                  colsample_bytree=0.8, min_child_weight=20, max_bin=128, nthread=8, eval_metric="logloss", seed=RNG_SEED)

    def fit_one(y, rows, rounds, p_extra=None):
        dm = xgb.QuantileDMatrix(Xf[rows], label=y[rows], feature_names=FEATURES, max_bin=128)
        return xgb.train({**params, **(p_extra or {})}, dm, num_boost_round=rounds)

    def raw(bst, rows):
        return bst.inplace_predict(Xf[rows])

    y7 = Y[H - 1].reshape(-1)
    known = ~np.isnan(y7)
    tr, ca, te = (np.where(known & (segf == k))[0] for k in (0, 1, 2))
    log(f"[forecast] rows train={len(tr):,} calib={len(ca):,} test={len(te):,} | base rate test={y7[te].mean():.3f}")
    bst = fit_one(y7, tr, 300)
    iso = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(raw(bst, ca), y7[ca])
    p_te_raw = raw(bst, te)
    p_te = iso.predict(p_te_raw)
    meta = {
        "target": f"At least one {VIIRS_REFERENCE} VIIRS 375 m presumed-vegetation detection in the 0.25 deg cell within {H} days of the issue date",
        "target_kind": "probability of a detectable satellite hotspot (NOT a verified ground ignition)",
        "trained_on": "NASA FIRMS S-NPP VIIRS detections (repository archive) + NASA POWER meteorology" if ds["has_weather"] else "NASA FIRMS detections only (weather layer unavailable)",
        "has_weather": ds["has_weather"], "features": FEATURES, "feature_labels": FEATURE_LABELS,
        "split": {"train_until": TRAIN_END, "calibrate_until": CALIB_END, "test_from": str((pd.Timestamp(CALIB_END) + pd.Timedelta(days=1)).date()),
                  "test_until": str(end[seg == 2].max().date()) if (seg == 2).any() else None},
        "rows": {"train": int(len(tr)), "calibration": int(len(ca)), "test": int(len(te))},
        "calibration_method": "Isotonic regression fitted on 2022-2023 predictions of the XGBoost model (prefit), applied before any threshold comparison",
        "test": _clf_metrics(y7[te], p_te), "test_uncalibrated": _clf_metrics(y7[te], p_te_raw),
        "reliability": _reliability(y7[te], p_te), "reliability_uncalibrated": _reliability(y7[te], p_te_raw),
    }
    # climatology-only baseline, calibrated the same way
    clim = Xf[:, FEATURES.index("clim")]
    okb = ~np.isnan(clim)
    if okb[ca].sum() > 100:
        iso_b = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(clim[ca][okb[ca]], y7[ca][okb[ca]])
        pb = iso_b.predict(np.nan_to_num(clim[te], nan=float(np.nanmean(clim[ca]))))
        meta["baseline_climatology"] = _clf_metrics(y7[te], pb)
        meta["brier_skill_vs_climatology"] = float(1 - meta["test"]["brier"] / meta["baseline_climatology"]["brier"])
    gain = bst.get_score(importance_type="total_gain")
    tot = sum(gain.values()) or 1
    meta["feature_importance"] = sorted(({"feature": k, "label": FEATURE_LABELS[k], "gain_share": v / tot} for k, v in gain.items()), key=lambda r: -r["gain_share"])
    cells_df = store.cells().loc[ids]
    lu = np.tile(cells_df["land_use"].to_numpy(), I)
    meta["test_by_land_use"] = {k: _clf_metrics(y7[te][lu[te] == k], p_te[lu[te] == k]) for k in pd.unique(lu[te]) if (lu[te] == k).sum() > 500 and 0 < y7[te][lu[te] == k].mean() < 1}

    # ensemble for model uncertainty: year-block bootstrap of the training years
    rng = np.random.default_rng(RNG_SEED)
    yrs = np.unique(yrf[tr])
    ens = []
    for k in range(ENSEMBLE):
        pick = rng.choice(yrs, len(yrs), replace=True)
        rows = np.concatenate([tr[yrf[tr] == y] for y in pick])
        rows = rng.choice(rows, size=min(len(rows), 600_000), replace=False)
        b = fit_one(y7, np.sort(rows), 140, {"seed": RNG_SEED + k + 1})
        ens.append((b, IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(raw(b, ca), y7[ca])))
        log(f"[forecast] ensemble member {k + 1}/{ENSEMBLE}")
    # cumulative-horizon models (probability of a detection within h days)
    hz = {}
    for h in range(1, H):
        yh = Y[h - 1].reshape(-1)
        kn = ~np.isnan(yh)
        trh, cah = np.where(kn & (segf == 0))[0], np.where(kn & (segf == 1))[0]
        trh = np.sort(rng.choice(trh, size=min(len(trh), 500_000), replace=False))
        b = fit_one(yh, trh, 120)
        hz[h] = (b, IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(raw(b, cah), yh[cah]))
    log("[forecast] horizon models done")

    # spatial-dependence exponent for regional aggregation, fitted on calibration-year districts
    pall = iso.predict(bst.inplace_predict(Xf)).reshape(I, C)
    dist = cells_df["district_id"].fillna("none").to_numpy()
    st = cells_df["state"].to_numpy()

    def regional(groups, issue_idx):
        rows = []
        for i in issue_idx:
            if np.isnan(Y[H - 1, i]).all():
                continue
            g = pd.DataFrame({"g": groups, "s": np.log1p(-np.clip(pall[i], 0, 1 - 1e-6)), "p": pall[i], "y": Y[H - 1, i]})
            a = g.groupby("g").agg(s=("s", "sum"), mx=("p", "max"), mean=("p", "mean"), y=("y", "max"), n=("p", "size"))
            rows.append(a[a.index != "none"])
        return pd.concat(rows)

    rc = regional(dist, np.where(seg == 1)[0])
    grid_a = np.linspace(0.05, 1, 96)
    ll = [-(rc["y"] * np.log(np.clip(1 - np.exp(a * rc["s"]), 1e-9, 1)) + (1 - rc["y"]) * (a * rc["s"])).mean() for a in grid_a]
    alpha = float(grid_a[int(np.argmin(ll))])
    agg_eval = {}
    for nm, groups in (("district", dist), ("state", st)):
        rt = regional(groups, np.where(seg == 2)[0])
        cand = {"alpha_adjusted (used)": 1 - np.exp(alpha * rt["s"]), "independent_cells": 1 - np.exp(rt["s"]),
                "max_cell": rt["mx"], "mean_of_cells (invalid, for contrast)": rt["mean"]}
        agg_eval[nm] = {"n": int(len(rt)), "event_rate": float(rt["y"].mean()),
                        "brier": {k: float(((v - rt["y"]) ** 2).mean()) for k, v in cand.items()}}
    meta["aggregation"] = {"alpha": alpha, "fitted_on": "district-weeks in 2022-2023",
                           "formula": "P(any detection in region) = 1 - prod(1 - p_cell) ** alpha", "test_brier": agg_eval}

    # store recent issues (with verification where the window has passed) + explanations for the latest
    keep = np.arange(max(0, I - N_ISSUES_KEPT), I)
    ep = np.stack([i_.predict(b_.inplace_predict(X[keep].reshape(-1, Fn))).reshape(len(keep), C) for b_, i_ in ens])
    hp = np.stack([i_.predict(b_.inplace_predict(X[keep].reshape(-1, Fn))).reshape(len(keep), C) for b_, i_ in hz.values()] + [pall[keep]])
    hp = np.maximum.accumulate(np.minimum(hp, pall[keep][None]), axis=0)   # monotone in horizon, capped by the 7-day value
    rows = []
    for j, i in enumerate(keep):
        r = pd.DataFrame({"issue_date": dates[i], "cell_id": ids, "p": pall[i], "p_lo": np.minimum(ep[:, j].min(0), pall[i]),
                          "p_hi": np.maximum(ep[:, j].max(0), pall[i]), "observed": Y[H - 1, i], "clim": X[i, :, FEATURES.index("clim")]})
        for h in range(1, H + 1):
            r[f"p_d{h}"] = hp[h - 1, j]
        for nm in ("v7", "v30", "since", "t7", "p30", "rh7", "wind7", "soil7", "gap30", "frp30"):
            r["f_" + nm] = X[i, :, FEATURES.index(nm)]
        rows.append(r)
    fc = pd.concat(rows, ignore_index=True)
    fc.to_parquet(FC_PATH, index=False)
    contrib = bst.predict(xgb.DMatrix(X[-1], feature_names=FEATURES), pred_contribs=True)
    cdf = pd.DataFrame(contrib[:, :-1], columns=FEATURES)
    cdf.insert(0, "cell_id", ids)
    cdf["bias"] = contrib[:, -1]
    cdf.to_parquet(CONTRIB_PATH, index=False)
    with open(MODEL_PATH, "wb") as fh:
        pickle.dump({"model": bst.save_raw("json"), "iso": iso}, fh)
    meta.update(issue_date=str(dates[-1].date()), issues_kept=[str(x.date()) for x in dates[keep]], n_cells=int(C),
                uncertainty_method=f"Range of {ENSEMBLE} calibrated models trained on year-block bootstraps of the training years (model spread, not a formal interval)",
                explanation_method="TreeSHAP contributions of the XGBoost model in log-odds, before calibration")
    META_PATH.write_text(json.dumps(meta, indent=1))
    clear()
    log(f"[forecast] test Brier={meta['test']['brier']:.4f} AUC={meta['test']['roc_auc']:.3f} alpha={alpha:.2f}")
    return meta


# --------------------------------------------------------------------------- serving
@lru_cache(maxsize=1)
def meta() -> dict:
    return json.loads(META_PATH.read_text()) if META_PATH.exists() else {}


@lru_cache(maxsize=1)
def cells_fc() -> pd.DataFrame:
    return pd.read_parquet(FC_PATH) if FC_PATH.exists() else pd.DataFrame()


@lru_cache(maxsize=1)
def contribs() -> pd.DataFrame:
    return pd.read_parquet(CONTRIB_PATH).set_index("cell_id") if CONTRIB_PATH.exists() else pd.DataFrame()


def available() -> bool:
    return bool(meta()) and FC_PATH.exists()


def issue(issue_date: str | None = None) -> pd.DataFrame:
    fc = cells_fc()
    if fc.empty:
        return fc
    d = pd.Timestamp(issue_date) if issue_date else fc["issue_date"].max()
    return fc[fc["issue_date"] == d]


def explain(cell_id: int) -> list:
    c = contribs()
    if c.empty or cell_id not in c.index:
        return []
    row = c.loc[cell_id]
    out = [{"group": g, "contribution": float(sum(row[f] for f in fs)),
            "features": sorted(({"feature": f, "label": FEATURE_LABELS[f], "contribution": float(row[f])} for f in fs), key=lambda r: -abs(r["contribution"]))}
           for g, fs in FACTOR_GROUPS.items()]
    return sorted(out, key=lambda r: -abs(r["contribution"]))


def clear():
    for fn in (meta, cells_fc, contribs):
        fn.cache_clear()


if __name__ == "__main__":
    train()
