# PyroScope Deployment (Vercel Frontend + Render/Railway Backend)

## Architecture

- **Frontend:** Deployed on **Vercel** (static Vite React build, super fast CDN).
- **Backend:** Deployed on **Render / Railway / Fly.io** via Docker (`backend/Dockerfile`).
  - Solves AWS Lambda 500 MB limit by running full Python geospatial stack (GDAL, XGBoost, Scipy, PyArrow, etc.) in a Linux container.

---

## Step 1: Deploy Backend (Render or Railway)

### Option A: Render (Easiest)
1. Go to [dashboard.render.com](https://dashboard.render.com/) -> **New +** -> **Web Service**.
2. Connect your repository: `https://github.com/HIFIGUY1234/Pyra`.
3. Choose **Docker**.
4. Set:
   - **Dockerfile Path:** `backend/Dockerfile`
   - **Docker Context:** `.` (root directory)
5. Add Environment Variables:
   - `PYROSCOPE_EMBEDDED_WORKER` = `1`
   - `PYROSCOPE_NOTIFY_PROVIDER` = `simulated`
   - `PYROSCOPE_CORS_ORIGIN_REGEX` = `^https://.*\.vercel\.app$`
   - `DATABASE_URL` = (optional, default SQLite in persistent disk, or Supabase/Neon PostgreSQL)
6. Click **Deploy Web Service**.
7. Copy your backend URL once live: e.g. `https://pyroscope-backend.onrender.com`.

### Option B: Railway
1. Go to [railway.app](https://railway.app/) -> **New Project** -> **Deploy from GitHub repo**.
2. Select `HIFIGUY1234/Pyra`.
3. In settings, set Dockerfile path to `backend/Dockerfile`.
4. Add environment variables above.
5. Generate domain and copy URL.

---

## Step 2: Deploy Frontend on Vercel

1. Go to [vercel.com/new](https://vercel.com/new) -> Select `HIFIGUY1234/Pyra`.
2. Under **Environment Variables**, add:
   - `VITE_API_BASE_URL` = `https://YOUR-BACKEND-URL.onrender.com`
3. Click **Deploy**.
4. Vercel will build the frontend cleanly with zero size limit issues.
5. Frontend communicates directly with your backend container.
