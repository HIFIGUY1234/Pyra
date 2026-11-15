"""Geostationary fire observations, diurnal coverage and multi-sensor agreement (EXPERIMENTAL).

Provider registry (researched 2026-11; facts and gaps recorded per provider). No provider is wired to download
automatically because every product suitable for India needs an account PyroScope does not have:

* INSAT-3D / 3DR / 3DS imager fire product (MOSDAC, product 3DIMG_L2P_FIR / 3RIMG_L2P_FIR / 3SIMG_L2P_FIR):
  point fire locations in KML from MIR/TIR brightness temperatures; full-disk every 30 min per satellite (staggered
  3D/3DR give ~15 min); ~4 km MIR pixels; INSAT-3D since 2013, 3DR since 2016. Access: MOSDAC registration.
* Meteosat IODC (SEVIRI, 3 km, 15 min): LSA SAF lists an MSG-IODC FRP-PIXEL DEMONSTRATION product since 2017;
  its operational status and India coverage are not confirmed. Access: LSA SAF registration.
* Himawari-8/9 (140.7 E): India lies at view zenith angles of ~55-75 deg -> pixels too large / too oblique;
  not used (at most marginal for far north-east India).
* GOES (75 W / 137 W): no view of India. Not applicable.
* Fengyun-4: not evaluated (product access and India geometry unverified) - not used.

Because INSAT starts in 2013 it can never validate the 2000-2002 Terra-only reconstruction; the morning-gap
validation stays purely statistical (see app.harmonize).

What runs today: (1) an authorised import of geostationary fire pixels exported from a provider (CSV schema below or
INSAT KML), stored with provenance; (2) the polar-orbiter diurnal sampling picture from real detection times
(only the hours the sensors actually observe; no interpolation); (3) per-event agreement classes.
"""
from __future__ import annotations

import io
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .config import PROCESSED

OUT = PROCESSED / "geostationary"
OBS = OUT / "observations.parquet"
CSV_COLUMNS = ["timestamp_utc", "latitude", "longitude", "platform", "product"]
OPTIONAL = ["frp_mw", "confidence", "pixel_km", "view_zenith_deg", "quality_flag"]
PLATFORMS = {"INSAT-3D": 82.0, "INSAT-3DR": 74.0, "INSAT-3DS": 82.0, "Meteosat-9": 45.5, "Meteosat-8": 41.5}   # sub-satellite lon E

PROVIDERS = [
    {"id": "insat_mosdac", "name": "INSAT-3D/3DR/3DS imager fire (MOSDAC)", "products": ["3DIMG_L2P_FIR", "3RIMG_L2P_FIR", "3SIMG_L2P_FIR"],
     "smoke_products": ["3DIMG_L2P_SMK"], "format": "KML point placemarks (fire); HDF5 for most other INSAT products",
     "coverage": "Full disk centred 74-82 E: all of India", "view_angle": "suitable (India within ~45 deg of nadir)",
     "resolution": "~4 km MIR", "cadence": "30 min per satellite (~15 min combined 3D + 3DR)", "archive": "INSAT-3D 2013-, 3DR 2016-",
     "access": "MOSDAC registration and data-access policy", "licence": "ISRO/MOSDAC data policy (registration)",
     "status": "BLOCKED_BY_DATA_LICENCE_OR_ACCESS", "connector": "authorised KML/CSV import implemented; automatic download not implemented",
     "sources": ["https://www.mosdac.gov.in/docs/INSAT3D_Products.pdf", "https://www.mosdac.gov.in/node/886"]},
    {"id": "lsasaf_iodc", "name": "Meteosat IODC SEVIRI FRP-PIXEL (LSA SAF)", "products": ["MSG-IODC FRP-PIXEL (demonstration)"],
     "format": "HDF5 / NetCDF", "coverage": "Indian Ocean disk centred 45.5 E; western/central India at moderate angles, "
     "north-east India oblique", "view_angle": "partly suitable", "resolution": "3 km at nadir", "cadence": "15 min",
     "archive": "2017- (demonstration)", "access": "LSA SAF registration", "licence": "EUMETSAT LSA SAF data policy",
     "status": "BLOCKED_BY_DATA_LICENCE_OR_ACCESS", "connector": "authorised CSV import implemented",
     "sources": ["https://lsa-saf.eumetsat.int/data/products/fire-products/"]},
    {"id": "himawari", "name": "Himawari-8/9 AHI wildfire (JAXA)", "coverage": "disk centred 140.7 E", "view_angle": "unsuitable for most of India (~55-75 deg)",
     "status": "NOT_USED", "connector": "none (viewing geometry)"},
    {"id": "goes", "name": "GOES ABI fire (NOAA)", "coverage": "Americas", "view_angle": "no view of India", "status": "NOT_APPLICABLE", "connector": "none"},
    {"id": "fengyun4", "name": "Fengyun-4 AGRI fire (CMA)", "status": "NOT_EVALUATED", "connector": "none",
     "note": "access route and India geometry not verified; not used"},
]


def _view_zenith(lat: np.ndarray, lon: np.ndarray, sub_lon: float) -> np.ndarray:
    """Satellite view zenith angle (deg) for a geostationary platform at sub_lon, spherical Earth."""
    re_, h = 6371.0, 35786.0
    la, dl = np.radians(lat), np.radians(lon - sub_lon)
    cosg = np.cos(la) * np.cos(dl)
    d = np.sqrt(re_ ** 2 + (re_ + h) ** 2 - 2 * re_ * (re_ + h) * cosg)
    return np.degrees(np.arcsin(np.clip((re_ + h) / d * np.sqrt(1 - cosg ** 2), -1, 1)))


def parse_kml(text: str, platform: str, product: str, timestamp_utc: str | None = None) -> pd.DataFrame:
    """Point placemarks -> rows. Time from <TimeStamp><when>, else from a YYYYMMDD_HHMM / DDMONYYYY_HHMM token in the
    product name, else `timestamp_utc`. Written against the KML 2.2 standard; NOT yet verified on an authentic MOSDAC file."""
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    root = ET.fromstring(text)
    rows = []
    for pm in root.iter("{http://www.opengis.net/kml/2.2}Placemark"):
        c = pm.find(".//k:Point/k:coordinates", ns)
        if c is None or not c.text:
            continue
        lon, lat = (float(x) for x in c.text.strip().split(",")[:2])
        w = pm.find(".//k:TimeStamp/k:when", ns)
        rows.append({"timestamp_utc": w.text if w is not None else timestamp_utc, "latitude": lat, "longitude": lon,
                     "platform": platform, "product": product})
    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    if df["timestamp_utc"].isna().any():
        raise ValueError("KML placemarks without <TimeStamp> need an explicit timestamp_utc")
    return df


def import_observations(content: bytes, filename: str, source: str, licence: str, actor: str, platform: str | None = None,
                        product: str | None = None, timestamp_utc: str | None = None) -> dict:
    """Authorised import of geostationary fire pixels exported from a provider. Provenance is mandatory."""
    if not source.strip() or not licence.strip():
        raise ValueError("source and licence are required (provenance of the exported data)")
    name = filename.lower()
    if name.endswith(".kml"):
        if not platform or not product:
            raise ValueError("KML import needs platform and product")
        df = parse_kml(content.decode("utf-8", "replace"), platform, product, timestamp_utc)
    elif name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content))
        miss = [c for c in CSV_COLUMNS if c not in df.columns]
        if miss:
            raise ValueError(f"CSV missing columns {miss}; required {CSV_COLUMNS}, optional {OPTIONAL}")
    else:
        raise ValueError("file must be .csv or .kml")
    df = df[[c for c in CSV_COLUMNS + OPTIONAL if c in df.columns]].copy()
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce").dt.tz_convert(None)
    bad = df["timestamp_utc"].isna() | ~df["latitude"].between(-90, 90) | ~df["longitude"].between(-180, 180)
    if bad.all():
        raise ValueError("no valid rows (timestamps / coordinates)")
    df = df[~bad]
    unknown = sorted(set(df["platform"]) - set(PLATFORMS))
    if unknown:
        raise ValueError(f"unknown platform(s) {unknown}; supported {sorted(PLATFORMS)}")
    if "view_zenith_deg" not in df or df["view_zenith_deg"].isna().all():
        df["view_zenith_deg"] = [float(_view_zenith(np.array([la]), np.array([lo]), PLATFORMS[p])[0])
                                 for la, lo, p in zip(df["latitude"], df["longitude"], df["platform"])]
    if "pixel_km" not in df:
        df["pixel_km"] = np.where(df["platform"].str.startswith("INSAT"), 4.0, 3.0) / np.cos(np.radians(df["view_zenith_deg"].clip(upper=80)))
    df["source"], df["licence"], df["imported_by"] = source, licence, actor
    df["imported_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    df["source_file"] = re.sub(r"[^\w.\-]", "_", filename)[:120]
    OUT.mkdir(parents=True, exist_ok=True)
    allobs = pd.concat([pd.read_parquet(OBS), df], ignore_index=True) if OBS.exists() else df
    allobs = allobs.drop_duplicates(["platform", "product", "timestamp_utc", "latitude", "longitude"])
    allobs.to_parquet(OBS, index=False)
    return {"imported": int(len(df)), "rejected": int(bad.sum()), "total": int(len(allobs)),
            "platforms": df["platform"].value_counts().to_dict(),
            "period": [df["timestamp_utc"].min().isoformat(), df["timestamp_utc"].max().isoformat()]}


def observations(start=None, end=None, limit: int = 5000) -> pd.DataFrame:
    if not OBS.exists():
        return pd.DataFrame(columns=CSV_COLUMNS + OPTIONAL)
    d = pd.read_parquet(OBS)
    if start:
        d = d[d["timestamp_utc"] >= pd.Timestamp(start)]
    if end:
        d = d[d["timestamp_utc"] < pd.Timestamp(end) + pd.Timedelta(days=1)]
    return d.head(limit)


def coverage() -> dict:
    d = observations(limit=10 ** 9)
    return {"providers": PROVIDERS, "imported_observations": int(len(d)),
            "by_platform": d.groupby("platform").agg(n=("latitude", "size"), first=("timestamp_utc", "min"), last=("timestamp_utc", "max"))
            .reset_index().astype({"first": str, "last": str}).to_dict("records") if len(d) else [],
            "status": "IMPORTED_EXPERIMENTAL" if len(d) else "NO_GEOSTATIONARY_DATA",
            "historical_limit": "INSAT archives begin in 2013 and cannot validate the 2000-2002 Terra-only reconstruction.",
            "label": "EXPERIMENTAL - NOT INDEPENDENTLY VALIDATED"}


def diurnal() -> dict:
    """Hour-of-day sampling of fire activity from REAL detection local solar times (polar orbiters) plus any imported
    geostationary pixels. Counts are per sensor and are not comparable across sensors (different sensitivity), so no
    blended hourly curve is produced from polar data alone; hours no sensor observes are listed as missing."""
    from . import store
    lst = pd.read_parquet(store.LST) if store.LST.exists() else pd.DataFrame(columns=["satellite", "daynight", "lst_bin", "n"])
    lst = lst.assign(hour=np.floor(lst["lst_bin"]).astype(int) % 24)
    polar = lst.groupby(["satellite", "hour"])["n"].sum().reset_index()
    observed = sorted(set(polar.loc[polar["n"] > 0, "hour"].astype(int)))
    geo_rows, geo_hours = [], []
    g = observations(limit=10 ** 9)
    if len(g):
        lst_h = (g["timestamp_utc"].dt.hour + g["timestamp_utc"].dt.minute / 60 + g["longitude"] / 15) % 24
        gh = g.assign(hour=np.floor(lst_h).astype(int)).groupby(["platform", "hour"]).size().reset_index(name="n")
        geo_rows = gh.to_dict("records")
        geo_hours = sorted(set(gh["hour"].astype(int)))
    hours_any = sorted(set(observed) | set(geo_hours))
    return {"polar_by_sensor_hour": polar.to_dict("records"), "geostationary_by_platform_hour": geo_rows,
            "observed_hours_polar": observed, "observed_hours_any": hours_any,
            "missing_hours": [h for h in range(24) if h not in hours_any],
            "hourly_activity_estimate": {"status": "NOT_AVAILABLE" if not geo_rows else "EXPERIMENTAL",
                                         "reason": "Polar orbiters sample ~4 fixed local times; an hourly curve needs geostationary "
                                                   "observations, none of which are imported." if not geo_rows else
                                                   "Geostationary counts by local hour; coarse pixels detect fewer small fires than VIIRS."},
            "time_basis": "local solar time = UTC + longitude/15", "label": "EXPERIMENTAL"}


AGREEMENT = ("POLAR_ONLY", "POLAR_GEO_AGREE", "POLAR_GEO_DISAGREE", "GEO_ONLY", "NO_CORROBORATION")


def agreement(event: dict, geo: pd.DataFrame, window_h: float = 1.0) -> dict:
    """Classify geostationary support for one fire event. Agreement: a geo pixel whose footprint (pixel_km/2) reaches
    the event footprint box within +/- window_h of a polar detection day. Disagreement: geo data exist for the event's
    hours (any pixel within 300 km in the window) but none near the event. Coarse geo pixels are never equated with
    375 m VIIRS detections."""
    if geo is None or geo.empty:
        return {"class": "POLAR_ONLY", "geo_pixels": 0, "note": "no geostationary observations imported for this period"}
    t0 = pd.Timestamp(event["first_detection"]).tz_localize(None) - pd.Timedelta(hours=window_h)
    t1 = pd.Timestamp(event["last_detection"]).tz_localize(None) + pd.Timedelta(hours=window_h)
    w = geo[(geo["timestamp_utc"] >= t0) & (geo["timestamp_utc"] <= t1)]
    if w.empty:
        return {"class": "POLAR_ONLY", "geo_pixels": 0, "note": "no geostationary observations in the event's time window"}
    k = 111.32
    dx = np.maximum(0, np.maximum(event["west"] - w["longitude"], w["longitude"] - event["east"])) * k * math.cos(math.radians(event["lat"]))
    dy = np.maximum(0, np.maximum(event["south"] - w["latitude"], w["latitude"] - event["north"])) * k
    dist = np.hypot(dx, dy)
    near = w[dist <= w["pixel_km"].fillna(4.0) / 2 + 1.0]
    if len(near):
        return {"class": "POLAR_GEO_AGREE", "geo_pixels": int(len(near)), "platforms": sorted(near["platform"].unique().tolist()),
                "mean_view_zenith_deg": float(near["view_zenith_deg"].mean())}
    if (dist <= 300).any():
        return {"class": "POLAR_GEO_DISAGREE", "geo_pixels": 0,
                "note": "geostationary data cover the area and time but show no fire near the event (small/short fires are often below geo detection limits)"}
    return {"class": "NO_CORROBORATION", "geo_pixels": 0}


def agreement_summary(start, end, limit_events: int = 2000) -> dict:
    """Agreement classes for fire events in [start, end] plus GEO_ONLY pixels (geo detections near no event)."""
    from . import events
    q = events.query(start=start, end=end, limit=limit_events, sort="last_detection")
    from sqlalchemy import select
    from . import models as M
    ids = [e["event_id"] for e in q["items"]]
    with M.Session() as s:
        evs = [{k: getattr(e, k) for k in ("event_id", "first_detection", "last_detection", "west", "east", "south", "north", "lat")}
               for e in s.scalars(select(M.FireEvent).where(M.FireEvent.event_id.in_(ids)))]
    geo = observations(start, end, limit=10 ** 9)
    classes = {c: 0 for c in AGREEMENT}
    used = np.zeros(len(geo), bool)
    for e in evs:
        a = agreement(e, geo)
        classes[a["class"]] += 1
    if len(geo) and evs:
        k = 111.32
        for e in evs:
            m = (geo["longitude"].between(e["west"] - 0.05, e["east"] + 0.05) & geo["latitude"].between(e["south"] - 0.05, e["north"] + 0.05))
            used |= m.to_numpy()
    classes["GEO_ONLY"] = int((~used).sum()) if len(geo) else 0
    return {"start": start, "end": end, "events": len(evs), "classes": classes, "geo_pixels": int(len(geo)),
            "note": "GEO_ONLY counts geostationary pixels, not events. Without imported geostationary data every event is POLAR_ONLY.",
            "label": "EXPERIMENTAL"}
