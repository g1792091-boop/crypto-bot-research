"""Verifier: per year block, split the with - all effect of the 1h judges on 15m / 30m entries into a timing part
((with + coin-flip twin)/2 - all) and a direction part ((with - twin)/2); and the share of all 1h sources whose
with - all effect is positive in all six blocks.     python3 v_years.py"""
import numpy as np
import pandas as pd
import v_perm as V

R = pd.read_csv("v_real.csv")
for nm in ("j_V4OF4", "j_DIR"):
    si = V.SRCS.index(nm)
    for ti in range(2):
        W = V.with_sums(V.ST[:, si], ti)
        A = V.ALLB[ti]
        mW, mO, mA = W[:, 1] / W[:, 0], W[:, 2] / W[:, 0], A[:, 1] / A[:, 0]
        print(nm, V.TFN[ti], "eff", np.round(100 * (mW - mA), 2), "timing", np.round(100 * ((mW + mO) / 2 - mA), 2),
              "direction", np.round(100 * (mW - mO) / 2, 2), "long share", np.round(W[:, 0] * 0 + 0, 0)[:0])
for tf in ("15m", "30m"):
    q = R[R.tf == tf]
    ally = (q[[f"eff_y{b}" for b in range(6)]] > 0).all(1)
    print(tf, "sources", len(q), "all 6 years eff>0:", int(ally.sum()), "| both SEL&CONF eff>0:",
          int(((q.eff_SEL > 0) & (q.eff_CONF > 0)).sum()), "| flip both >0:", int(((q.flip_SEL > 0) & (q.flip_CONF > 0)).sum()))
    q = q.assign(mn=np.minimum(q.eff_SEL, q.eff_CONF))
    print(q.sort_values("mn", ascending=False)[["src", "eff_SEL", "eff_CONF", "flip_SEL", "flip_CONF", "timing_SEL",
                                                 "timing_CONF", "t_eff_SEL", "t_eff_CONF", "years_pos", "years_flip_pos"]].head(12).round(4).to_string())
    print("rank of V4OF4 by SEL eff:", int((q.eff_SEL > q[q.src == "j_V4OF4"].eff_SEL.iloc[0]).sum()) + 1,
          "by SEL t:", int((q.t_eff_SEL > q[q.src == "j_V4OF4"].t_eff_SEL.iloc[0]).sum()) + 1, "of", len(q))
