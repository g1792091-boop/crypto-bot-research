"""Adversarial luck / multiple-testing check of the claim
  'gross ~0 per trade, cost ~3.9 ROE pts, payback 2.4, October edge = falling market, x6 only if October repeats'.
Reads only ../trades/trades_<v>.csv.gz (the study's own outputs). Independent re-implementation (no lb_core import).
Run: python3 lm_goal_luck.py <trades_dir> <out_dir>"""
import os
import sys

import numpy as np
import pandas as pd
import numba

TD, OUT = sys.argv[1], sys.argv[2]
DAY = 86_400_000
V = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "W0", "W3"]
COST = 2 * (0.00042 + 0.0002)
PAYBACK = 2 * 0.9 * 0.00042


def lev(coin):
    return np.where(np.asarray(coin) == 0, 40.0, 30.0)


def bh(p):
    p = np.asarray(p, float); m = len(p); o = np.argsort(p)
    adj = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
    q = np.empty(m); q[o] = np.minimum(adj, 1); return q


T = {v: pd.read_csv(os.path.join(TD, f"trades_{v}.csv.gz")) for v in V}
POOLS = {"select": ["select"], "conf+late": ["confirm", "late"], "fwd": ["fwd"]}
rng = np.random.default_rng(7)

# ------------------------------------------------------------- A. gross / cost / payback, day-block CI, coin-flip null
rowsA = []
for v in V:
    for pn, per in POOLS.items():
        P = T[v][T[v].period.isin(per)]
        L = lev(P.coin)
        net, opp = P.tb_roe.to_numpy(), P.tb_opp_roe.to_numpy()
        cost = COST * L
        gross = net + cost
        flip = (net + opp) / 2 + cost                     # expected gross with a fair coin for the side
        d = (P.t.to_numpy() // DAY)
        ud, inv = np.unique(d, return_inverse=True)
        sg = np.bincount(inv, gross, len(ud)); n = np.bincount(inv, minlength=len(ud))
        sd = np.bincount(inv, net - opp, len(ud))
        B = rng.integers(0, len(ud), (4000, len(ud)))
        gb = sg[B].sum(1) / n[B].sum(1)
        db = sd[B].sum(1) / n[B].sum(1)
        # day-level sign flip of (own - opp): p(own side beats coin) one-sided
        S = rng.choice([-1.0, 1.0], (4000, len(ud)))
        null = (S * sd).sum(1) / n.sum()
        obs = (net - opp).mean()
        rowsA.append({"v": v, "pool": pn, "n": len(P), "net": 100 * net.mean(), "cost": 100 * cost.mean(),
                      "payback": 100 * (PAYBACK * L).mean(), "gross": 100 * gross.mean(),
                      "gross_lo": 100 * np.quantile(gb, .025), "gross_hi": 100 * np.quantile(gb, .975),
                      "gross_coinflip": 100 * flip.mean(), "own_minus_opp": 100 * obs,
                      "p_own_beats_coin": (null >= obs).mean(), "net_payback": 100 * (net + PAYBACK * L).mean(),
                      "p_gross_le0": (gb <= 0).mean()})
A = pd.DataFrame(rowsA)
for pn in POOLS:
    m = A.pool == pn
    A.loc[m, "q_own_beats_coin_13"] = bh(A.loc[m, "p_own_beats_coin"])
    A.loc[m, "q_gross_gt0_13"] = bh(A.loc[m, "p_gross_le0"])
A.to_csv(os.path.join(OUT, "lm_gross.csv"), index=False, float_format="%.4f")
pd.set_option("display.width", 250)
print(A.round(3).to_string(index=False))

# ------------------------------------------------------------- B. whole-search max-statistic permutation (joint flips)
# flip key = (coin, UTC day): every variant's trades on that coin-day get the same random side flip
for pn in ["conf+late", "select"]:
    Ds = []
    keys = []
    for v in V:
        P = T[v][T[v].period.isin(POOLS[pn])]
        k = P.coin.to_numpy().astype(np.int64) * 10_000_000 + P.t.to_numpy() // DAY
        Ds.append((P.tb_roe - P.tb_opp_roe).to_numpy()); keys.append(k)
    uk = np.unique(np.concatenate(keys))
    idx = [np.searchsorted(uk, k) for k in keys]
    sums = [np.bincount(i, d, len(uk)) for i, d in zip(idx, Ds)]
    ns = [len(d) for d in Ds]
    obs = np.array([d.mean() for d in Ds])
    sdv = np.array([np.sqrt((np.bincount(i, d, len(uk)) ** 2).sum()) / len(d) for i, d in zip(idx, Ds)])
    zobs = obs / sdv
    NP = 4000
    zmax = np.empty(NP)
    for b in range(NP):
        s = rng.choice([-1.0, 1.0], len(uk))
        z = np.array([(s * sm).sum() / n for sm, n in zip(sums, ns)]) / sdv
        zmax[b] = z.max()
    print(pn, "own-opp z per variant:", dict(zip(V, np.round(zobs, 2))))
    print(pn, "best variant z=%.2f (%s); whole-search P(max z >= best) = %.4f" %
          (zobs.max(), V[int(zobs.argmax())], (zmax >= zobs.max()).mean()))
    print(pn, "family-wise adjusted p per variant:", dict(zip(V, [round((zmax >= z).mean(), 3) for z in zobs])))

# ------------------------------------------------------------- C. October: market direction vs timing
rowsC = []
NP = 20000
for v in V:
    P = T[v][T[v].period == "fwd"]
    own, opp, side = P.tb_roe.to_numpy(), P.tb_opp_roe.to_numpy(), P.side.to_numpy()
    shortr = np.where(side < 0, own, opp); longr = np.where(side > 0, own, opp)
    n, ns = len(P), int((side < 0).sum())
    # matched short share: shuffle which trades are short, same count
    perm = np.empty(NP)
    for b in range(NP):
        sh = np.zeros(n, bool); sh[rng.choice(n, ns, replace=False)] = True
        perm[b] = np.where(sh, shortr, longr).mean()
    coin = np.empty(NP)
    for b in range(NP):
        coin[b] = np.where(rng.random(n) < .5, shortr, longr).mean()
    rnd = ((own + opp) / 2).mean()
    rowsC.append({"v": v, "n": n, "short_share": ns / n, "own": 100 * own.mean(), "opp": 100 * opp.mean(),
                  "always_short": 100 * shortr.mean(), "always_long": 100 * longr.mean(),
                  "coinflip_mean": 100 * rnd, "matched_share_mean": 100 * perm.mean(),
                  "edge_vs_coin": 100 * (own.mean() - rnd),
                  "short_bias_part": 100 * (perm.mean() - rnd), "timing_part": 100 * (own.mean() - perm.mean()),
                  "p_timing": (perm >= own.mean()).mean(), "p_vs_coin": (coin >= own.mean()).mean(),
                  "se_per_trade": 100 * own.std(ddof=1) / np.sqrt(n)})
C = pd.DataFrame(rowsC)
C["q_timing_13"] = bh(C.p_timing); C["q_vs_coin_13"] = bh(C.p_vs_coin)
C.to_csv(os.path.join(OUT, "lm_october.csv"), index=False, float_format="%.4f")
print(C.round(3).to_string(index=False))


# ------------------------------------------------------------- D. goal bootstrap, independent (numba), + luck null
@numba.njit(cache=True)
def boot(roe, dstart, dcount, nd, margin, horizon, nb, seed, target):
    np.random.seed(seed)
    hit = 0; l50 = 0; l90 = 0
    fin = np.empty(nb)
    for b in range(nb):
        eq = 1.0; half = False; done = False
        for _ in range(horizon):
            di = np.random.randint(0, nd)
            for j in range(dstart[di], dstart[di] + dcount[di]):
                eq *= 1.0 + margin * roe[j]
                if not done:
                    if eq >= target:
                        hit += 1; done = True
                    else:
                        if eq <= 0.5 and not half:
                            l50 += 1; half = True
                        if eq <= 0.1:
                            l90 += 1; done = True
        fin[b] = eq
    return hit / nb, l50 / nb, l90 / nb, np.median(fin)


def prep(P, roe, a_day, b_day):
    o = np.argsort(P.t.to_numpy(), kind="stable")
    d = (P.t.to_numpy()[o] // DAY) - a_day
    nd = int(b_day - a_day + 1)
    cnt = np.bincount(d, minlength=nd)[:nd]
    st = np.concatenate([[0], np.cumsum(cnt)[:-1]])
    return np.ascontiguousarray(roe[o]), st.astype(np.int64), cnt.astype(np.int64), nd


def ms(s):
    return int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)


RANGE = {"conf+late": (ms("2024-01-01") // DAY, (ms("2026-10-05 15:00") - 1) // DAY),
         "fwd": (ms("2026-10-05 15:00") // DAY, (ms("2026-10-24 15:00") - 1) // DAY)}
rowsD = []
for v in V:
    for pn in ["conf+late", "fwd"]:
        P = T[v][T[v].period.isin(POOLS[pn])]
        L = lev(P.coin)
        for pb in (False, True):
            r = np.maximum(P.tb_roe.to_numpy() + (PAYBACK * L if pb else 0), -1.0)
            for mg in (0.4, 0.6, 1.0):
                x = prep(P, r, *RANGE[pn])
                h, a50, a90, med = boot(x[0], x[1], x[2], x[3], mg, 30, 20000, 11, 6.0)
                rowsD.append({"v": v, "pool": pn, "payback": pb, "margin": mg, "n": len(P), "days": x[3],
                              "p_x6": h, "p_l50": a50, "p_l90": a90, "median": med})
D = pd.DataFrame(rowsD)
D.to_csv(os.path.join(OUT, "lm_goal.csv"), index=False, float_format="%.4f")
print(D[(D.margin == 0.4) & D.payback].round(4).to_string(index=False))
print("max P(x6) over 13 variants, Oct, payback, m=0.4:",
      D[(D.pool == "fwd") & D.payback & (D.margin == 0.4)].p_x6.max())
print("max P(x6) 2024-26 any margin, payback:", D[(D.pool == "conf+late") & D.payback].sort_values("p_x6").tail(3)
      .round(4).to_string(index=False))
print("max P(x6) Oct no payback:", D[(D.pool == "fwd") & ~D.payback].sort_values("p_x6").tail(4)
      .round(4).to_string(index=False))

# luck null for October goal: same entries, sides shuffled with the same short count; P(x6) distribution
rowsE = []
for v in ["B3", "B6", "B0", "W3"]:
    P = T[v][T[v].period == "fwd"]
    L = lev(P.coin)
    own, opp, side = P.tb_roe.to_numpy(), P.tb_opp_roe.to_numpy(), P.side.to_numpy()
    shortr = np.where(side < 0, own, opp) + PAYBACK * L; longr = np.where(side > 0, own, opp) + PAYBACK * L
    n, ns = len(P), int((side < 0).sum())
    ps = []
    for b in range(300):
        sh = np.zeros(n, bool); sh[rng.choice(n, ns, replace=False)] = True
        r = np.maximum(np.where(sh, shortr, longr), -1.0)
        x = prep(P, r, *RANGE["fwd"])
        ps.append(boot(x[0], x[1], x[2], x[3], 0.4, 30, 3000, 100 + b, 6.0)[0])
    ps = np.array(ps)
    x = prep(P, np.maximum(shortr, -1.0), *RANGE["fwd"])
    allshort = boot(x[0], x[1], x[2], x[3], 0.4, 30, 20000, 5, 6.0)
    rowsE.append({"v": v, "matched_short_shuffle_Px6_median": np.median(ps), "p10": np.quantile(ps, .1),
                  "p90": np.quantile(ps, .9), "always_short_Px6": allshort[0], "always_short_l50": allshort[1]})
E = pd.DataFrame(rowsE)
E.to_csv(os.path.join(OUT, "lm_october_goal_null.csv"), index=False, float_format="%.4f")
print(E.round(4).to_string(index=False))
