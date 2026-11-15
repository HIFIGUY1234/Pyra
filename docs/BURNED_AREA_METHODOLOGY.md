# Burned-area mapping

Module: `backend/app/burned_area.py` · API: `/api/burned-area/*` · UI: **Burned-Area Mapping** · Job: `burned_area`

Status: **BLOCKED BY CREDENTIALS** (code implemented and tested on synthetic HDF4; no authentic month processed).

## Products (verified in NASA CMR, 2026-11-15)

| Product | Version | Concept | Sensor | Grid | Archive | Format |
|---|---|---|---|---|---|---|
| MCD64A1 | 061 | C2565786756-LPCLOUD | Terra+Aqua MODIS | 500 m sinusoidal, monthly | 2000-11 → | HDF4-EOS |
| VNP64A1 | 002 | C2847928673-LPCLOUD | Suomi NPP VIIRS | 500 m sinusoidal, monthly | 2012-03 → | `.hdf` (read as HDF4 or HDF5 by signature) |

For November 2024 CMR lists 16 MCD64A1 and 32 VNP64A1 granules over the India AOI. These are burn-scar products, not
active-fire hotspots.

## Access test (authentic)

* EARTHDATA_TOKEN is present and valid (user token, expires 2027-01-13).
* LP DAAC cloud (`data.lpdaac.earthdatacloud.nasa.gov`) redirects the bearer request to Earthdata OAuth → the account has
  not authorised the LP DAAC application.
* LAADS DAAC accepts the token for listings (`/archive/allData/61/MCD64A1/2024/306.json` works) but file downloads
  redirect to `/profiles/licenses/...` → the account has not accepted the LAADS data licence.

Unblock: sign in once at https://ladsweb.modaps.eosdis.nasa.gov and accept the licence; in Earthdata Login →
Applications → Authorized Apps approve "LP DAAC Data Pool" / LP DAAC cloud. Then queue `burned_area` (year, month).
The client reports this exact blocker (`BLOCKED_BY_CREDENTIALS: ... accept the data licence`).

## Processing

1. LAADS listing for the first day-of-year of the month; India tiles computed from the AOI (h23–h28, v05–v08 range).
2. Resumable download (`Range` on `.part`), signature check (HDF4 `0e031301` / HDF5), SHA-256 manifest.
3. Read `Burn Date`, `Burn Date Uncertainty`, `QA` (pyhdf for HDF4, h5py for HDF5).
4. Geolocate pixels with the MODIS sinusoidal equations (R = 6 371 007.181 m, tile 1 111 950.52 m, 2400 px).
5. Burn Date coding: 1–366 burned (day of year), 0 unburned, −1 unmapped, −2 water. **Unmapped and water are never
   counted as unburned**; burned, mapped (burned+unburned) and unmapped area are reported separately.
6. Area: the sinusoidal grid is equal-area → every pixel is 463.3127² m² = 0.21466 km² (no reprojection needed for area).
7. Outputs per month: burned pixels (lat, lon, burn date, uncertainty, QA) Parquet; 0.25° cell totals; manifest JSON.

## Event association (corroboration, not validation)

For each fire event, burned pixels within the event box + 1 km with burn date in [first − 16 d, last + 16 d] count as a
matching scar. Reported: event-scar rate, share of burned area with an event, omission/commission proxies. MCD64A1 uses
MODIS active fires to guide its mapping, so this is **not independent** of the hotspots.

## Limitations

500 m pixels miss many small/short crop burns; the product's documented omission is not corrected; burn dates carry
per-pixel uncertainty (reported, not propagated into totals).
