"""Run the single-account planted-edge simulation for one TF.

Output: out/<tag>/<tf>_daily.npy  (E, C, S, D) float32 daily sum of log equity factors
        out/<tag>/<tf>_dmin.npy   (E, C, S, D) float32 intraday min of cumulative log (<= 0)
        out/<tag>/<tf>_stats.npz  per (E, C, S) trade statistics
        out/<tag>/<tf>_meta.json
"""
import argparse, json, os, time
import numpy as np
from simlib import *

ap = argparse.ArgumentParser()
ap.add_argument("--tf", required=True)
ap.add_argument("--seeds", type=int, default=100)
ap.add_argument("--wick", default="raw")
ap.add_argument("--order", default="heur")        # heur = O-L-H-C / O-H-L-C by bar colour; adv = adverse first always
ap.add_argument("--tag", default="base")
ap.add_argument("--combos", default="all")
ap.add_argument("--cost", default="taker")      # taker = market entry 0.07 %; maker = limit entry 0.02 % (optimistic: always filled)
ap.add_argument("--subbar", type=int, default=0)   # 1 = resolve exits on 5m sub-bars
ap.add_argument("--edge_h", type=int, default=0)   # 0 = plant the edge at H; >0 = at edge_h bars (front-loaded)
args = ap.parse_args()

def combo_list(which):
    C = []
    for P in ["P0", "P1", "P2"]:
        for st in "ABC":
            C.append(f"{P}|{st}|10")
    for P in ["P3", "P4", "P5"]:
        for tp in ["10", "30", "100"]:
            for st in "ABC":
                C.append(f"{P}|{st}|{tp}")
    C += ["P6|B|none", "P6h|B|none", "P6|B|10"]
    # P5c: P5 leverage rule, margin 40 % on trades that carry the planted information and 20 % otherwise
    # (a perfect 'chart confidence' signal inside the user's 20-40 % bounds; an upper bound, not a real strategy)
    C += ["P5c|A|10", "P5c|B|10", "P5c|C|10"]
    if which == "user":
        C = [c for c in C if c.split("|")[0] in ("P0", "P3", "P4", "P5", "P6") and c.split("|")[2] in ("10", "none")]
    return C

COMBOS = combo_list(args.combos)
import simlib
if args.cost == "maker":
    simlib.C_IN = simlib.FEE_M
t0 = time.time()
P = Panel(args.tf, wick=args.wick, edge_h=args.edge_h, subbar=bool(args.subbar))
tfm, H = P.tfm, P.H
outdir = os.path.join("out", args.tag); os.makedirs(outdir, exist_ok=True)

# edge calibration: per-coin q_c = D / E_c|r_H|, feasible iff q_c <= 1 for all coins
Eabs = np.array([P.Eabs[c] for c in COINS])
EDG = [D for D in EDGES if D / Eabs.min() <= 1.0]
qmat = np.array([[D / e for e in Eabs] for D in EDG])      # (E, 7)
nE, nC, S, ND = len(EDG), len(COMBOS), args.seeds, P.ndays
print(f"{args.tf}: H={H} lam={P.lam:.3f}/day grid={len(P.grid)} edges={EDG} combos={nC} load {time.time()-t0:.1f}s", flush=True)

daily = np.zeros((nE, nC, S, ND), dtype=np.float32)
dmin = np.zeros((nE, nC, S, ND), dtype=np.float32)
stat_names = ["n", "n_liq", "n_tp", "n_stop", "n_time", "sum_g", "sum_y", "sum_r", "n_win", "sum_drift", "sum_N", "sum_M",
              "sum_L", "sum_log", "min_log", "mdd_log", "sum_y2", "sum_hold"]
ST = np.zeros((len(stat_names), nE, nC, S))
DAY_NS = 86400 * 10**9
BIG = 1e4
# pooled per-trade net-per-notional returns for the reference exit (P0|B|10 ~ 1.5 ATR stop + time exit) -> Kelly scan
kelly_y = {e: [] for e in range(nE)}
kref = COMBOS.index("P0|B|10")
P5C = [j for j, c in enumerate(COMBOS) if c.startswith("P5c|")]

for s in range(S):
    rng = np.random.default_rng([tfm, s, 20260929])
    gi, ci, ti = P.draw_candidates(rng)
    n = len(gi)
    u = rng.random(n)
    rs = np.where(rng.random(n) < 0.5, 1, -1)
    pp = P.paths(ci, ti)
    orc = np.sign(pp["rH"]).astype(np.int64)
    orc = np.where(orc == 0, rs, orc)
    cand_ts = P.grid[gi]
    # outcomes for both sides x all combos
    K = np.empty((2, nC, n), dtype=np.int64); CC = np.empty((2, nC, n), dtype=np.int8)
    G = np.empty((2, nC, n)); R = np.empty((2, nC, n)); Y = np.empty((2, nC, n))
    NN = np.empty((nC, n)); MM = np.empty((nC, n)); LL = np.empty((nC, n))
    for j, cname in enumerate(COMBOS):
        M_, L_, N_, dl, sd, td = policy_params(cname.replace("P5c|", "P5|"), pp["atr"])
        NN[j], MM[j], LL[j] = N_, M_, L_
        for si, sgn in enumerate((1, -1)):
            k, cc, gg, r, y = outcomes(pp, np.full(n, sgn), M_, L_, N_, dl, sd, td, P.path_tfm,
                                       adverse_first_all=("fav" if args.order == "fav" else args.order == "adv"))
            K[si, j], CC[si, j], G[si, j], R[si, j], Y[si, j] = k, cc, gg, r, y
    for e in range(nE):
        q = qmat[e][ci]
        side = np.where(u < q, orc, rs)
        sidx = (side < 0).astype(np.int64)                 # 0 -> long outcomes, 1 -> short outcomes
        ar = np.arange(n)
        k_e = K[sidx, :, ar].T                              # (nC, n)
        cc_e = CC[sidx, :, ar].T
        g_e = G[sidx, :, ar].T
        r_e = R[sidx, :, ar].T
        MM_e = MM.copy(); NN_e = NN.copy()
        if P5C:
            Mnew = np.where(u < q, 0.40, 0.20)
            for j in P5C:
                r_e[j] = r_e[j] * Mnew / MM[j]           # equity return is linear in M at fixed L (incl. liquidation)
                NN_e[j] = NN[j] * Mnew / MM[j]; MM_e[j] = Mnew
        r_e = np.maximum(r_e, -0.999999)
        y_e = Y[sidx, :, ar].T
        exit_ts = pp["ts_bar"][ar[None, :], k_e - 1]          # (nC, n)
        taken = chase(cand_ts, exit_ts)                      # (nC, n)
        b_idx, i_idx = np.nonzero(taken)
        lr = np.log1p(r_e[b_idx, i_idx])
        day = ((exit_ts[b_idx, i_idx] - P.day0) // DAY_NS).astype(np.int64)
        day = np.clip(day, 0, ND - 1)
        # daily sums
        key = b_idx * ND + day
        dsum = np.bincount(key, weights=lr, minlength=nC * ND).reshape(nC, ND)
        daily[e, :, s, :] = dsum
        # cumulative per chain
        cum = np.cumsum(lr)
        starts_chain = np.r_[0, np.nonzero(np.diff(b_idx))[0] + 1]
        chain_off = np.zeros(len(lr))
        off = cum[starts_chain] - lr[starts_chain]
        chain_id_run = np.repeat(np.arange(len(starts_chain)), np.diff(np.r_[starts_chain, len(lr)]))
        cumc = cum - off[chain_id_run]
        # intraday min per (chain, day)
        gstart = np.r_[0, np.nonzero(np.diff(key))[0] + 1]
        before = cumc[gstart] - lr[gstart]
        gmin = np.minimum.reduceat(cumc, gstart) - before
        dm = np.zeros(nC * ND); dm[key[gstart]] = np.minimum(gmin, 0.0)
        dmin[e, :, s, :] = dm.reshape(nC, ND)
        # stats per chain
        chains = b_idx[starts_chain]
        def per_chain(v, fn=np.add):
            out = np.zeros(nC)
            out[chains] = fn.reduceat(v, starts_chain)
            return out
        ones = np.ones(len(lr))
        ccv = cc_e[b_idx, i_idx]
        ST[0, e, :, s] = per_chain(ones)
        ST[1, e, :, s] = per_chain((ccv == 3).astype(float))
        ST[2, e, :, s] = per_chain((ccv == 1).astype(float))
        ST[3, e, :, s] = per_chain((ccv == 2).astype(float))
        ST[4, e, :, s] = per_chain((ccv == 4).astype(float))
        ST[5, e, :, s] = per_chain(g_e[b_idx, i_idx])
        ST[6, e, :, s] = per_chain(y_e[b_idx, i_idx])
        ST[7, e, :, s] = per_chain(r_e[b_idx, i_idx])
        ST[8, e, :, s] = per_chain((r_e[b_idx, i_idx] > 0).astype(float))
        ST[9, e, :, s] = per_chain(side[i_idx] * pp["rH"][i_idx])
        ST[10, e, :, s] = per_chain(NN_e[b_idx, i_idx])
        ST[11, e, :, s] = per_chain(MM_e[b_idx, i_idx])
        ST[12, e, :, s] = per_chain(LL[b_idx, i_idx])
        ST[13, e, :, s] = per_chain(lr)
        ST[14, e, :, s] = np.minimum(per_chain(cumc, np.minimum), 0.0)
        rm = np.maximum(np.maximum.accumulate(cumc + b_idx * BIG) - b_idx * BIG, 0.0)
        ST[15, e, :, s] = per_chain(rm - cumc, np.maximum)
        ST[16, e, :, s] = per_chain(y_e[b_idx, i_idx] ** 2)
        ST[17, e, :, s] = per_chain(k_e[b_idx, i_idx].astype(float))
        # Kelly reference sample (net per unit notional, reference exit)
        m = b_idx == kref
        kelly_y[e].append(y_e[kref, i_idx[m]].astype(np.float32))
    if s % 10 == 0 or s == S - 1:
        print(f"  seed {s} n_cand={n} taken(P3|A|10,e0)={int(ST[0,0,COMBOS.index('P3|A|10'),s])} t={time.time()-t0:.0f}s", flush=True)

np.save(os.path.join(outdir, f"{args.tf}_daily.npy"), daily)
np.save(os.path.join(outdir, f"{args.tf}_dmin.npy"), dmin)
np.savez_compressed(os.path.join(outdir, f"{args.tf}_stats.npz"), ST=ST, names=np.array(stat_names),
                    **{f"kelly_y_{e}": np.concatenate(kelly_y[e]) for e in range(nE)})
meta = dict(tf=args.tf, H=H, lam=P.lam, tfm=tfm, edges=EDG, combos=COMBOS, seeds=S, ndays=ND, wick=args.wick,
            order=args.order, edge_h=args.edge_h, subbar=args.subbar, cost=args.cost, C_IN=simlib.C_IN, Eabs={c: P.Eabs[c] for c in COINS}, Eabs_pooled=P.Eabs_pooled,
            atr_med={c: P.atr_med[c] for c in COINS}, q=qmat.tolist(), runtime_s=time.time() - t0)
json.dump(meta, open(os.path.join(outdir, f"{args.tf}_meta.json"), "w"), indent=1)
print("done", args.tf, f"{time.time()-t0:.0f}s")
