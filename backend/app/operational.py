"""Operational reference selection after the Suomi NPP data cessation (2 Nov 2026).

Two reference concepts are kept apart:
  * HISTORICAL reference (config.HISTORICAL_REFERENCE = Suomi NPP): defines the VIIRS-equivalent scale of the
    harmonized 2000-2026 record. Unchanged and reproducible; S-NPP is retired but its archive remains valid.
  * OPERATIONAL reference: the currently observing VIIRS platform used as the live forecasting target.
    Chosen from config.OPERATIONAL_CANDIDATES by declared evidence criteria, never by string replacement.

Acceptance criteria (declared before evaluation; a candidate must pass ALL):
  C1 platform officially operational (config.PLATFORMS)
  C2 data fresh: last loaded observation within FRESH_DAYS of the newest observation of any loaded sensor
  C3 >= MIN_ARCHIVE_MONTHS months of science-quality (standard-processing) archive
  C4 missing-day share <= MAX_GAP_SHARE over its record
  C5 an independent forecast model trained on that sensor exists
  C6 that model, on its own chronological test period: >= MIN_TEST_ROWS test rows, Brier skill vs its own
     climatology > 0, ROC-AUC >= MIN_AUC and expected calibration error <= MAX_ECE

Default choice among passing candidates follows NOAA's order (NOAA-21 primary, NOAA-20 secondary). An
administrator may select any other PASSING candidate; a failing one can never be selected. If none passes,
there is no operational reference: forecasts are labelled provisional/unavailable, and NOAA-20/NOAA-21
observations are still shown as independent actual streams.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache

import numpy as np
import pandas as pd

from . import store
from .config import HISTORICAL_REFERENCE, OPERATIONAL_CANDIDATES, PLATFORMS

FRESH_DAYS = 14
MIN_ARCHIVE_MONTHS = 24
MAX_GAP_SHARE = 0.05
MIN_TEST_ROWS = 50_000
MIN_AUC = 0.80
MAX_ECE = 0.05
CRITERIA = {
    "C1": "Platform officially operational", "C2": f"Last observation within {FRESH_DAYS} days of the newest loaded observation",
    "C3": f">= {MIN_ARCHIVE_MONTHS} months of science-quality archive", "C4": f"Missing-day share <= {MAX_GAP_SHARE:.0%}",
    "C5": "Independent forecast model trained on this sensor exists",
    "C6": f"Own test period: >= {MIN_TEST_ROWS:,} rows, Brier skill > 0 vs climatology, ROC-AUC >= {MIN_AUC}, ECE <= {MAX_ECE}",
}
SEASON = {12: "winter", 1: "winter", 2: "winter", 3: "pre-monsoon", 4: "pre-monsoon", 5: "pre-monsoon",
          6: "monsoon", 7: "monsoon", 8: "monsoon", 9: "monsoon", 10: "post-monsoon", 11: "post-monsoon"}


def _months(a: str, b: str) -> float:
    return (pd.Timestamp(b) - pd.Timestamp(a)).days / 30.44


@lru_cache(maxsize=8)
def evaluate(sensor: str) -> dict:
    """Data-quality and model evidence for one platform. Nothing is pooled with any other sensor."""
    from . import forecast
    sp = store.spans()
    pl = PLATFORMS.get(sensor, {})
    if sensor not in sp:
        return {"sensor": sensor, "loaded": False, "platform": pl, "passes": False, "checks": {}}
    s = sp[sensor]
    newest = max(v["last"] for k, v in sp.items() if k in PLATFORMS)
    d = store.daily()
    d = d[d["satellite"] == sensor]
    first, last, last_typed = s["first"], s["last"], s.get("last_typed") or s["last"]
    days_total = (pd.Timestamp(last) - pd.Timestamp(first)).days + 1
    gaps = len(s.get("gap_days") or [])
    tot = d[["n", "n_veg", "n_low", "n_high"]].sum()
    dn = d.groupby("daynight", observed=True)["n"].sum()
    mon = d.groupby(d["acq_date"].dt.month)["n_veg"].sum()
    yearly = d.groupby(d["acq_date"].dt.year)["n_veg"].sum()
    sci = d[d["acq_date"] <= last_typed]
    ov = {}
    for other in ("Suomi NPP", "NOAA-20", "NOAA-21"):
        if other != sensor and other in sp:
            a, b = max(first, sp[other]["first"]), min(last_typed, sp[other].get("last_typed") or sp[other]["last"])
            ov[other] = {"from": a, "to": b, "months": round(max(_months(a, b), 0), 1)} if a <= b else None
    m = forecast._meta(sensor) if sensor in forecast.SENSOR_CONFIG else {}
    ev = m.get("evaluation") or {}
    test = m.get("test") or {}
    auc = ev.get("roc_auc", test.get("roc_auc"))
    bss = ev.get("brier_skill", m.get("brier_skill_vs_climatology"))
    ece = ev.get("ece")
    rows = (m.get("rows") or {}).get("test", 0)
    checks = {
        "C1": pl.get("status") == "operational",
        "C2": (pd.Timestamp(newest) - pd.Timestamp(last)).days <= FRESH_DAYS,
        "C3": _months(max(first, pl.get("firms_start", first)), last_typed) >= MIN_ARCHIVE_MONTHS,
        "C4": gaps / max(days_total, 1) <= MAX_GAP_SHARE,
        "C5": bool(m),
        "C6": bool(m) and rows >= MIN_TEST_ROWS and (bss or 0) > 0 and (auc or 0) >= MIN_AUC and ece is not None and ece <= MAX_ECE,
    }
    return {
        "sensor": sensor, "loaded": True, "platform": pl,
        "coverage": {"first": first, "last": last, "science_quality_last": last_typed,
                     "nrt_days": max((pd.Timestamp(last) - pd.Timestamp(last_typed)).days, 0),
                     "archive_months": round(_months(first, last_typed), 1),
                     "operational_archive_months": round(_months(max(first, pl.get("firms_start", first)), last_typed), 1), "missing_days": gaps,
                     "missing_share": round(gaps / max(days_total, 1), 4), "newest_loaded_observation_any_sensor": newest,
                     "days_behind_newest": (pd.Timestamp(newest) - pd.Timestamp(last)).days,
                     "wall_clock_age_days": (date.today() - date.fromisoformat(last)).days},
        "detections": {"total": int(tot["n"]), "presumed_vegetation": int(tot["n_veg"]), "science_quality": int(sci["n"].sum()),
                       "per_year": {int(k): int(v) for k, v in yearly.items()}},
        "confidence": {"low": int(tot["n_low"]), "high": int(tot["n_high"]), "nominal": int(tot["n"] - tot["n_low"] - tot["n_high"]),
                       "high_share": round(float(tot["n_high"] / max(tot["n"], 1)), 4)},
        "day_night": {str(k): int(v) for k, v in dn.items()},
        "seasonal_share": {str(k): round(float(v / max(mon.sum(), 1)), 4) for k, v in mon.groupby(mon.index.map(SEASON)).sum().items()},
        "overlap": ov,
        "model": None if not m else {"model_version": m.get("model_version"), "trained_at": m.get("trained_at"), "split": m.get("split"),
                                     "test_rows": rows, "roc_auc": auc, "brier_skill": bss, "ece": ece,
                                     "pr_auc": ev.get("pr_auc", test.get("pr_auc")), "brier": ev.get("brier", test.get("brier"))},
        "checks": checks, "passes": all(checks.values()),
    }


@lru_cache(maxsize=1)
def _stored_choice() -> str | None:
    """Latest admin choice. Cached (cleared on select/clear) so hot paths never open a DB session --
    serving code can run inside another session's write transaction (SQLite would block)."""
    try:
        from sqlalchemy import select
        from . import models as M
        with M.Session() as s:
            row = s.scalar(select(M.OperationalSelection).order_by(M.OperationalSelection.id.desc()))
            return row.platform if row and row.platform else None
    except Exception:
        return None


def candidates() -> list[dict]:
    return [evaluate(c) for c in OPERATIONAL_CANDIDATES]


def selected() -> str | None:
    """Approved operational reference or None. A stored admin choice is honoured only while it still passes."""
    return _selected_cached()


def summary() -> dict:
    from . import bridge, forecast
    cands = candidates()
    sel = selected()
    stored = _stored_choice()
    hist = PLATFORMS[HISTORICAL_REFERENCE]
    sp = store.spans().get(HISTORICAL_REFERENCE, {})
    why_none = None
    if not sel:
        why_none = "; ".join(f"{c['sensor']} fails " + ", ".join(f"{k} ({CRITERIA[k]})" for k, v in c["checks"].items() if not v)
                             for c in cands) or "no candidate loaded"
    return {
        "historical_reference": {"platform": HISTORICAL_REFERENCE, "status": hist["status"], "science_data_end": hist.get("science_data_end"),
                                 "loaded_first": sp.get("first"), "loaded_last": sp.get("last"), "science_quality_last": sp.get("last_typed"),
                                 "role": "Defines the VIIRS-equivalent scale of the harmonized record; unchanged after the cessation.",
                                 "source": hist.get("source")},
        "operational_reference": sel, "selection_mode": ("administrator" if stored == sel else "evidence_default") if sel else "none",
        "operational_status": "APPROVED" if sel else "UNAVAILABLE",
        "unavailable_reason": why_none, "stored_admin_choice": stored,
        "stored_choice_rejected": bool(stored and stored != sel),
        "candidates": cands, "criteria": CRITERIA,
        "default_rule": "Among passing candidates follow NOAA's order: NOAA-21 (primary), then NOAA-20 (secondary).",
        "forecast_served": forecast.active_sensor(), "forecast_models": forecast.models_available(),
        "bridges": bridge.studies()["pairs"],
    }


def select(platform: str | None, actor: str, role: str, reason: str) -> dict:
    """Administrator choice among PASSING candidates (None reverts to the evidence default)."""
    from . import models as M
    if platform is not None:
        ev = evaluate(platform) if platform in OPERATIONAL_CANDIDATES else None
        if ev is None:
            raise ValueError(f"{platform} is not an operational candidate ({OPERATIONAL_CANDIDATES})")
        if not ev["passes"]:
            failed = [k for k, v in ev["checks"].items() if not v]
            raise ValueError(f"{platform} does not meet the acceptance criteria ({', '.join(failed)}); it cannot be selected")
    clear()
    with M.Session() as s:
        s.add(M.OperationalSelection(platform=platform, selected_by=actor, reason=reason[:500]))
        s.add(M.AuditLog(actor=actor, actor_role=role, action="OPERATIONAL_REFERENCE_SELECTED", entity="operational_reference",
                         entity_id=platform or "evidence_default", detail={"reason": reason}))
        s.commit()
    clear()
    from . import forecast
    forecast.clear()
    return summary()


def transition_report(window_months: int = 12) -> dict:
    """S-NPP -> successor transition: coverage, raw and bridged platform discontinuity, verdict."""
    from . import bridge
    sp = store.spans()
    hist = HISTORICAL_REFERENCE
    cess = PLATFORMS[hist].get("science_data_end")
    out = {"historical_reference": hist, "science_data_end": cess, "last_loaded_snpp": sp.get(hist, {}).get("last"),
           "last_science_quality_snpp": sp.get(hist, {}).get("last_typed"), "successors": {}}
    d = store.daily()
    d = d[d["satellite"].isin([hist, *OPERATIONAL_CANDIDATES])]
    mon = d.assign(ym=d["acq_date"].dt.to_period("M")).groupby(["ym", "satellite"], observed=True)["n_veg"].sum().unstack("satellite")
    for c in OPERATIONAL_CANDIDATES:
        if c not in sp or hist not in sp:
            out["successors"][c] = {"status": "unavailable"}
            continue
        lt = pd.Period(sp[hist].get("last_typed") or sp[hist]["last"], "M")
        win = [lt - k for k in range(window_months)][::-1]
        both = mon.reindex(win)[[hist, c]].dropna()
        raw_ratio = float(both[hist].sum() / max(both[c].sum(), 1)) if len(both) else None
        br = bridge.status(c, hist)
        monthly_ratio = (both[hist] / both[c].clip(lower=1)) if len(both) else pd.Series(dtype=float)
        out["successors"][c] = {
            "coverage": {"first": sp[c]["first"], "last": sp[c]["last"], "science_quality_last": sp[c].get("last_typed")},
            "window": [str(win[0]), str(win[-1])], "months_compared": int(len(both)),
            "raw_discontinuity": {"snpp_per_successor_ratio": raw_ratio,
                                  "abs_log_step": round(abs(float(np.log(raw_ratio))), 4) if raw_ratio else None,
                                  "monthly_ratio_p05_p95": [round(float(monthly_ratio.quantile(.05)), 3), round(float(monthly_ratio.quantile(.95)), 3)] if len(both) else None},
            "bridge": {"status": br.get("status"), "selected": br.get("selected"), "reason": br.get("selection_reason") or br.get("reason")},
            "calibrated_discontinuity": ("not computed: no bridge calibration passed its acceptance rule, so no calibrated continuation is produced"
                                         if br.get("status") != "calibrated" else
                                         {"state_month_wape_pct": br["experiments"][0]["state_month"][br["selected"]]["wape_pct"],
                                          "bias_pct": br["experiments"][0]["state_month"][br["selected"]]["bias_pct"]}),
        }
    any_cal = any((v.get("bridge") or {}).get("status") == "calibrated" for v in out["successors"].values())
    out["verdict"] = ("BRIDGED" if any_cal else "NOT_BRIDGED")
    out["interpretation"] = ("Month-to-month S-NPP/successor ratios measure the sensor difference during simultaneous observation; "
                             "the spread (p05-p95) shows how much of an apparent step can be sensor noise. Genuine burning changes must "
                             "appear in BOTH platforms. No continuation of the S-NPP-equivalent record past "
                             f"{out['last_science_quality_snpp']} is produced unless a bridge passes its acceptance rule.")
    return out


@lru_cache(maxsize=1)
def _selected_cached() -> str | None:
    passing = [c["sensor"] for c in candidates() if c["passes"]]
    choice = _stored_choice()
    if choice in passing:
        return choice
    return passing[0] if passing else None


def clear():
    if hasattr(evaluate, "cache_clear"):
        evaluate.cache_clear()
    _stored_choice.cache_clear()
    _selected_cached.cache_clear()
