"""Forward 19-day 보류 vs with-trend split (signal level, each signal alone, the bot's exits): is the -6.46 vs +0.83 gap
more than luck? Also the share of member signals passing all B0 checks, and the 보류 share among them.
Uses the study's lb_core (read-only). Run: python3 vdir_fwdhold.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import lb_core as L          # noqa: E402
import numpy as np           # noqa: E402

B0_USE = ["blk", "na", "against", "chase", "weak", "tired", "breakout", "far_htf", "far_etf", "rsi"]
S = L.candidates("B0", keep_all=True)
S = S[(S.tb_why != 3) & (S.tb_opp_why != 3) & S.period.ne("")].reset_index(drop=True)
F = S[[f"f_{k}" for k in B0_USE]].to_numpy()
ok = F.sum(1) == 0
for pn in ("select", "confirm", "late", "fwd"):
    P = S.period.to_numpy() == pn
    print(pn, "signals", P.sum(), "pass", (P & ok).sum(), "share %.3f" % ((P & ok).sum() / P.sum()),
          "hold among pass %.3f" % ((P & ok & (S.j_dir.to_numpy() == 0)).sum() / max((P & ok).sum(), 1)))

DAY = 86_400_000
rng = np.random.default_rng(9)
for pn in ("select", "confirm", "late", "fwd"):
    G = S[(S.period == pn) & ok]
    h = (G.j_dir.to_numpy() == 0)
    x = G.tb_roe.to_numpy()
    obs = x[h].mean() - x[~h].mean()
    # label permutation within days (hold vs with-trend label shuffled among same-day signals) and day-block bootstrap
    day = G.t.to_numpy() // DAY
    ud, inv = np.unique(day, return_inverse=True)
    sims = np.empty(5000)
    for b in range(5000):
        pk = rng.integers(0, len(ud), len(ud))
        w = np.bincount(pk, minlength=len(ud))[inv]
        sims[b] = (w * x * h).sum() / max((w * h).sum(), 1) - (w * x * ~h).sum() / max((w * ~h).sum(), 1)
    print(f"{pn:8s} hold {100 * x[h].mean():+.2f} (n {h.sum()}) with-trend {100 * x[~h].mean():+.2f} (n {(~h).sum()}) "
          f"diff {100 * obs:+.2f}pt  day-boot 95% [{100 * np.quantile(sims, .025):+.2f}, {100 * np.quantile(sims, .975):+.2f}] "
          f"p(diff>=0) {(sims >= 0).mean():.3f}  days {len(ud)}")
