"""Zero-edge TP-first / liquidation / time-exit probabilities on real IS paths, random entries, random sides.
Independent of the sim code. Also basic analytic numbers (liq distance, fee drag, break-even win rate)."""
import sys
import numpy as np
import pandas as pd
from common import *

print("== analytic ==")
for L in [1, 5, 10, 20, 50]:
    print(f"L={L:>2}: d_liq = 1/L - MMR = {100*(1/L-MMR):.2f}% ; TP 10% ROE price = {10/L:.2f}%")
for name, M, L in [("P0", 1, 1), ("P1", .25, 5), ("P2", .25, 10), ("P3", .2, 20), ("P4", .4, 50)]:
    N = M * L
    rt_mkt = 2 * (TAKER + SLIP); rt_tp = TAKER + SLIP + MAKER
    tp_eq = M * 0.10 - N * rt_tp
    liq_eq = -M - N * (TAKER + SLIP)
    be = -liq_eq / (tp_eq - liq_eq)
    dl = 1 / L - MMR; td = 0.10 / L
    p_bm = dl / (dl + td)          # driftless continuous: P(TP before liq), no time limit
    ev_bm = p_bm * tp_eq + (1 - p_bm) * liq_eq
    print(f"{name}: N={N:.2f}x  drag/trade: market RT {100*N*rt_mkt:.3f}% eq, TP RT {100*N*rt_tp:.3f}% eq; "
          f"TP win {100*tp_eq:+.3f}% eq, liq {100*liq_eq:+.3f}% eq; break-even P(TP|TP or liq) {be:.4f}; "
          f"driftless P(TP first, no time cap) {p_bm:.4f} -> E[r] {100*ev_bm:+.3f}% eq")

rng = np.random.default_rng(12345)
rows = []
for tf in sys.argv[1:] or ["15m", "1h"]:
    D = load(tf)
    H = HB[tf]
    allO, allH, allL, allC = [], [], [], []
    for c in COINS:
        df = D[c]
        ok = np.where(admissible(df, tf))[0]
        t = rng.choice(ok, size=min(len(ok), 60000), replace=False)
        j = t[:, None] + np.arange(1, H + 1)[None, :]
        allO.append(df.open.values[j]); allH.append(df.high.values[j]); allL.append(df.low.values[j]); allC.append(df.close.values[j])
    o, h, l, cl = (np.vstack(x) for x in (allO, allH, allL, allC))
    n = len(o)
    side = np.where(rng.random(n) < 0.5, 1, -1)
    for name, M, L in [("P3 20%x20", 0.2, 20), ("P4 40%x50", 0.4, 50)]:
        for order in ["colour", "adv", "fav"]:
            dl = np.full(n, 1 / L - MMR); sd = np.full(n, np.inf); td = np.full(n, 0.10 / L)
            jx, code, g = exits(o, h, l, cl, side, dl, sd, td, order)
            r = equity_ret(code, g, jx, M, L, TFMIN[tf])
            rows.append(dict(tf=tf, policy=name, order=order, n=n, p_tp=np.mean(code == 1), p_liq=np.mean(code == 3),
                             p_time=np.mean(code == 4), mean_gross_pct=100 * g.mean(), mean_eq_ret_pct=100 * r.mean(),
                             win=np.mean(r > 0), p_tp_given_tp_or_liq=np.mean(code == 1) / max(1e-12, np.mean((code == 1) | (code == 3)))))
        # stop C (0.5 d_liq) with colour order
        dl = np.full(n, 1 / L - MMR); sd = 0.5 * dl; td = np.full(n, 0.10 / L)
        jx, code, g = exits(o, h, l, cl, side, dl, sd, td, "colour")
        r = equity_ret(code, g, jx, M, L, TFMIN[tf])
        rows.append(dict(tf=tf, policy=name + " stopC", order="colour", n=n, p_tp=np.mean(code == 1), p_liq=np.mean(code == 3),
                         p_time=np.mean(code == 4), mean_gross_pct=100 * g.mean(), mean_eq_ret_pct=100 * r.mean(), win=np.mean(r > 0),
                         p_tp_given_tp_or_liq=np.nan))
df = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print(df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
df.to_csv(f"out_tpfirst_{'_'.join(sys.argv[1:]) or '15m_1h'}.csv", index=False)
