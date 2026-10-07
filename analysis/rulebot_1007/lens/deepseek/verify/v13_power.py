import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from vlib import *
R = load_replay(); T = R[R.status == "TRADED"]
days = 1.503
for tf in ["15m", "30m"]:
    g = T[T.timeframe == tf]
    rows = []
    for s, c in g.groupby("strategy"):
        if len(c) >= 10 and c.cl1h.nunique() >= 8:
            x = crse(c.R, c.cl1h); x4 = crse(c.R, c.cl4h)
            rows.append(dict(s=s, n=len(c), se=x["se"], deff=x["deff"], deff4=x4["deff"], sd=x["sd"], perday=len(c) / days))
    D = pd.DataFrame(rows)
    sd = g.R.std(ddof=1)
    med_se = D.se.median(); med_deff = D.deff.median(); med_deff4 = D.deff4.median(); med_rate = D.perday.median()
    print(tf, "pooled sd %.3f" % sd, "cells", len(D), "median cell SE %.3f" % med_se, "median deff(1h) %.2f deff(4h) %.2f" % (med_deff, med_deff4),
          "median MDE80 two-sided %.2f one-sided %.2f" % (2.80 * med_se, 2.49 * med_se), "median cell signals/day %.1f" % med_rate)
    for eff in (0.1, 0.2):
        for z, lab in ((2.80, "two-sided"), (2.49, "one-sided")):
            for de, dl in ((med_deff, "deff1h"), (med_deff4, "deff4h"), (3.05 if tf == "15m" else 2.24, "tf-level deff1h")):
                n = (z * sd / eff) ** 2 * de
                print("   effect %.1f %s %s: n %.0f signals, days at median rate %.0f" % (eff, lab, dl, n, n / med_rate))
