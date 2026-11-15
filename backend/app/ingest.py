"""Discovery, validation, cleaning and standardisation of FIRMS active-fire CSVs.

Every original record that passes structural validation is preserved (one row per
detection) in Parquet under data/processed/hotspots/<source>/. Nothing is merged or
de-duplicated across sensors; only exact duplicate rows inside one source are dropped.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as pads
import pyarrow.parquet as pq

from . import grid
from .config import (ARCHIVE_DIRS, CLASS_NAMES, HOTSPOTS, MODIS_CONF_BINS, PROCESSED, RAW, ROOT, SAT_INSTRUMENT, UPLOADS,
                     VIIRS_CONF_SCORE)

AGG_DIR = PROCESSED / "agg"
AGG_DIR.mkdir(exist_ok=True)
REGISTRY = PROCESSED / "datasets.json"
CHUNK = 600_000

SAT_ALIASES = {
    "terra": "Terra", "t": "Terra", "aqua": "Aqua", "a": "Aqua",
    "n": "Suomi NPP", "snpp": "Suomi NPP", "npp": "Suomi NPP", "suomi npp": "Suomi NPP", "suomi-npp": "Suomi NPP",
    "1": "NOAA-20", "n20": "NOAA-20", "noaa-20": "NOAA-20", "noaa20": "NOAA-20", "j1": "NOAA-20",
    "2": "NOAA-21", "n21": "NOAA-21", "noaa-21": "NOAA-21", "noaa21": "NOAA-21", "j2": "NOAA-21",
}
REQUIRED = ["latitude", "longitude", "acq_date", "acq_time"]
STR_COLS = {c: "string" for c in ["acq_date", "acq_time", "satellite", "instrument", "confidence", "version", "daynight"]}

STD_COLUMNS = [
    "latitude", "longitude", "acq_date", "acq_time", "timestamp_utc", "satellite", "instrument", "product_type",
    "confidence_raw", "confidence_class", "confidence_score", "frp_mw", "daynight", "scan", "track",
    "pixel_area_km2", "anomaly_type", "brightness_k", "bright_t31_k", "dataset_version", "source_kind",
    "source_file", "cell_id",
]


# --------------------------------------------------------------------------- discovery
def discover_sources() -> list[dict]:
    """Repository archives (DL_FIRE_*.zip or loose CSVs) plus user uploads."""
    out = []
    from .acquire import lfs_pointer
    for z in sorted(z for d in ARCHIVE_DIRS for z in d.glob("*.zip")):
        ptr = lfs_pointer(z)
        if ptr:
            out.append({"key": z.stem, "origin": "repository", "container": str(z), "member": None, "bytes": 0, "lfs_pointer": ptr,
                        "error": f"Git LFS pointer (archive of {ptr.get('size', 0) / 1e6:.1f} MB not downloaded): run `git lfs pull` "
                                 "or `python -m app.acquire lfs`"})
            continue
        try:
            with zipfile.ZipFile(z) as zf:
                for info in zf.infolist():
                    if info.filename.lower().endswith(".csv"):
                        out.append({"key": Path(info.filename).stem, "origin": "repository", "container": str(z),
                                    "member": info.filename, "bytes": info.file_size})
        except zipfile.BadZipFile:
            # e.g. a Git LFS pointer file that was never pulled
            out.append({"key": z.stem, "origin": "repository", "container": str(z), "member": None, "bytes": 0,
                        "error": "Not a valid zip (Git LFS pointer? run `git lfs pull`)"})
    for c in sorted(list(ROOT.glob("fire_*.csv")) + list(RAW.glob("*.csv"))):
        side = c.with_suffix(".json")
        out.append({"key": c.stem, "origin": "repository", "container": str(c), "member": None, "bytes": c.stat().st_size,
                    "hint": json.loads(side.read_text()) if side.exists() else {}})
    for c in sorted(UPLOADS.glob("*.csv")):
        meta = {}
        side = c.with_suffix(".json")
        if side.exists():
            meta = json.loads(side.read_text())
        out.append({"key": "upload_" + c.stem, "origin": "upload", "container": str(c), "member": None,
                    "bytes": c.stat().st_size, "hint": meta})
    return out


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}


def _save_registry(reg: dict):
    REGISTRY.write_text(json.dumps(reg, indent=1, default=str))


# --------------------------------------------------------------------------- standardisation
def standardise(raw: pd.DataFrame, source_file: str, hint: dict | None = None):
    """Return (standardised frame, quality counters). Pure function; easy to test."""
    hint = hint or {}
    q = {"rows_read": int(len(raw))}
    df = raw.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")

    lat = pd.to_numeric(df["latitude"], errors="coerce")
    lon = pd.to_numeric(df["longitude"], errors="coerce")
    bad_coord = lat.isna() | lon.isna() | (lat.abs() > 90) | (lon.abs() > 180)

    date = pd.to_datetime(df["acq_date"].astype("string").str.strip(), format="%Y-%m-%d", errors="coerce")
    t = df["acq_time"].astype("string").str.strip().str.replace(":", "", regex=False).str.zfill(4)
    hh = pd.to_numeric(t.str[:2], errors="coerce").astype("float64")
    mm = pd.to_numeric(t.str[2:4], errors="coerce").astype("float64")
    bad_time = date.isna() | hh.isna() | mm.isna() | (hh > 23) | (mm > 59) | (t.str.len() != 4).fillna(True).astype(bool)
    bad_time |= (date < "2000-01-01") | (date > pd.Timestamp.now(tz=None) + pd.Timedelta(days=2))

    sat_raw = df["satellite"].astype("string").str.strip().str.lower() if "satellite" in df else pd.Series(pd.NA, index=df.index, dtype="string")
    sat = sat_raw.map(SAT_ALIASES)
    if hint.get("satellite"):
        sat = sat.fillna(hint["satellite"])
    bad_sat = sat.isna()

    q["dropped_invalid_coordinates"] = int(bad_coord.sum())
    q["dropped_invalid_timestamp"] = int((bad_time & ~bad_coord).sum())
    q["dropped_unknown_sensor"] = int((bad_sat & ~bad_coord & ~bad_time).sum())
    keep = ~(bad_coord | bad_time | bad_sat)
    df, lat, lon, date, t, hh, mm, sat = (x[keep] for x in (df, lat, lon, date, t, hh, mm, sat))

    instrument = sat.map(SAT_INSTRUMENT)
    if "instrument" in df:
        q["instrument_relabelled"] = int((df["instrument"].astype("string").str.strip().str.upper() != instrument).sum())
    is_modis = (instrument == "MODIS").to_numpy()
    vprod = hint.get("product_type") or "375m"
    if "source_product" in df:  # e.g. rows converted from VNP14 750 m granules
        sp = df["source_product"].astype("string").str.strip().str.lower()
        vprod = np.where(sp.isin(["375m", "750m"]), sp.fillna("375m"), vprod)
    product = np.where(is_modis, "1km", vprod)
    if hint.get("product_type") == "1km" and (~is_modis).any():
        raise ValueError("1km product hint given for VIIRS rows")

    conf_raw = df["confidence"].astype("string").str.strip() if "confidence" in df else pd.Series(pd.NA, index=df.index, dtype="string")
    conf_num = pd.to_numeric(conf_raw, errors="coerce").astype("float64")
    letter = conf_raw.str.lower().str[:1]
    score = np.where(is_modis, conf_num / 100.0, letter.map(VIIRS_CONF_SCORE).astype("float64"))
    lo, hi = MODIS_CONF_BINS
    modis_cls = np.select([conf_num < lo, conf_num <= hi, conf_num > hi], ["low", "nominal", "high"], default="")
    cls = np.where(is_modis, modis_cls, letter.map(CLASS_NAMES).fillna("").astype(str))
    cls = pd.Series(cls, index=df.index).replace("", pd.NA).where(pd.notna(score), pd.NA)
    q["confidence_missing"] = int(pd.isna(score).sum())

    def num(col):
        return pd.to_numeric(df[col], errors="coerce").astype("float64") if col in df else pd.Series(np.nan, index=df.index)

    frp = num("frp")
    q["frp_missing"] = int(frp.isna().sum())
    bad_frp = frp < 0
    q["frp_invalid_negative"] = int(bad_frp.sum())
    frp = frp.mask(bad_frp)
    q["frp_extreme_gt_10000MW"] = int((frp > 10000).sum())
    scan, track = num("scan"), num("track")
    bad_geom = (scan <= 0) | (track <= 0)
    q["scan_track_invalid"] = int(bad_geom.sum())
    scan, track = scan.mask(bad_geom), track.mask(bad_geom)
    bright = num("brightness") if "brightness" in df else num("bright_ti4")
    bt31 = num("bright_t31") if "bright_t31" in df else num("bright_ti5")
    q["brightness_outside_200_700K"] = int(((bright < 200) | (bright > 700)).sum())

    dn = df["daynight"].astype("string").str.strip().str.upper().str[:1] if "daynight" in df else pd.Series(pd.NA, index=df.index, dtype="string")
    dn = dn.where(dn.isin(["D", "N"]))
    q["daynight_missing"] = int(dn.isna().sum())
    if "type" in df:
        atype = pd.to_numeric(df["type"], errors="coerce").astype("Int8")
    else:
        atype = pd.Series(pd.NA, index=df.index, dtype="Int8")
    q["anomaly_type_missing"] = int(atype.isna().sum())

    ts = date + pd.to_timedelta(hh.astype("int64") * 60 + mm.astype("int64"), unit="m")
    version = df["version"].astype("string").str.strip() if "version" in df else pd.Series(pd.NA, index=df.index, dtype="string")
    kind = np.where(version.str.upper().str.contains("NRT", na=False), "nrt", "archive")
    if hint.get("origin") == "upload":
        kind = np.char.add("upload-", kind.astype(str))

    out = pd.DataFrame({
        "latitude": lat.astype("float64"), "longitude": lon.astype("float64"),
        "acq_date": date.dt.date, "acq_time": t.astype("string"), "timestamp_utc": ts,
        "satellite": sat.astype("string"), "instrument": instrument.astype("string"), "product_type": product,
        "confidence_raw": conf_raw, "confidence_class": cls.astype("string"),
        "confidence_score": pd.Series(score, index=df.index).astype("float32"),
        "frp_mw": frp.astype("float32"), "daynight": dn, "scan": scan.astype("float32"), "track": track.astype("float32"),
        "pixel_area_km2": (scan * track).astype("float32"), "anomaly_type": atype,
        "brightness_k": bright.astype("float32"), "bright_t31_k": bt31.astype("float32"),
        "dataset_version": version, "source_kind": kind, "source_file": source_file,
        "cell_id": grid.cell_of(lat, lon),
    })
    before = len(out)
    out = out.drop_duplicates(subset=["latitude", "longitude", "timestamp_utc", "satellite", "frp_mw", "confidence_raw"])
    q["duplicates_removed"] = int(before - len(out))
    q["rows_kept"] = int(len(out))
    return out[STD_COLUMNS], q


def aggregate_daily(std: pd.DataFrame) -> pd.DataFrame:
    """Daily cell x satellite x day/night summary. FRP is kept separate from counts."""
    t = std["anomaly_type"]
    d = pd.DataFrame({
        "acq_date": pd.to_datetime(std["acq_date"]), "cell_id": std["cell_id"].to_numpy(),
        "satellite": stream_of(std).to_numpy(), "daynight": std["daynight"].fillna("U").astype(str).to_numpy(),
        "n": 1,
        "n_veg": (t.isna() | (t == 0)).astype("int32").to_numpy(),
        "n_static": (t == 2).fillna(False).astype("int32").to_numpy(),
        "n_typed": t.notna().astype("int32").to_numpy(),
        "n_low": (std["confidence_class"] == "low").fillna(False).astype("int32").to_numpy(),
        "n_high": (std["confidence_class"] == "high").fillna(False).astype("int32").to_numpy(),
        "frp_sum": std["frp_mw"].fillna(0).astype("float64").to_numpy(),
        "frp_n": std["frp_mw"].notna().astype("int32").to_numpy(),
        "frp_max": std["frp_mw"].astype("float64").to_numpy(),
        "area_sum": std["pixel_area_km2"].fillna(0).astype("float64").to_numpy(),
    })
    return regroup_daily(d)


def stream_of(std: pd.DataFrame) -> pd.Series:
    """Aggregation stream: the satellite name for its default product (MODIS 1 km, VIIRS 375 m),
    '<satellite> 750m' for the VIIRS 750 m product, so 375 m and 750 m counts never mix."""
    sat = std["satellite"].astype(str)
    is750 = (std["product_type"].astype(str) == "750m").to_numpy()
    return pd.Series(np.where(is750, sat + " 750m", sat), index=std.index)


def regroup_daily(d: pd.DataFrame) -> pd.DataFrame:
    keys = ["acq_date", "cell_id", "satellite", "daynight"]
    agg = {c: "sum" for c in d.columns if c not in keys}
    agg["frp_max"] = "max"
    return d.groupby(keys, sort=False, observed=True).agg(agg).reset_index()


def _lst_hist(std: pd.DataFrame) -> pd.DataFrame:
    """Local-solar-time histogram of overpasses actually present in the data."""
    ts = pd.to_datetime(std["timestamp_utc"])
    lst = (ts.dt.hour + ts.dt.minute / 60.0 + std["longitude"].to_numpy() / 15.0) % 24
    h = pd.DataFrame({"satellite": std["satellite"].astype(str).to_numpy(), "daynight": std["daynight"].fillna("U").astype(str).to_numpy(),
                      "lst_bin": (np.floor(lst * 2) / 2).to_numpy(), "n": 1})
    return h.groupby(["satellite", "daynight", "lst_bin"]).n.sum().reset_index()


# --------------------------------------------------------------------------- processing
def _open_source(src: dict):
    if src.get("member"):
        return zipfile.ZipFile(src["container"]).open(src["member"])
    return open(src["container"], "rb")


def process_source(src: dict, log=print) -> dict:
    key = src["key"]
    out_dir = HOTSPOTS / key
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    hint = dict(src.get("hint") or {}, origin=src["origin"])
    totals: dict[str, int] = {}
    aggs, hists, versions = [], [], {}
    sats: dict[str, dict] = {}
    products: set = set()
    name = src.get("member") or Path(src["container"]).name
    with _open_source(src) as fh:
        for i, raw in enumerate(pd.read_csv(fh, chunksize=CHUNK, dtype=STR_COLS, low_memory=False)):
            std, q = standardise(raw, name, hint)
            for k, v in q.items():
                totals[k] = totals.get(k, 0) + v
            if len(std):
                pq.write_table(pa.Table.from_pandas(std, preserve_index=False), out_dir / f"part-{i:04d}.parquet",
                               compression="zstd", row_group_size=100_000)
                aggs.append(aggregate_daily(std))
                products.update(std["product_type"].astype(str).unique().tolist())
                hists.append(_lst_hist(std))
                for v, n in std["dataset_version"].fillna("unknown").value_counts().items():
                    versions[v] = versions.get(v, 0) + int(n)
                for s, g in std.groupby("satellite"):
                    rec = sats.setdefault(s, {"rows": 0, "first": str(g["acq_date"].min()), "last": str(g["acq_date"].max())})
                    rec["rows"] += len(g)
                    rec["first"] = min(rec["first"], str(g["acq_date"].min()))
                    rec["last"] = max(rec["last"], str(g["acq_date"].max()))
            log(f"[ingest] {key}: chunk {i} -> {totals.get('rows_kept', 0):,} rows kept")
    if aggs:
        regroup_daily(pd.concat(aggs, ignore_index=True)).to_parquet(AGG_DIR / f"{key}.parquet", index=False)
        pd.concat(hists).groupby(["satellite", "daynight", "lst_bin"]).n.sum().reset_index().to_parquet(AGG_DIR / f"{key}.lst.parquet", index=False)
    rec = {
        "key": key, "origin": src["origin"], "file": name, "container": Path(src["container"]).name,
        "bytes": src.get("bytes"), "quality": totals, "versions": versions, "satellites": sats,
        "product_types": sorted(products),
        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "has_anomaly_type": totals.get("anomaly_type_missing", 0) < totals.get("rows_kept", 0),
    }
    reg = load_registry()
    reg[key] = rec
    _save_registry(reg)
    return rec


def process_all(only_new: bool = False, log=print) -> dict:
    reg = load_registry()
    results = {}
    for src in discover_sources():
        if src.get("error"):
            results[src["key"]] = {"key": src["key"], "error": src["error"]}
            continue
        if only_new and src["key"] in reg and not reg[src["key"]].get("error") and (HOTSPOTS / src["key"]).exists():
            continue
        try:
            results[src["key"]] = process_source(src, log=log)
        except Exception as exc:  # record and continue: one bad file must not block the others
            rec = {"key": src["key"], "origin": src["origin"], "file": src.get("member") or Path(src["container"]).name,
                   "error": f"{type(exc).__name__}: {exc}", "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            reg = load_registry()
            reg[src["key"]] = rec
            _save_registry(reg)
            results[src["key"]] = rec
            log(f"[ingest] {src['key']} FAILED: {exc}")
    return results


# --------------------------------------------------------------------------- queries on preserved records
def hotspot_dataset():
    files = [str(p) for p in HOTSPOTS.glob("*/*.parquet")]
    return pads.dataset(files, format="parquet") if files else None


def query_hotspots(start, end, bbox=None, satellites=None, limit=6000, min_conf=None, daynight=None):
    """Original records for a date range / bbox. Returns (frame, total_matching)."""
    ds = hotspot_dataset()
    if ds is None:
        return pd.DataFrame(columns=STD_COLUMNS), 0
    f = (pads.field("acq_date") >= pd.Timestamp(start).date()) & (pads.field("acq_date") <= pd.Timestamp(end).date())
    if bbox:
        w, s, e, n = bbox
        f &= (pads.field("longitude") >= w) & (pads.field("longitude") <= e) & (pads.field("latitude") >= s) & (pads.field("latitude") <= n)
    if satellites:
        f &= pads.field("satellite").isin(list(satellites))
    if daynight in ("D", "N"):
        f &= pads.field("daynight") == daynight
    if min_conf is not None:
        f &= pads.field("confidence_score") >= float(min_conf)
    df = ds.to_table(filter=f).to_pandas()
    total = len(df)
    if total > limit:
        # even, deterministic thinning (never "top by FRP", which would bias the picture)
        df = df.iloc[np.linspace(0, total - 1, limit).astype(int)]
    return df, total
