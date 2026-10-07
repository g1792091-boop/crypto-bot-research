import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = pd.read_pickle("xl.pkl")
X = X[X.kind.isin(["strategy","ds200"])]
LEV = {"lev10","lev20m20","lev30m30","lev40m40","lev50m50"}
X = X[~X.variant.isin(LEV)]
print("flip variants present:", X[X.flip==1].variant.nunique())
out = {}
for fl in (0,1):
    Y = X[X.flip==fl]
    P = Y.pivot_table(index=["run","sig_id"], columns="variant", values="R")
    meta = Y[Y.variant=="base"].set_index(["run","sig_id"])[["strategy","timeframe","bar_close"]]
    P = P.join(meta)
    ex = [c for c in P.columns if c not in meta.columns]
    rows = []
    for (s, tf), g in P.groupby(["strategy","timeframe"]):
        if len(g) < 25: continue
        m = g[ex].mean()
        rows.append(dict(strategy=s, tf=tf, house=g.base.mean(), npos=int((m>0).sum()), nex=len(m)))
    out[fl] = pd.DataFrame(rows).set_index(["strategy","tf"])
J = out[0].join(out[1], rsuffix="_flip")
print("cells", len(J), "| real: all exits>0", (J.npos==J.nex).sum(), "house>0", (J.house>0).sum(), "| flip: all exits>0", (J.npos_flip==J.nex_flip).sum(), "house>0", (J.house_flip>0).sum(), "all<0", (J.npos_flip==0).sum())
print(J.loc[[("N17_KC_RSI","15m"),("N20_EMA9_CHOP","30m"),("F6_VWAP_CROSS","1h"),("N18_VWMA_MACD","30m"),("F4_PULL","15m")]].round(3).to_string())
print("flip cells all exits>0:", list(J[J.npos_flip==J.nex_flip].index))
print("corr(house real, house flip) across cells:", round(np.corrcoef(J.house, J.house_flip)[0,1],3))
