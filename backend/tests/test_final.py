"""Final-completion tests: robust LFS recovery, collection/version parsing, pipeline CLI,
calibration model selection (year-blocked, leakage-free), morning-gap validation design,
seam verdict / robustness, health checks."""
import hashlib
import json

import numpy as np
import pytest

import tests.test_api  # noqa: F401  (throw-away database before the app is imported)
from fastapi.testclient import TestClient

from app import acquire, harmonize, pipeline, store
from app.main import app

c = TestClient(app)
needs_data = pytest.mark.skipif(not store.has_data(), reason="pipeline has not been run")
PAYLOAD = b"PK\x03\x04" + b"real-archive-bytes" * 500


def _pointer(path, data=PAYLOAD, oid=None):
    oid = oid or hashlib.sha256(data).hexdigest()
    path.write_text(f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {len(data)}\n")


class _Resp:
    def __init__(self, status, body=b"", fail_after=None):
        self.status_code, self.body, self.fail_after = status, body, fail_after

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, n):
        if self.fail_after is not None:
            yield self.body[: self.fail_after]
            raise ConnectionError("connection reset mid-transfer")
        yield self.body


class _Session:
    """Scripted fake: each call pops the next behaviour; honours Range requests."""
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def get(self, url, stream=True, timeout=None, headers=None):
        self.calls.append(dict(headers or {}))
        kind = self.script.pop(0)
        start = int((headers or {}).get("Range", "bytes=0-")[6:-1] or 0)
        if kind == "404":
            return _Resp(404)
        if kind == "503":
            return _Resp(503)
        if kind == "cut":
            return _Resp(206 if start else 200, PAYLOAD[start:], fail_after=len(PAYLOAD) // 3)
        if kind == "wrong":
            return _Resp(200, b"X" * len(PAYLOAD))
        return _Resp(206 if start else 200, PAYLOAD[start:])


def _recover(tmp_path, script, **kw):
    s = _Session(script)
    res = acquire.recover_lfs(base_url="https://example.invalid", log=lambda *a: None, root=tmp_path, session=s,
                              sleep=lambda *_: None, report_path=tmp_path / "report.json", **kw)
    return res, s


# --------------------------------------------------------------------------- LFS recovery
def test_lfs_valid_pointer_recovered_and_verified(tmp_path):
    _pointer(tmp_path / "A.zip")
    res, _ = _recover(tmp_path, ["ok"])
    assert res[0]["status"] == "recovered" and (tmp_path / "A.zip").read_bytes() == PAYLOAD
    assert json.loads((tmp_path / "report.json").read_text())["results"][0]["status"] == "recovered"


def test_lfs_invalid_pointer_rejected(tmp_path):
    (tmp_path / "B.zip").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\n")
    res, s = _recover(tmp_path, [])
    assert res[0]["status"] == "invalid_pointer" and not s.calls


def test_lfs_missing_remote_object(tmp_path):
    _pointer(tmp_path / "C.zip")
    res, s = _recover(tmp_path, ["404"])
    assert res[0]["status"] == "remote_missing" and len(s.calls) == 1        # not retried
    assert acquire.lfs_pointer(tmp_path / "C.zip")                           # pointer untouched


def test_lfs_interrupted_transfer_resumes_with_range(tmp_path):
    _pointer(tmp_path / "D.zip")
    res, s = _recover(tmp_path, ["cut", "503", "ok"])
    assert res[0]["status"] == "recovered" and (tmp_path / "D.zip").read_bytes() == PAYLOAD
    assert "Range" in s.calls[-1] and s.calls[-1]["Range"] != "bytes=0-"     # resumed, not restarted


def test_lfs_checksum_mismatch_never_overwrites(tmp_path):
    _pointer(tmp_path / "E.zip")
    res, _ = _recover(tmp_path, ["wrong"])
    assert res[0]["status"] == "checksum_mismatch"
    assert acquire.lfs_pointer(tmp_path / "E.zip") and not (tmp_path / "E.zip.part").exists()


def test_lfs_already_recovered_archive_untouched(tmp_path):
    (tmp_path / "F.zip").write_bytes(PAYLOAD * 3)
    res, s = _recover(tmp_path, [])
    assert res[0]["status"] == "already_present" and not s.calls


def test_lfs_retries_exhausted_keeps_partial_for_resume(tmp_path):
    _pointer(tmp_path / "G.zip")
    res, _ = _recover(tmp_path, ["cut", "503", "503"], retries=2)
    assert res[0]["status"] == "download_failed" and res[0]["resumable"]
    assert acquire.lfs_pointer(tmp_path / "G.zip")


# --------------------------------------------------------------------------- collection / version parsing
def test_collection_from_archive_name_and_versions_kept_verbatim():
    ci = acquire.collection_info("DL_FIRE_M-C61_848456.zip", {"6.03": 10, "61.03": 5, "6.1NRT": 2})
    assert ci["instrument"] == "MODIS" and ci["collection"] == "Collection 6.1"
    st = {v["version"]: v["status"] for v in ci["row_versions"]}
    assert st == {"6.03": "undocumented", "61.03": "undocumented", "6.1NRT": "documented"}
    v = acquire.collection_info("DL_FIRE_J2V-C2_846939.zip", {"2": 1, "weird": 1})
    assert v["collection"] == "Collection 2" and {r["version"]: r["status"] for r in v["row_versions"]}["weird"] == "unknown"


def test_pointer_status_is_never_a_zip(tmp_path):
    _pointer(tmp_path / "H.zip")
    a = acquire.archive_status(tmp_path / "H.zip")
    assert a["status"] == "lfs_pointer" and a["integrity"] == "not_downloaded" and a["expected_bytes"] == len(PAYLOAD)


# --------------------------------------------------------------------------- pipeline CLI
def test_pipeline_rejects_unknown_and_conflicting_args():
    with pytest.raises(SystemExit):
        pipeline.parse_args(["--bogus"])
    with pytest.raises(SystemExit):
        pipeline.parse_args(["--skip-train", "--retrain"])
    a = pipeline.parse_args(["--only-new", "--skip-weather", "--dry-run"])
    assert a.only_new and a.skip_weather and a.dry_run and not a.recover_lfs


def test_pipeline_dry_run_changes_nothing(tmp_path, monkeypatch):
    before = pipeline.STATE.read_text() if pipeline.STATE.exists() else None
    plan = pipeline.main(["--dry-run", "--only-new"])
    assert {"archives", "sources_new", "would_ingest"} <= set(plan)
    assert (pipeline.STATE.read_text() if pipeline.STATE.exists() else None) == before


# --------------------------------------------------------------------------- calibration model selection
@needs_data
def test_model_selection_is_year_blocked_and_reported():
    ms = harmonize.model_selection("mg")
    assert ms["selected"] in harmonize.CANDIDATES
    assert set(ms["designs"]) == {"leave_one_year_out", "block_20_month", "rolling_origin_forward", "rolling_origin_backward"}
    for d in ms["designs"].values():
        assert set(d["scores"]) == set(harmonize.CANDIDATES)
    # blocks have the Terra-only-era length and the calibration beats the constant ratio there
    blk = ms["designs"]["block_20_month"]
    assert blk["n_folds"] >= 3
    sc = blk["scores"]
    assert sc[ms["selected"]]["state"]["wape_pct"] < sc["constant"]["state"]["wape_pct"]
    assert 0 <= ms["band"]["empirical_coverage_pct"] <= 100


@needs_data
def test_cv_folds_never_train_on_a_test_year():
    p, args, train = harmonize._stage_data("mg", harmonize.VIIRS_REFERENCE)
    years = p.ax.year.to_numpy()
    tidx = np.where(train)[0]
    for s0 in range(0, len(tidx) - harmonize.SIM_TERRA_ONLY_MONTHS + 1, harmonize.BLOCK_STEP):
        tt = tidx[s0: s0 + harmonize.SIM_TERRA_ONLY_MONTHS]
        tr = train & ~np.isin(years, np.unique(years[tt]))
        assert not np.isin(years[tr], years[tt]).any()
    # leakage guard on the fitted model itself: changing a test year's targets must not change its prediction
    y0 = int(np.unique(years[train])[3])
    W = (train & (years != y0)).astype(float)[None]
    X, Ys, Yt, NX, NY = args
    a = harmonize.fit_pair(W, p.moy, X, Ys, Yt, NX, NY, p.ncell)
    Yt2, Ys2 = Yt.copy(), Ys.copy()
    Yt2[years == y0] *= 5
    Ys2[years == y0] *= 5
    b = harmonize.fit_pair(W, p.moy, X, Ys2, Yt2, NX, NY, p.ncell)
    assert np.allclose(a["F"], b["F"]) and np.allclose(a["a"], b["a"])


@needs_data
def test_morning_gap_validation_uses_terra_only_length_blocks_not_decade_extrapolation():
    v = c.get("/api/validation").json()
    mg = v["morning_gap"]
    assert mg["design"] == "block_20_month" and mg["selected_model"] in harmonize.CANDIDATES
    for a, b in mg["blocks"]:
        months = (b // 100 - a // 100) * 12 + (b % 100 - a % 100) + 1
        assert months <= 36                                   # 20 overlap months (may straddle a coverage gap)
    ch = mg["chain_experiment"]
    if ch.get("period"):
        a, b = ch["period"]
        assert (b // 100 - a // 100) * 12 + (b % 100 - a % 100) + 1 <= harmonize.SIM_TERRA_ONLY_MONTHS
    assert mg["metrics"]["wape_pct"] < mg["baseline_constant_ratio"]["wape_pct"]


@needs_data
def test_seam_verdict_targets_reference_sensor_not_one():
    s = c.get("/api/validation/seam-test").json()
    assert s["verdict"] in ("pass", "partial", "fail", "not_evaluable") and "verdict_rule" in s
    tgt = s["step_true"] or s["step_reference_sensor"]
    assert abs(s["artificial_jump_after"] - abs(np.log(s["step_harmonized"] / tgt))) < 1e-9
    assert "resolvable_change_pct" in s["genuine_change"]


@needs_data
def test_seam_robustness_endpoint():
    r = c.get("/api/validation/seam-robustness").json()
    assert [w["window_months"] for w in r["windows"]] == [12, 24, 36]
    assert r["states"] and all("verdict" in s or "error" in s for s in r["states"])


@needs_data
def test_model_selection_endpoint_validates_stage():
    assert c.get("/api/validation/model-selection?stage=sh").status_code == 200
    assert c.get("/api/validation/model-selection?stage=xx").status_code == 422


def test_health_reports_database_and_storage():
    h = c.get("/api/health").json()
    assert h["database"]["ok"] is True and "free_gb" in h["storage"]


@needs_data
def test_terra_only_sensitivity_is_labelled_estimate():
    r = c.get("/api/morning-gap/sensitivity").json()
    assert r["n_months"] >= 1 and r["period"][0] < 200207
    assert set(r["aqua_equivalent_total_by_model"]) == set(harmonize.CANDIDATES)
    assert "no Aqua ground truth" in r["note"]


@needs_data
def test_stress_test_interpretation_matches_numbers():
    st = harmonize.extrapolation_stress_test()
    best = min(st["scores"], key=lambda k: st["scores"][k]["wape_pct"])
    assert st["most_robust"] == best and best in st["interpretation"]
