"""Verifier part 4: does the direction skill of the 374 SELECT-BH with-cells (and bot G) survive the real execution?
Variants of the w35 exit walk (frdeep.walk3 on the 1m grid, both sides):
  base         study: entry at the open of the first minute after the bar close, 0.124 % round trip
  cost2x       0.248 % round trip
  woo_real     0.173 % round trip = the WOO X Pro live executor's measured round-trip cost (11 trades, xc_exec_fills.py)
  late1        entry one minute later (open of the 2nd minute; the live executors enter 70-79 s after the close)
  late2        entry two minutes later
  late1_woo    late1 + 0.173 %
Per cell (flip_picked.csv, the study's own cellsig.cell_rows) on CONFIRM / LATE / FWD: with-side mean ROE vs its twin;
share of cells where the with side beats the twin; pooled signal-level gap; plus bot G (one position, study priority).
    python3 xc_cells_latency.py      -> xc_cells_latency.csv, xc_cells_latency_bot.csv"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xc_gbot_costs as XG          # noqa: E402
from xc_gbot_costs import *         # noqa: E402,F401

XG.VARS = {"base": dict(cost=COST, lag=0, fund=True), "cost2x": dict(cost=2 * COST, lag=0, fund=True),
           "woo_real": dict(cost=0.00173, lag=0, fund=True), "late1": dict(cost=COST, lag=1, fund=True),
           "late2": dict(cost=COST, lag=2, fund=True), "late1_woo": dict(cost=0.00173, lag=1, fund=True)}


def main():
    t0 = time.time()
    F = pd.read_csv(os.path.join(FY, "flip_picked.csv"))
    p = os.path.join(SH, "cells374_rows.pkl")
    if os.path.exists(p):
        A = pd.read_pickle(p)
    else:
        parts = []
        for i, r in F.iterrows():
            S = cell_rows(r["name"], r.etf, r.htf, r.kind, r.source, "W")
            if len(S):
                S = S[["coin", "e", "t", "side", "name", "tf", "w35_r", "w35_opp_r"]].copy()
                S["cell_i"] = i
                parts.append(S)
        A = pd.concat(parts, ignore_index=True)
        A.to_pickle(p)
    log("cell rows", len(A), f"{time.time() - t0:.0f}s")
    # walk each distinct (coin, e, side) once
    U = A[["coin", "e", "side"]].drop_duplicates().reset_index(drop=True)
    W = XG.rewalk(U)
    chk = U.merge(A[["coin", "e", "side", "w35_r"]].drop_duplicates(["coin", "e", "side"]), on=["coin", "e", "side"])
    log("base check max |r diff|", np.nanmax(np.abs(W["base"][0] - chk.w35_r.to_numpy())))
    key = U.coin.to_numpy(np.int64) * 10**9 * 4 + U.e.to_numpy(np.int64) * 4 + (U.side.to_numpy(np.int64) + 1)
    order = np.argsort(key)
    ka = A.coin.to_numpy(np.int64) * 10**9 * 4 + A.e.to_numpy(np.int64) * 4 + (A.side.to_numpy(np.int64) + 1)
    pos = order[np.searchsorted(key[order], ka)]
    rows = []
    for v in XG.VARS:
        r, k, w, ro, ko, wo = W[v]
        A[f"{v}_own"] = 35 * r[pos]
        A[f"{v}_opp"] = 35 * ro[pos]
        A[f"{v}_ok"] = np.isfinite(r[pos]) & np.isfinite(ro[pos]) & (w[pos] != 3) & (wo[pos] != 3)
    for per in ("SEL", "CONF", "LATE", "FWD"):
        P = period_rows(A, per)
        for v in XG.VARS:
            Q = P[P[f"{v}_ok"]]
            g = Q.groupby("cell_i").agg(n=(f"{v}_own", "size"), own=(f"{v}_own", "mean"), opp=(f"{v}_opp", "mean"))
            g = g[g.n > 0]
            Ud = Q.drop_duplicates(["coin", "e", "side", "name", "tf"])
            rows.append({"period": per, "variant": v, "cells": len(g), "beat_share": float((g.own > g.opp).mean()),
                         "cell_avg_own": g.own.mean(), "cell_avg_opp": g.opp.mean(),
                         "pooled_distinct_signals": len(Ud), "pooled_own": Ud[f"{v}_own"].mean(),
                         "pooled_opp": Ud[f"{v}_opp"].mean(), "pooled_gap": Ud[f"{v}_own"].mean() - Ud[f"{v}_opp"].mean()})
            print({k_: (round(x, 4) if isinstance(x, float) else x) for k_, x in rows[-1].items()})
    pd.DataFrame(rows).to_csv(os.path.join(MY, "xc_cells_latency.csv"), index=False, float_format="%.5g")
    # bot G under the new variants
    S = pd.read_pickle(os.path.join(SH, "G_rows.pkl"))
    Wg = XG.rewalk(S)
    brow = []
    for v in XG.VARS:
        r, k, w, ro, ko, wo = Wg[v]
        P0 = S.assign(w35_r=r, w35_roe=35 * r, w35_k=k, w35_why=w, w35_opp_r=ro, w35_opp_roe=35 * ro, w35_opp_k=ko,
                      w35_opp_why=wo)
        P0 = P0[np.isfinite(r) & np.isfinite(ro) & (w != 3) & (wo != 3)]
        for per in ("CONF", "LATE", "FWD"):
            res = XG.bot_read(period_rows(P0, per), per)
            brow.append({"variant": v, "period": per, **res})
            print(v, per, {k_: (round(x, 4) if isinstance(x, float) else x) for k_, x in res.items()
                           if k_ in ("trades", "per_day", "mean_roe", "mean_roe_pb", "flip_mean_roe", "px6_m04_pb",
                                     "pl50_m04_pb", "pl90_m04_pb", "med_m04_pb")})
    pd.DataFrame(brow).to_csv(os.path.join(MY, "xc_cells_latency_bot.csv"), index=False, float_format="%.5g")
    log("done", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
