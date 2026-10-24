"""Verifier: how much of the a2 family TOP5 H2 number is 'being short in H2'?

1. always-short / always-long / follow-the-trend at every bar close of the base table (a2, H2) for 1h and 4h bars
2. short-matched control: for each picked cell, draw at random the same number of its OWN H2 signals with the same
   side mix (unfiltered by the trend source) -> pooled mean; repeated 20,000 times; share >= actual
Run: python3 rc_short.py"""
import os
import sys
import json

FW = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, FW)
from fw_lib import *  # noqa: F401,F403,E402

OUTD = os.path.dirname(os.path.abspath(__file__))


def main():
    out = {}
    B = load("base")
    h2b = (B.t.to_numpy() >= SPLIT)
    r = roe(B, "a2")
    ro = roe(B, "a2", True)
    side = B.side.to_numpy()
    for tf in ("15m", "1h", "4h"):
        m = (B.tf.to_numpy() == tf) & h2b & np.isfinite(r)
        # base rows carry one side per bar (side column); the opposite side outcome is *_opp
        rs = np.where(side[m] < 0, r[m], ro[m])     # short outcome
        rl = np.where(side[m] > 0, r[m], ro[m])     # long outcome
        o = {"n": int(m.sum()), "short": float(np.nanmean(rs)), "long": float(np.nanmean(rl)),
             "short_ci_day": day_boot_ci(rs, B.day.to_numpy()[m])}
        for src, htf in (("c_N07_ICHI_CMO", "4h"), ("c_T5_ST10_3", "1d"), ("Jlive", "1d"), ("l_OBV_S", "1d"),
                         ("Jdir", "4h")):
            if (tf, htf) not in (("1h", "4h"), ("4h", "1d"), ("15m", "4h")):
                continue
            st = state(B[m], src, htf)
            fol = np.where(st < 0, rs, np.where(st > 0, rl, np.nan))
            o[f"follow_{src}@{htf}"] = {"n": int(np.isfinite(fol).sum()), "mean": float(np.nanmean(fol)),
                                         "short_share": float(np.mean(st[st != 0] < 0)) if (st != 0).any() else None}
        out[f"base_{tf}_H2"] = o
    # short-matched control on the picked cells
    S = load("sig")
    S = S[S.role != "trend"].reset_index(drop=True)
    P = pd.read_csv(os.path.join(FW, "search_picks.csv"))
    P = P[(P.exit == "a2") & (P.level == "F")].sort_values("rank")
    rS = roe(S, "a2")
    k = S["a2_k"].to_numpy(np.int64)
    why = S["a2_why"].to_numpy()
    h2 = S.t.to_numpy() >= SPLIT
    ok2 = h2 & (why != 3) & np.isfinite(rS) & (k >= 0)
    sd = S.side.to_numpy()
    pools, actual_sum, actual_n = [], 0.0, 0
    for _, c in P.iterrows():
        role, tf = c.key.split("|")
        m = (S.role.to_numpy() == role) & (S.tf.to_numpy() == tf) & ok2
        st = state(S, c.src, c.htf)
        al = m & (st * sd == 1)
        nS, nL = int((al & (sd < 0)).sum()), int((al & (sd > 0)).sum())
        pools.append((rS[m & (sd < 0)], nS, rS[m & (sd > 0)], nL))
        actual_sum += rS[al].sum()
        actual_n += int(al.sum())
    act = actual_sum / actual_n
    rng = np.random.default_rng(5)
    nb = 20000
    sims = np.empty(nb)
    for b in range(nb):
        tot = 0.0
        for xs, nS, xl, nL in pools:
            if nS:
                tot += rng.choice(xs, nS, replace=False).sum()
            if nL:
                tot += rng.choice(xl, nL, replace=False).sum()
        sims[b] = tot / actual_n
    out["short_matched"] = {"actual": act, "n": actual_n, "null_mean": float(sims.mean()),
                            "null_p95": float(np.quantile(sims, 0.95)), "p": float(np.mean(sims >= act)),
                            "note": "random same-size, same-side-mix subsets of each cell's own H2 signals "
                                    "(signal-level, no clustering, so this p is if anything too small)"}
    json.dump(out, open(os.path.join(OUTD, "rc_short.json"), "w"), indent=1, default=float)
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
