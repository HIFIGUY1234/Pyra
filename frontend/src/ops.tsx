/* Operational pages: Live Fire Map, Regional Fire Risk Forecast, Smart Observation Intelligence,
 * Government Monitoring Dashboard, Organisation Dashboard. */
import { Fragment, useEffect, useMemo, useState } from 'react'
import { Circle } from 'react-leaflet'
import { Link } from 'react-router-dom'
import { Bell, Building2, Download, Play, Plus, RefreshCw, Square, Trash2 } from 'lucide-react'
import { api, download, useApi, useApp, num, pct, compact, titleCase, Prov, Tabs, C, SAT_COLOR, SAT_LABEL, TIER_COLOR, TIERS, LAND_COLOR } from './lib'
import { Banner, Button, Card, CardBody, EmptyStateCard, FormGroup, RiskTierBadge, SimulatedBadge, Table, UncertaintyNote, ArgonStatCard } from './argon'
import { Series, StatusBars } from './charts'
import { BaseMap, BoxDraw, CellLayer, PointLayer, Swatch, seq } from './map'
import { enc, Load, PageHead, Panel, Td } from './science'

const esc = (s: any) => String(s ?? '–').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string))
const isoDay = (d: Date) => d.toISOString().slice(0, 10)
const addDays = (s: string, n: number) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return isoDay(d) }
const tierOf = (c: any) => c.tier || 'UNKNOWN'
const GOV_ROLES = ['gov_officer', 'admin']

/* ================================================================== 02 Live Fire Map */
type Layer = 'hotspots' | 'harmonized' | 'modis' | 'viirs' | 'forecast' | 'landuse'
const LAYERS: { key: Layer; label: string }[] = [
  { key: 'hotspots', label: 'Original detections' }, { key: 'modis', label: 'MODIS density' }, { key: 'viirs', label: 'VIIRS density' },
  { key: 'harmonized', label: 'Harmonized VIIRS-eq.' }, { key: 'forecast', label: 'Forecast risk tiers' }, { key: 'landuse', label: 'Land-use jurisdiction' },
]

export function LiveMapPage() {
  const { region, setRegion, meta } = useApp()
  const end = meta?.data_end || isoDay(new Date())
  const [start, setStart] = useState(addDays(end, -6))
  const [stop, setStop] = useState(end)
  const [sats, setSats] = useState<string[]>(['Terra', 'Aqua', 'Suomi NPP', 'NOAA-20', 'NOAA-21'])
  const [dn, setDn] = useState('')
  const [minConf, setMinConf] = useState(0)
  const [layers, setLayers] = useState<Layer[]>(['hotspots'])
  const [draw, setDraw] = useState(false)
  const [sel, setSel] = useState<any>(null)
  const on = (l: Layer) => layers.includes(l)
  const ym = (s: string) => Number(s.slice(0, 4)) * 100 + Number(s.slice(5, 7))
  const rq = region === 'country' ? '' : `&region=${enc(region)}`
  const hsQ = `/api/hotspots?start=${start}&end=${stop}${rq}&satellites=${enc(sats.join(','))}${dn ? `&daynight=${dn}` : ''}${minConf ? `&min_conf=${minConf}` : ''}&limit=6000`
  const hs = useApi<any>(on('hotspots') && sats.length ? hsQ : null)
  const cellsNeeded = on('harmonized') || on('modis') || on('viirs')
  const cl = useApi<any>(cellsNeeded ? `/api/hotspots/cell-layer?ym_from=${ym(start)}&ym_to=${ym(stop)}&region=${enc(region)}` : null)
  const fc = useApi<any>(on('forecast') ? `/api/forecast/${enc(region)}/grid-cells` : null)
  const geo = useApi<any>(`/api/geo/cells?region=${enc(region)}`)
  const hist = useApi<any>(`/api/historical-trends?region=${enc(region)}`)
  const anomalyLabel: Record<string, string> = (meta as any)?.anomaly_types || {}

  const cellRows: any[] = cl.data?.cells || []
  const cellVal = (c: any, l: Layer) => (l === 'harmonized' ? c.veq : l === 'modis' ? (c.Terra || 0) + (c.Aqua || 0) : (c['Suomi NPP'] || 0) + (c['NOAA-20'] || 0) + (c['NOAA-21'] || 0))
  const densityLayers = (['modis', 'viirs', 'harmonized'] as Layer[]).filter(on)
  const toggle = (l: Layer) => setLayers((x) => (x.includes(l) ? x.filter((y) => y !== l) : [...x, l]))
  const hotspotPopup = (p: any) => `<div style="font-size:12px;line-height:1.5"><b>${esc(SAT_LABEL[p.satellite] || p.satellite)}</b> · ${esc(p.product_type)} · <i>Actual observation</i><br/>
    ${esc(p.timestamp_utc)} (${p.daynight === 'D' ? 'day' : 'night'})<br/>Lat ${num(p.latitude, 4)}, Lon ${num(p.longitude, 4)}<br/>
    Confidence: <b>${esc(p.confidence_raw)}</b> (${esc(p.confidence_class)}, std. score ${num(p.confidence_score, 2)})<br/>
    FRP: ${p.frp_mw == null ? 'n/a' : `${num(p.frp_mw, 1)} MW`} · pixel ${num(p.pixel_area_km2, 2)} km² (scan ${num(p.scan, 2)} × track ${num(p.track, 2)})<br/>
    Type: ${p.anomaly_type == null ? 'not provided (NRT)' : esc(anomalyLabel[String(p.anomaly_type)] || p.anomaly_type)}${p.static_share > 0.3 ? ' · <b>cell often hosts static sources</b>' : ''}<br/>
    ${esc(p.district || '')} ${esc(p.state || '')} · land use: ${esc(p.land_use)}</div>`
  const yearly = (hist.data?.yearly || []).map((y: any) => ({ ...y, band: y.harm_lo == null ? null : [y.harm_lo, y.harm_hi] }))

  return (
    <div className="space-y-5">
      <PageHead idx="02" title="Live Fire Map" badges={<Prov kind="actual" />}
        intro="Original FIRMS detections (squares = MODIS 1 km, circles = VIIRS 375 m) with optional density, harmonized, forecast and land-use layers. Click a detection for full metadata. Draw a box to analyse a custom area everywhere in PyroScope." />
      <Card>
        <CardBody className="space-y-3 p-4">
          <div className="flex flex-wrap items-end gap-3 text-xs">
            <FormGroup label="From"><input type="date" value={start} max={stop} onChange={(e) => setStart(e.target.value)} /></FormGroup>
            <FormGroup label="To"><input type="date" value={stop} min={start} max={addDays(start, 92)} onChange={(e) => setStop(e.target.value)} /></FormGroup>
            <FormGroup label="Day / night"><select value={dn} onChange={(e) => setDn(e.target.value)}><option value="">Both</option><option value="D">Day</option><option value="N">Night</option></select></FormGroup>
            <FormGroup label={`Min. std. confidence ${minConf.toFixed(2)}`}><input type="range" min={0} max={0.9} step={0.05} value={minConf} onChange={(e) => setMinConf(Number(e.target.value))} /></FormGroup>
            <div className="flex flex-wrap gap-2">
              {['Terra', 'Aqua', 'Suomi NPP', 'NOAA-20', 'NOAA-21'].map((s) => (
                <label key={s} className="flex items-center gap-1.5 rounded border border-[#26324a] px-2 py-1">
                  <input type="checkbox" checked={sats.includes(s)} onChange={() => setSats((x) => (x.includes(s) ? x.filter((y) => y !== s) : [...x, s]))} />
                  <Swatch color={SAT_COLOR[s]} label={SAT_LABEL[s]} square={s === 'Terra' || s === 'Aqua'} />
                </label>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Layers</span>
            {LAYERS.map((l) => (
              <button key={l.key} onClick={() => toggle(l.key)} className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${on(l.key) ? 'border-orange-500 bg-orange-500/15 text-orange-200' : 'border-[#26324a] text-slate-400 hover:text-slate-200'}`}>{l.label}</button>
            ))}
            <span className="mx-1 h-4 w-px bg-[#26324a]" />
            <Button size="xs" variant={draw ? 'warning' : 'secondary'} onClick={() => setDraw((d) => !d)}><Square className="h-3 w-3" />{draw ? 'Click two corners…' : 'Draw custom area'}</Button>
            {region !== 'country' && <Button size="xs" variant="outline" onClick={() => setRegion('country')}>Reset to India</Button>}
          </div>
        </CardBody>
      </Card>
      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#26324a] px-4 py-2 text-xs text-slate-400">
            <span>{geo.data?.label || 'India'}{hs.loading && ' · loading detections…'}{hs.error && <span className="text-red-300"> · {hs.error}</span>}</span>
            {hs.data && <span>{num(hs.data.returned)} of {num(hs.data.total_matching)} detections shown{hs.data.thinned && ' (evenly thinned - narrow the filters to see all)'}</span>}
          </div>
          <BaseMap height={600} bbox={region === 'country' ? null : geo.data?.bbox}>
            {on('landuse') && geo.data && <CellLayer cells={geo.data.cells} colorOf={(c) => LAND_COLOR[c.land_use] || LAND_COLOR.Unknown} opacityOf={() => 0.35}
              popup={(c) => `<b>${esc(c.land_use)}</b><br/>${esc(c.district || '')} ${esc(c.state || '')}<br/>forest ${pct(c.lc_forest)} · cropland ${pct(c.lc_cropland)} · urban ${pct(c.lc_urban)}<br/><i>Land use decides who responds, not the fire cause.</i>`} />}
            {densityLayers.map((l) => {
              const max = Math.max(1, ...cellRows.map((c) => cellVal(c, l)))
              return <CellLayer key={l} cells={cellRows.filter((c) => cellVal(c, l) > 0)} colorOf={(c) => seq(cellVal(c, l), max)} opacityOf={() => 0.65}
                popup={(c) => `<b>${l === 'harmonized' ? 'VIIRS-equivalent estimate' : l === 'modis' ? 'MODIS detections (actual)' : 'VIIRS detections (actual)'}</b>: ${num(cellVal(c, l), 1)}<br/>Terra ${num(c.Terra)} · Aqua ${num(c.Aqua)} · S-NPP ${num(c['Suomi NPP'])} · NOAA-21 ${num(c['NOAA-21'])}<br/>VIIRS-eq. estimate ${num(c.veq, 1)}`} />
            })}
            {on('forecast') && fc.data && <CellLayer cells={fc.data.cells} colorOf={(c) => TIER_COLOR[tierOf(c)]} opacityOf={(c) => (c.tier === 'LOW' ? 0.25 : 0.6)}
              stroke={(c) => (c.tier === 'VERY_HIGH' ? '#fecaca' : undefined)}
              popup={(c) => `<b>${titleCase(c.tier)}</b> · 7-day hotspot probability ${pct(c.p)} (${pct(c.p_lo)}–${pct(c.p_hi)})<br/>${esc(c.district || '')} ${esc(c.state || '')} · ${esc(c.land_use)}<br/><i>Calibrated model forecast</i>`} />}
            {on('hotspots') && hs.data && <PointLayer points={hs.data.hotspots} colorOf={(p) => SAT_COLOR[p.satellite] || '#fff'} isSquare={(p) => p.instrument === 'MODIS'} popup={hotspotPopup} onClick={setSel} />}
            <BoxDraw active={draw} onDone={(b) => { setDraw(false); setRegion(`bbox:${b.join(',')}`) }} />
          </BaseMap>
          <div className="flex flex-wrap gap-3 border-t border-[#26324a] px-4 py-2">
            {on('forecast') && TIERS.map((t) => <Swatch key={t} color={TIER_COLOR[t]} label={titleCase(t)} square />)}
            {on('landuse') && Object.entries(LAND_COLOR).map(([k, v]) => <Swatch key={k} color={v} label={k} square />)}
            {densityLayers.length > 0 && <span className="text-[11px] text-slate-400">Density ramp: light = few, dark = many (log scale). Months {cl.data?.months?.join(' – ')}.</span>}
          </div>
        </Card>
        <div className="space-y-4">
          <Panel title="Selected detection" badge={sel ? <Prov kind="actual" /> : undefined}>
            {!sel ? <p className="text-xs text-slate-400">Click a detection on the map.</p> : (
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                {[['Satellite', SAT_LABEL[sel.satellite]], ['Product', sel.product_type], ['Acquired (UTC)', sel.timestamp_utc], ['Day/Night', sel.daynight === 'D' ? 'Day' : 'Night'],
                  ['Latitude', num(sel.latitude, 5)], ['Longitude', num(sel.longitude, 5)], ['Confidence (raw)', sel.confidence_raw], ['Confidence class', sel.confidence_class],
                  ['Std. confidence score', num(sel.confidence_score, 2)], ['FRP', sel.frp_mw == null ? 'n/a' : `${num(sel.frp_mw, 1)} MW`], ['Pixel area', `${num(sel.pixel_area_km2, 3)} km² (${num(sel.scan, 2)}×${num(sel.track, 2)})`],
                  ['Anomaly type', sel.anomaly_type == null ? 'not provided (NRT file)' : anomalyLabel[String(sel.anomaly_type)] || sel.anomaly_type], ['Static-source share (cell)', pct(sel.static_share)],
                  ['Land use', sel.land_use], ['District', sel.district || '–'], ['State', sel.state || '–'], ['Dataset', `${sel.dataset_version} (${sel.source_kind})`]].map(([k, v]) => (
                  <Fragment key={String(k)}><dt className="text-slate-400">{k}</dt><dd className="text-slate-100">{v}</dd></Fragment>
                ))}
              </dl>
            )}
            {sel && <p className="mt-2 text-[11px] text-slate-500">The standardized score is an ordinal convention; MODIS and VIIRS confidence are not comparable probabilities. A detection is not a confirmed wildfire.</p>}
          </Panel>
          <Panel title={`Fire history - ${hist.data?.region || '…'}`} badge={<Prov kind="veq" />}>
            {hist.data ? <Series data={yearly} x="year" monthly={false} height={200} legend={false} bands={[{ key: 'band', name: 'Band', color: C.est }]} lines={[{ key: 'harmonized', name: 'Harmonized', color: C.est, dots: true }, { key: 'viirs', name: 'Actual VIIRS', color: C.viirs }]} /> : <p className="text-xs text-slate-400">Loading…</p>}
            <p className="mt-1 text-[11px] text-slate-500">Yearly harmonized VIIRS-equivalent activity (amber) and actual S-NPP VIIRS (orange).</p>
          </Panel>
        </div>
      </div>
    </div>
  )
}

/* ================================================================== 10 Regional Fire Risk Forecast */
export function ForecastPage() {
  const { region, setRegion, meta } = useApp()
  const [issue, setIssue] = useState('')
  const [level, setLevel] = useState<'district' | 'state'>('district')
  const [cellId, setCellId] = useState<number | null>(null)
  const iq = issue ? `?issue_date=${issue}` : ''
  const model = useApi<any>('/api/forecast/model')
  const f = useApi<any>(model.data?.available ? `/api/forecast/${enc(region)}${iq}` : null)
  const cells = useApi<any>(model.data?.available ? `/api/forecast/${enc(region)}/grid-cells${iq}` : null)
  const rank = useApi<any>(model.data?.available ? `/api/forecast/ranking?level=${level}&top=40` : null)
  const cell = useApi<any>(cellId != null ? `/api/forecast/cell/${cellId}` : null)
  const geo = useApi<any>(`/api/geo/cells?region=${enc(region)}`)
  useEffect(() => setCellId(null), [region, issue])
  const d = f.data, m = model.data
  if (model.data && !m.available) return <EmptyStateCard title="No trained forecast model" description={m.message} action={<Link to="/data" className="text-xs text-orange-300 underline">Open Data Management</Link>} />

  return (
    <div className="space-y-5">
      <PageHead idx="10" title="Regional Fire Risk Forecast" badges={<Prov kind="forecast" />}
        intro="Calibrated 7-day probability of at least one detectable S-NPP VIIRS hotspot, computed per 0.25° grid cell and aggregated to the region with a dependence-adjusted joint probability - never a plain average."
        actions={<label className="flex items-center gap-2 text-xs text-slate-400">Issue date
          <select value={issue} onChange={(e) => setIssue(e.target.value)}><option value="">Latest</option>{(meta?.issue_dates || []).slice().reverse().map((x) => <option key={x}>{x}</option>)}</select></label>} />
      <Load loading={f.loading || model.loading} error={f.error || model.error} data={d} what="forecast">
        {d && (d.status !== 'ok' ? <Banner tone="warning">{d.message || d.status}</Banner> : <>
          <div className="grid gap-4 xl:grid-cols-[1.1fr_1fr]">
            <Card>
              <CardBody className="space-y-3 p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div><div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Selected area</div><div className="text-lg font-bold text-white">{d.region}</div></div>
                  <div className="flex flex-wrap gap-2"><Prov kind="forecast" text={d.mode === 'trained' ? 'Trained on historical detections' : 'Illustrative demo mode'} /></div>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div><div className="text-[11px] uppercase text-slate-400">Prediction period</div><div className="font-semibold text-slate-100">Next 7 days<br /><span className="text-xs font-normal text-slate-400">{d.prediction_period?.from} → {d.prediction_period?.to}</span></div></div>
                  <div><div className="text-[11px] uppercase text-slate-400">Regional probability</div><div className="text-3xl font-bold text-white tabular-nums">{pct(d.headline_probability)}</div>
                    <div className="text-[11px] text-slate-400">range {pct(d.regional?.p_any_lower)}–{pct(d.regional?.p_any_upper)}</div></div>
                  <div><div className="text-[11px] uppercase text-slate-400">Risk category</div><div className="mt-1"><RiskTierBadge tier={d.risk_category} /></div><div className="mt-1 text-[11px] text-slate-400">highest cell {pct(d.max_cell_probability)}</div></div>
                </div>
                <Banner tone={d.risk_category === 'VERY_HIGH' || d.risk_category === 'HIGH' ? 'danger' : 'info'} title="Suggested action">{d.suggested_action}</Banner>
                <p className="text-xs leading-relaxed text-slate-300"><strong className="text-white">Meaning: </strong>{d.meaning}</p>
                <p className="text-[11px] text-slate-400">{d.tier_basis} {d.aggregation_note}</p>
              </CardBody>
            </Card>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <ArgonStatCard title="Model confidence" value={`±${num((d.confidence?.model_band_mean_width || 0) * 50, 1)} pts`} subValue="mean bootstrap-model band half-width" provenance="Calibrated Forecast" />
                <ArgonStatCard title="Observation quality" value={pct(d.confidence?.observation_coverage_score)} subValue="reference-sensor coverage (separate from probability)" provenance="Actual Observation" />
                <ArgonStatCard title="Expected cells with a detection" value={num(d.regional?.expected_cells_with_detection, 1)} subValue={`of ${num(d.n_cells)} forecast cells`} provenance="Calibrated Forecast" />
                <ArgonStatCard title="Test skill" value={`AUC ${num(d.confidence?.test_roc_auc, 3)}`} subValue={`Brier ${num(d.confidence?.test_brier, 3)} (chronological hold-out)`} provenance="Calibrated Forecast" />
              </div>
              <UncertaintyNote>{d.confidence?.note} Target: {d.target}</UncertaintyNote>
            </div>
          </div>
          <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
            <Card className="overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#26324a] px-4 py-2 text-xs text-slate-400">
                <span>Grid-cell probabilities · click a cell for its drivers and jurisdiction</span>
                <span className="flex flex-wrap gap-2">{TIERS.map((t) => <Swatch key={t} color={TIER_COLOR[t]} label={`${titleCase(t)} (${num(d.tier_counts?.[t] || 0)})`} square />)}</span>
              </div>
              <BaseMap height={520} bbox={region === 'country' ? null : geo.data?.bbox}>
                {cells.data && <CellLayer cells={cells.data.cells} colorOf={(c) => TIER_COLOR[tierOf(c)]} opacityOf={(c) => (c.tier === 'LOW' ? 0.3 : 0.7)} stroke={(c) => (c.cell_id === cellId ? '#ffffff' : undefined)}
                  onClick={(c) => setCellId(c.cell_id)} popup={(c) => `<b>${titleCase(c.tier)}</b> ${pct(c.p)} (${pct(c.p_lo)}–${pct(c.p_hi)})<br/>${esc(c.district || '')} ${esc(c.state || '')} · ${esc(c.land_use)}`} />}
              </BaseMap>
            </Card>
            <CellPanel cell={cell} cellId={cellId} />
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            <Panel title="Seven-day prediction timeline" badge={<Prov kind="forecast" />} sub="Cumulative probability of a detection by each day.">
              <Series data={d.timeline} x="date" monthly={false} height={220} yFmt={(v) => `${Math.round(v * 100)}%`} yDomain={[0, 1]} xFmt={(v) => String(v).slice(5)}
                lines={[{ key: 'p_any_by_day', name: 'Regional', color: C.viirs, dots: true }, { key: 'max_cell_by_day', name: 'Highest cell', color: TIER_COLOR.VERY_HIGH, dots: true }]} />
            </Panel>
            <Panel title="Contributing factors" sub="Grouped SHAP-style contributions (log-odds) across the region's cells.">
              <StatusBars data={(d.factors || []).map((x: any) => ({ ...x, label: x.group.split(' ').slice(0, 2).join(' ') }))} x="label" y="contribution" name="Contribution" yFmt={(v) => num(v, 2)} height={220}
                colorOf={(r) => (r.contribution >= 0 ? TIER_COLOR.HIGH : '#3987e5')} />
            </Panel>
            <Panel title="Supporting conditions (regional mean)" badge={<Prov kind="actual" text="NASA POWER / FIRMS" />}>
              <dl className="grid grid-cols-[1fr_auto] gap-y-1.5 text-xs">
                {[['Max temperature, 7-day', `${num(d.supporting?.temperature_max_7d_c, 1)} °C`], ['Rainfall, 30 days', `${num(d.supporting?.rain_30d_mm, 0)} mm`], ['Relative humidity, 7-day', `${num(d.supporting?.humidity_7d_pct, 0)}%`],
                  ['Wind speed, 7-day', `${num(d.supporting?.wind_7d_ms, 1)} m/s`], ['Soil wetness, 7-day', num(d.supporting?.soil_wetness_7d, 2)], ['VIIRS detections, 7 days', num(d.supporting?.viirs_detections_7d)],
                  ['VIIRS detections, 30 days', num(d.supporting?.viirs_detections_30d)], ['Seasonal recurrence', pct(d.supporting?.seasonal_recurrence)]].map(([k, v]) => <Fragment key={String(k)}><dt className="text-slate-400">{k}</dt><dd className="text-right text-slate-100 tabular-nums">{v}</dd></Fragment>)}
              </dl>
            </Panel>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Historical comparison: forecast vs what was observed" sub="Past issue dates in the hold-out period." pad={false}>
              <div className="max-h-80 overflow-y-auto"><Table headers={['Issued', 'Regional p', 'Highest cell', 'Expected cells', 'Observed cells', 'Any detection']}>
                {(d.history || []).slice().reverse().map((h: any) => <tr key={h.issue_date}><Td mono>{h.issue_date}</Td><Td right>{pct(h.p_any)}</Td><Td right>{pct(h.max_cell)}</Td><Td right>{num(h.expected_cells, 1)}</Td><Td right>{num(h.observed_cells)}</Td><Td>{h.observed_any == null ? '–' : h.observed_any ? 'yes' : 'no'}</Td></tr>)}
              </Table></div>
            </Panel>
            <Panel title="Highest-risk regions" actions={<Tabs value={level} onChange={setLevel} options={[{ value: 'district', label: 'Districts' }, { value: 'state', label: 'States' }]} />} pad={false}>
              <div className="max-h-80 overflow-y-auto"><Table headers={['Region', 'Tier', 'Joint p', 'Highest cell', 'High / V.high cells', 'Coverage', '']}>
                {(rank.data?.items || []).map((r: any) => <tr key={r.id} className={r.id === region ? 'bg-orange-500/10' : ''}><Td>{r.name}</Td><Td><RiskTierBadge tier={r.tier} /></Td><Td right>{pct(r.p_any)}</Td><Td right>{pct(r.max_cell)}</Td><Td right>{r.cells_high} / {r.cells_very_high}</Td><Td right>{pct(r.coverage)}</Td><Td><Button size="xs" variant="outline" onClick={() => setRegion(r.id)}>Open</Button></Td></tr>)}
              </Table></div>
            </Panel>
          </div>
        </>)}
      </Load>
      {m?.available && <ModelCard m={m} />}
    </div>
  )
}

function CellPanel({ cell, cellId }: { cell: { data: any; loading: boolean; error: string | null }; cellId: number | null }) {
  const c = cell.data
  if (cellId == null) return <Panel title="Grid cell detail"><p className="text-xs text-slate-400">Click a grid cell on the map to see its probability, drivers, land use and responsible authority.</p></Panel>
  return (
    <Panel title={`Cell ${cellId}`} badge={<Prov kind="forecast" />}>
      {cell.loading && !c ? <p className="animate-pulse text-xs text-slate-400">Loading…</p> : cell.error ? <Banner tone="danger">{cell.error}</Banner> : c && (
        <div className="space-y-3 text-xs">
          <div className="flex items-center justify-between"><span className="text-2xl font-bold text-white">{pct(c.probability)}</span><RiskTierBadge tier={c.tier} /></div>
          <div className="text-slate-400">band {pct(c.p_lower)}–{pct(c.p_upper)} · seasonal recurrence {pct(c.seasonal_recurrence)}</div>
          <Series data={(c.daily_cumulative || []).map((p: number, i: number) => ({ day: `D${i + 1}`, p }))} x="day" monthly={false} height={110} legend={false} yFmt={(v) => `${Math.round(v * 100)}%`} yDomain={[0, 1]} lines={[{ key: 'p', name: 'Cumulative p', color: C.viirs, dots: true }]} />
          <div>
            <div className="mb-1 font-semibold text-slate-200">Drivers (log-odds contribution)</div>
            {(c.factors || []).map((g: any) => (
              <div key={g.group} className="flex items-center gap-2 py-0.5">
                <span className="w-40 shrink-0 truncate text-slate-300" title={g.group}>{g.group}</span>
                <div className="relative h-2 flex-1 rounded bg-[#172033]"><i className="absolute top-0 h-2 rounded" style={{ left: g.contribution >= 0 ? '50%' : `${50 - Math.min(50, Math.abs(g.contribution) * 25)}%`, width: `${Math.min(50, Math.abs(g.contribution) * 25)}%`, background: g.contribution >= 0 ? TIER_COLOR.HIGH : '#3987e5' }} /></div>
                <span className="w-12 text-right font-mono text-slate-400">{num(g.contribution, 2)}</span>
              </div>
            ))}
          </div>
          <div className="rounded border border-[#26324a] p-2">
            <div className="font-semibold text-slate-200">Jurisdiction · {c.jurisdiction?.land_use}</div>
            <div className="text-slate-400">{c.jurisdiction?.district || '–'}, {c.jurisdiction?.state || '–'}</div>
            <ul className="mt-1 list-disc pl-4 text-slate-300">{(c.jurisdiction?.authorities || []).map((a: any, i: number) => <li key={i}>L{a.level} {a.role_title} - {a.authority} {a.verified_contact ? <span className="text-emerald-300">(verified contact)</span> : <span className="text-amber-300">(no verified contact)</span>}</li>)}</ul>
            {c.jurisdiction?.routing_status === 'ADMIN_JURISDICTION_REVIEW_REQUIRED' && <div className="mt-1 font-semibold text-amber-300">{c.jurisdiction?.message}</div>}
            <div className="mt-1 text-[11px] text-slate-500">{c.jurisdiction?.note}</div>
          </div>
        </div>
      )}
    </Panel>
  )
}

function ModelCard({ m }: { m: any }) {
  const rel = (m.reliability || []).map((r: any, i: number) => ({ ...r, uncal: m.reliability_uncalibrated?.[i]?.observed, ideal: r.mean_pred }))
  return (
    <Panel title="Model, calibration & threshold validation" badge={<Prov kind="forecast" />} sub={`${m.target_kind}. ${m.trained_on}`}>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <ArgonStatCard title="Brier (test)" value={num(m.test?.brier, 4)} subValue={`climatology ${num(m.baseline_climatology?.brier, 4)}`} provenance="Calibrated Forecast" />
          <ArgonStatCard title="Brier skill vs climatology" value={pct(m.brier_skill_vs_climatology, 1)} provenance="Calibrated Forecast" />
          <ArgonStatCard title="ROC-AUC" value={num(m.test?.roc_auc, 3)} subValue={`PR-AUC ${num(m.test?.pr_auc, 3)}`} provenance="Calibrated Forecast" />
          <ArgonStatCard title="Base rate" value={pct(m.test?.base_rate, 1)} subValue={`${compact(m.test?.n)} test cell-weeks`} provenance="Actual Observation" />
          <ArgonStatCard title="Chronological split" value={<span className="text-sm">train ≤ {m.split?.train_until?.slice(0, 4)}</span>} subValue={`calibrate ≤ ${m.split?.calibrate_until?.slice(0, 4)} · test ${m.split?.test_from?.slice(0, 4)}–${m.split?.test_until?.slice(0, 4)}`} provenance="Calibrated Forecast" />
        </div>
        <div className="grid gap-4 xl:grid-cols-3">
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-200">Reliability (calibrated vs raw)</div>
            <Series data={rel} x="mean_pred" monthly={false} height={220} xFmt={(v) => `${Math.round(Number(v) * 100)}%`} yFmt={(v) => `${Math.round(v * 100)}%`} yDomain={[0, 1]}
              lines={[{ key: 'observed', name: 'Calibrated', color: C.viirs, dots: true }, { key: 'uncal', name: 'Uncalibrated', color: '#94a3b8', dash: '3 3' }, { key: 'ideal', name: 'Perfect', color: '#e2e8f0', dash: '2 4', width: 1 }]} />
            <p className="text-[11px] text-slate-500">{m.calibration_method}</p>
          </div>
          <div className="xl:col-span-2">
            <div className="mb-1 text-xs font-semibold text-slate-200">Confusion at the alert thresholds (test period)</div>
            <Table headers={['Threshold', 'TP', 'FP', 'FN', 'TN', 'Precision', 'Recall', 'False-alarm rate', 'False-alarm ratio', 'Missed-event rate']}>
              {['60', '80'].map((t) => { const c = m.test?.confusion?.[t]; return c && <tr key={t}><Td>≥ {t}%</Td><Td right>{compact(c.tp)}</Td><Td right>{compact(c.fp)}</Td><Td right>{compact(c.fn)}</Td><Td right>{compact(c.tn)}</Td><Td right>{pct(c.precision, 1)}</Td><Td right>{pct(c.recall, 1)}</Td><Td right>{pct(c.false_alarm_rate, 1)}</Td><Td right>{pct(c.false_alarm_ratio, 1)}</Td><Td right>{pct(c.missed_event_rate, 1)}</Td></tr> })}
            </Table>
            <div className="mt-3 mb-1 text-xs font-semibold text-slate-200">Feature importance (gain share, top 10)</div>
            <StatusBars data={(m.feature_importance || []).slice(0, 10).map((f: any) => ({ ...f, short: f.feature }))} x="short" y="gain_share" name="Gain share" yFmt={(v) => `${Math.round(v * 100)}%`} height={180} colorOf={() => C.viirs} />
            <p className="text-[11px] text-slate-500">{(m.feature_importance || []).slice(0, 10).map((f: any) => `${f.feature} = ${f.label}`).join(' · ')}</p>
          </div>
        </div>
      </div>
    </Panel>
  )
}

/* ================================================================== 12 Smart Observation Intelligence */
const REASON_COLOR = ['#3987e5', '#f97316', '#9085e9', '#d55181']
export function ObservationsPage() {
  const { region } = useApp()
  const [days, setDays] = useState(30)
  const q = useApi<any>(`/api/observations/quality?region=${enc(region)}&days=${days}`)
  const alt = useApi<any>(`/api/observations/alternatives?days=${days}`)
  const ov = useApi<any>('/api/observations/overpasses')
  const reasons = Object.keys(alt.data?.counts || {})
  const rc = (r: string) => REASON_COLOR[Math.max(0, reasons.indexOf(r)) % REASON_COLOR.length]
  const hist = useMemo(() => {
    const out: Record<string, any> = {}
    for (const h of ov.data?.observed_local_time_histogram || []) {
      const k = h.lst_bin
      out[k] = out[k] || { lst: k }
      out[k][h.satellite] = (out[k][h.satellite] || 0) + h.n
    }
    return Object.values(out).sort((a: any, b: any) => a.lst - b.lst)
  }, [ov.data])
  const drift = useMemo(() => {
    const out: Record<string, any> = {}
    for (const r of ov.data?.orbit_drift || []) { out[r.year] = out[r.year] || { year: r.year }; out[r.year][r.satellite] = r.drift_h }
    return Object.values(out).sort((a: any, b: any) => a.year - b.year)
  }, [ov.data])
  const d = q.data
  return (
    <div className="space-y-5">
      <PageHead idx="12" title="Smart Observation Intelligence" badges={<Prov kind="actual" />}
        intro="Where are the observations incomplete or unreliable, and can another satellite fill the gap? Compares Terra, Aqua, S-NPP, NOAA-20 and NOAA-21 coverage, cloud/rain obscuration and model disagreement."
        actions={<label className="flex items-center gap-2 text-xs text-slate-400">Window<select value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 14, 30, 60, 90, 120].map((x) => <option key={x} value={x}>{x} days</option>)}</select></label>} />
      <Load loading={q.loading} error={q.error} data={d} what="observation quality">
        {d && <>
          <Banner tone="info" title="Limits">{d.limits}</Banner>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <ArgonStatCard title="Coverage score" value={pct(d.coverage_score)} subValue={d.coverage_score_definition} provenance="Actual Observation" />
            <ArgonStatCard title="Rain days (recent)" value={num(d.obscuration?.rain_days_recent)} subValue={`${num(d.obscuration?.rain_mm_recent, 0)} mm - rain implies cloud`} provenance="Actual Observation" />
            <ArgonStatCard title="Cloud (recent)" value={d.obscuration?.cloud_pct_recent == null ? 'not yet available' : `${num(d.obscuration.cloud_pct_recent, 0)}%`} subValue={`climatology same months ${num(d.obscuration?.cloud_pct_climatology_same_months, 0)}%`} provenance="Actual Observation" />
            <ArgonStatCard title="Window" value={<span className="text-base">{d.window?.[0]} → {d.window?.[1]}</span>} subValue={d.region} provenance="Actual Observation" />
          </div>
          <p className="text-[11px] text-slate-500">{d.obscuration?.cloud_note}</p>
          <Panel title={`Sensor-by-sensor observation record - ${d.region}`} pad={false}>
            <Table headers={['Sensor', 'Loaded', 'Days observing', 'Gap days', 'Days with detections', 'Detections', 'Low / high conf.', 'Mean pixel', 'Night share', 'Last detection']}>
              {d.sensors.map((s: any) => (
                <tr key={s.satellite} className={s.loaded ? '' : 'opacity-60'}>
                  <Td><span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-full" style={{ background: SAT_COLOR[s.satellite] }} />{s.label}</span></Td>
                  <Td>{s.loaded ? 'yes' : <span className="text-amber-300">not loaded</span>}</Td>
                  <Td right>{s.loaded ? `${num(s.days_observing)} / ${num(s.days_in_record)}` : '–'}</Td><Td right>{s.loaded ? num(s.gap_days) : '–'}</Td><Td right>{s.loaded ? num(s.days_with_detections) : '–'}</Td>
                  <Td right>{s.loaded ? num(s.detections) : '–'}</Td><Td right>{s.loaded ? `${pct(s.low_conf_share)} / ${pct(s.high_conf_share)}` : '–'}</Td>
                  <Td right>{s.loaded ? `${num(s.mean_pixel_km2, 2)} km²` : '–'}</Td><Td right>{s.loaded ? pct(s.night_share) : '–'}</Td><Td mono>{s.last_detection || '–'}</Td>
                </tr>
              ))}
            </Table>
          </Panel>
          {Array.isArray(d.alternatives_on_gap_days) && d.alternatives_on_gap_days.length > 0 && (
            <Panel title="Alternative sensors on reference-sensor gap days" pad={false}>
              <Table headers={Object.keys(d.alternatives_on_gap_days[0])}>{d.alternatives_on_gap_days.map((r: any, i: number) => <tr key={i}>{Object.values(r).map((v: any, j) => <Td key={j}>{typeof v === 'number' ? num(v, 2) : String(v)}</Td>)}</tr>)}</Table>
            </Panel>
          )}
        </>}
      </Load>
      <Load loading={alt.loading} error={alt.error} data={alt.data} what="monitoring gaps">
        {alt.data && <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center gap-3 border-b border-[#26324a] px-4 py-2 text-xs text-slate-400">
              <span>Cells where additional monitoring may be needed (last {alt.data.window_days} days)</span>
              {reasons.map((r) => <Swatch key={r} color={rc(r)} label={`${r} (${alt.data.counts[r]})`} square />)}
            </div>
            <BaseMap height={460}>
              <CellLayer cells={alt.data.items} colorOf={(c) => rc(c.reason)} opacityOf={() => 0.75}
                popup={(c) => `<b>${esc(c.reason)}</b><br/>${esc(c.district || '')} ${esc(c.state || '')} · ${esc(c.land_use)}<br/>forecast ${pct(c.p)} (${pct(c.p_lo)}–${pct(c.p_hi)})<br/>Terra ${num(c.Terra)} · Aqua ${num(c.Aqua)} · S-NPP ${num(c['Suomi NPP'])} · NOAA-21 ${num(c['NOAA-21'])}<br/>S-NPP gap share ${pct(c.f_gap30)}`} />
            </BaseMap>
          </Card>
          <Panel title="Monitoring-gap cells" pad={false}>
            <div className="max-h-[460px] overflow-y-auto"><Table headers={['Area', 'Reason', 'MODIS', 'VIIRS', 'Forecast']}>
              {alt.data.items.map((c: any) => <tr key={c.cell_id}><Td>{c.district || '–'}<div className="text-[10px] text-slate-500">{c.state}</div></Td><Td><span style={{ color: rc(c.reason) }}>{c.reason}</span></Td><Td right>{num((c.Terra || 0) + (c.Aqua || 0))}</Td><Td right>{num((c['Suomi NPP'] || 0) + (c['NOAA-21'] || 0))}</Td><Td right>{pct(c.p)}</Td></tr>)}
            </Table></div>
          </Panel>
        </div>}
      </Load>
      <Load loading={ov.loading} error={ov.error} data={ov.data} what="overpasses">
        {ov.data && <>
          <Banner tone={ov.data.reliable_orbital_data ? 'success' : 'warning'} title={ov.data.reliable_orbital_data ? 'Orbital data available' : 'No reliable orbital data - future overpasses are not predicted'}>{ov.data.message}</Banner>
          <div className="grid gap-4 xl:grid-cols-3">
            <Panel title="Nominal local equator-crossing times" pad={false}>
              <Table headers={['Sensor', 'Day pass', 'Night pass']}>
                {Object.entries(ov.data.nominal_local_time_hours || {}).map(([s, t]: any) => <tr key={s}><Td>{SAT_LABEL[s] || s}</Td><Td right>{t.day.toFixed(1)} h</Td><Td right>{t.night.toFixed(1)} h</Td></tr>)}
              </Table>
            </Panel>
            <Panel title="Observed local solar time of detections" sub="From the data itself (recent window).">
              <Series data={hist} x="lst" monthly={false} height={220} xFmt={(v) => `${v}h`} bars={Object.keys(SAT_COLOR).filter((s) => hist.some((h: any) => h[s])).map((s) => ({ key: s, name: SAT_LABEL[s], color: SAT_COLOR[s], stack: 'a' }))} />
            </Panel>
            <Panel title="Orbit drift (day-pass LST vs baseline, hours)" sub="Terra and Aqua drifted late in their missions; drifted years are excluded from calibration.">
              <Series data={drift} x="year" monthly={false} height={220} yFmt={(v) => num(v, 2)} yDomain={['auto', 'auto']} refs={[{ y: 0.25, label: '+0.25 h' }, { y: -0.25, label: '−0.25 h' }]}
                lines={['Terra', 'Aqua', 'Suomi NPP', 'NOAA-20', 'NOAA-21'].filter((s) => drift.some((r: any) => r[s] != null)).map((s) => ({ key: s, name: SAT_LABEL[s], color: SAT_COLOR[s], dots: true }))} />
            </Panel>
          </div>
        </>}
      </Load>
    </div>
  )
}

/* ================================================================== 14 Government Monitoring Dashboard */
const ACTIONS = ['acknowledge', 'verify', 'approve', 'reject', 'escalate'] as const
export function GovernmentPage() {
  const { role, region, setRegion, meta } = useApp()
  const can = GOV_ROLES.includes(role)
  const [landUse, setLandUse] = useState('')
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger' | 'info'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const lu = landUse ? `&land_use=${enc(landUse)}` : ''
  const adv = useApi<any>(`/api/alerts?alert_type=ADVISORY&open_only=true&limit=50${lu}`)
  const det = useApi<any>(`/api/alerts?alert_type=UNVERIFIED_SATELLITE_DETECTION&open_only=true&limit=50${lu}`)
  const crit = useApi<any>('/api/critical-regions?top=20')
  const cells = useApi<any>(`/api/forecast/${enc(region)}/grid-cells`)
  const thr = useApi<any>('/api/thresholds/config')
  const dash = useApi<any>('/api/dashboard/summary')
  const audit = useApi<any>(can ? '/api/audit?limit=25' : null)
  const reload = () => { adv.reload(); det.reload(); audit.reload() }
  const evaluate = () => {
    setBusy(true); setMsg(null)
    api('/api/alerts/evaluate', { body: {} }).then((s: any) => {
      setMsg({ tone: s.status === 'ok' ? 'success' : 'info', text: s.status === 'ok' ? `Evaluation complete for issue ${s.issue_date ?? 'latest'}: ${s.created ?? 0} advisories created (${s.jurisdiction_review_required ?? 0} need administrator jurisdiction review, ${s.held_insufficient_evidence ?? 0} held for insufficient evidence), ${s.duplicates_skipped ?? 0} duplicates skipped, ${s.cooldown_suppressed ?? 0} suppressed by cooldown, ${s.superseded ?? 0} superseded, ${s.downgraded ?? 0} downgraded, ${s.detection_alerts_created ?? 0} unverified detection alerts.` : s.message || s.status })
      reload()
    }).catch((e) => setMsg({ tone: 'danger', text: e.message })).finally(() => setBusy(false))
  }
  const act = (id: string, a: string) => {
    const note = a === 'reject' || a === 'escalate' ? window.prompt(`Reason for ${a}:`) ?? undefined : undefined
    if ((a === 'reject' || a === 'escalate') && note === undefined) return
    api(`/api/alerts/${enc(id)}/${a}`, { body: { note } }).then(() => { setMsg({ tone: 'success', text: `${id}: ${a} recorded in the audit log.` }); reload() }).catch((e) => setMsg({ tone: 'danger', text: e.message }))
  }
  const report = () => {
    api('/api/reports/generate', { body: { region_id: region, format: 'pdf', kind: 'full' } }).then((r: any) => download(`/api/reports/${r.id}/download`, r.file)).catch((e) => setMsg({ tone: 'danger', text: e.message }))
  }
  const fcells = useMemo(() => (cells.data?.cells || []).filter((c: any) => !landUse || c.land_use === landUse), [cells.data, landUse])
  const def = (thr.data?.configs || []).find((c: any) => c.scope_type === 'default')
  const tl = (dash.data?.timeline || []).map((r: any) => ({ ...r, band: r.veq_lo == null ? null : [r.veq_lo, r.veq_hi] }))

  const Feed = ({ title, data, kind }: { title: string; data: any; kind: 'adv' | 'det' }) => (
    <Panel title={`${title} (${data.data?.total ?? '…'})`} badge={kind === 'adv' ? <Prov kind="forecast" text="Predicted pre-fire risk advisory" /> : <Prov kind="actual" text="Unverified satellite detection" />} pad={false}>
      <Load loading={data.loading} error={data.error} data={data.data} what="alerts">
        {data.data?.items?.length ? <div className="max-h-[420px] overflow-y-auto"><Table headers={['Alert', kind === 'adv' ? 'Probability' : 'Detection', 'Region / land use', 'Status / routing', can ? 'Actions' : '']}>
          {data.data.items.map((a: any) => (
            <tr key={a.alert_id} className="align-top hover:bg-[#172033]/60">
              <Td><div className="font-mono text-[11px] text-slate-200">{a.alert_id}</div><div className="mt-0.5">{kind === 'adv' ? <RiskTierBadge tier={a.risk_category} /> : <span className="text-[11px] text-sky-300">{SAT_LABEL[a.satellite] || a.satellite}</span>}</div><div className="text-[10px] text-slate-500">{titleCase(a.alert_type)}</div></Td>
              <Td>{kind === 'adv' ? <><strong>{pct(a.probability)}</strong><div className="text-[10px] text-slate-400">{pct(a.p_lower)}–{pct(a.p_upper)} · {a.n_cells ?? '–'} cells</div></> : <>{a.frp_mw == null ? 'FRP n/a' : `${num(a.frp_mw, 1)} MW`}<div className="text-[10px] text-slate-400">{a.issue_date}</div></>}</Td>
              <Td>{a.region_name}<div className="text-[10px] text-slate-400">{a.land_use} · {a.state}</div></Td>
              <Td><div className="text-[11px] font-semibold">{titleCase(a.status)}</div><div className={`text-[10px] ${a.routing_status === 'ROUTED_TO_VERIFIED_CONTACT' ? 'text-emerald-300' : 'text-amber-300'}`}>{titleCase(a.routing_status)}</div></Td>
              <Td>{can && <div className="flex flex-wrap gap-1">{ACTIONS.map((x) => <Button key={x} size="xs" variant={x === 'reject' ? 'danger' : x === 'escalate' ? 'warning' : 'outline'} onClick={() => act(a.alert_id, x)}>{titleCase(x)}</Button>)}</div>}</Td>
            </tr>
          ))}
        </Table></div> : <p className="p-4 text-xs text-slate-400">No open {kind === 'adv' ? 'advisories' : 'detection alerts'}{landUse ? ` for ${landUse}` : ''}. Run an evaluation to generate them from the latest calibrated forecast.</p>}
      </Load>
    </Panel>
  )

  return (
    <div className="space-y-5">
      <PageHead idx="14" title="Government Monitoring Dashboard" badges={<SimulatedBadge />}
        intro="For forest departments, agriculture officers, panchayats and municipal fire services: review advisories and unverified detections, check the evidence, and acknowledge, verify, approve, reject or escalate. PyroScope never issues public emergency warnings or dispatches services."
        actions={<>
          <select aria-label="Jurisdiction land use" value={landUse} onChange={(e) => setLandUse(e.target.value)}><option value="">All land-use jurisdictions</option>{(meta?.land_use_classes || []).map((l) => <option key={l}>{l}</option>)}</select>
          <Button size="sm" onClick={evaluate} disabled={!can || busy} title={can ? '' : 'Requires a government officer or admin persona'}><Play className="h-3.5 w-3.5" />{busy ? 'Evaluating…' : 'Evaluate alerts'}</Button>
          <Button size="sm" variant="outline" onClick={reload}><RefreshCw className="h-3.5 w-3.5" /></Button>
        </>} />
      {!can && <Banner tone="warning" title="Read-only">Your current persona ({role}) can view this dashboard but cannot act on alerts. Switch to a government officer or admin persona in the top bar.</Banner>}
      {msg && <Banner tone={msg.tone}>{msg.text}</Banner>}
      <div className="grid gap-3 md:grid-cols-4">
        {[['Predicted Pre-Fire Risk Advisory', 'Model forecast ≥ HIGH threshold. Needs human review.', 'border-orange-500/50'], ['Unverified Satellite Hotspot Detection', 'A real MODIS/VIIRS detection - not yet confirmed on the ground.', 'border-sky-500/50'],
          ['Verified Fire Incident', 'Only after an authorised officer verifies on the ground.', 'border-emerald-500/50'], ['Official Public Emergency Warning', 'Issued only through the authority\'s own channels. PyroScope never issues one.', 'border-red-500/50']].map(([t, s, b]) => (
          <div key={t} className={`rounded-xl border ${b} bg-[#111827] px-4 py-3`}><div className="text-xs font-bold text-white">{t}</div><div className="mt-1 text-[11px] text-slate-400">{s}</div></div>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Feed title="Pre-fire risk advisories (60% High / 80% Very High)" data={adv} kind="adv" />
        <Feed title="Unverified satellite detection alerts" data={det} kind="det" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#26324a] px-4 py-2 text-xs text-slate-400">
            <span>7-day calibrated risk by grid cell · {landUse || 'all jurisdictions'} · {fcells.length} cells</span>
            <span className="flex flex-wrap gap-2">{TIERS.map((t) => <Swatch key={t} color={TIER_COLOR[t]} label={titleCase(t)} square />)}</span>
          </div>
          <BaseMap height={440}>
            <CellLayer cells={fcells} colorOf={(c) => TIER_COLOR[tierOf(c)]} opacityOf={(c) => (c.tier === 'LOW' ? 0.2 : 0.7)} popup={(c) => `<b>${titleCase(c.tier)}</b> ${pct(c.p)} (${pct(c.p_lo)}–${pct(c.p_hi)})<br/>${esc(c.district || '')} ${esc(c.state || '')} · ${esc(c.land_use)}`} />
          </BaseMap>
        </Card>
        <Panel title="Critical regions" sub="Priority combines forecast, recurrence, FRP, gaps and exposure." pad={false}>
          <div className="max-h-[440px] overflow-y-auto"><Table headers={['District', 'Priority', 'p', '']}>
            {(crit.data?.items || []).filter((c: any) => !landUse || c.land_use === landUse).map((c: any) => (
              <tr key={c.id}><Td>{c.name}<div className="text-[10px] text-slate-500">{c.state} · {c.land_use}</div></Td><Td><RiskTierBadge tier={c.priority} customLabel={titleCase(c.priority)} /></Td><Td right>{pct(c.p_any)}</Td><Td><Button size="xs" variant="outline" onClick={() => setRegion(c.id)}>Focus</Button></Td></tr>
            ))}
          </Table></div>
        </Panel>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Harmonized historical activity (India)" badge={<Prov kind="veq" />}>
          <Series data={tl} height={200} legend={false} bands={[{ key: 'band', name: 'Band', color: C.est }]} lines={[{ key: 'harmonized', name: 'Harmonized', color: C.est }]} />
        </Panel>
        <Panel title="Active thresholds" sub={thr.data?.governance} actions={<Link to="/thresholds" className="text-xs text-orange-300 underline">Configure</Link>}>
          {def ? <div className="space-y-1">{(def.tiers || []).map((t: any) => <div key={t.name} className="flex items-center justify-between text-xs"><RiskTierBadge tier={t.name} /><span className="font-mono text-slate-300">{Math.round(t.min * 100)}–{Math.round(t.max * 100)}%</span></div>)}
            <div className="pt-1 text-[11px] text-slate-400">cooldown {def.cooldown_hours} h · evidence ≥ {def.evidence_min} indicators · {(thr.data?.configs || []).length - 1} override(s)</div></div> : <p className="text-xs text-slate-400">Loading…</p>}
        </Panel>
        <Panel title="Reports" sub="Official advisory report for the active region (PDF).">
          <Button size="sm" onClick={report}><Download className="h-3.5 w-3.5" />Generate & download PDF</Button>
          <p className="mt-2 text-[11px] text-slate-500">Includes harmonized history, forecast, grid-cell breakdown, alert routing log, observation quality and disclaimers. <Link to="/reports" className="text-orange-300 underline">All reports</Link></p>
        </Panel>
      </div>
      {can && <Panel title="Monitoring history (audit log)" pad={false}>
        <Load loading={audit.loading} error={audit.error} data={audit.data} what="audit log">
          <div className="max-h-80 overflow-y-auto"><Table headers={['When (UTC)', 'Actor', 'Action', 'Entity', 'Detail']}>
            {(audit.data?.items || []).map((r: any, i: number) => <tr key={i}><Td mono>{r.at?.slice(0, 16).replace('T', ' ')}</Td><Td>{r.actor} <span className="text-slate-500">({r.role})</span></Td><Td>{titleCase(r.action)}</Td><Td mono>{r.entity_id}</Td><Td><span className="text-[10px] text-slate-400">{r.detail ? JSON.stringify(r.detail).slice(0, 120) : ''}</span></Td></tr>)}
          </Table></div>
        </Load>
      </Panel>}
    </div>
  )
}

/* ================================================================== 15 Organisation Dashboard */
const SECTORS = ['Insurance', 'Agriculture', 'Electricity / utility', 'Industrial facility', 'Logistics', 'Infrastructure operator', 'Environmental organisation', 'Other']
const TAGS = ['Industrial', 'Utility Corridor', 'Agricultural Cooperative', 'Warehouse / Logistics', 'Infrastructure', 'Forest Concession', 'Other']
export function OrganisationPage() {
  const { role } = useApp()
  const can = role === 'org_user' || role === 'admin'
  const orgs = useApi<any>(can ? '/api/organisations' : null)
  const [orgId, setOrgId] = useState<number | null>(null)
  const ov = useApi<any>(orgId != null ? `/api/organisations/${orgId}/overview` : null)
  const [org, setOrg] = useState({ name: '', sector: SECTORS[0], contact_email: '' })
  const [loc, setLoc] = useState({ name: '', land_use_tag: TAGS[0], latitude: '30.9', longitude: '75.85', buffer_km: '25', alert_threshold: '0.6', notify_safety_team: true })
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null)
  useEffect(() => { if (orgId == null && orgs.data?.items?.length) setOrgId(orgs.data.items[0].id) }, [orgs.data, orgId])
  const fail = (e: any) => setMsg({ tone: 'danger', text: e.message })
  const createOrg = () => api('/api/organisations', { body: { ...org, contact_email: org.contact_email || null } }).then((r: any) => { setMsg({ tone: 'success', text: `Registered ${r.name}.` }); setOrg({ ...org, name: '', contact_email: '' }); orgs.reload(); setOrgId(r.id) }).catch(fail)
  const addLoc = () => orgId != null && api(`/api/organisations/${orgId}/locations`, { body: { ...loc, latitude: Number(loc.latitude), longitude: Number(loc.longitude), buffer_km: Number(loc.buffer_km), alert_threshold: Number(loc.alert_threshold) } })
    .then(() => { setMsg({ tone: 'success', text: `Added ${loc.name}.` }); setLoc({ ...loc, name: '' }); ov.reload(); orgs.reload() }).catch(fail)
  const delLoc = (id: number) => orgId != null && window.confirm('Remove this monitoring location?') && api(`/api/organisations/${orgId}/locations/${id}`, { method: 'DELETE' }).then(() => { ov.reload(); orgs.reload() }).catch(fail)
  const report = (rid: string, fmt: 'pdf' | 'csv') => api('/api/reports/generate', { body: { region_id: rid, format: fmt, kind: fmt === 'csv' ? 'forecast_cells' : 'full', organisation_id: orgId } }).then((r: any) => download(`/api/reports/${r.id}/download`, r.file)).catch(fail)

  if (!can) return (
    <div className="space-y-5">
      <PageHead idx="15" title="Organisation Dashboard" intro="Facility and monitoring-area surveillance for insurers, utilities, agricultural cooperatives, industrial facilities and logistics operators." />
      <EmptyStateCard title="Organisation persona required" description={`Your current persona (${role}) has no organisation access. Switch to “Organisation User” or “Administrator” in the top bar. Organisation data is private to the account that registered it.`} />
    </div>
  )
  return (
    <div className="space-y-5">
      <PageHead idx="15" title="Organisation Dashboard" badges={<SimulatedBadge />}
        intro="Register facilities with a land-use tag and buffer zone. PyroScope reports nearby MODIS/VIIRS detections, the facility's harmonized fire history and the calibrated 7-day probability, and raises a simulated notification to the safety team when your threshold is met." />
      {msg && <Banner tone={msg.tone}>{msg.text}</Banner>}
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Your organisations" pad={false}>
          <Load loading={orgs.loading} error={orgs.error} data={orgs.data} what="organisations">
            {orgs.data?.items?.length ? <ul className="divide-y divide-[#26324a]">{orgs.data.items.map((o: any) => (
              <li key={o.id}><button onClick={() => setOrgId(o.id)} className={`flex w-full items-center justify-between px-4 py-2.5 text-left text-xs ${o.id === orgId ? 'bg-orange-500/10 text-white' : 'text-slate-300 hover:bg-[#172033]'}`}>
                <span><Building2 className="mr-1.5 inline h-3.5 w-3.5 text-orange-400" />{o.name}<span className="block pl-5 text-[10px] text-slate-500">{o.sector}</span></span><span className="text-slate-400">{o.locations} site(s)</span></button></li>))}</ul>
              : <p className="p-4 text-xs text-slate-400">No organisation registered yet.</p>}
          </Load>
        </Panel>
        <Panel title="Register organisation">
          <div className="space-y-2.5">
            <FormGroup label="Name"><input className="w-full" value={org.name} onChange={(e) => setOrg({ ...org, name: e.target.value })} /></FormGroup>
            <FormGroup label="Sector"><select className="w-full" value={org.sector} onChange={(e) => setOrg({ ...org, sector: e.target.value })}>{SECTORS.map((s) => <option key={s}>{s}</option>)}</select></FormGroup>
            <FormGroup label="Safety-team email (optional)" hint="Stored privately. Deliveries are simulated in this prototype."><input className="w-full" type="email" value={org.contact_email} onChange={(e) => setOrg({ ...org, contact_email: e.target.value })} /></FormGroup>
            <Button size="sm" onClick={createOrg} disabled={org.name.trim().length < 2}><Plus className="h-3.5 w-3.5" />Register</Button>
          </div>
        </Panel>
        <Panel title="Add monitoring location" sub={orgId == null ? 'Register or select an organisation first.' : undefined}>
          <div className="grid grid-cols-2 gap-2.5">
            <div className="col-span-2"><FormGroup label="Facility name"><input className="w-full" value={loc.name} onChange={(e) => setLoc({ ...loc, name: e.target.value })} /></FormGroup></div>
            <FormGroup label="Land-use tag"><select className="w-full" value={loc.land_use_tag} onChange={(e) => setLoc({ ...loc, land_use_tag: e.target.value })}>{TAGS.map((t) => <option key={t}>{t}</option>)}</select></FormGroup>
            <FormGroup label="Buffer (km)"><input className="w-full" type="number" min={1} max={200} value={loc.buffer_km} onChange={(e) => setLoc({ ...loc, buffer_km: e.target.value })} /></FormGroup>
            <FormGroup label="Latitude"><input className="w-full" type="number" step="0.01" value={loc.latitude} onChange={(e) => setLoc({ ...loc, latitude: e.target.value })} /></FormGroup>
            <FormGroup label="Longitude"><input className="w-full" type="number" step="0.01" value={loc.longitude} onChange={(e) => setLoc({ ...loc, longitude: e.target.value })} /></FormGroup>
            <FormGroup label={`Alert threshold ${Math.round(Number(loc.alert_threshold) * 100)}%`}><input type="range" min={0.2} max={0.95} step={0.05} value={loc.alert_threshold} onChange={(e) => setLoc({ ...loc, alert_threshold: e.target.value })} /></FormGroup>
            <label className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={loc.notify_safety_team} onChange={(e) => setLoc({ ...loc, notify_safety_team: e.target.checked })} />Notify safety team</label>
            <div className="col-span-2"><Button size="sm" onClick={() => addLoc()} disabled={orgId == null || loc.name.trim().length < 2}><Plus className="h-3.5 w-3.5" />Add location</Button></div>
          </div>
        </Panel>
      </div>
      {orgId != null && <Load loading={ov.loading} error={ov.error} data={ov.data} what="organisation overview">
        {ov.data && <>
          <p className="text-[11px] text-slate-500">{ov.data.privacy}</p>
          {ov.data.locations.length === 0 && <EmptyStateCard title="No monitoring locations" description="Add a facility above to start monitoring nearby fire activity and forecast risk." />}
          {ov.data.locations.map((l: any) => <LocationCard key={l.id} l={l} onDelete={() => delLoc(l.id)} onReport={(f) => report(l.region_id, f)} />)}
        </>}
      </Load>}
    </div>
  )
}

function LocationCard({ l, onDelete, onReport }: { l: any; onDelete: () => void; onReport: (f: 'pdf' | 'csv') => void }) {
  const fc = l.forecast || {}
  const hist = (l.history || []).filter((h: any) => h.complete)
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#26324a] px-5 py-3">
        <div><div className="flex items-center gap-2"><h3 className="text-sm font-semibold text-white">{l.name}</h3><span className="rounded border border-[#26324a] px-1.5 py-0.5 text-[10px] text-slate-300">{l.land_use_tag}</span>{l.threshold_breached && <RiskTierBadge tier="VERY_HIGH" customLabel="Threshold met" />}</div>
          <div className="text-[11px] text-slate-400">{num(l.latitude, 3)}, {num(l.longitude, 3)} · buffer {num(l.buffer_km)} km · your threshold {pct(l.alert_threshold)} · jurisdiction {l.jurisdiction?.land_use} ({l.jurisdiction?.district || '–'}, {l.jurisdiction?.state || '–'})</div></div>
        <div className="flex gap-2"><Button size="xs" variant="outline" onClick={() => onReport('pdf')}><Download className="h-3 w-3" />PDF</Button><Button size="xs" variant="outline" onClick={() => onReport('csv')}><Download className="h-3 w-3" />CSV</Button><Button size="xs" variant="danger" onClick={onDelete}><Trash2 className="h-3 w-3" /></Button></div>
      </div>
      <CardBody className="grid gap-4 p-4 xl:grid-cols-[1fr_1fr_1.2fr]">
        <div className="space-y-3">
          {l.notification && <Banner tone="danger" title={<span className="flex items-center gap-2"><Bell className="h-3.5 w-3.5" />Notification to {l.notification.to} <SimulatedBadge /></span>}>{l.notification.text}</Banner>}
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded border border-[#26324a] p-2"><div className="text-[10px] uppercase text-slate-400">Highest cell p (7 d)</div><div className="text-xl font-bold text-white">{pct(fc.max_cell_probability)}</div><RiskTierBadge tier={fc.risk_category} /></div>
            <div className="rounded border border-[#26324a] p-2"><div className="text-[10px] uppercase text-slate-400">Buffer joint p</div><div className="text-xl font-bold text-white">{pct(fc.headline_probability)}</div><div className="text-[10px] text-slate-500">issue {fc.issue_date || '–'}</div></div>
            <div className="rounded border border-[#26324a] p-2"><div className="text-[10px] uppercase text-slate-400">Detections in buffer, 7 d</div><div className="text-xl font-bold text-white">{num(l.nearby_7d?.total)}</div><div className="text-[10px] text-slate-500">nearest {l.nearby_7d?.nearest_km == null ? '–' : `${num(l.nearby_7d.nearest_km, 1)} km`}</div></div>
            <div className="rounded border border-[#26324a] p-2"><div className="text-[10px] uppercase text-slate-400">Max FRP</div><div className="text-xl font-bold text-white">{l.nearby_7d?.max_frp_mw == null ? '–' : `${num(l.nearby_7d.max_frp_mw, 0)}`}</div><div className="text-[10px] text-slate-500">MW</div></div>
          </div>
          <div className="flex flex-wrap gap-2 text-[11px]">{Object.entries(l.nearby_7d?.by_satellite || {}).map(([s, n]: any) => <Swatch key={s} color={SAT_COLOR[s]} label={`${SAT_LABEL[s] || s}: ${n}`} square={s === 'Terra' || s === 'Aqua'} />)}</div>
          {fc.status !== 'ok' && fc.message && <Banner tone="info">{fc.message}</Banner>}
          <p className="text-[10px] text-slate-500">Detections are actual observations, not confirmed fires. Probability = chance of a detectable VIIRS hotspot, not of damage.</p>
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-200">Historical fire activity within the buffer</div>
          <Series data={hist} x="year" monthly={false} height={210} bars={[{ key: 'harmonized', name: 'Harmonized (VIIRS-eq.)', color: C.est }]} lines={[{ key: 'viirs', name: 'Actual VIIRS', color: C.viirs, dots: true }]} />
          <Prov kind="veq" />
        </div>
        <div className="overflow-hidden rounded-lg border border-[#26324a]">
          <BaseMap height={260} bbox={l.bbox} showStates={false}>
            <Circle center={[l.latitude, l.longitude]} radius={l.buffer_km * 1000} pathOptions={{ color: '#f97316', weight: 1.5, fillOpacity: 0.05, dashArray: '4 3' }} />
            <PointLayer points={l.nearby_7d?.points || []} colorOf={(p) => SAT_COLOR[p.satellite] || '#fff'} isSquare={(p) => p.satellite === 'Terra' || p.satellite === 'Aqua'}
              popup={(p) => `<b>${esc(SAT_LABEL[p.satellite])}</b> ${esc(p.acq_date)} ${esc(p.acq_time)}<br/>${num(p.distance_km, 1)} km away · FRP ${p.frp_mw == null ? 'n/a' : num(p.frp_mw, 1) + ' MW'} · conf ${esc(p.confidence_raw)}`} />
          </BaseMap>
        </div>
      </CardBody>
    </Card>
  )
}

