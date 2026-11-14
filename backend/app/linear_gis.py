"""Linear infrastructure and settlement layers from an OpenStreetMap PBF extract (Geofabrik).

Source: Geofabrik India extract (https://download.geofabrik.de/asia/india-latest.osm.pbf), OpenStreetMap
contributors, ODbL 1.0. A downloadable PBF is used instead of Overpass: national road/rail/power networks are
far too large for interactive Overpass queries. Geofabrik publishes an ``.md5`` next to every extract, which is
verified after the (resumable) download.

Categories and OSM tags (classification is attribute-based, never inferred from fires):
  road_major      highway=motorway|trunk|primary|secondary (+ _link)        LINE
  road_minor      highway=tertiary|tertiary_link                             LINE
  railway         railway=rail|light_rail|narrow_gauge|subway (not abandoned/disused)  LINE
  power_line      power=line (transmission)                                  LINE
  power_minor     power=minor_line (distribution, where mapped)              LINE
  power_facility  power=substation|plant  (node or closed way, centre)      POINT
  settlement      place=city|town|village|hamlet (node)                     POINT
  residential     landuse=residential (closed way / multipolygon)            POLYGON
  industrial      landuse=industrial (closed way / multipolygon)             POLYGON

Geometry is kept: lines stay lines (no centroids). Two geometries are stored per feature in GeoParquet
(WKB, EPSG:4326): ``geometry`` (analytical, full vertex detail inside the AOI) and ``geometry_display``
(Douglas-Peucker simplified, 0.001 deg ~ 100 m, for maps only). Distances are computed in kilometres in a
local azimuthal-equidistant-like projection centred on each query point (x = R cos(phi0) dlambda, y = R dphi),
accurate to < 0.5 % within 50 km -- never in raw degrees.

OSM completeness varies: a missing road means "not mapped", not "absent". Categories absent from the build are
reported unavailable, never zero. Proximity is not damage: a hotspot near a power line says nothing about the line.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import grid
from .config import AOI_BBOX, AUX

LIN_DIR = AUX / "linear"
PBF_URL = "https://download.geofabrik.de/asia/india-latest.osm.pbf"
LICENCE = "Open Database License (ODbL) 1.0 - (c) OpenStreetMap contributors"
MANIFEST = LIN_DIR / "manifest.json"
BY_CELL = LIN_DIR / "linear_by_cell.parquet"
R_EARTH = 6371.0088
SIMPLIFY_DEG = 0.001

ROAD_MAJOR = {"motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link", "secondary_link"}
ROAD_MINOR = {"tertiary", "tertiary_link"}
RAIL = {"rail", "light_rail", "narrow_gauge", "subway"}
PLACES = {"city", "town", "village", "hamlet"}
CATEGORIES = {
    "road_major": "LINE", "road_minor": "LINE", "railway": "LINE", "power_line": "LINE", "power_minor": "LINE",
    "power_facility": "POINT", "settlement": "POINT", "residential": "POLYGON", "industrial": "POLYGON",
}
LINE_CATS = [k for k, v in CATEGORIES.items() if v == "LINE"]


def classify(tags: dict) -> str | None:
    """Attribute-based category for an OSM object (None = not used)."""
    hw, rw, pw, lu, pl = (tags.get(k) for k in ("highway", "railway", "power", "landuse", "place"))
    if hw in ROAD_MAJOR:
        return "road_major"
    if hw in ROAD_MINOR:
        return "road_minor"
    if rw in RAIL and tags.get("disused") != "yes" and tags.get("abandoned") != "yes":
        return "railway"
    if pw == "line":
        return "power_line"
    if pw == "minor_line":
        return "power_minor"
    if pw in ("substation", "plant"):
        return "power_facility"
    if pl in PLACES:
        return "settlement"
    if lu == "residential":
        return "residential"
    if lu == "industrial":
        return "industrial"
    return None


# --------------------------------------------------------------------------- acquisition
def acquire(log=print, session=None, retries: int = 4, url: str = PBF_URL) -> Path:
    """Resumable download; accepted only if its MD5 matches Geofabrik's published .md5 and it opens as PBF."""
    import requests

    from .acquire import _download
    s = session or requests.Session()
    LIN_DIR.mkdir(parents=True, exist_ok=True)
    dest = LIN_DIR / url.rsplit("/", 1)[1]
    md5_txt = s.get(url + ".md5", timeout=60)
    md5_txt.raise_for_status()
    expected = md5_txt.text.split()[0].strip().lower()
    if len(expected) != 32:
        raise ValueError("unexpected .md5 content")
    head = s.head(url, timeout=60, allow_redirects=True)
    size = int(head.headers.get("Content-Length", 0)) or None
    if dest.exists() and _md5(dest) == expected:
        log(f"[linear] {dest.name} already present and verified")
        return dest
    tmp = dest.with_suffix(".pbf.part")
    _download(url, tmp, size, s, retries, time.sleep, log)
    got = _md5(tmp)
    if got != expected:
        tmp.unlink(missing_ok=True)
        raise IOError(f"MD5 mismatch for {dest.name}: expected {expected}, got {got}")
    tmp.replace(dest)
    (LIN_DIR / "download.json").write_text(json.dumps({"url": url, "md5": expected, "bytes": dest.stat().st_size,
                                                       "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
    return dest


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# --------------------------------------------------------------------------- PBF processing
def extract(pbf: Path, bbox=AOI_BBOX, node_index: str | None = None, log=print) -> dict[str, pd.DataFrame]:
    """Parse ways/relations/nodes, build geometries, classify, clip to the AOI. Returns one frame per category
    with WKB geometry columns. Uses osmium's area assembler for multipolygons."""
    import osmium
    from shapely import wkb as swkb
    from shapely.geometry import LineString, Point, box

    aoi = box(*bbox)
    fab = osmium.geom.WKBFactory()
    rows: dict[str, list] = {k: [] for k in CATEGORIES}
    stats = {"ways_seen": 0, "invalid_geometry": 0, "outside_aoi": 0}

    class H(osmium.SimpleHandler):
        def node(self, n):
            tags = dict(n.tags)
            cat = classify(tags)
            if cat in ("power_facility", "settlement") and n.location.valid():
                lon, lat = n.location.lon, n.location.lat
                if aoi.contains(Point(lon, lat)):
                    rows[cat].append({"osm_type": "node", "osm_id": n.id, "name": tags.get("name"), "class": tags.get("place") or tags.get("power"),
                                      "geometry": Point(lon, lat).wkb})

        def way(self, w):
            tags = dict(w.tags)
            cat = classify(tags)
            if cat is None or CATEGORIES[cat] == "POLYGON":
                return
            stats["ways_seen"] += 1
            try:
                coords = [(nd.lon, nd.lat) for nd in w.nodes if nd.location.valid()]
            except osmium.InvalidLocationError:
                stats["invalid_geometry"] += 1
                return
            if CATEGORIES[cat] == "POINT":             # power facility mapped as a way -> centre point
                if len(coords) >= 1:
                    c = LineString(coords).centroid if len(coords) > 1 else Point(coords[0])
                    if aoi.contains(c):
                        rows[cat].append({"osm_type": "way", "osm_id": w.id, "name": tags.get("name"), "class": tags.get("power"), "geometry": c.wkb})
                return
            if len(coords) < 2:
                stats["invalid_geometry"] += 1
                return
            g = LineString(coords)
            if not g.is_valid or g.length == 0:
                stats["invalid_geometry"] += 1
                return
            if not g.intersects(aoi):
                stats["outside_aoi"] += 1
                return
            if not aoi.contains(g):
                g = g.intersection(aoi)
            rows[cat].append({"osm_type": "way", "osm_id": w.id, "name": tags.get("name") or tags.get("ref"),
                              "class": tags.get("highway") or tags.get("railway") or tags.get("power"),
                              "voltage": tags.get("voltage"), "geometry": g.wkb})

        def area(self, a):
            tags = dict(a.tags)
            cat = classify(tags)
            if cat not in ("residential", "industrial"):
                return
            try:
                g = swkb.loads(fab.create_multipolygon(a), hex=True)
            except Exception:
                stats["invalid_geometry"] += 1
                return
            if not g.is_valid:
                g = g.buffer(0)
            if g.is_empty or not g.intersects(aoi):
                return
            if not aoi.contains(g):
                g = g.intersection(aoi)
            rows[cat].append({"osm_type": "area", "osm_id": a.orig_id(), "name": tags.get("name"), "class": tags.get("landuse"), "geometry": g.wkb})

    h = H()
    if node_index:
        h.apply_file(str(pbf), locations=True, idx=node_index)
    else:
        h.apply_file(str(pbf), locations=True)
    out = {}
    for cat, r in rows.items():
        df = pd.DataFrame(r)
        if df.empty:
            out[cat] = df
            continue
        df = df.drop_duplicates(["osm_type", "osm_id"])
        out[cat] = df
    log(f"[linear] {', '.join(f'{k}={len(v):,}' for k, v in out.items())} | {stats}")
    out["_stats"] = pd.DataFrame([stats])
    return out


def geodesic_length_km(g) -> float:
    """Sum of great-circle segment lengths (haversine) of a (Multi)LineString in EPSG:4326."""
    parts = getattr(g, "geoms", [g])
    tot = 0.0
    for p in parts:
        c = np.asarray(p.coords)
        if len(c) < 2:
            continue
        lon, lat = np.radians(c[:, 0]), np.radians(c[:, 1])
        dlat, dlon = np.diff(lat), np.diff(lon)
        a = np.sin(dlat / 2) ** 2 + np.cos(lat[:-1]) * np.cos(lat[1:]) * np.sin(dlon / 2) ** 2
        tot += float((2 * R_EARTH * np.arcsin(np.sqrt(a))).sum())
    return tot


def build(pbf: Path | None = None, out_dir: Path | None = None, bbox=AOI_BBOX, log=print, node_index: str | None = None) -> dict:
    """Extract -> validate -> GeoParquet per category (+ display geometry) -> per-cell line lengths -> manifest."""
    from shapely import wkb as swkb
    out_dir = out_dir or LIN_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    pbf = pbf or LIN_DIR / PBF_URL.rsplit("/", 1)[1]
    t0 = time.time()
    frames = extract(pbf, bbox, node_index, log)
    stats = frames.pop("_stats").iloc[0].to_dict()
    cats = {}
    cell_rows = []
    for cat, df in frames.items():
        if df.empty:
            cats[cat] = {"status": "no_features_in_extract", "features": 0}
            continue
        geoms = [swkb.loads(b) for b in df["geometry"]]
        df = df.assign(geometry_display=[g.simplify(SIMPLIFY_DEG, preserve_topology=True).wkb for g in geoms])
        if CATEGORIES[cat] == "LINE":
            df["length_km"] = [geodesic_length_km(g) for g in geoms]
            cell_rows.append(_lengths_by_cell(cat, geoms))
        elif CATEGORIES[cat] == "POLYGON":
            df["area_km2"] = [_area_km2(g) for g in geoms]
        b = np.array([g.bounds for g in geoms])
        df = df.assign(minx=b[:, 0], miny=b[:, 1], maxx=b[:, 2], maxy=b[:, 3])
        _write_geoparquet(df, out_dir / f"{cat}.parquet", CATEGORIES[cat])
        cats[cat] = {"status": "loaded", "features": int(len(df)), "geometry_type": CATEGORIES[cat],
                     "total_length_km": round(float(df["length_km"].sum()), 1) if "length_km" in df else None,
                     "total_area_km2": round(float(df["area_km2"].sum()), 1) if "area_km2" in df else None,
                     "named_share": round(float(df["name"].notna().mean()), 3)}
    if cell_rows:
        pd.concat(cell_rows, ignore_index=True).groupby(["cell_id", "category"], as_index=False)["length_km"].sum().to_parquet(out_dir / BY_CELL.name, index=False)
    src = {}
    dl = LIN_DIR / "download.json"
    if dl.exists():
        src = json.loads(dl.read_text())
    man = {"source": "Geofabrik OpenStreetMap extract", "url": src.get("url", PBF_URL), "licence": LICENCE,
           "pbf_file": pbf.name, "pbf_md5": src.get("md5") or _md5(pbf), "pbf_bytes": pbf.stat().st_size,
           "download_date": src.get("downloaded_at"), "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "processing_seconds": round(time.time() - t0, 1), "aoi_bbox": list(bbox), "categories": cats, "parse_stats": stats,
           "coverage": "Features clipped to the AOI bounding box; OSM completeness varies by region (rural power lines and "
                       "minor roads are the least complete). Not an official register.",
           "known_gaps": ["power_minor (distribution lines) is sparsely mapped in OSM India",
                          "residential/industrial landuse polygons are incomplete outside cities"],
           "geometry": {"analytical": "full vertices (EPSG:4326 WKB)", "display": f"Douglas-Peucker {SIMPLIFY_DEG} deg"}}
    (out_dir / MANIFEST.name).write_text(json.dumps(man, indent=1, default=str))
    clear()
    return man


def _area_km2(g) -> float:
    """Approximate geodesic area: shoelace in local equal-area scaling at the polygon centroid latitude."""
    lat0 = math.radians(g.centroid.y)
    return float(g.area * (math.pi / 180 * R_EARTH) ** 2 * math.cos(lat0))


def _lengths_by_cell(cat: str, geoms) -> pd.DataFrame:
    """Length of each line inside each 0.25 deg analysis cell. Lines are clipped to cell boxes; each clipped
    sub-segment is credited only to the cell containing its midpoint (half-open cells), so a line running exactly
    along a cell edge is counted once, not twice."""
    from shapely.geometry import box
    rows = []
    for g in geoms:
        w, s, e, n = g.bounds
        for cid in grid.cells_in_bbox(w - 1e-9, s - 1e-9, e + 1e-9, n + 1e-9):
            cw, cs, ce, cn = (float(x[0]) for x in grid.cell_bounds(np.array([cid])))
            part = g.intersection(box(cw, cs, ce, cn))
            if part.is_empty or part.length == 0:
                continue
            tot = 0.0
            for ln in getattr(part, "geoms", [part]):
                if ln.geom_type != "LineString":
                    continue
                c = np.asarray(ln.coords)
                if len(c) < 2:
                    continue
                mid = (c[:-1] + c[1:]) / 2
                own = grid.cell_of(mid[:, 1], mid[:, 0]) == cid
                lon, lat = np.radians(c[:, 0]), np.radians(c[:, 1])
                a = np.sin(np.diff(lat) / 2) ** 2 + np.cos(lat[:-1]) * np.cos(lat[1:]) * np.sin(np.diff(lon) / 2) ** 2
                tot += float((2 * R_EARTH * np.arcsin(np.sqrt(a)))[own].sum())
            if tot > 0:
                rows.append((int(cid), cat, tot))
    return pd.DataFrame(rows, columns=["cell_id", "category", "length_km"])


def _write_geoparquet(df: pd.DataFrame, path: Path, gtype: str):
    import pyarrow as pa
    import pyarrow.parquet as pq
    t = pa.Table.from_pandas(df, preserve_index=False)
    geo = {"version": "1.0.0", "primary_column": "geometry",
           "columns": {"geometry": {"encoding": "WKB", "crs": "EPSG:4326", "geometry_types": []},
                       "geometry_display": {"encoding": "WKB", "crs": "EPSG:4326", "geometry_types": []}}}
    t = t.replace_schema_metadata({**(t.schema.metadata or {}), b"geo": json.dumps(geo).encode(), b"pyroscope_geometry": gtype.encode()})
    pq.write_table(t, path)


# --------------------------------------------------------------------------- serving
def manifest(base: Path | None = None) -> dict | None:
    p = (base or LIN_DIR) / MANIFEST.name
    return json.loads(p.read_text()) if p.exists() else None


@lru_cache(maxsize=16)
def _layer(cat: str, base: str | None = None):
    from shapely import STRtree
    from shapely import wkb as swkb
    p = Path(base or LIN_DIR) / f"{cat}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    geoms = np.array([swkb.loads(b) for b in df["geometry"]], dtype=object)
    return df.drop(columns=["geometry", "geometry_display"]), geoms, STRtree(geoms)


def _local_xy(lon, lat, lon0, lat0):
    return (np.radians(np.asarray(lon) - lon0) * R_EARTH * math.cos(math.radians(lat0)), np.radians(np.asarray(lat) - lat0) * R_EARTH)


def _to_local(g, lon0: float, lat0: float):
    import shapely
    k = math.cos(math.radians(lat0))
    return shapely.transform(g, lambda c: np.column_stack([np.radians(c[:, 0] - lon0) * R_EARTH * k, np.radians(c[:, 1] - lat0) * R_EARTH]))


def _dist_km(g, lon0: float, lat0: float) -> float:
    """Distance (km) from (lon0, lat0) to geometry g in a local equidistant projection centred on the point."""
    from shapely.geometry import Point
    return float(_to_local(g, lon0, lat0).distance(Point(0, 0)))


def nearest(lat: float, lon: float, category: str, max_km: float = 50.0, base: str | None = None) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {list(CATEGORIES)}")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("invalid coordinates")
    L = _layer(category, base)
    if L is None:
        return {"category": category, "status": "unavailable", "reason": "layer not built (see /api/infrastructure/linear/status)"}
    df, geoms, tree = L
    dlat = max_km / 111.0
    dlon = max_km / (111.0 * max(math.cos(math.radians(lat)), 0.05))
    from shapely.geometry import box
    idx = tree.query(box(lon - dlon, lat - dlat, lon + dlon, lat + dlat))
    if len(idx) == 0:
        return {"category": category, "status": "none_within", "max_km": max_km}
    d = np.array([_dist_km(geoms[i], lon, lat) for i in idx])
    j = int(np.argmin(d))
    if d[j] > max_km:
        return {"category": category, "status": "none_within", "max_km": max_km}
    r = df.iloc[int(idx[j])]
    return {"category": category, "status": "found", "distance_km": round(float(d[j]), 3), "osm_type": r["osm_type"], "osm_id": int(r["osm_id"]),
            "name": None if pd.isna(r.get("name")) else r.get("name"), "class": None if pd.isna(r.get("class")) else r.get("class")}


def within(lat: float, lon: float, radius_km: float, category: str, base: str | None = None) -> dict:
    """Infrastructure intersecting a circular exposure buffer: line length (km) inside it, or feature count."""
    L = _layer(category, base)
    if L is None:
        return {"category": category, "status": "unavailable"}
    df, geoms, tree = L
    from shapely.geometry import Point, box
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.05))
    idx = tree.query(box(lon - dlon, lat - dlat, lon + dlon, lat + dlat))
    circle = Point(0, 0).buffer(radius_km, 64)
    n, length = 0, 0.0
    for i in idx:
        pg = _to_local(geoms[i], lon, lat)
        if pg.intersects(circle):
            n += 1
            if CATEGORIES[category] == "LINE":
                length += pg.intersection(circle).length
    return {"category": category, "status": "ok", "radius_km": radius_km, "features": n,
            "length_km": round(length, 3) if CATEGORIES[category] == "LINE" else None}


@lru_cache(maxsize=2)
def by_cell(base: str | None = None) -> pd.DataFrame | None:
    p = Path(base or LIN_DIR) / BY_CELL.name
    return pd.read_parquet(p) if p.exists() else None


def status(base: Path | None = None) -> dict:
    man = manifest(base)
    if not man:
        return {"status": "not_built", "categories": {k: {"status": "unavailable"} for k in CATEGORIES},
                "how": "On a machine with internet access: python -m app.linear_gis fetch && python -m app.linear_gis build "
                       "(or run the 'Data integration' GitHub workflow with linear_gis=true). Needs ~2 GB disk.",
                "licence": LICENCE, "source": PBF_URL,
                "national_coverage": "INCOMPLETE: no extract has been processed in this deployment"}
    return {"status": "built", **man}


def clear():
    _layer.cache_clear()
    by_cell.cache_clear()


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    if not a or a[0] == "status":
        print(json.dumps(status(), indent=1))
    elif a[0] == "fetch":
        print(acquire())
    elif a[0] == "build":
        print(json.dumps(build(node_index="sparse_file_array," + str(LIN_DIR / "nodes.idx")), indent=1)[:3000])
    else:
        raise SystemExit("usage: python -m app.linear_gis [status|fetch|build]")
