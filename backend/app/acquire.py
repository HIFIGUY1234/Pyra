"""Dataset acquisition and recovery.

* Git LFS pointer detection + verified recovery of the repository archives.
* NASA FIRMS API downloader (needs FIRMS_MAP_KEY in the environment; never hard-coded).
* VIIRS 750 m (VNP14 / VJ114 Level-2 swath) fire-pixel converter -> FIRMS-like CSV.
* Ingestion / inventory report: what is loaded, what is missing, and how to obtain it.

Nothing here fabricates observations. When a source cannot be reached the function
raises or reports the blocker; it never substitutes synthetic records.
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .config import AOI_BBOX, PROCESSED, ROOT

RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
REPORT_JSON = PROCESSED / "ingestion_report.json"
REPORT_MD = PROCESSED / "ingestion_report.md"
LFS_MEDIA = os.getenv("PYRA_LFS_MEDIA_BASE", "https://media.githubusercontent.com/media/HIFIGUY1234/Pyra/main")

# Official FIRMS temporal coverage (FIRMS Archive Download page). Used to say what is
# missing; the actual loaded coverage always comes from the records themselves.
EXPECTED = {
    "Terra": {"product": "MODIS C6.1 1 km (MCD14ML)", "firms_start": "2000-11-01", "firms_source": "MODIS_SP",
              "note": "Terra MODIS launched Dec 1999; FIRMS C6.1 starts 1 Nov 2000 (earlier MOD14 data have known quality issues)."},
    "Aqua": {"product": "MODIS C6.1 1 km (MCD14ML)", "firms_start": "2002-07-04", "firms_source": "MODIS_SP",
             "note": "Aqua MODIS fire record begins July 2002."},
    "Suomi NPP": {"product": "VIIRS C2 375 m (VNP14IMGT)", "firms_start": "2012-01-20", "firms_source": "VIIRS_SNPP_SP"},
    "NOAA-20": {"product": "VIIRS C2 375 m (VJ114IMGT)", "firms_start": "2018-04-01", "firms_source": "VIIRS_NOAA20_SP"},
    "NOAA-21": {"product": "VIIRS C2 375 m (VJ214IMGT)", "firms_start": "2024-01-17", "firms_source": "VIIRS_NOAA21_NRT",
                "note": "FIRMS distributes NOAA-21 as NRT; this repository's archive file contains NOAA-21 records from 2023-03 (pre-operational period)."},
}
VIIRS_750 = {
    "status": "not_in_firms",
    "products": {"Suomi NPP": "VNP14 (VIIRS/NPP Thermal Anomalies/Fire 6-Min L2 Swath 750 m)",
                 "NOAA-20": "VJ114 (VIIRS/JPSS1 Thermal Anomalies/Fire 6-Min L2 Swath 750 m)"},
    "facts": ["The 750 m product applies the MODIS Collection 6 fire algorithm to VIIRS M-bands and is NASA's continuity product for the MODIS 1 km record.",
              "FIRMS distributes only the 375 m VIIRS product as CSV; 750 m data are Level-2 NetCDF swath granules from LAADS DAAC / LP DAAC (Earthdata Login required)."],
    "how_to_add": "Download VNP14 granules for the AOI from LAADS DAAC, run `python -m app.acquire vnp14 <granule dir> --satellite 'Suomi NPP'` "
                  "to convert the fire-pixel tables to a FIRMS-like CSV in data/raw/, then rerun the pipeline. It is ingested as product_type=750m "
                  "and calibrated separately from 375 m.",
}


# --------------------------------------------------------------------------- Git LFS
def lfs_pointer(path: Path) -> dict | None:
    """Parse a Git LFS pointer file. Returns {'oid', 'size'} or None if `path` is real content."""
    try:
        if path.stat().st_size > 1024:
            return None
        txt = path.read_text(errors="ignore")
    except OSError:
        return None
    if not txt.startswith("version https://git-lfs.github.com/spec/"):
        return None
    out = {}
    for line in txt.splitlines():
        k, _, v = line.partition(" ")
        if k == "oid":
            out["oid"] = v.split(":", 1)[-1].strip()
        elif k == "size":
            out["size"] = int(v)
    return out or None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# Collection identifiers in FIRMS archive names (FIRMS download Readme: "C61 stands for MODIS Collection 6.1").
ARCHIVE_COLLECTIONS = {"M-C61": ("MODIS", "Collection 6.1", "MCD14ML"), "SV-C2": ("VIIRS", "Collection 2", "VNP14IMGT"),
                       "J1V-C2": ("VIIRS", "Collection 2", "VJ114IMGT"), "J2V-C2": ("VIIRS", "Collection 2", "VJ214IMGT")}
# Row-level `version` strings. FIRMS documents "<collection>" = standard processing and an NRT/RT/URT suffix for
# near-real-time sources (earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs).
VERSION_NOTES = {
    "6.1NRT": ("documented", "MODIS Collection 6.1, near-real-time processing (provisional)"),
    "6.1": ("documented", "MODIS Collection 6.1, standard processing"),
    "2.0NRT": ("pattern", "VIIRS Collection 2, near-real-time processing (provisional); follows the documented NRT-suffix convention"),
    "2": ("pattern", "VIIRS Collection 2, standard processing; follows the documented collection-only convention"),
    "6.03": ("undocumented", "found in FIRMS MODIS C6.1 standard-processing archives for 2000-2022; not defined in the FIRMS Readme or "
                             "attribute page. Kept verbatim; the collection is taken from the archive name (C6.1), not from this string."),
    "61.03": ("undocumented", "found in FIRMS MODIS C6.1 standard-processing archives from 2023-01 onward; not defined in readable FIRMS "
                              "documentation. Kept verbatim; it is NOT relabelled."),
}


def collection_info(archive_name: str, versions: dict | None = None) -> dict:
    tag = next((t for t in ARCHIVE_COLLECTIONS if f"_{t}_" in archive_name), None)
    inst, coll, prod = ARCHIVE_COLLECTIONS.get(tag, (None, None, None))
    vinfo = [{"version": v, "rows": n, "status": VERSION_NOTES.get(str(v), ("unknown", ""))[0],
              "meaning": VERSION_NOTES.get(str(v), ("unknown", "not recognised; kept verbatim"))[1]} for v, n in (versions or {}).items()]
    return {"archive_tag": tag, "instrument": inst, "collection": coll, "product": prod, "row_versions": vinfo,
            "collection_source": "archive file name (FIRMS Readme convention)" if tag else "unknown"}


CHECKSUMS = PROCESSED / "archive_checksums.json"


def cached_sha256(path: Path) -> str:
    """SHA-256 of a real archive, cached by (name, size, mtime) so the inventory does not rehash gigabytes each run."""
    st = path.stat()
    key = f"{path.name}|{st.st_size}|{int(st.st_mtime)}"
    try:
        cache = json.loads(CHECKSUMS.read_text())
    except (OSError, ValueError):
        cache = {}
    if key not in cache:
        cache = {k: v for k, v in cache.items() if not k.startswith(path.name + "|")}
        cache[key] = sha256(path)
        CHECKSUMS.write_text(json.dumps(cache, indent=1))
    return cache[key]


def archive_status(path: Path, checksum: bool = True) -> dict:
    p = lfs_pointer(path)
    if p:
        return {"file": path.name, "status": "lfs_pointer", "expected_sha256": p.get("oid"), "expected_bytes": p.get("size"),
                "bytes": path.stat().st_size, "integrity": "not_downloaded",
                "message": "Git LFS pointer, archive not downloaded. Run `git lfs pull` or `python -m app.acquire lfs`."}
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            members = [{"name": i.filename, "bytes": i.file_size,
                        "kind": "nrt" if "_nrt_" in i.filename.lower() else "archive" if "_archive_" in i.filename.lower() else "other"}
                       for i in zf.infolist()]
        if bad:
            return {"file": path.name, "status": "corrupt", "integrity": "crc_failure", "message": f"CRC failure in {bad}"}
        out = {"file": path.name, "status": "valid", "integrity": "zip_crc_ok", "bytes": path.stat().st_size, "members": members,
               "csv_members": [m["name"] for m in members if m["name"].lower().endswith(".csv")], **collection_info(path.name)}
        if checksum:
            out["sha256"] = cached_sha256(path)
        return out
    except zipfile.BadZipFile as exc:
        return {"file": path.name, "status": "corrupt", "integrity": "not_a_zip", "message": str(exc)}


LFS_REPORT = PROCESSED / "lfs_recovery_report.json"
RETRYABLE = (429, 500, 502, 503, 504)


def _download(url: str, tmp: Path, expected_size: int | None, session, retries: int, sleep, log) -> None:
    """Resumable download into `tmp` (HTTP Range); retries transient failures with exponential back-off.
    Raises on permanent failure. Never touches the destination archive."""
    last = None
    for attempt in range(retries + 1):
        have = tmp.stat().st_size if tmp.exists() else 0
        if expected_size and have > expected_size:
            tmp.unlink()
            have = 0
        if expected_size and have == expected_size:
            return
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with session.get(url, stream=True, timeout=120, headers=headers) as r:
                if r.status_code == 404:
                    raise FileNotFoundError(f"remote object not found (HTTP 404): {url}")
                if r.status_code in RETRYABLE:
                    raise ConnectionError(f"HTTP {r.status_code}")
                r.raise_for_status()
                mode = "ab" if have and r.status_code == 206 else "wb"   # server ignored Range -> restart
                with open(tmp, mode) as fh:
                    for chunk in r.iter_content(1 << 20):
                        if chunk:
                            fh.write(chunk)
            if not expected_size or tmp.stat().st_size >= expected_size:
                return
            last = ConnectionError(f"transfer interrupted at {tmp.stat().st_size} of {expected_size} bytes")
        except FileNotFoundError:
            raise
        except Exception as exc:  # network errors, timeouts, 5xx: retry
            last = exc
        if attempt < retries:
            wait = min(60, 2 ** attempt)
            log(f"[lfs] {url}: {last} - retry {attempt + 1}/{retries} in {wait}s (resuming)")
            sleep(wait)
    raise ConnectionError(f"download failed after {retries + 1} attempts: {last}")


def recover_lfs(base_url: str = LFS_MEDIA, log=print, root: Path | None = None, session=None, retries: int = 4,
                sleep=None, report_path: Path | None | bool = None) -> list[dict]:
    """Replace Git LFS pointer stubs with the real archives.

    * expected size and SHA-256 come from the pointer;
    * downloads go to `<name>.zip.part` and resume after interruption (HTTP Range);
    * transient errors are retried with back-off; a missing remote object is reported at once;
    * the archive is replaced only after size AND SHA-256 match - a valid archive is never overwritten;
    * a JSON recovery report is written."""
    import time as _time
    import requests
    root = root or ROOT
    session = session or requests.Session()
    sleep = sleep or _time.sleep
    out = []
    for z in sorted(root.glob("*.zip")):
        p = lfs_pointer(z)
        if not p:
            out.append({"file": z.name, "status": "already_present", "bytes": z.stat().st_size})
            continue
        if len(p.get("oid", "")) != 64 or "size" not in p:
            out.append({"file": z.name, "status": "invalid_pointer", "message": f"pointer lacks a sha256 oid / size: {p}"})
            continue
        tmp = z.with_suffix(".zip.part")
        url = f"{base_url.rstrip('/')}/{z.name}"
        log(f"[lfs] downloading {url} ({p['size']:,} bytes)")
        try:
            _download(url, tmp, p["size"], session, retries, sleep, log)
        except FileNotFoundError as exc:
            out.append({"file": z.name, "status": "remote_missing", "message": str(exc)})
            continue
        except Exception as exc:
            out.append({"file": z.name, "status": "download_failed", "message": str(exc),
                        "partial_bytes": tmp.stat().st_size if tmp.exists() else 0, "resumable": tmp.exists()})
            continue
        size = tmp.stat().st_size
        got = sha256(tmp)
        if size != p["size"] or got != p["oid"]:
            tmp.unlink(missing_ok=True)
            out.append({"file": z.name, "status": "checksum_mismatch", "expected": p["oid"], "got": got,
                        "expected_bytes": p["size"], "got_bytes": size})
            continue
        tmp.replace(z)
        out.append({"file": z.name, "status": "recovered", "sha256": got, "bytes": size})
    report_path = LFS_REPORT if report_path is None else report_path   # resolved at call time; False disables the report
    if report_path:
        report_path.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                           "base_url": base_url, "results": out}, indent=1))
    return out


# --------------------------------------------------------------------------- NASA FIRMS API
FIRMS_API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_SOURCES = {"MODIS_SP", "MODIS_NRT", "VIIRS_SNPP_SP", "VIIRS_SNPP_NRT", "VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"}


def firms_fetch(source: str, start: str, end: str, bbox=AOI_BBOX, day_range: int = 10, log=print, session=None) -> Path:
    """Download FIRMS records for [start, end] in DAY_RANGE windows into data/raw/.
    Requires FIRMS_MAP_KEY. Restartable: completed windows are skipped."""
    key = os.getenv("FIRMS_MAP_KEY")
    if not key:
        raise RuntimeError("FIRMS_MAP_KEY is not set. Request a free key at https://firms.modaps.eosdis.nasa.gov/api/map_key/ "
                           "and export it in the environment (never commit it).")
    if source not in FIRMS_SOURCES:
        raise ValueError(f"source must be one of {sorted(FIRMS_SOURCES)}")
    import requests
    s = session or requests.Session()
    area = ",".join(str(v) for v in bbox)
    tag = f"firms_api_{source}_{start.replace('-', '')}_{end.replace('-', '')}"
    part_dir = RAW / (tag + ".parts")
    part_dir.mkdir(exist_ok=True)
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    cur = d0
    while cur <= d1:
        n = min(day_range, (d1 - cur).days + 1)
        part = part_dir / f"{cur.isoformat()}_{n}.csv"
        if not part.exists():
            url = f"{FIRMS_API}/{key}/{source}/{area}/{n}/{cur.isoformat()}"
            r = s.get(url, timeout=180)
            if r.status_code != 200 or r.text.lstrip().lower().startswith(("invalid", "error")):
                raise RuntimeError(f"FIRMS request failed for {cur} ({r.status_code}): {r.text[:200]}")
            part.write_text(r.text)
            log(f"[firms] {source} {cur} +{n}d: {max(r.text.count(chr(10)) - 1, 0)} rows")
        cur += timedelta(days=n)
    out = RAW / f"{tag}.csv"
    frames = [pd.read_csv(p, dtype=str) for p in sorted(part_dir.glob("*.csv")) if p.stat().st_size > 0]
    frames = [f for f in frames if len(f)]
    if not frames:
        raise RuntimeError("FIRMS returned no records for the requested period/area")
    pd.concat(frames, ignore_index=True).to_csv(out, index=False)
    return out


# --------------------------------------------------------------------------- VIIRS 750 m converter
def vnp14_to_csv(granule_dir: str | Path, satellite: str, out: Path | None = None) -> Path:
    """Convert VNP14 / VJ114 750 m Level-2 NetCDF granules (fire-pixel `FP_*` arrays) into a
    FIRMS-like CSV with product_type 750m. Requires h5py (pip install h5py)."""
    import h5py
    import numpy as np
    rows = []
    files = sorted(Path(granule_dir).glob("*.nc")) + sorted(Path(granule_dir).glob("*.h5"))
    if not files:
        raise FileNotFoundError(f"no .nc/.h5 granules in {granule_dir}")
    for f in files:
        # granule name: VNP14.AYYYYDDD.HHMM.collection.production.nc
        parts = f.name.split(".")
        try:
            day = datetime.strptime(parts[1][1:], "%Y%j").date()
            hhmm = parts[2]
        except (IndexError, ValueError):
            raise ValueError(f"unexpected granule name {f.name}; expected VNP14.AYYYYDDD.HHMM.*")
        with h5py.File(f, "r") as h:
            if "FP_latitude" not in h or h["FP_latitude"].shape[0] == 0:
                continue
            g = lambda k: h[k][()] if k in h else np.full(h["FP_latitude"].shape[0], np.nan)
            lat, lon, frp, conf = g("FP_latitude"), g("FP_longitude"), g("FP_power"), g("FP_confidence")
            day_flag = g("FP_day")
            # VNP14 follows MOD14 C6: confidence is a 0-100 percentage. Fire-mask classes 7/8/9 map to l/n/h.
            vals = set(np.unique(conf[~np.isnan(conf)]).astype(int).tolist()) if np.issubdtype(conf.dtype, np.number) else set()
            if vals and vals <= {7, 8, 9}:
                conf = np.vectorize({7: "l", 8: "n", 9: "h"}.get)(conf.astype(int))
            for i in range(len(lat)):
                rows.append({"latitude": float(lat[i]), "longitude": float(lon[i]), "acq_date": day.isoformat(), "acq_time": hhmm,
                             "satellite": satellite, "instrument": "VIIRS", "confidence": conf[i], "frp": float(frp[i]),
                             "daynight": "D" if (day_flag[i] == 1) else "N", "version": f"VNP14.{parts[3] if len(parts) > 3 else '002'}",
                             "source_product": "750m"})
    if not rows:
        raise RuntimeError("granules contained no fire pixels")
    out = out or RAW / f"viirs750_{satellite.replace(' ', '').lower()}_{rows[0]['acq_date']}_{rows[-1]['acq_date']}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    out.with_suffix(".json").write_text(json.dumps({"satellite": satellite, "product_type": "750m", "source": "VNP14/VJ114 L2 swath"}))
    return out


# --------------------------------------------------------------------------- inventory report
def build_report() -> dict:
    from .ingest import discover_sources, load_registry
    archives = [archive_status(z) for z in sorted(list(ROOT.glob("*.zip")) + list(RAW.glob("*.zip")))]
    reg = load_registry()
    loaded: dict[str, dict] = {}
    products: dict[str, set] = {}
    for rec in reg.values():
        for sat, v in (rec.get("satellites") or {}).items():
            kind = "nrt" if "nrt" in rec["key"].lower() or any("NRT" in str(k) for k in (rec.get("versions") or {})) else "archive"
            L = loaded.setdefault(sat, {"archive": None, "nrt": None, "rows": 0, "versions": set()})
            cur = L[kind]
            L[kind] = {"first": min(cur["first"], v["first"]) if cur else v["first"], "last": max(cur["last"], v["last"]) if cur else v["last"],
                       "rows": (cur["rows"] if cur else 0) + v["rows"]}
            L["rows"] += v["rows"]
            L["versions"] |= set((rec.get("versions") or {}).keys())
            products.setdefault(sat, set()).update(rec.get("product_types") or [])
    sats, missing = {}, []
    for sat, exp in EXPECTED.items():
        L = loaded.get(sat)
        first = min([x["first"] for x in (L["archive"], L["nrt"]) if x], default=None) if L else None
        entry = {"expected": exp, "loaded": None if not L else {**{k: v for k, v in L.items() if k != "versions"}, "versions": sorted(L["versions"]),
                                                               "products": sorted(products.get(sat, []))}}
        if not L:
            entry["status"] = "missing"
            missing.append({"satellite": sat, "period": f"{exp['firms_start']} onward", "how": f"FIRMS Archive Download or `python -m app.acquire firms {exp['firms_source']} <start> <end>` with FIRMS_MAP_KEY"})
        elif first > exp["firms_start"]:
            entry["status"] = "partial"
            missing.append({"satellite": sat, "period": f"{exp['firms_start']} to {(date.fromisoformat(first) - timedelta(days=1)).isoformat()}",
                            "how": f"FIRMS Archive Download (MODIS C6.1 / VIIRS C2, CSV, AOI {AOI_BBOX}) or `python -m app.acquire firms {exp['firms_source']} {exp['firms_start']} {first}`"})
        else:
            entry["status"] = "complete_from_firms_start"
        if L and first and (date.fromisoformat(exp["firms_start"]) - date.fromisoformat(first)).days > 30:
            entry["pre_operational_records"] = {"first": first, "official_start": exp["firms_start"],
                                                "note": "records exist before the official FIRMS start date (pre-operational / early-mission period); "
                                                        "kept as actual observations, labelled, and not used as a calibration target"}
        sats[sat] = entry
    terra_first = (loaded.get("Terra", {}).get("archive") or {}).get("first")
    aqua_first = (loaded.get("Aqua", {}).get("archive") or {}).get("first")
    viirs_first = min([(loaded.get(s, {}).get("archive") or {}).get("first") or "9999" for s in ("Suomi NPP",)])
    days_before = lambda a, b: (date.fromisoformat(b) - date.fromisoformat(a)).days if a and b and b != "9999" else 0
    terra_only = days_before(terra_first, aqua_first) >= 180       # needs a real Terra-only era, not a few days
    pre_viirs = days_before(terra_first, viirs_first) >= 365        # the seam test needs >= 12 months before VIIRS
    caps = {
        "terra_only_era_loaded": terra_only,
        "pre_viirs_modis_loaded": pre_viirs,
        "real_morning_gap_correction": "possible" if terra_only else "blocked: no Terra-only (Nov 2000 - Jun 2002) records loaded",
        "real_2012_seam_test": "possible" if pre_viirs else "blocked: fewer than 12 months of MODIS records precede the first VIIRS record",
        "viirs_750m": "loaded" if any("750m" in p for p in products.values()) else "unavailable",
        "noaa20": "loaded" if "NOAA-20" in loaded else "missing",
    }
    # missing observation periods (runs of >= gap_rule_min_run_days days without any record inside the span)
    try:
        from . import store
        spans = store.spans()
    except Exception:
        spans = {}
    for sat, e in sats.items():
        sp = spans.get(sat) or {}
        days = sorted(sp.get("gap_days") or [])
        periods = []
        for d in days:
            if periods and (date.fromisoformat(d) - date.fromisoformat(periods[-1][1])).days == 1:
                periods[-1][1] = d
            else:
                periods.append([d, d])
        e["gaps"] = {"missing_days": len(days), "missing_periods": periods, "rule_min_run_days": sp.get("gap_rule_min_run_days"),
                     "days_in_span": sp.get("days_in_span"), "days_with_detections": sp.get("days_with_detections")}

    def qstatus(q: dict) -> str:
        if not q:
            return "unknown"
        read = max(q.get("rows_read", 0), 1)
        dropped = q.get("dropped_invalid_coordinates", 0) + q.get("dropped_invalid_timestamp", 0) + q.get("dropped_unknown_sensor", 0)
        return "good" if dropped / read < 0.001 else "warning" if dropped / read < 0.01 else "poor"
    rep = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "aoi_bbox": AOI_BBOX, "archives": archives,
           "sources": [{k: v for k, v in s.items() if k != "hint"} for s in discover_sources()], "satellites": sats,
           "missing": missing, "capabilities": caps, "viirs_750m": VIIRS_750,
           "registry": {k: {"file": v.get("file"), "rows_kept": (v.get("quality") or {}).get("rows_kept"), "versions": v.get("versions"),
                            "satellites": v.get("satellites"), "product_types": v.get("product_types"), "processed_at": v.get("processed_at"),
                            "container": v.get("container"), "kind": "nrt" if "nrt" in k.lower() else "archive",
                            "quality": v.get("quality"), "quality_status": qstatus(v.get("quality") or {}),
                            "processing_status": "error" if v.get("error") else "processed",
                            "collection": collection_info(v.get("container") or v.get("file") or "", v.get("versions")),
                            "error": v.get("error")} for k, v in reg.items()}}
    REPORT_JSON.write_text(json.dumps(rep, indent=1, default=str))
    REPORT_MD.write_text(report_markdown(rep), encoding="utf-8")
    return rep


def report_markdown(rep: dict) -> str:
    L = [f"# PyroScope ingestion report", f"Generated {rep['generated_at']} - AOI bbox {rep['aoi_bbox']}", "", "## Archives", "",
         "| File | Status | Collection | Size | SHA-256 | Members |", "|---|---|---|---|---|---|"]
    for a in rep["archives"]:
        mem = ", ".join(f"{m['name']} ({m['kind']}, {m['bytes'] / 1e6:.1f} MB)" for m in a.get("members", []) if m["kind"] != "other")
        L.append(f"| {a['file']} | {a['status']} ({a.get('integrity', '-')}) | {a.get('instrument') or '-'} {a.get('collection') or ''} | "
                 f"{(a.get('bytes') or 0) / 1e6:.1f} MB | `{(a.get('sha256') or a.get('expected_sha256') or '-')[:16]}...` | {mem or a.get('message', '')} |")
    L += ["", "## Sources (per CSV member)", "", "| Source | Kind | Rows kept | Row versions | Quality | Dropped coords / time | Duplicates removed | Missing FRP / confidence |",
          "|---|---|---|---|---|---|---|---|"]
    for k, r in rep["registry"].items():
        q = r.get("quality") or {}
        vers = "; ".join(f"{v['version']} ({v['status']})" for v in (r.get("collection") or {}).get("row_versions", []))
        L.append(f"| {k} | {r.get('kind')} | {r.get('rows_kept') or 0:,} | {vers or '-'} | {r.get('quality_status')} | "
                 f"{q.get('dropped_invalid_coordinates', 0)} / {q.get('dropped_invalid_timestamp', 0)} | {q.get('duplicates_removed', 0)} | "
                 f"{q.get('frp_missing', 0)} / {q.get('confidence_missing', 0)} |")
    L += ["", "Row `version` strings are kept verbatim. `6.03` / `61.03` (MODIS) are not defined in readable FIRMS documentation; the "
          "collection (C6.1) is taken from the archive name per the FIRMS download Readme. NRT rows are provisional and never used for calibration."]
    L += ["", "## Satellite coverage (loaded vs FIRMS availability)", "", "| Satellite | Status | Archive period | NRT period | Rows | Products | FIRMS starts |",
          "|---|---|---|---|---|---|---|"]
    for sat, e in rep["satellites"].items():
        ld = e["loaded"] or {}
        per = lambda k: f"{ld[k]['first']} - {ld[k]['last']}" if ld.get(k) else "-"
        L.append(f"| {sat} | {e['status']}{' (pre-operational records from ' + e['pre_operational_records']['first'] + ')' if e.get('pre_operational_records') else ''} | {per('archive')} | {per('nrt')} | {ld.get('rows', 0):,} | {', '.join(ld.get('products', [])) or '-'} | {e['expected']['firms_start']} |")
    L += ["", "## Missing observation periods (days with no record inside the sensor span; rule from the daily summaries)", "", "| Satellite | Missing days | Periods |", "|---|---|---|"]
    for sat, e in rep["satellites"].items():
        g = e.get("gaps") or {}
        L.append(f"| {sat} | {g.get('missing_days', 0)} | {', '.join(f'{a} to {b}' for a, b in g.get('missing_periods', [])) or '-'} |")
    L += ["", "## Missing data", ""] + [f"- **{m['satellite']}** {m['period']}: {m['how']}" for m in rep["missing"]]
    L += ["", "## Scientific capabilities with the loaded data", ""] + [f"- {k}: **{v}**" for k, v in rep["capabilities"].items()]
    L += ["", "## VIIRS 750 m", ""] + [f"- {f}" for f in rep["viirs_750m"]["facts"]] + [f"- To add: {rep['viirs_750m']['how_to_add']}"]
    return "\n".join(L) + "\n"


def main(argv=None):
    import sys
    a = argv if argv is not None else sys.argv[1:]
    cmd = a[0] if a else "report"
    if cmd == "lfs":
        print(json.dumps(recover_lfs(), indent=1))
    elif cmd == "firms":
        print(firms_fetch(a[1], a[2], a[3]))
    elif cmd == "vnp14":
        sat = a[a.index("--satellite") + 1] if "--satellite" in a else "Suomi NPP"
        print(vnp14_to_csv(a[1], sat))
    else:
        rep = build_report()
        print(REPORT_MD.read_text(encoding="utf-8"))
        return rep


if __name__ == "__main__":
    main()
