"""How often is a strategy positive in a 7-day window? (native-lite ledgers, 15m IS, 5 symbols)
Answers: are 'positive in the 7-day live audit' strategies distinguishable from noise?"""
import os, glob, pickle, numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
OUT = "out"
parts = [pickle.load(open(p, "rb")) for p in sorted(glob.glob(os.path.join(OUT, "parts_*.pkl")))]
Dn = pd.concat([p["D"] for p in parts])
print("exit reasons by config:\n", pd.crosstab(Dn.exit, Dn.reason).to_string())
base = Dn[~Dn.strategy.str.contains("~")]            # 12 new + 17 tested, primary ports only
for cfg in ("NATIVE_fg_gate0.6", "NATIVE_fg_gatecap0.54", "NATIVE_real_gate0.6"):
    d = base[base.exit == cfg].copy()
    d["wk"] = pd.to_datetime(d.entry_ts, utc=True).dt.tz_localize(None).dt.to_period("W-TUE")
    W = d.groupby(["wk", "strategy"]).net.sum().unstack()      # weeks x strategies (NaN = no trade)
    W = W.iloc[1:-1]                                         # drop partial first/last week
    npos = (W > 0).sum(axis=1); ntr = W.notna().sum(axis=1)
    share = (W > 0).sum() / W.notna().sum()
    tot = d.groupby("strategy").net.agg(["count", "mean"])
    print(f"\n== {cfg}: weeks={len(W)} strategies={W.shape[1]} all with negative IS mean: {bool((tot['mean']<0).all())}")
    print(" positive strategies per week: median", int(npos.median()), "IQR", int(npos.quantile(.25)), "-", int(npos.quantile(.75)),
          "min", int(npos.min()), "max", int(npos.max()), "| strategies trading per week median", int(ntr.median()))
    print(" share of weeks with >=4 positive strategies:", round(float((npos >= 4).mean()), 3))
    s = pd.DataFrame({"weeks_traded": W.notna().sum(), "share_weeks_pos": share.round(3), "IS_trades": tot["count"], "IS_net_mean_pct": (tot["mean"]*100).round(3)})
    print(s.sort_values("share_weeks_pos", ascending=False).head(12).to_string())
