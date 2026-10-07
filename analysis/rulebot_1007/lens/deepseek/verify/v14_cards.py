import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from scipy import stats
from vlib import *
pd.set_option("display.width", 300); pd.set_option("display.max_columns", 60); pd.set_option("display.max_rows", 300)
E = EXP + "/current"
days = 1.503
sig = pd.read_csv(E + "/signal_log.csv"); acc = pd.read_csv(E + "/accounts.csv")
dsa = acc[acc.kind == "ds200"]
sub = sig[sig.status == "SUBMITTED"]
nsig = sub.groupby(["strategy", "timeframe"]).size()
TE = pd.read_csv(OUT_REAL + "/trades_enriched.csv"); TE = TE[(TE.run == "current") & (TE.kind == "ds200")]
A = TE.groupby("account_id").R.agg(["size", "mean"])
RA = pd.read_csv(OUT_REAL + "/replay_signals.csv"); RA = RA[(RA.run == "current") & RA.kind.isin(["ds200", "strategy"]) & (RA.status == "TRADED")].copy()
RA["cl4h"] = RA.bar_close // (4 * H)
# peers: same tf, side, 4h block, other strategy
key = ["timeframe", "side", "cl4h"]
g_sum = RA.groupby(key).R.transform("sum"); g_n = RA.groupby(key).R.transform("size")
s_sum = RA.groupby(key + ["strategy"]).R.transform("sum"); s_n = RA.groupby(key + ["strategy"]).R.transform("size")
RA["peer"] = (g_sum - s_sum) / (g_n - s_n).replace(0, np.nan)
RA["vs_peer"] = RA.R - RA.peer
R = load_replay(); T = R[R.status == "TRADED"].merge(RA[["sig_id", "vs_peer"]], on="sig_id", how="left")
d = (T.entry_price - T.stop_initial).abs()
T["gross"] = T.R + (T.fees + T.funding) / (T.qty * d) + 2 * 0.0002 * T.entry_price / d
SF = pd.read_csv(OUT_REAL + "/coinflip_sideflip.csv"); SF = SF[(SF.level == "strategy_tf") & (SF.kind == "ds200")].set_index(["strategy", "timeframe"])
L = pd.read_csv(sys.argv[1] + "/my_lev.csv"); L["Rv"] = np.where(L.status == "TRADED", L.R, np.where(L.status == "UNRESOLVED", L.mark_R, np.nan))
LV = L.groupby(["strategy", "timeframe", "L"]).Rv.mean().unstack("L")
Y = pd.read_csv("/home/user/crypto-bot-research/research/deepseek200/out/results.csv")
yb = Y.loc[Y.groupby(["entry", "tf"]).mean12_pct.idxmax()][["entry", "tf", "exit", "mean12_pct"]].rename(columns={"entry": "strategy", "tf": "timeframe"})
yb["rank"] = yb.groupby("timeframe").mean12_pct.rank(ascending=False)
yb = yb.set_index(["strategy", "timeframe"])
rows = []
for a in dsa.itertuples():
    s, tf = a.strategy, a.timeframe
    g = T[(T.strategy == s) & (T.timeframe == tf)]
    r = dict(strategy=s, tf=tf, sigd=nsig.get((s, tf), 0) / days, acct_n=A["size"].get(a.account_id, 0), acct_R=A["mean"].get(a.account_id, np.nan), n=len(g))
    if len(g):
        c = crse(g.R, g.cl1h) if len(g) > 1 else dict(mean=g.R.mean(), G=1)
        nL, nS = (g.side > 0).sum(), (g.side < 0).sum()
        r.update(G=c.get("G"), mean=c["mean"], lo=c.get("lo"), hi=c.get("hi"), p_gt=c.get("p_gt"), p_lt=c.get("p_lt"),
                 sideBal=0.5 * (g[g.side > 0].R.mean() + g[g.side < 0].R.mean()) if nL >= 3 and nS >= 3 else np.nan,
                 peers=g.vs_peer.mean(), exBest=(g.R.sum() - g.R.max()) / (len(g) - 1) if len(g) > 1 else np.nan,
                 long=(g.side > 0).mean(), gross=g.gross.mean())
    if (s, tf) in SF.index: r["flip"] = SF.loc[(s, tf), "excess_R"]
    if (s, tf) in LV.index: r["lev10"] = LV.loc[(s, tf), 10]; r["lev30"] = LV.loc[(s, tf), 30]
    if (s, tf) in yb.index: r["y5"] = yb.loc[(s, tf), "mean12_pct"]; r["y5exit"] = yb.loc[(s, tf), "exit"][:2]; r["y5rank"] = yb.loc[(s, tf), "rank"]
    rows.append(r)
C = pd.DataFrame(rows)
C["testable"] = (C.n >= 10) & (C.G >= 8)
m = C.testable
C.loc[m, "q_gt"] = bhq(C.loc[m, "p_gt"].values); C.loc[m, "q_lt"] = bhq(C.loc[m, "p_lt"].values)
C.to_csv(sys.argv[1] + "/my_cards.csv", index=False)
show = C[C.tf.isin(["15m", "30m"])].sort_values(["tf", "strategy"])
print(show[["strategy", "tf", "sigd", "acct_n", "acct_R", "n", "G", "mean", "lo", "hi", "q_gt", "q_lt", "sideBal", "peers", "exBest", "long", "gross", "flip", "lev10", "lev30", "y5exit", "y5", "y5rank"]].round(3).to_string(index=False))
print("live replay vs 5y rank spearman (testable):")
for tf in ["15m", "30m"]:
    z = C[C.testable & (C.tf == tf)]
    print(tf, len(z), np.round(stats.spearmanr(z["mean"], z.y5), 3))
