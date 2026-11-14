"""Auxiliary geography: administrative boundaries, land cover and the cell table.

Sources (all real, downloaded on demand and cached under data/auxiliary):
  * geoBoundaries gbOpen IND ADM1 / ADM2 (state, district polygons).
  * NASA GIBS WMS layer MODIS_Combined_L3_IGBP_Land_Cover_Type_Annual (MCD12Q1 IGBP).

The land-cover layer is sampled at 0.025 deg and summarised to per-cell class
fractions. The jurisdiction land-use class is a *prototype rule* over those
fractions; "Residential/Village" and "Industrial" cannot be derived from IGBP and
are only assigned from administrator- or organisation-supplied layers.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point, mapping, shape
from shapely.strtree import STRtree

from . import grid
from .config import AOI_BBOX, AUX, GRID_DEG, PROCESSED

GB_URL = "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/IND/{lvl}/geoBoundaries-IND-{lvl}_simplified.geojson"
GIBS_WMS = (
    "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1"
    "&LAYERS=MODIS_Combined_L3_IGBP_Land_Cover_Type_Annual&STYLES=&SRS=EPSG:4326"
    "&BBOX={w},{s},{e},{n}&WIDTH={px}&HEIGHT={py}&FORMAT=image/png&TIME=2022-01-01"
)
GIBS_CMAP = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_IGBP_Land_Cover_Type.xml"
LC_YEAR = 2022
LC_PX_DEG = 0.025

IGBP_GROUPS = {
    "forest": [1, 2, 3, 4, 5], "savanna": [8, 9], "shrub_grass": [6, 7, 10], "wetland": [11],
    "cropland": [12, 14], "urban": [13], "barren_snow": [15, 16], "water": [0, 17],
}
LAND_USE_CLASSES = ["Forest", "Agricultural", "Residential/Village", "Municipal/Urban", "Industrial", "Other"]

CELLS_PATH = PROCESSED / "cells.parquet"
STATES_GEOJSON = PROCESSED / "states.geojson"
DISTRICTS_INDEX = PROCESSED / "districts.parquet"


def _download(url: str, dest, timeout=180):
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def _load_features(level: str):
    path = AUX / "boundaries" / f"india_{level.lower()}.geojson"
    _download(GB_URL.format(lvl=level), path)
    with open(path, encoding="utf-8") as f:
        fc = json.load(f)
    out = []
    for ft in fc["features"]:
        g = shape(ft["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        out.append((ft["properties"], g))
    return out


def _landcover_fractions(cell_ids: np.ndarray) -> pd.DataFrame:
    """Per-cell IGBP group fractions from the GIBS image; NaN if unavailable."""
    from PIL import Image

    w, s, e, n = AOI_BBOX
    px = int(round((e - w) / LC_PX_DEG))
    py = int(round((n - s) / LC_PX_DEG))
    gdir = AUX / "gibs"
    try:
        img_path = _download(GIBS_WMS.format(w=w, s=s, e=e, n=n, px=px, py=py), gdir / "lc.png")
        cmap_path = _download(GIBS_CMAP, gdir / "colormap.xml")
    except Exception as exc:  # network unavailable -> land cover unknown, never guessed
        print(f"[geo] land cover unavailable: {exc}")
        return pd.DataFrame({"cell_id": cell_ids})
    rgb = np.asarray(Image.open(img_path).convert("RGB")).astype("int32")
    if rgb.shape[0] != py or rgb.shape[1] != px:
        print("[geo] unexpected land-cover image size", rgb.shape)
        return pd.DataFrame({"cell_id": cell_ids})
    code = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]
    lut = {}
    for m in re.finditer(r'rgb="(\d+),(\d+),(\d+)"[^>]*sourceValue="([\d,]+)"', cmap_path.read_text()):
        r_, g_, b_, sv = int(m[1]), int(m[2]), int(m[3]), int(m[4].split(",")[-1])
        lut[(r_ << 16) | (g_ << 8) | b_] = sv
    cls = np.full(code.shape, -1, dtype="int16")
    for k, v in lut.items():
        cls[code == k] = v
    print(f"[geo] land-cover pixels matched to IGBP legend: {(cls >= 0).mean():.1%}")
    k = int(round(GRID_DEG / LC_PX_DEG))
    ix, iy = grid.cell_ixiy(cell_ids)
    col0 = np.round((ix * GRID_DEG - 180.0 - w) / LC_PX_DEG).astype(int)
    row0 = np.round((n - (iy * GRID_DEG - 90.0 + GRID_DEG)) / LC_PX_DEG).astype(int)
    rec = {g: np.full(len(cell_ids), np.nan) for g in IGBP_GROUPS}
    for i, (c0, r0) in enumerate(zip(col0, row0)):
        if c0 < 0 or r0 < 0 or c0 + k > px or r0 + k > py:
            continue
        block = cls[r0:r0 + k, c0:c0 + k]
        valid = block >= 0
        nv = valid.sum()
        if nv == 0:
            continue
        for g, codes in IGBP_GROUPS.items():
            rec[g][i] = np.isin(block[valid], codes).sum() / nv
    df = pd.DataFrame({"cell_id": cell_ids, **{f"lc_{g}": v.astype("float32") for g, v in rec.items()}})
    return df


def classify_land_use(df: pd.DataFrame) -> pd.Series:
    """Prototype jurisdiction rule over IGBP fractions (configurable; see module docstring)."""
    if "lc_forest" not in df:
        return pd.Series("Unknown", index=df.index)
    woody = df["lc_forest"].fillna(0) + df["lc_savanna"].fillna(0)
    crop = df["lc_cropland"].fillna(0)
    urban = df["lc_urban"].fillna(0)
    out = pd.Series("Other", index=df.index)
    out[(crop >= woody) & (crop >= 0.35)] = "Agricultural"
    out[(woody > crop) & (woody >= 0.35)] = "Forest"
    out[urban >= 0.20] = "Municipal/Urban"
    out[df["lc_forest"].isna()] = "Unknown"
    return out


def build_cells(extra_cells: np.ndarray | None = None) -> pd.DataFrame:
    """Build the cell table: admin assignment by centroid + land-cover fractions."""
    states = _load_features("ADM1")
    districts = _load_features("ADM2")
    w, s, e, n = AOI_BBOX
    cand = grid.cells_in_bbox(w, s, e, n)
    lat, lon = grid.cell_center(cand)
    pts = [Point(x, y) for x, y in zip(lon, lat)]

    def assign(features, max_dist=0.0):
        geoms = [g for _, g in features]
        tree = STRtree(geoms)
        idx = np.full(len(pts), -1, dtype=int)
        qi, gi = tree.query(pts, predicate="within")
        idx[qi] = gi
        if max_dist > 0:
            miss = np.where(idx < 0)[0]
            if len(miss):
                near = tree.nearest([pts[i] for i in miss])
                for i, j in zip(miss, near):
                    if geoms[j].distance(pts[i]) <= max_dist:
                        idx[i] = j
        return idx

    sidx = assign(states, max_dist=GRID_DEG * 0.75)  # coastal cells whose centroid falls just offshore
    didx = assign(districts)
    if extra_cells is not None:
        keep = (sidx >= 0) | np.isin(cand, extra_cells)
    else:
        keep = sidx >= 0
    df = pd.DataFrame({
        "cell_id": cand, "lat": lat.astype("float32"), "lon": lon.astype("float32"),
        "state": [states[i][0]["shapeName"] if i >= 0 else None for i in sidx],
        "state_iso": [states[i][0].get("shapeISO") if i >= 0 else None for i in sidx],
        "district": [districts[i][0]["shapeName"] if i >= 0 else None for i in didx],
        "district_id": [districts[i][0]["shapeID"] if i >= 0 else None for i in didx],
    })[keep].reset_index(drop=True)
    df = df.merge(_landcover_fractions(df["cell_id"].to_numpy()), on="cell_id", how="left")
    df["land_use"] = classify_land_use(df)
    df["land_use_source"] = np.where(
        df["land_use"] == "Unknown", "unavailable",
        f"NASA MCD12Q1 IGBP {LC_YEAR} via GIBS, majority rule at {GRID_DEG} deg (prototype)")
    df["in_country"] = df["state"].notna()
    df.to_parquet(CELLS_PATH, index=False)

    # Simplified state outlines for the map + district index (state via representative point).
    feats = []
    for props, g in states:
        feats.append({"type": "Feature", "properties": {"name": props["shapeName"], "iso": props.get("shapeISO")},
                      "geometry": mapping(g.simplify(0.02, preserve_topology=True))})
    STATES_GEOJSON.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    sgeoms = [g for _, g in states]
    stree = STRtree(sgeoms)
    rows = []
    for props, g in districts:
        rp = g.representative_point()
        hit = stree.query(rp, predicate="within")
        st = states[int(hit[0])][0]["shapeName"] if len(hit) else None
        b = g.bounds
        rows.append({"district_id": props["shapeID"], "district": props["shapeName"], "state": st,
                     "west": b[0], "south": b[1], "east": b[2], "north": b[3]})
    pd.DataFrame(rows).to_parquet(DISTRICTS_INDEX, index=False)
    print(f"[geo] cells: {len(df)} | states: {df['state'].nunique()} | districts: {df['district_id'].nunique()}")
    print(df["land_use"].value_counts().to_string())
    return df


@lru_cache(maxsize=1)
def district_geometries() -> dict:
    return {p["shapeID"]: g for p, g in _load_features("ADM2")}


def district_geojson(district_id: str):
    g = district_geometries().get(district_id)
    return None if g is None else mapping(g)


if __name__ == "__main__":
    build_cells()
