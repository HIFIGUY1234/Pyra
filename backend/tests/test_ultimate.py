"""Fire events, durable jobs, storage, burned area, emissions, smoke, geostationary import, external validation,
PostgreSQL / Supabase readiness and Vercel configuration.

SYNTHETIC FIXTURES are used for software behaviour only (labelled `synthetic` below). They prove the code paths,
never the science: authentic-data results are produced by the pipelines and reported in the docs.
"""
import json
import math
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import tests.test_api  # noqa: F401  (throw-away DB before app import)
from fastapi.testclient import TestClient

from app import burned_area, emissions, events, external_validation, geostationary, jobs, pg_migrate, smoke, storage
from app import models as M
from app.main import app

c = TestClient(app)
ADMIN, GOV, ANALYST = {"X-User": "admin"}, {"X-User": "forest.officer"}, {"X-User": "analyst"}
ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- synthetic detections
def _det(rows):
    """synthetic detections: (minutes offset, lat, lon, satellite, scan_km, frp)"""
    t0 = pd.Timestamp("2030-01-01 05:00")
    df = pd.DataFrame([{"timestamp_utc": t0 + pd.Timedelta(minutes=m), "latitude": la, "longitude": lo, "satellite": sat,
                        "product_type": "375m" if sat not in ("Terra", "Aqua") else "1km", "scan": sc, "track": sc,
                        "frp_mw": frp, "confidence_class": "nominal", "confidence_score": 0.55, "daynight": "D", "cell_id": -1,
                        "acq_date": (t0 + pd.Timedelta(minutes=m)).date(), "anomaly_type": 0, "source_kind": "synthetic",
                        "source_file": "synthetic"} for m, la, lo, sat, sc, frp in rows])
    df = df.sort_values("timestamp_utc", kind="stable").reset_index(drop=True)
    df["obs_key"] = events.obs_keys(df)
    return df


def test_event_linking_uses_pixel_footprints_and_persistence():
    d = _det([(0, 30.0, 75.0, "NOAA-20", 0.375, 5), (0, 30.0, 75.0036, "NOAA-20", 0.375, 6),   # adjacent pixels (~0.35 km)
              (0, 30.0, 75.02, "NOAA-20", 0.375, 4),                                            # ~1.9 km away: separate fire
              (60 * 24 * 2, 30.0, 75.0, "NOAA-21", 0.375, 3)])                                  # same spot 2 days later
    lab = events.link(d, persistence=np.full(len(d), 1.0))            # cropland persistence 1 day
    assert lab[0] == lab[1] and lab[2] != lab[0] and lab[3] != lab[0]
    lab3 = events.link(d, persistence=np.full(len(d), 3.0))           # forest persistence 3 days re-links the later pass
    assert lab3[3] == lab3[0]
    m = _det([(0, 30.0, 75.0, "Aqua", 1.0, 20), (5, 30.0, 75.009, "NOAA-20", 0.375, 8)])     # ~0.87 km < 0.71 + 0.27 km: footprints touch
    assert len(set(events.link(m, persistence=np.ones(2)))) == 1
    with pytest.raises(ValueError):
        events.link(d.iloc[::-1].reset_index(drop=True), persistence=np.ones(len(d)))


def test_event_identity_continuation_merge_split():
    d = _det([(0, 30.0, 75.0, "NOAA-20", 0.375, 5), (1, 30.0, 75.0036, "NOAA-20", 0.375, 5), (2, 30.0, 75.03, "NOAA-20", 0.375, 5)])
    lab = np.array([0, 0, 1])
    m1, h1 = events.reconcile(d, lab, pd.DataFrame(columns=["obs_key", "event_id", "first_ts"]))
    assert len(set(m1.values())) == 2 and not h1
    prior = pd.DataFrame({"obs_key": d["obs_key"], "event_id": [m1[0], m1[0], m1[1]], "first_ts": d["timestamp_utc"]})
    m2, h2 = events.reconcile(d, lab, prior)                                   # identical re-run: continuation
    assert m2 == m1 and not h2
    m3, h3 = events.reconcile(d, np.array([0, 0, 0]), prior)                   # bridging data: merge into the earlier event
    assert m3[0] == m1[0] and [x["action"] for x in h3] == ["MERGED"] and h3[0]["event_id"] == m1[1]
    m4, h4 = events.reconcile(d, np.array([0, 1, 2]), prior)                   # corrected data: split
    assert m4[0] == m1[0] and m4[1] not in (m1[0], m1[1]) and any(x["action"] == "SPLIT" and x["related_event_id"] == m1[0] for x in h4)


def test_event_status_never_contained_and_end_needs_opportunities():
    d = _det([(0, 30.0, 75.0, "NOAA-20", 0.375, 5)])
    A = events.arrays(d)
    t_last = d["timestamp_utc"].iloc[0]
    no_opps = events.summarise(np.array([0]), A, t_last + pd.Timedelta(days=10), lambda ts: 0)
    assert no_opps["status"] == "POSSIBLY_INACTIVE"                           # quiet but no observing opportunities
    ended = events.summarise(np.array([0]), A, t_last + pd.Timedelta(days=10), lambda ts: 12)
    assert ended["status"] == "ENDED" and "cloud" in ended["end_basis"]
    fresh = events.summarise(np.array([0]), A, t_last + pd.Timedelta(hours=3), lambda ts: 0)
    assert fresh["status"] == "DETECTED" and "CONTAINED" not in events.STATUSES
    assert fresh["fre_mj_low"] < fresh["fre_mj_high"]
    assert fresh["footprint_km2"] == pytest.approx(0.375 ** 2, rel=0.05)      # one pixel: its own extent


def test_events_api_on_demo_data_and_validation():
    s = c.get("/api/events/summary", headers=ANALYST).json()
    assert "NOT INDEPENDENTLY VALIDATED" in s["validation"]
    r = c.get("/api/events", params={"limit": 5, "sort": "n_obs"}, headers=ANALYST)
    assert r.status_code == 200
    assert c.get("/api/events", params={"limit": 5000}, headers=ANALYST).status_code == 422
    assert c.get("/api/events", params={"status": "CONTAINED"}, headers=ANALYST).status_code == 400
    assert c.get("/api/events/FE-00000000-nothere", headers=ANALYST).status_code == 404
    items = r.json()["items"]
    if items:                                                                   # demo window loaded in the committed DB
        eid = items[0]["event_id"]
        d = c.get(f"/api/events/{eid}", headers=ANALYST).json()
        assert "NOT a fire perimeter" in d["interpretation"]["footprint"] and d["geostationary_agreement"]["class"] == "POLAR_ONLY"
        assert c.get(f"/api/events/{eid}/timeline", headers=ANALYST).json()["timeline"]
        obs = c.get(f"/api/events/{eid}/observations", headers=ANALYST).json()
        assert obs["total"] == d["n_obs"] and len(obs["items"]) == d["n_obs"]


# --------------------------------------------------------------------------- durable jobs
def _job(kind="tle_refresh"):
    with M.Session() as s:
        for j in s.query(M.DataJob).filter(M.DataJob.kind == kind, M.DataJob.status.in_(jobs.ACTIVE)):
            j.status = "CANCELLED"
        s.commit()


def test_jobs_retry_backoff_then_success():
    _job()
    calls = []

    def flaky(kind, params, jid):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("transient network failure")
        return {"ok": True}
    j = jobs.submit("tle_refresh", {}, "admin", runner=flaky, wait=True)
    assert j["status"] == "RETRYING" and j["attempts"] == 1 and j["next_run_at"]
    with M.Session() as s:
        s.get(M.DataJob, j["id"]).next_run_at = datetime.utcnow() - timedelta(seconds=1)
        s.commit()
    jobs._overrides[j["id"]] = flaky
    assert jobs.claim(job_id=j["id"]) == j["id"]
    jobs.execute(j["id"])
    done = jobs.get(j["id"])
    assert done["status"] == "SUCCEEDED" and done["attempts"] == 2 and done["result"] == {"ok": True}


def test_jobs_permanent_failure_and_expired_lease_recovery():
    _job()
    j = jobs.submit("tle_refresh", {}, "admin", runner=lambda k, p, i: (_ for _ in ()).throw(ValueError("bad params")), wait=True)
    assert j["status"] == "FAILED" and j["error_code"] == "ValueError" and j["attempts"] == 1
    _job()
    with M.Session() as s:                                   # a worker died mid-job: RUNNING with an expired lease
        dj = M.DataJob(kind="tle_refresh", params={}, status="RUNNING", attempts=1, max_attempts=3, worker_id="dead",
                       lease_expires_at=datetime.utcnow() - timedelta(minutes=1))
        s.add(dj)
        s.commit()
        jid = dj.id
    assert jobs.claim(job_id=jid, worker_id="rescuer") == jid
    assert jobs.get(jid)["worker_id"] == "rescuer" and jobs.get(jid)["attempts"] == 2
    assert jobs.claim(job_id=jid, worker_id="third") is None              # live lease: nobody else can take it
    jobs.cancel(jid, "admin")


def test_jobs_idempotency_and_queued_cancel_and_atomic_claim():
    _job("emissions")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(jobs, "wake", lambda: None)
        os.environ["PYROSCOPE_EMBEDDED_WORKER"] = "0"
        a = jobs.submit("emissions", {}, "admin", idempotency_key="em-2030-01")
        b = jobs.submit("emissions", {}, "admin", idempotency_key="em-2030-01")
        assert a["id"] == b["id"]
        got = []
        ts = [threading.Thread(target=lambda: got.append(jobs.claim(job_id=a["id"], worker_id=f"w{threading.get_ident()}"))) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert sum(1 for g in got if g) == 1                                 # compare-and-set: exactly one owner
        jobs.cancel(a["id"], "admin")
        _job("emissions")
        q = jobs.submit("emissions", {}, "admin")
        assert jobs.cancel(q["id"], "admin")["status"] == "CANCELLED"        # queued: cancelled immediately
    assert c.post("/api/jobs", json={"kind": "fire_events", "params": {"start": "2030-02-01", "end": "2030-01-01"}}, headers=ADMIN).status_code == 400
    assert c.get("/api/jobs", params={"limit": 2}, headers=ANALYST).json()["limit"] == 2


# --------------------------------------------------------------------------- storage
def test_local_storage_roundtrip_and_key_safety(tmp_path):
    st = storage.LocalStorage(tmp_path / "store")
    f = tmp_path / "a.parquet"
    f.write_bytes(b"x" * 1000)
    meta = st.upload("processed-parquet", "events/a.parquet", f)
    assert meta["sha256"] == storage.sha256_file(f) and meta["bytes"] == 1000
    assert st.download("processed-parquet", "events/a.parquet", tmp_path / "b").read_bytes() == f.read_bytes()
    for bad in ("../x", "/abs", "a//b", "a/../../b", "a\\b"):
        with pytest.raises(ValueError):
            st.upload("processed-parquet", bad, f)
    with pytest.raises(ValueError):
        st.upload("not-a-bucket", "k", f)
    assert st.delete("processed-parquet", "events/a.parquet") and not st.delete("processed-parquet", "events/a.parquet")


class _Resp:
    def __init__(self, code=200, headers=None, body=None, content=b""):
        self.status_code, self.headers, self._b, self.content = code, headers or {}, body, content
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        return self._b

    def iter_content(self, n):
        yield self.content


class _FakeSupabase:
    """synthetic Supabase Storage endpoint (records requests; fails one PATCH to exercise TUS resume)"""
    def __init__(self):
        self.headers, self.calls, self.received, self.fail_once = {}, [], 0, True

    def request(self, method, url, **kw):
        self.calls.append((method, url.split("/storage/v1/")[1], kw.get("headers", {})))
        path = url.split("/storage/v1/")[1]
        if method == "POST" and path == "upload/resumable":
            return _Resp(201, {"Location": "https://x.supabase.co/storage/v1/upload/resumable/abc"})
        if method == "PATCH":
            if int(kw["headers"]["Upload-Offset"]) != self.received:
                return _Resp(409)                                    # TUS offset conflict
            self.received += len(kw["data"])
            if self.fail_once and self.received > storage.CHUNK:
                self.fail_once = False                               # chunk stored but the response is lost
                raise ConnectionError("connection reset")
            return _Resp(204, {"Upload-Offset": str(self.received)})
        if method == "HEAD":
            return _Resp(200, {"Upload-Offset": str(self.received)})
        if method == "POST" and path.startswith("object/sign/"):
            return _Resp(200, body={"signedURL": "/object/sign/processed-parquet/k?token=t"})
        if method == "POST" and path.startswith("object/"):
            return _Resp(200, body={"Key": path})
        if path.startswith("object/info/"):
            return _Resp(401)
        return _Resp(404)


def test_supabase_storage_small_tus_resume_sign_and_auth_errors(tmp_path):
    fake = _FakeSupabase()
    st = storage.SupabaseStorage("https://x.supabase.co", "service-role-test-only", session=fake, sleep=lambda s: None)
    small = tmp_path / "s.bin"
    small.write_bytes(b"a" * 100)
    assert st.upload("model-artifacts", "m/s.bin", small)["bytes"] == 100
    assert fake.calls[-1][0] == "POST" and fake.calls[-1][2]["x-upsert"] == "true"
    big = tmp_path / "b.bin"
    big.write_bytes(os.urandom(storage.CHUNK * 2 + 123))
    st.upload("raw-satellite-archives", "firms/b.bin", big)
    assert fake.received == big.stat().st_size                       # all bytes arrived despite one failed chunk
    assert any(m == "HEAD" for m, _, _ in fake.calls)                # resumed from the server offset
    assert st.signed_url("processed-parquet", "k", 600).startswith("https://x.supabase.co/storage/v1/object/sign/")
    with pytest.raises(PermissionError):
        st.metadata("processed-parquet", "k")
    with pytest.raises(PermissionError):
        storage.SupabaseStorage("", "")
    with pytest.raises(ValueError):
        storage.SupabaseStorage("http://evil.example", "k", session=fake)


# --------------------------------------------------------------------------- burned area
def test_sinusoidal_grid_and_india_tiles():
    assert burned_area.tile_of(30.5, 75.5) == (24, 5)                # Punjab: MODIS tile h24v05
    h, v = 24, 5
    lat, lon = burned_area.pixel_latlon(h, v, np.array([1200]), np.array([1200]))
    assert burned_area.tile_of(float(lat[0]), float(lon[0])) == (h, v)
    tiles = burned_area.india_tiles()
    assert (24, 5) in tiles and (25, 6) in tiles and all(22 <= x <= 28 and 4 <= y <= 9 for x, y in tiles)
    assert burned_area.PIX_KM2 == pytest.approx(0.21466, rel=1e-4)


def test_burned_area_hdf4_read_never_counts_unmapped_as_unburned(tmp_path, monkeypatch):
    from pyhdf.SD import SD, SDC
    p = tmp_path / "MCD64A1.A2030305.h24v05.061.2030000000000.hdf"     # synthetic HDF4 granule
    bd = np.zeros((2400, 2400), np.int16)
    bd[1000:1010, 1000:1010] = 306                                     # 100 burned pixels (DOY 306)
    bd[1500:1550, :] = -1                                              # unmapped rows (inside the AOI)
    bd[2390:, :] = -2                                                  # water
    sd = SD(str(p), SDC.WRITE | SDC.CREATE)
    for name, arr, typ in (("Burn Date", bd, SDC.INT16), ("Burn Date Uncertainty", np.ones_like(bd, np.uint8), SDC.UINT8),
                           ("QA", np.full_like(bd, 3, np.uint8), SDC.UINT8)):
        ds = sd.create(name, typ, arr.shape)
        ds[:] = arr
        ds.endaccess()
    sd.end()
    monkeypatch.setattr(burned_area, "OUT", tmp_path / "out")
    meta = burned_area.process_month("MCD64A1", 2030, 11, [p])
    assert meta["burned_km2"] == pytest.approx(100 * burned_area.PIX_KM2)
    assert meta["unmapped_km2"] > 0 and meta["water_km2"] > 0
    assert meta["mapped_km2"] < 2400 * 2400 * burned_area.PIX_KM2       # unmapped/water excluded from mapped area
    px = pd.read_parquet(tmp_path / "out" / "MCD64A1_203011_pixels.parquet")
    assert len(px) == 100 and (px["burn_date"] == pd.Timestamp("2030-11-02")).all()


def test_laads_licence_redirect_is_reported_as_credential_blocker(monkeypatch):
    class S:
        headers = {}

        def get(self, url, **kw):
            r = _Resp(303, {"Location": "/profiles/licenses/archive/allData/61/MCD64A1/2024/306.json"})
            r.is_redirect, r.url = True, url
            return r
    with pytest.raises(PermissionError, match="licence"):
        burned_area.search("MCD64A1", 2024, 11, session=S())
    with pytest.raises(ValueError):
        burned_area.search("MOD14", 2024, 11, session=S())


# --------------------------------------------------------------------------- emissions
def test_emission_factor_table_and_units():
    ef = emissions.emission_factors()
    assert ef.loc["PM2.5", "AGRI"] == 6.26 and ef.loc["CO2", "SAVA"] == 1686 and ef.loc["CH4", "DEFO"] == 5.07
    fre = 1.0e6                                                         # MJ
    dm = fre * emissions.CR_MEAN                                        # 368 000 kg dry matter
    assert dm * ef.loc["PM2.5", "AGRI"] / 1000 == pytest.approx(2303.68)  # kg PM2.5
    assert emissions.burned_area_method_status()["status"] in ("BLOCKED_BY_EXTERNAL_DATA", "BLOCKED_BY_CREDENTIALS")


def test_emissions_monte_carlo_brackets_central(monkeypatch, tmp_path):
    monkeypatch.setattr(emissions, "OUT", tmp_path)
    ev = pd.DataFrame({"event_id": ["E1", "E2"], "first_detection": [pd.Timestamp("2030-01-01")] * 2, "last_detection": [pd.Timestamp("2030-01-02")] * 2,
                       "state": ["Punjab", "Odisha"], "district_id": [None, None], "land_use": ["Agricultural", "Forest"],
                       "fre_mj_low": [1e5, 2e5], "fre_mj_high": [1e6, 2e6], "n_obs": [3, 4], "status": ["ENDED", "ENDED"]})
    monkeypatch.setattr(emissions, "_events", lambda s=None, e=None: ev)
    r = emissions.build(n_draws=500)
    pm = r["totals_tonnes"]["PM2.5"]
    assert pm["p05"] < pm["median"] < pm["p95"] and "NOT INDEPENDENTLY VALIDATED" in r["label"]
    per = pd.read_parquet(tmp_path / "event_emissions.parquet")
    assert (per["PM2.5_kg_low"] < per["PM2.5_kg"]).all() and (per["PM2.5_kg"] < per["PM2.5_kg_high"]).all()
    with pytest.raises(ValueError):
        emissions.build(n_draws=5)


# --------------------------------------------------------------------------- smoke
def _uniform_met(u=10.0, v=0.0):
    """synthetic wind field: uniform u, v (m/s) on a 1 deg grid"""
    lats, lons = np.arange(20, 41, 1.0), np.arange(60, 91, 1.0)
    shape = (30, len(lats), len(lons))
    return {"times": pd.date_range("2030-01-01", periods=30, freq="h"), "lats": lats, "lons": lons,
            "surface_10m": (np.full(shape, u), np.full(shape, v)), "850hPa": (np.full(shape, u), np.full(shape, v)), "blh": np.full(shape, 800.0)}


def test_trajectory_kinematics_and_labels():
    pts = smoke.trajectory(30.0, 75.0, 0.0, 6, _uniform_met(10.0, 0.0), "surface_10m")
    assert pts[-1]["h"] == pytest.approx(6.0)
    km = (pts[-1]["lon"] - 75.0) * 111.32 * math.cos(math.radians(30.0))
    assert km == pytest.approx(216.0, rel=0.02) and abs(pts[-1]["lat"] - 30.0) < 1e-6   # 10 m/s x 6 h = 216 km east
    out = smoke.trajectory(30.0, 89.5, 0.0, 24, _uniform_met(10.0, 0.0), "surface_10m")
    assert out[-1]["h"] < 24                                         # leaves the grid: stops, never extrapolates
    assert "not HYSPLIT" in smoke.LABEL and "no concentrations" in smoke.LABEL


def test_wind_fetch_retries_rate_limit():
    class S:
        n = 0

        def get(self, url, params=None, timeout=None):
            S.n += 1
            if S.n == 1:
                return _Resp(429, body={"reason": "limit"})
            k = len(params["latitude"].split(","))
            hourly = {"time": [f"2030-01-01T{h:02d}:00" for h in range(3)], **{v: [5.0, 5.0, 5.0] for v in params["hourly"].split(",")}}
            return _Resp(200, body=[{"hourly": hourly} for _ in range(k)])
    met = smoke.fetch_winds((74, 29, 76, 31), pd.Timestamp("2030-01-01"), 2, session=S(), sleep=lambda s: None)
    assert S.n >= 2 and met["surface_10m"][0].shape[0] == 3


# --------------------------------------------------------------------------- geostationary
KML = """<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><TimeStamp><when>2030-01-01T05:30:00Z</when></TimeStamp><Point><coordinates>75.0,30.0,0</coordinates></Point></Placemark>
<Placemark><TimeStamp><when>2030-01-01T05:30:00Z</when></TimeStamp><Point><coordinates>80.0,20.0,0</coordinates></Point></Placemark>
</Document></kml>"""


def test_geostationary_import_requires_provenance_and_classifies(tmp_path, monkeypatch):
    monkeypatch.setattr(geostationary, "OUT", tmp_path)
    monkeypatch.setattr(geostationary, "OBS", tmp_path / "obs.parquet")
    with pytest.raises(ValueError):
        geostationary.import_observations(KML.encode(), "x.kml", "", "lic", "admin", "INSAT-3DR", "3RIMG_L2P_FIR")
    with pytest.raises(ValueError):
        geostationary.import_observations(KML.encode(), "x.kml", "synthetic test export", "test", "admin", "Himawari-9", "WLF")
    r = geostationary.import_observations(KML.encode(), "synthetic.kml", "synthetic test export", "test-only", "admin", "INSAT-3DR", "3RIMG_L2P_FIR")
    assert r["imported"] == 2
    geo = geostationary.observations(limit=10)
    assert geo["view_zenith_deg"].between(0, 60).all() and (geo["pixel_km"] >= 4.0).all()
    ev = {"first_detection": "2030-01-01T05:00:00", "last_detection": "2030-01-01T06:00:00", "west": 74.99, "east": 75.01,
          "south": 29.99, "north": 30.01, "lat": 30.0}
    assert geostationary.agreement(ev, geo)["class"] == "POLAR_GEO_AGREE"
    far = dict(ev, west=76.9, east=77.0, lat=30.0)
    assert geostationary.agreement(far, geo)["class"] == "POLAR_GEO_DISAGREE"
    assert geostationary.agreement(ev, geo.iloc[0:0])["class"] == "POLAR_ONLY"
    d = geostationary.diurnal()
    assert d["missing_hours"] and d["hourly_activity_estimate"]["status"] == "EXPERIMENTAL"


def test_geostationary_registry_never_fakes_providers():
    by = {p["id"]: p for p in geostationary.PROVIDERS}
    assert by["goes"]["status"] == "NOT_APPLICABLE" and by["himawari"]["status"] == "NOT_USED"
    assert all(p["status"] != "AVAILABLE" for p in geostationary.PROVIDERS)


# --------------------------------------------------------------------------- external validation
def test_incident_import_and_event_matching(monkeypatch):
    csv = ("incident_id,source_authority,start_date,latitude,longitude\n"
           "SYN-1,Synthetic Test Authority,2030-03-01,30.0,75.0\nSYN-2,Synthetic Test Authority,2030-03-01,10.0,77.0\n"
           "bad,Synthetic Test Authority,not-a-date,30,75\n").encode()
    with pytest.raises(ValueError):
        external_validation.import_incidents(csv, "", "x", "admin")
    r = external_validation.import_incidents(csv, "synthetic-test-register", "test-only", "admin", replace_source=True)
    assert r["imported"] == 2 and r["rejected"] == 1
    with M.Session() as s:
        s.query(M.FireEvent).filter(M.FireEvent.event_id == "FE-SYN-0001").delete()
        s.add(M.FireEvent(event_id="FE-SYN-0001", status="ENDED", first_detection=datetime(2030, 3, 1, 5), last_detection=datetime(2030, 3, 2, 8),
                          n_obs=4, lat=30.01, lon=75.01, west=75.0, east=75.02, south=30.0, north=30.02))
        s.commit()
    v = external_validation.validate_events("2030-03-01", "2030-03-01", dataset="synthetic-test-register")
    assert v["status"] == "COMPUTED" and v["matched_incidents"] == 1 and v["recall"] == 0.5 and "lower bound" in v["caveat"]
    with M.Session() as s:
        s.query(M.FireEvent).filter(M.FireEvent.event_id == "FE-SYN-0001").delete()
        s.query(M.ReferenceIncident).filter(M.ReferenceIncident.dataset == "synthetic-test-register").delete()
        s.commit()


def test_harmonization_baselines_on_real_holdout():
    r = external_validation.harmonization_baselines("country")
    m = r["models"]
    assert r["test_months"] > 0
    assert abs(m["naive_modis_plus_viirs"]["bias_pct"]) > abs(m["pyroscope"]["bias_pct"])   # adding sensors double-counts
    assert m["pyroscope"]["wape_pct"] < m["raw_modis"]["wape_pct"]


def test_advisories_need_review_and_refuse_official_warnings():
    assert c.post("/api/advisories", json={"kind": "OFFICIAL_EMERGENCY_WARNING", "ref": "anything"}, headers=GOV).status_code == 409
    assert c.post("/api/advisories", json={"kind": "MODELLED_PM25_EXPOSURE", "ref": "anything"}, headers=GOV).status_code == 409
    items = c.get("/api/events", params={"limit": 1}, headers=GOV).json()["items"]
    if items:
        r = c.post("/api/advisories", json={"kind": "FIRE_EVENT_ADVISORY", "ref": items[0]["event_id"]}, headers=GOV).json()
        assert r["status"] == "PENDING_HUMAN_REVIEW" and r["payload"]["human_review_required"] and r["payload"]["public_warning"] is False
        assert c.post("/api/advisories", json={"kind": "FIRE_EVENT_ADVISORY", "ref": items[0]["event_id"]}, headers=GOV).status_code == 409


# --------------------------------------------------------------------------- PostgreSQL / Supabase / Vercel readiness
def test_supabase_schema_sql_is_current_and_postgres_native():
    sql = pg_migrate.schema_sql()
    assert (ROOT / "supabase/migrations/20261115000000_pyroscope_schema.sql").read_text(encoding="utf-8") == sql, \
        "run `python -m app.pg_migrate schema-sql` after changing models"
    assert "ENABLE ROW LEVEL SECURITY" in sql and "REVOKE ALL" in sql
    assert "AUTOINCREMENT" not in sql and "DATETIME" not in sql and "TIMESTAMP WITHOUT TIME ZONE" in sql
    for t in ("fire_events", "fire_event_history", "data_jobs", "reference_incidents", "storage_objects", "alerts", "users"):
        assert f"CREATE TABLE IF NOT EXISTS {t} (" in sql
    b = (ROOT / "supabase/migrations/20261115000100_pyroscope_storage_buckets.sql").read_text(encoding="utf-8")
    assert all(f"'{x}'" in b for x in storage.BUCKETS) and "true)" not in b


def test_engine_configuration_for_supabase_poolers(monkeypatch):
    monkeypatch.delenv("PYROSCOPE_DB_POOL", raising=False)
    assert M.normalise_url("postgres://u:p@h/db").startswith("postgresql+psycopg://")
    tx = "postgresql://u:p@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
    assert M.is_transaction_pooler(tx) and not M.is_transaction_pooler("postgresql://u:p@db.x.supabase.co:5432/postgres")
    e = M.make_engine(tx)
    from sqlalchemy.pool import NullPool, QueuePool
    assert isinstance(e.pool, NullPool)
    assert isinstance(M.make_engine("postgresql://u:p@db.x.supabase.co:5432/postgres").pool, QueuePool)
    monkeypatch.setenv("PYROSCOPE_DB_POOL", "transaction")
    assert M.is_transaction_pooler("postgresql://u:p@h:5432/db")


def test_vercel_configuration_and_public_env():
    v = json.loads((ROOT / "frontend/vercel.json").read_text())
    assert v["framework"] == "vite" and v["outputDirectory"] == "dist" and v["buildCommand"] == "npm run build"
    assert any(r["destination"] == "/index.html" for r in v["rewrites"])      # SPA deep links
    txt = json.dumps(v).lower()
    assert "secret" not in txt and "service_role" not in txt and "env" not in v
    env = (ROOT / "frontend/.env.example").read_text()
    keys = [l.split("=")[0] for l in env.splitlines() if l and not l.startswith("#")]
    assert keys == ["VITE_API_BASE_URL"]


def test_cors_regex_validation_and_credentials_hide_values():
    from app import system_config
    base = {"PYROSCOPE_AUTH_MODE": "production", "PYROSCOPE_CORS_ORIGINS": "https://pyroscope.example.org",
            "PYROSCOPE_ADMIN_PASSWORD": "Test-Only-Passw0rd-Long"}
    bad = system_config.validate(dict(base, PYROSCOPE_CORS_ORIGIN_REGEX=".*"))
    assert any(i["key"] == "PYROSCOPE_CORS_ORIGIN_REGEX" for i in bad["issues"])
    good = system_config.validate(dict(base, PYROSCOPE_CORS_ORIGIN_REGEX=r"^https://pyroscope-[a-z0-9-]+-team\.vercel\.app$"))
    assert not any(i["key"] == "PYROSCOPE_CORS_ORIGIN_REGEX" for i in good["issues"])
    creds = system_config.credentials({"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "sk-secret-123", "PYROSCOPE_STORAGE": "supabase"})
    assert "sk-secret-123" not in json.dumps(creds)
    assert next(x for x in creds if x["integration"] == "Supabase Storage")["status"] == "CONFIGURED"


PG = os.getenv("PYROSCOPE_TEST_PG_URL")


@pytest.mark.skipif(not PG, reason="set PYROSCOPE_TEST_PG_URL to a disposable PostgreSQL database (CI provides one)")
def test_postgres_migrations_rls_copy_and_job_claims(tmp_path):
    import shutil
    import subprocess
    import sys
    import sqlalchemy as sa
    eng = sa.create_engine(M.normalise_url(PG))
    with eng.begin() as cx:
        cx.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        cx.execute(sa.text("DO $$BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF; END$$;"))
        cx.execute(sa.text("GRANT USAGE ON SCHEMA public TO anon; ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO anon;"))
        cx.execute(sa.text(pg_migrate.schema_sql()))
        cx.execute(sa.text("CREATE SCHEMA IF NOT EXISTS storage; CREATE TABLE IF NOT EXISTS storage.buckets(id text primary key, name text, public boolean)"))
        cx.execute(sa.text(pg_migrate.buckets_sql()))
    with eng.connect() as cx:
        assert cx.execute(sa.text("select count(*) from pg_tables where schemaname='public' and not rowsecurity")).scalar() == 0
        assert cx.execute(sa.text("select count(*) from storage.buckets where public")).scalar() == 0
        cx.execute(sa.text("SET ROLE anon"))
        with pytest.raises(sa.exc.ProgrammingError):
            cx.execute(sa.text("select * from users")).fetchall()
    src = tmp_path / "src.db"
    shutil.copy(os.environ["DATABASE_URL"].replace("sqlite:///", "", 1), src)
    before = storage.sha256_file(src)
    rep = pg_migrate.copy(f"sqlite:///{src.as_posix()}", PG, log=lambda *a: None)
    assert rep["reconciled"] and storage.sha256_file(src) == before
    assert sum(v.get("copied", 0) for v in pg_migrate.copy(f"sqlite:///{src.as_posix()}", PG, log=lambda *a: None)["tables"].values()) == 0
    code = ("from app import db_sync, jobs, models as M; import threading; db_sync.init_db(); assert M.engine.dialect.name=='postgresql';"
            "j=jobs.submit('tle_refresh', {}, 'admin'); got=[];"
            "ts=[threading.Thread(target=lambda i=i: got.append(jobs.claim(worker_id=f'w{i}'))) for i in range(8)];"
            "[t.start() for t in ts]; [t.join() for t in ts]; print(sum(1 for g in got if g))")
    p = subprocess.run([sys.executable, "-c", code], env=dict(os.environ, DATABASE_URL=PG, PYROSCOPE_EMBEDDED_WORKER="0"),
                       capture_output=True, text=True, timeout=300, cwd=str(ROOT / "backend"))
    assert p.returncode == 0, p.stderr[-2000:]
    assert p.stdout.strip().splitlines()[-1] == "1"


def test_committed_database_carries_no_credentials():
    """The tracked demo DB must never ship a password hash or session (init_db bootstraps the admin from .env)."""
    import sqlite3
    db = ROOT / "data" / "pyroscope.db"
    if not db.exists() or db.stat().st_size < 1000:      # LFS pointer / absent
        pytest.skip("demo database not present")
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        assert con.execute("select count(*) from users where password_hash is not null").fetchone()[0] == 0, \
            "data/pyroscope.db contains a password hash: reset it before committing (see docs/SECURITY.md)"
        assert con.execute("select count(*) from user_sessions").fetchone()[0] == 0
    finally:
        con.close()
