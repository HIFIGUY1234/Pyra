import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { EmissionsPage, ExternalValidationPage, FireEventsPage, JobsPage, SmokePage } from '../src/intel'
import { apiUrl } from '../src/lib'
import { mockFetch, withApp } from './helpers'

vi.mock('../src/map', () => ({ BaseMap: ({ children }: { children?: unknown }) => <div data-testid="map">{children as never}</div>, PointLayer: () => null, Swatch: () => null }))
vi.mock('react-leaflet', () => ({ Polygon: () => null, Polyline: () => null }))

const inRouter = (el: JSX.Element, role = 'analyst') => render(<MemoryRouter>{withApp(el, { role })}</MemoryRouter>)

describe('API base URL', () => {
  it('keeps same-origin paths when VITE_API_BASE_URL is unset and never rewrites absolute URLs', () => {
    expect(apiUrl('/api/events')).toBe('/api/events')
    expect(apiUrl('https://api.example.org/api/x')).toBe('https://api.example.org/api/x')
  })
})

describe('fire events', () => {
  it('shows an explicit empty state (no fabricated events) and the no-CONTAINED rule', async () => {
    mockFetch((url) => {
      if (url === '/api/events/summary') return { body: { events: 0, status_counts: {}, method: 'pyroscope-events-1.0', validation: 'NOT INDEPENDENTLY VALIDATED', last_run: null } }
      if (url.startsWith('/api/events?')) return { body: { total: 0, limit: 100, offset: 0, items: [] } }
      return undefined
    })
    inRouter(<FireEventsPage />)
    expect(await screen.findByText(/No event delineation has run yet/)).toBeInTheDocument()
    expect(screen.getByText(/No CONTAINED status exists/)).toBeInTheDocument()
    expect(await screen.findByText('No data.')).toBeInTheDocument()
  })
  it('lists events with status and links', async () => {
    const ev = { event_id: 'FE-20261030-abcdef12', status: 'ACTIVE', first_detection: '2026-10-30T05:00:00Z', last_detection: '2026-10-31T08:00:00Z', n_obs: 12, n_days: 2,
      platforms: { 'NOAA-20': 6, Aqua: 6 }, lat: 30, lon: 75, footprint_km2: 2.5, peak_frp_mw: 40, sum_frp_mw: 200, confidence_mean: 0.6, evidence: 'multi-sensor, multi-day',
      land_use: 'Agricultural', state: 'Punjab', district_id: null, merged_into: null, split_from: null, truncated_start: false }
    mockFetch((url) => {
      if (url === '/api/events/summary') return { body: { events: 1, status_counts: { ACTIVE: 1 }, method: 'm', validation: 'v', last_run: { start: '2026-10-25', end: '2026-10-31', detections: 30, events: 1, data_through: '2026-10-31T22:00:00', multi_sensor_events: 1, single_detection_events: 0, seconds: 1, parameters: {} } } }
      if (url.startsWith('/api/events?')) return { body: { total: 1, limit: 100, offset: 0, items: [ev] } }
      return undefined
    })
    inRouter(<FireEventsPage />)
    expect(await screen.findByText('FE-20261030-abcdef12')).toBeInTheDocument()
    expect(screen.getByText(/1 matching/)).toBeInTheDocument()
  })
})

describe('estimates are labelled', () => {
  it('emissions show ESTIMATED with uncertainty bounds and the blocked burned-area method', async () => {
    mockFetch((url) => {
      if (url === '/api/emissions/summary') return { body: { status: 'ESTIMATED', label: 'ESTIMATED', method: 'FRP/FRE', events: 2, n_draws: 1000,
        totals_tonnes: { 'PM2.5': { median: 3485, p05: 2062, p95: 7489 } }, burned_area_method: { status: 'BLOCKED_BY_EXTERNAL_DATA', missing: 'fuel_consumption.csv' } } }
      if (url.startsWith('/api/emissions/regions')) return { body: { items: [], note: 'envelope' } }
      if (url.startsWith('/api/emissions/events')) return { body: { total: 0, items: [] } }
      return undefined
    })
    inRouter(<EmissionsPage />)
    expect(await screen.findByText(/ESTIMATED · EXPERIMENTAL · NOT INDEPENDENTLY VALIDATED/)).toBeInTheDocument()
    expect(screen.getByText(/90%: 2.1k – 7.5k/)).toBeInTheDocument()
    expect(screen.getByText(/fuel_consumption.csv/)).toBeInTheDocument()
  })
  it('smoke page states that trajectories are not PM2.5 forecasts', async () => {
    mockFetch((url) => (url === '/api/smoke/forecasts' ? { body: { items: [], label: 'EXPERIMENTAL TRAJECTORY (kinematic fallback, not HYSPLIT) - no concentrations' } } : undefined))
    inRouter(<SmokePage />)
    expect(await screen.findByText(/not HYSPLIT/)).toBeInTheDocument()
    expect(screen.getByText(/PyroScope does not forecast PM2.5/)).toBeInTheDocument()
  })
  it('external validation separates software tests from science and shows independence', async () => {
    mockFetch((url) => (url === '/api/external-validation/summary' ? { body: {
      sources: [{ id: 'mcd64a1', name: 'MCD64A1', kind: 'events', independence: 'NOT INDEPENDENT of MODIS active fires', status: 'BLOCKED_BY_CREDENTIALS' }],
      harmonization: { test_months: 40, target: 'withheld VIIRS', band_coverage_pct: 88, models: { pyroscope: { wape_pct: 12.1, bias_pct: 1 }, naive_modis_plus_viirs: { wape_pct: 9, bias_pct: 9 } } },
      events_vs_incidents: { datasets: [], status: 'BLOCKED_BY_EXTERNAL_DATA', csv_format: { required: ['incident_id'], optional: [] }, note: 'never created' },
      smoke: { status: 'BLOCKED_BY_CREDENTIALS', reason: 'no ground PM2.5' } } } : undefined))
    inRouter(<ExternalValidationPage />)
    expect(await screen.findByText(/NOT INDEPENDENT of MODIS active fires/)).toBeInTheDocument()
    expect(screen.getByText('Naive MODIS + VIIRS sum')).toBeInTheDocument()
    expect(screen.getByText(/passing tests prove code behaviour, not accuracy/)).toBeInTheDocument()
  })
})

describe('jobs', () => {
  it('shows attempts, error codes and lets an admin cancel', async () => {
    mockFetch((url) => (url.startsWith('/api/jobs') ? { body: { kinds: {}, items: [
      { id: 7, kind: 'burned_area', status: 'FAILED', attempts: 1, max_attempts: 3, error_code: 'BLOCKED_BY_CREDENTIALS', error: 'accept the LAADS licence', requested_by: 'admin' },
      { id: 8, kind: 'fire_events', status: 'RUNNING', attempts: 1, max_attempts: 3, stage: 'linking detections', requested_by: 'admin' }] } } : undefined))
    inRouter(<JobsPage />, 'admin')
    expect(await screen.findByText(/BLOCKED_BY_CREDENTIALS:/)).toBeInTheDocument()
    expect(screen.getByText('linking detections')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Cancel' })).toHaveLength(1)
  })
})
