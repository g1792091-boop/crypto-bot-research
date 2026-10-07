import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = pd.read_pickle("xl.pkl")
b = X[(X.flip==0)&(X.variant=="base")].copy()
b["fp"] = b.run + "|" + b.timeframe + "|" + b.symbol + "|" + b.bar_close.astype(str) + "|" + b.side.astype(str)
g = b.groupby("fp").agg(n=("R","size"), Rsd=("R","std"), refsd=("ref_price","std"), atrsd=("atr","std"), Rmin=("R","min"), Rmax=("R","max"))
m = g[g.n>1]
print("groups with >1 rows", len(m), "| identical R (range<1e-9):", int(((m.Rmax-m.Rmin)<1e-9).sum()), "| identical ref", int((m.refsd.fillna(0)<1e-12).sum()), "| identical atr", int((m.atrsd.fillna(0)<1e-12).sum()))
print("median R range in groups", (m.Rmax-m.Rmin).median(), "share range<0.05R", ((m.Rmax-m.Rmin)<0.05).mean())
# kinds in dup groups
b["k"] = b.kind
mix = b[b.fp.isin(m.index)].groupby("fp").k.apply(lambda s: "+".join(sorted(set(s))))
print(mix.value_counts().to_string())
