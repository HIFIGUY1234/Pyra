"""Central configuration: paths, grid definition and scientific constants."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path):
    """Minimal .env reader (KEY=VALUE, '#' comments). Never overrides variables already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        if k.strip() and v:
            os.environ.setdefault(k.strip(), v)


_load_dotenv(ROOT / ".env")
DATA = ROOT / "data"
PROCESSED = DATA / "processed"
HOTSPOTS = PROCESSED / "hotspots"
UPLOADS = DATA / "uploads"
AUX = DATA / "auxiliary"
REPORTS = Path(os.getenv("PYROSCOPE_REPORTS_DIR", str(DATA / "reports")))
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
# HISTORICAL harmonization reference: the VIIRS record that defines the "VIIRS-equivalent" scale.
# It stays Suomi NPP for reproducibility even though S-NPP data delivery has ended (see PLATFORMS).
VIIRS_REFERENCE = "Suomi NPP"
HISTORICAL_REFERENCE = VIIRS_REFERENCE
# OPERATIONAL reference (live forecasting/monitoring target) is chosen by app.operational from evidence,
# among OPERATIONAL_CANDIDATES; it is never assumed to equal the historical reference.
OPERATIONAL_CANDIDATES = ["NOAA-21", "NOAA-20"]   # NOAA order of preference: NOAA-21 primary, NOAA-20 secondary
# Official platform status (sources: NOAA NESDIS / NASA Earthdata notices, Aug-Oct 2026; FIRMS archive pages).
PLATFORMS = {
    "Terra": {"status": "operational_drifting", "instrument": "MODIS", "firms_start": "2000-11-01",
              "note": "Orbit drifting toward earlier crossing times since ~2022; PyroScope excludes drift years from calibration."},
    "Aqua": {"status": "operational_drifting", "instrument": "MODIS", "firms_start": "2002-07-04",
             "note": "Orbit drifting toward later crossing times since ~2022."},
    "Suomi NPP": {"status": "retired", "instrument": "VIIRS", "firms_start": "2012-01-20", "science_data_end": "2026-11-02",
                  "role": "historical harmonization reference",
                  "source": "NOAA NESDIS notice (Aug 2026) and NASA Earthdata 'Suomi NPP Observations to Cease on November 2, 2026': "
                            "delivery of new S-NPP science data ended 2 Nov 2026; users should transition to NOAA-21 (primary) and NOAA-20 (secondary)."},
    "NOAA-20": {"status": "operational", "instrument": "VIIRS", "firms_start": "2018-04-01", "noaa_role": "secondary successor"},
    "NOAA-21": {"status": "operational", "instrument": "VIIRS", "firms_start": "2024-01-17", "noaa_role": "primary successor",
                "note": "FIRMS records from 2023-03 are pre-operational."},
}

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
