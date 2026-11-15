"""Processed-dataset readiness, provenance manifest and first-boot seed installation.

* `evaluate()` validates the artefacts every dashboard reads (metadata only: Parquet footers and schemas, the spans
  JSON), so it is cheap enough to back `store.has_data()`; results are cached on the files' (size, mtime).
* `readiness()` adds archives (Git LFS pointer / corrupt / valid), registry, calibration, forecast, manifest and the
  next valid action. It is what `GET /api/data/readiness` and the Calendar's waiting state show.
* `install_seed()` copies the processed dataset bundled into the Docker image into an EMPTY data directory (e.g. a
  freshly mounted persistent disk). It verifies every file against the manifest's SHA-256, publishes atomically and
  never replaces an existing dataset - except a previous, older copy of the same seed.

Usage:  python -m app.dataset check | manifest | seed
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .config import ARCHIVE_DIRS, PROCESSED, SEED_PROCESSED, UPLOADS

# Build identity: Render sets RENDER_GIT_COMMIT at runtime; other hosts may set PYROSCOPE_BUILD_SHA.
BUILD_COMMIT = os.getenv("PYROSCOPE_BUILD_SHA") or os.getenv("RENDER_GIT_COMMIT") or None
IMAGE = os.getenv("PYROSCOPE_IMAGE") or "source-checkout"   # set in the Dockerfiles: root-with-seed | api-only
# Fallback seed source when the image carries no bundled dataset (e.g. a host building backend/Dockerfile): the committed
# data/processed of the SAME commit, every file SHA-256-verified against that commit's manifest. "off" disables it.
SEED_URL = os.getenv("PYROSCOPE_SEED_URL") or (
    f"https://raw.githubusercontent.com/HIFIGUY1234/Pyra/{BUILD_COMMIT or 'main'}/data/processed")

log_ = logging.getLogger("pyroscope.dataset")

SCHEMA_VERSION = 1
PROCESSING_VERSION = "2026.11"      # bump when the processed artefacts' layout or meaning changes
MANIFEST = "manifest.json"
# Runtime state / reports that live beside the dataset but are not part of it.
NOT_DATASET = {MANIFEST, "pipeline_state.json", "lfs_recovery_report.json", "ingestion_report.json", "ingestion_report.md"}

REQUIRED: dict[str, set | None] = {
    "daily_cell.parquet": {"acq_date", "cell_id", "satellite", "daynight", "n", "frp_sum", "frp_n"},
    "monthly_cell.parquet": {"ym", "cell_id", "satellite", "daynight", "n", "frp_sum", "days"},
    "spans.json": None,
    "cells.parquet": {"cell_id", "lat", "lon", "state", "district_id"},
    "districts.parquet": {"district_id", "district", "state"},
}

READY, PARTIAL, MISSING, CORRUPT, LFS, PROCESSING, FAILED = (
    "READY", "PARTIAL", "MISSING", "CORRUPT", "LFS_NOT_RECOVERED", "PROCESSING", "FAILED")


# --------------------------------------------------------------------------- file checks
def _is_lfs_pointer(p: Path) -> bool:
    try:
        if p.stat().st_size > 1024:
            return False
        return p.read_bytes()[:64].startswith(b"version https://git-lfs.github.com/spec/")
    except OSError:
        return False


def _check_spans(p: Path) -> str | None:
    from datetime import date
    sp = json.loads(p.read_text())
    if not isinstance(sp, dict) or not sp:
        return "spans.json holds no satellite spans"
    for sat, v in sp.items():
        first, last = date.fromisoformat(v["first"]), date.fromisoformat(v["last"])
        if first > last:
            return f"{sat}: first {first} after last {last}"
        if not isinstance(v.get("gap_days", []), list):
            return f"{sat}: gap_days is not a list"
    return None


def check_file(p: Path, cols: set | None) -> dict:
    out = {"file": p.name, "status": "ok", "bytes": None, "rows": None, "detail": None}
    if not p.exists():
        return out | {"status": "missing"}
    try:
        out["bytes"] = p.stat().st_size
        if out["bytes"] == 0:
            return out | {"status": "empty"}
        if _is_lfs_pointer(p):
            return out | {"status": "lfs_pointer", "detail": "Git LFS pointer, content not downloaded"}
        if p.suffix == ".parquet":
            import pyarrow.parquet as pq
            pf = pq.ParquetFile(p)             # reads the footer only; a truncated / partial write fails here
            out["rows"] = pf.metadata.num_rows
            lack = sorted((cols or set()) - set(pf.schema_arrow.names))
            if lack:
                return out | {"status": "missing_columns", "detail": f"missing columns: {lack}"}
            if out["rows"] == 0:
                return out | {"status": "empty", "detail": "no rows"}
        elif p.suffix == ".json":
            err = _check_spans(p)
            if err:
                return out | {"status": "corrupt", "detail": err}
    except Exception as exc:                      # unreadable / corrupt
        return out | {"status": "corrupt", "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return out


def _signature(processed: Path) -> tuple:
    sig = []
    for name in REQUIRED:
        try:
            st = (processed / name).stat()
            sig.append((name, st.st_size, st.st_mtime_ns))
        except OSError:
            sig.append((name, None, None))
    return tuple(sig)


_cache: dict = {}
_cache_lock = threading.Lock()


def evaluate(processed: Path | None = None) -> dict:
    """Validate the core artefacts. Status: READY | PARTIAL | MISSING | CORRUPT | LFS_NOT_RECOVERED."""
    processed = Path(processed or PROCESSED)
    sig = (str(processed), _signature(processed))
    with _cache_lock:
        if _cache.get("sig") == sig:
            return _cache["result"]
    files = [check_file(processed / n, c) for n, c in REQUIRED.items()]
    st = {f["status"] for f in files}
    if st == {"missing"}:
        status = MISSING
    elif "lfs_pointer" in st:
        status = LFS
    elif st & {"corrupt", "empty", "missing_columns"}:
        status = CORRUPT
    elif "missing" in st:
        status = PARTIAL
    else:
        status = READY
    res = {"status": status, "ready": status == READY, "files": files,
           "missing": [f["file"] for f in files if f["status"] == "missing"],
           "problems": [f for f in files if f["status"] not in ("ok", "missing")]}
    with _cache_lock:
        _cache.update(sig=sig, result=res)
    return res


def core_ready() -> bool:
    return evaluate()["ready"]


def clear_cache():
    with _cache_lock:
        _cache.clear()


# --------------------------------------------------------------------------- archives
def _expected_sizes() -> dict:
    """Expected archive sizes from the checksum cache written when the archives were last verified."""
    try:
        cache = json.loads((PROCESSED / "archive_checksums.json").read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    for k, sha in cache.items():
        name, size, _ = (k.split("|") + ["", ""])[:3]
        out[name] = {"bytes": int(size) if size.isdigit() else None, "sha256": sha}
    return out


def archive_report() -> dict:
    """Cheap per-archive state (no CRC pass over hundreds of MB): lfs_pointer | corrupt | valid."""
    from .acquire import lfs_pointer
    exp = _expected_sizes()
    items = []
    for z in sorted(z for d in ARCHIVE_DIRS for z in Path(d).glob("*.zip")):
        size = z.stat().st_size
        e = exp.get(z.name, {})
        it = {"file": z.name, "bytes": size, "expected_bytes": e.get("bytes"), "expected_sha256": e.get("sha256"),
              "checksum": "not_verified_here (see /api/data/inventory?refresh=true)"}
        ptr = lfs_pointer(z)
        if ptr:
            it.update(status="lfs_pointer", expected_bytes=ptr.get("size"), expected_sha256=ptr.get("oid"),
                      message="Git LFS archives have not been downloaded.")
        else:
            try:
                with zipfile.ZipFile(z) as zf:
                    n_csv = sum(1 for i in zf.infolist() if i.filename.lower().endswith(".csv"))
                it.update(status="valid" if n_csv else "corrupt", csv_members=n_csv,
                          message=None if n_csv else "archive holds no CSV member")
                if it["status"] == "valid" and e.get("bytes") and e["bytes"] != size:
                    it.update(status="corrupt", message=f"size {size:,} B differs from verified {e['bytes']:,} B")
            except (zipfile.BadZipFile, OSError) as exc:
                it.update(status="corrupt", message=f"not a valid ZIP: {exc}")
        items.append(it)
    count = lambda s: sum(1 for i in items if i["status"] == s)
    uploads = sorted(p.name for p in UPLOADS.glob("*.csv"))
    return {"items": items, "total": len(items), "valid": count("valid"), "lfs_pointers": count("lfs_pointer"),
            "corrupt": count("corrupt"), "uploads": len(uploads), "ingestable": count("valid") + len(uploads) > 0}


# --------------------------------------------------------------------------- manifest
def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _dataset_files(processed: Path):
    for p in sorted(processed.rglob("*")):
        rel = p.relative_to(processed).as_posix()
        if p.is_file() and rel not in NOT_DATASET and not any(part.startswith(".") for part in Path(rel).parts):
            yield rel, p


def load_manifest(processed: Path | None = None) -> dict | None:
    try:
        return json.loads((Path(processed or PROCESSED) / MANIFEST).read_text())
    except (OSError, ValueError):
        return None


def build_manifest(processed: Path | None = None, provenance: str = "pipeline") -> dict:
    processed = Path(processed or PROCESSED)
    try:
        spans = json.loads((processed / "spans.json").read_text())
    except (OSError, ValueError):
        spans = {}
    try:
        reg = json.loads((processed / "datasets.json").read_text())
    except (OSError, ValueError):
        reg = {}
    return {
        "schema_version": SCHEMA_VERSION, "processing_version": PROCESSING_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "provenance": provenance,
        "coverage": {s: {"first": v.get("first"), "last": v.get("last"), "detections": v.get("detections")} for s, v in spans.items()},
        "sources": {k: {"container": Path(str(v.get("container", ""))).name, "rows_kept": (v.get("quality") or {}).get("rows_kept"),
                        "processed_at": v.get("processed_at")} for k, v in reg.items()},
        "archives": {k: v["sha256"] for k, v in _expected_sizes().items() if v.get("sha256")},
        "files": {rel: {"bytes": p.stat().st_size, "sha256": _sha256(p)} for rel, p in _dataset_files(processed)},
    }


def write_manifest(processed: Path | None = None, provenance: str = "pipeline") -> dict:
    processed = Path(processed or PROCESSED)
    m = build_manifest(processed, provenance)
    tmp = processed / f".{MANIFEST}.tmp"
    tmp.write_text(json.dumps(m, indent=1), newline="\n")
    os.replace(tmp, processed / MANIFEST)
    return m


def verify_manifest(processed: Path, manifest: dict, only: set | None = None) -> list[str]:
    """Return problems (missing file / size / SHA-256 mismatch) for the manifest's files (optionally a subset)."""
    bad = []
    for rel, e in manifest.get("files", {}).items():
        if only is not None and rel not in only and rel.split("/")[0] not in only:
            continue
        p = processed / rel
        if not p.exists():
            bad.append(f"{rel}: missing")
        elif p.stat().st_size != e["bytes"]:
            bad.append(f"{rel}: {p.stat().st_size} B, manifest says {e['bytes']} B")
        elif _sha256(p) != e["sha256"]:
            bad.append(f"{rel}: SHA-256 mismatch")
    return bad


# --------------------------------------------------------------------------- seed installation
SEED_STATE: dict = {"state": "idle", "detail": None, "at": None}


def _has_files(d: Path) -> bool:
    return d.exists() and any(p.is_file() for p in d.rglob("*"))


def _log(msg: str):
    print(msg, file=sys.stderr, flush=True)       # visible in container logs whatever the logging config
    log_.info(msg)


def install_seed(target: Path | None = None, seed: Path | None = None, log=_log, source: str = "image seed") -> dict:
    """Install the bundled processed dataset into `target` when it holds no dataset (or an older copy of the seed)."""
    target, seed = Path(target or PROCESSED), Path(seed or SEED_PROCESSED)

    def done(state, detail):
        SEED_STATE.update(state=state, detail=detail, at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        log(f"[seed] {state}: {detail}")
        return dict(SEED_STATE)

    if not seed.is_dir() or (target.exists() and seed.resolve() == target.resolve()):
        return done("not_applicable", "no bundled seed dataset (source checkout)")
    sm = load_manifest(seed)
    if not sm or not evaluate(seed)["ready"]:
        return done("failed", f"bundled seed at {seed} has no manifest or fails validation; nothing installed")
    cur, tm = evaluate(target), load_manifest(target)
    if cur["ready"]:
        newer_seed = bool(tm and tm.get("provenance") == "repository-seed" and sm["created_at"] > tm.get("created_at", ""))
        if not newer_seed:
            return done("skipped", f"existing dataset kept ({(tm or {}).get('provenance', 'no manifest')}, created {(tm or {}).get('created_at', '?')})")
    elif cur["status"] != MISSING:
        return done("skipped", f"target holds a {cur['status']} dataset; left untouched for an administrator "
                               "(Data Management -> Load Repository Dataset)")
    lock = target.parent / ".seed.lock"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        if time.time() - lock.stat().st_mtime < 3600:
            return done("skipped", "another process is installing the seed")
        lock.unlink(missing_ok=True)
        return install_seed(target, seed, log, source)
    SEED_STATE.update(state="installing", detail=f"copying {len(sm['files'])} files")
    tmp = target.parent / f".processed.seed-{os.getpid()}"
    try:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(seed, tmp)
        bad = verify_manifest(tmp, sm)
        if bad:
            shutil.rmtree(tmp, ignore_errors=True)
            return done("failed", f"seed copy failed verification ({len(bad)} files), nothing installed: {bad[:5]}")
        sm = sm | {"installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "installed_from": source}
        (tmp / MANIFEST).write_text(json.dumps(sm, indent=1), newline="\n")
        if target.exists():
            if _has_files(target):
                prev = target.parent / "processed.previous"
                shutil.rmtree(prev, ignore_errors=True)
                os.replace(target, prev)
            else:
                shutil.rmtree(target)
        os.replace(tmp, target)
        clear_cache()
        if not evaluate(target)["ready"]:
            return done("failed", "installed seed does not validate")
        return done("installed", f"{len(sm['files'])} files, created {sm['created_at']}, coverage "
                                 + ", ".join(f"{k} {v['first']}..{v['last']}" for k, v in sm.get("coverage", {}).items()))
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        return done("failed", f"{type(exc).__name__}: {exc}")
    finally:
        lock.unlink(missing_ok=True)


def _fetch(url: str, dest: Path, session, retries: int = 4):
    last = None
    for attempt in range(retries):
        try:
            with session.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
            return
        except Exception as exc:          # transient network errors: retry with back-off
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"download failed: {url.rsplit('/', 1)[-1]}: {type(last).__name__}")


def install_remote_seed(target: Path | None = None, base_url: str | None = None, session=None, log=_log) -> dict:
    """Download the committed processed dataset (manifest first) into a temp dir beside `target`, verify every file's
    size and SHA-256 against the manifest, then install it with the same rules as the bundled seed."""
    target, base_url = Path(target or PROCESSED), (base_url or SEED_URL).rstrip("/")
    if base_url.lower() == "off":
        return {"state": "not_applicable", "detail": "no bundled seed and remote seed disabled (PYROSCOPE_SEED_URL=off)"}
    cur = evaluate(target)
    if cur["status"] != MISSING:
        SEED_STATE.update(state="skipped", detail=f"target holds a {cur['status']} dataset; remote seed not needed")
        return dict(SEED_STATE)
    import requests
    session = session or requests.Session()
    staging = target.parent / f".remote-seed-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    SEED_STATE.update(state="installing", detail="downloading manifest", source="remote")
    try:
        _fetch(f"{base_url}/{MANIFEST}", staging / MANIFEST, session)
        m = json.loads((staging / MANIFEST).read_text())
        files = m.get("files") or {}
        if not files:
            raise RuntimeError("remote manifest lists no files")
        for i, rel in enumerate(sorted(files), 1):
            SEED_STATE["detail"] = f"downloading {i}/{len(files)}: {rel}"
            _fetch(f"{base_url}/{rel}", staging / rel, session)
        log(f"[seed] downloaded {len(files)} files from the repository (commit {BUILD_COMMIT or 'main'}); verifying")
        res = install_seed(target, staging, log=log, source=f"repository download ({BUILD_COMMIT or 'main'})")
        SEED_STATE["source"] = "remote"
        return res | {"source": "remote"}
    except Exception as exc:
        SEED_STATE.update(state="failed", detail=f"remote seed: {exc}", at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        log(f"[seed] failed: remote seed: {exc}")
        return dict(SEED_STATE)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def build_info() -> dict:
    man = load_manifest()
    core = evaluate()
    return {"commit": BUILD_COMMIT, "image": IMAGE, "bundled_seed": SEED_PROCESSED.is_dir(),
            "dataset": {"status": readiness_status(core, None), "ready": core["ready"],
                        "processing_version": (man or {}).get("processing_version"), "manifest_created_at": (man or {}).get("created_at"),
                        "provenance": (man or {}).get("provenance"), "installed_at": (man or {}).get("installed_at")},
            "seed": {k: SEED_STATE.get(k) for k in ("state", "detail", "at", "source")}}


def install_seed_in_background(on_done=None):
    if not SEED_PROCESSED.is_dir():
        if evaluate()["status"] != MISSING:
            SEED_STATE.update(state="not_applicable", detail="no bundled seed dataset; existing data directory used")
            return

        def remote():
            res = install_remote_seed()
            if on_done and res.get("state") == "installed":
                on_done()
        SEED_STATE.update(state="checking", detail="no bundled seed in this image; fetching the verified dataset of this commit")
        threading.Thread(target=remote, name="pyroscope-remote-seed", daemon=True).start()
        return

    def run():
        res = install_seed()
        if on_done and res["state"] == "installed":
            on_done()
    SEED_STATE.update(state="checking")
    threading.Thread(target=run, name="pyroscope-seed", daemon=True).start()


# --------------------------------------------------------------------------- full readiness report
def _json_ok(p: Path) -> bool:
    try:
        json.loads(p.read_text())
        return True
    except (OSError, ValueError):
        return False


def _running(job: dict | None) -> bool:
    return (job or {}).get("state") == "running" or SEED_STATE.get("state") in ("installing", "checking")


def readiness_status(core: dict, job: dict | None = None) -> str:
    """Dataset status with the job overlay: PROCESSING while a job / seed install runs, FAILED after a failed job."""
    if core["ready"]:
        return READY
    if _running(job):
        return PROCESSING
    if (job or {}).get("state") == "failed":
        return FAILED
    return core["status"]


def readiness(job: dict | None = None, admin: bool = False) -> dict:
    core = evaluate()
    job = job or {}
    arch = archive_report()
    agg = sorted(p.name for p in (PROCESSED / "agg").glob("*.parquet") if not p.name.endswith(".lst.parquet"))
    hot = sum(1 for _ in (PROCESSED / "hotspots").rglob("*.parquet"))
    reg_path = PROCESSED / "datasets.json"
    reg = json.loads(reg_path.read_text()) if _json_ok(reg_path) else None
    reg_status = {"status": "missing" if not reg_path.exists() else "corrupt" if reg is None else "ok",
                  "sources": len(reg or {}),
                  "without_aggregate": sorted(k for k in (reg or {}) if f"{k}.parquet" not in agg)}
    if reg_status["status"] == "ok" and reg_status["without_aggregate"]:
        reg_status["status"] = "inconsistent"
    calib = {n: (PROCESSED / n).exists() and _json_ok(PROCESSED / n) for n in ("bridge_calibrations.json", "noaa21_calibration.json")}
    models = PROCESSED / "models"
    forecast = {"meta": (models / "forecast_meta.json").exists(), "model": (models / "forecast_models.pkl").exists(),
                "cells": (PROCESSED / "forecast_cells.parquet").exists()}
    man = load_manifest()
    coverage = {}
    if core["ready"]:
        sp = json.loads((PROCESSED / "spans.json").read_text())
        coverage = {s: {"first": v["first"], "last": v["last"], "detections": v.get("detections"),
                        "gap_days": len(v.get("gap_days", []))} for s, v in sp.items()}

    running = _running(job)
    status = readiness_status(core, job)

    if core["ready"]:
        nxt = {"code": "none", "message": "Processed dataset is ready."}
    elif running:
        nxt = {"code": "wait", "message": "A dataset job is running; this page refreshes automatically."}
    elif core["status"] == LFS or (not arch["ingestable"] and arch["lfs_pointers"]):
        nxt = {"code": "recover_lfs", "message": "Git LFS archives have not been downloaded.",
               "command": "git lfs pull", "endpoint": "POST /api/data/recover-lfs", "admin_only": True}
    elif arch["ingestable"]:
        nxt = {"code": "load_repo", "message": "Archives are available: load the repository dataset to build the processed summaries.",
               "endpoint": "POST /api/data/load-repo", "admin_only": True}
    elif arch["corrupt"]:
        nxt = {"code": "replace_archives", "message": "Repository archives are corrupt; replace them (git lfs pull / re-download from FIRMS).",
               "admin_only": True}
    else:
        nxt = {"code": "install_dataset", "message": "No processed dataset and no FIRMS archives are available to this backend. "
               "Deploy the image that bundles the processed dataset, or add archives and load the repository dataset.", "admin_only": True}

    files = core["files"]
    if not admin:   # filesystem details are for administrators only
        files = [{k: f[k] for k in ("file", "status")} for f in files]
    out = {
        "status": status, "dataset_status": core["status"], "ready": core["ready"],
        "required": files, "missing": core["missing"],
        "processed_files": sum(1 for _ in _dataset_files(PROCESSED)) if PROCESSED.exists() else 0,
        "coverage": coverage, "satellites": sorted(coverage),
        "registry": reg_status, "aggregates": len(agg), "hotspot_partitions": hot,
        "calibration": calib, "forecast": forecast,
        "archives": {k: arch[k] for k in ("total", "valid", "lfs_pointers", "corrupt", "uploads", "ingestable")}
                    | {"items": [{k: i.get(k) for k in ("file", "status", "message", "expected_bytes", "bytes")} for i in arch["items"]]},
        "lfs": {"pointers": arch["lfs_pointers"], "recovered": arch["lfs_pointers"] == 0,
                "message": "Git LFS archives have not been downloaded." if arch["lfs_pointers"] else None},
        "job": {k: job.get(k) for k in ("state", "step", "started", "finished", "error", "mode")} | {"log_tail": (job.get("log") or [])[-3:]},
        "seed": dict(SEED_STATE),
        "manifest": {k: man.get(k) for k in ("schema_version", "processing_version", "created_at", "provenance", "installed_at")} if man else None,
        "last_success": (man or {}).get("created_at") if core["ready"] else None,
        "next_action": nxt,
    }
    if admin:
        out["paths"] = {"processed": str(PROCESSED), "seed": str(SEED_PROCESSED)}
    return out


def main(argv=None):
    cmd = (argv or sys.argv[1:] or ["check"])[0]
    if cmd == "check":
        print(json.dumps(readiness(admin=True), indent=1, default=str))
        return 0 if core_ready() else 1
    if cmd == "manifest":
        prov = (argv or sys.argv[1:])[1] if len(argv or sys.argv[1:]) > 1 else "repository-seed"
        m = write_manifest(provenance=prov)
        print(f"manifest: {len(m['files'])} files, provenance {prov}")
        return 0
    if cmd == "seed":
        logging.basicConfig(level=logging.INFO)
        r = install_seed(log=print)
        return 0 if r["state"] in ("installed", "skipped", "not_applicable") else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
