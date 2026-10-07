"""Verifier: N23_HA_ST 4h robustness: BH over 72 cells with week clusters; long/short split; coin split; 5m exits.
    python3 -I vn23.py <v_cells_1h_4h.csv> <v_tf_all.pkl> <v_5m_htf.pkl>"""
import site, sys
from math import erf, sqrt
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
CE, TFA, H5 = sys.argv[1:4]
DAY = 86_400_000
def p2(t): return 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2)))) if t == t else np.nan
def bh(p):
    p = np.asarray(p, float); q = np.full(len(p), np.nan); ok = np.isfinite(p); pp = p[ok]; o = np.argsort(pp)
    r = np.minimum.accumulate((pp[o] * len(pp) / np.arange(1, len(pp) + 1))[::-1])[::-1]; qq = np.empty_like(pp); qq[o] = np.minimum(r, 1); q[ok] = qq; return q
C = pd.read_csv(CE)
for lab in ("tfbars", "5mbars"):
    c = C[C.res == lab].copy()
    c["q_week"] = bh(c.gross_A_t_week.map(p2))
    c["q_day"] = bh(c.gross_A_t.map(p2))
    print(lab, c.sort_values("q_week")[["strategy", "tf", "n", "gross_A", "gross_A_t", "gross_A_t_week", "q_day", "q_week"]].head(4).round(4).to_string())
def cl(x, c):
    m = x.mean(); s = pd.Series(x - m).groupby(c).sum().to_numpy(); G = len(s)
    return m, np.sqrt(G / (G - 1) * (s ** 2).sum()) / len(x)
for lab, f in (("tfbars", TFA), ("5mbars", H5)):
    D = pd.read_pickle(f)
    D = D[(D.strategy.astype(str) == "N23_HA_ST") & (D.tf.astype(str) == "4h") & (D.lev > 0)].copy()
    D["gA"] = D.R + 0.0014 / (2 * D.atr_frac + 0.0002)
    D["day"] = D.close_ms // DAY
    print(lab, "n", len(D), "long share", round((D.side > 0).mean(), 3))
    for sd, g in D.groupby("side"):
        m, se = cl(g.gA.to_numpy(), g.day.to_numpy()); mn, sn = cl(g.R.to_numpy(), g.day.to_numpy())
        print("  side", sd, "n", len(g), "gross", round(m, 3), "t", round(m / se, 2), "net", round(mn, 3), "t", round(mn / sn, 2))
    for co, g in D.groupby(D.coin.astype(str)):
        if len(g) < 20: continue
        m, se = cl(g.gA.to_numpy(), g.day.to_numpy())
        print("  coin", co, "n", len(g), "net", round(g.R.mean(), 3), "gross", round(m, 3), "t", round(m / se, 2))
    # last 12 months
    last = D[D.close_ms >= pd.Timestamp("2025-10-01").value // 1_000_000]
    print("  last 12m n", len(last), "net", round(last.R.mean(), 3), "gross", round(last.gA.mean(), 3))
