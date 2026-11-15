"""Precomputed summaries + in-memory access layer used by the analytics and the API."""
from __future__ import annotations

import json
import os
from functools import lru_cache

import numpy as np
import pandas as pd

from . import grid
from .config import PROCESSED, SATELLITES
from .ingest import AGG_DIR, regroup_daily

DAILY = PROCESSED / "daily_cell.parquet"
MONTHLY = PROCESSED / "monthly_cell.parquet"
SPANS = PROCESSED / "spans.json"
LST = PROCESSED / "lst_hist.parquet"
OUTSIDE = "Outside mapped boundaries"
DN = {"D": 0, "N": 1, "U": 0}


def _atomic_parquet(df: pd.DataFrame, path):
    """Write beside the target and rename, so readers never see a partially written summary."""
    tmp = path.with_name(f".{path.name}.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def build_summaries(log=print) -> dict:
    """Combine per-source daily aggregates into the stores every dashboard reads."""
    files = [f for f in AGG_DIR.glob("*.parquet") if not f.name.endswith(".lst.parquet")]
    if not files:
        raise RuntimeError("no processed sources; run ingestion first")
    daily = regroup_daily(pd.concat([pd.read_parquet(f) for f in files], ignore_index=True))
    daily = daily.sort_values(["acq_date", "cell_id"]).reset_index(drop=True)
    daily["satellite"] = daily["satellite"].astype("category")
    daily["daynight"] = daily["daynight"].astype("category")
    _atomic_parquet(daily, DAILY)
    log(f"[store] daily_cell rows: {len(daily):,}")

    d = daily.assign(ym=daily["acq_date"].dt.year * 100 + daily["acq_date"].dt.month)
    keys = ["ym", "cell_id", "satellite", "daynight"]
    agg = {c: "sum" for c in d.columns if c not in keys + ["acq_date"]}
    agg["frp_max"] = "max"
    monthly = d.groupby(keys, observed=True).agg(agg).reset_index()
    monthly["days"] = d.groupby(keys, observed=True)["acq_date"].nunique().to_numpy()
    _atomic_parquet(monthly, MONTHLY)
    log(f"[store] monthly_cell rows: {len(monthly):,}")

    nat = daily.groupby(["satellite", "acq_date"], observed=True).agg(n=("n", "sum"), typed=("n_typed", "sum")).reset_index()
    spans = {}
    for sat, g in nat.groupby("satellite", observed=True):
        first, last = g["acq_date"].min(), g["acq_date"].max()
        all_days = pd.date_range(first, last, freq="D")
        zero = all_days.difference(pd.DatetimeIndex(g["acq_date"]))
        typed = g.loc[g["typed"] > 0, "acq_date"]
        # A long run of whole-domain zero-detection days is a sensor/data gap (missing).
        # Short runs are kept as observed days: cloud can genuinely suppress all detections.
        min_run = 5 if str(sat) in ("Terra", "Aqua") else 3
        zs = pd.Series(zero)
        run = (zs.diff().dt.days != 1).cumsum()
        gaps = zs[run.map(run.value_counts()) >= min_run] if len(zs) else zs
        spans[str(sat)] = {
            "gap_days": [str(x.date()) for x in gaps], "gap_rule_min_run_days": min_run,
            "first": str(first.date()), "last": str(last.date()), "days_in_span": len(all_days),
            "days_with_detections": int(len(g)), "zero_detection_days": [str(x.date()) for x in zero],
            "last_typed": str(typed.max().date()) if len(typed) else None, "detections": int(g["n"].sum()),
        }
    _tmp = SPANS.with_name(".spans.json.tmp")
    _tmp.write_text(json.dumps(spans, indent=1))
    os.replace(_tmp, SPANS)
    lst = [pd.read_parquet(f) for f in AGG_DIR.glob("*.lst.parquet")]
    if lst:
        pd.concat(lst).groupby(["satellite", "daynight", "lst_bin"]).n.sum().reset_index().to_parquet(LST, index=False)
    build_orbit_table(log)
    clear_caches()
    return spans


ORBIT = PROCESSED / "orbit_lst.parquet"
ORBIT_TOL_H = 0.25


def build_orbit_table(log=print):
    """Mean local solar time of day-time detections per satellite and year, measured from
    the records themselves. MODIS orbits are no longer maintained (Terra drifts earlier,
    Aqua later), which changes diurnal sampling; drifted years are excluded from calibration."""
    from .ingest import HOTSPOTS
    import pyarrow.dataset as pads
    parts = []
    for src in HOTSPOTS.iterdir():
        files = [str(f) for f in src.glob("*.parquet")]
        if not files:
            continue
        t = pads.dataset(files).to_table(columns=["timestamp_utc", "longitude", "satellite", "daynight"]).to_pandas()
        ts = t["timestamp_utc"]
        t["lst"] = (ts.dt.hour + ts.dt.minute / 60.0 + t["longitude"] / 15.0) % 24
        t["year"] = ts.dt.year
        parts.append(t[t["daynight"] == "D"].groupby(["satellite", "year"]).agg(lst_sum=("lst", "sum"), n=("lst", "size")).reset_index())
    o = pd.concat(parts).groupby(["satellite", "year"]).sum().reset_index()
    o["lst_day_mean"] = o["lst_sum"] / o["n"]
    base = o.sort_values("year").groupby("satellite").head(5).groupby("satellite")["lst_day_mean"].median()
    o["baseline"] = o["satellite"].map(base)
    o["drift_h"] = o["lst_day_mean"] - o["baseline"]
    o["stable"] = o["drift_h"].abs() <= ORBIT_TOL_H
    o.drop(columns="lst_sum").to_parquet(ORBIT, index=False)
    log("[store] orbit stability: " + str({s_: [int(y) for y in g.loc[~g["stable"], "year"]] for s_, g in o.groupby("satellite")}))
    return o


@lru_cache(maxsize=1)
def orbit() -> pd.DataFrame:
    return pd.read_parquet(ORBIT) if ORBIT.exists() else pd.DataFrame(columns=["satellite", "year", "n", "lst_day_mean", "baseline", "drift_h", "stable"])


def stable_years(sat: str) -> set:
    o = orbit()
    return set(int(y) for y in o.loc[(o["satellite"] == sat) & o["stable"], "year"])


# --------------------------------------------------------------------------- cached loaders
@lru_cache(maxsize=1)
def cells() -> pd.DataFrame:
    from .gis_layers import apply_overrides
    df = pd.read_parquet(PROCESSED / "cells.parquet")
    df["state"] = df["state"].fillna(OUTSIDE)
    return apply_overrides(df.set_index("cell_id", drop=False))   # administrator jurisdiction layers win


@lru_cache(maxsize=1)
def daily() -> pd.DataFrame:
    return pd.read_parquet(DAILY)


@lru_cache(maxsize=1)
def monthly() -> pd.DataFrame:
    return pd.read_parquet(MONTHLY)


@lru_cache(maxsize=1)
def spans() -> dict:
    return json.loads(SPANS.read_text()) if SPANS.exists() else {}


@lru_cache(maxsize=1)
def districts() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / "districts.parquet")


@lru_cache(maxsize=1)
def states() -> list[str]:
    return sorted(s for s in cells()["state"].unique() if s != OUTSIDE) + [OUTSIDE]


def has_data() -> bool:
    """True only when every core artefact (daily/monthly summaries, spans, cells, districts) exists and validates."""
    from . import dataset
    return dataset.core_ready()


def clear_caches():
    from . import dataset
    dataset.clear_cache()
    for f in (cells, daily, monthly, spans, districts, states, month_axis, coverage, region_cells, cell_static, orbit):
        f.cache_clear()
    from .gis_layers import clear as _gclear
    _gclear()
    from . import operational
    operational.clear()


# --------------------------------------------------------------------------- time axis & coverage
@lru_cache(maxsize=1)
def month_axis() -> pd.PeriodIndex:
    sp = spans()
    if not sp:                      # no processed dataset: an empty axis, never a min() over nothing
        return pd.PeriodIndex([], freq="M")
    first = min(pd.Timestamp(v["first"]) for v in sp.values())
    last = max(pd.Timestamp(v["last"]) for v in sp.values())
    return pd.period_range(first, last, freq="M")


def ym_of(periods: pd.PeriodIndex) -> np.ndarray:
    return (periods.year * 100 + periods.month).to_numpy()


@lru_cache(maxsize=1)
def coverage() -> pd.DataFrame:
    """Per satellite x month: fraction of days inside the sensor's data span and outside
    identified sensor gaps (runs of whole-domain zero-detection days: >=5 days for MODIS,
    >=3 for VIIRS). Days outside the span or inside a gap are treated as NOT observed --
    never as zero fire activity. Shorter zero runs stay "observed": cloud can suppress every
    detection, which is flagged separately as possible obscuration. `typed` marks months fully covered by standard-processing
    files (FIRMS `type` present); NRT months are provisional."""
    ax = month_axis()
    out = {}
    for sat in SATELLITES + sorted(k for k in spans() if k not in SATELLITES):   # + product streams e.g. "Suomi NPP 750m"
        sp = spans().get(sat)
        if not sp:
            out[sat] = np.zeros(len(ax))
            out[sat + "|typed"] = np.zeros(len(ax), dtype=bool)
            continue
        days = pd.date_range(sp["first"], sp["last"], freq="D").difference(pd.DatetimeIndex(sp["gap_days"]))
        per = pd.Series(1, index=days.to_period("M")).groupby(level=0).sum()
        out[sat] = (per.reindex(ax, fill_value=0) / ax.days_in_month).to_numpy()
        lt = pd.Timestamp(sp["last_typed"]) if sp.get("last_typed") else pd.Timestamp("1900-01-01")
        out[sat + "|typed"] = (ax.end_time.normalize() <= lt)
    return pd.DataFrame(out, index=ax)


def sensor_available(sat: str, day) -> bool | None:
    sp = spans().get(sat)
    if not sp:
        return None
    d = str(pd.Timestamp(day).date())
    return sp["first"] <= d <= sp["last"] and d not in sp["gap_days"]


# --------------------------------------------------------------------------- regions
CUSTOM = PROCESSED / "custom_regions.json"


def custom_regions() -> dict:
    return json.loads(CUSTOM.read_text()) if CUSTOM.exists() else {}


def add_custom_region(name: str, geojson: dict) -> dict:
    """Store a drawn polygon as a region: the grid cells whose centres fall inside it."""
    import hashlib
    from .gis_layers import cells_in_geojson
    ids = cells_in_geojson(geojson)
    rid = hashlib.sha1(json.dumps(geojson, sort_keys=True).encode()).hexdigest()[:10]
    reg = custom_regions()
    reg[rid] = {"name": name[:120], "cell_ids": ids, "geojson": geojson}
    CUSTOM.write_text(json.dumps(reg))
    region_cells.cache_clear()
    return {"region_id": f"custom:{rid}", "name": name, "n_cells": len(ids),
            "rule": "grid cells (0.25 deg) whose centre lies inside the polygon; regional totals use exactly these cells"}

@lru_cache(maxsize=256)
def region_cells(region_id: str) -> tuple:
    """Resolve a region id to grid cells.
    country | state:<name> | district:<id> | bbox:w,s,e,n | cell:<id> | landuse:<class>"""
    c = cells()
    rid = (region_id or "country").strip()
    if rid in ("country", "IND", "all"):
        return tuple(c.index[c["in_country"]].tolist())
    kind, _, val = rid.partition(":")
    if kind == "state":
        return tuple(c.index[c["state"] == val].tolist())
    if kind == "district":
        return tuple(c.index[c["district_id"] == val].tolist())
    if kind == "landuse":
        return tuple(c.index[(c["land_use"] == val) & c["in_country"]].tolist())
    if kind == "cell":
        return (int(val),)
    if kind == "custom":
        reg = custom_regions()
        if val not in reg:
            raise ValueError(f"unknown custom region {val}")
        return tuple(int(x) for x in reg[val]["cell_ids"])
    if kind == "bbox":
        w, s, e, n = (float(x) for x in val.split(","))
        if e <= w or n <= s:
            raise ValueError("bbox must be west,south,east,north with east>west and north>south")
        return tuple(grid.cells_in_bbox(w, s, e, n).tolist())
    raise ValueError(f"unknown region id: {region_id}")


def region_label(region_id: str) -> str:
    rid = region_id or "country"
    kind, _, val = rid.partition(":")
    if rid in ("country", "IND", "all"):
        return "India"
    if kind == "state":
        return val
    if kind == "district":
        d = districts()
        row = d[d["district_id"] == val]
        return f"{row.iloc[0]['district']}, {row.iloc[0]['state']}" if len(row) else val
    if kind == "bbox":
        return f"Custom area ({val})"
    if kind == "custom":
        return custom_regions().get(val, {}).get("name", f"Custom polygon {val}")
    if kind == "cell":
        lat, lon = grid.cell_center(int(val))
        return f"Grid cell {val} ({float(lat):.3f}N, {float(lon):.3f}E)"
    return val


def region_bbox(region_id: str):
    ids = np.array(region_cells(region_id))
    if len(ids) == 0:
        return None
    w, s, e, n = grid.cell_bounds(ids)
    return [float(w.min()), float(s.min()), float(e.max()), float(n.max())]


def _subset(df: pd.DataFrame, region_id: str) -> pd.DataFrame:
    if region_id in (None, "", "country", "IND", "all"):
        return df
    return df[df["cell_id"].isin(np.array(region_cells(region_id), dtype="int32"))]


def region_monthly(region_id: str) -> pd.DataFrame:
    return _subset(monthly(), region_id)


def region_daily(region_id: str) -> pd.DataFrame:
    return _subset(daily(), region_id)


@lru_cache(maxsize=1)
def cell_static() -> pd.DataFrame:
    """Share of typed archive detections flagged as static land sources, per cell."""
    m = monthly().groupby("cell_id").agg(n=("n", "sum"), n_typed=("n_typed", "sum"), n_static=("n_static", "sum"))
    m["static_share"] = (m["n_static"] / m["n_typed"]).where(m["n_typed"] > 0)
    return m
