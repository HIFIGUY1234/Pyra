/* Application frame: grouped navigation, sidebar, operational top bar. Identity comes only from AuthProvider. */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  Activity, AlertOctagon, BarChart3, Bell, Building2, Calendar, ChevronRight, Clock, Compass, Cpu, Database, FileText, Flame, Gauge,
  GitCompare, Landmark, Layers, LineChart, MapPin, Menu, Network, Orbit, Radar, RefreshCw, Satellite, Settings, ShieldCheck, Sliders,
  TrendingUp, Users, Wind, X,
} from 'lucide-react'
import { regionName, RegionPicker, useApp } from './lib'
import { useAuth } from './auth'
import { AuthBanners, IdentityControl } from './auth-ui'
import { BrandLockup } from './brand'

export type NavItem = { path: string; label: string; icon: ReactNode; adminOnly?: boolean }
export type NavGroup = { label: string; items: NavItem[] }

const I = 'h-4 w-4'
/* Every route has exactly one entry. `adminOnly` marks pages whose API is admin-only on the server (shown, labelled,
 * never hidden: the backend enforces it and a non-admin sees the server's 403 explanation). */
export const NAV: NavGroup[] = [
  { label: 'Monitor', items: [
    { path: '/', label: 'Overview', icon: <Gauge className={I} /> },
    { path: '/map', label: 'Fire Map', icon: <MapPin className={I} /> },
    { path: '/calendar', label: 'Burning Activity Calendar', icon: <Calendar className={I} /> },
    { path: '/events', label: 'Fire Events', icon: <Flame className={I} /> },
  ] },
  { label: 'Satellite Data', items: [
    { path: '/reference', label: 'Historical & Operational Reference', icon: <Radar className={I} /> },
    { path: '/sensors/noaa-20', label: 'VIIRS NOAA-20', icon: <Satellite className={I} /> },
    { path: '/sensors/noaa-21', label: 'VIIRS NOAA-21', icon: <Satellite className={I} /> },
    { path: '/products/viirs375', label: 'VIIRS 375 m', icon: <Layers className={I} /> },
    { path: '/products/viirs750', label: 'VIIRS 750 m', icon: <Layers className={I} /> },
    { path: '/geostationary', label: 'Geostationary & Diurnal', icon: <Satellite className={I} /> },
    { path: '/orbits', label: 'Orbital Opportunities', icon: <Orbit className={I} /> },
    { path: '/observations', label: 'Observation Intelligence', icon: <Compass className={I} /> },
  ] },
  { label: 'Harmonization & Science', items: [
    { path: '/harmonization', label: 'MODIS–VIIRS Harmonizer', icon: <GitCompare className={I} /> },
    { path: '/morning-gap', label: 'Morning-Gap Correction', icon: <Clock className={I} /> },
    { path: '/uncertainty', label: 'Uncertainty', icon: <Activity className={I} /> },
    { path: '/validation', label: 'Validation & Seam Test', icon: <ShieldCheck className={I} /> },
    { path: '/historical-trends', label: 'Historical Trends', icon: <TrendingUp className={I} /> },
    { path: '/external-validation', label: 'External Validation', icon: <ShieldCheck className={I} /> },
  ] },
  { label: 'Forecast & Exposure', items: [
    { path: '/forecast', label: 'Fire Forecast', icon: <LineChart className={I} /> },
    { path: '/forecast/models', label: 'Forecast Model Comparison', icon: <Cpu className={I} /> },
    { path: '/anomalies', label: 'Anomaly Detection', icon: <AlertOctagon className={I} /> },
    { path: '/exposure/population', label: 'Population Exposure', icon: <Users className={I} /> },
    { path: '/exposure/infrastructure', label: 'Infrastructure Exposure', icon: <Network className={I} /> },
    { path: '/critical-regions', label: 'Critical Regions', icon: <Flame className={I} /> },
  ] },
  { label: 'Fire Intelligence', items: [
    { path: '/burned-area', label: 'Burned Area', icon: <Layers className={I} /> },
    { path: '/emissions', label: 'Emissions', icon: <Activity className={I} /> },
    { path: '/smoke', label: 'Smoke Transport', icon: <Wind className={I} /> },
  ] },
  { label: 'Operations', items: [
    { path: '/alerts', label: 'Alerts', icon: <Bell className={I} /> },
    { path: '/government', label: 'Government Dashboard', icon: <Landmark className={I} /> },
    { path: '/organisation', label: 'Organisation Dashboard', icon: <Building2 className={I} /> },
    { path: '/jobs', label: 'Background Jobs', icon: <RefreshCw className={I} /> },
  ] },
  { label: 'Data & Administration', items: [
    { path: '/data', label: 'Data Inventory', icon: <Database className={I} /> },
    { path: '/data/quality', label: 'Data Quality', icon: <BarChart3 className={I} /> },
    { path: '/reports', label: 'Reports', icon: <FileText className={I} /> },
    { path: '/thresholds', label: 'Alert Thresholds', icon: <Sliders className={I} /> },
    { path: '/system', label: 'System Configuration', icon: <Settings className={I} />, adminOnly: true },
    { path: '/deployment', label: 'Deployment Health', icon: <Cpu className={I} /> },
  ] },
]
const FLAT = NAV.flatMap((g) => g.items.map((it) => ({ ...it, group: g.label })))

/** Resolve the nav entry for a path (exact, then longest prefix, e.g. /events/123 -> Fire Events). */
export function sectionFor(path: string) {
  return FLAT.find((s) => s.path === path)
    || FLAT.filter((s) => s.path !== '/' && path.startsWith(`${s.path}/`)).sort((a, b) => b.path.length - a.path.length)[0]
    || (path === '/sensor-harmonizer' ? FLAT.find((s) => s.path === '/harmonization') : undefined)
    || FLAT[0]
}

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { meta } = useApp()
  const { mode } = useAuth()
  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-black/60 lg:hidden" onClick={onClose} aria-hidden="true" />}
      <aside id="app-sidebar" aria-label="Main navigation"
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-line bg-ink-900 transition-transform duration-200 lg:static lg:translate-x-0 ${open ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <BrandLockup />
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:text-white lg:hidden" aria-label="Close navigation menu"><X className="h-4 w-4" /></button>
        </div>
        <nav className="flex-1 space-y-4 overflow-y-auto px-2 py-3">
          {NAV.map((g) => (
            <div key={g.label}>
              <h2 className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500">{g.label}</h2>
              <ul>
                {g.items.map((it) => (
                  <li key={it.path}>
                    <NavLink to={it.path} end={it.path === '/' || it.path === '/data' || it.path === '/forecast'} onClick={onClose}
                      className={({ isActive }) => `flex items-center gap-2.5 border-l-2 px-2 py-1.5 text-[13px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 ${isActive ? 'border-[#e8692a] bg-ink-800 text-white' : 'border-transparent text-slate-300 hover:bg-ink-800 hover:text-white'}`}>
                      <span className="shrink-0 text-slate-500">{it.icon}</span>
                      <span className="min-w-0 flex-1 truncate">{it.label}</span>
                      {it.adminOnly && <span className="rounded border border-line px-1 text-[9px] uppercase tracking-wide text-slate-500" title="Server restricts this page's API to administrators">Admin</span>}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="space-y-1 border-t border-line px-4 py-3 text-[11px]">
          <div className="flex items-center justify-between gap-2">
            <span className="text-slate-500">Processed archive</span>
            {meta == null ? <span className="text-slate-500">–</span>
              : meta.has_data ? <span className="text-emerald-300">Loaded{meta.data_end ? ` · to ${meta.data_end}` : ''}</span>
                : <span className="text-amber-300">Not loaded</span>}
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-slate-500">Forecast model</span>
            {meta == null || !meta.has_data ? <span className="text-slate-500">–</span>
              : meta.forecast_available ? <span className="text-slate-300">Trained</span> : <span className="text-slate-500">Not trained</span>}
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-slate-500">Auth mode</span>
            <span className={mode === 'production' ? 'text-slate-300' : 'text-amber-300'}>{mode === 'production' ? 'Production' : mode === 'dev' ? 'Development' : '–'}</span>
          </div>
        </div>
      </aside>
    </>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { region, meta } = useApp()
  const [mobileOpen, setMobileOpen] = useState(false)
  const section = useMemo(() => sectionFor(location.pathname), [location.pathname])
  useEffect(() => { document.title = `${section.label} · PyroScope` }, [section.label])

  return (
    <div className="flex h-screen w-full overflow-hidden bg-ink-950 text-slate-100">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-ink-800 focus:px-3 focus:py-2 focus:text-sm">Skip to content</a>
      <Sidebar open={mobileOpen} onClose={() => setMobileOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="border-b border-line bg-ink-900">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2 lg:px-6">
            <button type="button" onClick={() => setMobileOpen(true)} aria-label="Open navigation menu" aria-controls="app-sidebar" aria-expanded={mobileOpen}
              className="rounded-md border border-line p-1.5 text-slate-300 hover:text-white lg:hidden"><Menu className="h-4 w-4" /></button>
            <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
              <ol className="flex min-w-0 items-center gap-1 text-[11px] text-slate-500">
                <li className="truncate">{section.group}</li>
                <li aria-hidden="true"><ChevronRight className="h-3 w-3" /></li>
                <li className="truncate text-slate-200" aria-current="page">{section.label}</li>
              </ol>
              <div className="truncate text-[11px] text-slate-500">
                Area <span className="text-slate-300">{regionName(region, meta)}</span>
                {meta?.data_end && <> · Observations to <span className="font-mono text-slate-300">{meta.data_end}</span></>}
              </div>
            </nav>
            <div className="order-last w-full sm:order-none sm:w-auto"><IdentityControl /></div>
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t border-line/70 px-3 py-1.5 lg:px-6">
            <RegionPicker allowCustom />
          </div>
        </header>
        <AuthBanners />
        <main id="main" tabIndex={-1} className="flex-1 overflow-y-auto overflow-x-hidden bg-ink-950 p-3 sm:p-4 lg:p-6">
          <div className="mx-auto max-w-[1500px]">{children}</div>
        </main>
      </div>
    </div>
  )
}
