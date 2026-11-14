"""NASA POWER daily meteorology on a 1-degree node lattice (cached).

Parameters: T2M_MAX (deg C), PRECTOTCORR (mm/day), RH2M (%), WS2M (m/s),
GWETTOP (surface soil wetness 0-1, used as a vegetation/fuel dryness proxy) and
CLOUD_AMT (%, CERES; lags several months so it is only used for history).
Each 0.25 deg cell uses its enclosing 1 deg node. Missing values stay missing.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

from .config import AUX, PROCESSED

PARAMS = ["T2M_MAX", "PRECTOTCORR", "RH2M", "WS2M", "GWETTOP", "CLOUD_AMT"]
COLS = ["t2m_max", "precip", "rh", "wind", "soil_wet", "cloud"]
URL = ("https://power.larc.nasa.gov/api/temporal/daily/point?parameters={p}&community=AG"
       "&longitude={lon}&latitude={lat}&start={s}&end={e}&format=JSON")
CACHE = AUX / "power"
WEATHER_PATH = PROCESSED / "weather.parquet"


def node_of(lat, lon):
    """1-degree node id for coordinates (node centre at x.5, y.5)."""
    la = np.floor(np.asarray(lat, dtype="float64")).astype("int32")
    lo = np.floor(np.asarray(lon, dtype="float64")).astype("int32")
    return (la + 90) * 360 + (lo + 180)


def node_center(node):
    node = np.asarray(node)
    return node // 360 - 90 + 0.5, node % 360 - 180 + 0.5


def _fetch(node: int, start: str, end: str):
    out = CACHE / f"{node}_{start}_{end}.parquet"
    if out.exists():
        return True
    lat, lon = node_center(node)
    url = URL.format(p=",".join(PARAMS), lat=float(lat), lon=float(lon), s=start, e=end)
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=120)
            if r.status_code == 200:
                par = r.json()["properties"]["parameter"]
                df = pd.DataFrame({c: pd.Series(par.get(p, {}), dtype="float32") for p, c in zip(PARAMS, COLS)})
                df = df.replace(-999.0, np.nan)
                df.index = pd.to_datetime(df.index, format="%Y%m%d")
                df.index.name = "date"
                df.reset_index().assign(node=np.int32(node)).to_parquet(out, index=False)
                return True
            if r.status_code in (422, 404):
                return False
        except Exception:
            pass
        time.sleep(3 * (attempt + 1))
    return False


def fetch_all(start="20120101", end="20261031", workers=5):
    cells = pd.read_parquet(PROCESSED / "cells.parquet")
    cells = cells[cells["in_country"]]
    nodes = np.unique(node_of(cells["lat"], cells["lon"]))
    CACHE.mkdir(parents=True, exist_ok=True)
    print(f"[weather] {len(nodes)} nodes, {start}..{end}", flush=True)
    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for ok in ex.map(lambda n: _fetch(int(n), start, end), nodes):
            done += 1
            if done % 25 == 0:
                print(f"[weather] {done}/{len(nodes)}", flush=True)
    files = sorted(CACHE.glob(f"*_{start}_{end}.parquet"))
    if not files:
        print("[weather] nothing downloaded")
        return None
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df.to_parquet(WEATHER_PATH, index=False)
    print(f"[weather] wrote {len(df):,} rows for {df['node'].nunique()} / {len(nodes)} nodes", flush=True)
    return df


if __name__ == "__main__":
    fetch_all(*sys.argv[1:3]) if len(sys.argv) >= 3 else fetch_all()
