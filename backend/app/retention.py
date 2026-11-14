"""Audit-log retention: archive, then prune.

Policy (env, defaults):
  PYROSCOPE_AUDIT_RETENTION_DAYS = 730   audit rows older than this are eligible
  Only routine rows (PRUNABLE_ACTIONS: logins, logouts, report generation, TLE refresh) are ever pruned. Alert
  lifecycle, contact verification, user, threshold and layer changes are the record of human decisions and are
  kept indefinitely (archive them manually if storage requires).

Pruning always writes the rows first to a gzip JSON-lines archive (data/backups/audit/) and verifies the archive
can be read back with the same row count before anything is deleted. Default is a dry run.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select

from . import models as M
from .config import DATA

ARCHIVE_DIR = DATA / "backups" / "audit"
PRUNABLE_ACTIONS = {"LOGIN", "LOGIN_FAILED", "LOGOUT", "REPORT_GENERATED", "TLE_REFRESH"}


def retention_days() -> int:
    return int(os.getenv("PYROSCOPE_AUDIT_RETENTION_DAYS", "730"))


def _protected(action: str | None) -> bool:
    return (action or "").upper() not in PRUNABLE_ACTIONS


def prune_audit(days: int | None = None, dry_run: bool = True, archive_dir: Path | None = None, now: datetime | None = None) -> dict:
    days = retention_days() if days is None else days
    if days < 30:
        raise ValueError("retention below 30 days is not allowed")
    cutoff = (now or datetime.now(timezone.utc)).replace(tzinfo=None) - timedelta(days=days)
    with M.Session() as s:
        old = s.scalars(select(M.AuditLog).where(M.AuditLog.at < cutoff).order_by(M.AuditLog.id)).all()
        eligible = [r for r in old if not _protected(r.action)]
        res = {"cutoff": cutoff.isoformat(), "retention_days": days, "older_than_cutoff": len(old),
               "protected_kept": len(old) - len(eligible), "eligible": len(eligible), "dry_run": dry_run, "archive": None, "deleted": 0}
        if dry_run or not eligible:
            return res
        d = archive_dir or ARCHIVE_DIR
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"audit_until_{cutoff:%Y%m%d}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            for r in eligible:
                fh.write(json.dumps({"id": r.id, "at": r.at.isoformat() if r.at else None, "actor": r.actor, "actor_role": r.actor_role,
                                     "action": r.action, "entity": r.entity, "entity_id": r.entity_id, "detail": r.detail}, default=str) + "\n")
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            back = sum(1 for _ in fh)
        if back != len(eligible):
            raise IOError(f"archive verification failed ({back} != {len(eligible)}); nothing deleted")
        ids = [r.id for r in eligible]
        for i in range(0, len(ids), 500):
            s.execute(delete(M.AuditLog).where(M.AuditLog.id.in_(ids[i:i + 500])))
        s.add(M.AuditLog(actor="system", action="AUDIT_RETENTION", entity="audit_logs", entity_id=str(len(ids)),
                         detail={"archive": path.name, "cutoff": cutoff.isoformat()}))
        s.commit()
        res.update(archive=str(path), deleted=len(ids))
        return res
