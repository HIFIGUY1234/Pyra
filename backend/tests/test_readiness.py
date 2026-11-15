"""Processed-dataset readiness, seed installation, Load Repository Dataset workflow and seed-DB security.

Two kinds of test, kept apart on purpose:
* SYNTHETIC fixtures (tiny Parquet / JSON / ZIP files written to tmp_path) exercise every failure mode of the
  readiness checks. They never feed the calendar and are never presented as observations.
* REPOSITORY tests (marked `repo_data`) run against the committed data/processed dataset and the real
  /api/calendar output.
"""
import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd
import pytest

import tests.test_api  # noqa: F401  (throw-away DATABASE_URL before the app is imported)
from fastapi.testclient import TestClient

from app import dataset, main, store
from app.config import PROCESSED, ROOT

c = TestClient(main.app)
ADMIN, GOV, ANALYST = ({"X-User": u} for u in ("admin", "forest.officer", "analyst"))
repo_data = pytest.mark.skipif(not store.has_data(), reason="committed processed dataset not present")


# --------------------------------------------------------------------------- synthetic fixtures
def _write_core(d: Path, skip=(), **override):
    d.mkdir(parents=True, exist_ok=True)
    frames = {
        "daily_cell.parquet": pd.DataFrame({"acq_date": pd.to_datetime(["2024-01-01"]), "cell_id": [1], "satellite": ["Aqua"],
                                            "daynight": ["D"], "n": [1], "frp_sum": [2.0], "frp_n": [1]}),
        "monthly_cell.parquet": pd.DataFrame({"ym": [202401], "cell_id": [1], "satellite": ["Aqua"], "daynight": ["D"],
                                              "n": [1], "frp_sum": [2.0], "days": [1]}),
        "cells.parquet": pd.DataFrame({"cell_id": [1], "lat": [20.0], "lon": [80.0], "state": ["X"], "district_id": ["X/1"]}),
        "districts.parquet": pd.DataFrame({"district_id": ["X/1"], "district": ["D"], "state": ["X"]}),
    }
    for name, df in frames.items():
        if name not in skip:
            (override.get(name) if name in override else df).to_parquet(d / name, index=False)
    if "spans.json" not in skip:
        (d / "spans.json").write_text(override.get("spans.json", json.dumps({"Aqua": {"first": "2024-01-01", "last": "2024-01-31", "gap_days": []}})))
    return d


def test_all_required_files_present_is_ready(tmp_path):
    r = dataset.evaluate(_write_core(tmp_path / "p"))
    assert r["status"] == "READY" and r["ready"] and not r["missing"]


def test_all_required_files_missing(tmp_path):
    (tmp_path / "p").mkdir()
    r = dataset.evaluate(tmp_path / "p")
    assert r["status"] == "MISSING" and set(r["missing"]) == set(dataset.REQUIRED)


@pytest.mark.parametrize("name", ["cells.parquet", "districts.parquet", "spans.json"])
def test_one_missing_core_file_is_partial(tmp_path, name):
    r = dataset.evaluate(_write_core(tmp_path / "p", skip=(name,)))
    assert r["status"] == "PARTIAL" and r["missing"] == [name] and not r["ready"]


def test_empty_file_is_corrupt(tmp_path):
    d = _write_core(tmp_path / "p")
    (d / "monthly_cell.parquet").write_bytes(b"")
    r = dataset.evaluate(d)
    assert r["status"] == "CORRUPT" and r["problems"][0]["status"] == "empty"


def test_truncated_parquet_is_corrupt(tmp_path):
    d = _write_core(tmp_path / "p")
    raw = (d / "daily_cell.parquet").read_bytes()
    (d / "daily_cell.parquet").write_bytes(raw[: len(raw) // 2])     # a partially written file
    assert dataset.evaluate(d)["status"] == "CORRUPT"


def test_invalid_spans_json(tmp_path):
    assert dataset.evaluate(_write_core(tmp_path / "a", **{"spans.json": "{not json"}))["status"] == "CORRUPT"
    bad_range = json.dumps({"Aqua": {"first": "2024-02-01", "last": "2024-01-01", "gap_days": []}})
    assert dataset.evaluate(_write_core(tmp_path / "b", **{"spans.json": bad_range}))["status"] == "CORRUPT"


def test_missing_columns_is_corrupt(tmp_path):
    d = _write_core(tmp_path / "p", **{"districts.parquet": pd.DataFrame({"district_id": ["X/1"]})})
    r = dataset.evaluate(d)
    assert r["status"] == "CORRUPT" and "missing columns" in r["problems"][0]["detail"]


def test_lfs_pointer_in_place_of_parquet(tmp_path):
    d = _write_core(tmp_path / "p")
    (d / "daily_cell.parquet").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:" + "0" * 64 + "\nsize 66588523\n")
    assert dataset.evaluate(d)["status"] == "LFS_NOT_RECOVERED"


def test_cache_refreshes_when_files_change(tmp_path):
    d = _write_core(tmp_path / "p")
    assert dataset.evaluate(d)["ready"]
    (d / "cells.parquet").unlink()
    assert dataset.evaluate(d)["status"] == "PARTIAL"     # (size, mtime) signature invalidates the cache
    _write_core(d)
    assert dataset.evaluate(d)["ready"]


def test_readiness_status_overlay():
    missing = {"status": "MISSING", "ready": False}
    assert dataset.readiness_status(missing, {"state": "running"}) == "PROCESSING"
    assert dataset.readiness_status(missing, {"state": "failed"}) == "FAILED"
    assert dataset.readiness_status({"status": "READY", "ready": True}, {"state": "failed"}) == "READY"


# --------------------------------------------------------------------------- archives
def _archives(monkeypatch, tmp_path, files: dict):
    d = tmp_path / "arch"
    d.mkdir()
    for name, content in files.items():
        if content == "ZIP":
            with zipfile.ZipFile(d / name, "w") as zf:
                zf.writestr("fire_archive_M-C61_1.csv", "latitude,longitude,acq_date,acq_time\n")
        else:
            (d / name).write_bytes(content)
    monkeypatch.setattr(dataset, "ARCHIVE_DIRS", (d,))
    import app.acquire  # noqa: F401
    return d


POINTER = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 1234567\n"


def test_lfs_pointer_archives_detected_without_opening_zip(monkeypatch, tmp_path):
    _archives(monkeypatch, tmp_path, {"DL_FIRE_X.zip": POINTER})
    r = dataset.archive_report()
    assert r["lfs_pointers"] == 1 and not r["ingestable"]
    it = r["items"][0]
    assert it["status"] == "lfs_pointer" and it["expected_bytes"] == 1234567 and it["message"] == "Git LFS archives have not been downloaded."


def test_valid_and_invalid_zip_archives(monkeypatch, tmp_path):
    _archives(monkeypatch, tmp_path, {"DL_FIRE_A.zip": "ZIP", "DL_FIRE_B.zip": b"PK\x03\x04 truncated garbage" * 10})
    r = dataset.archive_report()
    st = {i["file"]: i["status"] for i in r["items"]}
    assert st == {"DL_FIRE_A.zip": "valid", "DL_FIRE_B.zip": "corrupt"} and r["ingestable"]


# --------------------------------------------------------------------------- manifest + seed installation
def test_seed_installs_into_empty_target_with_verified_checksums(tmp_path):
    seed = _write_core(tmp_path / "seed")
    dataset.write_manifest(seed, provenance="repository-seed")
    target = tmp_path / "data" / "processed"
    (target / "agg").mkdir(parents=True)            # what config creates at import: empty dirs only
    r = dataset.install_seed(target, seed, log=lambda *a: None)
    assert r["state"] == "installed"
    assert dataset.evaluate(target)["ready"]
    m = dataset.load_manifest(target)
    assert m["provenance"] == "repository-seed" and m["installed_from"] == "image seed" and m["installed_at"]
    assert not dataset.verify_manifest(target, m)
    assert dataset.install_seed(target, seed, log=lambda *a: None)["state"] == "skipped"   # no duplicate copy


def test_seed_never_replaces_a_pipeline_dataset(tmp_path):
    seed = _write_core(tmp_path / "seed")
    target = _write_core(tmp_path / "data" / "processed")
    dataset.write_manifest(target, provenance="pipeline")
    dataset.write_manifest(seed, provenance="repository-seed")      # newer timestamp, still must not win
    before = (target / "daily_cell.parquet").read_bytes()
    assert dataset.install_seed(target, seed, log=lambda *a: None)["state"] == "skipped"
    assert (target / "daily_cell.parquet").read_bytes() == before


def test_seed_leaves_partial_target_for_an_administrator(tmp_path):
    seed = _write_core(tmp_path / "seed")
    dataset.write_manifest(seed, provenance="repository-seed")
    target = _write_core(tmp_path / "data" / "processed", skip=("cells.parquet",))
    r = dataset.install_seed(target, seed, log=lambda *a: None)
    assert r["state"] == "skipped" and "PARTIAL" in r["detail"]


def test_tampered_seed_is_refused(tmp_path):
    seed = _write_core(tmp_path / "seed")
    dataset.write_manifest(seed, provenance="repository-seed")
    m = json.loads((seed / "manifest.json").read_text())
    m["files"]["cells.parquet"]["sha256"] = "0" * 64
    (seed / "manifest.json").write_text(json.dumps(m))
    target = tmp_path / "data" / "processed"
    r = dataset.install_seed(target, seed, log=lambda *a: None)
    assert r["state"] == "failed" and not dataset.evaluate(target)["ready"]
    assert not any(p.name.startswith(".processed.seed") for p in target.parent.iterdir())   # temp copy cleaned up


@repo_data
def test_committed_manifest_matches_committed_dataset():
    """Stale-derived-files guard: the manifest shipped with the image must describe the committed Parquet."""
    m = dataset.load_manifest(PROCESSED)
    assert m and m["schema_version"] == dataset.SCHEMA_VERSION and m["coverage"]
    core = set(dataset.REQUIRED) | {"datasets.json", "agg"}
    assert not dataset.verify_manifest(PROCESSED, m, only=core), "run `python -m app.dataset manifest` after changing data/processed"


# --------------------------------------------------------------------------- API
def test_health_reports_data_readiness():
    h = c.get("/api/health").json()
    assert h["data"]["ready"] == h["has_data"] == store.has_data()
    assert h["status"] == ("ok" if h["database"]["ok"] and h["has_data"] else "degraded")


def test_readiness_hides_paths_from_non_admins():
    r = c.get("/api/data/readiness", headers=GOV).json()
    assert r["can_administer"] is False and "paths" not in r and "bytes" not in r["required"][0]
    a = c.get("/api/data/readiness", headers=ADMIN).json()
    assert a["can_administer"] is True and "paths" in a and "bytes" in a["required"][0]
    assert not any(k in json.dumps(a).lower() for k in ("password", "token", "secret"))


def test_non_admins_get_403_for_dataset_administration():
    for path in ("/api/data/load-repo", "/api/data/recover-lfs", "/api/data/process"):
        assert c.post(path, headers=GOV).status_code == 403
        assert c.post(path, headers=ANALYST).status_code == 403


def test_missing_dataset_returns_structured_409(monkeypatch, tmp_path):
    (tmp_path / "empty").mkdir()
    real = dataset.evaluate
    monkeypatch.setattr(dataset, "evaluate", lambda processed=None: real(tmp_path / "empty"))
    r = c.get("/api/calendar?region=country", headers=ANALYST)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "DATASET_NOT_READY" and d["status"] == "MISSING" and d["next_action"]["code"]
    assert c.get("/api/health").json()["status"] == "degraded"


def test_load_repo_refuses_pointer_only_archives(monkeypatch, tmp_path):
    (tmp_path / "empty").mkdir()
    real = dataset.evaluate
    monkeypatch.setattr(dataset, "evaluate", lambda processed=None: real(tmp_path / "empty"))
    monkeypatch.setattr(main.store, "has_data", lambda: False)
    _archives(monkeypatch, tmp_path, {"DL_FIRE_X.zip": POINTER})
    monkeypatch.setattr(dataset, "UPLOADS", tmp_path / "no_uploads")
    r = c.post("/api/data/load-repo", headers=ADMIN)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "LFS_NOT_RECOVERED" and "git lfs pull" in d["message"] and d["archives"][0]["expected_bytes"] == 1234567
    assert main.JOB["state"] != "running"                     # no ingestion was started


def test_failed_rebuild_keeps_previous_outputs(monkeypatch, tmp_path):
    """Ingestion that yields no source aggregate must stop before touching the summaries."""
    monkeypatch.setattr(main.ingest, "process_all", lambda **k: {"x": {"error": "Git LFS pointer"}})
    monkeypatch.setattr(main.ingest, "AGG_DIR", tmp_path / "no-agg")
    built = []
    monkeypatch.setattr(main.store, "build_summaries", lambda **k: built.append(1))
    assert main._job_lock.acquire(blocking=False)
    main._run_job(False, False, False)                       # releases the lock in `finally`
    assert main.JOB["state"] == "failed" and "left untouched" in main.JOB["error"] and not built


@repo_data
def test_load_repo_validates_existing_dataset_without_rebuild(monkeypatch):
    monkeypatch.setattr(main.ingest, "process_all", lambda **k: pytest.fail("must not re-ingest a valid dataset"))
    assert main._job_lock.acquire(blocking=False)
    main.JOB.update(state="running", log=[])
    main._run_job(False, False, False, "validate")
    assert main.JOB["state"] == "done", main.JOB.get("error")
    assert any("calendar check" in line for line in main.JOB["log"])
    r = c.get("/api/data/readiness", headers=ADMIN).json()
    assert r["status"] == "READY" and r["next_action"]["code"] == "none"


@repo_data
def test_load_repo_endpoint_chooses_validate_mode(monkeypatch):
    started = []
    monkeypatch.setattr(main, "_run_job", lambda *a: (started.append(a), main._job_lock.release()))
    r = c.post("/api/data/load-repo", headers=ADMIN)
    assert r.status_code == 200 and r.json()["mode"] == "validate" and started[0][3] == "validate"


def test_recover_lfs_reports_failure_honestly(monkeypatch):
    monkeypatch.setattr(main.acquire, "recover_lfs", lambda: [{"file": "DL_FIRE_X.zip", "status": "checksum_mismatch"}])
    monkeypatch.setattr(main.acquire, "build_report", lambda: {})
    r = c.post("/api/data/recover-lfs", headers=ADMIN).json()
    assert r["ok"] is False and r["failed"] == ["DL_FIRE_X.zip"]


# --------------------------------------------------------------------------- calendar on REAL repository data
@repo_data
@pytest.mark.parametrize("region", ["country", "state:Odisha"])
def test_calendar_real_data_daily_monthly_and_missing_days(region):
    sp = store.spans()
    r = c.get(f"/api/calendar?region={region}&year=2024", headers=ANALYST)
    assert r.status_code == 200
    cal = r.json()
    assert cal["year"] == 2024 and len(cal["days"]) == 366 and len(cal["months"]) == 12
    assert {2012, 2024} <= set(cal["years_available"])
    day = cal["days"][0]
    for sat in ("Suomi NPP", "NOAA-20", "NOAA-21", "Aqua", "Terra"):
        assert sat in day and f"{sat}|frp" in day and f"{sat}|status" in day
    assert "veq" in day and "provenance" in day
    # A documented sensor gap must be null (missing), never 0.
    for d in cal["days"]:
        for sat in ("Aqua", "Terra", "Suomi NPP", "NOAA-20"):
            if d["date"] in set(sp[sat]["gap_days"]):
                assert d[sat] is None, (sat, d["date"])


@repo_data
def test_calendar_real_data_outside_sensor_record_is_missing():
    cal = c.get("/api/calendar?region=country&year=2023", headers=ANALYST).json()
    jan = cal["days"][0]
    assert jan["date"] == "2023-01-01" and jan["NOAA-21"] is None          # NOAA-21 record starts 2023-03-01
    assert any(d["NOAA-21"] is not None for d in cal["days"][100:])


# --------------------------------------------------------------------------- seed database / credentials
SEED_DB = ROOT / "data" / "pyroscope.db"
seed_db = pytest.mark.skipif(not SEED_DB.exists() or SEED_DB.stat().st_size < 1000, reason="demo database not present")


@seed_db
def test_seed_db_has_no_session_secrets_or_hash_bytes():
    blob = SEED_DB.read_bytes()
    assert b"pbkdf2_sha256$" not in blob, "freed pages still hold a password hash: VACUUM the seed DB"
    con = sqlite3.connect(f"file:{SEED_DB.as_posix()}?mode=ro", uri=True)
    try:
        assert con.execute("select count(*) from user_sessions").fetchone()[0] == 0
        assert con.execute("select count(*) from users where locked_until is not null or failed_logins > 0").fetchone()[0] == 0
        assert con.execute("select count(*) from users").fetchone()[0] >= 5          # demo personas preserved
    finally:
        con.close()


def test_application_never_uses_the_tracked_seed_as_runtime_db():
    from app import config
    assert config.RUNTIME_DB != config.SEED_DB and "runtime" in config.RUNTIME_DB.parts
    assert config._default_database_url().endswith("runtime/pyroscope.db")
    assert "data/runtime/" in (ROOT / ".gitignore").read_text()


def test_fresh_database_initialises_reproducibly_without_credentials(tmp_path):
    import subprocess
    import sys
    code = ("from app import db_sync, models as M; from sqlalchemy import select; db_sync.init_db(); db_sync.init_db();"
            "s=M.Session(); us=list(s.scalars(select(M.User))); print(len(us), sum(1 for u in us if u.password_hash))")
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}", PYROSCOPE_ADMIN_PASSWORD="",
               PYROSCOPE_EMBEDDED_WORKER="0")
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=300, cwd=str(ROOT / "backend"))
    assert p.returncode == 0, p.stderr[-1500:]
    n_users, n_hashed = map(int, p.stdout.split()[-2:])
    assert n_users >= 5 and n_hashed == 0


def test_admin_bootstrap_from_env_and_rotation_revokes_sessions(tmp_path):
    import subprocess
    import sys
    code = ("import os; from app import db_sync, security, models as M; from sqlalchemy import select;"
            "db_sync.init_db(); s=M.Session(); a=s.scalar(select(M.User).where(M.User.username=='admin'));"
            "assert security.verify_password('Rotate-Me-0ne', a.password_hash); h1=a.password_hash;"
            "s.add(M.UserSession(user_id=a.id, token_sha256='x'*64, expires_at=M.now().replace(year=2099))); s.commit(); s.close();"
            "db_sync.init_db(); s=M.Session(); a=s.scalar(select(M.User).where(M.User.username=='admin')); assert a.password_hash==h1;"
            "assert s.scalar(select(M.UserSession)).revoked_at is None; s.close();"     # same password: no churn
            "os.environ['PYROSCOPE_ADMIN_PASSWORD']='Rotate-Me-Tw0'; db_sync.init_db(); s=M.Session();"
            "a=s.scalar(select(M.User).where(M.User.username=='admin'));"
            "assert security.verify_password('Rotate-Me-Tw0', a.password_hash) and not security.verify_password('Rotate-Me-0ne', a.password_hash);"
            "assert s.scalar(select(M.UserSession)).revoked_at is not None; print('ok')")
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{(tmp_path / 'boot.db').as_posix()}", PYROSCOPE_ADMIN_PASSWORD="Rotate-Me-0ne",
               PYROSCOPE_EMBEDDED_WORKER="0")
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=300, cwd=str(ROOT / "backend"))
    assert p.returncode == 0 and p.stdout.strip().endswith("ok"), p.stderr[-1500:]


def test_production_without_admin_password_fails_closed():
    from app import system_config
    v = system_config.validate({"PYROSCOPE_AUTH_MODE": "production", "PYROSCOPE_CORS_ORIGINS": "https://x.example.org"})
    assert v["mode"] == "production" and not v["ok"]
    assert any(i["key"] == "PYROSCOPE_ADMIN_PASSWORD" and i["level"] == "error" for i in v["issues"])
