# Deployment architecture: Vercel + Supabase + persistent Python

```
 browser ──HTTPS──▶ Vercel (static React/Vite build, SPA rewrites, asset caching)
    │
    └──HTTPS (VITE_API_BASE_URL, Bearer session)──▶ FastAPI service (container: Render / Railway / Fly.io / DO / any Docker host)
                                                   │            ▲
                                                   │ SQL        │ jobs claimed by lease (data_jobs)
                                                   ▼            │
                                          Supabase PostgreSQL ◀─┴── worker service (`python -m app.worker`, same image)
                                                   │
                         Supabase Storage (private buckets; signed URLs only) ◀── API + worker (service role, server-side)
```

* **Vercel = frontend only.** No secret is ever in the bundle (`VITE_API_BASE_URL` is the only variable).
* **FastAPI stays the single authentication layer** (PBKDF2 passwords, hashed bearer sessions, roles, organisation
  isolation). Supabase Auth is not used, so there are no two unsynchronised auth systems.
* **PostgreSQL**: every table has Row Level Security enabled and no policies; `anon`/`authenticated` have no table
  privileges. The browser cannot read tables even with the public anon key. The backend connects as a server role.
* **Storage**: 12 private buckets; large archives, granules, rasters, Parquet, models and reports live there — never in
  PostgreSQL `bytea`.
* **Worker**: heavy work (ingestion, 750 m downloads, burned area, events, emissions, smoke, GIS, population, harmonization,
  forecast training, reports) runs outside HTTP requests in a durable queue.

Why not serverless Python on Vercel: the scientific stack (pandas, pyarrow, rasterio/GDAL, h5py, pyhdf, osmium, xgboost,
scipy) exceeds Vercel's Python function bundle limit (250 MB unzipped) and jobs run for minutes to hours (function
duration limits). A thin read-only API adapter on Vercel was evaluated and rejected: it would duplicate auth and
connection handling for no gain.

Connection modes (`backend/app/models.py:make_engine`): SQLite (local), PostgreSQL / Supabase direct or session pooler
(bounded QueuePool, pre-ping, recycle), Supabase transaction pooler port 6543 (NullPool, psycopg `prepare_threshold=None`).
