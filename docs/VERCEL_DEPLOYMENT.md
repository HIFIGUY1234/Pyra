# Vercel frontend deployment

Status: **IMPLEMENTED BUT NOT DEPLOYED** (no Vercel project/credentials; no production deploy without your approval).
CI job `vercel-build` builds exactly as Vercel does with an external API origin and checks the bundle for secrets.

## Project settings

| Setting | Value |
|---|---|
| Root directory | `frontend` |
| Framework preset | Vite (also declared in `frontend/vercel.json`) |
| Install command | `npm ci --no-audit --no-fund` |
| Build command | `npm run build` (tsc + vite) |
| Output directory | `dist` |
| Node | 20.x |

`frontend/vercel.json`: SPA fallback (`/(.*)` → `/index.html`; Vercel serves existing files before rewrites, so
assets and deep links both work), immutable caching for `/assets/*`, `no-cache` for `index.html`, security headers
(nosniff, DENY framing, referrer policy, permissions policy).

## Environment variables

| Variable | Preview | Production | Notes |
|---|---|---|---|
| `VITE_API_BASE_URL` | staging API origin | production API origin, e.g. `https://api.pyroscope.example.org` | public; baked into the bundle at build time; never a secret |

Nothing else. Never put Supabase keys, Earthdata tokens or passwords in `VITE_*`.

## Backend CORS for Vercel

On the API: `PYROSCOPE_CORS_ORIGINS=https://<your-production-domain>` and, for preview deployments,
`PYROSCOPE_CORS_ORIGIN_REGEX=^https://pyroscope-[a-z0-9-]+-<team>\.vercel\.app$` (anchored; `.*` / `.+` rejected by
`python -m app.system_config`).

## Steps (manual, after approval)

```bash
npm i -g vercel
cd frontend
vercel link                      # choose/create the project; root = frontend
vercel env add VITE_API_BASE_URL preview
vercel env add VITE_API_BASE_URL production
vercel build                     # local Vercel build check
vercel deploy                    # preview
vercel deploy --prod             # production — only after approval
```

API errors surface in the UI through `lib.tsx:api()` (detail text, 401 clears the session).
