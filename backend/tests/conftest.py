"""Keep test side effects out of the working data directory."""
import os
import tempfile

os.environ.setdefault("PYROSCOPE_REPORTS_DIR", tempfile.mkdtemp(prefix="pyroscope_reports_"))
os.environ.setdefault("PYROSCOPE_PBKDF2_ITERATIONS", "20000")   # faster hashing in tests only


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
