# Population exposure

`backend/app/population.py`, `backend/app/exposure.py`. API: `GET /api/gis/population`, `GET /api/exposure/layers|point|hotspots|regions`.
UI: Critical Regions → *State comparison – exposure, activity and forecast*; Government Dashboard → *People and facilities near recent actual hotspots*.

## Dataset

| Field | Value |
|---|---|
| Dataset | WorldPop Global 2000–2020, 1 km, UN-adjusted population counts, India, **2020** |
| URL | https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/2020/IND/ind_ppp_2020_1km_Aggregated_UNadj.tif |
| Licence | CC BY 4.0 — WorldPop (www.worldpop.org), doi:10.5258/SOTON/WP00671 |
| CRS / resolution | EPSG:4326, 30 arc-second (~0.92 km at the equator) |
| File | 18,313,124 bytes, SHA-256 `27d08e3eabf59f63a2147901c25c046d584c3295f9ceb4c4cf08a902a5bec911` |
| Total in AOI | **1,380,004,385** people (consistent with the UN 2020 India estimate used for the adjustment) |
| Derived | 4,885 cells at 0.25° (1,360 partially covered), 113,736 cells at 0.05° |

Why WorldPop over GHSL and GPW: see [DATA_ACQUISITION.md §7](DATA_ACQUISITION.md#7-population--worldpop-2020-backendapppopulationpy).

## Processing

* The GeoTIFF is read in 256-row windows with rasterio; the whole raster is never held in memory.
* NoData pixels are dropped (not zero). Each valid pixel is assigned by its **centre** to exactly one 0.25° analysis cell
  and one 0.05° fine cell, so nothing is counted twice and the totals are preserved (tested on a synthetic raster:
  `test_population_build_preserves_totals`).
* The raster origin (68.18208° E, 35.50792° N) is **not** on the 30″ lattice (`grid_aligned: false`). Pixel-centre
  assignment avoids double counting; values near a cell edge carry about half a pixel of positional uncertainty.
* Cells partly outside the WorldPop India mask (coast, borders) are flagged `partial`; their totals are lower bounds.
* Reference year 2020 only. Years are not mixed. 2026 population is higher; counts are not projected forward.

## What the exposure numbers mean

* *Population near a hotspot* = sum of fine cells (0.05°) whose centre lies within the radius (5 / 10 / 25 km) of a
  de-duplicated actual detection location (~375 m). Uncertainty at the radius edge is about one fine cell (~5 km).
* *Population in a forecast cell* = people living in that 0.25° cell; paired with the 7-day detection probability.
* These are **proximity counts**. They do not predict that a settlement will burn, that people are affected by smoke,
  or that anyone is in danger. Most Indian detections are agricultural residue burning near villages, so large
  nearby-population counts are expected and normal.
* When the layer is not loaded, every API response and UI panel says **unavailable**; it is never treated as zero and
  never changes a critical-region ranking.

## Refresh

```bash
cd backend && python -m app.population          # download (resumable) + build
python -m app.pipeline --refresh-exposure        # population + infrastructure
```
