"""Verifier: side-flip (chosen side vs the other side at the same moment) for our 36 at 1h/4h, own cluster sign-flip.
    python3 -I vflip.py <out_real_dir>"""
import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
O = sys.argv[1]
RP = pd.read_csv(O + "/replay_signals.csv", low_memory=False)
RP = RP[(RP.kind == "strategy") & (RP.status == "TRADED") & (RP.flip_status == "TRADED")].copy()
TFMS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
RP["blk"] = [max(TFMS[t], 3_600_000) for t in RP.timeframe]
RP["cl"] = RP.run + "|" + (RP.bar_close // RP.blk).astype(np.int64).astype(str)
RP["d"] = (RP.R - RP.flip_R) / 2
rng = np.random.default_rng(5)

def test(g, B=20000):
    s = g.groupby("cl").d.sum().to_numpy()
    n = len(g)
    obs = s.sum() / n
    sg = rng.choice([-1, 1], size=(B, len(s)))
    null = (sg * s).sum(1) / n
    return obs, (null >= obs).mean(), len(s)

rows = []
for tf in ("1h", "4h"):
    g = RP[RP.timeframe == tf]
    o, p, G = test(g)
    rows.append(dict(level="tf", strategy="*", tf=tf, n=len(g), clusters=G, excess=o, p_better=p))
    for s, gg in g.groupby("strategy"):
        if len(gg) < 5:
            continue
        o, p, G = test(gg)
        if G < 5:
            continue
        rows.append(dict(level="cell", strategy=s, tf=tf, n=len(gg), clusters=G, excess=o, p_better=p))
P = pd.DataFrame(rows)
c = P.level == "cell"
p = P.loc[c, "p_better"].to_numpy(); o = np.argsort(p); m = len(p)
q = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
qq = np.empty(m); qq[o] = np.minimum(q, 1)
P.loc[c, "bh_q"] = qq
pd.set_option("display.width", 200)
print(P.round(4).to_string())
print("testable cells:", int(c.sum()), " raw p<0.05:", int((P.loc[c, 'p_better'] < 0.05).sum()))
S = pd.read_csv(O + "/coinflip_sideflip.csv")
S = S[(S.level == "strategy_tf") & (S.kind == "strategy") & S.timeframe.isin(["1h", "4h"])]
print("their file: cells with p_better:", S.p_better.notna().sum(), S[S.p_better.notna()].sort_values("p_better")[["strategy","timeframe","n_pairs","n_clusters","excess_R","p_better","bh_q_better"]].head(5).to_string())
