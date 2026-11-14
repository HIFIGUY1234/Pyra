/* Held-out calibration model selection, seam verdict and seam robustness (typed API shapes). */
import { useState } from 'react'
import { useApi, num, titleCase, Prov, Tabs } from './lib'
import { Banner, Table } from './argon'
import { Panel, Load, Td } from './science'

export type Metrics = { n: number; mae?: number; rmse?: number; wape_pct?: number | null; bias_pct?: number | null; r2?: number | null; mean_actual?: number }
type Score = { national: Metrics; state: Metrics }
type Design = { n_folds: number; scores: Record<string, Score>; blocks?: [number, number][] }
type Band = { empirical_coverage_pct: number | null; nominal_pct: number; median_relative_width_pct?: number | null }
export type ModelSelection = {
  stage: string; pair: string; train_years: number[]; candidates: Record<string, string>; designs: Record<string, Design>
  selected: string; reason: string; selection_rule?: string; band?: Band; band_backward?: Band; backward_extrapolation_warning?: string | null
}
export type SeamRow = {
  window_months?: number; state?: string; mode?: string; step_raw?: number | null; step_harmonized?: number | null
  step_harmonized_band?: [number, number] | null; step_reference_sensor?: number | null; artificial_jump_before?: number | null
  artificial_jump_after?: number | null; reduction_pct?: number | null; verdict?: string; error?: string
}
export type SeamRobustness = { windows: SeamRow[]; states: SeamRow[]; state_summary: Record<string, number> }
export type Seam = SeamRow & {
  verdict?: string; verdict_rule?: string; reference_in_band?: boolean
  genuine_change?: { detectable: boolean; direction: string; why?: string | null; resolvable_change_pct?: number | null }
}

const DESIGN_LABEL: Record<string, string> = {
  leave_one_year_out: 'Leave one year out', block_20_month: '20-month block (Terra-only length)',
  rolling_origin_forward: 'Rolling origin - forward', rolling_origin_backward: 'Rolling origin - backward',
}
const VERDICT_TONE: Record<string, 'success' | 'warning' | 'danger' | 'info'> = { pass: 'success', partial: 'warning', fail: 'danger', not_evaluable: 'info' }

export const fmtScore = (m?: Metrics) => (!m || !m.n ? '–' : `${num(m.wape_pct, 1)}% · ${num(m.bias_pct, 1)}% · ${num(m.r2, 2)}`)

export function SeamVerdict({ seam }: { seam: Seam }) {
  if (!seam.verdict) return null
  const g = seam.genuine_change
  return (
    <Banner tone={VERDICT_TONE[seam.verdict] || 'info'} title={`Seam verdict: ${seam.verdict.toUpperCase()}`}>
      <div>{seam.verdict_rule}</div>
      <div>Reference-sensor step {seam.reference_in_band ? 'lies inside' : 'lies outside'} the harmonized step band.</div>
      {g?.why && <div className="mt-1">{g.why}</div>}
    </Banner>
  )
}

export function ModelSelectionPanel() {
  const [stage, setStage] = useState<'mg' | 'sh'>('mg')
  const { data, loading, error } = useApi<ModelSelection>(`/api/validation/model-selection?stage=${stage}`)
  return (
    <Panel title="Calibration model selection (held-out, year-blocked)" badge={<Prov kind="experiment" />}
      sub="Each cell: state-month WAPE · bias · R² on months the model never saw. The default model is replaced only if a candidate wins on both leave-one-year-out and the 20-month block design."
      actions={<Tabs value={stage} onChange={setStage} options={[{ value: 'mg', label: 'Terra → Aqua' }, { value: 'sh', label: 'Aqua → VIIRS' }]} />}>
      <Load loading={loading} error={error} data={data} what="model selection">
        {data && <div className="space-y-3">
          <Banner tone="info" title={`Selected: ${titleCase(data.selected)}`}>{data.reason}{data.selection_rule && <div className="mt-1 text-slate-400">{data.selection_rule}</div>}</Banner>
          {data.backward_extrapolation_warning && <Banner tone="warning" title="Limitation for pre-overlap estimates">{data.backward_extrapolation_warning}</Banner>}
          <div className="overflow-x-auto">
            <Table headers={['Design', 'Folds', ...Object.keys(data.candidates).map(titleCase)]}>
              {Object.entries(data.designs).map(([k, d]) => (
                <tr key={k}>
                  <Td>{DESIGN_LABEL[k] || k}</Td><Td right>{d.n_folds}</Td>
                  {Object.keys(data.candidates).map((cnd) => <Td key={cnd} mono>{cnd === data.selected ? <strong className="text-orange-300">{fmtScore(d.scores[cnd]?.state)}</strong> : fmtScore(d.scores[cnd]?.state)}</Td>)}
                </tr>
              ))}
            </Table>
          </div>
          <p className="text-xs text-slate-400">
            Bootstrap + residual band of the selected model: empirical coverage {num(data.band?.empirical_coverage_pct, 1)}% on 20-month blocks and{' '}
            {num(data.band_backward?.empirical_coverage_pct, 1)}% on backward rolling-origin folds (nominal {num(data.band?.nominal_pct, 0)}%). Training years {data.train_years[0]}–{data.train_years[data.train_years.length - 1]}.
          </p>
          <ul className="list-disc pl-5 text-xs text-slate-400">{Object.entries(data.candidates).map(([k, v]) => <li key={k}><strong>{titleCase(k)}</strong>: {v}</li>)}</ul>
        </div>}
      </Load>
    </Panel>
  )
}

export function SeamRobustnessPanel() {
  const { data, loading, error } = useApi<SeamRobustness>('/api/validation/seam-robustness')
  const row = (r: SeamRow, scope: string, key: string) => (
    <tr key={key}>
      <Td>{scope}</Td><Td right>±{r.window_months ?? 24}</Td><Td right>×{num(r.step_raw, 2)}</Td>
      <Td mono>×{num(r.step_harmonized, 3)} ({num(r.step_harmonized_band?.[0], 2)}–{num(r.step_harmonized_band?.[1], 2)})</Td>
      <Td right>×{num(r.step_reference_sensor, 3)}</Td><Td mono>{num(r.artificial_jump_before, 2)} → {num(r.artificial_jump_after, 3)}</Td>
      <Td>{r.verdict ? titleCase(r.verdict) : r.error}</Td>
    </tr>
  )
  return (
    <Panel title="Real seam robustness - windows and states" badge={<Prov kind="actual" text="Real 2012 seam" />} pad={false}
      sub="The same declared rule applied to several before/after windows nationally and to the most active states (24-month window).">
      <Load loading={loading} error={error} data={data} what="seam robustness">
        {data && <>
          <div className="overflow-x-auto">
            <Table headers={['Scope', 'Window', 'Raw step', 'Harmonized (band)', 'Reference', 'Jump before → after', 'Verdict']}>
              {data.windows.map((w) => row(w, 'India', `w${w.window_months}`))}
              {data.states.map((s) => row(s, s.state || '', `s${s.state}`))}
            </Table>
          </div>
          <p className="px-4 py-2 text-xs text-slate-400">State verdicts: {Object.entries(data.state_summary).map(([k, v]) => `${titleCase(k)} ${v}`).join(' · ') || '–'}</p>
        </>}
      </Load>
    </Panel>
  )
}
