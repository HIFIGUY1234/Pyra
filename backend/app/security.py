"""Authentication: password hashing, opaque bearer sessions, auth mode.

AUTH_MODE (env PYROSCOPE_AUTH_MODE):
  dev         default for zero-config local evaluation. A Bearer token is honoured if sent;
              otherwise the X-User demo-persona header is accepted. Responses say so.
  production  Bearer token required on every protected endpoint. The X-User header is ignored.

Passwords: PBKDF2-HMAC-SHA256 (stdlib), per-user random salt, constant-time comparison.
Sessions: 256-bit random tokens; only their SHA-256 is stored, so a database leak does not
reveal usable tokens. Sessions expire and are revoked on logout.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import timedelta

ITERATIONS = int(os.getenv("PYROSCOPE_PBKDF2_ITERATIONS", "240000"))
SESSION_HOURS = int(os.getenv("PYROSCOPE_SESSION_HOURS", "12"))
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 10


def auth_mode() -> str:
    m = os.getenv("PYROSCOPE_AUTH_MODE", "dev").strip().lower()
    return m if m in ("dev", "production") else "dev"


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    check_password_policy(password)
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not password:
        # burn comparable time so user enumeration by timing is harder
        hashlib.pbkdf2_hmac("sha256", b"x", b"pyroscope-dummy-salt", ITERATIONS)
        return False
    try:
        algo, it, salt, dk = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(got.hex(), dk)
    except (ValueError, TypeError):
        return False


def check_password_policy(password: str):
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    if password.lower() == password or password.upper() == password or not any(ch.isdigit() for ch in password):
        raise ValueError("password needs upper- and lower-case letters and a digit")


def new_token() -> tuple[str, str]:
    """-> (token for the client, sha256 digest for the database)."""
    t = secrets.token_urlsafe(32)
    return t, token_digest(t)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_ttl() -> timedelta:
    return timedelta(hours=SESSION_HOURS)


# --------------------------------------------------------------------------- rate limiting
# Sliding-window limiter keyed by (bucket, client). It is per-process: with several backend workers each
# worker counts separately, so production deployments must ALSO limit at the reverse proxy (frontend/nginx.conf
# uses limit_req for /api/auth/login, uploads and reports). Disable with PYROSCOPE_RATE_LIMIT=off (tests only).
import threading as _threading
import time as _time
from collections import deque as _deque

RATE_LIMITS = {  # bucket: (max requests, window seconds)
    "login": (int(os.getenv("PYROSCOPE_RL_LOGIN", "10")), 60),
    "upload": (int(os.getenv("PYROSCOPE_RL_UPLOAD", "5")), 600),
    "processing": (int(os.getenv("PYROSCOPE_RL_PROCESSING", "6")), 600),
    "report": (int(os.getenv("PYROSCOPE_RL_REPORT", "20")), 600),
    "admin": (int(os.getenv("PYROSCOPE_RL_ADMIN", "30")), 600),
}
_hits: dict = {}
_rl_lock = _threading.Lock()


def rate_limit_enabled() -> bool:
    return os.getenv("PYROSCOPE_RATE_LIMIT", "on").strip().lower() != "off"


def check_rate(bucket: str, client: str, now: float | None = None) -> float | None:
    """Record one hit. Returns None if allowed, else seconds until the next request is allowed."""
    if not rate_limit_enabled():
        return None
    limit, window = RATE_LIMITS[bucket]
    t = _time.monotonic() if now is None else now
    with _rl_lock:
        q = _hits.setdefault((bucket, client), _deque())
        while q and q[0] <= t - window:
            q.popleft()
        if len(q) >= limit:
            return max(0.0, q[0] + window - t)
        q.append(t)
        return None


def reset_rate_limits():
    with _rl_lock:
        _hits.clear()
