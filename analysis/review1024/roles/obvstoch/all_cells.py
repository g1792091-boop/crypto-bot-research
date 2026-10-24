"""Descriptive (after the one CONF read of the picks): every cell x period (PRE, SEL, CONF, YTD, FWD, FIVE) with the
coin-flip twin, against-trend, trend-only and timing-only controls. NOT for picking (PLAN.md section 4).
Writes all_cells.csv.gz and controls_all.csv."""
import oscore as O
from oscore import *

D = O.load_all()
PERS = ("PRE", "SEL", "CONF", "YTD", "FWD", "FIVE")
ctl = []
for per in PERS:
    a, b = O.P[per]
    nd = (min(b, ext_end()) - a) / DAY
    for (tf, htf) in O.MAPS:
        for X in O.EXITS:
            for T in O.TRENDS:
                s = O.summarize(O.rows(D, tf, htf, T, None, X, per, trend_only=True))
                s.update(period=per, kind="trend_only", tf=tf, htf=htf, trend=T, timing="", exit=X, per_day=s["n"] / nd)
                ctl.append(s)
    for tf in O.ENTRY_TFS:
        for X in O.EXITS:
            for Ot in O.TIMINGS:
                s = O.summarize(O.rows(D, tf, None, None, Ot, X, per, timing_only=True))
                s.update(period=per, kind="timing_only", tf=tf, htf="", trend="", timing=Ot, exit=X, per_day=s["n"] / nd)
                ctl.append(s)
CT = pd.DataFrame(ctl)
CT.to_csv("controls_all.csv", index=False)
to = CT[CT.kind == "trend_only"].set_index(["period", "tf", "htf", "trend", "exit"]).mean_roe
ti = CT[CT.kind == "timing_only"].set_index(["period", "tf", "timing", "exit"]).mean_roe
recs = []
for per in PERS:
    a, b = O.P[per]
    nd = (min(b, ext_end()) - a) / DAY
    for (tf, htf, T, Ot, X) in O.cells():
        R = O.rows(D, tf, htf, T, Ot, X, per)
        s = O.summarize(R)
        Ra = O.rows(D, tf, htf, T, Ot, X, per, against=True)
        s.update(period=per, cell=O.cell_id(tf, htf, T, Ot, X), tf=tf, htf=htf, trend=T, timing=Ot, exit=X,
                 per_day=s["n"] / nd, n_against=len(Ra["roe"]),
                 mean_against=float(Ra["roe"].mean()) if len(Ra["roe"]) else np.nan,
                 trend_only=to[(per, tf, htf, T, X)], timing_only=ti[(per, tf, Ot, X)],
                 mean_roe_pb=s["mean_roe"] + PAYBACK * O.LEVX[X])
        recs.append(s)
A = pd.DataFrame(recs)
A.to_csv("all_cells.csv.gz", index=False, float_format="%.6g")
print(A.groupby("period")[["mean_roe", "mean_opp", "mean_d", "mean_against", "trend_only", "timing_only", "long_share"]].mean().round(4))
print(A.groupby("period").apply(lambda g: pd.Series({"cells": len(g), "pos": int((g.mean_roe > 0).sum()),
      "pos_pb": int((g.mean_roe_pb > 0).sum()), "d_pos": int((g.mean_d > 0).sum())})))
