"""Independent / external scientific validation (separate from software tests).

Every reference source carries an independence assessment. Passing unit tests proves software behaviour only;
the numbers here are scientific evidence, and a source is called INDEPENDENT only if it does not share the
observations or algorithm inputs being validated.

Implemented validations:
* Harmonization vs baselines (raw MODIS, naive MODIS+VIIRS sum, constant ratio, PyroScope) under the chronological
  hold-out, nationally and per state. The calibration is national, so the per-state table measures regional
  transfer under a TEMPORAL hold-out; a true leave-region-out REFIT is not implemented (stated in the output).
* Fire events vs official incident records: an authorised CSV import (never invented records) and matching with
  precision / recall / F1, time and distance errors. No official records are loaded yet -> BLOCKED.
* Fire events vs burned area (MCD64A1/VNP64A1): corroboration only (those products use active fires) -> app.burned_area.
* Smoke / PM2.5: needs ground monitors (CPCB, OpenAQ) -> BLOCKED_BY_CREDENTIALS.
"""
from __future__ import annotations

import io
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import delete, select

from . import models as M

INCIDENT_COLUMNS = ["incident_id", "source_authority", "start_date", "latitude", "longitude"]
INCIDENT_OPTIONAL = ["end_date", "state", "district", "area_ha", "incident_type", "notes"]

SOURCES = [
    {"id": "viirs_holdout", "name": "Withheld real VIIRS observations (chronological hold-out)", "kind": "harmonization",
     "platform": "Suomi NPP VIIRS 375 m", "resolution": "0.25 deg monthly", "algorithm": "FIRMS VIIRS C2 active fire",
     "independence": "INDEPENDENT OF THE MODEL FIT (never seen in training); same sensor family as the target by design",
     "known_dependence": "Not independent of VIIRS detection limitations themselves", "status": "AVAILABLE"},
    {"id": "official_incidents", "name": "State forest department / fire service / disaster authority incident records",
     "kind": "events", "independence": "INDEPENDENT (ground reports)", "known_dependence": "Some agencies log incidents from FIRMS alerts: "
     "records flagged as satellite-derived must be excluded", "access": "not publicly available as a bulk feed; authorised CSV import",
     "status": "BLOCKED_BY_EXTERNAL_DATA"},
    {"id": "mcd64a1", "name": "MODIS MCD64A1 C6.1 burned area", "kind": "events/burned_area", "platform": "Terra+Aqua MODIS 500 m",
     "independence": "NOT INDEPENDENT of MODIS active fires (used to guide burn mapping): corroboration only",
     "status": "BLOCKED_BY_CREDENTIALS (LAADS licence acceptance)"},
    {"id": "vnp64a1", "name": "VIIRS VNP64A1 v002 burned area", "kind": "events/burned_area", "platform": "S-NPP VIIRS 500 m",
     "independence": "NOT INDEPENDENT of VIIRS active fires: corroboration only", "status": "BLOCKED_BY_CREDENTIALS (LAADS licence acceptance)"},
    {"id": "insat_fire", "name": "INSAT-3D/3DR fire product (MOSDAC)", "kind": "events/diurnal",
     "independence": "INDEPENDENT sensor and algorithm; coarser pixels, so non-detection is weak evidence",
     "status": "BLOCKED_BY_DATA_LICENCE_OR_ACCESS"},
    {"id": "cpcb_pm25", "name": "CPCB CAAQMS ground PM2.5", "kind": "smoke", "independence": "INDEPENDENT (in-situ)",
     "known_dependence": "PM2.5 has many non-fire sources; attribution needs care", "status": "BLOCKED_BY_CREDENTIALS (data.gov.in / CPCB API key)"},
    {"id": "openaq", "name": "OpenAQ v3 (aggregates CPCB and others)", "kind": "smoke", "independence": "INDEPENDENT (in-situ)",
     "status": "BLOCKED_BY_CREDENTIALS (OpenAQ API key)"},
]


# --------------------------------------------------------------------------- harmonization
def _metrics(actual, pred) -> dict:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    ok = np.isfinite(a) & np.isfinite(p)
    a, p = a[ok], p[ok]
    if not len(a) or a.sum() <= 0:
        return {"n": int(len(a))}
    return {"n": int(len(a)), "wape_pct": float(100 * np.abs(p - a).sum() / a.sum()), "bias_pct": float(100 * (p.sum() - a.sum()) / a.sum()),
            "rmse": float(np.sqrt(np.mean((p - a) ** 2))), "mae": float(np.mean(np.abs(p - a))),
            "r": float(np.corrcoef(a, p)[0, 1]) if len(a) > 2 and a.std() > 0 and p.std() > 0 else None}


def harmonization_baselines(region_id: str = "country") -> dict:
    from . import harmonize
    split = harmonize.default_split()
    if not split:
        return {"status": "insufficient_data"}
    df, _ = harmonize.series(region_id, split)
    test = df[df["withheld_viirs"] & df["viirs_complete"] & ~df["nrt"]]
    train = df[df["train_sensor"]]
    const = train["viirs"].sum() / train["aqua"].sum() if train["aqua"].sum() > 0 else np.nan
    const_mg = train["aqua"].sum() / train["terra"].sum() if train["terra"].sum() > 0 else np.nan
    base = np.where(test["provenance"] == "morning_gap_sensor", test["terra"] * const_mg * const, test["aqua"] * const)
    return {"region_id": region_id, "split": split, "test_months": int(len(test)),
            "test_period": [int(test["ym"].min()), int(test["ym"].max())] if len(test) else None,
            "target": "withheld real Suomi NPP VIIRS monthly detections",
            "models": {"raw_modis": _metrics(test["viirs"], test["modis_total"]),
                       "naive_modis_plus_viirs": _metrics(test["viirs"], test["modis_total"] + test["viirs"]),
                       "constant_ratio": _metrics(test["viirs"], base),
                       "pyroscope": _metrics(test["viirs"], test["veq"])},
            "band_coverage_pct": float(100 * ((test["viirs"] >= test["veq_lo"]) & (test["viirs"] <= test["veq_hi"])).mean()) if len(test) else None}


def harmonization_by_state(top: int = 12) -> dict:
    from . import store
    m = store.monthly()
    cells = store.cells().set_index("cell_id")
    m = m.assign(state=m["cell_id"].map(cells["state"]))
    tops = m[m["satellite"] == "Suomi NPP"].groupby("state")["n"].sum().sort_values(ascending=False).head(top).index.tolist()
    rows = []
    for st in tops:
        r = harmonization_baselines(f"state:{st}")
        rows.append({"state": st, **{k: r["models"][k] for k in r.get("models", {})}, "test_months": r.get("test_months"),
                     "band_coverage_pct": r.get("band_coverage_pct")})
    return {"design": "chronological hold-out per state with the NATIONAL calibration (temporal hold-out; regional transfer). "
                      "A leave-region-out refit (spatial hold-out) is NOT implemented.", "states": rows}


# --------------------------------------------------------------------------- official incidents
def import_incidents(content: bytes, source: str, licence: str, actor: str, replace_source: bool = False) -> dict:
    if not source.strip() or not licence.strip():
        raise ValueError("source (issuing authority / dataset) and licence are required")
    df = pd.read_csv(io.BytesIO(content))
    miss = [c for c in INCIDENT_COLUMNS if c not in df.columns]
    if miss:
        raise ValueError(f"CSV missing columns {miss}; required {INCIDENT_COLUMNS}, optional {INCIDENT_OPTIONAL}")
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce") if "end_date" in df else pd.NaT
    ok = df["start_date"].notna() & df["latitude"].between(-90, 90) & df["longitude"].between(-180, 180) & df["incident_id"].notna()
    good = df[ok]
    with M.Session() as s:
        if replace_source:
            s.execute(delete(M.ReferenceIncident).where(M.ReferenceIncident.dataset == source))
        have = {r for (r,) in s.execute(select(M.ReferenceIncident.incident_id).where(M.ReferenceIncident.dataset == source))}
        n = 0
        for r in good.itertuples(index=False):
            if str(r.incident_id) in have:
                continue
            s.add(M.ReferenceIncident(incident_id=str(r.incident_id), dataset=source, licence=licence, authority=str(r.source_authority),
                                      start_date=r.start_date.to_pydatetime(),
                                      end_date=None if pd.isna(getattr(r, "end_date", pd.NaT)) else r.end_date.to_pydatetime(),
                                      latitude=float(r.latitude), longitude=float(r.longitude),
                                      state=getattr(r, "state", None), district=getattr(r, "district", None),
                                      area_ha=None if pd.isna(getattr(r, "area_ha", np.nan)) else float(r.area_ha),
                                      incident_type=getattr(r, "incident_type", None), imported_by=actor))
            n += 1
        s.add(M.AuditLog(actor=actor, action="REFERENCE_INCIDENTS_IMPORTED", entity="reference_incident", entity_id=source[:60],
                         detail={"imported": n, "rejected": int((~ok).sum())}))
        s.commit()
    return {"imported": n, "rejected": int((~ok).sum()), "duplicates_skipped": int(len(good) - n), "dataset": source}


def incidents_status() -> dict:
    from sqlalchemy import func
    with M.Session() as s:
        rows = s.execute(select(M.ReferenceIncident.dataset, func.count(), func.min(M.ReferenceIncident.start_date),
                                func.max(M.ReferenceIncident.start_date)).group_by(M.ReferenceIncident.dataset)).all()
    return {"datasets": [{"dataset": d, "n": n, "first": a.isoformat() if a else None, "last": b.isoformat() if b else None} for d, n, a, b in rows],
            "status": "AVAILABLE" if rows else "BLOCKED_BY_EXTERNAL_DATA",
            "csv_format": {"required": INCIDENT_COLUMNS, "optional": INCIDENT_OPTIONAL},
            "note": "PyroScope never creates incident records; only authorised imports with provenance are used."}


def validate_events(start, end, dist_km: float = 5.0, days: float = 2.0, dataset: str | None = None) -> dict:
    """Match official incidents to fire events. Incident recall is meaningful; event 'precision' is a LOWER BOUND
    because incident registers are incomplete (many real fires are never reported)."""
    s0, e0 = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)
    with M.Session() as s:
        q = select(M.ReferenceIncident).where(M.ReferenceIncident.start_date >= s0.to_pydatetime(), M.ReferenceIncident.start_date < e0.to_pydatetime())
        if dataset:
            q = q.where(M.ReferenceIncident.dataset == dataset)
        inc = list(s.scalars(q))
        evs = list(s.scalars(select(M.FireEvent).where(M.FireEvent.status != "MERGED",
                                                       M.FireEvent.last_detection >= (s0 - pd.Timedelta(days=days)).to_pydatetime(),
                                                       M.FireEvent.first_detection < (e0 + pd.Timedelta(days=days)).to_pydatetime())))
    if not inc:
        return {"status": "BLOCKED_BY_EXTERNAL_DATA", "reason": "no official incident records imported for this period", "events": len(evs)}
    if not evs:
        return {"status": "NO_EVENTS", "incidents": len(inc)}
    k = 111.32
    ev_matched, rows = set(), []
    for r in inc:
        best = None
        rend = r.end_date or r.start_date
        for e in evs:
            if e.first_detection - pd.Timedelta(days=days) > rend or e.last_detection + pd.Timedelta(days=days) < r.start_date:
                continue
            dx = max(0.0, e.west - r.longitude, r.longitude - e.east) * k * math.cos(math.radians(r.latitude))
            dy = max(0.0, e.south - r.latitude, r.latitude - e.north) * k
            d = math.hypot(dx, dy)
            if d <= dist_km and (best is None or d < best[0]):
                best = (d, e)
        if best:
            ev_matched.add(best[1].event_id)
            rows.append({"incident_id": r.incident_id, "event_id": best[1].event_id, "distance_km": round(best[0], 3),
                         "start_error_h": round((best[1].first_detection - r.start_date).total_seconds() / 3600, 1)})
    recall = len(rows) / len(inc)
    prec = len(ev_matched) / len(evs)
    f1 = 2 * prec * recall / (prec + recall) if prec + recall else 0.0
    return {"status": "COMPUTED", "incidents": len(inc), "events": len(evs), "matched_incidents": len(rows),
            "recall": recall, "precision_lower_bound": prec, "f1_lower_bound": f1, "missed_incident_rate": 1 - recall,
            "median_distance_km": float(np.median([x["distance_km"] for x in rows])) if rows else None,
            "median_start_error_h": float(np.median([x["start_error_h"] for x in rows])) if rows else None,
            "matching": {"distance_km": dist_km, "days": days}, "matches": rows[:500],
            "caveat": "Precision is a lower bound: unmatched events may be real fires absent from the register."}


def summary() -> dict:
    out = {"sources": SOURCES, "software_tests_are_not_scientific_validation": True,
           "harmonization": None, "events_vs_incidents": incidents_status(),
           "smoke": {"status": "BLOCKED_BY_CREDENTIALS", "reason": "no ground PM2.5 source configured"},
           "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        out["harmonization"] = harmonization_baselines("country")
    except Exception as exc:     # no data loaded
        out["harmonization"] = {"status": "unavailable", "error": str(exc)[:200]}
    return out
