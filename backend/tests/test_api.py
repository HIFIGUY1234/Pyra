"""API tests against the processed repository data.

Run the pipeline first (python -m app.pipeline). Tests that mutate state use a
throw-away SQLite database so they never touch the working one.
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="pyroscope_test_"))
_src = Path(__file__).resolve().parents[2] / "data" / "pyroscope.db"
if _src.exists():
    shutil.copy(_src, _tmp / "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402

from app import store  # noqa: E402
from app.main import app  # noqa: E402

pytestmark = pytest.mark.skipif(not store.has_data(), reason="pipeline has not been run")
c = TestClient(app)
ADMIN, GOV, ORG, ANALYST = ({"X-User": u} for u in ("admin", "forest.officer", "org.user", "analyst"))

GETS = [
    "/api/health", "/api/meta", "/api/geo/states", "/api/geo/cells?region=state:Goa", "/api/dashboard/summary",
    "/api/hotspots?start=2026-10-25&end=2026-10-31&limit=500", "/api/hotspots?start=2024-03-01&end=2024-03-07&region=state:Odisha&satellites=Aqua,Terra",
    "/api/hotspots/cell-layer?ym_from=202403&ym_to=202404&region=state:Odisha", "/api/data/status", "/api/data/quality",
    "/api/harmonization/summary", "/api/harmonization/summary?region=state:Punjab&split=201701", "/api/harmonization/compare",
    "/api/morning-gap/analysis?state=Punjab", "/api/sensor-harmonizer/calibration?state=Odisha", "/api/uncertainty", "/api/uncertainty?split=201701",
    "/api/validation", "/api/validation?region=state:Mizoram&split=201801", "/api/validation/seam-test", "/api/validation/seam-test?split=201901&window=12",
    "/api/calendar?year=2024", "/api/calendar?region=bbox:74,29,77,32&year=2012", "/api/historical-trends", "/api/historical-trends?region=state:Assam",
    "/api/historical-trends/regions?level=state", "/api/historical-trends/regions?level=district", "/api/anomalies", "/api/anomalies?region=state:Punjab&level=district",
    "/api/critical-regions", "/api/observations/quality", "/api/observations/quality?region=state:Kerala", "/api/observations/alternatives", "/api/observations/overpasses",
    "/api/forecast/model", "/api/forecast/ranking", "/api/forecast/ranking?level=state", "/api/forecast/country", "/api/forecast/state:Punjab",
    "/api/forecast/state:Punjab/grid-cells", "/api/forecast/bbox:76,10,78,12", "/api/thresholds/config", "/api/jurisdictions/resolve?lat=21.1&lon=79.0",
    "/api/jurisdictions/resolve?lat=0&lon=0", "/api/authorities", "/api/alerts", "/api/reports",
]


@pytest.mark.parametrize("url", GETS)
def test_get_ok(url):
    r = c.get(url)
    assert r.status_code == 200, r.text[:400]


def test_harmonized_series_never_mixes_provenance():
    s = c.get("/api/harmonization/summary?split=201701").json()["series"]
    for row in s:
        if row["provenance"] == "actual_viirs":
            assert row["harmonized"] == row["viirs"]            # actual VIIRS is passed through untouched
        elif row["veq"] is not None:
            assert row["veq_lo"] <= row["veq"] <= row["veq_hi"] or row["veq"] < 5
            assert row["harmonized"] != (row["terra"] or 0) + (row["aqua"] or 0) + (row["viirs"] or 0)
    assert any(r["provenance"] == "morning_gap_sensor" for r in s) and any(r["provenance"] == "sensor_calibrated" for r in s)


def test_validation_is_chronological_and_reported():
    v = c.get("/api/validation").json()
    assert v["test_period"][1] < v["split"]
    assert min(v["train_years"]) * 100 + 1 >= v["split"]
    assert v["status"] in ("good", "moderate", "poor")
    assert v["overall"]["wape_pct"] < v["baseline_raw_modis"]["wape_pct"]


def test_seam_does_not_force_smoothness():
    s = c.get("/api/validation/seam-test").json()
    assert s["mode"] == "simulated" and s["real_seam_possible"] is False
    assert s["artificial_jump_after"] < s["artificial_jump_before"]
    assert abs(s["step_harmonized"] - 1.0) > 1e-6          # a genuine change remains


def test_missing_days_are_null_not_zero():
    cal = c.get("/api/calendar?year=2022").json()
    gap = [d for d in cal["days"] if d["Suomi NPP|status"] == "sensor_gap"]
    assert gap and all(d["Suomi NPP"] is None for d in gap)
    y2012 = c.get("/api/calendar?year=2012").json()["days"]
    assert y2012[0]["Suomi NPP"] is None and y2012[0]["Suomi NPP|status"] == "outside_record"


def test_region_probability_is_not_an_average():
    f = c.get("/api/forecast/state:Punjab").json()
    cells = c.get("/api/forecast/state:Punjab/grid-cells").json()["cells"]
    ps = [x["p"] for x in cells]
    reg = f["regional"]
    assert reg["p_any_lower"] <= reg["p_any"] <= reg["p_any_upper"]
    assert abs(reg["p_any_lower"] - max(ps)) < 1e-3
    assert "not" in f["meaning"] and "hotspot" in f["meaning"]
    assert all(0 <= x["p_lo"] <= x["p"] <= x["p_hi"] <= 1 for x in cells)


def test_bad_inputs():
    assert c.get("/api/forecast/planet:mars").status_code == 400
    assert c.get("/api/hotspots?start=2026-10-31&end=2026-10-01").status_code == 400
    assert c.get("/api/hotspots?start=2020-01-01&end=2021-01-01").status_code == 400
    assert c.get("/api/validation?split=2017").status_code == 400
    assert c.put("/api/thresholds/config", json={"high": 0.9, "very_high": 0.8}, headers=ADMIN).status_code == 422


def test_roles_enforced():
    assert c.put("/api/thresholds/config", json={}, headers=ANALYST).status_code == 403
    assert c.post("/api/alerts/evaluate", json={}, headers=ANALYST).status_code == 403
    assert c.get("/api/organisations", headers=GOV).status_code == 403
    assert c.post("/api/data/load-repo", headers=GOV).status_code == 403
    assert c.get("/api/meta", headers={"X-User": "nobody"}).status_code == 200      # public metadata
    assert c.get("/api/authorities", headers={"X-User": "nobody"}).status_code == 401


def test_threshold_config_roundtrip():
    r = c.put("/api/thresholds/config", headers=ADMIN, json={"scope_type": "land_use", "scope_value": "Forest", "watch": 0.15, "moderate": 0.35,
                                                             "high": 0.55, "very_high": 0.75, "cooldown_hours": 48, "evidence_min": 1, "rationale": "test"})
    assert r.status_code == 200
    cfg = [x for x in r.json()["configs"] if x["scope_type"] == "land_use"][0]
    assert cfg["tiers"][3]["min"] == 0.55
    assert c.delete(f"/api/thresholds/config/{cfg['id']}", headers=ADMIN).status_code == 200


def test_alert_lifecycle_and_safety():
    dates = c.get("/api/meta").json()["issue_dates"]
    first = c.post("/api/alerts/evaluate", json={"issue_date": dates[-3]}, headers=GOV).json()
    assert first["status"] == "ok" and first["created"] > 0
    again = c.post("/api/alerts/evaluate", json={"issue_date": dates[-3]}, headers=GOV).json()
    assert again["created"] == 0 and again["duplicates_skipped"] + again["cooldown_suppressed"] >= first["created"]   # deterministic ids
    later = c.post("/api/alerts/evaluate", json={"issue_date": dates[-1]}, headers=GOV).json()
    assert later["status"] == "ok"
    adv = c.get("/api/alerts?alert_type=ADVISORY&limit=1000").json()
    # no verified contact was ever registered -> nothing may be "routed", and nothing is delivered
    assert adv["items"] and all(a["routing_status"] == "ADMIN_JURISDICTION_REVIEW_REQUIRED" for a in adv["items"])
    det = c.get("/api/alerts?alert_type=UNVERIFIED_SATELLITE_DETECTION&limit=5").json()["items"]
    assert det and all(d["classification"] == "Unverified Satellite Hotspot Detection" for d in det)
    full = c.get(f"/api/alerts/{det[0]['alert_id']}").json()
    assert "not a confirmed wildfire" in full["payload"]["label"]
    aid = next(a["alert_id"] for a in adv["items"] if a["status"] in ("JURISDICTION_REVIEW_REQUIRED", "NEW"))
    one = c.get(f"/api/alerts/{aid}").json()
    for key in ("alert_id", "alert_type", "bounding_box", "grid_cells", "probability_pct", "risk_category", "prediction_period", "generated_at_utc",
                "generated_at_local", "evidence", "recent_satellite_observations", "data_quality", "model_uncertainty", "recommended_action", "routing"):
        assert key in one["payload"], key
    assert all(r["delivery_status"] == "NOT_SENT_NO_VERIFIED_CONTACT" and r["simulated"] for r in one["recipients"])
    assert c.post(f"/api/alerts/{aid}/acknowledge", json={}, headers=ANALYST).status_code == 403
    assert c.post(f"/api/alerts/{aid}/acknowledge", json={}, headers=GOV).json()["status"] == "ACKNOWLEDGED"
    assert c.post(f"/api/alerts/{aid}/reject", json={}, headers=GOV).status_code == 400            # reason required
    assert c.post(f"/api/alerts/{aid}/escalate", json={"note": "to nodal officer"}, headers=GOV).json()["status"] == "ESCALATED"
    assert c.post(f"/api/alerts/{aid}/reject", json={"note": "field check negative"}, headers=GOV).json()["status"] == "REJECTED"
    assert c.post(f"/api/alerts/{aid}/approve", json={}, headers=GOV).status_code == 409           # closed
    hist = c.get(f"/api/alerts/{aid}").json()["history"]
    assert [h["action"] for h in hist][-3:] == ["ACKNOWLEDGE", "ESCALATE", "REJECT"]
    v = c.post(f"/api/alerts/{det[0]['alert_id']}/verify", json={"note": "confirmed by range officer"}, headers=GOV).json()
    assert v["status"] == "VERIFIED_FIRE_INCIDENT" and v["classification"] == "Verified Fire Incident"
    assert not any("PUBLIC" in a["alert_type"] for a in c.get("/api/alerts?limit=1000").json()["items"])


def test_verified_contact_enables_routing():
    j = c.get("/api/jurisdictions/resolve?lat=21.1&lon=79.0").json()
    assert j["routing_status"] == "ADMIN_JURISDICTION_REVIEW_REQUIRED" and "Administrator Jurisdiction Review Required" in j["message"]
    body = {"land_use": j["land_use"], "state": j["state"], "authority": j["authorities"][0]["authority"], "role_title": j["authorities"][0]["role_title"],
            "level": 1, "contact_channel": "in-app"}
    assert c.post("/api/authorities", json=body, headers=ADMIN).status_code == 400          # must attest verification
    cid = c.post("/api/authorities", json={**body, "confirm_verified": True}, headers=ADMIN).json()["id"]
    assert c.get("/api/jurisdictions/resolve?lat=21.1&lon=79.0").json()["routing_status"] == "ROUTED_TO_VERIFIED_CONTACT"
    assert c.delete(f"/api/authorities/{cid}", headers=ADMIN).status_code == 200


def test_organisation_privacy_and_overview():
    oid = c.post("/api/organisations", json={"name": "Test Utility", "sector": "Electricity"}, headers=ORG).json()["id"]
    loc = {"name": "Substation A", "land_use_tag": "Utility Corridor", "latitude": 30.9, "longitude": 75.85, "buffer_km": 30, "alert_threshold": 0.5}
    assert c.post(f"/api/organisations/{oid}/locations", json=loc, headers=ORG).status_code == 200
    assert c.post(f"/api/organisations/{oid}/locations", json={**loc, "latitude": 123}, headers=ORG).status_code == 422
    ov = c.get(f"/api/organisations/{oid}/overview", headers=ORG).json()
    assert ov["locations"][0]["forecast"]["status"] in ("ok", "no_cells")
    assert c.get(f"/api/organisations/{oid}/overview", headers=ANALYST).status_code == 403
    assert c.get(f"/api/organisations/{oid}/overview", headers=ADMIN).status_code == 200


def test_reports_pdf_and_csv():
    r = c.post("/api/reports/generate", json={"region_id": "state:Goa", "format": "pdf"}, headers=ANALYST)
    assert r.status_code == 200, r.text[:500]
    d = c.get(f"/api/reports/{r.json()['id']}/download", headers=ANALYST)
    assert d.status_code == 200 and d.content[:4] == b"%PDF"
    r2 = c.post("/api/reports/generate", json={"region_id": "state:Goa", "format": "csv", "kind": "harmonized"}, headers=ANALYST).json()
    body = c.get(f"/api/reports/{r2['id']}/download", headers=ANALYST).text
    assert "provenance" in body.splitlines()[0] and "viirs_equivalent_estimate" in body.splitlines()[0]
    assert c.post("/api/reports/generate", json={"region_id": "nope:1", "format": "pdf"}, headers=ANALYST).status_code == 400
