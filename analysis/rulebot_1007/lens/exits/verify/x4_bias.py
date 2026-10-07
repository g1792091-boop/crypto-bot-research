import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
ex = sys.argv[1]
X = pd.read_pickle("xl.pkl")
X = X[(X.flip==0)&(X.run=="current")]
P = X.pivot_table(index=["strategy","timeframe","symbol","bar_close"], columns="variant", values="R")
D = pd.read_csv(os.path.join(ex, "current", "d3_shadows.csv"), low_memory=False)
T = pd.read_csv(os.path.join(ex, "current", "trades.csv"), low_memory=False)
T["bar"] = T.signal_ts + 1
T["sf"] = (T.entry_price - T.stop_initial).abs()/T.entry_price
sf = {(r.account_id, r.symbol, int(r.bar)): r.sf for r in T.itertuples()}
D["acct"] = D.key.str.split("|").str[1]
D["bar"] = D.key.str.split("|").str[3].astype("int64")
D["lev"] = D.data.map(lambda s: json.loads(s).get("leverage") if isinstance(s,str) and s.startswith("{") else np.nan)
D["sf"] = [sf.get((a,s,b), np.nan) for a,s,b in zip(D.acct, D.symbol, D.bar)]
D["R"] = D.roe/(D.lev*D.sf)
D["strategy"] = D.acct.str.split("@").str[0]
base = D[D.kind=="base"].set_index(["acct","symbol","bar"])
rows = []
for v in ["lev10","tp3R","lock30","tp2R","stopw3","timestop"]:
    V = D[D.kind==v].set_index(["acct","symbol","bar"])
    J = V[["R","resolved","timeframe","strategy","roe"]].join(base[["R","resolved","roe"]], rsuffix="_b", how="inner")
    J = J[J.resolved_b==1]
    for tf in ["15m","30m","1h"]:
        g = J[J.timeframe==tf].reset_index()
        key = list(zip(g.strategy, g.timeframe, g.symbol, g.bar))
        xv = P.reindex(key)
        g["Rx_v"] = xv[v if v!="lev10" else "lev10"].to_numpy() if v in P.columns else np.nan
        g["Rx_b"] = xv["base"].to_numpy()
        pr = g[(g.resolved==1)&g.R.notna()]           # nightly shadow pairs (dropped: unresolved / not entered)
        dropped = g[~g.index.isin(pr.index)]
        rows.append(dict(variant=v, tf=tf, trades=len(g), shadow_pairs=len(pr), shadow_dR=(pr.R-pr.R_b).mean(),
                         rerun_same_trades=(g.Rx_v-g.Rx_b).mean(), n_rerun=int((g.Rx_v-g.Rx_b).notna().sum()),
                         rerun_on_shadow_pairs=(pr.Rx_v-pr.Rx_b).mean(), rerun_on_dropped=(dropped.Rx_v-dropped.Rx_b).mean(),
                         n_dropped=len(dropped), match_base=float(np.mean(np.abs(pr.R_b-pr.Rx_b)<1e-6))))
pd.set_option("display.width", 250)
print(pd.DataFrame(rows).round(3).to_string())
