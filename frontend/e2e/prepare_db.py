"""Copy the demo database for an e2e run and strip credentials from the COPY only.

The working data/pyroscope.db may carry an admin hash bootstrapped from a developer's .env; the backend only
bootstraps PYROSCOPE_ADMIN_PASSWORD when the admin has no hash, so without this the e2e password would be ignored.
Usage: python prepare_db.py <source.db> <dest.db>"""
import shutil
import sqlite3
import sys

src, dst = sys.argv[1], sys.argv[2]
shutil.copy(src, dst)
con = sqlite3.connect(dst)
try:
    con.execute("UPDATE users SET password_hash = NULL, failed_logins = 0, locked_until = NULL")
    con.execute("DELETE FROM user_sessions")
    con.commit()
finally:
    con.close()
print(f"e2e database prepared: {dst}")
