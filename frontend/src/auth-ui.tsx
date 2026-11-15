/* Authentication UI: sign-in screen (production), sign-in dialog (dev), identity control for the top bar and the
 * demonstration-access banner. Every control here reads the single AuthProvider state; none keeps its own idea of
 * who the user is. */
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { NavLink } from 'react-router-dom'
import { ChevronDown, Eye, EyeOff, LogIn, LogOut, RefreshCw, ShieldCheck, X } from 'lucide-react'
import { ApiError, SAT_LABEL } from './lib'
import { roleLabel, useAuth } from './auth'
import { BrandLockup, BrandMark } from './brand'

/* ------------------------------------------------------------------ helpers */
/** Map a failed /api/auth/login call to a message. Backend detail text is only used for known, short cases. */
export function loginErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return 'Username or password is incorrect, or the account is disabled.'
    if (e.status === 429) return /locked/i.test(e.message)
      ? 'This account is temporarily locked after repeated failed attempts. Try again later or contact an administrator.'
      : `Too many sign-in attempts from this connection. Try again in ${e.retryAfter ?? 60} s.`
    if (e.status === 422) return 'Enter a username and password.'
    if (e.status >= 500) return `The server could not complete sign-in (HTTP ${e.status}). Try again shortly.`
    return `Sign-in failed (HTTP ${e.status}).`
  }
  return 'Cannot reach the PyroScope API. Check your network connection or the configured API address.'
}

/** Persona option text: seed names carry a '(demo persona)' suffix the DEMO MODE badge already states; add the role only when it adds information. */
const personaLabel = (name: string, role: string) => {
  const n = name.replace(/\s*\(demo persona\)\s*$/i, '')
  const r = roleLabel(role)
  return n.toLowerCase() === r.toLowerCase() ? n : `${n} · ${r}`
}
const fmtTime = (ms: number) => new Date(ms).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })

/* ------------------------------------------------------------------ form */
export function LoginForm({ onDone, autoFocus = true }: { onDone?: () => void; autoFocus?: boolean }) {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [fieldErr, setFieldErr] = useState<{ u?: string; p?: string }>({})
  const [err, setErr] = useState<string | null>(null)
  const uid = useId()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    const fe = { u: username.trim() ? undefined : 'Enter your username.', p: password ? undefined : 'Enter your password.' }
    setFieldErr(fe); setErr(null)
    if (fe.u || fe.p) return
    setBusy(true)
    try {
      await login(username.trim(), password)
      setPassword('')
      onDone?.()
    } catch (ex) {
      setErr(loginErrorMessage(ex)); setPassword('')
    } finally { setBusy(false) }
  }

  const input = 'w-full rounded-md border bg-[#0b1220] px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-400'
  return (
    <form onSubmit={submit} noValidate className="space-y-4" aria-describedby={err ? `${uid}-err` : undefined}>
      <div>
        <label htmlFor={`${uid}-u`} className="mb-1 block text-xs font-medium text-slate-300">Username</label>
        <input id={`${uid}-u`} name="username" autoComplete="username" autoFocus={autoFocus} value={username} disabled={busy}
          onChange={(e) => setUsername(e.target.value)} aria-invalid={Boolean(fieldErr.u)} aria-describedby={fieldErr.u ? `${uid}-ue` : undefined}
          className={`${input} ${fieldErr.u ? 'border-red-500' : 'border-[#2a3a55]'}`} />
        {fieldErr.u && <p id={`${uid}-ue`} className="mt-1 text-xs text-red-300">{fieldErr.u}</p>}
      </div>
      <div>
        <label htmlFor={`${uid}-p`} className="mb-1 block text-xs font-medium text-slate-300">Password</label>
        <div className="relative">
          <input id={`${uid}-p`} name="password" type={show ? 'text' : 'password'} autoComplete="current-password" value={password} disabled={busy}
            onChange={(e) => setPassword(e.target.value)} aria-invalid={Boolean(fieldErr.p)} aria-describedby={fieldErr.p ? `${uid}-pe` : undefined}
            className={`${input} pr-10 ${fieldErr.p ? 'border-red-500' : 'border-[#2a3a55]'}`} />
          <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show}
            className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-md text-slate-400 hover:text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400">
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        {fieldErr.p && <p id={`${uid}-pe`} className="mt-1 text-xs text-red-300">{fieldErr.p}</p>}
      </div>
      {err && <div id={`${uid}-err`} role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 px-3 py-2 text-xs text-red-100">{err}</div>}
      <button type="submit" disabled={busy}
        className="flex w-full items-center justify-center gap-2 rounded-md bg-[#e8692a] px-3 py-2 text-sm font-semibold text-white hover:bg-[#f07a3d] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400 disabled:cursor-wait disabled:opacity-60">
        {busy ? <><RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />Signing in…</> : <><LogIn className="h-4 w-4" aria-hidden="true" />Sign in</>}
      </button>
    </form>
  )
}

/* ------------------------------------------------------------------ sign-in screen (production) */
/** Schematic only: a lat/lon graticule with the swath widths of the two instrument families drawn to relative scale. */
function SwathGraphic() {
  return (
    <svg viewBox="0 0 400 220" className="h-auto w-full" role="img" aria-label="Schematic of MODIS and VIIRS orbital swaths over a latitude-longitude grid">
      <defs>
        <pattern id="grat" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#1d2a40" strokeWidth="1" /></pattern>
      </defs>
      <rect width="400" height="220" fill="url(#grat)" />
      {/* VIIRS swath ~3060 km, MODIS ~2330 km: drawn 77 px vs 59 px wide */}
      <polygon points="150,0 227,0 287,220 210,220" fill="#d95926" fillOpacity="0.13" stroke="#d95926" strokeOpacity="0.55" />
      <polygon points="60,0 119,0 179,220 120,220" fill="#3987e5" fillOpacity="0.13" stroke="#3987e5" strokeOpacity="0.55" />
      <text x="70" y="16" fill="#8fb6ec" fontSize="10">MODIS · 1 km</text>
      <text x="160" y="16" fill="#eaa07f" fontSize="10">VIIRS · 375 m</text>
      {[[138, 98], [146, 112], [232, 120], [241, 135], [250, 128], [300, 170]].map(([x, y], i) => (
        <rect key={i} x={x} y={y} width="5" height="5" fill="#f0782d" opacity={x > 280 ? 0.35 : 0.9} />
      ))}
      <text x="392" y="212" textAnchor="end" fill="#64748b" fontSize="9">schematic · not data</text>
    </svg>
  )
}

export function LoginScreen() {
  const { status, notice, meta } = useAuth()
  const spans = meta?.spans || {}
  const order = ['Terra', 'Aqua', 'Suomi NPP', 'NOAA-20', 'NOAA-21'].filter((s) => spans[s])
  return (
    <div className="min-h-screen w-full bg-[#080d17] text-slate-200 lg:grid lg:grid-cols-[1.15fr_1fr]">
      <section className="hidden flex-col justify-between border-r border-[#1d2a40] bg-[#0b1220] p-10 lg:flex" aria-label="About PyroScope">
        <BrandLockup subtitle="MODIS–VIIRS Fire Monitoring" />
        <div className="max-w-xl space-y-5">
          <h1 className="text-2xl font-semibold leading-snug text-white">Satellite Fire Intelligence and MODIS–VIIRS Harmonization</h1>
          <p className="text-sm leading-relaxed text-slate-400">
            Explore historical active-fire observations, harmonized satellite records, regional burning patterns and scientifically evaluated fire forecasts.
          </p>
          <div className="rounded-md border border-[#1d2a40] bg-[#080d17] p-3"><SwathGraphic /></div>
          {order.length > 0 && (
            <div>
              <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Archive held by this deployment</h2>
              <table className="text-xs">
                <tbody>
                  {order.map((s) => (
                    <tr key={s}><td className="border-0 py-0.5 pl-0 pr-4 text-slate-300">{SAT_LABEL[s] || s}</td>
                      <td className="border-0 py-0.5 font-mono tabular-nums text-slate-400">{spans[s].first} – {spans[s].last}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <p className="text-[11px] text-slate-500">Source observations: NASA FIRMS MODIS C6.1 and VIIRS C2 active-fire products. Harmonized values are estimates and are labelled as such throughout.</p>
      </section>

      <main className="flex min-h-screen items-center justify-center p-4 sm:p-8">
        <div className="w-full max-w-sm">
          <div className="mb-6 lg:hidden"><BrandLockup /></div>
          <h2 className="text-lg font-semibold text-white">Sign in</h2>
          <p className="mt-1 text-sm text-slate-400">Use the account issued by your PyroScope administrator.</p>
          {status === 'session_expired' && notice && (
            <div role="status" className="mt-4 rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">{notice}</div>
          )}
          {status === 'anonymous' && notice && (
            <div role="status" className="mt-4 rounded-md border border-[#2a3a55] bg-[#0f1726] px-3 py-2 text-xs text-slate-300">{notice}</div>
          )}
          <div className="mt-5"><LoginForm /></div>
          <p className="mt-6 text-[11px] leading-relaxed text-slate-500">
            Sessions are issued by the server for a fixed period and end when this browser tab is closed. Repeated failed attempts temporarily lock the account.
          </p>
        </div>
      </main>
    </div>
  )
}

/* ------------------------------------------------------------------ boot / error screens */
export function AuthSplash() {
  const { status, error, retry } = useAuth()
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#080d17] p-4 text-slate-200">
      <div className="w-full max-w-sm text-center">
        <div className="mb-4 flex justify-center"><BrandMark size={40} /></div>
        {status === 'error' ? (
          <div role="alert">
            <h1 className="text-base font-semibold text-white">PyroScope API unavailable</h1>
            <p className="mt-2 text-sm text-slate-400">The application could not load its configuration from the server.</p>
            {error && <p className="mt-2 break-words font-mono text-xs text-slate-500">{error.slice(0, 200)}</p>}
            <button onClick={retry} className="mt-4 inline-flex items-center gap-2 rounded-md border border-[#2a3a55] bg-[#0f1726] px-3 py-1.5 text-sm hover:bg-[#16213a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400">
              <RefreshCw className="h-4 w-4" aria-hidden="true" />Retry
            </button>
          </div>
        ) : (
          <p role="status" className="text-sm text-slate-400">Checking session…</p>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ dialog (dev: demo -> real account) */
export function SignInDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Tab' && ref.current) {   // keep focus inside the dialog
        const f = ref.current.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled])')
        if (!f.length) return
        const first = f[0], last = f[f.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); prev?.focus?.() }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[10vh]" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} className="w-full max-w-sm rounded-lg border border-[#2a3a55] bg-[#0f1726] p-5 shadow-2xl">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h2 id={titleId} className="text-base font-semibold text-white">Sign in with an account</h2>
            <p className="mt-1 text-xs leading-relaxed text-slate-400">Replaces the demo persona with a verified server session. Your role and organisation will come from the account.</p>
          </div>
          <button onClick={onClose} aria-label="Close sign-in dialog" className="rounded p-1 text-slate-400 hover:bg-[#16213a] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"><X className="h-4 w-4" /></button>
        </div>
        <LoginForm onDone={onClose} />
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ top-bar identity control */
const ADMIN_LINKS = [
  { to: '/system', label: 'System configuration' }, { to: '/thresholds', label: 'Alert thresholds' },
  { to: '/jobs', label: 'Background jobs' }, { to: '/data', label: 'Data management' }, { to: '/deployment', label: 'Deployment health' },
]

export function IdentityControl() {
  const { status, mode, identity, meta, selectPersona, logout, sessionExpiresAt } = useAuth()
  const [dialog, setDialog] = useState(false)
  const [menu, setMenu] = useState(false)
  const [busy, setBusy] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!menu) return
    const onDoc = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setMenu(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(false) }
    document.addEventListener('mousedown', onDoc); document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey) }
  }, [menu])

  if (status === 'initialising') return <span role="status" className="text-xs text-slate-500">Checking session…</span>
  if (!identity) return null

  if (status === 'demo') {
    return (
      <div className="flex flex-wrap items-center gap-2" data-testid="identity-demo">
        <span className="rounded border border-amber-500/60 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">Demo mode</span>
        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          <span className="sr-only sm:not-sr-only">Persona</span>
          <select aria-label="Demo persona" value={identity.username} disabled={busy}
            onChange={async (e) => { setBusy(true); try { await selectPersona(e.target.value) } finally { setBusy(false) } }}
            className="max-w-[12rem] py-1 text-xs">
            {(meta?.users || []).map((u) => <option key={u.username} value={u.username}>{personaLabel(u.display_name, u.role)}</option>)}
          </select>
        </label>
        <button onClick={() => setDialog(true)}
          className="inline-flex items-center gap-1.5 rounded-md border border-[#2a3a55] px-2 py-1 text-xs text-slate-200 hover:bg-[#16213a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400">
          <LogIn className="h-3.5 w-3.5" aria-hidden="true" />Sign in with an account
        </button>
        <SignInDialog open={dialog} onClose={() => setDialog(false)} />
      </div>
    )
  }

  // authenticated
  return (
    <div ref={wrap} className="relative" data-testid="identity-account">
      <button onClick={() => setMenu((m) => !m)} aria-expanded={menu} aria-controls={menuId}
        className="flex items-center gap-2 rounded-md border border-[#2a3a55] bg-[#0f1726] px-2.5 py-1 text-left text-xs hover:bg-[#16213a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400">
        <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-emerald-400" aria-hidden="true" />
        <span className="hidden text-slate-400 md:inline">Signed in ·</span>
        <span className="max-w-[10rem] truncate font-medium text-slate-100">{identity.display_name}</span>
        <span className="hidden text-slate-400 sm:inline">· {roleLabel(identity.role)}</span>
        <ChevronDown className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
      </button>
      {menu && (
        <div id={menuId} className="absolute right-0 z-40 mt-2 w-72 rounded-lg border border-[#2a3a55] bg-[#0f1726] p-3 text-xs shadow-2xl">
          <div className="text-sm font-semibold text-white">{identity.display_name}</div>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-slate-300">
            <dt className="text-slate-500">Username</dt><dd className="font-mono">{identity.username}</dd>
            <dt className="text-slate-500">Role</dt><dd>{roleLabel(identity.role)}</dd>
            {identity.organisation_id != null && <><dt className="text-slate-500">Organisation</dt><dd>{identity.organisation_name || `#${identity.organisation_id}`}</dd></>}
            <dt className="text-slate-500">Session</dt><dd>Verified server session{sessionExpiresAt ? ` · until ${fmtTime(sessionExpiresAt)}` : ''}</dd>
            <dt className="text-slate-500">Mode</dt><dd>{mode === 'production' ? 'Production' : 'Development'}</dd>
          </dl>
          {identity.role === 'admin' && (
            <nav aria-label="Administration" className="mt-3 border-t border-[#2a3a55] pt-2">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Administration</div>
              <ul>{ADMIN_LINKS.map((l) => <li key={l.to}><NavLink to={l.to} onClick={() => setMenu(false)} className="block rounded px-1.5 py-1 text-slate-200 hover:bg-[#16213a]">{l.label}</NavLink></li>)}</ul>
            </nav>
          )}
          <button onClick={async () => { setMenu(false); await logout() }}
            className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md border border-[#2a3a55] px-2 py-1.5 text-slate-100 hover:bg-[#16213a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400">
            <LogOut className="h-3.5 w-3.5" aria-hidden="true" />{mode === 'dev' ? 'Sign out and return to demo mode' : 'Sign out'}
          </button>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ banners */
export function AuthBanners() {
  const { status, notice, clearNotice } = useAuth()
  return (
    <>
      {status === 'demo' && (
        <div className="border-b border-amber-500/30 bg-amber-500/[0.07] px-4 py-1.5 text-[11px] text-amber-200 lg:px-6" role="note">
          Demonstration access. Actions use a demo identity and do not establish a verified government account.
        </div>
      )}
      {notice && (status === 'demo' || status === 'authenticated') && (
        <div role="status" className="flex items-center justify-between gap-3 border-b border-[#2a3a55] bg-[#0f1726] px-4 py-1.5 text-[11px] text-slate-300 lg:px-6">
          <span>{notice}</span>
          <button onClick={clearNotice} aria-label="Dismiss message" className="rounded p-0.5 text-slate-400 hover:text-white"><X className="h-3.5 w-3.5" /></button>
        </div>
      )}
    </>
  )
}
