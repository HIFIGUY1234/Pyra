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
Secrets come from environment variables only.
"""
from __future__ import annotations

import json
import os
import re
import smtplib
from email.message import EmailMessage
from urllib.parse import urlparse

from sqlalchemy import select

from . import models as M

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ATTEMPTS = 2


def provider_name() -> str:
    p = os.getenv("PYROSCOPE_NOTIFY_PROVIDER", "simulated").strip().lower()
    return p if p in ("simulated", "webhook", "smtp") else "simulated"


def status() -> dict:
    p = provider_name()
    cfg = {"simulated": True,
           "webhook": bool(os.getenv("PYROSCOPE_WEBHOOK_ALLOWED_HOSTS")),
           "smtp": all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_FROM"))}
    return {"provider": p, "configured": cfg[p], "external_delivery_enabled": p != "simulated" and cfg[p],
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


def _send_webhook(url: str, body: dict):
    import requests
    allowed = {h.strip().lower() for h in os.getenv("PYROSCOPE_WEBHOOK_ALLOWED_HOSTS", "").split(",") if h.strip()}
    u = urlparse(url)
    if u.scheme != "https" or (u.hostname or "").lower() not in allowed:
        raise PermissionError(f"webhook host not in PYROSCOPE_WEBHOOK_ALLOWED_HOSTS or not https: {u.hostname}")
    headers = {"Content-Type": "application/json"}
    if os.getenv("PYROSCOPE_WEBHOOK_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['PYROSCOPE_WEBHOOK_TOKEN']}"
    r = requests.post(url, data=json.dumps(body), headers=headers, timeout=15)
    r.raise_for_status()


def _send_smtp(addr: str, body: dict):
    if not EMAIL_RE.match(addr or ""):
        raise ValueError("invalid email address on verified contact")
    msg = EmailMessage()
    msg["Subject"] = f"[PyroScope {body['risk_category'] or ''}] {body['classification']} {body['alert_id']} - {body['region']}"
    msg["From"], msg["To"] = os.environ["SMTP_FROM"], addr
    msg.set_content(json.dumps(body, indent=2, default=str))
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=20) as sm:
        if os.getenv("SMTP_STARTTLS", "1") == "1":
            sm.starttls()
        if os.getenv("SMTP_USER"):
            sm.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        sm.send_message(msg)


SENDERS = {"webhook": _send_webhook, "smtp": _send_smtp}
CHANNEL_FOR = {"webhook": {"webhook"}, "smtp": {"email"}}


def deliver(s, alert: M.Alert, approved_by: str | None, sender_override=None) -> list[dict]:
    """Attempt delivery to every recipient of `alert`. Call inside an open session; the caller commits."""
    prov = provider_name()
    st = status()
    contacts = {c.id: c for c in s.scalars(select(M.AuthorityContact))}
    out = []
    for r in alert.recipients:
        c = contacts.get(r.contact_id) if r.contact_id else None
        rec = M.NotificationDelivery(alert_pk=alert.id, recipient_pk=r.id, contact_id=r.contact_id, provider=prov,
                                     channel=c.contact_channel if c else None, simulated=True, approved_by=approved_by)
        if c is None or c.is_template or not c.verified:
            rec.status = "BLOCKED_NO_VERIFIED_CONTACT"
        elif prov == "simulated" or not st["configured"]:
            rec.status = "SIMULATED_DELIVERED"
        elif not approved_by or alert.status not in ("APPROVED", "ESCALATED"):
            rec.status = "BLOCKED_AWAITING_HUMAN_APPROVAL"
        elif (c.contact_channel or "").lower() not in CHANNEL_FOR[prov]:
            rec.status = "SKIPPED_CHANNEL_MISMATCH"
        else:
            rec.simulated = False
            send = sender_override or SENDERS[prov]
            for attempt in range(1, MAX_ATTEMPTS + 1):
                rec.attempts = attempt
                try:
                    send(c.contact_value, _payload(alert))
                    rec.status, rec.error = "SENT", None
                    break
                except Exception as exc:  # recorded, never raised to the officer's UI as a crash
                    rec.status, rec.error = "FAILED", f"{type(exc).__name__}: {exc}"[:500]
                    if isinstance(exc, (PermissionError, ValueError)):
                        break
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
