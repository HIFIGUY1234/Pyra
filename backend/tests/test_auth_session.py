"""Session lifecycle cases the frontend AuthProvider relies on: expiry, disabled accounts, password change,
organisation identity in /api/auth/me and the 401-vs-403 distinction. Runs on the conftest throw-away DB."""
from datetime import timedelta

import tests.test_api  # noqa: F401  (sets DATABASE_URL to a throw-away copy before the app is imported)
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as M
from app.main import app

c = TestClient(app)
ADMIN = {"X-User": "admin"}


def _user(username: str, role: str = "analyst", password: str = "Sess10n-Passw0rd", **extra) -> str:
    r = c.post("/api/users", json={"username": username, "display_name": username.title(), "role": role, "password": password, **extra}, headers=ADMIN)
    assert r.status_code in (200, 409), r.text
    return password


def _login(username: str, password: str) -> dict:
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in_s"] > 0 and body["user"]["username"] == username
    return {"Authorization": f"Bearer {body['token']}"}


def test_expired_session_is_rejected():
    pw = _user("sess.expiry")
    H = _login("sess.expiry", pw)
    assert c.get("/api/auth/me", headers=H).status_code == 200
    with M.Session() as s:
        uid = s.scalar(select(M.User.id).where(M.User.username == "sess.expiry"))
        for ses in s.scalars(select(M.UserSession).where(M.UserSession.user_id == uid)):
            ses.expires_at = M.now() - timedelta(minutes=1)
        s.commit()
    r = c.get("/api/auth/me", headers=H)
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_disabled_account_loses_session_and_cannot_log_in():
    pw = _user("sess.disabled")
    H = _login("sess.disabled", pw)
    with M.Session() as s:
        s.scalar(select(M.User).where(M.User.username == "sess.disabled")).is_active = False
        s.commit()
    assert c.get("/api/auth/me", headers=H).status_code == 401
    r = c.post("/api/auth/login", json={"username": "sess.disabled", "password": pw})
    assert r.status_code == 401 and r.json()["detail"] == "invalid username or password"   # no account enumeration


def test_password_change_revokes_every_session():
    pw = _user("sess.pwchange")
    H1, H2 = _login("sess.pwchange", pw), _login("sess.pwchange", pw)
    r = c.put("/api/auth/password", json={"current_password": pw, "new_password": "N3w-Passw0rd-xyz"}, headers=H1)
    assert r.status_code == 200 and r.json()["sessions_revoked"] is True
    assert c.get("/api/auth/me", headers=H1).status_code == 401
    assert c.get("/api/auth/me", headers=H2).status_code == 401
    assert c.post("/api/auth/login", json={"username": "sess.pwchange", "password": pw}).status_code == 401
    _login("sess.pwchange", "N3w-Passw0rd-xyz")


def test_me_reports_organisation_name_and_auth_kind():
    with M.Session() as s:
        org = M.Organisation(name="Session Test Mills", sector="Agri-processing")
        s.add(org)
        s.commit()
        oid = org.id
    pw = _user("sess.orguser", role="org_user", organisation_id=oid)
    me = c.get("/api/auth/me", headers=_login("sess.orguser", pw)).json()
    assert me["role"] == "org_user" and me["organisation_id"] == oid and me["organisation_name"] == "Session Test Mills"
    assert me["auth"] == "token" and me["warning"] is None
    persona = c.get("/api/auth/me", headers={"X-User": "analyst"}).json()
    assert persona["auth"] == "dev-persona" and persona["organisation_name"] is None and "Development persona" in persona["warning"]


def test_authenticated_non_admin_gets_403_not_401():
    pw = _user("sess.analyst")
    H = _login("sess.analyst", pw)
    r = c.get("/api/system/config", headers=H)
    assert r.status_code == 403
    assert c.get("/api/auth/me", headers=H).status_code == 200      # a 403 never ends the session


def test_production_logout_revokes_and_rejects_persona(monkeypatch):
    pw = _user("sess.prod")
    monkeypatch.setenv("PYROSCOPE_AUTH_MODE", "production")
    H = _login("sess.prod", pw)
    assert c.get("/api/auth/me", headers=H).json()["auth_mode"] == "production"
    assert c.get("/api/auth/me", headers={"X-User": "sess.prod"}).status_code == 401
    assert c.post("/api/auth/logout", headers=H).status_code == 200
    assert c.get("/api/auth/me", headers=H).status_code == 401
    _login("sess.prod", pw)                                           # re-login works after logout


def test_bootstrapped_admin_drops_demo_persona_label(monkeypatch):
    from app import db_sync
    with M.Session() as s:
        adm = s.scalar(select(M.User).where(M.User.username == "admin"))
        saved = (adm.password_hash, adm.display_name, adm.is_demo)
        adm.password_hash, adm.display_name = None, db_sync.DEMO_USERS[0][1]
        s.commit()
    try:
        monkeypatch.setenv("PYROSCOPE_ADMIN_PASSWORD", "B00tstrap-Admin-Pw")
        db_sync.init_db()
        with M.Session() as s:
            adm = s.scalar(select(M.User).where(M.User.username == "admin"))
            assert adm.display_name == "Administrator" and adm.password_hash and adm.is_demo is False
            assert s.scalar(select(M.User).where(M.User.username == "analyst")).display_name.endswith("(demo persona)")
    finally:
        with M.Session() as s:
            adm = s.scalar(select(M.User).where(M.User.username == "admin"))
            adm.password_hash, adm.display_name, adm.is_demo = saved
            s.commit()
