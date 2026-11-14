# PyroScope — security notes

This file reflects the code as it stands (`backend/app/security.py`, `main.py`, `notify.py`, `migrate.py`).
Where something is missing, the gap is stated.

## Authentication and sessions

| Control | Implementation |
|---|---|
| Password hashing | PBKDF2-HMAC-SHA256, random salt, 240,000 iterations by default (`PYROSCOPE_PBKDF2_ITERATIONS`). Unknown users still pay a dummy hash, so response time does not reveal which accounts exist. |
| Session tokens | `secrets.token_urlsafe(32)`. Only the SHA-256 digest is stored. Tokens expire (`PYROSCOPE_SESSION_HOURS`, default 12) and are revoked on logout. |
| Login failures | 5 consecutive failures lock the account for 15 minutes. |
| Modes | `dev`: demo personas via the `X-User` header, labelled "DEV PERSONA" in the UI. `production`: the header is ignored and every `/api` route except health, meta and login needs a Bearer session (`test_production_mode_ignores_identity_header`). |
| Roles | admin, gov_officer, org user, analyst. User creation and LFS recovery are admin-only. |
| Organisation isolation | Organisation users see only their own locations and alerts (`test_org_users_cannot_see_other_organisations`). |
| Frontend | The token is kept in `sessionStorage` (cleared when the browser session ends) and dropped on any 401 (tested in `frontend/tests/api.test.ts`). |

## Input and file handling

* **Uploads:** `.csv` only. The file name is sanitised to `[A-Za-z0-9_.-]` and only the base name is kept, so path traversal is not possible. Uploads stream to disk with a 1.5 GB cap. A 2,000-row sample must pass `ingest.standardise` or the file is deleted.
* **ZIP archives:** members are streamed and read in memory (`ZipFile.open`), never extracted to disk, so there is no zip-slip path. Integrity is checked with the CRC test and, for repository archives, SHA-256. A Git LFS pointer is never parsed as a ZIP.
* **SQL:** SQLAlchemy ORM / bound parameters throughout. No string-built SQL from user input.
* **Validation:** FastAPI/Pydantic types and query patterns (e.g. `stage` must match `^(mg|sh)$`). Region ids are parsed and rejected when unknown.
* **Errors:** unexpected exceptions return a generic 500. The health check reports only the exception class name, never connection strings.

## Outbound notifications

* Nothing is sent when an alert is generated or acknowledged. Delivery happens only after an officer approves, and only to administrator-verified contacts.
* Webhooks must be `https` and their host must be in `PYROSCOPE_WEBHOOK_ALLOWED_HOSTS`. SMTP credentials come from the environment and are never returned by the API.
* Every attempt, including failures, is written to the delivery log. PyroScope never issues public warnings or dispatches services.

## Secrets

* `.env` is git-ignored and `.env.example` contains no values. CI workflows contain no keys; use repository secrets when needed.
* Docker images contain no credentials. Configuration is supplied at run time.

## Dependency checks (2026-11-14)

* `pip-audit -r backend/requirements.txt`: only Pillow 12.x is affected (CVE batch fixed in 13.0.0). The requirement now asks for Pillow ≥ 13 on Python ≥ 3.11. **Python 3.10 cannot install the fix, so run production on 3.11+.**
* `npm audit --omit=dev`: 2 moderate, 0 high or critical.
* Both checks run in CI (`.github/workflows/ci.yml`).

## Known gaps

* There is no general request rate limiting. Brute force is limited only by per-account lockout. Add rate limiting at the reverse proxy (e.g. nginx `limit_req` on `/api/auth/login`).
* No CSRF token is needed, because auth uses a Bearer header and not cookies. Keep it that way, or add CSRF protection if cookies are ever introduced.
* CORS is restricted by `PYROSCOPE_CORS_ORIGINS`. Set the exact production origin.
* Audit logs are kept in the database indefinitely. No retention policy is configured.
