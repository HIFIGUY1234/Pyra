"""Additive, non-destructive schema migrations.

    python -m app.migrate            # back up (SQLite) then upgrade
    python -m app.migrate --dry-run  # list what would change

New tables are created; new columns are added with ALTER TABLE ... ADD COLUMN. Nothing is
dropped or rewritten, so existing records survive. Before changing a SQLite database the
file is copied to data/backups/. Rollback: stop the API and copy the backup over
data/pyroscope.db (PostgreSQL: restore your pg_dump taken before upgrading).
Applied migrations are recorded in `schema_migrations`.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text

from . import models as M
from .config import DATA, DATABASE_URL

BACKUPS = DATA / "backups"


def sqlite_path() -> Path | None:
    if not DATABASE_URL.startswith("sqlite:///"):
        return None
    return Path(DATABASE_URL.replace("sqlite:///", "", 1))


def backup() -> Path | None:
    p = sqlite_path()
    if not p or not p.exists():
        return None
    bdir = BACKUPS if p.parent == DATA else p.parent / "backups"   # keep backups beside the database they protect
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / f"{p.stem}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
    shutil.copy2(p, dest)
    return dest


def _coltype(col, dialect) -> str:
    return col.type.compile(dialect=dialect)


def pending() -> dict:
    insp = inspect(M.engine)
    existing = set(insp.get_table_names())
    out = {"new_tables": [], "new_columns": [], "new_indexes": []}
    for t in M.Base.metadata.sorted_tables:
        if t.name not in existing:
            out["new_tables"].append(t.name)
            continue
        have = {c["name"] for c in insp.get_columns(t.name)}
        for c in t.columns:
            if c.name not in have:
                out["new_columns"].append((t.name, c))
        idx = {i["name"] for i in insp.get_indexes(t.name)}
        for i in t.indexes:
            if i.name and i.name not in idx:
                out["new_indexes"].append(i)
    return out


def upgrade(dry_run: bool = False, log=print) -> dict:
    todo = pending()
    summary = {"new_tables": todo["new_tables"], "new_columns": [f"{t}.{c.name}" for t, c in todo["new_columns"]],
               "new_indexes": [i.name for i in todo["new_indexes"]], "backup": None}
    if dry_run or not any(todo.values()):
        return summary
    summary["backup"] = str(backup()) if sqlite_path() else None
    if summary["backup"]:
        log(f"[migrate] backup written to {summary['backup']}")
    M.Base.metadata.create_all(M.engine)          # creates new tables (+ their indexes) only
    with M.engine.begin() as conn:
        for t, c in todo["new_columns"]:
            ddl = f'ALTER TABLE {t} ADD COLUMN {c.name} {_coltype(c, M.engine.dialect)}'
            if c.default is not None and getattr(c.default, "is_scalar", False):
                v = c.default.arg
                ddl += f" DEFAULT {int(v) if isinstance(v, bool) else repr(v) if isinstance(v, str) else v}"
            conn.execute(text(ddl))
            log(f"[migrate] {ddl}")
        for i in todo["new_indexes"]:
            if i.table.name not in todo["new_tables"]:
                i.create(conn, checkfirst=True)
        pk = "SERIAL PRIMARY KEY" if M.engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
        conn.execute(text(f"CREATE TABLE IF NOT EXISTS schema_migrations (id {pk}, applied_at VARCHAR(40), summary TEXT)"))
        conn.execute(text("INSERT INTO schema_migrations (applied_at, summary) VALUES (:a, :s)"),
                     {"a": datetime.now(timezone.utc).isoformat(timespec="seconds"), "s": str({k: v for k, v in summary.items() if k != 'backup'})})
    return summary


if __name__ == "__main__":
    print(upgrade(dry_run="--dry-run" in sys.argv[1:]))
