"""Account view (40 % margin, compounding, all calendar days) of B0 / B1 / B2 / B3 over confirm+late, with and
without the TetherMax payback, plus the forward hold vs with-trend signal gap with a day-block bootstrap.
Run: python3 verify/vcx_acct.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LBD = os.path.dirname(HERE)
sys.path.insert(0, LBD)
import numpy as np            # noqa: E402
import pandas as pd           # noqa: E402
import lb_core as L           # noqa: E402

DAY = 86_400_000
a, b = L.P_CON[0], L.P_LATE[1]
nd = int((b - a) // DAY)
for v in ("B0", "B1", "B2", "B3", "B5", "B6"):
    T = pd.read_csv(os.path.join(LBD, "trades", f"trades_{v}.csv.gz"))
    T = T[(T.t >= a) & (T.t < b)]
    lev = L.lev_of(T.coin.to_numpy())
    for pb in (False, True):
        roe = T.tb_roe.to_numpy() + (lev * L.PAYBACK if pb else 0)
        lg = np.log(np.maximum(1 + L.MARGIN * np.maximum(roe, -1), 1e-9))
        tot = lg.sum()
        print(f"{v} pb={pb!s:5} n {len(T)} per-day {len(T) / nd:.2f} per-trade {roe.mean():+.4f} "
              f"mean daily log {tot / nd:+.5f} -> 30-day x{np.exp(30 * tot / nd):.3f}")
# forward hold vs with-trend signals (whatif part1 rows), day-block
S = L.candidates("B0", keep_all=True)
S = S[(S.tb_why != 3) & (S.tb_opp_why != 3) & (S.period == "fwd")]
use = ["blk", "na", "against", "chase", "weak", "tired", "breakout", "far_htf", "far_etf", "rsi"]
nf = S[[f"f_{k}" for k in use]].to_numpy().sum(1)
P = S[nf == 0]
H, W = P[P.j_dir == 0], P[P.j_dir != 0]
print("fwd signals hold", len(H), f"{H.tb_roe.mean():+.4f} opp {H.tb_opp_roe.mean():+.4f}", "| with-trend", len(W),
      f"{W.tb_roe.mean():+.4f} opp {W.tb_opp_roe.mean():+.4f}", "| hold days", H.t.floordiv(DAY).nunique(),
      "trend days", W.t.floordiv(DAY).nunique())
ud = np.unique(P.t.to_numpy() // DAY)
rng = np.random.default_rng(5)
pk = rng.integers(0, len(ud), (5000, len(ud)))


def agg(G):
    i = np.searchsorted(ud, G.t.to_numpy() // DAY)
    s, c = np.bincount(i, G.tb_roe.to_numpy(), len(ud)), np.bincount(i, minlength=len(ud))
    return s[pk].sum(1) / np.maximum(c[pk].sum(1), 1)


d = agg(W) - agg(H)
print(f"with-trend minus hold {W.tb_roe.mean() - H.tb_roe.mean():+.4f}; day-block p(<=0) {(d <= 0).mean():.4f};"
      f" 95% {np.quantile(d, .025):+.4f} .. {np.quantile(d, .975):+.4f}")
