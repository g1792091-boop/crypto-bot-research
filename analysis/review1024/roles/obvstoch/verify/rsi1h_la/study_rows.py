"""Rows of OBV20@4h>RSI@1h|a2 from the study's own code (cache rebuilt in /dev/shm/claude_v_rsi1h_la): reproduce the
claimed per-period numbers and save every row (coin, entry minute, side, roe) for the independent comparison."""
import os, sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O
from oscore import *
O.CACHE = "/dev/shm/claude_v_rsi1h_la"
D = O.load_all()
pb = PAYBACK * 30.0
out = []
for per in ("SEL", "CONF", "YTD", "FWD", "PRE", "FIVE"):
    R = O.rows(D, "1h", "4h", "OBV20", "RSI", "a2", per)
    s = O.summarize(R)
    R2 = dict(R); R2["roe"] = R["roe"] + pb; R2["opp"] = R["opp"] + pb
    s2 = O.summarize(R2)
    print(f"{per:5s} n={s['n']:4d} mean={s['mean_roe']*100:+.3f}% t={s['t_abs']:+.2f} | payback mean={s2['mean_roe']*100:+.3f}% t={s2['t_abs']:+.2f}")
R = O.rows(D, "1h", "4h", "OBV20", "RSI", "a2", (ms("2020-01-01"), ext_end()), drop_open=False)
df = pd.DataFrame({"coin": [COINS[i] for i in R["coin"]], "e": R["e"], "side": R["side"], "roe": R["roe"], "opp": R["opp"], "w": R["w"]})
df["t_utc"] = pd.to_datetime(T0 + df.e * MIN, unit="ms")
df.to_csv("study_rows.csv", index=False)
print(len(df), "rows saved")
