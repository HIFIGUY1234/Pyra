import { defineConfig, devices } from '@playwright/test'
import { existsSync } from 'node:fs'

/* Browser end-to-end tests against the REAL backend and the loaded data.
   The backend runs on a throw-away copy of data/pyroscope.db (data/e2e.db), so journeys that approve alerts or
   register organisations never touch the working database. An admin password is bootstrapped only for this run. */
const winVenv = '../backend/.venv/Scripts/python.exe'
const PY = process.env.PYROSCOPE_E2E_PYTHON || (existsSync(winVenv) ? winVenv.replace(/\//g, '\\') : 'python')

export default defineConfig({
  testDir: 'e2e',
  timeout: 420_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    {
      command: `${PY} -c "import shutil; shutil.copy('../data/pyroscope.db', '../data/e2e.db')" && ${PY} -m uvicorn app.main:app --port 8000`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/api/health',
      timeout: 180_000,
      reuseExistingServer: false,
      env: {
        DATABASE_URL: 'sqlite:///../data/e2e.db',
        PYROSCOPE_ADMIN_PASSWORD: 'E2e-Admin-Passw0rd',
        PYROSCOPE_REPORTS_DIR: '../data/e2e_reports',
        PYROSCOPE_AUTH_MODE: 'dev',
      },
    },
    { command: 'npm run dev -- --port 5173 --strictPort --host 127.0.0.1', url: 'http://127.0.0.1:5173', timeout: 120_000, reuseExistingServer: false },
  ],
})
