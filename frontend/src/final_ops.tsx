/* Operational-transition, sensor, product, exposure, orbit and system-configuration screens.
 * Every value comes from the backend; unavailable data / credentials are shown as such, never filled in. */
import { useState, type ReactNode } from 'react'
import { api, Btn, Card, Note, num, pct, Prov, SAT_LABEL, State, titleCase, useApi, useApp } from './lib'
import { ExposurePanel, ForecastComparisonPanel, Noaa21Panel, OrbitPanel, Viirs750Panel } from './completion_final'
import { NotificationLogCard } from './completion'

/* ------------------------------------------------------------------ contracts */
type Checks = Record<string, boolean>
interface ModelSummary { model_version?: string | null; trained_at?: string | null; test_rows?: number; roc_auc?: number | null; brier_skill?: number | null; ece?: number | null; pr_auc?: number | null; brier?: number | null; split?: Record<string, string | null> | null }
interface PlatformEval {
  sensor: string; loaded: boolean; passes: boolean; checks: Checks
  platform: { status?: string; noaa_role?: string; firms_start?: string; science_data_end?: string; note?: string }
  coverage?: { first: string; last: string; science_quality_last: string; nrt_days: number; archive_months: number; operational_archive_months?: number; missing_days: number; missing_share: number; days_behind_newest: number; wall_clock_age_days: number }
  detections?: { total: number; presumed_vegetation: number; science_quality: number; per_year: Record<string, number> }
  confidence?: { low: number; nominal: number; high: number; high_share: number }
  day_night?: Record<string, number>
  seasonal_share?: Record<string, number>
  overlap?: Record<string, { from: string; to: string; months: number } | null>
  model?: ModelSummary | null
}
interface Bridge { target: string; reference: string; status: string; selected?: string | null; selection_reason?: string; reason?: string; overlap?: string[]; reference_per_target_ratio?: Record<string, number> }
interface OpSummary {
  historical_reference: { platform: string; status: string; science_data_end?: string; loaded_first?: string; loaded_last?: string; science_quality_last?: string; role: string; source?: string }
  operational_reference: string | null; selection_mode: string; operational_status: string; unavailable_reason?: string | null
  stored_admin_choice?: string | null; stored_choice_rejected?: boolean; candidates: PlatformEval[]; criteria: Record<string, string>
  default_rule: string; forecast_served: string; forecast_models: string[]; bridges: Bridge[]
}
interface Successor { status?: string; coverage?: { first: string; last: string; science_quality_last?: string }; window?: string[]; months_compared?: number
  raw_discontinuity?: { snpp_per_successor_ratio: number | null; abs_log_step: number | null; monthly_ratio_p05_p95: number[] | null }
  bridge?: { status?: string; selected?: string | null; reason?: string }; calibrated_discontinuity?: string | { state_month_wape_pct: number; bias_pct: number } }
interface Transition { historical_reference: string; science_data_end?: string; last_loaded_snpp?: string; last_science_quality_snpp?: string; successors: Record<string, Successor>; verdict: string; interpretation: string }
interface Metrics { n?: number; brier?: number; brier_skill?: number | null; roc_auc?: number | null; pr_auc?: number | null; ece?: number; precision?: number | null; recall?: number | null; specificity?: number | null; missed_event_rate?: number | null; false_positive_rate?: number | null; reliable?: boolean }
interface ServingStatus { status: string; message?: string | null; issue_date?: string | null; issue_age_days?: number | null }
interface ModelCardItem { reference_sensor: string; model_version?: string; trained_at?: string | null; target?: string; split?: Record<string, string | null>; rows?: Record<string, number>
  issue_date?: string; serving_status?: ServingStatus; evaluation?: Metrics; baseline_climatology?: number | null; breakdowns?: Record<string, Record<string, Metrics>> | null; nrt_in_labels?: boolean; legacy?: boolean }
interface RegionForecast { status: string; message?: string; region?: string; issue_date?: string; headline_probability?: number; max_cell_probability?: number; risk_category?: string; meaning?: string
  regional?: { p_any_lower?: number; p_any_upper?: number }; reference?: { reference_sensor?: string; model_version?: string; serving_status?: ServingStatus } }
interface Issue { level: 'error' | 'warning'; key: string; message: string }
interface ConfigView { mode: string; ok: boolean; errors: number; warnings: number; issues: Issue[]; x_user_header_trusted: boolean }
interface CredItem { integration: string; variables: string[]; status: string; needed_for: string }
interface Job { id: number; kind: string; description?: string; status: string; progress?: { message?: string } | null; error?: string | null; requested_by?: string; created_at?: string; finished_at?: string | null; cancel_requested?: boolean }
interface Step { step: string; done: boolean | null }
interface LinearStatus { status: string; how?: string; licence?: string; source?: string; national_coverage?: string; url?: string; download_date?: string | null; processed_at?: string
  categories?: Record<string, { status: string; features?: number; total_length_km?: number | null; geometry_type?: string }>; known_gaps?: string[]; coverage?: string }
interface Nearest { category: string; status: string; distance_km?: number; name?: string | null; class?: string | null; max_km?: number; reason?: string }
interface Creds750 { configured: boolean; state: string; method: string | null; last_success?: string | null; last_error?: string | null; how: string }
interface Granule { granule: string; daynight?: string | null; size_bytes_approx?: number | null; url?: string | null }
interface Search750 { status: string; error?: string; count?: number; granules: Granule[]; truncated?: boolean }
interface Weights { active: { profile: string; version: string; weights: Record<string, number>; set_by?: string; set_at?: string }; profiles: Record<string, Record<string, number>>; labels: Record<string, string> }
interface Sensitivity { status: string; sensitivity?: { profiles: Record<string, { spearman_vs_active: number; top_overlap: number }>; min_top_overlap_under_20pct_perturbation: number | null }
  historical_alignment?: Record<string, { issues: number; mean_spearman: number | null; mean_top_hit_rate: number | null }>; historical_alignment_sensor?: string; interpretation?: string; not_available?: string[] }

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
const yes = (b: boolean | null | undefined) => (b == null ? <span className="text-slate-400">manual</span> : b ? <span className="text-emerald-300">pass</span> : <span className="text-red-300">fail</span>)
const Head = ({ title, intro, children }: { title: string; intro: ReactNode; children?: ReactNode }) => (
  <header className="mb-4"><h1 className="text-xl font-semibold text-white">{title}</h1><p className="mt-1 max-w-4xl text-sm text-slate-400">{intro}</p>{children}</header>
)
const Th = ({ children }: { children: ReactNode }) => <th className="px-2 py-1 text-left font-medium text-slate-400">{children}</th>
const Tc = ({ children, right }: { children: ReactNode; right?: boolean }) => <td className={`border-t border-line px-2 py-1 ${right ? 'text-right font-mono' : ''}`}>{children}</td>
const StatusTag = ({ s }: { s: string }) => {
  const cls = /^(APPROVED|CONFIGURED|CURRENT|DONE|loaded|built|calibrated|found|ok)$/i.test(s) ? 'border-emerald-500/60 text-emerald-300'
    : /^(UNAVAILABLE|NOT_CONFIGURED|not_built|unavailable|not_calibrated|PENDING|QUEUED|RUNNING|none_within)$/i.test(s) ? 'border-amber-500/60 text-amber-300'
      : 'border-red-500/60 text-red-300'
  return <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${cls}`}>{titleCase(s)}</span>
}

/* ------------------------------------------------------------------ operational reference */
export function ReferencePage() {
  const { role } = useApp()
  const s = useApi<OpSummary>('/api/reference/operational')
  const t = useApi<Transition>('/api/reference/transition')
  const [choice, setChoice] = useState('')
  const [reason, setReason] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const d = s.data
  const passing = (d?.candidates || []).filter((c) => c.passes).map((c) => c.sensor)
  const save = (platform: string | null) => api<OpSummary>('/api/reference/operational', { method: 'PUT', body: { platform, reason } })
    .then(() => { setMsg('Saved.'); s.reload() }).catch((e) => setMsg(errText(e)))
  return (
    <div className="space-y-4" data-testid="reference-page">
      <Head title="Historical & Operational Reference" intro="Suomi NPP stays the historical harmonization reference (its archive defines the VIIRS-equivalent scale). The live forecasting target is a separately validated operational platform chosen by declared evidence criteria." />
      <State loading={s.loading} error={s.error} empty={!d}>
        {d && <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Historical reference" badges={<StatusTag s={d.historical_reference.status} />} sub={d.historical_reference.role}>
              <dl className="grid grid-cols-2 gap-1 text-xs">
                <dt className="text-slate-400">Platform</dt><dd>{d.historical_reference.platform}</dd>
                <dt className="text-slate-400">Science-data delivery ended</dt><dd>{d.historical_reference.science_data_end || '–'}</dd>
                <dt className="text-slate-400">Loaded record</dt><dd>{d.historical_reference.loaded_first} → {d.historical_reference.loaded_last}</dd>
                <dt className="text-slate-400">Last science-quality day</dt><dd>{d.historical_reference.science_quality_last || '–'}</dd>
              </dl>
              {d.historical_reference.source && <p className="mt-2 text-[11px] text-slate-500">{d.historical_reference.source}</p>}
            </Card>
            <Card title="Operational reference" badges={<StatusTag s={d.operational_status} />} sub={d.default_rule}>
              <p className="text-sm">{d.operational_reference ? <><b>{d.operational_reference}</b> ({titleCase(d.selection_mode)})</> : <span className="text-amber-300">No approved operational reference</span>}</p>
              {d.unavailable_reason && <Note tone="warn">{d.unavailable_reason}</Note>}
              {d.stored_choice_rejected && <Note tone="warn">The stored administrator choice ({d.stored_admin_choice}) no longer meets the criteria and is not used.</Note>}
              <p className="mt-2 text-xs text-slate-400">Forecast served by default: <b>{d.forecast_served}</b>. Independent models: {d.forecast_models.join(', ') || 'none'}.</p>
              {role === 'admin' && passing.length > 0 && (
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <select aria-label="Operational platform" value={choice} onChange={(e) => setChoice(e.target.value)} className="rounded border border-line bg-[#080d17] px-2 py-1">
                    <option value="">Evidence default</option>{passing.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                  <input aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required)" className="min-w-[14rem] rounded border border-line bg-[#080d17] px-2 py-1" />
                  <Btn small kind="primary" disabled={reason.length < 5} onClick={() => save(choice || null)}>Save selection</Btn>
                  {msg && <span className="text-slate-300">{msg}</span>}
                </div>
              )}
            </Card>
          </div>
          <Card title="Candidate evaluation" sub="Each platform is evaluated on its own data and its own independently trained model. A failing candidate can never be selected.">
            <div className="overflow-x-auto"><table className="w-full text-xs">
              <thead><tr><Th>Criterion</Th>{d.candidates.map((c) => <Th key={c.sensor}>{c.sensor} {c.platform.noaa_role ? `(${c.platform.noaa_role})` : ''}</Th>)}</tr></thead>
              <tbody>
                {Object.entries(d.criteria).map(([k, label]) => <tr key={k}><Tc>{k} — {label}</Tc>{d.candidates.map((c) => <Tc key={c.sensor}>{yes(c.checks[k])}</Tc>)}</tr>)}
                <tr><Tc><b>Overall</b></Tc>{d.candidates.map((c) => <Tc key={c.sensor}>{c.passes ? <StatusTag s="APPROVED" /> : <StatusTag s="FAILED" />}</Tc>)}</tr>
              </tbody>
            </table></div>
          </Card>
          <Card title="Bridge calibrations (successor → reference scale)" sub="Adopted only if a candidate beats identity on both splits with |bias| ≤ 5 % and ≥ 80 % band coverage. The historical S-NPP-equivalent record is never altered.">
            <table className="w-full text-xs"><thead><tr><Th>Pair</Th><Th>Status</Th><Th>Overlap</Th><Th>Raw ratio (day / night)</Th><Th>Reason</Th></tr></thead>
              <tbody>{d.bridges.map((b) => <tr key={b.target + b.reference}><Tc>{b.target} → {b.reference}</Tc><Tc><StatusTag s={b.status} /></Tc><Tc>{b.overlap?.join(' → ') || '–'}</Tc>
                <Tc>{b.reference_per_target_ratio ? `${num(b.reference_per_target_ratio.D, 3)} / ${num(b.reference_per_target_ratio.N, 3)}` : '–'}</Tc><Tc><span className="text-[11px] text-slate-400">{(b.selection_reason || b.reason || '').slice(0, 260)}</span></Tc></tr>)}</tbody></table>
          </Card>
        </>}
      </State>
      <Card title="S-NPP → successor transition report" badges={t.data && <StatusTag s={t.data.verdict} />}>
        <State loading={t.loading} error={t.error} empty={!t.data}>
          {t.data && <>
            <p className="mb-2 text-xs text-slate-400">S-NPP science data ended {t.data.science_data_end}; last science-quality S-NPP day loaded: {t.data.last_science_quality_snpp}.</p>
            <table className="w-full text-xs"><thead><tr><Th>Successor</Th><Th>Coverage</Th><Th>Window</Th><Th>Raw S-NPP / successor</Th><Th>Monthly ratio p05–p95</Th><Th>Bridge</Th><Th>Calibrated discontinuity</Th></tr></thead>
              <tbody>{Object.entries(t.data.successors).map(([k, v]) => <tr key={k}><Tc>{k}</Tc><Tc>{v.coverage ? `${v.coverage.first} → ${v.coverage.last}` : '–'}</Tc><Tc>{v.window?.join(' → ') || '–'}</Tc>
                <Tc right>{num(v.raw_discontinuity?.snpp_per_successor_ratio, 3)}</Tc><Tc>{v.raw_discontinuity?.monthly_ratio_p05_p95?.map((x) => num(x, 3)).join(' – ') || '–'}</Tc>
                <Tc>{v.bridge?.status ? <StatusTag s={v.bridge.status} /> : '–'}</Tc><Tc><span className="text-[11px] text-slate-400">{typeof v.calibrated_discontinuity === 'string' ? v.calibrated_discontinuity : `WAPE ${num(v.calibrated_discontinuity?.state_month_wape_pct, 1)} %, bias ${num(v.calibrated_discontinuity?.bias_pct, 1)} %`}</span></Tc></tr>)}</tbody></table>
            <Note>{t.data.interpretation}</Note>
          </>}
        </State>
      </Card>
    </div>
  )
}

/* ------------------------------------------------------------------ per-sensor analysis */
export function SensorPage({ sensor }: { sensor: string }) {
  const e = useApi<PlatformEval>(`/api/reference/platform/${encodeURIComponent(sensor)}`)
  const models = useApi<{ items: ModelCardItem[] }>('/api/forecast/models')
  const card = models.data?.items.find((m) => m.reference_sensor === sensor)
  const d = e.data
  return (
    <div className="space-y-4" data-testid={`sensor-page-${sensor}`}>
      <Head title={`${SAT_LABEL[sensor] || sensor} analysis`} intro={`Actual ${sensor} observations, evaluated independently. Never pooled with another VIIRS platform.`}>
        <div className="mt-2 flex gap-2"><Prov kind="actual" /></div>
      </Head>
      <State loading={e.loading} error={e.error} empty={!d}>
        {d && !d.loaded && <Note tone="warn">{sensor} is not loaded.</Note>}
        {d && d.loaded && d.coverage && <>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Platform & coverage" badges={<StatusTag s={d.platform.status || 'unknown'} />}>
              <dl className="grid grid-cols-2 gap-1 text-xs">
                <dt className="text-slate-400">Loaded</dt><dd>{d.coverage.first} → {d.coverage.last}</dd>
                <dt className="text-slate-400">Science-quality to</dt><dd>{d.coverage.science_quality_last} ({d.coverage.nrt_days} NRT days after)</dd>
                <dt className="text-slate-400">Archive months</dt><dd>{num(d.coverage.archive_months, 1)}{d.coverage.operational_archive_months != null ? ` (operational ${num(d.coverage.operational_archive_months, 1)})` : ''}</dd>
                <dt className="text-slate-400">Missing days</dt><dd>{d.coverage.missing_days} ({pct(d.coverage.missing_share, 2)})</dd>
                <dt className="text-slate-400">Data age</dt><dd>{d.coverage.wall_clock_age_days} days</dd>
              </dl>
              {d.platform.note && <p className="mt-2 text-[11px] text-slate-500">{d.platform.note}</p>}
            </Card>
            <Card title="Detections & confidence">
              <dl className="grid grid-cols-2 gap-1 text-xs">
                <dt className="text-slate-400">All</dt><dd>{num(d.detections?.total)}</dd>
                <dt className="text-slate-400">Presumed vegetation</dt><dd>{num(d.detections?.presumed_vegetation)}</dd>
                <dt className="text-slate-400">Science quality</dt><dd>{num(d.detections?.science_quality)}</dd>
                <dt className="text-slate-400">Confidence l / n / h</dt><dd>{num(d.confidence?.low)} / {num(d.confidence?.nominal)} / {num(d.confidence?.high)}</dd>
                <dt className="text-slate-400">Day / night</dt><dd>{num(d.day_night?.D)} / {num(d.day_night?.N)}</dd>
              </dl>
            </Card>
            <Card title="Seasonal share & overlap">
              <ul className="text-xs">{Object.entries(d.seasonal_share || {}).map(([k, v]) => <li key={k}>{k}: {pct(v, 1)}</li>)}</ul>
              <ul className="mt-2 text-xs text-slate-400">{Object.entries(d.overlap || {}).map(([k, v]) => <li key={k}>Overlap with {k}: {v ? `${v.from} → ${v.to} (${num(v.months, 1)} months)` : 'none'}</li>)}</ul>
            </Card>
          </div>
          <Card title="Detections per year (presumed vegetation)" sub="Actual observations; partial years are partial.">
            <div className="flex flex-wrap gap-3 text-xs">{Object.entries(d.detections?.per_year || {}).map(([y, n]) => <span key={y} className="rounded border border-line px-2 py-1">{y}: <b>{num(n)}</b></span>)}</div>
          </Card>
        </>}
      </State>
      <ModelCard item={card} loading={models.loading} error={models.error} />
      {sensor === 'NOAA-21' && <Noaa21Panel />}
    </div>
  )
}

function ModelCard({ item, loading, error }: { item?: ModelCardItem; loading: boolean; error: string | null }) {
  return (
    <Card title="Independent forecast model" badges={item?.serving_status && <StatusTag s={item.serving_status.status} />} sub={item?.target}>
      <State loading={loading} error={error} empty={!item}>
        {item && <>
          {item.serving_status?.message && <Note tone="warn">{item.serving_status.message}</Note>}
          <div className="grid gap-2 text-xs sm:grid-cols-4">
            <div>Model <b className="font-mono">{item.model_version}</b><div className="text-slate-500">trained {item.trained_at || 'legacy (date not recorded)'}</div></div>
            <div>Split: train ≤ {item.split?.train_until}, calibrate ≤ {item.split?.calibrate_until}, test {item.split?.test_from} → {item.split?.test_until}</div>
            <div>Test rows {num(item.rows?.test)}; NRT in labels: {item.nrt_in_labels ? 'yes (legacy)' : 'no'}</div>
            <div>Latest issue {item.issue_date}</div>
          </div>
          <table className="mt-3 w-full text-xs"><thead><tr><Th>Brier</Th><Th>BSS vs climatology</Th><Th>ROC-AUC</Th><Th>PR-AUC</Th><Th>ECE</Th><Th>Precision@60%</Th><Th>Recall@60%</Th><Th>Specificity</Th><Th>Missed events</Th></tr></thead>
            <tbody><tr><Tc right>{num(item.evaluation?.brier, 4)}</Tc><Tc right>{num(item.evaluation?.brier_skill, 3)}</Tc><Tc right>{num(item.evaluation?.roc_auc, 3)}</Tc><Tc right>{num(item.evaluation?.pr_auc, 3)}</Tc>
              <Tc right>{num(item.evaluation?.ece, 4)}</Tc><Tc right>{pct(item.evaluation?.precision, 1)}</Tc><Tc right>{pct(item.evaluation?.recall, 1)}</Tc><Tc right>{pct(item.evaluation?.specificity, 1)}</Tc><Tc right>{pct(item.evaluation?.missed_event_rate, 1)}</Tc></tr></tbody></table>
          {item.breakdowns?.season && <table className="mt-3 w-full text-xs"><thead><tr><Th>Season</Th><Th>n</Th><Th>Brier</Th><Th>ROC-AUC</Th><Th>ECE</Th><Th>Reliable sample</Th></tr></thead>
            <tbody>{Object.entries(item.breakdowns.season).map(([k, m]) => <tr key={k}><Tc>{k}</Tc><Tc right>{num(m.n)}</Tc><Tc right>{num(m.brier, 4)}</Tc><Tc right>{num(m.roc_auc, 3)}</Tc><Tc right>{num(m.ece, 4)}</Tc><Tc>{m.reliable ? 'yes' : 'no'}</Tc></tr>)}</tbody></table>}
          <p className="mt-2 text-[11px] text-slate-500">Probability = at least one {item.reference_sensor} VIIRS 375 m hotspot in the cell within 7 days. Not ignition probability.</p>
        </>}
      </State>
    </Card>
  )
}

/* ------------------------------------------------------------------ forecast models + sensor selector */
export function ForecastModelsPage() {
  const { region } = useApp()
  const models = useApi<{ items: ModelCardItem[]; served_by_default: string; rule: string }>('/api/forecast/models')
  const [sensor, setSensor] = useState<string>('')
  const chosen = sensor || models.data?.served_by_default || ''
  const f = useApi<RegionForecast>(chosen ? `/api/forecast/${encodeURIComponent(region)}?sensor=${encodeURIComponent(chosen)}` : null)
  return (
    <div className="space-y-4" data-testid="forecast-models-page">
      <Head title="Forecast models by target sensor" intro={models.data?.rule || 'One independent model per VIIRS platform.'} />
      <Card title="Region forecast by sensor" sub="Choose the target satellite explicitly. There is no silent fallback between sensors.">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
          <label htmlFor="fsensor" className="text-slate-400">Target sensor</label>
          <select id="fsensor" aria-label="Forecast target sensor" value={chosen} onChange={(e) => setSensor(e.target.value)} className="rounded border border-line bg-[#080d17] px-2 py-1">
            {(models.data?.items || []).map((m) => <option key={m.reference_sensor} value={m.reference_sensor}>{m.reference_sensor}{m.legacy ? ' (legacy, retired)' : ''}</option>)}
          </select>
          <span className="text-slate-500">default: {models.data?.served_by_default}</span>
        </div>
        <State loading={f.loading} error={f.error} empty={!f.data}>
          {f.data && f.data.status === 'ok' ? <div className="text-sm">
            <p><b>{pct(f.data.headline_probability)}</b> regional probability ({pct(f.data.regional?.p_any_lower)}–{pct(f.data.regional?.p_any_upper)}), highest cell {pct(f.data.max_cell_probability)}, {titleCase(f.data.risk_category)} — issued {f.data.issue_date}.</p>
            <p className="mt-1 text-xs text-slate-400">Target sensor <b>{f.data.reference?.reference_sensor}</b>, model <span className="font-mono">{f.data.reference?.model_version}</span>, status {f.data.reference?.serving_status?.status}.</p>
            {f.data.reference?.serving_status?.message && <Note tone="warn">{f.data.reference.serving_status.message}</Note>}
            <p className="mt-2 text-xs text-slate-400">{f.data.meaning}</p>
          </div> : f.data && <Note tone="warn">{f.data.message || f.data.status}</Note>}
        </State>
      </Card>
      {(models.data?.items || []).map((m) => <ModelCard key={m.reference_sensor} item={m} loading={false} error={null} />)}
      <ForecastComparisonPanel />
    </div>
  )
}

/* ------------------------------------------------------------------ VIIRS products */
export function Viirs375Page() {
  const s = useApi<OpSummary>('/api/reference/operational')
  return (
    <div className="space-y-4" data-testid="viirs375-page">
      <Head title="VIIRS 375 m active fire" intro="FIRMS VIIRS Collection 2 375 m product (VNP14IMGT / VJ114IMGT / VJ214IMGT). Each satellite is a separate actual stream; 375 m is never pooled with 750 m or MODIS 1 km." />
      <State loading={s.loading} error={s.error} empty={!s.data}>
        <Card title="Platforms (375 m)">
          <table className="w-full text-xs"><thead><tr><Th>Satellite</Th><Th>Status</Th><Th>Loaded</Th><Th>Science-quality to</Th><Th>Detections</Th><Th>Role</Th></tr></thead>
            <tbody>
              {s.data && <tr><Tc>{s.data.historical_reference.platform}</Tc><Tc><StatusTag s={s.data.historical_reference.status} /></Tc><Tc>{s.data.historical_reference.loaded_first} → {s.data.historical_reference.loaded_last}</Tc><Tc>{s.data.historical_reference.science_quality_last}</Tc><Tc>–</Tc><Tc>historical reference</Tc></tr>}
              {(s.data?.candidates || []).map((c) => <tr key={c.sensor}><Tc>{c.sensor}</Tc><Tc><StatusTag s={c.platform.status || 'unknown'} /></Tc><Tc>{c.coverage ? `${c.coverage.first} → ${c.coverage.last}` : 'not loaded'}</Tc><Tc>{c.coverage?.science_quality_last || '–'}</Tc><Tc right>{num(c.detections?.total)}</Tc><Tc>{c.platform.noaa_role || '–'}</Tc></tr>)}
            </tbody></table>
        </Card>
      </State>
    </div>
  )
}

export function Viirs750Page() {
  const { role } = useApp()
  const cr = useApi<Creds750>('/api/viirs750/credentials')
  const [q, setQ] = useState({ satellite: 'NOAA-21', start: '2025-11-01', end: '2025-11-01' })
  const [res, setRes] = useState<Search750 | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const search = () => { setBusy(true); setRes(null); api<Search750>(`/api/viirs750/search?satellite=${encodeURIComponent(q.satellite)}&start=${q.start}&end=${q.end}`).then(setRes).catch((e) => setRes({ status: 'search_failed', error: errText(e), granules: [] })).finally(() => setBusy(false)) }
  const fetchJob = () => api<Job>('/api/jobs', { body: { kind: 'viirs750_fetch', params: { satellites: [q.satellite], start: q.start, end: q.end } } }).then((j) => setMsg(`Job ${j.id} queued (${j.status}). See System Configuration → Jobs.`)).catch((e) => setMsg(errText(e)))
  return (
    <div className="space-y-4" data-testid="viirs750-page">
      <Head title="VIIRS 750 m (VNP14 / VJ114 / VJ214)" intro="Continuity product (MODIS C6 algorithm on VIIRS M-bands). Level-2 swath granules from LP DAAC; download needs Earthdata Login. Converted records form separate '<sat> 750m' streams and are calibrated separately." />
      <Card title="Earthdata credentials" badges={cr.data && <StatusTag s={cr.data.state} />}>
        <State loading={cr.loading} error={cr.error} empty={!cr.data}>
          {cr.data && <div className="text-xs">
            <p>Method: {cr.data.method || 'none'} · last success: {cr.data.last_success || 'never'} · last error: {cr.data.last_error || 'none'}</p>
            {!cr.data.configured && <Note tone="warn">NOT CONFIGURED. Authentic granule download and real-granule verification are blocked until credentials are added. {cr.data.how}</Note>}
          </div>}
        </State>
      </Card>
      <Card title="Granule search (public CMR, no login)">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select aria-label="750 m satellite" value={q.satellite} onChange={(e) => setQ({ ...q, satellite: e.target.value })} className="rounded border border-line bg-[#080d17] px-2 py-1">{['NOAA-21', 'NOAA-20', 'Suomi NPP'].map((s) => <option key={s}>{s}</option>)}</select>
          <input aria-label="Start date" type="date" value={q.start} onChange={(e) => setQ({ ...q, start: e.target.value })} className="rounded border border-line bg-[#080d17] px-2 py-1" />
          <input aria-label="End date" type="date" value={q.end} onChange={(e) => setQ({ ...q, end: e.target.value })} className="rounded border border-line bg-[#080d17] px-2 py-1" />
          <Btn small onClick={search} disabled={busy}>{busy ? 'Searching…' : 'Search'}</Btn>
          {role === 'admin' && <Btn small kind="primary" onClick={fetchJob} disabled={!cr.data?.configured} title={cr.data?.configured ? 'Queue download + conversion job' : 'Earthdata credentials not configured'}>Download & convert (job)</Btn>}
        </div>
        {msg && <p className="mt-2 text-xs text-slate-300">{msg}</p>}
        {res && (res.status !== 'ok' ? <Note tone="warn">Search failed: {res.error}</Note> : <div className="mt-2 text-xs">
          <p>{res.count} granule(s){res.truncated ? ' (first 50 shown)' : ''}.</p>
          <ul className="mt-1 max-h-48 overflow-auto font-mono text-[11px]">{res.granules.map((g) => <li key={g.granule}>{g.granule} · {g.daynight || '–'} · {g.size_bytes_approx ? `${(g.size_bytes_approx / 1e6).toFixed(1)} MB` : 'size n/a'}</li>)}</ul>
        </div>)}
      </Card>
      <Viirs750Panel />
    </div>
  )
}

/* ------------------------------------------------------------------ exposure */
export function ExposurePage({ kind }: { kind: 'population' | 'infrastructure' }) {
  const lin = useApi<LinearStatus>(kind === 'infrastructure' ? '/api/infrastructure/linear/status' : null)
  const [pt, setPt] = useState({ lat: '28.6', lon: '77.2', category: 'road_major' })
  const [near, setNear] = useState<Nearest | null>(null)
  const look = () => api<Nearest>(`/api/infrastructure/nearest?lat=${pt.lat}&lon=${pt.lon}&category=${pt.category}`).then(setNear).catch((e) => setNear({ category: pt.category, status: 'error', reason: errText(e) }))
  return (
    <div className="space-y-4" data-testid={`exposure-page-${kind}`}>
      <Head title={kind === 'population' ? 'Population exposure' : 'Infrastructure exposure'} intro="Exposure = people / facilities / lines near detected or predicted hotspots. It does not mean anything will burn or is damaged. Unavailable layers are shown as unavailable, never as zero." />
      {kind === 'infrastructure' && <Card title="Linear infrastructure (OpenStreetMap / Geofabrik)" badges={lin.data && <StatusTag s={lin.data.status} />}>
        <State loading={lin.loading} error={lin.error} empty={!lin.data}>
          {lin.data && (lin.data.status !== 'built' ? <Note tone="warn">{lin.data.national_coverage} {lin.data.how}</Note> : <>
            <table className="w-full text-xs"><thead><tr><Th>Category</Th><Th>Status</Th><Th>Features</Th><Th>Length (km)</Th></tr></thead>
              <tbody>{Object.entries(lin.data.categories || {}).map(([k, v]) => <tr key={k}><Tc>{titleCase(k)}</Tc><Tc><StatusTag s={v.status === 'loaded' ? 'loaded' : 'unavailable'} /></Tc><Tc right>{num(v.features)}</Tc><Tc right>{num(v.total_length_km)}</Tc></tr>)}</tbody></table>
            <p className="mt-2 text-[11px] text-slate-500">{lin.data.licence} · downloaded {lin.data.download_date || '–'} · {lin.data.coverage}</p>
            <ul className="text-[11px] text-amber-300">{(lin.data.known_gaps || []).map((g) => <li key={g}>{g}</li>)}</ul>
          </>)}
        </State>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <input aria-label="Latitude" value={pt.lat} onChange={(e) => setPt({ ...pt, lat: e.target.value })} className="w-20 rounded border border-line bg-[#080d17] px-2 py-1" />
          <input aria-label="Longitude" value={pt.lon} onChange={(e) => setPt({ ...pt, lon: e.target.value })} className="w-20 rounded border border-line bg-[#080d17] px-2 py-1" />
          <select aria-label="Category" value={pt.category} onChange={(e) => setPt({ ...pt, category: e.target.value })} className="rounded border border-line bg-[#080d17] px-2 py-1">{['road_major', 'road_minor', 'railway', 'power_line', 'power_minor', 'power_facility', 'settlement'].map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}</select>
          <Btn small onClick={look}>Nearest</Btn>
          {near && <span>{near.status === 'found' ? `${num(near.distance_km, 2)} km — ${near.name || near.class || 'unnamed'}` : `${titleCase(near.status)}${near.reason ? `: ${near.reason}` : ''}`}</span>}
        </div>
      </Card>}
      <ExposurePanel />
    </div>
  )
}

export function OrbitsPage() {
  return (
    <div className="space-y-4" data-testid="orbits-page">
      <Head title="Orbital observation opportunities" intro="Predicted overpasses from SGP4 + CelesTrak TLEs. Predictions are observation opportunities, never fire detections; stale TLEs are flagged." />
      <OrbitPanel />
    </div>
  )
}

/* ------------------------------------------------------------------ critical-region scoring */
export function ScoringPanel() {
  const { role } = useApp()
  const w = useApi<Weights>('/api/critical-regions/weights')
  const sv = useApi<Sensitivity>('/api/critical-regions/sensitivity')
  const [msg, setMsg] = useState<string | null>(null)
  const reset = () => api<Weights['active']>('/api/critical-regions/weights', { method: 'DELETE' }).then(() => { setMsg('Reverted to v2-balanced.'); w.reload(); sv.reload() }).catch((e) => setMsg(errText(e)))
  return (
    <Card title="Critical-region scoring: weights & sensitivity" badges={w.data && <Prov kind="proto" text={`weights ${w.data.active.version}`} />}
      sub="Deterministic decision-support ranking, not a ground-truth risk score. Exposure components raise monitoring priority, never fire probability.">
      <State loading={w.loading} error={w.error} empty={!w.data}>
        {w.data && <div className="flex flex-wrap gap-2 text-xs">{Object.entries(w.data.active.weights).map(([k, v]) => <span key={k} className="rounded border border-line px-2 py-1" title={w.data?.labels[k]}>{k}: <b>{pct(v)}</b></span>)}</div>}
        {role === 'admin' && w.data?.active.profile === 'custom' && <Btn small onClick={reset}>Revert to default profile</Btn>}
        {msg && <p className="text-xs">{msg}</p>}
      </State>
      <State loading={sv.loading} error={sv.error} empty={!sv.data}>
        {sv.data?.sensitivity && <div className="mt-3 grid gap-3 lg:grid-cols-2 text-xs">
          <table className="w-full"><thead><tr><Th>Profile</Th><Th>Spearman vs active</Th><Th>Top-20 overlap</Th></tr></thead>
            <tbody>{Object.entries(sv.data.sensitivity.profiles).map(([k, v]) => <tr key={k}><Tc>{k}</Tc><Tc right>{num(v.spearman_vs_active, 3)}</Tc><Tc right>{pct(v.top_overlap)}</Tc></tr>)}</tbody></table>
          <table className="w-full"><thead><tr><Th>Profile</Th><Th>Past issues</Th><Th>Spearman vs observed</Th><Th>Top-20 hit rate</Th></tr></thead>
            <tbody>{Object.entries(sv.data.historical_alignment || {}).map(([k, v]) => <tr key={k}><Tc>{k}</Tc><Tc right>{v.issues}</Tc><Tc right>{num(v.mean_spearman, 3)}</Tc><Tc right>{pct(v.mean_top_hit_rate)}</Tc></tr>)}</tbody></table>
          <p className="text-[11px] text-slate-500 lg:col-span-2">Min top-20 overlap under ±20 % single-weight changes: {pct(sv.data.sensitivity.min_top_overlap_under_20pct_perturbation)}. History check uses {sv.data.historical_alignment_sensor} issues with verified outcomes. {sv.data.interpretation}</p>
          {(sv.data.not_available || []).map((n) => <Note key={n} tone="warn">{n}</Note>)}
        </div>}
      </State>
    </Card>
  )
}

/* ------------------------------------------------------------------ system configuration */
export function SystemConfigPage() {
  const { role } = useApp()
  const admin = role === 'admin'
  const cfg = useApi<ConfigView>(admin ? '/api/system/config' : null)
  const cred = useApi<{ items: CredItem[]; note: string }>(admin ? '/api/system/credentials' : null)
  const chk = useApi<{ steps: Step[]; issues: Issue[] }>(admin ? '/api/notifications/checklist' : null)
  const jobs = useApi<{ items: Job[]; kinds: Record<string, string> }>(admin || role === 'analyst' || role === 'gov_officer' ? '/api/jobs' : null)
  const [msg, setMsg] = useState<string | null>(null)
  const test = () => api<{ ok: boolean; error?: string; explanation?: string; note?: string }>('/api/notifications/check').then((r) => setMsg(r.ok ? `Connection OK. ${r.note || ''}` : `${r.error} ${r.explanation || ''}`)).catch((e) => setMsg(errText(e)))
  const submit = (kind: string) => api<Job>('/api/jobs', { body: { kind, params: {} } }).then(() => jobs.reload()).catch((e) => setMsg(errText(e)))
  const cancel = (id: number) => api<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }).then(() => jobs.reload()).catch((e) => setMsg(errText(e)))
  return (
    <div className="space-y-4" data-testid="system-page">
      <Head title="System configuration" intro="Configuration checks, credential readiness, notification setup and background jobs. Secret values are never displayed." />
      {!admin && <Note>Configuration and credential status are visible to administrators only.</Note>}
      {admin && <>
        <Card title="Configuration validation" badges={cfg.data && <StatusTag s={cfg.data.ok ? 'ok' : 'FAILED'} />} sub={cfg.data ? `Mode: ${cfg.data.mode} · X-User header trusted: ${cfg.data.x_user_header_trusted ? 'yes (development only)' : 'no'}` : undefined}>
          <State loading={cfg.loading} error={cfg.error} empty={!cfg.data}>
            <ul className="space-y-1 text-xs">{(cfg.data?.issues || []).map((i, k) => <li key={k} className={i.level === 'error' ? 'text-red-300' : 'text-amber-300'}><b>{i.level.toUpperCase()}</b> {i.key}: {i.message}</li>)}</ul>
          </State>
        </Card>
        <Card title="Credential readiness" sub={cred.data?.note}>
          <State loading={cred.loading} error={cred.error} empty={!cred.data}>
            <table className="w-full text-xs"><thead><tr><Th>Integration</Th><Th>Status</Th><Th>Variables</Th><Th>Needed for</Th></tr></thead>
              <tbody>{(cred.data?.items || []).map((c) => <tr key={c.integration}><Tc>{c.integration}</Tc><Tc><StatusTag s={c.status} /></Tc><Tc><span className="font-mono text-[11px]">{c.variables.join(', ')}</span></Tc><Tc>{c.needed_for}</Tc></tr>)}</tbody></table>
          </State>
        </Card>
        <Card title="Notification setup checklist" right={<Btn small onClick={test}>Check provider connection</Btn>}>
          <State loading={chk.loading} error={chk.error} empty={!chk.data}>
            <ul className="space-y-1 text-xs">{(chk.data?.steps || []).map((s) => <li key={s.step}>{yes(s.done)} {s.step}</li>)}</ul>
            <ul className="mt-2 text-xs">{(chk.data?.issues || []).map((i, k) => <li key={k} className={i.level === 'error' ? 'text-red-300' : 'text-amber-300'}>{i.key}: {i.message}</li>)}</ul>
            {msg && <p className="mt-2 text-xs text-slate-300">{msg}</p>}
          </State>
        </Card>
      </>}
      <Card title="Background data jobs" sub="Long downloads and processing run as jobs; API requests never block on them.">
        <State loading={jobs.loading} error={jobs.error} empty={!jobs.data}>
          {admin && <div className="mb-2 flex flex-wrap gap-2">{Object.entries(jobs.data?.kinds || {}).filter(([k]) => k !== 'viirs750_fetch').map(([k, v]) => <Btn key={k} small onClick={() => submit(k)} title={v}>{titleCase(k)}</Btn>)}</div>}
          <table className="w-full text-xs"><thead><tr><Th>#</Th><Th>Kind</Th><Th>Status</Th><Th>Progress / error</Th><Th>By</Th><Th>Created</Th><Th>{" "}</Th></tr></thead>
            <tbody>{(jobs.data?.items || []).map((j) => <tr key={j.id}><Tc>{j.id}</Tc><Tc>{titleCase(j.kind)}</Tc><Tc><StatusTag s={j.status} /></Tc><Tc><span className="text-[11px]">{j.error || j.progress?.message || ''}</span></Tc><Tc>{j.requested_by}</Tc><Tc>{j.created_at?.slice(0, 16).replace('T', ' ')}</Tc>
              <Tc>{admin && (j.status === 'RUNNING' || j.status === 'QUEUED') && !j.cancel_requested && <Btn small kind="danger" onClick={() => cancel(j.id)}>Cancel</Btn>}</Tc></tr>)}</tbody></table>
        </State>
      </Card>
      <NotificationLogCard />
    </div>
  )
}
