/* Overview: what is in the archive, what the satellites saw in the most recent week, and the honest state of the
 * harmonization, event, forecast and alert layers. Every number is read from the API; nothing is defaulted to zero. */
import { useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, Database, RefreshCw } from 'lucide-react'
import { num, SAT_COLOR, SAT_LABEL, titleCase, useApi } from './lib'
import { BaseMap, PointLayer, Swatch } from './map'
import { Button, Card, CardBody, CardHeader, EmptyStateCard, ProvenanceBadge, Table } from './ui'
import type { AlertList, DashboardSummary, HotspotResponse, Hotspot } from './types'

const SENSORS = ['Terra', 'Aqua', 'Suomi NPP', 'NOAA-20', 'NOAA-21']
const MODIS = ['Terra', 'Aqua']
const VIIRS = ['Suomi NPP', 'NOAA-20', 'NOAA-21']
const addDays = (s: string, n: number) => { const d = new Date(`${s}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
type EventSummary = { events: number; status_counts: Record<string, number>; validation: string; last_run: null | { data_through: string } }

type Tone = 'ok' | 'warn' | 'bad' | 'na' | 'info'
const TONE: Record<Tone, string> = {
  ok: 'border-emerald-500/50 text-emerald-300', warn: 'border-amber-500/50 text-amber-300', bad: 'border-red-500/50 text-red-300',
  na: 'border-slate-600 text-slate-400', info: 'border-sky-500/50 text-sky-300',
}
export function StatusChip({ tone, children }: { tone: Tone; children: string }) {
  return <span className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${TONE[tone]}`}>{children}</span>
}
const verdictTone = (s?: string | null): Tone => {
  const v = (s || '').toLowerCase()
  if (!v) return 'na'
  if (['pass', 'good', 'ok', 'approved'].includes(v)) return 'ok'
  if (['fail', 'poor', 'failed'].includes(v)) return 'bad'
  return 'warn'
}

function Metric({ label, value, detail }: { label: string; value: string; detail: React.ReactNode }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-white">{value}</div>
      <div className="mt-1 text-xs leading-snug text-slate-400">{detail}</div>
    </div>
  )
}

function StatusRow({ label, chip, children, to }: { label: string; chip: React.ReactNode; children: React.ReactNode; to?: string }) {
  return (
    <li className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 border-b border-line/60 px-4 py-2.5 last:border-0">
      <div className="text-sm text-slate-100">{to ? <Link to={to} className="hover:underline">{label}</Link> : label}</div>
      <div className="justify-self-end">{chip}</div>
      <div className="col-span-2 text-xs leading-snug text-slate-400">{children}</div>
    </li>
  )
}

export function OverviewDashboardPage() {
  const navigate = useNavigate()
  const { data: summary, loading, error, reload } = useApi<DashboardSummary>('/api/dashboard/summary')
  const alerts = useApi<AlertList>('/api/alerts?open_only=true&limit=1')
  const events = useApi<EventSummary>('/api/events/summary')
  const end = summary?.data_end
  const start = end ? addDays(end, -6) : null
  const hs = useApi<HotspotResponse>(end && start ? `/api/hotspots?start=${start}&end=${end}&limit=4000` : null, [end])

  const sats = summary?.satellites || {}
  const sumOf = (keys: string[]) => keys.reduce((a, k) => a + Number(sats[k]?.detections || 0), 0)
  const loadedSensors = SENSORS.filter((s) => sats[s])
  const firsts = loadedSensors.map((s) => sats[s]?.first).filter(Boolean).sort() as string[]

  const topDistricts = useMemo(() => {
    const m = new Map<string, number>()
    for (const h of hs.data?.hotspots || []) {
      if (!h.district) continue
      const k = `${h.district}, ${h.state || ''}`
      m.set(k, (m.get(k) || 0) + 1)
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6)
  }, [hs.data])
  const maxFrp = useMemo(() => {
    let best: Hotspot | null = null
    for (const h of hs.data?.hotspots || []) if (h.frp_mw != null && (best == null || Number(h.frp_mw) > Number(best.frp_mw))) best = h
    return best
  }, [hs.data])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-xl font-semibold text-white">Overview</h1>
          <p className="mt-1 text-sm text-slate-400">
            Satellite active-fire records held by this deployment, the most recent week of observations, and the current state of harmonization, events, forecasts and alerts.
            Observations, harmonized estimates and model output are labelled separately.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => { reload(); alerts.reload(); events.reload(); hs.reload() }}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />Refresh
        </Button>
      </div>

      {loading && !summary && <Card><CardBody className="py-12 text-center text-sm text-slate-400">Loading archive summary…</CardBody></Card>}

      {!loading && (error || !summary) && (
        <EmptyStateCard title="No processed archive"
          description={<><code>GET /api/dashboard/summary</code> returned {error ? <span className="text-red-300">{error}</span> : 'no data'}. Load the repository FIRMS archives or upload a satellite CSV in Data Inventory.</>}
          action={<Button variant="primary" onClick={() => navigate('/data')}><Database className="h-4 w-4" aria-hidden="true" />Open Data Inventory</Button>} />
      )}

      {summary && (
        <>
          {/* Archive totals */}
          <Card>
            <div className="grid divide-y divide-line sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-4 xl:divide-x">
              <Metric label="Fire records ingested" value={num(summary.total_detections)}
                detail={<>Sum of FIRMS detections across {loadedSensors.length} sensor stream(s). Streams overlap in time, so this counts detections, not distinct fires.</>} />
              <Metric label="MODIS records" value={num(sumOf(MODIS))}
                detail={MODIS.map((s) => `${s} ${num(sats[s]?.detections ?? null)}`).join(' · ')} />
              <Metric label="VIIRS records" value={num(sumOf(VIIRS))}
                detail={VIIRS.map((s) => `${s === 'Suomi NPP' ? 'S-NPP' : s} ${num(sats[s]?.detections ?? null)}`).join(' · ')} />
              <Metric label="Archive coverage" value={summary.data_end || '–'}
                detail={<>From {firsts[0] || '–'} · last observation date.{summary.missing_sensors?.length ? <span className="text-amber-300"> Not loaded: {summary.missing_sensors.join(', ')}.</span> : ''}</>} />
            </div>
            <div className="flex items-center justify-end border-t border-line px-4 py-1.5"><ProvenanceBadge type="Actual Observation" /></div>
          </Card>

          {/* Map + recent activity */}
          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title={`Active-fire detections · ${start || '–'} to ${end || '–'}`}
                subtitle={hs.data ? (hs.data.thinned ? `Showing ${num(hs.data.returned)} of ${num(hs.data.total_matching)} detections (evenly thinned by the server).` : `${num(hs.data.total_matching)} detections in the last seven days of the archive.`) : hs.error ? `Could not load detections: ${hs.error}` : 'Loading detections…'}
                badge={<ProvenanceBadge type="Actual Observation" />}
                actions={<Link to="/map" className="inline-flex items-center gap-1 text-xs text-sky-300 hover:underline">Open Fire Map<ArrowRight className="h-3 w-3" aria-hidden="true" /></Link>} />
              <BaseMap height={420}>
                <PointLayer points={hs.data?.hotspots || []} colorOf={(p) => SAT_COLOR[p.satellite] || '#94a3b8'} isSquare={() => false} radius={2.6}
                  popup={(p) => `<b>${SAT_LABEL[p.satellite] || p.satellite}</b><br/>${p.timestamp_utc || ''}<br/>FRP ${p.frp_mw == null ? 'n/a' : `${num(p.frp_mw, 1)} MW`} · conf. ${p.confidence_raw ?? '–'}<br/>${p.district || ''} ${p.state || ''}`} />
              </BaseMap>
              <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-4 py-2" aria-label="Map legend">
                {SENSORS.filter((s) => sats[s]).map((s) => <Swatch key={s} color={SAT_COLOR[s]} label={SAT_LABEL[s]} />)}
              </div>
            </Card>

            <div className="space-y-4">
              <Card>
                <CardHeader title="Last 7 days by sensor" subtitle="Detections, peak FRP and distinct 0.25° grid cells." />
                <CardBody noPadding>
                  <Table headers={['Sensor', 'Detections', 'Peak FRP', 'Cells']}>
                    {SENSORS.filter((s) => sats[s]).map((s) => {
                      const r = summary.last7?.[s]
                      return (
                        <tr key={s}>
                          <td className="px-3 py-1.5"><Swatch color={SAT_COLOR[s]} label={SAT_LABEL[s]} /></td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{r ? num(r.detections) : <span className="text-slate-500">none</span>}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{r?.frp_max != null ? `${num(r.frp_max, 0)} MW` : '–'}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{r ? num(r.cells) : '–'}</td>
                        </tr>
                      )
                    })}
                  </Table>
                  <p className="px-3 py-2 text-[11px] text-slate-500">"none" means no records for that sensor in the window — check Data Inventory before reading it as no fire.</p>
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Most active districts" subtitle={hs.data?.thinned ? 'Ranked within the displayed (thinned) sample.' : 'Detections in the same seven-day window.'} />
                <CardBody noPadding>
                  {topDistricts.length ? (
                    <ol className="divide-y divide-line/60 text-sm">
                      {topDistricts.map(([d, n], i) => (
                        <li key={d} className="flex items-center justify-between gap-2 px-4 py-1.5"><span className="min-w-0 truncate"><span className="mr-2 text-slate-500 tabular-nums">{i + 1}</span>{d}</span><span className="tabular-nums text-slate-300">{num(n)}</span></li>
                      ))}
                    </ol>
                  ) : <p className="px-4 py-3 text-xs text-slate-500">{hs.loading ? 'Loading…' : 'No district-attributed detections in this window.'}</p>}
                  {maxFrp && <p className="border-t border-line px-4 py-2 text-xs text-slate-400">Highest FRP: <span className="tabular-nums text-slate-200">{num(maxFrp.frp_mw, 1)} MW</span> · {SAT_LABEL[maxFrp.satellite] || maxFrp.satellite} · {maxFrp.district || '–'} · {maxFrp.timestamp_utc}</p>}
                </CardBody>
              </Card>
            </div>
          </div>

          {/* Status of derived layers */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="Science & model status" subtitle="Verdicts computed by the backend on held-out data." />
              <ul>
                <StatusRow label="MODIS → VIIRS harmonization (hold-out)" to="/validation"
                  chip={<StatusChip tone={verdictTone(summary.validation?.status)}>{summary.validation?.status ? titleCase(summary.validation.status) : 'Not run'}</StatusChip>}>
                  {summary.validation?.band_coverage_pct != null ? `Empirical 95% interval coverage ${num(summary.validation.band_coverage_pct, 1)}%.` : 'No hold-out result available.'}
                </StatusRow>
                <StatusRow label="2012 sensor-transition seam test" to="/validation"
                  chip={<StatusChip tone={verdictTone(summary.seam?.status)}>{summary.seam?.status ? titleCase(summary.seam.status) : 'Not run'}</StatusChip>}>
                  {summary.seam?.reduction_pct != null ? `Seam step reduced by ${num(summary.seam.reduction_pct, 1)}% at ${summary.seam.seam_month || '2012-01'}.` : 'No seam result available.'}
                </StatusRow>
                <StatusRow label="7-day fire forecast" to="/forecast"
                  chip={summary.forecast ? <StatusChip tone="info">Model · experimental</StatusChip> : <StatusChip tone="na">Not trained</StatusChip>}>
                  {summary.forecast
                    ? <>Issued {summary.forecast.issue_date || '–'} · test Brier {num(summary.forecast.brier, 4)} · ROC-AUC {num(summary.forecast.roc_auc, 3)} · {num(summary.forecast.cells_high)} cells ≥60% and {num(summary.forecast.cells_very_high)} ≥80%. Model output, not an official warning.</>
                    : 'No trained forecast model is loaded.'}
                </StatusRow>
                {summary.validation_error && (
                  <StatusRow label="Validation pipeline" chip={<StatusChip tone="bad">Error</StatusChip>}>{summary.validation_error}</StatusRow>
                )}
              </ul>
            </Card>
            <Card>
              <CardHeader title="Events & alerts" subtitle="Operational layers derived from the observations." />
              <ul>
                <StatusRow label="Fire events (clustered detections)" to="/events"
                  chip={events.data ? <StatusChip tone={events.data.events ? 'warn' : 'na'}>{events.data.events ? 'Not independently validated' : 'None built'}</StatusChip> : <StatusChip tone="na">{events.error ? 'Unavailable' : '…'}</StatusChip>}>
                  {events.data
                    ? <>{num(events.data.events)} events{Object.keys(events.data.status_counts || {}).length ? ` (${Object.entries(events.data.status_counts).map(([k, v]) => `${titleCase(k)} ${num(v)}`).join(', ')})` : ''}{events.data.last_run ? ` · data through ${events.data.last_run.data_through}` : ''}.</>
                    : events.error || 'Loading…'}
                </StatusRow>
                <StatusRow label="Open alerts" to="/alerts"
                  chip={alerts.data ? <StatusChip tone={alerts.data.total ? 'warn' : 'ok'}>{`${num(alerts.data.total)} open`}</StatusChip> : <StatusChip tone="na">{alerts.error ? 'Unavailable' : '…'}</StatusChip>}>
                  {alerts.data ? 'Alerts in the review queue. External notifications are simulated unless a provider is configured.' : alerts.error || 'Loading…'}
                </StatusRow>
              </ul>
            </Card>
          </div>

          {/* Sensor inventory */}
          {loadedSensors.length > 0 && (
            <Card>
              <CardHeader title="Sensor inventory" subtitle="Temporal coverage and gaps per instrument stream." badge={<ProvenanceBadge type="Actual Observation" />} />
              <CardBody noPadding>
                <Table headers={['Sensor', 'First', 'Last', 'Days in span', 'Days with detections', 'Gap days', 'Detections']}>
                  {loadedSensors.map((s) => {
                    const info = sats[s]!
                    return (
                      <tr key={s}>
                        <td className="px-3 py-2"><Swatch color={SAT_COLOR[s]} label={info.label || SAT_LABEL[s]} /></td>
                        <td className="px-3 py-2 font-mono text-xs">{info.first || '–'}</td>
                        <td className="px-3 py-2 font-mono text-xs">{info.last || '–'}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{num(info.days_in_span)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{num(info.days_with_detections)}</td>
                        <td className={`px-3 py-2 text-right tabular-nums ${Number(info.gap_days) ? 'text-amber-300' : ''}`}>{num(info.gap_days)}</td>
                        <td className="px-3 py-2 text-right font-medium tabular-nums text-white">{num(info.detections)}</td>
                      </tr>
                    )
                  })}
                </Table>
              </CardBody>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
