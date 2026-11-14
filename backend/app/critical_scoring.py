"""Transparent, versioned critical-region (district) prioritisation.

This is a deterministic decision-support ranking, NOT a ground-truth risk score and NOT a learned model:
there is no independent ground truth of "which districts needed attention" to learn from.

Components (each normalised to [0, 1] before weighting):
  forecast         highest calibrated 7-day hotspot probability among the district's cells (already a probability)
  recent           30-day detections per cell, percentile rank across districts (ranks stop one huge count dominating)
  recurrence       historical seasonal recurrence (share of earlier years with a detection in these weeks)
  frp              mean FRP per detection, percentile rank (only where >= 5 detections)
  anomaly          seasonal anomaly z-score (robust, leave-one-year-out), mapped by clip(z, 0, 3) / 3
  population       people in the district's cells, percentile rank (WorldPop layer)        -- exposure, not hazard
  infrastructure   km of major road / railway / power line + mapped facilities, percentile -- exposure, not hazard
  land_cover       forest + savanna/woodland share (fuel context)
  observation_gap  share of the last 30 days the target sensor did not observe (uncertain picture -> monitor more)
  uncertainty      mean width of the model-spread band (wider -> monitor more)

Missing inputs are NEVER zero: a component that is unavailable for a district is dropped and the remaining weights
are renormalised for that district; the item lists its missing components. Population proximity is exposure: it
raises monitoring priority, it does not raise any fire probability.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .config import PROCESSED

CUSTOM = PROCESSED / "critical_weights.json"
COMPONENTS = ["forecast", "recent", "recurrence", "frp", "anomaly", "population", "infrastructure", "land_cover", "observation_gap", "uncertainty"]
HAZARD = {"forecast", "recent", "recurrence", "frp", "anomaly", "land_cover"}
EXPOSURE = {"population", "infrastructure"}
PROFILES = {
    "v2-balanced": {"forecast": 0.25, "recent": 0.15, "recurrence": 0.10, "frp": 0.08, "anomaly": 0.07, "population": 0.12,
                    "infrastructure": 0.08, "land_cover": 0.07, "observation_gap": 0.05, "uncertainty": 0.03},
    "hazard-led": {"forecast": 0.35, "recent": 0.20, "recurrence": 0.15, "frp": 0.10, "anomaly": 0.10, "land_cover": 0.05,
                   "observation_gap": 0.03, "uncertainty": 0.02},
    "exposure-led": {"forecast": 0.20, "recent": 0.10, "recurrence": 0.05, "frp": 0.05, "anomaly": 0.05, "population": 0.25,
                     "infrastructure": 0.20, "land_cover": 0.05, "observation_gap": 0.03, "uncertainty": 0.02},
    "v1-legacy": {"forecast": 0.30, "recent": 0.20, "recurrence": 0.15, "frp": 0.10, "observation_gap": 0.10, "land_cover": 0.10},
}
DEFAULT_PROFILE = "v2-balanced"
LABELS = {"forecast": "calibrated 7-day hotspot probability", "recent": "recent 30-day detections", "recurrence": "historical seasonal recurrence",
          "frp": "high fire radiative power", "anomaly": "above-normal activity for the season", "population": "population exposure",
          "infrastructure": "infrastructure exposure (roads, rail, power, facilities)", "land_cover": "forest / woodland fuel context",
          "observation_gap": "recent observation gaps (uncertain picture)", "uncertainty": "wide model uncertainty"}


def pct(s: pd.Series) -> pd.Series:
    """Percentile rank in [0, 1]; NaN stays NaN (missing, not zero)."""
    return s.rank(pct=True)


def active_weights() -> dict:
    if CUSTOM.exists():
        c = json.loads(CUSTOM.read_text())
        return {"profile": "custom", "version": c["version"], "weights": c["weights"], "set_by": c.get("set_by"), "set_at": c.get("set_at")}
    return {"profile": DEFAULT_PROFILE, "version": DEFAULT_PROFILE, "weights": PROFILES[DEFAULT_PROFILE]}


def set_weights(weights: dict, actor: str, note: str = "") -> dict:
    bad = set(weights) - set(COMPONENTS)
    if bad:
        raise ValueError(f"unknown components {sorted(bad)}; allowed {COMPONENTS}")
    if any((not isinstance(v, (int, float))) or v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError("weights must be non-negative numbers with a positive sum")
    tot = sum(weights.values())
    prev = json.loads(CUSTOM.read_text())["version"] if CUSTOM.exists() else None
    n = int(prev.split("-")[-1]) + 1 if prev and prev.startswith("custom-") else 1
    rec = {"version": f"custom-{n}", "weights": {k: round(v / tot, 6) for k, v in weights.items() if v > 0}, "set_by": actor,
           "set_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": note[:300], "previous": prev}
    CUSTOM.write_text(json.dumps(rec, indent=1))
    return rec


def reset_weights():
    CUSTOM.unlink(missing_ok=True)


def normalise(r: pd.DataFrame) -> pd.DataFrame:
    """District table -> component matrix in [0, 1] (NaN = unavailable)."""
    comp = pd.DataFrame(index=r.index)
    comp["forecast"] = r["max_cell_p"].clip(0, 1)
    comp["recent"] = pct(r["recent30"] / r["n_cells"])
    comp["recurrence"] = r["recurrence"].clip(0, 1)
    comp["frp"] = pct((r["frp30"] / r["recent30"].clip(lower=1)).where(r["recent30"] >= 5))
    comp["anomaly"] = (r["anomaly_z"].clip(0, 3) / 3) if "anomaly_z" in r else np.nan
    comp["population"] = pct(r["population"]) if "population" in r else np.nan
    comp["infrastructure"] = pct(r["infrastructure"]) if "infrastructure" in r else np.nan
    comp["land_cover"] = r["forest"].clip(0, 1)
    comp["observation_gap"] = (r["gap30"] / 30).clip(0, 1)
    comp["uncertainty"] = pct(r["band"])
    return comp[COMPONENTS]


def score(comp: pd.DataFrame, weights: dict) -> tuple[pd.Series, pd.DataFrame, pd.Series]:
    """Weighted mean of AVAILABLE components per row (weights renormalised over what is present).
    Returns (score, per-component contribution, available weight share)."""
    w = pd.Series({k: weights.get(k, 0.0) for k in COMPONENTS})
    present = comp.notna() & (w > 0)
    wm = present.mul(w, axis=1)
    denom = wm.sum(axis=1).replace(0, np.nan)
    contrib = comp.fillna(0).mul(wm).div(denom, axis=0)
    return contrib.sum(axis=1), contrib, denom / w.sum()


def priority_band(s: pd.Series) -> pd.Series:
    return pd.cut(s.rank(pct=True), [0, 0.5, 0.8, 0.95, 1.0], labels=["Routine", "Elevated", "High", "Critical"]).astype(str)


def sensitivity(comp: pd.DataFrame, base_weights: dict, top: int = 20) -> dict:
    """How stable is the ranking? Profile alternatives and +/-20 % single-weight perturbations."""
    base, _, _ = score(comp, base_weights)
    base_top = set(base.nlargest(top).index)
    out = {"top_n": top, "profiles": {}, "perturbations": []}
    for name, wts in PROFILES.items():
        s, _, _ = score(comp, wts)
        out["profiles"][name] = {"spearman_vs_active": round(float(base.corr(s, method="spearman")), 4),
                                 "top_overlap": round(len(base_top & set(s.nlargest(top).index)) / top, 3)}
    for k, v in base_weights.items():
        for f in (0.8, 1.2):
            w2 = {**base_weights, k: v * f}
            s, _, _ = score(comp, w2)
            out["perturbations"].append({"component": k, "factor": f, "top_overlap": round(len(base_top & set(s.nlargest(top).index)) / top, 3),
                                         "spearman": round(float(base.corr(s, method="spearman")), 4)})
    po = [p["top_overlap"] for p in out["perturbations"]]
    out["min_top_overlap_under_20pct_perturbation"] = min(po) if po else None
    return out


def evaluate_against_history(tables: list[tuple[str, pd.DataFrame]], top: int = 20) -> dict:
    """For past forecast issues whose 7-day outcome is known: does each profile put districts that then had
    detections near the top? Measures HAZARD alignment only -- exposure components are not meant to predict fires,
    so exposure-led profiles are expected to score lower here; that is not a defect."""
    res = {k: {"spearman": [], "top_hit_rate": []} for k in PROFILES}
    for _, r in tables:
        if "observed_cells" not in r or r["observed_cells"].isna().all():
            continue
        comp = normalise(r)
        y = r["observed_cells"] / r["n_cells"]
        for name, wts in PROFILES.items():
            s, _, _ = score(comp, wts)
            ok = y.notna()
            res[name]["spearman"].append(float(s[ok].corr(y[ok], method="spearman")))
            t = s[ok].nlargest(top).index
            res[name]["top_hit_rate"].append(float((r.loc[t, "observed_cells"] > 0).mean()))
    return {k: {"issues": len(v["spearman"]), "mean_spearman": round(float(np.mean(v["spearman"])), 4) if v["spearman"] else None,
                "mean_top_hit_rate": round(float(np.mean(v["top_hit_rate"])), 4) if v["top_hit_rate"] else None} for k, v in res.items()}
