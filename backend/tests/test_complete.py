"""Tests for the complete-final branch: orbit prediction (SGP4), NOAA-21 study rule, forecast comparison metrics,
population and infrastructure exposure, VIIRS 750 m granule handling, notification hardening, rate limiting and
audit retention. All external services are replaced by local fixtures; no credentials or network are needed."""
import gzip
import json
import socket
import threading
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

import tests.test_api  # noqa: F401  (throw-away database before the app is imported)
from fastapi.testclient import TestClient

from app import forecast_eval, infrastructure, noaa21, notify, orbits, population, retention, security, store, viirs750
from app import models as M
from app.main import app

c = TestClient(app)
ADMIN = {"X-User": "admin"}
needs_data = pytest.mark.skipif(not store.has_data(), reason="pipeline has not been run")

# A real CelesTrak element set for NOAA-20 (epoch 2026-11-14), used as a fixed fixture.
TLE = {"satellite": "NOAA-20", "catnr": 43013, "name": "NOAA 20 (JPSS-1)",
       "line1": "1 43013U 17073A   26318.27699829  .00000079  00000+0  58684-4 0  9991",
       "line2": "2 43013  98.7927 256.4869 0001180 130.5819 229.5459 14.19537036465765",
       "epoch": "2026-11-14T06:38:52.652256+00:00", "source": "fixture", "acquired": "2026-11-14T18:12:05+00:00"}


# --------------------------------------------------------------------------- orbits
def test_tle_parsing_checksum_and_epoch():
    name, l1, l2 = orbits.parse_tle(f"NOAA 20\n{TLE['line1']}\n{TLE['line2']}\n")
    assert name == "NOAA 20" and l1 == TLE["line1"]
    assert orbits.tle_epoch(l1).isoformat().startswith("2026-11-14T06:38")
    bad = TLE["line1"][:68] + str((int(TLE["line1"][68]) + 1) % 10)
    with pytest.raises(ValueError):
        orbits.parse_tle(f"{bad}\n{TLE['line2']}")


def test_fetch_tle_rejects_wrong_satellite(tmp_path, monkeypatch):
    monkeypatch.setattr(orbits, "TLE_DIR", tmp_path)

    class R:
        status_code = 200
        text = f"NOAA 20\n{TLE['line1']}\n{TLE['line2']}"

        def raise_for_status(self):
            pass

    class S:
        def get(self, *a, **k):
            return R()
    rec = orbits.fetch_tle("NOAA-20", session=S())
    assert rec["catnr"] == 43013 and (tmp_path / "43013.json").exists()
    with pytest.raises(ValueError):
        orbits.fetch_tle("Aqua", session=S())   # catalogue number mismatch


def test_swath_geometry_and_passes():
    assert 18 < orbits.swath_min_elevation("NOAA-20", 830) < 22      # VIIRS 3000 km swath edge
    assert 22 < orbits.swath_min_elevation("Aqua", 705) < 27         # MODIS 2330 km swath edge
    t0 = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    p = orbits.passes("NOAA-20", 30.9, 75.85, t0, 48, rec=TLE)
    assert p["available"] and not p["freshness"]["stale"]
    assert 2 <= len(p["passes"]) <= 10
    for x in p["passes"]:
        assert x["max_elevation_deg"] >= p["swath_edge_elevation_deg"]
        assert x["daynight"] in ("D", "N") and 0 < x["duration_min"] < 20
    # sun-synchronous afternoon orbit: day passes near 13:30 local solar time
    day = [x["local_solar_time_h"] for x in p["passes"] if x["daynight"] == "D"]
    assert day and all(12.0 < h < 15.0 for h in day)
    stale = orbits.passes("NOAA-20", 30.9, 75.85, t0 + timedelta(days=40), 6, rec=TLE)
    assert stale["freshness"]["stale"] and stale["freshness"]["warning"]
    assert "Not a fire prediction" in p["meaning"]


def test_overpass_validation_recovers_known_times():
    t0 = datetime(2026, 11, 14, 0, tzinfo=timezone.utc)
    pts = []
    for lat, lon in ((30.9, 75.85), (21.0, 80.0), (12.5, 77.5)):
        for x in orbits.passes("NOAA-20", lat, lon, t0, 24, rec=TLE, step_s=10)["passes"]:
            pts.append({"latitude": lat, "longitude": lon, "timestamp_utc": pd.Timestamp(x["max_utc"].rstrip("Z"))})
    v = orbits.validate("NOAA-20", pd.DataFrame(pts), rec=TLE)
    assert v["validated"] and v["n"] == len(pts) >= 4
    assert v["mean_abs_residual_min"] <= 0.5          # exact pass times are recovered
    far = pd.DataFrame([{"latitude": 20.0, "longitude": 80.0, "timestamp_utc": pd.Timestamp("2025-01-01")}])
    assert not orbits.validate("NOAA-20", far, rec=TLE)["validated"]   # too far from the TLE epoch


def test_orbit_api_validation():
    assert c.get("/api/orbits/passes?satellite=Nope&lat=20&lon=80").status_code == 400
    assert c.get("/api/orbits/passes?satellite=NOAA-20").status_code == 400
    assert c.get("/api/orbits/passes?satellite=NOAA-20&lat=20&lon=80&start=notadate").status_code == 400
    r = c.get("/api/orbits/status")
    assert r.status_code == 200 and "observation opportunities" in r.json()["meaning"]
    assert c.post("/api/orbits/refresh", headers={"X-User": "analyst"}).status_code == 403


# --------------------------------------------------------------------------- NOAA-21 rule
def _exp(id_w, nat_w, cand_w, bias=1.0, cov=90.0, months=12, n=50000):
    sc = {"identity": {"wape_pct": id_w, "bias_pct": 0}, "national_ratio": {"wape_pct": nat_w, "bias_pct": 0},
          "state_ratio": {"wape_pct": cand_w + 5, "bias_pct": bias}, "state_season_ratio": {"wape_pct": cand_w, "bias_pct": bias}}
    return {"state_month": sc, "band_coverage_pct": {"state_ratio": cov, "state_season_ratio": cov, "national_ratio": cov},
            "test_months": months, "test_reference_detections": n}


def test_noaa21_acceptance_rule():
    assert noaa21._accept([_exp(10, 10, 8), _exp(10, 10, 8.5)])[0] == "state_season_ratio"
    assert noaa21._accept([_exp(10, 10, 8), _exp(10, 10, 9.5)])[0] is None              # fails on one split
    assert noaa21._accept([_exp(10, 10, 8, bias=7), _exp(10, 10, 8, bias=7)])[0] is None  # biased
    assert noaa21._accept([_exp(10, 10, 8, cov=50), _exp(10, 10, 8, cov=50)])[0] is None  # band too narrow
    sel, why = noaa21._accept([_exp(10, 10, 8, months=6), _exp(10, 10, 8)])
    assert sel is None and "insufficient" in why
    s = noaa21._score(np.array([10.0, 20.0, 30.0]), np.array([11.0, 19.0, 33.0]))
    assert s["wape_pct"] == pytest.approx(5 / 60 * 100, abs=0.01) and s["bias_pct"] == pytest.approx(3 / 60 * 100, abs=0.01)


@needs_data
def test_noaa21_study_uses_operational_period_only():
    r = noaa21.study()
    assert r["status"] in ("calibrated", "not_calibrated")
    for e in r["experiments"]:
        assert e["train"][0] >= "2024-01" and e["test"][0] >= "2024-01"
        assert "identity" in e["state_month"]
    if r["pre_operational_check"]:
        assert r["pre_operational_check"]["months"][1] <= "2024-01"


# --------------------------------------------------------------------------- forecast comparison
def test_forecast_metrics_definitions():
    y = np.array([1, 1, 0, 0, 0, 1, 0, 0] * 100)
    p = np.array([0.9, 0.7, 0.2, 0.65, 0.1, 0.3, 0.05, 0.4] * 100)
    m = forecast_eval.metrics(y, p, clim_brier=0.3)
    cm = m["confusion"]
    assert (cm["tp"], cm["fp"], cm["fn"], cm["tn"]) == (200, 100, 100, 400)
    assert m["precision"] == pytest.approx(2 / 3, abs=1e-4) and m["recall"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["specificity"] == pytest.approx(0.8) and m["missed_event_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert m["brier_skill"] == pytest.approx(1 - m["brier"] / 0.3, abs=1e-3)
    assert m["reliable"]
    assert not forecast_eval.metrics(y[:40], p[:40])["reliable"]          # small samples are flagged


def test_forecast_comparison_endpoint_shape():
    r = c.get("/api/forecast/comparison").json()
    if r.get("status") == "unavailable":
        return
    assert set(r["main"]) >= {"climatology", "logistic", "random_forest", "hist_gradient_boosting", "xgboost"}
    assert r["production_model"] == "xgboost" and "selection_rule" in r
    assert all(set(card) >= {"algorithm", "training_period", "test_period", "metrics", "limitations"} for card in r["model_cards"].values())


# --------------------------------------------------------------------------- population
def test_population_build_preserves_totals(tmp_path, monkeypatch):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    from app import gis_layers
    monkeypatch.setattr(population, "POP_DIR", tmp_path)
    monkeypatch.setattr(population, "MANIFEST", tmp_path / "m.json")
    monkeypatch.setattr(population, "CELLS", tmp_path / "c.parquet")
    monkeypatch.setattr(population, "FINE", tmp_path / "f.parquet")
    exp = tmp_path / "exposure"
    exp.mkdir()
    monkeypatch.setattr(gis_layers, "EXPOSURE_DIR", exp)
    a = np.full((60, 60), 10.0, "float32")        # 0.5 x 0.5 deg of 30" pixels, 10 people each
    a[0, :5] = -99999.0                            # NoData
    tif = tmp_path / "pop.tif"
    with rasterio.open(tif, "w", driver="GTiff", height=60, width=60, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(77.0, 29.0, 1 / 120, 1 / 120), nodata=-99999.0) as ds:
        ds.write(a, 1)
    man = population.build(tif, log=lambda *_: None)
    assert man["total_population_in_aoi"] == (3600 - 5) * 10
    assert man["grid_aligned"] and man["cells_0p25"] == 4
    cells = pd.read_parquet(tmp_path / "c.parquet")
    assert cells["population"].sum() == pytest.approx(35950)
    assert (cells["valid_frac"] < 1).sum() == 1                     # NoData shows as partial coverage, not low population
    within = population.people_within(28.75, 77.25, 5.0)
    assert within is not None and 0 < within[0] <= 35950
    assert (exp / "population.parquet").exists()
    population.clear()


def test_population_absent_is_none(monkeypatch, tmp_path):
    monkeypatch.setattr(population, "FINE", tmp_path / "none.parquet")
    population.clear()
    assert population.people_within(20, 80, 5) is None
    population.clear()


# --------------------------------------------------------------------------- infrastructure
def test_infrastructure_clean_dedupes_and_clips():
    df = pd.DataFrame([
        {"osm_id": "n1", "category": "hospital", "lat": 28.6, "lon": 77.2, "name": "AIIMS"},
        {"osm_id": "n1", "category": "hospital", "lat": 28.6, "lon": 77.2, "name": "AIIMS"},          # same OSM object
        {"osm_id": "w9", "category": "hospital", "lat": 28.60001, "lon": 77.20001, "name": "aiims"},  # outline of same site
        {"osm_id": "n2", "category": "hospital", "lat": 51.5, "lon": -0.1, "name": "Outside"},       # outside AOI
        {"osm_id": "n3", "category": "school", "lat": None, "lon": 77.0, "name": "Bad"},             # invalid
        {"osm_id": "n4", "category": "school", "lat": 28.6, "lon": 77.2, "name": "AIIMS"},           # other category kept
    ])
    out, st = infrastructure.clean(df)
    assert st == {"input": 6, "invalid_or_outside_aoi": 2, "duplicate_osm_id": 1, "colocated_duplicates": 1, "kept": 2}
    assert set(out["category"]) == {"hospital", "school"}


def test_infrastructure_fetch_retries_mirrors():
    calls = []

    class R:
        def __init__(self, code, js=None):
            self.status_code, self._js = code, js

        def raise_for_status(self):
            pass

        def json(self):
            return self._js

    class S:
        def post(self, url, **k):
            calls.append(url)
            if len(calls) < 2:
                return R(504)
            return R(200, {"elements": [{"type": "node", "id": 1, "lat": 20.0, "lon": 80.0, "tags": {"name": "H"}},
                                        {"type": "way", "id": 2, "center": {"lat": 21.0, "lon": 81.0}, "tags": {}}]})
    df = infrastructure.fetch_category("hospital", session=S(), sleep=lambda s: None, log=lambda *_: None)
    assert len(df) == 2 and list(df["osm_id"]) == ["n1", "w2"]
    assert calls[0] != calls[1]                                            # moved to the next mirror


def test_infrastructure_nearby_distances(monkeypatch):
    pts = pd.DataFrame({"osm_id": ["n1", "n2"], "category": ["hospital", "hospital"], "lat": [20.0, 20.5], "lon": [80.0, 80.0],
                        "name": ["A", "B"], "cell_id": [0, 0]})
    monkeypatch.setattr(infrastructure, "points", lambda: pts)
    monkeypatch.setattr(infrastructure, "manifest", lambda: {"categories": {"hospital": {"status": "loaded"}}})
    infrastructure._trees.cache_clear()
    r = infrastructure.nearby(20.0, 80.05, radius_km=10)
    assert r["hospital"]["count"] == 1 and 5.0 < r["hospital"]["nearest"][0]["distance_km"] < 5.5   # 0.05 deg lon at 20N ~ 5.2 km
    assert r["school"]["status"] == "unavailable" and r["school"]["count"] is None                 # missing != zero
    infrastructure._trees.cache_clear()


# --------------------------------------------------------------------------- VIIRS 750 m
def _granule(path, n=3, with_mask=True, sza=(30.0, 100.0, 40.0), daynight="Day"):
    h5py = pytest.importorskip("h5py")
    with h5py.File(path, "w") as h:
        h.attrs["DayNightFlag"] = daynight
        h["FP_latitude"] = np.array([20.0, 21.0, -999.0][:n], "float32")
        h["FP_latitude"].attrs["_FillValue"] = np.float32(-999.0)
        h["FP_longitude"] = np.array([80.0, 81.0, 82.0][:n], "float32")
        h["FP_power"] = np.array([12.5, 3.0, 8.0][:n], "float32")
        h["FP_confidence"] = np.array([85, 50, 20][:n], "uint8")
        h["FP_line"] = np.array([1, 2, 3][:n], "int32")
        h["FP_sample"] = np.array([1, 2, 3][:n], "int32")
        h["FP_SolZenAng"] = np.array(sza[:n], "float32")
        if with_mask:
            m = np.zeros((5, 5), "uint8")
            m[1, 1], m[2, 2], m[3, 3] = 9, 7, 8
            h["fire mask"] = m


def test_viirs750_granule_conversion_follows_filespec(tmp_path):
    g = tmp_path / "VJ214.A2025305.0530.002.2025340031314.nc"
    _granule(g)
    df = viirs750.granule_pixels(g)
    assert len(df) == 2                                   # fill-value latitude dropped, nothing invented
    assert list(df["confidence"]) == ["h", "l"]           # from the fire-mask class at (line, sample), not the %
    assert list(df["daynight"]) == ["D", "N"]             # per-pixel solar zenith (85 deg), no FP_day variable
    assert set(df["satellite"]) == {"NOAA-21"} and set(df["source_product"]) == {"750m"}
    assert df["acq_date"].iat[0] == "2025-11-01" and df["acq_time"].iat[0] == "0530" and df["version"].iat[0] == "VJ214.002"


def test_viirs750_fallbacks_and_empty(tmp_path):
    g = tmp_path / "VNP14.A2024306.0636.002.2024306141840.nc"
    _granule(g, n=2, with_mask=False, sza=(np.nan, np.nan), daynight="Night")
    df = viirs750.granule_pixels(g)
    assert list(df["confidence"]) == ["h", "n"]           # MOD14 percentage bands when the mask is missing
    assert list(df["daynight"]) == ["N", "N"]             # granule DayNightFlag fallback
    e = tmp_path / "VJ114.A2024306.0636.002.2024306141840.nc"
    _granule(e, n=0)
    assert viirs750.granule_pixels(e).empty
    with pytest.raises(ValueError):
        viirs750.granule_pixels(tmp_path / "random.nc")


def test_viirs750_download_requires_credentials_and_detects_corruption(tmp_path, monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.setattr(viirs750, "credentials_status", lambda: {"configured": False, "how": "set EARTHDATA_TOKEN"})
    with pytest.raises(PermissionError):
        viirs750.download([{"granule": "x", "url": "https://e/x.nc", "product": "VJ114"}])
    monkeypatch.setattr(viirs750, "GRANULE_DIR", tmp_path)
    monkeypatch.setattr(viirs750, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(viirs750, "RAW", tmp_path)
    good = tmp_path / "src.nc"
    _granule(good)
    payload = {"good": good.read_bytes(), "bad": b"<html>login page</html>"}

    class R:
        def __init__(self, b):
            self.b, self.status_code = b, 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield self.b

    class S:
        def get(self, url, **k):
            return R(payload["good" if "good" in url else "bad"])
    gr = [{"granule": "VJ114.A2024306.0636.002.good", "url": "https://e/good.nc", "product": "VJ114", "size_bytes_approx": None},
          {"granule": "VJ114.A2024306.0642.002.bad", "url": "https://e/bad.nc", "product": "VJ114", "size_bytes_approx": None}]
    st = viirs750.download(gr, session=S(), sleep=lambda s: None, log=lambda *_: None)
    assert st["downloaded"] == 1 and st["corrupt"] == 1
    again = viirs750.download(gr[:1], session=S(), sleep=lambda s: None, log=lambda *_: None)
    assert again["already_present"] == 1                               # de-duplicated by granule id + SHA-256
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["granules"]["VJ114.A2024306.0636.002.good"]["status"] == "ok" and len(m["granules"]["VJ114.A2024306.0636.002.good"]["sha256"]) == 64


def test_viirs750_search_parses_cmr():
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"items": [{"umm": {"GranuleUR": "VJ214.A2025305.0530.002.2025340031314",
                                       "RelatedUrls": [{"URL": "s3://x"}, {"URL": "https://data.lpdaac.earthdatacloud.nasa.gov/a/VJ214.nc"}],
                                       "DataGranule": {"DayNightFlag": "Day", "ArchiveAndDistributionInformation": [{"Size": 0.5, "SizeUnit": "MB"}]}}}]}

    class S:
        def get(self, url, params=None, **k):
            assert params["short_name"] == "VJ214" and params["version"] == "002"
            return R()
    g = viirs750.search("NOAA-21", "2025-11-01", "2025-11-01", session=S())
    assert g[0]["url"].startswith("https://") and g[0]["size_bytes_approx"] == 524288


def test_viirs750_status_endpoint_says_unavailable_without_data():
    r = c.get("/api/viirs750/status").json()
    assert "credentials" in r and r["products"]["viirs_750m"] in ("loaded", "unavailable")


# --------------------------------------------------------------------------- notifications (wire-level SMTP)
class _SMTPServer:
    """Minimal SMTP server on localhost: EHLO / MAIL / RCPT / DATA / NOOP / QUIT. Records messages."""

    def __init__(self, fail_first=0):
        self.msgs, self.fail_first, self.conns = [], fail_first, 0
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.conns += 1
            if self.conns <= self.fail_first:
                conn.close()                      # simulate a dropped connection (transient)
                continue
            f = conn.makefile("rwb")
            f.write(b"220 test ESMTP\r\n"); f.flush()
            data, rcpt = None, []
            while True:
                line = f.readline()
                if not line:
                    break
                cmd = line.decode().strip()
                up = cmd.upper()
                if data is not None:
                    if cmd == ".":
                        self.msgs.append({"rcpt": rcpt, "data": b"".join(data).decode()})
                        data = None
                        f.write(b"250 queued\r\n")
                    else:
                        data.append(line)
                    f.flush()
                    continue
                if up.startswith("EHLO") or up.startswith("HELO"):
                    f.write(b"250 test\r\n")
                elif up.startswith("RCPT"):
                    rcpt.append(cmd.split(":", 1)[1].strip("<> "))
                    f.write(b"250 ok\r\n")
                elif up == "DATA":
                    data = []
                    f.write(b"354 go\r\n")
                elif up == "QUIT":
                    f.write(b"221 bye\r\n"); f.flush()
                    break
                else:
                    f.write(b"250 ok\r\n")
                f.flush()
            conn.close()

    def close(self):
        self.sock.close()


def _smtp_env(monkeypatch, port):
    monkeypatch.setenv("PYROSCOPE_NOTIFY_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(port))
    monkeypatch.setenv("SMTP_FROM", "pyroscope@test.invalid")
    monkeypatch.setenv("SMTP_TLS_MODE", "none")
    monkeypatch.delenv("SMTP_USER", raising=False)


class _Contact:
    def __init__(self, **k):
        self.__dict__.update({"is_template": False, "verified": True, "contact_channel": "email",
                              "contact_value": "dfo@forest.example", "authority": "State Forest Department"} | k)


def test_smtp_wire_level_test_message_and_connection_check(monkeypatch):
    srv = _SMTPServer()
    try:
        _smtp_env(monkeypatch, srv.port)
        assert notify.check_connection()["ok"]
        r = notify.send_test(_Contact(), "admin", sleep=lambda s: None)
        assert r["status"] == "SENT" and r["attempts"] == 1
        assert srv.msgs[0]["rcpt"] == ["dfo@forest.example"]
        assert "TEST MESSAGE - no action required" in srv.msgs[0]["data"] and "Not an alert" in srv.msgs[0]["data"]
        assert notify.send_test(_Contact(verified=False), "admin")["status"] == "BLOCKED_NO_VERIFIED_CONTACT"
        assert notify.send_test(_Contact(contact_channel="webhook"), "admin")["status"] == "SKIPPED_CHANNEL_MISMATCH"
    finally:
        srv.close()


def test_smtp_transient_failure_is_retried(monkeypatch):
    srv = _SMTPServer(fail_first=1)
    try:
        _smtp_env(monkeypatch, srv.port)
        waits = []
        r = notify.send_test(_Contact(), "admin", sleep=waits.append)
        assert r["status"] == "SENT" and r["attempts"] == 2 and len(waits) == 1
    finally:
        srv.close()


def test_smtp_unreachable_fails_after_retries_and_bad_address_is_not_retried(monkeypatch):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()     # nothing listening
    _smtp_env(monkeypatch, port)
    waits = []
    r = notify.send_test(_Contact(), "admin", sleep=waits.append)
    assert r["status"] == "FAILED" and r["attempts"] == notify.MAX_ATTEMPTS and len(waits) == notify.MAX_ATTEMPTS - 1
    waits.clear()
    r = notify.send_test(_Contact(contact_value="not-an-email"), "admin", sleep=waits.append)
    assert r["status"] == "FAILED" and r["attempts"] == 1 and not waits


def test_webhook_ssrf_and_redirect_guards(monkeypatch):
    monkeypatch.setenv("PYROSCOPE_WEBHOOK_ALLOWED_HOSTS", "localhost,hooks.example.org")
    monkeypatch.delenv("PYROSCOPE_WEBHOOK_ALLOW_PRIVATE", raising=False)
    with pytest.raises(PermissionError):
        notify._send_webhook("https://localhost/hook", {})                 # allow-listed but resolves to loopback
    with pytest.raises(PermissionError):
        notify._send_webhook("http://hooks.example.org/x", {})             # not https
    with pytest.raises(PermissionError):
        notify._send_webhook("https://evil.example.com/x", {})             # not allow-listed

    class R:
        status_code = 302

        def raise_for_status(self):
            pass
    import requests
    monkeypatch.setattr(notify, "_check_public_host", lambda h: None)
    monkeypatch.setattr(requests, "post", lambda *a, **k: (k.get("allow_redirects") is False) and R())
    with pytest.raises(PermissionError):
        notify._send_webhook("https://hooks.example.org/x", {})            # redirects are refused, not followed


# --------------------------------------------------------------------------- rate limiting
def test_rate_limiter_window():
    security.reset_rate_limits()
    lim, win = security.RATE_LIMITS["login"]
    for i in range(lim):
        assert security.check_rate("login", "1.2.3.4", now=100.0 + i) is None
    wait = security.check_rate("login", "1.2.3.4", now=100.0 + lim)
    assert wait is not None and 0 < wait <= win
    assert security.check_rate("login", "5.6.7.8", now=100.0 + lim) is None       # other clients unaffected
    assert security.check_rate("login", "1.2.3.4", now=100.0 + win + 1) is None    # window slides
    security.reset_rate_limits()


def test_login_endpoint_rate_limited():
    security.reset_rate_limits()
    codes = [c.post("/api/auth/login", json={"username": "ghost", "password": "wrong"}).status_code
             for _ in range(security.RATE_LIMITS["login"][0] + 1)]
    assert codes[:-1] == [401] * security.RATE_LIMITS["login"][0]
    assert codes[-1] == 429
    security.reset_rate_limits()


# --------------------------------------------------------------------------- audit retention
def test_audit_retention_archives_then_prunes_routine_rows_only(tmp_path):
    old = datetime(2020, 1, 1)
    with M.Session() as s:
        s.add_all([M.AuditLog(at=old, actor="u", action="LOGIN", entity="user", entity_id="u"),
                   M.AuditLog(at=old, actor="u", action="LOGOUT", entity="user", entity_id="u"),
                   M.AuditLog(at=old, actor="gov", action="APPROVED", entity="alert", entity_id="A-1")])
        s.commit()
    dry = retention.prune_audit(365, dry_run=True, archive_dir=tmp_path)
    assert dry["eligible"] >= 2 and dry["protected_kept"] >= 1 and dry["deleted"] == 0
    res = retention.prune_audit(365, dry_run=False, archive_dir=tmp_path)
    assert res["deleted"] == dry["eligible"]
    with gzip.open(res["archive"], "rt") as fh:
        rows = [json.loads(x) for x in fh]
    assert len(rows) == res["deleted"] and {r["action"] for r in rows} <= retention.PRUNABLE_ACTIONS
    with M.Session() as s:
        assert s.query(M.AuditLog).filter(M.AuditLog.action == "APPROVED", M.AuditLog.at == old).count() == 1   # decisions kept
    with pytest.raises(ValueError):
        retention.prune_audit(7)
    assert c.post("/api/admin/audit-retention", headers={"X-User": "analyst"}).status_code == 403
    assert c.post("/api/admin/audit-retention?dry_run=true", headers=ADMIN).json()["dry_run"] is True


# --------------------------------------------------------------------------- exposure API
def test_exposure_endpoints_report_missing_layers_honestly():
    r = c.get("/api/exposure/layers").json()
    assert r["population"]["status"] in ("loaded", "unavailable") and "not a prediction" in r["meaning"]
    assert c.get("/api/exposure/point?lat=0&lon=80").status_code == 422              # outside the AOI
    p = c.get("/api/exposure/point?lat=28.6&lon=77.2&radius_km=10").json()
    if r["population"]["status"] == "unavailable":
        assert p["population"] is None                                                # never zero
    assert c.get("/api/gis/infrastructure?category=nope").status_code == 400
    assert c.get("/api/gis/infrastructure?bbox=1,2,3").status_code == 400
