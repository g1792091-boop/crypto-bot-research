"""Adversarial check (luck / multiple testing) of the claim: 'the 7 extra checks make the bot's direction significantly
worse than a coin flip (B0 own -4.39 vs opposite -2.26, p 0.003, q13 0.039; B2 q 0.046; B3 gap only -0.48)' and
'보류 entries are 38-39% of the bot's trades'.
Reads only ../trades/trades_<v>.csv.gz (the study's own taken trades, with the paired opposite-side outcome).
Run: python3 vdir_luck.py <trades_dir>"""
import os
import sys

import numpy as np
import pandas as pd

TD = sys.argv[1]
DAY = 86_400_000
V = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "W0", "W3"]
T = {v: pd.read_csv(os.path.join(TD, f"trades_{v}.csv.gz")) for v in V}
for v in V:
    T[v]["d"] = T[v].tb_roe - T[v].tb_opp_roe


def bh(p):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)
    adj = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
    q = np.empty(m)
    q[o] = np.minimum(adj, 1)
    return q


def sub(df, per):
    return df[df.period.isin(per)]


def block_sums(dfs, bms, col="d"):
    blocks = [df.t.to_numpy() // bms for df in dfs]
    ub = np.unique(np.concatenate(blocks))
    S, C = [], []
    for df, b in zip(dfs, blocks):
        i = np.searchsorted(ub, b)
        S.append(np.bincount(i, df[col].to_numpy(), len(ub)))
        C.append(np.bincount(i, minlength=len(ub)))
    return np.array(S), np.array(C)


def boot_p(dfs, bms, n=20000, seed=11):
    """percentile block bootstrap (same as the study's day_boot): one-sided p(own better) = frac(boot mean <= 0)."""
    S, C = block_sums(dfs, bms)
    rng = np.random.default_rng(seed)
    nb = S.shape[1]
    out = []
    for k in range(len(dfs)):
        acc = np.empty(n)
        for s in range(0, n, 2000):
            pk = rng.integers(0, nb, (min(2000, n - s), nb))
            acc[s:s + len(pk)] = S[k][pk].sum(1) / np.maximum(C[k][pk].sum(1), 1)
        out.append(acc)
    return out


def signflip(dfs, bms, n=20000, seed=7):
    """Coin-flip null: flip own<->opposite for whole blocks (the SAME flips for every variant, so the 13 tests keep their
    dependence). Returns per-variant two-sided p, one-sided p(opp better), and the family-wise (max |z| over the
    variants) p for each variant."""
    S, C = block_sums(dfs, bms)
    nk = C.sum(1)
    obs = S.sum(1) / nk
    rng = np.random.default_rng(seed)
    sims = np.empty((n, len(dfs)))
    for s in range(0, n, 2000):
        m = min(2000, n - s)
        sg = rng.choice([-1.0, 1.0], (m, S.shape[1]))
        sims[s:s + m] = (sg @ S.T) / nk
    sd = sims.std(0)
    z = obs / sd
    zs = np.abs(sims / sd)
    p2 = (np.abs(sims) >= np.abs(obs)).mean(0)
    p_neg = (sims <= obs).mean(0)
    mx = zs.max(1)
    p_fw = np.array([(mx >= abs(z[k])).mean() for k in range(len(dfs))])
    return obs, z, p2, p_neg, p_fw


rows = []
WINDOWS = [("confirm+late", ["confirm", "late"]), ("select", ["select"]), ("confirm", ["confirm"]), ("late", ["late"]),
           ("all_2020-03_2026-10-05", ["select", "confirm", "late"])]
for wname, per in WINDOWS:
    dfs = [sub(T[v], per) for v in V]
    for bname, bms in [("day", DAY), ("week", 7 * DAY), ("month", 30 * DAY)]:
        bs = boot_p(dfs, bms)
        obs, z, p2, p_neg, p_fw = signflip(dfs, bms)
        p_boot_neg = np.array([(b > 0).mean() for b in bs])       # study's dir_neg_p = 1 - frac(<=0)
        q_boot_neg = bh(p_boot_neg)
        q_boot_two = bh(np.minimum(1, 2 * np.minimum(p_boot_neg, 1 - p_boot_neg)))
        q_flip_two = bh(p2)
        for k, v in enumerate(V):
            rows.append({"window": wname, "block": bname, "variant": v, "n": len(dfs[k]),
                         "own": dfs[k].tb_roe.mean(), "opp": dfs[k].tb_opp_roe.mean(), "gap": obs[k],
                         "boot_p_oppbetter": p_boot_neg[k], "boot_q13_oppbetter": q_boot_neg[k],
                         "boot_q13_twosided": q_boot_two[k], "flip_p_oppbetter": p_neg[k], "flip_p_two": p2[k],
                         "flip_q13_two": q_flip_two[k], "flip_fwer_maxz": p_fw[k], "z": z[k]})
R = pd.DataFrame(rows)
R.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vdir_luck.csv"), index=False, float_format="%.5g")
pd.set_option("display.width", 250)
show = R[R.variant.isin(["B0", "B1", "B2", "B3"])]
print(show.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

# ---- does removing the checks (B2 -> B3) significantly shrink the 'opposite is better' gap? joint block resampling
print("\nGap difference B3 - B2 and B3 - B0 (positive = removing checks makes direction less bad); joint resampling")
for wname, per in WINDOWS:
    for bname, bms in [("day", DAY), ("week", 7 * DAY), ("month", 30 * DAY)]:
        for a_, b_ in (("B2", "B3"), ("B0", "B3")):
            dfs = [sub(T[a_], per), sub(T[b_], per)]
            S, C = block_sums(dfs, bms)
            rng = np.random.default_rng(5)
            pk = rng.integers(0, S.shape[1], (10000, S.shape[1]))
            g = [S[k][pk].sum(1) / np.maximum(C[k][pk].sum(1), 1) for k in range(2)]
            diff = g[1] - g[0]
            ob = S[1].sum() / C[1].sum() - S[0].sum() / C[0].sum()
            print(f"{wname:24s} {bname:5s} {b_}-{a_}: gapdiff {100 * ob:+.2f}pt  p(<=0) {(diff <= 0).mean():.3f}  "
                  f"95% [{100 * np.quantile(diff, .025):+.2f}, {100 * np.quantile(diff, .975):+.2f}]")

# ---- 보류 share and the gap split inside B0
print("\nB0 trades: 보류 (j_dir==0) share and gap by period")
B0 = T["B0"]
for pn in ["select", "confirm", "late", "fwd", "oos1022"]:
    P = B0[B0.period == pn]
    if not len(P):
        continue
    H, W = P[P.j_dir == 0], P[P.j_dir != 0]
    print(f"{pn:8s} n {len(P):5d} hold share {len(H) / len(P):.3f} | hold own {100 * H.tb_roe.mean():+.2f} opp "
          f"{100 * H.tb_opp_roe.mean():+.2f} (n {len(H)}) | with-trend own {100 * W.tb_roe.mean():+.2f} opp "
          f"{100 * W.tb_opp_roe.mean():+.2f} (n {len(W)})")
for nm, per in [("2020-03..2026-10-05", ["select", "confirm", "late"]), ("confirm+late", ["confirm", "late"])]:
    P = sub(B0, per)
    print(nm, "hold share", round((P.j_dir == 0).mean(), 4), "n", len(P))
for v in ["B1", "B2"]:
    print(v, "hold share (should be 0):", round((T[v].j_dir == 0).mean(), 4))
