"""VIIRS 750 m active-fire Level-2 granules (VNP14 / VJ114 / VJ214, Collection 2 "002").

Product facts (NASA CMR collection records, checked 2026-11-14):
  * VNP14.002  Suomi NPP   C2545314536-LPCLOUD  from 2012-01-17  (S-NPP science data delivery ceased 2026-11-02)
  * VJ114.002  NOAA-20     C2545310869-LPCLOUD  from 2018-01-01
  * VJ214.002  NOAA-21     C2830465410-LPCLOUD  from 2023-02-10
  * 6-minute swath granules, 750 m M-band, NetCDF4, MODIS Collection 6 fire algorithm (MOD14 heritage);
    distributed by LP DAAC from Earthdata Cloud; download requires Earthdata Login (searching does not).
File structure (LAADS file specification for VNP14):
  * fire-pixel tables ``FP_latitude``, ``FP_longitude``, ``FP_power`` (MW), ``FP_confidence`` (uint8, %),
    ``FP_line``, ``FP_sample``, ``FP_SolZenAng`` (deg), ...; swath arrays ``fire mask`` (classes 7/8/9 =
    low/nominal/high-confidence fire) and ``algorithm QA``; granule attribute ``DayNightFlag``.
  * There is no per-pixel day flag: day/night uses FP_SolZenAng < 85 deg (MOD14 day definition) and falls back to
    the granule DayNightFlag.

Credentials: ``EARTHDATA_TOKEN`` (EDL user token, sent as a Bearer header) or a ``~/.netrc`` entry for
urs.earthdata.nasa.gov (used by ``requests`` automatically). Never in code, never logged.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import AOI_BBOX, DATA

RAW = DATA / "raw"

CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
PRODUCTS = {"Suomi NPP": ("VNP14", "002"), "NOAA-20": ("VJ114", "002"), "NOAA-21": ("VJ214", "002")}
PREFIX_SAT = {"VNP14": "Suomi NPP", "VJ114": "NOAA-20", "VJ214": "NOAA-21"}
GRANULE_DIR = RAW / "viirs750"
MANIFEST = GRANULE_DIR / "manifest.json"
DAY_SZA = 85.0
CLASS = {7: "l", 8: "n", 9: "h"}


# --------------------------------------------------------------------------- search (public)
def search(satellite: str, start: str, end: str, bbox=AOI_BBOX, session=None, page_size: int = 200, max_pages: int = 50) -> list[dict]:
    import requests
    s = session or requests
    short, ver = PRODUCTS[satellite]
    out, page = [], 1
    while page <= max_pages:
        r = s.get(CMR, params={"short_name": short, "version": ver, "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z",
                               "bounding_box": ",".join(str(x) for x in bbox), "page_size": page_size, "page_num": page}, timeout=60)
        r.raise_for_status()
        items = r.json().get("items", [])
        for it in items:
            u = it["umm"]
            url = next((x["URL"] for x in u.get("RelatedUrls", []) if x["URL"].startswith("https") and x["URL"].endswith(".nc")), None)
            size = next((a.get("Size") for a in u.get("DataGranule", {}).get("ArchiveAndDistributionInformation", [])), None)
            unit = next((a.get("SizeUnit") for a in u.get("DataGranule", {}).get("ArchiveAndDistributionInformation", [])), "MB")
            out.append({"granule": u["GranuleUR"], "url": url, "satellite": satellite, "product": short, "version": ver,
                        "daynight": u.get("DataGranule", {}).get("DayNightFlag"),
                        "size_bytes_approx": int(size * (1 << 20 if unit == "MB" else 1 << 10)) if size else None})
        if len(items) < page_size:
            break
        page += 1
    return out


# --------------------------------------------------------------------------- download (Earthdata Login)
def credentials_status() -> dict:
    tok = bool(os.getenv("EARTHDATA_TOKEN"))
    netrc = any((Path.home() / n).exists() for n in (".netrc", "_netrc"))
    return {"configured": tok or netrc, "method": "token" if tok else ("netrc" if netrc else None),
            "how": "Set EARTHDATA_TOKEN (Earthdata Login > Generate Token) in the backend environment, or add "
                   "'machine urs.earthdata.nasa.gov login <user> password <pass>' to ~/.netrc. Never commit either."}


def _session():
    import requests
    s = requests.Session()
    tok = os.getenv("EARTHDATA_TOKEN")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    s.headers["User-Agent"] = "PyroScope/1.0"
    return s


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"granules": {}}


def _save_manifest(m: dict):
    GRANULE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=1), encoding="utf-8")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _valid_hdf5(p: Path) -> bool:
    try:
        import h5py
        with h5py.File(p, "r"):
            return True
    except Exception:
        return False


def download(granules: list[dict], session=None, retries: int = 4, sleep=time.sleep, log=print) -> dict:
    """Resumable, de-duplicated download. A file is accepted only if it opens as HDF5/NetCDF4 and its size is within
    2 % of the CMR size (CMR publishes MB with rounding; it does not publish checksums, so the SHA-256 of the accepted
    file is recorded for later integrity checks)."""
    from .acquire import _download
    if session is None and not credentials_status()["configured"]:
        raise PermissionError("Earthdata Login not configured. " + credentials_status()["how"])
    s = session or _session()
    m = manifest()
    stats = {"downloaded": 0, "already_present": 0, "corrupt": 0, "failed": 0}
    for g in granules:
        name = g["granule"] + ".nc"
        dest = GRANULE_DIR / g["product"] / name
        rec = m["granules"].get(g["granule"])
        if rec and rec.get("status") == "ok" and dest.exists() and _sha256(dest) == rec["sha256"]:
            stats["already_present"] += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".nc.part")
        try:
            _download(g["url"], tmp, None, s, retries, sleep, log)
        except Exception as exc:
            stats["failed"] += 1
            m["granules"][g["granule"]] = {**g, "status": "download_failed", "error": f"{type(exc).__name__}: {exc}"}
            continue
        size = tmp.stat().st_size
        approx = g.get("size_bytes_approx")
        if (approx and abs(size - approx) > 0.02 * approx + 4096) or not _valid_hdf5(tmp):
            tmp.unlink(missing_ok=True)
            stats["corrupt"] += 1
            m["granules"][g["granule"]] = {**g, "status": "corrupt", "bytes": size}
            continue
        tmp.replace(dest)
        m["granules"][g["granule"]] = {**g, "status": "ok", "bytes": size, "sha256": _sha256(dest), "path": str(dest.relative_to(RAW)),
                                       "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        stats["downloaded"] += 1
    _save_manifest(m)
    return stats


# --------------------------------------------------------------------------- conversion
def _find(h, name):
    """Dataset by name anywhere in the file (root or nested groups)."""
    if name in h:
        return h[name]
    found = []
    h.visititems(lambda k, v: found.append(v) if k.split("/")[-1] == name and hasattr(v, "shape") else None)
    return found[0] if found else None


def _arr(ds, n):
    if ds is None:
        return np.full(n, np.nan)
    a = ds[()].astype("float64")
    fv = ds.attrs.get("_FillValue")
    if fv is not None:
        a = np.where(a == np.asarray(fv).astype("float64").ravel()[0], np.nan, a)
    return a


def _attr(h, key):
    v = h.attrs.get(key)
    if v is None:
        return None
    if isinstance(v, bytes):
        return v.decode()
    if isinstance(v, np.ndarray):
        v = v.ravel()[0]
        return v.decode() if isinstance(v, bytes) else str(v)
    return str(v)


def granule_pixels(path: Path) -> pd.DataFrame:
    """Fire pixels of one granule as FIRMS-like rows (product_type 750m). Never invents pixels: an empty FP table
    gives an empty frame."""
    import h5py
    parts = path.name.split(".")
    if len(parts) < 4 or parts[0] not in PREFIX_SAT or not parts[1].startswith("A"):
        raise ValueError(f"unexpected granule name {path.name}; expected VNP14|VJ114|VJ214.AYYYYDDD.HHMM.VVV.*")
    sat = PREFIX_SAT[parts[0]]
    day = datetime.strptime(parts[1][1:], "%Y%j").date()
    hhmm = parts[2]
    cols = ["latitude", "longitude", "acq_date", "acq_time", "satellite", "instrument", "confidence", "confidence_pct", "frp",
            "daynight", "version", "source_product", "granule"]
    with h5py.File(path, "r") as h:
        lat_ds = _find(h, "FP_latitude")
        if lat_ds is None or lat_ds.shape[0] == 0:
            return pd.DataFrame(columns=cols)
        n = lat_ds.shape[0]
        lat, lon = _arr(lat_ds, n), _arr(_find(h, "FP_longitude"), n)
        frp, pct = _arr(_find(h, "FP_power"), n), _arr(_find(h, "FP_confidence"), n)
        sza = _arr(_find(h, "FP_SolZenAng"), n)
        line, samp = _arr(_find(h, "FP_line"), n), _arr(_find(h, "FP_sample"), n)
        fm = _find(h, "fire mask")
        cls = np.full(n, np.nan)
        if fm is not None and np.isfinite(line).all() and np.isfinite(samp).all():
            mask = fm[()]
            li, si = line.astype(int), samp.astype(int)
            okix = (li >= 0) & (li < mask.shape[0]) & (si >= 0) & (si < mask.shape[1])
            cls[okix] = mask[li[okix], si[okix]]
        dnf = (_attr(h, "DayNightFlag") or "").strip().lower()
    conf = np.array([CLASS.get(int(c)) if np.isfinite(c) else None for c in cls], dtype=object)
    # fallback when the mask is unavailable: MOD14 C6 percentage bands (low < 30, nominal 30-79, high >= 80)
    nomask = pd.isna(conf)
    conf[nomask] = np.where(pct[nomask] >= 80, "h", np.where(pct[nomask] >= 30, "n", "l"))
    dn = np.where(np.isfinite(sza), np.where(sza < DAY_SZA, "D", "N"), "D" if dnf.startswith("day") else ("N" if dnf.startswith("night") else "U"))
    ok = np.isfinite(lat) & np.isfinite(lon) & (np.abs(lat) <= 90) & (np.abs(lon) <= 180)
    df = pd.DataFrame({"latitude": lat, "longitude": lon, "acq_date": day.isoformat(), "acq_time": hhmm, "satellite": sat,
                       "instrument": "VIIRS", "confidence": conf, "confidence_pct": pct, "frp": frp, "daynight": dn,
                       "version": f"{parts[0]}.{parts[3]}", "source_product": "750m", "granule": ".".join(parts[:5])})
    return df[ok].reset_index(drop=True)


def convert(paths: list[Path] | None = None, bbox=AOI_BBOX, out: Path | None = None, log=print) -> Path | None:
    """Convert downloaded granules to one FIRMS-like CSV in data/raw (picked up by the normal ingest)."""
    paths = paths or sorted(GRANULE_DIR.glob("*/*.nc"))
    if not paths:
        raise FileNotFoundError(f"no granules in {GRANULE_DIR}")
    frames = [granule_pixels(p) for p in paths]
    df = pd.concat([f for f in frames if len(f)], ignore_index=True) if any(len(f) for f in frames) else pd.DataFrame()
    if df.empty:
        log("[750m] granules contain no fire pixels")
        return None
    w, s, e, n = bbox
    df = df[df["longitude"].between(w, e) & df["latitude"].between(s, n)]
    df = df.drop_duplicates(["granule", "latitude", "longitude"])
    sats = "_".join(sorted(df["satellite"].str.replace(" ", "").str.lower().unique()))
    out = out or RAW / f"viirs750_{sats}_{df['acq_date'].min()}_{df['acq_date'].max()}.csv"
    df.to_csv(out, index=False)
    out.with_suffix(".json").write_text(json.dumps({"product_type": "750m", "granules": int(len(paths)), "rows": int(len(df)),
                                                    "source": "LP DAAC VNP14/VJ114/VJ214 Collection 2 L2 swath",
                                                    "converted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=1))
    log(f"[750m] {len(df):,} fire pixels from {len(paths)} granules -> {out.name}")
    return out


def status() -> dict:
    m = manifest()
    gr = m.get("granules", {})
    ok = [g for g in gr.values() if g.get("status") == "ok"]
    return {"credentials": credentials_status(), "granules_downloaded": len(ok),
            "granules_failed": sum(1 for g in gr.values() if g.get("status") != "ok"),
            "by_product": pd.Series([g["product"] for g in ok]).value_counts().to_dict() if ok else {},
            "products": {s: {"short_name": p, "version": v} for s, (p, v) in PRODUCTS.items()},
            "coverage_note": "Downloaded granules cover only the requested dates and swaths; they are not complete India coverage unless every granule of every day was fetched."}


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    if not a or a[0] == "status":
        print(json.dumps(status(), indent=1))
    elif a[0] == "search":
        g = search(a[1], a[2], a[3])
        print(json.dumps(g[:5], indent=1), f"\n{len(g)} granules")
    elif a[0] == "fetch":   # fetch <satellite> <start> <end>
        print(download(search(a[1], a[2], a[3])))
        convert()
    else:
        raise SystemExit("usage: python -m app.viirs750 [status|search SAT START END|fetch SAT START END]")
