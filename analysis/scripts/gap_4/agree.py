"""Two-porter agreement on BTC 15m (IS window, bars >= warmup): critic's spec ports vs gap_4's
independent spec ports.  This is NOT the requested diff against fingrad evaluate() (that code
is not available); it measures how much the prose spec under-determines the signals."""
import os, sys, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "bt"))
from run import load_csv, window_bounds
import critic_extra_ports as CR
import ports12 as P

D = os.path.join(HERE, "..", "data")
pairs = [("N11_BREAKAWAY*", "N11_BREAKAWAY"), ("N13_3OUTSIDE*", "N13_3OUTSIDE"), ("N19_FIB_CHOP*", "N19_FIB_CHOP"),
         ("N20_EMA9_CHOP*", "N20_EMA9_CHOP"), ("S4_BB_BBP*", "S4_BB_BBP"), ("N15_KC_AO*", "N15_KC_AO")]
rows = []
for sym in ("BTCUSD", "ETHUSD", "SOLUSD", "LTCUSD", "BCHUSD"):
    df = load_csv(os.path.join(D, f"{sym.lower()}-15m-ohlcv.csv"), 15)
    lo, hi = window_bounds(df, "IS"); lo = max(lo, 1000)
    for cn, mn in pairs:
        cl, cs = CR.EXTRA[cn](df); cl = np.asarray(cl, bool); cs = np.asarray(cs, bool) & ~cl
        for var in (0, 1):
            if var == 1 and mn not in ("N11_BREAKAWAY", "N13_3OUTSIDE", "N19_FIB_CHOP"):
                continue
            s = P.PORTS12[mn](df, variant=var)
            ml, ms = s["L"], s["S"]
            a = np.where(cl[lo:hi], 1, np.where(cs[lo:hi], -1, 0))
            b = np.where(ml[lo:hi], 1, np.where(ms[lo:hi], -1, 0))
            ca, cb = int((a != 0).sum()), int((b != 0).sum())
            both = int(((a != 0) & (a == b)).sum())
            union = int(((a != 0) | (b != 0)).sum())
            rows.append(dict(symbol=sym, strategy=mn, my_variant=var, critic_signals=ca, my_signals=cb, same=both,
                             jaccard=both / union if union else np.nan,
                             bar_agreement=float((a == b).mean())))
R = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(R[R.symbol == "BTCUSD"].round(4).to_string(index=False))
g = R.groupby(["strategy", "my_variant"])[["critic_signals", "my_signals", "same"]].sum()
g["jaccard_all5"] = g["same"] / (g["critic_signals"] + g["my_signals"] - g["same"])
print(g.round(3).to_string())
R.to_csv(os.path.join(HERE, "agree.csv"), index=False)
