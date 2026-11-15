# Supabase / PostgreSQL migrations

| File | Content |
|---|---|
| `supabase/migrations/20261115000000_pyroscope_schema.sql` | 37 tables + indexes rendered from the SQLAlchemy models with the PostgreSQL dialect; RLS on every table; privileges revoked from `anon`/`authenticated` |
| `supabase/migrations/20261115000100_pyroscope_storage_buckets.sql` | 12 private Storage buckets (`ON CONFLICT DO NOTHING`) |

Generated, never hand-edited: `cd backend && python -m app.pg_migrate schema-sql`. A test and the CI `postgres` job fail
if the committed SQL differs from the models.

Tables cover users, roles, organisations, sessions, monitoring locations, authority contacts, thresholds, alerts,
escalations, recipients, notification deliveries, satellite datasets, data jobs, fire events, fire-event history,
reference incidents, storage objects, harmonized observations, calibrations, uncertainty, validation results,
anomalies, forecasts and features, critical regions, operational selections, jurisdiction layers, reports, audit logs.
Burned area, emissions and smoke outputs are files (Parquet/JSON) registered in `storage_objects`; fire-event
observation associations are Parquet (`processed-parquet` bucket) to keep the database small.

Types: `TIMESTAMP WITHOUT TIME ZONE` (UTC by convention), `JSON`, `BOOLEAN`, `SERIAL` keys — no SQLite syntax
(test asserts no `AUTOINCREMENT`/`DATETIME`).

## Verified

* Local: PostgreSQL 16 (pgserver) — schema applied, 37 tables, 0 without RLS, 12 private buckets, `anon` denied
  (InsufficientPrivilege); SQLite → PostgreSQL copy of the repository DB reconciled for every table in 57 s
  (e.g. 361,976 daily_fire_activity, 69,478 hotspot_observations, 5,151 grid cells, 11,232 harmonized observations);
  re-run copied 0 rows; app `init_db` on PostgreSQL; 8 concurrent workers → exactly 1 job claim.
* CI: the same test (`test_postgres_migrations_rls_copy_and_job_claims`) against a `postgres:16` service.

## Upgrades and rollback

App-level additive migrations (`python -m app.migrate`) still run on start (new tables/columns only). On Supabase,
take a backup (dashboard or `pg_dump`) before applying a new migration file; rollback = restore the backup.
