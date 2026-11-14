# Manual setup after code completion

Everything below needs a value only you can provide. Until it is set, the matching feature reports
`NOT_CONFIGURED` / `BLOCKED_BY_CREDENTIALS` (see *System configuration* in the UI or `GET /api/system/credentials`
as admin) and nothing pretends to work. **Never commit any of these values.** Put them in `.env` (git-ignored)
next to `docker-compose.yml`, or in your host's secret store.

```bash
cp .env.example .env      # then edit .env
```

## 1. Administrator password (required for production)

```bash
PYROSCOPE_ADMIN_PASSWORD=<at least 10 chars, upper + lower case + digit, not a common word>
```
Used once at start-up to set the `admin` login if it has no password. Start the API, log in as `admin`, then
create real accounts (`POST /api/users` or the UI). You may remove the variable afterwards.
Check: `GET /api/health` → `"admin_bootstrap": "configured"`.

## 2. Production mode and CORS

```bash
PYROSCOPE_AUTH_MODE=production
PYROSCOPE_CORS_ORIGINS=https://<your frontend domain>
DATABASE_URL=sqlite:////app/data/pyroscope.db     # or postgresql+psycopg://user:pass@host:5432/pyroscope
PYROSCOPE_TRUST_PROXY=1                            # only behind the bundled nginx / your reverse proxy
```
The API refuses to start in production while any blocking error remains (wildcard CORS, no admin bootstrap,
weak admin password, in-memory DB, rate limiting off). Validate first:
```bash
cd backend && python -m app.system_config     # exit code 0 = OK; prints only variable names and problems
```

## 3. NASA Earthdata (VIIRS 750 m granules)

Earthdata Login → *Generate Token*, then either
```bash
EARTHDATA_TOKEN=<token>
```
or a `~/.netrc` line for the account running the backend:
```
machine urs.earthdata.nasa.gov login <user> password <password>
```
Then: *VIIRS 750 m* page → **Download & convert (job)**, or
```bash
cd backend && python -m app.pipeline --viirs750 2025-11-01 2025-11-07 --skip-train --skip-weather
```
Real-granule verification stays `BLOCKED_BY_CREDENTIALS` until at least one authentic granule is downloaded and
converted (`GET /api/viirs750/status` → `real_data_verification`).

## 4. Notifications (choose one; default stays simulated)

SMTP:
```bash
PYROSCOPE_NOTIFY_PROVIDER=smtp
SMTP_HOST=<host>  SMTP_PORT=587  SMTP_TLS_MODE=starttls   # or ssl on 465
SMTP_USER=<user>  SMTP_PASSWORD=<password>  SMTP_FROM=<verified sender address>
```
Webhook (to an authority's own gateway):
```bash
PYROSCOPE_NOTIFY_PROVIDER=webhook
PYROSCOPE_WEBHOOK_ALLOWED_HOSTS=<host1,host2>     # https only, public addresses only
PYROSCOPE_WEBHOOK_TOKEN=<bearer token the receiver checks>
```
Then, as admin: *System configuration* → **Check provider connection**; register a verified contact; send one
labelled TEST message (`POST /api/notifications/test/{contact_id}`). Real advisories are still delivered only
after an officer approves an alert, and never as public warnings. SMS is not implemented (use a verified webhook
to an authority's own SMS gateway).

## 5. Verified authority contacts

As admin, for each authority: *Alerts* → contacts, or `POST /api/authorities` with `confirm_verified: true`
**after** you have confirmed the address with that authority. Never use guessed addresses.

## 6. FIRMS MAP_KEY (optional)

```bash
FIRMS_MAP_KEY=<key from https://firms.modaps.eosdis.nasa.gov/api/map_key/>
cd backend && python -m app.acquire firms VIIRS_NOAA21_NRT 2026-11-01 2026-11-10
python -m app.pipeline --only-new --sensor-models
```

## 7. Public data refreshes that need internet access (no credentials)

Run where the network allows it, or with the **Data integration** GitHub workflow (Actions → *Data integration
(manual)* → tick `linear_gis` and/or `population`), then copy the artifact into `data/auxiliary/`:
```bash
cd backend
python -m app.pipeline --linear-gis --skip-train --skip-weather        # Geofabrik India (~1.5 GB download)
python -m app.pipeline --refresh-exposure --skip-train --skip-weather  # WorldPop 2020 area-weighted + OSM facilities
python -m app.pipeline --refresh-tle --skip-train --skip-weather       # CelesTrak TLEs
```

## 8. Hosting, domain and DNS

1. A Linux host with Docker (2 vCPU / 8 GB RAM / 30 GB disk is enough for the bundled data).
2. `git clone https://github.com/HIFIGUY1234/Pyra.git && cd Pyra && git lfs pull`
3. `cp .env.example .env` and fill sections 1–2 (and 3–4 when ready).
4. `docker compose up -d --build` (serves on port 8080 through nginx).
5. Point an `A`/`AAAA` record for your domain at the host and terminate TLS in front of port 8080
   (e.g. Caddy or nginx with Let's Encrypt). Set `PYROSCOPE_CORS_ORIGINS` to that https origin.
6. `curl https://<domain>/api/health` → `status: ok`, `admin_bootstrap: configured`.

See also `docs/DEPLOYMENT.md` and `docs/PRODUCTION_READINESS.md`.
