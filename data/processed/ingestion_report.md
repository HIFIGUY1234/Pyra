# PyroScope ingestion report
Generated 2026-11-14T14:50:59+00:00 - AOI bbox (68.0, 6.0, 98.0, 36.0)

## Archives

| File | Status | Members |
|---|---|---|
| DL_FIRE_J1V-C2_846938.zip | valid | fire_archive_J1V-C2_846938.csv (archive, 410.1 MB), fire_nrt_J1V-C2_846938.csv (nrt, 2.8 MB) |
| DL_FIRE_J2V-C2_846939.zip | valid | fire_archive_J2V-C2_846939.csv (archive, 171.4 MB), fire_nrt_J2V-C2_846939.csv (nrt, 2.5 MB) |
| DL_FIRE_M-C61_846937.zip | valid | fire_archive_M-C61_846937.csv (archive, 96.2 MB), fire_nrt_M-C61_846937.csv (nrt, 0.3 MB) |
| DL_FIRE_SV-C2_846940.zip | valid | fire_archive_SV-C2_846940.csv (archive, 700.3 MB), fire_nrt_SV-C2_846940.csv (nrt, 2.5 MB) |

## Satellite coverage (loaded vs FIRMS availability)

| Satellite | Status | Archive period | NRT period | Rows | Products | FIRMS starts |
|---|---|---|---|---|---|---|
| Terra | partial | 2012-01-01 - 2026-08-31 | 2026-09-01 - 2026-10-31 | 383,418 | 1km | 2000-11-01 |
| Aqua | partial | 2012-01-01 - 2026-08-30 | 2026-09-01 - 2026-10-31 | 854,470 | 1km | 2002-07-04 |
| Suomi NPP | complete_from_firms_start | 2012-01-20 - 2026-07-31 | 2026-08-01 - 2026-10-31 | 8,756,886 | 375m | 2012-01-20 |
| NOAA-20 | complete_from_firms_start | 2018-04-01 - 2026-07-31 | 2026-08-01 - 2026-10-31 | 5,144,008 | 375m | 2018-04-01 |
| NOAA-21 | complete_from_firms_start | 2023-03-01 - 2026-07-31 | 2026-08-01 - 2026-10-31 | 2,166,009 | 375m | 2024-01-17 |

## Missing data

- **Terra** 2000-11-01 to 2011-12-31: FIRMS Archive Download (MODIS C6.1 / VIIRS C2, CSV, AOI (68.0, 6.0, 98.0, 36.0)) or `python -m app.acquire firms MODIS_SP 2000-11-01 2012-01-01`
- **Aqua** 2002-07-04 to 2011-12-31: FIRMS Archive Download (MODIS C6.1 / VIIRS C2, CSV, AOI (68.0, 6.0, 98.0, 36.0)) or `python -m app.acquire firms MODIS_SP 2002-07-04 2012-01-01`

## Scientific capabilities with the loaded data

- terra_only_era_loaded: **False**
- pre_viirs_modis_loaded: **False**
- real_morning_gap_correction: **blocked: no Terra-only (Nov 2000 - Jun 2002) records loaded**
- real_2012_seam_test: **blocked: fewer than 12 months of MODIS records precede the first VIIRS record**
- viirs_750m: **unavailable**
- noaa20: **loaded**

## VIIRS 750 m

- The 750 m product applies the MODIS Collection 6 fire algorithm to VIIRS M-bands and is NASA's continuity product for the MODIS 1 km record.
- FIRMS distributes only the 375 m VIIRS product as CSV; 750 m data are Level-2 NetCDF swath granules from LAADS DAAC / LP DAAC (Earthdata Login required).
- To add: Download VNP14 granules for the AOI from LAADS DAAC, run `python -m app.acquire vnp14 <granule dir> --satellite 'Suomi NPP'` to convert the fire-pixel tables to a FIRMS-like CSV in data/raw/, then rerun the pipeline. It is ingested as product_type=750m and calibrated separately from 375 m.
