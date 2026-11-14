# PyroScope ingestion report
Generated 2026-11-14T17:11:04+00:00 - AOI bbox (68.0, 6.0, 98.0, 36.0)

## Archives

| File | Status | Collection | Size | SHA-256 | Members |
|---|---|---|---|---|---|
| DL_FIRE_J1V-C2_846938.zip | valid (zip_crc_ok) | VIIRS Collection 2 | 94.3 MB | `bf560d9071829726...` | fire_archive_J1V-C2_846938.csv (archive, 410.1 MB), fire_nrt_J1V-C2_846938.csv (nrt, 2.8 MB) |
| DL_FIRE_J2V-C2_846939.zip | valid (zip_crc_ok) | VIIRS Collection 2 | 40.0 MB | `a5916fbb704f9a0f...` | fire_archive_J2V-C2_846939.csv (archive, 171.4 MB), fire_nrt_J2V-C2_846939.csv (nrt, 2.5 MB) |
| DL_FIRE_M-C61_846937.zip | valid (zip_crc_ok) | MODIS Collection 6.1 | 21.8 MB | `abe840b5277297af...` | fire_archive_M-C61_846937.csv (archive, 96.2 MB), fire_nrt_M-C61_846937.csv (nrt, 0.3 MB) |
| DL_FIRE_M-C61_848456.zip | valid (zip_crc_ok) | MODIS Collection 6.1 | 11.9 MB | `3491e9398b7a8629...` | fire_archive_M-C61_848456.csv (archive, 53.2 MB) |
| DL_FIRE_SV-C2_846940.zip | valid (zip_crc_ok) | VIIRS Collection 2 | 159.9 MB | `258cbbf1c4748358...` | fire_archive_SV-C2_846940.csv (archive, 700.3 MB), fire_nrt_SV-C2_846940.csv (nrt, 2.5 MB) |

## Sources (per CSV member)

| Source | Kind | Rows kept | Row versions | Quality | Dropped coords / time | Duplicates removed | Missing FRP / confidence |
|---|---|---|---|---|---|---|---|
| fire_archive_J2V-C2_846939 | archive | 2,135,511 | 2 (pattern) | good | 0 / 0 | 0 | 0 / 0 |
| fire_nrt_J2V-C2_846939 | nrt | 30,498 | 2.0NRT (pattern) | good | 0 / 0 | 0 | 0 / 0 |
| fire_archive_M-C61_846937 | archive | 1,233,985 | 6.03 (undocumented); 61.03 (undocumented) | good | 0 / 0 | 0 | 0 / 0 |
| fire_nrt_M-C61_846937 | nrt | 3,903 | 6.1NRT (documented) | good | 0 / 0 | 0 | 0 / 0 |
| fire_archive_SV-C2_846940 | archive | 8,726,813 | 2 (pattern) | good | 0 / 0 | 0 | 0 / 0 |
| fire_nrt_SV-C2_846940 | nrt | 30,073 | 2.0NRT (pattern) | good | 0 / 0 | 0 | 0 / 0 |
| fire_archive_J1V-C2_846938 | archive | 5,109,832 | 2 (pattern) | good | 0 / 0 | 0 | 0 / 0 |
| fire_nrt_J1V-C2_846938 | nrt | 34,176 | 2.0NRT (pattern) | good | 0 / 0 | 0 | 0 / 0 |
| fire_archive_M-C61_848456 | archive | 683,359 | 6.03 (undocumented) | good | 0 / 0 | 0 | 0 / 0 |

Row `version` strings are kept verbatim. `6.03` / `61.03` (MODIS) are not defined in readable FIRMS documentation; the collection (C6.1) is taken from the archive name per the FIRMS download Readme. NRT rows are provisional and never used for calibration.

## Satellite coverage (loaded vs FIRMS availability)

| Satellite | Status | Archive period | NRT period | Rows | Products | FIRMS starts |
|---|---|---|---|---|---|---|
| Terra | complete_from_firms_start | 2000-11-01 - 2026-08-31 | 2026-09-01 - 2026-10-31 | 595,991 | 1km | 2000-11-01 |
| Aqua | complete_from_firms_start | 2002-07-04 - 2026-08-30 | 2026-09-01 - 2026-10-31 | 1,325,256 | 1km | 2002-07-04 |
| Suomi NPP | complete_from_firms_start | 2012-01-20 - 2026-07-31 | 2026-08-01 - 2026-10-31 | 8,756,886 | 375m | 2012-01-20 |
| NOAA-20 | complete_from_firms_start | 2018-04-01 - 2026-07-31 | 2026-08-01 - 2026-10-31 | 5,144,008 | 375m | 2018-04-01 |
| NOAA-21 | complete_from_firms_start (pre-operational records from 2023-03-01) | 2023-03-01 - 2026-07-31 | 2026-08-01 - 2026-10-31 | 2,166,009 | 375m | 2024-01-17 |

## Missing observation periods (days with no record inside the sensor span; rule from the daily summaries)

| Satellite | Missing days | Periods |
|---|---|---|
| Terra | 63 | 2001-06-15 to 2001-07-03, 2002-03-20 to 2002-03-28, 2003-12-17 to 2003-12-24, 2006-07-10 to 2006-07-14, 2016-02-19 to 2016-02-27, 2022-10-11 to 2022-10-23 |
| Aqua | 27 | 2002-07-28 to 2002-08-07, 2022-04-01 to 2022-04-16 |
| Suomi NPP | 46 | 2022-07-27 to 2022-08-10, 2024-05-30 to 2024-06-03, 2024-07-10 to 2024-07-15, 2024-07-24 to 2024-07-28, 2024-11-03 to 2024-11-05, 2026-03-10 to 2026-03-12, 2026-04-28 to 2026-04-30, 2026-07-11 to 2026-07-16 |
| NOAA-20 | 4 | 2023-07-19 to 2023-07-22 |
| NOAA-21 | 0 | - |

## Missing data


## Scientific capabilities with the loaded data

- terra_only_era_loaded: **True**
- pre_viirs_modis_loaded: **True**
- real_morning_gap_correction: **possible**
- real_2012_seam_test: **possible**
- viirs_750m: **unavailable**
- noaa20: **loaded**

## VIIRS 750 m

- The 750 m product applies the MODIS Collection 6 fire algorithm to VIIRS M-bands and is NASA's continuity product for the MODIS 1 km record.
- FIRMS distributes only the 375 m VIIRS product as CSV; 750 m data are Level-2 NetCDF swath granules from LAADS DAAC / LP DAAC (Earthdata Login required).
- To add: Download VNP14 granules for the AOI from LAADS DAAC, run `python -m app.acquire vnp14 <granule dir> --satellite 'Suomi NPP'` to convert the fire-pixel tables to a FIRMS-like CSV in data/raw/, then rerun the pipeline. It is ingested as product_type=750m and calibrated separately from 375 m.
