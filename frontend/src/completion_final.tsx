/* Orbit observation opportunities, population / infrastructure exposure, forecast model comparison,
   NOAA-21 cross-calibration study and VIIRS 750 m product status. All values come from the API; missing layers
   are shown as unavailable, never as zero. */
import { useState } from 'react'
import { useApi, useApp, num, compact, titleCase, Prov, Tabs } from './lib'
import { Banner, Table } from './ui'
import { Panel, Load, Td } from './science'

/* ------------------------------------------------------------------ types */
type Freshness = { tle_age_days: number; stale: boolean; warning: string | null }
type TleInfo = { catnr: number; name: string; epoch: string; source: string; acquired: string } & Freshness
type OrbitValidation = { validated: boolean; n: number; mean_abs_residual_min?: number; p95_abs_residual_min?: number; median_residual_min?: number; reason?: string; tle_epoch?: string }
type OrbitStatus = { tles: Record<string, TleInfo | null>; validation: Record<string, OrbitValidation | string>; stale_after_days: number; meaning: string }
type Pass = { rise_utc: string; max_utc: string; set_utc: string; max_local: string; local_solar_time_h: number; daynight: string; duration_min: number; max_elevation_deg: number; min_range_km: number }
type Passes = { satellite: string; available: boolean; reason?: string; observer?: [number, number]; tle?: TleInfo; freshness?: Freshness; swath_edge_elevation_deg?: number; passes: Pass[]; meaning?: string; validation?: OrbitValidation | null; local_time_zone?: string }

type Layers = {
  population: { status: string; name?: string; reference_year?: number; licence?: string; total_population_in_aoi?: number; cells_partial_coverage?: number; how?: string }
  infrastructure: { status: string; source?: string; licence?: string; updated?: string; categories?: Record<string, { status?: string; features?: number | null; last_error?: string }>; not_loaded?: Record<string, string>; completeness_note?: string; how?: string }
  meaning: string
}
type HotspotItem = { lat: number; lon: number; n: number; frp_max: number | null; sats: string; last: string; population?: number | null; facilities?: number; hospital?: number; school?: number; state?: string; district?: string | null }
type HotspotExposure = { window: [string, string]; radius_km: number; detections: number; locations?: number; high_frp_locations?: number; high_frp_threshold_mw: number; population: { locations_with_people_within_radius: number; median_people_within_radius: number; high_frp_locations_over_10k_people: number; note: string } | null; items: HotspotItem[]; meaning: string }
type RegionRow = { state: string; population: number | null; detections_30d: number; forecast_max_cell_p?: number | null; population_in_high_prob_cells?: number; facilities_total?: number; hospital?: number; school?: number; power_substation?: number }
type Regions = { items: RegionRow[]; window_30d_end: string; layers: Layers }

type FMetrics = { n: number; positives: number; brier?: number; brier_skill?: number | null; roc_auc?: number | null; pr_auc?: number | null; ece?: number; precision?: number | null; recall?: number | null; specificity?: number | null; false_positive_rate?: number | null; missed_event_rate?: number | null; reliable: boolean }
type Card = { algorithm: string; training_period: string; calibration: string; test_period: string; training_rows: number; trained_at: string; limitations: string[]; features: string | string[] }
type Comparison = { status?: string; how?: string; generated: string; target: string; rows: Record<string, number>; equal_footing: string; selection_rule: string; decision: string; main: Record<string, FMetrics>
  rolling_origin: { train_until: string; calibrate_until: string; test_until: string; scores: Record<string, FMetrics> }[]
  breakdown: Record<string, Record<string, { xgboost: FMetrics; climatology: FMetrics }>>; model_cards: Record<string, Card>; not_included: Record<string, string>; day_night: string }

type N21Score = { wape_pct: number | null; bias_pct: number | null; r2: number | null }
type N21Exp = { design: string; train: [string, string]; test: [string, string]; test_months: number; test_reference_detections: number; state_month: Record<string, N21Score>; national_month: Record<string, N21Score>; band_coverage_pct: Record<string, number> }
type Noaa21 = { status: string; reason?: string; selected: string | null; selection_reason: string; matched_days: number; operational_start: string; overall_ratio_operational: Record<string, number>; experiments: N21Exp[]; pre_operational_check: { months: [string, string]; national_month: Record<string, N21Score> } | null; why_not_aqua: string; scope: string; criteria: string }

type V750 = { credentials: { configured: boolean; method: string | null; how: string }; granules_downloaded: number; granules_failed: number; by_product: Record<string, number>; products: { viirs_750m: string; viirs_750m_message: string | null; streams: { stream: string; label: string; product_type: string }[] }; coverage_note: string }

const SATS = ['Terra', 'Aqua', 'Suomi NPP', 'NOAA-20', 'NOAA-21'] as const
const short = (s: string) => s.replace('T', ' ').replace(/:\d\dZ$/, 'Z')

/* ------------------------------------------------------------------ orbit */
export function OrbitPanel() {
  const { region } = useApp()
  const [sat, setSat] = useState<string>('NOAA-20')
  const [mode, setMode] = useState<'region' | 'point'>('region')
  const [lat, setLat] = useState('30.90')
  const [lon, setLon] = useState('75.85')
  const [hours, setHours] = useState('48')
  const where = mode === 'region' ? `region=${encodeURIComponent(region || 'country')}` : `lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`
  const { data, loading, error } = useApi<Passes>(`/api/orbits/passes?satellite=${encodeURIComponent(sat)}&${where}&hours=${encodeURIComponent(hours)}`)
  const st = useApi<OrbitStatus>('/api/orbits/status')
  const v = data?.validation
  return (
    <Panel title="Predicted satellite overpasses (SGP4)" badge={<Prov kind="experiment" text="Prediction - not a hotspot" />}
      sub="When the selected location will be inside the instrument swath. This is an observation opportunity, not a fire prediction: cloud, sun glint and the absence of fire all mean no detection."
      actions={<Tabs value={mode} onChange={setMode} options={[{ value: 'region', label: 'Selected area' }, { value: 'point', label: 'Coordinates' }]} />}>
      <div className="mb-3 flex flex-wrap items-end gap-3 text-xs">
        <label className="flex flex-col gap-1">Satellite
          <select aria-label="Satellite" className="rounded border border-line bg-ink-800 px-2 py-1" value={sat} onChange={(e) => setSat(e.target.value)}>
            {SATS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        {mode === 'point' && <>
          <label className="flex flex-col gap-1">Latitude<input aria-label="Latitude" className="w-24 rounded border border-line bg-ink-800 px-2 py-1" value={lat} onChange={(e) => setLat(e.target.value)} /></label>
          <label className="flex flex-col gap-1">Longitude<input aria-label="Longitude" className="w-24 rounded border border-line bg-ink-800 px-2 py-1" value={lon} onChange={(e) => setLon(e.target.value)} /></label>
        </>}
        <label className="flex flex-col gap-1">Hours ahead
          <select aria-label="Hours ahead" className="rounded border border-line bg-ink-800 px-2 py-1" value={hours} onChange={(e) => setHours(e.target.value)}>
            {['24', '48', '72', '168'].map((h) => <option key={h} value={h}>{h}</option>)}
          </select>
        </label>
      </div>
      <Load loading={loading} error={error} data={data} what="overpass prediction">
        {data && !data.available && <Banner tone="warning" title="No orbital elements">{data.reason}</Banner>}
        {data && data.available && <div className="space-y-3">
          {data.freshness?.stale && <Banner tone="warning" title="Stale orbital elements">{data.freshness.warning}</Banner>}
          <p className="text-xs text-slate-400">
            {data.tle?.name} (NORAD {data.tle?.catnr}) · TLE epoch {data.tle?.epoch.slice(0, 16)}Z · age {num(data.freshness?.tle_age_days, 1)} d · source CelesTrak ·
            swath edge at {num(data.swath_edge_elevation_deg, 1)}° elevation · location {num(data.observer?.[0], 2)}°N {num(data.observer?.[1], 2)}°E
          </p>
          {data.passes.length === 0 ? <Banner tone="info" title="No pass in this window">The location is not inside the swath during the selected period.</Banner> :
            <div className="overflow-x-auto"><Table headers={['Closest approach (UTC)', `Local (${data.local_time_zone || 'IST'})`, 'Solar time', 'Day/night', 'Max elevation', 'Duration', 'Range']}>
              {data.passes.map((p) => <tr key={p.max_utc}><Td mono>{short(p.max_utc)}</Td><Td mono>{p.max_local}</Td><Td right>{num(p.local_solar_time_h, 2)} h</Td><Td>{p.daynight === 'D' ? 'Day' : 'Night'}</Td><Td right>{num(p.max_elevation_deg, 1)}°</Td><Td right>{num(p.duration_min, 1)} min</Td><Td right>{num(p.min_range_km)} km</Td></tr>)}
            </Table></div>}
          <p className="text-xs text-slate-400">
            Validation against actual {data.satellite} detections: {v && v.validated ? `${v.n} detections, mean |recorded − predicted| ${num(v.mean_abs_residual_min, 2)} min (95th pct ${num(v.p95_abs_residual_min, 2)} min). Recorded FIRMS times are minute/granule resolution.` : (v?.reason || 'not yet validated (python -m app.orbits validate)')}
          </p>
        </div>}
      </Load>
      {st.data && <p className="mt-2 text-[11px] text-slate-500">TLEs cached for {Object.values(st.data.tles).filter(Boolean).length} of {SATS.length} satellites; flagged stale after {st.data.stale_after_days} days.</p>}
    </Panel>
  )
}

/* ------------------------------------------------------------------ exposure */
export function ExposureLayersBanner({ layers }: { layers: Layers }) {
  const p = layers.population, i = layers.infrastructure
  return (
    <div className="grid gap-2 md:grid-cols-2">
      <Banner tone={p.status === 'loaded' ? 'success' : 'warning'} title={`Population: ${p.status}`}>
        {p.status === 'loaded' ? <>{p.name} · {p.licence} · total in area {compact(p.total_population_in_aoi)} · {num(p.cells_partial_coverage)} edge cells with partial raster coverage</> : <>Not loaded ({p.how}). Population exposure is not scored and is not treated as zero.</>}
      </Banner>
      <Banner tone={i.status === 'loaded' ? 'success' : 'warning'} title={`Infrastructure: ${i.status}`}>
        {i.status === 'loaded' ? <>{i.source} · {i.licence} · {Object.entries(i.categories || {}).map(([k, v]) => `${titleCase(k)} ${v.status === 'loaded' ? num(v.features) : 'unavailable'}`).join(' · ')}<div className="mt-1 text-slate-400">{i.completeness_note}</div></> : <>Not loaded ({i.how}). Missing facilities are never counted as zero.</>}
      </Banner>
    </div>
  )
}

export function ExposurePanel({ compactView = false }: { compactView?: boolean }) {
  const { region } = useApp()
  const [days, setDays] = useState('7')
  const hs = useApi<HotspotExposure>(`/api/exposure/hotspots?days=${days}&radius_km=5&region=${encodeURIComponent(region || 'country')}&top=${compactView ? 10 : 25}`)
  const rg = useApi<Regions>(compactView ? null : '/api/exposure/regions')
  const lay = useApi<Layers>('/api/exposure/layers')
  return (
    <div className="space-y-4">
      {lay.data && <ExposureLayersBanner layers={lay.data} />}
      <Panel title="People and facilities near recent actual hotspots" badge={<Prov kind="actual" text="Actual detections" />}
        sub="Within 5 km of each de-duplicated detection location (all satellites). Describes who is nearby; it is not a prediction that anything will burn."
        actions={<Tabs value={days} onChange={setDays} options={[{ value: '1', label: '1 day' }, { value: '7', label: '7 days' }, { value: '30', label: '30 days' }]} />}>
        <Load loading={hs.loading} error={hs.error} data={hs.data} what="hotspot exposure">
          {hs.data && <div className="space-y-2">
            <p className="text-xs text-slate-400">{hs.data.window[0]} → {hs.data.window[1]} · {num(hs.data.detections)} detections at {num(hs.data.locations)} locations · {num(hs.data.high_frp_locations)} with FRP ≥ {hs.data.high_frp_threshold_mw} MW
              {hs.data.population && <> · {num(hs.data.population.locations_with_people_within_radius)} locations have people within {hs.data.radius_km} km (median {num(hs.data.population.median_people_within_radius)}) · {num(hs.data.population.high_frp_locations_over_10k_people)} high-FRP locations near ≥ 10,000 people</>}</p>
            {hs.data.items.length === 0 ? <Banner tone="info" title="No detections">No actual detections in this window and area.</Banner> :
              <div className="overflow-x-auto"><Table headers={['Location', 'District, state', 'Detections', 'Max FRP (MW)', 'Satellites', 'People ≤ 5 km', 'Facilities ≤ 5 km', 'Last seen']}>
                {hs.data.items.map((r) => <tr key={`${r.lat},${r.lon}`}><Td mono>{num(r.lat, 3)}, {num(r.lon, 3)}</Td><Td>{[r.district, r.state].filter(Boolean).join(', ')}</Td><Td right>{r.n}</Td><Td right>{num(r.frp_max, 1)}</Td><Td>{r.sats}</Td><Td right>{r.population === undefined || r.population === null ? 'unavailable' : num(r.population)}</Td><Td right>{r.facilities === undefined ? 'unavailable' : num(r.facilities)}</Td><Td>{r.last}</Td></tr>)}
              </Table></div>}
            {hs.data.population && <p className="text-[11px] text-slate-500">{hs.data.population.note}</p>}
          </div>}
        </Load>
      </Panel>
      {!compactView && <Panel title="State comparison - exposure, activity and forecast" badge={<Prov kind="aux" text="WorldPop 2020 · OSM" />} pad={false}
        sub="Population from WorldPop 2020 (one reference year), facilities as mapped in OpenStreetMap, detections from the last 30 days, forecast = highest calibrated 7-day hotspot probability of any cell.">
        <Load loading={rg.loading} error={rg.error} data={rg.data} what="regional comparison">
          {rg.data && <div className="overflow-x-auto"><Table headers={['State', 'Population', 'Detections (30 d)', 'Max cell p (7 d)', 'People in cells ≥ 60 %', 'Facilities', 'Hospitals', 'Schools', 'Substations']}>
            {rg.data.items.slice(0, 40).map((r) => <tr key={r.state}><Td>{r.state}</Td><Td right>{r.population === null ? 'unavailable' : compact(r.population)}</Td><Td right>{num(r.detections_30d)}</Td><Td right>{num(r.forecast_max_cell_p, 2)}</Td><Td right>{r.population_in_high_prob_cells === undefined ? '–' : compact(r.population_in_high_prob_cells)}</Td><Td right>{r.facilities_total === undefined ? 'unavailable' : num(r.facilities_total)}</Td><Td right>{num(r.hospital)}</Td><Td right>{num(r.school)}</Td><Td right>{num(r.power_substation)}</Td></tr>)}
          </Table></div>}
        </Load>
      </Panel>}
    </div>
  )
}

/* ------------------------------------------------------------------ forecast comparison */
const MODEL_LABEL: Record<string, string> = { climatology: 'Seasonal climatology', logistic: 'Logistic regression', random_forest: 'Random forest', hist_gradient_boosting: 'Hist. gradient boosting', xgboost: 'XGBoost (production)' }

export function ForecastComparisonPanel() {
  const { data, loading, error } = useApi<Comparison>('/api/forecast/comparison')
  const [group, setGroup] = useState<string>('season')
  return (
    <Panel title="Forecast model comparison (same rows, same split, same calibration)" badge={<Prov kind="experiment" text="Held-out test 2024+" />}
      sub="Target: at least one S-NPP VIIRS hotspot in the 0.25° cell within 7 days. A detectable satellite hotspot, not a verified ignition.">
      <Load loading={loading} error={error} data={data} what="model comparison">
        {data && data.status === 'unavailable' && <Banner tone="warning" title="Not computed">{data.how}</Banner>}
        {data && data.main && <div className="space-y-3">
          <Banner tone="info" title={data.decision}>{data.selection_rule}<div className="mt-1 text-slate-400">{data.equal_footing}</div></Banner>
          <div className="overflow-x-auto"><Table headers={['Model', 'Brier', 'Skill vs clim.', 'ROC-AUC', 'PR-AUC', 'Calib. error', 'Precision @0.6', 'Recall', 'Specificity', 'Missed events']}>
            {Object.entries(data.main).map(([k, m]) => <tr key={k}><Td>{MODEL_LABEL[k] || k}</Td><Td mono>{num(m.brier, 4)}</Td><Td right>{num(m.brier_skill, 3)}</Td><Td right>{num(m.roc_auc, 3)}</Td><Td right>{num(m.pr_auc, 3)}</Td><Td right>{num(m.ece, 4)}</Td><Td right>{num(m.precision, 3)}</Td><Td right>{num(m.recall, 3)}</Td><Td right>{num(m.specificity, 3)}</Td><Td right>{num(m.missed_event_rate, 3)}</Td></tr>)}
          </Table></div>
          <div className="overflow-x-auto"><Table headers={['Rolling origin (train ≤ / test ≤)', ...Object.keys(data.main).map((k) => MODEL_LABEL[k] || k)]}>
            {data.rolling_origin.map((o) => <tr key={o.test_until}><Td mono>{o.train_until.slice(0, 4)} / {o.test_until.slice(0, 4)}</Td>{Object.keys(data.main).map((k) => <Td key={k} mono>{num(o.scores[k]?.brier, 4)} · {num(o.scores[k]?.roc_auc, 3)}</Td>)}</tr>)}
          </Table></div>
          <div className="flex items-center gap-2 text-xs"><span className="text-slate-400">XGBoost vs climatology by</span>
            <Tabs value={group} onChange={setGroup} options={['season', 'month', 'state', 'land_use', 'activity_last_30d', 'observation_coverage'].map((g) => ({ value: g, label: titleCase(g) }))} /></div>
          <div className="max-h-80 overflow-auto"><Table headers={[titleCase(group), 'Cell-weeks', 'Events', 'Brier (XGB)', 'Brier (clim.)', 'Skill', 'ROC-AUC', 'Reliable?']}>
            {Object.entries(data.breakdown[group] || {}).sort((a, b) => b[1].xgboost.n - a[1].xgboost.n).map(([k, v]) => <tr key={k} className={v.xgboost.reliable ? '' : 'opacity-60'}><Td>{k}</Td><Td right>{num(v.xgboost.n)}</Td><Td right>{num(v.xgboost.positives)}</Td><Td mono>{num(v.xgboost.brier, 4)}</Td><Td mono>{num(v.climatology.brier, 4)}</Td><Td right>{num(v.xgboost.brier_skill, 3)}</Td><Td right>{num(v.xgboost.roc_auc, 3)}</Td><Td>{v.xgboost.reliable ? 'yes' : 'small sample'}</Td></tr>)}
          </Table></div>
          <p className="text-[11px] text-slate-500">{data.day_night} Rows: train {num(data.rows.train_used)} of {num(data.rows.train_available)}, calibration {num(data.rows.calibration)}, test {num(data.rows.test)}. {Object.entries(data.not_included).map(([k, v]) => `${k}: ${v}`).join(' ')}</p>
          <details className="text-xs"><summary className="cursor-pointer text-slate-300">Model cards</summary>
            <div className="mt-2 grid gap-2 md:grid-cols-2">{Object.entries(data.model_cards).map(([k, cd]) => <div key={k} className="rounded border border-line p-2"><div className="font-semibold">{MODEL_LABEL[k] || k}</div><div>{cd.algorithm}</div><div className="text-slate-400">Train: {cd.training_period} ({num(cd.training_rows)} rows) · {cd.calibration} · Test: {cd.test_period} · trained {cd.trained_at.slice(0, 16)}</div><ul className="list-disc pl-4 text-slate-400">{cd.limitations.map((l) => <li key={l}>{l}</li>)}</ul></div>)}</div>
          </details>
        </div>}
      </Load>
    </Panel>
  )
}

/* ------------------------------------------------------------------ NOAA-21 */
export function Noaa21Panel() {
  const { data, loading, error } = useApi<Noaa21>('/api/validation/noaa21')
  const cands = ['identity', 'national_ratio', 'state_ratio', 'state_season_ratio']
  return (
    <Panel title="NOAA-21 cross-calibration study (VIIRS → S-NPP equivalent)" badge={<Prov kind="experiment" />}
      sub="Same instrument and product, same orbit plane. Operational records only (from the official FIRMS start); pre-operational 2023 records are scored separately.">
      <Load loading={loading} error={error} data={data} what="NOAA-21 study">
        {data && data.status === 'unavailable' && <Banner tone="warning" title="Unavailable">{data.reason}</Banner>}
        {data && data.experiments && <div className="space-y-3">
          <Banner tone={data.selected ? 'success' : 'info'} title={data.selected ? `Calibrated: ${titleCase(data.selected)}` : 'Not calibrated - NOAA-21 stays a separate actual stream'}>
            {data.selection_reason}. {data.scope}<div className="mt-1 text-slate-400">Rule: {data.criteria}. {data.why_not_aqua}</div>
          </Banner>
          <div className="overflow-x-auto"><Table headers={['Design', 'Train', 'Test', ...cands.map(titleCase), 'Band coverage (state-season)']}>
            {data.experiments.map((e) => <tr key={e.design}><Td>{e.design}</Td><Td mono>{e.train.join('–')}</Td><Td mono>{e.test.join('–')} ({e.test_months} mo)</Td>
              {cands.map((k) => <Td key={k} mono>{num(e.state_month[k]?.wape_pct, 1)}% · {num(e.state_month[k]?.bias_pct, 1)}%</Td>)}<Td right>{num(e.band_coverage_pct.state_season_ratio, 0)}%</Td></tr>)}
          </Table></div>
          <p className="text-xs text-slate-400">Cells: state-month WAPE · bias of NOAA-21-based estimates against actual S-NPP on {num(data.matched_days)} days when both observed. Overall operational S-NPP/NOAA-21 ratio: day {num(data.overall_ratio_operational.D, 3)}, night {num(data.overall_ratio_operational.N, 3)}.
            {data.pre_operational_check && <> Pre-operational {data.pre_operational_check.months.join('–')}: national monthly WAPE without correction {num(data.pre_operational_check.national_month.identity?.wape_pct, 1)}%.</>}</p>
        </div>}
      </Load>
    </Panel>
  )
}

/* ------------------------------------------------------------------ VIIRS 750 m */
export function Viirs750Panel() {
  const { data, loading, error } = useApi<V750>('/api/viirs750/status')
  return (
    <Panel title="VIIRS product streams - 375 m and 750 m" badge={<Prov kind="aux" text="Never pooled" />}
      sub="375 m (VNP14IMG/VJ114IMG/VJ214IMG via FIRMS) and 750 m (VNP14/VJ114/VJ214 Level-2 swath via LP DAAC) are separate products with separate calibrations.">
      <Load loading={loading} error={error} data={data} what="VIIRS product status">
        {data && <div className="space-y-2 text-xs">
          <div className="flex flex-wrap gap-2">{data.products.streams.map((s) => <span key={s.stream} className="rounded border border-line px-2 py-1">{s.label} <span className="text-slate-400">({s.product_type})</span></span>)}</div>
          <Banner tone={data.products.viirs_750m === 'loaded' ? 'success' : 'warning'} title={`VIIRS 750 m: ${data.products.viirs_750m === 'loaded' ? 'loaded' : 'unavailable'}`}>
            {data.products.viirs_750m_message || '750 m records are ingested and calibrated separately.'}
            <div className="mt-1">Earthdata Login: {data.credentials.configured ? `configured (${data.credentials.method})` : 'not configured'} · granules downloaded {num(data.granules_downloaded)}{data.granules_failed ? ` · ${data.granules_failed} failed` : ''}</div>
            {!data.credentials.configured && <div className="mt-1 text-slate-400">{data.credentials.how}</div>}
          </Banner>
          <p className="text-slate-500">{data.coverage_note}</p>
        </div>}
      </Load>
    </Panel>
  )
}
