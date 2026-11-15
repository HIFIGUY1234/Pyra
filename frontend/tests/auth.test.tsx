import { describe, expect, it } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider, useAuth } from '../src/auth'
import { AuthBanners, AuthSplash, IdentityControl, LoginScreen } from '../src/auth-ui'
import { api, getAuthToken, setAuthToken } from '../src/lib'
import { META, mockFetch } from './helpers'

/* Same decision table as <Gate> in App.tsx, without the page routes. */
function Harness() {
  const a = useAuth()
  if (a.status === 'initialising' || a.status === 'error') return <AuthSplash />
  if (a.status === 'anonymous' || a.status === 'session_expired' || !a.identity) return <LoginScreen />
  return <div><IdentityControl /><AuthBanners /><div>protected content for {a.identity.username}</div><button onClick={() => { void api('/api/alerts').catch(() => {}) }}>call api</button></div>
}
const mount = () => render(<AuthProvider><MemoryRouter><Harness /></MemoryRouter></AuthProvider>)

const USERS = [
  { username: 'analyst', display_name: 'Fire Analyst', role: 'analyst' },
  { username: 'forest.officer', display_name: 'Range Officer', role: 'gov_officer' },
  { username: 'admin', display_name: 'System Admin', role: 'admin' },
]
type Opts = { mode: 'dev' | 'production'; login?: (u: string, p: string) => { status?: number; body: unknown; headers?: Record<string, string> } }
/** Fake backend implementing the real auth contract (token in Authorization, X-User only honoured in dev). */
function server({ mode, login }: Opts) {
  const sessions = new Map<string, { username: string; display_name: string; role: string; organisation_id: number | null; organisation_name: string | null }>()
  const calls = mockFetch((url, init) => {
    const h = (init?.headers || {}) as Record<string, string>
    const bearer = h.Authorization?.replace('Bearer ', '')
    if (url === '/api/meta') return { body: { ...META, auth_mode: mode, users: mode === 'dev' ? USERS : [] } }
    if (url === '/api/auth/login') {
      const b = JSON.parse(String(init?.body))
      if (login) return login(b.username, b.password)
      if (b.password !== 'Correct-Horse-1') return { status: 401, body: { detail: 'invalid username or password' } }
      const tok = `T-${b.username}`
      sessions.set(tok, b.username === 'org.mgr'
        ? { username: 'org.mgr', display_name: 'Org Manager', role: 'org_user', organisation_id: 4, organisation_name: 'Ludhiana Mills' }
        : { username: b.username, display_name: b.username === 'admin' ? 'System Admin' : 'Real Analyst', role: b.username === 'admin' ? 'admin' : 'analyst', organisation_id: null, organisation_name: null })
      return { body: { token: tok, token_type: 'bearer', expires_in_s: 3600 } }
    }
    if (url === '/api/auth/logout') { if (bearer) sessions.delete(bearer); return { body: { logged_out: true } } }
    if (url === '/api/auth/me' || url === '/api/alerts') {
      if (bearer) { const s = sessions.get(bearer); return s ? { body: { ...s, auth: 'token' } } : { status: 401, body: { detail: 'session invalid or expired; log in again' } } }
      if (mode === 'production') return { status: 401, body: { detail: 'authentication required (Bearer token)' } }
      const u = USERS.find((x) => x.username === (h['X-User'] || 'analyst'))
      return u ? { body: { ...u, organisation_id: null, auth: 'dev-persona' } } : { status: 401, body: { detail: 'unknown user' } }
    }
    return undefined
  })
  return { calls, sessions }
}

describe('development mode', () => {
  it('starts in demo mode with one identity control set and the demonstration notice', async () => {
    setAuthToken(null)
    const { calls } = server({ mode: 'dev' })
    mount()
    expect(screen.getByText('Checking session…')).toBeInTheDocument()
    expect(await screen.findByText('Demo mode')).toBeInTheDocument()
    expect(screen.getByLabelText('Demo persona')).toHaveValue('analyst')
    expect(screen.getByText(/Demonstration access\. Actions use a demo identity and do not establish a verified government account\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in with an account' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^log in$/i })).toBeNull()
    expect(screen.queryByText(/signed in ·/i)).toBeNull()
    expect(calls.find((c) => c.url === '/api/auth/me')?.headers['X-User']).toBe('analyst')
  })

  it('switching persona re-resolves identity on the server and persists the choice', async () => {
    setAuthToken(null)
    const { calls } = server({ mode: 'dev' })
    const u = userEvent.setup()
    mount()
    await u.selectOptions(await screen.findByLabelText('Demo persona'), 'forest.officer')
    expect(await screen.findByText('protected content for forest.officer')).toBeInTheDocument()
    expect(calls.filter((c) => c.url === '/api/auth/me').at(-1)?.headers['X-User']).toBe('forest.officer')
    expect(localStorage.getItem('pyro_user')).toBe('forest.officer')
    expect(screen.getByRole('option', { name: 'Range Officer · Forest Officer' })).toBeInTheDocument()
  })

  it('restores the stored persona after a reload, ignoring one the server no longer lists', async () => {
    setAuthToken(null)
    server({ mode: 'dev' })
    localStorage.setItem('pyro_user', 'admin')
    const first = mount()
    expect(await screen.findByText('protected content for admin')).toBeInTheDocument()
    first.unmount()
    localStorage.setItem('pyro_user', 'deleted.user')
    mount()
    expect(await screen.findByText('protected content for analyst')).toBeInTheDocument()
  })

  it('demo -> real account -> sign out returns to demo, revoking the session', async () => {
    setAuthToken(null)
    const { calls, sessions } = server({ mode: 'dev' })
    const u = userEvent.setup()
    mount()
    await u.click(await screen.findByRole('button', { name: 'Sign in with an account' }))
    const dlg = screen.getByRole('dialog', { name: 'Sign in with an account' })
    await u.type(within(dlg).getByLabelText('Username'), 'alice')
    await u.type(within(dlg).getByLabelText('Password'), 'Correct-Horse-1{Enter}')
    expect(await screen.findByText('protected content for alice')).toBeInTheDocument()
    expect(screen.queryByLabelText('Demo persona')).toBeNull()
    expect(screen.queryByText('Demo mode')).toBeNull()
    expect(screen.queryByText(/Demonstration access/)).toBeNull()
    expect(screen.getByTestId('identity-account')).toHaveTextContent('Real Analyst')
    expect(screen.getByTestId('identity-account')).toHaveTextContent('Analyst')
    expect(getAuthToken()).toBe('T-alice')
    expect(calls.filter((c) => c.url === '/api/auth/me').at(-1)?.headers.Authorization).toBe('Bearer T-alice')

    await u.click(screen.getByRole('button', { name: /Real Analyst/ }))
    await u.click(screen.getByRole('button', { name: 'Sign out and return to demo mode' }))
    expect(await screen.findByText('Demo mode')).toBeInTheDocument()
    expect(getAuthToken()).toBeNull()
    expect(sessions.size).toBe(0)
    expect(calls.some((c) => c.url === '/api/auth/logout' && c.headers.Authorization === 'Bearer T-alice')).toBe(true)
  })
})

describe('production mode', () => {
  it('anonymous visitor sees only the sign-in screen and no persona is ever sent', async () => {
    setAuthToken(null)
    localStorage.setItem('pyro_user', 'admin')   // stale dev choice must not leak into production
    const { calls } = server({ mode: 'production' })
    mount()
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByText(/demo/i)).toBeNull()
    expect(screen.queryByText(/dev persona/i)).toBeNull()
    expect(screen.queryByText(/protected content/)).toBeNull()
    expect(calls.every((c) => c.headers['X-User'] === undefined)).toBe(true)
  })

  it('validates empty fields client-side without calling the server', async () => {
    setAuthToken(null)
    const { calls } = server({ mode: 'production' })
    const u = userEvent.setup()
    mount()
    await u.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(screen.getByText('Enter your username.')).toBeInTheDocument()
    expect(screen.getByText('Enter your password.')).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toHaveAttribute('aria-invalid', 'true')
    expect(calls.some((c) => c.url === '/api/auth/login')).toBe(false)
  })

  it.each([
    [{ status: 401, body: { detail: 'invalid username or password' } }, /incorrect, or the account is disabled/],
    [{ status: 429, body: { detail: 'account temporarily locked after repeated failures; try again later' } }, /temporarily locked/],
    [{ status: 429, body: { detail: 'rate limit exceeded for login; retry in 30 s' }, headers: { 'Retry-After': '30' } }, /Try again in 30 s/],
    [{ status: 500, body: { detail: 'Traceback (most recent call last): secret path' } }, /could not complete sign-in \(HTTP 500\)/],
  ])('maps login failures to safe messages (%#)', async (resp, msg) => {
    setAuthToken(null)
    mockFetch((url) => (url === '/api/meta' ? { body: { ...META, auth_mode: 'production', users: [] } } : undefined))
    const base = globalThis.fetch
    globalThis.fetch = (async (url: string, init?: RequestInit) => url === '/api/auth/login'
      ? new Response(JSON.stringify(resp.body), { status: resp.status, headers: resp.headers })
      : base(url, init)) as typeof fetch
    const u = userEvent.setup()
    mount()
    await u.type(await screen.findByLabelText('Username'), 'admin')
    await u.type(screen.getByLabelText('Password'), 'whatever-1{Enter}')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(msg)
    expect(alert).not.toHaveTextContent(/Traceback/)
    expect(screen.getByLabelText('Password')).toHaveValue('')   // password not retained after a failure
    expect(getAuthToken()).toBeNull()
  })

  it('reports network failure and blocks double submission while pending', async () => {
    setAuthToken(null)
    let release: () => void = () => {}
    let loginCalls = 0
    mockFetch((url) => (url === '/api/meta' ? { body: { ...META, auth_mode: 'production', users: [] } } : undefined))
    const base = globalThis.fetch
    globalThis.fetch = ((url: string, init?: RequestInit) => {
      if (url !== '/api/auth/login') return base(url, init)
      loginCalls++
      return new Promise((_, rej) => { release = () => rej(new TypeError('Failed to fetch')) })
    }) as typeof fetch
    const u = userEvent.setup()
    mount()
    await u.type(await screen.findByLabelText('Username'), 'admin')
    await u.type(screen.getByLabelText('Password'), 'x{Enter}')
    const btn = await screen.findByRole('button', { name: /Signing in/ })
    expect(btn).toBeDisabled()
    await u.click(btn)
    expect(loginCalls).toBe(1)
    await act(async () => release())
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the PyroScope API')
  })

  it('successful login shows the server identity, organisation and, for admins, the administration menu', async () => {
    setAuthToken(null)
    server({ mode: 'production' })
    const u = userEvent.setup()
    const first = mount()
    await u.type(await screen.findByLabelText('Username'), 'org.mgr')
    await u.type(screen.getByLabelText('Password'), 'Correct-Horse-1')
    await u.click(screen.getByRole('button', { name: 'Show password' }))
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'text')
    await u.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('protected content for org.mgr')).toBeInTheDocument()
    await u.click(screen.getByRole('button', { name: /Org Manager/ }))
    expect(screen.getByText('Ludhiana Mills')).toBeInTheDocument()
    expect(screen.getByText('Organisation Manager')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Administration' })).toBeNull()
    expect(screen.queryByText(/demo/i)).toBeNull()
    await u.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByText('You have signed out.')).toBeInTheDocument()
    expect(getAuthToken()).toBeNull()
    first.unmount()

    mount()
    await u.type(await screen.findByLabelText('Username'), 'admin')
    await u.type(screen.getByLabelText('Password'), 'Correct-Horse-1{Enter}')
    await u.click(await screen.findByRole('button', { name: /System Admin/ }))
    const admin = screen.getByRole('navigation', { name: 'Administration' })
    expect(within(admin).getByRole('link', { name: 'System configuration' })).toHaveAttribute('href', '/system')
  })

  it('a stored token the server rejects becomes SESSION_EXPIRED with an explanation', async () => {
    setAuthToken('T-revoked')
    server({ mode: 'production' })
    mount()
    expect(await screen.findByText(/session has expired or was revoked/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(getAuthToken()).toBeNull()
  })

  it('a 401 on any later request returns to the sign-in screen', async () => {
    setAuthToken(null)
    const { sessions } = server({ mode: 'production' })
    const u = userEvent.setup()
    mount()
    await u.type(await screen.findByLabelText('Username'), 'alice')
    await u.type(screen.getByLabelText('Password'), 'Correct-Horse-1{Enter}')
    expect(await screen.findByText('protected content for alice')).toBeInTheDocument()
    sessions.clear()   // revoked elsewhere (other tab logout, password change, admin action)
    await u.click(screen.getByRole('button', { name: 'call api' }))
    await waitFor(() => expect(screen.getByText(/session has expired or was revoked/)).toBeInTheDocument())
    expect(screen.queryByText(/protected content/)).toBeNull()
  })
})
