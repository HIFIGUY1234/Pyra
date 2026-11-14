import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

/* ------------------------------------------------------------------ colours */
// Sensor palette: validated for the dark surface (CVD-safe adjacent order). Entities keep their colour everywhere.
export const SAT_COLOR: Record<string, string> = {
  Terra: '#3987e5', 'Suomi NPP': '#d95926', Aqua: '#199e70', 'NOAA-21': '#d55181', 'NOAA-20': '#9085e9',
}
export const C = { terra: '#3987e5', viirs: '#d95926', aqua: '#199e70', est: '#c98500', n21: '#d55181', n20: '#9085e9', muted: '#64748b', grid: '#223049' }
export const SAT_LABEL: Record<string, string> = {
  Terra: 'Terra MODIS', Aqua: 'Aqua MODIS', 'Suomi NPP': 'S-NPP VIIRS', 'NOAA-20': 'NOAA-20 VIIRS', 'NOAA-21': 'NOAA-21 VIIRS',
}
// Risk tiers are status colours: always shown with their label, never colour alone.
export const TIER_COLOR: Record<string, string> = { LOW: '#10b981', WATCH: '#eab308', MODERATE: '#f59e0b', HIGH: '#f97316', VERY_HIGH: '#dc2626', UNKNOWN: '#64748b' }
export const TIERS = ['LOW', 'WATCH', 'MODERATE', 'HIGH', 'VERY_HIGH']
export const LAND_COLOR: Record<string, string> = {
  Forest: '#15803d', Agricultural: '#ca8a04', 'Municipal/Urban': '#a855f7', 'Residential/Village': '#ec4899', Industrial: '#0ea5e9', Other: '#64748b', Unknown: '#334155',
}
export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/* ------------------------------------------------------------------ formatting */
type Numeric = number | string | null | undefined
export const num = (v: Numeric, d = 0) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '–' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d }))
export const pct = (v: Numeric, d = 0) => (v === null || v === undefined ? '–' : `${(Number(v) * 100).toFixed(d)}%`)
export const compact = (x: Numeric) => { if (x === null || x === undefined || Number.isNaN(Number(x))) return '–'; const v = Number(x); return Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : Math.abs(v) >= 1e4 ? `${(v / 1e3).toFixed(0)}k` : Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(1)}k` : `${Math.round(v)}` }
export const ymLabel = (ym: number) => `${MONTHS[(ym % 100) - 1]} ${Math.floor(ym / 100)}`
export const titleCase = (s?: string | null) => (s || '').toLowerCase().replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase())

/* ------------------------------------------------------------------ app context */
export type Meta = {
  has_data: boolean; states?: string[]; districts?: { id: string; name: string; state: string }[]; users: { username: string; display_name: string; role: string }[]
  spans?: Record<string, { first: string; last: string }>; data_end?: string; default_split?: number; forecast_available?: boolean; issue_dates?: string[]
  land_use_classes: string[]; satellites: string[]; auth_mode?: 'dev' | 'production'; anomaly_types?: Record<string, string>
}
type Ctx = { user: string; setUser: (u: string) => void; role: string; region: string; setRegion: (r: string) => void; meta: Meta | null; reloadMeta: () => void }
export const AppCtx = createContext<Ctx>(null as unknown as Ctx)
export const useApp = () => useContext(AppCtx)

let currentUser = localStorage.getItem('pyro_user') || 'analyst'
export const setApiUser = (u: string) => { currentUser = u; localStorage.setItem('pyro_user', u) }
export const getApiUser = () => currentUser
// Bearer session token (real authentication). Kept in sessionStorage so it ends with the browser session.
let authToken: string | null = sessionStorage.getItem('pyro_token')
export const getAuthToken = () => authToken
export const setAuthToken = (t: string | null) => { authToken = t; if (t) sessionStorage.setItem('pyro_token', t); else sessionStorage.removeItem('pyro_token') }
const authHeaders = (): Record<string, string> => (authToken ? { Authorization: `Bearer ${authToken}` } : { 'X-User': currentUser })

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = authHeaders()
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  const r = await fetch(path, { method: opts.method || (opts.body !== undefined || opts.form ? 'POST' : 'GET'), headers, body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined) })
  if (r.status === 401 && authToken && path !== '/api/auth/login') setAuthToken(null)   // expired / revoked session
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: { loc?: (string | number)[]; msg: string }) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ') : JSON.stringify(j) } catch { /* keep status text */ }
    throw new Error(msg)
  }
  return r.json()
}

export async function download(path: string, filename: string) {
  const r = await fetch(path, { headers: authHeaders() })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export function useApi<T = unknown>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const seq = useRef(0)
  const load = useCallback(() => {
    if (!path) { setData(null); return }
    const id = ++seq.current
    setLoading(true); setError(null)
    api<T>(path).then((d) => { if (id === seq.current) setData(d) }).catch((e) => { if (id === seq.current) { setError(e.message); setData(null) } }).finally(() => { if (id === seq.current) setLoading(false) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps])
  useEffect(load, [load])
  return { data, error, loading, reload: load }
}

/* ------------------------------------------------------------------ primitives */
const PROV: Record<string, { label: string; cls: string }> = {
  actual: { label: 'Actual Observation', cls: 'border-sky-500/50 text-sky-300 bg-sky-500/10' },
  mg: { label: 'Morning-Gap Corrected Estimate', cls: 'border-teal-500/50 text-teal-300 bg-teal-500/10' },
  veq: { label: 'VIIRS-Equivalent Harmonized Estimate', cls: 'border-amber-500/50 text-amber-300 bg-amber-500/10' },
  forecast: { label: 'Calibrated Model Forecast', cls: 'border-orange-500/50 text-orange-300 bg-orange-500/10' },
  simulated: { label: 'Simulated Notification', cls: 'border-fuchsia-500/50 text-fuchsia-300 bg-fuchsia-500/10' },
  experiment: { label: 'Hold-out Experiment (real data withheld)', cls: 'border-violet-500/50 text-violet-300 bg-violet-500/10' },
  aux: { label: 'Auxiliary Layer', cls: 'border-slate-500/50 text-slate-300 bg-slate-500/10' },
  proto: { label: 'Prototype Rule', cls: 'border-slate-500/50 text-slate-300 bg-slate-500/10' },
}
export function Prov({ kind, text }: { kind: keyof typeof PROV | string; text?: string }) {
  const p = PROV[kind] || PROV.aux
  return <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide whitespace-nowrap ${p.cls}`}>{text || p.label}</span>
}

export function Card({ title, sub, badges, right, children, className = '', pad = true }: { title?: ReactNode; sub?: ReactNode; badges?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`rounded-lg border border-line bg-ink-900 ${className}`}>
      {(title || right) && (
        <header className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-4 py-2.5">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-slate-100">{title}</h3>{badges}</div>
            {sub && <p className="mt-0.5 text-xs text-slate-400">{sub}</p>}
          </div>
          {right && <div className="flex items-center gap-2">{right}</div>}
        </header>
      )}
      <div className={pad ? 'p-4' : ''}>{children}</div>
    </section>
  )
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'good' | 'warn' | 'bad' }) {
  const t = tone === 'good' ? 'text-emerald-400' : tone === 'warn' ? 'text-amber-400' : tone === 'bad' ? 'text-red-400' : 'text-slate-50'
  return (
    <div className="rounded-lg border border-line bg-ink-900 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${t}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-400">{sub}</div>}
    </div>
  )
}

export const Note = ({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warn' | 'bad' }) => (
  <div className={`rounded border px-3 py-2 text-xs leading-relaxed ${tone === 'warn' ? 'border-amber-500/40 bg-amber-500/10 text-amber-100' : tone === 'bad' ? 'border-red-500/40 bg-red-500/10 text-red-100' : 'border-line bg-ink-800 text-slate-300'}`}>{children}</div>
)

export function State({ loading, error, empty, children }: { loading?: boolean; error?: string | null; empty?: boolean; children?: ReactNode }) {
  if (error) return <Note tone="bad">Could not load: {error}</Note>
  if (loading && empty !== false) return <div className="animate-pulse py-10 text-center text-sm text-slate-500">Loading…</div>
  if (empty) return <div className="py-8 text-center text-sm text-slate-500">No data.</div>
  return <>{children}</>
}

export function Btn({ children, onClick, kind = 'default', disabled, title, small }: { children: ReactNode; onClick?: () => void; kind?: 'default' | 'primary' | 'danger' | 'ghost'; disabled?: boolean; title?: string; small?: boolean }) {
  const k = kind === 'primary' ? 'bg-orange-600 hover:bg-orange-500 text-white border-orange-500' : kind === 'danger' ? 'bg-red-700/80 hover:bg-red-600 text-white border-red-500' : kind === 'ghost' ? 'border-transparent text-slate-300 hover:bg-ink-700' : 'bg-ink-700 hover:bg-ink-600 text-slate-100 border-line'
  return <button title={title} disabled={disabled} onClick={onClick} className={`rounded border ${small ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm'} font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${k}`}>{children}</button>
}

export const TierPill = ({ tier }: { tier?: string | null }) => {
  const t = tier || 'UNKNOWN'
  return <span className="inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[11px] font-semibold" style={{ background: `${TIER_COLOR[t] || '#64748b'}22`, color: '#f1f5f9', border: `1px solid ${TIER_COLOR[t] || '#64748b'}` }}><i className="h-2 w-2 rounded-full" style={{ background: TIER_COLOR[t] || '#64748b' }} />{titleCase(t)}</span>
}

const STATUS_TONE: Record<string, string> = { good: 'border-emerald-500 text-emerald-300', moderate: 'border-amber-500 text-amber-300', poor: 'border-red-500 text-red-300', insufficient_data: 'border-slate-500 text-slate-300' }
export const StatusPill = ({ status }: { status?: string }) => <span className={`rounded border px-2 py-0.5 text-xs font-semibold uppercase ${STATUS_TONE[status || ''] || 'border-slate-500 text-slate-300'}`}>{titleCase(status) || 'n/a'}</span>

export function Page({ title, intro, children, actions }: { title: string; intro?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mx-auto max-w-[1500px] space-y-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0 max-w-4xl"><h1 className="text-xl font-semibold text-white">{title}</h1>{intro && <p className="mt-1 text-sm text-slate-400">{intro}</p>}</div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}

/* ------------------------------------------------------------------ region picker (shared, global) */
export function RegionPicker({ allowCustom = true }: { allowCustom?: boolean }) {
  const { region, setRegion, meta } = useApp()
  const kind = region.split(':')[0]
  const [box, setBox] = useState(kind === 'bbox' ? region.slice(5) : '74,29,77,32')
  const stateOfDistrict = kind === 'district' ? meta?.districts?.find((d) => d.id === region.slice(9))?.state : undefined
  const [dState, setDState] = useState(stateOfDistrict || meta?.states?.[0] || '')
  useEffect(() => { if (stateOfDistrict) setDState(stateOfDistrict) }, [stateOfDistrict])
  const districts = (meta?.districts || []).filter((d) => d.state === dState)
  const boxOk = (() => { const p = box.split(',').map(Number); return p.length === 4 && p.every((x) => Number.isFinite(x)) && p[2] > p[0] && p[3] > p[1] })()
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-xs uppercase tracking-wide text-slate-400">Area</span>
      <select value={kind} aria-label="Area type" onChange={(e) => {
        const k = e.target.value
        if (k === 'country') setRegion('country')
        else if (k === 'state') setRegion(`state:${meta?.states?.[0]}`)
        else if (k === 'district') { const d = (meta?.districts || []).find((x) => x.state === dState) || meta?.districts?.[0]; if (d) setRegion(`district:${d.id}`) }
        else if (k === 'bbox' && boxOk) setRegion(`bbox:${box}`)
      }}>
        <option value="country">Country (India)</option><option value="state">State</option><option value="district">District</option>
        {allowCustom && <option value="bbox">Custom box</option>}
        {kind === 'cell' && <option value="cell">Grid cell</option>}
      </select>
      {kind === 'state' && <select aria-label="State" value={region.slice(6)} onChange={(e) => setRegion(`state:${e.target.value}`)}>{meta?.states?.map((s) => <option key={s}>{s}</option>)}</select>}
      {kind === 'district' && <>
        <select aria-label="State of district" value={dState} onChange={(e) => { setDState(e.target.value); const d = (meta?.districts || []).find((x) => x.state === e.target.value); if (d) setRegion(`district:${d.id}`) }}>{meta?.states?.map((s) => <option key={s}>{s}</option>)}</select>
        <select aria-label="District" value={region.slice(9)} onChange={(e) => setRegion(`district:${e.target.value}`)}>{districts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
      </>}
      {kind === 'bbox' && <>
        <input aria-label="West,South,East,North" className="w-44 font-mono text-xs" value={box} onChange={(e) => setBox(e.target.value)} placeholder="W,S,E,N" />
        <Btn small disabled={!boxOk} onClick={() => setRegion(`bbox:${box}`)}>Apply</Btn>
        <span className="text-xs text-slate-500">or draw on the Live Fire Map</span>
      </>}
    </div>
  )
}

export function regionName(region: string, meta: Meta | null) {
  const [k, v] = [region.split(':')[0], region.slice(region.indexOf(':') + 1)]
  if (k === 'country') return 'India'
  if (k === 'state') return v
  if (k === 'district') { const d = meta?.districts?.find((x) => x.id === v); return d ? `${d.name}, ${d.state}` : v }
  if (k === 'bbox') return `Custom area (${v})`
  return region
}

export function Tabs<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[] }) {
  return <div className="inline-flex rounded border border-line bg-ink-800 p-0.5">{options.map((o) => <button key={o.value} onClick={() => onChange(o.value)} className={`rounded px-2.5 py-1 text-xs font-medium ${value === o.value ? 'bg-orange-600 text-white' : 'text-slate-300 hover:bg-ink-700'}`}>{o.label}</button>)}</div>
}

export function SplitPicker({ value, onChange, allowOperational = false }: { value: number | null; onChange: (v: number | null) => void; allowOperational?: boolean }) {
  const { meta } = useApp()
  const first = Number((meta?.spans?.['Suomi NPP']?.first || '2012').slice(0, 4))
  const years = Array.from({ length: 8 }, (_, i) => first + 3 + i)
  return (
    <label className="flex items-center gap-2 text-xs text-slate-400">Train only from
      <select value={value ?? ''} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        {allowOperational && <option value="">all overlap years (operational)</option>}
        {years.map((y) => <option key={y} value={y * 100 + 1}>Jan {y} onward</option>)}
      </select>
    </label>
  )
}
