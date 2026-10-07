import os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
TH, RES = sys.argv[1:3]
S0, S1 = pd.Timestamp("2021-08-01").value, pd.Timestamp("2026-09-30").value
R = pd.read_csv(RES)
R["m"] = (R.is_n * R.is_mean_pct + R.cf_n * R.cf_mean_pct) / (R.is_n + R.cf_n)
for tf in ("15m", "30m", "1h", "4h"):
    T = pd.read_pickle(os.path.join(TH, f"fyds_{tf}.pkl.gz"))
    T = T[(T.ts >= S0) & (T.ts < S1) & (T.v4n_lev > 0) & T.v4n_done]
    T["ret"] = T.v4n_ret.astype(float) * 100
    h = T.groupby("strategy", observed=True).agg(house=("ret", "mean"), h_is=("ret", lambda x: x[T.loc[x.index, "win"] == 0].mean()),
                                                 h_cf=("ret", lambda x: x[T.loc[x.index, "win"] == 1].mean()), n=("ret", "size"))
    h["Rm"] = T.groupby("strategy", observed=True).v4n_R.mean()
    out = [tf, "cells", len(h), "house cellavg %", round(h.house.mean(), 4), "pooled %", round(T.ret.mean(), 4)]
    for ex in ("X5_TRAIL2", "X2_SL15_TP3"):
        x = R[(R.tf == tf) & (R.exit == ex)].set_index("entry")
        j = h.join(x[["m", "is_mean_pct", "cf_mean_pct"]], how="inner")
        out += [ex, round(x.m.mean(), 4), "rho", round(j.house.rank().corr(j.m.rank()), 3),
                "IS&CF>0", list(x.index[(x.is_mean_pct > 0) & (x.cf_mean_pct > 0)])]
    out += ["house IS&CF>0 (n>=30)", list(h.index[(h.h_is > 0) & (h.h_cf > 0) & (h.n >= 30)])]
    print(*out)
