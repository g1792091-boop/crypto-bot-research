"""Pooled 5-year (current live rules) every-signal mean R and gross R per timeframe, all 36 strategies, IS/CF,
day-clustered SE; plus a sanity check of the own simulation against the reference profiles (old tier-walk ROE).
    python3 -I fy_tf_summary.py <work_dir>"""
import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
W = sys.argv[1]
D = pd.read_pickle(f"{W}/fy_signals.pkl")
D = D[(D.lev > 0) & D.R.notna()].copy()
D["gross"] = D.R + 0.0014 / (2 * D.atr_frac.astype(float) + 0.0002)
D["day"] = D.close_ms // 86_400_000
def cl(x, c):
    m = x.mean(); s = pd.Series(x - m).groupby(c).sum().to_numpy(); G = len(s)
    return m, np.sqrt(G / (G - 1) * (s ** 2).sum()) / len(x)
rows = []
for tf, g in D.groupby("tf", observed=True):
    for w, wl in ((None, "ALL"), (0, "IS"), (1, "CF")):
        gg = g if w is None else g[g.win == w]
        m, se = cl(gg.R.to_numpy(float), gg.day.to_numpy()); mg, seg = cl(gg.gross.to_numpy(float), gg.day.to_numpy())
        rows.append(dict(tf=tf, window=wl, n=len(gg), mean_R=m, ci_lo=m - 1.96 * se, ci_hi=m + 1.96 * se, gross_R=mg,
                         gross_ci_lo=mg - 1.96 * seg, gross_ci_hi=mg + 1.96 * seg, sd_R=gg.R.std(),
                         win_pct=100 * (gg.roe > 0).mean(), mean_cost_R=(gg.gross - gg.R).mean()))
T = pd.DataFrame(rows); T.to_csv(f"{W}/tf_summary_5y.csv", index=False)
print(T.round(4).to_string())
C = pd.read_csv(f"{W}/cards_1h_4h.csv")
x = C[C.fy_n >= 100]
print("sanity: own-sim mean R vs reference profiles ROE-per-notional, 1h/4h cells with fy_n>=100: spearman",
      round(x[["fy_mean_R", "ref5y_ret_notional"]].corr(method="spearman").iloc[0, 1], 3), "n", len(x))
