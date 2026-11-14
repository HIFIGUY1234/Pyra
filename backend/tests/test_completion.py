"""Tests for the completion work: acquisition/LFS, product streams, harmonization science,
authentication, permissions, notifications, GIS layers, migrations."""
import importlib
import io
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import tests.test_api  # noqa: F401  (sets DATABASE_URL to a throw-away copy before the app is imported)
from fastapi.testclient import TestClient

from app import acquire, gis_layers, harmonize, ingest, notify, security, store
from app import models as M
from app.main import app

c = TestClient(app)
ADMIN, GOV, ORG, ANALYST = ({"X-User": u} for u in ("admin", "forest.officer", "org.user", "analyst"))
needs_data = pytest.mark.skipif(not store.has_data(), reason="pipeline has not been run")


# --------------------------------------------------------------------------- acquisition / LFS
def test_lfs_pointer_detected_not_treated_as_zip(tmp_path):
    z = tmp_path / "DL_FIRE_X.zip"
    z.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:" + "a" * 64 + "\nsize 123456\n")
    p = acquire.lfs_pointer(z)
    assert p == {"oid": "a" * 64, "size": 123456}
    st = acquire.archive_status(z)
    assert st["status"] == "lfs_pointer" and "git lfs pull" in st["message"]


def test_firms_fetch_requires_key_from_environment(monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FIRMS_MAP_KEY"):
        acquire.firms_fetch("MODIS_SP", "2001-01-01", "2001-01-10")


def test_firms_fetch_windows_and_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRMS_MAP_KEY", "x" * 32)
    monkeypatch.setattr(acquire, "RAW", tmp_path)
    calls = []

    class R:
        status_code = 200
        def __init__(self, t): self.text = t

    class S:
        def get(self, url, timeout):
            calls.append(url)
            d = url.rsplit("/", 1)[1]
            return R(f"latitude,longitude,acq_date,acq_time,satellite\n20,78,{d},0530,T\n")
    out = acquire.firms_fetch("MODIS_SP", "2001-01-01", "2001-01-25", session=S())
    assert len(calls) == 3 and "/10/2001-01-01" in calls[0] and "/5/2001-01-21" in calls[2]   # 10+10+5 days
    assert "x" * 32 in calls[0]                                                                  # key goes in the URL path, from env
    assert len(pd.read_csv(out)) == 3
    acquire.firms_fetch("MODIS_SP", "2001-01-01", "2001-01-25", session=S())
    assert len(calls) == 3                                                                       # restartable: windows cached


def test_inventory_report_is_honest_about_missing_history():
    rep = c.get("/api/data/inventory?refresh=true").json()
    assert all(a["status"] in ("valid", "lfs_pointer", "corrupt") for a in rep["archives"])
    sats = rep["satellites"]
    assert (sats["NOAA-20"]["status"] == "missing") == (rep["capabilities"]["noaa20"] == "missing")
    if sats["Terra"]["loaded"] and sats["Terra"]["loaded"]["archive"]["first"] > "2000-11-01":
        assert sats["Terra"]["status"] == "partial"
        assert rep["capabilities"]["real_morning_gap_correction"].startswith("blocked")
    assert rep["viirs_750m"]["status"] == "not_in_firms"
    assert Path(acquire.REPORT_MD).read_text().startswith("# PyroScope ingestion report")


# --------------------------------------------------------------------------- standardisation, all five satellites
def _raw(sat, conf, n=3, **kw):
    d = {"latitude": [20.1] * n, "longitude": [78.2] * n, "acq_date": ["2020-03-01"] * n, "acq_time": ["0530", "1330", "2010"][:n],
         "satellite": [sat] * n, "confidence": [conf] * n, "frp": ["12.5"] * n, "daynight": ["D"] * n, "scan": ["1.1"] * n, "track": ["1.0"] * n,
         "version": ["6.1"] * n}
    d.update(kw)
    return pd.DataFrame(d)


@pytest.mark.parametrize("code,sat,conf,score,cls", [
    ("T", "Terra", "85", 0.85, "high"), ("A", "Aqua", "20", 0.20, "low"), ("N", "Suomi NPP", "n", 0.55, "nominal"),
    ("1", "NOAA-20", "h", 0.90, "high"), ("N21", "NOAA-21", "l", 0.15, "low")])
def test_standardise_each_satellite_keeps_sensor_specific_confidence(code, sat, conf, score, cls):
    std, q = ingest.standardise(_raw(code, conf), "x.csv")
    assert set(std["satellite"]) == {sat} and q["rows_kept"] == 3
    assert (std["confidence_raw"] == conf).all()                       # original value preserved
    assert np.allclose(std["confidence_score"], score) and (std["confidence_class"] == cls).all()
    assert set(std["product_type"]) == ({"1km"} if sat in ("Terra", "Aqua") else {"375m"})
    assert np.allclose(std["pixel_area_km2"], 1.1)


def test_invalid_csv_and_duplicates():
    with pytest.raises(ValueError, match="missing required columns"):
        ingest.standardise(pd.DataFrame({"lat": [1]}), "bad.csv")
    raw = pd.concat([_raw("T", "50", 1)] * 3 + [_raw("T", "50", 1, latitude=["999"])])
    std, q = ingest.standardise(raw, "dup.csv")
    assert q["duplicates_removed"] == 2 and q["dropped_invalid_coordinates"] == 1 and len(std) == 1


def test_cross_sensor_neighbours_are_not_merged():
    raw = pd.concat([_raw("A", "50", 1), _raw("N", "n", 1)])
    std, q = ingest.standardise(raw, "both.csv")
    assert len(std) == 2 and q["duplicates_removed"] == 0


def test_750m_rows_form_a_separate_stream():
    raw = pd.concat([_raw("N", "n", 2), _raw("N", "n", 1, source_product=["750m"], acq_time=["0100"])])
    raw["source_product"] = raw["source_product"].fillna("375m")
    std, _ = ingest.standardise(raw, "mixed.csv")
    assert sorted(std["product_type"]) == ["375m", "375m", "750m"]
    agg = ingest.aggregate_daily(std)
    assert set(agg["satellite"]) == {"Suomi NPP", "Suomi NPP 750m"}             # 375 m and 750 m counts never mix
    assert agg.loc[agg["satellite"] == "Suomi NPP", "n"].sum() == 2


# --------------------------------------------------------------------------- calibration maths (pure functions)
def test_fit_pair_learns_ratio_below_one_and_silent_rate():
    T, S = 48, 3
    moy = np.arange(T) % 12
    rng = np.random.default_rng(0)
    X = rng.uniform(200, 400, (T, S, 2))
    true_F = np.where(np.arange(2) == 0, 0.6, 0.2)[None, None, :]            # target sees FEWER than predictor
    Y = X * true_F
    ncell = np.full(S, 50.0)
    nact = np.full((T, S, 2), 50.0)                                            # no silent cells
    par = harmonize.fit_pair(np.ones((1, T)), moy, X, Y, Y, nact, nact, ncell)
    assert np.allclose(par["F"][0, :, :, 0], 0.6, atol=0.02) and np.allclose(par["F"][0, :, :, 1], 0.2, atol=0.02)
    yh, _ = harmonize.predict_pair(par, moy, X, nact, ncell)
    assert np.allclose(yh[0], Y, rtol=0.05)


def test_bootstrap_resamples_whole_years():
    years = np.repeat(np.arange(2012, 2020), 12)
    W, yrs = harmonize._boot_weights(years, np.ones(len(years), bool), 20, np.random.default_rng(1))
    for b in range(W.shape[0]):
        for y in yrs:
            assert len(set(W[b, years == y])) == 1                               # every month of a year shares one weight
    assert np.allclose(W.sum(1), len(years))


@needs_data
def test_validation_actual_holdout_beats_both_baselines():
    v = c.get("/api/validation").json()
    assert v["validation_kind"] == "actual_holdout"
    assert v["morning_gap"]["validation_kind"] == "simulated_withheld_experiment"
    o = v["overall"]["wape_pct"]
    assert o < v["baseline_constant_ratio"]["wape_pct"] < v["baseline_raw_modis"]["wape_pct"]
    assert set(v["by_daynight"]) == {"day", "night"} and v["by_daynight"]["day"]["n"] > 0
    assert 0 <= v["band_coverage_pct"] <= 100 and v["band_nominal_pct"] == 90.0
    assert "ACTUAL hold-out" in v["methodology"]["sensor_stage"] and "SIMULATED" in v["methodology"]["morning_gap_stage"]


@needs_data
def test_seam_simulated_fallback_is_labelled_and_keeps_genuine_change():
    s = c.get("/api/validation/seam-test").json()
    if s["real_seam_possible"]:
        assert s["mode"] == "real" and s["validation_kind"] == "actual_seam"
    else:
        assert s["mode"] == "simulated" and s["validation_kind"] == "simulated_seam" and "real_seam_note" in s
    g = s["genuine_change"]
    assert set(g) >= {"detectable", "direction", "harmonized_band_excludes_no_change"}
    lo, hi = s["step_harmonized_band"]
    assert lo <= s["step_harmonized"] <= hi * 1.5


@needs_data
def test_morning_gap_reports_real_vs_simulated_mode():
    m = c.get("/api/morning-gap/analysis").json()
    assert m["mode"] in ("real_correction", "simulated_only")
    if m["terra_only_real_months"] == 0:
        assert m["mode"] == "simulated_only" and m["mode_message"]
    assert set(m["by_daynight_overlap"]) == {"day", "night"}


@needs_data
def test_product_pathway_and_750m_unavailable():
    pr = c.get("/api/harmonization/products").json()
    assert pr["viirs_750m"] in ("loaded", "unavailable")
    if pr["viirs_750m"] == "unavailable":
        r = c.get("/api/validation?product=750m")
        assert r.status_code == 400 and "750 m" in r.json()["detail"]
    # the calibration code is product-generic: any loaded VIIRS stream can be the target, separately
    t = harmonize.calibration_table("sh", None, None, ref="NOAA-21")
    assert t["reference_product"] == "NOAA-21" and "NOAA-21 VIIRS 375 m" in t["pair"]


@needs_data
def test_harmonized_never_adds_counts_and_actual_viirs_unchanged():
    s = c.get("/api/harmonization/summary").json()
    for r in s["series"]:
        if r["provenance"] == "actual_viirs":
            assert r["harmonized"] == r["viirs"]
    assert s["reference_product"] == "Suomi NPP VIIRS 375 m"


# --------------------------------------------------------------------------- authentication & permissions
def test_password_hashing():
    h = security.hash_password("Correct-Horse-9")
    assert h.startswith("pbkdf2_sha256$") and "Correct" not in h
    assert security.verify_password("Correct-Horse-9", h) and not security.verify_password("wrong", h)
    with pytest.raises(ValueError):
        security.hash_password("short")


def test_login_token_logout_and_lockout():
    u = {"username": "test.officer", "display_name": "Test Officer", "role": "gov_officer", "password": "Str0ng-Passw0rd"}
    r = c.post("/api/users", json=u, headers=ADMIN)
    assert r.status_code in (200, 409)
    assert c.post("/api/users", json=u, headers=GOV).status_code == 403                    # only admins create users
    bad = c.post("/api/auth/login", json={"username": "test.officer", "password": "nope"})
    assert bad.status_code == 401
    tok = c.post("/api/auth/login", json={"username": "test.officer", "password": u["password"]}).json()["token"]
    H = {"Authorization": f"Bearer {tok}"}
    me = c.get("/api/auth/me", headers=H).json()
    assert me["username"] == "test.officer" and me["auth"] == "token" and me["role"] == "gov_officer"
    with M.Session() as s:                                                                  # only the digest is stored
        assert s.query(M.UserSession).filter(M.UserSession.token_sha256 == tok).count() == 0
    assert c.post("/api/auth/logout", headers=H).status_code == 200
    assert c.get("/api/auth/me", headers=H).status_code == 401                              # revoked
    for _ in range(security.MAX_FAILED):
        c.post("/api/auth/login", json={"username": "test.officer", "password": "nope"})
    assert c.post("/api/auth/login", json={"username": "test.officer", "password": u["password"]}).status_code == 429


def test_production_mode_ignores_identity_header(monkeypatch):
    monkeypatch.setenv("PYROSCOPE_AUTH_MODE", "production")
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/meta").json()["users"] == []                                         # no persona list
    assert c.get("/api/auth/me", headers=ADMIN).status_code == 401
    assert c.get("/api/alerts", headers=ADMIN).status_code == 401                           # gate covers every route
    assert c.put("/api/thresholds/config", json={}, headers=ADMIN).status_code == 401
    u = {"username": "prod.admin", "display_name": "P", "role": "admin", "password": "Pr0d-Admin-Pass"}
    monkeypatch.setenv("PYROSCOPE_AUTH_MODE", "dev")
    c.post("/api/users", json=u, headers=ADMIN)
    monkeypatch.setenv("PYROSCOPE_AUTH_MODE", "production")
    tok = c.post("/api/auth/login", json={"username": "prod.admin", "password": u["password"]}).json()["token"]
    assert c.get("/api/alerts", headers={"Authorization": f"Bearer {tok}"}).status_code == 200


def test_org_users_cannot_see_other_organisations():
    c.post("/api/users", json={"username": "org.two", "display_name": "Org Two", "role": "org_user", "password": "0rg-Two-Passw0rd",
                               "organisation_id": 1}, headers=ADMIN)
    oid = c.post("/api/organisations", json={"name": "Private Co", "sector": "Insurance"}, headers=ORG).json()["id"]
    tok = c.post("/api/auth/login", json={"username": "org.two", "password": "0rg-Two-Passw0rd"}).json()["token"]
    H = {"Authorization": f"Bearer {tok}"}
    assert oid not in [o["id"] for o in c.get("/api/organisations", headers=H).json()["items"]]
    assert c.get(f"/api/organisations/{oid}/overview", headers=H).status_code in (403, 404)


# --------------------------------------------------------------------------- notifications
@needs_data
def test_notifications_only_after_approval_and_only_to_verified(monkeypatch):
    dates = c.get("/api/meta").json()["issue_dates"]
    c.post("/api/alerts/evaluate", json={"issue_date": dates[-2]}, headers=GOV)
    items = c.get("/api/alerts?alert_type=ADVISORY&limit=1000&open_only=true").json()["items"]
    target = next(a for a in items if a["status"] not in ("REJECTED", "SUPERSEDED") and not a["status"].startswith("DOWNGRADED"))
    full = c.get(f"/api/alerts/{target['alert_id']}").json()
    rt = full["payload"]["routing"]
    auth = rt["authorities"][0]
    body = {"land_use": full["land_use"] if "land_use" in full else full["payload"].get("land_use"), "state": full["state"], "authority": auth["authority"],
            "role_title": auth["role_title"], "level": 1, "contact_channel": "webhook", "contact_value": "https://hooks.example.org/pyroscope",
            "confirm_verified": True}
    assert c.post("/api/authorities", json={**body, "contact_value": "http://insecure"}, headers=ADMIN).status_code == 422
    cid = c.post("/api/authorities", json=body, headers=ADMIN).json()["id"]
    sent = []
    monkeypatch.setenv("PYROSCOPE_NOTIFY_PROVIDER", "webhook")
    monkeypatch.setenv("PYROSCOPE_WEBHOOK_ALLOWED_HOSTS", "hooks.example.org")
    monkeypatch.setitem(notify.SENDERS, "webhook", lambda url, payload: sent.append((url, payload)))
    with M.Session() as s:                                                                   # attach the verified contact as a recipient
        a = s.query(M.Alert).filter(M.Alert.alert_id == target["alert_id"]).one()
        s.add(M.AlertRecipient(alert=a, authority=auth["authority"], role_title=auth["role_title"], level=1, contact_id=cid, simulated=True))
        s.commit()
    assert not sent                                                                          # nothing sent on generation
    c.post(f"/api/alerts/{target['alert_id']}/acknowledge", json={}, headers=GOV)
    assert not sent                                                                          # nor on acknowledgement
    r = c.post(f"/api/alerts/{target['alert_id']}/approve", json={"note": "reviewed"}, headers=GOV)
    assert r.status_code == 200
    assert len(sent) == 1 and sent[0][0] == "https://hooks.example.org/pyroscope"
    assert "Not a public emergency warning" in sent[0][1]["disclaimer"]
    log = c.get(f"/api/notifications/log?alert_id={target['alert_id']}", headers=GOV).json()["items"]
    st = {x["status"] for x in log}
    assert "SENT" in st and all(x["status"] in ("SENT", "BLOCKED_NO_VERIFIED_CONTACT") for x in log)
    assert c.get("/api/notifications/log", headers=ANALYST).status_code == 403
    c.delete(f"/api/authorities/{cid}", headers=ADMIN)


def test_delivery_failure_is_logged_not_raised(monkeypatch):
    monkeypatch.setenv("PYROSCOPE_NOTIFY_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.invalid")
    monkeypatch.setenv("SMTP_FROM", "pyroscope@example.org")
    assert notify.status()["external_delivery_enabled"]

    def boom(addr, body):
        raise ConnectionError("smtp down")
    with M.Session() as s:
        con = M.AuthorityContact(land_use="Forest", state="Goa", authority="A", role_title="R", level=1, contact_channel="email",
                                 contact_value="dfo@example.org", verified=True, is_template=False)
        al = M.Alert(alert_id="TEST-FAILDELIV", alert_type="PRE_FIRE_RISK_ADVISORY", status="APPROVED")
        s.add_all([con, al])
        s.flush()
        s.add(M.AlertRecipient(alert=al, authority="A", role_title="R", level=1, contact_id=con.id))
        s.flush()
        res = notify.deliver(s, al, approved_by="forest.officer", sender_override=boom)
        assert res[0]["status"] == "FAILED" and "smtp down" in res[0]["error"]
        s.rollback()


# --------------------------------------------------------------------------- GIS
@needs_data
def test_admin_jurisdiction_layer_overrides_land_use():
    before = c.get("/api/jurisdictions/resolve?lat=21.1&lon=79.0").json()
    poly = {"type": "Polygon", "coordinates": [[[78.9, 21.0], [79.3, 21.0], [79.3, 21.3], [78.9, 21.3], [78.9, 21.0]]]}
    body = {"name": "Test industrial estate", "land_use": "Industrial", "source": "Test fixture (not real)", "geojson": poly}
    assert c.post("/api/jurisdictions/layers", json={**body, "land_use": "Volcano"}, headers=ADMIN).status_code == 400
    assert c.post("/api/jurisdictions/layers", json=body, headers=GOV).status_code == 403
    lid = c.post("/api/jurisdictions/layers", json=body, headers=ADMIN).json()["id"]
    j = c.get("/api/jurisdictions/resolve?lat=21.1&lon=79.0").json()
    assert j["land_use"] == "Industrial" and "administrator layer" in j["land_use_source"]
    assert any(l["id"] == lid for l in c.get("/api/geo/coverage").json()["jurisdiction_layers"])
    c.delete(f"/api/jurisdictions/layers/{lid}", headers=ADMIN)
    assert c.get("/api/jurisdictions/resolve?lat=21.1&lon=79.0").json()["land_use"] == before["land_use"]


def test_geo_coverage_is_explicit():
    g = c.get("/api/geo/coverage").json()
    assert g["global"] is False and g["administrative_coverage"]["countries"] == ["India"]
    assert all({"source", "resolution", "date", "licence"} <= set(d) for d in g["datasets"])


@needs_data
def test_exposure_layers_unavailable_vs_loaded(monkeypatch, tmp_path):
    monkeypatch.setattr(gis_layers, "EXPOSURE_DIR", tmp_path)
    gis_layers.clear()
    from app import analytics
    analytics.clear()
    cr = c.get("/api/critical-regions").json()
    assert "infrastructure" not in cr["weights"] and any("infrastructure" in x for x in cr["not_available"])
    csv = "latitude,longitude,type\n30.9,75.85,substation\n21.1,79.0,hospital\n"
    r = c.post("/api/geo/exposure", data={"kind": "infrastructure", "source": "Test fixture (not real)"},
               files={"file": ("infra.csv", io.BytesIO(csv.encode()), "text/csv")}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["rows"] == 2
    cr = c.get("/api/critical-regions").json()
    assert "infrastructure" in cr["weights"] and abs(sum(cr["weights"].values()) - 1) < 1e-9
    analytics.clear()
    gis_layers.clear()


@needs_data
def test_custom_polygon_region(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "CUSTOM", tmp_path / "custom.json")
    poly = {"type": "Polygon", "coordinates": [[[75.0, 30.0], [76.5, 30.0], [76.5, 31.5], [75.0, 31.5], [75.0, 30.0]]]}
    r = c.post("/api/regions/custom", json={"name": "Test polygon", "geojson": poly}).json()
    assert r["region_id"].startswith("custom:") and r["n_cells"] == 36
    assert c.get(f"/api/calendar?region={r['region_id']}&year=2024").status_code == 200
    assert c.get(f"/api/forecast/{r['region_id']}").status_code == 200
    store.region_cells.cache_clear()


# --------------------------------------------------------------------------- migrations
def test_migration_adds_columns_and_backs_up(tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE roles (id INTEGER PRIMARY KEY, name VARCHAR(40) UNIQUE NOT NULL, description VARCHAR(200), permissions JSON)")
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(60) UNIQUE NOT NULL, display_name VARCHAR(120), role_id INTEGER NOT NULL, "
                "organisation_id INTEGER, jurisdiction_state VARCHAR(80), jurisdiction_land_use VARCHAR(40), is_demo BOOLEAN, created_at DATETIME)")
    con.execute("INSERT INTO roles (id, name) VALUES (1, 'admin')")
    con.execute("INSERT INTO users (id, username, role_id) VALUES (1, 'keepme', 1)")
    con.commit(); con.close()
    from sqlalchemy import create_engine
    from app import migrate
    monkeypatch.setattr(M, "engine", create_engine(f"sqlite:///{db}"))
    monkeypatch.setattr(migrate, "DATABASE_URL", f"sqlite:///{db}")
    res = migrate.upgrade(log=lambda *a: None)
    assert "users.password_hash" in res["new_columns"] and res["backup"] and Path(res["backup"]).exists()
    con = sqlite3.connect(db)
    assert con.execute("SELECT username, is_active FROM users").fetchall() == [("keepme", 1)]     # existing record preserved
    con.close()
    assert migrate.upgrade(dry_run=True)["new_columns"] == []
