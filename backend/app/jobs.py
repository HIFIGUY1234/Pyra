"""Background jobs for expensive data acquisition / processing (visible state, cooperative cancellation).

API requests never block on long downloads: an administrator queues a job, the job runs in a worker thread,
and its status, progress and (secret-free) error are stored in the `data_jobs` table. Cancellation is
cooperative: steps check `cancelled(job_id)` between units of work (granules, categories, sensors).
One job of each kind runs at a time.
"""
from __future__ import annotations

import threading
import traceback
from datetime import datetime, timezone

from sqlalchemy import select

from . import models as M

KINDS = {
    "viirs750_fetch": "Search + download + convert VIIRS 750 m granules (needs Earthdata Login)",
    "linear_gis": "Download the Geofabrik India extract and build road / rail / power / settlement layers",
    "population_refresh": "Download WorldPop 2020 and rebuild area-weighted population layers",
    "sensor_models": "Retrain the independent NOAA-20 and NOAA-21 forecast models",
    "tle_refresh": "Refresh CelesTrak TLEs and re-validate overpass prediction",
}
_lock = threading.Lock()
_running: dict[str, int] = {}


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


def _runner(kind: str, params: dict, job_id: int):
    from .viirs750 import _redact

    def progress(msg: str, **extra):
        if cancelled(job_id):
            raise Cancelled()
        _update(job_id, progress={"message": msg[:300], **extra, "at": _now().isoformat(timespec="seconds")})

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
            out[sat] = viirs750.download(g, log=lambda *a: None)
        progress("converting")
        viirs750.convert()
        return out
    if kind == "linear_gis":
        from . import linear_gis
        progress("downloading Geofabrik extract")
        pbf = linear_gis.acquire(log=lambda *a: None)
        progress("processing PBF")
        return linear_gis.build(pbf, node_index="sparse_file_array," + str(linear_gis.LIN_DIR / "nodes.idx"), log=lambda *a: None)
    if kind == "population_refresh":
        from . import population
        progress("downloading WorldPop")
        p = population.acquire(log=lambda *a: None)
        progress("area-weighted allocation")
        return population.build(p, log=lambda *a: None, method="area_weighted")
    if kind == "sensor_models":
        from . import forecast, operational
        res = {}
        for snr in ("NOAA-20", "NOAA-21"):
            progress(f"training {snr}")
            m = forecast.train(log=lambda *a: None, sensor=snr)
            res[snr] = m.get("model_version")
        operational.clear()
        return res
    if kind == "tle_refresh":
        from . import orbits
        progress("refreshing TLEs")
        orbits.refresh_all()
        progress("validating")
        return orbits.run_validation()
    raise ValueError(f"unknown job kind {kind}")


def submit(kind: str, params: dict, actor: str, runner=None, wait: bool = False) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}")
    if kind == "viirs750_fetch":
        import pandas as pd
        if not params.get("start") or not params.get("end") or pd.Timestamp(params["start"]) > pd.Timestamp(params["end"]):
            raise ValueError("viirs750_fetch needs start <= end (YYYY-MM-DD)")
    with _lock:
        if kind in _running:
            raise PermissionError(f"a {kind} job is already running (id {_running[kind]})")
        with M.Session() as s:
            j = M.DataJob(kind=kind, params=params, status="QUEUED", requested_by=actor)
            s.add(j)
            s.add(M.AuditLog(actor=actor, action="DATA_JOB_SUBMITTED", entity="data_job", entity_id=kind, detail=params))
            s.commit()
            jid = j.id
        _running[kind] = jid

    def work():
        _update(jid, status="RUNNING", started_at=_now())
        try:
            res = (runner or _runner)(kind, params, jid)
            _update(jid, status="DONE", finished_at=_now(), progress={"message": "done", "result": _summ(res)})
        except Cancelled:
            _update(jid, status="CANCELLED", finished_at=_now())
        except Exception as exc:
            from .viirs750 import _redact
            _update(jid, status="FAILED", finished_at=_now(), error=_redact(f"{type(exc).__name__}: {exc}"))
            traceback.print_exc()
        finally:
            with _lock:
                _running.pop(kind, None)

    t = threading.Thread(target=work, name=f"job-{kind}-{jid}", daemon=True)
    t.start()
    if wait:
        t.join()
    return get(jid)


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
    return {"id": j.id, "kind": j.kind, "description": KINDS.get(j.kind), "params": j.params, "status": j.status, "progress": j.progress,
            "error": j.error, "requested_by": j.requested_by, "cancel_requested": j.cancel_requested,
            "created_at": iso(j.created_at), "started_at": iso(j.started_at), "finished_at": iso(j.finished_at)}


def listing(limit: int = 50) -> list[dict]:
    with M.Session() as s:
        return [_view(j) for j in s.scalars(select(M.DataJob).order_by(M.DataJob.id.desc()).limit(limit))]


def cancel(job_id: int, actor: str) -> dict:
    with M.Session() as s:
        j = s.get(M.DataJob, job_id)
        if j is None:
            raise KeyError(job_id)
        if j.status not in ("QUEUED", "RUNNING"):
            raise PermissionError(f"job {job_id} is {j.status}")
        j.cancel_requested = True
        s.add(M.AuditLog(actor=actor, action="DATA_JOB_CANCEL_REQUESTED", entity="data_job", entity_id=str(job_id)))
        s.commit()
    return get(job_id)
