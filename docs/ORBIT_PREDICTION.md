# Satellite overpass prediction (SGP4)

`backend/app/orbits.py`. API: `GET /api/orbits/status`, `GET /api/orbits/passes?satellite=&lat=&lon=&hours=`,
`POST /api/orbits/refresh` (admin). UI: Observation Intelligence → *Predicted satellite overpasses (SGP4)*.

## Method

1. **Elements:** current GP/TLE sets from CelesTrak for Terra 25994, Aqua 27424, Suomi NPP 37849, NOAA-20 43013,
   NOAA-21 54234. Line checksums and the catalogue number are verified; each set is cached with its epoch in
   `data/auxiliary/tle/<catnr>.json`. Sets older than 7 days are flagged **stale** in the API and UI.
2. **Propagation:** `sgp4` (Vallado) gives TEME position every 20 s; rotated to Earth-fixed by Greenwich mean sidereal
   time (polar motion and nutation ignored — sub-km effect, far below swath scale).
3. **Visibility:** topocentric elevation of the satellite from the location. A *pass* is an interval when the elevation
   exceeds the elevation of the swath edge, derived from the scan half-angle (MODIS ±55°, VIIRS ±56.28°) and the
   orbit altitude. The closest-approach time and maximum elevation are reported, in UTC and IST.
4. **Meaning:** a predicted pass says the sensor *can observe* the place. It is never a hotspot, and clouds, sun glint
   and the fire's own timing decide whether anything is detected.

## Validation against actual detections

For each satellite, 400 recent NRT FIRMS detections (≤ 30 days old) are taken; for each, the predicted closest approach
nearest the recorded `acq_time` is computed with the current TLE. Residual = recorded − predicted.

| Satellite | TLE epoch (UTC) | n | Oldest detection (days) | Median residual (min) | Mean abs (min) | 95th pct abs (min) | Within 10 min |
|---|---|---|---|---|---|---|---|
| Terra | 2026-11-14T06:19 | 400 | 29.7 | -0.5 | 0.83 | 1.83 | 100.0 % |
| Aqua | 2026-11-14T06:27 | 400 | 29.9 | -0.5 | 0.82 | 1.83 | 100.0 % |
| Suomi NPP | 2026-11-14T06:18 | 400 | 30.0 | -0.5 | 0.9 | 2.0 | 100.0 % |
| NOAA-20 | 2026-11-14T06:38 | 400 | 30.0 | -0.5 | 0.85 | 2.17 | 100.0 % |
| NOAA-21 | 2026-11-14T05:41 | 400 | 30.0 | -0.33 | 0.86 | 1.84 | 100.0 % |

FIRMS `acq_time` has minute resolution and marks the granule/scan time, so sub-minute agreement is not measurable.
Accuracy degrades with TLE age (typically km per day of propagation); refresh at least weekly:
`python -m app.orbits refresh && python -m app.orbits validate` or `python -m app.pipeline --refresh-tle`.

## Limitations

* No terrain, cloud or day/night detectability model. Swath-edge geometry only.
* S-NPP science-data delivery ceased 2026-11-02; its passes are still predicted (it is still in orbit) but no new
  science detections are expected.
* TLEs require network access to CelesTrak; offline, the cached sets are used and marked stale after 7 days.
