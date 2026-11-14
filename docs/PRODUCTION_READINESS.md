# Production readiness

## Enforced at start-up (`app/system_config.py`)

In `PYROSCOPE_AUTH_MODE=production` the API refuses to start while any of these is true:

| Check | Error when |
|---|---|
| CORS | no origin set, or any wildcard origin |
| Admin bootstrap | no admin password in the database and `PYROSCOPE_ADMIN_PASSWORD` unset |
| Admin password strength | shorter than 10, missing mixed case / digit, or a common default |
| Storage | in-memory / non-persistent `DATABASE_URL` |
| Rate limiting | `PYROSCOPE_RATE_LIMIT=off` |
| Password hashing | `PYROSCOPE_PBKDF2_ITERATIONS` < 200,000 |
| Notifications | invalid provider settings (bad port, TLS off for a remote host, invalid sender, bad webhook host, SSRF guard disabled) |

Warnings (non-blocking): non-https CORS origin, sessions > 24 h, notifications simulated, Earthdata not configured.
`python -m app.system_config` prints the result and exits non-zero on errors (used in CI with test-only values).

## Authentication and authorisation (unchanged, verified)

PBKDF2-SHA256 passwords; sessions are random tokens stored only as SHA-256, expiring, revoked on logout and on
password change; 5 failed logins → 15-minute lock; role checks on every write route; organisation isolation;
audit log for logins, alert actions, configuration changes, weight changes, operational-reference choices,
jobs and notifications. In production the `X-User` demo header is ignored everywhere.

## Secrets

Read from the environment only. Never returned by any endpoint (`/api/system/credentials`,
`/api/viirs750/credentials` return status / method only), never logged (provider errors are redacted), never
baked into Docker images (CI checks image environments).

## Health and observability

`GET /api/health`: database, data present, forecast present, free disk, `admin_bootstrap`, `auth_mode`.
Pipeline steps record start / ok / skipped / failed with durations in `data/processed/pipeline_state.json`.
Background jobs (`/api/jobs`) expose status, progress, secret-free errors and cooperative cancellation.

## Before going live — checklist

- [ ] `.env` filled from `docs/MANUAL_SETUP_AFTER_CODE_COMPLETION.md` §1–2; `python -m app.system_config` exits 0
- [ ] TLS terminated in front of nginx; `PYROSCOPE_TRUST_PROXY=1`
- [ ] Backups of `data/pyroscope.db` (migrations also back it up automatically before schema changes)
- [ ] At least one verified authority contact before enabling a real notification provider
- [ ] Notification provider connection check passes; one TEST message received
- [ ] Operational reference shows `APPROVED` (or the reason it is unavailable is accepted)
- [ ] `docker compose up -d --build` healthy; `/api/health` ok
