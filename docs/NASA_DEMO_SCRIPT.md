# PyroScope — 6-minute demonstration script

Numbers come from `docs/SCIENTIFIC_VALIDATION.md` (generated 2026-11-14 from the loaded archives).
If you regenerate the report, re-read the numbers before presenting.

**Setup (before the demo):** `uvicorn app.main:app --port 8000` and `npm run dev`. Open
http://localhost:5173 and leave the area picker on *Country (India)*. Open `/validation` once so the
calibration cache is warm; the first fit takes about 4 s.

| Time | Screen | Say / show |
|---|---|---|
| 0:00 | **Overview Dashboard** (`/`) | "Twenty-six years of satellite fire records over India, from five satellites and two instrument families. MODIS and VIIRS see fire differently, so the raw record jumps sevenfold in 2012. PyroScope removes that artificial jump and keeps the real changes." |
| 0:30 | **Data Management** (`/data`) → inventory card | Five FIRMS archives, all *valid (zip crc ok)*, each with its SHA-256. Terra from 2000-11-01, Aqua from 2002-07-04, S-NPP from 2012-01-20, NOAA-20 from 2018-04-01. NOAA-21 is flagged *pre-operational records from 2023-03-01* (official start 2024-01-17). MODIS row versions `6.03` / `61.03` are flagged *undocumented*: "we keep them verbatim rather than guess". NRT rows are marked provisional. |
| 1:15 | **Morning-Gap Fixer** (`/morning-gap`) | Real Terra-only months, Nov 2000 – Jun 2002 (19 months), shown as **estimates** with bands. "No Aqua existed yet, so there is no ground truth. We test the method by hiding 20-month blocks of real Aqua: WAPE 18.4 %, bias +3.7 %, R² 0.92, against 45 % for a constant ratio. The band covers 91 % of hidden months, close to its 90 % target." |
| 2:00 | Same page → honesty point | "Trained only on *later* years, which is the real 2000–02 situation, the model runs about 12 % high, and five model forms disagree by 9 % on the 2000–02 total. Both numbers are on screen; we report them, we don't hide them." |
| 2:30 | **MODIS–VIIRS Harmonizer** (`/harmonization`) | A continuous VIIRS-equivalent record from 2000-11 to 2026-10, coloured by provenance: actual VIIRS (unchanged), sensor-calibrated, morning-gap + sensor. NOAA-20 stays a separate actual stream and is never pooled. |
| 3:00 | **Validation & Seam Test** (`/validation`) | Actual hold-out: trained on 2017–22, tested on real VIIRS 2012–16. WAPE **13.0 %** vs constant ratio 32.0 % and raw MODIS 85.1 %; bias −0.3 %; R² 0.96. |
| 3:40 | Same page → seam panel | Real seam, Feb 2012. Raw step ×6.98 → harmonized ×1.03. Artificial jump cut by **96 %**. "The target is not 1.0. It is the change seen by unchanged Aqua: +10 %. Our harmonized step is +3 %, so we damp part of a real change. Verdict: **PARTIAL**, by our own declared rule." Scroll: ±36 months **passes**; 5 of 8 states pass. |
| 4:20 | Same page → model-selection panel | "Every model form was compared on held-out years: leave-one-year-out, 20-month blocks, forward and backward. The simpler candidates did not beat the default, so it stayed." Switch the tab to Aqua → VIIRS. |
| 4:45 | **Burning Activity Calendar** (`/calendar`) → area *State: Punjab* | Daily calendar. Missing days are hatched, never shown as zero. Toggle detections / FRP and sensor / VIIRS-equivalent. |
| 5:10 | **Regional Fire Forecast** (`/forecast`) | Seven-day probability of a *detectable satellite hotspot*, not an ignition. Test 2024–26: ROC-AUC 0.92, Brier 0.097 vs 0.107 climatology. Regional probability uses a fitted dependence correction, not an average. |
| 5:25 | Same page → *Forecast model comparison* | "Five models, same rows, same split. XGBoost and gradient boosting tie; nothing beat our declared rule, so we kept XGBoost." |
| 5:35 | **Government Dashboard** (`/government`) → exposure panel → **Alerts & Escalation** | People and facilities near recent actual hotspots (WorldPop 2020, OpenStreetMap): "proximity, not harm". Advisory lifecycle: acknowledge → approve → notification log. "Delivery is simulated here, and real delivery only ever goes to verified contacts after a human approves." |
| 5:50 | **Observation Intelligence** (`/observations`) | SGP4 overpass prediction for the selected place: "checked against 400 real detections per satellite, under a minute off on average". |
| 5:55 | **Reports & Exports** (`/reports`) | Generate the PDF and CSV; provenance and bands are in every row. |

**If asked about VIIRS 750 m:** search, download and conversion are implemented for VNP14/VJ114/VJ214 v002. Download needs an Earthdata login that this deployment does not have, so the panel says *unavailable* and nothing is claimed.
**If asked about NOAA-21:** four ways to convert it to S-NPP-equivalent were tested on the operational period; none beat "leave it unchanged" under the declared rule, so it stays separate.
**If asked about exposure:** WorldPop 2020 (1.38 billion people in the AOI) and 11 OSM facility categories. Roads, rail and power lines are not loaded and are shown as missing.
