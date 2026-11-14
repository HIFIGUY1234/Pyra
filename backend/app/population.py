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


# --------------------------------------------------------------------------- exact area-weighted allocation
def _split_axis(lo: np.ndarray, hi: np.ndarray, origin: float, step: float, weight=None):
    """For pixel edges [lo, hi) along one axis, the (at most two) target-cell indices and the share of the
    pixel falling in each. `weight` maps a coordinate to a cumulative measure (identity for longitude,
    sin(lat) for latitude, which makes the y-shares exact spherical-area shares). Pixels are assumed smaller
    than a target cell (30 arc-seconds vs 0.05 / 0.25 deg)."""
    f = (lambda x: x) if weight is None else weight
    i0 = np.floor((lo - origin) / step + 1e-12).astype("int64")
    edge = origin + (i0 + 1) * step
    whole = f(hi) - f(lo)
    first = np.where(hi > edge + 1e-12, (f(np.minimum(edge, hi)) - f(lo)) / whole, 1.0)
    return i0, i0 + 1, first, 1.0 - first


def allocate(block: np.ndarray, valid: np.ndarray, lat_top: np.ndarray, lat_bot: np.ndarray, lon_left: np.ndarray, lon_right: np.ndarray,
             step: float, origin_lon: float, origin_lat: float) -> pd.DataFrame:
    """Distribute every valid pixel's population over the target cells it overlaps, in proportion to spherical
    area (exact on the sphere: dA = R^2 dlambda d(sin phi)). Returns per-cell population, valid area and total area
    (relative units). Shares of each pixel sum to 1, so totals are conserved and nothing is double counted."""
    sinw = lambda d: np.sin(np.radians(d))
    xi0, xi1, fx0, fx1 = _split_axis(lon_left, lon_right, origin_lon, step)
    yi0, yi1, fy0, fy1 = _split_axis(lat_bot, lat_top, origin_lat, step, sinw)
    area = (np.radians(lon_right - lon_left))[None, :] * (sinw(lat_top) - sinw(lat_bot))[:, None]
    vals = np.where(valid, block, 0.0)
    keys, pops, va, ta = [], [], [], []
    for yi, fy in ((yi0, fy0), (yi1, fy1)):
        for xi, fx in ((xi0, fx0), (xi1, fx1)):
            w = fy[:, None] * fx[None, :]
            m = w > 0
            if not m.any():
                continue
            Y = np.broadcast_to(yi[:, None], w.shape)[m]
            X = np.broadcast_to(xi[None, :], w.shape)[m]
            keys.append(Y * 1_000_000 + X)
            pops.append((vals * w)[m])
            va.append((area * w * valid)[m])
            ta.append((area * w)[m])
    if not keys:
        return pd.DataFrame(columns=["iy", "ix", "population", "valid_area", "total_area"])
    df = pd.DataFrame({"k": np.concatenate(keys), "population": np.concatenate(pops), "valid_area": np.concatenate(va),
                       "total_area": np.concatenate(ta)}).groupby("k", as_index=False).sum()
    df["iy"], df["ix"] = df["k"] // 1_000_000, df["k"] % 1_000_000
    return df.drop(columns="k")


def build_area_weighted(path: Path | None = None, log=print, out_dir: Path | None = None) -> dict:
    """Area-weighted allocation of the raster to the 0.25 deg analysis grid and the 0.05 deg exposure grid,
    read in row blocks. Pixel boundaries come from the GeoTIFF affine transform (no alignment assumed)."""
    import rasterio
    path = path or POP_DIR / SOURCE["file"]
    out_dir = out_dir or POP_DIR
    w, s, e, n = AOI_BBOX
    coarse, fine = [], []
    total_valid = 0.0
    with rasterio.open(path) as ds:
        if ds.crs is None or ds.crs.to_epsg() != 4326:
            raise ValueError(f"expected EPSG:4326, got {ds.crs}")
        tr = ds.transform
        if tr.b != 0 or tr.d != 0:
            raise ValueError("rotated rasters are not supported")
        nod = ds.nodata
        cols = np.arange(ds.width)
        lon_l, lon_r = tr.c + cols * tr.a, tr.c + (cols + 1) * tr.a
        inx = (lon_r > w) & (lon_l < e)
        for r0 in range(0, ds.height, 256):
            h = min(256, ds.height - r0)
            rows = np.arange(r0, r0 + h)
            lat_t, lat_b = tr.f + rows * tr.e, tr.f + (rows + 1) * tr.e
            iny = (lat_b < n) & (lat_t > s)
            if not iny.any():
                continue
            block = ds.read(1, window=((r0, r0 + h), (0, ds.width))).astype("float64")[iny][:, inx]
            valid = np.isfinite(block) & (block >= 0)
            if nod is not None:
                valid &= block != nod
            lt, lb, ll, lr = lat_t[iny], lat_b[iny], lon_l[inx], lon_r[inx]
            total_valid += float(np.where(valid, block, 0).sum())
            coarse.append(allocate(block, valid, lt, lb, ll, lr, GRID_DEG, -180.0, -90.0))
            fine.append(allocate(block, valid, lt, lb, ll, lr, FINE_DEG, w, s))
    agg = lambda frames: pd.concat(frames).groupby(["iy", "ix"], as_index=False).sum()
    c = agg(coarse)
    from .config import GRID_NX
    c["cell_id"] = (c["iy"] * GRID_NX + c["ix"]).astype("int32")
    c["valid_frac"] = c["valid_area"] / c["total_area"]
    c = c[c["valid_frac"] > 0]
    cells_df = pd.DataFrame({"cell_id": c["cell_id"].to_numpy(), "population": c["population"].to_numpy(), "valid_frac": c["valid_frac"].to_numpy()})
    cells_df["density_km2"] = cells_df["population"] / grid.cell_area_km2(cells_df["cell_id"].to_numpy())
    f = agg(fine)
    fdf = pd.DataFrame({"lat": s + (f["iy"] + 0.5) * FINE_DEG, "lon": w + (f["ix"] + 0.5) * FINE_DEG, "population": f["population"]})
    fdf = fdf[fdf["population"] > 0].round({"lat": 4, "lon": 4})
    return {"cells": cells_df, "fine": fdf, "total_valid_in_window": total_valid,
            "conservation_rel_error": abs(float(cells_df["population"].sum()) - total_valid) / max(total_valid, 1)}


def compare_methods(path: Path | None = None) -> dict:
    """Sensitivity of the 0.25 deg cell populations to the assignment rule (pixel centre vs area-weighted)."""
    aw = build_area_weighted(path)["cells"].set_index("cell_id")["population"]
    pc = _centre_cells(path).set_index("cell_id")["population"]
    j = pd.concat([pc.rename("centre"), aw.rename("area")], axis=1).fillna(0.0)
    j = j[(j["centre"] > 0) | (j["area"] > 0)]
    rel = (j["area"] - j["centre"]).abs() / j[["area", "centre"]].max(axis=1).clip(lower=1)
    return {"cells": int(len(j)), "total_centre": float(j["centre"].sum()), "total_area_weighted": float(j["area"].sum()),
            "total_rel_diff": float(abs(j["area"].sum() - j["centre"].sum()) / max(j["centre"].sum(), 1)),
            "median_cell_rel_diff": float(rel.median()), "p95_cell_rel_diff": float(rel.quantile(0.95)), "max_cell_rel_diff": float(rel.max()),
            "cells_changed_over_1pct": int((rel > 0.01).sum()), "cells_changed_over_5pct": int((rel > 0.05).sum())}


def _centre_cells(path: Path | None = None) -> pd.DataFrame:
    """Pixel-centre baseline as a pure function (same rule as build(), no files written)."""
    import rasterio
    path = path or POP_DIR / SOURCE["file"]
    w, s, e, n = AOI_BBOX
    acc = {}
    with rasterio.open(path) as ds:
        tr, nod = ds.transform, ds.nodata
        lon = tr.c + (np.arange(ds.width) + 0.5) * tr.a
        for r0 in range(0, ds.height, 256):
            h = min(256, ds.height - r0)
            lat = tr.f + (np.arange(r0, r0 + h) + 0.5) * tr.e
            b = ds.read(1, window=((r0, r0 + h), (0, ds.width))).astype("float64")
            m = ((lat >= s) & (lat < n))[:, None] & ((lon >= w) & (lon < e))[None, :] & np.isfinite(b) & (b >= 0)
            if nod is not None:
                m &= b != nod
            if not m.any():
                continue
            LAT, LON = np.broadcast_to(lat[:, None], b.shape)[m], np.broadcast_to(lon[None, :], b.shape)[m]
            g = pd.Series(b[m]).groupby(grid.cell_of(LAT, LON)).sum()
            for k, v in g.items():
                acc[k] = acc.get(k, 0.0) + v
    return pd.DataFrame({"cell_id": list(acc), "population": list(acc.values())})


def build(path: Path | None = None, log=print, method: str = "area_weighted") -> dict:
    """Write the derived population layers. method='area_weighted' (default) or 'pixel_centre' (baseline)."""
    if method == "area_weighted":
        return _build_area_weighted_files(path, log)
    if method != "pixel_centre":
        raise ValueError("method must be area_weighted or pixel_centre")
    return _build_centre(path, log)


def _build_area_weighted_files(path: Path | None, log) -> dict:
    t0 = datetime.now(timezone.utc)
    path = path or POP_DIR / SOURCE["file"]
    r = build_area_weighted(path, log)
    cells, fdf = r["cells"], r["fine"]
    POP_DIR.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(CELLS, index=False)
    fdf.to_parquet(FINE, index=False)
    from . import gis_layers
    pd.DataFrame({"cell_id": cells["cell_id"], "value": cells["population"], "type": "population"}).to_parquet(gis_layers.EXPOSURE_DIR / "population.parquet", index=False)
    (gis_layers.EXPOSURE_DIR / "population.json").write_text(json.dumps({
        "kind": "population", "rows": int(len(cells)), "rejected_rows": 0, "source": SOURCE["name"], "licence": SOURCE["licence"],
        "source_date": str(SOURCE["reference_year"]), "uploaded_by": "pipeline (population.build area_weighted)",
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "url": SOURCE["url"]}, indent=1))
    gis_layers.exposure_by_cell.cache_clear()
    import rasterio
    with rasterio.open(path) as ds:
        tr = ds.transform
    sens = compare_methods(path)
    man = {**SOURCE, "sha256": _sha256(path), "bytes": path.stat().st_size, "pixel_deg": tr.a,
           "transform": [tr.a, tr.b, tr.c, tr.d, tr.e, tr.f],
           "grid_aligned": bool(abs(tr.c * 120 - round(tr.c * 120)) < 1e-3 and abs(tr.f * 120 - round(tr.f * 120)) < 1e-3),
           "assignment": "area-weighted: each pixel split over the cells it overlaps by exact spherical area (pixel edges from the affine transform)",
           "total_population_in_aoi": round(float(cells["population"].sum())), "conservation_rel_error": r["conservation_rel_error"],
           "cells_0p25": int(len(cells)), "cells_partial_coverage": int((cells["valid_frac"] < 0.999).sum()),
           "fine_grid_deg": FINE_DEG, "fine_cells": int(len(fdf)), "sensitivity_vs_pixel_centre": sens,
           "uncertainty": "Residual uncertainty is the WorldPop model itself (not quantified here) plus within-pixel distribution: "
                          "area weighting assumes people are spread uniformly inside each ~1 km pixel.",
           "processed_at": t0.isoformat(timespec="seconds"),
           "processing_seconds": round((datetime.now(timezone.utc) - t0).total_seconds(), 1)}
    MANIFEST.write_text(json.dumps(man, indent=1), encoding="utf-8")
    clear()
    log(f"[population] area-weighted: {man['cells_0p25']} cells, total {man['total_population_in_aoi']:,}; "
        f"vs centre median cell diff {sens['median_cell_rel_diff']:.4f}")
    return man


def _build_centre(path: Path | None = None, log=print) -> dict:
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
