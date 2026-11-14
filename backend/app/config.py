"""Central configuration: paths, grid definition and scientific constants."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
PROCESSED = DATA / "processed"
HOTSPOTS = PROCESSED / "hotspots"
UPLOADS = DATA / "uploads"
AUX = DATA / "auxiliary"
REPORTS = DATA / "reports"
MODELS = PROCESSED / "models"

for _p in (PROCESSED, HOTSPOTS, UPLOADS, AUX, REPORTS, MODELS):
    _p.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(DATA / 'pyroscope.db').as_posix()}")

# ---- spatial grid (global, so uploads outside India still index correctly) ----
GRID_DEG = 0.25
GRID_NX = int(360 / GRID_DEG)
GRID_NY = int(180 / GRID_DEG)

# Study-area bounding box used for auxiliary layers (W, S, E, N).
AOI_BBOX = (68.0, 6.0, 98.0, 36.0)
COUNTRY_ISO = "IND"
COUNTRY_NAME = "India"

# ---- sensors ----
SATELLITES = ["Terra", "Aqua", "Suomi NPP", "NOAA-20", "NOAA-21"]
SAT_INSTRUMENT = {"Terra": "MODIS", "Aqua": "MODIS", "Suomi NPP": "VIIRS", "NOAA-20": "VIIRS", "NOAA-21": "VIIRS"}
SAT_LABEL = {
    "Terra": "Terra MODIS", "Aqua": "Aqua MODIS", "Suomi NPP": "Suomi NPP VIIRS",
    "NOAA-20": "NOAA-20 VIIRS", "NOAA-21": "NOAA-21 VIIRS",
}
# Nominal local equatorial crossing times, hours local solar time.
SAT_NOMINAL_LST = {
    "Terra": {"day": 10.5, "night": 22.5}, "Aqua": {"day": 13.5, "night": 1.5},
    "Suomi NPP": {"day": 13.5, "night": 1.5}, "NOAA-20": {"day": 13.5, "night": 1.5},
    "NOAA-21": {"day": 13.5, "night": 1.5},
}
# The VIIRS reference record that defines the "VIIRS-equivalent" scale.
VIIRS_REFERENCE = "Suomi NPP"

# Confidence standardisation. MODIS reports 0-100; VIIRS reports l/n/h. The FIRMS
# convention bins MODIS as low <30, nominal 30-80, high >80. VIIRS classes are mapped
# to the midpoint of the matching MODIS class. This is an ordinal convention for
# display and filtering -- it is NOT a claim that the two confidences are equivalent.
MODIS_CONF_BINS = (30, 80)
VIIRS_CONF_SCORE = {"l": 0.15, "n": 0.55, "h": 0.90}
CLASS_NAMES = {"l": "low", "n": "nominal", "h": "high"}

# FIRMS `type` attribute (standard-processing files only).
ANOMALY_TYPES = {
    0: "Presumed vegetation fire",
    1: "Active volcano",
    2: "Other static land source (e.g. gas flare, industrial)",
    3: "Offshore detection",
}

# ---- alerting defaults (configurable prototype starting points, not statutory) ----
DEFAULT_TIERS = [
    {"name": "LOW", "min": 0.0, "max": 0.20, "color": "#10b981"},
    {"name": "WATCH", "min": 0.20, "max": 0.40, "color": "#eab308"},
    {"name": "MODERATE", "min": 0.40, "max": 0.60, "color": "#f59e0b"},
    {"name": "HIGH", "min": 0.60, "max": 0.80, "color": "#f97316"},
    {"name": "VERY_HIGH", "min": 0.80, "max": 1.0001, "color": "#dc2626"},
]
DEFAULT_COOLDOWN_HOURS = 72
FORECAST_HORIZON_DAYS = 7

BOOTSTRAP_N = 200
RNG_SEED = 20261114
