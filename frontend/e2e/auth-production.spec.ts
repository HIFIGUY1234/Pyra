import { test, expect, type Page } from '@playwright/test'
import { randomBytes } from 'node:crypto'
import { E2E_ADMIN_PASSWORD } from './env'

/* Production-mode stack (backend :8001 with PYROSCOPE_AUTH_MODE=production, Vite :5174). */
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screens/${name}.png`, fullPage: false })

async function signIn(page: Page, username: string, password: string) {
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
}

test('anonymous visitor: sign-in screen only; X-User rejected by the server', async ({ page }) => {
  await page.goto('/alerts')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByText('Satellite Fire Intelligence and MODIS–VIIRS Harmonization')).toBeVisible()
  await expect(page.getByLabel('Demo persona')).toHaveCount(0)
  await expect(page.getByText(/demo|dev persona/i)).toHaveCount(0)
  await expect(page.getByRole('complementary', { name: 'Main navigation' })).toHaveCount(0)
  await shot(page, 'prod-login')
  for (const u of ['admin', 'analyst']) {
    expect((await page.request.get('/api/alerts', { headers: { 'X-User': u } })).status()).toBe(401)
    expect((await page.request.get('/api/auth/me', { headers: { 'X-User': u } })).status()).toBe(401)
  }
  expect((await (await page.request.get('/api/meta')).json()).users).toEqual([])
})

test('admin: invalid then valid credentials, destination kept, admin menu, logout revokes token, re-login', async ({ page }) => {
  await page.goto('/alerts')
  await signIn(page, 'admin', 'definitely-wrong-1')
  await expect(page.getByRole('alert')).toContainText('Username or password is incorrect')
  await signIn(page, 'admin', E2E_ADMIN_PASSWORD)
  await expect(page.getByTestId('identity-account')).toContainText('Administrator')
  await expect(page).toHaveURL(/\/alerts$/)                                         // requested page preserved
  await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
  await expect(page.getByText(/demo/i)).toHaveCount(0)
  await page.goto('/system')
  await expect(page.getByRole('heading', { level: 1, name: 'System configuration' })).toBeVisible()
  await page.getByTestId('identity-account').getByRole('button').click()
  await expect(page.getByRole('navigation', { name: 'Administration' })).toBeVisible()
  await expect(page.getByTestId('identity-account').getByText('Production', { exact: true })).toBeVisible()
  await shot(page, 'prod-admin-menu')
  const token = await page.evaluate(() => sessionStorage.getItem('pyro_token'))
  expect(token).toBeTruthy()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByText('You have signed out.')).toBeVisible()
  expect(await page.evaluate(() => sessionStorage.getItem('pyro_token'))).toBeNull()
  expect((await page.request.get('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } })).status()).toBe(401)
  await signIn(page, 'admin', E2E_ADMIN_PASSWORD)
  await expect(page.getByTestId('identity-account')).toContainText('Administrator')
})

test('analyst account: actual role, admin API refused with 403, revoked session returns to sign-in', async ({ page }) => {
  // create a disposable analyst through the real admin API (random password, never stored)
  const admin = await (await page.request.post('/api/auth/login', { data: { username: 'admin', password: E2E_ADMIN_PASSWORD } })).json()
  const username = `e2e.analyst.${Date.now()}`
  const password = `An-${randomBytes(9).toString('base64url')}9`
  const created = await page.request.post('/api/users', { headers: { Authorization: `Bearer ${admin.token}` }, data: { username, display_name: 'E2E Analyst', role: 'analyst', password } })
  expect(created.status()).toBe(200)

  await page.goto('/')
  await signIn(page, username, password)
  const account = page.getByTestId('identity-account')
  await expect(account).toContainText('E2E Analyst')
  await expect(account).toContainText('Analyst')
  await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
  await shot(page, 'prod-analyst-overview')
  await account.getByRole('button').click()
  await expect(page.getByRole('navigation', { name: 'Administration' })).toHaveCount(0)
  await page.keyboard.press('Escape')

  await page.goto('/system')
  await expect(page.getByText('Configuration and credential status are visible to administrators only.')).toBeVisible()
  const token = await page.evaluate(() => sessionStorage.getItem('pyro_token'))
  const denied = await page.request.get('/api/system/config', { headers: { Authorization: `Bearer ${token}` } })
  expect(denied.status()).toBe(403)                                                      // enforced by the server, not the UI
  expect((await denied.json()).detail).toMatch(/may not perform this action/)
  await expect(page.getByTestId('identity-account')).toBeVisible()

  // revoke the session out of band (another tab signing out / admin action) -> next request ends the session
  expect((await page.request.post('/api/auth/logout', { headers: { Authorization: `Bearer ${token}` } })).status()).toBe(200)
  await page.getByRole('link', { name: 'Fire Events', exact: true }).click()
  await expect(page.getByText(/session has expired or was revoked/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await shot(page, 'prod-session-expired')
})
