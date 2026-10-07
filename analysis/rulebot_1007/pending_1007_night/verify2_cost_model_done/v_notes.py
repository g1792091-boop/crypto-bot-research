"""Check the analyst's strategy_notes against my recounts. python3 -I v_notes.py <lens2_cost_model.json> <rates_mine.csv> <outc_dir> <v5y_for_pol.csv> <live_mine.csv>"""
import sys, json, os, collections
sys.path.insert(0, "/root/.local/lib/python3.11/site-packages")
import numpy as np, pandas as pd
J, RM, OUTC, V5, LM = sys.argv[1:6]
notes = json.load(open(J))["strategy_notes"]
rm = pd.read_csv(RM)
# 5y signal rates from outc masks (all signals incl. infeasible)
NDAY = 1886
y5 = collections.Counter()
for f in os.listdir(OUTC):
    tf = f.split("_")[1]; z = np.load(os.path.join(OUTC, f))
    for k in z.files:
        if k.startswith("m__C:"): y5[(k[5:], tf)] += len(z[k])
probs = []; nrate = 0; diffs = []
for n in notes:
    if n["grade"] not in ("rate",): continue
    s, tf, num = n["strategy"], n["timeframe"], n["numbers"]; nrate += 1
    for run, col in (("v3b", "live_v3b_signals_per_day"), ("v4", "live_v4_signals_per_day")):
        r = rm[(rm.run == run) & (rm.strategy == s) & (rm.tf == tf)]
        mine = float(r.signals_per_day.iloc[0]) if len(r) else None
        theirs = num.get(col)
        if (mine or 0) != (theirs or 0) and not (mine and theirs and abs(mine - theirs) < 0.02):
            probs.append((s, tf, col, theirs, mine))
    if "y5_signals_per_day" in num and (s, tf) in y5:
        diffs.append((s, tf, num["y5_signals_per_day"], y5[(s, tf)] / NDAY))
d = pd.DataFrame(diffs, columns=["s", "tf", "theirs", "mine"]); d["ratio"] = d.mine / d.theirs.replace(0, np.nan)
print("rate notes", nrate, "live mismatches", len(probs), probs[:8])
print("5y rate ratio mine/theirs: median %.3f, p10 %.3f, p90 %.3f, n %d" % (d.ratio.median(), d.ratio.quantile(.1), d.ratio.quantile(.9), d.ratio.notna().sum()))
print(d[(d.ratio < 0.8) | (d.ratio > 1.25)].round(2).to_string()[:1500])
# typical/heavy/light notes: y5 switch P4 mean vs mine
v5 = pd.read_csv(V5); v5 = v5[v5.kind == "feas"].set_index(["strategy", "setup"])
v5["swP4"] = v5.entry + v5.switch + v5.p2_sw + v5.mv05 + v5.otf_sw; v5["igP2"] = v5.entry + v5.p2_ign
rows = []
for n in notes:
    if n["grade"] in ("typical", "heavy", "light", "rare") and n["timeframe"].startswith("setup"):
        su = n["timeframe"].split()[1]; k = (n["strategy"], su)
        if k in v5.index:
            rows.append((n["strategy"], su, n["grade"], n["numbers"].get("y5_switch_P4_mean"), v5.loc[k, "swP4"], n["numbers"].get("y5_ignore_P2_mean"), v5.loc[k, "igP2"], n["numbers"].get("y5_occupancy"), v5.loc[k, "occupancy"]))
t = pd.DataFrame(rows, columns=["s", "setup", "grade", "swP4_theirs", "swP4_mine", "igP2_theirs", "igP2_mine", "occ_theirs", "occ_mine"])
t["r"] = t.swP4_mine / t.swP4_theirs
print("swP4 ratio median %.2f p10 %.2f p90 %.2f; spearman %.2f; occ diff median %.2f" % (t.r.median(), t.r.quantile(.1), t.r.quantile(.9), t[["swP4_theirs", "swP4_mine"]].corr("spearman").iloc[0, 1], (t.occ_mine - t.occ_theirs).median()))
print(t[(t.r < 0.75) | (t.r > 1.33)].round(2).to_string())
print("grade counts", t.groupby(["setup", "grade"]).size().to_dict())
# grade consistency: analyst's heavy should be top by my swP4
for su in "AB":
    tt = t[t.setup == su].sort_values("swP4_mine", ascending=False)
    print(su, "my top6:", list(tt.s[:6]), "their heavy:", list(t[(t.setup == su) & (t.grade == "heavy")].s))
    print(su, "min/max mine %.1f / %.1f; theirs %.1f / %.1f" % (tt.swP4_mine.min(), tt.swP4_mine.max(), tt.swP4_theirs.min(), tt.swP4_theirs.max()))
