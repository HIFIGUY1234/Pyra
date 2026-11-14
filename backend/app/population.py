"""Population grid acquisition, aggregation and hotspot exposure.

Dataset choice (see docs/POPULATION_EXPOSURE.md for the comparison):
  WorldPop Global 2000-2020, 1 km, UN-adjusted, country mosaic for India, reference year 2020.
  CC BY 4.0. Geographic WGS84 (EPSG:4326), 30 arc-second pixels, values = people per pixel.
  One year only; it is never mixed with other years.

Processing:
  * the GeoTIFF is read in row blocks (never the whole raster at once);
  * pixels are assigned to the 0.25 deg analysis grid and to a 0.05 deg exposure grid by pixel centre.
    30" pixels nest exactly in both grids when the raster origin is on a 30" boundary (checked; otherwise
    the centre rule misplaces at most half a pixel, ~0.5 km, at grid edges, and this is reported);
  * NoData pixels are excluded and the valid-pixel fraction per cell is kept, so partial coverage
    (coast, borders) is visible instead of silently reading as low population;
  * each pixel is counted once (centre rule), so there is no double counting at cell boundaries.

Exposure = people living within R km of a location (hotspot, forecast cell, alert area). It describes who is
near a detected or predicted hotspot. It is NOT a prediction that a settlement will burn.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import grid
from .config import AOI_BBOX, AUX, GRID_DEG

POP_DIR = AUX / "population"
FINE_DEG = 0.05
SOURCE = {
    "id": "worldpop_2020_1km_unadj_IND",
    "name": "WorldPop Global 2000-2020 1 km UN-adjusted population counts, India, 2020",
    "url": "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/2020/IND/ind_ppp_2020_1km_Aggregated_UNadj.tif",
    "file": "ind_ppp_2020_1km_Aggregated_UNadj.tif",
    "licence": "CC BY 4.0 (WorldPop, www.worldpop.org; doi:10.5258/SOTON/WP00671)",
    "reference_year": 2020, "resolution": "30 arc-second (~1 km)", "crs": "EPSG:4326",
    "units": "people per pixel", "version": "Global_2000_2020_1km_UNadj (2020 release)",
    "coverage": "India national mosaic (country boundary as used by WorldPop)",
}
MANIFEST = POP_DIR / "manifest.json"
CELLS = POP_DIR / "population_cells.parquet"
FINE = POP_DIR / "population_fine.parquet"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def acquire(log=print, session=None, retries: int = 4) -> Path:
    """Resumable download with size verification; the manifest records the SHA-256 of what was used."""
    import requests

    from .acquire import _download
    s = session or requests.Session()
    POP_DIR.mkdir(parents=True, exist_ok=True)
    dest = POP_DIR / SOURCE["file"]
    head = s.head(SOURCE["url"], timeout=30, allow_redirects=True)
    head.raise_for_status()
    size = int(head.headers.get("Content-Length", 0)) or None
    if dest.exists() and size and dest.stat().st_size == size:
        log(f"[population] {dest.name} already present ({size:,} bytes)")
        return dest
    tmp = dest.with_suffix(".tif.part")
    _download(SOURCE["url"], tmp, size, s, retries, __import__("time").sleep, log)
    if size and tmp.stat().st_size != size:
        raise IOError("population download size mismatch")
    tmp.replace(dest)
    log(f"[population] downloaded {dest.name}")
    return dest


def build(path: Path | None = None, log=print) -> dict:
    """Aggregate the raster to the analysis grid (0.25 deg) and the exposure grid (0.05 deg), block by block."""
    import rasterio
    path = path or POP_DIR / SOURCE["file"]
    t0 = datetime.now(timezone.utc)
    w, s, e, n = AOI_BBOX
    acc, accv, accn, fine = {}, {}, {}, {}
    with rasterio.open(path) as ds:
        if ds.crs is None or ds.crs.to_epsg() != 4326:
            raise ValueError(f"expected EPSG:4326, got {ds.crs}")
        tr = ds.transform
        px = tr.a
        # 30" grid: the origin should be a multiple of 1/120 deg (px is stored rounded, so test against 1/120)
        aligned = abs(tr.c * 120 - round(tr.c * 120)) < 1e-3 and abs(tr.f * 120 - round(tr.f * 120)) < 1e-3
        nod = ds.nodata
        cols = np.arange(ds.width)
        lon = tr.c + (cols + 0.5) * tr.a
        inlon = (lon >= w) & (lon < e)
        total = 0.0
        step = 256
        for r0 in range(0, ds.height, step):
            h = min(step, ds.height - r0)
            block = ds.read(1, window=((r0, r0 + h), (0, ds.width))).astype("float64")
            lat = tr.f + (np.arange(r0, r0 + h) + 0.5) * tr.e
            m_lat = (lat >= s) & (lat < n)
            if not m_lat.any():
                continue
            LAT = np.repeat(lat[:, None], ds.width, 1)
            LON = np.repeat(lon[None, :], h, 0)
            inside = m_lat[:, None] & inlon[None, :]
            valid = inside & np.isfinite(block) & ((block != nod) if nod is not None else True) & (block >= 0)
            cid = grid.cell_of(LAT[inside], LON[inside])
            vv = valid[inside]
            vals = np.where(vv, block[inside], 0.0)
            df = pd.DataFrame({"c": cid, "v": vals, "valid": vv})
            g = df.groupby("c").agg(v=("v", "sum"), valid=("valid", "sum"), n=("valid", "size"))
            for c, row in g.iterrows():
                acc[c] = acc.get(c, 0.0) + row.v
                accv[c] = accv.get(c, 0) + row.valid
                accn[c] = accn.get(c, 0) + row.n
            fx = np.floor((LON[inside][vv] - w) / FINE_DEG).astype(int)
            fy = np.floor((LAT[inside][vv] - s) / FINE_DEG).astype(int)
            gf = pd.DataFrame({"k": fy * 10000 + fx, "v": block[inside][vv]}).groupby("k")["v"].sum()
            for k, v in gf.items():
                fine[k] = fine.get(k, 0.0) + v
            total += vals.sum()
    cells = pd.DataFrame({"cell_id": np.array(list(acc), dtype="int32"), "population": np.array(list(acc.values())),
                          "valid_frac": np.array([accv[c] / accn[c] for c in acc])})
    cells = cells[cells["valid_frac"] > 0].copy()
    cells["density_km2"] = cells["population"] / grid.cell_area_km2(cells["cell_id"].to_numpy())
    POP_DIR.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(CELLS, index=False)
    k = np.array(list(fine))
    fdf = pd.DataFrame({"lat": s + (k // 10000 + 0.5) * FINE_DEG, "lon": w + (k % 10000 + 0.5) * FINE_DEG,
                        "population": np.array(list(fine.values()))})
    fdf = fdf[fdf["population"] > 0].round({"lat": 4, "lon": 4})
    fdf.to_parquet(FINE, index=False)
    # register with the generic exposure-layer mechanism used by critical-region scoring
    from . import gis_layers
    pd.DataFrame({"cell_id": cells["cell_id"], "value": cells["population"], "type": "population"}).to_parquet(
        gis_layers.EXPOSURE_DIR / "population.parquet", index=False)
    meta = {"kind": "population", "rows": int(len(cells)), "rejected_rows": 0, "source": SOURCE["name"], "licence": SOURCE["licence"],
            "source_date": str(SOURCE["reference_year"]), "uploaded_by": "pipeline (population.build)",
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "url": SOURCE["url"]}
    (gis_layers.EXPOSURE_DIR / "population.json").write_text(json.dumps(meta, indent=1))
    gis_layers.exposure_by_cell.cache_clear()
    man = {**SOURCE, "sha256": _sha256(path), "bytes": path.stat().st_size, "pixel_deg": px, "grid_aligned": bool(aligned),
           "assignment": "pixel centre (each pixel counted once)", "total_population_in_aoi": round(total),
           "cells_0p25": int(len(cells)), "cells_partial_coverage": int((cells["valid_frac"] < 0.999).sum()),
           "fine_grid_deg": FINE_DEG, "fine_cells": int(len(fdf)),
           "processed_at": t0.isoformat(timespec="seconds"),
           "processing_seconds": round((datetime.now(timezone.utc) - t0).total_seconds(), 1)}
    MANIFEST.write_text(json.dumps(man, indent=1), encoding="utf-8")
    clear()
    log(f"[population] {man['cells_0p25']} cells, total {man['total_population_in_aoi']:,} people, aligned={aligned}")
    return man


def manifest() -> dict | None:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else None


@lru_cache(maxsize=1)
def cells() -> pd.DataFrame | None:
    return pd.read_parquet(CELLS).set_index("cell_id") if CELLS.exists() else None


@lru_cache(maxsize=1)
def _fine():
    if not FINE.exists():
        return None
    from scipy.spatial import cKDTree  # scipy ships with scikit-learn
    f = pd.read_parquet(FINE)
    xyz = _xyz(f["lat"].to_numpy(), f["lon"].to_numpy())
    return cKDTree(xyz), f["population"].to_numpy()


def _xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)]) * 6371.0


def people_within(lat, lon, radius_km: float = 5.0) -> np.ndarray | None:
    """People in 0.05 deg exposure cells whose centres lie within radius_km of each point (chord ~ arc at these scales).
    Resolution limit: +/- one 0.05 deg cell (~5.5 km) at the circle edge, so use radius_km >= 5."""
    fi = _fine()
    if fi is None:
        return None
    tree, pop = fi
    idx = tree.query_ball_point(_xyz(np.atleast_1d(lat), np.atleast_1d(lon)), r=radius_km)
    return np.array([pop[i].sum() if len(i) else 0.0 for i in idx])


def clear():
    cells.cache_clear()
    _fine.cache_clear()


if __name__ == "__main__":
    build(acquire())
