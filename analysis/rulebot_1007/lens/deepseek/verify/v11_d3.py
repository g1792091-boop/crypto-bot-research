import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from vlib import *
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 60)
L = pd.read_csv(sys.argv[1] + "/my_lev.csv")
r50 = L[(L.L == 50) & (L.status == "REJECTED_SIZING")].reject_reasons.fillna("")
print("50x: too close to liq", int(r50.str.contains("too close to liq").sum()), "15%", int(r50.str.contains("15%").sum()), "bracket", int(r50.str.contains("bracket").sum()), "total rejected", len(r50))
# lock mechanism in R at 15m (30x): (0.12/L + rt)/stop_frac
P = load_replay(); T = P[P.status == "TRADED"]
for tf in ["15m", "30m", "1h"]:
    sf = T[T.timeframe == tf].stop_frac.median()
    print(tf, "median stop %.3f%%" % (100 * sf), " first-lock trigger in R: 10x %.2f 20x %.2f 30x %.2f 40x %.2f" % tuple((0.12 / l + 0.0014) / sf for l in (10, 20, 30, 40)))
# d3 shadows
D = pd.read_csv(EXP + "/current/d3_shadows.csv")
D["bc"] = D.key.str.split("|").str[-1].astype("int64")
acc = pd.read_csv(EXP + "/current/accounts.csv"); ds = set(acc[acc.kind == "ds200"].account_id)
D = D[D.account_id.isin(ds)]
print("d3 ds200 rows by kind:", D.kind.value_counts().head(30).to_dict())
print("days:", D.day.value_counts().to_dict())
P["account_id"] = P.strategy + "@" + P.timeframe
X = D.merge(P[["account_id", "symbol", "bar_close", "status", "roe", "R", "leverage", "stop_frac", "mark_R", "acct_status"]], left_on=["account_id", "symbol", "bc"], right_on=["account_id", "symbol", "bar_close"], how="left", suffixes=("_d3", "_rp"))
# skipped shadows vs replay
sk = X[(X.kind == "skipped")]
b = sk[(sk.resolved == 1) & sk.roe_d3.notna() & (sk.status == "TRADED")]
print("skipped rows", len(sk), "matched replay", int(sk.status.notna().sum()), "both resolved+traded", len(b), "max |roe diff|", float((b.roe_d3 - b.roe_rp).abs().max()), "median", float((b.roe_d3 - b.roe_rp).abs().median()), "share exactly equal(<1e-9)", float(((b.roe_d3 - b.roe_rp).abs() < 1e-9).mean()))
# limit
li = X[X.kind == "limit"].copy()
print("limit rows by tf", li.groupby("timeframe").size().to_dict(), "matched", int(li.status.notna().sum()))
for tf, g in li.groupby("timeframe"):
    g = g[g.status == "TRADED"]
    fr = g.filled.mean()
    fl = g[g.filled == 1]; uf = g[g.filled == 0]
    flr = fl[(fl.resolved == 1) & fl.roe_d3.notna()]
    limR = flr.roe_d3 / (flr.leverage * flr.stop_frac)
    # per signal: filled & resolved -> limit R, unfilled -> 0
    sigs = pd.concat([flr.assign(Rl=limR), uf.assign(Rl=0.0)])
    print(tf, "n traded-matched", len(g), "fill %.2f" % fr, "| market R of filled %.3f (n%d) unfilled %.3f (n%d)" % (fl.R.mean(), len(fl), uf.R.mean(), len(uf)),
          "| per signal (resolved fills + unfilled): limit %.3f market %.3f n%d" % (sigs.Rl.mean(), sigs.R.mean(), len(sigs)),
          "| filled unresolved dropped:", int(((fl.resolved != 1) | fl.roe_d3.isna()).sum()), "| limit R per fill %.3f vs market same %.3f" % (limR.mean(), flr.R.mean()))
# lev10 variant in d3 vs my replay
for k in ["lev10", "lev20", "lev50", "lev40"]:
    v = X[X.kind == k]
    if len(v):
        print(k, "rows", len(v), "resolved share", round(v.resolved.mean(), 3), "by tf", v.groupby("timeframe").size().to_dict())
