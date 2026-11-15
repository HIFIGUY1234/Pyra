import { test, expect, type Page } from '@playwright/test'

/* Four user journeys from the completion brief, run in a real browser against the real API and loaded data.
   Screenshots go to test-results/screens (evidence of actual rendering, not committed). */

const SLOW = { timeout: 240_000 }   // first calibration fit / bootstrap on a cold server
const field = (page: Page, label: string) =>
  page.locator('div[class~="space-y-1.5"]', { has: page.locator('label', { hasText: new RegExp(`^${label}$`) }) }).locator('input').first()

const shot = (page: Page, name: string) => page.screenshot({ path: `test-results/screens/${name}.png`, fullPage: false })

async function persona(page: Page, username: string) {
  await page.getByLabel('Active operator profile').selectOption(username)
}

async function heading(page: Page, text: string | RegExp) {
  await expect(page.getByRole('heading', { level: 1, name: text })).toBeVisible()
}

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await expect(page.getByLabel('Active operator profile')).toBeVisible()
})

test('A - historical fire researcher', async ({ page }) => {
  await persona(page, 'analyst')
  await shot(page, 'desktop-dashboard')

  await page.goto('/data')
  await expect(page.getByText('Dataset inventory & ingestion report')).toBeVisible()
  await expect(page.getByText('DL_FIRE_M-C61_848456.zip').first()).toBeVisible()
  await shot(page, 'data-management')

  await page.goto('/map')
  await expect(page.locator('.leaflet-container').first()).toBeVisible()
  await shot(page, 'live-map')

  await page.goto('/morning-gap')
  await heading(page, 'Morning-Gap Fixer')
  await expect(page.getByText(/estimate/i).first()).toBeVisible()
  await shot(page, 'morning-gap')

  await page.goto('/harmonization')
  await heading(page, /Harmonization/)
  await expect(page.getByText('VIIRS product streams - 375 m and 750 m')).toBeVisible()
  await expect(page.getByText(/VIIRS 750 m: (unavailable|loaded)/)).toBeVisible()
  await page.getByText('VIIRS product streams - 375 m and 750 m').scrollIntoViewIfNeeded()
  await shot(page, 'harmonization-750m')

  await page.goto('/validation')
  await expect(page.getByText(/Seam verdict: (PASS|PARTIAL|FAIL)/)).toBeVisible(SLOW)
  await expect(page.getByText('Calibration model selection (held-out, year-blocked)')).toBeVisible()
  await expect(page.getByText('NOAA-21 cross-calibration study (VIIRS → S-NPP equivalent)')).toBeVisible()
  await expect(page.getByText(/Not calibrated - NOAA-21 stays a separate actual stream|Calibrated:/)).toBeVisible(SLOW)
  await page.getByText('NOAA-21 cross-calibration study (VIIRS → S-NPP equivalent)').scrollIntoViewIfNeeded()
  await shot(page, 'validation-noaa21')

  await page.goto('/calendar')
  await page.getByLabel('Area type').first().selectOption('state')
  await page.getByLabel('State').first().selectOption('Punjab')
  await expect(page.getByText(/Punjab/).first()).toBeVisible()
  await shot(page, 'calendar-punjab')

  await page.goto('/anomalies')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

  await page.goto('/reports')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})

test('B - forest officer: forecast, exposure, alert lifecycle, audit', async ({ page }) => {
  await persona(page, 'forest.officer')
  await page.goto('/government')
  await expect(page.getByText('People and facilities near recent actual hotspots')).toBeVisible()
  // wait for the real computation: detection/location counts or an explicit "no detections" state
  await expect(page.getByText(/detections at [\d,]+ locations/).first()).toBeVisible(SLOW)
  await expect(page.getByText('Loading hotspot exposure...')).toHaveCount(0)
  await page.getByText('People and facilities near recent actual hotspots').scrollIntoViewIfNeeded()
  await shot(page, 'government-exposure')

  await page.goto('/forecast')
  await expect(page.getByText('Forecast model comparison (same rows, same split, same calibration)')).toBeVisible()
  await expect(page.getByText(/XGBoost retained|meets the rule/)).toBeVisible()
  await expect(page.getByText(/not a verified ignition/).first()).toBeVisible()
  await page.getByText('Forecast model comparison (same rows, same split, same calibration)').scrollIntoViewIfNeeded()
  await shot(page, 'forecast-comparison')

  await page.goto('/critical-regions')
  await expect(page.getByText('State comparison - exposure, activity and forecast')).toBeVisible()
  await expect(page.getByText(/Population: (loaded|unavailable)/)).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Punjab', exact: true }).first()).toBeVisible(SLOW)
  await page.getByText('State comparison - exposure, activity and forecast').scrollIntoViewIfNeeded()
  await shot(page, 'critical-regions-exposure')

  await page.goto('/alerts')
  await page.getByRole('button', { name: /Evaluate Alert Rules/ }).click()
  await expect(page.getByText(/Evaluated alert rules/)).toBeVisible(SLOW)
  const ack = page.locator('button[title*="/acknowledge"]').first()
  await expect(ack).toBeVisible()
  const title = await ack.getAttribute('title')
  const id = title!.split('/')[3]
  await ack.click()
  await expect(page.getByText(new RegExp(`Alert #${id} updated via POST /api/alerts/${id}/acknowledge`))).toBeVisible()
  await page.locator(`button[title="POST /api/alerts/${id}/approve"]`).click()
  await expect(page.getByText(new RegExp(`/api/alerts/${id}/approve`)).first()).toBeVisible()
  // the audit trail and delivery log record the human decision; nothing goes to a real provider by default
  const detail = await page.request.get(`/api/alerts/${id}`, { headers: { 'X-User': 'forest.officer' } })
  const body = await detail.json()
  expect(['APPROVED', 'ESCALATED']).toContain(body.status)
  const log = await (await page.request.get(`/api/notifications/log?alert_id=${id}`, { headers: { 'X-User': 'forest.officer' } })).json()
  expect(log.items.every((x: { status: string }) => x.status !== 'SENT')).toBeTruthy()
})

test('C - organisation: register, add location, isolation', async ({ page }) => {
  await persona(page, 'org.user')
  await page.goto('/organisation')
  await heading(page, 'Organisation Dashboard')
  const name = `E2E Mills ${Date.now()}`
  await field(page, 'Name').fill(name)
  await page.getByRole('button', { name: 'Register' }).click()
  await expect(page.getByText(name).first()).toBeVisible()
  await page.getByText(name).first().click()
  await field(page, 'Facility name').fill('Boiler house')
  await page.getByRole('button', { name: 'Add location' }).click()
  await expect(page.getByText('Boiler house').first()).toBeVisible(SLOW)
  await shot(page, 'organisation')
  // another persona without organisation access cannot see it
  await persona(page, 'analyst')
  await expect(page.getByText('Organisation persona required')).toBeVisible()
})

test('D - administrator: password login, invalid login, observation intelligence, logout', async ({ page }) => {
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('wrong-password-1A')
  await page.locator('div.absolute').getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByText('invalid username or password')).toBeVisible()
  await page.getByLabel('Password').fill('E2e-Admin-Passw0rd')
  await page.locator('div.absolute').getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByTitle('Signed in with a session token. Click to log out.')).toContainText('admin')

  await page.goto('/data')
  await expect(page.getByRole('button', { name: 'Recover Git LFS archives' })).toBeVisible()
  await page.goto('/thresholds')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

  await page.goto('/observations')
  await expect(page.getByText('Predicted satellite overpasses (SGP4)')).toBeVisible()
  await expect(page.getByText(/Prediction - not a hotspot/)).toBeVisible()
  await page.getByLabel('Satellite').selectOption('Suomi NPP')
  await expect(page.getByText(/Validation against actual Suomi NPP detections/)).toBeVisible()
  await page.getByText('Predicted satellite overpasses (SGP4)').scrollIntoViewIfNeeded()
  await shot(page, 'observations-orbit')

  const health = await (await page.request.get('/api/health')).json()
  expect(health.database.ok).toBeTruthy()

  await page.getByTitle('Signed in with a session token. Click to log out.').click()
  await expect(page.getByRole('button', { name: 'Log in' })).toBeVisible()
})

test('mobile dashboard renders without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByLabel('Open navigation menu')).toBeVisible()
  await shot(page, 'mobile-dashboard')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})

test('E - operational transition, sensor products, 750 m and system readiness (no credentials)', async ({ page }) => {
  await persona(page, 'admin')
  await page.goto('/reference')
  await heading(page, 'Historical & Operational Reference')
  await expect(page.getByText('Historical reference')).toBeVisible()
  await expect(page.getByText('Candidate evaluation')).toBeVisible()
  await expect(page.getByText(/S-NPP → successor transition report/)).toBeVisible()
  await expect(page.getByText(/NOT_BRIDGED|Not Bridged|BRIDGED|Bridged/).first()).toBeVisible(SLOW)
  await shot(page, 'reference')

  await page.goto('/sensors/noaa-20')
  await heading(page, /NOAA-20 VIIRS analysis/)
  await expect(page.getByText('Independent forecast model')).toBeVisible()
  await page.goto('/sensors/noaa-21')
  await heading(page, /NOAA-21 VIIRS analysis/)

  await page.goto('/forecast/models')
  await heading(page, 'Forecast models by target sensor')
  await page.getByLabel('Forecast target sensor').selectOption('NOAA-20')
  await expect(page.getByText(/Target sensor NOAA-20/)).toBeVisible(SLOW)
  await page.getByLabel('Forecast target sensor').selectOption('Suomi NPP')
  await expect(page.getByText(/Stale Retired Sensor|STALE_RETIRED_SENSOR/).first()).toBeVisible(SLOW)
  await shot(page, 'forecast-models')

  await page.goto('/products/viirs750')
  await heading(page, /VIIRS 750 m/)
  await expect(page.getByText(/NOT CONFIGURED\. Authentic granule download/)).toBeVisible()
  await expect(page.getByRole('button', { name: /Download & convert/ })).toBeDisabled()

  await page.goto('/exposure/infrastructure')
  await heading(page, 'Infrastructure exposure')
  await expect(page.getByText('Linear infrastructure (OpenStreetMap / Geofabrik)')).toBeVisible()

  await page.goto('/system')
  await heading(page, 'System configuration')
  await expect(page.getByRole('heading', { level: 3, name: 'Credential readiness', exact: true })).toBeVisible()
  await expect(page.getByText('NASA Earthdata (VIIRS 750 m)')).toBeVisible()
  await expect(page.getByRole('heading', { level: 3, name: 'Notification setup checklist', exact: true })).toBeVisible()
  await shot(page, 'system-config')
  const r = await page.request.get('/api/system/credentials', { headers: { 'X-User': 'admin' } })
  expect(await r.text()).not.toContain('E2e-Admin-Passw0rd')
})

test('F - fire intelligence: events, detail, emissions, smoke, geostationary, validation, jobs', async ({ page }) => {
  await persona(page, 'analyst')
  await page.goto('/events')
  await heading(page, 'Fire events')
  await expect(page.getByText(/No CONTAINED status exists/)).toBeVisible()
  await expect(page.locator('.leaflet-container').first()).toBeVisible()
  const first = page.locator('tbody tr').first()
  await expect(first).toBeVisible(SLOW)
  const id = (await first.locator('td').first().innerText()).trim()
  expect(id).toMatch(/^FE-\d{8}-[0-9a-f]{8}$/)
  await page.getByLabel('Event sort').selectOption('n_obs')
  await shot(page, 'fire-events')
  await page.goto(`/events/${id}`)
  await heading(page, `Fire event ${id}`)
  await expect(page.getByText(/observation footprint/i).first()).toBeVisible()
  await expect(page.getByRole('heading', { level: 3, name: 'Linked satellite observations', exact: true })).toBeVisible()
  await expect(page.getByText(/original FIRMS records/)).toBeVisible(SLOW)
  await shot(page, 'fire-event-detail')

  await page.goto('/emissions')
  await heading(page, 'Biomass-burning emissions')
  await expect(page.getByText(/ESTIMATED · EXPERIMENTAL · NOT INDEPENDENTLY VALIDATED/)).toBeVisible()
  await expect(page.getByText(/BLOCKED BY EXTERNAL DATA|Blocked By External Data/i).first()).toBeVisible()

  await page.goto('/smoke')
  await heading(page, 'Smoke transport')
  await expect(page.getByText(/PyroScope does not forecast PM2.5/)).toBeVisible()

  await page.goto('/burned-area')
  await heading(page, 'Burned-area mapping')
  await expect(page.getByText(/never counted as unburned/)).toBeVisible()

  await page.goto('/geostationary')
  await heading(page, 'Geostationary fire monitoring and diurnal activity')
  await expect(page.getByText(/cannot validate the 2000-2002 Terra-only reconstruction/)).toBeVisible()
  await expect(page.getByText('Polar Only').first()).toBeVisible(SLOW)
  await shot(page, 'geostationary')

  await page.goto('/external-validation')
  await heading(page, 'External scientific validation')
  await expect(page.getByText('Naive MODIS + VIIRS sum')).toBeVisible(SLOW)
  await expect(page.getByText(/NOT INDEPENDENT of MODIS active fires/)).toBeVisible()
  await shot(page, 'external-validation')

  await page.goto('/jobs')
  await heading(page, 'Background jobs')
  await persona(page, 'admin')
  await page.goto('/deployment')
  await heading(page, 'Deployment health')
  await expect(page.getByText(/Dialect/)).toBeVisible()
  const r = await page.request.post('/api/advisories', { headers: { 'X-User': 'forest.officer' }, data: { kind: 'OFFICIAL_EMERGENCY_WARNING', ref: id } })
  expect(r.status()).toBe(409)
})
