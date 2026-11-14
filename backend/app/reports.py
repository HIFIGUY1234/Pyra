"""PDF and CSV report generation for a region."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select

from . import alerts, analytics, forecast, harmonize, ingest, risk, store
from . import models as M
from .config import REPORTS, SAT_LABEL

DISCLAIMERS = [
    "Hotspot counts from MODIS (1 km) and VIIRS (375 m) are not equivalent and are never added together.",
    "VIIRS-equivalent values outside the VIIRS record are statistical estimates, not satellite detections.",
    "Uncertainty bands are 5-95% bootstrap resampling ranges, not formal confidence intervals or guarantees.",
    "Days or months without sensor coverage are missing data, not zero fire activity or low risk.",
    "Forecast probabilities are the probability of a detectable S-NPP VIIRS hotspot, not of a verified ground fire.",
    "Alert thresholds (60% / 80%) are configurable prototype starting points, not statutory values.",
    "A satellite hotspot is an unverified thermal anomaly until confirmed by the responsible authority; land-use class identifies who is responsible, not the cause.",
    "Notifications in this prototype are simulated in-app entries. No external message or public warning is sent.",
]


def _slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:60]


def _fmt(v, d=0):
    return "-" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:,.{d}f}"


def collect(region_id: str) -> dict:
    hs, _ = harmonize.series(region_id)
    out = {"region_id": region_id, "region": store.region_label(region_id), "series": hs, "trends": analytics.trends(region_id),
           "validation": harmonize.validation(region_id), "seam": harmonize.seam_test(region_id), "sensor": harmonize.calibration_table("sh"),
           "morning": harmonize.calibration_table("mg"), "anomaly": analytics.anomaly_series(region_id), "quality": analytics.observation_quality(region_id),
           "forecast": risk.region_forecast(region_id), "datasets": ingest.load_registry(), "spans": store.spans()}
    cells = store.cells()
    ids = [c for c in store.region_cells(region_id) if c in cells.index]
    out["land_use_mix"] = cells.loc[ids, "land_use"].value_counts().to_dict() if ids else {}
    with M.Session() as s:
        rows = list(s.scalars(select(M.Alert).order_by(M.Alert.id.desc())))
    st = set(cells.loc[ids, "state"]) if ids else set()
    dset = set(cells.loc[ids, "district_id"].dropna()) if ids else set()
    rid_kind = region_id.split(":")[0]
    keep = [a for a in rows if (rid_kind == "country") or (rid_kind == "state" and a.state in st) or (a.district_id in dset)]
    out["alerts"] = [alerts.serialize(a) for a in keep[:60]]
    return out


def generate(region_id: str, fmt: str, user: str, kind: str = "full", organisation_id: int | None = None) -> dict:
    fmt = fmt.lower()
    data = collect(region_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    title = f"PyroScope report - {data['region']}"
    path = REPORTS / f"pyroscope_{_slug(data['region'])}_{kind}_{stamp}.{fmt}"
    if fmt == "csv":
        _csv(data, kind).to_csv(path, index=False)
    elif fmt == "pdf":
        _pdf(data, path, title, user)
    else:
        raise ValueError("format must be pdf or csv")
    with M.Session() as s:
        r = M.Report(title=title + (f" ({kind})" if fmt == "csv" else ""), region_id=region_id, format=fmt, path=path.name, created_by=user,
                     organisation_id=organisation_id, bytes=path.stat().st_size)
        s.add(r)
        s.add(M.AuditLog(actor=user, action="REPORT_GENERATED", entity="report", entity_id=path.name, detail={"region": region_id, "format": fmt}))
        s.commit()
        return {"id": r.id, "title": r.title, "format": fmt, "file": path.name, "bytes": r.bytes, "created_at": r.created_at.isoformat() + "Z"}


def _csv(data: dict, kind: str) -> pd.DataFrame:
    if kind == "forecast_cells":
        return pd.DataFrame(risk.grid_cells(data["region_id"])["cells"])
    if kind == "alerts":
        return pd.DataFrame(data["alerts"])
    hs = data["series"]
    df = hs[["date", "terra", "aqua", "viirs", "aqua_est", "aqua_est_lo", "aqua_est_hi", "veq", "veq_lo", "veq_hi", "harmonized", "provenance",
             "cov_terra", "cov_aqua", "cov_viirs", "nrt"]].copy()
    df.columns = ["month", "terra_modis_detections", "aqua_modis_detections", "snpp_viirs_detections_actual", "aqua_estimated_from_terra",
                  "aqua_estimate_p05", "aqua_estimate_p95", "viirs_equivalent_estimate", "viirs_equivalent_p05", "viirs_equivalent_p95",
                  "harmonized_record", "provenance", "coverage_terra", "coverage_aqua", "coverage_viirs", "includes_nrt_untyped"]
    df.insert(0, "region", data["region"])
    return df


def _pdf(data: dict, path, title: str, user: str):
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=17, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#b45309"))
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11.5)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, textColor=colors.HexColor("#555555"))

    def table(rows, widths=None, head=True):
        t = Table(rows, colWidths=widths, repeatRows=1 if head else 0)
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937") if head else colors.white),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white if head else colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        return t

    P = lambda t, st=body: Paragraph(t, st)
    el = [P(title, h1), P(f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by {user} | Region id: {data['region_id']}", small), Spacer(1, 4)]
    el += [P("1. Region and land-use jurisdiction", h2),
           P("Land-use mix of the region's 0.25 deg grid cells (NASA MCD12Q1 IGBP, prototype majority rule): " +
             (", ".join(f"{k}: {v} cells" for k, v in data["land_use_mix"].items()) or "no mapped cells") + ".")]
    el += [P("2. Satellite data sources", h2),
           table([["Sensor", "Record loaded", "Detections", "Gap days"]] + [[SAT_LABEL[s], f"{v['first']} to {v['last']}", f"{v['detections']:,}", str(len(v["gap_days"]))]
                                                                            for s, v in data["spans"].items()], [45 * mm, 50 * mm, 30 * mm, 25 * mm]),
           P("Source: NASA FIRMS archive / NRT files committed to the Pyra repository" + (" and user uploads" if any(v["origin"] == "upload" for v in data["datasets"].values()) else "") +
             ". VIIRS product: 375 m. No 750 m product and no NOAA-20 data are loaded.", small)]
    yr = data["trends"]["yearly"]
    el += [P("3. Original and harmonized fire activity by year", h2),
           table([["Year", "Terra MODIS", "Aqua MODIS", "S-NPP VIIRS (actual)", "Harmonized (VIIRS-equiv.)", "5-95% band", "Estimated months"]] +
                 [[str(r["year"]) + ("" if r["complete"] else " *"), _fmt(r["terra"]), _fmt(r["aqua"]), _fmt(r["viirs"]), _fmt(r["harmonized"]),
                   f"{_fmt(r['harm_lo'])} - {_fmt(r['harm_hi'])}", str(r["estimated_months"])] for r in yr]),
           P("* incomplete year. Presumed-vegetation detections (FIRMS type 0) plus untyped NRT rows. Columns are different sensors and must not be summed.", small)]
    hs = data["series"]
    pts_h = [(i, float(v)) for i, v in enumerate(hs["harmonized"]) if pd.notna(v)]
    pts_m = [(i, float(v)) for i, v in enumerate(hs["modis_total"]) if pd.notna(v)]
    if pts_h:
        d = Drawing(480, 150)
        lp = LinePlot()
        lp.x, lp.y, lp.width, lp.height = 40, 22, 420, 110
        lp.data = [pts_h, pts_m] if pts_m else [pts_h]
        lp.lines[0].strokeColor = colors.HexColor("#dc2626")
        if pts_m:
            lp.lines[1].strokeColor = colors.HexColor("#2563eb")
        lp.xValueAxis.valueSteps = [i for i in range(len(hs)) if hs["month"].iloc[i] == 1][::2]
        lp.xValueAxis.labelTextFormat = lambda v: str(hs["year"].iloc[int(v)]) if 0 <= int(v) < len(hs) else ""
        lp.xValueAxis.labels.fontSize = lp.yValueAxis.labels.fontSize = 6
        d.add(lp)
        d.add(String(40, 138, "Monthly activity: harmonized VIIRS-equivalent record (red) vs raw Terra+Aqua MODIS detections (blue)", fontSize=7))
        el.append(d)
    for key, name in (("morning", "4. Morning-gap correction (Terra -> Aqua)"), ("sensor", "5. Sensor calibration (Aqua MODIS -> S-NPP VIIRS 375 m)")):
        c = data[key]
        day = [r for r in c["by_month"] if r["daynight"] == "day"]
        el += [P(name, h2), P(f"Model: {c['model']}. Training years: {c['train_years']}. Band: {c['band']}.", small),
               table([["Calendar month"] + [str(r["moy"]) for r in day], ["Day-time ratio"] + [f"{r['ratio']:.2f}" for r in day],
                      ["5-95%"] + [f"{r['ratio_lo']:.1f}-{r['ratio_hi']:.1f}" for r in day], ["Reliable"] + ["yes" if r["reliable"] else "NO" for r in day]])]
        for n in c["notes"]:
            el.append(P(n, small))
    v, sm = data["validation"], data["seam"]
    if v.get("overall"):
        o = v["overall"]
        el += [P("6. Held-out validation", h2),
               P(f"Calibration trained only on {v['train_years']}; tested on withheld {v['test_period']}. <b>Status: {v['status'].upper()}</b> ({v['status_rule']})"),
               table([["Metric", "Harmonized estimate", "Constant-ratio baseline", "Raw MODIS as VIIRS"],
                      ["MAE (detections / month)", _fmt(o.get("mae")), _fmt(v["baseline_constant_ratio"].get("mae")), _fmt(v["baseline_raw_modis"].get("mae"))],
                      ["RMSE", _fmt(o.get("rmse")), _fmt(v["baseline_constant_ratio"].get("rmse")), _fmt(v["baseline_raw_modis"].get("rmse"))],
                      ["Weighted abs. % error", _fmt(o.get("wape_pct"), 1), _fmt(v["baseline_constant_ratio"].get("wape_pct"), 1), _fmt(v["baseline_raw_modis"].get("wape_pct"), 1)],
                      ["Bias %", _fmt(o.get("bias_pct"), 1), _fmt(v["baseline_constant_ratio"].get("bias_pct"), 1), _fmt(v["baseline_raw_modis"].get("bias_pct"), 1)],
                      ["Band coverage %", _fmt(v.get("band_coverage_pct"), 0), "-", "-"]])]
    if sm.get("step_raw"):
        el += [P("7. Seam test (%s)" % sm["mode"], h2),
               P(f"Seam month {sm['seam_month']}, {sm['window_months']}-month windows. Step before harmonization: x{sm['step_raw']:.2f}; after: x{sm['step_harmonized']:.2f} "
                 f"(band x{sm['step_harmonized_band'][0]:.2f}-x{sm['step_harmonized_band'][1]:.2f}); genuine change seen by {sm['reference_sensor']}: x{sm['step_reference_sensor']:.2f}"
                 + (f"; withheld real VIIRS: x{sm['step_true']:.2f}" if sm.get("step_true") else "") + f". <b>Status: {str(sm.get('status', 'n/a')).upper()}</b>."),
               P(sm.get("real_seam_note", ""), small)]
    tr = data["trends"]
    t = tr.get("trend_harmonized")
    el += [P("8. Historical trends and anomalies", h2),
           P(f"Mean harmonized activity per complete year: {_fmt(tr.get('historical_average_per_year'))}. Peak month: {tr.get('peak_month')}. " +
             (f"Linear trend: {t['pct_per_year']:+.1f}% per year over {t['n_years']} years ({'statistically distinguishable from zero' if t['significant_95'] else 'not distinguishable from zero'})." if t else "Trend not estimated (too few complete years).") +
             " " + tr["trend_note"])]
    an = [r for r in data["anomaly"]["series"] if r.get("flag") in ("high", "low")][-10:]
    if an:
        el.append(table([["Month", "Observed", "Seasonal median", "Robust z", "Flag"]] + [[r["date"][:7], _fmt(r["observed"]), _fmt(r["baseline_median"]), f"{r['z']:+.1f}", r["flag"]] for r in an]))
    el.append(P(data["anomaly"]["disclaimer"], small))
    f = data["forecast"]
    el.append(P("9. Seven-day calibrated hotspot probability", h2))
    if f.get("status") == "ok":
        el += [P(f"Issued from data to {f['issue_date']} for {f['prediction_period']['from']} to {f['prediction_period']['to']}. <b>Risk category: {f['risk_category']}</b>. "
                 f"Regional probability of any detection: {f['regional']['p_any'] * 100:.0f}% (bounds {f['regional']['p_any_lower'] * 100:.0f}-{f['regional']['p_any_upper'] * 100:.0f}%); "
                 f"highest cell: {f['max_cell_probability'] * 100:.0f}%. {f['meaning']}"),
               table([["Tier"] + list(f["tier_counts"].keys()), ["Grid cells"] + [str(x) for x in f["tier_counts"].values()]]),
               P(f"{f['aggregation_note']} Test-period Brier score {f['confidence']['test_brier']:.3f}, ROC-AUC {f['confidence']['test_roc_auc']:.3f} "
                 f"({forecast.meta()['split']['test_from']} onward). Observation coverage score: {_fmt((f['confidence']['observation_coverage_score'] or 0) * 100)}%.", small)]
    else:
        el.append(P(f.get("message", "Forecast unavailable.")))
    el.append(P("10. Authority alert routing and acknowledgement log", h2))
    if data["alerts"]:
        el.append(table([["Alert ID", "Type", "Area", "Tier", "Status", "Routing"]] +
                        [[a["alert_id"], a["alert_type"].replace("_", " ").title(), P(a["region_name"] or "", small), a["risk_category"] or "-", a["status"],
                          P((a["routing_status"] or "").replace("_", " ").title(), small)] for a in data["alerts"][:25]], [30 * mm, 34 * mm, 42 * mm, 18 * mm, 30 * mm, 30 * mm]))
    else:
        el.append(P("No alerts recorded for this region."))
    q = data["quality"]
    el += [P("11. Observation quality (%s to %s)" % tuple(q["window"]), h2),
           table([["Sensor", "Days observing", "Gap days", "Detections", "Low-confidence share", "Mean pixel km2"]] +
                 [[x["label"], str(x["days_observing"]), str(x["gap_days"]), f"{x['detections']:,}", _fmt((x["low_conf_share"] or 0) * 100, 1) + "%", _fmt(x["mean_pixel_km2"], 2)]
                  for x in q["sensors"] if x.get("loaded")]), P(q["coverage_score_definition"], small)]
    el.append(P("12. Warnings and methodological disclaimers", h2))
    el += [P("- " + d, body) for d in DISCLAIMERS]
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm, title=title, author="PyroScope").build(el)
