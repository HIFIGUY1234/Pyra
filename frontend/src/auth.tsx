/* Single authoritative authentication state for the frontend.
 *
 * States
 *   initialising    - /api/meta and (if a token is stored) /api/auth/me are in flight; no identity controls are shown.
 *   anonymous       - production, no session. Only the sign-in screen is rendered.
 *   authenticated   - a Bearer session the server accepted; identity/role/organisation come from /api/auth/me.
 *   demo            - development only: the X-User demo persona, resolved by the server from its user table.
 *   session_expired - production, the server rejected the stored token. Sign-in screen with an explanation.
 *   error           - the API could not be reached / answered unexpectedly. Retry is offered.
 *
 * The request credential itself lives in lib.tsx (setCredential) because api() reads it synchronously; only this
 * provider changes it. The server stays the authority: the role shown is always the role /api/auth/me returned. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, ApiError, getCredential, getStoredPersona, getTokenExpiry, SESSION_EXPIRED_EVENT, setCredential, type Meta } from './lib'

export type AuthStatus = 'initialising' | 'anonymous' | 'authenticated' | 'demo' | 'session_expired' | 'error'
export type AuthMode = 'dev' | 'production'
export type Identity = {
  id?: number; username: string; display_name: string; role: string
  organisation_id?: number | null; organisation_name?: string | null; auth: 'token' | 'dev-persona'
}
type LoginResp = { token: string; token_type: string; expires_in_s: number }

export type AuthValue = {
  status: AuthStatus
  mode: AuthMode | null
  identity: Identity | null
  meta: Meta | null
  /** Human-readable message about the last transition (session ended, signed out, ...). */
  notice: string | null
  error: string | null
  /** Epoch ms when the current Bearer session expires (from the login response), if known. */
  sessionExpiresAt: number | null
  /** Changes whenever the effective identity changes; used to remount pages so no user-specific data survives. */
  identityKey: string
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  selectPersona: (username: string) => Promise<void>
  retry: () => void
  reloadMeta: () => void
  clearNotice: () => void
}

const AuthCtx = createContext<AuthValue | null>(null)
export function useAuth(): AuthValue {
  const v = useContext(AuthCtx)
  if (!v) throw new Error('useAuth must be used inside <AuthProvider>')
  return v
}

export const ROLE_LABEL: Record<string, string> = {
  analyst: 'Analyst', gov_officer: 'Forest Officer', org_user: 'Organisation Manager', admin: 'Administrator',
}
export const roleLabel = (r?: string | null) => (r ? ROLE_LABEL[r] || r : '')

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** Pick the demo persona: the stored choice if the server still lists it, else 'analyst', else the first active user. */
export function resolvePersona(meta: Meta, wanted: string | null): string | null {
  const users = meta.users || []
  if (wanted && users.some((u) => u.username === wanted)) return wanted
  return users.find((u) => u.username === 'analyst')?.username || users[0]?.username || null
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('initialising')
  const [mode, setMode] = useState<AuthMode | null>(null)
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expiresAt, setExpiresAt] = useState<number | null>(getTokenExpiry())
  // Every transition takes a ticket; async results from an older ticket are discarded (StrictMode double effects,
  // a persona switch racing a login, ...).
  const ticket = useRef(0)
  const modeRef = useRef<AuthMode | null>(null)
  const metaRef = useRef<Meta | null>(null)

  const fail = useCallback((t: number, e: unknown) => {
    if (t !== ticket.current) return
    setIdentity(null); setError(errText(e)); setStatus('error')
  }, [])

  /** Enter demo mode as `wanted` (dev only). */
  const enterDemo = useCallback(async (t: number, m: Meta, wanted: string | null, note: string | null) => {
    const persona = resolvePersona(m, wanted)
    if (!persona) { fail(t, new Error('Development mode is active but the server lists no demo users.')); return }
    setCredential({ kind: 'persona', username: persona })
    const me = await api<Identity>('/api/auth/me')
    if (t !== ticket.current) return
    setIdentity(me); setExpiresAt(null); setNotice(note); setError(null); setStatus('demo')
  }, [fail])

  /** No usable token: production -> sign-in screen, dev -> demo persona. */
  const enterSignedOut = useCallback(async (t: number, m: Meta, how: 'anonymous' | 'session_expired', note: string | null) => {
    if (modeRef.current === 'dev') { await enterDemo(t, m, getStoredPersona(), note); return }
    setCredential({ kind: 'none' })
    if (t !== ticket.current) return
    setIdentity(null); setExpiresAt(null); setNotice(note); setError(null); setStatus(how)
  }, [enterDemo])

  const boot = useCallback(async () => {
    const t = ++ticket.current
    setStatus('initialising'); setError(null)
    try {
      const m = await api<Meta>('/api/meta')
      if (t !== ticket.current) return
      const md: AuthMode = m.auth_mode === 'production' ? 'production' : 'dev'
      modeRef.current = md; metaRef.current = m
      setMode(md); setMeta(m)
      const cred = getCredential()
      if (cred.kind === 'token') {
        try {
          const me = await api<Identity>('/api/auth/me')
          if (t !== ticket.current) return
          setIdentity(me); setExpiresAt(getTokenExpiry()); setNotice(null); setStatus('authenticated')
          return
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 401)) throw e
          await enterSignedOut(t, m, 'session_expired', 'Your session has expired or was revoked. Sign in again to continue.')
          return
        }
      }
      // A persona left over from an earlier page load is never trusted in production: it is simply not sent.
      await enterSignedOut(t, m, 'anonymous', null)
    } catch (e) { fail(t, e) }
  }, [enterSignedOut, fail])

  useEffect(() => { void boot() }, [boot])

  // Any API call that gets a 401 for our token lands here.
  useEffect(() => {
    const onExpired = () => {
      const m = metaRef.current
      if (!m) return
      const t = ++ticket.current
      void enterSignedOut(t, m, 'session_expired', 'Your session has expired or was revoked. Sign in again to continue.').catch((e) => fail(t, e))
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
  }, [enterSignedOut, fail])

  const login = useCallback(async (username: string, password: string) => {
    const t = ++ticket.current
    const before = getCredential()
    const r = await api<LoginResp>('/api/auth/login', { body: { username, password } })
    setCredential({ kind: 'token', token: r.token }, r.expires_in_s)
    try {
      const me = await api<Identity>('/api/auth/me')
      if (t !== ticket.current) return
      setIdentity(me); setExpiresAt(getTokenExpiry()); setNotice(null); setError(null); setStatus('authenticated')
    } catch (e) {
      setCredential(before.kind === 'token' ? { kind: 'none' } : before)
      throw e
    }
  }, [])

  const logout = useCallback(async () => {
    const t = ++ticket.current
    if (getCredential().kind === 'token') {
      try { await api('/api/auth/logout', { method: 'POST' }) } catch { /* already expired/revoked server-side */ }
    }
    setCredential({ kind: 'none' })
    const m = metaRef.current
    if (!m) { void boot(); return }
    try {
      await enterSignedOut(t, m, 'anonymous', modeRef.current === 'dev' ? 'Signed out. You are back in demonstration mode.' : 'You have signed out.')
    } catch (e) { fail(t, e) }
  }, [boot, enterSignedOut, fail])

  const selectPersona = useCallback(async (username: string) => {
    const m = metaRef.current
    if (modeRef.current !== 'dev' || !m || getCredential().kind === 'token') return
    const t = ++ticket.current
    try { await enterDemo(t, m, username, null) } catch (e) { fail(t, e) }
  }, [enterDemo, fail])

  const reloadMeta = useCallback(() => {
    void api<Meta>('/api/meta').then((m) => { metaRef.current = m; setMeta(m) }).catch(() => { /* keep previous meta */ })
  }, [])

  const value = useMemo<AuthValue>(() => ({
    status, mode, identity, meta, notice, error, sessionExpiresAt: status === 'authenticated' ? expiresAt : null,
    identityKey: identity ? `${identity.auth}:${identity.username}` : status,
    login, logout, selectPersona, retry: () => { void boot() }, reloadMeta, clearNotice: () => setNotice(null),
  }), [status, mode, identity, meta, notice, error, expiresAt, login, logout, selectPersona, boot, reloadMeta])

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>
}
