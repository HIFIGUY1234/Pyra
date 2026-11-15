import { test, expect, type Page, type Route } from '@playwright/test'

/* Burning Activity Calendar + dataset readiness.
   Journey 1 uses the REAL committed processed dataset through the real API (no mocks, no fixtures).
   Journeys 2-4 replace only /api/calendar and /api/data/readiness with failure FIXTURES to show the waiting states;
   the fixtures contain no fire detections. */

const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screens/${name}.png`, fullPage: false })

async function persona(page: Page, username: string) {
  await page.goto('/')
  const sel = page.getByLabel('Demo persona')
  await expect(sel).toBeVisible()
  if ((await sel.inputValue()) !== username) {
    const me = page.waitForResponse((r) => r.url().endsWith('/api/auth/me') && r.request().headers()['x-user'] === username)
    await sel.selectOption(username)
    await me
  }
}

test('real dataset: admin validates on Data Management, calendar shows actual daily/monthly activity', async ({ page }) => {
  await persona(page, 'admin')
  await page.goto('/data')
  const steps = page.getByTestId('dataset-steps')
  await expect(steps.getByText('Check repository archives')).toBeVisible()
  await expect(steps.getByText('Check Git LFS status')).toBeVisible()
  await expect(steps.getByText(/^READY ·/)).toBeVisible()                       // step 7: verified readiness
  await shot(page, 'data-readiness-steps')

  // Load Repository Dataset on a valid dataset = validate + reload, never a historical rebuild.
  await steps.getByRole('button', { name: 'Load Repository Dataset', exact: true }).click()
  await expect(steps.getByText(/Validating the existing processed dataset|validate existing dataset/).first()).toBeVisible()
  await expect.poll(async () => (await (await page.request.get('/api/data/status')).json()).job.state, { timeout: 180_000 }).toBe('done')
  const rd = await (await page.request.get('/api/data/readiness', { headers: { 'X-User': 'admin' } })).json()
  expect(rd.status).toBe('READY')
  expect(rd.satellites).toEqual(expect.arrayContaining(['Aqua', 'Terra', 'Suomi NPP', 'NOAA-20', 'NOAA-21']))

  await page.goto('/calendar')
  await expect(page.getByRole('heading', { level: 1, name: 'Burning Activity Calendar' })).toBeVisible()
  await page.getByLabel('Year').selectOption('2023')
  await expect(page.getByText(/· 2023 ·/).first()).toBeVisible()
  const heat = page.getByLabel('Daily activity heatmap')
  await expect(heat).toBeVisible()

  // NOAA-21's record starts 2023-03-01: January must be hatched "no observation", never a zero cell.
  await page.getByRole('button', { name: 'NOAA-21', exact: true }).click()
  await expect(heat.locator('span[title^="2023-01-15: no observation"]')).toHaveCount(1)
  await expect(heat.locator('span[title^="2023-06-15:"]')).not.toHaveAttribute('title', /no observation/)

  await page.getByRole('button', { name: 'NOAA-20', exact: true }).click()
  await page.getByRole('button', { name: 'FRP (MW)' }).click()
  await expect(page.getByText(/NOAA-20 VIIRS FRP/).first()).toBeVisible()
  await expect(heat.locator('span[title*=" MW"]').first()).toBeVisible()
  await page.getByRole('button', { name: 'Detections' }).click()
  await page.getByRole('button', { name: 'VIIRS-equivalent', exact: true }).click()
  await expect(page.getByText(/VIIRS-equivalent \(actual VIIRS where observed\)/)).toBeVisible()
  await expect(page.getByText('Monthly comparison: original sensors vs harmonized record')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Mar' })).toBeVisible()            // monthly coverage table
  await shot(page, 'calendar-real-2023')

  await page.reload()
  await expect(page.getByLabel('Daily activity heatmap')).toBeVisible()
  await expect(page.getByTestId('dataset-waiting')).toHaveCount(0)
})

const notReady = (route: Route) => route.fulfill({
  status: 409, contentType: 'application/json',
  body: JSON.stringify({ detail: { code: 'DATASET_NOT_READY', status: 'LFS_NOT_RECOVERED', message: 'No processed satellite dataset is available yet. Git LFS archives have not been downloaded.',
    next_action: { code: 'recover_lfs', message: 'Git LFS archives have not been downloaded.' } } }),
})
const readiness = (admin: boolean) => ({
  status: 'LFS_NOT_RECOVERED', dataset_status: 'MISSING', ready: false, can_administer: admin,
  required: ['daily_cell.parquet', 'monthly_cell.parquet', 'spans.json', 'cells.parquet', 'districts.parquet'].map((file) => ({ file, status: 'missing' })),
  missing: ['daily_cell.parquet', 'monthly_cell.parquet', 'spans.json', 'cells.parquet', 'districts.parquet'], processed_files: 0,
  coverage: {}, satellites: [], registry: { status: 'missing', sources: 0, without_aggregate: [] }, aggregates: 0, hotspot_partitions: 0,
  calibration: {}, forecast: {},
  archives: { total: 1, valid: 0, lfs_pointers: 1, corrupt: 0, uploads: 0, ingestable: false,
    items: [{ file: 'DL_FIRE_SV-C2_846940.zip', status: 'lfs_pointer', message: 'Git LFS archives have not been downloaded.', expected_bytes: 159863811, bytes: 133 }] },
  lfs: { pointers: 1, recovered: false, message: 'Git LFS archives have not been downloaded.' },
  job: { state: 'idle', log_tail: [] }, seed: { state: 'not_applicable' }, manifest: null, last_success: null,
  next_action: { code: 'recover_lfs', message: 'Git LFS archives have not been downloaded.', command: 'git lfs pull', admin_only: true },
})

test('fixture: dataset unavailable, Forest Officer sees guidance but no admin controls', async ({ page }) => {
  await persona(page, 'forest.officer')
  await page.route(/\/api\/calendar\?/, notReady)
  await page.route(/\/api\/data\/readiness$/, (r) => r.fulfill({ json: readiness(false) }))
  await page.goto('/calendar')
  const w = page.getByTestId('dataset-waiting')
  await expect(page.getByText('Burning Activity Calendar is waiting for a processed satellite dataset.')).toBeVisible()
  await expect(w.getByText('Dataset administration requires an authorised administrator.')).toBeVisible()
  await expect(w.getByText(/1 Git LFS pointer/)).toBeVisible()
  await expect(page.getByRole('button', { name: /Recover Git LFS archives/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Load Repository Dataset', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Daily activity heatmap')).toHaveCount(0)          // nothing drawn, no zeros
  await shot(page, 'calendar-waiting-officer')
  await page.getByRole('button', { name: 'Open Data Management' }).click()
  await expect(page).toHaveURL(/\/data$/)
})

test('fixture: dataset unavailable, administrator is offered LFS recovery', async ({ page }) => {
  await persona(page, 'admin')
  await page.route(/\/api\/calendar\?/, notReady)
  await page.route(/\/api\/data\/readiness$/, (r) => r.fulfill({ json: readiness(true) }))
  await page.goto('/calendar')
  await expect(page.getByText('Git LFS content not downloaded')).toBeVisible()
  await expect(page.getByRole('button', { name: /Recover Git LFS archives/ })).toBeVisible()
  await shot(page, 'calendar-waiting-admin')
})

test('fixture: backend offline', async ({ page }) => {
  await persona(page, 'analyst')
  await page.route(/\/api\/calendar\?/, (r) => r.abort('connectionrefused'))
  await page.route(/\/api\/data\/readiness$/, (r) => r.abort('connectionrefused'))
  await page.goto('/calendar')
  await expect(page.getByText('Backend unreachable')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry Burning Activity Calendar' })).toBeVisible()
})
