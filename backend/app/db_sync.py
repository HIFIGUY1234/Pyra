"""Create the schema, seed reference rows and persist pipeline outputs into the database."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import delete, select

from . import analytics, forecast, harmonize, ingest, store
from . import models as M
from .config import SATELLITES

ROLES = {
    "admin": ("Platform administrator", ["*"]),
    "gov_officer": ("Government / authority officer", ["alerts:review", "alerts:act", "reports", "read"]),
    "org_user": ("Organisation user", ["org", "reports", "read"]),
    "analyst": ("Analyst (read-only + reports)", ["reports", "read"]),
}
DEMO_USERS = [
    ("admin", "Administrator (demo persona)", "admin", None, None),
    ("forest.officer", "Forest Officer (demo persona)", "gov_officer", None, "Forest"),
    ("district.officer", "District Officer (demo persona)", "gov_officer", None, None),
    ("org.user", "Organisation User (demo persona)", "org_user", None, None),
    ("analyst", "Analyst (demo persona)", "analyst", None, None),
]
# Role templates only. No names, numbers or addresses: real contacts must be entered and verified by an administrator.
AUTHORITY_TEMPLATES = {
    "Forest": [("State Forest Department", "Forest Range Officer", 1), ("State Forest Department", "Divisional / District Forest Officer (DFO)", 1),
               ("State Forest Department", "State Forest Nodal Officer", 2)],
    "Agricultural": [("State Agriculture Department", "District Agriculture Officer", 1), ("District / Block Administration", "Block Development Officer", 1),
                     ("District Administration", "District Collector / environmental authority", 2)],
    "Residential/Village": [("Gram Panchayat", "Panchayat Secretary / Sarpanch", 1), ("Tehsil Administration", "Tehsildar", 1),
                            ("Fire and Emergency Services", "Local Fire Station Officer", 2)],
    "Municipal/Urban": [("Municipal Council / Corporation", "Municipal Commissioner's office", 1), ("Municipal Fire Department", "Chief Fire Officer", 1),
                        ("District Administration", "District Disaster Management Authority", 2)],
    "Industrial": [("Facility Safety Department", "Site Safety Officer", 1), ("Industrial Emergency Response Team", "Emergency Response Lead", 1),
                   ("Fire Service & Industrial Safety Inspectorate", "Inspector of Factories / Fire Officer", 2)],
    "Other": [("District Administration", "District Disaster Management Authority", 1), ("State Disaster Management Authority", "State Nodal Officer", 2)],
}


def init_db():
    import os
    from . import migrate, security
    migrate.upgrade(log=lambda *a: None)           # additive; backs up SQLite first when anything changes
    M.Base.metadata.create_all(M.engine)
    with M.Session() as s:
        if not s.scalar(select(M.Role).limit(1)):
            for name, (desc, perms) in ROLES.items():
                s.add(M.Role(name=name, description=desc, permissions=perms))
            s.flush()
            rid = {r.name: r.id for r in s.scalars(select(M.Role))}
            for u, dn, role, st, lu in DEMO_USERS:
                s.add(M.User(username=u, display_name=dn, role_id=rid[role], jurisdiction_state=st, jurisdiction_land_use=lu, is_demo=True))
        if not s.scalar(select(M.ThresholdConfig).limit(1)):
            s.add(M.ThresholdConfig(scope_type="default", scope_value=None, updated_by="system",
                                    rationale="Configurable prototype starting thresholds (60% notify, 80% urgent). Not statutory values."))
        if not s.scalar(select(M.AuthorityContact).limit(1)):
            for lu, rows in AUTHORITY_TEMPLATES.items():
                for auth, title, lvl in rows:
                    s.add(M.AuthorityContact(land_use=lu, authority=auth, role_title=title, level=lvl, is_template=True, verified=False))
        pw = os.getenv("PYROSCOPE_ADMIN_PASSWORD")  # bootstrap a real admin login; never hard-coded
        if pw:
            adm = s.scalar(select(M.User).where(M.User.username == "admin"))
            if adm is not None and not adm.password_hash:
                adm.password_hash = security.hash_password(pw)
                adm.is_demo = False
                if adm.display_name == DEMO_USERS[0][1]:   # now a real account: drop the "(demo persona)" seed label
                    adm.display_name = "Administrator"
        s.commit()


def _replace(table, df: pd.DataFrame, where=None):
    with M.engine.begin() as conn:
        conn.execute(delete(table.__table__) if where is None else delete(table.__table__).where(where))
    if len(df):
        records = df.astype(object).where(pd.notna(df), None).to_dict("records")
        with M.engine.begin() as conn:      # core insert: handles JSON / Date columns on every backend
            for i in range(0, len(records), 20000):
                conn.execute(table.__table__.insert(), records[i:i + 20000])


def sync_all(log=print):
    init_db()
    if not store.has_data():
        return
    reg = ingest.load_registry()
    rows = []
    for k, v in reg.items():
        firsts = [x["first"] for x in v["satellites"].values()] or [None]
        lasts = [x["last"] for x in v["satellites"].values()] or [None]
        rows.append({"key": k, "origin": v["origin"], "file": v["file"], "container": v["container"], "satellites": v["satellites"],
                     "product_types": v["product_types"], "versions": v["versions"], "quality": v["quality"], "rows_kept": v["quality"].get("rows_kept"),
                     "first_date": pd.Timestamp(min(firsts)).date() if firsts[0] else None, "last_date": pd.Timestamp(max(lasts)).date() if lasts[0] else None,
                     "processed_at": pd.Timestamp(v["processed_at"]).tz_localize(None).to_pydatetime()})
    with M.Session() as s:
        s.execute(delete(M.SatelliteDataset))
        s.add_all(M.SatelliteDataset(**r) for r in rows)
        s.commit()

    c = store.cells().copy()
    c["static_share"] = store.cell_static()["static_share"].reindex(c.index).to_numpy()
    cols = ["cell_id", "lat", "lon", "state", "district", "district_id", "land_use", "land_use_source", "lc_forest", "lc_savanna", "lc_cropland", "lc_urban", "static_share"]
    _replace(M.SpatialGridCell, c[[x for x in cols if x in c]].reset_index(drop=True))
    j = c[c["in_country"]].groupby(["state", "land_use"]).agg(n_cells=("cell_id", "size"), west=("lon", "min"), east=("lon", "max"), south=("lat", "min"),
                                                              north=("lat", "max"), source=("land_use_source", "first")).reset_index()
    j["area_km2"] = j["n_cells"] * 730.0
    _replace(M.LandUseJurisdiction, j)

    m = store.monthly()
    st = c["state"].reindex(m["cell_id"]).fillna(store.OUTSIDE).to_numpy()
    mm = m.assign(state=st).groupby(["ym", "state", "satellite"], observed=True).agg(detections=("n", "sum"), presumed_vegetation=("n_veg", "sum"),
                                                                                    static_sources=("n_static", "sum"), frp_sum_mw=("frp_sum", "sum")).reset_index()
    cov = store.coverage()
    covl = cov[[x for x in SATELLITES if x in cov]].copy()
    covl.index = store.ym_of(covl.index)
    mm["coverage"] = [float(covl.at[y, sat]) if sat in covl and y in covl.index else None for y, sat in zip(mm["ym"], mm["satellite"].astype(str))]
    mm["satellite"] = mm["satellite"].astype(str)
    _replace(M.MonthlyFireActivity, mm)
    d = store.daily()
    dd = d.assign(state=c["state"].reindex(d["cell_id"]).fillna(store.OUTSIDE).to_numpy()).groupby(["acq_date", "state", "satellite"], observed=True).agg(
        detections=("n", "sum"), presumed_vegetation=("n_veg", "sum"), static_sources=("n_static", "sum"), frp_sum_mw=("frp_sum", "sum"), frp_max_mw=("frp_max", "max")).reset_index()
    dd = dd.rename(columns={"acq_date": "date"})
    dd["date"] = dd["date"].dt.date
    dd["satellite"] = dd["satellite"].astype(str)
    _replace(M.DailyFireActivity, dd)
    log(f"[db] activity tables: monthly={len(mm):,} daily={len(dd):,}")

    hrows, urows = [], []
    for rid in ["country"] + [f"state:{x}" for x in store.states() if x != store.OUTSIDE]:
        hs, _ = harmonize.series(rid)
        h = pd.DataFrame({"region_id": rid, "ym": hs["ym"], "provenance": hs["provenance"], "terra": hs["terra"], "aqua": hs["aqua"], "viirs_actual": hs["viirs"],
                          "viirs_equivalent": hs["veq"], "lower": hs["veq_lo"], "upper": hs["veq_hi"], "harmonized": hs["harmonized"],
                          "cov_terra": hs["cov_terra"], "cov_aqua": hs["cov_aqua"], "cov_viirs": hs["cov_viirs"]})
        hrows.append(h)
        if rid == "country":
            urows.append(pd.DataFrame({"region_id": rid, "ym": hs["ym"], "central": hs["veq"], "lower": hs["veq_lo"], "upper": hs["veq_hi"],
                                       "relative_width": (hs["veq_hi"] - hs["veq_lo"]) / hs["veq"].where(hs["veq"] > 0), "provenance": hs["provenance"],
                                       "method": "year-block bootstrap + out-of-sample residual resampling (5-95%)"}))
    _replace(M.HarmonizedObservation, pd.concat(hrows, ignore_index=True))
    _replace(M.UncertaintyEstimate, pd.concat(urows, ignore_index=True))
    split = harmonize.default_split()
    for table, which in ((M.MorningGapCalibration, "mg"), (M.SensorCalibration, "sh")):
        out = []
        for run, sp_ in (("operational", None), ("holdout", split)):
            if run == "holdout" and not sp_:
                continue
            t = harmonize.calibration_table(which, sp_)
            for r in t["by_month"]:
                out.append({"run": run, **{k: r[k] for k in ("moy", "daynight", "ratio", "ratio_lo", "ratio_hi", "silent_rate", "predictor_detections", "reliable")},
                            "train_years": t["train_years"]})
        with M.Session() as s:
            s.execute(delete(table))
            s.add_all(table(**r) for r in out)
            s.commit()
    with M.Session() as s:
        s.execute(delete(M.ValidationResult))
        v, sm = harmonize.validation("country"), harmonize.seam_test("country")
        s.add(M.ValidationResult(kind="holdout", region_id="country", split=v.get("split"), status=v.get("status"),
                                 metrics={k: v.get(k) for k in ("overall", "by_stage", "baseline_constant_ratio", "band_coverage_pct", "morning_gap", "train_years", "test_period")}))
        s.add(M.ValidationResult(kind="seam_test", region_id="country", split=split, status=sm.get("status"), metrics={k: x for k, x in sm.items() if k != "series"}))
        if forecast.available():
            fm = forecast.meta()
            s.add(M.ValidationResult(kind="forecast_test", region_id="country", status="reported",
                                     metrics={k: fm.get(k) for k in ("test", "baseline_climatology", "brier_skill_vs_climatology", "split", "aggregation")}))
        s.commit()

    an = analytics.anomalies_now()
    if an.get("items"):
        a = pd.DataFrame(an["items"])
        _replace(M.Anomaly, pd.DataFrame({"region_id": a["id"], "name": a["name"], "window_start": pd.Timestamp(an["window"][0]).date(), "window_end": pd.Timestamp(an["window"][1]).date(),
                                          "current": a["current"], "baseline_median": a["median"], "z": a["z"], "flag": a["flag"], "factors": a["factors"]}))
    oq = analytics.observation_quality("country")
    _replace(M.ObservationQuality, pd.DataFrame([{"region_id": "country", "satellite": x["satellite"], "window_start": pd.Timestamp(oq["window"][0]).date(),
                                                  "window_end": pd.Timestamp(oq["window"][1]).date(), "days_observing": x["days_observing"], "gap_days": x["gap_days"],
                                                  "detections": x["detections"], "low_conf_share": x["low_conf_share"], "mean_pixel_km2": x["mean_pixel_km2"],
                                                  "coverage": x["coverage"]} for x in oq["sensors"] if x.get("loaded")]))
    if forecast.available():
        from .alerts import tier_name
        fc = forecast.issue()
        idate = pd.Timestamp(forecast.meta()["issue_date"]).date()
        alpha = forecast.meta()["aggregation"]["alpha"]
        f = pd.DataFrame({"issue_date": idate, "level": "cell", "region_id": "cell:" + fc["cell_id"].astype(str), "cell_id": fc["cell_id"], "probability": fc["p"],
                          "p_lower": fc["p_lo"], "p_upper": fc["p_hi"], "tier": [tier_name(p) for p in fc["p"]], "aggregation": "none (single cell)", "horizon_days": 7, "observed": fc["observed"]})
        agg = []
        g = fc.merge(c[["state", "district_id"]], left_on="cell_id", right_index=True)
        for lvl, key in (("state", "state"), ("district", "district_id")):
            for k, gg in g.dropna(subset=[key]).groupby(key):
                a_ = forecast.aggregate_region(gg["p"].to_numpy(), alpha)
                agg.append({"issue_date": idate, "level": lvl, "region_id": f"{lvl}:{k}", "cell_id": None, "probability": a_["p_any"], "p_lower": a_["p_any_lower"],
                            "p_upper": a_["p_any_upper"], "tier": tier_name(a_["max_cell"]), "aggregation": "1-prod(1-p)^alpha; bounds = max cell / independent cells",
                            "horizon_days": 7, "observed": None})
        _replace(M.Forecast, pd.concat([f, pd.DataFrame(agg)], ignore_index=True))
        cb = forecast.contribs()
        hot = fc.loc[fc["p"] >= 0.4, "cell_id"]
        ff = []
        for grp, feats in forecast.FACTOR_GROUPS.items():
            ff.append(pd.DataFrame({"issue_date": idate, "cell_id": hot.to_numpy(), "factor_group": grp, "contribution_logodds": cb.loc[hot, feats].sum(axis=1).to_numpy()}))
        _replace(M.ForecastFeature, pd.concat(ff, ignore_index=True))
        cr = analytics.critical_regions(top=200)
        _replace(M.CriticalRegion, pd.DataFrame([{"issue_date": idate, "region_id": x["id"], "name": x["name"], "score": x["score"], "priority": x["priority"],
                                                  "land_use": x["land_use"], "components": x["components"], "reasons": x["reasons"]} for x in cr["items"]]))
    end = analytics.data_end()
    recent, _ = ingest.query_hotspots(end - pd.Timedelta(days=29), end, limit=10 ** 9)
    recent = recent.copy()
    recent["anomaly_type"] = recent["anomaly_type"].astype("float")
    recent["timestamp_utc"] = [t.to_pydatetime() for t in pd.to_datetime(recent["timestamp_utc"])]
    _replace(M.HotspotObservation, recent)
    log(f"[db] recent hotspot window: {len(recent):,} rows")
