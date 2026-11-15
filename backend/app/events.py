"""Fire-event delineation: groups related active-fire detections into space-time fire events.

One hotspot is ONE thermal-anomaly detection, not one fire. An event here is a connected component of a
space-time graph whose nodes are original FIRMS detections (all sensors, raw records untouched) and whose edges
join two detections when

  * their pixel footprints touch: ground distance <= r_i + r_j, with r = half the footprint diagonal
    (0.5 * sqrt(scan^2 + track^2) km, i.e. ~0.27 km for VIIRS 375 m at nadir, ~0.71 km for MODIS 1 km), and
  * they are no more than `persistence` days apart, where persistence depends on the land cover of the cell
    (cropland / urban: 1 day; forest, savanna and other: 3 days) - short field burns are not chained across days.

Static/industrial sources (FIRMS type 1/2/3) are excluded. The footprint polygon is an OBSERVATION footprint
(hull of detected pixel extents), not a fire perimeter or a burned area. Status never says CONTAINED, and ENDED
needs both a quiet period longer than the persistence window and enough sensor-days with data since the last
detection (FIRMS carries no cloud mask, so a quiet period can still be cloud-obscured; see `end_basis`).

Event identity is stable across runs: IDs derive from the first observation, and a re-run reconciles new
components against the stored observation -> event associations (continuation / merge / split, with history).
Associations are stored as Parquet (processed/events/associations.parquet); event summaries and history in the DB.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from sqlalchemy import delete, select

from . import models as M
from .config import PROCESSED

EVENTS_DIR = PROCESSED / "events"
ASSOC = EVENTS_DIR / "associations.parquet"
RUNS = EVENTS_DIR / "runs.json"
METHOD_VERSION = "pyroscope-events-1.0"
R_EARTH = 6371.0088
PERSISTENCE_DAYS = {"Agricultural": 1.0, "Municipal/Urban": 1.0, "Forest": 3.0, "Other": 3.0}
DEFAULT_PERSISTENCE = 3.0
REVISIT_H = 12.0                 # polar-orbiter revisit bound used for start/end uncertainty
FRE_ISOLATED_H = (0.5, 6.0)      # unobserved burning credited to each side of an isolated overpass (low, high bracket)
END_MIN_SENSOR_DAYS = 6          # sensor-days with data required after the last detection before ENDED
MAX_RANGE_DAYS = 400
STATUSES = ("DETECTED", "ACTIVE", "POSSIBLY_INACTIVE", "ENDED", "MERGED", "SPLIT", "UNVERIFIED")
FAMILY = {"Terra": "MODIS", "Aqua": "MODIS", "Suomi NPP": "VIIRS", "NOAA-20": "VIIRS", "NOAA-21": "VIIRS"}


# --------------------------------------------------------------------------- inputs
def load_detections(start, end, bbox=None) -> pd.DataFrame:
    """Original detections (vegetation fires and untyped NRT rows) with a stable observation key."""
    import pyarrow.dataset as pads
    from .ingest import hotspot_dataset
    ds = hotspot_dataset()
    cols = ["latitude", "longitude", "acq_date", "timestamp_utc", "satellite", "product_type", "confidence_class",
            "confidence_score", "frp_mw", "daynight", "scan", "track", "anomaly_type", "source_kind", "source_file", "cell_id"]
    if ds is None:
        return pd.DataFrame(columns=cols + ["obs_key"])
    f = (pads.field("acq_date") >= pd.Timestamp(start).date()) & (pads.field("acq_date") <= pd.Timestamp(end).date())
    if bbox:
        w, s, e, n = bbox
        f &= (pads.field("longitude") >= w) & (pads.field("longitude") <= e) & (pads.field("latitude") >= s) & (pads.field("latitude") <= n)
    df = ds.to_table(filter=f, columns=cols).to_pandas()
    df = df[df["anomaly_type"].isna() | (df["anomaly_type"] == 0)]
    # NRT rows duplicate archive rows once the archive catches up: keep the archive record.
    df = df.sort_values("source_kind").drop_duplicates(["satellite", "product_type", "latitude", "longitude", "timestamp_utc"], keep="first")
    df = df.sort_values("timestamp_utc", kind="stable").reset_index(drop=True)
    df["obs_key"] = obs_keys(df)
    return df


def obs_keys(df: pd.DataFrame) -> np.ndarray:
    """Stable id of one original detection: platform, product, position and acquisition time."""
    txt = (df["satellite"].astype(str) + "|" + df["product_type"].astype(str) + "|" + df["latitude"].round(5).astype(str) + "|"
           + df["longitude"].round(5).astype(str) + "|" + pd.to_datetime(df["timestamp_utc"]).dt.strftime("%Y%m%dT%H%M"))
    return np.array([hashlib.sha1(t.encode()).hexdigest()[:16] for t in txt])


def _xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.c_[R_EARTH * np.cos(la) * np.cos(lo), R_EARTH * np.cos(la) * np.sin(lo), R_EARTH * np.sin(la)]


def _radius_km(df: pd.DataFrame) -> np.ndarray:
    nominal = pd.Series(np.where(df["satellite"].map(FAMILY).eq("VIIRS") & ~df["product_type"].astype(str).eq("750m"), 0.375,
                                 np.where(df["product_type"].astype(str).eq("750m"), 0.75, 1.0)), index=df.index)
    scan = df["scan"].astype(float).fillna(nominal)
    track = df["track"].astype(float).fillna(scan)
    return 0.5 * np.sqrt(scan.to_numpy() ** 2 + track.to_numpy() ** 2)


def _persistence(df: pd.DataFrame) -> np.ndarray:
    from . import store
    lu = store.cells().set_index("cell_id")["land_use"] if store.has_data() else pd.Series(dtype=str)
    return df["cell_id"].map(lu).map(PERSISTENCE_DAYS).fillna(DEFAULT_PERSISTENCE).to_numpy(float)


# --------------------------------------------------------------------------- clustering
def link(df: pd.DataFrame, persistence: np.ndarray | None = None) -> np.ndarray:
    """Connected-component label per detection (see module docstring for the edge rule)."""
    n = len(df)
    if n == 0:
        return np.zeros(0, int)
    t = pd.to_datetime(df["timestamp_utc"]).to_numpy("datetime64[s]").astype("int64") / 86400.0
    order = np.argsort(t, kind="stable")
    if not np.all(order == np.arange(n)):
        raise ValueError("detections must be sorted by timestamp_utc")
    xyz = _xyz(df["latitude"].to_numpy(float), df["longitude"].to_numpy(float))
    r = _radius_km(df)
    p = _persistence(df) if persistence is None else persistence
    pmax = float(p.max())
    day = np.floor(t).astype(int)
    rows, cols = [], []
    starts = np.searchsorted(day, np.unique(day))
    uniq = np.unique(day)
    for k, d0 in enumerate(uniq):
        a = starts[k]
        b = starts[k + 1] if k + 1 < len(uniq) else n
        w0 = np.searchsorted(t, d0 - pmax - 1e-9)          # window: everything within pmax days before this day
        if b - a == 0:
            continue
        tree_new = cKDTree(xyz[a:b])
        tree_win = cKDTree(xyz[w0:b])
        rmax = float(r[a:b].max() + r[w0:b].max())
        pairs = tree_new.sparse_distance_matrix(tree_win, rmax, output_type="ndarray")
        if len(pairs) == 0:
            continue
        i = pairs["i"] + a
        j = pairs["j"] + w0
        keep = (j < i) & (pairs["v"] <= r[i] + r[j]) & (np.abs(t[i] - t[j]) <= np.minimum(p[i], p[j]) + 1e-9)
        rows.append(i[keep])
        cols.append(j[keep])
    if rows:
        ri, ci = np.concatenate(rows), np.concatenate(cols)
    else:
        ri = ci = np.zeros(0, int)
    g = coo_matrix((np.ones(len(ri), np.int8), (ri, ci)), shape=(n, n))
    _, labels = connected_components(g, directed=False)
    return labels


# --------------------------------------------------------------------------- event attributes
def arrays(df: pd.DataFrame) -> dict:
    """Column arrays used by `summarise` (numpy, computed once per run)."""
    ctx = context()
    sats = df["satellite"].astype(str).to_numpy()
    conf = df["confidence_class"].fillna("unknown").astype(str).to_numpy()
    return {
        "t": pd.to_datetime(df["timestamp_utc"]).to_numpy("datetime64[s]").astype("int64"),
        "lat": df["latitude"].to_numpy(float), "lon": df["longitude"].to_numpy(float),
        "scan": df["scan"].astype(float).fillna(1.0).to_numpy(), "track": df["track"].astype(float).fillna(1.0).to_numpy(),
        "frp": df["frp_mw"].astype(float).to_numpy(), "conf": conf, "score": df["confidence_score"].astype(float).to_numpy(),
        "sat": sats, "fam": np.array([FAMILY.get(x, x) for x in sats]), "dn": df["daynight"].astype(str).to_numpy(),
        "lu": df["cell_id"].map(ctx["land_use"]).to_numpy(object), "state": df["cell_id"].map(ctx["state"]).to_numpy(object),
        "district": df["cell_id"].map(ctx["district_id"]).to_numpy(object),
    }


def _hull(x, y):
    import shapely
    return shapely.convex_hull(shapely.multipoints(np.c_[x, y]))


def _corners(lat, lon, scan, track):
    """Pixel-extent corner points (lon, lat) and local km scale factors."""
    lat0 = float(lat.mean())
    kx, ky = 111.32 * math.cos(math.radians(lat0)), 110.57
    sx, sy = scan / 2 / kx, track / 2 / ky
    return (np.concatenate([lon - sx, lon + sx, lon + sx, lon - sx]),
            np.concatenate([lat - sy, lat - sy, lat + sy, lat + sy]), kx, ky)


def _bearing(lat1, lon1, lat2, lon2):
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1)))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _haversine(lat1, lon1, lat2, lon2):
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * R_EARTH * math.asin(math.sqrt(a))


def fre_mj(t: np.ndarray, sat: np.ndarray, frp: np.ndarray, isolated_h: float) -> float | None:
    """EXPERIMENTAL fire radiative energy (MJ): time-integration of per-overpass total FRP.

    Overpasses (platform + time) up to 24 h apart are joined trapezoidally; a side with no neighbouring pass within
    24 h is credited `isolated_h` hours. Polar orbiters see 2-8 snapshots a day and miss the diurnal peak, so the
    unobserved duration dominates the uncertainty: callers bracket it (FRE_ISOLATED_H) instead of assuming one value."""
    ok = ~np.isnan(frp)
    if not ok.any():
        return None
    keys = np.char.add(sat[ok].astype(str), t[ok].astype(str))
    _, inv = np.unique(keys, return_inverse=True)
    v = np.bincount(inv, weights=frp[ok])
    tp = np.zeros(len(v))
    tp[inv] = t[ok]
    o = np.argsort(tp, kind="stable")
    tp, v = tp[o], v[o]
    gaps = np.diff(tp)
    left, right = np.r_[np.inf, gaps], np.r_[gaps, np.inf]
    iso = isolated_h * 3600
    wl = np.where(left <= 86400, left / 2, iso)
    wr = np.where(right <= 86400, right / 2, iso)
    return float((v * (wl + wr)).sum())  # MW * s = MJ


def _mode(a: np.ndarray):
    a = a[pd.notna(a)]
    if not len(a):
        return None
    u, c = np.unique(a.astype(str), return_counts=True)
    return str(u[np.argmax(c)])


def context() -> dict:
    """Cell lookups used to attach land cover / state / district to events."""
    from . import store
    if not store.has_data():
        return {"land_use": {}, "state": {}, "district_id": {}}
    c = store.cells().set_index("cell_id")
    return {k: c[k].to_dict() for k in ("land_use", "state", "district_id")}


def summarise(idx: np.ndarray, A: dict, data_through: pd.Timestamp, sensor_days_after) -> dict:
    """Attributes of one event; idx = row indices of its detections (time-sorted) into the arrays A."""
    t, lat, lon, frp = A["t"][idx], A["lat"][idx], A["lon"][idx], A["frp"][idx]
    sat, conf = A["sat"][idx], A["conf"][idx]
    n = len(idx)
    first, last = pd.Timestamp(int(t[0]), unit="s"), pd.Timestamp(int(t[-1]), unit="s")
    cx, cy, kx, ky = _corners(lat, lon, A["scan"][idx], A["track"][idx])
    poly = _hull(cx, cy)
    area_hi = poly.area * kx * ky
    area_lo = _hull(lon, lat).area * kx * ky if n > 2 else 0.0
    us, cs = np.unique(sat, return_counts=True)
    sats = {str(a): int(b) for a, b in zip(us, cs)}
    fams = sorted(set(A["fam"][idx].tolist()))
    lu, state, district = _mode(A["lu"][idx]), _mode(A["state"][idx]), _mode(A["district"][idx])
    persistence = PERSISTENCE_DAYS.get(lu, DEFAULT_PERSISTENCE)
    day = t // 86400
    udays = np.unique(day)
    daily = []
    for d in udays:
        m = day == d
        m4, up4 = np.tile(m, 4), np.tile(day <= d, 4)
        fd = frp[m]
        daily.append({"date": pd.Timestamp(int(d) * 86400, unit="s").date().isoformat(), "detections": int(m.sum()),
                      "sensors": sorted(set(sat[m].tolist())),
                      "frp_sum_mw": float(np.nansum(fd)), "frp_max_mw": float(np.nanmax(fd)) if np.isfinite(fd).any() else 0.0,
                      "footprint_km2": round(_hull(cx[m4], cy[m4]).area * kx * ky, 3),
                      "cumulative_footprint_km2": round(_hull(cx[up4], cy[up4]).area * kx * ky, 3),
                      "lat": float(lat[m].mean()), "lon": float(lon[m].mean())})
    d0, d1 = daily[0], daily[-1]
    span_days = int(udays[-1] - udays[0])
    move_km = _haversine(d0["lat"], d0["lon"], d1["lat"], d1["lon"]) if span_days else 0.0
    gap_days = (data_through - last).total_seconds() / 86400
    opp = sensor_days_after(last)
    if gap_days <= 1:
        status = "DETECTED" if (len(daily) == 1 and n <= 2) else "ACTIVE"
    elif gap_days > persistence + 2 and opp >= END_MIN_SENSOR_DAYS:
        status = "ENDED"
    else:
        status = "POSSIBLY_INACTIVE"
    if bool((conf == "low").all()) and len(fams) == 1 and status in ("DETECTED", "ACTIVE"):
        status = "UNVERIFIED"
    multi_days = sum(len(x["sensors"]) > 1 for x in daily)
    score = A["score"][idx]
    uc, cc = np.unique(conf, return_counts=True)
    has_frp = bool(np.isfinite(frp).any())
    return {
        "first_detection": first.to_pydatetime(), "last_detection": last.to_pydatetime(),
        "est_start_earliest": (first - pd.Timedelta(hours=REVISIT_H)).to_pydatetime(),
        "est_end_latest": None if status != "ENDED" else (last + pd.Timedelta(hours=REVISIT_H)).to_pydatetime(),
        "n_obs": int(n), "n_days": len(daily), "platforms": sats, "sensor_families": fams,
        "lat": float(lat.mean()), "lon": float(lon.mean()),
        "west": float(lon.min()), "south": float(lat.min()), "east": float(lon.max()), "north": float(lat.max()),
        "footprint_km2": round(area_hi, 4), "footprint_centres_km2": round(area_lo, 4),
        "footprint_geojson": {"type": "Polygon", "coordinates": [[[round(x, 5), round(y, 5)] for x, y in poly.exterior.coords]]},
        "peak_frp_mw": float(np.nanmax(frp)) if has_frp else None, "sum_frp_mw": float(np.nansum(frp)),
        "fre_mj_low": fre_mj(t, sat, frp, FRE_ISOLATED_H[0]), "fre_mj_high": fre_mj(t, sat, frp, FRE_ISOLATED_H[1]),
        "confidence_mean": float(np.nanmean(score)) if np.isfinite(score).any() else None,
        "confidence_counts": {str(a): int(b) for a, b in zip(uc, cc)},
        "evidence": ("multi-sensor" if len(sats) > 1 else "single-sensor") + (", multi-day" if len(daily) > 1 else ", single-day"),
        "multi_sensor_day_share": round(multi_days / len(daily), 3),
        "land_use": lu, "state": state, "district_id": district,
        "day_count": int((A["dn"][idx] == "D").sum()), "night_count": int((A["dn"][idx] == "N").sum()),
        "status": status, "gap_days": round(gap_days, 2), "sensor_days_since_last": int(opp),
        "end_basis": (f"no detection for {gap_days:.1f} d (> persistence {persistence:g} d + 2) with {opp} sensor-days of data since; "
                      "FIRMS has no cloud mask, so obscured burning cannot be excluded") if status == "ENDED" else None,
        "growth": {"span_days": span_days, "apparent_movement_km": round(move_km, 3),
                   "apparent_bearing_deg": round(_bearing(d0["lat"], d0["lon"], d1["lat"], d1["lon"]), 1) if move_km > 0 else None,
                   "footprint_growth_km2_per_day": round((d1["cumulative_footprint_km2"] - d0["footprint_km2"]) / span_days, 4) if span_days else None,
                   "note": "Derived from detection footprints (observation geometry), not from a mapped fire perimeter."},
        "timeline": daily,
    }


# --------------------------------------------------------------------------- identity reconciliation
def _new_id(first_ts: pd.Timestamp, key: str) -> str:
    return f"FE-{first_ts:%Y%m%d}-{key[:8]}"


def reconcile(df: pd.DataFrame, labels: np.ndarray, prior: pd.DataFrame) -> tuple[dict, list[dict]]:
    """Map component label -> event_id given prior obs_key -> event_id associations. Returns (mapping, history).

    * component holding no prior observations -> new id (derived from its first observation)
    * prior event whose observations all fall in one component -> continuation (id kept)
    * several prior events in one component -> MERGED into the earliest; the others record merged_into
    * a prior event spread over several components -> the component with most of its observations keeps the id,
      the others get new ids with history SPLIT (split_from = prior id)."""
    prior_map = dict(zip(prior["obs_key"], prior["event_id"])) if len(prior) else {}
    prior_first = prior.groupby("event_id")["first_ts"].min().to_dict() if len(prior) else {}
    pe = df["obs_key"].map(prior_map).to_numpy(object)
    first_idx = pd.Series(np.arange(len(labels))).groupby(labels).min()          # labels -> first row (time-sorted)
    hist, mapping = [], {}
    has = pd.notna(pe)
    holder = pd.DataFrame({"label": labels[has], "prior": pe[has]}).groupby(["prior", "label"]).size().reset_index(name="n")
    keep = holder.sort_values(["prior", "n", "label"], ascending=[True, False, True]).drop_duplicates("prior")
    owner = dict(zip(keep["prior"], keep["label"]))                               # prior id -> component keeping it
    priors_in = holder.groupby("label")["prior"].apply(list).to_dict()            # component -> prior ids present
    for comp, idx in first_idx.items():
        present = priors_in.get(comp, [])
        kept = [p for p in present if owner.get(p) == comp]
        if not kept:
            new = _new_id(pd.Timestamp(df["timestamp_utc"].iat[idx]), df["obs_key"].iat[idx])
            mapping[comp] = new
            for par in present:
                hist.append({"event_id": new, "action": "SPLIT", "related_event_id": par,
                             "detail": {"note": "observations split off from an existing event"}})
            continue
        survivor = sorted(kept, key=lambda i: (prior_first.get(i), i))[0]
        mapping[comp] = survivor
        for other in kept:
            if other != survivor:
                hist.append({"event_id": other, "action": "MERGED", "related_event_id": survivor,
                             "detail": {"note": f"merged into {survivor}"}})
    return mapping, hist


# --------------------------------------------------------------------------- run
def _sensor_day_counter(df: pd.DataFrame, data_through: pd.Timestamp):
    """Sensor-days that delivered data (any detection in the window by that platform) - an observation-opportunity proxy."""
    t = pd.to_datetime(df["timestamp_utc"]).to_numpy("datetime64[s]").astype("int64") // 86400
    pairs = np.unique(np.c_[pd.factorize(df["satellite"])[0], t], axis=0)
    days = np.sort(pairs[:, 1])

    def count_after(ts):
        d = int(pd.Timestamp(ts).value // 10**9 // 86400)
        return int(len(days) - np.searchsorted(days, d, side="right"))
    return count_after


def build(start, end, bbox=None, log=print, persist: bool = True, progress=None) -> dict:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    if e < s:
        raise ValueError("start must be <= end")
    if (e - s).days > MAX_RANGE_DAYS:
        raise ValueError(f"range limited to {MAX_RANGE_DAYS} days per run")
    lead = pd.Timedelta(days=max(PERSISTENCE_DAYS.values()) + 1)
    t0 = datetime.now(timezone.utc)
    df = load_detections(s - lead, e, bbox)
    log(f"{len(df):,} vegetation-fire detections loaded")
    if df.empty:
        return {"events": 0, "detections": 0, "note": "no detections in range"}
    labels = link(df)
    data_through = pd.to_datetime(df["timestamp_utc"]).max()
    prior = associations()
    mapping, hist = reconcile(df, labels, prior)
    counter = _sensor_day_counter(df, data_through)
    A = arrays(df)
    ev_rows = []
    order = np.argsort(labels, kind="stable")
    bounds = np.r_[0, np.flatnonzero(np.diff(labels[order])) + 1, len(order)]
    for k in range(len(bounds) - 1):
        idx = order[bounds[k]:bounds[k + 1]]
        idx = np.sort(idx)
        if A["t"][idx[-1]] < s.value // 10**9:      # entirely inside the lead-in window
            continue
        att = summarise(idx, A, data_through, counter)
        att["event_id"] = mapping[labels[idx[0]]]
        att["truncated_start"] = bool(A["t"][idx[0]] < s.value // 10**9)
        ev_rows.append(att)
        if progress and k % 5000 == 0:
            progress(f"summarised {k:,} of {len(bounds) - 1:,} components")
    assoc = pd.DataFrame({"obs_key": df["obs_key"], "event_id": [mapping[l] for l in labels],
                          "satellite": df["satellite"].astype(str), "timestamp_utc": pd.to_datetime(df["timestamp_utc"]),
                          "latitude": df["latitude"], "longitude": df["longitude"], "frp_mw": df["frp_mw"],
                          "confidence_class": df["confidence_class"], "source_file": df["source_file"].astype(str)})
    kept = {r["event_id"] for r in ev_rows}
    assoc = assoc[assoc["event_id"].isin(kept)]
    result = {"run_at": t0.isoformat(timespec="seconds"), "method": METHOD_VERSION, "start": s.date().isoformat(), "end": e.date().isoformat(),
              "bbox": bbox, "detections": int(len(df)), "events": len(ev_rows), "data_through": data_through.isoformat(),
              "status_counts": pd.Series([r["status"] for r in ev_rows]).value_counts().to_dict(),
              "multi_sensor_events": int(sum(len(r["platforms"]) > 1 for r in ev_rows)),
              "single_detection_events": int(sum(r["n_obs"] == 1 for r in ev_rows)),
              "history_entries": len(hist), "seconds": round((datetime.now(timezone.utc) - t0).total_seconds(), 1),
              "parameters": {"persistence_days": PERSISTENCE_DAYS, "default_persistence_days": DEFAULT_PERSISTENCE,
                             "link_distance": "r_i + r_j, r = 0.5*sqrt(scan^2+track^2) km", "end_min_sensor_days": END_MIN_SENSOR_DAYS,
                             "excluded": "FIRMS type 1 (volcano), 2 (static/industrial), 3 (offshore)"}}
    if persist:
        _persist(ev_rows, assoc, hist, prior, result)
    log(json.dumps({k: v for k, v in result.items() if k != "parameters"}, default=str))
    return result


def _persist(ev_rows: list[dict], assoc: pd.DataFrame, hist: list[dict], prior: pd.DataFrame, result: dict):
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    new_keys = set(assoc["obs_key"])
    keep_prior = prior[~prior["obs_key"].isin(new_keys)] if len(prior) else prior
    merged_away = {h["event_id"] for h in hist if h["action"] == "MERGED"}
    out = pd.concat([keep_prior.drop(columns=["first_ts"], errors="ignore"), assoc], ignore_index=True)
    if merged_away:
        out = out[~out["event_id"].isin(merged_away)]
    out.to_parquet(ASSOC, index=False)
    ids = [r["event_id"] for r in ev_rows]
    with M.Session() as s:
        existing = {e.event_id: e for e in s.scalars(select(M.FireEvent).where(M.FireEvent.event_id.in_(ids + list(merged_away))))}
        for r in ev_rows:
            ev = existing.get(r["event_id"])
            is_new = ev is None
            if is_new:
                ev = M.FireEvent(event_id=r["event_id"])
                s.add(ev)
            prev_status, prev_n = (None, None) if is_new else (ev.status, ev.n_obs)
            for k, v in r.items():
                if k != "event_id":
                    setattr(ev, k, v)
            ev.method = METHOD_VERSION
            ev.updated_at = M.now()
            if is_new:
                s.add(M.FireEventHistory(event_id=r["event_id"], action="CREATED", detail={"n_obs": r["n_obs"], "status": r["status"]}))
            elif prev_n != r["n_obs"] or prev_status != r["status"]:
                s.add(M.FireEventHistory(event_id=r["event_id"], action="UPDATED",
                                         detail={"n_obs": [prev_n, r["n_obs"]], "status": [prev_status, r["status"]]}))
        for h in hist:
            if h["action"] == "MERGED" and h["event_id"] in existing:
                existing[h["event_id"]].status = "MERGED"
                existing[h["event_id"]].merged_into = h["related_event_id"]
            if h["action"] == "SPLIT":
                child = next((e for e in s.new if isinstance(e, M.FireEvent) and e.event_id == h["event_id"]), None)
                if child is not None:
                    child.split_from = h["related_event_id"]
            s.add(M.FireEventHistory(**h))
        s.commit()
    runs = json.loads(RUNS.read_text()) if RUNS.exists() else []
    runs.append(result)
    RUNS.write_text(json.dumps(runs[-50:], indent=1, default=str))


def associations() -> pd.DataFrame:
    if not ASSOC.exists():
        return pd.DataFrame(columns=["obs_key", "event_id", "first_ts"])
    a = pd.read_parquet(ASSOC)
    a["first_ts"] = a.groupby("event_id")["timestamp_utc"].transform("min")
    return a


# --------------------------------------------------------------------------- queries
SUMMARY_FIELDS = ("event_id", "status", "first_detection", "last_detection", "n_obs", "n_days", "platforms", "lat", "lon",
                  "footprint_km2", "peak_frp_mw", "sum_frp_mw", "confidence_mean", "evidence", "land_use", "state", "district_id",
                  "merged_into", "split_from", "truncated_start")


def _view(e: M.FireEvent, full: bool = False) -> dict:
    iso = lambda d: d.isoformat() + "Z" if d else None
    d = {k: getattr(e, k) for k in SUMMARY_FIELDS}
    d["first_detection"], d["last_detection"] = iso(e.first_detection), iso(e.last_detection)
    if full:
        for k in ("est_start_earliest", "est_end_latest", "updated_at"):
            d[k] = iso(getattr(e, k))
        for k in ("sensor_families", "west", "south", "east", "north", "footprint_centres_km2", "footprint_geojson", "fre_mj_low", "fre_mj_high",
                  "confidence_counts", "multi_sensor_day_share", "day_count", "night_count", "gap_days", "sensor_days_since_last",
                  "end_basis", "growth", "method", "timeline"):
            d[k] = getattr(e, k)
        d["interpretation"] = {
            "footprint": "Hull of detected pixel extents (observation footprint), NOT a fire perimeter or burned area.",
            "sum_frp_mw": "Sum of instantaneous FRP over all detections (MW). Not energy; overlapping sensors are summed.",
            "fre_mj_low/high": "EXPERIMENTAL time-integrated FRP bracket: isolated overpasses credited 0.5 h vs 6 h of burning each side.",
            "status": "No CONTAINED status exists: containment needs official incident data.",
            "validation": "NOT INDEPENDENTLY VALIDATED against official incident records (none available to PyroScope).",
        }
    return d


def query(start=None, end=None, status=None, state=None, region_id=None, min_obs: int = 1, bbox=None,
          limit: int = 100, offset: int = 0, sort: str = "last_detection") -> dict:
    from . import store
    q = select(M.FireEvent).where(M.FireEvent.n_obs >= min_obs)
    if start:
        q = q.where(M.FireEvent.last_detection >= pd.Timestamp(start).to_pydatetime())
    if end:
        q = q.where(M.FireEvent.first_detection < (pd.Timestamp(end) + pd.Timedelta(days=1)).to_pydatetime())
    if status:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        q = q.where(M.FireEvent.status == status)
    if state:
        q = q.where(M.FireEvent.state == state)
    if region_id:
        cells, _ = store.region_cells(region_id)
        w, s_, e_, n = store.region_bbox(region_id)
        q = q.where(M.FireEvent.lon >= w, M.FireEvent.lon <= e_, M.FireEvent.lat >= s_, M.FireEvent.lat <= n)
    if bbox:
        w, s_, e_, n = bbox
        q = q.where(M.FireEvent.lon >= w, M.FireEvent.lon <= e_, M.FireEvent.lat >= s_, M.FireEvent.lat <= n)
    col = {"last_detection": M.FireEvent.last_detection.desc(), "n_obs": M.FireEvent.n_obs.desc(),
           "peak_frp": M.FireEvent.peak_frp_mw.desc(), "footprint": M.FireEvent.footprint_km2.desc()}.get(sort)
    if col is None:
        raise ValueError("sort must be last_detection | n_obs | peak_frp | footprint")
    from sqlalchemy import func
    with M.Session() as s:
        total = s.scalar(select(func.count()).select_from(q.subquery()))
        rows = s.scalars(q.order_by(col, M.FireEvent.event_id).limit(min(limit, 1000)).offset(offset)).all()
        return {"total": total, "limit": limit, "offset": offset, "items": [_view(e) for e in rows]}


def get(event_id: str) -> dict:
    with M.Session() as s:
        e = s.scalar(select(M.FireEvent).where(M.FireEvent.event_id == event_id))
        if e is None:
            raise KeyError(f"event {event_id} not found")
        d = _view(e, full=True)
        d["history"] = [{"action": h.action, "related_event_id": h.related_event_id, "detail": h.detail, "at": h.at.isoformat() + "Z"}
                        for h in s.scalars(select(M.FireEventHistory).where(M.FireEventHistory.event_id == event_id).order_by(M.FireEventHistory.id))]
        return d


def timeline(event_id: str) -> dict:
    with M.Session() as s:
        e = s.scalar(select(M.FireEvent).where(M.FireEvent.event_id == event_id))
        if e is None:
            raise KeyError(f"event {event_id} not found")
        return {"event_id": event_id, "timeline": e.timeline, "growth": e.growth}


def observations(event_id: str, limit: int = 2000, offset: int = 0) -> dict:
    get(event_id)
    a = associations()
    a = a[a["event_id"] == event_id].sort_values("timestamp_utc")
    page = a.iloc[offset:offset + min(limit, 5000)].drop(columns=["first_ts"], errors="ignore")
    return {"event_id": event_id, "total": int(len(a)), "items": page.to_dict("records"),
            "note": "Original FIRMS detections linked to this event (raw records are unchanged; obs_key identifies each)."}


def status_summary() -> dict:
    from sqlalchemy import func
    with M.Session() as s:
        counts = dict(s.execute(select(M.FireEvent.status, func.count()).group_by(M.FireEvent.status)).all())
        n = sum(counts.values())
    runs = json.loads(RUNS.read_text()) if RUNS.exists() else []
    return {"events": n, "status_counts": counts, "last_run": runs[-1] if runs else None, "method": METHOD_VERSION,
            "validation": "NOT INDEPENDENTLY VALIDATED: no official incident records are available; import them via /api/external-validation."}


def clear_all():
    with M.Session() as s:
        s.execute(delete(M.FireEventHistory))
        s.execute(delete(M.FireEvent))
        s.commit()
    for p in (ASSOC, RUNS):
        if p.exists():
            p.unlink()
