import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from scipy import stats
from vlib import *
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 200)
E = EXP + "/current"
start = int(pd.read_csv(E + "/runs.csv").started_ts.min())
end = int(pd.read_csv(E + "/live_bars.csv", usecols=["ts"]).ts.max())
mid = start + (end - start) / 2
kst = lambda ms: (pd.to_datetime(ms, unit="ms") + pd.Timedelta(hours=9)).strftime("%m/%d %H:%M")
print("start", kst(start), "end", kst(end), "mid", kst(mid), "days", round((end - start) / 864e5, 3))
R = load_replay()
T = R[R.status == "TRADED"].copy()
T["half"] = np.where(T.bar_close < mid, "H1", "H2")
print(T.groupby(["timeframe", "half", "side"]).R.agg(["size", "mean"]).round(3).unstack(["side"]))
# unique-signal version
U = T.drop_duplicates(["timeframe", "bar_close", "symbol", "side"])
print("unique signals"); print(U.groupby(["timeframe", "half", "side"]).R.agg(["size", "mean"]).round(3).unstack(["side"]))
# market path: equal-weight 6 coins, by hour (KST) from live_bars
B = pd.read_csv(E + "/live_bars.csv")
print(B.columns.tolist()[:12])
