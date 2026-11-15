# Smoke transport and PM2.5

Module: `backend/app/smoke.py` · API: `/api/smoke/*` · UI: **Smoke Transport** · Job: `smoke_trajectories`

| Capability | Status |
|---|---|
| Forward smoke trajectories (kinematic fallback) | IMPLEMENTED BUT NOT FULLY VALIDATED (EXPERIMENTAL) — ran on authentic GFS winds |
| HYSPLIT dispersion | NOT IMPLEMENTED (not installed in this environment; no adapter is faked) |
| PM2.5 concentration forecast | NOT IMPLEMENTED (trajectories carry no mass) |
| PM2.5 validation vs ground monitors | BLOCKED BY CREDENTIALS (CPCB / data.gov.in or OpenAQ v3 API key) |
| People near the modelled smoke path | IMPLEMENTED (WorldPop 2020, no double counting) |

This is separate from the 7-day hotspot-probability forecast. Outputs are model results, **not official health warnings**.

## HYSPLIT review

NOAA ARL HYSPLIT (https://www.arl.noaa.gov/hysplit/) needs ARL-format meteorology (GDAS/GFS 0.25° ARL files), an
emission rate and release height per source, particle/puff configuration, deposition settings and a CONTROL/SETUP pair;
outputs concentration grids (cdump) and trajectories (tdump). It is distributed for Linux/Windows/macOS under NOAA terms
(registration for some builds). It is not installed here, so PyroScope uses the fallback below and labels every output
"not HYSPLIT". Integration point: `smoke.run()` is the job entry; a HYSPLIT runner would replace `trajectory()` and add
concentration output.

## Fallback trajectory model

* Sources: burning fire events (ACTIVE / DETECTED / POSSIBLY_INACTIVE / UNVERIFIED), ranked by FRE bracket, or explicit IDs.
* Meteorology: NCEP GFS 0.25° hourly via the Open-Meteo GFS API (no key), sampled every 1° (Open-Meteo counts each location
  as one call; free tier 600/min; 429 responses wait and retry). Variables: 10 m and 850 hPa wind, boundary-layer height.
* Injection height: unknown (no plume-rise model). PyroScope does **not** invent one: every source is run at two
  bracketing levels — 10 m (surface layer) and 850 hPa (~1.5 km, lofted). GFS boundary-layer height is reported along the path.
* Integration: Heun (RK2), 15-min steps, bilinear space, linear time; trajectories leaving the grid stop and are flagged
  incomplete (no extrapolation).
* Exposure: WorldPop 0.05° cells within 25 km of any trajectory point, each cell counted once, earliest arrival time; bands
  ≤6/12/24/48 h.

## Authentic run (example stored in `data/processed/smoke/`)

Run `SM-2026103121-…`: 10 burning events (since 30 Oct 2026), 48 h from 2026-10-31 21:00 UTC, 20 trajectories, 6.7 s.
People living within 25 km of the modelled path: 16.2 M (10 m level) / 24.2 M (850 hPa) within 48 h. These are people near
a **path**, not people exposed to a concentration.

Because the start time is in the past, the winds are archived GFS output (a hindcast), not a live forecast.

## Required for PM2.5

1. A dispersion model (HYSPLIT or equivalent) with ARL meteorology.
2. Emission rates per source (from `emissions.py`, FRP method) and a plume-rise scheme or measured injection heights.
3. Independent ground PM2.5 (CPCB CAAQMS via data.gov.in, or OpenAQ) with separate training/testing periods.
