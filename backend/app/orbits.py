"""Orbit-based observation-opportunity prediction (SGP4).

A predicted pass is an *observation opportunity*: the location lies inside the instrument swath while the
satellite is overhead. It is never a prediction that a fire exists or will be detected.

TLEs come from CelesTrak (public GP data). Each fetch is cached with its acquisition time and TLE epoch;
elements older than ``STALE_DAYS`` are flagged. Propagation uses the maintained ``sgp4`` package (Vallado
implementation, WGS-72 constants as SGP4 requires). TEME -> Earth-fixed uses GMST (IAU-82); polar motion
and the equation of the equinoxes are ignored (< 30 m, irrelevant at swath scale).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .config import DATA

TLE_DIR = DATA / "auxiliary" / "tle"
CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=TLE"
STALE_DAYS = 7.0
R_EARTH = 6378.137          # WGS-84 equatorial radius, km
F_EARTH = 1 / 298.257223563

# NORAD catalogue numbers and instrument geometry. Max scan angle from instrument specifications
# (MODIS ±55°, VIIRS ±56.28°); swath edge elevation is derived from it and the orbit height.
SATS = {
    "Terra":     {"catnr": 25994, "instrument": "MODIS", "scan_deg": 55.0},
    "Aqua":      {"catnr": 27424, "instrument": "MODIS", "scan_deg": 55.0},
    "Suomi NPP": {"catnr": 37849, "instrument": "VIIRS", "scan_deg": 56.28},
    "NOAA-20":   {"catnr": 43013, "instrument": "VIIRS", "scan_deg": 56.28},
    "NOAA-21":   {"catnr": 54234, "instrument": "VIIRS", "scan_deg": 56.28},
}


# --------------------------------------------------------------------------- TLE acquisition
def parse_tle(text: str) -> tuple[str, str, str]:
    lines = [ln.rstrip() for ln in text.strip().splitlines() if ln.strip()]
    l1 = next((ln for ln in lines if ln.startswith("1 ")), None)
    l2 = next((ln for ln in lines if ln.startswith("2 ")), None)
    if not l1 or not l2 or len(l1) < 69 or len(l2) < 69:
        raise ValueError("not a valid two-line element set")
    for ln in (l1, l2):  # modulo-10 checksum
        s = sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in ln[:68])
        if s % 10 != int(ln[68]):
            raise ValueError("TLE checksum failed")
    name = lines[0] if not lines[0].startswith(("1 ", "2 ")) else ""
    return name, l1, l2


def tle_epoch(l1: str) -> datetime:
    yy = int(l1[18:20])
    year = 2000 + yy if yy < 57 else 1900 + yy
    doy = float(l1[20:32])
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1)


def _cache(sat: str) -> Path:
    return TLE_DIR / f"{SATS[sat]['catnr']}.json"


def fetch_tle(sat: str, session=None, now: datetime | None = None) -> dict:
    """Download the current TLE for one satellite and cache it with provenance."""
    import requests
    s = session or requests
    url = CELESTRAK.format(catnr=SATS[sat]["catnr"])
    r = s.get(url, timeout=30, headers={"User-Agent": "PyroScope/1.0"})
    r.raise_for_status()
    name, l1, l2 = parse_tle(r.text)
    if int(l1[2:7]) != SATS[sat]["catnr"]:
        raise ValueError(f"catalogue number mismatch for {sat}")
    rec = {"satellite": sat, "catnr": SATS[sat]["catnr"], "name": name, "line1": l1, "line2": l2,
           "epoch": tle_epoch(l1).isoformat(), "source": url,
           "acquired": (now or datetime.now(timezone.utc)).isoformat()}
    TLE_DIR.mkdir(parents=True, exist_ok=True)
    _cache(sat).write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def load_tle(sat: str) -> dict | None:
    p = _cache(sat)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def refresh_all(log=print, session=None) -> dict:
    out = {}
    for sat in SATS:
        try:
            out[sat] = fetch_tle(sat, session=session)
            log(f"TLE {sat}: epoch {out[sat]['epoch']}")
        except Exception as exc:  # reported, never invented
            out[sat] = {"error": f"{type(exc).__name__}: {exc}"}
            log(f"TLE {sat}: FAILED {exc}")
    return out


def freshness(rec: dict, at: datetime | None = None) -> dict:
    at = at or datetime.now(timezone.utc)
    age = (at - datetime.fromisoformat(rec["epoch"])).total_seconds() / 86400
    return {"tle_age_days": round(age, 2), "stale": abs(age) > STALE_DAYS,
            "warning": (f"TLE epoch is {abs(age):.1f} days from the requested time; SGP4 timing error grows with "
                        f"element age, so passes are indicative only.") if abs(age) > STALE_DAYS else None}


# --------------------------------------------------------------------------- geometry
def _sat(rec: dict):
    from sgp4.api import Satrec
    return Satrec.twoline2rv(rec["line1"], rec["line2"])


def _jd(t: np.ndarray):
    """datetime64[s] UTC array -> (jd, fr)."""
    sec = (t - np.datetime64("2000-01-01T12:00:00")).astype("timedelta64[ms]").astype(np.float64) / 86400000.0
    return np.full(len(sec), 2451545.0), sec


def _gmst(jd: np.ndarray, fr: np.ndarray) -> np.ndarray:
    tu = ((jd - 2451545.0) + fr) / 36525.0
    g = 67310.54841 + (876600 * 3600 + 8640184.812866) * tu + 0.093104 * tu ** 2 - 6.2e-6 * tu ** 3
    return np.radians((g % 86400) / 240.0)


def ecef_positions(rec: dict, t: np.ndarray) -> np.ndarray:
    """Earth-fixed satellite position (km) at UTC times ``t`` (datetime64)."""
    sat = _sat(rec)
    jd, fr = _jd(t.astype("datetime64[s]"))
    err, r, _ = sat.sgp4_array(jd, fr)
    r = np.asarray(r, dtype=float)
    r[err != 0] = np.nan
    th = _gmst(jd, fr)
    c, s = np.cos(th), np.sin(th)
    return np.column_stack([c * r[:, 0] + s * r[:, 1], -s * r[:, 0] + c * r[:, 1], r[:, 2]])


def _observer(lat: float, lon: float, h_km: float = 0.0):
    la, lo = math.radians(lat), math.radians(lon)
    e2 = F_EARTH * (2 - F_EARTH)
    n = R_EARTH / math.sqrt(1 - e2 * math.sin(la) ** 2)
    p = np.array([(n + h_km) * math.cos(la) * math.cos(lo), (n + h_km) * math.cos(la) * math.sin(lo),
                  (n * (1 - e2) + h_km) * math.sin(la)])
    up = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    return p, up


def look(rec: dict, lat: float, lon: float, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Elevation (deg), slant range (km) and sub-satellite (lat, lon) for an observer."""
    pos = ecef_positions(rec, t)
    o, up = _observer(lat, lon)
    d = pos - o
    rng = np.linalg.norm(d, axis=1)
    el = np.degrees(np.arcsin(np.clip((d @ up) / rng, -1, 1)))
    rr = np.linalg.norm(pos, axis=1)
    sub = np.column_stack([np.degrees(np.arcsin(pos[:, 2] / rr)), np.degrees(np.arctan2(pos[:, 1], pos[:, 0]))])
    return el, rng, sub


def swath_min_elevation(sat: str, height_km: float) -> float:
    """Observer elevation of the satellite at the swath edge (spherical Earth)."""
    s = math.radians(SATS[sat]["scan_deg"])
    zen = math.asin(min(1.0, (R_EARTH + height_km) / R_EARTH * math.sin(s)))
    return 90.0 - math.degrees(zen)


def passes(sat: str, lat: float, lon: float, start: datetime, hours: float = 48, step_s: int = 20,
           rec: dict | None = None, tz_offset_h: float = 5.5) -> dict:
    """Observation opportunities: intervals where the point is inside the instrument swath."""
    rec = rec or load_tle(sat)
    if not rec:
        return {"satellite": sat, "available": False, "reason": "No TLE cached. Run `python -m app.orbits refresh`.", "passes": []}
    t0 = np.datetime64(start.astimezone(timezone.utc).replace(tzinfo=None), "s")
    t = t0 + np.arange(0, int(hours * 3600) + 1, step_s).astype("timedelta64[s]")
    el, rng, sub = look(rec, lat, lon, t)
    pos = ecef_positions(rec, t[:1])
    h = float(np.linalg.norm(pos[0]) - R_EARTH)
    emin = swath_min_elevation(sat, h)
    vis = el >= emin
    out = []
    i = 0
    while i < len(t):
        if not vis[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(t) and vis[j + 1]:
            j += 1
        k = i + int(np.nanargmax(el[i:j + 1]))
        tmax = t[k].astype("datetime64[s]").astype(datetime).replace(tzinfo=timezone.utc)
        lst = (tmax.hour + tmax.minute / 60 + lon / 15.0) % 24
        out.append({"rise_utc": str(t[i]) + "Z", "max_utc": str(t[k]) + "Z", "set_utc": str(t[j]) + "Z",
                    "max_local": (tmax + timedelta(hours=tz_offset_h)).strftime("%Y-%m-%d %H:%M"),
                    "local_solar_time_h": round(lst, 2), "daynight": "D" if 6 <= lst < 18 else "N",
                    "duration_min": round((j - i) * step_s / 60, 1), "max_elevation_deg": round(float(el[k]), 1),
                    "min_range_km": round(float(rng[k]), 0),
                    "subsatellite_at_max": [round(float(sub[k, 0]), 3), round(float(sub[k, 1]), 3)]})
        i = j + 1
    track = [[round(float(a), 2), round(float(b), 2)] for a, b in sub[:: max(1, 180 // step_s)][: 400]]
    return {"satellite": sat, "instrument": SATS[sat]["instrument"], "available": True, "observer": [lat, lon],
            "tle": {k: rec[k] for k in ("catnr", "name", "epoch", "source", "acquired")},
            "freshness": freshness(rec, start.astimezone(timezone.utc)),
            "swath_edge_elevation_deg": round(emin, 1), "orbit_height_km": round(h, 0),
            "local_time_zone": "IST (UTC+5:30)" if tz_offset_h == 5.5 else f"UTC{tz_offset_h:+}",
            "passes": out, "ground_track": track,
            "meaning": "Predicted observation opportunity (point inside the swath). Not a fire prediction: a pass does not mean a fire exists or will be detected; cloud and sun glint also block detection."}


# --------------------------------------------------------------------------- validation
def validate(sat: str, detections, rec: dict | None = None, max_days: float = 30.0) -> dict:
    """Compare predicted closest-approach times with actual detection times.

    For each detection (lat, lon, timestamp_utc) the time of maximum satellite elevation within ±30 min of
    the recorded time is found; the residual is recorded time - predicted time. FIRMS ``acq_time`` is the
    scan time rounded to the minute for VIIRS and the 5-min granule start for MODIS, so residuals of a few
    minutes are expected from the record format, not from the orbit.
    """
    rec = rec or load_tle(sat)
    if rec is None or detections is None or len(detections) == 0:
        return {"satellite": sat, "validated": False, "reason": "no TLE or no detections", "n": 0}
    ep = np.datetime64(datetime.fromisoformat(rec["epoch"]).replace(tzinfo=None), "s")
    d = detections.copy()
    ts = d["timestamp_utc"].values.astype("datetime64[s]")
    age = np.abs((ts - ep).astype(np.float64)) / 86400
    d = d[age <= max_days]
    ts = ts[age <= max_days]
    if len(d) == 0:
        return {"satellite": sat, "validated": False, "n": 0,
                "reason": f"no detections within {max_days:.0f} days of the TLE epoch"}
    res = []
    offs = np.arange(-1800, 1801, 10).astype("timedelta64[s]")
    for (la, lo), t in zip(d[["latitude", "longitude"]].to_numpy(), ts):
        el, _, _ = look(rec, float(la), float(lo), t + offs)
        if np.all(np.isnan(el)):
            continue
        k = int(np.nanargmax(el))
        res.append(-float(offs[k].astype(np.float64)) / 60.0)
    r = np.array(res)
    if len(r) == 0:
        return {"satellite": sat, "validated": False, "n": 0, "reason": "propagation failed"}
    return {"satellite": sat, "validated": True, "n": int(len(r)),
            "tle_epoch": rec["epoch"], "max_detection_age_days": round(float(age[age <= max_days].max()), 1),
            "median_residual_min": round(float(np.median(r)), 2), "mean_abs_residual_min": round(float(np.mean(np.abs(r))), 2),
            "p95_abs_residual_min": round(float(np.percentile(np.abs(r), 95)), 2),
            "within_10_min_pct": round(float(np.mean(np.abs(r) <= 10) * 100), 1),
            "note": "Residual = recorded acq_time - predicted closest approach. Recorded times are minute/granule resolution."}


def validate_from_store(sat: str, n: int = 400, seed: int = 20261114) -> dict:
    """Validate against NRT detections loaded in the hotspot store (sampled, reproducible)."""
    import pandas as pd

    from .config import PROCESSED
    tag = {"Terra": "M-C61", "Aqua": "M-C61", "Suomi NPP": "SV-C2", "NOAA-20": "J1V-C2", "NOAA-21": "J2V-C2"}[sat]
    files = sorted((PROCESSED / "hotspots").glob(f"fire_nrt_{tag}_*/*.parquet"))
    if not files:
        return {"satellite": sat, "validated": False, "n": 0, "reason": "no NRT detections loaded"}
    df = pd.concat([pd.read_parquet(f, columns=["latitude", "longitude", "timestamp_utc", "satellite"]) for f in files])
    df = df[df["satellite"] == sat]
    rec = load_tle(sat)
    if rec is None:
        return {"satellite": sat, "validated": False, "n": 0, "reason": "no TLE cached"}
    ep = pd.Timestamp(datetime.fromisoformat(rec["epoch"]).replace(tzinfo=None))
    df = df[(df["timestamp_utc"] - ep).abs() <= pd.Timedelta(days=30)]
    if len(df) > n:
        df = df.sample(n, random_state=seed)
    return validate(sat, df, rec)


VALIDATION = DATA / "auxiliary" / "tle" / "validation.json"


def run_validation(log=print) -> dict:
    out = {s: validate_from_store(s) for s in SATS}
    out["generated"] = datetime.now(timezone.utc).isoformat()
    TLE_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for s in SATS:
        log(f"{s}: {out[s]}")
    return out


def validation_summary() -> dict:
    return json.loads(VALIDATION.read_text(encoding="utf-8")) if VALIDATION.exists() else {}


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "refresh"
    if cmd == "refresh":
        refresh_all()
    elif cmd == "validate":
        run_validation()
    else:
        raise SystemExit("usage: python -m app.orbits [refresh|validate]")
