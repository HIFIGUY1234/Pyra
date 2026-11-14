"""Regional forecast views: grid cells, statistically aggregated summaries, timelines."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import alerts, forecast, grid, store
from .analytics import _f, _rec

MEANING = ("Based on the model and available information, there is an estimated {p:.0f}% probability of at least one detectable "
           "{sensor} VIIRS 375 m active-fire hotspot in {where} during the seven days after {d}. The model is trained on NASA FIRMS "
           "{sensor} detections, so this is the probability of observing a hotspot from that satellite, not of a verified ground fire.")


def reference_block(m: dict | None = None) -> dict:
    """Reference platform metadata attached to every forecast output."""
    m = m or forecast.meta()
    return {"reference_sensor": m.get("reference_sensor"), "product": m.get("product"), "model_version": m.get("model_version"),
            "trained_at": m.get("trained_at"), "target": m.get("target"), "serving_status": m.get("serving_status")}


def _cells(region_id: str, issue_date: str | None = None) -> pd.DataFrame:
    fc = forecast.issue(issue_date)
    if fc.empty:
        return fc
    ids = np.array(store.region_cells(region_id))
    df = fc[fc["cell_id"].isin(ids)].merge(store.cells()[["lat", "lon", "state", "district", "district_id", "land_use"]], left_on="cell_id", right_index=True)
    cfgs = alerts.get_configs()
    df["tier"] = [alerts.tier_name(p, alerts.resolve_config(st, lu, cfgs)) for p, st, lu in zip(df["p"], df["state"], df["land_use"])]
    return df


def region_forecast(region_id: str, issue_date: str | None = None) -> dict:
    if not forecast.available():
        return {"status": "unavailable", "mode": "none",
                "message": "No trained forecast model is available. PyroScope does not show placeholder or random risk values."}
    m = forecast.meta()
    df = _cells(region_id, issue_date)
    n_region = len(store.region_cells(region_id))
    if df.empty:
        return {"status": "no_cells", "region": store.region_label(region_id), "n_region_cells": n_region,
                "message": f"None of this area's grid cells has a forecast (no {m.get('reference_sensor')} detection history inside the mapped country cells).",
                "reference": reference_block(m)}
    alpha = m["aggregation"]["alpha"]
    agg = forecast.aggregate_region(df["p"].to_numpy(), alpha)
    lo = forecast.aggregate_region(df["p_lo"].to_numpy(), alpha)["p_any"]
    hi = forecast.aggregate_region(df["p_hi"].to_numpy(), alpha)["p_any"]
    top = df.loc[df["p"].idxmax()]
    cfg = alerts.resolve_config(top["state"], top["land_use"])
    tier = alerts.TIERS[max(alerts.TIERS.index(t) for t in df["tier"])]
    idate = pd.Timestamp(df["issue_date"].iloc[0])
    timeline = [{"day": h, "date": str((idate + pd.Timedelta(days=h)).date()),
                 "p_any_by_day": forecast.aggregate_region(df[f"p_d{h}"].to_numpy(), alpha)["p_any"], "max_cell_by_day": _f(df[f"p_d{h}"].max())} for h in range(1, 8)]
    # contributing factors: mean TreeSHAP of the cells at or above WATCH (or all cells if none)
    factors = []
    if str(idate.date()) == m["issue_date"]:
        cb = forecast.contribs()
        sel = df.loc[df["p"] >= cfg["watch"], "cell_id"] if (df["p"] >= cfg["watch"]).any() else df["cell_id"]
        sel = [c for c in sel if c in cb.index]
        if sel:
            mean = cb.loc[sel].mean()
            factors = sorted(({"group": g, "contribution": float(mean[fs].sum())} for g, fs in forecast.FACTOR_GROUPS.items()), key=lambda r: -abs(r["contribution"]))
    hist = []
    allfc = forecast.cells_fc()
    sub = allfc[allfc["cell_id"].isin(df["cell_id"])]
    for d_, g in sub.groupby("issue_date"):
        known = g["observed"].notna()
        hist.append({"issue_date": str(pd.Timestamp(d_).date()), "p_any": forecast.aggregate_region(g["p"].to_numpy(), alpha)["p_any"], "max_cell": _f(g["p"].max()),
                     "expected_cells": _f(g["p"].sum()), "observed_cells": _f(g.loc[known, "observed"].sum()) if known.any() else None,
                     "observed_any": bool(g.loc[known, "observed"].max() > 0) if known.any() else None})
    w = lambda c: _f(df[c].mean()) if df[c].notna().any() else None
    gap = w("f_gap30") or 0.0
    where = store.region_label(region_id)
    return {
        "status": "ok", "mode": "trained", "region": where, "region_id": region_id, "issue_date": str(idate.date()),
        "prediction_period": {"from": str((idate + pd.Timedelta(days=1)).date()), "to": str((idate + pd.Timedelta(days=7)).date())},
        "n_cells": int(len(df)), "n_region_cells": n_region, "regional": {**agg, "p_any_model_lo": lo, "p_any_model_hi": hi},
        "headline_probability": agg["p_any"] if len(df) > 1 else float(top["p"]), "max_cell_probability": float(top["p"]),
        "risk_category": tier, "suggested_action": alerts.ACTIONS[tier],
        "tier_basis": "Risk category is set by the highest calibrated grid-cell probability in the area, compared with the thresholds applying to that cell's state / land use.",
        "meaning": MEANING.format(p=(agg["p_any"] if len(df) > 1 else float(top["p"])) * 100, where=where, d=idate.date(), sensor=m.get("reference_sensor")),
        "reference": reference_block(m),
        "aggregation_note": "Regional probability = 1 - prod(1 - p_cell)^alpha with alpha = %.2f fitted on %s; bounds are the "
                            "largest cell probability (fully dependent cells) and the independent-cells product. Cell probabilities are never averaged." % (alpha, m["aggregation"].get("fitted_on", "calibration-period district-weeks")),
        "tier_counts": df["tier"].value_counts().reindex(alerts.TIERS, fill_value=0).to_dict(),
        "land_use_mix": df["land_use"].value_counts().to_dict(),
        "supporting": {"temperature_max_7d_c": w("f_t7"), "rain_30d_mm": w("f_p30"), "humidity_7d_pct": w("f_rh7"), "wind_7d_ms": w("f_wind7"),
                       "soil_wetness_7d": w("f_soil7"), "viirs_detections_7d": _f(np.expm1(df["f_v7"]).sum()), "viirs_detections_30d": _f(np.expm1(df["f_v30"]).sum()),
                       "seasonal_recurrence": w("clim")},
        "factors": factors, "timeline": timeline, "history": hist,
        "confidence": {"model_band_mean_width": _f((df["p_hi"] - df["p_lo"]).mean()), "observation_coverage_score": _f(max(0.0, 1 - gap / 30)),
                       "test_brier": m["test"]["brier"], "test_roc_auc": m["test"]["roc_auc"],
                       "note": f"Model confidence (spread between bootstrap models) and observation quality ({m.get('reference_sensor')} coverage in the last 30 days) are separate "
                               "from the predicted probability. Low coverage is never read as low risk."},
        "thresholds": alerts.tiers_view(cfg), "thresholds_scope": {"scope_type": cfg.get("scope_type"), "scope_value": cfg.get("scope_value")},
        "trained_on": m["trained_on"], "target": m["target"],
    }


def grid_cells(region_id: str, issue_date: str | None = None) -> dict:
    df = _cells(region_id, issue_date)
    if df.empty:
        return {"cells": [], "regional": None}
    w, s, e, n = grid.cell_bounds(df["cell_id"].to_numpy())
    df = df.assign(west=w, south=s, east=e, north=n)
    cols = ["cell_id", "lat", "lon", "west", "south", "east", "north", "p", "p_lo", "p_hi", "tier", "land_use", "state", "district", "clim", "observed", "f_gap30"]
    alpha = forecast.meta()["aggregation"]["alpha"]
    return {"issue_date": str(pd.Timestamp(df["issue_date"].iloc[0]).date()), "cells": _rec(df[cols].round(4)),
            "regional": forecast.aggregate_region(df["p"].to_numpy(), alpha), "reference": reference_block()}


def cell_detail(cell_id: int) -> dict:
    df = _cells(f"cell:{cell_id}")
    if df.empty:
        return {"status": "no_forecast", "cell_id": cell_id, "jurisdiction": alerts.resolve_jurisdiction(cell_id=cell_id)}
    r = df.iloc[0]
    hist = forecast.cells_fc()
    h = hist[hist["cell_id"] == cell_id]
    return {"status": "ok", "cell_id": int(cell_id), "probability": float(r["p"]), "p_lower": float(r["p_lo"]), "p_upper": float(r["p_hi"]), "tier": r["tier"],
            "daily_cumulative": [float(r[f"p_d{k}"]) for k in range(1, 8)], "factors": forecast.explain(int(cell_id)),
            "jurisdiction": alerts.resolve_jurisdiction(cell_id=int(cell_id)),
            "history": [{"issue_date": str(pd.Timestamp(a).date()), "p": float(b), "observed": None if pd.isna(c) else bool(c)} for a, b, c in zip(h["issue_date"], h["p"], h["observed"])],
            "inputs": {k[2:]: _f(r[k]) for k in r.index if k.startswith("f_")}, "seasonal_recurrence": _f(r["clim"]), "reference": reference_block()}


def ranking(level: str = "district", top: int = 50) -> list:
    df = _cells("country")
    if df.empty:
        return []
    alpha = forecast.meta()["aggregation"]["alpha"]
    key = "state" if level == "state" else "district_id"
    out = []
    for k, g in df.dropna(subset=[key]).groupby(key):
        a = forecast.aggregate_region(g["p"].to_numpy(), alpha)
        t = g.loc[g["p"].idxmax()]
        out.append({"id": f"{level}:{k}", "name": k if level == "state" else f"{t['district']}, {t['state']}", "state": t["state"], "n_cells": int(len(g)),
                    "p_any": a["p_any"], "max_cell": a["max_cell"], "expected_cells": a["expected_cells_with_detection"],
                    "tier": alerts.TIERS[max(alerts.TIERS.index(x) for x in g["tier"])], "cells_high": int((g["tier"] == "HIGH").sum()),
                    "cells_very_high": int((g["tier"] == "VERY_HIGH").sum()), "land_use": g["land_use"].mode().iat[0],
                    "band": _f((g["p_hi"] - g["p_lo"]).mean()), "coverage": _f(max(0.0, 1 - g["f_gap30"].max() / 30))})
    out.sort(key=lambda r: (-r["cells_very_high"], -r["cells_high"], -r["max_cell"]))
    return out[:top]
