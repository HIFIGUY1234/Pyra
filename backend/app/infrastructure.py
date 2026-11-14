"""Critical-infrastructure layers from OpenStreetMap (Overpass API) or administrator uploads.

Source: OpenStreetMap contributors, ODbL 1.0. Each category is a separate tagged query over India
(``area["ISO3166-1"="IN"][admin_level=2]``). Ways/relations are reduced to their centre point. OSM completeness
varies by region and category and is not an official register: a missing facility is "not mapped", never
"not present", and categories that failed to download are reported as unavailable, never as zero.

Linear networks (roads, railways, transmission lines) are not loaded: India-wide they are tens of millions of
vertices; they need a planet extract (Geofabrik) and a vector tile pipeline. Reported as not available.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
import pandas as pd

from . import grid
from .config import AOI_BBOX, AUX

INFRA_DIR = AUX / "infrastructure"
POINTS = INFRA_DIR / "infrastructure_points.parquet"
MANIFEST = INFRA_DIR / "manifest.json"
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
           "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
CATEGORIES = {
    "hospital": ['nwr["amenity"="hospital"]'],
    "clinic": ['nwr["amenity"="clinic"]'],
    "fire_station": ['nwr["amenity"="fire_station"]'],
    "police": ['nwr["amenity"="police"]'],
    "school": ['nwr["amenity"="school"]'],
    "power_substation": ['nwr["power"="substation"]'],
    "power_plant": ['nwr["power"="plant"]'],
    "railway_station": ['node["railway"="station"]'],
    "water_works": ['nwr["man_made"="water_works"]', 'nwr["man_made"="wastewater_plant"]'],
    "communications": ['nwr["man_made"="mast"]["tower:type"="communication"]', 'nwr["man_made"="tower"]["tower:type"="communication"]'],
    "industrial_site": ['nwr["landuse"="industrial"]["name"]'],
}
NOT_LOADED = {"roads": "linear network; needs a Geofabrik extract", "railways": "linear network; needs a Geofabrik extract",
              "transmission_lines": "linear network; needs a Geofabrik extract",
              "residential_settlements": "use the WorldPop population layer instead of OSM polygons"}
LICENCE = "Open Database License (ODbL) 1.0 - (c) OpenStreetMap contributors"


def _query(cat: str) -> str:
    body = "".join(f"{q}(area.a);" for q in CATEGORIES[cat])
    return f'[out:json][timeout:300];area["ISO3166-1"="IN"][admin_level=2]->.a;({body});out center tags;'


def fetch_category(cat: str, session=None, retries: int = 6, sleep=time.sleep, log=print) -> pd.DataFrame:
    import requests
    s = session or requests.Session()
    last = None
    for attempt in range(retries):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            r = s.post(url, data={"data": _query(cat)}, timeout=360, headers={"User-Agent": "PyroScope/1.0"})
            if r.status_code in (429, 502, 503, 504):
                raise IOError(f"HTTP {r.status_code} from {url}")
            r.raise_for_status()
            els = r.json().get("elements", [])
            rows = []
            for e in els:
                lat = e.get("lat", (e.get("center") or {}).get("lat"))
                lon = e.get("lon", (e.get("center") or {}).get("lon"))
                tags = e.get("tags", {})
                rows.append({"osm_id": f"{e['type'][0]}{e['id']}", "category": cat, "lat": lat, "lon": lon,
                             "name": tags.get("name") or tags.get("name:en")})
            log(f"[infra] {cat}: {len(rows):,} features from {url}")
            return pd.DataFrame(rows, columns=["osm_id", "category", "lat", "lon", "name"])
        except Exception as exc:  # transient: back off and try the next mirror
            last = exc
            log(f"[infra] {cat}: attempt {attempt + 1} failed ({exc}); backing off")
            sleep(min(120, 5 * 2 ** attempt))
    raise IOError(f"{cat}: all Overpass attempts failed ({last})")


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Validate coordinates, keep the AOI, drop exact duplicates (same OSM object) and co-located duplicates
    within a category (same name within ~50 m, e.g. a node and a building outline for one hospital)."""
    n0 = len(df)
    lat = pd.to_numeric(df["lat"], errors="coerce")
    lon = pd.to_numeric(df["lon"], errors="coerce")
    w, s, e, n = AOI_BBOX
    ok = lat.between(s, n) & lon.between(w, e)
    df = df[ok].assign(lat=lat[ok], lon=lon[ok])
    bad = n0 - len(df)
    df = df.drop_duplicates(["osm_id", "category"])   # one object may legitimately be in two categories
    d1 = n0 - bad - len(df)
    key = df["category"] + "|" + df["name"].fillna("#" + df["osm_id"]).str.lower() + "|" + (df["lat"] * 2000).round().astype(str) + "|" + (df["lon"] * 2000).round().astype(str)
    df = df[~key.duplicated()]
    d2 = n0 - bad - d1 - len(df)
    df = df.assign(cell_id=grid.cell_of(df["lat"].to_numpy(), df["lon"].to_numpy()))
    return df.reset_index(drop=True), {"input": n0, "invalid_or_outside_aoi": int(bad), "duplicate_osm_id": int(d1), "colocated_duplicates": int(d2), "kept": int(len(df))}


def acquire(categories=None, log=print, session=None, sleep=time.sleep) -> dict:
    INFRA_DIR.mkdir(parents=True, exist_ok=True)
    old = pd.read_parquet(POINTS) if POINTS.exists() else pd.DataFrame(columns=["osm_id", "category", "lat", "lon", "name", "cell_id"])
    man = manifest() or {"categories": {}}
    frames = [old]
    for cat in categories or CATEGORIES:
        try:
            df = fetch_category(cat, session=session, sleep=sleep, log=log)
            frames = [f[f["category"] != cat] for f in frames] + [df]
            man["categories"][cat] = {"status": "loaded", "raw_features": int(len(df)),
                                      "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "query": CATEGORIES[cat]}
        except Exception as exc:
            man["categories"].setdefault(cat, {})
            man["categories"][cat].update({"status": man["categories"][cat].get("status", "unavailable"), "last_error": str(exc)})
            log(f"[infra] {cat} unavailable: {exc}")
        sleep(3)  # be polite to the public Overpass service
    allp, stats = clean(pd.concat([f for f in frames if len(f)], ignore_index=True)) if any(len(f) for f in frames) else (frames[0], {})
    allp.to_parquet(POINTS, index=False)
    for cat in CATEGORIES:
        if cat in man["categories"] and man["categories"][cat].get("status") == "loaded":
            man["categories"][cat]["features"] = int((allp["category"] == cat).sum())
    man.update(source="OpenStreetMap via Overpass API", licence=LICENCE, coverage="India (ISO3166-1 IN), clipped to AOI bbox",
               crs="EPSG:4326", cleaning=stats, not_loaded=NOT_LOADED, updated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
               completeness_note="OSM is volunteer-mapped; completeness varies by region and category. Not an official register.")
    MANIFEST.write_text(json.dumps(man, indent=1), encoding="utf-8")
    _register(allp)
    clear()
    return man


def _register(pts: pd.DataFrame):
    """Feed the generic exposure mechanism (critical-region scoring) with facility counts per cell."""
    from . import gis_layers
    if not len(pts):
        return
    pd.DataFrame({"cell_id": pts["cell_id"].astype("int32"), "value": 1.0, "type": pts["category"]}).to_parquet(
        gis_layers.EXPOSURE_DIR / "infrastructure.parquet", index=False)
    meta = {"kind": "infrastructure", "rows": int(len(pts)), "rejected_rows": 0, "source": "OpenStreetMap (Overpass API)",
            "licence": LICENCE, "source_date": datetime.now(timezone.utc).date().isoformat(), "uploaded_by": "pipeline (infrastructure.acquire)",
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "categories": pts["category"].value_counts().to_dict()}
    (gis_layers.EXPOSURE_DIR / "infrastructure.json").write_text(json.dumps(meta, indent=1))
    gis_layers.exposure_by_cell.cache_clear()


def manifest() -> dict | None:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else None


@lru_cache(maxsize=1)
def points() -> pd.DataFrame | None:
    return pd.read_parquet(POINTS) if POINTS.exists() else None


@lru_cache(maxsize=1)
def _trees():
    from scipy.spatial import cKDTree
    p = points()
    if p is None or not len(p):
        return {}
    from .population import _xyz
    return {c: (cKDTree(_xyz(g["lat"].to_numpy(), g["lon"].to_numpy())), g.reset_index(drop=True)) for c, g in p.groupby("category")}


def nearby(lat: float, lon: float, radius_km: float = 10.0, limit: int = 25) -> dict:
    """Facilities within radius_km of a point, per category, with distances (great-circle via 3-D chord)."""
    from .population import _xyz
    tr = _trees()
    man = manifest() or {"categories": {}}
    q = _xyz(np.array([lat]), np.array([lon]))[0]
    out = {}
    for cat in CATEGORIES:
        st = man["categories"].get(cat, {}).get("status", "unavailable")
        if cat not in tr:
            out[cat] = {"status": st if st != "loaded" else "loaded", "count": 0 if st == "loaded" else None, "nearest": []}
            continue
        tree, g = tr[cat]
        idx = tree.query_ball_point(q, r=radius_km)
        d = np.linalg.norm(tree.data[idx] - q, axis=1) if idx else np.array([])
        order = np.argsort(d)[:limit]
        out[cat] = {"status": "loaded", "count": int(len(idx)),
                    "nearest": [{"osm_id": g.at[idx[i], "osm_id"], "name": g.at[idx[i], "name"], "lat": float(g.at[idx[i], "lat"]),
                                 "lon": float(g.at[idx[i], "lon"]), "distance_km": round(float(d[i]), 2)} for i in order]}
    return out


def counts_within(lat, lon, radius_km: float = 10.0) -> pd.DataFrame | None:
    """Per-point facility counts within radius_km, one column per loaded category."""
    from .population import _xyz
    tr = _trees()
    if not tr:
        return None
    q = _xyz(np.atleast_1d(lat), np.atleast_1d(lon))
    return pd.DataFrame({c: [len(i) for i in t.query_ball_point(q, r=radius_km)] for c, (t, _) in tr.items()})


def clear():
    points.cache_clear()
    _trees.cache_clear()


if __name__ == "__main__":
    import sys
    acquire(sys.argv[1:] or None)
