"""Calendar, historical trends, anomaly detection, critical regions and observation
intelligence. Every function works on a region id and never treats a day or month
without sensor coverage as zero fire activity."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from . import forecast, harmonize, store, weather
from .config import SAT_LABEL, SAT_NOMINAL_LST, SATELLITES, VIIRS_REFERENCE

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _rec(df: pd.DataFrame) -> list:
    return df.astype(object).where(pd.notna(df), None).to_dict("records")


def _f(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else float(x)


def data_end() -> pd.Timestamp:
    return max(pd.Timestamp(v["last"]) for v in store.spans().values())


# --------------------------------------------------------------------------- calendar
def calendar(region_id: str, year: int) -> dict:
    d = store.region_daily(region_id)
    d = d[d["acq_date"].dt.year == year]
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    piv = d.pivot_table(index="acq_date", columns="satellite", values="n_veg", aggfunc="sum", observed=True).reindex(days)
    frp = d.pivot_table(index="acq_date", columns="satellite", values="frp_sum", aggfunc="sum", observed=True).reindex(days)
    sp = store.spans()
    out = pd.DataFrame({"date": days.strftime("%Y-%m-%d")})
    avail = {}
    for s in SATELLITES:
        if s not in sp:
            continue
        ds = days.strftime("%Y-%m-%d")
        inspan = (ds >= sp[s]["first"]) & (ds <= sp[s]["last"])
        gap = np.isin(ds, sp[s]["gap_days"])
        avail[s] = inspan & ~gap
        col = piv[s].to_numpy() if s in piv else np.full(len(days), np.nan)
        out[s] = np.where(avail[s], np.nan_to_num(col), np.nan)       # observed zero vs. not observed
        fr = frp[s].to_numpy() if s in frp else np.full(len(days), np.nan)
        out[s + "|frp"] = np.where(avail[s], np.nan_to_num(fr), np.nan)
        out[s + "|status"] = np.where(~inspan, "outside_record", np.where(gap, "sensor_gap", "observed"))
    # daily VIIRS-equivalent: the month's harmonized estimate distributed by that month's daily Aqua (or Terra) share
    hs, _ = harmonize.series(region_id)
    hs = hs[hs["year"] == year].set_index("month")
    veq, prov = np.full(len(days), np.nan), np.array(["no_data"] * len(days), dtype=object)
    for mth, row in hs.iterrows():
        msk = days.month == mth
        prov[msk] = row["provenance"]
        if row["provenance"] == "actual_viirs" and VIIRS_REFERENCE in out:
            veq[msk] = out.loc[msk, VIIRS_REFERENCE]
            continue
        if pd.isna(row["veq"]):
            continue
        src = "Aqua" if row["provenance"] == "sensor_calibrated" and "Aqua" in out else "Terra"
        w = out.loc[msk, src].to_numpy() if src in out else np.full(msk.sum(), np.nan)
        obs = ~np.isnan(w)
        if obs.any():
            share = np.where(obs, (w + 1e-9) / (np.nansum(w) + 1e-9 * obs.sum()), np.nan) if np.nansum(w) > 0 else np.where(obs, 1.0 / obs.sum(), np.nan)
            veq[msk] = row["veq"] * share
    out["veq"], out["provenance"] = veq, prov
    monthly = hs.reset_index()[["month", "terra", "aqua", "viirs", "veq", "veq_lo", "veq_hi", "harmonized", "provenance", "cov_terra", "cov_aqua", "cov_viirs"]]
    years = sorted({int(y) for v in sp.values() for y in range(int(v["first"][:4]), int(v["last"][:4]) + 1)})
    return {"region": store.region_label(region_id), "year": year, "years_available": years, "days": _rec(out), "months": _rec(monthly),
            "note": "Null = the sensor did not observe that day (outside its record or inside a data gap). Zero = observed, no detection; "
                    "cloud or smoke can still hide fires on such days. Daily VIIRS-equivalent values outside the VIIRS era are estimates: the "
                    "monthly harmonized total distributed by the daily MODIS pattern."}


# --------------------------------------------------------------------------- trends
def _lin_trend(years, values):
    y, v = np.asarray(years, float), np.asarray(values, float)
    ok = ~np.isnan(v)
    if ok.sum() < 5 or np.nanmean(v) <= 0:
        return None
    slope, icpt = np.polyfit(y[ok], v[ok], 1)
    resid = v[ok] - (slope * y[ok] + icpt)
    se = np.sqrt((resid ** 2).sum() / (ok.sum() - 2) / ((y[ok] - y[ok].mean()) ** 2).sum())
    return {"slope_per_year": float(slope), "pct_per_year": float(100 * slope / np.nanmean(v)), "t_stat": float(slope / se) if se > 0 else None,
            "n_years": int(ok.sum()), "significant_95": bool(se > 0 and abs(slope / se) > 2.2)}


@lru_cache(maxsize=64)
def trends(region_id: str) -> dict:
    hs, _ = harmonize.series(region_id)
    m = store.region_monthly(region_id)
    g = m.groupby(["ym", "satellite"], observed=True).agg(n=("n_veg", "sum"), frp_sum=("frp_sum", "sum"), frp_n=("frp_n", "sum"),
                                                          frp_max=("frp_max", "max"), n_static=("n_static", "sum")).reset_index()
    g["frp_mean"] = g["frp_sum"] / g["frp_n"].where(g["frp_n"] > 0)
    cov = store.coverage()
    covl = cov[[s for s in SATELLITES if s in cov]].copy()
    covl.index = store.ym_of(covl.index)
    g["coverage"] = [covl.at[y, s] if s in covl and y in covl.index else 0 for y, s in zip(g["ym"], g["satellite"])]
    frp_m = g.pivot(index="ym", columns="satellite", values="frp_mean")
    frp_s = g.pivot(index="ym", columns="satellite", values="frp_sum")
    monthly = hs[["date", "ym", "year", "month", "terra", "aqua", "viirs", "veq", "veq_lo", "veq_hi", "harmonized", "harm_lo", "harm_hi",
                  "provenance", "cov_terra", "cov_aqua", "cov_viirs", "nrt"]].copy()
    for s in frp_m.columns:
        monthly[f"frp_mean|{s}"] = frp_m[s].reindex(monthly["ym"]).to_numpy()
        monthly[f"frp_sum|{s}"] = frp_s[s].reindex(monthly["ym"]).to_numpy()
    # yearly totals: only years where every month of the relevant sensor is covered count as complete
    yr = []
    for y, gy in hs.groupby("year"):
        complete = len(gy) == 12 and gy["harmonized"].notna().all() and (gy[["cov_viirs", "cov_aqua", "cov_terra"]].max(axis=1) >= 0.8).all()
        row = {"year": int(y), "complete": bool(complete), "harmonized": _f(gy["harmonized"].sum(min_count=1)), "harm_lo": _f(gy["harm_lo"].sum(min_count=1)),
               "harm_hi": _f(gy["harm_hi"].sum(min_count=1)), "viirs": _f(gy["viirs"].sum(min_count=1)), "terra": _f(gy["terra"].sum(min_count=1)),
               "aqua": _f(gy["aqua"].sum(min_count=1)), "months": int(len(gy)), "min_coverage": _f(gy[["cov_viirs", "cov_aqua"]].max(axis=1).min()),
               "estimated_months": int((gy["provenance"] != "actual_viirs").sum())}
        gg = g[g["ym"] // 100 == y]
        for s, gs in gg.groupby("satellite", observed=True):
            row[f"frp_mean|{s}"] = _f(gs["frp_sum"].sum() / gs["frp_n"].sum()) if gs["frp_n"].sum() > 0 else None
        yr.append(row)
    ydf = pd.DataFrame(yr)
    comp = ydf[ydf["complete"]]
    season = []
    for mth, gm in hs.groupby("month"):
        season.append({"month": int(mth), "label": MONTHS[mth - 1], "harmonized_mean": _f(gm["harmonized"].mean()), "harmonized_p10": _f(gm["harmonized"].quantile(0.1)),
                       "harmonized_p90": _f(gm["harmonized"].quantile(0.9)), "terra_mean": _f(gm["terra"].mean()), "aqua_mean": _f(gm["aqua"].mean()),
                       "viirs_mean": _f(gm["viirs"].mean()), "night_share_aqua": _f(gm["aqua_night"].sum() / gm["aqua"].sum()) if gm["aqua"].sum() > 0 else None})
    tot = sum(s_["harmonized_mean"] or 0 for s_ in season)
    peak = max(season, key=lambda s_: s_["harmonized_mean"] or 0) if season else None
    return {"region": store.region_label(region_id), "monthly": _rec(monthly), "yearly": yr, "seasonal": season,
            "trend_harmonized": _lin_trend(comp["year"], comp["harmonized"]) if len(comp) else None,
            "trend_note": "Ordinary least-squares slope over complete years only; with ~14 years this is descriptive, not proof of a long-term change.",
            "historical_average_per_year": _f(comp["harmonized"].mean()) if len(comp) else None,
            "peak_month": peak["label"] if peak else None,
            "peak_month_share": _f((peak["harmonized_mean"] or 0) / tot) if peak and tot > 0 else None,
            "frp_note": "FRP is reported per sensor and never pooled: MODIS and VIIRS retrieve FRP from different pixel sizes and channels."}


@lru_cache(maxsize=64)
def regional_comparison(level: str = "state") -> list:
    m = store.monthly()
    v = m[m["satellite"] == VIIRS_REFERENCE]
    c = store.cells()
    key = "state" if level == "state" else "district_id"
    lab = c[key].reindex(v["cell_id"]).to_numpy()
    df = pd.DataFrame({"k": lab, "ym": v["ym"].to_numpy(), "n": v["n_veg"].to_numpy(), "frp": v["frp_sum"].to_numpy(), "frp_n": v["frp_n"].to_numpy()}).dropna(subset=["k"])
    df["year"], df["month"] = df["ym"] // 100, df["ym"] % 100
    cov = store.coverage()[VIIRS_REFERENCE]
    full_years = [int(y) for y, g in cov.groupby(cov.index.year) if len(g) == 12 and (g >= 0.8).all()]
    yr = df[df["year"].isin(full_years)].groupby(["k", "year"]).n.sum().unstack(fill_value=0)
    ncell = c[c["in_country"]].groupby(key).size()
    pk = df.groupby(["k", "month"]).n.sum().unstack(fill_value=0)
    out = []
    names = store.districts().set_index("district_id") if level != "state" else None
    for k in yr.index:
        if k == store.OUTSIDE:
            continue
        tr = _lin_trend(yr.columns, yr.loc[k].to_numpy(dtype=float))
        sub = df[df["k"] == k]
        out.append({"id": f"{'state' if level == 'state' else 'district'}:{k}",
                    "name": k if level == "state" else f"{names.at[k, 'district']}, {names.at[k, 'state']}" if k in names.index else k,
                    "mean_per_year": float(yr.loc[k].mean()), "per_1000km2": float(yr.loc[k].mean() / (ncell.get(k, 1) * 0.73)),
                    "latest_year": float(yr.loc[k].iloc[-1]), "peak_month": MONTHS[int(pk.loc[k].idxmax()) - 1],
                    "trend_pct_per_year": tr["pct_per_year"] if tr else None, "trend_significant": tr["significant_95"] if tr else None,
                    "frp_mean_mw": float(sub["frp"].sum() / sub["frp_n"].sum()) if sub["frp_n"].sum() > 0 else None,
                    "series": [float(x) for x in yr.loc[k]], "years": full_years})
    return sorted(out, key=lambda r: -r["mean_per_year"])


# --------------------------------------------------------------------------- anomalies
def _robust_z(x, ref):
    ref = np.asarray(ref, float)
    ref = ref[~np.isnan(ref)]
    if len(ref) < 4:
        return None
    med = np.median(ref)
    mad = np.median(np.abs(ref - med)) * 1.4826
    sd = mad if mad > 1e-6 else ref.std(ddof=1)
    return float((x - med) / sd) if sd > 1e-6 else None


@lru_cache(maxsize=64)
def anomaly_series(region_id: str) -> dict:
    """Monthly S-NPP VIIRS activity vs the seasonal baseline of the OTHER years (leave-one-year-out)."""
    hs, _ = harmonize.series(region_id)
    v = hs[hs["cov_viirs"] >= 0.8].copy()
    v["lv"] = np.log1p(v["viirs"] / v["cov_viirs"])
    rows = []
    for _, r in hs.iterrows():
        ref = v[(v["month"] == r["month"]) & (v["year"] != r["year"])]
        usable = r["cov_viirs"] >= 0.8 and pd.notna(r["viirs"])
        val = r["viirs"] / r["cov_viirs"] if usable else np.nan
        z = _robust_z(np.log1p(val), ref["lv"]) if usable else None
        rows.append({"date": r["date"], "ym": int(r["ym"]), "observed": _f(val), "coverage": _f(r["cov_viirs"]),
                     "baseline_median": _f(np.expm1(ref["lv"].median())) if len(ref) else None,
                     "baseline_p10": _f(np.expm1(ref["lv"].quantile(0.1))) if len(ref) else None,
                     "baseline_p90": _f(np.expm1(ref["lv"].quantile(0.9))) if len(ref) else None,
                     "z": z, "flag": None if z is None else "high" if z >= 2.5 else "low" if z <= -2.5 else "normal",
                     "status": "ok" if usable else "insufficient_coverage"})
    df = pd.DataFrame(rows)
    df["rolling_3m"] = df["observed"].rolling(3, min_periods=2).mean()
    df["rolling_12m"] = df["observed"].rolling(12, min_periods=9).mean()
    # multivariate check (Isolation Forest) on deseasonalised monthly features
    iso_flag = {}
    try:
        from sklearn.ensemble import IsolationForest
        m = store.region_monthly(region_id)
        mv = m[m["satellite"] == VIIRS_REFERENCE].groupby(["ym", "daynight"], observed=True).agg(n=("n_veg", "sum"), frp=("frp_sum", "sum"), cells=("cell_id", "nunique")).reset_index()
        a = mv.groupby("ym").agg(n=("n", "sum"), frp=("frp", "sum"), cells=("cells", "max"))
        a["night"] = mv[mv["daynight"] == "N"].groupby("ym").n.sum().reindex(a.index).fillna(0) / a["n"].clip(lower=1)
        a["frp_mean"] = a["frp"] / a["n"].clip(lower=1)
        feat = pd.DataFrame({"n": np.log1p(a["n"]), "frp_mean": np.log1p(a["frp_mean"]), "cells": np.log1p(a["cells"]), "night": a["night"]})
        feat = feat.reindex(df.loc[df["status"] == "ok", "ym"]).dropna()
        mo = feat.index % 100
        feat = feat - feat.groupby(mo).transform("median")
        if len(feat) >= 36:
            sc = IsolationForest(n_estimators=200, contamination=0.05, random_state=7).fit(feat).decision_function(feat)
            iso_flag = dict(zip(feat.index, sc))
    except Exception:
        pass
    df["iforest_score"] = df["ym"].map(iso_flag)
    df["iforest_outlier"] = df["iforest_score"] < 0
    return {"region": store.region_label(region_id), "series": _rec(df),
            "method": "Robust z-score of log(1+detections) against the same calendar month in all other years (median / MAD), |z| >= 2.5 flagged; "
                      "plus an Isolation Forest on deseasonalised count, mean FRP, active cells and night share. S-NPP VIIRS only, so no sensor change can create an anomaly.",
            "disclaimer": "An anomaly is an unusual satellite-observed pattern. It is not a confirmed wildfire and says nothing about cause."}


@lru_cache(maxsize=64)
def anomalies_now(window_days: int = 30, level: str = "state") -> dict:
    """Latest window vs the same day-of-year window in earlier years, for every state/district."""
    end = pd.Timestamp(store.spans()[VIIRS_REFERENCE]["last"])
    d = store.daily()
    v = d[d["satellite"] == VIIRS_REFERENCE]
    c = store.cells()
    key = "state" if level == "state" else "district_id"
    lab = c[key].reindex(v["cell_id"]).to_numpy()
    df = pd.DataFrame({"k": lab, "date": v["acq_date"].to_numpy(), "n": v["n_veg"].to_numpy(), "frp": v["frp_sum"].to_numpy(),
                       "night": np.where(v["daynight"].astype(str) == "N", v["n_veg"], 0), "cell": v["cell_id"].to_numpy()}).dropna(subset=["k"])
    gaps = pd.DatetimeIndex(store.spans()[VIIRS_REFERENCE]["gap_days"])
    first = pd.Timestamp(store.spans()[VIIRS_REFERENCE]["first"])
    wins = {}
    for y in range(first.year, end.year + 1):
        e = end.replace(year=y) if not (end.month == 2 and end.day == 29) else pd.Timestamp(y, 2, 28)
        s = e - pd.Timedelta(days=window_days - 1)
        if s < first:
            continue
        ng = int(((gaps >= s) & (gaps <= e)).sum())
        if ng > window_days * 0.2:
            continue          # window not adequately observed -> excluded, not counted as quiet
        w = df[(df["date"] >= s) & (df["date"] <= e)]
        wins[y] = (w.groupby("k").agg(n=("n", "sum"), frp=("frp", "sum"), night=("night", "sum"), cells=("cell", "nunique")) , window_days / (window_days - ng))
    if end.year not in wins:
        return {"status": "insufficient_coverage", "items": [], "message": "The latest window overlaps an S-NPP data gap; anomaly scoring is withheld."}
    cur, scale = wins[end.year]
    names = store.districts().set_index("district_id") if level != "state" else None
    items = []
    keys = set().union(*[set(w.index) for w, _ in wins.values()])
    for k in keys:
        if k == store.OUTSIDE:
            continue
        hist = np.array([w.at[k, "n"] * sc if k in w.index else 0.0 for y, (w, sc) in wins.items() if y != end.year])
        now = float(cur.at[k, "n"] * scale) if k in cur.index else 0.0
        if max(now, np.median(hist) if len(hist) else 0) < 20:
            continue
        z = _robust_z(np.log1p(now), np.log1p(hist))
        if z is None:
            continue
        frp_now = float(cur.at[k, "frp"] / max(cur.at[k, "n"], 1)) if k in cur.index else None
        frp_hist = np.array([w.at[k, "frp"] / max(w.at[k, "n"], 1) for y, (w, _) in wins.items() if y != end.year and k in w.index])
        factors = []
        med = float(np.median(hist))
        factors.append(f"Detections {now:,.0f} vs seasonal median {med:,.0f} ({(now / med - 1) * 100:+.0f}%)" if med > 0 else f"Detections {now:,.0f}; none typical for this window")
        if k in cur.index:
            cells_hist = np.median([w.at[k, "cells"] for y, (w, _) in wins.items() if y != end.year and k in w.index] or [0])
            factors.append(f"Active grid cells {int(cur.at[k, 'cells'])} vs typical {cells_hist:.0f}")
            if frp_now is not None and len(frp_hist) >= 4:
                factors.append(f"Mean FRP {frp_now:.1f} MW vs typical {np.median(frp_hist):.1f} MW")
            factors.append(f"Night-time share {100 * cur.at[k, 'night'] / max(cur.at[k, 'n'], 1):.0f}%")
        items.append({"id": f"{'state' if level == 'state' else 'district'}:{k}",
                      "name": k if level == "state" else f"{names.at[k, 'district']}, {names.at[k, 'state']}" if k in names.index else k,
                      "current": now, "median": med, "z": z, "direction": "above" if z > 0 else "below",
                      "flag": "high" if z >= 2.5 else "low" if z <= -2.5 else "elevated" if z >= 1.5 else "reduced" if z <= -1.5 else "normal",
                      "years_compared": int(len(hist)), "factors": factors})
    items.sort(key=lambda r: -abs(r["z"]))
    lt = store.spans()[VIIRS_REFERENCE].get("last_typed")
    provisional = bool(lt and end > pd.Timestamp(lt))
    return {"status": "ok", "provisional_nrt": provisional,
            "nrt_note": ("The current window uses near-real-time (NRT) files while the comparison years use standard-processing archive files. NRT and "
                         "archive products can differ in completeness, so part of any difference may be a product effect rather than fire activity.") if provisional else None,
            "window": [str((end - pd.Timedelta(days=window_days - 1)).date()), str(end.date())], "level": level, "items": items,
            "disclaimer": "Unusual satellite-observed pattern - not a confirmed wildfire."}


# --------------------------------------------------------------------------- critical regions
CRIT_WEIGHTS = {"forecast": 0.30, "recent": 0.20, "recurrence": 0.15, "frp": 0.10, "observation_gap": 0.10, "forest": 0.10, "settlement": 0.05}


@lru_cache(maxsize=64)
def critical_regions(top: int = 60) -> dict:
    if not forecast.available():
        return {"status": "forecast_unavailable", "items": [], "weights": CRIT_WEIGHTS}
    fc = forecast.issue()
    c = store.cells()
    alpha = forecast.meta()["aggregation"]["alpha"]
    df = fc.merge(c[["state", "district", "district_id", "land_use", "lc_forest", "lc_savanna", "lc_urban", "lc_cropland"]], left_on="cell_id", right_index=True)
    df = df[df["district_id"].notna()]
    rows = []
    for (did, dname, st), g in df.groupby(["district_id", "district", "state"]):
        agg = forecast.aggregate_region(g["p"].to_numpy(), alpha)
        rows.append({"district_id": did, "name": f"{dname}, {st}", "state": st, "n_cells": len(g),
                     "p_any": agg["p_any"], "max_cell_p": agg["max_cell"], "expected_cells": agg["expected_cells_with_detection"],
                     "band": float((g["p_hi"] - g["p_lo"]).mean()),
                     "recent30": float(np.expm1(g["f_v30"]).sum()), "recent7": float(np.expm1(g["f_v7"]).sum()),
                     "recurrence": float(g["clim"].mean()) if g["clim"].notna().any() else np.nan,
                     "frp30": float(np.expm1(g["f_frp30"]).sum()), "gap30": float(g["f_gap30"].max()),
                     "rain7": float(g["f_p30"].mean()) if g["f_p30"].notna().any() else np.nan,
                     "forest": float((g["lc_forest"].fillna(0) + g["lc_savanna"].fillna(0)).mean()), "urban": float(g["lc_urban"].fillna(0).mean()),
                     "land_use": g["land_use"].mode().iat[0], "land_use_mix": g["land_use"].value_counts().to_dict()})
    r = pd.DataFrame(rows)
    pct = lambda s: s.rank(pct=True).fillna(0.5)
    r["frp_per_det"] = r["frp30"] / r["recent30"].clip(lower=1)
    comp = pd.DataFrame({"forecast": r["max_cell_p"], "recent": pct(r["recent30"] / r["n_cells"]), "recurrence": r["recurrence"].fillna(r["recurrence"].median()),
                         "frp": pct(r["frp_per_det"].where(r["recent30"] >= 5)), "observation_gap": (r["gap30"] / 30).clip(0, 1),
                         "forest": r["forest"], "settlement": pct(r["urban"])})
    r["score"] = sum(comp[k] * w for k, w in CRIT_WEIGHTS.items())
    r["priority"] = pd.cut(r["score"].rank(pct=True), [0, 0.5, 0.8, 0.95, 1.0], labels=["Routine", "Elevated", "High", "Critical"]).astype(str)
    labels = {"forecast": "calibrated 7-day hotspot probability", "recent": "recent 30-day detections", "recurrence": "historical seasonal recurrence",
              "frp": "high fire radiative power", "observation_gap": "recent observation gaps (uncertain picture)", "forest": "forest / woodland cover",
              "settlement": "urban land nearby (exposure proxy)"}
    out = []
    for i, row in r.sort_values("score", ascending=False).head(top).iterrows():
        contrib = {k: float(comp.at[i, k] * w) for k, w in CRIT_WEIGHTS.items()}
        reasons = [f"{labels[k]} ({comp.at[i, k]:.2f})" for k in sorted(contrib, key=contrib.get, reverse=True)[:3]]
        out.append({**{k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in row.items()},
                    "id": f"district:{row['district_id']}", "components": {k: float(comp.at[i, k]) for k in CRIT_WEIGHTS}, "reasons": reasons,
                    "reliability": "reduced - observation gaps" if row["gap30"] >= 4 else "normal"})
    return {"status": "ok", "issue_date": forecast.meta()["issue_date"], "items": out, "weights": CRIT_WEIGHTS, "n_districts": int(len(r)),
            "not_available": ["Population exposure (no population grid loaded)", "Critical infrastructure proximity (no infrastructure layer loaded)"],
            "note": "Decision-support ranking of districts. Urban land share from NASA MCD12Q1 is used as a coarse exposure proxy; population and "
                    "infrastructure layers are not loaded and therefore carry zero weight rather than invented values. Priority bands are score "
                    "percentiles (top 5% Critical, next 15% High, next 30% Elevated)."}


# --------------------------------------------------------------------------- observation intelligence
def observation_quality(region_id: str, days: int = 30) -> dict:
    end = data_end()
    start = end - pd.Timedelta(days=days - 1)
    d = store.region_daily(region_id)
    w = d[(d["acq_date"] >= start) & (d["acq_date"] <= end)]
    sp = store.spans()
    rng = pd.date_range(start, end, freq="D")
    sensors = []
    for s in SATELLITES:
        if s not in sp:
            sensors.append({"satellite": s, "label": SAT_LABEL[s], "loaded": False, "note": "No dataset loaded for this sensor."})
            continue
        ds = rng.strftime("%Y-%m-%d")
        inspan = (ds >= sp[s]["first"]) & (ds <= sp[s]["last"])
        gap = np.isin(ds, sp[s]["gap_days"])
        g = w[w["satellite"] == s]
        n = int(g["n"].sum())
        sensors.append({"satellite": s, "label": SAT_LABEL[s], "loaded": True, "days_in_record": int(inspan.sum()), "gap_days": int((inspan & gap).sum()),
                        "days_observing": int((inspan & ~gap).sum()), "days_with_detections": int(g["acq_date"].nunique()), "detections": n,
                        "low_conf_share": _f(g["n_low"].sum() / n) if n else None, "high_conf_share": _f(g["n_high"].sum() / n) if n else None,
                        "mean_pixel_km2": _f(g["area_sum"].sum() / n) if n else None, "night_share": _f(g.loc[g["daynight"].astype(str) == "N", "n"].sum() / n) if n else None,
                        "last_detection": str(g["acq_date"].max().date()) if n else None, "coverage": _f((inspan & ~gap).mean()),
                        "record": [sp[s]["first"], sp[s]["last"]]})
    # cloud / rain obscuration proxies from NASA POWER for the region's nodes
    cloud = None
    if weather.WEATHER_PATH.exists():
        c = store.cells()
        ids = [i for i in store.region_cells(region_id) if i in c.index]
        nodes = np.unique(weather.node_of(c.loc[ids, "lat"], c.loc[ids, "lon"])) if ids else []
        wx = pd.read_parquet(weather.WEATHER_PATH, filters=[("node", "in", [int(n) for n in nodes])]) if len(nodes) else pd.DataFrame()
        if len(wx):
            rec = wx[(wx["date"] >= start) & (wx["date"] <= end)]
            clim = wx[wx["date"].dt.month.isin(sorted(set(rng.month)))]
            cloud = {"rain_days_recent": _f((rec.groupby("date")["precip"].mean() >= 5).sum()), "rain_mm_recent": _f(rec.groupby("date")["precip"].mean().sum()),
                     "cloud_pct_recent": _f(rec["cloud"].mean()), "cloud_pct_climatology_same_months": _f(clim["cloud"].mean()),
                     "cloud_note": "CERES cloud amount from NASA POWER lags by months; when the recent value is null the same-month climatology and recent "
                                   "rain days are the only obscuration indicators. Neither is a per-overpass cloud mask."}
    ref = next((s for s in sensors if s["satellite"] == VIIRS_REFERENCE), None)
    score = None
    if ref and ref.get("loaded"):
        score = ref["coverage"] * (1 - 0.5 * min(1.0, (cloud or {}).get("rain_days_recent") or 0) / days * 2) if cloud else ref["coverage"]
    alt = []
    if ref and ref.get("loaded"):
        ds = rng.strftime("%Y-%m-%d")
        for day in ds[np.isin(ds, sp[VIIRS_REFERENCE]["gap_days"])]:
            others = [SAT_LABEL[s] for s in SATELLITES if s != VIIRS_REFERENCE and store.sensor_available(s, day)]
            alt.append({"date": day, "missing": SAT_LABEL[VIIRS_REFERENCE], "available": others})
    return {"region": store.region_label(region_id), "window": [str(start.date()), str(end.date())], "sensors": sensors, "obscuration": cloud,
            "coverage_score": _f(score), "alternatives_on_gap_days": alt,
            "coverage_score_definition": "Share of days the reference sensor (S-NPP VIIRS) was observing, reduced by up to half for rainy days (>= 5 mm) "
                                         "in the window. A low score means the picture is incomplete - it is never evidence of low fire risk.",
            "limits": "PyroScope cannot task, steer or request imagery from any satellite. It only reports which already-acquired observations exist."}


def observation_cells(days: int = 30) -> dict:
    """Cells where the picture is least certain: wide forecast band, data gaps, or disagreement between sensors."""
    if not forecast.available():
        return {"items": []}
    fc = forecast.issue().copy()
    c = store.cells()
    end = data_end()
    d = store.daily()
    w = d[d["acq_date"] > end - pd.Timedelta(days=days)]
    by = w.pivot_table(index="cell_id", columns="satellite", values="n", aggfunc="sum", observed=True).fillna(0)
    fc["band"] = fc["p_hi"] - fc["p_lo"]
    fc = fc.merge(c[["lat", "lon", "state", "district", "land_use"]], left_on="cell_id", right_index=True)
    fc = fc.join(by, on="cell_id")
    viirs_cols = [s for s in ("Suomi NPP", "NOAA-20", "NOAA-21") if s in fc]
    fc["modis"] = fc[[s for s in ("Terra", "Aqua") if s in fc]].fillna(0).sum(axis=1)
    fc["viirs_any"] = fc[viirs_cols].fillna(0).sum(axis=1)
    fc["reason"] = np.select(
        [fc["f_gap30"] >= 4, (fc["modis"] > 0) & (fc["viirs_any"] == 0), fc["band"] >= 0.25, (fc["p"] >= 0.4) & (fc["viirs_any"] == 0)],
        ["S-NPP data gap in the last 30 days", "MODIS detected, VIIRS did not (timing or cloud)", "Models disagree (wide probability band)",
         "Elevated forecast but no recent VIIRS detection"], default="")
    sel = fc[fc["reason"] != ""].sort_values("band", ascending=False).head(400)
    cols = ["cell_id", "lat", "lon", "state", "district", "land_use", "p", "p_lo", "p_hi", "band", "f_gap30", "reason"] + [s for s in SATELLITES if s in sel]
    return {"items": _rec(sel[cols]), "counts": fc.loc[fc["reason"] != "", "reason"].value_counts().to_dict(), "window_days": days}


def overpasses() -> dict:
    lst = pd.read_parquet(store.LST) if store.LST.exists() else pd.DataFrame(columns=["satellite", "daynight", "lst_bin", "n"])
    o = store.orbit()
    return {"reliable_orbital_data": False,
            "message": "No orbital elements (TLE) or overpass-prediction service is connected, so PyroScope does not predict future overpass times. "
                       "Shown instead: nominal equator-crossing times and the local solar time of observations actually present in the loaded data.",
            "nominal_local_time_hours": SAT_NOMINAL_LST, "observed_local_time_histogram": _rec(lst),
            "orbit_drift": _rec(o[["satellite", "year", "lst_day_mean", "drift_h", "stable", "n"]]) if len(o) else []}


# --------------------------------------------------------------------------- overview
@lru_cache(maxsize=64)
def dashboard_summary() -> dict:
    sp = store.spans()
    end = data_end()
    d = store.daily()
    last7 = d[d["acq_date"] > end - pd.Timedelta(days=7)].groupby("satellite", observed=True).agg(n=("n", "sum"), frp_max=("frp_max", "max"), cells=("cell_id", "nunique"))
    hs, _ = harmonize.series("country")
    reg = {k: v for k, v in __import__("app.ingest", fromlist=["load_registry"]).load_registry().items()}
    out = {"data_end": str(end.date()), "satellites": {s: {**{k: v for k, v in sp[s].items() if k not in ("zero_detection_days", "gap_days")},
                                                         "label": SAT_LABEL[s], "gap_days": len(sp[s]["gap_days"])} for s in sp},
           "missing_sensors": [SAT_LABEL[s] for s in SATELLITES if s not in sp],
           "total_detections": int(sum(v["detections"] for v in sp.values())), "datasets": len(reg),
           "last7": {str(s): {"detections": int(r["n"]), "frp_max": _f(r["frp_max"]), "cells": int(r["cells"])} for s, r in last7.iterrows()},
           "timeline": _rec(hs[["date", "terra", "aqua", "viirs", "veq", "veq_lo", "veq_hi", "harmonized", "provenance"]]),
           "provenance_counts": hs["provenance"].value_counts().to_dict()}
    try:
        v = harmonize.validation("country")
        s = harmonize.seam_test("country")
        out["validation"] = {k: v.get(k) for k in ("status", "split", "overall", "band_coverage_pct")}
        out["seam"] = {k: s.get(k) for k in ("mode", "status", "step_raw", "step_harmonized", "step_true", "reduction_pct", "seam_month")}
    except Exception as exc:  # surfaced, not hidden
        out["validation_error"] = str(exc)
    if forecast.available():
        m = forecast.meta()
        fc = forecast.issue()
        out["forecast"] = {"issue_date": m["issue_date"], "brier": m["test"]["brier"], "roc_auc": m["test"]["roc_auc"],
                           "cells_high": int(((fc["p"] >= 0.6) & (fc["p"] < 0.8)).sum()), "cells_very_high": int((fc["p"] >= 0.8).sum()), "cells": int(len(fc))}
    return out


def clear():
    for fn in (regional_comparison, anomalies_now, critical_regions, dashboard_summary, trends, anomaly_series):
        fn.cache_clear()
