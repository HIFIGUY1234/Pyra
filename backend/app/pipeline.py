"""One-command offline pipeline:  python -m app.pipeline [--skip-ingest] [--skip-weather] [--skip-train]

Repository archives -> standardised Parquet -> grid / boundaries / land cover ->
daily & monthly summaries -> NASA POWER weather -> forecast model -> database tables.
"""
from __future__ import annotations

import sys
import time

from . import analytics, db_sync, forecast, geo, harmonize, ingest, store, weather


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    t0 = time.time()
    if "--skip-ingest" not in argv:
        for k, v in ingest.process_all(log=lambda *a: None).items():
            print(f"[pipeline] {k}: {v.get('error') or v['quality']['rows_kept']}")
    if not geo.CELLS_PATH.exists() or "--rebuild-geo" in argv:
        geo.build_cells()
    store.build_summaries()
    harmonize.clear()
    if "--skip-weather" not in argv and not weather.WEATHER_PATH.exists():
        try:
            weather.fetch_all(end=analytics.data_end().strftime("%Y%m%d"))
        except Exception as exc:  # offline: the forecast then trains without weather and says so
            print(f"[pipeline] NASA POWER unavailable ({exc}); continuing without weather features")
    if "--skip-train" not in argv:
        forecast.train()
    db_sync.sync_all()
    v = harmonize.validation("country")
    print(f"[pipeline] harmonization hold-out: {v.get('status')} | WAPE {v['overall'].get('wape_pct'):.1f}% | done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
