/* Scientific modules: Morning-Gap Fixer, Sensor Harmonizer, Uncertainty, Validation & Seam Test,
 * Burning Activity Calendar, Historical Trends, Anomaly Detection.
 * Every number comes from the API. Estimates are always labelled as estimates. */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Play, RefreshCw } from 'lucide-react'
import { api, useApi, useApp, num, pct, compact, titleCase, Prov, Tabs, SplitPicker, C, SAT_COLOR, SAT_LABEL, MONTHS, TIER_COLOR } from './lib'
import { Banner, Button, Card, CardBody, CardHeader, EmptyStateCard, Table, UncertaintyNote, ArgonStatCard } from './argon'
import { Series, StatusBars, LogScatter, withBand } from './charts'
import { seq } from './map'

/* ------------------------------------------------------------------ shared helpers */
export const enc = (r: string) => encodeURIComponent(r)

export function PageHead({ idx, title, intro, badges, actions }: { idx: string; title: string; intro: ReactNode; badges?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0 max-w-4xl">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded border border-orange-500/30 bg-orange-500/15 px-2 py-0.5 font-mono text-xs font-bold text-orange-300">Section {idx}</span>
          <h1 className="text-xl font-bold tracking-tight text-white">{title}</h1>
          {badges}
        </div>
        <p className="mt-1 text-xs leading-relaxed text-slate-400">{intro}</p>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** Loading / error / empty wrapper using Argon empty-state cards (never dummy numbers). */
export function Load({ loading, error, data, children, what }: { loading: boolean; error: string | null; data: any; children: ReactNode; what: string }) {
  if (error) return <EmptyStateCard title={`Could not load ${what}`} description={<span className="text-red-300">{error}</span>} />
  if (loading && !data) return <Card><CardBody className="animate-pulse py-12 text-center text-sm text-slate-400">Loading {what}…</CardBody></Card>
  if (!data) return null
  return <>{children}</>
}

export function Panel({ title, sub, badge, actions, children, pad = true }: { title: ReactNode; sub?: ReactNode; badge?: ReactNode; actions?: ReactNode; children: ReactNode; pad?: boolean }) {
  return (
    <Card>
      <CardHeader title={title} subtitle={sub} badge={badge} actions={actions} />
      <CardBody noPadding={!pad} className={pad ? 'p-4' : ''}>{children}</CardBody>
    </Card>
  )
}

export const Td = ({ children, mono, right }: { children: ReactNode; mono?: boolean; right?: boolean }) => (
  <td className={`px-4 py-2 text-xs ${mono ? 'font-mono' : ''} ${right ? 'text-right tabular-nums' : ''}`}>{children}</td>
)

const STATUS_TONE: Record<string, 'success' | 'warning' | 'danger' | 'info'> = { good: 'success', moderate: 'warning', poor: 'danger', insufficient_data: 'info' }
export function StatusBanner({ status, rule, what }: { status?: string; rule?: string; what: string }) {
  const s = status || 'insufficient_data'
  return (
    <Banner tone={STATUS_TONE[s] || 'info'} title={`${what}: ${titleCase(s).toUpperCase()}`}>
      {rule}
    </Banner>
  )
}

const pf = (v: number) => `${Math.round(v * 100)}%`
const r2 = (v: number) => num(v, 2)
const isEst = (p?: string) => p === 'sensor_calibrated' || p === 'morning_gap_sensor'

/** Notes such as orbit drift returned by the calibration fit. */
function FitNotes({ notes }: { notes?: string[] }) {
  if (!notes?.length) return null
  return <Banner tone="warning" title="Calibration notes">{notes.map((n, i) => <div key={i}>{n}</div>)}</Banner>
}

function MetricsTable({ rows }: { rows: { name: ReactNode; m?: any }[] }) {
  return (
    <Table headers={['Model', 'n months', 'MAE', 'RMSE', 'WAPE', 'MAPE', 'Bias', 'R²']}>
      {rows.filter((r) => r.m).map((r, i) => (
        <tr key={i} className="hover:bg-[#172033]/60">
          <Td>{r.name}</Td><Td right>{num(r.m.n)}</Td><Td right>{num(r.m.mae)}</Td><Td right>{num(r.m.rmse)}</Td>
          <Td right>{num(r.m.wape_pct, 1)}%</Td><Td right>{num(r.m.mape_pct, 1)}%</Td><Td right>{num(r.m.bias_pct, 1)}%</Td><Td right>{num(r.m.r2, 3)}</Td>
        </tr>
      ))}
    </Table>
  )
}

/** Monthly calibration ratios (day & night) with bootstrap band, grouped by month of year. */
function RatioByMonth({ byMonth, yLabel }: { byMonth: any[]; yLabel: string }) {
  const rows = MONTHS.map((m, i) => {
    const d = byMonth.find((r) => r.moy === i + 1 && r.daynight === 'day')
    const n = byMonth.find((r) => r.moy === i + 1 && r.daynight === 'night')
    return { month: m, day: d?.ratio ?? null, day_b: d ? [d.ratio_lo, d.ratio_hi] : null, night: n?.ratio ?? null, night_b: n ? [n.ratio_lo, n.ratio_hi] : null }
  })
  return (
    <Series data={rows} x="month" monthly={false} yFmt={r2} yLabel={yLabel} height={260}
      bands={[{ key: 'day_b', name: 'Day band (5–95%)', color: C.aqua }, { key: 'night_b', name: 'Night band (5–95%)', color: C.n20 }]}
      lines={[{ key: 'day', name: 'Day ratio', color: C.aqua, dots: true }, { key: 'night', name: 'Night ratio', color: C.n20, dots: true }]}
      refs={[{ y: 1, label: 'ratio = 1' }]} />
  )
}

function CalibTable({ byMonth }: { byMonth: any[] }) {
  return (
    <Table headers={['Month', 'Pass', 'Learned ratio', 'Band (5–95%)', 'Silent-cell rate', 'Predictor detections', 'Reliable']}>
      {byMonth.map((r, i) => (
        <tr key={i} className={r.reliable ? '' : 'bg-red-500/5'}>
          <Td>{MONTHS[r.moy - 1]}</Td><Td>{titleCase(r.daynight)}</Td><Td right>{r2(r.ratio)}</Td>
          <Td mono>{r2(r.ratio_lo)} – {r2(r.ratio_hi)}</Td><Td right>{pct(r.silent_rate, 1)}</Td><Td right>{num(r.predictor_detections)}</Td>
          <Td>{r.reliable ? <span className="text-emerald-300">yes</span> : <span className="font-semibold text-red-300">WEAK</span>}</Td>
        </tr>
      ))}
    </Table>
  )
}

function StateFactors({ rows, label }: { rows: any[]; label: string }) {
  return (
    <Table headers={['State', label, 'Predictor detections', 'Data weight']}>
      {rows.slice(0, 18).map((r) => (
        <tr key={r.state}><Td>{r.state}</Td><Td right>{r2(r.ratio)}</Td><Td right>{num(r.predictor_detections)}</Td><Td right>{pct(r.data_weight)}</Td></tr>
      ))}
    </Table>
  )
}

/* ================================================================== 03 Morning-Gap Fixer */
export function MorningGapPage() {
  const { region } = useApp()
  const [split, setSplit] = useState<number | null>(null)
  const q = `region=${enc(region)}${split ? `&split=${split}` : ''}`
  const { data, loading, error } = useApi<any>(`/api/morning-gap/analysis?${q}`)
  const [run, setRun] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [runErr, setRunErr] = useState<string | null>(null)
  useEffect(() => setRun(null), [region, split])
  const doRun = () => {
    setBusy(true); setRunErr(null)
    api('/api/morning-gap/correct', { body: { region, split } }).then(setRun).catch((e) => setRunErr(e.message)).finally(() => setBusy(false))
  }
  const series = useMemo(() => withBand(data?.series || [], 'band', 'aqua_est_lo', 'aqua_est_hi'), [data])

  return (
    <div className="space-y-5">
      <PageHead idx="03" title="Morning-Gap Fixer" badges={<Prov kind="mg" />}
        intro="Terra (≈10:30 / 22:30 local) and Aqua (≈13:30 / 01:30) see the diurnal fire cycle at different times. The Terra→Aqua relationship is learned from the overlap by state, month and day/night, then applied to Terra-only months. Corrected values are statistical estimates, not satellite detections."
        actions={<SplitPicker value={split} onChange={setSplit} allowOperational />} />
      <Load loading={loading} error={error} data={data} what="morning-gap analysis">
        {data && <>
          <FitNotes notes={data.calibration?.notes} />
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <ArgonStatCard title="Months Aqua < Terra (day+night)" value={pct(data.share_months_aqua_below_terra)} subValue="Afternoon is NOT always higher - learned, not assumed" provenance="Actual Observation" />
            <ArgonStatCard title="Months Aqua night < Terra night" value={pct(data.share_months_aqua_night_below_terra_night)} subValue="01:30 pass sees fewer fires than 22:30" provenance="Actual Observation" />
            <ArgonStatCard title="Calibration years" value={num(data.calibration?.train_years?.length)} subValue={`${data.calibration?.train_years?.[0] ?? '–'}–${data.calibration?.train_years?.slice(-1)[0] ?? '–'}`} provenance="Harmonized Estimate" />
            <ArgonStatCard title="Real Terra-only months" value={num(data.terra_only_real_months)} subValue="months with Terra but no Aqua coverage in the loaded record" provenance="Actual Observation" />
          </div>
          <Panel title="Terra morning vs Aqua afternoon - monthly detections" badge={<><Prov kind="actual" /><Prov kind="mg" text="Aqua estimate from Terra" /></>}
            sub={`${data.region}. Solid = actual detections. Dashed amber = Aqua activity estimated from Terra alone, with its 5–95% bootstrap band.`}>
            <Series data={series} bands={[{ key: 'band', name: 'Estimate band', color: C.est }]}
              lines={[{ key: 'terra', name: 'Terra MODIS (actual)', color: C.terra }, { key: 'aqua', name: 'Aqua MODIS (actual)', color: C.aqua }, { key: 'aqua_est', name: 'Aqua estimated from Terra', color: C.est, dash: '5 3' }]} />
          </Panel>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Day vs night passes" badge={<Prov kind="actual" />} sub="The diurnal relationship differs completely by day and night, so the model is fitted separately for each.">
              <Series data={data.series} height={240} lines={[
                { key: 'terra_day', name: 'Terra day', color: C.terra }, { key: 'aqua_day', name: 'Aqua day', color: C.aqua },
                { key: 'terra_night', name: 'Terra night', color: C.terra, dash: '3 3' }, { key: 'aqua_night', name: 'Aqua night', color: C.aqua, dash: '3 3' }]} />
            </Panel>
            <Panel title="Learned Terra→Aqua ratio by month" badge={<Prov kind="mg" text="Learned relationship" />} sub={data.calibration?.model}>
              <RatioByMonth byMonth={data.calibration?.by_month || []} yLabel="Aqua / Terra" />
            </Panel>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Calibration table" sub={data.calibration?.band} pad={false}><div className="max-h-96 overflow-y-auto"><CalibTable byMonth={data.calibration?.by_month || []} /></div></Panel>
            <div className="space-y-4">
              <Panel title="State × month cells: Terra vs Aqua (log-log)" badge={<Prov kind="actual" />}>
                <LogScatter data={data.scatter || []} xName="Terra detections" yName="Aqua detections" color={C.aqua} height={240} />
              </Panel>
              <Panel title="Leave-one-year-out skill by month" sub="Out-of-sample error of the Terra→Aqua step." pad={false}>
                <Table headers={['Month', 'WAPE', 'Bias', 'Years', 'Mean actual']}>
                  {(data.calibration?.loyo?.by_month || []).map((r: any) => (
                    <tr key={r.moy}><Td>{MONTHS[r.moy - 1]}</Td><Td right>{pct(r.wape, 1)}</Td><Td right>{pct(r.bias, 1)}</Td><Td right>{r.n_years}</Td><Td right>{num(r.mean_actual)}</Td></tr>
                  ))}
                </Table>
              </Panel>
            </div>
          </div>
          <Panel title="State correction factors (Aqua / Terra)" sub="Pooled ratios shrink toward the national value where a state has little data (data weight)." pad={false}>
            <StateFactors rows={data.state_factors || []} label="Aqua / Terra" />
          </Panel>
          <Panel title="Apply the correction" badge={<Prov kind="mg" />}
            sub="Runs the Morning-Gap Fixer on the real Terra-only months and, as a test, on overlap months whose Aqua data is withheld before the split year."
            actions={<Button size="sm" onClick={doRun} disabled={busy}><Play className="h-3.5 w-3.5" />{busy ? 'Running…' : 'Run correction'}</Button>}>
            {runErr && <Banner tone="danger">{runErr}</Banner>}
            {!run && !runErr && <p className="text-xs text-slate-400">Press “Run correction” to compute corrected and withheld-period estimates.</p>}
            {run && <div className="space-y-4">
              <Banner tone="info" title="Label">{run.label}</Banner>
              {run.real_terra_only_message ? <Banner tone="warning">{run.real_terra_only_message}</Banner> : (
                <Table headers={['Month', 'Terra (actual)', 'Corrected Aqua-equivalent', 'Band', 'Difference']}>
                  {run.real_terra_only_period.map((r: any) => (
                    <tr key={r.date}><Td mono>{r.date.slice(0, 7)}</Td><Td right>{num(r.terra)}</Td><Td right>{num(r.aqua_est)}</Td><Td mono>{num(r.aqua_est_lo)} – {num(r.aqua_est_hi)}</Td><Td right>{num(r.aqua_est - r.terra)}</Td></tr>
                  ))}
                </Table>
              )}
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
                <Prov kind="experiment" /> Withheld-Aqua test before {String(run.split).slice(0, 4)}: status <strong className="uppercase">{run.simulated_validation?.status}</strong>,
                WAPE {num(run.simulated_validation?.metrics?.wape_pct, 1)}% vs {num(run.simulated_validation?.baseline_constant_ratio?.wape_pct, 1)}% for one constant ratio, band coverage {num(run.simulated_validation?.band_coverage_pct, 0)}%.
              </div>
              <Series data={withBand(run.simulated, 'band', 'aqua_est_lo', 'aqua_est_hi')} height={240} bands={[{ key: 'band', name: 'Estimate band', color: C.est }]}
                bars={[{ key: 'difference', name: 'Correction added (estimate − Terra)', color: '#475569' }]}
                lines={[{ key: 'terra', name: 'Terra (actual)', color: C.terra }, { key: 'aqua', name: 'Aqua (actual, withheld)', color: C.aqua }, { key: 'aqua_est', name: 'Corrected estimate', color: C.est, dash: '5 3' }]} />
            </div>}
          </Panel>
          <UncertaintyNote provenance="Harmonized Estimate">{data.note}</UncertaintyNote>
        </>}
      </Load>
    </div>
  )
}

/* ================================================================== 04 MODIS–VIIRS Harmonization / Sensor Harmonizer */
export function HarmonizerPage() {
  const { region } = useApp()
  const [tab, setTab] = useState<'timeline' | 'compare' | 'calib'>('timeline')
  const [split, setSplit] = useState<number | null>(null)
  return (
    <div className="space-y-5">
      <PageHead idx="04" title="MODIS–VIIRS Harmonization & Sensor Harmonizer" badges={<Prov kind="veq" />}
        intro="Aqua MODIS (1 km) is calibrated to S-NPP VIIRS (375 m) by state, month and day/night on aligned 0.25° cells, then applied to the (morning-gap-corrected) MODIS record. Actual VIIRS observations are kept separate from converted estimates; counts are never added together."
        actions={<><Tabs value={tab} onChange={setTab} options={[{ value: 'timeline', label: 'Continuous timeline' }, { value: 'compare', label: 'Sensor comparison' }, { value: 'calib', label: 'Calibration model' }]} />
          {tab !== 'compare' && <SplitPicker value={split} onChange={setSplit} allowOperational />}</>} />
      {tab === 'timeline' && <HarmTimeline region={region} split={split} />}
      {tab === 'compare' && <HarmCompare region={region} />}
      {tab === 'calib' && <HarmCalib split={split} />}
    </div>
  )
}

function HarmTimeline({ region, split }: { region: string; split: number | null }) {
  const q = `region=${enc(region)}${split ? `&split=${split}` : ''}`
  const { data, loading, error } = useApi<any>(`/api/harmonization/summary?${q}`)
  const [yearly, setYearly] = useState<any[] | null>(null)
  useEffect(() => {
    setYearly(null)
    api('/api/sensor-harmonizer/process', { body: { region, split } }).then((d: any) => setYearly(d.yearly)).catch(() => setYearly([]))
  }, [region, split])
  const rows = useMemo(() => (data?.series || []).map((r: any) => ({
    ...r, actual: r.provenance === 'actual_viirs' ? r.viirs : null, est: isEst(r.provenance) ? r.harmonized : null,
    band: isEst(r.provenance) && r.harm_lo != null ? [r.harm_lo, r.harm_hi] : null, veq_cmp: r.veq,
  })), [data])
  return (
    <Load loading={loading} error={error} data={data} what="harmonized timeline">
      {data && <>
        <FitNotes notes={data.notes} />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <ArgonStatCard title="Actual VIIRS months" value={num(data.provenance_counts?.actual_viirs || 0)} provenance="Actual Observation" />
          <ArgonStatCard title="Sensor-calibrated months" value={num(data.provenance_counts?.sensor_calibrated || 0)} subValue="estimated from actual Aqua MODIS" provenance="Harmonized Estimate" />
          <ArgonStatCard title="Morning-gap + sensor months" value={num(data.provenance_counts?.morning_gap_sensor || 0)} subValue="estimated from Terra only (two chained steps)" provenance="Harmonized Estimate" />
          <ArgonStatCard title="Pre-VIIRS MODIS months" value={num(data.pre_viirs_real_months)} subValue="loaded MODIS months before VIIRS began" provenance="Actual Observation" />
        </div>
        <Panel title={`Continuous VIIRS-equivalent record - ${data.region}`} badge={<><Prov kind="actual" text="Actual VIIRS" /><Prov kind="veq" /></>}
          sub="Orange = actual S-NPP VIIRS. Amber = VIIRS-equivalent estimate where VIIRS was not observing, with 5–95% band. Grey dotted = the VIIRS-equivalent estimate computed for every month, for comparison only. Raw MODIS shown for scale.">
          <Series data={rows} height={320} bands={[{ key: 'band', name: 'Estimate band', color: C.est }]}
            lines={[{ key: 'actual', name: 'Actual S-NPP VIIRS', color: C.viirs }, { key: 'est', name: 'VIIRS-equivalent estimate', color: C.est, width: 2.5 },
              { key: 'veq_cmp', name: 'VIIRS-eq. from MODIS (comparison)', color: '#94a3b8', dash: '2 3', width: 1 }, { key: 'modis_total', name: 'Raw MODIS (Terra+Aqua)', color: C.terra, width: 1 }]} />
        </Panel>
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel title="Provenance legend" sub="Every month carries exactly one provenance label.">
            <ul className="space-y-1.5 text-xs text-slate-300">
              {Object.entries(data.legend || {}).map(([k, v]) => <li key={k} className="flex gap-2"><code className="text-sky-300">{k}</code><span>{String(v)}</span></li>)}
            </ul>
            <div className="mt-3 space-y-1 text-xs text-slate-400"><div><strong className="text-slate-200">VIIRS product:</strong> {data.products?.viirs}</div><div><strong className="text-slate-200">MODIS product:</strong> {data.products?.modis}</div></div>
          </Panel>
          <Panel title="Yearly harmonized totals" sub="Sum of monthly values; a year with estimated months says how many." pad={false}>
            {!yearly ? <div className="animate-pulse p-4 text-xs text-slate-400">Computing…</div> : (
              <div className="max-h-80 overflow-y-auto"><Table headers={['Year', 'Harmonized', 'Band', 'Actual VIIRS', 'Raw MODIS', 'Estimated months']}>
                {yearly.map((y) => <tr key={y.year}><Td>{y.year}</Td><Td right>{num(y.harmonized)}</Td><Td mono>{num(y.lo)} – {num(y.hi)}</Td><Td right>{num(y.viirs)}</Td><Td right>{num(y.modis)}</Td><Td right>{y.estimated} / {y.months}</Td></tr>)}
              </Table></div>
            )}
          </Panel>
        </div>
      </>}
    </Load>
  )
}

function HarmCompare({ region }: { region: string }) {
  const { data, loading, error } = useApi<any>(`/api/harmonization/compare?region=${enc(region)}`)
  return (
    <Load loading={loading} error={error} data={data} what="sensor comparison">
      {data && <>
        <Banner tone="warning" title="Why counts cannot be added">{data.warning}</Banner>
        <Panel title={`Sensor characteristics - ${data.region}`} badge={<Prov kind="actual" />} pad={false}>
          <Table headers={['Sensor', 'Detections', 'Mean pixel area', 'Low-conf share', 'High-conf share', 'Night share', 'Mean FRP', 'Static-source share', 'Overpass (LST h)']}>
            {data.characteristics.map((c: any) => (
              <tr key={c.satellite}>
                <Td><span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-full" style={{ background: SAT_COLOR[c.satellite] }} />{c.label}</span></Td>
                <Td right>{num(c.detections)}</Td><Td right>{num(c.mean_pixel_area_km2, 2)} km²</Td><Td right>{pct(c.low_conf_share, 1)}</Td><Td right>{pct(c.high_conf_share, 1)}</Td>
                <Td right>{pct(c.night_share, 1)}</Td><Td right>{num(c.mean_frp_mw, 1)} MW</Td><Td right>{c.static_share_typed == null ? '–' : pct(c.static_share_typed, 1)}</Td><Td right>{c.nominal_overpass?.[0] ?? '–'}</Td>
              </tr>
            ))}
          </Table>
        </Panel>
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel title="Yearly detections where both sensors observed the full month" badge={<Prov kind="actual" />}>
            <Series data={data.yearly} x="year" monthly={false} height={260} bars={[{ key: 'terra', name: 'Terra', color: C.terra }, { key: 'aqua', name: 'Aqua', color: C.aqua }, { key: 'viirs', name: 'S-NPP VIIRS', color: C.viirs }]} />
          </Panel>
          <Panel title="VIIRS detections per Aqua detection, by month" sub="The ratio is strongly seasonal - one global factor would be wrong.">
            <StatusBars data={data.by_month.map((r: any) => ({ ...r, label: MONTHS[r.month - 1] }))} x="label" y="viirs_per_aqua" name="VIIRS / Aqua" yFmt={r2} colorOf={() => C.viirs} />
          </Panel>
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel title="Year-to-year ratios" pad={false}>
            <Table headers={['Year', 'VIIRS / Aqua', 'Aqua / Terra']}>
              {data.yearly.map((y: any) => <tr key={y.year}><Td>{y.year}</Td><Td right>{r2(y.viirs_per_aqua)}</Td><Td right>{r2(y.aqua_per_terra)}</Td></tr>)}
            </Table>
          </Panel>
          <Panel title="State × month cells: Aqua vs VIIRS (log-log)" badge={<Prov kind="actual" />}>
            <LogScatter data={data.scatter || []} xName="Aqua MODIS detections" yName="S-NPP VIIRS detections" color={C.viirs} height={300} />
          </Panel>
        </div>
      </>}
    </Load>
  )
}

function HarmCalib({ split }: { split: number | null }) {
  const { meta } = useApp()
  const [state, setState] = useState('')
  const q = [split ? `split=${split}` : '', state ? `state=${enc(state)}` : ''].filter(Boolean).join('&')
  const { data, loading, error } = useApi<any>(`/api/sensor-harmonizer/calibration${q ? `?${q}` : ''}`)
  return (
    <Load loading={loading} error={error} data={data} what="calibration model">
      {data && <>
        <Banner tone="info" title="Product choice">{data.product_note} {data.other_viirs}</Banner>
        <FitNotes notes={data.calibration?.notes} />
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel title={`${data.calibration?.pair} - learned ratio by month`} badge={<Prov kind="veq" text="Learned relationship" />} sub={data.calibration?.model}
            actions={<select aria-label="State" value={state} onChange={(e) => setState(e.target.value)}><option value="">National</option>{meta?.states?.map((s) => <option key={s}>{s}</option>)}</select>}>
            <RatioByMonth byMonth={data.calibration?.by_month || []} yLabel="VIIRS / Aqua" />
          </Panel>
          <Panel title="Leave-one-year-out skill by month" sub={`${data.calibration?.loyo?.n_years ?? '–'} calibration years, each withheld in turn.`} pad={false}>
            <Table headers={['Month', 'WAPE', 'Bias', 'Mean actual']}>
              {(data.calibration?.loyo?.by_month || []).map((r: any) => <tr key={r.moy}><Td>{MONTHS[r.moy - 1]}</Td><Td right>{pct(r.wape, 1)}</Td><Td right>{pct(r.bias, 1)}</Td><Td right>{num(r.mean_actual)}</Td></tr>)}
            </Table>
          </Panel>
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel title="Calibration table" sub={data.calibration?.band} pad={false}><div className="max-h-96 overflow-y-auto"><CalibTable byMonth={data.calibration?.by_month || []} /></div></Panel>
          <Panel title="State calibration factors (VIIRS / Aqua)" pad={false}><div className="max-h-96 overflow-y-auto"><StateFactors rows={data.state_factors || []} label="VIIRS / Aqua" /></div></Panel>
        </div>
      </>}
    </Load>
  )
}

/* ================================================================== 05 Uncertainty */
export function UncertaintyPage() {
  const { region } = useApp()
  const [split, setSplit] = useState<number | null>(null)
  const { data, loading, error } = useApi<any>(`/api/uncertainty?region=${enc(region)}${split ? `&split=${split}` : ''}`)
  const rows = useMemo(() => withBand(data?.series || [], 'band', 'veq_lo', 'veq_hi'), [data])
  return (
    <div className="space-y-5">
      <PageHead idx="05" title="Uncertainty Estimation" badges={<Prov kind="veq" />}
        intro="Both calibration steps are refitted on block-bootstrap resamples of whole years. The band is a resampling range (5th–95th percentile), not a formal confidence interval; its empirical coverage on withheld data is reported."
        actions={<SplitPicker value={split} onChange={setSplit} allowOperational />} />
      <Load loading={loading} error={error} data={data} what="uncertainty">
        {data && <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <ArgonStatCard title="Band coverage (VIIRS withheld)" value={data.band_coverage_pct == null ? '–' : `${num(data.band_coverage_pct, 0)}%`} subValue="share of withheld months whose actual value fell inside the 90% band" provenance="Harmonized Estimate" />
            <ArgonStatCard title="Band coverage (Aqua withheld)" value={data.morning_gap_band_coverage_pct == null ? '–' : `${num(data.morning_gap_band_coverage_pct, 0)}%`} subValue="morning-gap step" provenance="Harmonized Estimate" />
            {Object.entries(data.median_relative_width_by_stage || {}).map(([k, v]) => (
              <ArgonStatCard key={k} title={`Median band width - ${k}`} value={pct(v as number, 0)} subValue="(hi − lo) / central estimate" provenance="Harmonized Estimate" />
            ))}
          </div>
          <FitNotes notes={data.notes} />
          <Panel title={`Central estimate with uncertainty band - ${data.region}`} badge={<Prov kind="veq" />}>
            <Series data={rows} height={300} bands={[{ key: 'band', name: '5–95% bootstrap range', color: C.est }]}
              lines={[{ key: 'veq', name: 'VIIRS-equivalent estimate', color: C.est }, { key: 'viirs', name: 'Actual S-NPP VIIRS', color: C.viirs, width: 1.5 }]} />
          </Panel>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Uncertainty trend over time" sub="Median relative band width and mean Aqua coverage by year (both fractions).">
              <Series data={data.by_year} x="year" monthly={false} height={240} yFmt={pf} bars={[{ key: 'rel_width', name: 'Median relative width', color: C.est }]} lines={[{ key: 'coverage', name: 'Aqua coverage', color: C.aqua, dots: true }]} />
            </Panel>
            <Panel title="Relative band width by calendar month" sub="Low-activity months have wider relative bands.">
              <StatusBars data={data.by_month.map((r: any) => ({ ...r, label: MONTHS[r.month - 1] }))} x="label" y="rel_width" name="Median relative width" yFmt={pf} colorOf={(r) => (r.rel_width > 1 ? TIER_COLOR.HIGH : r.rel_width > 0.6 ? TIER_COLOR.MODERATE : C.est)} />
            </Panel>
          </div>
          <Panel title={`Weak calibration relationships (${data.weak_calibrations.length})`} sub="Month × pass combinations flagged unreliable (too few predictor detections or unstable ratio). Estimates that depend on them are less trustworthy." pad={false}>
            {data.weak_calibrations.length === 0 ? <p className="p-4 text-xs text-emerald-300">No weak relationships flagged.</p> : (
              <Table headers={['Step', 'Month', 'Pass', 'Ratio', 'Band', 'Predictor detections']}>
                {data.weak_calibrations.map((w: any, i: number) => (
                  <tr key={i} className="bg-red-500/5"><Td>{w.pair === 'mg' ? 'Terra→Aqua' : 'Aqua→VIIRS'}</Td><Td>{MONTHS[w.moy - 1]}</Td><Td>{titleCase(w.daynight)}</Td><Td right>{r2(w.ratio)}</Td><Td mono>{r2(w.ratio_lo)} – {r2(w.ratio_hi)}</Td><Td right>{num(w.predictor_detections)}</Td></tr>
                ))}
              </Table>
            )}
          </Panel>
          <Panel title="Method">
            <ol className="list-decimal space-y-1.5 pl-5 text-xs text-slate-300">{data.method.map((m: string, i: number) => <li key={i}>{m}</li>)}</ol>
          </Panel>
        </>}
      </Load>
    </div>
  )
}

/* ================================================================== 06 Validation & Seam Test */
export function ValidationPage() {
  const { region } = useApp()
  const [split, setSplit] = useState<number | null>(null)
  const [win, setWin] = useState(24)
  const sp = split ? `&split=${split}` : ''
  const v = useApi<any>(`/api/validation?region=${enc(region)}${sp}`)
  const s = useApi<any>(`/api/validation/seam-test?region=${enc(region)}${sp}&window=${win}`)
  const d = v.data, sm = s.data
  const vrows = useMemo(() => (d?.series || []).map((r: any) => ({ ...r, band: r.veq_lo == null ? null : [r.veq_lo, r.veq_hi], test: r.withheld_viirs ? r.viirs : null, train: r.withheld_viirs ? null : r.viirs })), [d])
  return (
    <div className="space-y-5">
      <PageHead idx="06" title="Validation & 2012 Seam Test" badges={<Prov kind="experiment" />}
        intro="Chronological hold-out: the calibration is trained only on years from the split onward, and the earlier months - where real VIIRS and Aqua exist - are withheld and predicted. No random splits, so no temporal leakage."
        actions={<SplitPicker value={split} onChange={setSplit} />} />
      <Load loading={v.loading} error={v.error} data={d} what="hold-out validation">
        {d && <>
          <StatusBanner status={d.status} rule={d.status_rule} what="Harmonization hold-out result" />
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <ArgonStatCard title="WAPE (held-out)" value={`${num(d.overall?.wape_pct, 1)}%`} subValue={`constant-ratio baseline ${num(d.baseline_constant_ratio?.wape_pct, 1)}% · raw MODIS ${num(d.baseline_raw_modis?.wape_pct, 1)}%`} provenance="Harmonized Estimate" />
            <ArgonStatCard title="Bias" value={`${num(d.overall?.bias_pct, 1)}%`} subValue={`${d.overall?.n ?? '–'} withheld months`} provenance="Harmonized Estimate" />
            <ArgonStatCard title="MAE / RMSE" value={`${compact(d.overall?.mae)} / ${compact(d.overall?.rmse)}`} subValue={`detections per month (mean actual ${compact(d.overall?.mean_actual)})`} provenance="Harmonized Estimate" />
            <ArgonStatCard title="Band coverage" value={d.band_coverage_pct == null ? '–' : `${num(d.band_coverage_pct, 0)}%`} subValue="target ≈ 90% for a 5–95% band" provenance="Harmonized Estimate" />
          </div>
          <FitNotes notes={d.notes} />
          <Panel title={`Withheld period: estimate vs actual VIIRS - ${d.region}`} badge={<Prov kind="experiment" />}
            sub={`Training years ${d.train_years?.[0] ?? '–'}–${d.train_years?.slice(-1)[0] ?? '–'}. Test months ${String(d.test_period?.[0] ?? '').slice(0, 4)}–${String(d.test_period?.[1] ?? '').slice(0, 4)}; Terra-only simulation up to ${d.terra_only_end ?? '–'}.`}>
            <Series data={vrows} height={300} bands={[{ key: 'band', name: 'Estimate band', color: C.est }]}
              lines={[{ key: 'test', name: 'Actual VIIRS (withheld)', color: C.viirs, width: 2.5 }, { key: 'train', name: 'Actual VIIRS (training)', color: C.viirs, dash: '2 3', width: 1 },
                { key: 'veq', name: 'Harmonized estimate', color: C.est, dash: '5 3' }, { key: 'modis_total', name: 'Raw MODIS', color: C.terra, width: 1 }]} />
          </Panel>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Hold-out metrics vs baselines" pad={false}>
              <MetricsTable rows={[{ name: <strong>PyroScope harmonization</strong>, m: d.overall }, { name: 'One constant ratio', m: d.baseline_constant_ratio }, { name: 'Raw MODIS (no conversion)', m: d.baseline_raw_modis },
                { name: '· from Aqua (sensor step)', m: d.by_stage?.sensor_calibrated }, { name: '· from Terra only (both steps)', m: d.by_stage?.morning_gap_sensor }, { name: 'Morning-gap step (Aqua withheld)', m: d.morning_gap?.metrics }]} />
            </Panel>
            <Panel title="Monthly calibration performance (WAPE)" sub="Colour reinforces the good / moderate / poor rule; values are labelled.">
              <StatusBars data={(d.by_month || []).map((r: any) => ({ ...r, label: MONTHS[r.month - 1] }))} x="label" y="wape_pct" name="WAPE %" yFmt={(x) => `${Math.round(x)}%`}
                colorOf={(r) => (r.wape_pct <= 20 ? TIER_COLOR.LOW : r.wape_pct <= 40 ? TIER_COLOR.MODERATE : TIER_COLOR.VERY_HIGH)} />
            </Panel>
          </div>
          <Panel title="Yearly totals in the withheld period" pad={false}>
            <Table headers={['Year', 'Actual VIIRS', 'Estimate', 'Band', 'Raw MODIS', 'Error']}>
              {(d.by_year || []).map((y: any) => <tr key={y.year}><Td>{y.year}</Td><Td right>{num(y.actual)}</Td><Td right>{num(y.estimate)}</Td><Td mono>{num(y.lo)} – {num(y.hi)}</Td><Td right>{num(y.raw_modis)}</Td><Td right>{pct((y.estimate - y.actual) / y.actual, 1)}</Td></tr>)}
            </Table>
          </Panel>
        </>}
      </Load>
      <Load loading={s.loading} error={s.error} data={sm} what="seam test">
        {sm && <Panel title={`Seam test at ${sm.seam_month?.slice(0, 7)}`} badge={sm.mode === 'simulated' ? <Prov kind="experiment" text="Simulated seam (real data withheld)" /> : <Prov kind="actual" text="Real 2012 seam" />}
          actions={<label className="flex items-center gap-2 text-xs text-slate-400">Window<select value={win} onChange={(e) => setWin(Number(e.target.value))}>{[12, 24, 36].map((w) => <option key={w} value={w}>{w} months</option>)}</select></label>}
          sub={sm.explanation}>
          <div className="space-y-4">
            {!sm.real_seam_possible && <Banner tone="info" title="Why the seam is simulated">{sm.real_seam_note}</Banner>}
            <StatusBanner status={sm.status} rule={sm.status_rule} what="Seam result" />
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <ArgonStatCard title="Step before harmonization" value={`×${r2(sm.step_raw)}`} subValue={`artificial jump ${r2(sm.artificial_jump_before)} ln-units`} provenance="Actual Observation" />
              <ArgonStatCard title="Step after harmonization" value={`×${r2(sm.step_harmonized)}`} subValue={`band ×${r2(sm.step_harmonized_band?.[0])}–×${r2(sm.step_harmonized_band?.[1])}; residual ${r2(sm.artificial_jump_after)} ln`} provenance="Harmonized Estimate" />
              <ArgonStatCard title="Genuine change (reference)" value={`×${r2(sm.step_true ?? sm.step_reference_sensor)}`} subValue={`${sm.reference_sensor} across the same seam - real changes must be kept`} provenance="Actual Observation" />
              <ArgonStatCard title="Artificial jump removed" value={`${num(sm.reduction_pct, 0)}%`} provenance="Harmonized Estimate" />
            </div>
            <Series data={sm.series} height={280} refs={[{ x: sm.seam_month, label: 'seam' }]}
              lines={[{ key: 'modis_total', name: 'Original MODIS', color: C.terra }, { key: 'viirs', name: 'Actual VIIRS', color: C.viirs }, { key: 'harmonized', name: 'Harmonized record', color: C.est, dash: '5 3', width: 2.5 }]} />
            <p className="text-xs text-slate-400">The goal is to remove the sensor-related jump, not to make the line smooth: the harmonized step should match the genuine change seen by a single unchanged sensor.</p>
          </div>
        </Panel>}
      </Load>
    </div>
  )
}

/* ================================================================== 07 Burning Activity Calendar */
const CAL_SOURCES = [{ value: 'Suomi NPP', label: 'S-NPP VIIRS' }, { value: 'NOAA-21', label: 'NOAA-21' }, { value: 'NOAA-20', label: 'NOAA-20' }, { value: 'Aqua', label: 'Aqua' }, { value: 'Terra', label: 'Terra' }, { value: 'veq', label: 'VIIRS-equivalent' }]
const HATCH = 'repeating-linear-gradient(45deg,#1f2a40,#1f2a40 2px,#0B0F19 2px,#0B0F19 4px)'
export function CalendarPage() {
  const { region } = useApp()
  const [year, setYear] = useState<number | null>(null)
  const [src, setSrc] = useState('Suomi NPP')
  const [metric, setMetric] = useState<'count' | 'frp'>('count')
  const { data, loading, error } = useApi<any>(`/api/calendar?region=${enc(region)}${year ? `&year=${year}` : ''}`)
  const days: any[] = useMemo(() => data?.days || [], [data])
  const frp = metric === 'frp' && src !== 'veq'
  const val = (d: any) => (src === 'veq' ? d.veq : frp ? d[`${src}|frp`] : d[src])
  const max = useMemo(() => Math.max(1, ...days.map((d) => Number(val(d)) || 0)), [days, src, metric]) // eslint-disable-line react-hooks/exhaustive-deps
  const weeks = useMemo(() => {
    if (!days.length) return [] as any[][]
    const first = new Date(days[0].date + 'T00:00:00Z').getUTCDay()
    const cells: any[] = Array(first).fill(null).concat(days)
    const out: any[][] = []
    for (let i = 0; i < cells.length; i += 7) out.push(cells.slice(i, i + 7))
    return out
  }, [days])
  const monthRows = useMemo(() => withBand((data?.months || []).map((m: any) => ({ ...m, label: MONTHS[m.month - 1] })), 'band', 'veq_lo', 'veq_hi'), [data])
  return (
    <div className="space-y-5">
      <PageHead idx="07" title="Burning Activity Calendar" badges={<><Prov kind="actual" />{src === 'veq' && <Prov kind="veq" />}</>}
        intro="Daily, monthly and yearly activity per sensor. A day the sensor did not observe is shown as missing (hatched), never as zero fire."
        actions={<>
          <select aria-label="Year" value={year ?? data?.year ?? ''} onChange={(e) => setYear(Number(e.target.value))}>{(data?.years_available || []).map((y: number) => <option key={y} value={y}>{y}</option>)}</select>
          <Tabs value={src} onChange={setSrc} options={CAL_SOURCES} />
          {src !== 'veq' && <Tabs value={metric} onChange={setMetric} options={[{ value: 'count', label: 'Detections' }, { value: 'frp', label: 'FRP (MW)' }]} />}
        </>} />
      <Load loading={loading} error={error} data={data} what="calendar">
        {data && <>
          <Panel title={`${data.region} · ${data.year} · ${src === 'veq' ? 'VIIRS-equivalent (actual VIIRS where observed)' : SAT_LABEL[src]} ${frp ? 'FRP' : 'detections'}`} sub={data.note}>
            <div className="overflow-x-auto">
              <div className="flex gap-[3px]" aria-label="Daily activity heatmap">
                <div className="mr-1 flex flex-col gap-[3px] pt-4 text-[9px] text-slate-500">{['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, i) => <span key={i} className="h-3 leading-3">{d}</span>)}</div>
                {weeks.map((w, wi) => {
                  const firstOfMonth = w.find((d) => d && d.date.slice(8) === '01')
                  return (
                    <div key={wi} className="flex flex-col gap-[3px]">
                      <span className="h-3 text-[9px] leading-3 text-slate-500">{firstOfMonth ? MONTHS[Number(firstOfMonth.date.slice(5, 7)) - 1] : ''}</span>
                      {Array.from({ length: 7 }, (_, di) => {
                        const d = w[di]
                        if (!d) return <span key={di} className="h-3 w-3" />
                        const v = val(d)
                        const status = src === 'veq' ? d.provenance : d[`${src}|status`]
                        const missing = v === null || v === undefined
                        const tip = `${d.date}: ${missing ? `no observation (${status || 'outside record'})` : `${num(v, frp ? 1 : 0)}${frp ? ' MW' : ' detections'}`}${src === 'veq' && !missing ? ` - ${d.provenance}` : ''}`
                        return <span key={di} title={tip} className="h-3 w-3 rounded-[2px]"
                          style={missing ? { background: HATCH } : { background: Number(v) > 0 ? seq(Number(v), max) : '#172033', outline: src === 'veq' && d.provenance !== 'actual_viirs' ? '1px solid #c98500' : undefined }} />
                      })}
                    </div>
                  )
                })}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] text-slate-400">
              <span className="flex items-center gap-1">0 <i className="inline-block h-3 w-3 rounded-[2px] bg-[#172033]" /></span>
              <span className="flex items-center gap-1">low {[0.05, 0.2, 0.5, 1].map((f) => <i key={f} className="inline-block h-3 w-3 rounded-[2px]" style={{ background: seq(max * f, max) }} />)} high ({compact(max)})</span>
              <span className="flex items-center gap-1"><i className="inline-block h-3 w-3 rounded-[2px]" style={{ background: HATCH }} /> not observed (missing ≠ zero)</span>
              {src === 'veq' && <span className="flex items-center gap-1"><i className="inline-block h-3 w-3 rounded-[2px]" style={{ outline: '1px solid #c98500' }} /> estimate</span>}
            </div>
          </Panel>
          <Panel title="Monthly comparison: original sensors vs harmonized record" badge={<><Prov kind="actual" /><Prov kind="veq" /></>}
            sub="Bars = actual detections per sensor. Amber line = harmonized record (actual VIIRS where complete, otherwise VIIRS-equivalent estimate) with band.">
            <Series data={monthRows} x="label" monthly={false} height={280} bands={[{ key: 'band', name: 'VIIRS-eq. band', color: C.est }]}
              bars={[{ key: 'terra', name: 'Terra', color: C.terra }, { key: 'aqua', name: 'Aqua', color: C.aqua }, { key: 'viirs', name: 'S-NPP VIIRS', color: C.viirs }]}
              lines={[{ key: 'harmonized', name: 'Harmonized', color: C.est, dots: true }]} />
          </Panel>
          <Panel title="Monthly coverage" sub="Fraction of days each sensor was observing - read every bar together with its coverage." pad={false}>
            <Table headers={['Month', 'Terra cov.', 'Aqua cov.', 'VIIRS cov.', 'Provenance']}>
              {(data.months || []).map((m: any) => <tr key={m.month}><Td>{MONTHS[m.month - 1]}</Td><Td right>{pct(m.cov_terra)}</Td><Td right>{pct(m.cov_aqua)}</Td><Td right>{pct(m.cov_viirs)}</Td><Td><Prov kind={m.provenance === 'actual_viirs' ? 'actual' : 'veq'} text={titleCase(m.provenance)} /></Td></tr>)}
            </Table>
          </Panel>
        </>}
      </Load>
    </div>
  )
}

/* ================================================================== 08 Historical Trends */
export function TrendsPage() {
  const { region, setRegion } = useApp()
  const [level, setLevel] = useState<'state' | 'district'>('state')
  const { data, loading, error } = useApi<any>(`/api/historical-trends?region=${enc(region)}`)
  const reg = useApi<any>(`/api/historical-trends/regions?level=${level}`)
  const monthly = useMemo(() => withBand(data?.monthly || [], 'band', 'harm_lo', 'harm_hi'), [data])
  const yearly = useMemo(() => withBand((data?.yearly || []).filter((y: any) => y.complete), 'band', 'harm_lo', 'harm_hi'), [data])
  const seasonal = useMemo(() => withBand(data?.seasonal || [], 'band', 'harmonized_p10', 'harmonized_p90'), [data])
  const t = data?.trend_harmonized
  return (
    <div className="space-y-5">
      <PageHead idx="08" title="Historical Fire Trends" badges={<><Prov kind="actual" /><Prov kind="veq" /></>}
        intro="Long-term monthly, yearly and seasonal activity on the harmonized VIIRS-equivalent scale, FRP per sensor, and regional comparisons. Select a region in the top bar or click a row below." />
      <Load loading={loading} error={error} data={data} what="trends">
        {data && <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <ArgonStatCard title="Historical average / year" value={compact(data.historical_average_per_year)} subValue="harmonized, complete years" provenance="Harmonized Estimate" />
            <ArgonStatCard title="Linear trend" value={t ? `${t.pct_per_year >= 0 ? '+' : ''}${num(t.pct_per_year, 1)}% / yr` : '–'} subValue={t ? `${t.significant_95 ? 'significant' : 'NOT significant'} at 95% (t = ${num(t.t_stat, 2)}, ${t.n_years} yrs)` : ''} provenance="Harmonized Estimate" />
            <ArgonStatCard title="Peak month" value={data.peak_month} subValue={`${pct(data.peak_month_share)} of annual activity`} provenance="Harmonized Estimate" />
            <ArgonStatCard title="Years on record" value={num(data.yearly?.length)} subValue={`${(data.yearly || []).filter((y: any) => !y.complete).length} incomplete year(s) excluded from trend`} provenance="Actual Observation" />
          </div>
          <Panel title={`Yearly activity - ${data.region}`} sub={data.trend_note} badge={<Prov kind="veq" />}>
            <Series data={yearly} x="year" monthly={false} height={260} bands={[{ key: 'band', name: 'Harmonized band', color: C.est }]}
              bars={[{ key: 'harmonized', name: 'Harmonized (VIIRS-eq.)', color: C.est }]} lines={[{ key: 'viirs', name: 'Actual S-NPP VIIRS', color: C.viirs, dots: true }, { key: 'aqua', name: 'Aqua MODIS', color: C.aqua, dots: true }]} />
          </Panel>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Monthly harmonized record" badge={<Prov kind="veq" />}>
              <Series data={monthly} height={260} bands={[{ key: 'band', name: 'Band', color: C.est }]} lines={[{ key: 'harmonized', name: 'Harmonized', color: C.est }, { key: 'viirs', name: 'Actual VIIRS', color: C.viirs, width: 1 }]} />
            </Panel>
            <Panel title="Seasonal pattern" sub="Mean monthly activity with the 10th–90th percentile across years.">
              <Series data={seasonal} x="label" monthly={false} height={260} bands={[{ key: 'band', name: 'P10–P90', color: C.est }]}
                lines={[{ key: 'harmonized_mean', name: 'Harmonized mean', color: C.est, dots: true }, { key: 'aqua_mean', name: 'Aqua mean', color: C.aqua }, { key: 'terra_mean', name: 'Terra mean', color: C.terra }]} />
            </Panel>
          </div>
          <Panel title="Fire Radiative Power trends (per sensor, never pooled)" sub={data.frp_note} badge={<Prov kind="actual" />}>
            <Series data={data.monthly} height={240} yFmt={(v) => num(v, 0)} yLabel="mean FRP (MW)"
              lines={[{ key: 'frp_mean|Suomi NPP', name: 'S-NPP VIIRS mean FRP', color: C.viirs }, { key: 'frp_mean|Aqua', name: 'Aqua MODIS mean FRP', color: C.aqua }, { key: 'frp_mean|Terra', name: 'Terra MODIS mean FRP', color: C.terra }, { key: 'frp_mean|NOAA-21', name: 'NOAA-21 mean FRP', color: C.n21 }]} />
          </Panel>
        </>}
      </Load>
      <Panel title="Regional comparison" sub={reg.data?.sensor} actions={<Tabs value={level} onChange={setLevel} options={[{ value: 'state', label: 'States' }, { value: 'district', label: 'Districts' }]} />} pad={false}>
        <Load loading={reg.loading} error={reg.error} data={reg.data} what="regional comparison">
          <div className="max-h-[480px] overflow-y-auto">
            <Table headers={['Region', 'Mean / yr', 'per 1000 km²', 'Latest yr', 'Peak', 'Trend / yr', 'Mean FRP', '']}>
              {(reg.data?.items || []).map((r: any) => (
                <tr key={r.id} className={`hover:bg-[#172033]/60 ${r.id === region ? 'bg-orange-500/10' : ''}`}>
                  <Td>{r.name}</Td><Td right>{num(r.mean_per_year)}</Td><Td right>{num(r.per_1000km2)}</Td><Td right>{num(r.latest_year)}</Td><Td>{r.peak_month}</Td>
                  <Td right><span className={r.trend_significant ? 'font-semibold' : 'text-slate-500'}>{r.trend_pct_per_year >= 0 ? '+' : ''}{num(r.trend_pct_per_year, 1)}%{r.trend_significant ? '' : ' (n.s.)'}</span></Td>
                  <Td right>{num(r.frp_mean_mw, 1)} MW</Td>
                  <Td><Button size="xs" variant="outline" onClick={() => setRegion(r.id)}>Analyse</Button></Td>
                </tr>
              ))}
            </Table>
          </div>
        </Load>
      </Panel>
    </div>
  )
}

/* ================================================================== 09 Anomaly Detection */
const FLAG_COLOR: Record<string, string> = { high: TIER_COLOR.VERY_HIGH, low: '#3987e5', normal: '#475569' }
export function AnomaliesPage() {
  const { region, setRegion } = useApp()
  const [level, setLevel] = useState<'state' | 'district'>('state')
  const [win, setWin] = useState(30)
  const { data, loading, error, reload } = useApi<any>(`/api/anomalies?region=${enc(region)}&level=${level}&window_days=${win}`)
  const ser = data?.series
  const rows = useMemo(() => withBand(ser?.series || [], 'band', 'baseline_p10', 'baseline_p90'), [ser])
  const flagged = rows.filter((r: any) => r.flag === 'high' || r.flag === 'low')
  const cur = data?.current
  return (
    <div className="space-y-5">
      <PageHead idx="09" title="Anomaly Detection" badges={<Prov kind="actual" />}
        intro="Current activity is compared with the same calendar window in earlier years (seasonal baseline, robust z-score), cross-checked with rolling means and an isolation-forest score. An anomaly is an unusual satellite-observed pattern - not a confirmed wildfire."
        actions={<>
          <label className="flex items-center gap-2 text-xs text-slate-400">Window<select value={win} onChange={(e) => setWin(Number(e.target.value))}>{[7, 14, 30, 60, 90].map((w) => <option key={w} value={w}>{w} days</option>)}</select></label>
          <Tabs value={level} onChange={setLevel} options={[{ value: 'state', label: 'States' }, { value: 'district', label: 'Districts' }]} />
          <Button size="sm" variant="outline" onClick={reload}><RefreshCw className="h-3.5 w-3.5" />Refresh</Button>
        </>} />
      <Load loading={loading} error={error} data={data} what="anomalies">
        {data && <>
          <Banner tone="warning" title="Not a wildfire confirmation">{ser?.disclaimer}</Banner>
          <Panel title={`Monthly activity vs seasonal baseline - ${ser?.region}`} sub={ser?.method} badge={<Prov kind="actual" text="Actual S-NPP VIIRS" />}>
            <Series data={rows} height={280} bands={[{ key: 'band', name: 'Baseline P10–P90', color: '#64748b' }]}
              lines={[{ key: 'observed', name: 'Observed', color: C.viirs }, { key: 'baseline_median', name: 'Seasonal median', color: '#e2e8f0', dash: '4 3', width: 1.5 }, { key: 'rolling_12m', name: '12-month rolling mean', color: C.n20, width: 1 }]} />
          </Panel>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Robust z-score by month (last 4 years)" sub="|z| ≥ 2 flagged. Colour reinforces the flag; hover shows the value.">
              <Series data={rows.slice(-48)} height={220} yFmt={r2} yDomain={['auto', 'auto']} bars={[{ key: 'z', name: 'z-score', color: '#64748b' }]} refs={[{ y: 2, label: '+2' }, { y: -2, label: '−2' }]} />
            </Panel>
            <Panel title={`Flagged months (${flagged.length})`} pad={false}>
              <div className="max-h-72 overflow-y-auto">
                <Table headers={['Month', 'Observed', 'Seasonal median', 'z', 'Flag', 'Isolation forest', 'Coverage']}>
                  {flagged.slice().reverse().map((r: any) => (
                    <tr key={r.date}><Td mono>{r.date.slice(0, 7)}</Td><Td right>{num(r.observed)}</Td><Td right>{num(r.baseline_median)}</Td><Td right>{r2(r.z)}</Td>
                      <Td><span className="font-semibold uppercase" style={{ color: FLAG_COLOR[r.flag] }}>{r.flag === 'high' ? '▲ high' : '▼ low'}</span></Td>
                      <Td>{r.iforest_outlier ? 'outlier' : '–'}</Td><Td right>{pct(r.coverage)}</Td></tr>
                  ))}
                </Table>
              </div>
            </Panel>
          </div>
          <Panel title={`Unusual areas now - last ${win} days (${cur?.window?.[0] ?? '–'} → ${cur?.window?.[1] ?? '–'})`} badge={cur?.provisional_nrt ? <Prov kind="aux" text="Provisional NRT data" /> : undefined}
            sub={cur?.provisional_nrt ? cur?.nrt_note : cur?.disclaimer} pad={false}>
            {cur?.status !== 'ok' || !cur?.items?.length ? <p className="p-4 text-xs text-slate-400">{cur?.message || 'No region is outside its seasonal range in this window.'}</p> : (
              <Table headers={['Region', 'Current', 'Seasonal median', 'z', 'Direction', 'Contributing factors', '']}>
                {cur.items.map((it: any) => (
                  <tr key={it.id} className="hover:bg-[#172033]/60">
                    <Td>{it.name}</Td><Td right>{num(it.current)}</Td><Td right>{num(it.median)}</Td><Td right>{r2(it.z)}</Td>
                    <Td><span className="font-semibold uppercase" style={{ color: it.direction === 'above' ? TIER_COLOR.HIGH : '#3987e5' }}>{it.direction === 'above' ? '▲ above' : '▼ below'}</span></Td>
                    <Td><ul className="list-disc pl-4 text-[11px] text-slate-300">{(it.factors || []).map((f: string, i: number) => <li key={i}>{f}</li>)}</ul></Td>
                    <Td><Button size="xs" variant="outline" onClick={() => setRegion(it.id)}>Focus</Button></Td>
                  </tr>
                ))}
              </Table>
            )}
          </Panel>
        </>}
      </Load>
    </div>
  )
}
