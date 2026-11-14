import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ModelSelectionPanel, SeamVerdict, SeamRobustnessPanel, type ModelSelection } from '../src/validation_extra'
import { mockFetch, withApp } from './helpers'

const m = (w: number, b: number, r: number) => ({ national: { n: 10, wape_pct: w, bias_pct: b, r2: r }, state: { n: 100, wape_pct: w + 10, bias_pct: b, r2: r } })
const sel = (stage: string, reason: string, warning: string | null = null): ModelSelection => ({
  stage, pair: stage === 'mg' ? 'Terra MODIS -> Aqua MODIS' : 'Aqua MODIS -> Suomi NPP VIIRS 375 m', train_years: [2002, 2022],
  candidates: { cell_silent: 'default', constant: 'one ratio' }, selected: 'cell_silent', reason, backward_extrapolation_warning: warning,
  designs: { leave_one_year_out: { n_folds: 21, scores: { cell_silent: m(19.3, 0.0, 0.91), constant: m(48.3, 0.1, 0.59) } },
    block_20_month: { n_folds: 7, scores: { cell_silent: m(18.4, 3.7, 0.92), constant: m(45.3, 5.0, 0.64) } } },
  band: { empirical_coverage_pct: 91.4, nominal_pct: 90 }, band_backward: { empirical_coverage_pct: 84.5, nominal_pct: 90 },
})

describe('calibration model selection panel', () => {
  it('shows the held-out decision and refetches when the calibration step changes', async () => {
    const calls = mockFetch((url) => (url.includes('stage=mg') ? { body: sel('mg', 'MG REASON', '+12.2% backward bias') }
      : url.includes('stage=sh') ? { body: sel('sh', 'SH REASON') } : undefined))
    const u = userEvent.setup()
    render(withApp(<ModelSelectionPanel />))
    expect(await screen.findByText('MG REASON')).toBeInTheDocument()
    expect(screen.getByText('+12.2% backward bias')).toBeInTheDocument()
    const row = screen.getByText('Leave one year out').closest('tr')!
    expect(within(row).getByText('29.3% · 0.0% · 0.91').tagName).toBe('STRONG')     // selected model highlighted (state-month score)
    expect(within(row).getByText('58.3% · 0.1% · 0.59').tagName).not.toBe('STRONG')
    expect(screen.getByText(/91.4% on 20-month blocks/)).toBeInTheDocument()

    await u.click(screen.getByRole('button', { name: 'Aqua → VIIRS' }))
    expect(await screen.findByText('SH REASON')).toBeInTheDocument()
    expect(screen.queryByText('+12.2% backward bias')).toBeNull()
    expect(calls.map((c) => c.url)).toEqual(['/api/validation/model-selection?stage=mg', '/api/validation/model-selection?stage=sh'])
  })

  it('shows an error card rather than empty numbers when the API fails', async () => {
    mockFetch(() => ({ status: 500, body: { detail: 'calibration failed' } }))
    render(withApp(<ModelSelectionPanel />))
    expect(await screen.findByText(/Could not load model selection/)).toBeInTheDocument()
    expect(screen.getByText('calibration failed')).toBeInTheDocument()
  })
})

describe('seam verdict', () => {
  it('reports a partial pass and explains a damped genuine change', () => {
    render(<SeamVerdict seam={{ verdict: 'partial', verdict_rule: 'RULE', reference_in_band: false,
      genuine_change: { detectable: false, direction: 'no clear change', why: 'harmonization damps part of this genuine change' } }} />)
    expect(screen.getByText('Seam verdict: PARTIAL')).toBeInTheDocument()
    expect(screen.getByText(/lies outside the harmonized step band/)).toBeInTheDocument()
    expect(screen.getByText(/damps part of this genuine change/)).toBeInTheDocument()
  })

  it('lists robustness by window and state with verdict counts', async () => {
    mockFetch(() => ({ body: { windows: [{ window_months: 36, step_raw: 6.47, step_harmonized: 0.971, step_harmonized_band: [0.89, 1.02], step_reference_sensor: 1.0, artificial_jump_before: 1.87, artificial_jump_after: 0.029, verdict: 'pass' }],
      states: [{ state: 'Punjab', step_raw: 5.0, step_harmonized: 1.11, step_harmonized_band: [0.94, 1.22], step_reference_sensor: 1.1, artificial_jump_before: 1.5, artificial_jump_after: 0.013, verdict: 'pass' }],
      state_summary: { pass: 1 } } }))
    render(withApp(<SeamRobustnessPanel />))
    await waitFor(() => expect(screen.getByText('Punjab')).toBeInTheDocument())
    expect(screen.getByText('±36')).toBeInTheDocument()
    expect(screen.getByText(/State verdicts: Pass 1/)).toBeInTheDocument()
  })
})
