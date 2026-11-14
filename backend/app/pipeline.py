"""One-command offline pipeline:
    python -m app.pipeline [--recover-lfs] [--only-new] [--skip-ingest] [--skip-weather] [--skip-train] [--rebuild-geo]

  --recover-lfs  download real archives for any Git LFS pointer stubs (SHA-256 verified)
  --only-new     ingest only sources not yet in the registry (restartable / incremental)
  --skip-train   keep the existing forecast model (default when nothing new was ingested)


Repository archives -> standardised Parquet -> grid / boundaries / land cover ->
daily & monthly summaries -> NASA POWER weather -> forecast model -> database tables.
"""
from __future__ import annotations

import sys
import time

from . import acquire, analytics, db_sync, forecast, geo, harmonize, ingest, store, weather


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    t0 = time.time()
    if "--recover-lfs" in argv:
        for r in acquire.recover_lfs():
            print(f"[pipeline] lfs {r['file']}: {r['status']}")
    new = {}
    if "--skip-ingest" not in argv:
        new = ingest.process_all(only_new="--only-new" in argv, log=lambda *a: None)
        for k, v in new.items():
            print(f"[pipeline] {k}: {v.get('error') or v['quality']['rows_kept']}")
    rep = acquire.build_report()
    print(f"[pipeline] inventory: {rep['capabilities']}")
    for m in rep["missing"]:
        print(f"[pipeline] MISSING {m['satellite']} {m['period']}")
    if not geo.CELLS_PATH.exists() or "--rebuild-geo" in argv:
        geo.build_cells()
    store.build_summaries()
    harmonize.clear()
    if "--skip-weather" not in argv and not weather.WEATHER_PATH.exists():
        try:
            weather.fetch_all(end=analytics.data_end().strftime("%Y%m%d"))
        except Exception as exc:  # offline: the forecast then trains without weather and says so
            print(f"[pipeline] NASA POWER unavailable ({exc}); continuing without weather features")
    ingested_ok = [k for k, v in new.items() if not v.get("error")]
    if "--skip-train" not in argv and (ingested_ok or not forecast.available() or "--retrain" in argv):
        forecast.train()
    else:
        print("[pipeline] forecast model kept (" + ("--skip-train" if "--skip-train" in argv else "nothing new ingested; pass --retrain to force") + ")")
    db_sync.sync_all()
    v = harmonize.validation("country")
    print(f"[pipeline] harmonization hold-out: {v.get('status')} | WAPE {v['overall'].get('wape_pct'):.1f}% | done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
