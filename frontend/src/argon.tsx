import { type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import {
  Flame,
  ShieldAlert,
  Info,
  Inbox,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  Radio,
} from 'lucide-react'

/* ==========================================================================
 * Argon Dashboard React (Creative Tim Free Tier Architecture)
 * Dark Theme Override: Base #0B0F19 / Surface #111827 / Border #26324a
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
 * Risk tier badges must use the five semantic colours (not Argon defaults):
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
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-[#26324a] bg-[#111827]/90 px-4 py-3 text-xs text-slate-300 shadow-sm">
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
 * Argon Card Primitives
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
      className={`rounded-xl border border-[#26324a] bg-[#111827] shadow-[0_0_2rem_0_rgba(0,0,0,0.38)] ${className}`}
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
      className={`flex flex-wrap items-center justify-between gap-3 border-b border-[#26324a] px-5 py-4 ${className}`}
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
  return <div className={`${noPadding ? '' : 'p-5'} ${className}`}>{children}</div>
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
      className={`border-t border-[#26324a] bg-[#0B0F19]/40 px-5 py-3 text-xs text-slate-400 rounded-b-xl ${className}`}
    >
      {children}
    </div>
  )
}

/* --------------------------------------------------------------------------
 * Argon KPI Stat Card (with mandatory Data Provenance Badge)
 * -------------------------------------------------------------------------- */
export function ArgonStatCard({
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
    <Card className="flex flex-col justify-between transition-transform duration-150 hover:-translate-y-0.5">
      <CardBody className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              {title}
            </p>
            <div className="mt-2 text-2xl font-bold tracking-tight text-white tabular-nums">
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
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border"
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
        <div className="mt-3.5 flex items-center justify-between border-t border-[#26324a]/70 pt-2.5">
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
 * Argon Table Component
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
          <tr className="border-b border-[#26324a] bg-[#0B0F19]/75">
            {headers.map((h, i) => (
              <th
                key={i}
                className="px-4 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-400 whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#26324a]/60 text-slate-200">
          {children}
        </tbody>
      </table>
    </div>
  )
}

/* --------------------------------------------------------------------------
 * Argon Form, Button, Banner & Empty State Primitives
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
      'bg-orange-600 hover:bg-orange-500 text-white border-orange-500 shadow-sm',
    secondary:
      'bg-[#172033] hover:bg-[#1f2a40] text-slate-100 border-[#26324a]',
    success:
      'bg-emerald-600/90 hover:bg-emerald-500 text-white border-emerald-500',
    warning:
      'bg-amber-600/90 hover:bg-amber-500 text-white border-amber-500',
    danger: 'bg-red-600/90 hover:bg-red-500 text-white border-red-500',
    outline:
      'bg-transparent hover:bg-[#172033] text-slate-200 border-[#26324a]',
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
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg border font-semibold transition-all disabled:cursor-not-allowed disabled:opacity-45 ${variants[variant]} ${sizes[size]} ${className}`}
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
      className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-xs leading-relaxed ${styles[tone]}`}
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
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-[#26324a] bg-[#0B0F19] text-slate-400">
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

/* --------------------------------------------------------------------------
 * Argon Sidebar Navigation Component (All 17 PyroScope Sections)
 * -------------------------------------------------------------------------- */
export interface NavSectionItem {
  idx: string
  path: string
  label: string
  group: 'Core & Maps' | 'Harmonization & QA' | 'Sensors & Products' | 'Analytics & Forecast' | 'Fire Intelligence' | 'Decision Support' | 'Governance & Data'
  icon: ReactNode
  badge?: string
}

export function ArgonSidebar({
  sections,
  hasData,
  mobileOpen,
  onCloseMobile,
}: {
  sections: NavSectionItem[]
  hasData?: boolean
  mobileOpen: boolean
  onCloseMobile: () => void
}) {
  const groups: NavSectionItem['group'][] = [
    'Core & Maps',
    'Harmonization & QA',
    'Sensors & Products',
    'Analytics & Forecast',
    'Fire Intelligence',
    'Decision Support',
    'Governance & Data',
  ]

  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={onCloseMobile}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-[#26324a] bg-[#111827] text-slate-200 transition-transform duration-200 lg:static lg:translate-x-0 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* PyroScope Brand Logo & Header */}
        <div className="flex items-center justify-between border-b border-[#26324a] bg-[#0B0F19]/60 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-orange-500/40 bg-gradient-to-br from-orange-500/25 to-red-600/25 text-orange-400 shadow-inner">
              <Flame className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-extrabold tracking-tight text-white">
                  PyroScope
                </span>
                <span className="rounded bg-orange-500/15 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-orange-300 border border-orange-500/30">
                  Argon UI
                </span>
              </div>
              <p className="text-[10px] text-slate-400">
                MODIS–VIIRS Harmonization Shell
              </p>
            </div>
          </div>
        </div>

        {/* Navigation Links for All 17 PyroScope Sections */}
        <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
          {groups.map((grp) => {
            const items = sections.filter((s) => s.group === grp)
            return (
              <div key={grp}>
                <div className="px-2.5 pb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                  {grp}
                </div>
                <ul className="space-y-0.5">
                  {items.map((item) => (
                    <li key={item.path}>
                      <NavLink
                        to={item.path}
                        end={item.path === '/'}
                        onClick={onCloseMobile}
                        className={({ isActive }) =>
                          `group flex items-center justify-between rounded-lg px-2.5 py-2 text-xs font-medium transition-colors ${
                            isActive
                              ? 'bg-orange-600/15 text-orange-300 border border-orange-500/40 font-semibold shadow-sm'
                              : 'text-slate-300 hover:bg-[#172033] hover:text-white border border-transparent'
                          }`
                        }
                      >
                        <span className="flex items-center gap-2.5 min-w-0">
                          <span className="text-[10px] font-mono text-slate-500 group-hover:text-slate-400">
                            {item.idx}
                          </span>
                          <span className="shrink-0 text-slate-400 group-hover:text-orange-400">
                            {item.icon}
                          </span>
                          <span className="truncate">{item.label}</span>
                        </span>
                        {item.badge && (
                          <span className="ml-1.5 rounded bg-[#0B0F19] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-slate-400 border border-[#26324a]">
                            {item.badge}
                          </span>
                        )}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </nav>

        {/* Sidebar Footer Status */}
        <div className="border-t border-[#26324a] bg-[#0B0F19]/80 px-4 py-3 text-[11px]">
          <div className="flex items-center justify-between">
            <span className="text-slate-400">Store Status</span>
            <span
              className={`inline-flex items-center gap-1.5 font-semibold ${
                hasData ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  hasData ? 'bg-emerald-400' : 'bg-amber-400'
                }`}
              />
              {hasData ? 'Datasets Active' : 'Awaiting Ingest'}
            </span>
          </div>
          <div className="mt-1.5 flex items-center gap-1 text-[10px] text-slate-500">
            <Sparkles className="h-3 w-3 text-orange-400" />
            <span>17 Scientific Sections Configured</span>
          </div>
        </div>
      </aside>
    </>
  )
}
