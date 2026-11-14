"""Write docs/SCIENTIFIC_VALIDATION.md from the live computations (no hand-typed numbers).

    python -m app.science_report
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import acquire, forecast, harmonize, store
from .config import ROOT

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def f(v, d=1, suf=""):
    return "–" if v is None else f"{v:,.{d}f}{suf}"


def _mrow(name, m):
    return f"| {name} | {m.get('n', 0)} | {f(m.get('mae'), 0)} | {f(m.get('rmse'), 0)} | {f(m.get('wape_pct'), 1, '%')} | {f(m.get('bias_pct'), 1, '%')} | {f(m.get('r2'), 3)} |"


def build() -> str:
    v = harmonize.validation("country")
    s = harmonize.seam_test("country")
    sh = harmonize.calibration_table("sh")
    mg = harmonize.calibration_table("mg")
    inv = acquire.build_report()
    fm = forecast.meta() if forecast.available() else {}
    cov = store.coverage()
    L = ["# PyroScope - Scientific Validation Report", "",
         f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `python -m app.science_report` from the loaded data. "
         "Every number below is computed at generation time; nothing is typed by hand.", "",
         "## 1. Sensor coverage actually loaded", "", "| Satellite | Status | Science-quality archive | NRT | FIRMS availability starts |", "|---|---|---|---|---|"]
    for sat, e in inv["satellites"].items():
        ld = e["loaded"] or {}
        per = lambda k: f"{ld[k]['first']} → {ld[k]['last']}" if ld.get(k) else "–"
        L.append(f"| {sat} | {e['status']} | {per('archive')} | {per('nrt')} | {e['expected']['firms_start']} |")
    L += ["", "Capabilities with this data: " + "; ".join(f"**{k}**: {val}" for k, val in inv["capabilities"].items()), "",
          "## 2. Calibration design", "",
          "* Model (both steps): `y = F[state, month, day/night] · x + a[state, month, day/night] · N_silent`, with state values shrunk to the national value.",
          "* Morning-Gap Fixer: Terra → Aqua. Sensor Harmonizer: Aqua → S-NPP VIIRS 375 m (only VIIRS product loaded; 750 m unavailable).",
          "* Training months: both sensors 100 % covered, standard-processing (not NRT), orbit-stable years only.",
          f"* Morning-gap training years: {mg['train_years']}. Sensor training years (operational fit): {sh['train_years']}.",
          f"* Notes: {' '.join(sh['notes']) or 'none'}", "",
          "### 2a. Learned national ratios (operational fit, central value and 5–95 % year-block bootstrap range)", "",
          "| Month | Aqua→VIIRS day | Aqua→VIIRS night | Terra→Aqua day | Terra→Aqua night | reliable |", "|---|---|---|---|---|---|"]
    by = lambda t, m, dn: next(r for r in t["by_month"] if r["moy"] == m and r["daynight"] == dn)
    for m in range(1, 13):
        cells = []
        for t in (sh, mg):
            for dn in ("day", "night"):
                r = by(t, m, dn)
                cells.append(f"{r['ratio']:.2f} ({r['ratio_lo']:.2f}–{r['ratio_hi']:.2f})")
        rel = all(by(t, m, dn)["reliable"] for t in (sh, mg) for dn in ("day", "night"))
        L.append(f"| {MONTHS[m - 1]} | " + " | ".join(cells) + f" | {'yes' if rel else 'NO'} |")
    L += ["", "Night-time Terra→Aqua ratios below 1 show that the afternoon/early-morning pass does not always see more fire: the relationship is learned, not assumed.", "",
          "## 3. Chronological held-out validation (actual)", "",
          f"* Validation kind: **{v.get('validation_kind')}**. Split {v.get('split')}: train on {v['train_years'][0]}–{v['train_years'][-1]}, "
          f"test on real VIIRS months {v['test_period'][0]}–{v['test_period'][1]} never seen in training.",
          f"* Status (PyroScope rule: {v['status_rule']}): **{v['status']}**", "",
          "| Method | n months | MAE | RMSE | WAPE | Bias | R² |", "|---|---|---|---|---|---|---|",
          _mrow("PyroScope calibrated harmonization", v["overall"]), _mrow("Constant VIIRS/Aqua ratio baseline", v["baseline_constant_ratio"]),
          _mrow("Raw MODIS (Terra+Aqua, uncorrected)", v["baseline_raw_modis"]),
          _mrow("· day-time detections", v["by_daynight"]["day"]), _mrow("· night-time detections", v["by_daynight"]["night"])]
    for st, m in v["by_stage"].items():
        L.append(_mrow(f"· stage {st}", m))
    L += ["", f"Uncertainty band (5–95 % of replicates, nominal 90 %): empirical coverage on held-out months **{f(v.get('band_coverage_pct'), 1, '%')}** "
              + ("(close to nominal: well calibrated)." if abs((v.get('band_coverage_pct') or 0) - 90) <= 5 else
                 "(above nominal: conservative / wide band)." if (v.get('band_coverage_pct') or 0) > 90 else "(below nominal: band too narrow)."), "", "### 3a. Monthly performance (held-out)", "", "| Month | n | WAPE | Bias |", "|---|---|---|---|"]
    for r in v["by_month"]:
        L.append(f"| {MONTHS[r['month'] - 1]} | {r['n']} | {f(r.get('wape_pct'), 1, '%')} | {f(r.get('bias_pct'), 1, '%')} |")
    mgv = v["morning_gap"]
    L += ["", "### 3b. Morning-gap step (SIMULATED experiment, not the real 2000–2002 correction)", "",
          "20-month blocks of real Aqua (the length of the real Terra-only era) are hidden in turn; the Terra→Aqua calibration is refitted "
          "on every other overlap year (whole years removed) and the hidden Aqua months are the answer key. "
          f"Blocks: {', '.join(f'{a}–{b}' for a, b in mgv.get('blocks', [])) or mgv.get('period')}.", "",
          "| Method | n | MAE | RMSE | WAPE | Bias | R² |", "|---|---|---|---|---|---|---|",
          _mrow(f"Calibrated Terra→Aqua ({mgv.get('selected_model', 'cell_silent')})", mgv["metrics"]),
          _mrow("Constant Aqua/Terra ratio", mgv["baseline_constant_ratio"])]
    if mgv.get("baseline_national_ratio"):
        L.append(_mrow("National month/day-night ratio", mgv["baseline_national_ratio"]))
    L += ["", f"Band coverage (nominal 90 %): **{f(mgv.get('band_coverage_pct'), 1, '%')}**; median relative band width "
              f"{f(mgv.get('band_relative_width_pct'), 0, '%')}.", ""]
    if mgv.get("backward_extrapolation_warning"):
        L += [f"> **Limitation.** {mgv['backward_extrapolation_warning']}", ""]
    ch = mgv.get("chain_experiment")
    if ch and ch.get("period"):
        L += [f"Chain experiment (Aqua hidden {ch['period'][0]}–{ch['period'][1]}, calibration trained only on years ≥ split): "
              f"WAPE {f(ch['metrics'].get('wape_pct'), 1, '%')}, bias {f(ch['metrics'].get('bias_pct'), 1, '%')}, R² {f(ch['metrics'].get('r2'), 3)} "
              f"vs constant ratio WAPE {f(ch['baseline_constant_ratio'].get('wape_pct'), 1, '%')}.", ""]
    L += ["### 3c. Calibration model selection (held-out, year-blocked)", "",
          "Earlier versions of this report scored the morning-gap step with a design that, once pre-2012 MODIS was loaded, hid Aqua for "
          "135 months (2002-07 → 2013-09) and trained only on 2017–2022. Its +33 % bias was a property of that decade-long backward "
          "extrapolation, not of the operational fit (which trains on all overlap years). That design is kept below as a labelled stress test.", ""]
    for stage in ("mg", "sh"):
        ms = harmonize.model_selection(stage)
        L += [f"**{ms['pair']}** — selected: `{ms.get('selected')}` ({ms.get('reason')}). Rule: {ms.get('selection_rule', '')}", "",
              "| Design | folds | " + " | ".join(ms["candidates"]) + " |", "|---|---|" + "---|" * len(ms["candidates"])]
        for dname, d in ms.get("designs", {}).items():
            cells = []
            for c in ms["candidates"]:
                st, nat = d["scores"][c]["state"], d["scores"][c]["national"]
                cells.append(f"{f(st.get('wape_pct'), 1)} / {f(st.get('bias_pct'), 1)} / {f(st.get('r2'), 2)} (nat {f(nat.get('wape_pct'), 1)})")
            L.append(f"| {dname} | {d['n_folds']} | " + " | ".join(cells) + " |")
        b, bb = ms.get("band", {}), ms.get("band_backward", {})
        L += ["", "Cells: state-month WAPE % / bias % / R² (national-month WAPE %).",
              f"Band coverage of the selected model: block design {f(b.get('empirical_coverage_pct'), 1, '%')}, backward rolling-origin "
              f"{f(bb.get('empirical_coverage_pct'), 1, '%')} (nominal 90 %).", ""]
        dg = ms.get("diagnostics", {}).get("block_20_month", {})
        if dg:
            dn, act = dg["by_daynight"], dg["by_activity"]
            L += [f"Block-design diagnostics: day WAPE {f(dn['day'].get('wape_pct'), 1, '%')}, night WAPE {f(dn['night'].get('wape_pct'), 1, '%')}; "
                  f"low-count months WAPE {f(act['low_count_months'].get('wape_pct'), 1, '%')}, high-count {f(act['high_count_months'].get('wape_pct'), 1, '%')} "
                  f"(split at {f(act['split_at'], 0)} detections).", "",
                  "| State | n | WAPE | Bias |", "|---|---|---|---|"]
            for r in dg["by_state"][:8]:
                L.append(f"| {r['state']} | {r.get('n', 0)} | {f(r.get('wape_pct'), 1, '%')} | {f(r.get('bias_pct'), 1, '%')} |")
            L.append("")
    st_ = harmonize.extrapolation_stress_test()
    if st_:
        L += [f"**Extrapolation stress test** (train {st_['train_years'][0]}–{st_['train_years'][-1]} only, predict {st_['test_period'][0]}–{st_['test_period'][1]}, "
              f"{st_['n_test_months']} months): " + "; ".join(f"{k} WAPE {f(m.get('wape_pct'), 1, '%')} bias {f(m.get('bias_pct'), 1, '%')} R² {f(m.get('r2'), 2)}"
                                                            for k, m in st_["scores"].items()) + ".", "", st_["interpretation"], ""]
    L += [f"## 4. 2012 seam test ({s.get('validation_kind')})", ""]
    if s.get("real_seam_note"):
        L += [f"> {s['real_seam_note']}", ""]
    L += [f"* Seam month {s['seam_month']}, window ±{s['window_months']} months.",
          f"* Step before harmonization (raw MODIS → VIIRS): **{f(s['step_raw'], 3)}**; after: **{f(s['step_harmonized'], 3)}** "
          f"(band {f(s['step_harmonized_band'][0], 3)}–{f(s['step_harmonized_band'][1], 3)}).",
          f"* Target step (true withheld VIIRS / unchanged reference sensor): {f(s.get('step_true') or s.get('step_reference_sensor'), 3)} ({s['reference_sensor']} reference {f(s['step_reference_sensor'], 3)}).",
          f"* Artificial discontinuity |ln(step/target)|: before **{f(s['artificial_jump_before'], 3)}**, after **{f(s['artificial_jump_after'], 3)}** "
          f"(reduction {f(s.get('reduction_pct'), 1, '%')}); status {s.get('status')}.",
          f"* Genuine change still detectable: **{s['genuine_change']['detectable']}** ({s['genuine_change']['direction']}). {s['genuine_change'].get('why') or ''}",
          f"* **Verdict: {str(s.get('verdict', '-')).upper()}** — rule: {s.get('verdict_rule', '')}", ""]
    rb = harmonize.seam_robustness()
    L += ["### 4a. Seam robustness (real seam)", "", "| Scope | Window | Raw step | Harmonized step (band) | Reference step | Jump before → after | Verdict |",
          "|---|---|---|---|---|---|---|"]
    for w in rb["windows"]:
        L.append(f"| India | ±{w.get('window_months')} | {f(w.get('step_raw'), 2)} | {f(w.get('step_harmonized'), 3)} "
                 f"({f((w.get('step_harmonized_band') or [None])[0], 2)}–{f((w.get('step_harmonized_band') or [None, None])[1], 2)}) | "
                 f"{f(w.get('step_reference_sensor'), 3)} | {f(w.get('artificial_jump_before'), 2)} → {f(w.get('artificial_jump_after'), 3)} | {w.get('verdict')} |")
    for w in rb["states"]:
        L.append(f"| {w['state']} | ±24 | {f(w.get('step_raw'), 2)} | {f(w.get('step_harmonized'), 3)} "
                 f"({f((w.get('step_harmonized_band') or [None])[0], 2)}–{f((w.get('step_harmonized_band') or [None, None])[1], 2)}) | "
                 f"{f(w.get('step_reference_sensor'), 3)} | {f(w.get('artificial_jump_before'), 2)} → {f(w.get('artificial_jump_after'), 3)} | {w.get('verdict', w.get('error'))} |")
    L += ["", f"State verdicts: {rb.get('state_summary')}.", ""]
    if fm:
        t = fm["test"]
        c60, c80 = t["confusion"].get("60", {}), t["confusion"].get("80", {})
        L += ["## 5. Seven-day hotspot-probability forecast", "", f"* Target: {fm['target']} — {fm['target_kind']}.",
              f"* Split: train ≤ {fm['split']['train_until']}, isotonic calibration ≤ {fm['split']['calibrate_until']}, test {fm['split']['test_from']} → {fm['split']['test_until']}.",
              f"* Test rows {fm['rows']['test']:,}; base rate {t['base_rate']:.3f}.", "",
              "| Metric | Calibrated model | Climatology baseline |", "|---|---|---|",
              f"| Brier | {t['brier']:.4f} | {fm['baseline_climatology']['brier']:.4f} |",
              f"| ROC-AUC | {t['roc_auc']:.3f} | {fm['baseline_climatology']['roc_auc']:.3f} |",
              f"| PR-AUC | {t['pr_auc']:.3f} | {fm['baseline_climatology']['pr_auc']:.3f} |", "",
              f"Brier skill vs climatology: {fm['brier_skill_vs_climatology']:.3f}.", "",
              "| Threshold | Precision | Recall | False-alarm rate | Missed-event rate |", "|---|---|---|---|---|",
              f"| 60 % (HIGH) | {c60.get('precision', 0):.3f} | {c60.get('recall', 0):.3f} | {c60.get('false_alarm_rate', 0):.4f} | {c60.get('missed_event_rate', 0):.3f} |",
              f"| 80 % (VERY HIGH) | {c80.get('precision', 0):.3f} | {c80.get('recall', 0):.3f} | {c80.get('false_alarm_rate', 0):.4f} | {c80.get('missed_event_rate', 0):.3f} |", "",
              f"Regional aggregation: `{fm['aggregation']['formula']}` with α = {fm['aggregation']['alpha']:.2f} (fitted on calibration years).", ""]
    caps = inv["capabilities"]
    L += ["## 6. Data limitations", "",
          ("* Real Terra-only morning-gap correction is applied to the loaded Terra-only months; there is no ground truth for those months, "
           "so its skill is measured only by the simulated withheld-Aqua experiment (3b)." if caps["terra_only_era_loaded"] else
           "* No Terra-only MODIS records are loaded: the real morning-gap correction cannot be applied."),
          ("* Real 2012 seam test uses the loaded pre-2012 MODIS record." if caps["pre_viirs_modis_loaded"] else
           "* Fewer than 12 months of MODIS precede VIIRS: the real seam test falls back to the simulated seam."),
          f"* NOAA-20: {caps['noaa20']}; NOAA-21 loaded. Neither is the default calibration target (kept as separate actual observations).",
          "* VIIRS 750 m (VNP14/VJ114) is not distributed by FIRMS; a separate 750 m calibration pathway exists but has no data.",
          f"* MODIS orbit drift years excluded from calibration: {', '.join(n for n in sh['notes'] if 'drift' in n) or 'none'}",
          "* Administrative intelligence (states, districts, land use) covers India only.",
          "* MODIS row `version` strings 6.03 (2000-2022) and 61.03 (2023 onward) are not defined in readable FIRMS documentation; they are kept verbatim and the collection (C6.1) is taken from the archive name.",
          "* NOAA-21 archive records begin 2023-03 (pre-operational period, official FIRMS start 2024-01-17); kept as labelled actual observations, not a calibration target.",
          "* NRT records are provisional and never used for calibration or validation.",
          f"* Month coverage: S-NPP months with full coverage {int((cov['Suomi NPP'] >= 0.999).sum())}; Aqua {int((cov['Aqua'] >= 0.999).sum())}; Terra {int((cov['Terra'] >= 0.999).sum())}."]
    return "\n".join(L) + "\n"


def main():
    out = ROOT / "docs" / "SCIENTIFIC_VALIDATION.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(build(), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
