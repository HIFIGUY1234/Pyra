# Supabase setup (PostgreSQL + Storage)

Status: **IMPLEMENTED; TESTED ON REAL POSTGRESQL 16 (local + CI); NOT CONNECTED TO A SUPABASE PROJECT** (no credentials).

## 1. Database

1. Create a Supabase project (region near India, e.g. `ap-south-1`).
2. Apply the migrations (either):
   * Supabase CLI: `supabase link --project-ref <ref>` then `supabase db push` (uses `supabase/migrations/`), or
   * SQL editor: run `20261115000000_pyroscope_schema.sql`, then `20261115000100_pyroscope_storage_buckets.sql`.
3. Backend connection string (server-side only):
   * API / worker on a persistent host: session pooler or direct
     `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require`
   * many short-lived processes: transaction pooler port **6543** (PyroScope switches to NullPool and disables prepared
     statements automatically).
4. Copy the existing SQLite records (source is opened read-only and never changed):
   `cd backend && python -m app.pg_migrate copy --target "$DATABASE_URL"` → per-table reconciliation, exit 1 on mismatch.
5. Start the API once (`init_db` adds any newer columns additively); start the worker.

## 2. Storage

Buckets (private): raw-satellite-archives, viirs750-granules, geostationary-data, processed-parquet, burned-area-data,
emissions-data, smoke-outputs, geo-data, population-data, model-artifacts, scientific-reports, user-uploads.

Backend env: `PYROSCOPE_STORAGE=supabase`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (never in the frontend).
Uploads ≥6 MiB use the TUS resumable endpoint (6 MiB chunks, resume from server offset); SHA-256 and size are recorded in
`storage_objects`; browsers get signed URLs (`POST /api/storage/sign`, 60 s – 7 days).

File-size limits: Free plan 50 MB per file; Pro/Team: configurable global limit (up to 500 GB). The FIRMS archives
(12–153 MB) need a paid plan or stay in Git LFS.

## 3. Row Level Security

All public tables: RLS enabled, no policies, privileges revoked from `anon` and `authenticated`. Test (run in CI): as
`anon`, `SELECT * FROM users` → permission denied. FastAPI remains the authority for users, roles and organisation
isolation; do not add browser-side Supabase table access without designing policies first.
