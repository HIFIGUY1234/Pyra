import { defineConfig, devices } from '@playwright/test'
import { existsSync } from 'node:fs'
import { E2E_ADMIN_PASSWORD } from './e2e/env'

/* Browser end-to-end tests against the REAL backend and the loaded data.
   Two independent stacks run side by side, each on its own throw-away copy of data/pyroscope.db:
     dev        backend :8000 (PYROSCOPE_AUTH_MODE=dev)        <- Vite :5173   journeys, demo-persona flows, page tour
     production backend :8001 (PYROSCOPE_AUTH_MODE=production) <- Vite :5174   sign-in screen, sessions, X-User rejection
   The working database is never touched. An admin password is bootstrapped only into the copies. */
const winVenv = '../backend/.venv/Scripts/python.exe'
const PY = process.env.PYROSCOPE_E2E_PYTHON || (existsSync(winVenv) ? winVenv.replace(/\//g, '\\') : 'python')
// Copy the demo DB and strip any developer credentials from the copy (see e2e/prepare_db.py).
const copyDb = (to: string) => `${PY} ../frontend/e2e/prepare_db.py ../data/pyroscope.db ../data/${to}`

export default defineConfig({
  testDir: 'e2e',
  timeout: 420_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop', testIgnore: /auth-production/, use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, baseURL: 'http://127.0.0.1:5173' } },
    { name: 'production', testMatch: /auth-production/, use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, baseURL: 'http://127.0.0.1:5174' } },
  ],
  webServer: [
    {
      command: `${copyDb('e2e.db')} && ${PY} -m uvicorn app.main:app --port 8000`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/api/health',
      timeout: 180_000,
      reuseExistingServer: false,
      env: {
        DATABASE_URL: 'sqlite:///../data/e2e.db',
        PYROSCOPE_ADMIN_PASSWORD: E2E_ADMIN_PASSWORD,
        PYROSCOPE_REPORTS_DIR: '../data/e2e_reports',
        PYROSCOPE_AUTH_MODE: 'dev',
      },
    },
    {
      command: `${copyDb('e2e_prod.db')} && ${PY} -m uvicorn app.main:app --port 8001`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8001/api/health',
      timeout: 180_000,
      reuseExistingServer: false,
      env: {
        DATABASE_URL: 'sqlite:///../data/e2e_prod.db',
        PYROSCOPE_ADMIN_PASSWORD: E2E_ADMIN_PASSWORD,
        PYROSCOPE_REPORTS_DIR: '../data/e2e_prod_reports',
        PYROSCOPE_AUTH_MODE: 'production',
        PYROSCOPE_CORS_ORIGINS: 'http://127.0.0.1:5174',
        PYROSCOPE_EMBEDDED_WORKER: '0',
      },
    },
    { command: 'npm run dev -- --port 5173 --strictPort --host 127.0.0.1', url: 'http://127.0.0.1:5173', timeout: 120_000, reuseExistingServer: false },
    {
      command: 'npm run dev -- --port 5174 --strictPort --host 127.0.0.1', url: 'http://127.0.0.1:5174', timeout: 120_000, reuseExistingServer: false,
      env: { PYROSCOPE_API_PROXY: 'http://127.0.0.1:8001' },
    },
  ],
})
