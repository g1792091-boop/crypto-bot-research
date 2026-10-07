import os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
TH = sys.argv[1]
W = pd.read_csv(os.path.join(TH, "fy_tf_windows.csv")); W = W[W["sample"] == "v3a"].set_index("tf")
S0, S1 = pd.Timestamp("2021-08-01").value, pd.Timestamp("2026-09-30").value
rng = np.random.default_rng(8); L = int(2.6075570 * 86400e9)
for tf in ("5m", "15m", "30m", "1h", "4h"):
    T = pd.read_pickle(os.path.join(TH, f"fy36_{tf}.pkl.gz"), )[["ts", "tw_lev", "tw_done", "tw_R", "stop_frac"]]
    T = T[(T.ts >= S0) & (T.ts < S1) & (T.tw_lev > 0) & T.tw_done].sort_values("ts")
    ts = T.ts.to_numpy(); R = T.tw_R.to_numpy(float); sf = T.stop_frac.to_numpy(float)
    cR, cS = np.r_[0, np.cumsum(R)], np.r_[0, np.cumsum(sf)]
    st = rng.uniform(S0, S1 - L, 4000).astype(np.int64); a, b = np.searchsorted(ts, st), np.searchsorted(ts, st + L); n = b - a; ok = n > 0
    mR = (cR[b] - cR[a])[ok] / n[ok]; mS = (cS[b] - cS[a])[ok] / n[ok]
    lm, ls = W.loc[tf, "live_mean_R"], W.loc[tf, "live_mean_stop_frac"]
    mt = np.abs(mS / ls - 1) <= 0.15
    pc = (mR < lm).mean(); pm = (mR[mt] < lm).mean()
    print(tf, "live", round(lm, 3), "n", W.loc[tf, "live_n"], "pct", round(pc, 3), "p2", round(2 * min(pc, 1 - pc), 3), "| stop pct", round((mS < ls).mean(), 3),
          "matched n", int(mt.sum()), "matched med", round(np.median(mR[mt]), 3), "matched pct", round(pm, 3), "| theirs pct", round(W.loc[tf, "pct_live"], 3))
    del T
