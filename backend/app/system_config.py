"""Configuration validation and credential readiness (never reveals secret values).

`validate()` checks the environment for the selected mode. In production it returns ERRORS for unsafe
settings (wildcard CORS, no admin bootstrap, weak/default admin password, non-persistent database, rate limiting
off, X-User trusted) and WARNINGS for things that degrade service (notifications simulated, no Earthdata access).
The API refuses to start in production while any ERROR remains (see main.py startup).

`credentials()` reports, per external integration, only CONFIGURED / NOT_CONFIGURED / INVALID plus the variable
names to set -- never the values.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

WEAK = {"admin", "password", "changeme", "change_me", "pyroscope", "123456", "12345678", "letmein", "secret", "test"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _issue(level: str, key: str, msg: str) -> dict:
    return {"level": level, "key": key, "message": msg}


def notification_issues(env=None) -> list[dict]:
    e = env if env is not None else os.environ
    out = []
    prov = (e.get("PYROSCOPE_NOTIFY_PROVIDER") or "simulated").strip().lower()
    if prov not in ("simulated", "smtp", "webhook"):
        out.append(_issue("error", "PYROSCOPE_NOTIFY_PROVIDER", f"unknown provider '{prov}' (simulated | smtp | webhook)"))
        return out
    if prov == "smtp":
        if not e.get("SMTP_HOST"):
            out.append(_issue("error", "SMTP_HOST", "required for the smtp provider"))
        port = e.get("SMTP_PORT", "587")
        if not port.isdigit() or not (0 < int(port) < 65536):
            out.append(_issue("error", "SMTP_PORT", "must be a TCP port number"))
        mode = (e.get("SMTP_TLS_MODE") or ("starttls" if e.get("SMTP_STARTTLS", "1") == "1" else "none")).lower()
        if mode not in ("starttls", "ssl", "none"):
            out.append(_issue("error", "SMTP_TLS_MODE", "must be starttls, ssl or none"))
        elif mode == "none" and (e.get("SMTP_HOST") or "") not in ("localhost", "127.0.0.1", "::1"):
            out.append(_issue("error", "SMTP_TLS_MODE", "'none' (no TLS) is only allowed for a local relay on localhost"))
        if not EMAIL_RE.match(e.get("SMTP_FROM") or ""):
            out.append(_issue("error", "SMTP_FROM", "must be a valid sender address verified with the provider"))
        if e.get("SMTP_USER") and not e.get("SMTP_PASSWORD"):
            out.append(_issue("warning", "SMTP_PASSWORD", "SMTP_USER is set without SMTP_PASSWORD"))
    if prov == "webhook":
        hosts = [h.strip().lower() for h in (e.get("PYROSCOPE_WEBHOOK_ALLOWED_HOSTS") or "").split(",") if h.strip()]
        if not hosts:
            out.append(_issue("error", "PYROSCOPE_WEBHOOK_ALLOWED_HOSTS", "required for the webhook provider (comma-separated host names)"))
        for h in hosts:
            if not HOST_RE.match(h):
                out.append(_issue("error", "PYROSCOPE_WEBHOOK_ALLOWED_HOSTS", f"'{h}' is not a valid public host name (no schemes, paths or IPs)"))
        if not e.get("PYROSCOPE_WEBHOOK_TOKEN"):
            out.append(_issue("warning", "PYROSCOPE_WEBHOOK_TOKEN", "no bearer token: the receiving endpoint cannot authenticate PyroScope"))
        if e.get("PYROSCOPE_WEBHOOK_ALLOW_PRIVATE", "0") == "1":
            out.append(_issue("error", "PYROSCOPE_WEBHOOK_ALLOW_PRIVATE", "disables SSRF protection; never enable outside local testing"))
    if prov == "simulated":
        out.append(_issue("warning", "PYROSCOPE_NOTIFY_PROVIDER", "notifications are SIMULATED: nothing leaves the application"))
    return out


def admin_bootstrap_state() -> str:
    """configured | env_pending | not_configured -- a safe indicator, no secret involved."""
    try:
        from sqlalchemy import select
        from . import models as M
        with M.Session() as s:
            u = s.scalar(select(M.User).where(M.User.username == "admin"))
            if u is not None and u.password_hash:
                return "configured"
    except Exception:
        pass
    return "env_pending" if os.getenv("PYROSCOPE_ADMIN_PASSWORD") else "not_configured"


def validate(env=None) -> dict:
    e = env if env is not None else os.environ
    from .security import MIN_PASSWORD
    mode = (e.get("PYROSCOPE_AUTH_MODE") or "dev").strip().lower()
    prod = mode == "production"
    issues = []
    lvl = "error" if prod else "warning"
    if mode not in ("dev", "production"):
        issues.append(_issue("error", "PYROSCOPE_AUTH_MODE", "must be dev or production"))
    origins = [o.strip() for o in (e.get("PYROSCOPE_CORS_ORIGINS") or "").split(",") if o.strip()]
    if prod:
        if not origins:
            issues.append(_issue("error", "PYROSCOPE_CORS_ORIGINS", "set the exact https origin(s) of the frontend"))
        for o in origins:
            if o == "*" or "*" in o:
                issues.append(_issue("error", "PYROSCOPE_CORS_ORIGINS", "wildcard origins are not allowed in production"))
            elif urlparse(o).scheme != "https" and urlparse(o).hostname not in ("localhost", "127.0.0.1"):
                issues.append(_issue("warning", "PYROSCOPE_CORS_ORIGINS", f"{o} is not https"))
        pw = e.get("PYROSCOPE_ADMIN_PASSWORD")
        state = admin_bootstrap_state() if env is None else ("env_pending" if pw else "not_configured")
        if state == "not_configured":
            issues.append(_issue("error", "PYROSCOPE_ADMIN_PASSWORD", "no administrator can log in: set it once to bootstrap the admin account"))
        if pw and (pw.lower() in WEAK or len(pw) < MIN_PASSWORD):
            issues.append(_issue("error", "PYROSCOPE_ADMIN_PASSWORD", f"too weak or a known default (min {MIN_PASSWORD} chars, mixed case + digit)"))
        db = e.get("DATABASE_URL") or ""
        if ":memory:" in db or db.startswith("sqlite://") and db.count("/") < 3:
            issues.append(_issue("error", "DATABASE_URL", "production needs persistent storage (file-backed SQLite on a volume, or PostgreSQL)"))
        if (e.get("PYROSCOPE_RATE_LIMIT") or "on").lower() == "off":
            issues.append(_issue("error", "PYROSCOPE_RATE_LIMIT", "must be on in production"))
        if int(e.get("PYROSCOPE_PBKDF2_ITERATIONS") or 240000) < 200000:
            issues.append(_issue("error", "PYROSCOPE_PBKDF2_ITERATIONS", "must be >= 200000 in production"))
        if int(e.get("PYROSCOPE_SESSION_HOURS") or 12) > 24:
            issues.append(_issue("warning", "PYROSCOPE_SESSION_HOURS", "sessions longer than 24 h"))
    else:
        issues.append(_issue("warning", "PYROSCOPE_AUTH_MODE", "development mode: X-User demo personas are accepted (never expose this deployment)"))
    issues += notification_issues(e)
    if not (e.get("EARTHDATA_TOKEN") or _netrc_ok()):
        issues.append(_issue("warning", "EARTHDATA_TOKEN", "VIIRS 750 m granule download is NOT CONFIGURED"))
    errors = [i for i in issues if i["level"] == "error"]
    return {"mode": mode, "ok": not errors, "errors": len(errors), "warnings": len(issues) - len(errors), "issues": issues,
            "x_user_header_trusted": not prod}


def _netrc_ok() -> bool:
    try:
        from .viirs750 import _netrc_has_urs
        return _netrc_has_urs()
    except Exception:
        return False


def credentials(env=None) -> list[dict]:
    e = env if env is not None else os.environ
    def st(ok, invalid=False):
        return "INVALID" if invalid else ("CONFIGURED" if ok else "NOT_CONFIGURED")
    n_iss = notification_issues(e)
    smtp_bad = any(i["level"] == "error" and i["key"].startswith("SMTP") for i in n_iss)
    wh_bad = any(i["level"] == "error" and "WEBHOOK" in i["key"] for i in n_iss)
    pw = e.get("PYROSCOPE_ADMIN_PASSWORD")
    return [
        {"integration": "NASA Earthdata (VIIRS 750 m)", "variables": ["EARTHDATA_TOKEN", "~/.netrc urs.earthdata.nasa.gov"],
         "status": st(bool(e.get("EARTHDATA_TOKEN")) or _netrc_ok()), "needed_for": "authentic VNP14/VJ114/VJ214 granule download"},
        {"integration": "SMTP e-mail", "variables": ["SMTP_HOST", "SMTP_PORT", "SMTP_TLS_MODE", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"],
         "status": st(bool(e.get("SMTP_HOST") and e.get("SMTP_FROM")), smtp_bad and (e.get("PYROSCOPE_NOTIFY_PROVIDER") == "smtp")),
         "needed_for": "e-mail delivery of approved advisories"},
        {"integration": "Webhook", "variables": ["PYROSCOPE_WEBHOOK_ALLOWED_HOSTS", "PYROSCOPE_WEBHOOK_TOKEN"],
         "status": st(bool(e.get("PYROSCOPE_WEBHOOK_ALLOWED_HOSTS")), wh_bad and (e.get("PYROSCOPE_NOTIFY_PROVIDER") == "webhook")),
         "needed_for": "delivery to an authority's own gateway"},
        {"integration": "Administrator bootstrap", "variables": ["PYROSCOPE_ADMIN_PASSWORD"],
         "status": (admin_bootstrap_state().upper() if env is None else st(bool(pw))), "needed_for": "first administrator login"},
        {"integration": "NASA FIRMS API (optional)", "variables": ["FIRMS_MAP_KEY"], "status": st(bool(e.get("FIRMS_MAP_KEY"))),
         "needed_for": "scripted FIRMS refresh (archives can also be added manually)"},
        {"integration": "Verified authority contacts", "variables": ["(admin UI / POST /api/authorities)"],
         "status": "CONFIGURED" if _verified_contacts() else "NOT_CONFIGURED", "needed_for": "any external advisory delivery"},
    ]


def _verified_contacts() -> int:
    try:
        from sqlalchemy import func, select
        from . import models as M
        with M.Session() as s:
            return int(s.scalar(select(func.count()).select_from(M.AuthorityContact).where(M.AuthorityContact.verified.is_(True),
                                                                                           M.AuthorityContact.is_template.is_(False))) or 0)
    except Exception:
        return 0


def notification_checklist() -> list[dict]:
    from . import notify
    st = notify.status()
    v = notification_issues()
    return [
        {"step": "Choose a provider (PYROSCOPE_NOTIFY_PROVIDER = smtp or webhook)", "done": st["provider"] != "simulated"},
        {"step": "Provider settings valid (no configuration errors)", "done": not any(i["level"] == "error" for i in v) and st["provider"] != "simulated"},
        {"step": "Connection check passes (GET /api/notifications/check)", "done": None},
        {"step": "At least one administrator-verified authority contact", "done": _verified_contacts() > 0},
        {"step": "Send one labelled TEST message (POST /api/notifications/test/{contact_id})", "done": None},
        {"step": "Remember: delivery only after an officer approves an alert; no public warnings", "done": True},
    ]


def explain_failure(err: str | None) -> str | None:
    """Human-readable cause for a provider error string (already secret-free)."""
    if not err:
        return None
    m = err.lower()
    for k, v in (("authentication", "The server rejected the SMTP login (check SMTP_USER / SMTP_PASSWORD)."),
                 ("connectionrefused", "Nothing is listening at SMTP_HOST:SMTP_PORT."),
                 ("timed out", "The provider did not answer in time (network or firewall)."),
                 ("certificate", "TLS certificate validation failed (wrong host name or untrusted certificate)."),
                 ("allow-list", "The webhook host is not in PYROSCOPE_WEBHOOK_ALLOWED_HOSTS."),
                 ("private", "The webhook resolves to a private/internal address (SSRF protection)."),
                 ("recipient", "The recipient address was refused by the server."),
                 ("http 4", "The webhook endpoint rejected the request (check PYROSCOPE_WEBHOOK_TOKEN)."),
                 ("http 5", "The webhook endpoint failed (server-side error).")):
        if k in m:
            return v
    return "Provider error; see the delivery log entry."


if __name__ == "__main__":
    import json
    import sys
    r = validate()
    print(json.dumps(r, indent=1))
    sys.exit(0 if r["ok"] else 1)
