"""NOAA-21 cross-calibration study (VIIRS 375 m -> Suomi NPP VIIRS 375 m equivalent).

Why not Aqua -> NOAA-21: every Aqua/NOAA-21 overlap month falls in Aqua's orbit-drift years (2023+), so the
MODIS pathway cannot be calibrated without confounding sensor and overpass-time change.

Candidate reference: Suomi NPP (the harmonized record's VIIRS reference). Both are the same instrument design and
product (VIIRS C2 375 m active fire) in the same afternoon orbit plane, ~25-50 min apart. Only standard-processing
(archive) days on which *both* satellites have data are compared, and only presumed-vegetation detections.

Design (declared before looking at results):
  * operational period only: NOAA-21 >= 2024-01-17 (official FIRMS start). Pre-operational 2023 records are scored
    separately, never used for training;
  * train on operational months up to TRAIN_END, test on the following 12 months (full seasonal cycle); also the
    reverse split, to check temporal stability;
  * candidates: identity (no correction), national day/night ratio, state x day/night ratio shrunk to national,
    state x season x day/night ratio shrunk to state;
  * scored on state-month totals: WAPE, bias, R^2; national monthly band from a 200-replicate month-block bootstrap;
  * acceptance: a candidate is adopted only if it beats BOTH identity and the national ratio by >= 1 WAPE point on
    both splits, with |bias| <= 5 % and band coverage >= 80 %, and the test has >= 12 months and >= 10,000
    reference detections. Otherwise NOAA-21 stays a separate actual stream.
"""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
import pandas as pd

from . import store
from .config import PROCESSED

REF, TGT = "Suomi NPP", "NOAA-21"
OPERATIONAL_START = pd.Timestamp("2024-01-17")
TRAIN_END = pd.Timestamp("2025-07-31")
K_STATE, K_SEASON = 200.0, 400.0
BOOT, SEED = 200, 20261114
OUT = PROCESSED / "noaa21_calibration.json"
SEASON = {12: "winter", 1: "winter", 2: "winter", 3: "pre-monsoon", 4: "pre-monsoon", 5: "pre-monsoon",
          6: "monsoon", 7: "monsoon", 8: "monsoon", 9: "monsoon", 10: "post-monsoon", 11: "post-monsoon"}


def _matched() -> pd.DataFrame:
    """Daily state x day/night counts for both satellites on days both observed (archive only)."""
    sp = store.spans()
    if REF not in sp or TGT not in sp:
        return pd.DataFrame()
    first = max(sp[REF]["first"], sp[TGT]["first"])
    last = min(sp[REF]["last_typed"], sp[TGT]["last_typed"])
    gaps = set(sp[REF]["gap_days"]) | set(sp[TGT]["gap_days"])
    d = store.daily()
    d = d[d["satellite"].isin([REF, TGT]) & (d["acq_date"] >= first) & (d["acq_date"] <= last)]
    d = d[~d["acq_date"].dt.strftime("%Y-%m-%d").isin(gaps)]
    st = store.cells()["state"]
    d = d.assign(state=st.reindex(d["cell_id"]).to_numpy(), daynight=d["daynight"].astype(str))
    d = d[d["daynight"].isin(["D", "N"])]
    g = d.groupby(["acq_date", "state", "daynight", "satellite"], observed=True)["n_veg"].sum().unstack("satellite", fill_value=0)
    # a day counts only if both satellites recorded at least one detection anywhere that day (both observing)
    both = g.groupby(level="acq_date").sum()
    keep = both[(both.get(REF, 0) > 0) & (both.get(TGT, 0) > 0)].index
    g = g[g.index.get_level_values("acq_date").isin(keep)].reset_index()
    g = g.rename(columns={REF: "y", TGT: "x"})
    g["month"] = g["acq_date"].dt.to_period("M")
    g["season"] = g["acq_date"].dt.month.map(SEASON)
    return g


def _fit(tr: pd.DataFrame) -> dict:
    nat = tr.groupby("daynight")[["y", "x"]].sum()
    r_nat = (nat["y"] / nat["x"].clip(lower=1)).to_dict()
    s = tr.groupby(["state", "daynight"])[["y", "x"]].sum()
    r_state = {k: (v.y + K_STATE * r_nat[k[1]]) / (v.x + K_STATE) for k, v in s.iterrows()}
    ss = tr.groupby(["state", "season", "daynight"])[["y", "x"]].sum()
    r_season = {k: (v.y + K_SEASON * r_state.get((k[0], k[2]), r_nat[k[2]])) / (v.x + K_SEASON) for k, v in ss.iterrows()}
    return {"national": r_nat, "state": r_state, "state_season": r_season}


def _predict(f: dict, te: pd.DataFrame) -> dict:
    x = te["x"].to_numpy(float)
    dn = te["daynight"].to_numpy()
    rn = np.array([f["national"].get(k, 1.0) for k in dn])
    rs = np.array([f["state"].get((s, k), f["national"].get(k, 1.0)) for s, k in zip(te["state"], dn)])
    rss = np.array([f["state_season"].get((s, se, k), f["state"].get((s, k), f["national"].get(k, 1.0)))
                    for s, se, k in zip(te["state"], te["season"], dn)])
    return {"identity": x, "national_ratio": rn * x, "state_ratio": rs * x, "state_season_ratio": rss * x}


def _score(y: np.ndarray, p: np.ndarray) -> dict:
    tot = y.sum()
    ss = ((y - y.mean()) ** 2).sum()
    return {"wape_pct": round(float(np.abs(p - y).sum() / tot * 100), 2) if tot else None,
            "bias_pct": round(float((p.sum() - tot) / tot * 100), 2) if tot else None,
            "r2": round(float(1 - ((y - p) ** 2).sum() / ss), 3) if ss else None,
            "mae": round(float(np.abs(p - y).mean()), 2), "rmse": round(float(np.sqrt(((p - y) ** 2).mean())), 2)}


def _experiment(g: pd.DataFrame, tr_mask, te_mask, label: str) -> dict:
    tr, te = g[tr_mask], g[te_mask]
    f = _fit(tr)
    preds = _predict(f, te)
    sm = te[["state", "month"]].copy()
    sm["y"] = te["y"].to_numpy()
    scores, nat_scores = {}, {}
    for name, p in preds.items():
        sm["p"] = p
        a = sm.groupby(["state", "month"])[["y", "p"]].sum()
        scores[name] = _score(a["y"].to_numpy(float), a["p"].to_numpy(float))
        n = sm.groupby("month")[["y", "p"]].sum()
        nat_scores[name] = _score(n["y"].to_numpy(float), n["p"].to_numpy(float))
    # month-block bootstrap of the training months -> national monthly band for every candidate fit
    rng = np.random.default_rng(SEED)
    months = tr["month"].unique()
    bymonth = {m: tr[tr["month"] == m] for m in months}
    nat_y = te.groupby("month")["y"].sum()
    cover = {}
    reps = {k: [] for k in preds if k != "identity"}
    for _ in range(BOOT):
        bt = pd.concat([bymonth[m] for m in rng.choice(months, len(months), replace=True)])
        fb = _predict(_fit(bt), te)
        for k in reps:
            reps[k].append(pd.Series(fb[k], index=te.index).groupby(te["month"]).sum().reindex(nat_y.index).to_numpy())
    for k, r in reps.items():
        r = np.array(r)
        lo, hi = np.percentile(r, 5, axis=0), np.percentile(r, 95, axis=0)
        cover[k] = round(float(np.mean((nat_y.to_numpy() >= lo) & (nat_y.to_numpy() <= hi)) * 100), 1)
    by_dn = {}
    for dn in ("D", "N"):
        m = (te["daynight"] == dn).to_numpy()
        if m.sum():
            by_dn[dn] = {k: _score(te["y"].to_numpy(float)[m], v[m])["bias_pct"] for k, v in preds.items()}
    return {"design": label, "train": [str(tr["month"].min()), str(tr["month"].max())],
            "test": [str(te["month"].min()), str(te["month"].max())], "test_months": int(te["month"].nunique()),
            "test_reference_detections": int(te["y"].sum()), "train_reference_detections": int(tr["y"].sum()),
            "state_month": scores, "national_month": nat_scores, "band_coverage_pct": cover,
            "bias_by_daynight_pct": by_dn,
            "coefficients": {"national": {k: round(v, 4) for k, v in f["national"].items()}}}


def _accept(exps: list[dict]) -> tuple[str | None, str]:
    for cand in ("state_season_ratio", "state_ratio"):
        okall = True
        for e in exps:
            sc = e["state_month"]
            if e["test_months"] < 12 or e["test_reference_detections"] < 10000:
                return None, "insufficient independent test sample"
            c = sc[cand]
            if not (c["wape_pct"] <= sc["identity"]["wape_pct"] - 1 and c["wape_pct"] <= sc["national_ratio"]["wape_pct"] - 1
                    and abs(c["bias_pct"]) <= 5 and e["band_coverage_pct"][cand] >= 80):
                okall = False
        if okall:
            return cand, f"{cand} beats identity and the national ratio by >= 1 WAPE point on both splits, |bias| <= 5 %, coverage >= 80 %"
    sc = exps[0]["state_month"]
    if abs(sc["national_ratio"]["bias_pct"]) <= 5 and sc["national_ratio"]["wape_pct"] <= sc["identity"]["wape_pct"] - 1:
        return "national_ratio", "state detail did not earn its keep; the national day/night ratio beats identity"
    return None, "no candidate met the declared criteria"


@lru_cache(maxsize=1)
def study() -> dict:
    g = _matched()
    if g.empty:
        return {"status": "unavailable", "reason": f"{REF} or {TGT} not loaded"}
    op = g["acq_date"] >= OPERATIONAL_START
    test_end = TRAIN_END + pd.DateOffset(months=12)
    fwd = _experiment(g, op & (g["acq_date"] <= TRAIN_END), op & (g["acq_date"] > TRAIN_END) & (g["acq_date"] <= test_end),
                      "forward: train early operational, test next 12 months")
    rev_split = g.loc[op, "acq_date"].max() - pd.DateOffset(months=12)
    rev = _experiment(g, op & (g["acq_date"] > rev_split), op & (g["acq_date"] <= rev_split) & (g["acq_date"] > rev_split - pd.DateOffset(months=12)),
                      "backward: train latest 12 months, test the 12 months before")
    pre = g[~op]
    pre_res = None
    if len(pre):
        f = _fit(g[op])
        p = _predict(f, pre)
        a = pre.assign(**{k: v for k, v in p.items()}).groupby("month")[["y", *p.keys()]].sum()
        pre_res = {"months": [str(pre["month"].min()), str(pre["month"].max())],
                   "reference_detections": int(pre["y"].sum()),
                   "national_month": {k: _score(a["y"].to_numpy(float), a[k].to_numpy(float)) for k in p},
                   "note": "Pre-operational NOAA-21 records scored with coefficients fitted on operational data only."}
    chosen, reason = _accept([fwd, rev])
    ratio_all = g[op].groupby("daynight")[["y", "x"]].sum()
    out = {"status": "calibrated" if chosen else "not_calibrated", "reference": REF, "target": TGT,
           "selected": chosen, "selection_reason": reason,
           "matched_days": int(g["acq_date"].nunique()), "operational_start": str(OPERATIONAL_START.date()),
           "overall_ratio_operational": {k: round(float(v.y / max(v.x, 1)), 4) for k, v in ratio_all.iterrows()},
           "experiments": [fwd, rev], "pre_operational_check": pre_res,
           "why_not_aqua": "All Aqua/NOAA-21 overlap is in Aqua orbit-drift years (2023+): sensor and overpass-time effects are confounded.",
           "scope": "VIIRS-to-VIIRS (NOAA-21 -> S-NPP-equivalent). This lets NOAA-21 stand in for S-NPP; it is not a MODIS calibration.",
           "criteria": "adopt only if better than identity AND national ratio by >= 1 WAPE point on both splits, |bias| <= 5 %, "
                       "national band coverage >= 80 %, test >= 12 months and >= 10,000 reference detections"}
    try:
        OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8", newline="\n")
    except OSError:
        pass
    return out


if __name__ == "__main__":
    print(json.dumps(study(), indent=1, default=str))
