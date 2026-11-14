"""Population and infrastructure exposure around actual hotspots, forecast cells and regions.

Exposure here means "people / facilities within R km". It describes who and what is near a detected or
predicted hotspot. It is not a prediction that a settlement or facility will burn.
Missing layers are reported as unavailable (None), never as zero.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import forecast, grid, infrastructure, ingest, linear_gis, population, store
from .analytics import data_end

HIGH_FRP_MW = 50.0
MEANING = ("Exposure = people (WorldPop 2020) or mapped facilities / lines (OpenStreetMap) within the radius of a location. "
           "It is not a prediction that anything will burn or is damaged; 'unavailable' means no layer is loaded, not zero.")


def layers() -> dict:
    pm = population.manifest()
    im = infrastructure.manifest()
    return {"population": ({k: pm.get(k) for k in ("name", "reference_year", "resolution", "licence", "url", "total_population_in_aoi",
                                                   "cells_0p25", "cells_partial_coverage", "grid_aligned", "processed_at", "sha256")}
                           | {"status": "loaded"}) if pm else {"status": "unavailable", "how": "python -m app.population"},
            "infrastructure": ({"status": "loaded", "source": im.get("source"), "licence": im.get("licence"), "updated": im.get("updated"),
                                "categories": {k: {"status": v.get("status"), "features": v.get("features"), "last_error": v.get("last_error")}
                                               for k, v in im.get("categories", {}).items()},
                                "not_loaded": im.get("not_loaded"), "completeness_note": im.get("completeness_note"), "cleaning": im.get("cleaning")})
                              if im else {"status": "unavailable", "how": "python -m app.infrastructure"},
            "meaning": MEANING}


def linear_proximity(lat: float, lon: float, radius_km: float) -> dict | None:
    """Nearest road / railway / power line / power facility / settlement and line length inside the buffer.
    None when the linear layer has not been built (unavailable, not zero)."""
    if linear_gis.manifest() is None:
        return None
    out = {}
    for cat in ("road_major", "railway", "power_line", "power_facility", "settlement"):
        nr = linear_gis.nearest(lat, lon, cat, max_km=max(radius_km * 3, 25))
        w = linear_gis.within(lat, lon, radius_km, cat)
        out[cat] = {"nearest_km": nr.get("distance_km"), "nearest_name": nr.get("name"), "status": nr.get("status"),
                    "features_within": w.get("features"), "length_km_within": w.get("length_km")}
    return out


def point(lat: float, lon: float, radius_km: float = 10.0) -> dict:
    pop = population.people_within(lat, lon, radius_km)
    return {"lat": lat, "lon": lon, "radius_km": radius_km, "linear": linear_proximity(lat, lon, radius_km),
            "population": None if pop is None else round(float(pop[0])),
            "population_reference_year": (population.manifest() or {}).get("reference_year"),
            "infrastructure": infrastructure.nearby(lat, lon, radius_km) if infrastructure.manifest() else None,
            "meaning": MEANING}


def hotspots(days: int = 7, radius_km: float = 5.0, region: str = "country", top: int = 25) -> dict:
    """Exposure around actual detections of the last `days` days (all satellites, archive + NRT)."""
    end = data_end()
    start = end - pd.Timedelta(days=days - 1)
    box = store.region_bbox(region) if region != "country" else None
    df, total = ingest.query_hotspots(start, end, box, None, limit=10 ** 9)
    if region not in ("country",) and not region.startswith("bbox"):
        df = df[df["cell_id"].isin(np.array(store.region_cells(region)))]
    out = {"window": [str(start.date()), str(end.date())], "region": region, "radius_km": radius_km, "detections": int(len(df)),
           "meaning": MEANING, "high_frp_threshold_mw": HIGH_FRP_MW}
    if df.empty:
        return out | {"population": None, "items": []}
    # de-duplicate to unique ~375 m locations so a fire seen by several satellites is counted once
    loc = df.assign(k=(df["latitude"] * 300).round().astype(int).astype(str) + "_" + (df["longitude"] * 300).round().astype(int).astype(str))
    g = loc.groupby("k").agg(lat=("latitude", "mean"), lon=("longitude", "mean"), n=("latitude", "size"), frp_max=("frp_mw", "max"),
                             sats=("satellite", lambda s: ", ".join(sorted(set(map(str, s))))), last=("acq_date", "max"),
                             cell_id=("cell_id", "first")).reset_index(drop=True)
    pop = population.people_within(g["lat"].to_numpy(), g["lon"].to_numpy(), radius_km)
    g["population"] = pop if pop is not None else np.nan
    inf = infrastructure.counts_within(g["lat"].to_numpy(), g["lon"].to_numpy(), radius_km)
    if inf is not None:
        g["facilities"] = inf.sum(axis=1).to_numpy()
        for c in ("hospital", "school", "power_substation", "fire_station"):
            if c in inf:
                g[c] = inf[c].to_numpy()
    c = store.cells()
    g["state"] = c["state"].reindex(g["cell_id"]).to_numpy()
    g["district"] = c["district"].reindex(g["cell_id"]).to_numpy()
    hi = g["frp_max"].fillna(0) >= HIGH_FRP_MW
    out["locations"] = int(len(g))
    out["high_frp_locations"] = int(hi.sum())
    if pop is not None:
        out["population"] = {"locations_with_people_within_radius": int((g["population"] > 0).sum()),
                             "median_people_within_radius": round(float(g["population"].median())),
                             "high_frp_locations_over_10k_people": int((hi & (g["population"] >= 10000)).sum()),
                             "note": "Per-location counts overlap where hotspots are close together, so they are not summed."}
    else:
        out["population"] = None
    sort = "population" if pop is not None else "frp_max"
    items = g.sort_values([sort, "frp_max"], ascending=False).head(top).copy()
    if linear_gis.manifest() is not None:      # actual-detection proximity to linear infrastructure (top items only)
        for cat in ("road_major", "railway", "power_line"):
            items[f"nearest_{cat}_km"] = [linear_gis.nearest(a, b, cat, 25).get("distance_km") for a, b in zip(items["lat"], items["lon"])]
    out["linear_layer"] = "loaded" if linear_gis.manifest() is not None else "unavailable"
    out["items"] = [{k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in r.items()} for r in items.round(3).to_dict("records")]
    return out


def regions() -> dict:
    """State comparison: population, mapped facilities, recent detections and forecast."""
    c = store.cells()
    c = c[c["in_country"]]
    pc = population.cells()
    rows = pd.DataFrame({"state": c["state"]}, index=c.index)
    rows["population"] = pc["population"].reindex(c.index).to_numpy() if pc is not None else np.nan
    pts = infrastructure.points()
    end = data_end()
    d = store.daily()
    rec = d[d["acq_date"] > end - pd.Timedelta(days=30)].groupby("cell_id")["n"].sum()
    rows["detections_30d"] = rec.reindex(c.index).fillna(0).to_numpy()
    if forecast.available():
        fc = forecast.issue().set_index("cell_id")["p"]
        rows["p"] = fc.reindex(c.index).to_numpy()
    agg = rows.groupby("state").agg(population=("population", lambda s: s.sum(min_count=1)), cells=("state", "size"),
                                    detections_30d=("detections_30d", "sum"),
                                    **({"forecast_max_cell_p": ("p", "max")} if "p" in rows else {}))
    if pts is not None and len(pts):
        st = c["state"].reindex(pts["cell_id"]).to_numpy()
        ic = pd.crosstab(pd.Series(st, name="state"), pts["category"].to_numpy())
        agg = agg.join(ic, how="left")
        agg["facilities_total"] = ic.sum(axis=1).reindex(agg.index)
    if pc is not None and forecast.available():
        # people living in cells with >= 60 % 7-day hotspot probability (decision-support summary)
        hp = rows[rows["p"] >= 0.6].groupby("state")["population"].sum()
        agg["population_in_high_prob_cells"] = hp.reindex(agg.index).fillna(0)
    agg = agg.reset_index().sort_values("detections_30d", ascending=False)
    return {"items": [{k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in r.items()} for r in agg.to_dict("records")],
            "window_30d_end": str(end.date()), "layers": layers(), "meaning": MEANING}


def population_layer(region: str = "country", min_density: float = 0.0) -> dict:
    pc = population.cells()
    if pc is None:
        return {"status": "unavailable", "cells": [], "meaning": MEANING}
    ids = np.array(store.region_cells(region)) if region != "country" else pc.index.to_numpy()
    p = pc.reindex(ids).dropna()
    p = p[p["density_km2"] >= min_density]
    lat, lon = grid.cell_center(p.index.to_numpy())
    return {"status": "loaded", "grid_deg": 0.25, "reference_year": population.SOURCE["reference_year"], "source": population.SOURCE["name"],
            "licence": population.SOURCE["licence"],
            "cells": [{"cell_id": int(i), "lat": float(a), "lon": float(b), "population": round(float(r.population)),
                       "density_km2": round(float(r.density_km2), 1), "valid_frac": round(float(r.valid_frac), 3)}
                      for i, a, b, r in zip(p.index, lat, lon, p.itertuples())]}


def infrastructure_layer(category: str | None = None, bbox=None, limit: int = 5000) -> dict:
    pts = infrastructure.points()
    if pts is None:
        return {"status": "unavailable", "points": [], "meaning": MEANING}
    if category:
        pts = pts[pts["category"] == category]
    if bbox:
        w, s, e, n = bbox
        pts = pts[pts["lon"].between(w, e) & pts["lat"].between(s, n)]
    total = len(pts)
    if total > limit:
        pts = pts.iloc[np.linspace(0, total - 1, limit).astype(int)]
    return {"status": "loaded", "total": int(total), "returned": int(len(pts)), "licence": infrastructure.LICENCE,
            "points": pts[["osm_id", "category", "lat", "lon", "name"]].where(pts[["osm_id", "category", "lat", "lon", "name"]].notna(), None).to_dict("records")}
