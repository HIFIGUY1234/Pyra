import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthControl, LoginGate } from '../src/completion'
import { getAuthToken, setAuthToken } from '../src/lib'
import { META, mockFetch, withApp } from './helpers'

describe('authentication workflow', () => {
  it('logs in, shows the account from /api/auth/me, then logs out and revokes the session', async () => {
    setAuthToken(null)
    let signedIn = false
    const calls = mockFetch((url, init) => {
      if (url === '/api/auth/login') {
        const b = JSON.parse(String(init?.body))
        if (b.password !== 'right-pass') return { status: 401, body: { detail: 'invalid credentials' } }
        signedIn = true
        return { body: { token: 'T-1' } }
      }
      if (url === '/api/auth/me') return signedIn ? { body: { username: 'officer1', role: 'gov_officer' } } : { status: 401, body: { detail: 'no session' } }
      if (url === '/api/auth/logout') { signedIn = false; return { body: { ok: true } } }
      return undefined
    })
    const onChange = vi.fn()
    const u = userEvent.setup()
    render(withApp(<AuthControl onChange={onChange} />))

    await u.click(screen.getByRole('button', { name: /log in/i }))
    await u.type(screen.getByLabelText('Username'), 'officer1')
    await u.type(screen.getByLabelText('Password'), 'wrong')
    await u.click(screen.getAllByRole('button', { name: /^log in$/i }).at(-1)!)
    expect(await screen.findByText('invalid credentials')).toBeInTheDocument()
    expect(getAuthToken()).toBeNull()

    await u.clear(screen.getByLabelText('Password'))
    await u.type(screen.getByLabelText('Password'), 'right-pass{Enter}')
    await waitFor(() => expect(getAuthToken()).toBe('T-1'))
    expect(onChange).toHaveBeenCalled()
    expect(await screen.findByText(/officer1/)).toBeInTheDocument()
    expect(calls.find((c) => c.url === '/api/auth/me' && c.headers.Authorization === 'Bearer T-1')).toBeTruthy()

    await u.click(screen.getByTitle(/click to log out/i))
    await waitFor(() => expect(getAuthToken()).toBeNull())
    expect(calls.some((c) => c.url === '/api/auth/logout' && c.method === 'POST')).toBe(true)
  })

  it('production mode blocks protected content until a session exists', () => {
    setAuthToken(null)
    const { rerender } = render(withApp(<LoginGate><div>secret dashboard</div></LoginGate>, { meta: { ...META, auth_mode: 'production' } }))
    expect(screen.getByText('Authentication required')).toBeInTheDocument()
    expect(screen.queryByText('secret dashboard')).toBeNull()
    setAuthToken('T-2')
    rerender(withApp(<LoginGate><div>secret dashboard</div></LoginGate>, { meta: { ...META, auth_mode: 'production' } }))
    expect(screen.getByText('secret dashboard')).toBeInTheDocument()
    setAuthToken(null)
  })
})
