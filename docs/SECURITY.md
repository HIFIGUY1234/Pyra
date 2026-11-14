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

* Nothing is sent when an alert is generated or acknowledged. Delivery happens only after an officer approves, and only to administrator-verified contacts. A recipient already marked SENT for an alert is skipped (`SKIPPED_ALREADY_SENT`), so re-approval cannot double-send.
* **Webhooks:** `https` only; host must be in `PYROSCOPE_WEBHOOK_ALLOWED_HOSTS`; every resolved IP must be public (private, loopback, link-local, reserved and multicast addresses are refused, which blocks SSRF via DNS); redirects are never followed.
* **SMTP:** `SMTP_TLS_MODE` = `starttls` (default) | `ssl` | `none` (local relay only). Credentials come from the environment and are never returned by the API.
* **Retries:** only transient failures (timeouts, connection errors, HTTP 5xx/429, SMTP 4xx) are retried, up to `PYROSCOPE_NOTIFY_MAX_ATTEMPTS` (default 3) with exponential backoff. Permanent errors fail at once.
* `GET /api/notifications/check` tests the provider connection without sending; `POST /api/notifications/test/{contact_id}` (admin) sends one labelled test message to a verified contact and logs it.
* Every attempt, including failures, is written to the delivery log. PyroScope never issues public warnings or dispatches services. SMS is not implemented.

## Rate limiting

* In-process sliding window per client and bucket (`security.RATE_LIMITS`): login 10 / 60 s, upload 5 / 600 s, processing 6 / 600 s, report generation 20 / 600 s, admin 30 / 600 s. Exceeding a limit returns 429 with `Retry-After`.
* The client is the socket address unless `PYROSCOPE_TRUST_PROXY=1` (set in compose behind nginx), when the first `X-Forwarded-For` hop is used. Never set it when the API is directly exposed.
* nginx adds `limit_req` zones: login 10 r/min, heavy endpoints 6 r/min.
* `PYROSCOPE_RATE_LIMIT=off` disables the in-process limiter (tests only). The limiter is per process; with several workers, rely on the nginx limits.

## Audit retention

* `POST /api/admin/audit-retention` (admin, dry run by default) and `retention.prune_audit`. Minimum retention 30 days.
* Only routine events (`LOGIN`, `LOGIN_FAILED`, `LOGOUT`, `REPORT_GENERATED`, `TLE_REFRESH`) can be pruned. Alert decisions, approvals, deliveries and user/role changes are never deleted.
* Rows are first archived to `data/backups/audit/*.jsonl.gz` (git-ignored), the archive is read back and verified, and only then are rows deleted.

## Secrets

* `.env` is git-ignored and `.env.example` contains no values. CI workflows contain no keys; use repository secrets when needed.
* Earthdata access for VIIRS 750 m uses `EARTHDATA_TOKEN` or `~/.netrc`; neither is read into logs or API responses (`/api/viirs750/status` reports only whether credentials are configured).
* Docker images contain no credentials. Configuration is supplied at run time.

## Dependency checks (2026-11-15)

* `pip-audit -r backend/requirements.txt` on Python 3.11.9 (with sgp4, rasterio, h5py added): **no known vulnerabilities**. Pillow 13.0.0 installs on 3.11. Python 3.10 still cannot install Pillow 13, so production runs 3.11 (`.python-version`, Dockerfile, CI).
* `npm audit --omit=dev --audit-level=high`: passes.
* Both checks run in CI (`.github/workflows/ci.yml`).

## Known gaps

* No CSRF token is needed, because auth uses a Bearer header and not cookies. Keep it that way, or add CSRF protection if cookies are ever introduced.
* CORS is restricted by `PYROSCOPE_CORS_ORIGINS`. Set the exact production origin.
* The in-process rate limiter does not share state across workers or hosts.
* Audit retention is manual (endpoint / function); no scheduler runs it.
