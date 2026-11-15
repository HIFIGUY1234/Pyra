/* API contracts for the PyroScope FastAPI backend (backend/app/main.py and the modules it calls).
 * Fields are optional / nullable where the backend can omit them or return null; nothing here
 * promises a value the API does not send. */

export type N = number | null

/* ------------------------------------------------------------------ shared */
export type Metric = { n?: number; mae?: N; rmse?: N; wape_pct?: N; mape_pct?: N; bias_pct?: N; r2?: N; mean_actual?: N }
export type CalibMonth = { moy: number; daynight: string; ratio: N; ratio_lo: N; ratio_hi: N; silent_rate?: N; predictor_detections?: N; reliable?: boolean }
export type LoyoMonth = { moy: number; wape: N; bias: N; n_years?: number; mean_actual?: N }
export type Calibration = {
  pair?: string; model?: string; band?: string; notes?: string[]; train_years?: number[]; by_month?: CalibMonth[]
  loyo?: { n_years?: number; by_month?: LoyoMonth[] }
}
export type StateFactor = { state: string; ratio: N; predictor_detections?: N; data_weight?: N }
export type XY = { x: number; y: number }
export type Status = { status?: string; message?: string }

/* ------------------------------------------------------------------ satellites / reference sensor */
export type SensorReference = {
  reference_sensor?: string; product?: string; model_version?: string; trained_at?: string; target?: string
  serving_status?: { status: string; message?: string | null; issue_date?: string | null; issue_age_days?: N; platform_status?: string }
}
export type SatelliteSummary = {
  label?: string; first?: string; last?: string; days_in_span?: N; days_with_detections?: N; gap_days?: N; detections?: N
}

/* ------------------------------------------------------------------ dashboard */
export type DashboardSummary = {
  satellites?: Record<string, SatelliteSummary>; modis_count?: N; viirs_count?: N; total_hotspots?: N; total_detections?: N
  data_end?: string; date_range?: string; datasets?: N; missing_sensors?: string[]; harmonization_status?: string
  provenance_counts?: Record<string, number>; active_alerts?: N
  seam?: { status?: string; reduction_pct?: N; seam_month?: string }
  validation?: { status?: string; band_coverage_pct?: N }
  forecast?: { cells_high?: N; cells_very_high?: N; cells?: N; brier?: N; roc_auc?: N; issue_date?: string }
  last7?: Record<string, { detections: number; frp_max?: N; cells: number }>
  validation_error?: string
  timeline?: TimelineRow[]
}
export type TimelineRow = { date: string; harmonized?: N; veq_lo?: N; veq_hi?: N }

/* ------------------------------------------------------------------ alerts */
export type RouteAuthority = { authority: string; role_title: string; level: number; contact_id?: number | null; verified_contact?: boolean; channel?: string | null; organisation?: string; role?: string }
export type Alert = {
  id?: number; alert_id: string; alert_type?: string; risk_category?: string | null; probability?: N; p_lower?: N; p_upper?: N
  n_cells?: N; satellite?: string; frp_mw?: N; issue_date?: string | null; region_name?: string | null; region_id?: string | null
  land_use?: string | null; state?: string | null; status?: string; routing_status?: string; generated_at?: string; created_at?: string
}
export type AlertList = { items: Alert[]; total?: number; public_warning_note?: string }
export type EvaluateResult = {
  status: string; message?: string; issue_date?: string | null; created?: number; total?: number; jurisdiction_review_required?: number
  held_insufficient_evidence?: number; duplicates_skipped?: number; cooldown_suppressed?: number; superseded?: number; downgraded?: number
  detection_alerts_created?: number
}
export type TierDef = { name: string; min: number; max: number; color?: string }
export type ThresholdConfig = {
  id?: number; scope_type: string; scope_value?: string | null; watch?: number; moderate?: number; high?: number; very_high?: number
  cooldown_hours?: number; evidence_min?: number; rationale?: string | null; updated_by?: string | null; tiers?: TierDef[]
}
export type ThresholdResponse = {
  configs: ThresholdConfig[]; governance?: string; precedence?: string
  validation_at_thresholds?: { overall?: Record<string, Confusion>; by_land_use?: Record<string, Record<string, Confusion>>; period?: ForecastModel['split']; brier?: N; roc_auc?: N }
}
export type AuditRow = { at?: string; actor?: string; role?: string; action: string; entity_id?: string; detail?: unknown }

/* ------------------------------------------------------------------ critical regions */
export type CriticalItem = {
  id: string; district_id?: string; name?: string; region_name?: string; state?: string; land_use?: string; n_cells?: N
  p_any?: N; forecast_probability?: N; max_cell_p?: N; score?: number; priority?: string; band?: number | number[] | null
  recent7?: number; recent30?: number; gap30?: number; reliability?: string; jurisdiction?: string; last_hotspot_date?: string
  authorities?: RouteAuthority[] | { contacts?: RouteAuthority[]; primary_authority?: string }
  components?: Record<string, N>; contributions?: Record<string, number>; missing_components?: string[]; reasons?: string[]
}
export type CriticalRegions = {
  status: string; items: CriticalItem[]; issue_date?: string; weights?: Record<string, number>; weights_version?: string
  profile?: string; not_available?: string[]; reference?: SensorReference; note?: string
}

/* ------------------------------------------------------------------ forecast */
export type ForecastCell = {
  cell_id: number; lat?: number; lon?: number; west?: number; south?: number; east?: number; north?: number
  p: number; p_lo: number; p_hi: number; tier?: string; land_use?: string; state?: string; district?: string
  clim?: N; observed?: N; f_gap30?: N
}
export type GridCells = { issue_date?: string; cells: ForecastCell[]; regional?: unknown; reference?: SensorReference }
export type Factor = { group: string; contribution: number }
export type RegionForecast = Status & {
  mode?: string; region?: string; region_id?: string; issue_date?: string; prediction_period?: { from: string; to: string }
  n_cells?: number; n_region_cells?: number; headline_probability?: N; max_cell_probability?: N; risk_category?: string
  suggested_action?: string; tier_basis?: string; meaning?: string; aggregation_note?: string; tier_counts?: Record<string, number>
  regional?: { p_any?: N; p_any_lower?: N; p_any_upper?: N; expected_cells_with_detection?: N }
  supporting?: Record<string, N>; factors?: Factor[]; timeline?: { day: number; date: string; p_any_by_day?: N; max_cell_by_day?: N }[]
  history?: { issue_date: string; p_any: N; max_cell: N; expected_cells: N; observed_cells: N; observed_any: boolean | null }[]
  confidence?: { model_band_mean_width?: N; observation_coverage_score?: N; test_brier?: N; test_roc_auc?: N; note?: string }
  target?: string; reference?: SensorReference
}
export type Jurisdiction = {
  land_use?: string; district?: string | null; state?: string | null; authorities?: RouteAuthority[]; routing_status?: string
  message?: string; note?: string
}
export type CellDetail = {
  status?: string; probability?: N; tier?: string; p_lower?: N; p_upper?: N; seasonal_recurrence?: N; daily_cumulative?: number[]
  factors?: Factor[]; jurisdiction?: Jurisdiction
}
export type Confusion = { tp: number; fp: number; fn: number; tn: number; precision?: N; recall?: N; false_alarm_rate?: N; false_alarm_ratio?: N; missed_event_rate?: N }
export type TestMetrics = { n?: number; base_rate?: N; brier?: N; roc_auc?: N; pr_auc?: N; confusion?: Record<string, Confusion> }
export type ReliabilityBin = { bin_lo: number; bin_hi: number; n: number; mean_pred: N; observed: N }
export type ForecastModel = SensorReference & {
  available: boolean; message?: string; target_kind?: string; trained_on?: string; test?: TestMetrics
  baseline_climatology?: TestMetrics; brier_skill_vs_climatology?: N; calibration_method?: string
  split?: { train_until?: string; calibrate_until?: string; test_from?: string; test_until?: string | null }
  reliability?: ReliabilityBin[]; reliability_uncalibrated?: ReliabilityBin[]
  feature_importance?: { feature: string; label: string; gain_share: number }[]
}
export type RankingItem = { id: string; name: string; tier: string; p_any: N; max_cell: N; cells_high: number; cells_very_high: number; coverage: N }

/* ------------------------------------------------------------------ geography / map */
export type GeoCell = { cell_id?: number; west?: number; south?: number; east?: number; north?: number; land_use: string; district?: string; state?: string; lc_forest?: N; lc_cropland?: N; lc_urban?: N }
export type GeoCells = { label?: string; bbox?: number[] | null; cells: GeoCell[] }
export type Hotspot = {
  latitude: number; longitude: number; satellite: string; instrument?: string; product_type?: string; timestamp_utc?: string; daynight?: string
  confidence_raw?: string | number; confidence_class?: string; confidence_score?: N; frp_mw?: N; pixel_area_km2?: N; scan?: N; track?: N
  anomaly_type?: number | string | null; static_share?: number; district?: string; state?: string; land_use?: string; dataset_version?: string; source_kind?: string
}
export type HotspotResponse = { hotspots: Hotspot[]; returned: number; total_matching: number; thinned?: boolean }
export type DensityCell = {
  cell_id?: number; west?: number; south?: number; east?: number; north?: number; veq?: N
  Terra?: N; Aqua?: N; 'Suomi NPP'?: N; 'NOAA-20'?: N; 'NOAA-21'?: N
}
export type CellLayerResponse = { cells: DensityCell[]; months?: string[] }

/* ------------------------------------------------------------------ observation intelligence */
export type SensorRecord = {
  satellite: string; label: string; loaded: boolean; days_observing?: N; days_in_record?: N; gap_days?: N; days_with_detections?: N
  detections?: N; low_conf_share?: N; high_conf_share?: N; mean_pixel_km2?: N; night_share?: N; last_detection?: string | null
}
export type ObservationQuality = {
  region?: string; limits?: string; coverage_score?: N; coverage_score_definition?: string; window?: [string, string]
  obscuration?: { rain_days_recent?: N; rain_mm_recent?: N; cloud_pct_recent?: N; cloud_pct_climatology_same_months?: N; cloud_note?: string }
  sensors: SensorRecord[]; alternatives_on_gap_days?: Record<string, unknown>[]
}
export type GapCell = DensityCell & { reason: string; district?: string; state?: string; land_use?: string; p?: N; p_lo?: N; p_hi?: N; f_gap30?: N }
export type Alternatives = { counts: Record<string, number>; items: GapCell[]; window_days?: number }
export type Overpasses = {
  reliable_orbital_data?: boolean; message?: string; nominal_local_time_hours?: Record<string, { day: number; night: number }>
  observed_local_time_histogram?: { lst_bin: number; satellite: string; n: number }[]
  orbit_drift?: { year: number; satellite: string; drift_h: N }[]
}

/* ------------------------------------------------------------------ organisations */
export type Organisation = { id: number; name: string; sector?: string; locations?: number }
export type OrgPoint = { latitude: number; longitude: number; satellite: string; acq_date?: string; acq_time?: string; distance_km?: N; frp_mw?: N; confidence_raw?: string | number }
export type OrgLocation = {
  id: number; name: string; region_id: string; land_use_tag?: string; latitude: number; longitude: number; buffer_km: number; alert_threshold?: N
  threshold_breached?: boolean; bbox?: number[] | null; jurisdiction?: Jurisdiction; notification?: { to: string; text: string } | null
  forecast?: RegionForecast; history?: { year: number; complete?: boolean; harmonized?: N; viirs?: N }[]
  nearby_7d?: { total?: N; nearest_km?: N; max_frp_mw?: N; by_satellite?: Record<string, number>; points?: OrgPoint[] }
}
export type OrgOverview = { privacy?: string; locations: OrgLocation[] }
export type Created = { id: number; name?: string }
export type ReportCreated = { id: number; file: string; title?: string; format?: string; bytes?: N; created_at?: string }

/* ------------------------------------------------------------------ science */
export type MorningGapRow = { date: string; terra?: N; aqua?: N; aqua_est?: N; aqua_est_lo?: N; aqua_est_hi?: N; terra_day?: N; aqua_day?: N; terra_night?: N; aqua_night?: N; difference?: N }
export type MorningGapAnalysis = {
  region?: string; mode?: string; mode_message?: string | null; share_months_aqua_below_terra?: N; share_months_aqua_night_below_terra_night?: N
  by_daynight_overlap?: Partial<Record<'day' | 'night', { aqua_per_terra?: N }>>; calibration?: Calibration; terra_only_real_months?: N
  series: MorningGapRow[]; scatter?: XY[]; state_factors?: StateFactor[]; note?: string
}
export type MorningGapRun = {
  label?: string; real_terra_only_message?: string | null; split?: number | string | null
  real_terra_only_period: { date: string; terra: number; aqua_est: number; aqua_est_lo: N; aqua_est_hi: N }[]
  simulated_validation?: { status?: string; metrics?: Metric; baseline_constant_ratio?: Metric; band_coverage_pct?: N }
  simulated: MorningGapRow[]
}
export type HarmRow = { date: string; provenance?: string; viirs?: N; harmonized?: N; harm_lo?: N; harm_hi?: N; veq?: N; veq_lo?: N; veq_hi?: N; modis_total?: N; withheld_viirs?: boolean }
export type HarmSummary = {
  region?: string; notes?: string[]; provenance_counts?: Record<string, number>; pre_viirs_real_months?: N; series?: HarmRow[]
  legend?: Record<string, string>; products?: { viirs?: string; modis?: string }
}
export type HarmYear = { year: number; harmonized: N; lo: N; hi: N; viirs: N; modis: N; estimated: number; months: number }
export type HarmCompare = {
  warning?: string; region?: string
  characteristics: { satellite: string; label: string; detections: N; mean_pixel_area_km2: N; low_conf_share: N; high_conf_share: N; night_share: N; mean_frp_mw: N; static_share_typed: N; nominal_overpass?: (number | null)[] }[]
  yearly: { year: number; terra?: N; aqua?: N; viirs?: N; viirs_per_aqua: N; aqua_per_terra: N }[]
  by_month: { month: number; viirs_per_aqua: N }[]; scatter?: XY[]
}
export type SensorCalib = { product_note?: string; other_viirs?: string; calibration?: Calibration; state_factors?: StateFactor[] }
export type Uncertainty = {
  region?: string; band_coverage_pct?: N; morning_gap_band_coverage_pct?: N; median_relative_width_by_stage?: Record<string, number>; notes?: string[]
  series?: HarmRow[]; by_year: { year: number; rel_width: N; coverage: N }[]; by_month: { month: number; rel_width: number }[]
  weak_calibrations: (CalibMonth & { pair: string })[]; method: string[]
}
export type Validation = {
  status?: string; status_rule?: string; region?: string; overall?: Metric; baseline_constant_ratio?: Metric; baseline_raw_modis?: Metric
  band_coverage_pct?: N; notes?: string[]; train_years?: number[]; test_period?: (string | number)[]; terra_only_end?: string
  by_stage?: Record<string, Metric>; morning_gap?: { validation_kind?: string; metrics?: Metric; baseline_constant_ratio?: Metric }
  by_month?: { month: number; wape_pct: number }[]; by_year?: { year: number; actual: number; estimate: number; lo: N; hi: N; raw_modis: N }[]
  series?: HarmRow[]; validation_kind?: string; reference_product?: string
  by_daynight?: Partial<Record<'day' | 'night', { wape_pct?: N; bias_pct?: N; n?: number }>>
  methodology?: { sensor_stage: string; morning_gap_stage: string; interval: string; baselines?: string[] }
}
export type CalendarDay = { date: string; veq?: N; provenance?: string } & Record<string, string | number | null | undefined>
export type CalendarMonth = { month: number; terra?: N; aqua?: N; viirs?: N; harmonized?: N; veq_lo?: N; veq_hi?: N; cov_terra?: N; cov_aqua?: N; cov_viirs?: N; provenance?: string }
export type Calendar = { region?: string; year?: number; years_available?: number[]; note?: string; days?: CalendarDay[]; months?: CalendarMonth[] }
export type TrendYear = { year: number; complete?: boolean; harmonized?: N; harm_lo?: N; harm_hi?: N; viirs?: N; aqua?: N }
export type Trends = {
  region?: string; yearly?: TrendYear[]; monthly: (HarmRow & Record<string, string | number | boolean | null | undefined>)[]
  seasonal?: { label: string; harmonized_mean?: N; harmonized_p10?: N; harmonized_p90?: N; aqua_mean?: N; terra_mean?: N }[]
  trend_harmonized?: { pct_per_year: number; significant_95?: boolean; t_stat?: N; n_years?: number } | null
  historical_average_per_year?: N; peak_month?: string; peak_month_share?: N; trend_note?: string; frp_note?: string
}
export type RegionTrend = { id: string; name: string; mean_per_year: N; per_1000km2: N; latest_year: N; peak_month?: string; trend_pct_per_year: number; trend_significant?: boolean; frp_mean_mw: N }
export type AnomalyRow = { date: string; observed?: N; baseline_median?: N; baseline_p10?: N; baseline_p90?: N; rolling_12m?: N; z?: N; flag: string; iforest_outlier?: boolean; coverage?: N }
export type AnomalyItem = { id: string; name: string; current: N; median: N; z: N; direction: string; factors?: string[] }
export type Anomalies = {
  series?: { series?: AnomalyRow[]; disclaimer?: string; region?: string; method?: string }
  current?: { status?: string; message?: string; window?: [string, string]; provisional_nrt?: boolean; nrt_note?: string | null; disclaimer?: string; items?: AnomalyItem[] }
}

/* ------------------------------------------------------------------ data management / quality / reports */
export type Job = { state?: string; step?: string; error?: string | null; log?: string[] }
export type DataStatus = { job?: Job | null }
export type JobResponse = { job?: Job | null }
export type UploadResult = { stored?: string; bytes?: number; sample_quality?: Record<string, number | null>; next?: string }
export type QualityCounts = {
  rows_read?: N; rows_kept?: N; dropped_invalid_coordinates?: N; dropped_invalid_timestamp?: N; duplicates_removed?: N
  frp_missing?: N; frp_invalid_negative?: N; frp_extreme_gt_10000MW?: N; confidence_missing?: N; daynight_missing?: N
  anomaly_type_missing?: N; missing_values_pct?: N; invalid_coordinates_pct?: N
}
export type QualityDataset = { key?: string; file?: string; satellite?: string; satellites?: Record<string, unknown>; first?: string; last?: string; rows_read?: N; rows_kept?: N; quality?: QualityCounts }
export type DataQuality = {
  totals?: QualityCounts; datasets?: QualityDataset[]
  sensors: { satellite: string; label?: string; loaded?: boolean; first?: string; last?: string; days_in_span?: N; detections?: N; zero_detection_days?: N }[]
}
export type ReportRow = { id: number; title?: string; region_id?: string; format?: string; bytes?: N; created_at?: string; created_by?: string; file?: string }
export type ReportList = { items: ReportRow[] }
export type AuthMe = { username: string; role: string; display_name?: string; auth?: string }
