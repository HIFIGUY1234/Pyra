# Graph Report - Nasa Hack  (2026-11-14)

## Corpus Check
- Corpus is ~43,500 words - fits in a single context window. You may not need a graph.

## Summary
- 668 nodes · 1763 edges · 42 communities (26 shown, 16 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 46 edges (avg confidence: 0.85)
- Token cost: 209,564 input · 0 output

## Community Hubs (Navigation)
- FastAPI Routes (main.py)
- React App Pages
- PDF Report Concepts
- MODIS-VIIRS Harmonization
- Database ORM Models
- Geography & Land Use
- Alert Engine
- Data Store & Summaries
- Fire Probability Forecast
- Frontend Dev Dependencies
- FIRMS Ingestion
- TS App Config
- Validation & Seam Test
- API Test Suite
- TS Node Config
- Critical Regions & Splits
- Analytics & Anomalies
- Regional Risk Aggregation
- Pipeline, DB Sync, Weather
- Frontend Runtime Deps
- Report Generation
- ESLint Setup
- Leaflet Map Components
- GIBS Land Cover Image
- API Error Handlers
- Cell Table Builder
- Vite Build Config
- NPM Scripts
- Year-Month Helpers
- Hotspot Query
- TS Root Config
- Vite Logo
- Data Stack Deps
- Web Stack Deps
- Test Deps
- SQLAlchemy/PostGIS Deps

## God Nodes (most connected - your core abstractions)
1. `ok()` - 52 edges
2. `sync_all()` - 31 edges
3. `series()` - 24 edges
4. `cells()` - 24 edges
5. `Actor` - 22 edges
6. `evaluate()` - 20 edges
7. `fit()` - 20 edges
8. `region_forecast()` - 18 edges
9. `region_label()` - 18 edges
10. `ThresholdConfigurationPage()` - 18 edges

## Surprising Connections (you probably didn't know these)
- `reportlab + pillow PDF reporting` --conceptually_related_to--> `PyroScope report - Goa (08:51 UTC, no alerts)`  [INFERRED]
  backend/requirements.txt → data/reports/pyroscope_Goa_full_20261114T085143Z.pdf
- `Sensors: Terra/Aqua MODIS, S-NPP VIIRS, NOAA-21 VIIRS (375 m)` --shares_data_with--> `DL_FIRE_M-C61_846937.zip (MODIS C6.1 Terra/Aqua)`  [INFERRED]
  data/reports/pyroscope_Goa_full_20261114T085143Z.pdf → README.md
- `Sensors: Terra/Aqua MODIS, S-NPP VIIRS, NOAA-21 VIIRS (375 m)` --shares_data_with--> `DL_FIRE_J2V-C2_846939.zip (VIIRS NOAA-21 C2)`  [INFERRED]
  data/reports/pyroscope_Goa_full_20261114T085143Z.pdf → README.md
- `Sensors: Terra/Aqua MODIS, S-NPP VIIRS, NOAA-21 VIIRS (375 m)` --shares_data_with--> `DL_FIRE_SV-C2_846940.zip (VIIRS Suomi NPP C2)`  [INFERRED]
  data/reports/pyroscope_Goa_full_20261114T085143Z.pdf → README.md
- `scikit-learn / xgboost ML stack` --conceptually_related_to--> `Seven-day calibrated hotspot probability (VERY_HIGH, 93%)`  [INFERRED]
  backend/requirements.txt → data/reports/pyroscope_Goa_full_20261114T085143Z.pdf

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **MODIS-to-VIIRS harmonization and validation pipeline** — data_reports_pyroscope_goa_full_20261114t085143z_morning_gap_correction, data_reports_pyroscope_goa_full_20261114t085143z_sensor_calibration_model, data_reports_pyroscope_goa_full_20261114t085143z_modis_orbit_drift, data_reports_pyroscope_goa_full_20261114t085143z_held_out_validation, data_reports_pyroscope_goa_full_20261114t085143z_seam_test, data_reports_pyroscope_goa_full_20261114t085143z_harmonized_viirs_equivalent [EXTRACTED 1.00]
- **Forecast to authority alert routing flow** — data_reports_pyroscope_goa_full_20261114t085143z_seven_day_hotspot_probability, data_reports_pyroscope_goa_full_20261114t085143z_risk_tiers, data_reports_pyroscope_goa_full_20261114t085143z_land_use_jurisdiction, data_reports_pyroscope_goa_full_20261114t085143z_authority_alert_routing [INFERRED 0.85]
- **NASA FIRMS source archives feeding PyroScope** — readme_dl_fire_m_c61_846937, readme_dl_fire_j2v_c2_846939, readme_dl_fire_sv_c2_846940, readme_nasa_firms [EXTRACTED 1.00]
- **Land cover classes shown in GIBS LC map** — data_auxiliary_gibs_lc_croplands, data_auxiliary_gibs_lc_forests, data_auxiliary_gibs_lc_urban_built_up, data_auxiliary_gibs_lc_barren_snow, data_auxiliary_gibs_lc_water_wetlands [INFERRED 0.85]

## Communities (42 total, 16 thin omitted)

### Community 0 - "FastAPI Routes (main.py)"
Cohesion: 0.05
Nodes (75): _action(), handler(), ActionBody, actor(), Actor, alert_get(), alerts_evaluate(), alerts_list() (+67 more)

### Community 1 - "React App Pages"
Cohesion: 0.07
Nodes (77): ALERT_TYPE_STYLE, AlertsTablePage(), App(), ArgonShell(), CriticalRegionsPage(), DataManagementPage(), DataQualityReportPage(), OverviewDashboardPage() (+69 more)

### Community 2 - "PDF Report Concepts"
Cohesion: 0.08
Nodes (29): scikit-learn / xgboost ML stack, reportlab + pillow PDF reporting, shapely geometry, Authority alert routing and acknowledgement log, Held-out validation (WAPE/bias, status POOR), Land-use jurisdiction (MCD12Q1 IGBP majority rule, 0.25 deg cells), Observation quality / coverage score, PyroScope report - Goa (08:51 UTC, no alerts) (+21 more)

### Community 3 - "MODIS-VIIRS Harmonization"
Cohesion: 0.13
Nodes (18): _boot_weights(), calibration_table(), _draw(), fit(), Fit, fit_pair(), _loyo(), metrics() (+10 more)

### Community 4 - "Database ORM Models"
Cohesion: 0.11
Nodes (27): Alert, AlertEscalation, AlertRecipient, Anomaly, AuditLog, AuthorityContact, CriticalRegion, DailyFireActivity (+19 more)

### Community 5 - "Geography & Land Use"
Cohesion: 0.10
Nodes (12): classify_land_use(), district_geojson(), district_geometries(), _download(), _landcover_fractions(), _load_features(), cell_area_km2(), cell_bounds() (+4 more)

### Community 6 - "Alert Engine"
Cohesion: 0.14
Nodes (18): act(), _aid(), _audit(), _cfg_dict(), _detection_alerts(), evaluate(), cfg_for(), evidence() (+10 more)

### Community 7 - "Data Store & Summaries"
Cohesion: 0.20
Nodes (16): regional_comparison(), _lst_hist(), build_orbit_table(), build_summaries(), cell_static(), clear_caches(), coverage(), daily() (+8 more)

### Community 8 - "Fire Probability Forecast"
Cohesion: 0.16
Nodes (12): build_dataset(), wfeat(), cells_fc(), clear(), _clf_metrics(), contribs(), _dense(), explain() (+4 more)

### Community 9 - "Frontend Dev Dependencies"
Cohesion: 0.13
Nodes (21): devDependencies, autoprefixer@^10.6.2, eslint@^9.13.0, postcss@^8.5.33, tailwindcss@^3.4.19, @types/leaflet@^1.9.22, @types/react@^18.3.12, @types/react-dom@^18.3.1 (+13 more)

### Community 10 - "FIRMS Ingestion"
Cohesion: 0.18
Nodes (9): aggregate_daily(), discover_sources(), load_registry(), _open_source(), process_all(), process_source(), regroup_daily(), _save_registry() (+1 more)

### Community 11 - "TS App Config"
Cohesion: 0.10
Nodes (19): compilerOptions, allowImportingTsExtensions, isolatedModules, jsx, lib, module, moduleDetection, moduleResolution (+11 more)

### Community 12 - "Validation & Seam Test"
Cohesion: 0.18
Nodes (14): dashboard_summary(), data_end(), observation_quality(), _records(), seam_test(), status_of(), validation(), main() (+6 more)

### Community 14 - "TS Node Config"
Cohesion: 0.11
Nodes (17): compilerOptions, allowImportingTsExtensions, isolatedModules, lib, module, moduleDetection, moduleResolution, noEmit (+9 more)

### Community 15 - "Critical Regions & Splits"
Cohesion: 0.22
Nodes (12): critical_regions(), observation_cells(), _replace(), sync_all(), available(), meta(), clear(), default_split() (+4 more)

### Community 16 - "Analytics & Anomalies"
Cohesion: 0.25
Nodes (9): anomalies_now(), anomaly_series(), calendar(), clear(), _lin_trend(), overpasses(), _rec(), _robust_z() (+1 more)

### Community 17 - "Regional Risk Aggregation"
Cohesion: 0.25
Nodes (8): _f(), aggregate_region(), cell_detail(), _cells(), grid_cells(), ranking(), region_forecast(), region_cells()

### Community 18 - "Pipeline, DB Sync, Weather"
Cohesion: 0.20
Nodes (3): init_db(), _fetch(), node_center()

### Community 19 - "Frontend Runtime Deps"
Cohesion: 0.17
Nodes (12): dependencies, leaflet@^1.9.4, lucide-react@^1.73.0, react@^18.3.1, react-dom@^18.3.1, react-leaflet@^4.2.1, react-router-dom@^6.30.6, recharts@^3.10.1 (+4 more)

### Community 20 - "Report Generation"
Cohesion: 0.27
Nodes (5): _csv(), _fmt(), generate(), _pdf(), _slug()

### Community 21 - "ESLint Setup"
Cohesion: 0.18
Nodes (10): @eslint/js@^9.13.0, eslint-plugin-react-hooks@^5.0.0, eslint-plugin-react-refresh@^0.4.14, globals@^15.11.0, typescript-eslint@^8.11.0, @eslint/js, eslint-plugin-react-hooks, eslint-plugin-react-refresh (+2 more)

### Community 22 - "Leaflet Map Components"
Cohesion: 0.22
Nodes (5): BaseMap(), canvas, FitBounds(), mapRenderer, useStates()

### Community 23 - "GIBS Land Cover Image"
Cohesion: 0.22
Nodes (9): Barren / Snow and Ice classes, Croplands class, Forest classes, GIBS Land Cover Map (South Asia), MODIS Land Cover Type (IGBP classification), NASA GIBS, South Asia / Indian Subcontinent, Urban and Built-up class (+1 more)

### Community 24 - "API Error Handlers"
Cohesion: 0.32
Nodes (3): _bad(), _conflict(), _missing()

### Community 26 - "Vite Build Config"
Cohesion: 0.40
Nodes (4): vite@^5.4.10, @vitejs/plugin-react@^4.3.3, vite, @vitejs/plugin-react

### Community 27 - "NPM Scripts"
Cohesion: 0.40
Nodes (5): scripts, build, dev, lint, preview

## Ambiguous Edges - Review These
- `GIBS Land Cover Map (South Asia)` → `MODIS Land Cover Type (IGBP classification)`  [AMBIGUOUS]
  data/auxiliary/gibs/lc.png · relation: implements

## Knowledge Gaps
- **25 isolated node(s):** `fire_archive vs fire_nrt CSV detections`, `FastAPI + Uvicorn web stack`, `pandas / numpy / pyarrow data stack`, `scikit-learn / xgboost ML stack`, `SQLAlchemy (optional PostgreSQL/PostGIS via DATABASE_URL)` (+20 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 228 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `react` connect `React App Pages` to `Frontend Dev Dependencies`, `Frontend Runtime Deps`, `Leaflet Map Components`?**
  _High betweenness centrality (0.011) - this node is a cross-community bridge._
- **What connects `fire_archive vs fire_nrt CSV detections`, `FastAPI + Uvicorn web stack`, `pandas / numpy / pyarrow data stack` to the rest of the system?**
  _25 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `FastAPI Routes (main.py)` be split into smaller, more focused modules?**
  _Cohesion score 0.05369415807560137 - nodes in this community are weakly interconnected._
- **Why does `sync_all()` connect `Critical Regions & Splits` to `FastAPI Routes (main.py)`, `MODIS-VIIRS Harmonization`, `Alert Engine`, `Data Store & Summaries`, `Fire Probability Forecast`, `FIRMS Ingestion`, `Validation & Seam Test`, `Analytics & Anomalies`, `Regional Risk Aggregation`, `Pipeline, DB Sync, Weather`, `Year-Month Helpers`, `Hotspot Query`?**
  _High betweenness centrality (0.007) - this node is a cross-community bridge._
- **Should `React App Pages` be split into smaller, more focused modules?**
  _Cohesion score 0.06541822721598002 - nodes in this community are weakly interconnected._
- **Why does `build_cells()` connect `Cell Table Builder` to `MODIS-VIIRS Harmonization`, `Geography & Land Use`, `Data Store & Summaries`, `Fire Probability Forecast`, `Validation & Seam Test`, `Critical Regions & Splits`?**
  _High betweenness centrality (0.007) - this node is a cross-community bridge._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `GIBS Land Cover Map (South Asia)` and `MODIS Land Cover Type (IGBP classification)`?**
  _Edge tagged AMBIGUOUS (relation: implements) - confidence is low._