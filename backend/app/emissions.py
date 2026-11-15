"""Biomass-burning emission ESTIMATES (EXPERIMENTAL, NOT INDEPENDENTLY VALIDATED, not an official inventory).

Two mass-balance methods are kept separate and never merged:

1. FRP/FRE method (implemented, runs on PyroScope fire events)
       dry matter DM [kg]      = FRE [MJ] x combustion factor CR [kg MJ^-1]
       emission_species [kg]  = DM [kg] x EF_species [g kg^-1] / 1000
   * FRE per event is bracketed (fire_events.fre_mj_low / fre_mj_high): polar orbiters miss unobserved burning, so
     each isolated overpass is credited 0.5 h (low) to 6 h (high) per side. Draws are log-uniform inside the bracket.
   * CR = 0.368 +/- 0.015 kg MJ^-1 (Wooster et al. 2005, J. Geophys. Res. 110, D24311, laboratory biomass burns).
   * EF from the GFED4 emission-factor table (g species per kg DM, mostly Akagi et al. 2011), stored with its
     SHA-256 in data/auxiliary/emissions. Biome class from the event's dominant land cover; forest fires in India
     are ambiguous between the SAVA and DEFO classes, so draws pick either with equal probability.
   * Uncertainty: Monte Carlo over the FRE bracket (systematic, shared by all events in a draw), CR (normal) and the
     biome mapping. Within-class EF variability is NOT quantified by the GFED table and is therefore not included.

2. Burned-area method (implemented, needs inputs that are not available yet)
       DM = burned area [m^2] x fuel consumption [kg DM m^-2]
   Requires processed MCD64A1/VNP64A1 months AND an authoritative fuel-consumption table
   (data/auxiliary/emissions/fuel_consumption.csv with columns biome, fc_kg_m2, fc_sd_kg_m2, source). PyroScope does
   not invent fuel loads: without that file the method reports BLOCKED_BY_EXTERNAL_DATA.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select

from . import models as M
from .config import AUX, PROCESSED, RNG_SEED

EF_FILE = AUX / "emissions" / "GFED4_Emission_Factors.txt"
EF_URL = "https://www.geo.vu.nl/~gwerf/GFED/GFED4/ancill/GFED4_Emission_Factors.txt"
EF_SHA256 = "5f68c5c4ffdb7d81d3d2fefa662dcad9dd66f2b4097350a08a045523626383b2"
FUEL_FILE = AUX / "emissions" / "fuel_consumption.csv"
OUT = PROCESSED / "emissions"
SPECIES = ("PM2.5", "CO", "CO2", "CH4")
CR_MEAN, CR_SD = 0.368, 0.015       # kg MJ-1, Wooster et al. (2005)
BIOMES = {"Agricultural": ("AGRI",), "Forest": ("SAVA", "DEFO"), "Other": ("SAVA",), "Municipal/Urban": ("AGRI", "SAVA")}
DEFAULT_BIOMES = ("SAVA", "AGRI")
LABEL = "ESTIMATED - EXPERIMENTAL - NOT INDEPENDENTLY VALIDATED - not an official emissions inventory"


def emission_factors() -> pd.DataFrame:
    """GFED4 EF table (rows species, columns SAVA BORF TEMF DEFO PEAT AGRI; g per kg DM). Checksum-verified."""
    if not EF_FILE.exists():
        raise FileNotFoundError(f"BLOCKED_BY_EXTERNAL_DATA: {EF_FILE.name} missing (download from {EF_URL})")
    raw = EF_FILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EF_SHA256:
        raise ValueError("emission-factor table checksum mismatch: refusing to use a modified file")
    rows = {}
    cols = None
    for line in raw.decode().splitlines():
        if line.startswith("# SPECIE"):
            cols = line[1:].split()[1:]
        elif line.strip() and not line.startswith("#") and cols:
            parts = line.split()
            if len(parts) == len(cols) + 1:
                rows[parts[0]] = [float(x) for x in parts[1:]]
    return pd.DataFrame(rows, index=cols).T


def _biome_choices(land_use: str | None) -> tuple:
    return BIOMES.get(land_use, DEFAULT_BIOMES)


def _events(start=None, end=None) -> pd.DataFrame:
    q = select(M.FireEvent.event_id, M.FireEvent.first_detection, M.FireEvent.last_detection, M.FireEvent.state,
               M.FireEvent.district_id, M.FireEvent.land_use, M.FireEvent.fre_mj_low, M.FireEvent.fre_mj_high, M.FireEvent.n_obs,
               M.FireEvent.status).where(M.FireEvent.status != "MERGED")
    if start:
        q = q.where(M.FireEvent.last_detection >= pd.Timestamp(start).to_pydatetime())
    if end:
        q = q.where(M.FireEvent.first_detection < (pd.Timestamp(end) + pd.Timedelta(days=1)).to_pydatetime())
    with M.Session() as s:
        return pd.DataFrame(s.execute(q).all(), columns=["event_id", "first_detection", "last_detection", "state", "district_id",
                                                         "land_use", "fre_mj_low", "fre_mj_high", "n_obs", "status"])


def build(start=None, end=None, n_draws: int = 1000) -> dict:
    """FRP/FRE-method estimates for all fire events in the window, with Monte Carlo uncertainty on the totals."""
    if not 50 <= n_draws <= 20000:
        raise ValueError("n_draws must be 50-20000")
    ef = emission_factors()
    ev = _events(start, end)
    ev = ev.dropna(subset=["fre_mj_low", "fre_mj_high"])
    ev = ev[(ev["fre_mj_low"] > 0) & (ev["fre_mj_high"] > 0)]
    if ev.empty:
        return {"status": "NO_EVENTS", "note": "Run fire-event delineation first (job fire_events).", "label": LABEL}
    lo, hi = np.log(ev["fre_mj_low"].to_numpy()), np.log(ev["fre_mj_high"].to_numpy())
    choices = [_biome_choices(x) for x in ev["land_use"]]
    ef_by = {sp: {b: ef.loc[sp, b] for b in ef.columns} for sp in SPECIES}
    # central estimate per event: geometric-mid FRE, mean CR, mean EF over the biome choices
    fre_mid = np.exp((lo + hi) / 2)
    dm_mid = fre_mid * CR_MEAN
    per = pd.DataFrame({"event_id": ev["event_id"], "state": ev["state"], "district_id": ev["district_id"], "land_use": ev["land_use"],
                        "month": pd.to_datetime(ev["first_detection"]).dt.strftime("%Y-%m"), "fre_mj_mid": fre_mid, "dm_kg": dm_mid})
    for sp in SPECIES:
        efm = np.array([np.mean([ef_by[sp][b] for b in c]) for c in choices])
        efl = np.array([min(ef_by[sp][b] for b in c) for c in choices])
        efh = np.array([max(ef_by[sp][b] for b in c) for c in choices])
        per[f"{sp}_kg"] = dm_mid * efm / 1000
        per[f"{sp}_kg_low"] = ev["fre_mj_low"].to_numpy() * (CR_MEAN - 2 * CR_SD) * efl / 1000
        per[f"{sp}_kg_high"] = ev["fre_mj_high"].to_numpy() * (CR_MEAN + 2 * CR_SD) * efh / 1000
    # Monte Carlo on totals
    rng = np.random.default_rng(RNG_SEED)
    pick_second = np.array([len(c) > 1 for c in choices])
    tot = {sp: np.empty(n_draws) for sp in SPECIES}
    tot_dm = np.empty(n_draws)
    e1 = {sp: np.array([ef_by[sp][c[0]] for c in choices]) for sp in SPECIES}
    e2 = {sp: np.array([ef_by[sp][c[-1]] for c in choices]) for sp in SPECIES}
    for k in range(n_draws):
        u = rng.random()                                # systematic position inside the FRE bracket
        fre = np.exp(lo + u * (hi - lo))
        cr = rng.normal(CR_MEAN, CR_SD)
        second = pick_second & (rng.random(len(ev)) < 0.5)
        dm = fre * cr
        tot_dm[k] = dm.sum()
        for sp in SPECIES:
            tot[sp][k] = (dm * np.where(second, e2[sp], e1[sp])).sum() / 1000
    q = lambda a: {"median": float(np.median(a)), "p05": float(np.percentile(a, 5)), "p95": float(np.percentile(a, 95))}
    res = {"label": LABEL, "method": "FRP/FRE mass balance (Wooster 2005 CR; GFED4 EF)", "start": start, "end": end,
           "events": int(len(ev)), "events_without_frp": int(len(_events(start, end)) - len(ev)), "n_draws": n_draws,
           "totals_tonnes": {"dry_matter": {k: v / 1000 for k, v in q(tot_dm).items()},
                             **{sp: {k: v / 1000 for k, v in q(tot[sp]).items()} for sp in SPECIES}},
           "inputs": {"combustion_factor_kg_per_MJ": {"mean": CR_MEAN, "sd": CR_SD, "source": "Wooster et al. 2005, JGR 110, D24311"},
                      "emission_factors": {"file": EF_FILE.name, "sha256": EF_SHA256, "source": EF_URL,
                                           "basis": "GFED4 table, mostly Akagi et al. 2011", "species": SPECIES,
                                           "values_g_per_kg": {sp: ef.loc[sp].to_dict() for sp in SPECIES}},
                      "biome_mapping": {k: list(v) for k, v in BIOMES.items()},
                      "fre_bracket_isolated_pass_hours": [0.5, 6.0]},
           "uncertainty_not_included": ["within-biome emission-factor variability (not in the GFED table)",
                                        "FRP omission of small/cool fires below the detection limit",
                                        "cloud-obscured burning", "land-cover misclassification beyond the biome choice"],
           "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    OUT.mkdir(parents=True, exist_ok=True)
    per.to_parquet(OUT / "event_emissions.parquet", index=False)
    (OUT / "summary.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def summary() -> dict:
    f = OUT / "summary.json"
    ba = burned_area_method_status()
    if not f.exists():
        return {"status": "NOT_COMPUTED", "label": LABEL, "burned_area_method": ba,
                "note": "Run the emissions job after fire events exist."}
    return json.loads(f.read_text()) | {"status": "ESTIMATED", "burned_area_method": ba}


def _per() -> pd.DataFrame:
    f = OUT / "event_emissions.parquet"
    if not f.exists():
        raise KeyError("emissions not computed yet")
    return pd.read_parquet(f)


def regions(by: str = "state") -> dict:
    if by not in ("state", "district_id", "month", "land_use"):
        raise ValueError("by must be state | district_id | month | land_use")
    d = _per()
    cols = ["dm_kg"] + [c for sp in SPECIES for c in (f"{sp}_kg", f"{sp}_kg_low", f"{sp}_kg_high")]
    g = d.groupby(d[by].fillna("unassigned"))[cols].sum().reset_index().sort_values("dm_kg", ascending=False)
    g["events"] = d.groupby(d[by].fillna("unassigned")).size().reindex(g[by]).to_numpy()
    return {"by": by, "label": LABEL, "items": g.to_dict("records"),
            "note": "Per-region low/high are simple sums of per-event bounds (conservative envelope, not a confidence interval)."}


def events(limit: int = 100, offset: int = 0) -> dict:
    d = _per().sort_values("PM2.5_kg", ascending=False)
    return {"label": LABEL, "total": int(len(d)), "items": d.iloc[offset:offset + min(limit, 1000)].to_dict("records")}


def burned_area_method_status() -> dict:
    from . import burned_area
    months = burned_area.coverage()["months"]
    if not FUEL_FILE.exists():
        return {"status": "BLOCKED_BY_EXTERNAL_DATA", "processed_burned_area_months": len(months),
                "missing": f"{FUEL_FILE.name}: authoritative fuel consumption per biome (kg DM m^-2) with source; PyroScope does not invent fuel loads"}
    if not months:
        return {"status": "BLOCKED_BY_CREDENTIALS", "missing": "processed MCD64A1/VNP64A1 months (Earthdata + LAADS licence)"}
    return {"status": "READY", "processed_burned_area_months": len(months)}


def burned_area_method(product: str, year: int, month: int) -> dict:
    """DM = burned area x fuel consumption, by the dominant land cover of each 0.25 deg cell."""
    from . import burned_area, store
    st = burned_area_method_status()
    if st["status"] != "READY":
        raise PermissionError(f"{st['status']}: {st.get('missing')}")
    fc = pd.read_csv(FUEL_FILE)
    need = {"biome", "fc_kg_m2", "fc_sd_kg_m2", "source"}
    if not need <= set(fc.columns):
        raise ValueError(f"{FUEL_FILE.name} needs columns {sorted(need)}")
    ef = emission_factors()
    cells = burned_area._cells(product, year, month)
    lu = store.cells().set_index("cell_id")["land_use"]
    cells["biome"] = cells["cell_id"].map(lu).map(lambda x: _biome_choices(x)[0])
    cells = cells.merge(fc, on="biome", how="left")
    if cells["fc_kg_m2"].isna().any():
        raise ValueError(f"fuel consumption missing for biomes {sorted(cells.loc[cells['fc_kg_m2'].isna(), 'biome'].unique())}")
    cells["dm_kg"] = cells["burned_km2"] * 1e6 * cells["fc_kg_m2"]
    out = {"label": LABEL, "method": "burned area x fuel consumption", "product": product, "year": year, "month": month,
           "dry_matter_t": float(cells["dm_kg"].sum() / 1000)}
    for sp in SPECIES:
        out[f"{sp}_t"] = float((cells["dm_kg"] * cells["biome"].map(ef.loc[sp])).sum() / 1e6)
    return out
