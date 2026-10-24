"""Verifier tests on the per-day sums from vstats.py: reproduction, day-clustered family SEs (cross-cell correlation
included), day/week trend-flip permutations, the direction-vs-composition split, and the 9-trend multiplicity."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
SHM = "/dev/shm/claude_verify_obvstoch"
V = pd.read_csv(os.path.join(HERE, "vcell.csv.gz"))
A = pd.read_csv("/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch/all_cells.csv.gz")
OBV = ("OBV20", "OBV30", "OBV50", "OBVSL10"); SRSI = ("SRSI_KD", "SRSI_X")
TRENDS = ("OBV20", "OBV30", "OBV50", "OBVSL10", "ST", "EMA21_52", "ICHI", "J3", "J3A")
rng = np.random.default_rng(20261024)
out = {}


def load(per):
    z = np.load(os.path.join(SHM, f"vday_{per}.npz"))
    return {k: z[k].astype(np.float64) for k in z.files}


def fam_stats(Z, idx, B=2000, block=1):
    """Family mean over cells idx of: dwa, te, comp, tim, dW; day-clustered SE of the family mean (influence summed
    per day across cells); trend-flip permutation p for dwa and te with flips per block of `block` days."""
    SW, NW, SWo, SA, NA, SAo, STO, NTO = (Z[k][idx] for k in ("SW", "NW", "SWo", "SA", "NA", "SAo", "STO", "NTO"))
    nW, nA, nT = NW.sum(1), NA.sum(1), NTO.sum(1)
    ok = (nW > 0) & (nA > 0)
    SW, NW, SWo, SA, NA, SAo, STO, NTO, nW, nA, nT = (x[ok] for x in (SW, NW, SWo, SA, NA, SAo, STO, NTO, nW, nA, nT))
    k = len(nW)
    mW, mA, mWo, mAo, mT = SW.sum(1) / nW, SA.sum(1) / nA, SWo.sum(1) / nW, SAo.sum(1) / nA, STO.sum(1) / nT
    dwa = mW - mA
    # same bars: trend side minus counter side over W u A
    te_num = (SW - SWo) + (SAo - SA)
    te = te_num.sum(1) / (nW + nA)
    comp = 0.5 * (mW + mWo) - 0.5 * (mA + mAo)
    tim = mW - mT
    dW = mW - mWo
    # influence per day (each cell), then average across cells
    I_dwa = (SW - NW * mW[:, None]) / nW[:, None] - (SA - NA * mA[:, None]) / nA[:, None]
    I_te = (te_num - (NW + NA) * te[:, None]) / (nW + nA)[:, None]
    I_tim = (SW - NW * mW[:, None]) / nW[:, None] - (STO - NTO * mT[:, None]) / nT[:, None]
    I_comp = 0.5 * ((SW + SWo - NW * (mW + mWo)[:, None]) / nW[:, None] - (SA + SAo - NA * (mA + mAo)[:, None]) / nA[:, None])
    I_dW = (SW - SWo - NW * dW[:, None]) / nW[:, None]
    act = (NW.sum(0) + NA.sum(0)) > 0
    G = act.sum()

    def se(I):
        v = I.mean(0)[act]
        return float(np.sqrt((v ** 2).sum() * G / (G - 1)))

    res = {"cells": int(k), "days": int(G)}
    for nm, est, I in (("dwa", dwa, I_dwa), ("te", te, I_te), ("comp", comp, I_comp), ("tim", tim, I_tim), ("dW", dW, I_dW)):
        m = float(est.mean()); s = se(I)
        res[nm] = m; res[nm + "_se"] = s; res[nm + "_z"] = m / s if s > 0 else np.nan
        res[nm + "_pos_share"] = float((est > 0).mean())
    # permutation: flip the trend on whole blocks of days (W <-> A on that block; te sign flips)
    days = np.where(act)[0]
    nb = int(np.ceil(Z["SW"].shape[1] / block))
    F = rng.integers(0, 2, size=(B, nb)).astype(np.float64)
    F = np.repeat(F, block, axis=1)[:, : Z["SW"].shape[1]]
    # dwa under flips
    pW_s = (1 - F) @ SW.T + F @ SA.T; pW_n = (1 - F) @ NW.T + F @ NA.T
    pA_s = (1 - F) @ SA.T + F @ SW.T; pA_n = (1 - F) @ NA.T + F @ NW.T
    with np.errstate(invalid="ignore", divide="ignore"):
        pd_ = (pW_s / pW_n - pA_s / pA_n)
    perm_dwa = np.nanmean(pd_, axis=1)
    sg = 1 - 2 * F
    perm_te = ((sg @ te_num.T) / (nW + nA)).mean(1)
    res["dwa_perm_p"] = float((np.sum(perm_dwa >= dwa.mean()) + 1) / (B + 1))
    res["dwa_perm_mean"] = float(np.mean(perm_dwa)); res["dwa_perm_95"] = float(np.quantile(perm_dwa, 0.95))
    res["te_perm_p"] = float((np.sum(perm_te >= te.mean()) + 1) / (B + 1))
    res["te_perm_95"] = float(np.quantile(perm_te, 0.95))
    return res


def ids(per, trends, timings, exits=None):
    q = V[V.period == per].reset_index(drop=True)
    m = q.trend.isin(trends) & q.timing.isin(timings)
    if exits:
        m &= q.exit.isin(exits)
    return np.where(m)[0], q


if __name__ == "__main__":
    # 1) reproduction of the study's cell means
    rep = {}
    for per in ("SEL", "CONF", "FIVE", "FWD"):
        Z = load(per)
        q = V[V.period == per].reset_index(drop=True)
        mW = Z["SW"].sum(1) / Z["NW"].sum(1); mA = Z["SA"].sum(1) / Z["NA"].sum(1); mT = Z["STO"].sum(1) / Z["NTO"].sum(1)
        a = A[A.period == per].set_index("cell").loc[q.cell]
        rep[per] = {"max_abs_diff_roe": float(np.nanmax(np.abs(mW - a.mean_roe.values))),
                    "max_abs_diff_against": float(np.nanmax(np.abs(mA - a.mean_against.values))),
                    "max_abs_diff_trendonly": float(np.nanmax(np.abs(mT - a.trend_only.values))),
                    "n_equal": bool((q.nW.values == a.n.values).all())}
    out["reproduction"] = rep
    print(json.dumps(rep, indent=1))
    # 2) family A and the other 8 trend families (x SRSI) and x all timings, per period, day blocks and week blocks
    TIM = ("SRSI_KD", "SRSI_X", "RSI", "WR", "CCI", "MFI")
    rows = []
    for per in ("SEL", "CONF", "FIVE", "FWD", "PRE"):
        Z = load(per)
        groups = [("famA_OBVx4_SRSI", OBV, SRSI), ("OBV30_SRSI", ("OBV30",), SRSI), ("OBV4_alltim", OBV, TIM),
                  ("other5_SRSI", ("ST", "EMA21_52", "ICHI", "J3", "J3A"), SRSI)]
        groups += [(f"{t}_SRSI", (t,), SRSI) for t in TRENDS if t != "OBV30"]
        groups += [(f"{t}_alltim", (t,), TIM) for t in TRENDS]
        groups += [("all1080", TRENDS, TIM)]
        for nm, tr, tm in groups:
            ix, q = ids(per, tr, tm)
            for blk in ((1, 7) if per != "FWD" else (1,)):
                r = fam_stats(Z, ix, B=2000, block=blk)
                r.update(period=per, group=nm, block_days=blk)
                rows.append(r)
                print(per, nm, blk, {k: round(v * 100, 3) if isinstance(v, float) and not k.endswith(("_p", "_z", "share")) else (round(v, 4) if isinstance(v, float) else v)
                                      for k, v in r.items() if k in ("dwa", "dwa_se", "dwa_z", "dwa_perm_p", "dwa_pos_share", "te", "te_z", "te_perm_p", "comp", "comp_z", "tim", "tim_z", "dW", "dW_z", "cells")})
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(HERE, "vfamily.csv"), index=False, float_format="%.6g")
    json.dump(out, open(os.path.join(HERE, "vtest.json"), "w"), indent=1)
