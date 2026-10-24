"""Verifier (luck / multiple testing) for the claim on OBV20@4h>RSI@1h|a2 (the 'longest-positive' cell).

Independent recomputation from the rebuilt cache (/dev/shm/claude_verify_rsi1h, made by vbuild.py with the study's
own build_coin):
  1. every cell x PRE / SEL / CONF: n, mean, day-cluster SE, t, with and without the TetherMax payback; reproduces
     sel_cells / picks_payback / conf_picks; BH on the 1,080 cells (SEL) with payback.
  2. whole-search day sign-flip permutation (coin-flip null: on a flipped UTC day every signal of every coin and cell
     takes the other side), B = 2,000, payback INCLUDED in the statistic (the study permuted only d):
       - null max t_pb and max mean_pb over the n >= 200 cells on SEL  (Westfall-Young p of the pick)
       - 'pick the SEL best by t_pb, read it on CONF' under the null  -> P(CONF mean_pb >= observed)
       - number of cells positive with payback in SEL and CONF and FIVE under the null  (observed: 1)
  3. signal-level coin flip (random side per signal) for the cell alone, SEL / CONF / FIVE, 20,000 draws.
  4. per-year means of the cell with and without payback; the RSI@1h|a2 neighbours and the timing-only control.
Writes vluck.json next to this file. Run from this folder without -I:  python3 vluck.py
"""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O
O.CACHE = "/dev/shm/claude_verify_rsi1h"
from oscore import PAYBACK, DAY, ms, GRID_END
from scipy.stats import norm
import pandas as pd

CELL = "OBV20@4h>RSI@1h|a2"
D = O.load_all()
cells = O.cells()
ids = [O.cell_id(*c) for c in cells]
ic = ids.index(CELL)
PERS = ("PRE", "SEL", "CONF")
d0 = {p: O.P[p][0] // DAY for p in PERS}
nd = {p: int((O.P[p][1] - O.P[p][0]) // DAY) for p in PERS}

# per-cell per-day sums
MAT = {}
for p in PERS:
    K = len(cells)
    N = np.zeros((K, nd[p])); SR = np.zeros((K, nd[p])); SO = np.zeros((K, nd[p]))
    lev = np.zeros(K)
    for k, (tf, htf, T, Ot, X) in enumerate(cells):
        R = O.rows(D, tf, htf, T, Ot, X, p)
        dd = R["day"].astype(np.int64) - d0[p]
        N[k] = np.bincount(dd, minlength=nd[p])[:nd[p]]
        SR[k] = np.bincount(dd, weights=R["roe"], minlength=nd[p])[:nd[p]]
        SO[k] = np.bincount(dd, weights=R["opp"], minlength=nd[p])[:nd[p]]
        lev[k] = O.LEVX[X]
    MAT[p] = (N, SR, SO)
LEV = lev
PBK = PAYBACK * LEV  # per-trade payback in ROE


def stats_from(N, S, pb):
    """mean, cluster SE, t for every cell from per-day sums S (payback pb per trade added)."""
    n = N.sum(1)
    S = S + pb[:, None] * N
    m = S.sum(1) / np.maximum(n, 1)
    G = (N > 0).sum(1)
    num = (S * S).sum(1) - 2 * m * (N * S).sum(1) + m * m * (N * N).sum(1)
    se = np.sqrt(np.maximum(num, 0) * G / np.maximum(G - 1, 1)) / np.maximum(n, 1)
    t = np.where(se > 0, m / se, np.nan)
    return n, m, se, t


out = {}
# 1. reproduction
obs = {}
for p in PERS:
    N, SR, SO = MAT[p]
    for lab, pb in (("nopb", np.zeros(len(cells))), ("pb", PBK)):
        obs[(p, lab)] = stats_from(N, SR, pb)
N5 = sum(MAT[p][0] for p in PERS[:0]) if False else None
# FIVE as concatenation of days
N5 = np.concatenate([MAT[p][0] for p in PERS], 1)
SR5 = np.concatenate([MAT[p][1] for p in PERS], 1)
SO5 = np.concatenate([MAT[p][2] for p in PERS], 1)
obs[("FIVE", "nopb")] = stats_from(N5, SR5, np.zeros(len(cells)))
obs[("FIVE", "pb")] = stats_from(N5, SR5, PBK)
rep = {}
for p in ("PRE", "SEL", "CONF", "FIVE"):
    for lab in ("nopb", "pb"):
        n, m, se, t = obs[(p, lab)]
        rep[f"{p}_{lab}"] = {"n": int(n[ic]), "mean": float(m[ic]), "t": float(t[ic])}
out["cell_reproduction"] = rep
sel = pd.read_csv("/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch/sel_cells.csv").set_index("cell")
n, m, se, t = obs[("SEL", "nopb")]
out["max_abs_diff_vs_sel_cells_mean"] = float(np.nanmax(np.abs(m - sel.loc[ids].mean_roe.to_numpy())))
out["max_abs_diff_vs_sel_cells_t"] = float(np.nanmax(np.abs(t - sel.loc[ids].t_abs.to_numpy())))

# BH on SEL with payback (n >= 200 eligible, others p = 1)
n, m, se, t = obs[("SEL", "pb")]
elig = n >= 200
p_pb = np.where(elig, norm.sf(t), 1.0)
q = O.bh(p_pb)
order = np.argsort(-np.where(elig, t, -np.inf))
out["SEL_pb"] = {"eligible": int(elig.sum()), "positive_mean_pb": int((elig & (m > 0)).sum()),
                 "top_by_t_pb": [ids[i] for i in order[:5]], "top_t_pb": [float(t[i]) for i in order[:5]],
                 "cell_t_pb": float(t[ic]), "cell_p_pb": float(p_pb[ic]), "cell_q_BH": float(q[ic]),
                 "min_q_BH": float(np.nanmin(q))}
n0, m0, se0, t0 = obs[("SEL", "nopb")]
o0 = np.argsort(-np.where(n0 >= 200, t0, -np.inf))
out["SEL_nopb_top5"] = [(ids[i], float(t0[i]), float(m0[i])) for i in o0[:5]]

# 2. whole-search day sign-flip permutation with payback
rng = np.random.default_rng(777)
B = 2000
res = {"null_max_t_pb_SEL": [], "null_max_mean_pb_SEL": [], "null_pick_conf_mean_pb": [], "null_pick_conf_t_pb": [],
       "null_pick_is_RSI1h_a2": [], "null_count_pos_all3": [], "null_count_pos_sel_conf": [],
       "null_pick_five_mean_pb": []}


def perm_stats(p, eps):
    """mean_pb and t_pb of all cells under flips eps (ndays x b) -> arrays (K x b)."""
    N, SR, SO = MAT[p]
    Mid = (SR + SO) / 2 + PBK[:, None] * N
    H = (SR - SO) / 2
    n = N.sum(1)[:, None]
    S_sum = Mid.sum(1)[:, None] + H @ eps
    m = S_sum / np.maximum(n, 1)
    G = (N > 0).sum(1)[:, None]
    sq = (Mid * Mid + H * H).sum(1)[:, None] + (2 * Mid * H) @ eps
    nS = (N * Mid).sum(1)[:, None] + (N * H) @ eps
    nn = (N * N).sum(1)[:, None]
    num = sq - 2 * m * nS + m * m * nn
    se = np.sqrt(np.maximum(num, 0) * G / np.maximum(G - 1, 1)) / np.maximum(n, 1)
    t = np.where(se > 0, m / se, np.nan)
    return n, m, t, S_sum


rsi1h_a2 = np.array([s.endswith(">RSI@1h|a2") for s in ids])
for i in range(0, B, 200):
    b = min(200, B - i)
    E = {p: rng.choice([-1.0, 1.0], size=(nd[p], b)) for p in PERS}
    nS_, mS, tS, sS = perm_stats("SEL", E["SEL"])
    nC_, mC, tC, sC = perm_stats("CONF", E["CONF"])
    nP_, mP, tP, sP = perm_stats("PRE", E["PRE"])
    el = (nS_[:, 0] >= 200)
    tSe = np.where(el[:, None], tS, -np.inf)
    mSe = np.where(el[:, None], mS, -np.inf)
    res["null_max_t_pb_SEL"] += list(np.nanmax(tSe, 0))
    res["null_max_mean_pb_SEL"] += list(np.nanmax(mSe, 0))
    pick = np.nanargmax(tSe, 0)
    res["null_pick_conf_mean_pb"] += list(mC[pick, np.arange(b)])
    res["null_pick_conf_t_pb"] += list(tC[pick, np.arange(b)])
    res["null_pick_is_RSI1h_a2"] += list(rsi1h_a2[pick].astype(float))
    n5 = nS_ + nC_ + nP_
    m5 = (sS + sC + sP) / np.maximum(n5, 1)
    res["null_pick_five_mean_pb"] += list(m5[pick, np.arange(b)])
    elc = el[:, None] & (nC_ >= 200)
    res["null_count_pos_sel_conf"] += list(((mS > 0) & (mC > 0) & elc).sum(0))
    res["null_count_pos_all3"] += list(((mS > 0) & (mC > 0) & (m5 > 0) & elc).sum(0))
R = {k: np.asarray(v, float) for k, v in res.items()}
nS, mS_obs, sS_, tS_obs = obs[("SEL", "pb")]
nC, mC_obs, _, tC_obs = obs[("CONF", "pb")]
n5o, m5_obs, _, _ = obs[("FIVE", "pb")]
elc_obs = (nS >= 200) & (nC >= 200)
out["perm_payback"] = {
    "B": B,
    "obs_max_t_pb_SEL": float(tS_obs[ic]), "null_max_t_pb_SEL_q50_q95": [float(np.quantile(R["null_max_t_pb_SEL"], q_)) for q_ in (0.5, 0.95)],
    "p_WY_cell_t_pb": float((1 + (R["null_max_t_pb_SEL"] >= tS_obs[ic]).sum()) / (1 + B)),
    "obs_mean_pb_SEL": float(mS_obs[ic]), "null_max_mean_pb_SEL_q50_q95": [float(np.quantile(R["null_max_mean_pb_SEL"], q_)) for q_ in (0.5, 0.95)],
    "p_max_mean_pb": float((1 + (R["null_max_mean_pb_SEL"] >= mS_obs[ic]).sum()) / (1 + B)),
    "obs_conf_mean_pb_of_pick": float(mC_obs[ic]),
    "null_pick_conf_mean_pb_q05_q50_q95": [float(np.quantile(R["null_pick_conf_mean_pb"], q_)) for q_ in (0.05, 0.5, 0.95)],
    "p_pick_conf_ge_obs": float((1 + (R["null_pick_conf_mean_pb"] >= mC_obs[ic]).sum()) / (1 + B)),
    "null_pick_conf_positive_share": float((R["null_pick_conf_mean_pb"] > 0).mean()),
    "null_pick_is_RSI1h_a2_share": float(R["null_pick_is_RSI1h_a2"].mean()),
    "obs_pick_five_mean_pb": float(m5_obs[ic]),
    "null_pick_five_mean_pb_q50_q95": [float(np.quantile(R["null_pick_five_mean_pb"], q_)) for q_ in (0.5, 0.95)],
    "p_pick_five_ge_obs": float((1 + (R["null_pick_five_mean_pb"] >= m5_obs[ic]).sum()) / (1 + B)),
    "obs_count_pos_sel_conf": int(((mS_obs > 0) & (mC_obs > 0) & elc_obs).sum()),
    "obs_count_pos_all3": int(((mS_obs > 0) & (mC_obs > 0) & (m5_obs > 0) & elc_obs).sum()),
    "null_count_pos_sel_conf_mean_q95": [float(R["null_count_pos_sel_conf"].mean()), float(np.quantile(R["null_count_pos_sel_conf"], 0.95))],
    "null_count_pos_all3_mean_P_ge1": [float(R["null_count_pos_all3"].mean()), float((R["null_count_pos_all3"] >= 1).mean())],
}

# 3. signal-level coin flip for the cell alone
tf, htf, T, Ot, X = O.parse(CELL)
cf = {}
rng2 = np.random.default_rng(99)
for p in ("SEL", "CONF", "FIVE", "PRE"):
    Rr = O.rows(D, tf, htf, T, Ot, X, p)
    roe = Rr["roe"] + PAYBACK * O.LEVX[X]
    opp = Rr["opp"] + PAYBACK * O.LEVX[X]
    sims = np.empty(20000)
    for j in range(0, 20000, 2000):
        z = rng2.random((2000, len(roe))) < 0.5
        sims[j:j + 2000] = np.where(z, roe, opp).mean(1)
    cf[p] = {"n": int(len(roe)), "obs_mean_pb": float(roe.mean()), "coinflip_mean_pb_expected": float(((roe + opp) / 2).mean()),
             "coinflip_q95": float(np.quantile(sims, 0.95)), "p_coinflip_ge_obs": float((1 + (sims >= roe.mean()).sum()) / 20001),
             "mean_opp_pb": float(opp.mean())}
out["coinflip_signal_level"] = cf

# 4. per year and neighbours
Rr = O.rows(D, tf, htf, T, Ot, X, "FIVE")
yr = pd.to_datetime(Rr["day"].astype(np.int64) * DAY, unit="ms").year
dfy = pd.DataFrame({"y": yr, "roe": Rr["roe"], "opp": Rr["opp"]})
g = dfy.groupby("y").agg(n=("roe", "size"), mean=("roe", "mean"), opp=("opp", "mean"))
g["mean_pb"] = g["mean"] + PAYBACK * 30
out["per_year"] = {int(k): {kk: float(v) for kk, v in r.items()} for k, r in g.iterrows()}
for p in ("SEL", "CONF", "FIVE"):
    Rt = O.rows(D, tf, None, None, Ot, X, p, timing_only=True)
    Rto = O.rows(D, tf, htf, T, None, X, p, trend_only=True)
    out[f"controls_{p}_pb"] = {"timing_only_RSI1h_a2": float(Rt["roe"].mean() + PAYBACK * 30), "timing_only_n": int(len(Rt["roe"])),
                               "trend_only_OBV20_4h_a2": float(Rto["roe"].mean() + PAYBACK * 30)}
nb = {}
for i in np.flatnonzero(rsi1h_a2):
    nb[ids[i]] = {p: [int(obs[(p, 'pb')][0][i]), round(float(obs[(p, 'pb')][1][i]), 4)] for p in ("SEL", "CONF", "FIVE")}
out["RSI1h_a2_neighbours_pb"] = nb
json.dump(out, open(os.path.join(HERE, "vluck.json"), "w"), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
