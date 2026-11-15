/* Fire intelligence screens: fire events, burned area, emissions, smoke transport, geostationary / diurnal,
 * external validation, background jobs and deployment health. Every value comes from the backend; empty or
 * blocked products are shown as such and never filled with placeholder data. */
import { useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Polygon, Polyline } from 'react-leaflet'
import { Bar, BarChart, CartesianGrid, Legend, Line, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, Btn, C, Card, compact, Note, num, Page, Stat, State, titleCase, useApi, useApp } from './lib'
import { BaseMap, PointLayer, Swatch } from './map'

/* ------------------------------------------------------------------ contracts */
interface EventRow {
  event_id: string; status: string; first_detection: string; last_detection: string; n_obs: number; n_days: number; platforms: Record<string, number>
  lat: number; lon: number; footprint_km2: number; peak_frp_mw: number | null; sum_frp_mw: number; confidence_mean: number | null; evidence: string
  land_use: string | null; state: string | null; district_id: string | null; merged_into: string | null; split_from: string | null; truncated_start: boolean
}
interface EventList { total: number; limit: number; offset: number; items: EventRow[] }
interface DayRow { date: string; detections: number; sensors: string[]; frp_sum_mw: number; frp_max_mw: number; footprint_km2: number; cumulative_footprint_km2: number }
interface EventDetail extends EventRow {
  est_start_earliest: string; est_end_latest: string | null; sensor_families: string[]; footprint_centres_km2: number
  footprint_geojson: { type: string; coordinates: number[][][] }; fre_mj_low: number | null; fre_mj_high: number | null
  confidence_counts: Record<string, number>; multi_sensor_day_share: number; day_count: number; night_count: number; gap_days: number
  sensor_days_since_last: number; end_basis: string | null; method: string; west: number; south: number; east: number; north: number
  growth: { span_days: number; apparent_movement_km: number; apparent_bearing_deg: number | null; footprint_growth_km2_per_day: number | null; note: string }
  interpretation: Record<string, string>; history: { action: string; related_event_id: string | null; at: string }[]
  geostationary_agreement: { class: string; note?: string; geo_pixels: number }
  timeline?: DayRow[]
}
interface EventSummary { events: number; status_counts: Record<string, number>; method: string; validation: string; last_run: null | { start: string; end: string; detections: number; events: number; data_through: string; multi_sensor_events: number; single_detection_events: number; seconds: number; parameters: Record<string, unknown> } }
interface Obs { obs_key: string; satellite: string; timestamp_utc: string; latitude: number; longitude: number; frp_mw: number | null; confidence_class: string; source_file: string }
interface Job { id: number; kind: string; status: string; stage?: string | null; progress?: { message?: string } | null; error?: string | null; error_code?: string | null; attempts?: number; max_attempts?: number; requested_by?: string; created_at?: string; finished_at?: string | null; cancel_requested?: boolean; result?: unknown }

const STATUS_COLOR: Record<string, string> = { ACTIVE: '#f97316', DETECTED: '#facc15', POSSIBLY_INACTIVE: '#a78bfa', ENDED: '#64748b', MERGED: '#334155', SPLIT: '#334155', UNVERIFIED: '#94a3b8' }
const Th = ({ children }: { children: ReactNode }) => <th className="px-2 py-1 text-left font-medium text-slate-400">{children}</th>
const Tc = ({ children, right }: { children: ReactNode; right?: boolean }) => <td className={`border-t border-line px-2 py-1 ${right ? 'text-right font-mono' : ''}`}>{children}</td>
const Tag = ({ s }: { s: string }) => {
  const cls = /^(SUCCEEDED|OK|ESTIMATED|COMPUTED|AVAILABLE|PROCESSED|CONFIGURED|IMPORTED_EXPERIMENTAL)/.test(s) ? 'border-emerald-500/60 text-emerald-300'
    : /^(QUEUED|RUNNING|RETRYING|ACTIVE|DETECTED|POSSIBLY_INACTIVE|EXPERIMENTAL|NOT_COMPUTED|NO_DATA|NO_GEOSTATIONARY_DATA|POLAR_ONLY|CONFIGURED_NOT_DOWNLOADED)/.test(s) ? 'border-amber-500/60 text-amber-300'
      : /^(ENDED|NOT_USED|NOT_APPLICABLE|NOT_EVALUATED|CANCELLED|MERGED|SPLIT|UNVERIFIED)/.test(s) ? 'border-slate-500/60 text-slate-300'
        : 'border-red-500/60 text-red-300'
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${cls}`}>{titleCase(s)}</span>
}
const Exp = ({ children = 'EXPERIMENTAL · NOT INDEPENDENTLY VALIDATED' }: { children?: ReactNode }) => <span className="rounded border border-amber-500/60 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">{children}</span>
const dt = (s?: string | null) => (s ? s.slice(0, 16).replace('T', ' ') : '–')
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))

/* ------------------------------------------------------------------ fire events */
export function FireEventsPage() {
  const nav = useNavigate()
  const { meta } = useApp()
  const [f, setF] = useState({ start: '', end: '', status: '', state: '', min_obs: '1', sort: 'last_detection' })
  const [page, setPage] = useState(0)
  const qs = new URLSearchParams({ limit: '100', offset: String(page * 100), min_obs: f.min_obs || '1', sort: f.sort })
  for (const k of ['start', 'end', 'status', 'state'] as const) if (f[k]) qs.set(k, f[k])
  const sum = useApi<EventSummary>('/api/events/summary')
  const list = useApi<EventList>(`/api/events?${qs.toString()}`)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => { setPage(0); setF({ ...f, [k]: e.target.value }) }
  const items = list.data?.items || []
  const lr = sum.data?.last_run
  return (
    <Page title="Fire events" intro="Related active-fire detections grouped into space-time fire events. One hotspot is one thermal-anomaly detection, not one fire; an event footprint is the hull of detected pixels, not a fire perimeter or burned area.">
      <div className="flex flex-wrap gap-2"><Exp /><Note>No CONTAINED status exists: containment needs official incident data. ENDED requires a quiet period longer than the land-cover persistence window and enough sensor-days of data since the last detection (FIRMS has no cloud mask).</Note></div>
      <State loading={sum.loading} error={sum.error} empty={!sum.data}>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
          <Stat label="Events stored" value={num(sum.data?.events)} />
          {['ACTIVE', 'DETECTED', 'POSSIBLY_INACTIVE', 'ENDED', 'UNVERIFIED'].map((s) => <Stat key={s} label={titleCase(s)} value={num(sum.data?.status_counts?.[s] || 0)} />)}
        </div>
        {lr ? <p className="text-xs text-slate-400">Last run: {lr.start} to {lr.end} · {num(lr.detections)} detections → {num(lr.events)} events ({num(lr.multi_sensor_events)} multi-sensor, {num(lr.single_detection_events)} single-detection) · data through {dt(lr.data_through)} · {lr.seconds}s · method {sum.data?.method}</p>
          : <Note tone="warn">No event delineation has run yet. An administrator can queue the <b>fire events</b> job on the Background jobs page.</Note>}
      </State>
      <Card title="Filters">
        <div className="flex flex-wrap items-end gap-3 text-xs">
          <label className="flex flex-col gap-1">From<input aria-label="Events from" type="date" value={f.start} onChange={set('start')} className="rounded border border-line bg-ink-800 px-2 py-1" /></label>
          <label className="flex flex-col gap-1">To<input aria-label="Events to" type="date" value={f.end} onChange={set('end')} className="rounded border border-line bg-ink-800 px-2 py-1" /></label>
          <label className="flex flex-col gap-1">Status<select aria-label="Event status" value={f.status} onChange={set('status')} className="rounded border border-line bg-ink-800 px-2 py-1"><option value="">any</option>{['ACTIVE', 'DETECTED', 'POSSIBLY_INACTIVE', 'ENDED', 'UNVERIFIED', 'MERGED'].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}</select></label>
          <label className="flex flex-col gap-1">State<select aria-label="Event state" value={f.state} onChange={set('state')} className="rounded border border-line bg-ink-800 px-2 py-1"><option value="">all</option>{(meta?.states || []).map((s) => <option key={s}>{s}</option>)}</select></label>
          <label className="flex flex-col gap-1">Min detections<input aria-label="Minimum detections" type="number" min={1} value={f.min_obs} onChange={set('min_obs')} className="w-24 rounded border border-line bg-ink-800 px-2 py-1" /></label>
          <label className="flex flex-col gap-1">Sort<select aria-label="Event sort" value={f.sort} onChange={set('sort')} className="rounded border border-line bg-ink-800 px-2 py-1"><option value="last_detection">latest</option><option value="n_obs">detections</option><option value="peak_frp">peak FRP</option><option value="footprint">footprint</option></select></label>
        </div>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Event map" sub="Event centres coloured by status (current page)." pad={false}>
          <BaseMap height={460}><PointLayer points={items.map((e) => ({ ...e, latitude: e.lat, longitude: e.lon }))} colorOf={(e) => STATUS_COLOR[e.status] || '#94a3b8'} isSquare={() => false}
            radius={4} onClick={(e) => nav(`/events/${e.event_id}`)} popup={(e) => `${e.event_id}<br/>${e.status} · ${e.n_obs} detections<br/>${dt(e.first_detection)} → ${dt(e.last_detection)}`} /></BaseMap>
          <div className="flex flex-wrap gap-3 px-4 py-2">{Object.entries(STATUS_COLOR).slice(0, 5).map(([k, v]) => <Swatch key={k} color={v} label={titleCase(k)} />)}</div>
        </Card>
        <Card title="Events" sub={list.data ? `${num(list.data.total)} matching · page ${page + 1}` : undefined} right={<><Btn small disabled={page === 0} onClick={() => setPage(page - 1)}>Prev</Btn><Btn small disabled={!list.data || (page + 1) * 100 >= list.data.total} onClick={() => setPage(page + 1)}>Next</Btn></>}>
          <State loading={list.loading} error={list.error} empty={!items.length}>
            <div className="max-h-[440px] overflow-auto"><table className="w-full text-xs"><thead><tr><Th>Event</Th><Th>Status</Th><Th>First / last detection (UTC)</Th><Th>Det.</Th><Th>Sensors</Th><Th>Footprint km²</Th><Th>Peak FRP</Th><Th>State</Th></tr></thead>
              <tbody>{items.map((e) => <tr key={e.event_id} className="cursor-pointer hover:bg-ink-800" onClick={() => nav(`/events/${e.event_id}`)}><Tc><span className="font-mono text-[11px] text-orange-300">{e.event_id}</span></Tc><Tc><Tag s={e.status} /></Tc><Tc>{dt(e.first_detection)} → {dt(e.last_detection)}</Tc><Tc right>{e.n_obs}</Tc><Tc>{Object.keys(e.platforms).join(', ')}</Tc><Tc right>{num(e.footprint_km2, 2)}</Tc><Tc right>{num(e.peak_frp_mw, 1)}</Tc><Tc>{e.state || '–'}</Tc></tr>)}</tbody></table></div>
          </State>
        </Card>
      </div>
    </Page>
  )
}

export function FireEventDetailPage() {
  const { id = '' } = useParams()
  const { role } = useApp()
  const ev = useApi<EventDetail>(`/api/events/${encodeURIComponent(id)}`)
  const obs = useApi<{ total: number; items: Obs[]; note: string }>(`/api/events/${encodeURIComponent(id)}/observations?limit=300`)
  const ex = useApi<{ population?: { people?: number } | null; radius_km: number; note: string } & Record<string, unknown>>(`/api/events/${encodeURIComponent(id)}/nearby-exposure?radius_km=10`)
  const [msg, setMsg] = useState<string | null>(null)
  const e = ev.data
  const draft = (kind: string) => api<{ alert_id: string; status: string }>('/api/advisories', { body: { kind, ref: id } }).then((r) => setMsg(`Draft ${r.alert_id} created (${titleCase(r.status)}). It is delivered only after approval on the Alerts page.`)).catch((x) => setMsg(errText(x)))
  const ring = e?.footprint_geojson?.coordinates?.[0]?.map(([lo, la]) => [la, lo] as [number, number])
  return (
    <Page title={`Fire event ${id}`} intro="Event attributes, growth of the detection footprint, linked satellite observations and nearby exposure.">
      <State loading={ev.loading} error={ev.error} empty={!e}>{e && <>
        <div className="flex flex-wrap items-center gap-2"><Tag s={e.status} /><Exp /><span className="text-xs text-slate-400">{e.interpretation.validation}</span></div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
          <Stat label="Detections" value={num(e.n_obs)} sub={`${e.n_days} day(s) · ${e.day_count} day / ${e.night_count} night`} />
          <Stat label="Platforms" value={Object.keys(e.platforms).length} sub={Object.entries(e.platforms).map(([k, v]) => `${k} ${v}`).join(' · ')} />
          <Stat label="Footprint km²" value={num(e.footprint_km2, 2)} sub={`pixel centres hull ${num(e.footprint_centres_km2, 2)} km²`} />
          <Stat label="Peak FRP (MW)" value={num(e.peak_frp_mw, 1)} sub={`sum of detections ${num(e.sum_frp_mw, 0)} MW`} />
          <Stat label="FRE bracket (GJ)" value={e.fre_mj_low != null ? `${num(e.fre_mj_low / 1000, 0)}–${num((e.fre_mj_high || 0) / 1000, 0)}` : '–'} sub="experimental" />
          <Stat label="Confidence" value={num(e.confidence_mean, 2)} sub={e.evidence} />
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <Card title="Observation footprint" sub={e.interpretation.footprint} pad={false}>
            <BaseMap height={380} bbox={[e.west - 0.05, e.south - 0.05, e.east + 0.05, e.north + 0.05]}>
              {ring && <Polygon positions={ring} pathOptions={{ color: '#f97316', weight: 2, fillOpacity: 0.15 }} />}
              <PointLayer points={obs.data?.items || []} colorOf={(o) => (o.satellite === 'Terra' || o.satellite === 'Aqua' ? C.aqua : C.viirs)} isSquare={() => false} radius={3}
                popup={(o) => `${o.satellite} ${dt(o.timestamp_utc)}<br/>FRP ${o.frp_mw ?? '–'} MW · ${o.confidence_class}`} />
            </BaseMap>
          </Card>
          <Card title="Timing and status">
            <ul className="space-y-1 text-xs text-slate-300">
              <li>First detection <b>{dt(e.first_detection)}</b> UTC (fire may have started up to 12 h earlier: earliest bound {dt(e.est_start_earliest)}).</li>
              <li>Last detection <b>{dt(e.last_detection)}</b> UTC · {num(e.gap_days, 1)} days before the latest data · {e.sensor_days_since_last} sensor-days with data since.</li>
              <li>{e.end_basis ? `Ended: ${e.end_basis}` : 'Not marked ended.'} {e.est_end_latest && `Latest plausible end ${dt(e.est_end_latest)}.`}</li>
              <li>Land cover {e.land_use || 'unknown'} · {e.state || 'outside mapped states'} · multi-sensor days {Math.round(e.multi_sensor_day_share * 100)}%</li>
              <li>Apparent movement {num(e.growth.apparent_movement_km, 2)} km {e.growth.apparent_bearing_deg != null && `toward ${e.growth.apparent_bearing_deg}°`} · footprint growth {e.growth.footprint_growth_km2_per_day != null ? `${num(e.growth.footprint_growth_km2_per_day, 3)} km²/day` : 'n/a (single day)'}. {e.growth.note}</li>
              <li>Geostationary corroboration: <Tag s={e.geostationary_agreement.class} /> {e.geostationary_agreement.note}</li>
              <li>Identity history: {e.history.map((h) => `${h.action}${h.related_event_id ? ` (${h.related_event_id})` : ''}`).join(' → ') || '–'} {e.truncated_start && '· started before the processed window'}</li>
            </ul>
            {(role === 'analyst' || role === 'gov_officer' || role === 'admin') && <div className="mt-3 flex flex-wrap gap-2">
              <Btn small onClick={() => draft('FIRE_EVENT_ADVISORY')}>Draft fire-event advisory (needs review)</Btn>
              <Btn small onClick={() => draft('EMISSIONS_ESTIMATE_NOTICE')}>Draft emissions notice</Btn></div>}
            {msg && <p className="mt-2 text-xs text-slate-300">{msg}</p>}
          </Card>
        </div>
        <Card title="Event timeline" sub="Daily detections, FRP and detection-footprint growth (observation geometry, not a perimeter).">
          <div className="h-64"><ResponsiveContainer><ComposedChart data={e.timeline || []}><CartesianGrid stroke={C.grid} /><XAxis dataKey="date" tick={{ fontSize: 10 }} /><YAxis yAxisId="l" tick={{ fontSize: 10 }} /><YAxis yAxisId="r" orientation="right" tick={{ fontSize: 10 }} />
            <Tooltip contentStyle={{ background: '#0b1220', border: '1px solid #26324a', fontSize: 12 }} /><Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar yAxisId="l" dataKey="detections" name="detections" fill={C.viirs} /><Line yAxisId="r" dataKey="cumulative_footprint_km2" name="cumulative footprint km²" stroke={C.est} dot={false} /><Line yAxisId="l" dataKey="frp_max_mw" name="max FRP (MW)" stroke={C.terra} dot={false} /></ComposedChart></ResponsiveContainer></div>
        </Card>
        <div className="grid gap-4 xl:grid-cols-2">
          <Card title="Linked satellite observations" sub={obs.data ? `${obs.data.total} original FIRMS records (first 300 shown). ${obs.data.note}` : undefined}>
            <State loading={obs.loading} error={obs.error} empty={!obs.data?.items.length}>
              <div className="max-h-72 overflow-auto"><table className="w-full text-xs"><thead><tr><Th>Time UTC</Th><Th>Platform</Th><Th>Lat</Th><Th>Lon</Th><Th>FRP</Th><Th>Conf.</Th></tr></thead>
                <tbody>{obs.data?.items.map((o) => <tr key={o.obs_key}><Tc>{dt(o.timestamp_utc)}</Tc><Tc>{o.satellite}</Tc><Tc right>{o.latitude.toFixed(4)}</Tc><Tc right>{o.longitude.toFixed(4)}</Tc><Tc right>{num(o.frp_mw, 1)}</Tc><Tc>{o.confidence_class}</Tc></tr>)}</tbody></table></div>
            </State>
          </Card>
          <Card title="Nearby exposure (10 km of centre)" sub={ex.data?.note}>
            <State loading={ex.loading} error={ex.error} empty={!ex.data}><pre className="max-h-72 overflow-auto whitespace-pre-wrap text-[11px] text-slate-300">{JSON.stringify(Object.fromEntries(Object.entries(ex.data || {}).filter(([k]) => !['note', 'centre'].includes(k))), null, 1)}</pre></State>
          </Card>
        </div>
      </>}</State>
    </Page>
  )
}

/* ------------------------------------------------------------------ burned area */
interface BaCoverage { products: Record<string, { version: string; sensor: string; format: string; start: string; doi: string }>; months: { product: string; year: number; month: number; burned_km2: number; mapped_km2: number; unmapped_km2: number; unmapped_share: number; granules: number; status: string }[]; tiles: string[]; access: { earthdata_login: string; provider: string; status: string; note: string }; interpretation: string }
export function BurnedAreaPage() {
  const cov = useApi<BaCoverage>('/api/burned-area/coverage')
  const [product, setProduct] = useState('MCD64A1')
  const sum = useApi<{ items: Record<string, number | string>[]; status: string; note?: string; uncertainty?: string }>(`/api/burned-area/summary?product=${product}&by=state`)
  const months = (cov.data?.months || []).filter((m) => m.product === product)
  return (
    <Page title="Burned-area mapping" intro="Monthly 500 m burn-scar products (MODIS MCD64A1 C6.1, VIIRS VNP64A1 v002). Kept separate from hotspot counts: burned area is never estimated from hotspots.">
      <State loading={cov.loading} error={cov.error} empty={!cov.data}>{cov.data && <>
        <Card title="Data access" badges={<Tag s={cov.data.access.status} />} sub={`${cov.data.access.provider} · Earthdata ${cov.data.access.earthdata_login}`}>
          <Note tone={cov.data.access.status === 'PROCESSED' ? 'info' : 'warn'}>{cov.data.access.note} Unmapped (insufficient data) and water pixels are reported separately and never counted as unburned. India is covered by {cov.data.tiles.length} MODIS sinusoidal tiles ({cov.data.tiles.join(', ')}).</Note>
          <table className="mt-3 w-full text-xs"><thead><tr><Th>Product</Th><Th>Version</Th><Th>Sensor</Th><Th>Format</Th><Th>Archive start</Th><Th>DOI</Th></tr></thead>
            <tbody>{Object.entries(cov.data.products).map(([k, p]) => <tr key={k}><Tc>{k}</Tc><Tc>{p.version}</Tc><Tc>{p.sensor}</Tc><Tc>{p.format}</Tc><Tc>{p.start}</Tc><Tc>{p.doi}</Tc></tr>)}</tbody></table>
        </Card>
        <Card title="Processed months" right={<select aria-label="Burned-area product" value={product} onChange={(e) => setProduct(e.target.value)} className="rounded border border-line bg-ink-800 px-2 py-1 text-xs"><option>MCD64A1</option><option>VNP64A1</option></select>}>
          <State empty={!months.length}>
            <table className="w-full text-xs"><thead><tr><Th>Month</Th><Th>Burned km²</Th><Th>Mapped km²</Th><Th>Unmapped km²</Th><Th>Unmapped share</Th><Th>Granules</Th></tr></thead>
              <tbody>{months.map((m) => <tr key={`${m.year}-${m.month}`}><Tc>{m.year}-{String(m.month).padStart(2, '0')}</Tc><Tc right>{num(m.burned_km2, 1)}</Tc><Tc right>{num(m.mapped_km2, 0)}</Tc><Tc right>{num(m.unmapped_km2, 0)}</Tc><Tc right>{num(m.unmapped_share * 100, 1)}%</Tc><Tc right>{m.granules}</Tc></tr>)}</tbody></table>
          </State>
        </Card>
        <Card title="Burned area by state" sub={sum.data?.uncertainty || sum.data?.note}>
          <State loading={sum.loading} error={sum.error} empty={!sum.data?.items.length}>
            <div className="h-72"><ResponsiveContainer><BarChart data={(sum.data?.items || []).slice(0, 15)}><CartesianGrid stroke={C.grid} /><XAxis dataKey="state" tick={{ fontSize: 9 }} interval={0} angle={-30} textAnchor="end" height={70} /><YAxis tick={{ fontSize: 10 }} /><Tooltip contentStyle={{ background: '#0b1220', border: '1px solid #26324a', fontSize: 12 }} /><Bar dataKey="burned_km2" name="burned km²" fill={C.viirs} /></BarChart></ResponsiveContainer></div>
          </State>
        </Card>
      </>}</State>
    </Page>
  )
}

/* ------------------------------------------------------------------ emissions */
interface Q { median: number; p05: number; p95: number }
interface EmSummary { status: string; label: string; method?: string; start?: string; end?: string; events?: number; n_draws?: number; totals_tonnes?: Record<string, Q>; inputs?: { combustion_factor_kg_per_MJ: { mean: number; sd: number; source: string }; emission_factors: { source: string; sha256: string; basis: string; values_g_per_kg: Record<string, Record<string, number>> }; biome_mapping: Record<string, string[]>; fre_bracket_isolated_pass_hours: number[] }; uncertainty_not_included?: string[]; burned_area_method: { status: string; missing?: string }; note?: string }
export function EmissionsPage() {
  const s = useApi<EmSummary>('/api/emissions/summary')
  const [by, setBy] = useState('state')
  const reg = useApi<{ items: Record<string, number | string>[]; note: string }>(s.data?.status === 'ESTIMATED' ? `/api/emissions/regions?by=${by}` : null)
  const ev = useApi<{ total: number; items: Record<string, number | string>[] }>(s.data?.status === 'ESTIMATED' ? '/api/emissions/events?limit=15' : null)
  const d = s.data
  return (
    <Page title="Biomass-burning emissions" intro="Mass-balance ESTIMATES. FRP/FRE method on fire events: dry matter = FRE × combustion factor; species = dry matter × emission factor. Not an official emissions inventory.">
      <State loading={s.loading} error={s.error} empty={!d}>{d && <>
        <div className="flex flex-wrap gap-2"><Exp>ESTIMATED · EXPERIMENTAL · NOT INDEPENDENTLY VALIDATED</Exp><Tag s={d.status} /></div>
        {d.status !== 'ESTIMATED' ? <Note tone="warn">{d.note || 'Not computed.'}</Note> : <>
          <p className="text-xs text-slate-400">{d.method} · {d.events} events · window {d.start || 'all'} to {d.end || 'all'} · Monte Carlo {d.n_draws} draws (median, 5th-95th percentile).</p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">{Object.entries(d.totals_tonnes || {}).map(([k, q]) => <Stat key={k} label={`${k === 'dry_matter' ? 'Dry matter' : k} (t)`} value={compact(q.median)} sub={`90%: ${compact(q.p05)} – ${compact(q.p95)}`} />)}</div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="By region" right={<select aria-label="Emissions grouping" value={by} onChange={(e) => setBy(e.target.value)} className="rounded border border-line bg-ink-800 px-2 py-1 text-xs"><option value="state">state</option><option value="land_use">land cover</option><option value="month">month</option></select>} sub={reg.data?.note}>
              <State loading={reg.loading} error={reg.error} empty={!reg.data?.items.length}>
                <div className="max-h-80 overflow-auto"><table className="w-full text-xs"><thead><tr><Th>{titleCase(by)}</Th><Th>Events</Th><Th>PM2.5 t (low–high)</Th><Th>CO t</Th><Th>CO₂ t</Th><Th>CH₄ t</Th></tr></thead>
                  <tbody>{reg.data?.items.map((r) => <tr key={String(r[by])}><Tc>{String(r[by])}</Tc><Tc right>{num(Number(r.events))}</Tc><Tc right>{num(Number(r['PM2.5_kg']) / 1000, 1)} ({num(Number(r['PM2.5_kg_low']) / 1000, 1)}–{num(Number(r['PM2.5_kg_high']) / 1000, 1)})</Tc><Tc right>{num(Number(r.CO_kg) / 1000, 0)}</Tc><Tc right>{num(Number(r.CO2_kg) / 1000, 0)}</Tc><Tc right>{num(Number(r.CH4_kg) / 1000, 1)}</Tc></tr>)}</tbody></table></div>
              </State>
            </Card>
            <Card title="Largest event estimates (PM2.5)">
              <State loading={ev.loading} error={ev.error} empty={!ev.data?.items.length}>
                <table className="w-full text-xs"><thead><tr><Th>Event</Th><Th>Land cover</Th><Th>PM2.5 kg</Th><Th>Bounds</Th></tr></thead>
                  <tbody>{ev.data?.items.map((r) => <tr key={String(r.event_id)}><Tc><a className="font-mono text-orange-300" href={`/events/${r.event_id}`}>{String(r.event_id)}</a></Tc><Tc>{String(r.land_use ?? '–')}</Tc><Tc right>{num(Number(r['PM2.5_kg']), 0)}</Tc><Tc right>{num(Number(r['PM2.5_kg_low']), 0)}–{num(Number(r['PM2.5_kg_high']), 0)}</Tc></tr>)}</tbody></table>
              </State>
            </Card>
          </div>
          {d.inputs && <Card title="Inputs and provenance">
            <ul className="space-y-1 text-xs text-slate-300">
              <li>Combustion factor {d.inputs.combustion_factor_kg_per_MJ.mean} ± {d.inputs.combustion_factor_kg_per_MJ.sd} kg/MJ ({d.inputs.combustion_factor_kg_per_MJ.source}).</li>
              <li>Emission factors: {d.inputs.emission_factors.basis}; file SHA-256 <span className="font-mono">{d.inputs.emission_factors.sha256.slice(0, 16)}…</span></li>
              <li>Biome mapping: {Object.entries(d.inputs.biome_mapping).map(([k, v]) => `${k} → ${v.join(' or ')}`).join('; ')}.</li>
              <li>FRE bracket: isolated overpasses credited {d.inputs.fre_bracket_isolated_pass_hours.join(' to ')} h of unobserved burning per side.</li>
              <li>Not included in the uncertainty: {d.uncertainty_not_included?.join('; ')}.</li>
            </ul></Card>}
        </>}
        <Card title="Burned-area method" badges={<Tag s={d.burned_area_method.status} />}><p className="text-xs text-slate-300">Dry matter = burned area × fuel consumption. {d.burned_area_method.missing}</p></Card>
      </>}</State>
    </Page>
  )
}

/* ------------------------------------------------------------------ smoke */
interface SmokePoint { h: number; lat: number; lon: number; blh_m?: number }
interface SmokeRun { run_id: string; label: string; start_utc: string; hours: number; model: string; hysplit: string; injection_height: string; levels: string[]
  sources: { event_id: string; lat: number; lon: number; status: string }[]; trajectories: { event_id: string; level: string; points: SmokePoint[]; complete: boolean }[]
  exposure: { corridor_km: number; levels: Record<string, { people_in_corridor: number; cells: number; by_arrival: Record<string, number> }>; interpretation: string }
  meteorology: { source: string; fetched_at: string; grid_deg: number }; pm25: { status: string; reason: string }; validation: { status: string; reason: string } }
export function SmokePage() {
  const runs = useApi<{ items: { run_id: string; start_utc: string; hours: number; computed_at: string; sources: number }[]; label: string }>('/api/smoke/forecasts')
  const [sel, setSel] = useState<string | null>(null)
  const rid = sel || runs.data?.items[0]?.run_id || null
  const run = useApi<SmokeRun>(rid ? `/api/smoke/trajectories/${rid}` : null)
  const r = run.data
  const [hour, setHour] = useState(48)
  return (
    <Page title="Smoke transport" intro="Forward trajectories from burning fire events with GFS winds. A trajectory is a path, not a concentration: PyroScope does not forecast PM2.5 (no dispersion model is installed) and these outputs are not health warnings.">
      <div className="flex flex-wrap gap-2"><Exp>{runs.data?.label || 'EXPERIMENTAL TRAJECTORY'}</Exp></div>
      <State loading={runs.loading} error={runs.error} empty={!runs.data?.items.length}>
        <Card title="Runs" right={<select aria-label="Smoke run" value={rid || ''} onChange={(e) => setSel(e.target.value)} className="rounded border border-line bg-ink-800 px-2 py-1 text-xs">{runs.data?.items.map((x) => <option key={x.run_id} value={x.run_id}>{x.run_id} · {x.sources} sources · {x.hours} h</option>)}</select>}>
          <State loading={run.loading} error={run.error} empty={!r}>{r && <div className="space-y-2 text-xs text-slate-300">
            <p>Start {dt(r.start_utc)} UTC · {r.hours} h · {r.model} · meteorology {r.meteorology.source} (sampled every {r.meteorology.grid_deg}°, fetched {dt(r.meteorology.fetched_at)}). HYSPLIT: {r.hysplit}.</p>
            <p>Injection height: {r.injection_height}. PM2.5: <Tag s={r.pm25.status} /> {r.pm25.reason}. Validation: <Tag s={r.validation.status} /> {r.validation.reason}</p>
            <label className="flex items-center gap-2">Show first <input aria-label="Trajectory hours" type="range" min={3} max={r.hours} value={Math.min(hour, r.hours)} onChange={(e) => setHour(Number(e.target.value))} /> {Math.min(hour, r.hours)} h</label>
          </div>}</State>
        </Card>
        {r && <div className="grid gap-4 xl:grid-cols-2">
          <Card title="Trajectory map" sub="Orange: 10 m (surface layer). Blue: 850 hPa (~1.5 km). Dots: fire events." pad={false}>
            <BaseMap height={460}>
              {r.trajectories.map((t, i) => <Polyline key={i} positions={t.points.filter((p) => p.h <= hour).map((p) => [p.lat, p.lon] as [number, number])} pathOptions={{ color: t.level === '850hPa' ? '#60a5fa' : '#f97316', weight: 2, opacity: 0.8, dashArray: t.complete ? undefined : '4 4' }} />)}
              <PointLayer points={r.sources.map((s) => ({ ...s, latitude: s.lat, longitude: s.lon }))} colorOf={() => '#facc15'} isSquare={() => false} radius={5} popup={(s) => `${s.event_id} (${s.status})`} />
            </BaseMap>
          </Card>
          <Card title="People near the modelled smoke path" sub={r.exposure.interpretation}>
            <table className="w-full text-xs"><thead><tr><Th>Level</Th>{Object.keys(Object.values(r.exposure.levels)[0]?.by_arrival || {}).map((k) => <Th key={k}>arrival {k}</Th>)}</tr></thead>
              <tbody>{Object.entries(r.exposure.levels).map(([lvl, v]) => <tr key={lvl}><Tc>{lvl}</Tc>{Object.values(v.by_arrival).map((n, i) => <Tc key={i} right>{compact(n)}</Tc>)}</tr>)}</tbody></table>
            <p className="mt-2 text-[11px] text-slate-400">Corridor {r.exposure.corridor_km} km; WorldPop 2020 cells counted once even when several trajectories pass.</p>
          </Card>
        </div>}
      </State>
    </Page>
  )
}

/* ------------------------------------------------------------------ geostationary + diurnal */
interface Provider { id: string; name: string; status: string; coverage?: string; view_angle?: string; resolution?: string; cadence?: string; archive?: string; access?: string; connector?: string; note?: string }
interface Diurnal { polar_by_sensor_hour: { satellite: string; hour: number; n: number }[]; observed_hours_polar: number[]; missing_hours: number[]; hourly_activity_estimate: { status: string; reason: string }; time_basis: string }
export function GeostationaryPage() {
  const { role } = useApp()
  const cov = useApi<{ providers: Provider[]; imported_observations: number; status: string; historical_limit: string }>('/api/geostationary/coverage')
  const di = useApi<Diurnal>('/api/geostationary/diurnal')
  const [range, setRange] = useState({ start: '2026-10-25', end: '2026-10-31' })
  const ag = useApi<{ events: number; classes: Record<string, number>; note: string }>(`/api/geostationary/agreement?start=${range.start}&end=${range.end}`)
  const sats = Array.from(new Set((di.data?.polar_by_sensor_hour || []).map((r) => r.satellite)))
  const rows = Array.from({ length: 24 }, (_, h) => Object.fromEntries([['hour', h], ...sats.map((s) => [s, di.data?.polar_by_sensor_hour.find((r) => r.satellite === s && r.hour === h)?.n || 0])]))
  const [msg, setMsg] = useState<string | null>(null)
  const upload = (form: HTMLFormElement) => api<{ imported: number }>('/api/geostationary/import', { form: new FormData(form) }).then((r) => { setMsg(`Imported ${r.imported} pixels.`); cov.reload() }).catch((e) => setMsg(errText(e)))
  return (
    <Page title="Geostationary fire monitoring and diurnal activity" intro="Multi-sensor fire fusion with geostationary observations. Providers are listed with verified coverage, geometry and access; only authorised exports are imported, nothing is simulated.">
      <div className="flex flex-wrap gap-2"><Exp /><Note>{cov.data?.historical_limit}</Note></div>
      <Card title="Providers" badges={cov.data && <Tag s={cov.data.status} />} sub={cov.data ? `${num(cov.data.imported_observations)} geostationary pixels imported` : undefined}>
        <State loading={cov.loading} error={cov.error} empty={!cov.data}>
          <div className="overflow-auto"><table className="w-full text-xs"><thead><tr><Th>Provider</Th><Th>Status</Th><Th>Coverage / view angle</Th><Th>Resolution · cadence</Th><Th>Archive</Th><Th>Access</Th><Th>Connector</Th></tr></thead>
            <tbody>{cov.data?.providers.map((p) => <tr key={p.id}><Tc>{p.name}</Tc><Tc><Tag s={p.status} /></Tc><Tc>{p.coverage} {p.view_angle && `· ${p.view_angle}`}</Tc><Tc>{[p.resolution, p.cadence].filter(Boolean).join(' · ') || '–'}</Tc><Tc>{p.archive || '–'}</Tc><Tc>{p.access || '–'}</Tc><Tc>{p.connector}{p.note && ` · ${p.note}`}</Tc></tr>)}</tbody></table></div>
        </State>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Diurnal sampling of fire detections (local solar time)" sub={di.data ? `${di.data.time_basis}. Counts are per sensor and not comparable across sensors.` : undefined}>
          <State loading={di.loading} error={di.error} empty={!di.data}>
            <div className="h-64"><ResponsiveContainer><BarChart data={rows}><CartesianGrid stroke={C.grid} /><XAxis dataKey="hour" tick={{ fontSize: 10 }} /><YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => compact(v)} /><Tooltip contentStyle={{ background: '#0b1220', border: '1px solid #26324a', fontSize: 12 }} /><Legend wrapperStyle={{ fontSize: 11 }} />
              {sats.map((s, i) => <Bar key={s} dataKey={s} stackId="a" fill={[C.terra, C.aqua, C.viirs, C.n20, C.n21][i % 5]} />)}</BarChart></ResponsiveContainer></div>
            <p className="text-xs text-slate-400">Hours with no observation from any sensor: {di.data?.missing_hours.join(', ')}. Hourly activity estimate: <Tag s={di.data?.hourly_activity_estimate.status || 'NOT_AVAILABLE'} /> {di.data?.hourly_activity_estimate.reason}</p>
          </State>
        </Card>
        <Card title="Multi-sensor agreement for fire events" right={<><input aria-label="Agreement from" type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} className="rounded border border-line bg-ink-800 px-1 text-xs" /><input aria-label="Agreement to" type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} className="rounded border border-line bg-ink-800 px-1 text-xs" /></>}>
          <State loading={ag.loading} error={ag.error} empty={!ag.data}>
            <table className="w-full text-xs"><tbody>{Object.entries(ag.data?.classes || {}).map(([k, v]) => <tr key={k}><Tc><Tag s={k} /></Tc><Tc right>{num(v)}</Tc></tr>)}</tbody></table>
            <p className="mt-2 text-[11px] text-slate-400">{ag.data?.events} events. {ag.data?.note}</p>
          </State>
          {role === 'admin' && <form className="mt-3 grid grid-cols-2 gap-2 text-xs" onSubmit={(e) => { e.preventDefault(); upload(e.currentTarget) }}>
            <input name="source" required placeholder="Source (e.g. MOSDAC export, order id)" className="col-span-2 rounded border border-line bg-ink-800 px-2 py-1" />
            <input name="licence" required placeholder="Licence / data policy" className="rounded border border-line bg-ink-800 px-2 py-1" />
            <select name="platform" className="rounded border border-line bg-ink-800 px-2 py-1"><option>INSAT-3DR</option><option>INSAT-3D</option><option>INSAT-3DS</option><option>Meteosat-9</option></select>
            <input name="product" placeholder="Product (e.g. 3RIMG_L2P_FIR)" className="rounded border border-line bg-ink-800 px-2 py-1" />
            <input name="file" type="file" accept=".csv,.kml" required aria-label="Geostationary file" />
            <div className="col-span-2"><Btn small>Import authorised export</Btn> {msg && <span className="ml-2 text-slate-300">{msg}</span>}</div>
          </form>}
        </Card>
      </div>
    </Page>
  )
}

/* ------------------------------------------------------------------ external validation */
interface Mx { n?: number; wape_pct?: number; bias_pct?: number; rmse?: number; mae?: number; r?: number | null }
interface XvSummary { sources: { id: string; name: string; kind: string; independence: string; known_dependence?: string; status: string }[]; harmonization: { test_months?: number; test_period?: number[]; target?: string; models?: Record<string, Mx>; band_coverage_pct?: number | null; status?: string }
  events_vs_incidents: { datasets: { dataset: string; n: number; first: string; last: string }[]; status: string; csv_format: { required: string[]; optional: string[] }; note: string }; smoke: { status: string; reason: string } }
const MODEL_LABEL: Record<string, string> = { raw_modis: 'Raw MODIS (Terra + Aqua)', naive_modis_plus_viirs: 'Naive MODIS + VIIRS sum', constant_ratio: 'Constant ratio', pyroscope: 'PyroScope harmonized' }
export function ExternalValidationPage() {
  const { role } = useApp()
  const s = useApi<XvSummary>('/api/external-validation/summary')
  const [states, setStates] = useState(false)
  const st = useApi<{ design: string; states: (Record<string, Mx> & { state: string; test_months?: number })[] }>(states ? '/api/external-validation/harmonization-states?top=8' : null)
  const [msg, setMsg] = useState<string | null>(null)
  const upload = (form: HTMLFormElement) => api<{ imported: number; rejected: number }>('/api/external-validation/incidents', { form: new FormData(form) }).then((r) => { setMsg(`Imported ${r.imported}, rejected ${r.rejected}.`); s.reload() }).catch((e) => setMsg(errText(e)))
  const h = s.data?.harmonization
  return (
    <Page title="External scientific validation" intro="Scientific evidence against reference data, kept apart from software tests (passing tests prove code behaviour, not accuracy). Every source states whether it is independent of what it validates.">
      <State loading={s.loading} error={s.error} empty={!s.data}>{s.data && <>
        <Card title="Harmonization vs baselines (chronological hold-out)" sub={h?.target ? `${h.target} · ${h.test_months} held-out months · band coverage ${num(h.band_coverage_pct, 0)}% (nominal 90%)` : h?.status}>
          <table className="w-full text-xs"><thead><tr><Th>Model</Th><Th>WAPE %</Th><Th>Bias %</Th><Th>RMSE</Th><Th>MAE</Th><Th>r</Th></tr></thead>
            <tbody>{Object.entries(h?.models || {}).map(([k, m]) => <tr key={k}><Tc>{MODEL_LABEL[k] || k}</Tc><Tc right>{num(m.wape_pct, 1)}</Tc><Tc right>{num(m.bias_pct, 1)}</Tc><Tc right>{num(m.rmse, 0)}</Tc><Tc right>{num(m.mae, 0)}</Tc><Tc right>{num(m.r, 3)}</Tc></tr>)}</tbody></table>
          <div className="mt-2"><Btn small onClick={() => setStates(true)} disabled={states}>Per-state hold-out (slow)</Btn></div>
          {states && <State loading={st.loading} error={st.error} empty={!st.data}>
            <p className="mt-2 text-[11px] text-amber-200">{st.data?.design}</p>
            <table className="mt-1 w-full text-xs"><thead><tr><Th>State</Th><Th>Months</Th><Th>PyroScope WAPE %</Th><Th>Constant ratio WAPE %</Th><Th>Raw MODIS WAPE %</Th></tr></thead>
              <tbody>{st.data?.states.map((r) => <tr key={r.state}><Tc>{r.state}</Tc><Tc right>{r.test_months}</Tc><Tc right>{num(r.pyroscope?.wape_pct, 1)}</Tc><Tc right>{num(r.constant_ratio?.wape_pct, 1)}</Tc><Tc right>{num(r.raw_modis?.wape_pct, 1)}</Tc></tr>)}</tbody></table>
          </State>}
        </Card>
        <Card title="Reference sources and independence">
          <div className="overflow-auto"><table className="w-full text-xs"><thead><tr><Th>Source</Th><Th>Validates</Th><Th>Independence</Th><Th>Known dependence</Th><Th>Status</Th></tr></thead>
            <tbody>{s.data.sources.map((x) => <tr key={x.id}><Tc>{x.name}</Tc><Tc>{x.kind}</Tc><Tc>{x.independence}</Tc><Tc>{x.known_dependence || '–'}</Tc><Tc><Tag s={x.status} /></Tc></tr>)}</tbody></table></div>
        </Card>
        <div className="grid gap-4 xl:grid-cols-2">
          <Card title="Fire events vs official incident records" badges={<Tag s={s.data.events_vs_incidents.status} />} sub={s.data.events_vs_incidents.note}>
            <p className="text-xs text-slate-300">CSV columns: required {s.data.events_vs_incidents.csv_format.required.join(', ')}; optional {s.data.events_vs_incidents.csv_format.optional.join(', ')}.</p>
            {s.data.events_vs_incidents.datasets.map((d) => <p key={d.dataset} className="text-xs text-slate-300">{d.dataset}: {d.n} records, {d.first?.slice(0, 10)} → {d.last?.slice(0, 10)}</p>)}
            {role === 'admin' && <form className="mt-3 flex flex-wrap gap-2 text-xs" onSubmit={(e) => { e.preventDefault(); upload(e.currentTarget) }}>
              <input name="source" required placeholder="Issuing authority / dataset" className="rounded border border-line bg-ink-800 px-2 py-1" />
              <input name="licence" required placeholder="Licence / permission" className="rounded border border-line bg-ink-800 px-2 py-1" />
              <input name="file" type="file" accept=".csv" required aria-label="Incident CSV" /><Btn small>Import</Btn>{msg && <span className="text-slate-300">{msg}</span>}
            </form>}
          </Card>
          <Card title="Smoke / PM2.5" badges={<Tag s={s.data.smoke.status} />}><p className="text-xs text-slate-300">{s.data.smoke.reason}</p></Card>
        </div>
      </>}</State>
    </Page>
  )
}

/* ------------------------------------------------------------------ jobs + deployment */
export function JobsPage() {
  const { role } = useApp()
  const can = role === 'admin' || role === 'analyst' || role === 'gov_officer'
  const jobs = useApi<{ items: Job[]; kinds: Record<string, string> }>(can ? '/api/jobs?limit=50' : null)
  const [p, setP] = useState({ start: '2026-10-25', end: '2026-10-31', year: '2024', month: '11' })
  const [msg, setMsg] = useState<string | null>(null)
  const submit = (kind: string, params: Record<string, unknown>) => api<Job>('/api/jobs', { body: { kind, params } }).then((j) => { setMsg(`Queued job #${j.id} (${titleCase(j.kind)}).`); jobs.reload() }).catch((e) => setMsg(errText(e)))
  const cancel = (id: number) => api<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }).then(() => jobs.reload()).catch((e) => setMsg(errText(e)))
  return (
    <Page title="Background jobs" intro="Long downloads and scientific processing run in a durable, database-leased queue served by a persistent worker. API requests never wait for them." actions={<Btn small onClick={() => jobs.reload()}>Refresh</Btn>}>
      {!can && <Note>Job status is visible to analysts, government officers and administrators.</Note>}
      {role === 'admin' && <Card title="Queue a job">
        <div className="flex flex-wrap items-end gap-3 text-xs">
          <label className="flex flex-col gap-1">Start<input aria-label="Job start" type="date" value={p.start} onChange={(e) => setP({ ...p, start: e.target.value })} className="rounded border border-line bg-ink-800 px-2 py-1" /></label>
          <label className="flex flex-col gap-1">End<input aria-label="Job end" type="date" value={p.end} onChange={(e) => setP({ ...p, end: e.target.value })} className="rounded border border-line bg-ink-800 px-2 py-1" /></label>
          <Btn small onClick={() => submit('fire_events', { start: p.start, end: p.end })}>Fire events</Btn>
          <Btn small onClick={() => submit('emissions', { start: p.start, end: p.end })}>Emissions</Btn>
          <Btn small onClick={() => submit('smoke_trajectories', { since: p.start, max_sources: 10, hours: 48 })}>Smoke trajectories</Btn>
          <label className="flex flex-col gap-1">Year<input aria-label="Burned-area year" value={p.year} onChange={(e) => setP({ ...p, year: e.target.value })} className="w-20 rounded border border-line bg-ink-800 px-2 py-1" /></label>
          <label className="flex flex-col gap-1">Month<input aria-label="Burned-area month" value={p.month} onChange={(e) => setP({ ...p, month: e.target.value })} className="w-14 rounded border border-line bg-ink-800 px-2 py-1" /></label>
          <Btn small onClick={() => submit('burned_area', { product: 'MCD64A1', year: Number(p.year), month: Number(p.month) })}>Burned area (MCD64A1)</Btn>
        </div>
        {msg && <p className="mt-2 text-xs text-slate-300">{msg}</p>}
      </Card>}
      <Card title="Jobs">
        <State loading={jobs.loading} error={jobs.error} empty={!jobs.data?.items.length}>
          <div className="overflow-auto"><table className="w-full text-xs"><thead><tr><Th>#</Th><Th>Kind</Th><Th>Status</Th><Th>Attempts</Th><Th>Stage / error</Th><Th>By</Th><Th>Created</Th><Th>Finished</Th><Th>{' '}</Th></tr></thead>
            <tbody>{jobs.data?.items.map((j) => <tr key={j.id}><Tc>{j.id}</Tc><Tc>{titleCase(j.kind)}</Tc><Tc><Tag s={j.status} /></Tc><Tc right>{j.attempts ?? 0}/{j.max_attempts ?? 3}</Tc>
              <Tc><span className="text-[11px]">{j.error_code ? <b className="text-red-300">{j.error_code}: </b> : null}{j.error || j.stage || j.progress?.message || ''}</span></Tc><Tc>{j.requested_by}</Tc><Tc>{dt(j.created_at)}</Tc><Tc>{dt(j.finished_at)}</Tc>
              <Tc>{role === 'admin' && ['QUEUED', 'RUNNING', 'RETRYING'].includes(j.status) && !j.cancel_requested && <Btn small kind="danger" onClick={() => cancel(j.id)}>Cancel</Btn>}</Tc></tr>)}</tbody></table></div>
        </State>
      </Card>
    </Page>
  )
}

export function DeploymentPage() {
  const { role } = useApp()
  const d = useApi<{ database: { dialect: string; host: string | null; port: number | null; pool: string; transaction_pooler: boolean }; storage: { backend: string; configured: boolean; buckets: string[]; note?: string }; embedded_worker: boolean; frontend: string; note: string }>(role === 'admin' ? '/api/deployment/status' : null)
  return (
    <Page title="Deployment health" intro="Vercel (frontend), persistent FastAPI service, background worker, PostgreSQL / Supabase and object storage. No credential values are ever shown.">
      {role !== 'admin' ? <Note>Visible to administrators only.</Note> : <State loading={d.loading} error={d.error} empty={!d.data}>{d.data && <div className="grid gap-4 md:grid-cols-3">
        <Card title="Database"><ul className="space-y-1 text-xs text-slate-300"><li>Dialect <b>{d.data.database.dialect}</b></li><li>Host {d.data.database.host || 'local file'}{d.data.database.port ? `:${d.data.database.port}` : ''}</li><li>Pool {d.data.database.pool}{d.data.database.transaction_pooler ? ' (Supabase transaction pooler: no prepared statements)' : ''}</li></ul></Card>
        <Card title="Object storage" badges={<Tag s={d.data.storage.configured ? 'CONFIGURED' : 'NOT_CONFIGURED'} />}><ul className="space-y-1 text-xs text-slate-300"><li>Backend <b>{d.data.storage.backend}</b></li><li>{d.data.storage.buckets.length} private buckets</li>{d.data.storage.note && <li>{d.data.storage.note}</li>}</ul></Card>
        <Card title="Workers and frontend"><ul className="space-y-1 text-xs text-slate-300"><li>Embedded worker in API process: {d.data.embedded_worker ? 'yes (development)' : 'no (separate worker service)'}</li><li>{d.data.frontend}</li><li>{d.data.note}</li></ul></Card>
      </div>}</State>}
    </Page>
  )
}
