"""Persistent background worker: `python -m app.worker [--once] [--poll SECONDS]`.

Claims jobs from the `data_jobs` table (see app.jobs), heartbeats while running, retries with backoff and
recovers jobs whose worker died (expired lease). Run one or more workers next to the API; they coordinate only
through the database, so they can run on another host as long as they share DATABASE_URL and storage.
"""
from __future__ import annotations

import argparse
import logging
import signal
import time

from . import db_sync, jobs

log = logging.getLogger("pyroscope.worker")
_stop = False


def _sig(*_):
    global _stop
    _stop = True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.worker")
    ap.add_argument("--once", action="store_true", help="process runnable jobs until the queue is empty, then exit")
    ap.add_argument("--poll", type=float, default=5.0, help="seconds between queue polls when idle")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    db_sync.init_db()
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    log.info("worker %s started (lease %ss)", jobs.WORKER_ID, jobs.LEASE_S)
    done = 0
    while not _stop:
        jid = jobs.run_once()
        if jid is not None:
            done += 1
            log.info("job %s finished: %s", jid, jobs.get(jid)["status"])
            continue
        if a.once:
            break
        time.sleep(a.poll)
    log.info("worker stopping after %d jobs", done)
    return done


if __name__ == "__main__":
    main()
