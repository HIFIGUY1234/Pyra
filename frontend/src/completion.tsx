/* Completion-stage UI: authentication, dataset inventory, geographic coverage,
 * notification delivery log and validation-kind labelling. All values come from the API. */
import { useState, type ReactNode } from 'react'
import { KeyRound, LogOut, RefreshCw, ShieldCheck } from 'lucide-react'
import { api, Card, getAuthToken, Note, num, setAuthToken, State, titleCase, useApi, useApp } from './lib'

/* ------------------------------------------------------------------ validation kind */
const KIND: Record<string, { label: string; cls: string; help: string }> = {
  actual_holdout: { label: 'Actual validation', cls: 'border-emerald-500/60 text-emerald-300 bg-emerald-500/10', help: 'Scored against real observations the model never saw.' },
  actual_seam: { label: 'Real 2012 seam', cls: 'border-emerald-500/60 text-emerald-300 bg-emerald-500/10', help: 'Uses real MODIS records preceding the first VIIRS month.' },
  simulated_seam: { label: 'Simulated seam', cls: 'border-violet-500/60 text-violet-300 bg-violet-500/10', help: 'Real VIIRS before the split was withheld and used only as the answer key.' },
  simulated_withheld_experiment: { label: 'Simulated experiment', cls: 'border-violet-500/60 text-violet-300 bg-violet-500/10', help: 'Real Aqua months hidden to imitate the Terra-only era.' },
  insufficient_calibration: { label: 'Insufficient calibration', cls: 'border-amber-500/60 text-amber-300 bg-amber-500/10', help: 'Too few overlapping years or test months.' },
  unavailable: { label: 'Unavailable', cls: 'border-slate-500/60 text-slate-300 bg-slate-500/10', help: 'The data needed for this test are not loaded.' },
  real_correction: { label: 'Real Terra-only correction', cls: 'border-emerald-500/60 text-emerald-300 bg-emerald-500/10', help: 'Applied to loaded Terra-only months.' },
  simulated_only: { label: 'Simulated only', cls: 'border-violet-500/60 text-violet-300 bg-violet-500/10', help: 'No Terra-only months (Nov 2000 - Jun 2002) are loaded.' },
}
export function KindBadge({ kind }: { kind?: string | null }) {
  const k = KIND[kind || 'unavailable'] || KIND.unavailable
  return <span title={k.help} className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${k.cls}`}>{k.label}</span>
}

export function ValidationMethod({ v, seam }: { v: any; seam?: any }) {
  if (!v) return null
  const dn = v.by_daynight || {}
  return (
    <Card title="Validation methodology" badges={<><KindBadge kind={v.validation_kind} /><KindBadge kind={v.morning_gap?.validation_kind} />{seam && <KindBadge kind={seam.validation_kind} />}</>}
      sub={v.reference_product ? `Calibration target: ${v.reference_product}` : undefined}>
      <ul className="list-disc space-y-1 pl-5 text-xs text-slate-300">
        {v.methodology && <><li>{v.methodology.sensor_stage}</li><li>{v.methodology.morning_gap_stage}</li><li>{v.methodology.interval}</li>
          <li>Compared against: {v.methodology.baselines?.join(' · ')}</li></>}
      </ul>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {(['day', 'night'] as const).map((k) => (
          <div key={k} className="rounded border border-line px-3 py-2 text-xs">
            <div className="font-semibold uppercase text-slate-400">{k}-time detections</div>
            <div className="mt-1 text-slate-200">WAPE {num(dn[k]?.wape_pct, 1)}% · bias {num(dn[k]?.bias_pct, 1)}% · {dn[k]?.n ?? '–'} months</div>
          </div>
        ))}
      </div>
      {seam?.genuine_change && (
        <Note tone={seam.genuine_change.detectable ? 'info' : 'warn'}>
          Seam: harmonized step band {num(seam.step_harmonized_band?.[0], 2)}–{num(seam.step_harmonized_band?.[1], 2)}; reference step {num(seam.genuine_change.reference_step, 2)}.
          Genuine change {seam.genuine_change.detectable ? `remains detectable (${seam.genuine_change.direction})` : 'not distinguishable from no change'}. {seam.genuine_change.note}
        </Note>
      )}
    </Card>
  )
}

/* ------------------------------------------------------------------ authentication */
export function AuthControl({ onChange }: { onChange: () => void }) {
  const { meta } = useApp()
  const [open, setOpen] = useState(false)
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const me = useApi<any>('/api/auth/me', [getAuthToken()])
  const token = getAuthToken()
  const login = async () => {
    setErr(null)
    try {
      const r = await api<any>('/api/auth/login', { body: { username: u, password: p } })
      setAuthToken(r.token); setP(''); setOpen(false); onChange(); me.reload()
    } catch (e: any) { setErr(e.message) }
  }
  const logout = async () => {
    try { await api('/api/auth/logout', { method: 'POST' }) } catch { /* session may already be gone */ }
    setAuthToken(null); onChange(); me.reload()
  }
  return (
    <div className="relative">
      {token ? (
        <button onClick={logout} className="flex items-center gap-1.5 rounded-lg border border-emerald-600/50 bg-[#0B0F19] px-2.5 py-1 text-xs text-emerald-300" title="Signed in with a session token. Click to log out.">
          <ShieldCheck className="h-3.5 w-3.5" />{me.data?.username || 'signed in'} ({me.data?.role || '…'})<LogOut className="h-3.5 w-3.5" />
        </button>
      ) : (
        <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 rounded-lg border border-[#26324a] bg-[#0B0F19] px-2.5 py-1 text-xs text-slate-200">
          <KeyRound className="h-3.5 w-3.5 text-orange-400" />Log in
        </button>
      )}
      {!token && meta && (meta as any).auth_mode === 'dev' && (
        <span className="ml-2 rounded border border-amber-500/50 px-1.5 py-0.5 text-[10px] uppercase text-amber-300" title="Demo personas use the X-User header; disabled when PYROSCOPE_AUTH_MODE=production.">dev persona</span>
      )}
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-72 rounded-lg border border-line bg-ink-900 p-3 shadow-xl">
          <div className="mb-2 text-xs font-semibold text-slate-200">Sign in</div>
          <input aria-label="Username" className="mb-2 w-full rounded border border-line bg-[#0B0F19] px-2 py-1 text-xs" placeholder="username" value={u} onChange={(e) => setU(e.target.value)} />
          <input aria-label="Password" type="password" className="mb-2 w-full rounded border border-line bg-[#0B0F19] px-2 py-1 text-xs" placeholder="password" value={p}
            onChange={(e) => setP(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && login()} />
          {err && <div className="mb-2 text-xs text-red-400">{err}</div>}
          <button onClick={login} className="w-full rounded bg-orange-600 px-2 py-1 text-xs font-semibold text-white">Log in</button>
          <p className="mt-2 text-[10px] text-slate-500">Accounts are created by an administrator (POST /api/users). Passwords are stored as PBKDF2 hashes; sessions expire.</p>
        </div>
      )}
    </div>
  )
}

export function LoginGate({ children }: { children: ReactNode }) {
  const { meta } = useApp()
  if (meta && (meta as any).auth_mode === 'production' && !getAuthToken()) {
    return <Card title="Authentication required"><p className="text-sm text-slate-300">This deployment runs in production mode. Log in with the button in the top bar.</p></Card>
  }
  return <>{children}</>
}

/* ------------------------------------------------------------------ dataset inventory */
const ST: Record<string, string> = { valid: 'text-emerald-300', complete_from_firms_start: 'text-emerald-300', partial: 'text-amber-300', missing: 'text-red-300', lfs_pointer: 'text-red-300', corrupt: 'text-red-300' }

export function InventoryCard() {
  const { role } = useApp()
  const [refresh, setRefresh] = useState(0)
  const inv = useApi<any>(`/api/data/inventory${refresh ? '?refresh=true' : ''}`, [refresh])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const recover = async () => {
    setBusy(true); setMsg(null)
    try { const r = await api<any>('/api/data/recover-lfs', { method: 'POST' }); setMsg(r.results.map((x: any) => `${x.file}: ${x.status}`).join(' · ')); setRefresh((n) => n + 1) }
    catch (e: any) { setMsg(e.message) } finally { setBusy(false) }
  }
  const d = inv.data
  return (
    <Card title="Dataset inventory & ingestion report" sub="Archives, loaded coverage per satellite versus official FIRMS availability, missing periods and their consequences."
      right={<>
        <button onClick={() => setRefresh((n) => n + 1)} className="flex items-center gap-1 rounded border border-line px-2 py-1 text-xs"><RefreshCw className="h-3 w-3" />Refresh</button>
        {role === 'admin' && <button disabled={busy} onClick={recover} className="rounded border border-orange-600/60 px-2 py-1 text-xs text-orange-300">{busy ? 'Recovering…' : 'Recover Git LFS archives'}</button>}
      </>}>
      <State loading={inv.loading} error={inv.error} empty={!d}>
        {d && <div className="space-y-4 text-xs">
          {msg && <Note>{msg}</Note>}
          <table className="w-full text-left">
            <thead className="text-slate-400"><tr><th className="py-1">Archive</th><th>Status</th><th>Collection</th><th>Size</th><th>SHA-256</th><th>Contents</th></tr></thead>
            <tbody>{d.archives.map((a: any) => (
              <tr key={a.file} className="border-t border-line"><td className="py-1 font-mono">{a.file}</td><td className={ST[a.status]}>{titleCase(a.status)}{a.integrity ? ` (${a.integrity.replace(/_/g, ' ')})` : ''}</td>
                <td>{a.instrument ? `${a.instrument} ${a.collection}` : '–'}</td><td>{a.bytes ? `${(a.bytes / 1e6).toFixed(1)} MB` : '–'}</td>
                <td className="font-mono" title={a.sha256 || a.expected_sha256}>{(a.sha256 || a.expected_sha256 || '–').slice(0, 12)}</td>
                <td>{(a.members || []).filter((m: any) => m.kind !== 'other').map((m: any) => `${m.kind} ${(m.bytes / 1e6).toFixed(0)} MB`).join(' · ') || a.message}</td></tr>))}</tbody>
          </table>
          <table className="w-full text-left">
            <thead className="text-slate-400"><tr><th className="py-1">Satellite</th><th>Status</th><th>Archive (science quality)</th><th>NRT (provisional)</th><th>Rows</th><th>Missing days</th><th>FIRMS from</th></tr></thead>
            <tbody>{Object.entries<any>(d.satellites).map(([s, e]) => (
              <tr key={s} className="border-t border-line align-top"><td className="py-1">{s}</td><td className={ST[e.status]}>{titleCase(e.status)}
                {e.pre_operational_records && <div className="text-amber-300" title={e.pre_operational_records.note}>pre-operational records from {e.pre_operational_records.first}</div>}</td>
                <td>{e.loaded?.archive ? `${e.loaded.archive.first} → ${e.loaded.archive.last}` : '–'}</td><td>{e.loaded?.nrt ? `${e.loaded.nrt.first} → ${e.loaded.nrt.last}` : '–'}</td>
                <td>{num(e.loaded?.rows)}</td>
                <td title={(e.gaps?.missing_periods || []).map((g: string[]) => `${g[0]} to ${g[1]}`).join(', ')}>{e.gaps ? `${num(e.gaps.missing_days)} (${e.gaps.missing_periods.length} periods)` : '–'}</td>
                <td>{e.expected.firms_start}</td></tr>))}</tbody>
          </table>
          {d.registry && <table className="w-full text-left">
            <thead className="text-slate-400"><tr><th className="py-1">Source</th><th>Kind</th><th>Rows kept</th><th>Row versions</th><th>Quality</th><th>Dropped (coord / time)</th><th>Duplicates</th></tr></thead>
            <tbody>{Object.entries<any>(d.registry).map(([k, r]) => (
              <tr key={k} className="border-t border-line"><td className="py-1 font-mono">{k}</td><td>{r.kind === 'nrt' ? 'NRT (provisional)' : 'archive'}</td><td>{num(r.rows_kept)}</td>
                <td>{(r.collection?.row_versions || []).map((v: any) => <span key={v.version} title={v.meaning} className={v.status === 'undocumented' || v.status === 'unknown' ? 'text-amber-300' : ''}>{v.version} ({v.status}) </span>)}</td>
                <td className={r.quality_status === 'good' ? 'text-emerald-300' : 'text-amber-300'}>{r.quality_status || '–'}</td>
                <td>{num(r.quality?.dropped_invalid_coordinates)} / {num(r.quality?.dropped_invalid_timestamp)}</td><td>{num(r.quality?.duplicates_removed)}</td></tr>))}</tbody>
          </table>}
          <div className="grid gap-2 sm:grid-cols-2">
            {Object.entries<any>(d.capabilities).map(([k, v]) => (
              <div key={k} className="rounded border border-line px-2 py-1"><span className="text-slate-400">{titleCase(k)}:</span>{' '}
                <span className={String(v).startsWith('blocked') || v === false || v === 'missing' || v === 'unavailable' ? 'text-amber-300' : 'text-emerald-300'}>{String(v)}</span></div>))}
          </div>
          {d.missing?.length > 0 && <Note tone="warn"><strong>Missing data (not replaced by synthetic records):</strong>
            <ul className="mt-1 list-disc pl-5">{d.missing.map((m: any) => <li key={m.satellite + m.period}><strong>{m.satellite}</strong> {m.period} — {m.how}</li>)}</ul></Note>}
          <Note>VIIRS 750 m: {d.viirs_750m?.facts?.join(' ')} {d.viirs_750m?.how_to_add}</Note>
          <div className="text-slate-500">Generated {d.generated_at}</div>
        </div>}
      </State>
    </Card>
  )
}

/* ------------------------------------------------------------------ geography */
export function CoverageCard() {
  const g = useApi<any>('/api/geo/coverage')
  const d = g.data
  return (
    <Card title="Geographic coverage & data provenance" sub={d?.statement}>
      <State loading={g.loading} error={g.error} empty={!d}>
        {d && <div className="space-y-3 text-xs">
          <table className="w-full text-left">
            <thead className="text-slate-400"><tr><th className="py-1">Layer</th><th>Source</th><th>Resolution</th><th>Date</th><th>Licence</th><th>Coverage</th></tr></thead>
            <tbody>{d.datasets.map((x: any) => <tr key={x.layer} className="border-t border-line align-top"><td className="py-1">{x.layer}</td><td>{x.source}</td><td>{x.resolution}</td><td>{x.date}</td><td>{x.licence}</td><td>{x.coverage}</td></tr>)}</tbody>
          </table>
          <div><strong>Administrator jurisdiction layers:</strong> {d.jurisdiction_layers.length ? d.jurisdiction_layers.map((l: any) => `${l.name} → ${l.land_use} (${l.n_cells} cells; ${l.source})`).join(' · ') : 'none loaded (Industrial and Residential/Village are only assigned from such layers)'}</div>
          <div><strong>Exposure layers:</strong> {Object.entries<any>(d.exposure_layers).map(([k, v]) => `${k}: ${v.status}${v.source ? ` (${v.source})` : ''}`).join(' · ')}</div>
          <ul className="list-disc pl-5 text-slate-400">{d.land_use_rules.map((r: string) => <li key={r}>{r}</li>)}</ul>
        </div>}
      </State>
    </Card>
  )
}

/* ------------------------------------------------------------------ notifications */
export function NotificationLogCard() {
  const { role } = useApp()
  const allowed = role === 'admin' || role === 'gov_officer'
  const log = useApi<any>(allowed ? '/api/notifications/log?limit=100' : null)
  const st = useApi<any>('/api/notifications/status')
  return (
    <Card title="Notification delivery log" sub={st.data ? `Provider: ${st.data.provider}${st.data.external_delivery_enabled ? ' (external delivery enabled)' : ' — simulated, nothing leaves the application'}` : undefined}>
      {st.data && <ul className="mb-3 list-disc pl-5 text-xs text-slate-400">{st.data.rules.map((r: string) => <li key={r}>{r}</li>)}</ul>}
      {!allowed ? <p className="text-xs text-slate-400">Visible to government officers and administrators.</p> : (
        <State loading={log.loading} error={log.error} empty={!log.data?.items?.length}>
          <table className="w-full text-left text-xs">
            <thead className="text-slate-400"><tr><th className="py-1">When (UTC)</th><th>Alert</th><th>Provider</th><th>Status</th><th>Approved by</th><th>Error</th></tr></thead>
            <tbody>{(log.data?.items || []).map((x: any) => (
              <tr key={x.id} className="border-t border-line"><td className="py-1">{x.at.slice(0, 16).replace('T', ' ')}</td><td className="font-mono">{x.alert_id}</td>
                <td>{x.provider}{x.simulated ? ' (simulated)' : ''}</td><td className={x.status === 'SENT' || x.status === 'SIMULATED_DELIVERED' ? 'text-emerald-300' : x.status === 'FAILED' ? 'text-red-300' : 'text-amber-300'}>{titleCase(x.status)}</td>
                <td>{x.approved_by || '–'}</td><td className="text-red-300">{x.error || ''}</td></tr>))}</tbody>
          </table>
        </State>
      )}
    </Card>
  )
}
