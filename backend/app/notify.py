"""Notification delivery with optional, authorised external providers.

Default provider is `simulated`: the advisory appears in the recipient authority's in-app
queue and the delivery log says SIMULATED. External delivery happens only when ALL hold:

  1. PYROSCOPE_NOTIFY_PROVIDER is set to a configured provider (webhook | smtp);
  2. the recipient is an administrator-verified authority contact (never a role template);
  3. the contact's channel matches the provider and its address passes validation;
  4. a human with authority approved the alert (action `approve`) -- predictions never
     auto-send, and detections are delivered only after approval too;
  5. the alert is an authority advisory. This module cannot issue public emergency warnings.

Every attempt, including blocked and failed ones, is written to `notification_deliveries`.
Transient failures (network, timeouts, 5xx/429, SMTP disconnects) are retried with exponential back-off;
configuration, validation and authentication failures are not. A recipient that already received an alert is
not sent it again. Webhooks: https only, host allow-list, every resolved address must be public (SSRF guard),
redirects are not followed. Secrets come from environment variables only and are never logged or returned.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import smtplib
import socket
import time
from email.message import EmailMessage
from urllib.parse import urlparse

from sqlalchemy import select

from . import models as M

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ATTEMPTS = int(os.getenv("PYROSCOPE_NOTIFY_MAX_ATTEMPTS", "3"))
RETRY_BASE_S = float(os.getenv("PYROSCOPE_NOTIFY_RETRY_BASE_S", "2"))
TIMEOUT_S = float(os.getenv("PYROSCOPE_NOTIFY_TIMEOUT_S", "15"))


class TransientError(Exception):
    """Network / server-side failure worth retrying."""


def provider_name() -> str:
    p = os.getenv("PYROSCOPE_NOTIFY_PROVIDER", "simulated").strip().lower()
    return p if p in ("simulated", "webhook", "smtp") else "simulated"


def status() -> dict:
    p = provider_name()
    cfg = {"simulated": True,
           "webhook": bool(os.getenv("PYROSCOPE_WEBHOOK_ALLOWED_HOSTS")),
           "smtp": all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_FROM"))}
    return {"provider": p, "configured": cfg[p], "external_delivery_enabled": p != "simulated" and cfg[p],
            "max_attempts": MAX_ATTEMPTS, "timeout_s": TIMEOUT_S,
            "sms": "not implemented: no approved SMS provider; use a verified webhook to an authority's own SMS gateway",
            "rules": ["External delivery only to administrator-verified authority contacts.",
                      "Only after an authorised officer approves the alert; model predictions never auto-send.",
                      "No public emergency warnings and no automatic dispatch of emergency services.",
                      "All attempts (including blocked and failed) are logged."]}


def _payload(alert: M.Alert) -> dict:
    p = alert.payload or {}
    return {"alert_id": alert.alert_id, "alert_type": alert.alert_type, "classification": alert.classification, "status": alert.status,
            "risk_category": alert.risk_category, "probability": alert.probability, "region": alert.region_name, "state": alert.state,
            "land_use": alert.land_use, "issue_date": str(alert.issue_date) if alert.issue_date else None,
            "recommended_action": p.get("recommended_action"), "meaning": p.get("probability_meaning"),
            "disclaimer": "Decision-support advisory for the responsible authority. Not a public emergency warning. "
                          "Satellite hotspots are unverified until confirmed in the field."}


# --------------------------------------------------------------------------- providers
def _check_public_host(host: str):
    """SSRF guard: every address the host resolves to must be public, unless explicitly allowed (lab testing)."""
    if os.getenv("PYROSCOPE_WEBHOOK_ALLOW_PRIVATE", "0") == "1":
        return
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise TransientError(f"DNS lookup failed for {host}: {exc}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise PermissionError(f"webhook host {host} resolves to non-public address {ip}")


def _send_webhook(url: str, body: dict):
    import requests
    allowed = {h.strip().lower() for h in os.getenv("PYROSCOPE_WEBHOOK_ALLOWED_HOSTS", "").split(",") if h.strip()}
    u = urlparse(url)
    if u.scheme != "https" or (u.hostname or "").lower() not in allowed:
        raise PermissionError(f"webhook host not in PYROSCOPE_WEBHOOK_ALLOWED_HOSTS or not https: {u.hostname}")
    _check_public_host(u.hostname)
    headers = {"Content-Type": "application/json"}
    if os.getenv("PYROSCOPE_WEBHOOK_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['PYROSCOPE_WEBHOOK_TOKEN']}"
    try:
        # no redirects: a redirect could point outside the allow-list
        r = requests.post(url, data=json.dumps(body, default=str), headers=headers, timeout=TIMEOUT_S, allow_redirects=False)
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise TransientError(f"{type(exc).__name__}: {exc}")
    if r.status_code >= 500 or r.status_code == 429:
        raise TransientError(f"HTTP {r.status_code}")
    if 300 <= r.status_code < 400:
        raise PermissionError(f"webhook answered with a redirect (HTTP {r.status_code}); redirects are not followed")
    r.raise_for_status()


def _smtp_connect():
    host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))
    mode = os.getenv("SMTP_TLS_MODE", "starttls" if os.getenv("SMTP_STARTTLS", "1") == "1" else "none").lower()
    try:
        sm = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT_S) if mode == "ssl" else smtplib.SMTP(host, port, timeout=TIMEOUT_S)
        if mode == "starttls":
            sm.starttls()
        if os.getenv("SMTP_USER"):
            sm.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        return sm
    except smtplib.SMTPAuthenticationError as exc:
        raise PermissionError(f"SMTP authentication failed ({exc.smtp_code})")
    except (OSError, smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError) as exc:
        raise TransientError(f"{type(exc).__name__}: {exc}")


def _send_smtp(addr: str, body: dict):
    if not EMAIL_RE.match(addr or ""):
        raise ValueError("invalid email address on verified contact")
    msg = EmailMessage()
    msg["Subject"] = f"[PyroScope {body.get('risk_category') or ''}] {body.get('classification')} {body.get('alert_id')} - {body.get('region')}"
    msg["From"], msg["To"] = os.environ["SMTP_FROM"], addr
    msg.set_content(json.dumps(body, indent=2, default=str))
    sm = _smtp_connect()
    try:
        sm.send_message(msg)
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPDataError, OSError) as exc:
        raise TransientError(f"{type(exc).__name__}: {exc}")
    finally:
        try:
            sm.quit()
        except Exception:
            pass


SENDERS = {"webhook": _send_webhook, "smtp": _send_smtp}
CHANNEL_FOR = {"webhook": {"webhook"}, "smtp": {"email"}}


def check_connection() -> dict:
    """Validate the configured provider without sending anything (SMTP: connect, TLS, login, NOOP)."""
    p = provider_name()
    if p == "smtp":
        if not status()["configured"]:
            return {"provider": p, "ok": False, "error": "SMTP_HOST and SMTP_FROM must be set"}
        try:
            sm = _smtp_connect()
            code = sm.noop()[0]
            sm.quit()
            return {"provider": p, "ok": code == 250, "noop": code}
        except Exception as exc:
            return {"provider": p, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if p == "webhook":
        hosts = [h for h in os.getenv("PYROSCOPE_WEBHOOK_ALLOWED_HOSTS", "").split(",") if h.strip()]
        return {"provider": p, "ok": bool(hosts), "allowed_hosts": hosts, "note": "Webhooks are validated per delivery (https, allow-list, public address)."}
    return {"provider": p, "ok": True, "note": "Simulated provider: nothing leaves the system."}


def _send_with_retry(send, addr, body, sleep=time.sleep) -> tuple:
    err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            send(addr, body)
            return "SENT", None, attempt
        except TransientError as exc:
            err = f"TransientError: {exc}"
            if attempt < MAX_ATTEMPTS:
                sleep(RETRY_BASE_S * 2 ** (attempt - 1))
        except Exception as exc:  # permanent: configuration, validation, authentication -> no retry
            return "FAILED", f"{type(exc).__name__}: {exc}"[:500], attempt
    return "FAILED", (err or "")[:500], MAX_ATTEMPTS


def send_test(contact, requested_by: str, sender_override=None, sleep=time.sleep) -> dict:
    """Administrator test message to ONE verified contact. Clearly labelled; not an alert; the caller audits it."""
    p = provider_name()
    if contact.is_template or not contact.verified:
        return {"status": "BLOCKED_NO_VERIFIED_CONTACT", "sent": False}
    if p == "simulated" or not status()["configured"]:
        return {"status": "SIMULATED_DELIVERED", "sent": False, "note": "No external provider configured."}
    if (contact.contact_channel or "").lower() not in CHANNEL_FOR[p]:
        return {"status": "SKIPPED_CHANNEL_MISMATCH", "sent": False}
    body = {"alert_id": "TEST", "alert_type": "provider_test", "classification": "TEST MESSAGE - no action required",
            "risk_category": None, "region": contact.authority, "requested_by": requested_by,
            "disclaimer": "Connectivity test from PyroScope. Not an alert and not a public emergency warning."}
    st, err, n = _send_with_retry(sender_override or SENDERS[p], contact.contact_value, body, sleep)
    return {"status": st, "sent": st == "SENT", "error": err, "attempts": n, "provider": p}


# --------------------------------------------------------------------------- delivery
def deliver(s, alert: M.Alert, approved_by: str | None, sender_override=None, sleep=time.sleep) -> list[dict]:
    """Attempt delivery to every recipient of `alert`. Call inside an open session; the caller commits."""
    prov = provider_name()
    st = status()
    contacts = {c.id: c for c in s.scalars(select(M.AuthorityContact))}
    already = {d.recipient_pk for d in s.scalars(select(M.NotificationDelivery).where(
        M.NotificationDelivery.alert_pk == alert.id, M.NotificationDelivery.status == "SENT"))}
    out = []
    for r in alert.recipients:
        c = contacts.get(r.contact_id) if r.contact_id else None
        rec = M.NotificationDelivery(alert_pk=alert.id, recipient_pk=r.id, contact_id=r.contact_id, provider=prov,
                                     channel=c.contact_channel if c else None, simulated=True, approved_by=approved_by)
        if r.id in already:
            rec.status, rec.simulated = "SKIPPED_ALREADY_SENT", False   # duplicate prevention (e.g. approve, then escalate)
        elif c is None or c.is_template or not c.verified:
            rec.status = "BLOCKED_NO_VERIFIED_CONTACT"
        elif prov == "simulated" or not st["configured"]:
            rec.status = "SIMULATED_DELIVERED"
        elif not approved_by or alert.status not in ("APPROVED", "ESCALATED"):
            rec.status = "BLOCKED_AWAITING_HUMAN_APPROVAL"
        elif (c.contact_channel or "").lower() not in CHANNEL_FOR[prov]:
            rec.status = "SKIPPED_CHANNEL_MISMATCH"
        else:
            rec.simulated = False
            rec.status, rec.error, rec.attempts = _send_with_retry(sender_override or SENDERS[prov], c.contact_value, _payload(alert), sleep)
        if rec.status != "SKIPPED_ALREADY_SENT":
            r.delivery_status = rec.status
            r.simulated = rec.simulated
            r.channel = (c.contact_channel if c else None) if not rec.simulated else ("in-app (simulated)" if c and c.verified and not c.is_template else None)
        s.add(rec)
        out.append({"recipient": r.role_title, "authority": r.authority, "status": rec.status, "simulated": rec.simulated, "error": rec.error})
    return out


def log(alert_id: str | None = None, limit: int = 200) -> list[dict]:
    with M.Session() as s:
        q = select(M.NotificationDelivery, M.Alert.alert_id).join(M.Alert, M.Alert.id == M.NotificationDelivery.alert_pk)
        if alert_id:
            q = q.where(M.Alert.alert_id == alert_id)
        rows = s.execute(q.order_by(M.NotificationDelivery.id.desc()).limit(limit)).all()
        return [{"id": d.id, "alert_id": aid, "provider": d.provider, "channel": d.channel, "simulated": d.simulated, "status": d.status,
                 "attempts": d.attempts, "error": d.error, "approved_by": d.approved_by, "at": d.created_at.isoformat() + "Z"} for d, aid in rows]
