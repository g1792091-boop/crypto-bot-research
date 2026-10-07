import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from vlib import *
E = EXP + "/current"
sig = pd.read_csv(E + "/signal_log.csv")
acc = pd.read_csv(E + "/accounts.csv")
dsdefs = set(acc[acc.kind == "ds200"].strategy)
s = sig[(sig.status == "SUBMITTED") & sig.strategy.isin(dsdefs)]
print("ds SUBMITTED", len(s), "status mix all ds:", sig[sig.strategy.isin(dsdefs)].status.value_counts().to_dict())
K = {k: set(zip(g.bar_close, g.symbol, g.side)) for k, g in s.groupby(["strategy", "timeframe"])}
def ov(a, b, tf, tf2=None):
    A = K.get((a, tf), set()); Bs = K.get((b, tf2 or tf), set())
    if tf2:  # cross-tf same def: compare (symbol, side, approx time) - use exact bar_close
        pass
    c = len(A & Bs)
    return f"{a}@{tf} n{len(A)} vs {b}@{tf2 or tf} n{len(Bs)}: common {c}, A in B {c}/{len(A)}, B in A {c}/{len(Bs)}, identical {A == Bs}"
pairs = [("F5_BOX_HTF", "F5_BOX"), ("F13_RAID_PD", "F11_RAID"), ("F11_TSOUP", "F11_RAID"), ("F11_TSOUP", "F13_RAID_PD"), ("F17_Z_HL", "F17_Z"),
         ("F12_MSS_DISP", "F12_MSS"), ("F13_FVG_PD", "F9_FVG"), ("F10_M2022", "F9_FVG"), ("F16_FIB618", "F10_OTE"), ("F7_RF_ONLY", "F7_RF_TRIPLE"),
         ("F1_MOM_DIV", "F1_RSI_DIV"), ("F1_PVT_DIV", "F1_RSI_DIV"), ("F1_PVT_DIV", "F1_MOM_DIV"), ("F5_BOX_RSI", "F5_BOX")]
for tf in ["15m", "30m", "1h", "4h"]:
    for a, b in pairs:
        if (a, tf) in K or (b, tf) in K:
            print(tf, ov(a, b, tf))
# cross tf for F15
for d in ["F15_OPEN0000", "F15_OPEN0930", "F15_ASIA_BRK", "F15_LON_BRK", "F15_ORB", "F15_ASIA_SWEEP"]:
    for t1, t2 in [("15m", "30m"), ("15m", "1h"), ("30m", "1h")]:
        A = K.get((d, t1), set()); Bs = K.get((d, t2), set())
        A2 = {(x[1], x[2]) + (x[0] // 86400000,) for x in A}; B2 = {(x[1], x[2]) + (x[0] // 86400000,) for x in Bs}
        print(d, t1, t2, "n", len(A), len(Bs), "same bar_close common", len(A & Bs), "same day/coin/side common", len(A2 & B2))
# F10_OTE vs F16_FIB618 4h; F17 1h/4h
# 4h-specific: list ds signals at 4h for listed defs
for d in ["F5_BOX", "F13_FVG_PD", "F1_RSI_DIV", "F10_M2022", "F4_PULL", "F4_PULL_RSI", "F1_PVT_DIV", "F5_BOX_RSI", "F1_MOM_DIV", "F12_MSS_DISP"]:
    for tf in ["1h", "4h"]:
        print("live signals", d, tf, len(K.get((d, tf), set())), "per day %.2f" % (len(K.get((d, tf), set())) / 1.503))
