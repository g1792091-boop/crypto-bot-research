"""Grid data checks for 2024-01 .. 2026-10-05: filled (missing) minutes, open != previous close, extreme 1m ranges,
and the minutes of taken trades' entries / exits that fall on filled minutes. Run: python3 vla_grid.py <trades_dir>"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "data"))
from common import *  # noqa
sys.path.insert(0, os.path.join(REPO, "research", "newlive", "code"))
import nlcommon as NL
TD = sys.argv[1]
a, b = (ms("2024-01-01") - T0) // MIN, (ms("2026-10-05 15:00") - T0) // MIN
T = {v: pd.read_csv(os.path.join(TD, f"trades_{v}.csv.gz")) for v in ("B0", "B6", "B5", "B4", "B9")}
for ci, coin in enumerate(COINS):
    g = NL.load_grid(coin, end=GRID_END)
    o, h, l, c = g["o"][a:b], g["h"][a:b], g["l"][a:b], g["c"][a:b]
    filled = g["filled"][a:b]
    gap = np.abs(o[1:] / c[:-1] - 1)
    rng = (h - l) / o
    line = f"{coin}: filled {filled.sum()} ({filled.mean():.5f}), open-vs-prev-close >0.5%: {(gap > 0.005).sum()}, 1m range >3%: {(rng > 0.03).sum()}, >5%: {(rng > 0.05).sum()}"
    for v, D in T.items():
        D = D[(D.coin == ci) & (D.t >= ms("2024-01-01")) & (D.t < ms("2026-10-05 15:00"))]
        e = D.e.to_numpy(np.int64)
        x = e + D.tb_k.to_numpy(np.int64)
        fl = g["filled"]
        big = (g["h"] - g["l"]) / g["o"] > 0.03
        line += f" | {v}: entry on filled {fl[e].sum()}, exit on filled {fl[x].sum()}, exit minute range>3% {big[x].sum()}"
    print(line, flush=True)
