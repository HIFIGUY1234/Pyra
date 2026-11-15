"""SQLAlchemy schema. SQLite by default; set DATABASE_URL for PostgreSQL/PostGIS.

Geometry is stored as lat/lon + bounding boxes + grid cell ids so the same schema runs
on SQLite with zero configuration. On PostGIS, add geometry columns/indexes on top.
The full detection archive lives in Parquet (data/processed/hotspots); the
`hotspot_observations` table holds the most recent window used by the live map and
detection alerts.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, create_engine)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from .config import DATABASE_URL

Base = declarative_base()


def normalise_url(url: str) -> str:
    """postgres:// and postgresql:// -> postgresql+psycopg:// (psycopg 3); other URLs unchanged."""
    for pre in ("postgres://", "postgresql://"):
        if url.startswith(pre):
            return "postgresql+psycopg://" + url[len(pre):]
    return url


def is_transaction_pooler(url: str) -> bool:
    """Supabase transaction pooler (Supavisor, port 6543) or PYROSCOPE_DB_POOL=transaction."""
    mode = os.getenv("PYROSCOPE_DB_POOL", "auto").lower()
    if mode in ("transaction", "session", "direct"):
        return mode == "transaction"
    from sqlalchemy.engine import make_url
    try:
        return make_url(url).port == 6543
    except Exception:
        return False


def make_engine(url: str):
    """SQLite (local default), PostgreSQL / Supabase direct or session pooler (bounded QueuePool with pre-ping),
    Supabase transaction pooler (NullPool + no server-side prepared statements, which transaction pooling breaks)."""
    url = normalise_url(url)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    if is_transaction_pooler(url):
        from sqlalchemy.pool import NullPool
        return create_engine(url, poolclass=NullPool, connect_args={"prepare_threshold": None})
    return create_engine(url, pool_size=int(os.getenv("PYROSCOPE_DB_POOL_SIZE", "5")), max_overflow=int(os.getenv("PYROSCOPE_DB_MAX_OVERFLOW", "5")),
                         pool_pre_ping=True, pool_recycle=1800)


engine = make_engine(DATABASE_URL)
Session = sessionmaker(bind=engine, expire_on_commit=False)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(40), unique=True, nullable=False)
    description = Column(String(200))
    permissions = Column(JSON, default=list)


class Organisation(Base):
    __tablename__ = "organisations"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    sector = Column(String(80))
    contact_email = Column(String(160))        # entered by the organisation itself; never invented
    created_by = Column(Integer, ForeignKey("users.id", use_alter=True))
    created_at = Column(DateTime, default=now)
    locations = relationship("MonitoringLocation", back_populates="organisation", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(60), unique=True, nullable=False)
    display_name = Column(String(120))
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    organisation_id = Column(Integer, ForeignKey("organisations.id"))
    jurisdiction_state = Column(String(80))
    jurisdiction_land_use = Column(String(40))
    is_demo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)
    password_hash = Column(String(200))                  # PBKDF2-SHA256; NULL = cannot log in (demo persona only)
    is_active = Column(Boolean, default=True)
    failed_logins = Column(Integer, default=0)
    locked_until = Column(DateTime)
    last_login_at = Column(DateTime)
    role = relationship("Role")


class UserSession(Base):
    """Bearer sessions. Only the SHA-256 of the token is stored."""
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_sha256 = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=now)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime)
    client = Column(String(200))


class MonitoringLocation(Base):
    __tablename__ = "monitoring_locations"
    id = Column(Integer, primary_key=True)
    organisation_id = Column(Integer, ForeignKey("organisations.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    land_use_tag = Column(String(60))
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    buffer_km = Column(Float, default=25.0)
    alert_threshold = Column(Float, default=0.6)
    notify_safety_team = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)
    organisation = relationship("Organisation", back_populates="locations")


class LandUseJurisdiction(Base):
    __tablename__ = "land_use_jurisdictions"
    id = Column(Integer, primary_key=True)
    state = Column(String(80), index=True)
    land_use = Column(String(40), index=True)
    n_cells = Column(Integer)
    area_km2 = Column(Float)
    west = Column(Float); south = Column(Float); east = Column(Float); north = Column(Float)
    source = Column(String(200))
    __table_args__ = (UniqueConstraint("state", "land_use"),)


class AuthorityContact(Base):
    __tablename__ = "authority_contacts"
    id = Column(Integer, primary_key=True)
    land_use = Column(String(40), index=True, nullable=False)
    state = Column(String(80), index=True)            # NULL = role template applying to every state
    district_id = Column(String(60), index=True)
    authority = Column(String(160), nullable=False)   # e.g. "State Forest Department"
    role_title = Column(String(160), nullable=False)  # e.g. "Divisional Forest Officer"
    level = Column(Integer, default=1)                # 1 = first responder, 2+ = escalation
    contact_name = Column(String(160))
    contact_channel = Column(String(40))              # in-app | sms | email
    contact_value = Column(String(200))
    verified = Column(Boolean, default=False)
    verified_by = Column(String(60))
    verified_at = Column(DateTime)
    is_template = Column(Boolean, default=False)


class ThresholdConfig(Base):
    __tablename__ = "threshold_configs"
    id = Column(Integer, primary_key=True)
    scope_type = Column(String(20), nullable=False, default="default")   # default | land_use | state
    scope_value = Column(String(80))
    watch = Column(Float, default=0.20)
    moderate = Column(Float, default=0.40)
    high = Column(Float, default=0.60)
    very_high = Column(Float, default=0.80)
    cooldown_hours = Column(Integer, default=72)
    evidence_min = Column(Integer, default=2)
    rationale = Column(Text)
    updated_by = Column(String(60))
    updated_at = Column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("scope_type", "scope_value"),)


class SatelliteDataset(Base):
    __tablename__ = "satellite_datasets"
    id = Column(Integer, primary_key=True)
    key = Column(String(120), unique=True)
    origin = Column(String(20))
    file = Column(String(200))
    container = Column(String(200))
    satellites = Column(JSON)
    product_types = Column(JSON)
    versions = Column(JSON)
    quality = Column(JSON)
    rows_kept = Column(Integer)
    first_date = Column(Date); last_date = Column(Date)
    processed_at = Column(DateTime)


class SpatialGridCell(Base):
    __tablename__ = "spatial_grid_cells"
    cell_id = Column(Integer, primary_key=True)
    lat = Column(Float); lon = Column(Float)
    state = Column(String(80), index=True)
    district = Column(String(120))
    district_id = Column(String(60), index=True)
    land_use = Column(String(40), index=True)
    land_use_source = Column(String(200))
    lc_forest = Column(Float); lc_savanna = Column(Float); lc_cropland = Column(Float); lc_urban = Column(Float)
    static_share = Column(Float)


class HotspotObservation(Base):
    __tablename__ = "hotspot_observations"
    id = Column(Integer, primary_key=True)
    latitude = Column(Float); longitude = Column(Float)
    acq_date = Column(Date, index=True); acq_time = Column(String(4)); timestamp_utc = Column(DateTime, index=True)
    satellite = Column(String(20), index=True); instrument = Column(String(10)); product_type = Column(String(8))
    confidence_raw = Column(String(8)); confidence_class = Column(String(10)); confidence_score = Column(Float)
    frp_mw = Column(Float); daynight = Column(String(1)); scan = Column(Float); track = Column(Float); pixel_area_km2 = Column(Float)
    anomaly_type = Column(Integer); brightness_k = Column(Float); bright_t31_k = Column(Float)
    dataset_version = Column(String(16)); source_kind = Column(String(20)); source_file = Column(String(120))
    cell_id = Column(Integer, ForeignKey("spatial_grid_cells.cell_id"), index=True)


class DailyFireActivity(Base):
    __tablename__ = "daily_fire_activity"
    id = Column(Integer, primary_key=True)
    date = Column(Date, index=True); state = Column(String(80), index=True); satellite = Column(String(20))
    detections = Column(Integer); presumed_vegetation = Column(Integer); static_sources = Column(Integer)
    frp_sum_mw = Column(Float); frp_max_mw = Column(Float)


class MonthlyFireActivity(Base):
    __tablename__ = "monthly_fire_activity"
    id = Column(Integer, primary_key=True)
    ym = Column(Integer, index=True); state = Column(String(80), index=True); satellite = Column(String(20))
    detections = Column(Integer); presumed_vegetation = Column(Integer); static_sources = Column(Integer)
    frp_sum_mw = Column(Float); coverage = Column(Float)


class HarmonizedObservation(Base):
    __tablename__ = "harmonized_observations"
    id = Column(Integer, primary_key=True)
    region_id = Column(String(120), index=True); ym = Column(Integer, index=True)
    provenance = Column(String(30))       # actual_viirs | sensor_calibrated | morning_gap_sensor | no_data
    terra = Column(Float); aqua = Column(Float); viirs_actual = Column(Float)
    viirs_equivalent = Column(Float); lower = Column(Float); upper = Column(Float); harmonized = Column(Float)
    cov_terra = Column(Float); cov_aqua = Column(Float); cov_viirs = Column(Float)


class MorningGapCalibration(Base):
    __tablename__ = "morning_gap_calibrations"
    id = Column(Integer, primary_key=True)
    run = Column(String(20), index=True); moy = Column(Integer); daynight = Column(String(5))
    ratio = Column(Float); ratio_lo = Column(Float); ratio_hi = Column(Float); silent_rate = Column(Float)
    predictor_detections = Column(Float); reliable = Column(Boolean); train_years = Column(JSON)


class SensorCalibration(Base):
    __tablename__ = "sensor_calibrations"
    id = Column(Integer, primary_key=True)
    run = Column(String(20), index=True); moy = Column(Integer); daynight = Column(String(5))
    ratio = Column(Float); ratio_lo = Column(Float); ratio_hi = Column(Float); silent_rate = Column(Float)
    predictor_detections = Column(Float); reliable = Column(Boolean); train_years = Column(JSON)


class UncertaintyEstimate(Base):
    __tablename__ = "uncertainty_estimates"
    id = Column(Integer, primary_key=True)
    region_id = Column(String(120), index=True); ym = Column(Integer)
    central = Column(Float); lower = Column(Float); upper = Column(Float); relative_width = Column(Float)
    provenance = Column(String(30)); method = Column(String(120))


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id = Column(Integer, primary_key=True)
    kind = Column(String(30)); region_id = Column(String(120)); split = Column(Integer)
    status = Column(String(30)); metrics = Column(JSON); created_at = Column(DateTime, default=now)


class Anomaly(Base):
    __tablename__ = "anomalies"
    id = Column(Integer, primary_key=True)
    region_id = Column(String(120), index=True); name = Column(String(160))
    window_start = Column(Date); window_end = Column(Date)
    current = Column(Float); baseline_median = Column(Float); z = Column(Float); flag = Column(String(12)); factors = Column(JSON)


class Forecast(Base):
    __tablename__ = "forecasts"
    id = Column(Integer, primary_key=True)
    issue_date = Column(Date, index=True); level = Column(String(10), index=True)   # cell | district | state
    region_id = Column(String(120), index=True); cell_id = Column(Integer, index=True)
    probability = Column(Float); p_lower = Column(Float); p_upper = Column(Float); tier = Column(String(12))
    aggregation = Column(String(60)); horizon_days = Column(Integer, default=7); observed = Column(Float)


class ForecastFeature(Base):
    __tablename__ = "forecast_features"
    id = Column(Integer, primary_key=True)
    issue_date = Column(Date, index=True); cell_id = Column(Integer, index=True)
    factor_group = Column(String(60)); contribution_logodds = Column(Float)


class ObservationQuality(Base):
    __tablename__ = "observation_quality"
    id = Column(Integer, primary_key=True)
    region_id = Column(String(120), index=True); satellite = Column(String(20))
    window_start = Column(Date); window_end = Column(Date)
    days_observing = Column(Integer); gap_days = Column(Integer); detections = Column(Integer)
    low_conf_share = Column(Float); mean_pixel_km2 = Column(Float); coverage = Column(Float)


class CriticalRegion(Base):
    __tablename__ = "critical_regions"
    id = Column(Integer, primary_key=True)
    issue_date = Column(Date); region_id = Column(String(120), index=True); name = Column(String(160))
    score = Column(Float); priority = Column(String(12)); land_use = Column(String(40))
    components = Column(JSON); reasons = Column(JSON)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    alert_id = Column(String(24), unique=True, nullable=False)
    alert_type = Column(String(40), index=True, nullable=False)   # PRE_FIRE_RISK_ADVISORY | URGENT_RISK_ESCALATION | UNVERIFIED_SATELLITE_DETECTION
    classification = Column(String(40))                           # Predicted Pre-Fire Risk Advisory | Unverified Satellite Hotspot Detection | Verified Fire Incident
    status = Column(String(40), index=True, default="NEW")
    routing_status = Column(String(50))
    dedupe_key = Column(String(160), index=True)
    region_id = Column(String(120)); region_name = Column(String(200))
    state = Column(String(80), index=True); district_id = Column(String(60)); land_use = Column(String(40), index=True)
    probability = Column(Float); p_lower = Column(Float); p_upper = Column(Float); risk_category = Column(String(12), index=True)
    issue_date = Column(Date, index=True); generated_at = Column(DateTime, default=now); last_evaluated = Column(DateTime, default=now)
    priority = Column(Integer, default=0)
    payload = Column(JSON)
    supersedes = Column(String(24))
    escalations = relationship("AlertEscalation", back_populates="alert", cascade="all, delete-orphan", order_by="AlertEscalation.id")
    recipients = relationship("AlertRecipient", back_populates="alert", cascade="all, delete-orphan")


class AlertEscalation(Base):
    __tablename__ = "alert_escalations"
    id = Column(Integer, primary_key=True)
    alert_pk = Column(Integer, ForeignKey("alerts.id"), index=True, nullable=False)
    action = Column(String(40), nullable=False)
    from_status = Column(String(40)); to_status = Column(String(40))
    actor = Column(String(60)); actor_role = Column(String(40)); note = Column(Text)
    created_at = Column(DateTime, default=now)
    alert = relationship("Alert", back_populates="escalations")


class AlertRecipient(Base):
    __tablename__ = "alert_recipients"
    id = Column(Integer, primary_key=True)
    alert_pk = Column(Integer, ForeignKey("alerts.id"), index=True, nullable=False)
    authority = Column(String(160)); role_title = Column(String(160)); level = Column(Integer, default=1)
    contact_id = Column(Integer, ForeignKey("authority_contacts.id"))
    channel = Column(String(40)); delivery_status = Column(String(50))
    simulated = Column(Boolean, default=True)
    acknowledged_at = Column(DateTime)
    alert = relationship("Alert", back_populates="recipients")


class OperationalSelection(Base):
    """Administrator choice of the operational VIIRS reference (NULL platform = evidence default). History kept."""
    __tablename__ = "operational_selections"
    id = Column(Integer, primary_key=True)
    platform = Column(String(40))
    selected_by = Column(String(60), nullable=False)
    reason = Column(String(500))
    created_at = Column(DateTime, default=now, index=True)


class DataJob(Base):
    """Durable background job (DB-leased queue, see app.jobs). Legacy rows may carry status DONE (= SUCCEEDED)."""
    __tablename__ = "data_jobs"
    id = Column(Integer, primary_key=True)
    kind = Column(String(60), nullable=False, index=True)
    params = Column(JSON)
    status = Column(String(20), nullable=False, default="QUEUED", index=True)   # QUEUED RUNNING RETRYING SUCCEEDED FAILED CANCELLED
    progress = Column(JSON)
    stage = Column(String(120))
    error = Column(Text)
    error_code = Column(String(60))
    result = Column(JSON)
    requested_by = Column(String(60))
    cancel_requested = Column(Boolean, default=False)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    next_run_at = Column(DateTime)
    lease_expires_at = Column(DateTime)
    heartbeat_at = Column(DateTime)
    worker_id = Column(String(120))
    idempotency_key = Column(String(160), index=True)
    created_at = Column(DateTime, default=now, index=True)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)


class NotificationDelivery(Base):
    """Delivery log for every notification attempt (simulated or through a configured provider)."""
    __tablename__ = "notification_deliveries"
    id = Column(Integer, primary_key=True)
    alert_pk = Column(Integer, ForeignKey("alerts.id"), index=True, nullable=False)
    recipient_pk = Column(Integer, ForeignKey("alert_recipients.id"), index=True)
    contact_id = Column(Integer, ForeignKey("authority_contacts.id"))
    provider = Column(String(40))           # simulated | webhook | smtp
    channel = Column(String(40))
    simulated = Column(Boolean, default=True)
    status = Column(String(40), index=True)  # SIMULATED_DELIVERED | SENT | FAILED | BLOCKED_* | SKIPPED_*
    attempts = Column(Integer, default=1)
    error = Column(Text)
    approved_by = Column(String(60))
    created_at = Column(DateTime, default=now, index=True)


class JurisdictionLayer(Base):
    """Administrator-supplied jurisdiction polygons (GeoJSON) that override the land-cover-derived class."""
    __tablename__ = "jurisdiction_layers"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    land_use = Column(String(40), nullable=False)
    source = Column(String(300), nullable=False)       # provenance: dataset name / authority
    licence = Column(String(120))
    source_date = Column(String(40))
    geojson = Column(JSON, nullable=False)
    n_cells = Column(Integer)
    cell_ids = Column(JSON)
    uploaded_by = Column(String(60))
    created_at = Column(DateTime, default=now)


class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    title = Column(String(200)); region_id = Column(String(120)); format = Column(String(8))
    path = Column(String(300)); created_by = Column(String(60)); organisation_id = Column(Integer, ForeignKey("organisations.id"))
    created_at = Column(DateTime, default=now); bytes = Column(Integer)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime, default=now, index=True)
    actor = Column(String(60)); actor_role = Column(String(40)); action = Column(String(60), index=True)
    entity = Column(String(40)); entity_id = Column(String(60)); detail = Column(JSON)


class FireEvent(Base):
    """Space-time fire event delineated from linked active-fire detections (app.events). Footprint = observation footprint."""
    __tablename__ = "fire_events"
    id = Column(Integer, primary_key=True)
    event_id = Column(String(32), unique=True, nullable=False)
    status = Column(String(20), index=True)
    first_detection = Column(DateTime, index=True); last_detection = Column(DateTime, index=True)
    est_start_earliest = Column(DateTime); est_end_latest = Column(DateTime)
    n_obs = Column(Integer, index=True); n_days = Column(Integer)
    platforms = Column(JSON); sensor_families = Column(JSON)
    lat = Column(Float); lon = Column(Float)
    west = Column(Float); south = Column(Float); east = Column(Float); north = Column(Float)
    footprint_km2 = Column(Float); footprint_centres_km2 = Column(Float); footprint_geojson = Column(JSON)
    peak_frp_mw = Column(Float); sum_frp_mw = Column(Float); fre_mj_low = Column(Float); fre_mj_high = Column(Float)
    confidence_mean = Column(Float); confidence_counts = Column(JSON); evidence = Column(String(60))
    multi_sensor_day_share = Column(Float)
    land_use = Column(String(40)); state = Column(String(80), index=True); district_id = Column(String(60))
    day_count = Column(Integer); night_count = Column(Integer)
    gap_days = Column(Float); sensor_days_since_last = Column(Integer); end_basis = Column(Text)
    growth = Column(JSON); timeline = Column(JSON)
    merged_into = Column(String(32)); split_from = Column(String(32)); truncated_start = Column(Boolean, default=False)
    method = Column(String(40)); updated_at = Column(DateTime, default=now)


class FireEventHistory(Base):
    """Identity history of a fire event: CREATED, UPDATED, MERGED (into related), SPLIT (off related)."""
    __tablename__ = "fire_event_history"
    id = Column(Integer, primary_key=True)
    event_id = Column(String(32), index=True, nullable=False)
    action = Column(String(20), nullable=False)
    related_event_id = Column(String(32))
    detail = Column(JSON)
    at = Column(DateTime, default=now)


class ReferenceIncident(Base):
    """Official fire-incident record imported (authorised CSV) for external validation. Never generated by PyroScope."""
    __tablename__ = "reference_incidents"
    id = Column(Integer, primary_key=True)
    incident_id = Column(String(80), nullable=False)
    dataset = Column(String(200), nullable=False, index=True)
    licence = Column(String(200), nullable=False)
    authority = Column(String(200))
    start_date = Column(DateTime, index=True, nullable=False); end_date = Column(DateTime)
    latitude = Column(Float, nullable=False); longitude = Column(Float, nullable=False)
    state = Column(String(80)); district = Column(String(120)); area_ha = Column(Float); incident_type = Column(String(80))
    imported_by = Column(String(60)); imported_at = Column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("dataset", "incident_id"),)


class StorageObject(Base):
    """Registry of files placed in object storage (local or Supabase): bucket, key, SHA-256, size."""
    __tablename__ = "storage_objects"
    id = Column(Integer, primary_key=True)
    bucket = Column(String(63), nullable=False, index=True)
    key = Column(String(500), nullable=False)
    sha256 = Column(String(64)); bytes = Column(Integer); content_type = Column(String(120))
    backend = Column(String(20)); meta = Column(JSON)
    created_by = Column(String(60)); created_at = Column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("bucket", "key"),)


Index("ix_alert_generated", Alert.generated_at)
Index("ix_hotspot_cell_date", HotspotObservation.cell_id, HotspotObservation.acq_date)
Index("ix_forecast_issue_level", Forecast.issue_date, Forecast.level)
Index("ix_alert_key_status", Alert.dedupe_key, Alert.status)
