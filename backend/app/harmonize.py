"""MODIS -> VIIRS harmonization: Morning-Gap Fixer, Sensor Harmonizer, bootstrap
uncertainty, held-out validation and seam test.

Model (identical form for both steps, x -> y):

    y_hat(region, month) =  F[state, moy, dn] * X  +  a[state, moy, dn] * N_silent

  X         detections of the predictor sensor in the region-month (day / night kept apart)
  N_silent  number of region grid cells in which the predictor sensor saw nothing
  F         ratio of target to predictor detections in cells where the predictor saw fire
  a         mean target detections per predictor-silent cell (fires below the predictor's
            detection floor / missed by its overpass)

F and a are learned per calendar month and day/night for every state, and shrunk toward
the national value in proportion to how little data the state has. The model is linear in
cell sums, so it aggregates consistently to any set of grid cells (district, custom box).

  Morning-Gap Fixer : Terra -> Aqua           (diurnal sampling difference)
  Sensor Harmonizer : Aqua  -> S-NPP VIIRS    (resolution / sensitivity difference)

Counts use presumed-vegetation detections (FIRMS type 0) plus untyped NRT rows. NRT
months are never used for training. Nothing here adds MODIS and VIIRS counts together.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

from . import store
from .config import BOOTSTRAP_N, RNG_SEED, VIIRS_REFERENCE

K_RATIO = 50.0        # pseudo-detections of prior weight for the state ratio
K_SILENT = 200.0      # pseudo cell-months of prior weight for the silent-cell rate
MIN_NATIONAL = 200.0  # predictor detections per calendar month below which calibration is flagged
MIN_YEARS = 3
SIM_TERRA_ONLY_MONTHS = 20   # length of the real FIRMS Terra-only era (Nov 2000 - Jun 2002)
RES_BINS = np.array([1.0, 2.0, 3.0, 4.0])  # log10(yhat+1) edges
SATS = ["Terra", "Aqua", VIIRS_REFERENCE]


# --------------------------------------------------------------------------- panels
@dataclass
class Panel:
    ax: pd.PeriodIndex
    states: list
    ncell: np.ndarray                      # [S] region cells per state
    n: dict = field(default_factory=dict)  # sat -> [T,S,2] detections
    aq_seen: np.ndarray = None             # Aqua detections in Terra-active cells
    n_act_terra: np.ndarray = None
    n_act_aqua: np.ndarray = None
    v_seen: np.ndarray = None              # VIIRS detections in Aqua-active cells
    frp: dict = field(default_factory=dict)
    ref: str = VIIRS_REFERENCE             # VIIRS product stream defining the target scale

    @property
    def ym(self):
        return store.ym_of(self.ax)

    @property
    def moy(self):
        return (self.ax.month - 1).to_numpy()


@lru_cache(maxsize=64)
def panel(region_id: str = "country", ref: str = VIIRS_REFERENCE) -> Panel:
    sats = ["Terra", "Aqua", ref]
    ax = store.month_axis()
    sts = store.states()
    sidx = {s: i for i, s in enumerate(sts)}
    cells = store.cells()
    rc = np.array(store.region_cells(region_id), dtype="int64")
    known = cells.index.intersection(rc)
    ncell = np.zeros(len(sts))
    for s, k in cells.loc[known, "state"].value_counts().items():
        ncell[sidx[s]] = k
    ncell[sidx[store.OUTSIDE]] += len(rc) - len(known)

    m = store.region_monthly(region_id)
    m = m[m["satellite"].isin(sats)]
    T, S = len(ax), len(sts)
    p = Panel(ax=ax, states=sts, ncell=ncell, ref=ref)
    shape = (T, S, 2)
    for s in sats:
        p.n[s] = np.zeros(shape)
        p.frp[s] = np.zeros(shape)
    p.aq_seen, p.v_seen = np.zeros(shape), np.zeros(shape)
    p.n_act_terra, p.n_act_aqua = np.zeros(shape), np.zeros(shape)
    if len(m) == 0:
        return p
    ympos = pd.Series(np.arange(T), index=store.ym_of(ax))
    w = m.pivot_table(index=["ym", "cell_id", "daynight"], columns="satellite", values="n_veg", aggfunc="sum",
                      fill_value=0, observed=True).reset_index()
    for s in sats:
        if s not in w:
            w[s] = 0
    ti = ympos.reindex(w["ym"]).to_numpy()
    si = cells["state"].reindex(w["cell_id"]).fillna(store.OUTSIDE).map(sidx).to_numpy()
    di = w["daynight"].astype(str).map(store.DN).fillna(0).astype(int).to_numpy()
    ok = ~np.isnan(ti)
    ti, si, di, w = ti[ok].astype(int), si[ok].astype(int), di[ok], w[ok]
    te, aq, vi = (w[s].to_numpy(dtype=float) for s in sats)
    np.add.at(p.n["Terra"], (ti, si, di), te)
    np.add.at(p.n["Aqua"], (ti, si, di), aq)
    np.add.at(p.n[ref], (ti, si, di), vi)
    np.add.at(p.aq_seen, (ti, si, di), aq * (te > 0))
    np.add.at(p.v_seen, (ti, si, di), vi * (aq > 0))
    np.add.at(p.n_act_terra, (ti, si, di), (te > 0).astype(float))
    np.add.at(p.n_act_aqua, (ti, si, di), (aq > 0).astype(float))
    return p


# --------------------------------------------------------------------------- the calibration model
def _sum_by_moy(W, A, moy):
    """sum_t W[b,t] * A[t,s,d] grouped by calendar month -> [B,S,12,2]."""
    out = np.zeros((W.shape[0], A.shape[1], 12, A.shape[2]))
    for mth in range(12):
        idx = np.where(moy == mth)[0]
        if len(idx):
            out[:, :, mth, :] = np.tensordot(W[:, idx], A[idx], axes=(1, 0))
    return out


def fit_pair(W, moy, X, Yseen, Ytot, NactX, NactY, ncell):
    """Vectorised over bootstrap weight rows W[B,T]. Returns params with leading B axis."""
    Nsil = np.clip(ncell[None, :, None] - NactX, 0, None)
    sx, sys_, syt = _sum_by_moy(W, X, moy), _sum_by_moy(W, Yseen, moy), _sum_by_moy(W, Ytot, moy)
    sns, snx, sny = _sum_by_moy(W, Nsil, moy), _sum_by_moy(W, NactX, moy), _sum_by_moy(W, NactY, moy)
    sysil = syt - sys_
    nx, nys, nsil, nns = sx.sum(1), sys_.sum(1), sysil.sum(1), sns.sum(1)   # national [B,12,2]
    with np.errstate(divide="ignore", invalid="ignore"):
        pooled = nys.sum(1, keepdims=True) / nx.sum(1, keepdims=True)
        R = np.where(nx >= MIN_NATIONAL, nys / nx, pooled)
        R = np.nan_to_num(R, nan=1.0, posinf=1.0)
        F = (sys_ + K_RATIO * R[:, None]) / (sx + K_RATIO)
        a_nat = np.nan_to_num(nsil / nns, nan=0.0, posinf=0.0)
        a = (sysil + K_SILENT * a_nat[:, None]) / (sns + K_SILENT)
        g_nat = np.nan_to_num(sny.sum(1) / snx.sum(1), nan=1.0, posinf=1.0)
        g = (sny + 20.0 * g_nat[:, None]) / (snx + 20.0)
    return {"F": F, "a": a, "g": g, "R": R, "a_nat": a_nat, "nx": nx}


def predict_pair(par, moy, X, NactX, ncell):
    """-> y_hat [B,T,S,2] and estimated number of target-active cells."""
    F = np.moveaxis(par["F"][:, :, moy, :], 2, 1)
    a = np.moveaxis(par["a"][:, :, moy, :], 2, 1)
    g = np.moveaxis(par["g"][:, :, moy, :], 2, 1)
    Nsil = np.clip(ncell[None, None, :, None] - NactX, 0, None)
    y = F * X + a * Nsil
    nact_y = np.minimum(ncell[None, None, :, None], g * NactX)
    return y, nact_y


def _pools(log_resid, size):
    """Empirical out-of-sample log residuals binned by predicted magnitude."""
    b = np.digitize(size, RES_BINS)
    pools = [log_resid[b == i] for i in range(len(RES_BINS) + 1)]
    filled = []
    for i, p_ in enumerate(pools):
        j = i
        if len(p_) < 15:  # borrow from the nearest adequately populated bin
            cand = [k for k in sorted(range(len(pools)), key=lambda k: abs(k - i)) if len(pools[k]) >= 15]
            j = cand[0] if cand else i
        filled.append(pools[j] if len(pools[j]) else np.zeros(1))
    return filled


def _draw(pools, yhat, rng, inflate=None):
    b = np.digitize(np.log10(np.clip(yhat, 0, None) + 1.0), RES_BINS)
    e = np.zeros_like(yhat)
    for i, p_ in enumerate(pools):
        msk = b == i
        if msk.any():
            e[msk] = rng.choice(p_, size=int(msk.sum()))
    if inflate is not None:
        e = e * inflate
    return e


@dataclass
class Fit:
    split: int | None
    train_mg: np.ndarray
    train_sh: np.ndarray
    mg: dict
    sh: dict
    pools_mg: list
    pools_sh: list
    years_mg: list
    years_sh: list
    terra_only_end: int | None       # simulated Terra-only era ends before this ym (demo only)
    loyo: dict
    notes: list


def _boot_weights(years_of_t, train_mask, B, rng):
    yrs = np.unique(years_of_t[train_mask])
    W = np.zeros((B, len(years_of_t)))
    W[0, train_mask] = 1.0
    for b in range(1, B):
        pick = rng.choice(yrs, size=len(yrs), replace=True)
        cnt = pd.Series(pick).value_counts()
        W[b] = np.where(train_mask, pd.Series(years_of_t).map(cnt).fillna(0).to_numpy(), 0.0)
    return W, yrs


def _loyo(p: Panel, train, moy, years, args, target, name):
    """Leave-one-year-out predictions -> residual pools + per-calendar-month skill."""
    yrs = np.unique(years[train])
    if len(yrs) < 2:
        return [np.zeros(1)] * (len(RES_BINS) + 1), {"n_years": int(len(yrs)), "by_month": []}
    W = np.stack([np.where(train & (years != y), 1.0, 0.0) for y in yrs])
    par = fit_pair(W, moy, *args, p.ncell)
    yh, _ = predict_pair(par, moy, args[0], args[3], p.ncell)       # [Y,T,S,2]
    res, size, rows = [], [], []
    for i, y in enumerate(yrs):
        tt = np.where(train & (years == y))[0]
        ps, ts = yh[i, tt].sum(-1), target[tt].sum(-1)              # state level [t,S]
        pn, tn = ps.sum(-1), ts.sum(-1)                             # national   [t]
        keep = (ps + ts) > 0
        res += [np.log((ts[keep] + 1) / (ps[keep] + 1)), np.log((tn + 1) / (pn + 1))]
        size += [np.log10(ps[keep] + 1), np.log10(pn + 1)]
        rows += [{"year": int(y), "moy": int(moy[t]) + 1, "pred": float(a_), "actual": float(b_)} for t, a_, b_ in zip(tt, pn, tn)]
    df = pd.DataFrame(rows)
    by = []
    for mth, g in df.groupby("moy"):
        err = (g["pred"] - g["actual"]).abs().sum()
        by.append({"moy": int(mth), "wape": float(err / g["actual"].sum()) if g["actual"].sum() > 0 else None,
                   "bias": float((g["pred"].sum() - g["actual"].sum()) / g["actual"].sum()) if g["actual"].sum() > 0 else None,
                   "n_years": int(len(g)), "mean_actual": float(g["actual"].mean())})
    return _pools(np.concatenate(res), np.concatenate(size)), {"n_years": int(len(yrs)), "by_month": by, "pairs": name}


@lru_cache(maxsize=16)
def fit(split: int | None = None, B: int = BOOTSTRAP_N, ref: str = VIIRS_REFERENCE) -> Fit:
    """Fit both calibrations on the national panel.
    split=None  -> operational: every overlapping, fully covered, standard-processing month.
    split=YYYYMM -> held-out experiment: train ONLY on months >= split; everything earlier is
                    treated as unseen (VIIRS withheld; Aqua also withheld for the first
                    SIM_TERRA_ONLY_MONTHS months to imitate the Terra-only era)."""
    p = panel("country", ref)
    cov = store.coverage()
    if ref not in cov:
        raise ValueError(f"VIIRS product stream '{ref}' is not loaded")
    ym, moy, years = p.ym, p.moy, p.ax.year.to_numpy()
    full = lambda s: (cov[s].to_numpy() >= 0.999) & cov[s + "|typed"].to_numpy()
    after = (ym >= split) if split else np.ones(len(ym), bool)
    stab = lambda s: np.isin(years, list(store.stable_years(s)))
    train_mg = full("Terra") & full("Aqua") & after & stab("Terra") & stab("Aqua")
    train_sh = full("Aqua") & full(ref) & after & stab("Aqua")
    notes = []
    o = store.orbit()
    drift = {s: sorted(int(y) for y in o.loc[(o["satellite"] == s) & ~o["stable"], "year"]) for s in ("Terra", "Aqua")}
    if drift["Terra"] or drift["Aqua"]:
        notes.append("MODIS orbit drift detected in the loaded records (mean day-time local overpass time moved more than "
                     f"{store.ORBIT_TOL_H} h from its early baseline): Terra {drift['Terra'] or 'none'}, Aqua {drift['Aqua'] or 'none'}. "
                     "Those years are excluded from calibration because their diurnal sampling differs from the historical MODIS era.")
    rng = np.random.default_rng(RNG_SEED)
    T_, A_, V_ = p.n["Terra"], p.n["Aqua"], p.n[ref]
    mg_args = (T_, p.aq_seen, A_, p.n_act_terra, p.n_act_aqua)
    sh_args = (A_, p.v_seen, V_, p.n_act_aqua, p.n_act_aqua)   # target-active cells unused downstream
    Wm, ymg = _boot_weights(years, train_mg, B, rng)
    Ws, ysh = _boot_weights(years, train_sh, B, rng)
    mg = fit_pair(Wm, moy, *mg_args, p.ncell)
    sh = fit_pair(Ws, moy, *sh_args, p.ncell)
    pools_mg, loyo_mg = _loyo(p, train_mg, moy, years, mg_args, A_, "Terra->Aqua")
    pools_sh, loyo_sh = _loyo(p, train_sh, moy, years, sh_args, V_, "Aqua->VIIRS")
    for nm, yrs in (("Morning-gap (Terra->Aqua)", ymg), ("Sensor (Aqua->VIIRS)", ysh)):
        if len(yrs) < MIN_YEARS:
            notes.append(f"{nm} calibration is UNRELIABLE: only {len(yrs)} training year(s) with full overlap.")
    terra_only_end = None
    if split:
        test = np.where((ym < split) & (cov[ref].to_numpy() >= 0.999))[0]
        if len(test):
            k = min(SIM_TERRA_ONLY_MONTHS, max(len(test) // 2, 1))
            terra_only_end = int(ym[test[min(k, len(test) - 1)]])
    return Fit(split, train_mg, train_sh, mg, sh, pools_mg, pools_sh, [int(y) for y in ymg], [int(y) for y in ysh],
               terra_only_end, {"mg": loyo_mg, "sh": loyo_sh}, notes)


# --------------------------------------------------------------------------- region series
def series(region_id: str = "country", split: int | None = None, with_reps: bool = False, ref: str = VIIRS_REFERENCE):
    """Monthly harmonized record for a region. Returns (DataFrame, replicates[B,T] or None)."""
    ft, p = fit(split, ref=ref), panel(region_id, ref)
    cov = store.coverage()
    ym, moy = p.ym, p.moy
    cT, cA, cV = (cov[s].to_numpy() for s in ("Terra", "Aqua", ref))
    typedV = cov[ref + "|typed"].to_numpy()
    held = (ym < split) if split else np.zeros(len(ym), bool)
    viirs_avail = (cV >= 0.999) & ~held
    aqua_withheld = held & (ym < (ft.terra_only_end or 0))
    aqua_avail = (cA >= 0.5) & ~aqua_withheld
    terra_avail = cT >= 0.5
    rng = np.random.default_rng(RNG_SEED + 1)

    def scaled(arr, c):  # partial-month coverage: scale up, never treat missing days as zero
        f_ = np.where(c >= 0.5, 1.0 / np.clip(c, 0.5, 1.0), np.nan)
        return arr * f_[:, None, None]

    Tx, Ax = scaled(p.n["Terra"], cT), scaled(p.n["Aqua"], cA)
    infl_T = 1.0 / np.sqrt(np.clip(cT, 0.25, 1.0))
    infl_A = 1.0 / np.sqrt(np.clip(cA, 0.25, 1.0))

    # Step 1 - morning gap: Aqua estimated from Terra (computed everywhere, used where Aqua is absent)
    aq_hat, nact_aq_hat = predict_pair(ft.mg, moy, np.nan_to_num(Tx), p.n_act_terra, p.ncell)   # [B,T,S,2]
    aq_tot = aq_hat.sum((2, 3))
    e_mg = _draw(ft.pools_mg, aq_tot, rng, infl_T[None, :])
    e_mg[0] = 0.0
    scale_mg = (aq_tot + 1.0) * np.exp(e_mg) / (aq_tot + 1.0)
    aq_rep = aq_hat * scale_mg[:, :, None, None]
    use_est = ~aqua_avail
    aq_used = np.where(use_est[None, :, None, None], aq_rep, np.nan_to_num(Ax)[None])
    nact_used = np.where(use_est[None, :, None, None], nact_aq_hat, p.n_act_aqua[None])

    # Step 2 - sensor harmonizer: VIIRS-equivalent from (actual or estimated) Aqua
    F = np.moveaxis(ft.sh["F"][:, :, moy, :], 2, 1)
    a = np.moveaxis(ft.sh["a"][:, :, moy, :], 2, 1)
    nsil = np.clip(p.ncell[None, None, :, None] - nact_used, 0, None)
    v_sd = F * aq_used + a * nsil                                # [B,T,S,2]
    v_dn = v_sd[0].sum(1)                                        # central estimate by day/night [T,2]
    v_tot = v_sd.sum((2, 3))                                     # [B,T]
    e_sh = _draw(ft.pools_sh, v_tot, rng, np.where(use_est, 1.0, infl_A)[None, :])
    e_sh[0] = 0.0
    reps = np.clip((v_tot + 1.0) * np.exp(e_sh) - 1.0, 0, None)
    central = v_tot[0]
    lo, hi = np.percentile(reps[1:], [5, 95], axis=0) if reps.shape[0] > 2 else (central, central)
    aq_reps = np.clip((aq_tot + 1.0) * np.exp(e_mg) - 1.0, 0, None)
    aq_lo, aq_hi = np.percentile(aq_reps[1:], [5, 95], axis=0) if aq_reps.shape[0] > 2 else (aq_tot[0], aq_tot[0])
    no_pred = ~(aqua_avail | terra_avail)

    tot = lambda s: p.n[s].sum((1, 2))
    nanif = lambda v, bad: np.where(bad, np.nan, v)
    prov = np.select([viirs_avail, aqua_avail, terra_avail], ["actual_viirs", "sensor_calibrated", "morning_gap_sensor"], "no_data")
    df = pd.DataFrame({
        "ym": ym, "date": p.ax.to_timestamp().strftime("%Y-%m-%d"), "year": p.ax.year, "month": p.ax.month,
        "terra": nanif(tot("Terra"), cT == 0), "aqua": nanif(tot("Aqua"), cA == 0), "viirs": nanif(tot(ref), cV == 0),
        "terra_day": nanif(p.n["Terra"][:, :, 0].sum(1), cT == 0), "terra_night": nanif(p.n["Terra"][:, :, 1].sum(1), cT == 0),
        "aqua_day": nanif(p.n["Aqua"][:, :, 0].sum(1), cA == 0), "aqua_night": nanif(p.n["Aqua"][:, :, 1].sum(1), cA == 0),
        "viirs_day": nanif(p.n[ref][:, :, 0].sum(1), cV == 0), "viirs_night": nanif(p.n[ref][:, :, 1].sum(1), cV == 0),
        "veq_day": nanif(v_dn[:, 0], no_pred), "veq_night": nanif(v_dn[:, 1], no_pred),
        "cov_terra": cT, "cov_aqua": cA, "cov_viirs": cV,
        "viirs_complete": (cV >= 0.999), "nrt": ~typedV & (cV > 0),
        "aqua_est": nanif(aq_tot[0], ~terra_avail), "aqua_est_lo": nanif(aq_lo, ~terra_avail), "aqua_est_hi": nanif(aq_hi, ~terra_avail),
        "veq": nanif(central, no_pred), "veq_lo": nanif(lo, no_pred), "veq_hi": nanif(hi, no_pred),
        "provenance": prov, "withheld_viirs": held & (cV > 0), "withheld_aqua": aqua_withheld & (cA > 0),
        "train_sensor": ft.train_sh, "train_morning_gap": ft.train_mg,
    })
    df["modis_total"] = df["terra"].fillna(0) + df["aqua"].fillna(0)
    df.loc[df["terra"].isna() & df["aqua"].isna(), "modis_total"] = np.nan
    df["harmonized"] = np.where(prov == "actual_viirs", df["viirs"], df["veq"])
    df["harm_lo"] = np.where(prov == "actual_viirs", df["viirs"], df["veq_lo"])
    df["harm_hi"] = np.where(prov == "actual_viirs", df["viirs"], df["veq_hi"])
    return df, (reps if with_reps else None)


# --------------------------------------------------------------------------- metrics
def metrics(actual, pred) -> dict:
    a, p_ = np.asarray(actual, float), np.asarray(pred, float)
    ok = ~(np.isnan(a) | np.isnan(p_))
    a, p_ = a[ok], p_[ok]
    if len(a) == 0:
        return {"n": 0}
    err = p_ - a
    big = a >= 10
    ss = float(((a - a.mean()) ** 2).sum())
    return {
        "n": int(len(a)), "mae": float(np.abs(err).mean()), "rmse": float(np.sqrt((err ** 2).mean())),
        "wape_pct": float(100 * np.abs(err).sum() / a.sum()) if a.sum() > 0 else None,
        "mape_pct": float(100 * (np.abs(err[big]) / a[big]).mean()) if big.any() else None,
        "bias_pct": float(100 * err.sum() / a.sum()) if a.sum() > 0 else None,
        "r2": float(1 - (err ** 2).sum() / ss) if ss > 0 else None,
        "mean_actual": float(a.mean()),
    }


def status_of(m: dict) -> str:
    """PyroScope's own convention (stated in the UI): WAPE<=20% and |bias|<=10% good; WAPE<=40% moderate."""
    if not m or m.get("wape_pct") is None or m.get("n", 0) < 6:
        return "insufficient_data"
    if m["wape_pct"] <= 20 and abs(m["bias_pct"]) <= 10:
        return "good"
    return "moderate" if m["wape_pct"] <= 40 else "poor"


def default_split(ref: str = VIIRS_REFERENCE) -> int | None:
    """Chronological split leaving ~35% of fully-overlapping years as the unseen early period."""
    cov = store.coverage()
    if ref not in cov:
        return None
    okm = (cov["Aqua"] >= 0.999) & (cov[ref] >= 0.999) & cov["Aqua|typed"] & cov[ref + "|typed"]
    yrs = sorted(set(cov.index[okm.to_numpy()].year))
    if len(yrs) < 5:
        return None
    return int(yrs[max(2, int(round(len(yrs) * 0.35)))] * 100 + 1)


def _ymfmt(ym: int) -> str:
    return f"{int(ym) // 100}-{int(ym) % 100:02d}"


def product_label(ref: str) -> str:
    return f"{ref.replace(' 750m', '')} VIIRS 750 m" if ref.endswith("750m") else f"{ref} VIIRS 375 m"


def products() -> dict:
    """VIIRS product streams available as calibration targets. 375 m and 750 m are never pooled."""
    cov = store.coverage()
    streams = [c for c in cov.columns if "|" not in c and c not in ("Terra", "Aqua")]
    out = []
    for st in streams:
        if cov[st].sum() == 0:
            continue
        out.append({"stream": st, "label": product_label(st), "product_type": "750m" if st.endswith("750m") else "375m",
                    "months_with_data": int((cov[st] > 0).sum()), "is_default_reference": st == VIIRS_REFERENCE,
                    "calibration_target": st == VIIRS_REFERENCE or st.endswith("750m")})
    has750 = any(o["product_type"] == "750m" for o in out)
    return {"streams": out, "viirs_750m": "loaded" if has750 else "unavailable",
            "viirs_750m_message": None if has750 else ("No VIIRS 750 m (VNP14/VJ114) records are loaded. FIRMS distributes only the 375 m product; "
                                                       "750 m Level-2 swath granules come from LAADS DAAC. Convert them with `python -m app.acquire vnp14` "
                                                       "or upload a CSV marked product 750m. Until then calibration targets S-NPP 375 m only.")}


def validation(region_id: str = "country", split: int | None = None, ref: str = VIIRS_REFERENCE) -> dict:
    split = split or default_split(ref)
    if not split:
        return {"status": "insufficient_data", "validation_kind": "unavailable",
                "message": "Fewer than 5 fully overlapping MODIS-VIIRS years are loaded; a chronological hold-out is not possible."}
    df, _ = series(region_id, split, ref=ref)
    ft = fit(split, ref=ref)
    test = df[df["withheld_viirs"] & df["viirs_complete"] & ~df["nrt"]].copy()
    train = df[df["train_sensor"]]
    const = train["viirs"].sum() / train["aqua"].sum() if train["aqua"].sum() > 0 else np.nan
    const_mg = train["aqua"].sum() / train["terra"].sum() if train["terra"].sum() > 0 else np.nan
    base_pred = np.where(test["provenance"] == "morning_gap_sensor", test["terra"] * const_mg * const, test["aqua"] * const)
    out = {
        "region": store.region_label(region_id), "split": split, "terra_only_end": ft.terra_only_end,
        "train_years": ft.years_sh, "test_period": [int(test["ym"].min()), int(test["ym"].max())] if len(test) else None,
        "overall": metrics(test["viirs"], test["veq"]),
        "baseline_constant_ratio": metrics(test["viirs"], base_pred),
        "baseline_raw_modis": metrics(test["viirs"], test["modis_total"]),
        "by_stage": {}, "by_month": [], "by_year": [], "notes": list(ft.notes),
    }
    for st, g in test.groupby("provenance"):
        out["by_stage"][st] = metrics(g["viirs"], g["veq"])
    for mth, g in test.groupby("month"):
        out["by_month"].append({"month": int(mth), **metrics(g["viirs"], g["veq"])})
    for y, g in test.groupby("year"):
        out["by_year"].append({"year": int(y), "actual": float(g["viirs"].sum()), "estimate": float(g["veq"].sum()),
                               "lo": float(g["veq_lo"].sum()), "hi": float(g["veq_hi"].sum()), "raw_modis": float(g["modis_total"].sum())})
    inside = ((test["viirs"] >= test["veq_lo"]) & (test["viirs"] <= test["veq_hi"])).mean() if len(test) else np.nan
    out["band_coverage_pct"] = None if np.isnan(inside) else float(100 * inside)
    mgt = df[df["withheld_aqua"]]
    out["morning_gap"] = {"metrics": metrics(mgt["aqua"], mgt["aqua_est"]),
                          "baseline_constant_ratio": metrics(mgt["aqua"], mgt["terra"] * const_mg),
                          "band_coverage_pct": float(100 * ((mgt["aqua"] >= mgt["aqua_est_lo"]) & (mgt["aqua"] <= mgt["aqua_est_hi"])).mean()) if len(mgt) else None,
                          "period": [int(mgt["ym"].min()), int(mgt["ym"].max())] if len(mgt) else None}
    out["morning_gap"]["status"] = status_of(out["morning_gap"]["metrics"])
    out["status"] = status_of(out["overall"])
    out["reference_product"] = product_label(ref)
    out["by_daynight"] = {
        "day": metrics(test["viirs_day"], test["veq_day"]), "night": metrics(test["viirs_night"], test["veq_night"])}
    out["band_nominal_pct"] = 90.0
    insuff = len(ft.years_sh) < MIN_YEARS or out["overall"].get("n", 0) < 6
    out["validation_kind"] = "insufficient_calibration" if insuff else "actual_holdout"
    out["morning_gap"]["validation_kind"] = "simulated_withheld_experiment" if out["morning_gap"]["period"] else "unavailable"
    out["methodology"] = {
        "sensor_stage": (f"ACTUAL hold-out: the calibration is trained only on {min(ft.years_sh) if ft.years_sh else '-'}-{max(ft.years_sh) if ft.years_sh else '-'} "
                         f"and scored against real {product_label(ref)} observations from {_ymfmt(out['test_period'][0]) if out['test_period'] else '-'} to "
                         f"{_ymfmt(out['test_period'][1]) if out['test_period'] else '-'} that the model never saw (chronological, no random split)."),
        "morning_gap_stage": ("SIMULATED experiment: real Aqua records in the first months of the held-out period are hidden so the Terra-only "
                              "era can be imitated; the hidden Aqua values are the answer key. This tests the method, it is not the real 2000-2002 correction."),
        "baselines": ["raw MODIS (Terra + Aqua counts, uncorrected)", "single constant VIIRS/Aqua ratio fitted on the training years", "PyroScope calibrated harmonization"],
        "interval": "Band = 5th-95th percentile of the year-block bootstrap replicates (nominal 90%); empirical coverage on held-out months is reported.",
    }
    out["status_rule"] = "good: WAPE <= 20% and |bias| <= 10%; moderate: WAPE <= 40%; otherwise poor (PyroScope convention, not an external standard)."
    out["series"] = _records(df[df["ym"] < split + 300][["date", "ym", "viirs", "veq", "veq_lo", "veq_hi", "modis_total", "aqua", "terra",
                                                         "provenance", "withheld_viirs", "withheld_aqua", "aqua_est"]])
    return out


def seam_test(region_id: str = "country", split: int | None = None, window: int = 24, ref: str = VIIRS_REFERENCE) -> dict:
    """Discontinuity at the MODIS->VIIRS hand-over, before vs after harmonization.
    Real seam (split=None): first month with actual VIIRS; needs MODIS before it.
    Simulated seam (split=YYYYMM): VIIRS withheld before `split`, so the truth is known."""
    df_real, _ = series(region_id, None, ref=ref)
    first_v = df_real.index[df_real["provenance"] == "actual_viirs"]
    pre_modis = int((df_real.loc[: first_v[0] - 1, "modis_total"].notna()).sum()) if len(first_v) and first_v[0] > 0 else 0
    real_possible = pre_modis >= 12
    mode = "real" if (split is None and real_possible) else "simulated"
    if mode == "simulated":
        split = split or default_split(ref)
        if not split:
            return {"mode": "unavailable", "message": "Not enough overlapping data to run a seam test."}
    df, reps = series(region_id, split if mode == "simulated" else None, with_reps=True, ref=ref)
    s_pos = int(np.where(df["provenance"].to_numpy() == "actual_viirs")[0][0])
    window = int(min(window, s_pos // 12 * 12, (len(df) - s_pos) // 12 * 12))
    if window < 12:
        return {"mode": "unavailable", "real_seam_possible": real_possible,
                "message": "Fewer than 12 months on one side of the seam; the test is not meaningful."}
    b, a_ = df.iloc[s_pos - window: s_pos], df.iloc[s_pos: s_pos + window]
    step = lambda x, y: float(np.nanmean(y) / np.nanmean(x)) if np.nanmean(x) > 0 else None
    raw, harm = step(b["modis_total"], a_["viirs"]), step(b["veq"], a_["viirs"])
    aq_before = np.where(b["aqua"].notna() & ~b["withheld_aqua"], b["aqua"], np.nan)
    ref_step = step(aq_before, a_["aqua"]) if np.isfinite(aq_before).sum() >= window // 2 else step(b["terra"], a_["terra"])
    ref_sensor = "Aqua MODIS" if np.isfinite(aq_before).sum() >= window // 2 else "Terra MODIS"
    truth = step(b["viirs"], a_["viirs"]) if mode == "simulated" else None
    rep_before = reps[1:, s_pos - window: s_pos].mean(1)
    hl, hh = np.percentile(np.nanmean(a_["viirs"]) / np.clip(rep_before, 1e-9, None), [5, 95])
    target = truth if truth else ref_step
    ln = lambda v: float(abs(np.log(v / target))) if v and target else None
    res = {
        "mode": mode, "real_seam_possible": real_possible, "region": store.region_label(region_id),
        "seam_month": df.iloc[s_pos]["date"], "window_months": window,
        "step_raw": raw, "step_harmonized": harm, "step_harmonized_band": [float(hl), float(hh)],
        "step_reference_sensor": ref_step, "reference_sensor": ref_sensor, "step_true": truth,
        "artificial_jump_before": ln(raw), "artificial_jump_after": ln(harm),
        "explanation": ("Each 'step' is mean activity in the %d months after the seam divided by the mean in the %d months before "
                        "(same calendar months on both sides). A genuine change in fire activity also moves the step, so the "
                        "target is NOT 1.0: it is the step measured by a sensor that did not change (%s)%s. The artificial jump is "
                        "|ln(step / target)|." % (window, window, ref_sensor, ", and here the withheld real VIIRS record" if truth else "")),
        "series": _records(df.iloc[max(0, s_pos - window - 12): s_pos + window + 12][
            ["date", "ym", "modis_total", "terra", "aqua", "viirs", "veq", "veq_lo", "veq_hi", "harmonized", "provenance", "withheld_viirs"]]),
    }
    # Is a genuine change still visible? The harmonized step's resampling band is compared with
    # 1.0 (no change); a change counts as detectable only if the unchanged reference sensor agrees.
    band_excl = hl > 1.0 or hh < 1.0
    ref_dir = None if not target else (1 if target > 1.05 else -1 if target < 0.95 else 0)
    harm_dir = 1 if hl > 1.0 else -1 if hh < 1.0 else 0
    res["genuine_change"] = {
        "reference_step": target, "harmonized_band_excludes_no_change": bool(band_excl),
        "detectable": bool(band_excl and ref_dir == harm_dir and ref_dir != 0),
        "direction": {1: "increase", -1: "decrease", 0: "no clear change"}[harm_dir],
        "note": "A real change in fire activity across the seam should survive harmonization. 'detectable' means the harmonized step band "
                "excludes 1.0 and agrees in direction with the step seen by the unchanged reference sensor."}
    res["validation_kind"] = "actual_seam" if mode == "real" else "simulated_seam"
    res["reference_product"] = product_label(ref)
    if res["artificial_jump_before"] is not None and res["artificial_jump_after"] is not None:
        red = 1 - res["artificial_jump_after"] / res["artificial_jump_before"] if res["artificial_jump_before"] > 0 else 0
        res["reduction_pct"] = float(100 * red)
        aj = res["artificial_jump_after"]
        res["status"] = "good" if aj <= 0.10 else "moderate" if aj <= 0.25 else "poor"
        res["status_rule"] = "good: residual artificial jump <= 0.10 ln-units (~10%); moderate: <= 0.25; otherwise poor (PyroScope convention)."
    if not real_possible:
        res["real_seam_note"] = ("The loaded MODIS record starts in the same month as the VIIRS record, so the real 2012 seam cannot be "
                                 "tested with this data. Upload MODIS C6.1 data for 2000-2011 to test it. Shown instead: a simulated seam "
                                 "where real VIIRS data before the seam month was withheld from calibration and used only as the answer key.")
    return res


# --------------------------------------------------------------------------- diagnostics for the UI
def _records(df: pd.DataFrame) -> list:
    return df.astype(object).where(pd.notna(df), None).to_dict("records")


def calibration_table(which: str = "sh", split: int | None = None, state: str | None = None, ref: str = VIIRS_REFERENCE) -> dict:
    """Learned relationship by calendar month (national, and one state if asked) with bootstrap bands."""
    ft = fit(split, ref=ref)
    par = ft.sh if which == "sh" else ft.mg
    sts = store.states()
    rows = []
    for d, dn in enumerate(["day", "night"]):
        for mth in range(12):
            R = par["R"][:, mth, d]
            row = {"moy": mth + 1, "daynight": dn, "ratio": float(R[0]), "ratio_lo": float(np.percentile(R[1:], 5)),
                   "ratio_hi": float(np.percentile(R[1:], 95)), "silent_rate": float(par["a_nat"][0, mth, d]),
                   "predictor_detections": float(par["nx"][0, mth, d]),
                   "reliable": bool(par["nx"][0, mth, d] >= MIN_NATIONAL and len(ft.years_sh if which == "sh" else ft.years_mg) >= MIN_YEARS)}
            if state in sts:
                Fs = par["F"][:, sts.index(state), mth, d]
                row.update(state_ratio=float(Fs[0]), state_lo=float(np.percentile(Fs[1:], 5)), state_hi=float(np.percentile(Fs[1:], 95)))
            rows.append(row)
    return {"pair": f"Aqua MODIS -> {product_label(ref)}" if which == "sh" else "Terra MODIS -> Aqua MODIS", "reference_product": ref,
            "train_years": ft.years_sh if which == "sh" else ft.years_mg, "split": split, "by_month": rows,
            "loyo": ft.loyo[which], "notes": ft.notes,
            "model": "y = F[state,month,day/night] * x + a[state,month,day/night] * (cells where x saw nothing); F and a shrunk to national values",
            "band": "5th-95th percentile of a year-block bootstrap (%d resamples) - a resampling spread, not a formal confidence interval" % (par["R"].shape[0] - 1)}


def state_factors(which: str = "sh", split: int | None = None, ref: str = VIIRS_REFERENCE) -> list:
    """Annual-mean day-time ratio per state (weighted by predictor detections) for mapping."""
    ft, p = fit(split, ref=ref), panel("country", ref)
    par = ft.sh if which == "sh" else ft.mg
    X = p.n["Aqua" if which == "sh" else "Terra"]
    train = ft.train_sh if which == "sh" else ft.train_mg
    out = []
    for i, s in enumerate(p.states):
        w = np.stack([X[train & (p.moy == m), i, :].sum(0) for m in range(12)])   # [12,2]
        tot = w.sum()
        if tot <= 0:
            continue
        out.append({"state": s, "ratio": float((par["F"][0, i] * w).sum() / tot), "predictor_detections": float(tot),
                    "data_weight": float(tot / (tot + K_RATIO * 24))})
    return sorted(out, key=lambda r: -r["predictor_detections"])


def scatter(which: str = "sh", split: int | None = None, max_points: int = 1500, ref: str = VIIRS_REFERENCE) -> list:
    """State-month pairs used for calibration (for a log-log scatter in the UI)."""
    ft, p = fit(split, ref=ref), panel("country", ref)
    x = p.n["Aqua" if which == "sh" else "Terra"].sum(-1)
    y = p.n[ref if which == "sh" else "Aqua"].sum(-1)
    train = ft.train_sh if which == "sh" else ft.train_mg
    ti, si = np.where((x + y > 0) & train[:, None])
    if len(ti) > max_points:
        sel = np.linspace(0, len(ti) - 1, max_points).astype(int)
        ti, si = ti[sel], si[sel]
    return [{"x": float(x[t, s]), "y": float(y[t, s]), "state": p.states[s], "month": int(p.moy[t]) + 1} for t, s in zip(ti, si)]


def clear():
    panel.cache_clear()
    fit.cache_clear()
