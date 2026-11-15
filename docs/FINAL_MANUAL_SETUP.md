# Final manual setup (things only you can do)

Everything below needs your accounts, decisions or credentials. Secret values go in `.env` (git-ignored) or the host's
secret store — never in the repository and never in `VITE_*` variables. After each step, `GET /api/system/credentials`
(admin) and `python -m app.system_config` show readiness without revealing values.

Already present in your `.env` (values not read by Claude): `EARTHDATA_TOKEN` (valid until 2027-01-13),
`FIRMS_MAP_KEY`, `PYROSCOPE_ADMIN_PASSWORD`.

## 1. Earthdata approvals (unblocks burned area + VIIRS 750 m) — 5 minutes

The token works, but downloads are refused until the account accepts two things:

1. Sign in at https://ladsweb.modaps.eosdis.nasa.gov with your Earthdata account and **accept the LAADS data licence**
   (downloads currently redirect to `/profiles/licenses/...`).
2. Earthdata Login → Applications → Authorized Apps → approve **LP DAAC** (cloud downloads currently redirect to OAuth).
3. Admin → Background Jobs → *Burned area (MCD64A1)* for e.g. 2024-11; and `viirs750_fetch` for a short period
   (`python -m app.pipeline --viirs750 2025-11-01 2025-11-07`).
4. Optional burned-area emissions: add `data/auxiliary/emissions/fuel_consumption.csv`
   (`biome,fc_kg_m2,fc_sd_kg_m2,source`) from an authoritative published source.

## 2. MOSDAC (INSAT fire / smoke) — registration

Register at https://www.mosdac.gov.in, order INSAT-3DR `3RIMG_L2P_FIR` (KML) for a test period, then import:
Geostationary & Diurnal → *Import authorised export* (source + licence mandatory).

## 3. Independent validation data

* Fire incidents: obtain a register from a state forest department / fire service with permission; import CSV
  (`incident_id,source_authority,start_date,latitude,longitude` …) on External Validation.
* Ground PM2.5: `OPENAQ_API_KEY` (https://explore.openaq.org) or `DATA_GOV_IN_API_KEY` (CPCB via data.gov.in).

## 4. Supabase

1. Create the project; note `<project-ref>`, DB password, `SUPABASE_URL`, service-role key.
2. `supabase link --project-ref <ref> && supabase db push` (or run the two SQL files in `supabase/migrations/`).
3. Backend env: `DATABASE_URL=postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require`
   (or port 6543 for the transaction pooler), `PYROSCOPE_STORAGE=supabase`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
4. `cd backend && python -m app.pg_migrate copy --target "$DATABASE_URL"` — check `"reconciled": true`.
5. Storage plan: Free = 50 MB/file; the FIRMS archives need Pro or stay in Git LFS.

## 5. Backend host (persistent containers)

Pick Render / Railway / Fly.io / DigitalOcean / any Docker host. Deploy `backend/Dockerfile` twice:
* **api**: default command (uvicorn), env from §4 + `PYROSCOPE_AUTH_MODE=production`, `PYROSCOPE_ADMIN_PASSWORD`,
  `PYROSCOPE_CORS_ORIGINS=https://<frontend-domain>`, `PYROSCOPE_EMBEDDED_WORKER=0`, `PYROSCOPE_TRUST_PROXY=1` behind the host proxy.
* **worker**: command `python -m app.worker`, same env.
* Persistent volume for `/app/data` if you keep Parquet locally (or move it to Supabase Storage).
* `python -m app.system_config` must exit 0 in production mode.

## 6. Vercel

See [VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md): root `frontend`, `VITE_API_BASE_URL=https://<api-domain>`,
`vercel deploy` (preview) → approve → `vercel deploy --prod`. Add the preview regex to the API's
`PYROSCOPE_CORS_ORIGIN_REGEX`.

## 7. Notifications

`PYROSCOPE_NOTIFY_PROVIDER=smtp|webhook` with `SMTP_*` or `PYROSCOPE_WEBHOOK_*`; register and verify a test contact you own;
`POST /api/notifications/test/{contact_id}`. Real authority contacts must be verified by an administrator before any
external delivery. SMS is not implemented.

## 8. Domain, DNS, TLS

Point `app.<domain>` to Vercel and `api.<domain>` to the backend host; both serve HTTPS (managed certificates).

## 9. Pull request

The feature branch `feature/pyroscope-ultimate-completion` is pushed; open/merge the PR after reviewing CI.
