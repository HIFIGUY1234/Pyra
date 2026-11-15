# Biomass-burning emissions (ESTIMATED · EXPERIMENTAL · NOT INDEPENDENTLY VALIDATED)

Module: `backend/app/emissions.py` · API: `/api/emissions/*` · UI: **Emissions Estimation** · Job: `emissions`

Not an official emissions inventory.

## Method 1 — FRP/FRE mass balance (implemented, run on authentic events)

    DM [kg]          = FRE [MJ] × CR [kg MJ⁻¹]
    E_species [kg]   = DM [kg] × EF_species [g kg⁻¹] / 1000

| Input | Value | Source |
|---|---|---|
| FRE | per-event bracket `fre_mj_low…fre_mj_high` | time-integrated FIRMS FRP ([FIRE_EVENT_DELINEATION.md](FIRE_EVENT_DELINEATION.md)) |
| CR (combustion factor) | 0.368 ± 0.015 kg MJ⁻¹ | Wooster et al. (2005) JGR 110, D24311 |
| EF (g/kg DM) | GFED4 table (mostly Akagi et al. 2011): PM2.5 AGRI 6.26, SAVA 7.17, DEFO 9.1; CO 102/63/93; CO₂ 1585/1686/1643; CH₄ 5.82/1.94/5.07 | `data/auxiliary/emissions/GFED4_Emission_Factors.txt`, SHA-256 `5f68c5c4…83b2`, downloaded from geo.vu.nl; the code refuses a modified file |
| Biome | cropland → AGRI; forest → SAVA or DEFO (equal probability: Indian forest fires are ambiguous between these classes); other → SAVA; urban → AGRI or SAVA | event dominant land cover |

Units: MW·s = MJ; kg throughout; totals reported in tonnes.

**Uncertainty (Monte Carlo, 1000 draws, seed fixed):** FRE position inside the bracket (log-uniform, systematic across
events), CR (normal), biome choice per event. Per-event low/high = (FRE_low, CR − 2σ, min EF) … (FRE_high, CR + 2σ, max EF).
**Not included:** within-biome EF variability (the GFED table has none), FRP omission of small/cool fires, cloud-obscured
burning, land-cover misclassification beyond the biome choice.

### Authentic result (stored window, India 25–31 Oct 2026, 8,948 events, all with FRP)

| | median (t) | 5th pct | 95th pct |
|---|---|---|---|
| Dry matter | 535,799 | 317,466 | 1,153,218 |
| PM2.5 | 3,485 | 2,062 | 7,489 |
| CO | 50,658 | 30,049 | 108,935 |
| CO₂ | 859,953 | 509,279 | 1,851,247 |
| CH₄ | 2,724 | 1,616 | 5,851 |

The wide interval is dominated by the unobserved-burning bracket (polar snapshots).

## Method 2 — burned area × fuel consumption (implemented, BLOCKED BY EXTERNAL DATA)

    DM = burned area [m²] × fuel consumption [kg DM m⁻²]

Needs processed MCD64A1/VNP64A1 months (blocked by the LAADS licence, see
[BURNED_AREA_METHODOLOGY.md](BURNED_AREA_METHODOLOGY.md)) **and** an authoritative fuel-consumption table
`data/auxiliary/emissions/fuel_consumption.csv` (columns `biome, fc_kg_m2, fc_sd_kg_m2, source`). PyroScope does not invent
fuel loads; without the file the method reports `BLOCKED_BY_EXTERNAL_DATA`. The two methods are never merged; when both
run they are reported side by side.

## Validation

None independent yet. Comparison candidates: GFED4.1s / GFAS / FINN monthly India totals — note GFAS is itself FRP-based
(not independent of method 1).
