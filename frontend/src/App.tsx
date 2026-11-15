import React, { useEffect, useMemo, useState } from 'react'
import {
  BrowserRouter,
  Routes,
  Route,
  useLocation,
  useNavigate,
} from 'react-router-dom'
import {
  Activity,
  AlertOctagon,
  BarChart3,
  Bell,
  Calendar,
  CheckCircle2,
  Clock,
  CloudUpload,
  Compass,
  Database,
  Download,
  FileSpreadsheet,
  FileText,
  Flame,
  Gauge,
  GitCompare,
  Layers,
  MapPin,
  Menu,
  RefreshCw,
  Satellite,
  ShieldCheck,
  Sliders,
  Sparkles,
  TrendingUp,
  UserCheck,
  ArrowUpDown,
  Landmark,
  Building2,
  Radar,
  Orbit,
  Settings,
  Network,
  Users,
  Cpu,
} from 'lucide-react'
import {
  AppCtx,
  api,
  download,
  getApiUser,
  getAuthToken,
  setApiUser,
  useApi,
  num,
  pct,
  titleCase,
  RegionPicker,
  regionName,
  type Meta,
} from './lib'
import {
  ArgonSidebar,
  ArgonStatCard,
  Banner,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyStateCard,
  FormGroup,
  ProvenanceBadge,
  RiskTierBadge,
  SimulatedBadge,
  Table,
  UncertaintyNote,
  normalizeRiskKey,
  type NavSectionItem,
  type ProvenanceType,
} from './argon'
import { AnomaliesPage, CalendarPage, HarmonizerPage, MorningGapPage, TrendsPage, UncertaintyPage, ValidationPage } from './science'
import { AuthControl, CoverageCard, InventoryCard, LoginGate } from './completion'
import { ForecastPage, GovernmentPage, LiveMapPage, ObservationsPage, OrganisationPage } from './ops'
import { ExposurePanel } from './completion_final'
import { BurnedAreaPage, DeploymentPage, EmissionsPage, ExternalValidationPage, FireEventDetailPage, FireEventsPage, GeostationaryPage, JobsPage, SmokePage } from './intel'
import { ExposurePage, ForecastModelsPage, OrbitsPage, ReferencePage, ScoringPanel, SensorPage, SystemConfigPage, Viirs375Page, Viirs750Page } from './final_ops'
import type { Alert, AlertList, AuthMe, CriticalItem, CriticalRegions, DashboardSummary, DataQuality, DataStatus, EvaluateResult, JobResponse, ReportCreated, ReportList, ReportRow, SatelliteSummary, ThresholdResponse, UploadResult } from './types'

/* ==========================================================================
 * 1. All 17 PyroScope Sections for Argon Sidebar & Router
 * ========================================================================== */
export const PYROSCOPE_SECTIONS: NavSectionItem[] = [
  { idx: '01', path: '/', label: 'Overview Dashboard', group: 'Core & Maps', icon: <Gauge className="h-4 w-4" /> },
  { idx: '02', path: '/map', label: 'Live Fire Map', group: 'Core & Maps', icon: <MapPin className="h-4 w-4" /> },
  { idx: '03', path: '/morning-gap', label: 'Morning-Gap Fixer', group: 'Harmonization & QA', icon: <Clock className="h-4 w-4" /> },
  { idx: '04', path: '/harmonization', label: 'MODIS–VIIRS Harmonizer', group: 'Harmonization & QA', icon: <GitCompare className="h-4 w-4" /> },
  { idx: '05', path: '/uncertainty', label: 'Uncertainty Estimation', group: 'Harmonization & QA', icon: <Activity className="h-4 w-4" /> },
  { idx: '06', path: '/validation', label: 'Validation & Seam Test', group: 'Harmonization & QA', icon: <ShieldCheck className="h-4 w-4" /> },
  { idx: '06a', path: '/reference', label: 'Historical & Operational Reference', group: 'Sensors & Products', icon: <Radar className="h-4 w-4" /> },
  { idx: '06b', path: '/sensors/noaa-20', label: 'NOAA-20 VIIRS', group: 'Sensors & Products', icon: <Satellite className="h-4 w-4" /> },
  { idx: '06c', path: '/sensors/noaa-21', label: 'NOAA-21 VIIRS', group: 'Sensors & Products', icon: <Satellite className="h-4 w-4" /> },
  { idx: '06d', path: '/products/viirs375', label: 'VIIRS 375 m', group: 'Sensors & Products', icon: <Layers className="h-4 w-4" /> },
  { idx: '06e', path: '/products/viirs750', label: 'VIIRS 750 m', group: 'Sensors & Products', icon: <Layers className="h-4 w-4" /> },
  { idx: '07', path: '/calendar', label: 'Burning Activity Calendar', group: 'Analytics & Forecast', icon: <Calendar className="h-4 w-4" /> },
  { idx: '08', path: '/historical-trends', label: 'Historical Trends', group: 'Analytics & Forecast', icon: <TrendingUp className="h-4 w-4" /> },
  { idx: '09', path: '/anomalies', label: 'Anomaly Detection', group: 'Analytics & Forecast', icon: <AlertOctagon className="h-4 w-4" /> },
  { idx: '10', path: '/forecast', label: 'Regional Fire Forecast', group: 'Analytics & Forecast', icon: <Sparkles className="h-4 w-4" /> },
  { idx: '10a', path: '/forecast/models', label: 'Forecast Models by Sensor', group: 'Analytics & Forecast', icon: <Cpu className="h-4 w-4" /> },
  { idx: '11', path: '/critical-regions', label: 'Critical Regions', group: 'Analytics & Forecast', icon: <Flame className="h-4 w-4" /> },
  { idx: 'F1', path: '/events', label: 'Fire Events', group: 'Fire Intelligence', icon: <Flame className="h-4 w-4" /> },
  { idx: 'F2', path: '/geostationary', label: 'Geostationary & Diurnal', group: 'Fire Intelligence', icon: <Satellite className="h-4 w-4" /> },
  { idx: 'F3', path: '/burned-area', label: 'Burned-Area Mapping', group: 'Fire Intelligence', icon: <Layers className="h-4 w-4" /> },
  { idx: 'F4', path: '/emissions', label: 'Emissions Estimation', group: 'Fire Intelligence', icon: <Activity className="h-4 w-4" /> },
  { idx: 'F5', path: '/smoke', label: 'Smoke Transport', group: 'Fire Intelligence', icon: <Compass className="h-4 w-4" /> },
  { idx: 'F6', path: '/external-validation', label: 'External Validation', group: 'Fire Intelligence', icon: <ShieldCheck className="h-4 w-4" /> },
  { idx: '12', path: '/observations', label: 'Observation Intelligence', group: 'Analytics & Forecast', icon: <Compass className="h-4 w-4" /> },
  { idx: '12a', path: '/orbits', label: 'Orbital Opportunities', group: 'Analytics & Forecast', icon: <Orbit className="h-4 w-4" /> },
  { idx: '12b', path: '/exposure/population', label: 'Population Exposure', group: 'Analytics & Forecast', icon: <Users className="h-4 w-4" /> },
  { idx: '12c', path: '/exposure/infrastructure', label: 'Infrastructure Exposure', group: 'Analytics & Forecast', icon: <Network className="h-4 w-4" /> },
  { idx: '13', path: '/alerts', label: 'Alerts & Escalation', group: 'Decision Support', icon: <Bell className="h-4 w-4" /> },
  { idx: '14', path: '/government', label: 'Government Dashboard', group: 'Decision Support', icon: <Landmark className="h-4 w-4" /> },
  { idx: '15', path: '/organisation', label: 'Organisation Dashboard', group: 'Decision Support', icon: <Building2 className="h-4 w-4" /> },
  { idx: '16', path: '/thresholds', label: 'Threshold Configuration', group: 'Governance & Data', icon: <Sliders className="h-4 w-4" /> },
  { idx: '17', path: '/data', label: 'Data Management', group: 'Governance & Data', icon: <Database className="h-4 w-4" /> },
  { idx: '18', path: '/data/quality', label: 'Data Quality Report', group: 'Governance & Data', icon: <BarChart3 className="h-4 w-4" /> },
  { idx: '19', path: '/reports', label: 'Reports & Exports', group: 'Governance & Data', icon: <FileText className="h-4 w-4" /> },
  { idx: '20a', path: '/jobs', label: 'Background Jobs', group: 'Governance & Data', icon: <RefreshCw className="h-4 w-4" /> },
  { idx: '20b', path: '/deployment', label: 'Deployment Health', group: 'Governance & Data', icon: <Cpu className="h-4 w-4" /> },
  { idx: '20', path: '/system', label: 'System Configuration', group: 'Governance & Data', icon: <Settings className="h-4 w-4" /> },
]

/* ==========================================================================
 * 2. Overview Dashboard (`/`)
 * ========================================================================== */
function OverviewDashboardPage() {
  const navigate = useNavigate()
  const { data: summary, loading, error, reload } = useApi<DashboardSummary>('/api/dashboard/summary')
  const { data: alertsResp } = useApi<AlertList>('/api/alerts?open_only=true')

  const derived = useMemo(() => {
    if (!summary) return null
    const sats = summary.satellites || {}
    const satEntries = Object.entries(sats) as [string, SatelliteSummary][]

    const modisCount =
      summary.modis_count ??
      (Number(sats.Terra?.detections || 0) + Number(sats.Aqua?.detections || 0))

    const viirsCount =
      summary.viirs_count ??
      (Number(sats['Suomi NPP']?.detections || 0) +
        Number(sats['NOAA-20']?.detections || 0) +
        Number(sats['NOAA-21']?.detections || 0))

    const totalHotspots =
      summary.total_hotspots ??
      summary.total_detections ??
      satEntries.reduce((acc, [, v]) => acc + Number(v?.detections || 0), 0)

    const firstDates = satEntries
      .map(([, v]) => v?.first)
      .filter(Boolean)
      .sort()
    const lastDates = satEntries
      .map(([, v]) => v?.last)
      .filter(Boolean)
      .sort()
    const earliest = firstDates[0] || null
    const latest = summary.data_end || lastDates[lastDates.length - 1] || null
    const dateRange =
      summary.date_range ||
      (earliest && latest ? `${earliest} → ${latest}` : latest || 'Unspanned')

    const seamStatus = summary.seam?.status || summary.validation?.status
    const harmonizationStatus =
      summary.harmonization_status ||
      (seamStatus
        ? `${titleCase(seamStatus)}`
        : summary.provenance_counts
          ? 'Harmonized Series Ready'
          : 'Awaiting Calibration')

    const activeAlerts =
      alertsResp?.total ??
      summary.active_alerts ??
      (summary.forecast
        ? Number(summary.forecast.cells_high || 0) +
          Number(summary.forecast.cells_very_high || 0)
        : null)

    return {
      totalHotspots,
      modisCount,
      viirsCount,
      dateRange,
      harmonizationStatus,
      activeAlerts,
      satEntries,
    }
  }, [summary, alertsResp])

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">
            PyroScope Overview Dashboard
          </h1>
          <p className="mt-0.5 text-xs text-slate-400">
            Multi-sensor MODIS &amp; VIIRS observation inventory, sensor harmonization state, and calibrated risk alert summary.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SimulatedBadge />
          <Button variant="secondary" size="sm" onClick={reload}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh Summary
          </Button>
        </div>
      </div>

      <UncertaintyNote provenance="Harmonized Estimate">
        Harmonized estimates adjust pre-2012 Terra/Aqua MODIS counts to VIIRS-equivalent detection scales with 95% predictive intervals.
        {summary?.validation?.band_coverage_pct !== undefined && (
          <>
            {' '}Hold-out empirical 95% interval coverage:{' '}
            <strong className="text-amber-300">
              {num(summary.validation.band_coverage_pct, 1)}%
            </strong>
            .
          </>
        )}
        {summary?.seam?.reduction_pct !== undefined && (
          <>
            {' '}2012 sensor-transition seam step reduction:{' '}
            <strong className="text-emerald-300">
              {num(summary.seam.reduction_pct, 1)}%
            </strong>
            .
          </>
        )}
        {summary?.forecast?.brier !== undefined && (
          <>
            {' '}7-day forecast Brier score:{' '}
            <strong className="text-orange-300">
              {num(summary.forecast.brier, 4)}
            </strong>{' '}
            (ROC-AUC: {num(summary.forecast.roc_auc, 3)}).
          </>
        )}
      </UncertaintyNote>

      {loading && !summary && (
        <Card>
          <CardBody className="py-12 text-center text-sm text-slate-400 animate-pulse">
            Loading dashboard summary from <code>GET /api/dashboard/summary</code>...
          </CardBody>
        </Card>
      )}

      {!loading && (error || !summary || !derived) && (
        <EmptyStateCard
          title="No Dashboard Summary Data Available"
          description={
            <>
              <code>GET /api/dashboard/summary</code> returned{' '}
              {error ? <span className="text-red-300">{error}</span> : 'an empty dataset'}.
              PyroScope does not fabricate placeholder numbers. Load the repository FIRMS datasets or upload a satellite CSV to populate live metrics.
            </>
          }
          action={
            <Button variant="primary" onClick={() => navigate('/data')}>
              <Database className="h-4 w-4" />
              Open Data Management
            </Button>
          }
        />
      )}

      {summary && derived && (
        <>
          {/* Six Required Argon Stat Cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <ArgonStatCard
              title="Total Hotspots Loaded"
              value={num(derived.totalHotspots)}
              subValue={
                <span>
                  Ingested across <strong>{num(summary.datasets ?? derived.satEntries.length)}</strong> registered dataset(s) and{' '}
                  <strong>{derived.satEntries.length}</strong> active satellite stream(s)
                </span>
              }
              provenance="Actual Observation"
              accentColor="#38bdf8"
              icon={<Flame className="h-5 w-5" />}
            />

            <ArgonStatCard
              title="MODIS Count"
              value={num(derived.modisCount)}
              subValue={
                <span>
                  Terra MODIS: <strong>{num(summary.satellites?.Terra?.detections ?? 0)}</strong> | Aqua MODIS:{' '}
                  <strong>{num(summary.satellites?.Aqua?.detections ?? 0)}</strong>
                </span>
              }
              provenance="Actual Observation"
              accentColor="#3987e5"
              icon={<Satellite className="h-5 w-5" />}
            />

            <ArgonStatCard
              title="VIIRS Count"
              value={num(derived.viirsCount)}
              subValue={
                <span>
                  S-NPP: <strong>{num(summary.satellites?.['Suomi NPP']?.detections ?? 0)}</strong> | NOAA-20:{' '}
                  <strong>{num(summary.satellites?.['NOAA-20']?.detections ?? 0)}</strong> | NOAA-21:{' '}
                  <strong>{num(summary.satellites?.['NOAA-21']?.detections ?? 0)}</strong>
                </span>
              }
              provenance="Actual Observation"
              accentColor="#d95926"
              icon={<Layers className="h-5 w-5" />}
            />

            <ArgonStatCard
              title="Date Range Covered"
              value={<span className="text-lg">{derived.dateRange}</span>}
              subValue={
                <span>
                  Archive end: <strong>{summary.data_end || 'N/A'}</strong>
                  {summary.missing_sensors?.length ? (
                    <span className="text-amber-300">
                      {' '}• Missing: {summary.missing_sensors.join(', ')}
                    </span>
                  ) : (
                    ' • All target sensors spanned'
                  )}
                </span>
              }
              provenance="Actual Observation"
              accentColor="#10b981"
              icon={<Calendar className="h-5 w-5" />}
            />

            <ArgonStatCard
              title="Harmonization Status"
              value={<span className="text-lg">{derived.harmonizationStatus}</span>}
              subValue={
                <span>
                  {summary.seam?.reduction_pct !== undefined
                    ? `Seam step reduced by ${num(summary.seam.reduction_pct, 1)}% (${summary.seam.seam_month || '2012-01'})`
                    : 'Cross-sensor MODIS→VIIRS calibration pipeline'}
                </span>
              }
              provenance="Harmonized Estimate"
              accentColor="#f59e0b"
              icon={<GitCompare className="h-5 w-5" />}
            />

            <ArgonStatCard
              title="Active Alerts"
              value={derived.activeAlerts !== null ? num(derived.activeAlerts) : '0'}
              subValue={
                <span className="flex flex-wrap items-center gap-1.5">
                  <span>
                    {alertsResp?.total !== undefined
                      ? `${num(alertsResp.total)} open alert(s) in queue`
                      : summary.forecast
                        ? `${num(summary.forecast.cells_high)} High + ${num(summary.forecast.cells_very_high)} Very High cells`
                        : 'No active advisories'}
                  </span>
                </span>
              }
              provenance="Calibrated Forecast"
              accentColor="#f97316"
              icon={<Bell className="h-5 w-5" />}
            />
          </div>

          {/* Sensor Inventory Breakdown Card */}
          {derived.satEntries.length > 0 && (
            <Card>
              <CardHeader
                title="Loaded Satellite Sensor Inventory"
                subtitle="Per-instrument temporal coverage, observation counts, and multi-day gap diagnostics from GET /api/dashboard/summary"
                badge={<ProvenanceBadge type="Actual Observation" />}
              />
              <CardBody noPadding>
                <Table
                  headers={[
                    'Sensor',
                    'Instrument Label',
                    'First Observation',
                    'Last Observation',
                    'Days in Span',
                    'Active Fire Days',
                    'Gap Days (≥Run)',
                    'Total Detections',
                    'Provenance',
                  ]}
                >
                  {derived.satEntries.map(([satKey, info]) => (
                    <tr
                      key={satKey}
                      className="hover:bg-[#172033]/60 transition-colors"
                    >
                      <td className="px-4 py-3 font-semibold text-white">
                        {satKey}
                      </td>
                      <td className="px-4 py-3 text-slate-300">
                        {info.label || satKey}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-300">
                        {info.first || '-'}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-300">
                        {info.last || '-'}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {num(info.days_in_span)}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {num(info.days_with_detections)}
                      </td>
                      <td className="px-4 py-3 tabular-nums text-amber-300">
                        {num(info.gap_days)}
                      </td>
                      <td className="px-4 py-3 font-bold text-white tabular-nums">
                        {num(info.detections)}
                      </td>
                      <td className="px-4 py-3">
                        <ProvenanceBadge type="Actual Observation" />
                      </td>
                    </tr>
                  ))}
                </Table>
              </CardBody>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

/* ==========================================================================
 * 3. Alerts Table (`/alerts`)
 * ========================================================================== */
const ALERT_TYPE_STYLE: Record<string, string> = {
  PRE_FIRE_RISK_ADVISORY:
    'border-amber-500/40 bg-amber-500/10 text-amber-300',
  URGENT_RISK_ESCALATION:
    'border-red-500/50 bg-red-500/15 text-red-300',
  UNVERIFIED_SATELLITE_DETECTION:
    'border-sky-500/40 bg-sky-500/10 text-sky-300',
}

function AlertsTablePage() {
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [tierFilter, setTierFilter] = useState<string>('')
  const [openOnly, setOpenOnly] = useState<boolean>(false)
  const [busyId, setBusyId] = useState<number | string | null>(null)
  const [evalBusy, setEvalBusy] = useState<boolean>(false)
  const [actionMsg, setActionMsg] = useState<{
    tone: 'info' | 'success' | 'danger'
    text: string
  } | null>(null)

  const queryPath = useMemo(() => {
    const params = new URLSearchParams()
    if (typeFilter) params.set('alert_type', typeFilter)
    if (tierFilter) params.set('tier', tierFilter)
    if (openOnly) params.set('open_only', 'true')
    params.set('limit', '150')
    const qs = params.toString()
    return `/api/alerts${qs ? `?${qs}` : ''}`
  }, [typeFilter, tierFilter, openOnly])

  const { data, loading, error, reload } = useApi<AlertList>(queryPath, [queryPath])

  const handleRowAction = async (
    alertId: number | string,
    action: 'acknowledge' | 'approve' | 'reject' | 'escalate'
  ) => {
    setBusyId(alertId)
    setActionMsg(null)
    try {
      await api<unknown>(`/api/alerts/${alertId}/${action}`, {
        method: 'POST',
        body: {
          note: `Action ${action.toUpperCase()} executed via PyroScope Argon UI (Simulated – Prototype Only)`,
        },
      })
      setActionMsg({
        tone: 'success',
        text: `Alert #${alertId} updated via POST /api/alerts/${alertId}/${action} (Simulated – Prototype Only).`,
      })
      reload()
    } catch (err) {
      setActionMsg({
        tone: 'danger',
        text: `Failed to ${action} alert #${alertId}: ${err instanceof Error ? err.message : String(err)}`,
      })
    } finally {
      setBusyId(null)
    }
  }

  const handleEvaluateAlerts = async () => {
    setEvalBusy(true)
    setActionMsg(null)
    try {
      const res = await api<EvaluateResult>('/api/alerts/evaluate', { method: 'POST', body: {} })
      setActionMsg({
        tone: 'info',
        text: `Evaluated alert rules across current observations & forecast (${num(res?.created ?? res?.total ?? 0)} alert records processed).`,
      })
      reload()
    } catch (err) {
      setActionMsg({
        tone: 'danger',
        text: `Alert evaluation failed: ${err instanceof Error ? err.message : String(err)}`,
      })
    } finally {
      setEvalBusy(false)
    }
  }

  const items: Alert[] = data?.items || []

  const getAlertProvenance = (alertType?: string): ProvenanceType => {
    if (alertType === 'UNVERIFIED_SATELLITE_DETECTION') {
      return 'Actual Observation'
    }
    return 'Calibrated Forecast'
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-bold tracking-tight text-white">
              Authority Alerts &amp; Escalation Queue
            </h1>
            <SimulatedBadge />
          </div>
          <p className="mt-0.5 text-xs text-slate-400">
            Multi-tier risk advisories, unverified hotspot detections, and human-in-the-loop authority review actions.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            disabled={evalBusy}
            onClick={handleEvaluateAlerts}
          >
            <Sparkles className="h-3.5 w-3.5 text-orange-400" />
            {evalBusy ? 'Evaluating...' : 'Evaluate Alert Rules'}
          </Button>
          <Button variant="outline" size="sm" onClick={reload}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </div>

      <Banner tone="warning" title="Simulated – Prototype Only (Governance & Notification Safeguard)">
        {data?.public_warning_note ||
          'All authority routing, escalation dispatches, and status transitions in this table operate in prototype simulation mode and do not issue statutory public emergency broadcasts.'}
      </Banner>

      <UncertaintyNote provenance="Calibrated Forecast">
        Alert probability values reflect calibrated 7-day regional fire occurrence probabilities with lower/upper confidence bounds{' '}
        <code>[p_lower, p_upper]</code>. Satellite detection alerts require corroborating evidence before incident verification.
      </UncertaintyNote>

      {actionMsg && (
        <Banner tone={actionMsg.tone === 'danger' ? 'danger' : actionMsg.tone === 'success' ? 'success' : 'info'}>
          {actionMsg.text}
        </Banner>
      )}

      {/* Filter Bar */}
      <Card>
        <CardBody className="py-3.5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Type
                </span>
                <select
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}
                  className="bg-[#0B0F19] border border-[#26324a] rounded-lg px-2.5 py-1.5 text-xs text-slate-100"
                >
                  <option value="">All Alert Types</option>
                  <option value="PRE_FIRE_RISK_ADVISORY">
                    PRE_FIRE_RISK_ADVISORY
                  </option>
                  <option value="URGENT_RISK_ESCALATION">
                    URGENT_RISK_ESCALATION
                  </option>
                  <option value="UNVERIFIED_SATELLITE_DETECTION">
                    UNVERIFIED_SATELLITE_DETECTION
                  </option>
                </select>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Risk Category
                </span>
                <select
                  value={tierFilter}
                  onChange={(e) => setTierFilter(e.target.value)}
                  className="bg-[#0B0F19] border border-[#26324a] rounded-lg px-2.5 py-1.5 text-xs text-slate-100"
                >
                  <option value="">All Tiers</option>
                  <option value="LOW">Low (Green)</option>
                  <option value="WATCH">Watch (Yellow)</option>
                  <option value="MODERATE">Moderate (Amber)</option>
                  <option value="HIGH">High (Orange)</option>
                  <option value="VERY_HIGH">Very High (Red)</option>
                </select>
              </div>

              <label className="inline-flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={openOnly}
                  onChange={(e) => setOpenOnly(e.target.checked)}
                />
                Open / Actionable Only
              </label>
            </div>

            <div className="text-xs text-slate-400">
              Showing <strong className="text-white">{num(items.length)}</strong> of{' '}
              <strong className="text-white">{num(data?.total ?? items.length)}</strong> alert(s)
            </div>
          </div>
        </CardBody>
      </Card>

      {loading && !data && (
        <Card>
          <CardBody className="py-12 text-center text-sm text-slate-400 animate-pulse">
            Loading alerts from <code>GET /api/alerts</code>...
          </CardBody>
        </Card>
      )}

      {!loading && (error || items.length === 0) && (
        <EmptyStateCard
          title="No Alerts Returned by API"
          description={
            error ? (
              <span className="text-red-300">Error loading alerts: {error}</span>
            ) : (
              'GET /api/alerts returned 0 matching alert records. Use "Evaluate Alert Rules" above after loading datasets to generate prototype advisories.'
            )
          }
          action={
            <Button
              variant="primary"
              size="sm"
              disabled={evalBusy}
              onClick={handleEvaluateAlerts}
            >
              <Sparkles className="h-4 w-4" />
              Run Alert Evaluation
            </Button>
          }
        />
      )}

      {items.length > 0 && (
        <Card>
          <CardHeader
            title="Active & Historical Alerts"
            subtitle="Columns: Alert ID, Type, Region, Risk Category (5 semantic colours), Probability % with Provenance, Created At, Status, and Row Actions"
            badge={<SimulatedBadge />}
          />
          <CardBody noPadding>
            <Table
              headers={[
                'Alert ID',
                'Type',
                'Region',
                'Risk Category',
                'Probability %',
                'Created At',
                'Status',
                'Row Actions',
              ]}
            >
              {items.map((item) => {
                const id = item.alert_id ?? item.id
                const aType = item.alert_type || 'PRE_FIRE_RISK_ADVISORY'
                const prov = getAlertProvenance(aType)
                const isRowBusy = busyId === id
                const createdAt =
                  item.generated_at || item.created_at || item.issue_date || '-'

                return (
                  <tr
                    key={id}
                    className="hover:bg-[#172033]/60 transition-colors"
                  >
                    <td className="px-4 py-3 font-mono text-xs font-bold text-orange-300 whitespace-nowrap">
                      #{id}
                    </td>

                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-[10px] font-semibold ${
                          ALERT_TYPE_STYLE[aType] ||
                          'border-slate-600 bg-slate-800 text-slate-200'
                        }`}
                      >
                        {aType}
                      </span>
                    </td>

                    <td className="px-4 py-3">
                      <div className="font-semibold text-white">
                        {item.region_name || item.region_id || 'Unknown Region'}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        {item.state ? `${item.state}` : ''}
                        {item.satellite ? ` • Sensor: ${item.satellite}` : ''}
                        {item.frp_mw !== null && item.frp_mw !== undefined
                          ? ` • FRP: ${num(item.frp_mw, 1)} MW`
                          : ''}
                      </div>
                    </td>

                    <td className="px-4 py-3">
                      <RiskTierBadge tier={item.risk_category} />
                    </td>

                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-1">
                        <div className="flex items-baseline gap-2">
                          <span className="text-sm font-bold text-white tabular-nums">
                            {item.probability !== null &&
                            item.probability !== undefined
                              ? pct(item.probability, 1)
                              : 'N/A'}
                          </span>
                          {item.p_lower !== null &&
                            item.p_lower !== undefined &&
                            item.p_upper !== null &&
                            item.p_upper !== undefined && (
                              <span className="text-[11px] text-slate-400 font-mono">
                                [{pct(item.p_lower, 0)}–{pct(item.p_upper, 0)}]
                              </span>
                            )}
                        </div>
                        <div>
                          <ProvenanceBadge type={prov} />
                        </div>
                      </div>
                    </td>

                    <td className="px-4 py-3 font-mono text-xs text-slate-300 whitespace-nowrap">
                      {String(createdAt).replace('T', ' ').slice(0, 19)}
                    </td>

                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-1">
                        <span className="inline-flex w-fit items-center rounded border border-[#26324a] bg-[#0B0F19] px-2 py-0.5 text-[11px] font-semibold text-slate-200">
                          {item.status || 'NEW'}
                        </span>
                        <span className="text-[10px] text-fuchsia-300">
                          Simulated – Prototype Only
                        </span>
                      </div>
                    </td>

                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Button
                          size="xs"
                          variant="secondary"
                          disabled={isRowBusy}
                          onClick={() => handleRowAction(id, 'acknowledge')}
                          title={`POST /api/alerts/${id}/acknowledge`}
                        >
                          Acknowledge
                        </Button>
                        <Button
                          size="xs"
                          variant="success"
                          disabled={isRowBusy}
                          onClick={() => handleRowAction(id, 'approve')}
                          title={`POST /api/alerts/${id}/approve`}
                        >
                          Approve
                        </Button>
                        <Button
                          size="xs"
                          variant="danger"
                          disabled={isRowBusy}
                          onClick={() => handleRowAction(id, 'reject')}
                          title={`POST /api/alerts/${id}/reject`}
                        >
                          Reject
                        </Button>
                        <Button
                          size="xs"
                          variant="warning"
                          disabled={isRowBusy}
                          onClick={() => handleRowAction(id, 'escalate')}
                          title={`POST /api/alerts/${id}/escalate`}
                        >
                          Escalate
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </Table>
          </CardBody>
        </Card>
      )}
    </div>
  )
}

/* ==========================================================================
 * 4. Critical Regions Table (`/critical-regions`)
 * ========================================================================== */
const PRIORITY_RANK_ORDER: Record<string, number> = {
  CRITICAL: 5,
  VERY_HIGH: 5,
  HIGH: 4,
  MODERATE: 3,
  WATCH: 2,
  LOW: 1,
}

function CriticalRegionsPage() {
  const [sortDir, setSortDir] = useState<'desc' | 'asc'>('desc')
  const { data, loading, error, reload } = useApi<CriticalRegions>('/api/critical-regions')

  const sortedItems = useMemo(() => {
    const raw: CriticalItem[] = data?.items || []
    const copy = [...raw]
    copy.sort((a, b) => {
      const keyA = normalizeRiskKey(a.priority)
      const keyB = normalizeRiskKey(b.priority)
      const rankA = PRIORITY_RANK_ORDER[keyA] || 0
      const rankB = PRIORITY_RANK_ORDER[keyB] || 0
      const scoreA = Number(a.score ?? a.p_any ?? 0)
      const scoreB = Number(b.score ?? b.p_any ?? 0)
      const cmp = rankA !== rankB ? rankA - rankB : scoreA - scoreB
      return sortDir === 'desc' ? -cmp : cmp
    })
    return copy
  }, [data, sortDir])

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">
            Critical Regions Priority Ranking
          </h1>
          <p className="mt-0.5 text-xs text-slate-400">
            District-level 7-day calibrated fire risk ranking, land-use jurisdiction routing, and sensor reliability assessment.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}
          >
            <ArrowUpDown className="h-3.5 w-3.5 text-orange-400" />
            Sort by Priority: {sortDir === 'desc' ? 'Highest First' : 'Lowest First'}
          </Button>
          <Button variant="outline" size="sm" onClick={reload}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </div>

      <UncertaintyNote provenance="Calibrated Forecast">
        7-day regional probabilities (<code>p_any</code>) combine calibrated cell-level logistic/gradient-boosted forecasts with 90% empirical confidence bands{' '}
        <code>[band_low, band_high]</code> and historical recurrence weights.
        {data?.issue_date && (
          <>
            {' '}Forecast issue date: <strong className="text-white">{data.issue_date}</strong>.
          </>
        )}
      </UncertaintyNote>

      {loading && !data && (
        <Card>
          <CardBody className="py-12 text-center text-sm text-slate-400 animate-pulse">
            Loading critical regions from <code>GET /api/critical-regions</code>...
          </CardBody>
        </Card>
      )}

      {!loading &&
        (error ||
          !data ||
          data.status === 'forecast_unavailable' ||
          sortedItems.length === 0) && (
          <EmptyStateCard
            title="No Critical Region Forecast Records Available"
            description={
              error ? (
                <span className="text-red-300">{error}</span>
              ) : (
                data?.note ||
                'GET /api/critical-regions returned no ranked districts. Ensure repository datasets are loaded and the forecast model has been built.'
              )
            }
          />
        )}

      {sortedItems.length > 0 && (
        <Card>
          <CardHeader
            title="Critical Regions Table"
            subtitle="Sortable by Priority Level. Displays Rank, Region Name, Priority Level (semantic badge), Jurisdiction, Last Hotspot Date, 7-Day Forecast Probability, and Data Reliability."
            badge={<ProvenanceBadge type="Calibrated Forecast" />}
            actions={<SimulatedBadge />}
          />
          <CardBody noPadding>
            <Table
              headers={[
                'Rank',
                'Region Name',
                <button
                  key="prio-sort"
                  type="button"
                  onClick={() =>
                    setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
                  }
                  className="inline-flex items-center gap-1 text-orange-300 hover:text-orange-200 uppercase font-bold"
                >
                  Priority Level
                  <ArrowUpDown className="h-3 w-3" />
                </button>,
                'Jurisdiction',
                'Last Hotspot Date',
                '7-Day Forecast Probability',
                'Data Reliability',
              ]}
            >
              {sortedItems.map((item, idx) => {
                const authorities = Array.isArray(item.authorities)
                  ? item.authorities
                  : item.authorities?.contacts || []
                const primaryJurisdiction =
                  item.jurisdiction ||
                  (Array.isArray(item.authorities) ? undefined : item.authorities?.primary_authority) ||
                  authorities[0]?.organisation ||
                  authorities[0]?.role ||
                  (item.land_use ? `${item.land_use} Directorate` : 'State Nodal Authority')

                const lastHotspot =
                  item.last_hotspot_date ||
                  ((item.recent7 ?? 0) > 0
                    ? `≤ 7d (${num(item.recent7)} det, thru ${data?.issue_date || 'latest'})`
                    : (item.recent30 ?? 0) > 0
                      ? `≤ 30d (${num(item.recent30)} det)`
                      : data?.issue_date
                        ? `No detections (30d prior to ${data.issue_date})`
                        : 'No recent detections')

                return (
                  <tr
                    key={item.district_id || item.id || idx}
                    className="hover:bg-[#172033]/60 transition-colors"
                  >
                    <td className="px-4 py-3 font-mono text-xs font-bold text-slate-300">
                      #{idx + 1}
                    </td>

                    <td className="px-4 py-3">
                      <div className="font-semibold text-white">
                        {item.name || item.region_name || item.district_id}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        {item.state} • {num(item.n_cells)} grid cell(s)
                      </div>
                    </td>

                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-1">
                        <RiskTierBadge
                          tier={item.priority}
                          customLabel={titleCase(item.priority || 'LOW')}
                        />
                        {item.score !== undefined && (
                          <span className="text-[10px] font-mono text-slate-400">
                            Score: {num(item.score, 2)}
                          </span>
                        )}
                      </div>
                    </td>

                    <td className="px-4 py-3">
                      <div className="text-xs font-medium text-slate-200">
                        {primaryJurisdiction}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        Land Use: {item.land_use || 'Mixed'}
                      </div>
                    </td>

                    <td className="px-4 py-3 font-mono text-xs text-slate-300">
                      {lastHotspot}
                    </td>

                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-1">
                        <div className="flex items-baseline gap-2">
                          <span className="text-sm font-bold text-white tabular-nums">
                            {pct(item.p_any ?? item.forecast_probability, 1)}
                          </span>
                          {Array.isArray(item.band) && item.band.length === 2 && (
                            <span className="font-mono text-[11px] text-slate-400">
                              [{pct(item.band[0], 0)}–{pct(item.band[1], 0)}]
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5">
                          <ProvenanceBadge type="Calibrated Forecast" />
                        </div>
                      </div>
                    </td>

                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-semibold uppercase ${
                          item.reliability === 'good' || item.reliability === 'high'
                            ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                            : item.reliability === 'moderate'
                              ? 'border-amber-500/50 bg-amber-500/10 text-amber-300'
                              : 'border-red-500/50 bg-red-500/10 text-red-300'
                        }`}
                      >
                        {titleCase(item.reliability || 'moderate')}
                      </span>
                      {item.gap30 !== undefined && (
                        <div className="mt-0.5 text-[10px] text-slate-400">
                          30d gap days: {num(item.gap30)}
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </Table>
          </CardBody>
        </Card>
      )}
      <ScoringPanel />
      <ExposurePanel />
    </div>
  )
}

/* ==========================================================================
 * 5. Threshold Configuration Panel (`/thresholds`)
 * ========================================================================== */
function ThresholdConfigurationPage() {
  const { data, loading, error, reload } = useApi<ThresholdResponse>('/api/thresholds/config')

  const [lowMaxPct, setLowMaxPct] = useState<number>(19)
  const [watchPct, setWatchPct] = useState<number>(20)
  const [moderatePct, setModeratePct] = useState<number>(40)
  const [highPct, setHighPct] = useState<number>(60)
  const [veryHighPct, setVeryHighPct] = useState<number>(80)
  const [cooldownHours, setCooldownHours] = useState<number>(72)
  const [scopeType, setScopeType] = useState<'default' | 'land_use' | 'state'>('default')
  const [scopeValue, setScopeValue] = useState<string>('')
  const [evidenceMin, setEvidenceMin] = useState<number>(2)
  const [rationale, setRationale] = useState<string>(
    'Prototype operational starting thresholds aligned with 60% High and 80% Very High alert escalation.'
  )
  const [saving, setSaving] = useState<boolean>(false)
  const [saveBanner, setSaveBanner] = useState<{
    tone: 'success' | 'danger'
    text: string
  } | null>(null)

  useEffect(() => {
    if (!data?.configs?.length) return
    const def =
      data.configs.find((c) => c.scope_type === 'default') ||
      data.configs[0]
    if (def) {
      const w = Math.round(Number(def.watch ?? 0.2) * 100)
      const m = Math.round(Number(def.moderate ?? 0.4) * 100)
      const h = Math.round(Number(def.high ?? 0.6) * 100)
      const vh = Math.round(Number(def.very_high ?? 0.8) * 100)
      setLowMaxPct(Math.max(0, w - 1))
      setWatchPct(w)
      setModeratePct(m)
      setHighPct(h)
      setVeryHighPct(vh)
      setCooldownHours(Number(def.cooldown_hours ?? 72))
      setEvidenceMin(Number(def.evidence_min ?? 2))
      if (def.rationale) setRationale(def.rationale)
    }
  }, [data])

  const handleSaveThresholds = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaveBanner(null)

    if (
      !(
        watchPct > 0 &&
        watchPct < moderatePct &&
        moderatePct < highPct &&
        highPct < veryHighPct &&
        veryHighPct < 100
      )
    ) {
      setSaveBanner({
        tone: 'danger',
        text: 'Thresholds must strictly ascend: 0% < WATCH < MODERATE < HIGH < VERY HIGH < 100%.',
      })
      return
    }

    setSaving(true)
    try {
      await api<unknown>('/api/thresholds/config', {
        method: 'PUT',
        body: {
          scope_type: scopeType,
          scope_value: scopeType === 'default' ? null : scopeValue.trim() || null,
          watch: Number((watchPct / 100).toFixed(4)),
          moderate: Number((moderatePct / 100).toFixed(4)),
          high: Number((highPct / 100).toFixed(4)),
          very_high: Number((veryHighPct / 100).toFixed(4)),
          cooldown_hours: Number(cooldownHours),
          evidence_min: Number(evidenceMin),
          rationale: rationale.trim() || null,
        },
      })
      setSaveBanner({
        tone: 'success',
        text: 'Threshold configuration saved via PUT /api/thresholds/config.',
      })
      reload()
    } catch (err) {
      setSaveBanner({
        tone: 'danger',
        text: `Failed to save threshold config: ${err instanceof Error ? err.message : String(err)}`,
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">
            Threshold Configuration Panel
          </h1>
          <p className="mt-0.5 text-xs text-slate-400">
            Configure the five semantic risk probability tiers and alert suppression cooldown window.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SimulatedBadge />
          <Button variant="outline" size="sm" onClick={reload}>
            <RefreshCw className="h-3.5 w-3.5" />
            Reload Config
          </Button>
        </div>
      </div>

      {/* Mandatory Prototype Statutory Disclaimer Banner */}
      <Banner tone="warning" title="Prototype Threshold Notice">
        <em>
          &ldquo;These are configurable prototype starting thresholds, not official statutory thresholds.&rdquo;
        </em>
      </Banner>

      <UncertaintyNote provenance="Calibrated Forecast">
        Tier cutoffs operate on calibrated 7-day regional fire occurrence probabilities.
        {data?.validation_at_thresholds?.brier !== undefined && (
          <>
            {' '}Current model validation Brier score:{' '}
            <strong className="text-orange-300">
              {num(data.validation_at_thresholds.brier, 4)}
            </strong>{' '}
            | ROC-AUC:{' '}
            <strong className="text-emerald-300">
              {num(data.validation_at_thresholds.roc_auc, 3)}
            </strong>
            .
          </>
        )}
      </UncertaintyNote>

      {saveBanner && (
        <Banner tone={saveBanner.tone === 'success' ? 'success' : 'danger'}>
          {saveBanner.text}
        </Banner>
      )}

      {loading && !data && (
        <Card>
          <CardBody className="py-10 text-center text-sm text-slate-400 animate-pulse">
            Loading threshold configuration from <code>GET /api/thresholds/config</code>...
          </CardBody>
        </Card>
      )}

      {error && !data && (
        <EmptyStateCard
          title="Could Not Load Threshold Configuration"
          description={<span className="text-red-300">{error}</span>}
        />
      )}

      <Card>
        <CardHeader
          title="Five-Tier Probability Thresholds & Cooldown Window"
          subtitle="Loads from GET /api/thresholds/config and saves via PUT /api/thresholds/config"
          badge={<ProvenanceBadge type="Calibrated Forecast" />}
        />
        <CardBody>
          <form onSubmit={handleSaveThresholds} className="space-y-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
              {/* Tier 1: LOW 0-19% */}
              <div className="rounded-xl border border-[#26324a] bg-[#0B0F19]/80 p-3.5">
                <FormGroup
                  label="LOW Tier (0–19%)"
                  badge={<RiskTierBadge tier="LOW" />}
                  hint={`Active span: 0% – ${Math.max(0, watchPct - 1)}%`}
                >
                  <input
                    type="number"
                    min={0}
                    max={95}
                    value={lowMaxPct}
                    onChange={(e) => {
                      const val = Number(e.target.value)
                      setLowMaxPct(val)
                      setWatchPct(Math.min(96, val + 1))
                    }}
                    className="w-full rounded-lg border border-[#26324a] bg-[#111827] px-3 py-2 text-sm font-bold text-white"
                  />
                </FormGroup>
                <div className="mt-2">
                  <ProvenanceBadge type="Calibrated Forecast" />
                </div>
              </div>

              {/* Tier 2: WATCH 20-39% */}
              <div className="rounded-xl border border-[#26324a] bg-[#0B0F19]/80 p-3.5">
                <FormGroup
                  label="WATCH Tier (20–39%)"
                  badge={<RiskTierBadge tier="WATCH" />}
                  hint={`Active span: ${watchPct}% – ${Math.max(watchPct, moderatePct - 1)}%`}
                >
                  <input
                    type="number"
                    min={1}
                    max={96}
                    value={watchPct}
                    onChange={(e) => {
                      const val = Number(e.target.value)
                      setWatchPct(val)
                      setLowMaxPct(Math.max(0, val - 1))
                    }}
                    className="w-full rounded-lg border border-[#26324a] bg-[#111827] px-3 py-2 text-sm font-bold text-white"
                  />
                </FormGroup>
                <div className="mt-2">
                  <ProvenanceBadge type="Calibrated Forecast" />
                </div>
              </div>

              {/* Tier 3: MODERATE 40-59% */}
              <div className="rounded-xl border border-[#26324a] bg-[#0B0F19]/80 p-3.5">
                <FormGroup
                  label="MODERATE Tier (40–59%)"
                  badge={<RiskTierBadge tier="MODERATE" />}
                  hint={`Active span: ${moderatePct}% – ${Math.max(moderatePct, highPct - 1)}%`}
                >
                  <input
                    type="number"
                    min={2}
                    max={97}
                    value={moderatePct}
                    onChange={(e) => setModeratePct(Number(e.target.value))}
                    className="w-full rounded-lg border border-[#26324a] bg-[#111827] px-3 py-2 text-sm font-bold text-white"
                  />
                </FormGroup>
                <div className="mt-2">
                  <ProvenanceBadge type="Calibrated Forecast" />
                </div>
              </div>

              {/* Tier 4: HIGH 60-79% */}
              <div className="rounded-xl border border-[#26324a] bg-[#0B0F19]/80 p-3.5">
                <FormGroup
                  label="HIGH Tier (60–79%)"
                  badge={<RiskTierBadge tier="HIGH" />}
                  hint={`Active span: ${highPct}% – ${Math.max(highPct, veryHighPct - 1)}% (Pre-Fire Advisory)`}
                >
                  <input
                    type="number"
                    min={3}
                    max={98}
                    value={highPct}
                    onChange={(e) => setHighPct(Number(e.target.value))}
                    className="w-full rounded-lg border border-[#26324a] bg-[#111827] px-3 py-2 text-sm font-bold text-white"
                  />
                </FormGroup>
                <div className="mt-2">
                  <ProvenanceBadge type="Calibrated Forecast" />
                </div>
              </div>

              {/* Tier 5: VERY HIGH 80-100% */}
              <div className="rounded-xl border border-[#26324a] bg-[#0B0F19]/80 p-3.5">
                <FormGroup
                  label="VERY HIGH (80–100%)"
                  badge={<RiskTierBadge tier="VERY_HIGH" />}
                  hint={`Active span: ${veryHighPct}% – 100% (Urgent Escalation)`}
                >
                  <input
                    type="number"
                    min={4}
                    max={99}
                    value={veryHighPct}
                    onChange={(e) => setVeryHighPct(Number(e.target.value))}
                    className="w-full rounded-lg border border-[#26324a] bg-[#111827] px-3 py-2 text-sm font-bold text-white"
                  />
                </FormGroup>
                <div className="mt-2">
                  <ProvenanceBadge type="Calibrated Forecast" />
                </div>
              </div>
            </div>

            {/* Cooldown Window & Scope Controls */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
              <FormGroup
                label="Cooldown Window (Hours)"
                hint="Minimum suppression window before re-alerting the same region"
              >
                <input
                  type="number"
                  min={0}
                  max={720}
                  value={cooldownHours}
                  onChange={(e) => setCooldownHours(Number(e.target.value))}
                  className="w-full rounded-lg border border-[#26324a] bg-[#0B0F19] px-3 py-2 text-sm text-white"
                />
              </FormGroup>

              <FormGroup
                label="Minimum Evidence Count"
                hint="Corroborating risk factors required (0–6)"
              >
                <input
                  type="number"
                  min={0}
                  max={6}
                  value={evidenceMin}
                  onChange={(e) => setEvidenceMin(Number(e.target.value))}
                  className="w-full rounded-lg border border-[#26324a] bg-[#0B0F19] px-3 py-2 text-sm text-white"
                />
              </FormGroup>

              <FormGroup
                label="Rule Scope"
                hint={data?.precedence || 'state override > land-use override > default'}
              >
                <select
                  value={scopeType}
                  onChange={(e) => setScopeType(e.target.value as 'default' | 'land_use' | 'state')}
                  className="w-full rounded-lg border border-[#26324a] bg-[#0B0F19] px-3 py-2 text-sm text-white"
                >
                  <option value="default">Default (National)</option>
                  <option value="land_use">Land-Use Override</option>
                  <option value="state">State Override</option>
                </select>
              </FormGroup>

              <FormGroup
                label="Scope Target (if Override)"
                hint="State or Land-Use class name when overriding default"
              >
                <input
                  type="text"
                  disabled={scopeType === 'default'}
                  value={scopeValue}
                  onChange={(e) => setScopeValue(e.target.value)}
                  placeholder={scopeType === 'default' ? 'National Default' : 'e.g. Forest or Madhya Pradesh'}
                  className="w-full rounded-lg border border-[#26324a] bg-[#0B0F19] px-3 py-2 text-sm text-white disabled:opacity-40"
                />
              </FormGroup>
            </div>

            <FormGroup label="Configuration Rationale">
              <input
                type="text"
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                className="w-full rounded-lg border border-[#26324a] bg-[#0B0F19] px-3 py-2 text-sm text-white"
              />
            </FormGroup>

            <div className="flex items-center justify-end gap-3 pt-2">
              <Button type="submit" variant="primary" disabled={saving}>
                <CheckCircle2 className="h-4 w-4" />
                {saving ? 'Saving Thresholds...' : 'Save Threshold Configuration'}
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>

      {/* Active Configurations List */}
      {data && data.configs.length > 0 && (
        <Card>
          <CardHeader
            title="Stored Threshold Scopes"
            subtitle="Active threshold profiles loaded from GET /api/thresholds/config"
            badge={<ProvenanceBadge type="Calibrated Forecast" />}
          />
          <CardBody noPadding>
            <Table
              headers={[
                'Scope',
                'Watch',
                'Moderate',
                'High',
                'Very High',
                'Cooldown (h)',
                'Min Evidence',
                'Updated By',
              ]}
            >
              {data.configs.map((cfg) => (
                <tr key={cfg.id} className="hover:bg-[#172033]/60">
                  <td className="px-4 py-3 font-semibold text-white">
                    {cfg.scope_type}
                    {cfg.scope_value ? `: ${cfg.scope_value}` : ' (Default)'}
                  </td>
                  <td className="px-4 py-3">
                    <RiskTierBadge
                      tier="WATCH"
                      customLabel={`Watch ≥ ${pct(cfg.watch, 0)}`}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <RiskTierBadge
                      tier="MODERATE"
                      customLabel={`Moderate ≥ ${pct(cfg.moderate, 0)}`}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <RiskTierBadge
                      tier="HIGH"
                      customLabel={`High ≥ ${pct(cfg.high, 0)}`}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <RiskTierBadge
                      tier="VERY_HIGH"
                      customLabel={`Very High ≥ ${pct(cfg.very_high, 0)}`}
                    />
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">
                    {num(cfg.cooldown_hours)}h
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">
                    {num(cfg.evidence_min)}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-400">
                    {cfg.updated_by || 'system'}
                  </td>
                </tr>
              ))}
            </Table>
          </CardBody>
        </Card>
      )}
    </div>
  )
}

/* ==========================================================================
 * 6. Data Management Page (`/data`)
 * ========================================================================== */
const UPLOAD_SATELLITE_OPTIONS = [
  { label: 'Terra MODIS', value: 'Terra' },
  { label: 'Aqua MODIS', value: 'Aqua' },
  { label: 'VIIRS Suomi NPP', value: 'Suomi NPP' },
  { label: 'VIIRS NOAA-20', value: 'NOAA-20' },
  { label: 'VIIRS NOAA-21', value: 'NOAA-21' },
]

function DataManagementPage() {
  const { reloadMeta } = React.useContext(AppCtx)
  const { data: statusData, reload: reloadStatus } = useApi<DataStatus>('/api/data/status')

  const [loadRepoBusy, setLoadRepoBusy] = useState(false)
  const [retrainFlag, setRetrainFlag] = useState(false)
  const [loadRepoResponse, setLoadRepoResponse] = useState<JobResponse | null>(null)
  const [loadRepoError, setLoadRepoError] = useState<string | null>(null)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [selectedSatellite, setSelectedSatellite] = useState<string>('Terra')
  const [selectedProduct, setSelectedProduct] = useState<'375m' | '750m'>('375m')
  const isViirsUpload = !['Terra', 'Aqua'].includes(selectedSatellite)
  const [uploadBusy, setUploadBusy] = useState(false)
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const jobState = statusData?.job?.state || loadRepoResponse?.job?.state

  useEffect(() => {
    if (jobState !== 'running') return
    const timer = setInterval(() => {
      reloadStatus()
      reloadMeta()
    }, 2000)
    return () => clearInterval(timer)
  }, [jobState, reloadStatus, reloadMeta])

  const handleLoadRepositoryDatasets = async () => {
    setLoadRepoBusy(true)
    setLoadRepoError(null)
    try {
      const res = await api<JobResponse>(
        `/api/data/load-repo${retrainFlag ? '?retrain=true' : ''}`,
        { method: 'POST', body: {} }
      )
      setLoadRepoResponse(res)
      reloadStatus()
      reloadMeta()
    } catch (err) {
      setLoadRepoError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoadRepoBusy(false)
    }
  }

  const handleUploadCsv = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedFile) {
      setUploadError('Please choose a CSV file to upload.')
      return
    }
    setUploadBusy(true)
    setUploadError(null)
    setUploadResult(null)
    try {
      const form = new FormData()
      form.append('file', selectedFile)
      form.append('satellite', selectedSatellite)
      form.append('product_type', isViirsUpload ? selectedProduct : '1km')
      const res = await api<UploadResult>('/api/data/upload', { method: 'POST', form })
      setUploadResult(res)
      reloadStatus()
      reloadMeta()
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err))
    } finally {
      setUploadBusy(false)
    }
  }

  const handleRebuildPipeline = async () => {
    setLoadRepoBusy(true)
    setLoadRepoError(null)
    try {
      const res = await api<JobResponse>('/api/data/process', { method: 'POST', body: {} })
      setLoadRepoResponse(res)
      reloadStatus()
      reloadMeta()
    } catch (err) {
      setLoadRepoError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoadRepoBusy(false)
    }
  }

  const activeJob = statusData?.job || loadRepoResponse?.job

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">
            Data Management &amp; Satellite CSV Ingestion
          </h1>
          <p className="mt-0.5 text-xs text-slate-400">
            Ingest NASA FIRMS repository archives or upload custom MODIS / VIIRS CSV observation files.
          </p>
        </div>
        <ProvenanceBadge type="Actual Observation" />
      </div>

      {/* Argon Card with Two Required Sections */}
      <Card>
        <CardHeader
          title="Dataset Ingestion & Upload Pipeline"
          subtitle="Section 1: Load Repository Datasets (POST /api/data/load-repo) • Section 2: Upload Satellite CSV (POST /api/data/upload)"
          badge={<ProvenanceBadge type="Actual Observation" />}
        />
        <CardBody className="space-y-6">
          {/* Section 1: Load Repository Datasets */}
          <div className="rounded-xl border border-[#26324a] bg-[#0B0F19]/70 p-5 space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  <Database className="h-4 w-4 text-orange-400" />
                  1. Load Repository Datasets
                </h4>
                <p className="mt-1 text-xs text-slate-400">
                  Triggers <code>POST /api/data/load-repo</code> to ingest discovered MODIS &amp; VIIRS archives and build harmonized series.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <label className="inline-flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={retrainFlag}
                    onChange={(e) => setRetrainFlag(e.target.checked)}
                  />
                  Retrain Forecast Model
                </label>
                <Button
                  variant="primary"
                  disabled={loadRepoBusy || activeJob?.state === 'running'}
                  onClick={handleLoadRepositoryDatasets}
                >
                  <Database className="h-4 w-4" />
                  {activeJob?.state === 'running'
                    ? 'Ingestion Job Running...'
                    : 'Load Repository Datasets'}
                </Button>
              </div>
            </div>

            {loadRepoError && (
              <Banner tone="danger" title="Repository Load Error">
                {loadRepoError}
              </Banner>
            )}

            {activeJob && (
              <div className="rounded-lg border border-[#26324a] bg-[#111827] p-4 space-y-2.5 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-300">
                      Pipeline Job Status:
                    </span>
                    <span
                      className={`rounded px-2 py-0.5 font-mono text-[11px] font-bold uppercase ${
                        activeJob.state === 'done' || activeJob.state === 'idle'
                          ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/40'
                          : activeJob.state === 'running'
                            ? 'bg-amber-500/15 text-amber-300 border border-amber-500/40'
                            : 'bg-red-500/15 text-red-300 border border-red-500/40'
                      }`}
                    >
                      {activeJob.state || 'idle'}
                    </span>
                    {activeJob.step && (
                      <span className="text-slate-300">
                        Step: <strong className="text-white">{activeJob.step}</strong>
                      </span>
                    )}
                  </div>
                  <ProvenanceBadge type="Actual Observation" />
                </div>

                {activeJob.error && (
                  <div className="text-red-300 font-mono">{activeJob.error}</div>
                )}

                {Array.isArray(activeJob.log) && activeJob.log.length > 0 && (
                  <div className="max-h-40 overflow-y-auto rounded bg-[#0B0F19] p-2.5 font-mono text-[11px] text-slate-300 space-y-1 border border-[#26324a]">
                    {activeJob.log.map((line: string, i: number) => (
                      <div key={i}>{line}</div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Section 2: Upload CSV Form */}
          <div className="rounded-xl border border-[#26324a] bg-[#0B0F19]/70 p-5 space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  <CloudUpload className="h-4 w-4 text-sky-400" />
                  2. Upload CSV Observation File
                </h4>
                <p className="mt-1 text-xs text-slate-400">
                  Select a satellite sensor stream and upload a FIRMS CSV file via <code>POST /api/data/upload</code> for schema &amp; quality validation.
                </p>
              </div>
              <ProvenanceBadge type="Actual Observation" />
            </div>

            <form
              onSubmit={handleUploadCsv}
              className="grid grid-cols-1 gap-4 md:grid-cols-3 items-end"
            >
              <FormGroup
                label="Satellite Sensor Selector"
                hint="Select the source instrument for the CSV file"
              >
                <select
                  value={selectedSatellite}
                  onChange={(e) => setSelectedSatellite(e.target.value)}
                  className="w-full rounded-lg border border-[#26324a] bg-[#111827] px-3 py-2 text-sm text-white"
                >
                  {UPLOAD_SATELLITE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                {isViirsUpload && (
                  <select
                    aria-label="VIIRS product"
                    value={selectedProduct}
                    onChange={(e) => setSelectedProduct(e.target.value as '375m' | '750m')}
                    className="mt-2 w-full rounded-lg border border-[#26324a] bg-[#111827] px-3 py-2 text-sm text-white"
                    title="375 m and 750 m are different products and are never pooled"
                  >
                    <option value="375m">VIIRS 375 m (FIRMS VNP14IMGT / VJ114IMGT)</option>
                    <option value="750m">VIIRS 750 m (VNP14 / VJ114 continuity product)</option>
                  </select>
                )}
              </FormGroup>

              <FormGroup
                label="CSV File Picker"
                hint="Standard NASA FIRMS MODIS or VIIRS CSV format"
              >
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) =>
                    setSelectedFile(e.target.files?.[0] || null)
                  }
                  className="w-full rounded-lg border border-[#26324a] bg-[#111827] px-3 py-1.5 text-xs text-slate-200 file:mr-3 file:rounded file:border-0 file:bg-orange-600 file:px-2.5 file:py-1 file:text-xs file:font-semibold file:text-white"
                />
              </FormGroup>

              <div>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={uploadBusy || !selectedFile}
                  className="w-full"
                >
                  <CloudUpload className="h-4 w-4" />
                  {uploadBusy ? 'Uploading & Validating...' : 'Upload & Validate CSV'}
                </Button>
              </div>
            </form>

            {uploadError && (
              <Banner tone="danger" title="CSV Upload Failed">
                {uploadError}
              </Banner>
            )}

            {/* API Validation Results */}
            {uploadResult && (
              <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/5 p-4 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                    <span className="text-xs font-bold text-white">
                      CSV Validation Succeeded: {uploadResult.stored} (
                      {num(uploadResult.bytes)} bytes)
                    </span>
                  </div>
                  <ProvenanceBadge type="Actual Observation" />
                </div>

                {uploadResult.sample_quality && (
                  <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 text-xs">
                    {Object.entries(uploadResult.sample_quality).map(
                      ([k, v]) => (
                        <div
                          key={k}
                          className="rounded border border-[#26324a] bg-[#111827] px-3 py-2"
                        >
                          <div className="text-[10px] uppercase text-slate-400">
                            {titleCase(k)}
                          </div>
                          <div className="mt-0.5 text-sm font-bold text-white tabular-nums">
                            {num(v)}
                          </div>
                        </div>
                      )
                    )}
                  </div>
                )}

                {uploadResult.next && (
                  <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-xs text-slate-300">
                    <span>Next Step: {uploadResult.next}</span>
                    <Button
                      size="xs"
                      variant="secondary"
                      onClick={handleRebuildPipeline}
                    >
                      Run POST /api/data/process Now
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>
        </CardBody>
      </Card>
      <InventoryCard />
      <CoverageCard />
    </div>
  )
}

/* ==========================================================================
 * 7. Data Quality Report (`/data/quality`)
 * ========================================================================== */
function DataQualityReportPage() {
  const navigate = useNavigate()
  const { data, loading, error, reload } = useApi<DataQuality>('/api/data/quality')

  const metrics = useMemo(() => {
    if (!data) return null
    const t = data.totals || {}
    const rowsRead = Number(t.rows_read || 0)
    const rowsKept = Number(t.rows_kept || 0)

    const missingCount =
      Number(t.confidence_missing || 0) +
      Number(t.frp_missing || 0) +
      Number(t.daynight_missing || 0) +
      Number(t.anomaly_type_missing || 0)
    const missingPct =
      t.missing_values_pct !== undefined
        ? Number(t.missing_values_pct)
        : rowsRead > 0
          ? (missingCount / rowsRead) * 100
          : 0

    const invalidCoordCount = Number(t.dropped_invalid_coordinates || 0)
    const invalidCoordPct =
      t.invalid_coordinates_pct !== undefined
        ? Number(t.invalid_coordinates_pct)
        : rowsRead > 0
          ? (invalidCoordCount / rowsRead) * 100
          : 0

    const duplicateRecords = Number(t.duplicates_removed || 0)
    const timestampErrors = Number(t.dropped_invalid_timestamp || 0)
    const frpIssues =
      Number(t.frp_missing || 0) +
      Number(t.frp_invalid_negative || 0) +
      Number(t.frp_extreme_gt_10000MW || 0)

    return {
      rowsRead,
      rowsKept,
      missingCount,
      missingPct,
      invalidCoordCount,
      invalidCoordPct,
      duplicateRecords,
      timestampErrors,
      frpIssues,
      t,
    }
  }, [data])

  const hasDatasets =
    Boolean(data?.datasets?.length) || Number(metrics?.rowsRead || 0) > 0

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">
            Data Quality &amp; Sensor Coverage Report
          </h1>
          <p className="mt-0.5 text-xs text-slate-400">
            Automated ingestion quality diagnostics from <code>GET /api/data/quality</code> across all satellite datasets.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ProvenanceBadge type="Actual Observation" />
          <Button variant="outline" size="sm" onClick={reload}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh Quality Report
          </Button>
        </div>
      </div>

      {loading && !data && (
        <Card>
          <CardBody className="py-12 text-center text-sm text-slate-400 animate-pulse">
            Loading quality diagnostics from <code>GET /api/data/quality</code>...
          </CardBody>
        </Card>
      )}

      {!loading && (error || !hasDatasets || !metrics) && (
        <EmptyStateCard
          title="No Data Quality Records Available"
          description={
            error ? (
              <span className="text-red-300">{error}</span>
            ) : (
              'GET /api/data/quality returned 0 ingested datasets. Load repository datasets or upload a CSV on the Data Management page to inspect quality metrics.'
            )
          }
          action={
            <Button variant="primary" size="sm" onClick={() => navigate('/data')}>
              <Database className="h-4 w-4" />
              Go to Data Management
            </Button>
          }
        />
      )}

      {hasDatasets && metrics && data && (
        <>
          {/* Argon Quality Metric Cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <ArgonStatCard
              title="Missing Values %"
              value={`${num(metrics.missingPct, 2)}%`}
              subValue={
                <span>
                  Total missing attribute flags: <strong>{num(metrics.missingCount)}</strong> (Confidence:{' '}
                  {num(metrics.t.confidence_missing)}, FRP: {num(metrics.t.frp_missing)}, Day/Night:{' '}
                  {num(metrics.t.daynight_missing)})
                </span>
              }
              provenance="Actual Observation"
              accentColor="#eab308"
            />

            <ArgonStatCard
              title="Invalid Coordinates %"
              value={`${num(metrics.invalidCoordPct, 3)}%`}
              subValue={
                <span>
                  Dropped out-of-bounds / non-finite lat-lon rows:{' '}
                  <strong>{num(metrics.invalidCoordCount)}</strong> of{' '}
                  {num(metrics.rowsRead)} read
                </span>
              }
              provenance="Actual Observation"
              accentColor="#f97316"
            />

            <ArgonStatCard
              title="Duplicate Records"
              value={num(metrics.duplicateRecords)}
              subValue={
                <span>
                  Deduplicated identical sensor-timestamp-coordinate records (
                  {metrics.rowsRead > 0
                    ? `${num((metrics.duplicateRecords / metrics.rowsRead) * 100, 2)}%`
                    : '0%'}
                  )
                </span>
              }
              provenance="Actual Observation"
              accentColor="#38bdf8"
            />

            <ArgonStatCard
              title="Timestamp Errors"
              value={num(metrics.timestampErrors)}
              subValue={
                <span>
                  Dropped unparseable or corrupt acquisition date/time rows
                </span>
              }
              provenance="Actual Observation"
              accentColor="#dc2626"
            />

            <ArgonStatCard
              title="FRP Issues"
              value={num(metrics.frpIssues)}
              subValue={
                <span>
                  Missing FRP: <strong>{num(metrics.t.frp_missing)}</strong> • Negative FRP:{' '}
                  <strong>{num(metrics.t.frp_invalid_negative)}</strong> • Extreme (&gt;10,000 MW):{' '}
                  <strong>{num(metrics.t.frp_extreme_gt_10000MW)}</strong>
                </span>
              }
              provenance="Actual Observation"
              accentColor="#f59e0b"
            />

            <ArgonStatCard
              title="Per-Dataset Retention"
              value={`${num(metrics.rowsKept)} / ${num(metrics.rowsRead)}`}
              subValue={
                <span>
                  Net valid records retained ({' '}
                  <strong>
                    {metrics.rowsRead > 0
                      ? `${num((metrics.rowsKept / metrics.rowsRead) * 100, 2)}%`
                      : '0%'}
                  </strong>{' '}
                  pass rate across {num(data.datasets?.length)} dataset files)
                </span>
              }
              provenance="Actual Observation"
              accentColor="#10b981"
            />
          </div>

          {/* Per-Dataset Coverage Card */}
          <Card>
            <CardHeader
              title="Per-Dataset Coverage & Ingestion Audit"
              subtitle="Detailed breakdown per ingested file from GET /api/data/quality"
              badge={<ProvenanceBadge type="Actual Observation" />}
            />
            <CardBody noPadding>
              <Table
                headers={[
                  'Dataset Key / File',
                  'Satellites',
                  'Date Span',
                  'Rows Read',
                  'Rows Kept',
                  'Invalid Coords',
                  'Timestamp Errors',
                  'Duplicates',
                  'FRP Issues',
                ]}
              >
                {(data.datasets || []).map((ds, i: number) => {
                  const q = ds.quality || {}
                  const dsFrp =
                    Number(q.frp_missing || 0) +
                    Number(q.frp_invalid_negative || 0) +
                    Number(q.frp_extreme_gt_10000MW || 0)
                  return (
                    <tr key={ds.key || i} className="hover:bg-[#172033]/60">
                      <td className="px-4 py-3 font-mono text-xs font-semibold text-white">
                        {ds.key || ds.file || `Dataset #${i + 1}`}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-300">
                        {ds.satellites
                          ? Object.keys(ds.satellites).join(', ')
                          : ds.satellite || '-'}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-300">
                        {ds.first && ds.last ? `${ds.first} → ${ds.last}` : '-'}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {num(q.rows_read ?? ds.rows_read)}
                      </td>
                      <td className="px-4 py-3 font-semibold text-emerald-300 tabular-nums">
                        {num(q.rows_kept ?? ds.rows_kept)}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {num(q.dropped_invalid_coordinates)}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {num(q.dropped_invalid_timestamp)}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {num(q.duplicates_removed)}
                      </td>
                      <td className="px-4 py-3 tabular-nums text-amber-300">
                        {num(dsFrp)}
                      </td>
                    </tr>
                  )
                })}
              </Table>
            </CardBody>
          </Card>

          {/* Per-Sensor Coverage Table */}
          {Array.isArray(data.sensors) && data.sensors.length > 0 && (
            <Card>
              <CardHeader
                title="Per-Sensor Temporal Coverage & Gap Summary"
                subtitle="Coverage diagnostics across Terra MODIS, Aqua MODIS, S-NPP VIIRS, NOAA-20 VIIRS, and NOAA-21 VIIRS"
                badge={<ProvenanceBadge type="Actual Observation" />}
              />
              <CardBody noPadding>
                <Table
                  headers={[
                    'Sensor',
                    'Status',
                    'First Date',
                    'Last Date',
                    'Detections',
                    'Days in Span',
                    'Zero-Detection Days',
                  ]}
                >
                  {data.sensors.map((s) => (
                    <tr key={s.satellite} className="hover:bg-[#172033]/60">
                      <td className="px-4 py-3 font-semibold text-white">
                        {s.label || s.satellite}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex rounded px-2 py-0.5 text-[11px] font-semibold ${
                            s.loaded
                              ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/40'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          {s.loaded ? 'Loaded' : 'Not Loaded'}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {s.first || '-'}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {s.last || '-'}
                      </td>
                      <td className="px-4 py-3 font-bold text-white tabular-nums">
                        {num(s.detections)}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {num(s.days_in_span)}
                      </td>
                      <td className="px-4 py-3 tabular-nums text-amber-300">
                        {num(s.zero_detection_days)}
                      </td>
                    </tr>
                  ))}
                </Table>
              </CardBody>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

/* ==========================================================================
 * 8. Reports Page (`/reports`)
 * ========================================================================== */
function ReportsPage() {
  const { meta } = React.useContext(AppCtx)
  const { data, loading, error, reload } = useApi<ReportList>('/api/reports')

  const [regionInput, setRegionInput] = useState<string>('country')
  const [reportType, setReportType] = useState<'full' | 'harmonized'>('full')
  const [generating, setGenerating] = useState<boolean>(false)
  const [genError, setGenError] = useState<string | null>(null)
  const [generatedPair, setGeneratedPair] = useState<{
    pdf: ReportCreated
    csv: ReportCreated
    regionLabel: string
    kindLabel: string
  } | null>(null)

  const resolveRegionId = (raw: string): string => {
    const trimmed = raw.trim()
    if (!trimmed || trimmed.toLowerCase() === 'india' || trimmed.toLowerCase() === 'country') {
      return 'country'
    }
    if (
      trimmed.startsWith('state:') ||
      trimmed.startsWith('district:') ||
      trimmed.startsWith('bbox:')
    ) {
      return trimmed
    }
    const matchedState = meta?.states?.find(
      (s) => s.toLowerCase() === trimmed.toLowerCase()
    )
    if (matchedState) return `state:${matchedState}`
    const matchedDist = meta?.districts?.find(
      (d) =>
        d.name.toLowerCase() === trimmed.toLowerCase() ||
        d.id.toLowerCase() === trimmed.toLowerCase()
    )
    if (matchedDist) return `district:${matchedDist.id}`
    return trimmed
  }

  const handleGenerateReport = async (e: React.FormEvent) => {
    e.preventDefault()
    setGenerating(true)
    setGenError(null)
    setGeneratedPair(null)

    const resolvedRegion = resolveRegionId(regionInput)
    try {
      const [pdfRes, csvRes] = await Promise.all([
        api<ReportCreated>('/api/reports/generate', {
          method: 'POST',
          body: {
            region_id: resolvedRegion,
            kind: reportType,
            format: 'pdf',
          },
        }),
        api<ReportCreated>('/api/reports/generate', {
          method: 'POST',
          body: {
            region_id: resolvedRegion,
            kind: reportType,
            format: 'csv',
          },
        }),
      ])
      setGeneratedPair({
        pdf: pdfRes,
        csv: csvRes,
        regionLabel: resolvedRegion,
        kindLabel:
          reportType === 'full' ? 'Full Report' : 'Harmonized Summary',
      })
      reload()
    } catch (err) {
      setGenError(err instanceof Error ? err.message : String(err))
    } finally {
      setGenerating(false)
    }
  }

  const reportsList: ReportRow[] = data?.items || []

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">
            Scientific Reports &amp; Harmonized Data Exports
          </h1>
          <p className="mt-0.5 text-xs text-slate-400">
            Generate downloadable PDF and CSV analytical reports via <code>POST /api/reports/generate</code>.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ProvenanceBadge type="Harmonized Estimate" />
          <Button variant="outline" size="sm" onClick={reload}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh List
          </Button>
        </div>
      </div>

      <UncertaintyNote provenance="Harmonized Estimate">
        Generated Full and Harmonized Summary reports embed sensor provenance tags, 95% harmonization confidence intervals, and calibrated 7-day forecast probability tables.
      </UncertaintyNote>

      {/* Argon Report Generator Form */}
      <Card>
        <CardHeader
          title="Generate Regional Fire & Harmonization Report"
          subtitle="Specify a region name/ID and report type (Full or Harmonized Summary) to generate both PDF and CSV deliverables"
          badge={<ProvenanceBadge type="Harmonized Estimate" />}
        />
        <CardBody className="space-y-4">
          <form
            onSubmit={handleGenerateReport}
            className="grid grid-cols-1 gap-4 md:grid-cols-3 items-end"
          >
            <FormGroup
              label="Region Name / Identifier"
              hint='Enter "country" (India), a State name (e.g. Madhya Pradesh), or state:Name'
            >
              <input
                type="text"
                value={regionInput}
                onChange={(e) => setRegionInput(e.target.value)}
                placeholder="country or state:Madhya Pradesh"
                className="w-full rounded-lg border border-[#26324a] bg-[#0B0F19] px-3 py-2 text-sm text-white"
              />
            </FormGroup>

            <FormGroup
              label="Report Type"
              hint="Choose Full Multi-Section Report or Harmonized Summary"
            >
              <select
                value={reportType}
                onChange={(e) =>
                  setReportType(e.target.value as 'full' | 'harmonized')
                }
                className="w-full rounded-lg border border-[#26324a] bg-[#0B0F19] px-3 py-2 text-sm text-white"
              >
                <option value="full">Full</option>
                <option value="harmonized">Harmonized Summary</option>
              </select>
            </FormGroup>

            <div>
              <Button
                type="submit"
                variant="primary"
                disabled={generating}
                className="w-full"
              >
                <FileText className="h-4 w-4" />
                {generating ? 'Generating PDF & CSV...' : 'Generate Report'}
              </Button>
            </div>
          </form>

          {genError && (
            <Banner tone="danger" title="Report Generation Failed">
              {genError}
            </Banner>
          )}

          {generatedPair && (
            <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-xs font-bold text-white">
                  Report Generated for{' '}
                  <span className="text-orange-300">
                    {generatedPair.regionLabel}
                  </span>{' '}
                  ({generatedPair.kindLabel})
                </div>
                <ProvenanceBadge type="Harmonized Estimate" />
              </div>
              <div className="flex flex-wrap items-center gap-3">
                {generatedPair.pdf?.id && (
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() =>
                      download(
                        `/api/reports/${generatedPair.pdf.id}/download`,
                        generatedPair.pdf.file ||
                          `pyroscope_report_${generatedPair.pdf.id}.pdf`
                      )
                    }
                  >
                    <Download className="h-3.5 w-3.5" />
                    Download PDF ({num(generatedPair.pdf.bytes)} B)
                  </Button>
                )}
                {generatedPair.csv?.id && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      download(
                        `/api/reports/${generatedPair.csv.id}/download`,
                        generatedPair.csv.file ||
                          `pyroscope_report_${generatedPair.csv.id}.csv`
                      )
                    }
                  >
                    <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-400" />
                    Download CSV ({num(generatedPair.csv.bytes)} B)
                  </Button>
                )}
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Existing Reports Argon Table */}
      {loading && !data && (
        <Card>
          <CardBody className="py-10 text-center text-sm text-slate-400 animate-pulse">
            Loading existing reports from <code>GET /api/reports</code>...
          </CardBody>
        </Card>
      )}

      {!loading && (error || reportsList.length === 0) && (
        <EmptyStateCard
          title="No Generated Reports Found"
          description={
            error ? (
              <span className="text-red-300">{error}</span>
            ) : (
              'GET /api/reports returned an empty list. Use the form above to generate a PDF and CSV report.'
            )
          }
        />
      )}

      {reportsList.length > 0 && (
        <Card>
          <CardHeader
            title="Existing Reports Archive"
            subtitle="All generated reports from GET /api/reports with direct download actions"
            badge={<ProvenanceBadge type="Harmonized Estimate" />}
          />
          <CardBody noPadding>
            <Table
              headers={[
                'ID',
                'Title',
                'Region',
                'Format',
                'Size',
                'Created By',
                'Created At',
                'Provenance',
                'Download',
              ]}
            >
              {reportsList.map((r) => (
                <tr key={r.id} className="hover:bg-[#172033]/60">
                  <td className="px-4 py-3 font-mono text-xs font-bold text-orange-300">
                    #{r.id}
                  </td>
                  <td className="px-4 py-3 font-semibold text-white">
                    {r.title}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-300">
                    {r.region_id || 'country'}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex rounded px-2 py-0.5 font-mono text-[10px] font-bold uppercase ${
                        r.format === 'pdf'
                          ? 'bg-red-500/15 text-red-300 border border-red-500/40'
                          : 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/40'
                      }`}
                    >
                      {r.format}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs tabular-nums">
                    {num(r.bytes)} B
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-300">
                    {r.created_by || 'analyst'}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-400">
                    {String(r.created_at || '').replace('T', ' ').slice(0, 19)}
                  </td>
                  <td className="px-4 py-3">
                    <ProvenanceBadge type="Harmonized Estimate" />
                  </td>
                  <td className="px-4 py-3">
                    <Button
                      size="xs"
                      variant="secondary"
                      onClick={() =>
                        download(
                          `/api/reports/${r.id}/download`,
                          `pyroscope_report_${r.id}.${r.format || 'pdf'}`
                        )
                      }
                    >
                      <Download className="h-3.5 w-3.5 text-orange-400" />
                      Download {String(r.format || 'file').toUpperCase()}
                    </Button>
                  </td>
                </tr>
              ))}
            </Table>
          </CardBody>
        </Card>
      )}
    </div>
  )
}

/* ==========================================================================
 * Top Navbar & Main Argon Shell Layout
 * ========================================================================== */
function ArgonShell() {
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [user, setUserState] = useState<string>(getApiUser())
  const [region, setRegion] = useState<string>('country')
  const { data: meta, reload: reloadMeta } = useApi<Meta>('/api/meta')
  const [authVersion, setAuthVersion] = useState(0)
  const me = useApi<AuthMe>('/api/auth/me', [authVersion, user])

  const setUser = (u: string) => {
    setApiUser(u)
    setUserState(u)
  }

  const role = useMemo(() => {
    if (me.data?.role) return me.data.role as string            // authoritative: the server's view of who we are
    const found = meta?.users?.find((x) => x.username === user)
    return found?.role || 'analyst'
  }, [meta, user, me.data])

  const activeSection = useMemo(() => {
    return (
      PYROSCOPE_SECTIONS.find((s) => s.path === location.pathname) ||
      PYROSCOPE_SECTIONS[0]
    )
  }, [location.pathname])

  return (
    <AppCtx.Provider
      value={{
        user,
        setUser,
        role,
        region,
        setRegion,
        meta: meta || null,
        reloadMeta,
      }}
    >
      <div className="flex h-screen w-full overflow-hidden bg-[#0B0F19] text-slate-100">
        {/* Persistent Left Argon Sidebar */}
        <ArgonSidebar
          sections={PYROSCOPE_SECTIONS}
          hasData={Boolean(meta?.has_data)}
          mobileOpen={mobileOpen}
          onCloseMobile={() => setMobileOpen(false)}
        />

        {/* Right Content Column: Top Argon Navbar + Main Router Outlet */}
        <div className="flex flex-1 flex-col min-w-0 overflow-hidden">
          <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-[#26324a] bg-[#111827]/95 px-4 py-3 backdrop-blur lg:px-6">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setMobileOpen(true)}
                className="inline-flex items-center justify-center rounded-lg border border-[#26324a] bg-[#0B0F19] p-2 text-slate-300 hover:text-white lg:hidden"
                aria-label="Open navigation menu"
              >
                <Menu className="h-4 w-4" />
              </button>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[11px] font-bold text-orange-400">
                    [{activeSection.idx}/{PYROSCOPE_SECTIONS.length}]
                  </span>
                  <span className="text-sm font-bold text-white">
                    {activeSection.label}
                  </span>
                </div>
                <div className="text-[11px] text-slate-400">
                  Active Region: <strong className="text-slate-200">{regionName(region, meta || null)}</strong>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <RegionPicker allowCustom />
              <AuthControl onChange={() => { setAuthVersion((n) => n + 1); reloadMeta() }} />
              {!getAuthToken() && meta?.auth_mode !== 'production' && <div className="flex items-center gap-1.5 rounded-lg border border-[#26324a] bg-[#0B0F19] px-2.5 py-1 text-xs">
                <UserCheck className="h-3.5 w-3.5 text-orange-400" />
                <select
                  aria-label="Active operator profile"
                  value={user}
                  onChange={(e) => setUser(e.target.value)}
                  className="bg-transparent border-0 p-0 text-xs font-semibold text-slate-200 focus:ring-0"
                >
                  {(
                    meta?.users || [
                      { username: 'analyst', display_name: 'Fire Analyst', role: 'analyst' },
                      { username: 'officer', display_name: 'Nodal Officer', role: 'officer' },
                      { username: 'admin', display_name: 'System Admin', role: 'admin' },
                    ]
                  ).map((u) => (
                    <option key={u.username} value={u.username} className="bg-[#111827]">
                      {u.display_name} ({u.role})
                    </option>
                  ))}
                </select>
              </div>}
            </div>
          </header>

          {/* Main Content Area with React Router v6 Routes */}
          <main className="flex-1 overflow-y-auto bg-[#0B0F19] p-4 lg:p-6">
            <div className="mx-auto max-w-[1500px]">
              <LoginGate>
              <Routes>
                <Route path="/" element={<OverviewDashboardPage />} />
                <Route path="/alerts" element={<AlertsTablePage />} />
                <Route path="/critical-regions" element={<CriticalRegionsPage />} />
                <Route path="/thresholds" element={<ThresholdConfigurationPage />} />
                <Route path="/data" element={<DataManagementPage />} />
                <Route path="/data/quality" element={<DataQualityReportPage />} />
                <Route path="/reports" element={<ReportsPage />} />

                <Route path="/map" element={<LiveMapPage />} />
                <Route path="/morning-gap" element={<MorningGapPage />} />
                <Route path="/harmonization" element={<HarmonizerPage />} />
                <Route path="/sensor-harmonizer" element={<HarmonizerPage />} />
                <Route path="/uncertainty" element={<UncertaintyPage />} />
                <Route path="/validation" element={<ValidationPage />} />
                <Route path="/calendar" element={<CalendarPage />} />
                <Route path="/historical-trends" element={<TrendsPage />} />
                <Route path="/anomalies" element={<AnomaliesPage />} />
                <Route path="/forecast" element={<ForecastPage />} />
                <Route path="/forecast/models" element={<ForecastModelsPage />} />
                <Route path="/reference" element={<ReferencePage />} />
                <Route path="/sensors/noaa-20" element={<SensorPage sensor="NOAA-20" />} />
                <Route path="/sensors/noaa-21" element={<SensorPage sensor="NOAA-21" />} />
                <Route path="/products/viirs375" element={<Viirs375Page />} />
                <Route path="/products/viirs750" element={<Viirs750Page />} />
                <Route path="/exposure/population" element={<ExposurePage kind="population" />} />
                <Route path="/exposure/infrastructure" element={<ExposurePage kind="infrastructure" />} />
                <Route path="/orbits" element={<OrbitsPage />} />
                <Route path="/system" element={<SystemConfigPage />} />
                <Route path="/observations" element={<ObservationsPage />} />
                <Route path="/government" element={<GovernmentPage />} />
                <Route path="/organisation" element={<OrganisationPage />} />
                <Route path="/events" element={<FireEventsPage />} />
                <Route path="/events/:id" element={<FireEventDetailPage />} />
                <Route path="/geostationary" element={<GeostationaryPage />} />
                <Route path="/burned-area" element={<BurnedAreaPage />} />
                <Route path="/emissions" element={<EmissionsPage />} />
                <Route path="/smoke" element={<SmokePage />} />
                <Route path="/external-validation" element={<ExternalValidationPage />} />
                <Route path="/jobs" element={<JobsPage />} />
                <Route path="/deployment" element={<DeploymentPage />} />
                <Route path="*" element={<OverviewDashboardPage />} />
              </Routes>
              </LoginGate>
            </div>
          </main>
        </div>
      </div>
    </AppCtx.Provider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ArgonShell />
    </BrowserRouter>
  )
}
