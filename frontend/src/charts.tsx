import { Area, Bar, CartesianGrid, Cell, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import type { ValueType } from 'recharts/types/component/DefaultTooltipContent'
import { C, compact, num } from './lib'

export type LineDef = { key: string; name: string; color: string; dash?: string; width?: number; dots?: boolean }
export type BandDef = { key: string; name: string; color: string }
export type BarDef = { key: string; name: string; color: string; stack?: string }
type RefDef = { x?: string | number; y?: number; label: string }
type Val = ValueType
type Row = object
const get = (r: Row, k: string) => (r as Record<string, unknown>)[k]

const axis = { stroke: '#475569', tick: { fill: '#94a3b8', fontSize: 11 }, tickLine: false as const }
const tip = { contentStyle: { background: '#0B0F19', border: '1px solid #26324a', borderRadius: 6, fontSize: 12, color: '#e2e8f0' }, labelStyle: { color: '#f8fafc', fontWeight: 600 }, itemStyle: { color: '#cbd5e1', padding: 0 } }

const fmtVal = (v: Val | null | undefined, yFmt?: (v: number) => string) => {
  if (Array.isArray(v)) return v[0] == null ? '–' : `${(yFmt || ((x) => num(x)))(Number(v[0]))} – ${(yFmt || ((x) => num(x)))(Number(v[1]))}`
  return v == null ? '–' : (yFmt || ((x: number) => num(x, Math.abs(x) < 10 ? 2 : 0)))(Number(v))
}

/** Lines + optional range bands + optional bars on ONE y-axis. Monthly x keys ("YYYY-MM-DD") get year ticks. */
export function Series({ data, x = 'date', lines = [], bands = [], bars = [], height = 280, yFmt, xFmt, refs = [], yLabel, monthly = true, yDomain, legend = true }: {
  data: readonly Row[]; x?: string; lines?: LineDef[]; bands?: BandDef[]; bars?: BarDef[]; height?: number; yFmt?: (v: number) => string; xFmt?: (v: string | number) => string
  refs?: RefDef[]; yLabel?: string; monthly?: boolean; yDomain?: [number | string, number | string]; legend?: boolean
}) {
  const ticks = monthly ? data.filter((d) => String(get(d, x)).slice(5, 7) === '01').map((d) => get(d, x) as string) : undefined
  const every = ticks && ticks.length > 16 ? 2 : 1
  const nSeries = lines.length + bands.length + bars.length
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data as Row[]} margin={{ top: 8, right: 12, bottom: 0, left: yLabel ? 8 : 0 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey={x} {...axis} ticks={ticks?.filter((_, i) => i % every === 0)} tickFormatter={xFmt || (monthly ? (v) => String(v).slice(0, 4) : undefined)} minTickGap={12} />
        <YAxis {...axis} axisLine={false} width={52} tickFormatter={yFmt || compact} domain={yDomain || [0, 'auto']} label={yLabel ? { value: yLabel, angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 11, dy: 40 } : undefined} />
        <Tooltip {...tip} labelFormatter={(v) => (xFmt ? xFmt(v as string) : monthly ? String(v).slice(0, 7) : String(v))} formatter={(v: unknown, name: unknown) => [fmtVal(v as Val, yFmt), String(name)] as [string, string]} />
        {legend && nSeries > 1 && <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: '#cbd5e1', paddingTop: 4 }} />}
        {bands.map((b) => <Area key={b.key} dataKey={b.key} name={b.name} stroke="none" fill={b.color} fillOpacity={0.22} isAnimationActive={false} connectNulls={false} legendType="rect" />)}
        {bars.map((b) => <Bar key={b.key} dataKey={b.key} name={b.name} fill={b.color} stackId={b.stack} radius={b.stack ? 0 : [3, 3, 0, 0]} maxBarSize={28} isAnimationActive={false} legendType="rect" />)}
        {lines.map((l) => <Line key={l.key} dataKey={l.key} name={l.name} stroke={l.color} strokeWidth={l.width ?? 2} strokeDasharray={l.dash} dot={l.dots ? { r: 3, fill: l.color, stroke: '#111827', strokeWidth: 1 } : false} activeDot={{ r: 4 }} isAnimationActive={false} connectNulls={false} />)}
        {refs.map((r, i) => <ReferenceLine key={i} x={r.x} y={r.y} stroke="#e2e8f0" strokeDasharray="4 3" label={{ value: r.label, fill: '#e2e8f0', fontSize: 11, position: r.x !== undefined ? 'insideTopRight' : 'insideTopLeft' }} />)}
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/** Bars whose colour is a status (e.g. tier) per row; the label carries the meaning, colour only reinforces it. */
export function StatusBars<T extends Row = Row>({ data, x, y, colorOf, height = 220, yFmt, name }: { data: readonly T[]; x: string; y: string; colorOf: (row: T) => string; height?: number; yFmt?: (v: number) => string; name: string }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data as T[]} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey={x} {...axis} interval={0} />
        <YAxis {...axis} axisLine={false} width={52} tickFormatter={yFmt || compact} />
        <Tooltip {...tip} formatter={(v: unknown) => [fmtVal(v as Val, yFmt), name] as [string, string]} cursor={{ fill: '#ffffff10' }} />
        <Bar dataKey={y} name={name} radius={[3, 3, 0, 0]} maxBarSize={48} isAnimationActive={false}>{data.map((d, i) => <Cell key={i} fill={colorOf(d)} />)}</Bar>
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/** Log-log scatter with an optional 1:k guide. */
export function LogScatter({ data, xName, yName, color, height = 280, guide }: { data: { x: number; y: number }[]; xName: string; yName: string; color: string; height?: number; guide?: number }) {
  const pts = data.filter((d) => d.x > 0 && d.y > 0)
  const max = Math.max(10, ...pts.map((d) => d.x))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 8, right: 12, bottom: 18, left: 8 }}>
        <CartesianGrid stroke={C.grid} />
        <XAxis type="number" dataKey="x" name={xName} scale="log" domain={[1, 'auto']} allowDataOverflow {...axis} tickFormatter={compact} label={{ value: xName, position: 'insideBottom', dy: 14, fill: '#94a3b8', fontSize: 11 }} />
        <YAxis type="number" dataKey="y" name={yName} scale="log" domain={[1, 'auto']} allowDataOverflow {...axis} width={52} tickFormatter={compact} label={{ value: yName, angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 11, dy: 50 }} />
        <Tooltip {...tip} cursor={{ strokeDasharray: '3 3' }} formatter={(v: unknown, n: unknown) => [num(Number(v)), String(n)] as [string, string]} />
        <Scatter data={pts} fill={color} fillOpacity={0.45} isAnimationActive={false} />
        {guide && <ReferenceLine segment={[{ x: 1, y: guide }, { x: max, y: max * guide }]} stroke="#e2e8f0" strokeDasharray="4 3" label={{ value: `overall ratio ×${guide.toFixed(1)}`, fill: '#e2e8f0', fontSize: 11, position: 'insideBottomRight' }} />}
      </ScatterChart>
    </ResponsiveContainer>
  )
}

/** Add `[lo, hi]` range fields so <Area> can draw a band. Null when either bound is missing. */
export function withBand<T extends Row = Row>(rows: readonly T[], out: string, lo: string, hi: string): (T & Record<string, unknown>)[] {
  return rows.map((r) => ({ ...r, [out]: get(r, lo) == null || get(r, hi) == null ? null : [get(r, lo), get(r, hi)] }))
}
