# Geostationary fusion and diurnal activity (EXPERIMENTAL)

Module: `backend/app/geostationary.py` · API: `/api/geostationary/*` · UI: **Geostationary & Diurnal**

## Provider research (2026-11)

| Provider | India geometry | Resolution / cadence | Archive | Access | Decision |
|---|---|---|---|---|---|
| INSAT-3D / 3DR / 3DS imager fire `3DIMG_L2P_FIR`, `3RIMG_L2P_FIR`, `3SIMG_L2P_FIR` (MOSDAC); smoke `3DIMG_L2P_SMK` | sub-satellite 74–82°E: all India within ~45° | ~4 km MIR; 30 min per satellite (~15 min staggered 3D+3DR) | 3D 2013–, 3DR 2016– | MOSDAC registration; fire product delivered as **KML point placemarks** (MIR/TIR BT algorithm) | BLOCKED BY DATA LICENCE OR ACCESS; authorised KML/CSV import implemented |
| Meteosat IODC SEVIRI FRP-PIXEL (LSA SAF) | 45.5°E: west/central India moderate angles, north-east oblique | 3 km, 15 min | 2017– (listed as *demonstration*) | LSA SAF registration | BLOCKED BY DATA LICENCE OR ACCESS; CSV import implemented; operational status unconfirmed |
| Himawari-8/9 AHI (JAXA) | 140.7°E: view zenith ~55–75° over India | — | — | JAXA P-Tree | NOT USED (geometry) |
| GOES ABI | no view of India | — | — | — | NOT APPLICABLE |
| Fengyun-4 AGRI | not verified | — | — | — | NOT EVALUATED |

Sources: MOSDAC INSAT-3D product list (https://www.mosdac.gov.in/docs/INSAT3D_Products.pdf; 3DR formats identical:
https://www.mosdac.gov.in/node/886); LSA SAF fire products (https://lsa-saf.eumetsat.int/data/products/fire-products/).

No provider is called automatically and nothing is simulated.

## Historical limitation

INSAT records begin in 2013 (3D) and 2016 (3DR). They cannot validate the November 2000 – June 2002 Terra-only
reconstruction. The morning-gap validation stays statistical (20-month Aqua-withheld blocks, see METHODOLOGY.md).

## What runs now

* **Authorised import** (`POST /api/geostationary/import`, admin): CSV (`timestamp_utc, latitude, longitude, platform,
  product` + optional `frp_mw, confidence, pixel_km, view_zenith_deg, quality_flag`) or INSAT KML (KML 2.2 placemarks;
  parser not yet verified on an authentic MOSDAC file). Source and licence are mandatory; view zenith is computed from the
  platform's sub-satellite longitude when absent; nominal pixel size grows with 1/cos(VZA). Native coordinates are kept
  (no reprojection).
* **Diurnal sampling from real polar detections** (local solar time = UTC + lon/15): counts per sensor per hour.
  Polar orbiters observe ~4 fixed local times; the remaining hours are listed as missing. No blended hourly curve is
  produced from polar data (sensor sensitivities differ); the hourly estimate is NOT AVAILABLE until geostationary data
  are imported.
* **Multi-sensor confidence per event**: POLAR_ONLY, POLAR_GEO_AGREE (a geo pixel footprint reaches the event box within
  ±1 h), POLAR_GEO_DISAGREE (geo data cover the area/time but show nothing — weak evidence: coarse pixels miss small fires),
  GEO_ONLY (geo pixels near no event; counted as pixels), NO_CORROBORATION. Without imported data every event is POLAR_ONLY.
