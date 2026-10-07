import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = pd.read_pickle("xl.pkl")
X["fp"] = X.run + "|" + X.timeframe + "|" + X.symbol + "|" + X.bar_close.astype(str) + "|" + X.side.astype(str) + "|" + X.atr.round(10).astype(str)
def pivot(flip=0, kinds=("strategy","ds200","random"), dedup=False):
    Y = X[(X.flip==flip) & X.kind.isin(kinds)]
    if dedup:
        keep = Y[Y.variant=="base"].drop_duplicates("fp")[["run","sig_id"]]
        Y = Y.merge(keep, on=["run","sig_id"])
    P = Y.pivot_table(index=["run","sig_id"], columns="variant", values="R")
    meta = Y[Y.variant=="base"].set_index(["run","sig_id"])[["timeframe","bar_close","runl","strategy","kind","fp"]]
    return P.join(meta)
def contrast(P, a, b, tfs=("15m","30m","1h","4h")):
    out = []
    for tf in tfs:
        for rl in ("v3b","v4","pooled"):
            g = P[(P.timeframe==tf) & ((P.runl==rl) if rl!="pooled" else True)]
            d = (g[a]-g[b]).dropna()
            bc = g.loc[d.index, "bar_close"]
            r1 = cboot(d, bc//3600_000); r6 = cboot(d, bc//(6*3600_000), seed=3); r12 = cboot(d, bc//(12*3600_000), seed=5)
            out.append(dict(a=a, b=b, tf=tf, run=rl, n=len(d), mean=r1["mean"], lo1h=r1["lo"], hi1h=r1["hi"], p1h=r1["p"],
                            lo6h=r6["lo"], hi6h=r6["hi"], p6h=r6["p"], G6=r6["G"], lo12h=r12["lo"], hi12h=r12["hi"], G12=r12["G"]))
    return out
if __name__ == "__main__":
    pairs = [x.split(":") for x in sys.argv[2].split(",")]
    flip = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    mode = sys.argv[4] if len(sys.argv) > 4 else "all"
    kinds = ("strategy","ds200") if mode in ("nornd","dedup") else ("strategy","ds200","random")
    P = pivot(flip=flip, kinds=kinds, dedup=(mode=="dedup"))
    rows = []
    for a, b in pairs:
        rows += contrast(P, a, b)
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
    print(R.round(3).to_string())
    R.to_csv(sys.argv[1], index=False)
