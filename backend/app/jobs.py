"""Durable background jobs: a database-leased queue plus a persistent worker (`python -m app.worker`).

API requests never run heavy work. `submit` inserts a QUEUED row; a worker claims it atomically with a
compare-and-set UPDATE (works identically on SQLite and PostgreSQL / Supabase; no row is claimed twice), holds a
lease it renews by heartbeat, and records stage, progress, result or a secret-free error.

Statuses: QUEUED -> RUNNING -> SUCCEEDED | FAILED | CANCELLED, with RETRYING (exponential backoff) between attempts.
A RUNNING job whose lease expired (worker crashed) is reclaimed by the next worker. Permanent failures
(missing credentials, invalid parameters) are not retried. Cancellation: QUEUED/RETRYING jobs cancel at once;
RUNNING jobs cancel cooperatively at the next `progress()` checkpoint. One active job per kind; an optional
idempotency key returns the existing job instead of queueing a duplicate.

For local development the API process runs an embedded worker thread (PYROSCOPE_EMBEDDED_WORKER=1, default);
production runs the separate worker service and sets PYROSCOPE_EMBEDDED_WORKER=0.
"""
from __future__ import annotations

import os
import socket
import threading
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update

from . import models as M

KINDS = {
    "viirs750_fetch": "Search + download + convert VIIRS 750 m granules (needs Earthdata Login)",
    "linear_gis": "Download the Geofabrik India extract and build road / rail / power / settlement layers",
    "population_refresh": "Download WorldPop 2020 and rebuild area-weighted population layers",
    "sensor_models": "Retrain the independent NOAA-20 and NOAA-21 forecast models",
    "tle_refresh": "Refresh CelesTrak TLEs and re-validate overpass prediction",
    "fire_events": "Delineate space-time fire events from the detection archive (params: start, end)",
    "burned_area": "Download + process MCD64A1 / VNP64A1 burned area for India (params: product, year, month; needs Earthdata)",
    "emissions": "Estimate biomass-burning emissions from fire events (FRP/FRE method) with Monte Carlo uncertainty",
    "smoke_trajectories": "Forward smoke trajectories from active fire events with GFS winds (experimental, not concentrations)",
    "harmonization": "Re-run MODIS-VIIRS harmonization, validation and bridge studies",
}
ACTIVE = ("QUEUED", "RUNNING", "RETRYING")
TERMINAL = ("SUCCEEDED", "FAILED", "CANCELLED", "DONE")
LEASE_S = int(os.getenv("PYROSCOPE_JOB_LEASE_S", "300"))
BACKOFF_S = 30
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
_overrides: dict[int, object] = {}          # job id -> runner (tests / embedded callers)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _update(job_id: int, **kw):
    with M.Session() as s:
        j = s.get(M.DataJob, job_id)
        for k, v in kw.items():
            setattr(j, k, v)
        s.commit()


def cancelled(job_id: int) -> bool:
    with M.Session() as s:
        j = s.get(M.DataJob, job_id)
        return bool(j and j.cancel_requested)


class Cancelled(Exception):
    pass


class PermanentError(Exception):
    """Failure that retrying cannot fix (bad parameters, missing credentials, missing data)."""


# --------------------------------------------------------------------------- runners
def _runner(kind: str, params: dict, job_id: int):
    def progress(msg: str, **extra):
        if cancelled(job_id):
            raise Cancelled()
        now = _now()
        _update(job_id, stage=msg[:120], progress={"message": msg[:300], **extra, "at": now.isoformat(timespec="seconds")},
                heartbeat_at=now, lease_expires_at=now + timedelta(seconds=LEASE_S))

    quiet = lambda *a, **k: None
    if kind == "viirs750_fetch":
        from . import viirs750
        if not viirs750.credentials_status()["configured"]:
            raise PermissionError("BLOCKED_BY_CREDENTIALS: Earthdata Login not configured (EARTHDATA_TOKEN or ~/.netrc)")
        sats = params.get("satellites") or ["NOAA-21", "NOAA-20"]
        out = {}
        for sat in sats:
            progress(f"searching {sat}")
            g = viirs750.search(sat, params["start"], params["end"])
            progress(f"downloading {len(g)} {sat} granules")
            out[sat] = viirs750.download(g, log=quiet)
        progress("converting")
        conv = viirs750.convert()
        out["conversion"] = conv.name if conv else "NO_FIRE_PIXELS_IN_AOI"
        return out
    if kind == "linear_gis":
        from . import linear_gis
        progress("downloading Geofabrik extract")
        pbf = linear_gis.acquire(log=quiet)
        progress("processing PBF")
        return linear_gis.build(pbf, node_index="sparse_file_array," + str(linear_gis.LIN_DIR / "nodes.idx"), log=quiet)
    if kind == "population_refresh":
        from . import population
        progress("downloading WorldPop")
        p = population.acquire(log=quiet)
        progress("area-weighted allocation")
        return population.build(p, log=quiet, method="area_weighted")
    if kind == "sensor_models":
        from . import forecast, operational
        res = {}
        for snr in ("NOAA-20", "NOAA-21"):
            progress(f"training {snr}")
            m = forecast.train(log=quiet, sensor=snr)
            res[snr] = m.get("model_version")
        operational.clear()
        return res
    if kind == "tle_refresh":
        from . import orbits
        progress("refreshing TLEs")
        orbits.refresh_all()
        progress("validating")
        return orbits.run_validation()
    if kind == "fire_events":
        from . import events
        progress("linking detections")
        return events.build(params["start"], params["end"], bbox=params.get("bbox"), log=quiet, progress=progress)
    if kind == "burned_area":
        from . import burned_area
        return burned_area.run(params.get("product", "MCD64A1"), int(params["year"]), params.get("month"), progress=progress)
    if kind == "emissions":
        from . import emissions
        progress("estimating emissions")
        return emissions.build(params.get("start"), params.get("end"), n_draws=int(params.get("n_draws", 1000)))
    if kind == "smoke_trajectories":
        from . import smoke
        return smoke.run(params, progress=progress)
    if kind == "harmonization":
        from . import pipeline
        progress("summaries, harmonization, validation (no ingest, no retrain)")
        return pipeline.main(["--skip-ingest", "--skip-weather", "--skip-train"])
    raise ValueError(f"unknown job kind {kind}")


def _permanent(exc: Exception) -> bool:
    return isinstance(exc, (PermanentError, PermissionError, ValueError, KeyError, FileNotFoundError))


def _error_code(exc: Exception) -> str:
    msg = str(exc)
    for code in ("BLOCKED_BY_CREDENTIALS", "BLOCKED_BY_EXTERNAL_DATA", "BLOCKED_BY_DATA_LICENCE"):
        if code in msg:
            return code
    return type(exc).__name__


# --------------------------------------------------------------------------- queue operations
def submit(kind: str, params: dict, actor: str, runner=None, wait: bool = False, idempotency_key: str | None = None,
           max_attempts: int = 3) -> dict:
    """Queue a job. `wait=True` executes it in the calling thread (CLI / tests); `runner` overrides the work function."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}")
    params = params or {}
    import pandas as pd
    if kind in ("viirs750_fetch", "fire_events"):
        if not params.get("start") or not params.get("end") or pd.Timestamp(params["start"]) > pd.Timestamp(params["end"]):
            raise ValueError(f"{kind} needs start <= end (YYYY-MM-DD)")
    if kind == "burned_area" and not str(params.get("year", "")).isdigit():
        raise ValueError("burned_area needs params.year (and optional month 1-12, product MCD64A1|VNP64A1)")
    with M.Session() as s:
        if idempotency_key:
            prev = s.scalar(select(M.DataJob).where(M.DataJob.idempotency_key == idempotency_key,
                                                    M.DataJob.status.notin_(("FAILED", "CANCELLED"))))
            if prev is not None:
                return _view(prev)
        busy = s.scalar(select(M.DataJob).where(M.DataJob.kind == kind, M.DataJob.status.in_(ACTIVE)))
        if busy is not None:
            raise PermissionError(f"a {kind} job is already active (id {busy.id}, {busy.status})")
        j = M.DataJob(kind=kind, params=params, status="QUEUED", requested_by=actor, attempts=0, max_attempts=max_attempts,
                      idempotency_key=idempotency_key, next_run_at=_now())
        s.add(j)
        s.add(M.AuditLog(actor=actor, action="DATA_JOB_SUBMITTED", entity="data_job", entity_id=kind, detail=params))
        s.commit()
        jid = j.id
    if runner is not None:
        _overrides[jid] = runner
    if wait:
        if claim(job_id=jid):
            execute(jid)
    elif runner is not None:
        # explicit runner: run in a dedicated thread now (embedded use); the queue still records the state
        if claim(job_id=jid):
            threading.Thread(target=execute, args=(jid,), name=f"job-{kind}-{jid}", daemon=True).start()
    else:
        wake()
    return get(jid)


def claim(job_id: int | None = None, worker_id: str = WORKER_ID) -> int | None:
    """Atomically claim one runnable job (or the given one). Compare-and-set: the UPDATE only succeeds if the row
    is still runnable, so two workers can never both own it."""
    now = _now()
    runnable = or_(
        (M.DataJob.status.in_(("QUEUED", "RETRYING"))) & or_(M.DataJob.next_run_at.is_(None), M.DataJob.next_run_at <= now),
        (M.DataJob.status == "RUNNING") & (M.DataJob.lease_expires_at < now),       # crashed worker: lease expired
    )
    with M.Session() as s:
        q = select(M.DataJob.id).where(runnable, M.DataJob.cancel_requested.isnot(True)).order_by(M.DataJob.id)
        if job_id is not None:
            q = q.where(M.DataJob.id == job_id)
        candidates = list(s.scalars(q.limit(5)))
        for cid in candidates:
            res = s.execute(update(M.DataJob).where(M.DataJob.id == cid, runnable).values(
                status="RUNNING", worker_id=worker_id, attempts=M.DataJob.attempts + 1, started_at=now, heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=LEASE_S), error=None, error_code=None))
            s.commit()
            if res.rowcount == 1:
                return cid
    return None


def _heartbeat(job_id: int, stop: threading.Event):
    while not stop.wait(max(5, LEASE_S // 3)):
        now = _now()
        try:
            with M.Session() as s:
                s.execute(update(M.DataJob).where(M.DataJob.id == job_id, M.DataJob.status == "RUNNING")
                          .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=LEASE_S)))
                s.commit()
        except Exception:      # a missed heartbeat only shortens the lease
            traceback.print_exc()


def execute(job_id: int):
    """Run a claimed job to a terminal or RETRYING state."""
    with M.Session() as s:
        j = s.get(M.DataJob, job_id)
        kind, params, attempts, max_attempts = j.kind, dict(j.params or {}), j.attempts or 1, j.max_attempts or 3
    stop = threading.Event()
    hb = threading.Thread(target=_heartbeat, args=(job_id, stop), daemon=True)
    hb.start()
    try:
        res = (_overrides.get(job_id) or _runner)(kind, params, job_id)
        _update(job_id, status="SUCCEEDED", finished_at=_now(), stage="done", result=_jsonable(res),
                progress={"message": "done", "result": _summ(res)}, lease_expires_at=None)
    except Cancelled:
        _update(job_id, status="CANCELLED", finished_at=_now(), lease_expires_at=None)
    except Exception as exc:
        from .viirs750 import _redact
        err = _redact(f"{type(exc).__name__}: {exc}")[:4000]
        if not _permanent(exc) and attempts < max_attempts:
            delay = min(BACKOFF_S * 2 ** (attempts - 1), 3600)
            _update(job_id, status="RETRYING", error=err, error_code=_error_code(exc), lease_expires_at=None,
                    next_run_at=_now() + timedelta(seconds=delay), stage=f"retry {attempts + 1}/{max_attempts} in {delay}s")
        else:
            _update(job_id, status="FAILED", finished_at=_now(), error=err, error_code=_error_code(exc), lease_expires_at=None)
        traceback.print_exc()
    finally:
        stop.set()
        _overrides.pop(job_id, None)


def run_once(worker_id: str = WORKER_ID) -> int | None:
    jid = claim(worker_id=worker_id)
    if jid is not None:
        execute(jid)
    return jid


# --------------------------------------------------------------------------- embedded worker (dev)
_wake = threading.Event()
_embedded: threading.Thread | None = None


def wake():
    _wake.set()


def start_embedded_worker(poll_s: float = 5.0):
    global _embedded
    if os.getenv("PYROSCOPE_EMBEDDED_WORKER", "1") != "1" or (_embedded and _embedded.is_alive()):
        return

    def loop():
        while True:
            try:
                while run_once() is not None:
                    pass
            except Exception:
                traceback.print_exc()
            _wake.wait(poll_s)
            _wake.clear()
    _embedded = threading.Thread(target=loop, name="embedded-job-worker", daemon=True)
    _embedded.start()


# --------------------------------------------------------------------------- views
def _jsonable(res):
    import json
    try:
        return json.loads(json.dumps(res, default=str))
    except (TypeError, ValueError):
        return {"repr": str(res)[:2000]}


def _summ(res):
    import json
    try:
        txt = json.dumps(res, default=str)
    except TypeError:
        txt = str(res)
    return txt[:2000]


def get(job_id: int) -> dict:
    with M.Session() as s:
        j = s.get(M.DataJob, job_id)
        if j is None:
            raise KeyError(job_id)
        return _view(j)


def _view(j) -> dict:
    iso = lambda d: d.isoformat() + "Z" if d else None
    status = "SUCCEEDED" if j.status == "DONE" else j.status
    return {"id": j.id, "kind": j.kind, "description": KINDS.get(j.kind), "params": j.params, "status": status, "progress": j.progress,
            "stage": j.stage, "error": j.error, "error_code": j.error_code, "result": j.result, "requested_by": j.requested_by,
            "cancel_requested": j.cancel_requested, "attempts": j.attempts, "max_attempts": j.max_attempts,
            "worker_id": j.worker_id, "idempotency_key": j.idempotency_key,
            "created_at": iso(j.created_at), "started_at": iso(j.started_at), "finished_at": iso(j.finished_at),
            "heartbeat_at": iso(j.heartbeat_at), "lease_expires_at": iso(j.lease_expires_at), "next_run_at": iso(j.next_run_at)}


def listing(limit: int = 50, offset: int = 0, status: str | None = None, kind: str | None = None) -> list[dict]:
    with M.Session() as s:
        q = select(M.DataJob)
        if status:
            q = q.where(M.DataJob.status == status)
        if kind:
            q = q.where(M.DataJob.kind == kind)
        return [_view(j) for j in s.scalars(q.order_by(M.DataJob.id.desc()).limit(min(limit, 500)).offset(offset))]


def cancel(job_id: int, actor: str) -> dict:
    with M.Session() as s:
        j = s.get(M.DataJob, job_id)
        if j is None:
            raise KeyError(job_id)
        if j.status not in ACTIVE:
            raise PermissionError(f"job {job_id} is {j.status}")
        j.cancel_requested = True
        if j.status in ("QUEUED", "RETRYING"):
            j.status, j.finished_at = "CANCELLED", _now()
        s.add(M.AuditLog(actor=actor, action="DATA_JOB_CANCEL_REQUESTED", entity="data_job", entity_id=str(job_id)))
        s.commit()
    return get(job_id)
