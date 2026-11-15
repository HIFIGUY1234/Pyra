/* Processed-dataset readiness: the Calendar's waiting state and the Data Management step guide.
 * Everything shown comes from GET /api/data/readiness. Administrator-only actions are rendered only for admins,
 * so no user is offered a control that can only answer 403. Missing data is never presented as zero activity. */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Database, RefreshCw, Wrench } from 'lucide-react'
import { api, useApi, useApp, DATASET_NOT_READY_MSG } from './lib'
import { Banner, Button, Card, CardBody, CardHeader } from './ui'

export type ReadinessFile = { file: string; status: string; bytes?: number | null; rows?: number | null; detail?: string | null }
export type Readiness = {
  status: 'READY' | 'PARTIAL' | 'MISSING' | 'CORRUPT' | 'LFS_NOT_RECOVERED' | 'PROCESSING' | 'FAILED'
  dataset_status: string; ready: boolean; can_administer: boolean
  required: ReadinessFile[]; missing: string[]; processed_files: number
  coverage: Record<string, { first: string; last: string; detections?: number; gap_days?: number }>
  satellites: string[]
  registry: { status: string; sources: number; without_aggregate: string[] }
  aggregates: number; hotspot_partitions: number
  calibration: Record<string, boolean>; forecast: Record<string, boolean>
  archives: { total: number; valid: number; lfs_pointers: number; corrupt: number; uploads: number; ingestable: boolean
    items: { file: string; status: string; message?: string | null; expected_bytes?: number | null; bytes?: number | null }[] }
  lfs: { pointers: number; recovered: boolean; message: string | null }
  job: { state?: string; step?: string; started?: string; finished?: string; error?: string; mode?: string; log_tail: string[] }
  seed: { state: string; detail?: string | null; at?: string | null }
  manifest: { created_at?: string; provenance?: string; processing_version?: string; installed_at?: string } | null
  last_success: string | null
  next_action: { code: string; message: string; command?: string; endpoint?: string; admin_only?: boolean }
}

export const READINESS_LABEL: Record<string, string> = {
  READY: 'Processed dataset ready',
  PARTIAL: 'Processed dataset incomplete',
  MISSING: 'Processed dataset not installed',
  CORRUPT: 'Processed dataset corrupt',
  LFS_NOT_RECOVERED: 'Git LFS content not downloaded',
  PROCESSING: 'Dataset job running',
  FAILED: 'Dataset processing failed',
}
const TONE: Record<string, 'info' | 'warning' | 'danger' | 'success'> = {
  READY: 'success', PROCESSING: 'info', PARTIAL: 'warning', MISSING: 'warning', LFS_NOT_RECOVERED: 'warning', CORRUPT: 'danger', FAILED: 'danger',
}
const mb = (b?: number | null) => (b ? `${(b / 1e6).toFixed(1)} MB` : '–')
const when = (t?: string | null) => (t ? new Date(t).toLocaleString() : '–')

/** Readiness with polling while a job / seed install runs; calls onReady once the dataset turns READY. */
export function useReadiness(onReady?: () => void) {
  const r = useApi<Readiness>('/api/data/readiness')
  const { reloadMeta } = useApp()
  const prev = useRef<string | null>(null)
  const { reload } = r
  const status = r.data?.status
  useEffect(() => {
    if (status !== 'PROCESSING') return
    const t = setInterval(reload, 3000)
    return () => clearInterval(t)
  }, [status, reload])
  useEffect(() => {
    if (status === 'READY' && prev.current && prev.current !== 'READY') { reloadMeta(); onReady?.() }
    if (status) prev.current = status
  }, [status]) // eslint-disable-line react-hooks/exhaustive-deps
  return r
}

/** Admin-only dataset actions. Returns null for every other role. */
function AdminActions({ rd, onStarted }: { rd: Readiness; onStarted: () => void }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'danger' | 'success' | 'info'; text: string } | null>(null)
  if (!rd.can_administer) return null
  const run = async (path: string, label: string) => {
    setBusy(true); setMsg(null)
    try {
      const res = await api<{ ok?: boolean; failed?: string[]; next?: string; mode?: string }>(path, { method: 'POST', body: {} })
      if (res.ok === false) setMsg({ tone: 'danger', text: `${label}: recovery incomplete (${(res.failed || []).join(', ') || 'no archives'}). ${res.next || ''}` })
      else setMsg({ tone: 'success', text: res.mode === 'validate' ? 'Validating the existing processed dataset (no rebuild)…' : `${label} started.` })
      onStarted()
    } catch (e) { setMsg({ tone: 'danger', text: e instanceof Error ? e.message : String(e) }) } finally { setBusy(false) }
  }
  const code = rd.next_action.code
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {(code === 'recover_lfs' || rd.lfs.pointers > 0) && (
          <Button size="sm" variant="warning" disabled={busy || rd.status === 'PROCESSING'} onClick={() => run('/api/data/recover-lfs', 'Recover Git LFS archives')}>
            <Wrench className="h-3.5 w-3.5" />Recover Git LFS archives
          </Button>
        )}
        {(code === 'load_repo' || rd.ready || rd.archives.ingestable) && (
          <Button size="sm" variant="primary" disabled={busy || rd.status === 'PROCESSING'} onClick={() => run('/api/data/load-repo', 'Load Repository Dataset')}>
            <Database className="h-3.5 w-3.5" />Load Repository Dataset
          </Button>
        )}
      </div>
      {msg && <Banner tone={msg.tone}>{msg.text}</Banner>}
    </div>
  )
}

function JobBox({ rd }: { rd: Readiness }) {
  const j = rd.job
  if (!j.state || j.state === 'idle') return rd.seed.state === 'installing' || rd.seed.state === 'checking'
    ? <div className="rounded border border-[#22324b] bg-[#0f1726] p-3 text-xs text-slate-300">Installing the bundled processed dataset: {rd.seed.detail || 'checking'}…</div>
    : null
  return (
    <div className="space-y-1 rounded border border-[#22324b] bg-[#0f1726] p-3 text-xs" data-testid="dataset-job">
      <div className="text-slate-300">Job <strong className="uppercase text-white">{j.state}</strong>{j.mode ? ` (${j.mode === 'validate' ? 'validate existing dataset' : 'full rebuild'})` : ''}
        {j.step && <> · stage: <strong className="text-white">{j.step}</strong></>} · started {when(j.started)}{j.finished ? ` · finished ${when(j.finished)}` : ''}</div>
      {j.error && <div className="font-mono text-red-300">{j.error}</div>}
      {j.log_tail?.length > 0 && <div className="max-h-24 overflow-y-auto rounded bg-[#080d17] p-2 font-mono text-[11px] text-slate-400">{j.log_tail.map((l, i) => <div key={i}>{l.slice(0, 300)}</div>)}</div>}
      {j.state === 'failed' && <div className="text-slate-400">Any previously valid processed dataset was left in place. {rd.can_administer ? 'Fix the cause shown above and start the job again.' : ''}</div>}
    </div>
  )
}

/** Shown by data pages (e.g. the Calendar) when the API answers 409 / is unreachable. */
export function DatasetWaiting({ what, onRetry }: { what: string; onRetry?: () => void }) {
  const navigate = useNavigate()
  const { reloadMeta } = useApp()
  const retry = onRetry || reloadMeta
  const r = useReadiness(onRetry)
  const health = useApi<{ database: { ok: boolean }; data: { status: string; seed?: string }; build?: { commit: string | null; image: string } }>('/api/health')
  const rd = r.data
  const offline = r.errorStatus === 0 || health.errorStatus === 0
  return (
    <Card>
      <CardHeader title={`${what} is waiting for a processed satellite dataset.`}
        subtitle="Nothing is drawn until real processed observations are available: a missing dataset is never shown as zero fire activity." />
      <CardBody className="text-xs text-slate-300"><div className="space-y-3" data-testid="dataset-waiting">
        {offline && <Banner tone="danger" title="Backend unreachable">The PyroScope API did not respond. Check that the backend service is running, then retry.</Banner>}
        {r.error && !offline && <Banner tone="danger" title="Readiness unavailable">{r.error}</Banner>}
        {!offline && <div><div className="font-semibold text-slate-100">{DATASET_NOT_READY_MSG}</div>
          <div className="text-slate-400">The frontend is connected, but the backend has not made its processed scientific dataset available.</div></div>}
        {health.data && <div className="flex flex-wrap gap-x-4 gap-y-1 rounded border border-[#22324b] bg-[#0f1726] px-3 py-2" data-testid="backend-status">
          <span>Backend: <strong className="text-emerald-300">connected</strong></span>
          <span>Database: <strong className={health.data.database.ok ? 'text-emerald-300' : 'text-red-300'}>{health.data.database.ok ? 'connected' : 'unavailable'}</strong></span>
          <span>Processed dataset: <strong className="text-amber-300">{READINESS_LABEL[health.data.data.status] || health.data.data.status}</strong></span>
          {rd && <span>Dataset installation: <strong>{rd.seed.state.replace(/_/g, ' ')}</strong>{rd.manifest?.installed_at ? ` (last ${when(rd.manifest.installed_at)})` : ''}</span>}
          {health.data.build && <span>Backend build: <code>{health.data.build.image}{health.data.build.commit ? ` @ ${health.data.build.commit.slice(0, 7)}` : ''}</code></span>}
        </div>}
        {rd && <>
          <Banner tone={TONE[rd.status] || 'info'} title={READINESS_LABEL[rd.status] || rd.status}>{rd.next_action.message}
            {rd.next_action.command && rd.can_administer && <> Server command: <code>{rd.next_action.command}</code>.</>}</Banner>
          <ul className="list-disc space-y-0.5 pl-5">
            <li>Processed summaries: {rd.missing.length ? `missing ${rd.missing.join(', ')}` : rd.required.every((f) => f.status === 'ok') ? 'present and valid' : `problems: ${rd.required.filter((f) => f.status !== 'ok').map((f) => `${f.file} (${f.status.replace(/_/g, ' ')})`).join(', ')}`}</li>
            <li>Repository archives: {rd.archives.total === 0 ? 'none available to this backend' : `${rd.archives.valid} valid, ${rd.archives.lfs_pointers} Git LFS pointer(s), ${rd.archives.corrupt} corrupt`}{rd.lfs.message ? ` - ${rd.lfs.message}` : ''}</li>
            <li>Processing job: {rd.status === 'PROCESSING' ? 'running (this panel refreshes every 3 s)' : rd.job.state && rd.job.state !== 'idle' ? rd.job.state : 'none running'}</li>
            {rd.seed.detail && <li>Dataset installation detail: {rd.seed.detail}</li>}
            <li>Your access: {rd.can_administer ? 'administrator - you can run the dataset actions below.' : 'Dataset administration requires an authorised administrator.'}</li>
          </ul>
          <JobBox rd={rd} />
          <AdminActions rd={rd} onStarted={r.reload} />
        </>}
        <div className="flex flex-wrap gap-2 pt-1">
          <Button size="sm" variant="secondary" onClick={r.reload}><RefreshCw className="h-3.5 w-3.5" />Check Data Readiness</Button>
          <Button size="sm" variant="outline" onClick={() => navigate('/data')}>Open Data Management</Button>
          <Button size="sm" variant="outline" onClick={() => { retry(); r.reload(); health.reload() }}>Retry {what}</Button>
        </div>
      </div></CardBody>
    </Card>
  )
}

/** Data Management: the seven-step dataset sequence, driven by readiness. */
export function DatasetSteps({ onChanged }: { onChanged?: () => void }) {
  const r = useReadiness(onChanged)
  const rd = r.data
  const step = (n: number, title: string, state: 'ok' | 'warn' | 'bad' | 'na', body: ReactNode) => (
    <li key={n} className="flex gap-3 border-t border-[#22324b] py-2 first:border-t-0">
      <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${state === 'ok' ? 'bg-emerald-500/20 text-emerald-300' : state === 'bad' ? 'bg-red-500/20 text-red-300' : state === 'warn' ? 'bg-amber-500/20 text-amber-300' : 'bg-slate-500/20 text-slate-300'}`}>{n}</span>
      <div className="min-w-0"><div className="font-semibold text-slate-100">{title}</div><div className="text-slate-400">{body}</div></div>
    </li>
  )
  return (
    <Card>
      <CardHeader title="Dataset readiness" subtitle="Archives → Git LFS → recovery → validation → load → monitor → verify. Source: GET /api/data/readiness"
        actions={<Button size="xs" variant="secondary" onClick={r.reload}><RefreshCw className="h-3 w-3" />Re-check</Button>} />
      <CardBody className="text-xs"><div className="space-y-3" data-testid="dataset-steps">
        {r.error && <Banner tone="danger" title={r.errorStatus === 0 ? 'Backend unreachable' : 'Readiness unavailable'}>{r.error}</Banner>}
        {rd && <>
          <ol>
            {step(1, 'Check repository archives', rd.archives.total ? (rd.archives.valid === rd.archives.total ? 'ok' : 'warn') : 'na',
              rd.archives.total ? <table className="mt-1 w-full text-left"><tbody>{rd.archives.items.map((a) => (
                <tr key={a.file}><td className="pr-3 font-mono">{a.file}</td><td className={a.status === 'valid' ? 'text-emerald-300' : 'text-amber-300'}>{a.status.replace(/_/g, ' ')}</td>
                  <td className="pl-3">actual {mb(a.bytes)}{a.expected_bytes ? ` / expected ${mb(a.expected_bytes)}` : ''}</td><td className="pl-3">{a.message || ''}</td></tr>))}</tbody></table>
                : 'No FIRMS archives on this backend (expected on a deployed API that ships the processed dataset instead).')}
            {step(2, 'Check Git LFS status', rd.lfs.pointers ? 'warn' : 'ok', rd.lfs.pointers ? `${rd.lfs.pointers} archive(s) are Git LFS pointers. Git LFS archives have not been downloaded.` : 'No LFS pointer stubs.')}
            {step(3, 'Recover missing archive files', rd.lfs.pointers ? 'warn' : 'na', rd.lfs.pointers
              ? (rd.can_administer ? <>Run <code>git lfs pull</code> on the server or use “Recover Git LFS archives” (SHA-256 verified). Needed only to rebuild from raw archives.</> : 'Dataset administration requires an authorised administrator.')
              : 'Not needed.')}
            {step(4, 'Validate processed datasets', rd.ready ? 'ok' : rd.dataset_status === 'CORRUPT' ? 'bad' : 'warn',
              <>{READINESS_LABEL[rd.dataset_status] || rd.dataset_status}. {rd.required.map((f) => `${f.file}: ${f.status.replace(/_/g, ' ')}${f.rows ? ` (${f.rows.toLocaleString()} rows)` : ''}`).join(' · ')}.
                {' '}Registry {rd.registry.status} ({rd.registry.sources} sources), {rd.aggregates} source aggregates, {rd.hotspot_partitions} hotspot partitions.</>)}
            {step(5, 'Load or process the repository dataset', rd.ready ? 'ok' : 'warn',
              rd.ready ? 'Not required: the processed dataset validates. “Load Repository Dataset” only re-validates and reloads it (tick “force full rebuild” below to re-ingest).'
                : rd.next_action.message)}
            {step(6, 'Monitor processing', rd.status === 'PROCESSING' ? 'warn' : rd.job.state === 'failed' ? 'bad' : 'na', rd.job.state && rd.job.state !== 'idle' || rd.seed.state === 'installing' ? <JobBox rd={rd} /> : 'No job running.')}
            {step(7, 'Verify final dataset readiness', rd.ready ? 'ok' : 'bad', rd.ready
              ? <>READY · {Object.entries(rd.coverage).map(([s, c]) => `${s} ${c.first} → ${c.last}`).join(' · ')}{rd.manifest ? ` · manifest ${rd.manifest.provenance}, created ${when(rd.manifest.created_at)}` : ''}</>
              : READINESS_LABEL[rd.status] || rd.status)}
          </ol>
          {rd.can_administer ? <AdminActions rd={rd} onStarted={r.reload} /> : <Banner tone="info">Dataset administration requires an authorised administrator.</Banner>}
        </>}
      </div></CardBody>
    </Card>
  )
}
