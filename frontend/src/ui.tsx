import { type ReactNode } from 'react'
import {
  ShieldAlert,
  Info,
  Inbox,
  CheckCircle2,
  AlertTriangle,
  Radio,
} from 'lucide-react'

/* ==========================================================================
 * PyroScope UI primitives: cards, tables, buttons, banners, provenance and risk badges.
 * Surfaces: base #080d17 / panel #0f1726 / raised #141f33 / rule #22324b. Colour carries meaning only:
 * sensor identity, provenance, risk tier, and status (green verified, amber warning, red critical, grey unavailable).
 * ========================================================================== */

export type ProvenanceType =
  | 'Actual Observation'
  | 'Harmonized Estimate'
  | 'Calibrated Forecast'

export const PROVENANCE_STYLE: Record<
  ProvenanceType,
  { bg: string; border: string; text: string; dot: string }
> = {
  'Actual Observation': {
    bg: 'rgba(14, 165, 233, 0.12)',
    border: 'rgba(56, 189, 248, 0.45)',
    text: '#7dd3fc',
    dot: '#38bdf8',
  },
  'Harmonized Estimate': {
    bg: 'rgba(245, 158, 11, 0.12)',
    border: 'rgba(251, 191, 36, 0.45)',
    text: '#fcd34d',
    dot: '#f59e0b',
  },
  'Calibrated Forecast': {
    bg: 'rgba(249, 115, 22, 0.14)',
    border: 'rgba(251, 146, 60, 0.5)',
    text: '#fdba74',
    dot: '#f97316',
  },
}

/**
 * Scientific / UI Rule:
 * Every probability, stat card, or estimate shown must have a data provenance badge
 * ('Actual Observation', 'Harmonized Estimate', or 'Calibrated Forecast').
 */
export function ProvenanceBadge({
  type,
  className = '',
}: {
  type: ProvenanceType
  className?: string
}) {
  const style = PROVENANCE_STYLE[type] || PROVENANCE_STYLE['Actual Observation']
  return (
    <span
      style={{
        backgroundColor: style.bg,
        borderColor: style.border,
        color: style.text,
      }}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap ${className}`}
    >
      <span
        style={{ backgroundColor: style.dot }}
        className="h-1.5 w-1.5 rounded-full"
      />
      {type}
    </span>
  )
}

/**
 * Scientific / UI Rule:
 * Risk tier badges must use the five semantic colours :
 * Low=green (#10b981), Watch=yellow (#eab308), Moderate=amber (#f59e0b),
 * High=orange (#f97316), Very High=red (#dc2626).
 */
export const SEMANTIC_RISK_COLORS: Record<
  string,
  { hex: string; bg: string; border: string; text: string; label: string }
> = {
  LOW: {
    hex: '#10b981',
    bg: 'rgba(16, 185, 129, 0.14)',
    border: '#10b981',
    text: '#6ee7b7',
    label: 'Low',
  },
  WATCH: {
    hex: '#eab308',
    bg: 'rgba(234, 179, 8, 0.14)',
    border: '#eab308',
    text: '#fde047',
    label: 'Watch',
  },
  MODERATE: {
    hex: '#f59e0b',
    bg: 'rgba(245, 158, 11, 0.15)',
    border: '#f59e0b',
    text: '#fcd34d',
    label: 'Moderate',
  },
  HIGH: {
    hex: '#f97316',
    bg: 'rgba(249, 115, 22, 0.16)',
    border: '#f97316',
    text: '#fdba74',
    label: 'High',
  },
  VERY_HIGH: {
    hex: '#dc2626',
    bg: 'rgba(220, 38, 38, 0.18)',
    border: '#dc2626',
    text: '#fca5a5',
    label: 'Very High',
  },
  CRITICAL: {
    hex: '#dc2626',
    bg: 'rgba(220, 38, 38, 0.22)',
    border: '#dc2626',
    text: '#fecaca',
    label: 'Very High (Critical)',
  },
}

export function normalizeRiskKey(raw?: string | null): string {
  if (!raw) return 'LOW'
  const u = raw.toUpperCase().trim().replace(/\s+/g, '_').replace(/-/g, '_')
  if (u in SEMANTIC_RISK_COLORS) return u
  if (u.includes('VERY') || u.includes('CRIT') || u.includes('EXTREME')) return 'VERY_HIGH'
  if (u.includes('HIGH')) return 'HIGH'
  if (u.includes('MOD') || u.includes('MED')) return 'MODERATE'
  if (u.includes('WATCH') || u.includes('GUARD') || u.includes('ELEV')) return 'WATCH'
  return 'LOW'
}

export function RiskTierBadge({
  tier,
  customLabel,
}: {
  tier?: string | null
  customLabel?: string
}) {
  if (!tier && !customLabel) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-slate-600 bg-slate-800/60 px-2 py-0.5 text-[11px] font-semibold text-slate-300">
        Unclassified
      </span>
    )
  }
  const key = normalizeRiskKey(tier)
  const spec = SEMANTIC_RISK_COLORS[key] || SEMANTIC_RISK_COLORS.LOW
  return (
    <span
      style={{
        backgroundColor: spec.bg,
        borderColor: spec.border,
        color: spec.text,
      }}
      className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-0.5 text-[11px] font-bold tracking-wide whitespace-nowrap"
    >
      <span
        style={{ backgroundColor: spec.hex }}
        className="h-2 w-2 rounded-full"
      />
      {customLabel || spec.label}
    </span>
  )
}

/**
 * Scientific / UI Rule:
 * Label all simulated notification features as "Simulated – Prototype Only".
 */
export function SimulatedBadge({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border border-fuchsia-500/40 bg-fuchsia-500/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-fuchsia-300 whitespace-nowrap ${className}`}
    >
      <Radio className="h-3 w-3 text-fuchsia-400" />
      Simulated – Prototype Only
    </span>
  )
}

/**
 * Scientific / UI Rule:
 * Pages that show model output must display a small uncertainty or confidence note.
 */
export function UncertaintyNote({
  children,
  provenance = 'Calibrated Forecast',
}: {
  children: ReactNode
  provenance?: ProvenanceType
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-[#22324b] bg-[#0f1726]/90 px-4 py-3 text-xs text-slate-300 shadow-sm">
      <div className="flex items-start gap-2.5 max-w-4xl">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
        <div className="leading-relaxed">
          <span className="font-semibold text-slate-100">
            Uncertainty &amp; Model Confidence Note:{' '}
          </span>
          {children}
        </div>
      </div>
      <ProvenanceBadge type={provenance} />
    </div>
  )
}

/* --------------------------------------------------------------------------
 * Card primitives
 * -------------------------------------------------------------------------- */
export function Card({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={`rounded-md border border-[#22324b] bg-[#0f1726] ${className}`}
    >
      {children}
    </div>
  )
}

export function CardHeader({
  title,
  subtitle,
  badge,
  actions,
  className = '',
}: {
  title: ReactNode
  subtitle?: ReactNode
  badge?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 border-b border-[#22324b] px-4 py-3 ${className}`}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2.5">
          <h3 className="text-sm font-semibold tracking-tight text-slate-100">
            {title}
          </h3>
          {badge}
        </div>
        {subtitle && (
          <p className="mt-1 text-xs text-slate-400 leading-relaxed">
            {subtitle}
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function CardBody({
  children,
  className = '',
  noPadding = false,
}: {
  children: ReactNode
  className?: string
  noPadding?: boolean
}) {
  return <div className={`${noPadding ? '' : 'p-4'} ${className}`}>{children}</div>
}

export function CardFooter({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={`border-t border-[#22324b] bg-[#080d17]/40 px-5 py-3 text-xs text-slate-400 rounded-b-xl ${className}`}
    >
      {children}
    </div>
  )
}

/* --------------------------------------------------------------------------
 * KPI stat card (with mandatory Data Provenance Badge)
 * -------------------------------------------------------------------------- */
export function StatCard({
  title,
  value,
  subValue,
  provenance,
  icon,
  accentColor = '#f97316',
}: {
  title: string
  value: ReactNode
  subValue?: ReactNode
  provenance: ProvenanceType
  icon?: ReactNode
  accentColor?: string
}) {
  return (
    <Card className="flex flex-col justify-between">
      <CardBody className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
              {title}
            </p>
            <div className="mt-1.5 text-2xl font-semibold tracking-tight text-white tabular-nums">
              {value}
            </div>
          </div>
          {icon && (
            <div
              style={{
                backgroundColor: `${accentColor}20`,
                borderColor: `${accentColor}55`,
                color: accentColor,
              }}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded border"
            >
              {icon}
            </div>
          )}
        </div>
        {subValue && (
          <div className="mt-2.5 text-xs text-slate-400 leading-snug">
            {subValue}
          </div>
        )}
        <div className="mt-3.5 flex items-center justify-between border-t border-[#22324b]/70 pt-2.5">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">
            Provenance
          </span>
          <ProvenanceBadge type={provenance} />
        </div>
      </CardBody>
    </Card>
  )
}

/* --------------------------------------------------------------------------
 * Table
 * -------------------------------------------------------------------------- */
export function Table({
  headers,
  children,
  className = '',
}: {
  headers: ReactNode[]
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`w-full overflow-x-auto ${className}`}>
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-[#22324b] bg-[#080d17]/75">
            {headers.map((h, i) => (
              <th
                key={i}
                scope="col"
                className="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-slate-400 whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#22324b]/60 text-slate-200">
          {children}
        </tbody>
      </table>
    </div>
  )
}

/* --------------------------------------------------------------------------
 * Form, button, Banner & Empty State Primitives
 * -------------------------------------------------------------------------- */
export function Button({
  children,
  onClick,
  type = 'button',
  variant = 'primary',
  size = 'md',
  disabled = false,
  className = '',
  title,
}: {
  children: ReactNode
  onClick?: () => void
  type?: 'button' | 'submit' | 'reset'
  variant?: 'primary' | 'secondary' | 'success' | 'warning' | 'danger' | 'outline'
  size?: 'xs' | 'sm' | 'md'
  disabled?: boolean
  className?: string
  title?: string
}) {
  const variants: Record<string, string> = {
    primary:
      'bg-[#e8692a] hover:bg-[#f07a3d] text-white border-[#e8692a]',
    secondary:
      'bg-[#141f33] hover:bg-[#1a2740] text-slate-100 border-[#22324b]',
    success:
      'bg-emerald-600/90 hover:bg-emerald-500 text-white border-emerald-500',
    warning:
      'bg-amber-600/90 hover:bg-amber-500 text-white border-amber-500',
    danger: 'bg-red-600/90 hover:bg-red-500 text-white border-red-500',
    outline:
      'bg-transparent hover:bg-[#141f33] text-slate-200 border-[#22324b]',
  }
  const sizes: Record<string, string> = {
    xs: 'px-2 py-1 text-[11px]',
    sm: 'px-3 py-1.5 text-xs',
    md: 'px-4 py-2 text-sm',
  }
  return (
    <button
      type={type}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400 disabled:cursor-not-allowed disabled:opacity-45 ${variants[variant]} ${sizes[size]} ${className}`}
    >
      {children}
    </button>
  )
}

export function FormGroup({
  label,
  hint,
  badge,
  children,
}: {
  label: ReactNode
  hint?: ReactNode
  badge?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-300">
          {label}
        </label>
        {badge}
      </div>
      {children}
      {hint && <p className="text-[11px] text-slate-400">{hint}</p>}
    </div>
  )
}

export function Banner({
  tone = 'warning',
  title,
  children,
}: {
  tone?: 'info' | 'warning' | 'danger' | 'success'
  title?: ReactNode
  children: ReactNode
}) {
  const styles: Record<string, string> = {
    info: 'border-sky-500/40 bg-sky-500/10 text-sky-100',
    warning: 'border-amber-500/50 bg-amber-500/12 text-amber-100',
    danger: 'border-red-500/50 bg-red-500/12 text-red-100',
    success: 'border-emerald-500/50 bg-emerald-500/12 text-emerald-100',
  }
  const icons: Record<string, ReactNode> = {
    info: <Info className="h-4 w-4 shrink-0 text-sky-400" />,
    warning: <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />,
    danger: <ShieldAlert className="h-4 w-4 shrink-0 text-red-400" />,
    success: <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />,
  }
  return (
    <div
      className={`flex items-start gap-3 rounded-md border px-4 py-3 text-xs leading-relaxed ${styles[tone]}`}
    >
      <div className="mt-0.5">{icons[tone]}</div>
      <div className="min-w-0 flex-1">
        {title && <div className="font-bold text-white mb-0.5">{title}</div>}
        <div>{children}</div>
      </div>
    </div>
  )
}

/**
 * Scientific / UI Rule:
 * Do not fabricate API data — if an endpoint returns empty, show an empty state card, not dummy numbers.
 */
export function EmptyStateCard({
  title,
  description,
  action,
}: {
  title: string
  description: ReactNode
  action?: ReactNode
}) {
  return (
    <Card>
      <CardBody className="py-12 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-[#22324b] bg-[#080d17] text-slate-400">
          <Inbox className="h-6 w-6" />
        </div>
        <h4 className="mt-3 text-sm font-semibold text-slate-100">{title}</h4>
        <p className="mx-auto mt-1 max-w-lg text-xs text-slate-400 leading-relaxed">
          {description}
        </p>
        {action && <div className="mt-4 flex justify-center">{action}</div>}
      </CardBody>
    </Card>
  )
}
