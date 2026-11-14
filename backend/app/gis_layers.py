"""Geographic coverage transparency + administrator-supplied layers.

* `DATASETS`        provenance (source, resolution, date, licence) of every auxiliary layer.
* Jurisdiction layers  GeoJSON polygons with an explicit land-use class (e.g. an official
                       industrial-estate map or a municipal boundary). They override the
                       land-cover-derived class for the grid cells whose centres they contain.
                       This is the only way "Industrial" or "Residential/Village" is assigned:
                       PyroScope never infers industry from hotspots.
* Exposure layers   population points/grid or infrastructure points (CSV) used by the
                       critical-region ranking. Absent layers are reported as unavailable,
                       never as zero exposure.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
import pandas as pd
from shapely.geometry import shape
from shapely.prepared import prep

from . import grid
from .config import AOI_BBOX, AUX, COUNTRY_NAME

EXPOSURE_DIR = AUX / "exposure"
EXPOSURE_DIR.mkdir(parents=True, exist_ok=True)
EXPOSURE_KINDS = {"population": "population count per point (e.g. WorldPop / census aggregated to points)",
                  "infrastructure": "critical infrastructure points (substations, hospitals, pipelines, industrial sites, ...)"}

DATASETS = [
    {"layer": "Active-fire detections", "source": "NASA FIRMS (MODIS C6.1 MCD14ML, VIIRS C2 VNP14IMGT/VJ114IMGT/VJ214IMGT)",
     "resolution": "1 km (MODIS) / 375 m (VIIRS) pixels", "date": "per record", "licence": "NASA open data; cite FIRMS (see Readme.txt in each archive)",
     "coverage": "Repository archives: AOI bbox " + str(AOI_BBOX)},
    {"layer": "State / district boundaries", "source": "geoBoundaries gbOpen IND ADM1/ADM2 (simplified), commit 9469f09",
     "resolution": "simplified vector", "date": "geoBoundaries release at that commit", "licence": "gbOpen (openly licensed; see the boundary's geoBoundaries metadata)",
     "coverage": f"{COUNTRY_NAME} only"},
    {"layer": "Land cover", "source": "NASA MCD12Q1 IGBP (MODIS_Combined_L3_IGBP_Land_Cover_Type_Annual) via NASA GIBS WMS",
     "resolution": "500 m product, sampled at 0.025 deg and summarised to 0.25 deg cells", "date": "2022", "licence": "NASA open data",
     "coverage": "AOI bbox " + str(AOI_BBOX)},
    {"layer": "Meteorology", "source": "NASA POWER daily (T2M_MAX, PRECTOTCORR, RH2M, WS2M, GWETTOP)", "resolution": "0.5 x 0.625 deg",
     "date": "daily", "licence": "NASA open data", "coverage": "AOI cells"},
    {"layer": "Analysis grid", "source": "PyroScope uniform lat/lon grid", "resolution": "0.25 deg", "date": "-", "licence": "-",
     "coverage": "global indexing; administrative attributes only inside India"},
]


def coverage() -> dict:
    from . import models as M
    from sqlalchemy import select
    with M.Session() as s:
        layers = [{"id": l.id, "name": l.name, "land_use": l.land_use, "source": l.source, "licence": l.licence, "source_date": l.source_date,
                   "n_cells": l.n_cells, "uploaded_by": l.uploaded_by, "created_at": l.created_at.isoformat() + "Z"}
                  for l in s.scalars(select(M.JurisdictionLayer).order_by(M.JurisdictionLayer.id))]
    return {"administrative_coverage": {"countries": [COUNTRY_NAME], "levels": ["state (ADM1)", "district (ADM2)"],
                                        "outside": "Hotspots outside India are indexed on the global grid and shown on the map, but jurisdiction "
                                                   "routing returns 'Administrator Jurisdiction Review Required'."},
            "global": False,
            "statement": f"PyroScope's administrative intelligence currently covers {COUNTRY_NAME} only. It does not claim global administrative coverage.",
            "datasets": DATASETS, "jurisdiction_layers": layers, "exposure_layers": exposure_status(),
            "land_use_rules": ["Forest / Agricultural / Municipal-Urban / Other: prototype rule on MCD12Q1 IGBP class fractions per cell.",
                               "Residential/Village and Industrial: only from administrator-supplied jurisdiction layers (IGBP cannot separate them).",
                               "Land-use decides WHO is responsible, not whether a fire is natural or human-caused."]}


# --------------------------------------------------------------------------- jurisdiction layers
def _geoms(gj: dict) -> list:
    t = gj.get("type")
    if t == "FeatureCollection":
        return [shape(f["geometry"]) for f in gj.get("features", []) if f.get("geometry")]
    if t == "Feature":
        return [shape(gj["geometry"])]
    if t in ("Polygon", "MultiPolygon"):
        return [shape(gj)]
    raise ValueError("GeoJSON must be a Polygon, MultiPolygon, Feature or FeatureCollection")


def cells_in_geojson(gj: dict, candidate_cells=None) -> list[int]:
    gs = _geoms(gj)
    if not gs:
        raise ValueError("GeoJSON contains no polygon geometry")
    out = set()
    for g in gs:
        if g.geom_type not in ("Polygon", "MultiPolygon") or not g.is_valid:
            raise ValueError("only valid Polygon/MultiPolygon geometries are accepted")
        w, s_, e, n = g.bounds
        ids = grid.cells_in_bbox(w, s_, e, n)
        if candidate_cells is not None:
            ids = np.intersect1d(ids, np.asarray(candidate_cells))
        lat, lon = grid.cell_center(ids)
        pg = prep(g)
        from shapely.geometry import Point
        hit = [int(c) for c, la, lo in zip(ids, lat, lon) if pg.contains(Point(float(lo), float(la)))]
        if not hit:  # a polygon smaller than a cell: assign the cell containing its centroid
            c = g.representative_point()
            hit = [int(grid.cell_of([c.y], [c.x])[0])]
        out.update(hit)
    return sorted(out)


@lru_cache(maxsize=1)
def overrides() -> dict:
    """cell_id -> (land_use, label). Most recent layer wins."""
    try:
        from . import models as M
        from sqlalchemy import select
        with M.Session() as s:
            rows = list(s.scalars(select(M.JurisdictionLayer).order_by(M.JurisdictionLayer.id)))
    except Exception:
        return {}
    out = {}
    for l in rows:
        for c in l.cell_ids or []:
            out[int(c)] = (l.land_use, f"administrator layer '{l.name}' ({l.source}{', ' + l.source_date if l.source_date else ''})")
    return out


def apply_overrides(cells: pd.DataFrame) -> pd.DataFrame:
    ov = overrides()
    if not ov:
        return cells
    idx = cells.index.intersection(list(ov))
    if len(idx):
        cells = cells.copy()
        cells.loc[idx, "land_use"] = [ov[i][0] for i in idx]
        cells.loc[idx, "land_use_source"] = [ov[i][1] for i in idx]
    return cells


# --------------------------------------------------------------------------- exposure layers
def _meta_path(kind):
    return EXPOSURE_DIR / f"{kind}.json"


def exposure_status() -> dict:
    out = {}
    for k, desc in EXPOSURE_KINDS.items():
        mp = _meta_path(k)
        out[k] = json.loads(mp.read_text()) | {"status": "loaded"} if mp.exists() else {"status": "unavailable", "expects": desc}
    return out


def save_exposure(kind: str, df: pd.DataFrame, source: str, licence: str | None, source_date: str | None, uploaded_by: str) -> dict:
    if kind not in EXPOSURE_KINDS:
        raise ValueError(f"kind must be one of {list(EXPOSURE_KINDS)}")
    df.columns = [c.strip().lower() for c in df.columns]
    for col in ("latitude", "longitude"):
        if col not in df:
            raise ValueError("CSV needs latitude and longitude columns")
    lat = pd.to_numeric(df["latitude"], errors="coerce")
    lon = pd.to_numeric(df["longitude"], errors="coerce")
    ok = lat.between(-90, 90) & lon.between(-180, 180)
    val = pd.to_numeric(df["population"], errors="coerce") if kind == "population" else pd.Series(1.0, index=df.index)
    if kind == "population":
        if "population" not in df:
            raise ValueError("population CSV needs a population column")
        ok &= val >= 0
    out = pd.DataFrame({"cell_id": grid.cell_of(lat[ok], lon[ok]), "value": val[ok].astype(float),
                        "type": df.loc[ok, "type"].astype(str) if "type" in df else kind})
    out.to_parquet(EXPOSURE_DIR / f"{kind}.parquet", index=False)
    meta = {"kind": kind, "rows": int(ok.sum()), "rejected_rows": int((~ok).sum()), "source": source, "licence": licence, "source_date": source_date,
            "uploaded_by": uploaded_by, "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _meta_path(kind).write_text(json.dumps(meta, indent=1))
    exposure_by_cell.cache_clear()
    return meta


@lru_cache(maxsize=4)
def exposure_by_cell(kind: str) -> pd.Series | None:
    p = EXPOSURE_DIR / f"{kind}.parquet"
    if not p.exists():
        return None
    return pd.read_parquet(p).groupby("cell_id")["value"].sum()


def clear():
    overrides.cache_clear()
    exposure_by_cell.cache_clear()
