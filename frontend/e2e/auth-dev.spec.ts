import { test, expect, type Page } from '@playwright/test'

/* Development-mode identity behaviour and a visual tour of every major page (screenshots in e2e-screens). */
const shot = (page: Page, name: string, fullPage = false) => page.screenshot({ path: `e2e-screens/${name}.png`, fullPage })

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await expect(page.getByLabel('Demo persona')).toBeVisible()
})

test('dev startup shows exactly one identity control set and no template branding', async ({ page }) => {
  await expect(page.getByText('Demo mode', { exact: true })).toHaveCount(1)
  await expect(page.getByLabel('Demo persona')).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'Sign in with an account' })).toHaveCount(1)
  await expect(page.getByRole('button', { name: /^log in$/i })).toHaveCount(0)
  await expect(page.getByText(/dev persona/i)).toHaveCount(0)
  await expect(page.getByText('Demonstration access. Actions use a demo identity and do not establish a verified government account.')).toBeVisible()
  await expect(page.getByText(/argon/i)).toHaveCount(0)
  await expect(page.getByRole('complementary', { name: 'Main navigation' }).getByText('PyroScope', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
  await expect(page.locator('.leaflet-container').first()).toBeVisible()
  await shot(page, 'dev-overview')
  await page.locator('header').first().screenshot({ path: 'e2e-screens/dev-header.png' })
})

test('persona switch changes the server identity and survives reload and navigation', async ({ page }) => {
  const sel = page.getByLabel('Demo persona')
  const me = page.waitForResponse((r) => r.url().endsWith('/api/auth/me') && r.request().headers()['x-user'] === 'forest.officer')
  await sel.selectOption('forest.officer')
  const body = await (await me).json()
  expect(body.role).toBe('gov_officer')
  expect(body.auth).toBe('dev-persona')
  await expect(sel).toHaveValue('forest.officer')
  await page.getByRole('link', { name: 'Alerts', exact: true }).click()
  await expect(sel).toHaveValue('forest.officer')
  await page.reload()
  await expect(page.getByLabel('Demo persona')).toHaveValue('forest.officer')
  const req = page.waitForRequest((r) => r.url().includes('/api/') && r.headers()['x-user'] !== undefined)
  await page.getByRole('link', { name: 'Fire Events', exact: true }).click()
  expect((await req).headers()['x-user']).toBe('forest.officer')
  await shot(page, 'dev-persona-forest-officer')
  await page.getByLabel('Demo persona').selectOption('analyst')
  await expect(page.getByLabel('Demo persona')).toHaveValue('analyst')
})

const PAGES: [string, string][] = [
  ['/', 'overview'], ['/map', 'fire-map'], ['/calendar', 'calendar'], ['/events', 'events'],
  ['/reference', 'reference'], ['/sensors/noaa-20', 'noaa-20'], ['/products/viirs375', 'viirs375'], ['/geostationary', 'geostationary'], ['/orbits', 'orbits'],
  ['/harmonization', 'harmonizer'], ['/morning-gap', 'morning-gap'], ['/uncertainty', 'uncertainty'], ['/validation', 'validation'],
  ['/historical-trends', 'trends'], ['/external-validation', 'external-validation'],
  ['/forecast', 'forecast'], ['/forecast/models', 'forecast-models'], ['/anomalies', 'anomalies'], ['/exposure/population', 'exposure-population'], ['/critical-regions', 'critical-regions'],
  ['/burned-area', 'burned-area'], ['/emissions', 'emissions'], ['/smoke', 'smoke'],
  ['/alerts', 'alerts'], ['/government', 'government'], ['/organisation', 'organisation'], ['/jobs', 'jobs'],
  ['/data', 'data'], ['/data/quality', 'data-quality'], ['/reports', 'reports'], ['/thresholds', 'thresholds'], ['/system', 'system'], ['/deployment', 'deployment'],
]

test('page tour: every major page renders a title, breadcrumb and no horizontal overflow', async ({ page }) => {
  test.setTimeout(900_000)
  await page.getByLabel('Demo persona').selectOption('admin')
  await expect(page.getByLabel('Demo persona')).toHaveValue('admin')
  for (const [path, name] of PAGES) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({ timeout: 120_000 })
    await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toBeVisible()
    await expect(page.getByText(/\[\d+[a-z]?\/\d+\]/)).toHaveCount(0)            // no technical section index as title
    await page.waitForTimeout(800)                                                // let charts settle for the screenshot
    await shot(page, `page-${name}`)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, `${path} overflows horizontally`).toBeLessThanOrEqual(1)
  }
})

test('mobile: compact header, drawer navigation, sign-in dialog fits', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByLabel('Demo persona')).toBeVisible()
  await shot(page, 'mobile-overview')
  await page.getByLabel('Open navigation menu').click()
  await expect(page.getByRole('complementary', { name: 'Main navigation' })).toBeInViewport()
  await shot(page, 'mobile-nav-open')
  await page.getByRole('link', { name: 'Fire Events', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
  for (const p of ['/', '/events', '/validation', '/alerts']) {
    await page.goto(p)
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({ timeout: 120_000 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), `${p} overflows on mobile`).toBeLessThanOrEqual(1)
  }
  await page.getByRole('button', { name: 'Sign in with an account' }).click()
  const dlg = page.getByRole('dialog', { name: 'Sign in with an account' })
  await expect(dlg).toBeInViewport()
  await shot(page, 'mobile-signin-dialog')
  await page.keyboard.press('Escape')
  await expect(dlg).toHaveCount(0)
})
