"""Keep test side effects out of the working data directory."""
import os
import tempfile

os.environ.setdefault("PYROSCOPE_REPORTS_DIR", tempfile.mkdtemp(prefix="pyroscope_reports_"))
os.environ.setdefault("PYROSCOPE_PBKDF2_ITERATIONS", "20000")   # faster hashing in tests only
