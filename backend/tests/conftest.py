"""Keep test side effects out of the working data directory."""
import os
import tempfile

os.environ.setdefault("PYROSCOPE_REPORTS_DIR", tempfile.mkdtemp(prefix="pyroscope_reports_"))
os.environ.setdefault("PYROSCOPE_PBKDF2_ITERATIONS", "20000")   # faster hashing in tests only

# Tests write alerts, contacts and audit rows: run them on a throw-away copy of data/pyroscope.db so the
# working database is never modified and every run starts from the same committed state.
if "DATABASE_URL" not in os.environ:
    import shutil
    from pathlib import Path
    _src = Path(__file__).resolve().parents[2] / "data" / "pyroscope.db"
    _db = Path(tempfile.mkdtemp(prefix="pyroscope_db_")) / "pyroscope.db"
    if _src.exists():
        shutil.copy(_src, _db)
    os.environ["DATABASE_URL"] = f"sqlite:///{_db.as_posix()}"


def pytest_configure(config):
    """Inventory/LFS reports written during tests go to a temp dir, never over data/processed."""
    from pathlib import Path
    from app import acquire
    out = Path(tempfile.mkdtemp(prefix="pyroscope_inventory_"))
    acquire.REPORT_JSON = out / "ingestion_report.json"
    acquire.REPORT_MD = out / "ingestion_report.md"
    acquire.LFS_REPORT = out / "lfs_recovery_report.json"
    import shutil
    ck = out / "archive_checksums.json"
    if acquire.CHECKSUMS.exists():
        shutil.copy(acquire.CHECKSUMS, ck)
    acquire.CHECKSUMS = ck


import pytest


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Each test starts with empty rate-limit windows (limits stay enabled, as in production)."""
    from app import security
    security.reset_rate_limits()
    yield
