"""One-command offline pipeline (restartable, incremental).

    python -m app.pipeline [--recover-lfs] [--only-new] [--skip-ingest] [--skip-weather]
                           [--skip-train | --retrain] [--rebuild-geo] [--skip-report]
                           [--refresh-exposure] [--refresh-tle] [--compare-forecast]
                           [--viirs750 START END] [--linear-gis] [--sensor-models] [--dry-run] [--validate-only]

Archive discovery -> LFS recovery -> ZIP validation -> CSV extraction / cleaning / satellite + product
identification / standardisation / de-duplication -> Parquet -> spatial assignment -> quality analysis
-> daily & monthly summaries -> harmonization + uncertainty + validation -> NASA POWER weather ->
forecast model -> database sync -> inventory report -> scientific report.

Per-source checkpoints live in the ingestion registry (data/processed/datasets.json): with --only-new
already processed sources are skipped. Every step's outcome is appended to
data/processed/pipeline_state.json (used by the data-freshness dashboard). Unknown arguments are an error.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime, timezone

from .config import PROCESSED

STATE = PROCESSED / "pipeline_state.json"


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m app.pipeline", description=__doc__.split("\n\n")[0])
    ap.add_argument("--recover-lfs", action="store_true", help="download real archives for Git LFS pointer stubs (SHA-256 verified)")
    ap.add_argument("--only-new", action="store_true", help="ingest only sources not yet in the registry")
    ap.add_argument("--skip-ingest", action="store_true", help="do not ingest archives; rebuild downstream products only")
    ap.add_argument("--skip-weather", action="store_true", help="do not fetch NASA POWER weather")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--skip-train", action="store_true", help="keep the existing forecast model")
    g.add_argument("--retrain", action="store_true", help="retrain the forecast model even if nothing new was ingested")
    ap.add_argument("--rebuild-geo", action="store_true", help="rebuild grid cells, boundaries and land cover")
    ap.add_argument("--skip-report", action="store_true", help="do not regenerate docs/SCIENTIFIC_VALIDATION.md")
    ap.add_argument("--refresh-exposure", action="store_true", help="download WorldPop 2020 and OpenStreetMap infrastructure, rebuild exposure layers")
    ap.add_argument("--refresh-tle", action="store_true", help="fetch current TLEs from CelesTrak and re-validate overpass prediction")
    ap.add_argument("--compare-forecast", action="store_true", help="run the forecast candidate-model comparison (slow)")
    ap.add_argument("--viirs750", nargs=2, metavar=("START", "END"), help="search, download (Earthdata Login) and convert VIIRS 750 m granules")
    ap.add_argument("--linear-gis", action="store_true", help="download the Geofabrik India PBF and build road / rail / power / settlement layers")
    ap.add_argument("--sensor-models", action="store_true", help="(re)train the independent NOAA-20 and NOAA-21 forecast models and re-run the operational-reference evaluation")
    ap.add_argument("--dry-run", action="store_true", help="show what would run (archives, new sources, steps) and change nothing")
    ap.add_argument("--validate-only", action="store_true", help="validate archives and the loaded data (integrity, hold-out, seam); write nothing else")
    return ap.parse_args(argv)   # argparse exits with an error on unknown arguments


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"steps": {}, "runs": []}


class Run:
    def __init__(self, args):
        self.state = _load_state()
        self.t0 = time.time()
        self.run = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "args": vars(args), "steps": []}

    def step(self, name, fn, *a, **kw):
        t = time.time()
        print(f"[pipeline] >> {name}", flush=True)
        try:
            res = fn(*a, **kw)
        except Exception as exc:
            rec = {"step": name, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "seconds": round(time.time() - t, 1)}
            self._record(rec)
            print(f"[pipeline] !! {name} failed: {exc}")
            traceback.print_exc()
            raise
        rec = {"step": name, "status": "ok", "seconds": round(time.time() - t, 1)}
        self._record(rec)
        print(f"[pipeline] ok {name} ({rec['seconds']}s)", flush=True)
        return res

    def skip(self, name, why):
        self._record({"step": name, "status": "skipped", "reason": why})
        print(f"[pipeline] -- {name} skipped: {why}")

    def _record(self, rec):
        rec["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.run["steps"].append(rec)
        if rec["status"] == "ok":
            self.state["steps"][rec["step"]] = {"last_success": rec["at"], "seconds": rec.get("seconds")}
        elif rec["status"] == "failed":
            self.state["steps"].setdefault(rec["step"], {})["last_failure"] = {"at": rec["at"], "error": rec["error"]}
        self.save()

    def save(self, final=False):
        if final:
            self.run["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.run["seconds"] = round(time.time() - self.t0, 1)
        runs = [r for r in self.state.get("runs", []) if r.get("started_at") != self.run["started_at"]]
        self.state["runs"] = (runs + [self.run])[-20:]
        STATE.write_text(json.dumps(self.state, indent=1, default=str))


def dry_run(args) -> dict:
    from . import acquire, ingest
    from .config import ROOT
    archives = [acquire.archive_status(z, checksum=False) for z in sorted(ROOT.glob("*.zip"))]
    reg = ingest.load_registry()
    srcs = ingest.discover_sources()
    new = [s["key"] for s in srcs if s["key"] not in reg]
    plan = {"archives": [{k: a.get(k) for k in ("file", "status", "integrity", "bytes")} for a in archives],
            "pointers_to_recover": [a["file"] for a in archives if a["status"] == "lfs_pointer"],
            "sources_total": len(srcs), "sources_new": new,
            "would_ingest": [] if args.skip_ingest else (new if args.only_new else [s["key"] for s in srcs])}
    print(json.dumps(plan, indent=1))
    return plan


def validate_only() -> dict:
    from . import acquire, harmonize, store
    from .config import ROOT
    out = {"archives": [acquire.archive_status(z) for z in sorted(ROOT.glob("*.zip"))]}
    bad = [a["file"] for a in out["archives"] if a["status"] != "valid"]
    out["archive_problems"] = bad
    if store.has_data():
        v = harmonize.validation("country")
        s = harmonize.seam_test("country")
        out["holdout"] = {"status": v.get("status"), "wape_pct": v["overall"].get("wape_pct"), "bias_pct": v["overall"].get("bias_pct"),
                          "morning_gap": {k: v["morning_gap"]["metrics"].get(k) for k in ("wape_pct", "bias_pct", "r2")}}
        out["seam"] = {k: s.get(k) for k in ("mode", "seam_month", "step_raw", "step_harmonized", "artificial_jump_after", "verdict")}
        out["coverage"] = {k: {x: v.get(x) for x in ("first", "last", "last_typed", "detections")} for k, v in store.spans().items()}
        from . import noaa21
        n = noaa21.study()
        out["noaa21"] = {"status": n.get("status"), "selected": n.get("selected"), "reason": n.get("selection_reason")}
    from . import orbits, population, infrastructure
    out["exposure_layers"] = {"population": bool(population.manifest()), "infrastructure": bool(infrastructure.manifest())}
    out["orbit_validation"] = {k: v.get("mean_abs_residual_min") for k, v in orbits.validation_summary().items() if isinstance(v, dict)}
    print(json.dumps(out, indent=1, default=str))
    return out


def main(argv=None):
    args = parse_args(argv)
    if args.dry_run:
        return dry_run(args)
    if args.validate_only:
        return validate_only()
    from . import acquire, analytics, db_sync, forecast, geo, harmonize, ingest, science_report, store, weather
    r = Run(args)
    try:
        if args.recover_lfs:
            for x in r.step("lfs_recovery", acquire.recover_lfs):
                print(f"[pipeline]    lfs {x['file']}: {x['status']}")
        else:
            r.skip("lfs_recovery", "pass --recover-lfs to download pointer stubs")
        new = {}
        if not args.skip_ingest:
            new = r.step("ingest", ingest.process_all, only_new=args.only_new, log=lambda *a: None)
            for k, v in new.items():
                print(f"[pipeline]    {k}: {v.get('error') or v['quality']['rows_kept']}")
        else:
            r.skip("ingest", "--skip-ingest")
        rep = r.step("inventory_report", acquire.build_report)
        print(f"[pipeline]    inventory: {rep['capabilities']}")
        for m in rep["missing"]:
            print(f"[pipeline]    MISSING {m['satellite']} {m['period']}")
        if not geo.CELLS_PATH.exists() or args.rebuild_geo:
            r.step("spatial_assignment", geo.build_cells)
        else:
            r.skip("spatial_assignment", "grid cells exist (pass --rebuild-geo to rebuild)")
        r.step("summaries", store.build_summaries)
        harmonize.clear()
        if args.skip_weather:
            r.skip("weather", "--skip-weather")
        elif weather.WEATHER_PATH.exists():
            r.skip("weather", "weather table exists")
        else:
            try:
                r.step("weather", weather.fetch_all, end=analytics.data_end().strftime("%Y%m%d"))
            except Exception as exc:  # offline: the forecast trains without weather and says so
                print(f"[pipeline]    NASA POWER unavailable ({exc}); continuing without weather features")
        ingested_ok = [k for k, v in new.items() if not v.get("error")]
        if not args.skip_train and (ingested_ok or not forecast.available("Suomi NPP") or args.retrain):
            r.step("forecast_training", forecast.train)
        else:
            r.skip("forecast_training", "--skip-train" if args.skip_train else "nothing new ingested; pass --retrain to force")
        if args.sensor_models or (not args.skip_train and (ingested_ok or args.retrain)):
            for snr in ("NOAA-20", "NOAA-21"):
                if snr in store.spans():
                    r.step(f"forecast_training_{snr}", forecast.train, sensor=snr)
                else:
                    r.skip(f"forecast_training_{snr}", f"{snr} not loaded")
        else:
            r.skip("forecast_training_sensors", "pass --sensor-models (or ingest new data) to retrain NOAA-20 / NOAA-21 models")
        from . import bridge, operational
        bridge.clear(recompute=bool(ingested_ok) or bool(args.sensor_models) or bool(getattr(args, "retrain", False))); operational.clear()
        sel = r.step("operational_reference", operational.summary)
        print(f"[pipeline]    operational reference: {sel['operational_reference']} ({sel['operational_status']})")
        r.step("database_sync", db_sync.sync_all)
        v = r.step("harmonization_validation", harmonize.validation, "country")
        print(f"[pipeline]    hold-out: {v.get('status')} | WAPE {v['overall'].get('wape_pct'):.1f}% | morning-gap WAPE "
              f"{v['morning_gap']['metrics'].get('wape_pct'):.1f}%")
        if args.refresh_exposure:
            from . import infrastructure, population
            r.step("population", lambda: population.build(population.acquire(), method="area_weighted"))
            r.step("infrastructure", infrastructure.acquire)
        else:
            r.skip("exposure_layers", "pass --refresh-exposure to download WorldPop / OpenStreetMap")
        if args.refresh_tle:
            from . import orbits
            r.step("tle_refresh", orbits.refresh_all)
            r.step("orbit_validation", orbits.run_validation)
        else:
            r.skip("tle_refresh", "pass --refresh-tle")
        if args.viirs750:
            from . import viirs750
            if not viirs750.credentials_status()["configured"]:
                r.skip("viirs750", "Earthdata Login not configured (EARTHDATA_TOKEN or ~/.netrc)")
            else:
                for sat in viirs750.PRODUCTS:
                    r.step(f"viirs750_{sat}", lambda s=sat: viirs750.download(viirs750.search(s, *args.viirs750)))
                r.step("viirs750_convert", viirs750.convert)
        if args.linear_gis:
            from . import linear_gis
            pbf = r.step("linear_gis_download", linear_gis.acquire)
            r.step("linear_gis_build", linear_gis.build, pbf, node_index="sparse_file_array," + str(linear_gis.LIN_DIR / "nodes.idx"))
        else:
            r.skip("linear_gis", "pass --linear-gis to download and process the Geofabrik extract")
        if args.compare_forecast:
            from . import forecast_eval
            r.step("forecast_comparison", forecast_eval.compare)
        if args.skip_report:
            r.skip("scientific_report", "--skip-report")
        else:
            r.step("scientific_report", science_report.main)
    finally:
        r.save(final=True)
    print(f"[pipeline] done in {time.time() - r.t0:.0f}s")


if __name__ == "__main__":
    main()
