"""Smoke transport: EXPERIMENTAL forward trajectories from fire events (NOT a dispersion model, NOT PM2.5).

NOAA ARL HYSPLIT is not installed in this deployment, so PyroScope runs a clearly labelled kinematic fallback:

* Sources: fire events still burning (ACTIVE / DETECTED / POSSIBLY_INACTIVE / UNVERIFIED) or explicit event ids,
  ranked by their FRE bracket (an emission proxy; see app.emissions).
* Meteorology: NCEP GFS 0.25 deg hourly winds through the Open-Meteo GFS API (no key), sampled on a 1 deg grid
  around the sources, at TWO bracketing transport levels: 10 m (smoke kept in the surface layer) and 850 hPa
  (~1.5 km, smoke lofted above a shallow boundary layer). No plume-rise model is available, so PyroScope does NOT
  invent an injection height; both levels are always reported, with the GFS boundary-layer height along the path.
* Integration: Heun (RK2) with 15-minute steps; bilinear in space, linear in time.
* Exposure: people living within `corridor_km` of any trajectory point (WorldPop 0.05 deg cells, each cell counted
  once even when several trajectories pass) with the earliest modelled arrival time.

What this is NOT: a concentration forecast. Trajectories have no mass, mixing, deposition or chemistry, so they
cannot give PM2.5. PM2.5 validation needs ground monitors (CPCB / OpenAQ), which need credentials not configured.
Model outputs are not official health warnings.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select

from . import models as M
from .config import PROCESSED

OUT = PROCESSED / "smoke"
API = "https://api.open-meteo.com/v1/gfs"
LEVELS = {"surface_10m": ("wind_speed_10m", "wind_direction_10m"), "850hPa": ("wind_speed_850hPa", "wind_direction_850hPa")}
GRID_DEG = 1.0          # GFS 0.25 deg sampled every 1 deg: Open-Meteo counts each location as one call (600/min free tier)
STEP_MIN = 15
LABEL = "EXPERIMENTAL TRAJECTORY (kinematic fallback, not HYSPLIT) - no concentrations - not an official health warning"
BURNING = ("ACTIVE", "DETECTED", "POSSIBLY_INACTIVE", "UNVERIFIED")


# --------------------------------------------------------------------------- meteorology
def fetch_winds(bbox, start: pd.Timestamp, hours: int, session=None, batch: int = 100, sleep=None) -> dict:
    """Hourly u/v (m/s) at both levels and boundary-layer height on a GRID_DEG grid. Arrays shaped (time, lat, lon)."""
    import time
    import requests
    s = session or requests.Session()
    sleep = sleep or time.sleep
    w, so, e, n = bbox
    lats = np.arange(math.floor(so / GRID_DEG) * GRID_DEG, n + GRID_DEG, GRID_DEG)
    lons = np.arange(math.floor(w / GRID_DEG) * GRID_DEG, e + GRID_DEG, GRID_DEG)
    pts = [(la, lo) for la in lats for lo in lons]
    end = start + pd.Timedelta(hours=hours)
    vars_ = sorted({v for pair in LEVELS.values() for v in pair} | {"boundary_layer_height"})
    recs = []
    for k in range(0, len(pts), batch):
        chunk = pts[k:k + batch]
        for attempt in range(6):
            r = s.get(API, params={"latitude": ",".join(f"{a:.3f}" for a, _ in chunk), "longitude": ",".join(f"{b:.3f}" for _, b in chunk),
                                   "hourly": ",".join(vars_), "wind_speed_unit": "ms", "timezone": "GMT",
                                   "start_date": start.strftime("%Y-%m-%d"), "end_date": end.strftime("%Y-%m-%d")}, timeout=90)
            if r.status_code != 429:
                break
            sleep(61)                         # free-tier minutely limit: wait for the window to reset
        if r.status_code >= 400:
            raise RuntimeError(f"BLOCKED_BY_EXTERNAL_DATA: Open-Meteo GFS HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        recs.extend(d if isinstance(d, list) else [d])
    times = pd.to_datetime(recs[0]["hourly"]["time"])
    nt, ny, nx = len(times), len(lats), len(lons)
    out = {"times": times, "lats": lats, "lons": lons, "source": "NCEP GFS 0.25 deg via Open-Meteo", "fetched_at":
           datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for lvl, (sp, di) in LEVELS.items():
        spd = np.array([r["hourly"][sp] for r in recs], float).T.reshape(nt, ny, nx)
        dr = np.radians(np.array([r["hourly"][di] for r in recs], float).T.reshape(nt, ny, nx))
        # meteorological direction = where the wind blows FROM
        out[lvl] = (-spd * np.sin(dr), -spd * np.cos(dr))
    out["blh"] = np.array([r["hourly"]["boundary_layer_height"] for r in recs], float).T.reshape(nt, ny, nx)
    if any(np.isnan(out[l][0]).all() for l in LEVELS):
        raise RuntimeError("BLOCKED_BY_EXTERNAL_DATA: GFS winds unavailable for the requested period")
    return out


def _interp(field: np.ndarray, met: dict, t: float, lat: float, lon: float) -> float:
    """Bilinear in space, linear in time (t in hours since met['times'][0]); NaN outside the grid."""
    lats, lons = met["lats"], met["lons"]
    fy = (lat - lats[0]) / GRID_DEG
    fx = (lon - lons[0]) / GRID_DEG
    if not (0 <= fy < len(lats) - 1 and 0 <= fx < len(lons) - 1 and 0 <= t < field.shape[0] - 1):
        return float("nan")
    i, j, k = int(fy), int(fx), int(t)
    a, b, c = fy - i, fx - j, t - k

    def sp(kk):
        f = field[kk]
        return (f[i, j] * (1 - a) * (1 - b) + f[i + 1, j] * a * (1 - b) + f[i, j + 1] * (1 - a) * b + f[i + 1, j + 1] * a * b)
    return float(sp(k) * (1 - c) + sp(k + 1) * c)


def trajectory(lat: float, lon: float, t0_h: float, hours: int, met: dict, level: str) -> list[dict]:
    u, v = met[level]
    dt = STEP_MIN / 60
    pts = [{"h": 0.0, "lat": lat, "lon": lon}]
    t = t0_h
    for step in range(int(hours / dt)):
        def vel(la, lo, tt):
            uu, vv = _interp(u, met, tt, la, lo), _interp(v, met, tt, la, lo)
            return uu, vv
        u1, v1 = vel(lat, lon, t)
        if math.isnan(u1):
            break
        k = 3.6 * dt                        # m/s -> km per step
        la2 = lat + v1 * k / 110.57
        lo2 = lon + u1 * k / (111.32 * math.cos(math.radians(lat)))
        u2, v2 = vel(la2, lo2, t + dt)
        if math.isnan(u2):
            break
        lat = lat + 0.5 * (v1 + v2) * k / 110.57
        lon = lon + 0.5 * (u1 + u2) * k / (111.32 * math.cos(math.radians(lat)))
        t += dt
        if (step + 1) % 4 == 0:
            pts.append({"h": round(t - t0_h, 2), "lat": round(lat, 4), "lon": round(lon, 4),
                        "blh_m": round(_interp(met["blh"], met, t, lat, lon), 0)})
    return pts


# --------------------------------------------------------------------------- run
def _sources(params: dict) -> list[M.FireEvent]:
    with M.Session() as s:
        if params.get("event_ids"):
            evs = list(s.scalars(select(M.FireEvent).where(M.FireEvent.event_id.in_(params["event_ids"]))))
            if not evs:
                raise KeyError("none of the event ids exist")
            return evs
        q = select(M.FireEvent).where(M.FireEvent.status.in_(BURNING))
        if params.get("since"):
            q = q.where(M.FireEvent.last_detection >= pd.Timestamp(params["since"]).to_pydatetime())
        q = q.order_by(M.FireEvent.fre_mj_high.desc().nulls_last()).limit(int(params.get("max_sources", 25)))
        return list(s.scalars(q))


def run(params: dict | None = None, progress=None, session=None) -> dict:
    params = params or {}
    hours = int(params.get("hours", 48))
    if not 6 <= hours <= 120:
        raise ValueError("hours must be 6-120")
    corridor = float(params.get("corridor_km", 25))
    srcs = _sources(params)
    if not srcs:
        return {"status": "NO_SOURCES", "label": LABEL, "note": "No burning fire events (run fire-event delineation)."}
    start = pd.Timestamp(params["start"]) if params.get("start") else pd.Timestamp(max(e.last_detection for e in srcs)).floor("h")
    pad = min(10.0, 0.15 * hours)     # degrees around the sources; trajectories leaving the box stop and are flagged incomplete
    lat = [e.lat for e in srcs]
    lon = [e.lon for e in srcs]
    bbox = (min(lon) - pad, min(lat) - pad, max(lon) + pad, max(lat) + pad)
    if progress:
        progress(f"fetching GFS winds for {len(srcs)} sources")
    met = fetch_winds(bbox, start.floor("D"), hours + 24, session=session)
    t0_h = (start - met["times"][0]).total_seconds() / 3600
    trajs = []
    for e in srcs:
        for lvl in LEVELS:
            pts = trajectory(e.lat, e.lon, t0_h, hours, met, lvl)
            trajs.append({"event_id": e.event_id, "level": lvl, "start_utc": start.isoformat(), "points": pts,
                          "fre_mj_high": e.fre_mj_high, "complete": pts[-1]["h"] >= hours - 0.01 if pts else False})
    exposure = corridor_exposure(trajs, start, corridor)
    run_id = f"SM-{start:%Y%m%d%H}-{uuid.uuid4().hex[:6]}"
    res = {"run_id": run_id, "label": LABEL, "model": "kinematic forward trajectory (Heun, 15 min), GFS 0.25 deg via Open-Meteo",
           "hysplit": "not installed: no dispersion / concentration output", "start_utc": start.isoformat(), "hours": hours,
           "levels": list(LEVELS), "injection_height": "unknown (no plume-rise model); 10 m and 850 hPa bracket the transport",
           "sources": [{"event_id": e.event_id, "lat": e.lat, "lon": e.lon, "status": e.status, "fre_mj_low": e.fre_mj_low,
                        "fre_mj_high": e.fre_mj_high} for e in srcs],
           "trajectories": trajs, "exposure": exposure, "meteorology": {"source": met["source"], "fetched_at": met["fetched_at"],
                                                                          "grid_deg": GRID_DEG, "bbox": bbox},
           "pm25": {"status": "NOT_IMPLEMENTED", "reason": "trajectories carry no mass; a dispersion model (e.g. HYSPLIT) is required"},
           "validation": {"status": "BLOCKED_BY_CREDENTIALS", "reason": "no ground PM2.5 source configured (CPCB / OpenAQ API keys)"},
           "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{run_id}.json").write_text(json.dumps(res, default=str))
    return {k: res[k] for k in ("run_id", "start_utc", "hours", "exposure")} | {"sources": len(srcs), "trajectories": len(trajs)}


def corridor_exposure(trajs: list[dict], start: pd.Timestamp, corridor_km: float) -> dict:
    from . import population
    fi = population._fine()
    if fi is None:
        return {"status": "NO_POPULATION_LAYER"}
    tree, pop = fi
    out = {}
    for lvl in LEVELS:
        first = {}
        for tr in (t for t in trajs if t["level"] == lvl):
            for p in tr["points"][1:]:
                for i in tree.query_ball_point(population._xyz(np.array([p["lat"]]), np.array([p["lon"]]))[0], r=corridor_km):
                    if i not in first or p["h"] < first[i]:
                        first[i] = p["h"]
        idx = np.fromiter(first.keys(), int) if first else np.zeros(0, int)
        hrs = np.fromiter(first.values(), float) if first else np.zeros(0)
        bands = {f"<= {b} h": float(pop[idx[hrs <= b]].sum()) for b in (6, 12, 24, 48, 72, 120)}
        out[lvl] = {"people_in_corridor": float(pop[idx].sum()), "cells": int(len(idx)), "by_arrival": bands}
    return {"corridor_km": corridor_km, "levels": out, "population_source": "WorldPop 2020 1 km (0.05 deg cells, each counted once)",
            "interpretation": "People living near the modelled smoke PATH. Not exposure to a concentration; not a health warning."}


def runs(limit: int = 20) -> list[dict]:
    if not OUT.exists():
        return []
    items = []
    for f in sorted(OUT.glob("SM-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        d = json.loads(f.read_text())
        items.append({k: d.get(k) for k in ("run_id", "start_utc", "hours", "computed_at", "label")}
                     | {"sources": len(d.get("sources", [])), "exposure": d.get("exposure")})
    return items


def get(run_id: str) -> dict:
    if not run_id.startswith("SM-") or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise ValueError("bad run id")
    f = OUT / f"{run_id}.json"
    if not f.exists():
        raise KeyError(f"smoke run {run_id} not found")
    return json.loads(f.read_text())
