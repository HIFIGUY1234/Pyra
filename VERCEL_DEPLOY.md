# PyroScope – Vercel Deployment Guide

## Architecture

Two services, one domain:

| Service | Root | Framework | Public? |
|---------|------|-----------|---------|
| `frontend` | `frontend/` | Vite (React) | Yes — catches `/*` |
| `backend` | `backend/` | FastAPI | Via `/api/(.*)` rewrite only |

No service-to-service bindings needed. Browser sends `/api/...` → Vercel edge rewrites → backend service. Frontend build is static; `VITE_API_BASE_URL` must be **left empty** (same-origin routing).

---

## Required Environment Variables

Set these in the Vercel project dashboard under each service's **Environment Variables** tab.

### Backend service

```env
# External database (SQLite won't persist on Vercel ephemeral FS)
DATABASE_URL=postgresql://user:pass@host/dbname

# CORS — same domain works without CORS, but preview deployments need this
PYROSCOPE_CORS_ORIGINS=https://your-project.vercel.app
PYROSCOPE_CORS_ORIGIN_REGEX=^https://your-project-[a-z0-9-]+\.vercel\.app$

# Disable embedded background worker (serverless = no long-lived threads)
PYROSCOPE_EMBEDDED_WORKER=0

# Notifications — keep simulated unless real SMTP configured
PYROSCOPE_NOTIFY_PROVIDER=simulated

# Optional: NASA FIRMS live data
FIRMS_MAP_KEY=your_nasa_firms_key

# Optional: GitHub LFS base for pre-processed Parquet files
PYRA_LFS_MEDIA_BASE=https://media.githubusercontent.com/media/HIFIGUY1234/Pyra/main
```

### Frontend service

```env
# Leave EMPTY for same-origin /api routing via Vercel rewrites
VITE_API_BASE_URL=
```

---

## Database Setup

Vercel's ephemeral filesystem means SQLite (`data/pyroscope.db`) resets on every cold start.

**Options (pick one):**

1. **Vercel Postgres** — add the add-on from the Vercel dashboard, copy the `DATABASE_URL` it provides.
2. **Neon** — free tier at [neon.tech](https://neon.tech), provision a DB, copy the connection string.
3. **Supabase** — free tier at [supabase.com](https://supabase.com), use the Postgres connection string.

After first deploy, run migrations:

```bash
# From the backend directory, with DATABASE_URL set
python -m app.pipeline --init-db
```

Or use the existing SQLite dump:

```bash
pg_restore -d $DATABASE_URL data/pyroscope.db  # if dump exists
```

---

## Parquet / Processed Data

Pre-processed Parquet files in `data/processed/` are **not** served from Vercel's filesystem in production. The backend `has_data()` check returns `False` gracefully — API returns empty arrays instead of crashing.

To serve real data: set `PYRA_LFS_MEDIA_BASE` to the GitHub LFS raw media URL. The `acquire.py` module will fetch Parquet files from there at runtime.

---

## Deploy Steps

1. Push this repo to GitHub (already done).
2. Go to [vercel.com/new](https://vercel.com/new) → **Import Git Repository** → select `HIFIGUY1234/Pyra`.
3. Vercel auto-detects `vercel.json` and shows two services.
4. Set environment variables for each service (see above).
5. Click **Deploy**.

---

## Local Dev with Vercel CLI

```bash
npm i -g vercel
vercel dev
```

`vercel dev` runs both services together and injects routing. Requires `vercel login` first.
