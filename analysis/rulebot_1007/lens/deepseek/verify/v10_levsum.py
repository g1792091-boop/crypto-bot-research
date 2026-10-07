import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from vlib import *
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 60)
L = pd.read_csv(sys.argv[1] + "/my_lev.csv")
E = EXP + "/current"
start = int(pd.read_csv(E + "/runs.csv").started_ts.min()); end = int(pd.read_csv(E + "/live_bars.csv", usecols=["ts"]).ts.max()); mid = start + (end - start) / 2
L["Rv"] = np.where(L.status == "TRADED", L.R, np.where(L.status == "UNRESOLVED", L.mark_R, np.nan))
L["half"] = np.where(L.bar_close < mid, "H1", "H2")
L["cl1h"] = L.bar_close // np.maximum(L.timeframe.map(TFMIN) * 60000, H)
L["cl4h"] = L.bar_close // (4 * H)
# parity with pipeline at 30x
P = load_replay()
m = L[L.L == 30].merge(P[["sig_id", "status", "R", "leverage"]], on="sig_id", suffixes=("", "_p"))
both = m[(m.status == "TRADED") & (m.status_p == "TRADED") & (m.leverage_p == 30)]
print("parity 30x vs pipeline (pipeline lev 30, both traded):", len(both), "max |dR|", float((both.R - both.R_p).abs().max()))
rows = []
for (tf, lv), g in L.groupby(["timeframe", "L"]):
    v = g.Rv.notna()
    rr = g[v]
    d = dict(tf=tf, L=lv, n=len(g), entered=v.mean(), unresolved=(g.status == "UNRESOLVED").mean(), meanRv=rr.Rv.mean(),
             meanR_resolved=g[g.status == "TRADED"].R.mean(), long=rr[rr.side > 0].Rv.mean(), short=rr[rr.side < 0].Rv.mean())
    d["sidebal"] = 0.5 * (d["long"] + d["short"])
    rows.append(d)
print(pd.DataFrame(rows).round(3).to_string())
# rejection reasons at 50x
r50 = L[(L.L == 50) & (L.status == "REJECTED_SIZING")].reject_reasons.fillna("")
for k in ["15%", "bracket", "liquid"]:
    print("50x reasons containing", k, int(r50.str.contains(k, case=False).sum()))
print(r50.str.slice(0, 160).value_counts().head(5).to_string())
# paired 10x vs 30x on signals valued at both
W = L.pivot_table(index=["sig_id", "timeframe", "side", "half", "cl1h", "cl4h"], columns="L", values="Rv").reset_index()
S = L.pivot_table(index="sig_id", columns="L", values="status", aggfunc="first")
W = W.join(S.add_prefix("st"), on="sig_id")
for tf in ["15m", "30m", "1h"]:
    g = W[(W.timeframe == tf) & W[10].notna() & W[30].notna()]
    dlt = g[10] - g[30]
    c1 = crse(dlt, g.cl1h); c4 = crse(dlt, g.cl4h)
    gr = g[(g.st10 == "TRADED") & (g.st30 == "TRADED")]
    dr = gr[10] - gr[30]
    print(tf, "paired n", len(g), "10x-30x mean %.3f (1h-cl CI %.3f..%.3f; 4h-cl CI %.3f..%.3f)" % (c1["mean"], c1["lo"], c1["hi"], c4["lo"], c4["hi"]),
          "| resolved-both n", len(gr), "diff %.3f" % dr.mean(),
          "| by half:", {h: round((g[g.half == h][10] - g[g.half == h][30]).mean(), 3) for h in ["H1", "H2"]},
          "| by side:", {s: round((g[g.side == s][10] - g[g.side == s][30]).mean(), 3) for s in [1, -1]},
          "| unresolved share 10x %.2f 30x %.2f" % ((g.st10 == "UNRESOLVED").mean(), (g.st30 == "UNRESOLVED").mean()))
    for h in ["H1", "H2"]:
        gh = g[g.half == h]
        sb10 = 0.5 * (gh[gh.side > 0][10].mean() + gh[gh.side < 0][10].mean()); sb30 = 0.5 * (gh[gh.side > 0][30].mean() + gh[gh.side < 0][30].mean())
        print("    ", h, "n", len(gh), "side-balanced 10x %.3f 30x %.3f diff %.3f" % (sb10, sb30, sb10 - sb30))
