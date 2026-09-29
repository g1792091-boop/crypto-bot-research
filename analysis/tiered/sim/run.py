"""Planted-edge single-account simulation for one TF: user tiered rule vs references vs recommended risk policy.

Output out/<tf>.npz:
  LR   (ncase, S, ND) float32  daily sum of log equity factors (trades bucketed by exit day)
  DMIN (ncase, S, ND) float32  intraday min of cumulative log equity within the day, relative to day start (<= 0)
  FEE  (ncase, S, ND) float32  daily sum of costs (fees + slippage + funding) as a fraction of equity at trade entry
  ST   (ncase, S, nstat)       per-chain trade statistics
  CAL  (nscen, S, 4)           calibration: mean side*r_he over ALL candidates, top-10 %, rest, and q mean
out/<tf>_meta.json: cases, scenarios, stat names, edge horizon, E|r_he| per coin, runtime.
"""
import argparse, json, os, time
import numpy as np
from lib import *

ap = argparse.ArgumentParser()
ap.add_argument("--tf", required=True)
ap.add_argument("--seeds", type=int, default=40)
ap.add_argument("--fine", type=int, default=0)       # 1 = resolve exits on 5m sub-bars (15m/1h/4h)
ap.add_argument("--tag", default="")
ap.add_argument("--he", type=int, default=0)         # >0: force the edge horizon (fine runs reuse the TF-bar run's h_e)
args = ap.parse_args()
t0 = time.time()
P = Panel(args.tf, fine=bool(args.fine))
TFM_EXIT = 5 if P.fine else P.tfm                     # bar length used by exits() for funding
tfm, ND, S = P.tfm, P.ndays, args.seeds
DAY = 86400 * 10**9

# ------------------------------------------------------------------ edge horizon (measured, not chosen):
# mean holding time of the user's NORMAL trade (20x, 1.5 ATR stop, TP +10 % ROE, 64-bar time exit, adverse-first)
# on random-side entries, seed 0.  Planted drift is defined on the forward return entry(open t+1) -> close(t+he).
rng = np.random.default_rng([tfm, 0, 4242])
gi, ci, ti = P.draw_candidates(rng)
pp = P.paths(ci, ti, 1)
hold = []
for sg in (1, -1):
    k, *_ = exits(prep_moves(pp, sg), 20.0, 1.5 * pp["atr"], np.full(len(gi), 0.10 / 20), TFM_EXIT, "adv")
    hold.append((k.astype(np.int64) - 1) // P.m + 1)
HE = max(1, int(round(float(np.mean(np.concatenate(hold))))))
HE_MEASURED = HE
if args.he > 0:
    HE = args.he
Eabs = P.fwd_abs(HE)
Eab = np.array([Eabs[c] for c in COINS])
del pp

# ------------------------------------------------------------------ scenarios
CONC_TOP, CONC_REST = 3.0, (1.0 - 0.1 * 3.0) / 0.9          # top-10 % gets 3x the average q; the other 90 % 0.778x
SCEN = [("S0", 0.0, False), ("S1", 0.0005, False), ("S2", 0.0010, False), ("S3", 0.0005, True), ("S4", 0.0010, True)]
GRID = [0.00025, 0.0005, 0.00075, 0.0010, 0.00125, 0.0015, 0.0020, 0.0025, 0.0030, 0.0040, 0.0050, 0.0060, 0.0080, 0.0100]
for D in GRID:
    if D / Eab.min() <= 1.0:
        SCEN.append((f"U{D*100:.3f}", D, False))
for D in GRID:
    if CONC_TOP * D / Eab.min() <= 1.0:
        SCEN.append((f"C{D*100:.3f}", D, True))
NAMED = 5
POL = ["tiered", "flat20", "max50", "rec"]
EXITS = [("1.5", "roe"), ("1.5", "2x"), ("1.0", "roe"), ("1.0", "2x")]
ORD = ["adv", "fav"]
CASES = []   # (scen_idx, pol, stop, tp, order)
for si, sc in enumerate(SCEN):
    if si < NAMED:
        for p in POL:
            for st, tp in EXITS:
                for o in ORD:
                    CASES.append((si, p, st, tp, o))
    else:
        for p in POL:
            for o in ORD:
                CASES.append((si, p, "1.5", "roe", o))
NCASE = len(CASES)
STN = ["n", "n_liq", "n_tp", "n_stop", "n_time", "sum_g", "sum_drift", "sum_r", "sum_lr", "sum_fee", "sum_N", "sum_hold",
       "n_t0", "n_t1", "n_t2", "liq_t0", "liq_t1", "liq_t2", "g_t0", "g_t1", "g_t2", "drift_t0", "drift_t1", "drift_t2",
       "n_win", "min_cum", "mdd"]
NST = len(STN)
LR = np.zeros((NCASE, S, ND), np.float32)
DMIN = np.zeros((NCASE, S, ND), np.float32)
FEEA = np.zeros((NCASE, S, ND), np.float32)
ST = np.zeros((NCASE, S, NST))
CAL = np.zeros((len(SCEN), S, 6))
print(f"{args.tf}: HE={HE} bars  E|r_he| {Eab.min()*100:.3f}-{Eab.max()*100:.3f}%  scen={len(SCEN)} cases={NCASE} "
      f"load {time.time()-t0:.1f}s", flush=True)

LS = [10.0, 20.0, 30.0, 50.0]
LSA = np.array(LS)

for s in range(S):
    rng = np.random.default_rng([tfm, s, 20260929])
    gi, ci, ti = P.draw_candidates(rng)
    n = len(gi)
    u = rng.random(n)
    rs = np.where(rng.random(n) < 0.5, 1, -1)
    score = rng.random(n)
    tier = (score >= TIER_CUT[0]).astype(np.int64) + (score >= TIER_CUT[1]).astype(np.int64)
    pp = P.paths(ci, ti, HE)
    atr = pp["atr"]
    orc = np.sign(pp["rhe"]).astype(np.int64)
    orc = np.where(orc == 0, rs, orc)
    cand_ts = P.grid[gi]
    ar = np.arange(n)
    mv = {0: prep_moves(pp, 1), 1: prep_moves(pp, -1)}
    # outcomes: OUT[(stop, tp, order)] = arrays (4 L, 2 sides, n)
    OUT = {}
    for st, tp in EXITS:
        sd = float(st) * atr
        for o in ORD:
            K = np.empty((4, 2, n), np.int16); CC = np.empty((4, 2, n), np.int8)   # K: exit offset (5m bars if fine)
            G = np.empty((4, 2, n), np.float32); CO = np.empty((4, 2, n), np.float32); Y = np.empty((4, 2, n), np.float32)
            for li, L in enumerate(LS):
                td = np.full(n, 0.10 / L) if tp == "roe" else np.maximum(0.10 / L, 2.0 * sd)
                for sx in (0, 1):
                    K[li, sx], CC[li, sx], G[li, sx], CO[li, sx], Y[li, sx] = exits(mv[sx], L, sd, td, TFM_EXIT, o)
            OUT[(st, tp, o)] = (K, CC, G, CO, Y)
    del mv
    # sizing per policy x stop
    SIZ = {}
    for st in ("1.5", "1.0"):
        sd = float(st) * atr
        SIZ[("tiered", st)] = (USER_L[tier], USER_M[tier] * USER_L[tier], USER_M[tier])
        SIZ[("flat20", st)] = (np.full(n, 20.0), np.full(n, 4.0), np.full(n, 0.2))
        SIZ[("max50", st)] = (np.full(n, 50.0), np.full(n, 20.0), np.full(n, 0.4))
        Nr = np.minimum(REC_RISK[tier] / sd, REC_NCAP)
        SIZ[("rec", st)] = (np.full(n, REC_L), Nr, Nr / REC_L)
    for si, (nm, D, conc) in enumerate(SCEN):
        qb = D / Eab[ci]
        q = qb * np.where(tier == 2, CONC_TOP, CONC_REST) if conc else qb
        q = np.minimum(q, 1.0)
        side = np.where(u < q, orc, rs)
        sidx = (side < 0).astype(np.int64)
        drift = side * pp["rhe"]
        top = tier == 2
        CAL[si, s] = [drift.mean(), drift[top].mean(), drift[~top].mean(), q.mean(), q[top].mean(), q[~top].mean()]
        for cj, (csi, pol, st, tp, o) in enumerate(CASES):
            if csi != si:
                continue
            Lv, Nv, Mv = SIZ[(pol, st)]
            li = np.searchsorted(LSA, Lv)
            K, CC, G, CO, Y = OUT[(st, tp, o)]
            k = K[li, sidx, ar]; cc = CC[li, sidx, ar]; g = G[li, sidx, ar]; co = CO[li, sidx, ar]; y = Y[li, sidx, ar]
            r = np.maximum(Nv * y, -0.9999)
            fee = Nv * co
            exit_ts = pp["tsb"][ar, k.astype(np.int64) - 1]
            tk = chase_one(cand_ts, exit_ts)
            lr = np.log1p(r[tk])
            day = np.clip((exit_ts[tk] - P.day0) // DAY, 0, ND - 1).astype(np.int64)
            LR[cj, s] = np.bincount(day, weights=lr, minlength=ND)
            FEEA[cj, s] = np.bincount(day, weights=fee[tk], minlength=ND)
            cum = np.cumsum(lr)
            gs = np.r_[0, np.nonzero(np.diff(day))[0] + 1]
            before = cum[gs] - lr[gs]
            gmin = np.minimum.reduceat(cum, gs) - before
            dm = np.zeros(ND); dm[day[gs]] = np.minimum(gmin, 0.0)
            DMIN[cj, s] = dm
            cct = cc[tk]; tt = tier[tk]; gt = g[tk]; dt = drift[tk]
            runmax = np.maximum.accumulate(np.r_[0.0, cum])[1:]
            v = [len(tk), (cct == 3).sum(), (cct == 1).sum(), (cct == 2).sum(), (cct == 4).sum(), gt.sum(), dt.sum(),
                 r[tk].sum(), lr.sum(), fee[tk].sum(), Nv[tk].sum(), ((k[tk].astype(np.int64) - 1) // P.m + 1).sum()]
            v += [(tt == j).sum() for j in range(3)] + [((tt == j) & (cct == 3)).sum() for j in range(3)]
            v += [gt[tt == j].sum() for j in range(3)] + [dt[tt == j].sum() for j in range(3)]
            v += [(r[tk] > 0).sum(), min(cum.min(), 0.0), (runmax - cum).max()]
            ST[cj, s] = v
    del OUT
    if s % 5 == 0 or s == S - 1:
        c0 = CASES.index((0, "tiered", "1.5", "roe", "adv"))
        print(f"  seed {s} n_cand={n} taken(tiered S0 base)={int(ST[c0, s, 0])} liq={int(ST[c0, s, 1])} "
              f"t={time.time()-t0:.0f}s", flush=True)

os.makedirs("out", exist_ok=True)
TAG = args.tf + args.tag
np.savez(os.path.join("out", f"{TAG}.npz"), LR=LR, DMIN=DMIN, FEE=FEEA, ST=ST, CAL=CAL)
meta = dict(tf=args.tf, tfm=tfm, HE=HE, Eabs=Eabs, S=S, ND=ND, lam=P.lam, scen=SCEN, cases=CASES, stn=STN,
            conc=[CONC_TOP, CONC_REST], runtime_s=time.time() - t0)
meta["fine"] = P.fine
meta["HE_measured_this_run"] = HE_MEASURED
json.dump(meta, open(os.path.join("out", f"{TAG}_meta.json"), "w"), indent=0)
print("done", args.tf, f"{time.time()-t0:.0f}s", flush=True)
