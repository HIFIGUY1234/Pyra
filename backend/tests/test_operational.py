"""Operational sensor transition: historical vs operational reference, per-sensor forecasts, bridges."""
import numpy as np
import pandas as pd
import pytest

import tests.test_api  # noqa: F401  (throw-away DB before app import)
from fastapi.testclient import TestClient

from app import bridge, forecast, operational, store
from app.config import HISTORICAL_REFERENCE, PLATFORMS, VIIRS_REFERENCE
from app.main import app

c = TestClient(app)
ADMIN, GOV = {"X-User": "admin"}, {"X-User": "forest.officer"}
needs_models = pytest.mark.skipif(not (store.has_data() and len(forecast.models_available()) >= 2), reason="sensor models not trained")


def test_historical_reference_unchanged_and_snpp_retired():
    assert HISTORICAL_REFERENCE == VIIRS_REFERENCE == "Suomi NPP"
    assert PLATFORMS["Suomi NPP"]["status"] == "retired" and PLATFORMS["Suomi NPP"]["science_data_end"] == "2026-11-02"
    assert PLATFORMS["NOAA-21"]["noaa_role"] == "primary successor"


def test_snpp_never_eligible_as_operational():
    assert "Suomi NPP" not in operational.OPERATIONAL_CANDIDATES
    with pytest.raises(ValueError, match="not an operational candidate"):
        operational.select("Suomi NPP", "admin", "admin", "trying to select a retired sensor")


def test_legacy_snpp_forecast_flagged_stale():
    m = forecast._meta("Suomi NPP")
    if not m:
        pytest.skip("legacy model absent")
    assert m["serving_status"]["status"] == "STALE_RETIRED_SENSOR" and "historical" in m["serving_status"]["message"]


@needs_models
def test_per_sensor_models_independent():
    metas = {s: forecast._meta(s) for s in ("NOAA-20", "NOAA-21")}
    for s, m in metas.items():
        assert m["reference_sensor"] == s and s in m["target"] and m["nrt_in_labels"] is False
        assert m["model_version"].startswith(forecast.slug(s)) and m["trained_at"]
        sq = pd.Timestamp(m["science_quality_last"])
        assert pd.Timestamp(m["split"]["test_until"]) <= sq                       # no NRT label in the test period
        assert pd.Timestamp(m["split"]["test_from"]) > pd.Timestamp(m["split"]["calibrate_until"])
        ev = m["evaluation"]
        assert {"brier", "brier_skill", "roc_auc", "pr_auc", "ece", "specificity", "missed_event_rate"} <= set(ev)
        assert {"month", "season", "state", "land_use", "coverage", "activity"} <= set(m["breakdowns"])
    assert metas["NOAA-20"]["model_version"] != metas["NOAA-21"]["model_version"]
    # NOAA-21 labels exclude the pre-operational period
    assert metas["NOAA-21"]["label_start"] == "2024-01-17"


@needs_models
def test_label_rules_no_leakage_no_missing_as_negative():
    ds = forecast.build_dataset(lambda *a: None, "NOAA-21")
    Y, dates = ds["Y"][-1], ds["dates"]
    sq = pd.Timestamp(ds["science_last"])
    late = (dates + pd.Timedelta(days=7)) > sq
    assert np.isnan(Y[late]).all()                                                 # windows into NRT are unknown
    early = dates + pd.Timedelta(days=1) < pd.Timestamp("2024-01-17")
    assert np.isnan(Y[early]).all()                                                # pre-operational labels unknown
    assert np.isin(np.unique(Y[~np.isnan(Y)]), [0, 1]).all()


@needs_models
def test_operational_selection_evidence_and_admin():
    s = c.get("/api/reference/operational").json()
    assert s["historical_reference"]["platform"] == "Suomi NPP"
    for cand in s["candidates"]:
        assert set(cand["checks"]) == set(operational.CRITERIA)
    passing = [x["sensor"] for x in s["candidates"] if x["passes"]]
    if not passing:
        assert s["operational_reference"] is None and s["operational_status"] == "UNAVAILABLE" and s["unavailable_reason"]
        return
    assert s["operational_reference"] == passing[0]                                # NOAA order among passers
    other = [p for p in passing if p != passing[0]]
    assert c.put("/api/reference/operational", json={"platform": passing[0], "reason": "x" * 10}, headers=GOV).status_code == 403
    if other:
        r = c.put("/api/reference/operational", json={"platform": other[0], "reason": "admin test choice"}, headers=ADMIN).json()
        assert r["operational_reference"] == other[0] and r["selection_mode"] == "administrator"
        assert c.get("/api/forecast/model").json()["reference_sensor"] == other[0]
    c.put("/api/reference/operational", json={"platform": None, "reason": "revert to evidence default"}, headers=ADMIN)
    assert c.get("/api/reference/operational").json()["operational_reference"] == passing[0]


def test_failing_candidate_cannot_be_selected(monkeypatch):
    real = operational.evaluate

    def fake(sensor):
        e = dict(real(sensor))
        e["checks"] = {**e.get("checks", {}), "C6": False}
        e["passes"] = False
        return e
    operational.clear()
    monkeypatch.setattr(operational, "evaluate", fake)
    with pytest.raises(ValueError, match="does not meet"):
        operational.select("NOAA-20", "admin", "admin", "should be refused")
    assert operational.candidates() and all(not x["passes"] for x in operational.candidates())
    s = operational.summary()
    assert s["operational_reference"] is None and "C6" in s["unavailable_reason"]
    monkeypatch.undo()
    operational.clear()
    forecast.clear()


@needs_models
def test_forecast_outputs_carry_reference_and_sensor_param():
    r = c.get("/api/forecast/state:Punjab?sensor=NOAA-20").json()
    assert r["reference"]["reference_sensor"] == "NOAA-20" and "NOAA-20" in r["meaning"]
    g = c.get("/api/forecast/state:Punjab/grid-cells?sensor=NOAA-21").json()
    assert g["reference"]["reference_sensor"] == "NOAA-21"
    assert c.get("/api/forecast/model?sensor=Suomi%20NPP").json()["serving_status"]["status"] == "STALE_RETIRED_SENSOR"
    assert c.get("/api/forecast/model?sensor=NOAA-99").status_code == 400
    ms = c.get("/api/forecast/models").json()
    assert {m["reference_sensor"] for m in ms["items"]} >= {"NOAA-20", "NOAA-21"}


def test_bridge_strict_rule_requires_coverage_and_both_splits():
    def exp(w_id, w_nat, bias, cov):
        return {"design": "forward: x", "test_months": 12, "test_reference_detections": 20000,
                "state_month": {"identity": {"wape_pct": w_id, "bias_pct": 0}, "national_ratio": {"wape_pct": w_nat, "bias_pct": bias},
                                "state_ratio": {"wape_pct": 99, "bias_pct": 0}, "state_season_ratio": {"wape_pct": 99, "bias_pct": 0}},
                "band_coverage_pct": {"national_ratio": cov, "state_ratio": 0, "state_season_ratio": 0}}
    assert bridge.accept_strict([exp(8, 6, 1, 90), exp(8, 6, 1, 85)])[0] == "national_ratio"
    assert bridge.accept_strict([exp(8, 6, 1, 90), exp(8, 6, 1, 40)])[0] is None          # coverage fails on one split
    assert bridge.accept_strict([exp(8, 6, 1, 90), exp(8, 7.5, 1, 90)])[0] is None        # not 1 point better on split 2


@needs_models
def test_transition_report_never_extends_snpp_record():
    t = c.get("/api/reference/transition").json()
    assert t["science_data_end"] == "2026-11-02"
    for name, v in t["successors"].items():
        if v.get("bridge", {}).get("status") != "calibrated":
            assert isinstance(v["calibrated_discontinuity"], str) and "not computed" in v["calibrated_discontinuity"]
    assert t["verdict"] in ("BRIDGED", "NOT_BRIDGED")
    # actual VIIRS observations in the harmonized record are untouched
    h = c.get("/api/harmonization/summary").json()
    assert all(r["harmonized"] == r["viirs"] for r in h["series"] if r["provenance"] == "actual_viirs")
