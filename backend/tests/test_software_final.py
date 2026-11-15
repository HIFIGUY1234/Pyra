"""Software completion before credentials: VIIRS 750 m readiness, linear GIS, area-weighted population,
critical-region scoring, configuration validation, notification fixtures, pipeline CLI."""
import json
import socket
import socketserver
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import tests.test_api  # noqa: F401  (throw-away DB before app import)
from fastapi.testclient import TestClient

from app import critical_scoring as CS
from app import linear_gis, notify, pipeline, population, system_config, viirs750
from app.main import app

c = TestClient(app)
ADMIN, GOV, ANALYST = {"X-User": "admin"}, {"X-User": "forest.officer"}, {"X-User": "analyst"}


# --------------------------------------------------------------------------- VIIRS 750 m
def test_750m_credential_status_never_reveals_secrets(monkeypatch, tmp_path):
    monkeypatch.setattr(viirs750, "ACCESS_STATE", tmp_path / "state.json")
    monkeypatch.setattr(viirs750, "GRANULE_DIR", tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))      # Path.home() on Windows
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    st = c.get("/api/viirs750/credentials").json()
    assert st["state"] == "NOT_CONFIGURED" and st["method"] is None
    secret = "edl-SECRET-token-value-123"
    monkeypatch.setenv("EARTHDATA_TOKEN", secret)
    viirs750._record_access(False, f"HTTP 401 for Authorization: Bearer {secret}")
    r = c.get("/api/viirs750/credentials")
    assert secret not in r.text and r.json()["method"] == "token" and r.json()["last_error"]
    (tmp_path / ".netrc").write_text("machine urs.earthdata.nasa.gov login u password p4ss\n")
    monkeypatch.delenv("EARTHDATA_TOKEN")
    r = c.get("/api/viirs750/credentials")
    assert r.json()["method"] == "netrc" and "p4ss" not in r.text
    assert c.get("/api/viirs750/status").json()["real_data_verification"] in ("PENDING_DOWNLOAD", "BLOCKED_BY_CREDENTIALS")


def test_750m_search_paginates_with_search_after_and_dedupes():
    def item(g):
        return {"umm": {"GranuleUR": g, "RelatedUrls": [{"URL": f"https://data/{g}.nc"}],
                        "DataGranule": {"DayNightFlag": "Day", "ArchiveAndDistributionInformation": [{"Size": 1.0, "SizeUnit": "MB"}]}}}
    pages = [([item("A"), item("B")], "tok1"), ([item("B"), item("C")], "tok2"), ([item("D")], None)]
    seen = []

    class R:
        def __init__(self, items, after):
            self.items, self.headers = items, ({"CMR-Search-After": after} if after else {})
        def raise_for_status(self):
            pass
        def json(self):
            return {"items": self.items}

    class S:
        def get(self, url, params=None, headers=None, timeout=None):
            seen.append(((headers or {}).get("CMR-Search-After"), params.get("page_num")))
            return R(*pages[len(seen) - 1])
    out = viirs750.search("NOAA-21", "2025-01-01", "2025-01-02", session=S(), page_size=2)
    assert [g["granule"] for g in out] == ["A", "B", "C", "D"]            # duplicate B dropped
    assert seen[0] == (None, 1) and seen[1][0] == "tok1" and seen[2][0] == "tok2"
    with pytest.raises(ValueError):
        viirs750.search("NOAA-21", "2025-02-01", "2025-01-01", session=S())
    with pytest.raises(ValueError):
        viirs750.search("Landsat", "2025-01-01", "2025-01-02", session=S())


def _granule(path, lat=(20.0, 21.0), plat=None, extra_len=False):
    h5py = pytest.importorskip("h5py")
    n = len(lat)
    with h5py.File(path, "w") as h:
        h.attrs["DayNightFlag"] = "Day"
        if plat:
            h.attrs["PlatformShortName"] = plat
        h["FP_latitude"] = np.array(lat, "float32")
        h["FP_longitude"] = np.array([80.0] * (n + (1 if extra_len else 0)), "float32")
        h["FP_power"] = np.array([5.0] * n, "float32")
        h["FP_confidence"] = np.array([50] * n, "uint8")
        h["FP_line"] = np.zeros(n, "int32")
        h["FP_sample"] = np.zeros(n, "int32")
        h["FP_SolZenAng"] = np.full(n, 30.0, "float32")
        h["fire mask"] = np.full((2, 2), 8, "uint8")
        h["algorithm QA"] = np.zeros((2, 2), "uint32")


def test_750m_validator_follows_filespec(tmp_path):
    ok = tmp_path / "VJ114.A2025010.0600.002.2025011000000.nc"
    _granule(ok, plat="NOAA-20")
    d = viirs750.validate_granule(ok)
    assert d["fire_pixels"] == 2 and d["missing_datasets"] == [] and d["algorithm_qa_present"] and d["fire_mask_shape"] == [2, 2]
    bad_len = tmp_path / "VJ114.A2025010.0601.002.2025011000000.nc"
    _granule(bad_len, extra_len=True)
    with pytest.raises(ValueError, match="different lengths"):
        viirs750.validate_granule(bad_len)
    wrong_plat = tmp_path / "VJ214.A2025010.0602.002.2025011000000.nc"
    _granule(wrong_plat, plat="NOAA-20")
    with pytest.raises(ValueError, match="platform"):
        viirs750.validate_granule(wrong_plat)
    early = tmp_path / "VJ214.A2020010.0600.002.2020011000000.nc"     # before VJ214 exists
    _granule(early)
    with pytest.raises(ValueError, match="outside"):
        viirs750.validate_granule(early)
    coll = tmp_path / "VNP14.A2020010.0600.001.2020011000000.nc"
    _granule(coll)
    with pytest.raises(ValueError, match="collection"):
        viirs750.validate_granule(coll)
    tm = tmp_path / "VNP14.A2020010.2561.002.2020011000000.nc"
    _granule(tm)
    with pytest.raises(ValueError, match="time"):
        viirs750.validate_granule(tm)


def test_750m_download_refuses_without_credentials(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.setattr(viirs750, "_netrc_has_urs", lambda: False)
    with pytest.raises(PermissionError, match="Earthdata"):
        viirs750.download([{"granule": "g", "url": "https://x/g.nc", "product": "VJ214"}])


# --------------------------------------------------------------------------- linear GIS
def _pbf(path):
    osmium = pytest.importorskip("osmium")
    from osmium.osm.mutable import Node, Way
    w = osmium.SimpleWriter(str(path))
    pts = {1: (77.0, 28.0), 2: (77.1, 28.0), 3: (77.2, 28.05), 4: (77.0, 28.2), 5: (77.3, 28.2), 6: (76.9, 28.1), 7: (77.4, 28.1),
           8: (77.05, 28.05), 9: (77.5, 28.5), 10: (77.6, 28.6), 11: (77.62, 28.6), 12: (77.62, 28.62), 13: (77.6, 28.62),
           20: (60.0, 28.0), 21: (60.1, 28.0)}
    tags = {8: {"place": "village", "name": "Testpur"}, 9: {"power": "substation"}}
    for i, (lo, la) in sorted(pts.items()):
        w.add_node(Node(id=i, location=(lo, la), tags=tags.get(i, {}), version=1))
    for wid, nds, t in ((100, [1, 2, 3], {"highway": "primary", "name": "NH T"}), (101, [4, 5], {"railway": "rail"}),
                        (102, [6, 7], {"power": "line", "voltage": "220000"}), (103, [10, 11, 12, 13, 10], {"landuse": "industrial"}),
                        (104, [20, 21], {"highway": "trunk"}), (105, [1, 2], {"highway": "residential"}),
                        (106, [4, 5], {"railway": "rail", "disused": "yes"})):
        w.add_way(Way(id=wid, nodes=nds, tags=t, version=1))
    w.close()


def test_linear_gis_keeps_lines_classifies_and_measures(tmp_path):
    p = tmp_path / "t.osm.pbf"
    _pbf(p)
    out = tmp_path / "lin"
    m = linear_gis.build(p, out, log=lambda *a: None)
    cats = m["categories"]
    assert cats["road_major"]["features"] == 1 and cats["railway"]["features"] == 1     # disused rail and residential street excluded
    assert cats["power_line"]["features"] == 1 and cats["industrial"]["features"] == 1 and cats["settlement"]["features"] == 1
    assert cats["road_minor"]["status"] == "no_features_in_extract"                      # absent -> reported, not zero-filled
    assert m["parse_stats"]["outside_aoi"] == 1
    import pyarrow.parquet as pq
    from shapely import wkb
    t = pq.read_table(out / "road_major.parquet")
    assert b"geo" in t.schema.metadata
    g = wkb.loads(t.column("geometry")[0].as_py())
    assert g.geom_type == "LineString" and len(g.coords) == 3                           # line geometry preserved, not a centroid
    assert abs(cats["power_line"]["total_length_km"] - 49.0) < 0.5                      # 0.5 deg of longitude at 28.1 N
    b = linear_gis.by_cell(str(out))
    assert abs(b.groupby("category")["length_km"].sum()["road_major"] - cats["road_major"]["total_length_km"]) < 0.2   # no edge double count
    rail = linear_gis.nearest(28.3, 77.1, "railway", base=str(out))
    assert abs(rail["distance_km"] - 11.12) < 0.05                                        # km, not degrees
    w = linear_gis.within(28.1, 77.15, 10, "power_line", base=str(out))
    assert abs(w["length_km"] - 20.0) < 0.1
    assert linear_gis.nearest(28.0, 77.0, "railway", max_km=5, base=str(out))["status"] == "none_within"
    linear_gis.clear()


def test_linear_status_unavailable_when_not_built(monkeypatch, tmp_path):
    monkeypatch.setattr(linear_gis, "LIN_DIR", tmp_path)
    assert linear_gis.status(tmp_path)["status"] == "not_built"
    assert linear_gis.nearest(28, 77, "road_major", base=str(tmp_path))["status"] == "unavailable"
    with pytest.raises(ValueError):
        linear_gis.nearest(28, 77, "volcano")


def test_linear_classification_rules():
    assert linear_gis.classify({"highway": "trunk_link"}) == "road_major"
    assert linear_gis.classify({"highway": "residential"}) is None
    assert linear_gis.classify({"railway": "rail", "abandoned": "yes"}) is None
    assert linear_gis.classify({"power": "minor_line"}) == "power_minor"
    assert linear_gis.classify({"landuse": "industrial"}) == "industrial"


# --------------------------------------------------------------------------- population
def _tif(path, off, nodata_block=True):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    px = 1 / 120
    a = np.random.default_rng(3).uniform(0, 100, (120, 240)).astype("float32")
    if nodata_block:
        a[10:14, 10:14] = -99999
    with rasterio.open(path, "w", driver="GTiff", height=120, width=240, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(77.0 + off, 29.0 + off, px, px), nodata=-99999) as d:
        d.write(a, 1)
    return a


def test_area_weighted_conserves_population_and_matches_centre_when_aligned(tmp_path):
    p = tmp_path / "a.tif"
    a = _tif(p, 0.0)
    r = population.build_area_weighted(p)
    tot = float(a[a >= 0].astype("float64").sum())
    assert abs(r["cells"]["population"].sum() - tot) / tot < 1e-9 and abs(r["fine"]["population"].sum() - tot) / tot < 1e-9
    cmp = population.compare_methods(p)
    assert cmp["cells_changed_over_1pct"] == 0 and cmp["max_cell_rel_diff"] < 1e-9
    assert (r["cells"]["valid_frac"] < 1).sum() == 1                                   # NoData block is reported, not zero population


def test_area_weighted_differs_from_centre_when_misaligned(tmp_path):
    p = tmp_path / "m.tif"
    a = _tif(p, 1 / 240, nodata_block=False)                                           # half-pixel offset
    r = population.build_area_weighted(p)
    tot = float(a.astype("float64").sum())
    assert abs(r["cells"]["population"].sum() - tot) / tot < 1e-9                      # still conserved
    cmp = population.compare_methods(p)
    assert cmp["cells_changed_over_1pct"] > 0 and abs(cmp["total_area_weighted"] - cmp["total_centre"]) / tot < 1e-9


def test_split_axis_spherical_share():
    i0, i1, f0, f1 = population._split_axis(np.array([0.24]), np.array([0.26]), 0.0, 0.25)
    assert i0[0] == 0 and i1[0] == 1 and abs(f0[0] - 0.5) < 1e-12
    s = lambda d: np.sin(np.radians(d))
    i0, i1, f0, f1 = population._split_axis(np.array([59.9]), np.array([60.1]), 0.0, 60.0, s)
    assert f0[0] > 0.5   # more area south of 60 deg in a lat band straddling it


# --------------------------------------------------------------------------- critical-region scoring
def _table():
    return pd.DataFrame({"district_id": ["a", "b", "c", "d"], "n_cells": [4, 4, 4, 4], "max_cell_p": [0.9, 0.2, 0.5, 0.1],
                         "recent30": [400, 5, 50, 1e6], "recurrence": [0.8, 0.1, 0.4, 0.2], "frp30": [4000, 10, 500, 2e6],
                         "anomaly_z": [3, -1, np.nan, 0.5], "population": [1e6, 1e5, np.nan, 5e4], "forest": [0.5, 0.1, 0.3, 0.0],
                         "gap30": [0, 0, 6, 0], "band": [0.1, 0.05, 0.2, 0.02]}, index=["a", "b", "c", "d"])


def test_scoring_normalised_missing_not_zero_and_no_dominance():
    comp = CS.normalise(_table())
    assert ((comp.dropna(how="all") >= 0) & (comp.dropna(how="all") <= 1) | comp.isna()).all().all()
    s, contrib, share = CS.score(comp, CS.PROFILES["v2-balanced"])
    assert share["c"] < share["a"]                                                    # c lacks population + anomaly -> renormalised
    assert abs(contrib.loc["c"].sum() - s["c"]) < 1e-12
    assert s.idxmax() != "d"                     # a 1e6 detection count cannot dominate: counts enter as ranks
    assert comp.loc["d", "recent"] == 1.0 and comp["infrastructure"].isna().all()


def test_weights_versioned_and_validated(monkeypatch, tmp_path):
    monkeypatch.setattr(CS, "CUSTOM", tmp_path / "w.json")
    assert c.put("/api/critical-regions/weights", json={"weights": {"forecast": 1}}, headers=GOV).status_code == 403
    assert c.put("/api/critical-regions/weights", json={"weights": {"forecast": -1}}, headers=ADMIN).status_code == 400
    assert c.put("/api/critical-regions/weights", json={"weights": {"bogus": 1}}, headers=ADMIN).status_code == 400
    r1 = c.put("/api/critical-regions/weights", json={"weights": {"forecast": 2, "population": 2}, "note": "t"}, headers=ADMIN).json()
    r2 = c.put("/api/critical-regions/weights", json={"weights": {"forecast": 1}}, headers=ADMIN).json()
    assert r1["version"] == "custom-1" and r2["version"] == "custom-2" and r2["previous"] == "custom-1"
    assert r1["weights"] == {"forecast": 0.5, "population": 0.5}
    assert c.delete("/api/critical-regions/weights", headers=ADMIN).json()["version"] == "v2-balanced"


def test_sensitivity_reports_profiles_and_perturbations():
    comp = CS.normalise(_table())
    s = CS.sensitivity(comp, CS.PROFILES["v2-balanced"], top=2)
    assert set(s["profiles"]) == set(CS.PROFILES) and s["profiles"]["v2-balanced"]["top_overlap"] == 1.0
    assert len(s["perturbations"]) == 2 * len(CS.PROFILES["v2-balanced"])


def test_critical_regions_api_explains_contributions():
    r = c.get("/api/critical-regions?top=5").json()
    if r.get("status") != "ok":
        pytest.skip("no forecast")
    it = r["items"][0]
    assert r["weights_version"] and "reference" in r and "missing_components" in it
    assert abs(sum(it["contributions"].values()) - it["score"]) < 1e-3
    assert abs(it["hazard_part"] + it["exposure_part"] + it["contributions"].get("observation_gap", 0) + it["contributions"].get("uncertainty", 0) - it["score"]) < 1e-3


# --------------------------------------------------------------------------- configuration
def test_production_config_rejects_unsafe_values():
    bad = system_config.validate({"PYROSCOPE_AUTH_MODE": "production", "PYROSCOPE_CORS_ORIGINS": "*", "PYROSCOPE_ADMIN_PASSWORD": "admin",
                                  "PYROSCOPE_RATE_LIMIT": "off", "DATABASE_URL": "sqlite:///:memory:"})
    keys = {i["key"] for i in bad["issues"] if i["level"] == "error"}
    assert not bad["ok"] and {"PYROSCOPE_CORS_ORIGINS", "PYROSCOPE_ADMIN_PASSWORD", "PYROSCOPE_RATE_LIMIT", "DATABASE_URL"} <= keys
    assert bad["x_user_header_trusted"] is False
    good = system_config.validate({"PYROSCOPE_AUTH_MODE": "production", "PYROSCOPE_CORS_ORIGINS": "https://pyroscope.example.org",
                                   "PYROSCOPE_ADMIN_PASSWORD": "CI-only-Test-Passw0rd"})
    assert good["ok"], good["issues"]
    none = system_config.validate({"PYROSCOPE_AUTH_MODE": "production", "PYROSCOPE_CORS_ORIGINS": "https://x.example.org"})
    assert any(i["key"] == "PYROSCOPE_ADMIN_PASSWORD" and i["level"] == "error" for i in none["issues"])


def test_credentials_endpoint_is_status_only(monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "very-secret-smtp")
    monkeypatch.setenv("FIRMS_MAP_KEY", "firms-key-xyz")
    r = c.get("/api/system/credentials", headers=ADMIN)
    assert r.status_code == 200 and "very-secret-smtp" not in r.text and "firms-key-xyz" not in r.text
    st = {x["integration"]: x["status"] for x in r.json()["items"]}
    assert st["NASA FIRMS API (optional)"] == "CONFIGURED"
    assert c.get("/api/system/credentials", headers=ANALYST).status_code == 403
    h = c.get("/api/health").json()
    assert h["admin_bootstrap"] in ("configured", "env_pending", "not_configured")


@pytest.mark.parametrize("env,key", [
    ({"PYROSCOPE_NOTIFY_PROVIDER": "smtp", "SMTP_FROM": "bad"}, "SMTP_HOST"),
    ({"PYROSCOPE_NOTIFY_PROVIDER": "smtp", "SMTP_HOST": "smtp.example.org", "SMTP_FROM": "a@b.org", "SMTP_TLS_MODE": "none"}, "SMTP_TLS_MODE"),
    ({"PYROSCOPE_NOTIFY_PROVIDER": "smtp", "SMTP_HOST": "h.example.org", "SMTP_FROM": "a@b.org", "SMTP_PORT": "99999"}, "SMTP_PORT"),
    ({"PYROSCOPE_NOTIFY_PROVIDER": "webhook", "PYROSCOPE_WEBHOOK_ALLOWED_HOSTS": "http://x/y"}, "PYROSCOPE_WEBHOOK_ALLOWED_HOSTS"),
    ({"PYROSCOPE_NOTIFY_PROVIDER": "webhook", "PYROSCOPE_WEBHOOK_ALLOWED_HOSTS": "hooks.example.org", "PYROSCOPE_WEBHOOK_ALLOW_PRIVATE": "1"}, "PYROSCOPE_WEBHOOK_ALLOW_PRIVATE"),
    ({"PYROSCOPE_NOTIFY_PROVIDER": "pigeon"}, "PYROSCOPE_NOTIFY_PROVIDER"),
])
def test_notification_config_errors(env, key):
    assert any(i["key"] == key and i["level"] == "error" for i in system_config.notification_issues(env))


# --------------------------------------------------------------------------- notification fixtures
class _SMTP(socketserver.StreamRequestHandler):
    """Minimal RFC 5321 server for tests: accepts any mail, or rejects AUTH when the server says so."""
    def handle(self):
        srv = self.server
        self.wfile.write(b"220 test ESMTP\r\n")
        data = False
        while True:
            line = self.rfile.readline()
            if not line:
                return
            if data:
                if line in (b".\r\n", b".\n"):
                    data = False
                    srv.messages.append(b"".join(srv.buf))
                    srv.buf = []
                    self.wfile.write(b"250 OK queued\r\n")
                else:
                    srv.buf.append(line)
                continue
            cmd = line[:4].upper()
            if cmd == b"EHLO":
                self.wfile.write(b"250-test\r\n250 AUTH PLAIN LOGIN\r\n")
            elif cmd == b"HELO":
                self.wfile.write(b"250 test\r\n")
            elif cmd == b"AUTH":
                self.wfile.write(b"535 5.7.8 authentication failed\r\n" if srv.reject_auth else b"235 OK\r\n")
            elif cmd == b"DATA":
                data = True
                self.wfile.write(b"354 go\r\n")
            elif cmd == b"QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"250 OK\r\n")


@pytest.fixture
def smtp_server():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SMTP)
    srv.daemon_threads = True
    srv.messages, srv.buf, srv.reject_auth = [], [], False
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _smtp_env(monkeypatch, port, user=None):
    monkeypatch.setenv("PYROSCOPE_NOTIFY_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(port))
    monkeypatch.setenv("SMTP_TLS_MODE", "none")
    monkeypatch.setenv("SMTP_FROM", "pyroscope@example.org")
    if user:
        monkeypatch.setenv("SMTP_USER", user)
        monkeypatch.setenv("SMTP_PASSWORD", "wrong-Passw0rd-xyz")


class _Contact:
    is_template, verified, contact_channel, contact_value, authority = False, True, "email", "dfo@example.org", "Test DFO"


def test_local_smtp_success_and_labelled_test_message(monkeypatch, smtp_server):
    _smtp_env(monkeypatch, smtp_server.server_address[1])
    chk = notify.check_connection()
    assert chk["ok"] is True
    r = notify.send_test(_Contact(), "admin", sleep=lambda s: None)
    assert r["status"] == "SENT" and len(smtp_server.messages) == 1
    assert b"TEST MESSAGE" in smtp_server.messages[0] and b"Not an alert" in smtp_server.messages[0]


def test_invalid_smtp_credentials_reported_without_secret(monkeypatch, smtp_server):
    _smtp_env(monkeypatch, smtp_server.server_address[1], user="officer")
    monkeypatch.setattr(notify, "_smtp_connect", notify._smtp_connect)
    smtp_server.reject_auth = True
    chk = notify.check_connection()
    assert chk["ok"] is False and "wrong-Passw0rd-xyz" not in json.dumps(chk)
    assert "rejected the SMTP login" in (chk.get("explanation") or "")


def test_missing_credentials_keep_simulated(monkeypatch):
    for k in ("PYROSCOPE_NOTIFY_PROVIDER", "SMTP_HOST", "SMTP_FROM"):
        monkeypatch.delenv(k, raising=False)
    assert notify.status()["external_delivery_enabled"] is False
    assert notify.send_test(_Contact(), "admin")["status"] == "SIMULATED_DELIVERED"
    monkeypatch.setenv("PYROSCOPE_NOTIFY_PROVIDER", "smtp")                 # smtp chosen but not configured -> still simulated
    assert notify.send_test(_Contact(), "admin")["status"] == "SIMULATED_DELIVERED"


def test_webhook_failure_and_retry_then_duplicate_protection(monkeypatch):
    monkeypatch.setenv("PYROSCOPE_NOTIFY_PROVIDER", "webhook")
    monkeypatch.setenv("PYROSCOPE_WEBHOOK_ALLOWED_HOSTS", "hooks.example.org")
    monkeypatch.setenv("PYROSCOPE_WEBHOOK_TOKEN", "hook-token-SECRET")
    calls = []

    def flaky(url, body):
        calls.append(url)
        if len(calls) == 1:
            raise notify.TransientError("HTTP 503 with hook-token-SECRET echoed")
    st, err, n = notify._send_with_retry(flaky, "https://hooks.example.org/x", {}, sleep=lambda s: None)
    assert st == "SENT" and n == 2
    st, err, n = notify._send_with_retry(lambda u, b: (_ for _ in ()).throw(notify.TransientError("HTTP 503 hook-token-SECRET")),
                                         "https://hooks.example.org/x", {}, sleep=lambda s: None)
    assert st == "FAILED" and n == notify.MAX_ATTEMPTS and "hook-token-SECRET" not in err
    st, err, n = notify._send_with_retry(lambda u, b: (_ for _ in ()).throw(PermissionError("host not in allow-list")),
                                         "https://evil.example.com/x", {}, sleep=lambda s: None)
    assert st == "FAILED" and n == 1                                     # permanent: no retry
    assert "allow-list" in system_config.explain_failure(err) or "PYROSCOPE_WEBHOOK_ALLOWED_HOSTS" in system_config.explain_failure(err)


def test_notification_checklist_admin_only():
    assert c.get("/api/notifications/checklist", headers=GOV).status_code == 403
    r = c.get("/api/notifications/checklist", headers=ADMIN).json()
    assert len(r["steps"]) >= 5 and r["provider"]["provider"] in ("simulated", "smtp", "webhook")


# --------------------------------------------------------------------------- pipeline CLI
@pytest.mark.parametrize("argv,attr,val", [
    (["--dry-run"], "dry_run", True), (["--validate-only"], "validate_only", True), (["--only-new"], "only_new", True),
    (["--recover-lfs"], "recover_lfs", True), (["--rebuild-geo"], "rebuild_geo", True), (["--refresh-exposure"], "refresh_exposure", True),
    (["--refresh-tle"], "refresh_tle", True), (["--compare-forecast"], "compare_forecast", True), (["--retrain"], "retrain", True),
    (["--skip-train"], "skip_train", True), (["--skip-weather"], "skip_weather", True), (["--skip-report"], "skip_report", True),
    (["--linear-gis"], "linear_gis", True), (["--sensor-models"], "sensor_models", True),
    (["--viirs750", "2025-01-01", "2025-01-02"], "viirs750", ["2025-01-01", "2025-01-02"]),
])
def test_pipeline_flags(argv, attr, val):
    assert getattr(pipeline.parse_args(argv), attr) == val


def test_pipeline_rejects_unknown_and_conflicting():
    with pytest.raises(SystemExit):
        pipeline.parse_args(["--nope"])
    with pytest.raises(SystemExit):
        pipeline.parse_args(["--retrain", "--skip-train"])
    with pytest.raises(SystemExit):
        pipeline.parse_args(["--viirs750", "2025-01-01"])


def test_pipeline_dry_run_changes_nothing(tmp_path, capsys):
    from app.config import PROCESSED
    before = {p.name: p.stat().st_mtime for p in PROCESSED.glob("*.json")}
    plan = pipeline.main(["--dry-run", "--only-new"])
    assert "archives" in plan and "would_ingest" in plan
    after = {p.name: p.stat().st_mtime for p in PROCESSED.glob("*.json")}
    assert before == after


# --------------------------------------------------------------------------- background jobs
def test_jobs_visible_state_blocked_without_credentials(monkeypatch):
    from app import jobs
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.setattr(viirs750, "_netrc_has_urs", lambda: False)
    assert c.post("/api/jobs", json={"kind": "viirs750_fetch", "params": {"start": "2025-01-01", "end": "2025-01-02"}}, headers=GOV).status_code == 403
    assert c.post("/api/jobs", json={"kind": "rm -rf", "params": {}}, headers=ADMIN).status_code == 400
    j = jobs.submit("viirs750_fetch", {"start": "2025-01-01", "end": "2025-01-02"}, "admin", wait=True)
    assert j["status"] == "FAILED" and "BLOCKED_BY_CREDENTIALS" in j["error"]
    assert any(x["id"] == j["id"] for x in c.get("/api/jobs", headers=ANALYST).json()["items"])


def test_jobs_cooperative_cancel_and_single_instance():
    import time
    from app import jobs
    started = threading.Event()

    def slow(kind, params, jid):
        started.set()
        for _ in range(200):
            if jobs.cancelled(jid):
                raise jobs.Cancelled()
            time.sleep(0.02)
        return {"ok": True}
    j = jobs.submit("tle_refresh", {}, "admin", runner=slow)
    started.wait(5)
    with pytest.raises(PermissionError):
        jobs.submit("tle_refresh", {}, "admin", runner=slow)       # one job per kind at a time
    r = c.post(f"/api/jobs/{j['id']}/cancel", headers=ADMIN).json()
    assert r["cancel_requested"] is True
    for _ in range(100):
        if jobs.get(j["id"])["status"] == "CANCELLED":
            break
        time.sleep(0.05)
    assert jobs.get(j["id"])["status"] == "CANCELLED"


def test_tle_refresh_failure_is_recorded(tmp_path, monkeypatch):
    from app import orbits
    monkeypatch.setattr(orbits, "TLE_DIR", tmp_path)
    monkeypatch.setattr(orbits, "LAST_REFRESH", tmp_path / "last_refresh.json")

    def boom(sat, session=None):
        raise ConnectionError("celestrak unreachable")
    monkeypatch.setattr(orbits, "fetch_tle", boom)
    out = orbits.refresh_all(log=lambda *_: None)
    assert all("error" in v for v in out.values())
    lr = orbits.last_refresh()
    assert set(lr["failed"]) == set(orbits.SATS) and lr["at"]
    assert "celestrak unreachable" in next(iter(lr["results"].values()))["error"]
    stale = orbits.freshness({"epoch": "2020-01-01T00:00:00+00:00"})
    assert stale["stale"] and stale["warning"]


def test_bridge_studies_served_from_stored_result(tmp_path, monkeypatch):
    import json
    from app import bridge
    out = tmp_path / "bridge_calibrations.json"
    out.write_text(json.dumps({"pairs": [{"target": "NOAA-20", "reference": "Suomi NPP", "status": "not_calibrated"}]}))
    monkeypatch.setattr(bridge, "OUT", out)

    def no_recompute(*a, **k):
        raise AssertionError("stored result must be used")
    monkeypatch.setattr(bridge, "study_pair", no_recompute)
    bridge.clear()
    try:
        s = bridge.studies()
        assert s["source"] == "stored" and bridge.status("NOAA-20", "Suomi NPP")["status"] == "not_calibrated"
    finally:
        bridge.clear()
