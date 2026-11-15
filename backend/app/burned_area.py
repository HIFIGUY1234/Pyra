"""Burned-area mapping from MODIS MCD64A1 C6.1 and VIIRS VNP64A1 v002 (monthly, 500 m, MODIS sinusoidal grid).

Burned area is a SEPARATE product from active-fire hotspots: it maps burn scars and their burn date. Nothing here is
derived from hotspot counts.

Pipeline: LAADS DAAC archive listing (Earthdata bearer token) -> licence-aware resumable download -> SHA-256 ->
HDF4 (MCD64A1) / HDF5 (VNP64A1) read of `Burn Date`, `Burn Date Uncertainty` and `QA` -> sinusoidal geolocation of
each pixel -> burned pixels (lat, lon, burn day) kept as Parquet -> 0.25 deg cell totals.

Burn Date coding (MCD64A1 C6.1 user guide): 1-366 = day of year burned, 0 = unburned, -1 = unmapped (insufficient
data), -2 = water. Unmapped and water pixels are NEVER counted as unburned: totals report burned, mapped and unmapped
area separately. The sinusoidal grid is equal-area, so every 500 m pixel covers 463.3127^2 m^2 = 0.21466 km^2.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import AOI_BBOX, DATA, PROCESSED

RAW = DATA / "raw" / "burned_area"
OUT = PROCESSED / "burned_area"
LAADS = "https://ladsweb.modaps.eosdis.nasa.gov/archive/allData"
PRODUCTS = {
    "MCD64A1": {"collection": "61", "version": "061", "sensor": "MODIS Terra+Aqua", "format": "HDF4", "start": "2000-11",
                "doi": "10.5067/MODIS/MCD64A1.061"},
    "VNP64A1": {"collection": "5200", "version": "002", "sensor": "Suomi NPP VIIRS", "format": "HDF5/HDF-EOS5", "start": "2012-03",
                "doi": "10.5067/VIIRS/VNP64A1.002"},
}
R_SIN = 6371007.181
TILE_M = 1111950.5197665
NPIX = 2400
PIX_M = TILE_M / NPIX                         # 463.3127 m
PIX_KM2 = (PIX_M / 1000) ** 2                 # 0.21466 km2 (equal-area projection)


# --------------------------------------------------------------------------- grid
def tile_of(lat: float, lon: float) -> tuple[int, int]:
    y = math.radians(lat) * R_SIN
    x = math.radians(lon) * R_SIN * math.cos(math.radians(lat))
    return int(math.floor(x / TILE_M) + 18), int(9 - math.floor(y / TILE_M) - 1)


def india_tiles(bbox=AOI_BBOX) -> list[tuple[int, int]]:
    w, s, e, n = bbox
    tiles = set()
    for lat in np.arange(s, n + 0.01, 0.25):
        for lon in np.arange(w, e + 0.01, 0.25):
            tiles.add(tile_of(float(lat), float(lon)))
    return sorted(tiles)


def pixel_latlon(h: int, v: int, rows: np.ndarray, cols: np.ndarray):
    x = (h - 18) * TILE_M + (cols + 0.5) * PIX_M
    y = (9 - v) * TILE_M - (rows + 0.5) * PIX_M
    lat = np.degrees(y / R_SIN)
    lon = np.degrees(x / (R_SIN * np.cos(np.radians(lat))))
    return lat, lon


# --------------------------------------------------------------------------- access
def _token() -> str | None:
    return os.getenv("EARTHDATA_TOKEN") or None


def _session():
    import requests
    s = requests.Session()
    tok = _token()
    if not tok:
        raise PermissionError("BLOCKED_BY_CREDENTIALS: EARTHDATA_TOKEN not set")
    s.headers["Authorization"] = f"Bearer {tok}"
    s.headers["User-Agent"] = "PyroScope burned-area client"
    return s


def _check(r, what: str):
    loc = r.headers.get("Location", "") if r.is_redirect else ""
    if "/profiles/licenses" in loc or "/profiles/licenses" in r.url:
        raise PermissionError("BLOCKED_BY_CREDENTIALS: LAADS DAAC requires the Earthdata account to accept the data licence "
                              "(sign in once at https://ladsweb.modaps.eosdis.nasa.gov and accept it), then retry")
    if r.status_code in (401, 403):
        raise PermissionError(f"BLOCKED_BY_CREDENTIALS: HTTP {r.status_code} for {what}")
    r.raise_for_status()


def month_doy(year: int, month: int) -> int:
    return date(year, month, 1).timetuple().tm_yday


def search(product: str, year: int, month: int, session=None, tiles=None) -> list[dict]:
    """Granules (name, url, size) for one month over the India tiles, from the LAADS archive listing."""
    if product not in PRODUCTS:
        raise ValueError(f"product must be one of {list(PRODUCTS)}")
    s = session or _session()
    p = PRODUCTS[product]
    url = f"{LAADS}/{p['collection']}/{product}/{year}/{month_doy(year, month):03d}.json"
    r = s.get(url, timeout=60, allow_redirects=False)
    if r.status_code == 404:
        return []
    _check(r, url)
    want = {f".h{h:02d}v{v:02d}." for h, v in (tiles or india_tiles())}
    out = []
    for c in r.json().get("content", []):
        name = c["name"]
        if any(t in name for t in want) and name.endswith((".hdf", ".h5")):
            out.append({"name": name, "url": f"{LAADS}/{p['collection']}/{product}/{year}/{month_doy(year, month):03d}/{name}",
                        "size": c.get("size"), "product": product, "year": year, "month": month})
    return out


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def download(granules: list[dict], session=None, retries: int = 4, sleep=time.sleep, progress=None) -> list[Path]:
    """Resumable download (HTTP Range on a .part file); each file verified as HDF4/HDF5 and checksummed."""
    s = session or _session()
    RAW.mkdir(parents=True, exist_ok=True)
    man = _manifest()
    paths = []
    for k, g in enumerate(granules):
        dest = RAW / g["name"]
        if dest.exists() and _valid(dest) and man.get(g["name"], {}).get("sha256"):
            paths.append(dest)
            continue
        part = dest.with_suffix(dest.suffix + ".part")
        for attempt in range(retries):
            try:
                have = part.stat().st_size if part.exists() else 0
                hdr = {"Range": f"bytes={have}-"} if have else {}
                r = s.get(g["url"], headers=hdr, timeout=120, stream=True, allow_redirects=False)
                if r.is_redirect and "/profiles/licenses" not in r.headers.get("Location", ""):
                    r = s.get(r.headers["Location"], headers=hdr, timeout=120, stream=True)
                _check(r, g["name"])
                with open(part, "ab" if r.status_code == 206 else "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                break
            except PermissionError:
                raise
            except Exception:
                if attempt == retries - 1:
                    raise
                sleep(2 ** attempt)
        part.replace(dest)
        if not _valid(dest):
            dest.unlink()
            raise ValueError(f"{g['name']}: not an HDF4/HDF5 file (server returned something else)")
        man[g["name"]] = {"sha256": _sha256(dest), "bytes": dest.stat().st_size, "url": g["url"],
                          "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _save_manifest(man)
        paths.append(dest)
        if progress:
            progress(f"downloaded {k + 1}/{len(granules)} {g['name']}")
    return paths


def _valid(p: Path) -> bool:
    with open(p, "rb") as f:
        sig = f.read(8)
    return sig.startswith(b"\x0e\x03\x13\x01") or sig.startswith(b"\x89HDF\r\n\x1a\n")


def _manifest() -> dict:
    f = RAW / "manifest.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _save_manifest(m: dict):
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "manifest.json").write_text(json.dumps(m, indent=1))


# --------------------------------------------------------------------------- read
def read_granule(path: Path) -> dict:
    """Burn Date / uncertainty / QA arrays (2400x2400) and the tile indices from the file name."""
    name = path.name
    h, v = int(name.split(".h")[1][:2]), int(name.split(".h")[1][3:5])
    with open(path, "rb") as f:
        hdf5 = f.read(8).startswith(b"\x89HDF")
    if hdf5:
        import h5py
        found = {}
        with h5py.File(path, "r") as fh:
            def visit(n, obj):
                if isinstance(obj, h5py.Dataset):
                    found[n.rsplit("/", 1)[-1]] = obj[()]
            fh.visititems(visit)
    else:
        from pyhdf.SD import SD, SDC
        sd = SD(str(path), SDC.READ)
        found = {k: sd.select(k)[:] for k in sd.datasets()}
        sd.end()
    bd = found.get("Burn Date")
    if bd is None:
        raise ValueError(f"{name}: no 'Burn Date' layer (found {sorted(found)[:10]})")
    if bd.shape != (NPIX, NPIX):
        raise ValueError(f"{name}: unexpected grid {bd.shape}")
    return {"h": h, "v": v, "burn_date": bd.astype(np.int16), "uncertainty": found.get("Burn Date Uncertainty"),
            "qa": found.get("QA"), "first_day": found.get("First Day"), "last_day": found.get("Last Day")}


def granule_pixels(path: Path, year: int, bbox=AOI_BBOX) -> tuple[pd.DataFrame, dict]:
    """Burned pixels inside the AOI and per-granule mapped/unmapped/water pixel counts (also inside the AOI)."""
    g = read_granule(path)
    bd = g["burn_date"]
    rows, cols = np.indices(bd.shape)
    lat, lon = pixel_latlon(g["h"], g["v"], rows.ravel(), cols.ravel())
    w, s, e, n = bbox
    inside = (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)
    b = bd.ravel()
    burned = inside & (b >= 1) & (b <= 366)
    unc = g["uncertainty"].ravel()[burned] if g["uncertainty"] is not None else np.full(burned.sum(), np.nan)
    qa = g["qa"].ravel()[burned] if g["qa"] is not None else np.zeros(burned.sum(), np.uint8)
    px = pd.DataFrame({"lat": lat[burned], "lon": lon[burned], "burn_doy": b[burned].astype(np.int16),
                       "burn_date": pd.to_datetime(f"{year}-01-01") + pd.to_timedelta(b[burned].astype(int) - 1, unit="D"),
                       "uncertainty_days": unc.astype(float), "qa": qa.astype(np.uint8), "tile": f"h{g['h']:02d}v{g['v']:02d}"})
    from .grid import cell_of
    counts = {"burned": int(burned.sum()), "unburned": int((inside & (b == 0)).sum()), "unmapped": int((inside & (b == -1)).sum()),
              "water": int((inside & (b == -2)).sum())}
    cells = {}
    for kind, mask in (("burned", burned), ("unburned", inside & (b == 0)), ("unmapped", inside & (b == -1))):
        if mask.any():
            cid = cell_of(lat[mask], lon[mask])
            cells[kind] = pd.Series(np.asarray(cid)).value_counts()
    return px, {"counts": counts, "cells": cells}


# --------------------------------------------------------------------------- monthly product
def process_month(product: str, year: int, month: int, paths: list[Path], progress=None) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    pix, agg = [], {"burned": [], "unburned": [], "unmapped": []}
    tot = {"burned": 0, "unburned": 0, "unmapped": 0, "water": 0}
    for k, p in enumerate(paths):
        px, info = granule_pixels(p, year)
        pix.append(px)
        for kk in tot:
            tot[kk] += info["counts"][kk]
        for kind, sr in info["cells"].items():
            agg[kind].append(sr)
        if progress:
            progress(f"read {k + 1}/{len(paths)} {p.name}")
    px = pd.concat(pix, ignore_index=True) if pix else pd.DataFrame()
    ser = {k: (pd.concat(v).groupby(level=0).sum() if v else pd.Series(dtype=float)) for k, v in agg.items()}
    cells = pd.DataFrame(ser).fillna(0).rename_axis("cell_id").reset_index()
    cells["burned_km2"] = cells["burned"] * PIX_KM2
    cells["mapped_km2"] = (cells["burned"] + cells["unburned"]) * PIX_KM2
    cells["unmapped_km2"] = cells["unmapped"] * PIX_KM2
    cells["burned_fraction_of_mapped"] = np.where(cells["mapped_km2"] > 0, cells["burned_km2"] / cells["mapped_km2"], np.nan)
    tag = f"{product}_{year}{month:02d}"
    px.to_parquet(OUT / f"{tag}_pixels.parquet", index=False)
    cells.to_parquet(OUT / f"{tag}_cells.parquet", index=False)
    meta = {"product": product, **PRODUCTS[product], "year": year, "month": month, "granules": [p.name for p in paths],
            "granule_sha256": {p.name: _manifest().get(p.name, {}).get("sha256") for p in paths},
            "pixel_km2": PIX_KM2, "burned_km2": tot["burned"] * PIX_KM2, "mapped_km2": (tot["burned"] + tot["unburned"]) * PIX_KM2,
            "unmapped_km2": tot["unmapped"] * PIX_KM2, "water_km2": tot["water"] * PIX_KM2,
            "unmapped_share": tot["unmapped"] / max(1, tot["burned"] + tot["unburned"] + tot["unmapped"]),
            "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "PROCESSED_AUTHENTIC" if paths else "NO_GRANULES",
            "notes": "Unmapped (-1) and water (-2) pixels are reported separately and never counted as unburned."}
    (OUT / f"{tag}.json").write_text(json.dumps(meta, indent=1))
    return meta


def run(product: str, year: int, month: int | None = None, progress=None) -> dict:
    months = [int(month)] if month else list(range(1, 13))
    if any(m < 1 or m > 12 for m in months):
        raise ValueError("month must be 1-12")
    s = _session()
    out = {}
    for m in months:
        if progress:
            progress(f"searching {product} {year}-{m:02d}")
        g = search(product, year, m, session=s)
        if not g:
            out[f"{year}-{m:02d}"] = {"status": "NO_GRANULES"}
            continue
        paths = download(g, session=s, progress=progress)
        out[f"{year}-{m:02d}"] = process_month(product, year, m, paths, progress=progress)
    return out


# --------------------------------------------------------------------------- queries
def coverage() -> dict:
    items = []
    for f in sorted(OUT.glob("*.json")) if OUT.exists() else []:
        m = json.loads(f.read_text())
        items.append({k: m.get(k) for k in ("product", "year", "month", "burned_km2", "mapped_km2", "unmapped_km2", "unmapped_share",
                                            "processed_at", "status")} | {"granules": len(m.get("granules", []))})
    tok = bool(_token())
    return {"products": PRODUCTS, "months": items, "tiles": [f"h{h:02d}v{v:02d}" for h, v in india_tiles()],
            "access": {"earthdata_login": "token present" if tok else "token missing", "provider": "LAADS DAAC archive (bearer token)",
                       "status": "PROCESSED" if items else ("CONFIGURED_NOT_DOWNLOADED" if tok else "BLOCKED_BY_CREDENTIALS"),
                       "note": "A token alone is not enough: the Earthdata account must also accept the LAADS licence."},
            "interpretation": "Burned area (burn scars) is a separate product from active-fire hotspots and is never estimated from hotspot counts."}


def _cells(product: str, year: int, month: int) -> pd.DataFrame:
    f = OUT / f"{product}_{year}{month:02d}_cells.parquet"
    if not f.exists():
        raise KeyError(f"{product} {year}-{month:02d} not processed")
    return pd.read_parquet(f)


def summary(product: str = "MCD64A1", year: int | None = None, by: str = "state") -> dict:
    from . import store
    if by not in ("state", "district", "month"):
        raise ValueError("by must be state | district | month")
    files = sorted(OUT.glob(f"{product}_*_cells.parquet")) if OUT.exists() else []
    if year:
        files = [f for f in files if f.name.split("_")[1].startswith(str(year))]
    if not files:
        return {"product": product, "items": [], "status": "NO_DATA", "note": "No processed months (see /api/burned-area/coverage)."}
    frames = []
    for f in files:
        d = pd.read_parquet(f)
        d["ym"] = int(f.name.split("_")[1])
        frames.append(d)
    d = pd.concat(frames)
    if by == "month":
        g = d.groupby("ym")[["burned_km2", "mapped_km2", "unmapped_km2"]].sum().reset_index()
    else:
        cl = store.cells().set_index("cell_id")
        key = "state" if by == "state" else "district_id"
        d[key] = d["cell_id"].map(cl[key]).fillna(store.OUTSIDE)
        g = d.groupby(key)[["burned_km2", "mapped_km2", "unmapped_km2"]].sum().reset_index().sort_values("burned_km2", ascending=False)
    g["unmapped_share"] = g["unmapped_km2"] / (g["mapped_km2"] + g["unmapped_km2"]).replace(0, np.nan)
    return {"product": product, "by": by, "items": g.to_dict("records"), "status": "OK",
            "uncertainty": "Pixel-level burn-date uncertainty is reported per pixel; area totals carry the product's documented "
                           "omission of small/short burns (500 m pixels), which is not corrected here."}


def cells_layer(product: str, year: int, month: int) -> dict:
    from .grid import cell_bounds
    d = _cells(product, year, month)
    d = d[d["burned_km2"] > 0]
    return {"product": product, "year": year, "month": month, "cells": [
        {"cell_id": int(r.cell_id), "bounds": cell_bounds(int(r.cell_id)), "burned_km2": float(r.burned_km2),
         "mapped_km2": float(r.mapped_km2), "unmapped_km2": float(r.unmapped_km2)} for r in d.itertuples()]}


def event_association(product: str, year: int, month: int, buffer_km: float = 1.0, lag_days: int = 16) -> dict:
    """Compare fire events with burn scars of one month: does a mapped scar lie within the event footprint
    (+buffer) with a burn date between first detection - lag and last detection + lag? CORROBORATING evidence only:
    MCD64A1 uses MODIS active-fire observations to guide its mapping, so it is not independent of MODIS hotspots."""
    from scipy.spatial import cKDTree
    from sqlalchemy import select
    from . import models as M
    f = OUT / f"{product}_{year}{month:02d}_pixels.parquet"
    if not f.exists():
        raise KeyError(f"{product} {year}-{month:02d} not processed")
    px = pd.read_parquet(f)
    lo, hi = pd.Timestamp(year, month, 1), pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(1)
    with M.Session() as s:
        evs = list(s.scalars(select(M.FireEvent).where(M.FireEvent.last_detection >= lo.to_pydatetime(),
                                                       M.FireEvent.first_detection <= hi.to_pydatetime() + pd.Timedelta(days=1))))
    if px.empty or not evs:
        return {"events": len(evs), "burned_pixels": int(len(px)), "status": "INSUFFICIENT_DATA"}
    k = 111.32
    tree = cKDTree(np.c_[px["lat"].to_numpy() * k, px["lon"].to_numpy() * k * np.cos(np.radians(px["lat"].to_numpy()))])
    bd = px["burn_date"].to_numpy("datetime64[D]")
    matched, scar_hit = 0, np.zeros(len(px), bool)
    for e in evs:
        r = 0.5 * math.hypot((e.east - e.west) * k * math.cos(math.radians(e.lat)), (e.north - e.south) * k) + buffer_km
        idx = np.array(tree.query_ball_point([e.lat * k, e.lon * k * math.cos(math.radians(e.lat))], r), int)
        if len(idx):
            ok = (bd[idx] >= np.datetime64((e.first_detection - pd.Timedelta(days=lag_days)).date())) & \
                 (bd[idx] <= np.datetime64((e.last_detection + pd.Timedelta(days=lag_days)).date()))
            if ok.any():
                matched += 1
                scar_hit[idx[ok]] = True
    return {"product": product, "year": year, "month": month, "events": len(evs), "events_with_scar": matched,
            "event_scar_rate": matched / len(evs), "burned_pixels": int(len(px)),
            "burned_area_with_event_share": float(scar_hit.mean()),
            "omission_proxy": 1 - float(scar_hit.mean()), "commission_proxy": 1 - matched / len(evs),
            "independence": "NOT INDEPENDENT: MCD64A1/VNP64A1 use active-fire detections to guide burn mapping; this is corroboration, not validation.",
            "notes": "Event footprints are observation footprints; small/short crop burns are often below the 500 m burned-area detection limit."}
