import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from vlib import *
C = pd.read_csv(sys.argv[1] + "/my_cards.csv")
Y = pd.read_csv("/home/user/crypto-bot-research/research/deepseek200/out/results.csv")
all3 = set(map(tuple, Y[Y.all3_positive][["entry", "tf"]].values))
R = load_replay(); T = R[R.status == "TRADED"]
lo4 = {}
for (s, tf), g in T.groupby(["strategy", "timeframe"]):
    c = crse(g.R, g.cl4h); lo4[(s, tf)] = c.get("lo", np.nan)
C["y_med"] = C.groupby("tf").y5.transform("median"); C["y_q33"] = C.groupby("tf").y5.transform(lambda s: s.quantile(1 / 3))
nested = {"F5_BOX_HTF", "F13_RAID_PD", "F17_Z_HL", "F12_MSS_DISP", "F13_FVG_PD", "F10_M2022"}  # by PREREG definition
MERGE = {"F5_BOX_HTF", "F13_RAID_PD", "F11_TSOUP", "F17_Z_HL", "F12_MSS_DISP", "F13_FVG_PD", "F10_M2022", "F16_FIB618", "F7_RF_ONLY"}
SAME = {("F15_OPEN0000", "30m"), ("F15_OPEN0000", "1h"), ("F15_OPEN0930", "30m")}
g = []
for r in C.itertuples():
    if r.n < 5: g.append("N"); continue
    if r.strategy in MERGE or (r.strategy, r.tf) in SAME: g.append("X"); continue
    if (r.testable and r.q_lt <= 0.10) or (r.mean < 0 and r.y5 <= r.y_q33): g.append("D"); continue
    if r.testable and r.q_gt <= 0.10 and r.lo > 0 and lo4[(r.strategy, r.tf)] > 0 and r.sideBal > 0 and ((r.strategy, r.tf) in all3): g.append("A"); continue
    if r.testable and r.mean > 0 and r.sideBal > 0 and r.exBest > 0 and r.peers > 0 and r.y5 >= r.y_med: g.append("W"); continue
    g.append("C")
C["grade"] = g
x = C[C.tf.isin(["15m", "30m"])]
print("15m/30m grades:", x.grade.value_counts().to_dict(), " total", len(x))
print(C.groupby(["tf", "grade"]).size().unstack(fill_value=0))
print("W cells:", C[C.grade == "W"][["strategy", "tf", "n", "mean"]].values.tolist())
theirs = pd.read_csv("/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/deepseek/out/cards_deepseek.csv")
m = C.merge(theirs[["definition", "timeframe", "grade"]], left_on=["strategy", "tf"], right_on=["definition", "timeframe"], suffixes=("_mine", "_theirs"))
print("grade disagreements:", m[m.grade_mine != m.grade_theirs][["strategy", "tf", "grade_mine", "grade_theirs"]].values.tolist())
# what F7_RF_ONLY and F11_TSOUP@30m would be graded if not merged (75%/62% < 85% rule)
for s, tf in [("F7_RF_ONLY", "15m"), ("F7_RF_ONLY", "30m"), ("F11_TSOUP", "30m"), ("F11_TSOUP", "15m"), ("F16_FIB618", "30m"), ("F12_MSS_DISP", "15m")]:
    r = C[(C.strategy == s) & (C.tf == tf)].iloc[0]
    print(s, tf, "n", r.n, "mean %.3f" % r["mean"], "testable", r.testable, "q_lt %.3f" % r.q_lt if r.q_lt == r.q_lt else "", "y5 %.3f q33 %.3f med %.3f" % (r.y5, r.y_q33, r.y_med), "sideBal %.3f peers %.3f exBest %.3f" % (r.sideBal, r.peers, r.exBest))
