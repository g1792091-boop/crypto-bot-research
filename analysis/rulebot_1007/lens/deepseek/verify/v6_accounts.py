import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from scipy import stats
from vlib import *
E = EXP + "/current"
tr = pd.read_csv(E + "/trades.csv")
acc = pd.read_csv(E + "/accounts.csv")
print(tr.columns.tolist())
ds = acc[acc.kind == "ds200"].account_id
t = tr[tr.account_id.isin(ds)].copy()
print("ds200 accounts", len(ds), "trades", len(t), "pnl", round(t.pnl.sum(), 1) if "pnl" in t else None)
g = t.groupby("account_id")
n = g.size()
print("accounts traded", len(n), "median n", n.median(), "max", n.max())
pnl = g.pnl.sum()
prof = pnl[pnl > 0]
exb = g.pnl.apply(lambda s: s.sum() - s.max())
print("profitable", len(prof), "neg without best", int((exb[prof.index] <= 0).sum()), " strict <0:", int((exb[prof.index] < 0).sum()))
# R from trades_enriched
TE = pd.read_csv(OUT_REAL + "/trades_enriched.csv")
TE = TE[(TE.run == "current") & (TE.kind == "ds200")]
print("TE n", len(TE), "mean R", round(TE.R.mean(), 4), "pnl", round(TE.pnl.sum(), 1))
aR = TE.groupby("account_id").R.mean()
for a in ["F12_MSS@15m", "F3_HHHL@15m", "F9_FVG@30m", "F15_ORB@15m", "F6_VWAP_CROSS@15m"]:
    x = TE[TE.account_id == a]
    print(a, "n", len(x), "pnl", round(x.pnl.sum(), 1), "meanR", round(x.R.mean(), 3), "best share", round(x.pnl.max() / x.pnl.sum(), 3) if x.pnl.sum() > 0 else None)
rank = pnl.sort_values(ascending=False)
print("top 5 pnl:", rank.head(5).round(0).to_dict())
R = load_replay(); T = R[R.status == "TRADED"]
rm = T.groupby(T.strategy + "@" + T.timeframe).R.agg(["mean", "size"])
for a in ["F12_MSS@15m", "F3_HHHL@15m"]:
    print(a, "replay", rm.loc[a].round(3).to_dict())
J = pd.DataFrame({"acct": aR}).join(rm)
J["tf"] = J.index.str.split("@").str[1]
for tf in ["15m", "30m"]:
    z = J[J.tf == tf].dropna()
    print(tf, "spearman acct vs replay", len(z), np.round(stats.spearmanr(z.acct, z["mean"]), 3))
    # replay excluding the account's own entered signals
T2 = T.copy(); T2["aid"] = T2.strategy + "@" + T2.timeframe
sk = T2[T2.acct_status != "ENTERED"].groupby("aid").R.mean()
J = J.join(sk.rename("skipped_only"))
for tf in ["15m", "30m"]:
    z = J[J.tf == tf].dropna()
    print(tf, "spearman acct vs replay(skipped-only)", len(z), np.round(stats.spearmanr(z.acct, z["skipped_only"]), 3))
# share of replay signals that are the account's own trades
print("entered share of replay traded by tf:", T2.groupby("timeframe").apply(lambda g: (g.acct_status == "ENTERED").mean(), include_groups=False).round(3).to_dict())
