"""VIIRS-to-VIIRS bridge calibration studies (successor platform -> reference platform scale).

Pairs studied (target -> reference):
    NOAA-20 -> Suomi NPP,  NOAA-21 -> Suomi NPP,  NOAA-21 -> NOAA-20

Same declared design and acceptance rule as the original NOAA-21 study (``noaa21.py``), applied
independently to every pair:
  * only standard-processing (archive) days on which BOTH satellites observed, presumed-vegetation detections;
  * operational period of the target only (pre-operational records scored separately, never trained on);
  * forward split (train early, test next 12 months) and backward split (train latest 12, test the 12 before);
  * candidates: identity, national day/night ratio, state x day/night ratio, state x season x day/night ratio;
  * adopt a candidate only if it beats identity AND the national ratio by >= 1 WAPE point on both splits, with
    |bias| <= 5 %, national band coverage >= 80 %, test >= 12 months and >= 10,000 reference detections.

The purpose is to link new operational observations to the historical reference scale for display, NOT to
manufacture continuity: the historical S-NPP-equivalent record is never modified, and a bridge that fails the
rule is reported as NOT CALIBRATED (the target stays an independent actual stream).
"""
from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd

from . import noaa21 as N
from . import store
from .config import PLATFORMS, PROCESSED

PAIRS = [("NOAA-20", "Suomi NPP"), ("NOAA-21", "Suomi NPP"), ("NOAA-21", "NOAA-20")]
OUT = PROCESSED / "bridge_calibrations.json"


def _matched(ref: str, tgt: str) -> pd.DataFrame:
    """noaa21._matched generalised to any VIIRS pair."""
    old = N.REF, N.TGT
    try:
        N.REF, N.TGT = ref, tgt
        return N._matched()
    finally:
        N.REF, N.TGT = old


def accept_strict(exps: list[dict]) -> tuple[str | None, str]:
    """The declared rule applied uniformly to EVERY candidate (incl. the national ratio): beat identity by >= 1 WAPE
    point (and the national ratio, for state-level candidates) on BOTH splits, |bias| <= 5 %, band coverage >= 80 %.
    noaa21._accept has a looser national-ratio fallback (first split only, no coverage check); bridges do not use it."""
    for e in exps:
        if e["test_months"] < 12 or e["test_reference_detections"] < 10000:
            return None, "insufficient independent test sample"
    fails = {}
    for cand in ("state_season_ratio", "state_ratio", "national_ratio"):
        why = []
        for e in exps:
            sc, c = e["state_month"], e["state_month"][cand]
            if c["wape_pct"] > sc["identity"]["wape_pct"] - 1:
                why.append(f"{e['design'].split(':')[0]}: WAPE {c['wape_pct']} not >= 1 point better than identity {sc['identity']['wape_pct']}")
            if cand != "national_ratio" and c["wape_pct"] > sc["national_ratio"]["wape_pct"] - 1:
                why.append(f"{e['design'].split(':')[0]}: not >= 1 point better than national ratio")
            if abs(c["bias_pct"]) > 5:
                why.append(f"{e['design'].split(':')[0]}: |bias| {abs(c['bias_pct'])} > 5")
            if e["band_coverage_pct"][cand] < 80:
                why.append(f"{e['design'].split(':')[0]}: band coverage {e['band_coverage_pct'][cand]} % < 80 %")
        if not why:
            return cand, f"{cand} meets every declared criterion on both splits"
        fails[cand] = why
    return None, "no candidate met the declared criteria: " + " | ".join(f"{k}: {'; '.join(v[:3])}" for k, v in fails.items())


def study_pair(tgt: str, ref: str) -> dict:
    g = _matched(ref, tgt)
    if g.empty:
        return {"target": tgt, "reference": ref, "status": "unavailable", "reason": f"{ref} or {tgt} not loaded"}
    op_start = pd.Timestamp(PLATFORMS.get(tgt, {}).get("firms_start", g["acq_date"].min()))
    op = g["acq_date"] >= op_start
    gop = g[op]
    months = gop["month"].nunique()
    if months < 24:
        return {"target": tgt, "reference": ref, "status": "insufficient_overlap", "overlap_months": int(months),
                "reason": "Fewer than 24 operational overlap months: two independent 12-month tests are impossible."}
    last = gop["acq_date"].max()
    # forward: test the 12 months that end 12 months before the last overlap day, train on everything earlier
    test_end = last - pd.DateOffset(months=12)
    train_end = test_end - pd.DateOffset(months=12)
    fwd = N._experiment(g, op & (g["acq_date"] <= train_end), op & (g["acq_date"] > train_end) & (g["acq_date"] <= test_end),
                        "forward: train early operational overlap, test next 12 months")
    rev_split = last - pd.DateOffset(months=12)
    rev = N._experiment(g, op & (g["acq_date"] > rev_split), op & (g["acq_date"] <= rev_split) & (g["acq_date"] > rev_split - pd.DateOffset(months=12)),
                        "backward: train latest 12 months, test the 12 months before")
    chosen, reason = accept_strict([fwd, rev])
    ratio = gop.groupby("daynight")[["y", "x"]].sum()
    raw_step = {k: round(float(v.y / max(v.x, 1)), 4) for k, v in ratio.iterrows()}
    return {"target": tgt, "reference": ref, "status": "calibrated" if chosen else "not_calibrated", "selected": chosen,
            "selection_reason": reason, "matched_days": int(g["acq_date"].nunique()), "overlap_months": int(months),
            "overlap": [str(gop["acq_date"].min().date()), str(last.date())], "operational_start": str(op_start.date()),
            "reference_per_target_ratio": raw_step, "experiments": [fwd, rev], "criteria": accept_strict.__doc__.strip()}


@lru_cache(maxsize=1)
def studies() -> dict:
    out = {"pairs": [study_pair(t, r) for t, r in PAIRS],
           "principle": "Bridges link operational successors to the historical reference scale for comparison only. The historical "
                        "S-NPP-equivalent record is never altered; failed bridges leave the successor as an independent actual stream."}
    try:
        OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    except OSError:
        pass
    return out


def status(tgt: str, ref: str) -> dict:
    for p in studies()["pairs"]:
        if p["target"] == tgt and p["reference"] == ref:
            return p
    return {"target": tgt, "reference": ref, "status": "not_studied"}


def clear():
    studies.cache_clear()


if __name__ == "__main__":
    print(json.dumps(studies(), indent=1, default=str)[:4000])
