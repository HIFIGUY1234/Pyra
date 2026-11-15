# Durable background jobs

Modules: `backend/app/jobs.py` (queue), `backend/app/worker.py` (persistent worker) · API: `/api/jobs*` · UI: **Background Jobs**

## Queue (database table `data_jobs`)

Fields: id, kind, params, status, stage, progress, attempts / max_attempts, next_run_at, lease_expires_at,
heartbeat_at, worker_id, error, error_code, result, idempotency_key, requested_by, cancel_requested, created/started/finished.

Statuses: QUEUED → RUNNING → SUCCEEDED | FAILED | CANCELLED, with RETRYING between attempts (legacy DONE rows read as SUCCEEDED).

* **Atomic claim**: compare-and-set `UPDATE … WHERE id = ? AND <still runnable>`; identical on SQLite and PostgreSQL.
  Tested: 6 threads (SQLite) and 8 processes' threads (PostgreSQL) → exactly one owner.
* **Lease + heartbeat**: lease 300 s (`PYROSCOPE_JOB_LEASE_S`), renewed by a heartbeat thread and by every `progress()`.
  A RUNNING job whose lease expired (worker crashed) is reclaimed by the next worker (attempt count increases).
* **Retry / backoff**: transient failures → RETRYING, next run after 30 s × 2^(attempt−1) (max 1 h), up to 3 attempts.
  Permanent failures (missing credentials, bad parameters, missing data) fail immediately with an `error_code` such as
  `BLOCKED_BY_CREDENTIALS`.
* **Idempotency**: an `idempotency_key` returns the existing non-failed job.
* **One active job per kind**; **cancellation**: queued/retrying jobs cancel immediately, running jobs at the next
  progress checkpoint.
* Errors are redacted (tokens/passwords never stored).

## Kinds

viirs750_fetch, linear_gis, population_refresh, sensor_models, tle_refresh, fire_events, burned_area, emissions,
smoke_trajectories, harmonization.

## Running

* Development: the API starts an embedded worker thread (`PYROSCOPE_EMBEDDED_WORKER=1`, default).
* Production: `PYROSCOPE_EMBEDDED_WORKER=0` on the API; run `python -m app.worker` (same image) — `docker compose` has a
  `worker` service. Several workers may run; they coordinate only through the database.
* `python -m app.worker --once` drains the queue and exits (cron-style).
