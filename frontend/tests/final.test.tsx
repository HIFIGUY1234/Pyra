import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ExposurePage, ForecastModelsPage, ReferencePage, SensorPage, SystemConfigPage, Viirs750Page } from '../src/final_ops'
import { mockFetch, withApp } from './helpers'

vi.mock('../src/completion_final', () => ({
  ExposurePanel: () => <div>exposure-panel</div>, ForecastComparisonPanel: () => <div>comparison-panel</div>, Noaa21Panel: () => <div>noaa21-panel</div>,
  OrbitPanel: () => <div>orbit-panel</div>, Viirs750Panel: () => <div>viirs750-panel</div>,
}))

const cand = (sensor: string, passes: boolean, role: string) => ({
  sensor, loaded: true, passes, platform: { status: 'operational', noaa_role: role },
  checks: { C1: true, C2: true, C3: true, C4: true, C5: true, C6: passes },
  coverage: { first: '2018-04-01', last: '2026-10-31', science_quality_last: '2026-07-31', nrt_days: 92, archive_months: 100, missing_days: 4, missing_share: 0.0013, days_behind_newest: 0, wall_clock_age_days: 14 },
  detections: { total: 5144008, presumed_vegetation: 5000000, science_quality: 5100000, per_year: { 2025: 600000 } },
  confidence: { low: 10, nominal: 20, high: 30, high_share: 0.5 }, day_night: { D: 70, N: 30 }, seasonal_share: { winter: 0.2 }, overlap: { 'Suomi NPP': { from: '2018-04-01', to: '2026-07-31', months: 99.9 } },
})
const SUMMARY = (sel: string | null, passing: boolean[]) => ({
  historical_reference: { platform: 'Suomi NPP', status: 'retired', science_data_end: '2026-11-02', loaded_first: '2012-01-20', loaded_last: '2026-10-31', science_quality_last: '2026-07-31', role: 'historical scale' },
  operational_reference: sel, selection_mode: sel ? 'evidence_default' : 'none', operational_status: sel ? 'APPROVED' : 'UNAVAILABLE',
  unavailable_reason: sel ? null : 'NOAA-21 fails C6', candidates: [cand('NOAA-21', passing[0], 'primary successor'), cand('NOAA-20', passing[1], 'secondary successor')],
  criteria: { C1: 'operational', C2: 'fresh', C3: 'archive', C4: 'gaps', C5: 'model', C6: 'skill' }, default_rule: 'NOAA order', forecast_served: sel || 'Suomi NPP',
  forecast_models: ['Suomi NPP', 'NOAA-20', 'NOAA-21'], bridges: [{ target: 'NOAA-21', reference: 'Suomi NPP', status: 'not_calibrated', selection_reason: 'coverage 41 % < 80 %', overlap: ['2024-01-17', '2026-07-31'], reference_per_target_ratio: { D: 1.05, N: 1.02 } }],
})
const TRANSITION = { historical_reference: 'Suomi NPP', science_data_end: '2026-11-02', last_science_quality_snpp: '2026-07-31', verdict: 'NOT_BRIDGED', interpretation: 'Genuine changes must appear in both.',
  successors: { 'NOAA-21': { coverage: { first: '2023-03-01', last: '2026-10-31' }, window: ['2025-08', '2026-07'], months_compared: 12, raw_discontinuity: { snpp_per_successor_ratio: 0.963, abs_log_step: 0.038, monthly_ratio_p05_p95: [0.74, 1.05] },
    bridge: { status: 'not_calibrated' }, calibrated_discontinuity: 'not computed: no bridge calibration passed' } } }

describe('operational reference selector', () => {
  it('keeps S-NPP historical, shows evidence and lets an admin choose only passing candidates', async () => {
    const calls = mockFetch((url, init) => {
      if (url === '/api/reference/operational' && init?.method === 'PUT') return { body: SUMMARY('NOAA-20', [true, true]) }
      if (url === '/api/reference/operational') return { body: SUMMARY('NOAA-21', [true, true]) }
      if (url.startsWith('/api/reference/transition')) return { body: TRANSITION }
      return undefined
    })
    const u = userEvent.setup()
    render(withApp(<ReferencePage />, { role: 'admin' }))
    expect(await screen.findByText('Historical reference')).toBeInTheDocument()
    expect(screen.getAllByText('Suomi NPP').length).toBeGreaterThan(0)
    expect(screen.getAllByText('2026-11-02', { exact: false }).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Not Calibrated/).length).toBeGreaterThan(0)
    expect(await screen.findByText(/not computed: no bridge calibration passed/)).toBeInTheDocument()
    const sel = screen.getByLabelText('Operational platform')
    expect(within(sel).getAllByRole('option').map((o) => o.textContent)).toEqual(['Evidence default', 'NOAA-21', 'NOAA-20'])
    await u.selectOptions(sel, 'NOAA-20')
    await u.type(screen.getByLabelText('Reason'), 'field team uses NOAA-20')
    await u.click(screen.getByRole('button', { name: 'Save selection' }))
    const put = calls.find((c) => c.method === 'PUT')
    expect(JSON.parse(put!.body!)).toEqual({ platform: 'NOAA-20', reason: 'field team uses NOAA-20' })
  })

  it('shows UNAVAILABLE with the reason when no candidate passes, and offers no selector', async () => {
    mockFetch((url) => (url === '/api/reference/operational' ? { body: SUMMARY(null, [false, false]) } : url.startsWith('/api/reference/transition') ? { body: TRANSITION } : undefined))
    render(withApp(<ReferencePage />, { role: 'admin' }))
    expect(await screen.findByText('No approved operational reference')).toBeInTheDocument()
    expect(screen.getByText('NOAA-21 fails C6')).toBeInTheDocument()
    expect(screen.queryByLabelText('Operational platform')).toBeNull()
  })
})

const MODELS = { served_by_default: 'NOAA-21', rule: 'independent', items: [
  { reference_sensor: 'Suomi NPP', legacy: true, model_version: 'suomi-npp-xgb-legacy', serving_status: { status: 'STALE_RETIRED_SENSOR', message: 'historical only' }, evaluation: { brier: 0.09 }, split: {}, rows: { test: 1 } },
  { reference_sensor: 'NOAA-21', model_version: 'noaa-21-xgb-abc', trained_at: '2026-11-14', serving_status: { status: 'CURRENT' }, target: 'At least one NOAA-21 VIIRS 375 m detection', evaluation: { brier: 0.12, roc_auc: 0.9, ece: 0.03 }, split: { train_until: '2025-03-31' }, rows: { test: 194661 }, breakdowns: { season: { winter: { n: 100, brier: 0.1, roc_auc: 0.8, ece: 0.02, reliable: true } } } },
] }

describe('forecast models and sensor selector', () => {
  it('requests the chosen sensor explicitly and labels the stale legacy model', async () => {
    const calls = mockFetch((url) => {
      if (url === '/api/forecast/models') return { body: MODELS }
      if (url.startsWith('/api/forecast/country?sensor=')) {
        const s = decodeURIComponent(url.split('sensor=')[1])
        return { body: { status: 'ok', headline_probability: 0.4, max_cell_probability: 0.8, risk_category: 'HIGH', issue_date: '2026-10-31', meaning: `prob of ${s} hotspot`,
          regional: { p_any_lower: 0.3, p_any_upper: 0.5 }, reference: { reference_sensor: s, model_version: 'v', serving_status: { status: s === 'Suomi NPP' ? 'STALE_RETIRED_SENSOR' : 'CURRENT', message: s === 'Suomi NPP' ? 'historical only' : null } } } }
      }
      return undefined
    })
    const u = userEvent.setup()
    render(withApp(<ForecastModelsPage />))
    expect(await screen.findByText('prob of NOAA-21 hotspot')).toBeInTheDocument()
    await u.selectOptions(screen.getByLabelText('Forecast target sensor'), 'Suomi NPP')
    expect(await screen.findByText('prob of Suomi NPP hotspot')).toBeInTheDocument()
    expect(calls.some((c) => c.url === '/api/forecast/country?sensor=Suomi%20NPP')).toBe(true)
    expect(screen.getAllByText('historical only').length).toBeGreaterThan(0)
  })
})

describe('sensor pages', () => {
  it('NOAA-20 page shows independent evaluation and its own model', async () => {
    mockFetch((url) => (url.startsWith('/api/reference/platform/NOAA-20') ? { body: cand('NOAA-20', true, 'secondary successor') }
      : url === '/api/forecast/models' ? { body: { ...MODELS, items: [{ ...MODELS.items[1], reference_sensor: 'NOAA-20', model_version: 'noaa-20-xgb-1' }] } } : undefined))
    render(withApp(<SensorPage sensor="NOAA-20" />))
    expect(await screen.findByText('noaa-20-xgb-1')).toBeInTheDocument()
    expect(screen.getByText(/2018-04-01 → 2026-10-31/)).toBeInTheDocument()
    expect(screen.queryByText('noaa21-panel')).toBeNull()
  })
})

describe('VIIRS 750 m', () => {
  it('shows NOT CONFIGURED and disables the download job without credentials', async () => {
    mockFetch((url) => (url === '/api/viirs750/credentials' ? { body: { configured: false, state: 'NOT_CONFIGURED', method: null, how: 'Set EARTHDATA_TOKEN' } }
      : url.startsWith('/api/viirs750/search') ? { body: { status: 'search_failed', error: 'ConnectionError: offline', granules: [] } } : undefined))
    const u = userEvent.setup()
    render(withApp(<Viirs750Page />, { role: 'admin' }))
    expect(await screen.findByText(/NOT CONFIGURED\. Authentic granule download/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Download & convert/ })).toBeDisabled()
    await u.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText(/Search failed: ConnectionError: offline/)).toBeInTheDocument()   // no invented granules
  })
})

describe('infrastructure exposure', () => {
  it('reports the linear layer as not built instead of zero', async () => {
    mockFetch((url) => (url === '/api/infrastructure/linear/status' ? { body: { status: 'not_built', national_coverage: 'INCOMPLETE: no extract processed', how: 'run linear_gis' } }
      : url.startsWith('/api/infrastructure/nearest') ? { body: { category: 'road_major', status: 'unavailable', reason: 'layer not built' } } : undefined))
    const u = userEvent.setup()
    render(withApp(<ExposurePage kind="infrastructure" />))
    expect(await screen.findByText(/INCOMPLETE: no extract processed/)).toBeInTheDocument()
    await u.click(screen.getByRole('button', { name: 'Nearest' }))
    expect(await screen.findByText(/Unavailable: layer not built/)).toBeInTheDocument()
  })
})

describe('system configuration', () => {
  it('admin sees validation, status-only credentials, checklist and jobs; secrets never rendered', async () => {
    mockFetch((url) => {
      if (url === '/api/system/config') return { body: { mode: 'dev', ok: true, errors: 0, warnings: 1, x_user_header_trusted: true, issues: [{ level: 'warning', key: 'PYROSCOPE_NOTIFY_PROVIDER', message: 'notifications are SIMULATED' }] } }
      if (url === '/api/system/credentials') return { body: { note: 'Status only.', items: [{ integration: 'SMTP e-mail', variables: ['SMTP_HOST', 'SMTP_PASSWORD'], status: 'NOT_CONFIGURED', needed_for: 'e-mail' }] } }
      if (url === '/api/notifications/checklist') return { body: { steps: [{ step: 'Choose a provider', done: false }], issues: [] } }
      if (url === '/api/jobs') return { body: { kinds: { tle_refresh: 'TLE' }, items: [{ id: 3, kind: 'viirs750_fetch', status: 'FAILED', error: 'BLOCKED_BY_CREDENTIALS: Earthdata Login not configured' }] } }
      if (url === '/api/notifications/log?limit=100') return { body: { items: [] } }
      if (url === '/api/notifications/status') return { body: { provider: 'simulated', external_delivery_enabled: false, rules: [] } }
      return undefined
    })
    render(withApp(<SystemConfigPage />, { role: 'admin' }))
    expect(await screen.findByText(/notifications are SIMULATED/)).toBeInTheDocument()
    expect(await screen.findByText('SMTP e-mail')).toBeInTheDocument()
    expect(screen.getByText(/BLOCKED_BY_CREDENTIALS/)).toBeInTheDocument()
    expect(screen.getByText('Choose a provider')).toBeInTheDocument()
  })

  it('non-admins do not request configuration endpoints', async () => {
    const calls = mockFetch((url) => (url === '/api/jobs' ? { body: { kinds: {}, items: [] } } : url.startsWith('/api/notifications') ? { body: { items: [], provider: 'simulated', rules: [] } } : undefined))
    render(withApp(<SystemConfigPage />, { role: 'org_user' }))
    expect(await screen.findByText(/visible to administrators only/)).toBeInTheDocument()
    expect(calls.some((c) => c.url.startsWith('/api/system'))).toBe(false)
  })
})
