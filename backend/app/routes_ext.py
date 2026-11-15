"""API routes for fire events, burned area, emissions, smoke, geostationary data, external validation and storage.

Registered on the main FastAPI app (imported at the end of app.main). Read endpoints use the normal session rules;
heavy work is never run inside a request - it is queued as a background job (POST /api/jobs).
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from .main import Actor, actor, app, limited, ok, require

DATE = r"^\d{4}-\d{2}-\d{2}$"
MAX_UPLOAD = 50_000_000


def _bbox(bbox: Optional[str]):
    if not bbox:
        return None
    w, s, e, n = (float(x) for x in bbox.split(","))
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("bbox must be west,south,east,north")
    return (w, s, e, n)


async def _read(file: UploadFile, exts: tuple) -> bytes:
    if not (file.filename or "").lower().endswith(exts):
        raise ValueError(f"file must end with {' or '.join(exts)}")
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise ValueError("file larger than 50 MB")
    return raw


# --------------------------------------------------------------------------- fire events
@app.get("/api/events")
def events_list(start: Optional[str] = Query(None, pattern=DATE), end: Optional[str] = Query(None, pattern=DATE),
                status: Optional[str] = Query(None, max_length=20), state: Optional[str] = Query(None, max_length=80),
                region_id: Optional[str] = Query(None, max_length=200), bbox: Optional[str] = Query(None, max_length=80),
                min_obs: int = Query(1, ge=1, le=100000), sort: str = Query("last_detection", max_length=20),
                limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), a: Actor = Depends(actor)):
    from . import events
    return ok(events.query(start, end, status, state, region_id, min_obs, _bbox(bbox), limit, offset, sort))


@app.get("/api/events/summary")
def events_summary(a: Actor = Depends(actor)):
    from . import events
    return ok(events.status_summary())


@app.get("/api/events/region/{region_id}")
def events_region(region_id: str, start: Optional[str] = Query(None, pattern=DATE), end: Optional[str] = Query(None, pattern=DATE),
                  limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), a: Actor = Depends(actor)):
    from . import events
    return ok(events.query(start, end, region_id=region_id, limit=limit, offset=offset))


@app.get("/api/events/{event_id}")
def events_get(event_id: str, a: Actor = Depends(actor)):
    from . import events, geostationary
    d = events.get(event_id)
    d["geostationary_agreement"] = geostationary.agreement(d, geostationary.observations(d["first_detection"][:10], d["last_detection"][:10], 10 ** 7))
    return ok(d)


@app.get("/api/events/{event_id}/timeline")
def events_timeline(event_id: str, a: Actor = Depends(actor)):
    from . import events
    return ok(events.timeline(event_id))


@app.get("/api/events/{event_id}/observations")
def events_observations(event_id: str, limit: int = Query(2000, ge=1, le=5000), offset: int = Query(0, ge=0), a: Actor = Depends(actor)):
    from . import events
    return ok(events.observations(event_id, limit, offset))


@app.get("/api/events/{event_id}/nearby-exposure")
def events_exposure(event_id: str, radius_km: float = Query(10.0, ge=1, le=100), a: Actor = Depends(actor)):
    from . import events, exposure
    e = events.get(event_id)
    return ok({"event_id": event_id, "radius_km": radius_km, "centre": [e["lat"], e["lon"]], **exposure.point(e["lat"], e["lon"], radius_km),
               "note": "Exposure around the event centre; the footprint is an observation footprint, not a perimeter. No damage is implied."})


# --------------------------------------------------------------------------- burned area
@app.get("/api/burned-area/coverage")
def ba_coverage(a: Actor = Depends(actor)):
    from . import burned_area
    return ok(burned_area.coverage())


@app.get("/api/burned-area/summary")
def ba_summary(product: str = Query("MCD64A1", pattern="^(MCD64A1|VNP64A1)$"), year: Optional[int] = Query(None, ge=2000, le=2100),
               by: str = Query("state", pattern="^(state|district|month)$"), a: Actor = Depends(actor)):
    from . import burned_area
    return ok(burned_area.summary(product, year, by))


@app.get("/api/burned-area/cells")
def ba_cells(year: int = Query(..., ge=2000, le=2100), month: int = Query(..., ge=1, le=12),
             product: str = Query("MCD64A1", pattern="^(MCD64A1|VNP64A1)$"), a: Actor = Depends(actor)):
    from . import burned_area
    return ok(burned_area.cells_layer(product, year, month))


@app.get("/api/burned-area/events")
def ba_events(year: int = Query(..., ge=2000, le=2100), month: int = Query(..., ge=1, le=12),
              product: str = Query("MCD64A1", pattern="^(MCD64A1|VNP64A1)$"), a: Actor = Depends(actor)):
    from . import burned_area
    return ok(burned_area.event_association(product, year, month))


# --------------------------------------------------------------------------- emissions
@app.get("/api/emissions/summary")
def em_summary(a: Actor = Depends(actor)):
    from . import emissions
    return ok(emissions.summary())


@app.get("/api/emissions/regions")
def em_regions(by: str = Query("state", pattern="^(state|district_id|month|land_use)$"), a: Actor = Depends(actor)):
    from . import emissions
    return ok(emissions.regions(by))


@app.get("/api/emissions/events")
def em_events(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), a: Actor = Depends(actor)):
    from . import emissions
    return ok(emissions.events(limit, offset))


@app.get("/api/emissions/uncertainty")
def em_uncertainty(a: Actor = Depends(actor)):
    from . import emissions
    s = emissions.summary()
    return ok({k: s.get(k) for k in ("label", "totals_tonnes", "n_draws", "inputs", "uncertainty_not_included", "status", "burned_area_method")})


# --------------------------------------------------------------------------- smoke
@app.get("/api/smoke/forecasts")
def smoke_runs(limit: int = Query(20, ge=1, le=100), a: Actor = Depends(actor)):
    from . import smoke
    return ok({"items": smoke.runs(limit), "label": smoke.LABEL})


@app.get("/api/smoke/trajectories/{run_id}")
def smoke_get(run_id: str, a: Actor = Depends(actor)):
    from . import smoke
    return ok(smoke.get(run_id))


@app.get("/api/smoke/exposure/{run_id}")
def smoke_exposure(run_id: str, a: Actor = Depends(actor)):
    from . import smoke
    r = smoke.get(run_id)
    return ok({"run_id": run_id, "exposure": r["exposure"], "label": r["label"]})


@app.get("/api/smoke/validation")
def smoke_validation(a: Actor = Depends(actor)):
    return ok({"status": "BLOCKED_BY_CREDENTIALS", "pm25_forecast": "NOT_IMPLEMENTED (no dispersion model installed)",
               "needed": ["CPCB / data.gov.in API key or OpenAQ v3 API key for ground PM2.5", "HYSPLIT (or another dispersion model) for concentrations"]})


# --------------------------------------------------------------------------- geostationary
@app.get("/api/geostationary/providers")
def geo_providers(a: Actor = Depends(actor)):
    from . import geostationary
    return ok({"items": geostationary.PROVIDERS})


@app.get("/api/geostationary/coverage")
def geo_coverage(a: Actor = Depends(actor)):
    from . import geostationary
    return ok(geostationary.coverage())


@app.get("/api/geostationary/observations")
def geo_obs(start: Optional[str] = Query(None, pattern=DATE), end: Optional[str] = Query(None, pattern=DATE),
            limit: int = Query(2000, ge=1, le=10000), a: Actor = Depends(actor)):
    from . import geostationary
    d = geostationary.observations(start, end, limit)
    return ok({"items": d.astype({"timestamp_utc": str}).to_dict("records") if len(d) else [], "label": "EXPERIMENTAL"})


@app.get("/api/geostationary/diurnal")
def geo_diurnal(a: Actor = Depends(actor)):
    from . import geostationary
    return ok(geostationary.diurnal())


@app.get("/api/geostationary/agreement")
def geo_agreement(start: str = Query(..., pattern=DATE), end: str = Query(..., pattern=DATE), a: Actor = Depends(actor)):
    from . import geostationary
    return ok(geostationary.agreement_summary(start, end))


@app.post("/api/geostationary/import", dependencies=[Depends(limited("upload"))])
async def geo_import(source: str = Form(..., min_length=3, max_length=300), licence: str = Form(..., min_length=2, max_length=200),
                     platform: Optional[str] = Form(None, max_length=40), product: Optional[str] = Form(None, max_length=60),
                     timestamp_utc: Optional[str] = Form(None, max_length=40), file: UploadFile = File(...), a: Actor = Depends(require())):
    from . import geostationary
    raw = await _read(file, (".csv", ".kml"))
    return ok(geostationary.import_observations(raw, file.filename or "upload", source, licence, a.username, platform, product, timestamp_utc))


# --------------------------------------------------------------------------- external validation
@app.get("/api/external-validation/sources")
def xv_sources(a: Actor = Depends(actor)):
    from . import external_validation
    return ok({"items": external_validation.SOURCES})


@app.get("/api/external-validation/summary")
def xv_summary(a: Actor = Depends(actor)):
    from . import external_validation
    return ok(external_validation.summary())


@app.get("/api/external-validation/harmonization-states")
def xv_states(top: int = Query(8, ge=1, le=36), a: Actor = Depends(actor)):
    from . import external_validation
    return ok(external_validation.harmonization_by_state(top))


@app.get("/api/external-validation/results")
def xv_events(start: str = Query(..., pattern=DATE), end: str = Query(..., pattern=DATE), dist_km: float = Query(5.0, gt=0, le=50),
              days: float = Query(2.0, ge=0, le=30), dataset: Optional[str] = Query(None, max_length=200), a: Actor = Depends(actor)):
    from . import external_validation
    return ok(external_validation.validate_events(start, end, dist_km, days, dataset))


@app.post("/api/external-validation/incidents", dependencies=[Depends(limited("upload"))])
async def xv_import(source: str = Form(..., min_length=3, max_length=200), licence: str = Form(..., min_length=2, max_length=200),
                    replace: bool = Form(False), file: UploadFile = File(...), a: Actor = Depends(require())):
    from . import external_validation
    raw = await _read(file, (".csv",))
    return ok(external_validation.import_incidents(raw, source, licence, a.username, replace))


@app.get("/api/external-validation/incidents")
def xv_incidents(a: Actor = Depends(actor)):
    from . import external_validation
    return ok(external_validation.incidents_status())


# --------------------------------------------------------------------------- deployment / storage
class SignBody(BaseModel):
    bucket: str = Field(max_length=63)
    key: str = Field(max_length=500)
    expires_s: int = Field(3600, ge=60, le=7 * 86400)


@app.get("/api/storage/status")
def storage_status(a: Actor = Depends(require())):
    from . import storage
    return ok(storage.status())


@app.post("/api/storage/sign")
def storage_sign(body: SignBody, a: Actor = Depends(require("analyst", "gov_officer"))):
    from . import storage
    return ok({"url": storage.get_storage().signed_url(body.bucket, body.key, body.expires_s), "expires_s": body.expires_s})


@app.get("/api/deployment/status")
def deployment_status(a: Actor = Depends(require())):
    import os
    from . import models as M
    from . import storage
    url = M.engine.url
    return ok({"database": {"dialect": M.engine.dialect.name, "host": url.host, "port": url.port,
                            "pool": type(M.engine.pool).__name__, "transaction_pooler": M.is_transaction_pooler(str(url))},
               "storage": storage.status(), "embedded_worker": os.getenv("PYROSCOPE_EMBEDDED_WORKER", "1") == "1",
               "frontend": "Vercel (separate project; VITE_API_BASE_URL points at this API)",
               "note": "No credentials are returned by this endpoint."})


@app.get("/api/storage/local/{bucket}/{key:path}")
def storage_local(bucket: str, key: str, a: Actor = Depends(require("analyst", "gov_officer"))):
    """Download from the LOCAL object store (development backend); Supabase serves signed URLs itself."""
    from fastapi.responses import FileResponse
    from . import storage
    st = storage.get_storage()
    if not isinstance(st, storage.LocalStorage):
        raise PermissionError("local object download is only available with PYROSCOPE_STORAGE=local")
    st.metadata(bucket, key)
    return FileResponse(st._path(bucket, key), filename=key.rsplit("/", 1)[-1])


# --------------------------------------------------------------------------- advisories (human review required)
class AdvisoryBody(BaseModel):
    kind: str = Field(max_length=40)
    ref: str = Field(min_length=3, max_length=80)
    note: Optional[str] = Field(default=None, max_length=1000)


@app.get("/api/advisories/types")
def advisory_types(a: Actor = Depends(actor)):
    from . import alerts
    return ok({"creatable": alerts.ADVISORY_TYPES, "not_creatable": alerts.NOT_ISSUABLE})


@app.post("/api/advisories")
def advisory_create(body: AdvisoryBody, a: Actor = Depends(require("analyst", "gov_officer"))):
    from . import alerts
    return ok(alerts.create_advisory(body.kind, body.ref, a.username, a.role, body.note))
