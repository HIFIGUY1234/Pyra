"""Five-tier threshold engine, three-condition trigger, jurisdiction routing and the
alert lifecycle (cooldown, de-duplication, downgrade, human review).

Three alert types are kept strictly apart:
  PRE_FIRE_RISK_ADVISORY          calibrated cell probability >= HIGH threshold  (a prediction)
  URGENT_RISK_ESCALATION          calibrated cell probability >= VERY_HIGH       (a prediction)
  UNVERIFIED_SATELLITE_DETECTION  an actual MODIS/VIIRS hotspot, regardless of forecast

Nothing here contacts anyone outside the application. Deliveries are in-app queue
entries marked `simulated`. No public warning is ever issued by this code.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select

from . import forecast, grid, ingest, store
from . import models as M
from .config import ANOMALY_TYPES, DEFAULT_TIERS, SAT_LABEL

TIERS = ["LOW", "WATCH", "MODERATE", "HIGH", "VERY_HIGH"]
TIER_COLOR = {t["name"]: t["color"] for t in DEFAULT_TIERS}
CLOSED = {"REJECTED", "SUPERSEDED"}
IST = timezone(timedelta(hours=5, minutes=30), "IST")
CLASSIFICATION = {"PRE_FIRE_RISK_ADVISORY": "Predicted Pre-Fire Risk Advisory", "URGENT_RISK_ESCALATION": "Predicted Pre-Fire Risk Advisory",
                  "UNVERIFIED_SATELLITE_DETECTION": "Unverified Satellite Hotspot Detection"}
ACTIONS = {
    "LOW": "Routine monitoring. No alert required.",
    "WATCH": "Increase monitoring; check weather and historical fire patterns.",
    "MODERATE": "Show dashboard warning, prepare local monitoring teams and increase observation checks.",
    "HIGH": "Send a pre-fire risk advisory to the responsible authority for review; request acknowledgement.",
    "VERY_HIGH": "Urgent escalation: prioritise field verification and response readiness; notify the responsible authority and the higher-level nodal officer.",
}


def _cfg_dict(c: M.ThresholdConfig) -> dict:
    return {"id": c.id, "scope_type": c.scope_type, "scope_value": c.scope_value, "watch": c.watch, "moderate": c.moderate, "high": c.high,
            "very_high": c.very_high, "cooldown_hours": c.cooldown_hours, "evidence_min": c.evidence_min, "rationale": c.rationale,
            "updated_by": c.updated_by, "updated_at": c.updated_at.isoformat() if c.updated_at else None}


def get_configs() -> list[dict]:
    with M.Session() as s:
        return [_cfg_dict(c) for c in s.scalars(select(M.ThresholdConfig).order_by(M.ThresholdConfig.id))]


def resolve_config(state, land_use, configs=None) -> dict:
    """Most specific applicable configuration: state > land_use > default."""
    configs = configs or get_configs()
    by = {(c["scope_type"], c["scope_value"]): c for c in configs}
    return by.get(("state", state)) or by.get(("land_use", land_use)) or by.get(("default", None)) or {
        "scope_type": "default", "watch": 0.2, "moderate": 0.4, "high": 0.6, "very_high": 0.8, "cooldown_hours": 72, "evidence_min": 2}


def tier_name(p, cfg=None) -> str:
    cfg = cfg or {"watch": 0.2, "moderate": 0.4, "high": 0.6, "very_high": 0.8}
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "UNKNOWN"
    return TIERS[int(np.searchsorted([cfg["watch"], cfg["moderate"], cfg["high"], cfg["very_high"]], p, side="right"))]


def tiers_view(cfg) -> list[dict]:
    edges = [0.0, cfg["watch"], cfg["moderate"], cfg["high"], cfg["very_high"], 1.0]
    return [{"name": t, "min": edges[i], "max": edges[i + 1], "color": TIER_COLOR[t], "action": ACTIONS[t]} for i, t in enumerate(TIERS)]


def _aid(prefix: str, *parts) -> str:
    return f"{prefix}-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12].upper()


def _audit(s, actor, role, action, entity, entity_id, detail=None):
    s.add(M.AuditLog(actor=actor, actor_role=role, action=action, entity=entity, entity_id=str(entity_id), detail=detail or {}))


# --------------------------------------------------------------------------- jurisdiction
def resolve_jurisdiction(lat: float | None = None, lon: float | None = None, cell_id: int | None = None, land_use_override: str | None = None, contacts=None) -> dict:
    cells = store.cells()
    cid = int(cell_id) if cell_id is not None else int(grid.cell_of([lat], [lon])[0])
    if cid not in cells.index:
        return {"cell_id": cid, "resolved": False, "routing_status": "ADMIN_JURISDICTION_REVIEW_REQUIRED",
                "message": "Administrator Jurisdiction Review Required: this location is outside the mapped administrative boundaries."}
    c = cells.loc[cid]
    lu = land_use_override or c["land_use"]
    out = {"cell_id": cid, "state": c["state"], "district": c["district"], "district_id": c["district_id"], "land_use": lu,
           "land_use_source": c["land_use_source"] if not land_use_override else "supplied by user / organisation",
           "land_cover_fractions": {k[3:]: (None if pd.isna(c[k]) else round(float(c[k]), 3)) for k in c.index if k.startswith("lc_")},
           "note": "Land-use class decides WHO is responsible. It does not say whether a fire is natural or man-made."}
    out.update(route(c["state"], c["district_id"], lu, contacts))
    return out


def load_contacts() -> list:
    with M.Session() as s:
        return list(s.scalars(select(M.AuthorityContact)))


def route(state, district_id, land_use, contacts=None) -> dict:
    """Authority roles for a jurisdiction + whether a verified contact exists.
    Pass `contacts` (from load_contacts) when calling inside an open write transaction."""
    if not state or state == store.OUTSIDE or land_use in (None, "Unknown"):
        return {"resolved": False, "routing_status": "ADMIN_JURISDICTION_REVIEW_REQUIRED", "authorities": [],
                "message": "Administrator Jurisdiction Review Required: land-use class or administrative unit could not be determined."}
    rows = [r for r in (contacts if contacts is not None else load_contacts()) if r.land_use == land_use]
    templates = [r for r in rows if r.is_template]
    verified = [r for r in rows if not r.is_template and r.verified and r.state in (None, state) and r.district_id in (None, district_id)]
    auth = []
    for t in templates:
        match = [v for v in verified if v.role_title == t.role_title]
        auth.append({"authority": t.authority, "role_title": t.role_title, "level": t.level, "contact_id": match[0].id if match else None,
                     "verified_contact": bool(match), "channel": (match[0].contact_channel if match else None)})
    for v in verified:
        if v.role_title not in {t.role_title for t in templates}:
            auth.append({"authority": v.authority, "role_title": v.role_title, "level": v.level, "contact_id": v.id, "verified_contact": True, "channel": v.contact_channel})
    ok = any(a["verified_contact"] and a["level"] == 1 for a in auth)
    return {"resolved": True, "authorities": auth, "routing_status": "ROUTED_TO_VERIFIED_CONTACT" if ok else "ADMIN_JURISDICTION_REVIEW_REQUIRED",
            "message": None if ok else "Administrator Jurisdiction Review Required: no verified authority contact is registered for this jurisdiction. "
                                       "The responsible roles are listed; contact details are never invented."}


# --------------------------------------------------------------------------- evidence
def evidence(g: pd.DataFrame) -> dict:
    """Supporting indicators for a set of trigger cells (condition 2 of the trigger)."""
    mean = lambda c: float(g[c].mean()) if c in g and g[c].notna().any() else None
    v7 = float(np.expm1(g["f_v7"]).sum())
    clim, p30, soil, rh, t7, wind, gap = mean("clim"), mean("f_p30"), mean("f_soil7"), mean("f_rh7"), mean("f_t7"), mean("f_wind7"), mean("f_gap30")
    ind = [
        {"key": "recent_detections", "label": "Recent satellite detections (7 days)", "value": v7, "unit": "detections", "met": v7 > 0, "rule": "> 0"},
        {"key": "seasonal_recurrence", "label": "Historical seasonal recurrence", "value": clim, "unit": "share of past years", "met": clim is not None and clim >= 0.5, "rule": ">= 0.5"},
        {"key": "dryness", "label": "Rainfall last 30 days / surface soil wetness", "value": p30, "unit": "mm", "extra": soil,
         "met": (p30 is not None and p30 < 10) or (soil is not None and soil < 0.3), "rule": "rain < 10 mm or soil wetness < 0.30"},
        {"key": "low_humidity", "label": "Relative humidity (7-day mean)", "value": rh, "unit": "%", "met": rh is not None and rh < 40, "rule": "< 40%"},
        {"key": "heat", "label": "Max temperature (7-day mean)", "value": t7, "unit": "deg C", "met": t7 is not None and t7 >= 35, "rule": ">= 35"},
        {"key": "wind", "label": "Wind speed (7-day mean)", "value": wind, "unit": "m/s", "met": wind is not None and wind >= 4, "rule": ">= 4"},
    ]
    cov = None if gap is None else max(0.0, 1 - gap / 30)
    return {"indicators": ind, "met": int(sum(i["met"] for i in ind)), "coverage_score": cov, "weather_available": t7 is not None,
            "coverage_note": "Observation coverage is reduced; absence of recent detections is not evidence of low risk." if cov is not None and cov < 0.85 else None}


def _recent_obs(cell_ids, end, days=7) -> list:
    d = store.daily()
    w = d[(d["acq_date"] > end - pd.Timedelta(days=days)) & (d["acq_date"] <= end) & d["cell_id"].isin(cell_ids)]
    g = w.groupby("satellite", observed=True).agg(detections=("n", "sum"), frp_max=("frp_max", "max"), last=("acq_date", "max"))
    return [{"satellite": SAT_LABEL.get(str(k), str(k)), "detections": int(r["detections"]), "frp_max_mw": None if pd.isna(r["frp_max"]) else float(r["frp_max"]),
             "last_date": str(r["last"].date())} for k, r in g.iterrows()]


# --------------------------------------------------------------------------- evaluation
def evaluate(issue_date: str | None = None, actor: str = "system", actor_role: str = "system", include_detections: bool = True) -> dict:
    if not forecast.available():
        return {"status": "forecast_unavailable", "message": "No trained and calibrated forecast is available; advisories cannot be evaluated."}
    fc = forecast.issue(issue_date)
    if fc.empty:
        return {"status": "no_forecast_for_date", "available_issue_dates": forecast.meta().get("issues_kept")}
    idate = pd.Timestamp(fc["issue_date"].iloc[0])
    cells = store.cells()
    configs = get_configs()
    contacts = load_contacts()
    alpha = forecast.meta()["aggregation"]["alpha"]
    df = fc.merge(cells[["state", "district", "district_id", "land_use", "lat", "lon"]], left_on="cell_id", right_index=True)
    cfg_cache = {}
    def cfg_for(st, lu):
        if (st, lu) not in cfg_cache:
            cfg_cache[(st, lu)] = resolve_config(st, lu, configs)
        return cfg_cache[(st, lu)]
    df["tier"] = [tier_name(p, cfg_for(st, lu)) for p, st, lu in zip(df["p"], df["state"], df["land_use"])]
    df["rank"] = df["tier"].map(TIERS.index)
    now_utc = datetime.now(timezone.utc)
    summary = {"issue_date": str(idate.date()), "created": 0, "duplicates_skipped": 0, "cooldown_suppressed": 0, "held_insufficient_evidence": 0,
               "jurisdiction_review_required": 0, "downgraded": 0, "superseded": 0, "detection_alerts_created": 0, "by_type": {}}
    with M.Session() as s:
        open_adv = {a.dedupe_key: a for a in s.scalars(select(M.Alert).where(M.Alert.alert_type != "UNVERIFIED_SATELLITE_DETECTION").order_by(M.Alert.issue_date))
                    if a.status not in CLOSED and not a.status.startswith("DOWNGRADED")}
        seen_keys = set()
        trig = df[df["rank"] >= 3]
        for (st, did, lu), g in trig.groupby(["state", "district_id", "land_use"], dropna=False):
            cfg = cfg_for(st, lu)
            top = g.loc[g["p"].idxmax()]
            tier = TIERS[int(g["rank"].max())]
            atype = "URGENT_RISK_ESCALATION" if tier == "VERY_HIGH" else "PRE_FIRE_RISK_ADVISORY"
            key = f"ADV|{st}|{did}|{lu}"
            seen_keys.add(key)
            aid = _aid("URG" if tier == "VERY_HIGH" else "PFA", key, idate.date(), tier)
            if s.scalar(select(M.Alert.id).where(M.Alert.alert_id == aid)):
                summary["duplicates_skipped"] += 1
                continue
            prev = open_adv.get(key)
            if prev is not None and pd.Timestamp(prev.issue_date) <= idate:
                hours = (idate - pd.Timestamp(prev.issue_date)).total_seconds() / 3600
                if TIERS.index(prev.risk_category) >= TIERS.index(tier) and hours < cfg["cooldown_hours"]:
                    prev.last_evaluated = now_utc.replace(tzinfo=None)
                    _audit(s, actor, actor_role, "COOLDOWN_SUPPRESSED", "alert", prev.alert_id, {"issue_date": str(idate.date()), "tier": tier, "cooldown_hours": cfg["cooldown_hours"]})
                    summary["cooldown_suppressed"] += 1
                    continue
            ev = evidence(g)
            dist_cells = df[(df["district_id"] == did) & (df["land_use"] == lu)] if pd.notna(did) else g
            agg = forecast.aggregate_region(dist_cells["p"].to_numpy(), alpha)
            rt = route(st, did, lu, contacts)
            cond = {"probability": True, "evidence": ev["met"] >= cfg["evidence_min"], "location": rt["resolved"]}
            if not cond["evidence"]:
                status, summary_key = "HELD_INSUFFICIENT_EVIDENCE", "held_insufficient_evidence"
            elif rt["routing_status"] != "ROUTED_TO_VERIFIED_CONTACT":
                status, summary_key = "JURISDICTION_REVIEW_REQUIRED", "jurisdiction_review_required"
            else:
                status, summary_key = "NEW", None
            w_, s_, e_, n_ = grid.cell_bounds(g["cell_id"].to_numpy())
            name = f"{lu} land, {top['district']}, {st}" if pd.notna(top["district"]) else f"{lu} land, {st}"
            payload = {
                "alert_id": aid, "alert_type": atype, "classification": CLASSIFICATION[atype], "region": name,
                "jurisdiction": {"state": st, "district": top["district"], "district_id": did, "land_use": lu},
                "bounding_box": [float(w_.min()), float(s_.min()), float(e_.max()), float(n_.max())],
                "grid_cells": [{"cell_id": int(r.cell_id), "lat": float(r.lat), "lon": float(r.lon), "probability": float(r.p), "p_lower": float(r.p_lo),
                                "p_upper": float(r.p_hi), "tier": r.tier} for r in g.sort_values("p", ascending=False).itertuples()],
                "probability_pct": round(float(top["p"]) * 100, 1), "risk_category": tier,
                "probability_meaning": f"Estimated {top['p'] * 100:.0f}% probability of at least one detectable S-NPP VIIRS active-fire hotspot in the highest-risk "
                                       f"0.25 deg cell during the 7 days after {idate.date()}. Not a probability of verified ground ignition.",
                "regional_summary": agg, "prediction_period": {"from": str((idate + pd.Timedelta(days=1)).date()), "to": str((idate + pd.Timedelta(days=7)).date()), "label": "Next 7 days"},
                "generated_at_utc": now_utc.isoformat(timespec="seconds"), "generated_at_local": now_utc.astimezone(IST).isoformat(timespec="seconds"),
                "contributing_factors": [{"group": x["group"], "contribution_logodds": x["contribution"]} for x in forecast.explain(int(top["cell_id"]))[:6]]
                                        if str(idate.date()) == forecast.meta()["issue_date"] else [],
                "evidence": ev, "conditions": cond, "thresholds_applied": {k: cfg[k] for k in ("scope_type", "scope_value", "high", "very_high", "cooldown_hours", "evidence_min")},
                "recent_satellite_observations": _recent_obs(g["cell_id"].tolist(), idate),
                "data_quality": {"observation_coverage_score": ev["coverage_score"], "weather_layer": "NASA POWER" if ev["weather_available"] else "unavailable"},
                "model_uncertainty": {"p_lower_pct": round(float(top["p_lo"]) * 100, 1), "p_upper_pct": round(float(top["p_hi"]) * 100, 1), "method": forecast.meta().get("uncertainty_method")},
                "recommended_action": ACTIONS[tier], "routing": rt, "notification_channel": "in-app authority queue (SIMULATED notification - prototype)",
                "human_review_required": True,
            }
            alert = M.Alert(alert_id=aid, alert_type=atype, classification=CLASSIFICATION[atype], status=status, routing_status=rt["routing_status"], dedupe_key=key,
                            region_id=f"district:{did}" if pd.notna(did) else f"state:{st}", region_name=name, state=st, district_id=did if pd.notna(did) else None,
                            land_use=lu, probability=float(top["p"]), p_lower=float(top["p_lo"]), p_upper=float(top["p_hi"]), risk_category=tier,
                            issue_date=idate.date(), priority=2 if tier == "VERY_HIGH" else 1, payload=payload)
            if prev is not None and pd.Timestamp(prev.issue_date) <= idate:
                alert.supersedes = prev.alert_id
                s.add(M.AlertEscalation(alert=prev, action="SUPERSEDED", from_status=prev.status, to_status="SUPERSEDED", actor=actor, actor_role=actor_role,
                                        note=f"Replaced by {aid} ({prev.risk_category} -> {tier})"))
                prev.status = "SUPERSEDED"
                summary["superseded"] += 1
            s.add(alert)
            s.add(M.AlertEscalation(alert=alert, action="GENERATED", to_status=status, actor=actor, actor_role=actor_role,
                                    note=f"Conditions - probability: met; evidence: {ev['met']}/{cfg['evidence_min']} required; location: {'resolved' if rt['resolved'] else 'unresolved'}"))
            if cond["evidence"]:
                for a in rt.get("authorities", []):
                    if a["level"] == 1 or tier == "VERY_HIGH":
                        s.add(M.AlertRecipient(alert=alert, authority=a["authority"], role_title=a["role_title"], level=a["level"], contact_id=a["contact_id"],
                                               channel="in-app (simulated)" if a["verified_contact"] else None, simulated=True,
                                               delivery_status="DELIVERED_TO_DASHBOARD_SIMULATED" if a["verified_contact"] else "NOT_SENT_NO_VERIFIED_CONTACT"))
            if summary_key:
                summary[summary_key] += 1
            summary["created"] += 1
            summary["by_type"][atype] = summary["by_type"].get(atype, 0) + 1
            _audit(s, actor, actor_role, "ALERT_GENERATED", "alert", aid, {"type": atype, "tier": tier, "status": status})
        # downgrade open advisories whose cells no longer reach HIGH on a later issue date
        for key, prev in open_adv.items():
            if key in seen_keys or pd.Timestamp(prev.issue_date) >= idate or prev.status in CLOSED:
                continue
            ids = [c["cell_id"] for c in (prev.payload or {}).get("grid_cells", [])]
            cur = df[df["cell_id"].isin(ids)]
            new_tier = TIERS[int(cur["rank"].max())] if len(cur) else "LOW"
            to = f"DOWNGRADED_TO_{new_tier}"
            s.add(M.AlertEscalation(alert=prev, action="AUTO_DOWNGRADE", from_status=prev.status, to_status=to, actor=actor, actor_role=actor_role,
                                    note=f"Issue {idate.date()}: highest calibrated cell probability now {float(cur['p'].max()) * 100 if len(cur) else 0:.0f}% ({new_tier})"))
            prev.status = to
            prev.last_evaluated = now_utc.replace(tzinfo=None)
            summary["downgraded"] += 1
            _audit(s, actor, actor_role, "ALERT_DOWNGRADED", "alert", prev.alert_id, {"to": new_tier})
        if include_detections:
            summary["detection_alerts_created"] = _detection_alerts(s, df, actor, actor_role, now_utc, contacts)
        s.commit()
    summary["status"] = "ok"
    return summary


def _detection_alerts(s, fc_df, actor, actor_role, now_utc, contacts, hours: int = 24) -> int:
    """One alert per cell x satellite for hotspots acquired in the last `hours` of data."""
    end = max(pd.Timestamp(v["last"]) for v in store.spans().values())
    rec, _ = ingest.query_hotspots(end - pd.Timedelta(days=1), end, limit=10 ** 9)
    if rec.empty:
        return 0
    rec = rec[rec["timestamp_utc"] >= rec["timestamp_utc"].max() - pd.Timedelta(hours=hours)]
    cells, stat = store.cells(), store.cell_static()
    pmap = fc_df.set_index("cell_id")
    n = 0
    for (cid, sat), g in rec.groupby(["cell_id", "satellite"]):
        top = g.loc[g["frp_mw"].fillna(-1).idxmax()]
        day = str(g["acq_date"].max())
        aid = _aid("USD", cid, sat, day)
        if s.scalar(select(M.Alert.id).where(M.Alert.alert_id == aid)):
            continue
        j = resolve_jurisdiction(cell_id=int(cid), contacts=contacts)
        share = stat["static_share"].get(int(cid), np.nan)
        cause = []
        if pd.notna(top["anomaly_type"]) and int(top["anomaly_type"]) != 0:
            cause.append(f"FIRMS type flag: {ANOMALY_TYPES.get(int(top['anomaly_type']))}")
        if pd.notna(share) and share >= 0.5:
            cause.append(f"{share * 100:.0f}% of this cell's typed archive detections are static land sources (possible flare / industrial heat)")
        p = float(pmap.at[cid, "p"]) if cid in pmap.index else None
        lu = j.get("land_use")
        payload = {
            "alert_id": aid, "alert_type": "UNVERIFIED_SATELLITE_DETECTION", "classification": CLASSIFICATION["UNVERIFIED_SATELLITE_DETECTION"],
            "label": "UNVERIFIED SATELLITE DETECTION - a thermal hotspot, not a confirmed wildfire",
            "satellite": SAT_LABEL.get(sat, sat), "product": str(top["product_type"]), "acquired_utc": pd.Timestamp(top["timestamp_utc"]).isoformat(),
            "acquired_local": pd.Timestamp(top["timestamp_utc"]).tz_localize("UTC").tz_convert(IST).isoformat(), "daynight": top["daynight"],
            "coordinates": {"lat": float(top["latitude"]), "lon": float(top["longitude"])},
            "footprint": {"scan_km": float(top["scan"]), "track_km": float(top["track"]), "pixel_area_km2": float(top["pixel_area_km2"])},
            "confidence": {"raw": top["confidence_raw"], "class": top["confidence_class"], "standardized_score": None if pd.isna(top["confidence_score"]) else float(top["confidence_score"]),
                           "note": "Standardized score is an ordinal convention across sensors, not a probability of fire."},
            "frp_mw": None if pd.isna(top["frp_mw"]) else float(top["frp_mw"]), "detections_in_cell": int(len(g)),
            "frp_total_mw": float(g["frp_mw"].sum(skipna=True)), "jurisdiction": {k: j.get(k) for k in ("state", "district", "district_id", "land_use")},
            "possible_responsible_authority": j.get("authorities", []), "routing": {k: j.get(k) for k in ("routing_status", "message", "resolved")},
            "suspected_source_evidence": cause, "suspected_source_note": "Listed only when the data supports it. Land use never implies cause.",
            "forecast_probability_pct": None if p is None else round(p * 100, 1),
            "forecast_note": None if p is None else ("Detected although the 7-day forecast for this cell was below the 60% advisory threshold." if p < 0.6 else "Forecast for this cell was already at or above the advisory threshold."),
            "generated_at_utc": now_utc.isoformat(timespec="seconds"), "generated_at_local": now_utc.astimezone(IST).isoformat(timespec="seconds"),
            "recommended_action": "Request verification by the responsible authority. Do not treat as a confirmed fire until verified.",
            "notification_channel": "in-app authority queue (SIMULATED notification - prototype)", "human_review_required": True,
        }
        name = f"{j.get('district') or 'Unmapped area'}, {j.get('state') or ''}".strip(", ")
        a = M.Alert(alert_id=aid, alert_type="UNVERIFIED_SATELLITE_DETECTION", classification=CLASSIFICATION["UNVERIFIED_SATELLITE_DETECTION"],
                    status="NEW" if j.get("routing_status") == "ROUTED_TO_VERIFIED_CONTACT" else "JURISDICTION_REVIEW_REQUIRED", routing_status=j.get("routing_status"),
                    dedupe_key=f"DET|{cid}|{sat}", region_id=f"cell:{cid}", region_name=name, state=j.get("state"), district_id=j.get("district_id"), land_use=lu,
                    probability=p, risk_category=tier_name(p) if p is not None else None, issue_date=pd.Timestamp(day).date(),
                    priority=3 if (payload["frp_mw"] or 0) >= 50 else 1, payload=payload)
        s.add(a)
        s.add(M.AlertEscalation(alert=a, action="GENERATED", to_status=a.status, actor=actor, actor_role=actor_role, note=f"{len(g)} detection(s) by {SAT_LABEL.get(sat, sat)}"))
        n += 1
    return n


# --------------------------------------------------------------------------- lifecycle actions
TRANSITIONS = {
    "acknowledge": "ACKNOWLEDGED", "verify": None, "approve": "APPROVED", "reject": "REJECTED", "escalate": "ESCALATED",
}


def act(alert_id: str, action: str, actor: str, actor_role: str, note: str | None = None) -> dict:
    if action not in TRANSITIONS:
        raise ValueError(f"unknown action {action}")
    with M.Session() as s:
        a = s.scalar(select(M.Alert).where(M.Alert.alert_id == alert_id))
        if a is None:
            raise KeyError(alert_id)
        if a.status in CLOSED or a.status.startswith("DOWNGRADED"):
            raise PermissionError(f"alert is closed ({a.status}); no further action is possible")
        if action == "reject" and not (note or "").strip():
            raise ValueError("a reason is required to reject an alert")
        frm = a.status
        if action == "verify":
            if a.alert_type == "UNVERIFIED_SATELLITE_DETECTION":
                to, a.classification = "VERIFIED_FIRE_INCIDENT", "Verified Fire Incident"
            else:
                to = "EVIDENCE_VERIFIED"
        else:
            to = TRANSITIONS[action]
        if action == "escalate":
            have = {(r.authority, r.role_title) for r in a.recipients}
            for x in (a.payload or {}).get("routing", {}).get("authorities", []) or (a.payload or {}).get("possible_responsible_authority", []):
                if x["level"] >= 2 and (x["authority"], x["role_title"]) not in have:
                    s.add(M.AlertRecipient(alert=a, authority=x["authority"], role_title=x["role_title"], level=x["level"], contact_id=x.get("contact_id"), simulated=True,
                                           channel="in-app (simulated)" if x.get("verified_contact") else None,
                                           delivery_status="DELIVERED_TO_DASHBOARD_SIMULATED" if x.get("verified_contact") else "NOT_SENT_NO_VERIFIED_CONTACT"))
        if action == "acknowledge":
            for r in a.recipients:
                r.acknowledged_at = r.acknowledged_at or M.now()
        a.status = to
        s.add(M.AlertEscalation(alert=a, action=action.upper(), from_status=frm, to_status=to, actor=actor, actor_role=actor_role, note=note))
        _audit(s, actor, actor_role, f"ALERT_{action.upper()}", "alert", alert_id, {"from": frm, "to": to, "note": note})
        if action in ("approve", "escalate"):
            # Delivery happens only here, after an authorised human decision (see notify.py).
            from . import notify
            s.flush()
            res = notify.deliver(s, a, approved_by=actor)
            _audit(s, actor, actor_role, "NOTIFICATIONS_ATTEMPTED", "alert", alert_id, {"provider": notify.provider_name(), "results": res})
        s.commit()
        return serialize(a, full=True)


def serialize(a: M.Alert, full: bool = False) -> dict:
    out = {"alert_id": a.alert_id, "alert_type": a.alert_type, "classification": a.classification, "status": a.status, "routing_status": a.routing_status,
           "region_name": a.region_name, "region_id": a.region_id, "state": a.state, "district_id": a.district_id, "land_use": a.land_use,
           "probability": a.probability, "p_lower": a.p_lower, "p_upper": a.p_upper, "risk_category": a.risk_category, "priority": a.priority,
           "issue_date": str(a.issue_date), "generated_at": a.generated_at.isoformat() + "Z" if a.generated_at else None, "supersedes": a.supersedes,
           "frp_mw": (a.payload or {}).get("frp_mw"), "satellite": (a.payload or {}).get("satellite"),
           "coordinates": (a.payload or {}).get("coordinates"), "bounding_box": (a.payload or {}).get("bounding_box"),
           "n_cells": len((a.payload or {}).get("grid_cells", [])) or None, "evidence_met": ((a.payload or {}).get("evidence") or {}).get("met")}
    if full:
        out["payload"] = a.payload
        out["history"] = [{"action": e.action, "from": e.from_status, "to": e.to_status, "actor": e.actor, "role": e.actor_role, "note": e.note,
                           "at": e.created_at.isoformat() + "Z"} for e in a.escalations]
        out["recipients"] = [{"authority": r.authority, "role_title": r.role_title, "level": r.level, "channel": r.channel, "delivery_status": r.delivery_status,
                              "simulated": r.simulated, "acknowledged_at": r.acknowledged_at.isoformat() + "Z" if r.acknowledged_at else None} for r in a.recipients]
    return out


def list_alerts(alert_type=None, status=None, state=None, land_use=None, tier=None, open_only=False, limit=200, offset=0) -> dict:
    with M.Session() as s:
        q = select(M.Alert)
        if alert_type == "ADVISORY":
            q = q.where(M.Alert.alert_type != "UNVERIFIED_SATELLITE_DETECTION")
        elif alert_type:
            q = q.where(M.Alert.alert_type == alert_type)
        for col, val in ((M.Alert.status, status), (M.Alert.state, state), (M.Alert.land_use, land_use), (M.Alert.risk_category, tier)):
            if val:
                q = q.where(col == val)
        rows = list(s.scalars(q.order_by(M.Alert.priority.desc(), M.Alert.probability.desc().nullslast(), M.Alert.id.desc())))
        if open_only:
            rows = [r for r in rows if r.status not in CLOSED and not r.status.startswith("DOWNGRADED")]
        counts = {}
        for r in rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        return {"total": len(rows), "status_counts": counts, "items": [serialize(r) for r in rows[offset: offset + limit]]}
