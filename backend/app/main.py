"""PyroScope FastAPI backend."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from . import acquire, alerts, bridge, operational, analytics, db_sync, gis_layers, notify, security, forecast, geo, grid, harmonize, ingest, reports, risk, store
from . import models as M
from .config import (ANOMALY_TYPES, PROCESSED, REPORTS, SAT_INSTRUMENT, SAT_LABEL, SATELLITES, UPLOADS, VIIRS_CONF_SCORE,
                     VIIRS_REFERENCE)

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(_app):
    _production_config_guard()
    from . import jobs
    jobs.start_embedded_worker()       # dev convenience; production sets PYROSCOPE_EMBEDDED_WORKER=0 and runs app.worker
    yield


app = FastAPI(title="PyroScope API", version="1.0.0", lifespan=_lifespan,
              description="MODIS-VIIRS hot-spot harmonization, calibrated 7-day hotspot probability and authority alert routing.")
_origins = [o.strip() for o in os.getenv("PYROSCOPE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
# Vercel preview deployments get per-branch hostnames: allow them with an explicit regex, e.g.
# PYROSCOPE_CORS_ORIGIN_REGEX=^https://pyroscope-[a-z0-9-]+-myteam\.vercel\.app$  (never a bare wildcard)
_origin_regex = os.getenv("PYROSCOPE_CORS_ORIGIN_REGEX") or None
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_origin_regex=_origin_regex, allow_methods=["GET", "POST", "PUT", "DELETE"],
                   allow_headers=["Authorization", "Content-Type", "X-User"])
db_sync.init_db()


def _production_config_guard():
    """Refuse to serve in production while the configuration has blocking errors (wildcard CORS, no admin, ...)."""
    from . import system_config
    v = system_config.validate()
    log = logging.getLogger("pyroscope")
    for i in v["issues"]:
        (log.error if i["level"] == "error" else log.warning)("config %s: %s", i["key"], i["message"])
    if v["mode"] == "production" and not v["ok"]:
        raise RuntimeError(f"production configuration has {v['errors']} blocking error(s); see the log or GET /api/system/config in dev mode")


rec = analytics._rec


class NpEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (np.ndarray,)):
            return o.tolist()
        if isinstance(o, (pd.Timestamp, datetime)):
            return o.isoformat()
        return str(o)


def _clean(o):
    if isinstance(o, float):
        return o if np.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.floating):
        return float(o) if np.isfinite(o) else None
    return o


def ok(data):
    return JSONResponse(content=json.loads(json.dumps(_clean(data), cls=NpEncoder)))


PUBLIC_PATHS = {"/api/health", "/api/meta", "/api/auth/login", "/docs", "/openapi.json"}


@app.middleware("http")
async def _production_gate(request: Request, call_next):
    """AUTH_MODE=production: every /api route except PUBLIC_PATHS needs a valid Bearer session."""
    if security.auth_mode() == "production" and request.url.path.startswith("/api") and request.url.path not in PUBLIC_PATHS \
            and request.method != "OPTIONS":
        try:
            actor(request.headers.get("authorization"), None)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


SENSOR_SCOPED = ("/api/forecast", "/api/alerts/evaluate", "/api/critical-regions", "/api/reports")


@app.middleware("http")
async def _forecast_sensor(request: Request, call_next):
    """?sensor=<platform> on forecast-dependent routes selects that sensor's independent model for this request."""
    snr = request.query_params.get("sensor")
    if snr and request.url.path.startswith(SENSOR_SCOPED):
        try:
            tok = forecast.set_request_sensor(snr)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        try:
            return await call_next(request)
        finally:
            forecast._override.reset(tok)
    return await call_next(request)


@app.exception_handler(ValueError)
async def _bad(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(KeyError)
async def _missing(_: Request, exc: KeyError):
    return JSONResponse(status_code=404, content={"detail": f"not found: {exc}"})


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    logging.getLogger("pyroscope").exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "internal error (details are in the server log)"})


@app.exception_handler(PermissionError)
async def _conflict(_: Request, exc: PermissionError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# --------------------------------------------------------------------------- authentication
class Actor(BaseModel):
    id: int
    username: str
    role: str
    display_name: str
    organisation_id: Optional[int] = None
    auth: str = "token"            # token | dev-persona


def _actor_of(u: M.User, how: str) -> Actor:
    return Actor(id=u.id, username=u.username, role=u.role.name, display_name=u.display_name, organisation_id=u.organisation_id, auth=how)


def actor(authorization: Optional[str] = Header(default=None), x_user: Optional[str] = Header(default=None)) -> Actor:
    """Bearer session token (always honoured). In AUTH_MODE=dev only, the X-User demo-persona header
    is accepted when no token is sent. In production the header is ignored."""
    if authorization and authorization.lower().startswith("bearer "):
        dig = security.token_digest(authorization.split(" ", 1)[1].strip())
        with M.Session() as s:
            ses = s.scalar(select(M.UserSession).where(M.UserSession.token_sha256 == dig))
            if ses is None or ses.revoked_at is not None or ses.expires_at < M.now():
                raise HTTPException(401, "session invalid or expired; log in again")
            u = s.get(M.User, ses.user_id)
            if u is None or not u.is_active:
                raise HTTPException(401, "account disabled")
            return _actor_of(u, "token")
    if security.auth_mode() == "production":
        raise HTTPException(401, "authentication required (Bearer token)")
    with M.Session() as s:
        u = s.scalar(select(M.User).where(M.User.username == (x_user or "analyst")))
        if u is None or not u.is_active:
            raise HTTPException(401, "unknown user")
        return _actor_of(u, "dev-persona")


def require(*roles):
    def dep(a: Actor = Depends(actor)) -> Actor:
        if a.role != "admin" and a.role not in roles:
            raise HTTPException(403, f"role '{a.role}' may not perform this action (needs: {', '.join(roles) or 'admin'})")
        return a
    return dep


def limited(bucket: str):
    """Per-client rate limit (see security.check_rate). Keyed by client IP and, when present, the user header/token prefix."""
    def dep(request: Request):
        ip = request.client.host if request.client else "unknown"
        if os.getenv("PYROSCOPE_TRUST_PROXY", "0") == "1":  # behind our nginx: use the forwarded client address
            ip = (request.headers.get("x-forwarded-for") or ip).split(",")[0].strip()
        wait = security.check_rate(bucket, ip)
        if wait is not None:
            raise HTTPException(429, f"rate limit exceeded for {bucket}; retry in {int(wait) + 1} s",
                                headers={"Retry-After": str(int(wait) + 1)})
    return dep


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


@app.post("/api/auth/login", dependencies=[Depends(limited("login"))])
def auth_login(body: LoginBody, request: Request):
    with M.Session() as s:
        u = s.scalar(select(M.User).where(M.User.username == body.username))
        nowt = M.now()
        if u is not None and u.locked_until and u.locked_until > nowt:
            raise HTTPException(429, "account temporarily locked after repeated failures; try again later")
        if u is None or not u.is_active or not security.verify_password(body.password, u.password_hash):
            if u is not None:
                u.failed_logins = (u.failed_logins or 0) + 1
                if u.failed_logins >= security.MAX_FAILED:
                    from datetime import timedelta
                    u.locked_until, u.failed_logins = nowt + timedelta(minutes=security.LOCK_MINUTES), 0
                s.add(M.AuditLog(actor=body.username, actor_role=None, action="LOGIN_FAILED", entity="user", entity_id=body.username))
                s.commit()
            raise HTTPException(401, "invalid username or password")
        token, dig = security.new_token()
        s.add(M.UserSession(user_id=u.id, token_sha256=dig, expires_at=nowt + security.session_ttl(), client=(request.headers.get("user-agent") or "")[:200]))
        u.failed_logins, u.locked_until, u.last_login_at = 0, None, nowt
        s.add(M.AuditLog(actor=u.username, actor_role=u.role.name, action="LOGIN", entity="user", entity_id=u.username))
        s.commit()
        return ok({"token": token, "token_type": "bearer", "expires_in_s": int(security.session_ttl().total_seconds()),
                   "user": {"username": u.username, "display_name": u.display_name, "role": u.role.name, "organisation_id": u.organisation_id}})


@app.post("/api/auth/logout")
def auth_logout(authorization: Optional[str] = Header(default=None), a: Actor = Depends(actor)):
    if a.auth == "token" and authorization:
        dig = security.token_digest(authorization.split(" ", 1)[1].strip())
        with M.Session() as s:
            ses = s.scalar(select(M.UserSession).where(M.UserSession.token_sha256 == dig))
            if ses:
                ses.revoked_at = M.now()
                s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="LOGOUT", entity="user", entity_id=a.username))
                s.commit()
    return ok({"logged_out": True})


@app.get("/api/auth/me")
def auth_me(a: Actor = Depends(actor)):
    org_name = None
    if a.organisation_id is not None:
        with M.Session() as s:
            org = s.get(M.Organisation, a.organisation_id)
            org_name = org.name if org else None
    return ok({**a.model_dump(), "organisation_name": org_name, "auth_mode": security.auth_mode(),
               "warning": None if a.auth == "token" else "Development persona (X-User header). Not authentication; disabled when PYROSCOPE_AUTH_MODE=production."})


class UserBody(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    role: str = Field(pattern="^(admin|gov_officer|org_user|analyst)$")
    password: str = Field(min_length=10, max_length=200)
    organisation_id: Optional[int] = None
    jurisdiction_state: Optional[str] = None
    jurisdiction_land_use: Optional[str] = None


@app.get("/api/users")
def users_list(a: Actor = Depends(require())):
    with M.Session() as s:
        return ok({"items": [{"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role.name, "organisation_id": u.organisation_id,
                              "is_active": u.is_active, "can_log_in": bool(u.password_hash), "is_demo": u.is_demo,
                              "last_login_at": u.last_login_at.isoformat() + "Z" if u.last_login_at else None} for u in s.scalars(select(M.User).order_by(M.User.id))]})


@app.post("/api/users", dependencies=[Depends(limited("admin"))])
def users_create(body: UserBody, a: Actor = Depends(require())):
    with M.Session() as s:
        if s.scalar(select(M.User).where(M.User.username == body.username)):
            raise HTTPException(409, "username already exists")
        role = s.scalar(select(M.Role).where(M.Role.name == body.role))
        if body.role == "org_user" and body.organisation_id is None:
            raise ValueError("organisation users must belong to an organisation")
        u = M.User(username=body.username, display_name=body.display_name, role_id=role.id, organisation_id=body.organisation_id,
                   jurisdiction_state=body.jurisdiction_state, jurisdiction_land_use=body.jurisdiction_land_use, is_demo=False,
                   password_hash=security.hash_password(body.password))
        s.add(u)
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="USER_CREATED", entity="user", entity_id=body.username, detail={"role": body.role}))
        s.commit()
        return ok({"id": u.id, "username": u.username, "role": body.role})


class PasswordBody(BaseModel):
    current_password: Optional[str] = None
    new_password: str = Field(min_length=10, max_length=200)


@app.put("/api/auth/password")
def auth_password(body: PasswordBody, a: Actor = Depends(actor)):
    with M.Session() as s:
        u = s.get(M.User, a.id)
        if u.password_hash and not security.verify_password(body.current_password or "", u.password_hash):
            raise HTTPException(401, "current password is wrong")
        if not u.password_hash and a.auth != "token" and security.auth_mode() == "production":
            raise HTTPException(403, "not allowed")
        u.password_hash = security.hash_password(body.new_password)
        for ses in s.scalars(select(M.UserSession).where(M.UserSession.user_id == u.id, M.UserSession.revoked_at.is_(None))):
            ses.revoked_at = M.now()        # changing the password ends every existing session
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="PASSWORD_CHANGED", entity="user", entity_id=a.username))
        s.commit()
    return ok({"changed": True, "sessions_revoked": True})


def need_data():
    if not store.has_data():
        raise HTTPException(409, "No processed data yet. Use Data Management -> Load Repository Dataset.")


def _ref(product: Optional[str]) -> str:
    """VIIRS calibration target stream: default S-NPP 375 m, or e.g. 'Suomi NPP 750m' when loaded."""
    if not product or product in ("375m", VIIRS_REFERENCE):
        return VIIRS_REFERENCE
    cand = product if product.endswith("750m") else f"{VIIRS_REFERENCE} 750m" if product == "750m" else product
    if cand not in {p["stream"] for p in harmonize.products()["streams"]}:
        raise ValueError(f"VIIRS product '{product}' is not loaded. {harmonize.products()['viirs_750m_message'] or ''}")
    return cand


def _split(v: Optional[int]) -> Optional[int]:
    if v is None:
        return None
    if not (190001 <= v <= 210012) or not (1 <= v % 100 <= 12):
        raise ValueError("split must be YYYYMM")
    return int(v)


# --------------------------------------------------------------------------- meta / geography
@app.get("/api/health")
def health():
    """Liveness + dependency checks: database reachable, data present, free disk space."""
    import shutil
    from sqlalchemy import text
    db_ok, db_err = True, None
    try:
        with M.Session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:  # never leak connection strings
        db_ok, db_err = False, type(exc).__name__
    du = shutil.disk_usage(str(PROCESSED))
    free_gb = du.free / 1e9
    status = "ok" if db_ok else "degraded"
    from . import system_config
    return {"status": status, "has_data": store.has_data(), "forecast": forecast.available(),
            "database": {"ok": db_ok, "error": db_err}, "storage": {"free_gb": round(free_gb, 2), "low": free_gb < 2.0},
            "admin_bootstrap": system_config.admin_bootstrap_state(), "auth_mode": security.auth_mode()}


@app.get("/api/system/config")
def system_config_view(a: Actor = Depends(require())):
    """Configuration validation for the running mode. Variable NAMES and problems only, never values."""
    from . import system_config
    return ok(system_config.validate())


@app.get("/api/system/credentials")
def system_credentials(a: Actor = Depends(require())):
    from . import system_config
    return ok({"items": system_config.credentials(),
               "note": "Status only. Secrets are read from the environment and are never returned, logged or stored by PyroScope."})


@app.get("/api/meta")
def meta():
    out = {"has_data": store.has_data(), "satellites": SATELLITES, "sat_labels": SAT_LABEL, "anomaly_types": ANOMALY_TYPES,
           "land_use_classes": geo.LAND_USE_CLASSES, "viirs_reference": VIIRS_REFERENCE, "confidence_mapping": VIIRS_CONF_SCORE}
    out["auth_mode"] = security.auth_mode()
    out["users"] = []
    if security.auth_mode() == "dev":   # demo persona list only in development mode
        with M.Session() as s:
            out["users"] = [{"username": u.username, "display_name": u.display_name, "role": u.role.name} for u in s.scalars(select(M.User)) if u.is_active]
    if store.has_data():
        d = store.districts().dropna(subset=["state"]).sort_values(["state", "district"])
        have = set(store.cells()["district_id"].dropna())
        out.update(states=[x for x in store.states() if x != store.OUTSIDE],
                   districts=[{"id": r.district_id, "name": r.district, "state": r.state} for r in d.itertuples() if r.district_id in have],
                   spans={k: {"first": v["first"], "last": v["last"]} for k, v in store.spans().items()}, data_end=str(analytics.data_end().date()),
                   default_split=harmonize.default_split(), forecast_available=forecast.available(),
                   issue_dates=forecast.meta().get("issues_kept", []) if forecast.available() else [])
    return ok(out)


@app.get("/api/geo/states")
def geo_states():
    p = geo.STATES_GEOJSON
    if not p.exists():
        raise HTTPException(404, "state boundaries not built")
    return FileResponse(p, media_type="application/geo+json")


@app.get("/api/geo/district/{district_id}")
def geo_district(district_id: str):
    g = geo.district_geojson(district_id)
    if g is None:
        raise HTTPException(404, "unknown district")
    return ok({"type": "Feature", "properties": {"id": district_id}, "geometry": g})


@app.get("/api/geo/cells", dependencies=[Depends(need_data)])
def geo_cells(region: str = "country"):
    c = store.cells()
    ids = [i for i in store.region_cells(region) if i in c.index]
    df = c.loc[ids, ["cell_id", "lat", "lon", "state", "district", "land_use", "lc_forest", "lc_savanna", "lc_cropland", "lc_urban"]].copy()
    df["static_share"] = store.cell_static()["static_share"].reindex(df.index).to_numpy()
    return ok({"grid_deg": 0.25, "cells": rec(df.round(3)), "bbox": store.region_bbox(region), "label": store.region_label(region),
               "land_use_source": c["land_use_source"].iloc[0] if len(c) else None})


@app.get("/api/dashboard/summary", dependencies=[Depends(need_data)])
def dashboard():
    return ok(analytics.dashboard_summary())


# --------------------------------------------------------------------------- hotspots
@app.get("/api/hotspots", dependencies=[Depends(need_data)])
def hotspots(start: str, end: str, region: Optional[str] = None, bbox: Optional[str] = None, satellites: Optional[str] = None,
             daynight: Optional[str] = None, min_conf: Optional[float] = Query(None, ge=0, le=1), limit: int = Query(5000, ge=1, le=20000)):
    s_, e_ = pd.Timestamp(start), pd.Timestamp(end)
    if e_ < s_:
        raise ValueError("end must not be before start")
    if (e_ - s_).days > 92:
        raise ValueError("date range limited to 92 days per request")
    box = [float(x) for x in bbox.split(",")] if bbox else (store.region_bbox(region) if region else None)
    sats = [x for x in satellites.split(",") if x] if satellites else None
    df, total = ingest.query_hotspots(s_, e_, box, sats, limit=10 ** 9 if region else limit, min_conf=min_conf, daynight=daynight)
    if region and not region.startswith("bbox") and region != "country":
        df = df[df["cell_id"].isin(np.array(store.region_cells(region)))]
        total = len(df)
        if total > limit:
            df = df.iloc[np.linspace(0, total - 1, limit).astype(int)]
    c = store.cells()
    df = df.copy()
    df["land_use"] = c["land_use"].reindex(df["cell_id"]).to_numpy()
    df["state"] = c["state"].reindex(df["cell_id"]).to_numpy()
    df["district"] = c["district"].reindex(df["cell_id"]).to_numpy()
    df["static_share"] = store.cell_static()["static_share"].reindex(df["cell_id"]).to_numpy()
    df["acq_date"] = df["acq_date"].astype(str)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"]).dt.strftime("%Y-%m-%dT%H:%MZ")
    df["anomaly_type"] = df["anomaly_type"].astype("float")
    return ok({"total_matching": int(total), "returned": int(len(df)), "thinned": bool(total > len(df)), "hotspots": rec(df.drop(columns=["source_file"])),
               "provenance": "Actual Observation", "note": "Original FIRMS records. 'confidence_score' is a standardized ordinal score, not comparable across sensors as a probability."})


@app.get("/api/hotspots/cell-layer", dependencies=[Depends(need_data)])
def cell_layer(ym_from: int, ym_to: int, region: str = "country"):
    """Per-cell activity for a month range: original MODIS, original VIIRS, harmonized VIIRS-equivalent estimate."""
    if ym_to < ym_from:
        raise ValueError("ym_to must be >= ym_from")
    m = store.region_monthly(region)
    m = m[(m["ym"] >= ym_from) & (m["ym"] <= ym_to)]
    ft, p = harmonize.fit(None), harmonize.panel("country")
    c = store.cells()
    ids = np.array([i for i in store.region_cells(region) if i in c.index])
    sidx = {s: i for i, s in enumerate(p.states)}
    st = c.loc[ids, "state"].map(sidx).to_numpy()
    months = [y for y in p.ym if ym_from <= y <= ym_to]
    cov = store.coverage()
    covA = dict(zip(p.ym, cov["Aqua"].to_numpy()))
    moys = np.array([y % 100 - 1 for y in months if covA.get(y, 0) >= 0.5], dtype=int)
    base = ft.sh["a"][0][st][:, moys, :].sum(axis=(1, 2)) if len(moys) else np.zeros(len(ids))
    out = pd.DataFrame({"cell_id": ids, "veq": base}).set_index("cell_id")
    piv = m.pivot_table(index="cell_id", columns="satellite", values="n_veg", aggfunc="sum", observed=True)
    frp = m[m["satellite"] == VIIRS_REFERENCE].groupby("cell_id")["frp_sum"].sum()
    aq = m[m["satellite"] == "Aqua"]
    if len(aq):
        si = c["state"].reindex(aq["cell_id"]).map(sidx).to_numpy()
        okr = ~np.isnan(si)
        di = aq["daynight"].astype(str).map(store.DN).to_numpy()[okr]
        mo = (aq["ym"].to_numpy() % 100 - 1)[okr]
        sii = si[okr].astype(int)
        add = ft.sh["F"][0][sii, mo, di] * aq["n_veg"].to_numpy()[okr] - ft.sh["a"][0][sii, mo, di]
        out["veq"] = out["veq"].add(pd.Series(add, index=aq["cell_id"].to_numpy()[okr]).groupby(level=0).sum(), fill_value=0)
    for s in SATELLITES:
        out[s] = piv[s].reindex(out.index).fillna(0).to_numpy() if s in piv else 0.0
    out["viirs_frp"] = frp.reindex(out.index).fillna(0).to_numpy()
    out["lat"], out["lon"] = grid.cell_center(out.index.to_numpy())
    out = out[(out[SATELLITES].sum(axis=1) > 0) | (out["veq"] > 0.5)].reset_index()
    return ok({"cells": rec(out.round(3)), "months": [int(months[0]), int(months[-1])] if months else None,
               "note": "'veq' is the VIIRS-equivalent estimate derived from Aqua MODIS with the operational calibration. Where S-NPP VIIRS was "
                       "observing, the actual VIIRS count is authoritative and 'veq' is shown only for comparison."})


# --------------------------------------------------------------------------- data management
JOB = {"state": "idle", "step": None, "log": [], "started": None, "finished": None, "error": None}
_job_lock = threading.Lock()


def _run_job(only_new: bool, retrain: bool, rebuild_geo: bool):
    def log(*a):
        JOB["log"] = (JOB["log"] + [" ".join(str(x) for x in a)])[-60:]
    try:
        JOB.update(step="Discovering and standardising datasets")
        res = ingest.process_all(only_new=only_new, log=log)
        errs = {k: v["error"] for k, v in res.items() if v.get("error")}
        if errs:
            log(f"skipped: {errs}")
        if rebuild_geo or not geo.CELLS_PATH.exists():
            JOB.update(step="Building grid, boundaries and land cover")
            geo.build_cells()
        JOB.update(step="Building daily / monthly summaries")
        store.build_summaries(log=log)
        harmonize.clear()
        analytics.clear()
        if retrain or not forecast.available():
            JOB.update(step="Training and calibrating the forecast model")
            forecast.train(log=log)
        JOB.update(step="Fitting harmonization and writing database tables")
        db_sync.sync_all(log=log)
        analytics.clear()
        JOB.update(state="done", step="Complete", finished=datetime.now(timezone.utc).isoformat(), error=None)
    except Exception as exc:
        JOB.update(state="failed", error=f"{type(exc).__name__}: {exc}", finished=datetime.now(timezone.utc).isoformat())
        JOB["log"].append(traceback.format_exc()[-1500:])
    finally:
        _job_lock.release()


def _start_job(only_new, retrain, rebuild_geo=False):
    if not _job_lock.acquire(blocking=False):
        raise HTTPException(409, "A processing job is already running.")
    JOB.update(state="running", step="Starting", log=[], started=datetime.now(timezone.utc).isoformat(), finished=None, error=None)
    threading.Thread(target=_run_job, args=(only_new, retrain, rebuild_geo), daemon=True).start()
    return ok({"started": True, "job": JOB})


@app.post("/api/data/load-repo", dependencies=[Depends(limited("processing"))])
def load_repo(retrain: bool = False, a: Actor = Depends(require())):
    """Scan the repository for FIRMS archives/CSVs, ingest them and rebuild every derived product."""
    return _start_job(only_new=False, retrain=retrain)


@app.post("/api/data/process", dependencies=[Depends(limited("processing"))])
def process(retrain: bool = False, a: Actor = Depends(require())):
    """Ingest only new sources (e.g. fresh uploads), then rebuild summaries and calibrations."""
    return _start_job(only_new=True, retrain=retrain)


@app.get("/api/data/status")
def data_status():
    return ok({"job": JOB, "sources": [{k: v for k, v in s.items() if k != "hint"} | {"processed": s["key"] in ingest.load_registry()} for s in ingest.discover_sources()]})


@app.post("/api/data/upload", dependencies=[Depends(limited("upload"))])
async def upload(file: UploadFile = File(...), satellite: str = Form(...), product_type: str = Form("auto"), a: Actor = Depends(require())):
    if satellite not in SATELLITES:
        raise ValueError(f"satellite must be one of {SATELLITES}")
    if SAT_INSTRUMENT[satellite] == "VIIRS" and product_type not in ("375m", "750m"):
        raise ValueError("for VIIRS uploads state the product: 375m or 750m (they are not interchangeable)")
    if not (file.filename or "").lower().endswith(".csv"):
        raise ValueError("only .csv files are accepted")
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(file.filename).name)
    dest = UPLOADS / name
    size = 0
    with open(dest, "wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > 1_500_000_000:
                fh.close()
                dest.unlink(missing_ok=True)
                raise ValueError("file larger than 1.5 GB")
            fh.write(chunk)
    hint = {"satellite": satellite, "product_type": "1km" if SAT_INSTRUMENT[satellite] == "MODIS" else product_type, "uploaded_by": a.username}
    try:  # validate the header and a sample before accepting
        sample = pd.read_csv(dest, nrows=2000, dtype=ingest.STR_COLS)
        std, q = ingest.standardise(sample, name, {**hint, "origin": "upload"})
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise ValueError(f"file rejected: {exc}")
    dest.with_suffix(".json").write_text(json.dumps(hint))
    return ok({"stored": name, "bytes": size, "sample_quality": q, "sample_satellites": std["satellite"].value_counts().to_dict(),
               "next": "POST /api/data/process to ingest it and rebuild the harmonization."})


@app.get("/api/data/inventory")
def data_inventory(refresh: bool = False):
    """Ingestion / inventory report: archives (LFS status), loaded coverage per satellite, missing periods and blockers."""
    if refresh or not acquire.REPORT_JSON.exists():
        return ok(acquire.build_report())
    return ok(json.loads(acquire.REPORT_JSON.read_text()))


@app.post("/api/data/recover-lfs", dependencies=[Depends(limited("admin"))])
def data_recover_lfs(a: Actor = Depends(require())):
    """Replace Git LFS pointer stubs with the real archives (SHA-256 verified against the pointer)."""
    res = acquire.recover_lfs()
    acquire.build_report()
    return ok({"results": res})


@app.get("/api/data/quality")
def data_quality():
    reg = ingest.load_registry()
    tot = {}
    for v in reg.values():
        for k, n in v["quality"].items():
            tot[k] = tot.get(k, 0) + n
    sp = store.spans() if store.has_data() else {}
    return ok({"datasets": list(reg.values()), "totals": tot,
               "sensors": [{"satellite": s, "label": SAT_LABEL[s], "loaded": s in sp, **({k: v for k, v in sp[s].items() if k != "zero_detection_days"} if s in sp else {}),
                            "zero_detection_days": len(sp[s]["zero_detection_days"]) if s in sp else None} for s in SATELLITES],
               "schema": ingest.STD_COLUMNS,
               "rules": ["Rows are dropped only for invalid coordinates, unparseable date/time or unidentifiable sensor.",
                         "Negative FRP and non-positive scan/track are set to missing; the row is kept.",
                         "Only exact duplicate rows within one source are removed. Detections from different sensors are never merged, however close.",
                         "MODIS confidence 0-100 and VIIRS l/n/h keep their original value; the standardized score is an ordinal convention.",
                         "Runs of whole-domain zero-detection days (>=5 MODIS, >=3 VIIRS) are treated as sensor gaps (missing), not as zero fire."]})


# --------------------------------------------------------------------------- harmonization
@app.get("/api/harmonization/summary", dependencies=[Depends(need_data)])
def harm_summary(region: str = "country", split: Optional[int] = None, product: Optional[str] = None):
    ref = _ref(product)
    df, _ = harmonize.series(region, _split(split), ref=ref)
    ft = harmonize.fit(_split(split), ref=ref)
    return ok({"region": store.region_label(region), "split": split, "series": rec(df), "notes": ft.notes,
               "provenance_counts": df["provenance"].value_counts().to_dict(), "train_years": {"morning_gap": ft.years_mg, "sensor": ft.years_sh},
               "reference_product": harmonize.product_label(ref), "available_products": harmonize.products(),
               "legend": {"actual_viirs": f"Actual {harmonize.product_label(ref)} observation", "sensor_calibrated": "Sensor-calibrated estimate (from actual Aqua MODIS)",
                          "morning_gap_sensor": "Morning-gap-corrected + sensor-calibrated estimate (from Terra MODIS only)", "no_data": "No sensor coverage"},
               "products": {"viirs": harmonize.product_label(ref) + ("" if ref.endswith("750m") else
                                     (". " + (harmonize.products()["viirs_750m_message"] or "A 750 m stream is loaded: pass product=750m."))),
                            "modis": "1 km (MCD14ML, C6.1)"},
               "terra_only_real_months": int(((df["cov_terra"] >= 0.5) & (df["cov_aqua"] < 0.5) & ~df["withheld_aqua"]).sum()),
               "pre_viirs_real_months": int(((df["cov_viirs"] == 0) & (df["modis_total"].notna())).sum())})


@app.get("/api/harmonization/compare", dependencies=[Depends(need_data)])
def harm_compare(region: str = "country"):
    m = store.region_monthly(region)
    chars = []
    for s, g in m.groupby("satellite", observed=True):
        n = g["n"].sum()
        chars.append({"satellite": str(s), "label": SAT_LABEL[str(s)], "instrument": SAT_INSTRUMENT[str(s)], "detections": int(n),
                      "mean_pixel_area_km2": float(g["area_sum"].sum() / n), "low_conf_share": float(g["n_low"].sum() / n), "high_conf_share": float(g["n_high"].sum() / n),
                      "night_share": float(g.loc[g["daynight"].astype(str) == "N", "n"].sum() / n), "mean_frp_mw": float(g["frp_sum"].sum() / max(g["frp_n"].sum(), 1)),
                      "static_share_typed": float(g["n_static"].sum() / g["n_typed"].sum()) if g["n_typed"].sum() else None,
                      "nominal_overpass": harmonize.store.orbit().query("satellite == @s")["baseline"].head(1).round(2).tolist()})
    df, _ = harmonize.series(region)
    both = df[(df["cov_aqua"] >= 0.999) & (df["cov_viirs"] >= 0.999) & ~df["nrt"]]
    yearly = both.groupby("year").agg(terra=("terra", "sum"), aqua=("aqua", "sum"), viirs=("viirs", "sum")).reset_index()
    yearly["viirs_per_aqua"] = yearly["viirs"] / yearly["aqua"].where(yearly["aqua"] > 0)
    yearly["aqua_per_terra"] = yearly["aqua"] / yearly["terra"].where(yearly["terra"] > 0)
    bym = both.groupby("month").agg(terra=("terra", "sum"), aqua=("aqua", "sum"), viirs=("viirs", "sum")).reset_index()
    bym["viirs_per_aqua"] = bym["viirs"] / bym["aqua"].where(bym["aqua"] > 0)
    return ok({"region": store.region_label(region), "characteristics": chars, "yearly": rec(yearly), "by_month": rec(bym),
               "pairs": rec(both[["date", "terra", "aqua", "viirs"]]), "scatter": harmonize.scatter("sh"),
               "warning": "The ratio changes with season, region and day/night. A single conversion factor - or adding the two counts - is wrong.",
               "orbit": rec(store.orbit())})


@app.get("/api/morning-gap/analysis", dependencies=[Depends(need_data)])
def mg_analysis(region: str = "country", state: Optional[str] = None, split: Optional[int] = None):
    df, _ = harmonize.series(region, _split(split))
    ov = df[(df["cov_terra"] >= 0.999) & (df["cov_aqua"] >= 0.999)]
    real_months = int(((df["cov_terra"] >= 0.5) & (df["cov_aqua"] < 0.5) & ~df["withheld_aqua"]).sum())
    return ok({"region": store.region_label(region), "calibration": harmonize.calibration_table("mg", _split(split), state),
               "series": rec(df[["date", "ym", "terra", "aqua", "terra_day", "terra_night", "aqua_day", "aqua_night", "aqua_est", "aqua_est_lo", "aqua_est_hi",
                                 "withheld_aqua", "cov_terra", "cov_aqua", "train_morning_gap"]]),
               "share_months_aqua_below_terra": float((ov["aqua"] < ov["terra"]).mean()) if len(ov) else None,
               "share_months_aqua_night_below_terra_night": float((ov["aqua_night"] < ov["terra_night"]).mean()) if len(ov) else None,
               "orbit": rec(store.orbit()[store.orbit()["satellite"].isin(["Terra", "Aqua"])]),
               "state_factors": harmonize.state_factors("mg", _split(split)), "scatter": harmonize.scatter("mg", _split(split)),
               "terra_only_real_months": real_months,
               "mode": "real_correction" if real_months else "simulated_only",
               "mode_message": None if real_months else ("No Terra-only months (FIRMS: Nov 2000 - Jun 2002) are loaded, so the real historical "
                                                         "correction cannot be applied. Results labelled 'simulated' hide real Aqua months to test the method."),
               "by_daynight_overlap": {dn: {"terra": float(ov[f"terra_{dn}"].sum()), "aqua": float(ov[f"aqua_{dn}"].sum()),
                                            "aqua_per_terra": float(ov[f"aqua_{dn}"].sum() / ov[f"terra_{dn}"].sum()) if ov[f"terra_{dn}"].sum() else None}
                                       for dn in ("day", "night")},
               "note": "The relationship is learned, not assumed: night-time Aqua (01:30) sees far fewer fires than night-time Terra (22:30), and in monsoon "
                       "months day-time Aqua can be below Terra. Estimated Aqua values are statistical estimates, not satellite detections."})


class RunBody(BaseModel):
    region: str = "country"
    split: Optional[int] = Field(None, description="YYYYMM. Train only on months >= split and treat earlier months as unseen.")


@app.post("/api/morning-gap/correct", dependencies=[Depends(need_data)])
def mg_correct(body: RunBody):
    sp = _split(body.split) or harmonize.default_split()
    df, _ = harmonize.series(body.region, sp)
    v = harmonize.validation(body.region, sp)
    real, _ = harmonize.series(body.region, None)
    real_to = real[(real["cov_terra"] >= 0.5) & (real["cov_aqua"] < 0.5)].copy()
    aqua_first = (store.spans().get("Aqua") or {}).get("first", "9999")
    real_to["kind"] = np.where(real_to["date"] < aqua_first, "pre_aqua_era", "aqua_outage")
    sim = df[df["withheld_aqua"]][["date", "terra", "aqua", "aqua_est", "aqua_est_lo", "aqua_est_hi"]].copy()
    sim["difference"] = sim["aqua_est"] - sim["terra"]
    return ok({"region": store.region_label(body.region), "split": sp, "terra_only_end": harmonize.fit(sp).terra_only_end,
               "real_terra_only_period": rec(real_to[["date", "kind", "terra", "aqua_est", "aqua_est_lo", "aqua_est_hi"]]),
               "real_terra_only_months": {"pre_aqua_era": int((real_to["kind"] == "pre_aqua_era").sum()), "aqua_outage": int((real_to["kind"] == "aqua_outage").sum())},
               "real_terra_only_message": None if len(real_to) else "The loaded MODIS record contains no Terra-only months. "
                                                                    "Upload MODIS C6.1 data from Nov 2000 to correct the real Terra-only era.",
               "simulated": rec(sim), "simulated_validation": v.get("morning_gap"),
               "label": "Morning-Gap Corrected Estimate - a statistical estimate of afternoon (Aqua) activity, NOT satellite detections."})


@app.get("/api/sensor-harmonizer/calibration", dependencies=[Depends(need_data)])
def sh_calibration(state: Optional[str] = None, split: Optional[int] = None, product: Optional[str] = None):
    ref = _ref(product)
    pr = harmonize.products()
    return ok({"calibration": harmonize.calibration_table("sh", _split(split), state, ref), "state_factors": harmonize.state_factors("sh", _split(split), ref),
               "scatter": harmonize.scatter("sh", _split(split), ref=ref), "products": pr,
               "product_note": (f"Calibration target: {harmonize.product_label(ref)}. 375 m and 750 m are calibrated separately and never pooled. "
                                + (pr["viirs_750m_message"] or "")),
               "other_viirs": "NOAA-20 / NOAA-21 detections are kept as separate actual observations and are never pooled into the S-NPP reference record."})


@app.post("/api/sensor-harmonizer/process", dependencies=[Depends(need_data)])
def sh_process(body: RunBody):
    df, _ = harmonize.series(body.region, _split(body.split))
    yearly = df.groupby("year").agg(harmonized=("harmonized", lambda x: x.sum(min_count=1)), lo=("harm_lo", lambda x: x.sum(min_count=1)),
                                    hi=("harm_hi", lambda x: x.sum(min_count=1)), viirs=("viirs", lambda x: x.sum(min_count=1)),
                                    modis=("modis_total", lambda x: x.sum(min_count=1)), months=("ym", "size"),
                                    estimated=("provenance", lambda x: int((x != "actual_viirs").sum()))).reset_index()
    return ok({"region": store.region_label(body.region), "split": body.split, "timeline": rec(df[["date", "ym", "terra", "aqua", "viirs", "aqua_est", "veq", "veq_lo", "veq_hi",
                                                                                             "harmonized", "harm_lo", "harm_hi", "provenance", "withheld_viirs", "nrt"]]),
               "yearly": rec(yearly), "notes": harmonize.fit(_split(body.split)).notes})


@app.get("/api/uncertainty", dependencies=[Depends(need_data)])
def uncertainty(region: str = "country", split: Optional[int] = None):
    sp = _split(split)
    df, _ = harmonize.series(region, sp)
    df = df.copy()
    df["rel_width"] = (df["veq_hi"] - df["veq_lo"]) / df["veq"].where(df["veq"] > 0)
    est = df[df["veq"].notna()]
    by_prov = est.assign(stage=np.where(est["withheld_aqua"] | (est["provenance"] == "morning_gap_sensor"), "Terra-only (morning-gap + sensor)",
                                        "Aqua-based (sensor calibration)")).groupby("stage")["rel_width"].median().to_dict()
    by_year = est.groupby("year").agg(rel_width=("rel_width", "median"), coverage=("cov_aqua", "mean")).reset_index()
    by_month = est.groupby("month")["rel_width"].median().reset_index()
    ft = harmonize.fit(sp)
    weak = [r for w in ("mg", "sh") for r in [{**x, "pair": w} for x in harmonize.calibration_table(w, sp)["by_month"]] if not r["reliable"]]
    v = harmonize.validation(region, sp or harmonize.default_split())
    return ok({"region": store.region_label(region), "split": sp,
               "series": rec(df[["date", "ym", "veq", "veq_lo", "veq_hi", "rel_width", "provenance", "withheld_aqua", "withheld_viirs", "viirs", "cov_terra", "cov_aqua", "cov_viirs"]]),
               "median_relative_width_by_stage": by_prov, "by_year": rec(by_year), "by_month": rec(by_month), "weak_calibrations": weak, "notes": ft.notes,
               "band_coverage_pct": v.get("band_coverage_pct"), "morning_gap_band_coverage_pct": (v.get("morning_gap") or {}).get("band_coverage_pct"),
               "method": ["Calibration years are resampled with replacement as whole years (block bootstrap, %d resamples); both the Terra->Aqua and the Aqua->VIIRS relationship are re-fitted each time." % harmonize.BOOTSTRAP_N,
                          "Each replicate also draws an out-of-sample (leave-one-year-out) residual matched to the size of the estimate, so the band covers month-to-month scatter, not only parameter noise.",
                          "For Terra-only months the two steps are chained, so both sources of error accumulate.",
                          "Months with partial sensor coverage are scaled by coverage and their residual spread is inflated by 1/sqrt(coverage).",
                          "The band is the 5th-95th percentile of replicates. It is a resampling range, not a formal confidence interval and not a guarantee; its empirical coverage on withheld data is reported above."]})


@app.get("/api/validation", dependencies=[Depends(need_data)])
def validation(region: str = "country", split: Optional[int] = None, product: Optional[str] = None):
    return ok(harmonize.validation(region, _split(split), _ref(product)))


@app.get("/api/validation/seam-test", dependencies=[Depends(need_data)])
def seam(region: str = "country", split: Optional[int] = None, window: int = Query(24, ge=12, le=60), product: Optional[str] = None):
    return ok(harmonize.seam_test(region, _split(split), window, _ref(product)))


@app.get("/api/validation/model-selection", dependencies=[Depends(need_data)])
def model_selection(stage: str = Query("mg", pattern="^(mg|sh)$"), product: Optional[str] = None):
    """Held-out comparison of calibration model forms (LOYO, 20-month block, rolling origin) and the selection decision."""
    return ok(harmonize.model_selection(stage, _ref(product)))


@app.get("/api/morning-gap/sensitivity", dependencies=[Depends(need_data)])
def mg_sensitivity(product: Optional[str] = None):
    """Real Terra-only era: Aqua-equivalent totals by model form (structural sensitivity; no ground truth exists)."""
    return ok(harmonize.terra_only_sensitivity(_ref(product)) or {"status": "unavailable"})


@app.get("/api/validation/seam-robustness", dependencies=[Depends(need_data)])
def seam_robust(product: Optional[str] = None):
    return ok(harmonize.seam_robustness(_ref(product)))


@app.get("/api/validation/extrapolation-stress-test", dependencies=[Depends(need_data)])
def stress_test(product: Optional[str] = None):
    return ok(harmonize.extrapolation_stress_test(_ref(product)) or {"status": "unavailable"})


@app.get("/api/harmonization/products", dependencies=[Depends(need_data)])
def harm_products():
    return ok(harmonize.products())


# --------------------------------------------------------------------------- analysis modules
@app.get("/api/calendar", dependencies=[Depends(need_data)])
def calendar(region: str = "country", year: Optional[int] = None):
    return ok(analytics.calendar(region, year or analytics.data_end().year))


@app.get("/api/historical-trends", dependencies=[Depends(need_data)])
def trends(region: str = "country"):
    return ok(analytics.trends(region))


@app.get("/api/historical-trends/regions", dependencies=[Depends(need_data)])
def trends_regions(level: str = Query("state", pattern="^(state|district)$")):
    return ok({"level": level, "sensor": "S-NPP VIIRS 375 m (actual observations, complete years only)", "items": analytics.regional_comparison(level)[:150]})


@app.get("/api/anomalies", dependencies=[Depends(need_data)])
def anomalies(region: str = "country", level: str = Query("state", pattern="^(state|district)$"), window_days: int = Query(30, ge=7, le=90)):
    return ok({"series": analytics.anomaly_series(region), "current": analytics.anomalies_now(window_days, level)})


@app.get("/api/critical-regions", dependencies=[Depends(need_data)])
def critical(top: int = Query(60, ge=1, le=300)):
    out = analytics.critical_regions(top)
    contacts = alerts.load_contacts()
    items = [{**it, "authorities": alerts.route(it["state"], it["district_id"], it["land_use"], contacts)} for it in out.get("items", [])]
    return ok({**out, "items": items})


@app.get("/api/critical-regions/sensitivity", dependencies=[Depends(need_data)])
def critical_sensitivity(top: int = Query(20, ge=5, le=100)):
    return ok(analytics.critical_sensitivity(top))


@app.get("/api/critical-regions/weights")
def critical_weights():
    from . import critical_scoring as CS
    return ok({"active": CS.active_weights(), "profiles": CS.PROFILES, "components": CS.COMPONENTS, "labels": CS.LABELS})


class WeightsBody(BaseModel):
    weights: dict[str, float]
    note: str = Field("", max_length=300)


@app.put("/api/critical-regions/weights")
def critical_weights_set(body: WeightsBody, a: Actor = Depends(require())):
    from . import critical_scoring as CS
    rec = CS.set_weights(body.weights, a.username, body.note)
    with M.Session() as s:
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="CRITICAL_WEIGHTS_SET", entity="critical_weights", entity_id=rec["version"], detail=rec))
        s.commit()
    analytics.clear()
    return ok(rec)


@app.delete("/api/critical-regions/weights")
def critical_weights_reset(a: Actor = Depends(require())):
    from . import critical_scoring as CS
    CS.reset_weights()
    analytics.clear()
    return ok(CS.active_weights())


@app.get("/api/infrastructure/linear/status")
def linear_status():
    from . import linear_gis
    return ok(linear_gis.status())


@app.get("/api/infrastructure/nearest")
def linear_nearest(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
                   category: str = Query("road_major"), max_km: float = Query(50, gt=0, le=200)):
    from . import linear_gis
    return ok(linear_gis.nearest(lat, lon, category, max_km))


@app.get("/api/infrastructure/within")
def linear_within(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
                  radius_km: float = Query(10, gt=0, le=100), category: str = Query("road_major")):
    from . import linear_gis
    if category not in linear_gis.CATEGORIES:
        raise ValueError(f"category must be one of {list(linear_gis.CATEGORIES)}")
    return ok(linear_gis.within(lat, lon, radius_km, category))


@app.get("/api/viirs750/search")
def viirs750_search(satellite: str = Query("NOAA-21"), start: str = Query(...), end: str = Query(...), limit: int = Query(50, ge=1, le=500)):
    """Public CMR granule search (no login). Network failures are reported, never replaced with made-up granules."""
    from . import viirs750
    try:
        g = viirs750.search(satellite, start, end, max_pages=5)
    except ValueError:
        raise
    except Exception as exc:
        return ok({"status": "search_failed", "error": viirs750._redact(f"{type(exc).__name__}: {exc}"), "granules": []})
    return ok({"status": "ok", "satellite": satellite, "count": len(g), "granules": g[:limit], "truncated": len(g) > limit,
               "credentials": viirs750.credentials_status()})


# --------------------------------------------------------------------------- background data jobs
class JobBody(BaseModel):
    kind: str = Field(max_length=60)
    params: dict = Field(default_factory=dict)
    idempotency_key: Optional[str] = Field(default=None, max_length=160)


@app.get("/api/jobs")
def jobs_list(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), status: Optional[str] = Query(None, max_length=20),
              kind: Optional[str] = Query(None, max_length=60), a: Actor = Depends(require("gov_officer", "analyst"))):
    from . import jobs
    return ok({"items": jobs.listing(limit, offset, status, kind), "kinds": jobs.KINDS, "limit": limit, "offset": offset})


@app.post("/api/jobs", dependencies=[Depends(limited("processing"))])
def jobs_submit(body: JobBody, a: Actor = Depends(require())):
    from . import jobs
    return ok(jobs.submit(body.kind, body.params, a.username, idempotency_key=body.idempotency_key))


@app.get("/api/jobs/{job_id}")
def jobs_get(job_id: int, a: Actor = Depends(require("gov_officer", "analyst"))):
    from . import jobs
    return ok(jobs.get(job_id))


@app.post("/api/jobs/{job_id}/cancel")
def jobs_cancel(job_id: int, a: Actor = Depends(require())):
    from . import jobs
    return ok(jobs.cancel(job_id, a.username))


@app.get("/api/viirs750/credentials")
def viirs750_credentials():
    """Configured / method / last access only. Never returns the token or netrc contents."""
    from . import viirs750
    return ok(viirs750.credentials_status())


@app.get("/api/observations/quality", dependencies=[Depends(need_data)])
def obs_quality(region: str = "country", days: int = Query(30, ge=7, le=120)):
    return ok(analytics.observation_quality(region, days))


@app.get("/api/observations/alternatives", dependencies=[Depends(need_data)])
def obs_alternatives(days: int = Query(30, ge=7, le=120)):
    return ok(analytics.observation_cells(days))


@app.get("/api/observations/overpasses", dependencies=[Depends(need_data)])
def obs_overpasses():
    return ok(analytics.overpasses())


@app.get("/api/validation/noaa21", dependencies=[Depends(need_data)])
def validation_noaa21():
    """NOAA-21 -> S-NPP cross-calibration study with a declared acceptance rule."""
    from . import noaa21
    return ok(noaa21.study())


@app.get("/api/forecast/comparison")
def forecast_comparison():
    """Candidate-model comparison, rolling origins, breakdowns and model cards (python -m app.forecast_eval)."""
    from . import forecast_eval
    r = forecast_eval.load()
    if not r:
        return ok({"status": "unavailable", "how": "python -m app.forecast_eval"})
    return ok(r)


@app.get("/api/viirs750/status")
def viirs750_status():
    from . import viirs750
    return ok(viirs750.status() | {"products": harmonize.products()})


@app.get("/api/exposure/layers")
def exposure_layers():
    from . import exposure
    return ok(exposure.layers())


@app.get("/api/exposure/point")
def exposure_point(lat: float = Query(..., ge=6, le=36), lon: float = Query(..., ge=68, le=98), radius_km: float = Query(10, ge=5, le=50)):
    from . import exposure
    return ok(exposure.point(lat, lon, radius_km))


@app.get("/api/exposure/hotspots", dependencies=[Depends(need_data)])
def exposure_hotspots(days: int = Query(7, ge=1, le=30), radius_km: float = Query(5, ge=5, le=50), region: str = "country",
                      top: int = Query(25, ge=1, le=200)):
    from . import exposure
    return ok(exposure.hotspots(days, radius_km, region, top))


@app.get("/api/exposure/regions", dependencies=[Depends(need_data)])
def exposure_regions():
    from . import exposure
    return ok(exposure.regions())


@app.get("/api/gis/population")
def gis_population(region: str = "country", min_density: float = Query(0, ge=0)):
    from . import exposure
    return ok(exposure.population_layer(region, min_density))


@app.get("/api/gis/infrastructure")
def gis_infrastructure(category: Optional[str] = None, bbox: Optional[str] = None, limit: int = Query(5000, ge=1, le=20000)):
    from . import exposure, infrastructure
    if category and category not in infrastructure.CATEGORIES:
        raise HTTPException(400, f"category must be one of {list(infrastructure.CATEGORIES)}")
    box = None
    if bbox:
        try:
            box = [float(x) for x in bbox.split(",")]
            assert len(box) == 4
        except (ValueError, AssertionError):
            raise HTTPException(400, "bbox must be w,s,e,n")
    return ok(exposure.infrastructure_layer(category, box, limit))


@app.post("/api/admin/audit-retention", dependencies=[Depends(limited("admin"))])
def audit_retention(dry_run: bool = True, days: Optional[int] = Query(None, ge=30, le=3650), a: Actor = Depends(require())):
    """Archive-then-prune routine audit rows older than the retention period. Dry run by default."""
    from . import retention
    return ok(retention.prune_audit(days, dry_run=dry_run))


@app.get("/api/orbits/status")
def orbits_status():
    """Cached TLEs with freshness and the SGP4-vs-observed-detection validation."""
    from . import orbits
    tles = {}
    for sat in orbits.SATS:
        r = orbits.load_tle(sat)
        tles[sat] = ({k: r[k] for k in ("catnr", "name", "epoch", "source", "acquired")} | orbits.freshness(r)) if r else None
    return ok({"tles": tles, "last_refresh": orbits.last_refresh(), "validation": orbits.validation_summary(), "stale_after_days": orbits.STALE_DAYS,
               "meaning": "Predicted passes are observation opportunities, not fire predictions."})


@app.get("/api/orbits/passes")
def orbits_passes(satellite: str = Query(...), lat: Optional[float] = Query(None, ge=-90, le=90),
                  lon: Optional[float] = Query(None, ge=-180, le=180), region: Optional[str] = None,
                  start: Optional[str] = None, hours: float = Query(48, gt=0, le=240)):
    from . import orbits
    if satellite not in orbits.SATS:
        raise HTTPException(400, f"satellite must be one of {list(orbits.SATS)}")
    if lat is None or lon is None:
        if not region:
            raise HTTPException(400, "give lat & lon, or a region id")
        bb = store.region_bbox(region)
        if bb is None:
            raise HTTPException(404, "unknown or empty region")
        lon, lat = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    try:
        t0 = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else datetime.now(timezone.utc)
    except ValueError:
        raise HTTPException(400, "start must be ISO-8601")
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    res = orbits.passes(satellite, float(lat), float(lon), t0, hours)
    res["validation"] = orbits.validation_summary().get(satellite)
    return ok(res)


@app.post("/api/orbits/refresh", dependencies=[Depends(limited("admin"))])
def orbits_refresh(a: Actor = Depends(require())):
    from . import orbits
    res = orbits.refresh_all(log=lambda *_: None)
    with M.Session() as s:
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="TLE_REFRESH", entity="orbits", entity_id="celestrak"))
        s.commit()
    return ok(res)


# --------------------------------------------------------------------------- forecast
class ForecastBody(BaseModel):
    region_id: Optional[str] = None
    bbox: Optional[list[float]] = Field(None, min_length=4, max_length=4, description="west, south, east, north")
    issue_date: Optional[str] = None

    @model_validator(mode="after")
    def _one(self):
        if not self.region_id and not self.bbox:
            raise ValueError("give region_id or bbox")
        return self


@app.get("/api/forecast/model")
def forecast_model():
    if not forecast.available():
        return ok({"available": False, "message": "No trained model. Train it from Data Management; PyroScope never shows untrained or random forecasts."})
    return ok({"available": True, **forecast.meta(), "models_available": forecast.models_available()})


@app.get("/api/forecast/models")
def forecast_models():
    """Model card summary for every independently trained target sensor."""
    out = []
    for snr in forecast.models_available():
        m = forecast._meta(snr)
        out.append({"reference_sensor": snr, "model_version": m.get("model_version"), "trained_at": m.get("trained_at"), "target": m.get("target"),
                    "split": m.get("split"), "rows": m.get("rows"), "issue_date": m.get("issue_date"), "serving_status": m.get("serving_status"),
                    "evaluation": m.get("evaluation") or {k: m.get("test", {}).get(k) for k in ("brier", "roc_auc", "pr_auc")},
                    "baseline_climatology": m.get("baseline_climatology", {}).get("brier"), "breakdowns": m.get("breakdowns"),
                    "reliability": m.get("reliability"), "nrt_in_labels": m.get("nrt_in_labels"), "legacy": forecast.SENSOR_CONFIG[snr].get("legacy", False)})
    return ok({"items": out, "served_by_default": forecast.active_sensor(),
               "rule": "Each model is trained, calibrated and tested only on its own sensor; calibrators are never transferred."})


# --------------------------------------------------------------------------- operational reference (S-NPP cessation)
@app.get("/api/reference/operational")
def reference_operational():
    return ok(operational.summary())


class OpRefBody(BaseModel):
    platform: Optional[str] = Field(None, description="NOAA-21 | NOAA-20 | null to revert to the evidence default")
    reason: str = Field(min_length=5, max_length=500)


@app.put("/api/reference/operational")
def reference_operational_select(body: OpRefBody, a: Actor = Depends(require())):
    return ok(operational.select(body.platform, a.username, a.role, body.reason))


@app.get("/api/reference/transition")
def reference_transition(window: int = Query(12, ge=3, le=24)):
    return ok(operational.transition_report(window))


@app.get("/api/reference/bridges")
def reference_bridges():
    return ok(bridge.studies())


@app.get("/api/reference/platform/{sensor}")
def reference_platform(sensor: str):
    if sensor not in SATELLITES:
        raise KeyError(sensor)
    return ok(operational.evaluate(sensor))


@app.get("/api/forecast/ranking", dependencies=[Depends(need_data)])
def forecast_ranking(level: str = Query("district", pattern="^(state|district)$"), top: int = Query(50, ge=1, le=300)):
    return ok({"level": level, "items": risk.ranking(level, top)})


@app.get("/api/forecast/cell/{cell_id}", dependencies=[Depends(need_data)])
def forecast_cell(cell_id: int):
    return ok(risk.cell_detail(cell_id))


@app.post("/api/forecast", dependencies=[Depends(need_data)])
def forecast_post(body: ForecastBody):
    rid = body.region_id or "bbox:" + ",".join(str(x) for x in body.bbox)
    return ok(risk.region_forecast(rid, body.issue_date))


@app.get("/api/forecast/{region_id:path}/grid-cells", dependencies=[Depends(need_data)])
def forecast_cells(region_id: str, issue_date: Optional[str] = None):
    return ok(risk.grid_cells(region_id, issue_date))


@app.get("/api/forecast/{region_id:path}", dependencies=[Depends(need_data)])
def forecast_get(region_id: str, issue_date: Optional[str] = None):
    return ok(risk.region_forecast(region_id, issue_date))


# --------------------------------------------------------------------------- thresholds / jurisdictions / authorities
class ThresholdBody(BaseModel):
    scope_type: str = Field("default", pattern="^(default|land_use|state)$")
    scope_value: Optional[str] = None
    watch: float = Field(0.20, gt=0, lt=1)
    moderate: float = Field(0.40, gt=0, lt=1)
    high: float = Field(0.60, gt=0, lt=1)
    very_high: float = Field(0.80, gt=0, lt=1)
    cooldown_hours: int = Field(72, ge=0, le=24 * 30)
    evidence_min: int = Field(2, ge=0, le=6)
    rationale: Optional[str] = None

    @model_validator(mode="after")
    def _order(self):
        if not (self.watch < self.moderate < self.high < self.very_high):
            raise ValueError("thresholds must increase: watch < moderate < high < very_high")
        if self.scope_type != "default" and not self.scope_value:
            raise ValueError("scope_value is required for land_use / state scopes")
        return self


@app.get("/api/thresholds/config")
def thresholds_get():
    cfgs = alerts.get_configs()
    out = {"configs": [{**c, "tiers": alerts.tiers_view(c)} for c in cfgs],
           "governance": "Configurable prototype starting thresholds (60% authority notification, 80% urgent escalation). They are NOT official statutory "
                         "thresholds. Tune them per region / land use against the false-alarm vs missed-event trade-off below and the authority's own procedures.",
           "precedence": "state override > land-use override > default"}
    if forecast.available():
        m = forecast.meta()
        out["validation_at_thresholds"] = {"overall": m["test"]["confusion"], "by_land_use": {k: v["confusion"] for k, v in m.get("test_by_land_use", {}).items()},
                                           "period": m["split"], "brier": m["test"]["brier"], "roc_auc": m["test"]["roc_auc"]}
    return ok(out)


@app.put("/api/thresholds/config")
def thresholds_put(body: ThresholdBody, a: Actor = Depends(require())):
    val = None if body.scope_type == "default" else body.scope_value
    with M.Session() as s:
        c = s.scalar(select(M.ThresholdConfig).where(M.ThresholdConfig.scope_type == body.scope_type, M.ThresholdConfig.scope_value.is_(val) if val is None else M.ThresholdConfig.scope_value == val))
        before = alerts._cfg_dict(c) if c else None
        if c is None:
            c = M.ThresholdConfig(scope_type=body.scope_type, scope_value=val)
            s.add(c)
        for k in ("watch", "moderate", "high", "very_high", "cooldown_hours", "evidence_min", "rationale"):
            setattr(c, k, getattr(body, k))
        c.updated_by, c.updated_at = a.username, M.now()
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="THRESHOLDS_UPDATED", entity="threshold_config", entity_id=f"{body.scope_type}:{val}",
                         detail={"before": before, "after": body.model_dump()}))
        s.commit()
    return thresholds_get()


@app.delete("/api/thresholds/config/{config_id}")
def thresholds_delete(config_id: int, a: Actor = Depends(require())):
    with M.Session() as s:
        c = s.get(M.ThresholdConfig, config_id)
        if c is None:
            raise KeyError(config_id)
        if c.scope_type == "default":
            raise ValueError("the default configuration cannot be deleted")
        s.delete(c)
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="THRESHOLDS_DELETED", entity="threshold_config", entity_id=str(config_id)))
        s.commit()
    return thresholds_get()


@app.get("/api/jurisdictions/resolve", dependencies=[Depends(need_data)])
def jurisdiction(lat: Optional[float] = Query(None, ge=-90, le=90), lon: Optional[float] = Query(None, ge=-180, le=180), cell_id: Optional[int] = None):
    if cell_id is None and (lat is None or lon is None):
        raise ValueError("give lat & lon, or cell_id")
    return ok(alerts.resolve_jurisdiction(lat, lon, cell_id))


class ContactBody(BaseModel):
    land_use: str
    state: str
    district_id: Optional[str] = None
    authority: str = Field(min_length=3, max_length=160)
    role_title: str = Field(min_length=3, max_length=160)
    level: int = Field(1, ge=1, le=3)
    contact_name: Optional[str] = Field(None, max_length=160)
    contact_channel: str = Field("in-app", pattern="^(in-app|sms|email|webhook)$")
    contact_value: Optional[str] = Field(None, max_length=200)
    confirm_verified: bool = Field(False, description="Administrator attests the contact was verified with the authority.")

    @model_validator(mode="after")
    def _check_address(self):
        v = (self.contact_value or "").strip()
        if self.contact_channel == "email" and not notify.EMAIL_RE.match(v):
            raise ValueError("email channel needs a valid email address")
        if self.contact_channel == "webhook" and not v.startswith("https://"):
            raise ValueError("webhook channel needs an https:// URL")
        if self.contact_channel == "sms" and not re.fullmatch(r"\+?[0-9 ()-]{7,20}", v):
            raise ValueError("sms channel needs a phone number")
        return self


# --------------------------------------------------------------------------- GIS coverage & administrator layers
@app.get("/api/geo/coverage")
def geo_coverage():
    return ok(gis_layers.coverage())


class LayerBody(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    land_use: str
    source: str = Field(min_length=3, max_length=300, description="Dataset / issuing authority (provenance is mandatory)")
    licence: Optional[str] = Field(None, max_length=120)
    source_date: Optional[str] = Field(None, max_length=40)
    geojson: dict


@app.post("/api/jurisdictions/layers", dependencies=[Depends(limited("upload"))])
def layers_add(body: LayerBody, a: Actor = Depends(require())):
    if body.land_use not in geo.LAND_USE_CLASSES:
        raise ValueError(f"land_use must be one of {geo.LAND_USE_CLASSES}")
    ids = gis_layers.cells_in_geojson(body.geojson)
    with M.Session() as s:
        l = M.JurisdictionLayer(name=body.name, land_use=body.land_use, source=body.source, licence=body.licence, source_date=body.source_date,
                                geojson=body.geojson, n_cells=len(ids), cell_ids=ids, uploaded_by=a.username)
        s.add(l)
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="JURISDICTION_LAYER_ADDED", entity="jurisdiction_layer", entity_id=body.name,
                         detail={"land_use": body.land_use, "n_cells": len(ids), "source": body.source}))
        s.commit()
        lid = l.id
    store.clear_caches(); analytics.clear()
    return ok({"id": lid, "n_cells": len(ids), "land_use": body.land_use})


@app.delete("/api/jurisdictions/layers/{layer_id}")
def layers_delete(layer_id: int, a: Actor = Depends(require())):
    with M.Session() as s:
        l = s.get(M.JurisdictionLayer, layer_id)
        if l is None:
            raise KeyError(layer_id)
        s.delete(l)
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="JURISDICTION_LAYER_REMOVED", entity="jurisdiction_layer", entity_id=str(layer_id)))
        s.commit()
    store.clear_caches(); analytics.clear()
    return ok({"deleted": layer_id})


@app.post("/api/geo/exposure", dependencies=[Depends(limited("upload"))])
async def exposure_upload(kind: str = Form(...), source: str = Form(..., min_length=3), licence: Optional[str] = Form(None),
                          source_date: Optional[str] = Form(None), file: UploadFile = File(...), a: Actor = Depends(require())):
    if not (file.filename or "").lower().endswith(".csv"):
        raise ValueError("only .csv files are accepted")
    raw = await file.read(200_000_001)
    if len(raw) > 200_000_000:
        raise ValueError("file larger than 200 MB")
    import io
    meta = gis_layers.save_exposure(kind, pd.read_csv(io.BytesIO(raw), dtype=str), source, licence, source_date, a.username)
    analytics.clear()
    return ok(meta)


class CustomRegionBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    geojson: dict


@app.post("/api/regions/custom", dependencies=[Depends(need_data)])
def region_custom(body: CustomRegionBody):
    return ok(store.add_custom_region(body.name, body.geojson))


# --------------------------------------------------------------------------- notifications
@app.get("/api/notifications/status")
def notifications_status():
    return ok(notify.status())


@app.get("/api/notifications/checklist")
def notifications_checklist(a: Actor = Depends(require())):
    from . import system_config
    return ok({"steps": system_config.notification_checklist(), "issues": system_config.notification_issues(), "provider": notify.status()})


@app.get("/api/notifications/check")
def notifications_check(a: Actor = Depends(require())):
    """Admin: validate the configured provider without sending (SMTP connect / TLS / login / NOOP)."""
    return ok(notify.check_connection())


@app.post("/api/notifications/test/{contact_id}", dependencies=[Depends(limited("admin"))])
def notifications_test(contact_id: int, a: Actor = Depends(require())):
    """Admin: send one clearly labelled TEST message to one verified contact. Not an alert."""
    with M.Session() as s:
        c = s.get(M.AuthorityContact, contact_id)
        if c is None:
            raise HTTPException(404, "contact not found")
        res = notify.send_test(c, a.username)
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="NOTIFICATION_TEST", entity="contact", entity_id=str(contact_id),
                         detail={k: v for k, v in res.items() if k != "error"} | {"error": (res.get("error") or "")[:200]}))
        s.commit()
    return ok(res)


@app.get("/api/notifications/log")
def notifications_log(alert_id: Optional[str] = None, limit: int = Query(200, ge=1, le=1000), a: Actor = Depends(require("gov_officer"))):
    return ok({"items": notify.log(alert_id, limit), "provider": notify.status()})


@app.get("/api/authorities")
def authorities(a: Actor = Depends(actor)):
    with M.Session() as s:
        rows = list(s.scalars(select(M.AuthorityContact).order_by(M.AuthorityContact.land_use, M.AuthorityContact.level)))
    show = a.role in ("admin", "gov_officer")
    return ok({"items": [{"id": r.id, "land_use": r.land_use, "state": r.state, "district_id": r.district_id, "authority": r.authority, "role_title": r.role_title,
                          "level": r.level, "is_template": r.is_template, "verified": r.verified, "contact_channel": r.contact_channel,
                          "contact_name": r.contact_name if show else None, "contact_value": r.contact_value if show else None, "verified_by": r.verified_by} for r in rows],
               "note": "Templates list the responsible ROLES only. PyroScope ships with no contact details; an administrator must register and verify each one. "
                       "All deliveries in this prototype are simulated in-app entries regardless of the stored channel."})


@app.post("/api/authorities")
def authorities_add(body: ContactBody, a: Actor = Depends(require())):
    if body.land_use not in geo.LAND_USE_CLASSES:
        raise ValueError(f"land_use must be one of {geo.LAND_USE_CLASSES}")
    if not body.confirm_verified:
        raise ValueError("a contact can only be registered once an administrator confirms it has been verified")
    with M.Session() as s:
        c = M.AuthorityContact(**body.model_dump(exclude={"confirm_verified"}), verified=True, verified_by=a.username, verified_at=M.now(), is_template=False)
        s.add(c)
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="AUTHORITY_CONTACT_VERIFIED", entity="authority_contact", entity_id=f"{body.state}/{body.land_use}/{body.role_title}"))
        s.commit()
        return ok({"id": c.id})


@app.delete("/api/authorities/{contact_id}")
def authorities_delete(contact_id: int, a: Actor = Depends(require())):
    with M.Session() as s:
        c = s.get(M.AuthorityContact, contact_id)
        if c is None or c.is_template:
            raise KeyError(contact_id)
        s.delete(c)
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="AUTHORITY_CONTACT_REMOVED", entity="authority_contact", entity_id=str(contact_id)))
        s.commit()
    return ok({"deleted": contact_id})


# --------------------------------------------------------------------------- alerts
class EvaluateBody(BaseModel):
    issue_date: Optional[str] = None
    include_detections: bool = True


class ActionBody(BaseModel):
    note: Optional[str] = Field(None, max_length=1000)


@app.get("/api/alerts")
def alerts_list(alert_type: Optional[str] = None, status: Optional[str] = None, state: Optional[str] = None, land_use: Optional[str] = None,
                tier: Optional[str] = None, open_only: bool = False, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
    return ok({**alerts.list_alerts(alert_type, status, state, land_use, tier, open_only, limit, offset),
               "categories": ["Predicted Pre-Fire Risk Advisory", "Unverified Satellite Hotspot Detection", "Verified Fire Incident", "Official Public Emergency Warning"],
               "public_warning_note": "PyroScope never issues an Official Public Emergency Warning. That category exists only so authorised officers can record one issued through their own channels."})


@app.post("/api/alerts/evaluate", dependencies=[Depends(need_data)])
def alerts_evaluate(body: EvaluateBody, a: Actor = Depends(require("gov_officer"))):
    return ok(alerts.evaluate(body.issue_date, a.username, a.role, body.include_detections))


@app.get("/api/alerts/{alert_id}")
def alert_get(alert_id: str):
    with M.Session() as s:
        al = s.scalar(select(M.Alert).where(M.Alert.alert_id == alert_id))
        if al is None:
            raise KeyError(alert_id)
        return ok(alerts.serialize(al, full=True))


def _action(name):
    def handler(alert_id: str, body: ActionBody = ActionBody(), a: Actor = Depends(require("gov_officer"))):
        return ok(alerts.act(alert_id, name, a.username, a.role, body.note))
    handler.__name__ = f"alert_{name}"
    return handler


for _n in ("acknowledge", "verify", "approve", "reject", "escalate"):
    app.post(f"/api/alerts/{{alert_id}}/{_n}")(_action(_n))


@app.get("/api/audit")
def audit(limit: int = Query(200, ge=1, le=1000), a: Actor = Depends(require("gov_officer"))):
    with M.Session() as s:
        rows = list(s.scalars(select(M.AuditLog).order_by(M.AuditLog.id.desc()).limit(limit)))
    return ok({"items": [{"at": r.at.isoformat() + "Z", "actor": r.actor, "role": r.actor_role, "action": r.action, "entity": r.entity, "entity_id": r.entity_id, "detail": r.detail} for r in rows]})


# --------------------------------------------------------------------------- organisations
class OrgBody(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    sector: str = Field(min_length=2, max_length=80)
    contact_email: Optional[str] = Field(None, max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LocationBody(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    land_use_tag: str = Field(min_length=2, max_length=60)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    buffer_km: float = Field(25, gt=0, le=200)
    alert_threshold: float = Field(0.6, gt=0, lt=1)
    notify_safety_team: bool = True


def _org(s, org_id: int, a: Actor) -> M.Organisation:
    o = s.get(M.Organisation, org_id)
    if o is None or (a.role != "admin" and o.created_by != a.id):
        raise HTTPException(404, "organisation not found")       # same answer whether absent or not yours
    return o


@app.get("/api/organisations")
def orgs(a: Actor = Depends(require("org_user"))):
    with M.Session() as s:
        q = select(M.Organisation)
        if a.role != "admin":
            q = q.where(M.Organisation.created_by == a.id)
        return ok({"items": [{"id": o.id, "name": o.name, "sector": o.sector, "contact_email": o.contact_email, "locations": len(o.locations)} for o in s.scalars(q)]})


@app.post("/api/organisations")
def org_create(body: OrgBody, a: Actor = Depends(require("org_user"))):
    with M.Session() as s:
        o = M.Organisation(**body.model_dump(), created_by=a.id)
        s.add(o)
        s.add(M.AuditLog(actor=a.username, actor_role=a.role, action="ORGANISATION_REGISTERED", entity="organisation", entity_id=body.name))
        s.commit()
        return ok({"id": o.id, "name": o.name})


@app.post("/api/organisations/{org_id}/locations")
def org_add_location(org_id: int, body: LocationBody, a: Actor = Depends(require("org_user"))):
    with M.Session() as s:
        o = _org(s, org_id, a)
        loc = M.MonitoringLocation(organisation_id=o.id, **body.model_dump())
        s.add(loc)
        s.commit()
        return ok({"id": loc.id})


@app.delete("/api/organisations/{org_id}/locations/{loc_id}")
def org_del_location(org_id: int, loc_id: int, a: Actor = Depends(require("org_user"))):
    with M.Session() as s:
        _org(s, org_id, a)
        loc = s.get(M.MonitoringLocation, loc_id)
        if loc is None or loc.organisation_id != org_id:
            raise HTTPException(404, "location not found")
        s.delete(loc)
        s.commit()
    return ok({"deleted": loc_id})


def _buffer_bbox(lat, lon, km):
    dlat = km / 111.32
    dlon = km / (111.32 * max(np.cos(np.radians(lat)), 0.1))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


@app.get("/api/organisations/{org_id}/overview", dependencies=[Depends(need_data)])
def org_overview(org_id: int, a: Actor = Depends(require("org_user"))):
    with M.Session() as s:
        o = _org(s, org_id, a)
        locs = list(o.locations)
        org = {"id": o.id, "name": o.name, "sector": o.sector, "contact_email": o.contact_email}
    end = analytics.data_end()
    items = []
    for loc in locs:
        box = _buffer_bbox(loc.latitude, loc.longitude, loc.buffer_km)
        rid = "bbox:" + ",".join(f"{x:.4f}" for x in box)
        hs, _tot = ingest.query_hotspots(end - pd.Timedelta(days=6), end, box, limit=10 ** 9)
        if len(hs):
            dkm = np.hypot((hs["latitude"] - loc.latitude) * 111.32, (hs["longitude"] - loc.longitude) * 111.32 * np.cos(np.radians(loc.latitude)))
            hs = hs.assign(distance_km=dkm)[dkm <= loc.buffer_km]
        near = hs.sort_values("distance_km").head(200) if len(hs) else hs
        fc = risk.region_forecast(rid)
        hist = analytics.trends(rid)["yearly"]
        maxp = fc.get("max_cell_probability")
        breach = maxp is not None and maxp >= loc.alert_threshold
        items.append({"id": loc.id, "name": loc.name, "land_use_tag": loc.land_use_tag, "latitude": loc.latitude, "longitude": loc.longitude,
                      "buffer_km": loc.buffer_km, "alert_threshold": loc.alert_threshold, "region_id": rid, "bbox": box,
                      "jurisdiction": alerts.resolve_jurisdiction(loc.latitude, loc.longitude, land_use_override="Industrial" if "industr" in loc.land_use_tag.lower() else None),
                      "nearby_7d": {"total": int(len(hs)), "nearest_km": float(hs["distance_km"].min()) if len(hs) else None,
                                    "by_satellite": hs["satellite"].value_counts().to_dict() if len(hs) else {},
                                    "max_frp_mw": float(hs["frp_mw"].max()) if len(hs) and hs["frp_mw"].notna().any() else None,
                                    "points": rec(near[["latitude", "longitude", "satellite", "acq_date", "acq_time", "frp_mw", "confidence_raw", "distance_km", "daynight"]].assign(acq_date=lambda d: d["acq_date"].astype(str))) if len(near) else []},
                      "forecast": {k: fc.get(k) for k in ("status", "issue_date", "max_cell_probability", "headline_probability", "risk_category", "regional", "tier_counts", "confidence", "message")},
                      "history": [{"year": h["year"], "harmonized": h["harmonized"], "viirs": h["viirs"], "complete": h["complete"]} for h in hist],
                      "threshold_breached": bool(breach),
                      "notification": ({"status": "SIMULATED", "channel": "in-app (simulated)", "to": "Facility safety team",
                                        "text": f"Simulated notification: 7-day hotspot probability {maxp * 100:.0f}% within {loc.buffer_km:.0f} km of {loc.name} "
                                                f"meets your {loc.alert_threshold * 100:.0f}% threshold."} if breach and loc.notify_safety_team else None)})
    return ok({"organisation": org, "locations": items, "privacy": "Organisation data is visible only to the account that registered it and to administrators."})


# --------------------------------------------------------------------------- reports
class ReportBody(BaseModel):
    region_id: str = "country"
    format: str = Field("pdf", pattern="^(pdf|csv)$")
    kind: str = Field("full", pattern="^(full|harmonized|forecast_cells|alerts)$")
    organisation_id: Optional[int] = None


@app.get("/api/reports")
def reports_list(a: Actor = Depends(actor)):
    with M.Session() as s:
        rows = list(s.scalars(select(M.Report).order_by(M.Report.id.desc()).limit(200)))
        own = {o.id for o in s.scalars(select(M.Organisation).where(M.Organisation.created_by == a.id))}
    vis = [r for r in rows if r.organisation_id is None or a.role == "admin" or r.organisation_id in own]
    return ok({"items": [{"id": r.id, "title": r.title, "format": r.format, "region_id": r.region_id, "created_by": r.created_by, "bytes": r.bytes,
                          "created_at": r.created_at.isoformat() + "Z", "organisation_id": r.organisation_id} for r in vis]})


@app.post("/api/reports/generate", dependencies=[Depends(need_data), Depends(limited("report"))])
def reports_generate(body: ReportBody, a: Actor = Depends(actor)):
    store.region_cells(body.region_id)      # validates the region id
    if body.organisation_id is not None:
        with M.Session() as s:
            _org(s, body.organisation_id, a)
    return ok(reports.generate(body.region_id, body.format, a.username, body.kind if body.format == "csv" else "full", body.organisation_id))


@app.get("/api/reports/{report_id}/download")
def reports_download(report_id: int, a: Actor = Depends(actor)):
    with M.Session() as s:
        r = s.get(M.Report, report_id)
        if r is None:
            raise HTTPException(404, "report not found")
        if r.organisation_id is not None:
            _org(s, r.organisation_id, a)
        name = r.path
    path = (REPORTS / name).resolve()
    if REPORTS.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "report file missing")
    return FileResponse(path, filename=name, media_type="application/pdf" if name.endswith(".pdf") else "text/csv")


from . import routes_ext  # noqa: E402,F401  (registers the fire-intelligence / deployment routes on `app`)
