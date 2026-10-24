"""Verifier (lens: costs / executability / overlap) for the 'direction skill' claim, part 2: bot G under other costs.
  1. G's 321 cells in the study's exact order (rebuilt cell table copy, BH on SELECT paired t, SELECT mean + payback > 0,
     sorted by SELECT paired t), rows from the study's own cellsig.cell_rows / goalpath.bot_rows / goalpath.read ->
     reproduce goalpath_G.csv and goal_boot_G.csv (CONFIRM, margin 0.4, payback).
  2. Re-walk the w35 exits of every row (own side and coin-flip twin) with frdeep.walk3 on the 1m grid under:
       base       0.124 % round trip (must equal the grid)
       cost2x     0.248 % round trip (taker + slippage doubled)
       slip3x     taker 0.042 + slippage 0.06 each side = 0.204 %
       late1      entry at the open of the NEXT minute (one minute of order latency), base cost
       late1_2x   both
       nofund     funding set to 0
     then the bot again (one position at a time over all coins, the study's priority), its coin flip, and the 30-day
     bootstrap at margin 0.4 with the payback.
Writes only under this folder (xc_gbot_costs.csv) and /dev/shm/claude_verify_xc.
    python3 xc_gbot_costs.py"""
import os
import sys
import time
FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, FY)
sys.path.insert(0, "/home/user/crypto-bot-research/research/friendroc/code")
from goalpath import *              # noqa: E402,F401  (cellsig, RD, pd, np, read, bot_rows ...)
from fy_analyze import bh, pval     # noqa: E402
from frdeep import walk3            # noqa: E402

MY = os.path.dirname(os.path.abspath(__file__))
SH = "/dev/shm/claude_verify_xc"
PB35 = 35 * PAYBACK


def g_specs():
    fam = pd.read_pickle(os.path.join(SH, "cells.pkl"))
    Wf = fam[(fam.SEL_nW >= 60) & (fam.SEL_MW >= 12)].copy()
    Wf["bh"] = bh(pval(Wf.SEL_tFlip.to_numpy(), Wf.SEL_MW.to_numpy()))
    g = Wf[Wf.bh & (Wf.SEL_mW + 35 * PAYBACK > 0)].sort_values("SEL_tFlip", ascending=False)
    return [(r["name"], r.etf, r.htf, r.kind, r.source, "W") for _, r in g.iterrows()]


VARS = {"base": dict(cost=COST, lag=0, fund=True), "cost2x": dict(cost=2 * COST, lag=0, fund=True),
        "slip3x": dict(cost=2 * (0.00042 + 0.0006), lag=0, fund=True), "late1": dict(cost=COST, lag=1, fund=True),
        "late1_2x": dict(cost=2 * COST, lag=1, fund=True), "nofund": dict(cost=COST, lag=0, fund=False)}


def rewalk(S):
    """{variant: (r_own, k_own, why_own, r_opp, k_opp, why_opp)} per row of S."""
    out = {v: [np.full(len(S), np.nan), np.full(len(S), -1, np.int64), np.full(len(S), -1, np.int8),
               np.full(len(S), np.nan), np.full(len(S), -1, np.int64), np.full(len(S), -1, np.int8)] for v in VARS}
    dummy = np.zeros(1, bool)
    for ci, coin in enumerate(COINS):
        m = np.flatnonzero(S.coin.to_numpy() == ci)
        if not len(m):
            continue
        g = grid(coin)
        o, h, l, c, n = g["o"], g["h"], g["l"], g["c"], g["n"]
        cumf1 = np.cumsum(g["fund"])
        cumf0 = np.zeros_like(cumf1)
        e = S.e.to_numpy(np.int64)[m]
        sd = S.side.to_numpy()[m]
        for v, cfg in VARS.items():
            es_all = e + cfg["lag"]
            cf = cumf1 if cfg["fund"] else cumf0
            for which, sgn in ((0, 1), (3, -1)):
                for s in (1, -1):
                    q = np.flatnonzero(sd * sgn == s)
                    if not len(q):
                        continue
                    ue, inv = np.unique(es_all[q], return_inverse=True)
                    a = walk3(o, h, l, c, cf, ue, s, 35.0, cfg["cost"], FL, STEP, GAP, -0.50, 9.0, 0.01, 0, dummy,
                              False, c, o, 0.0, n)
                    rows = m[q]
                    out[v][which][rows] = a[0][inv]
                    out[v][which + 1][rows] = a[1][inv] + cfg["lag"]      # minutes from the SIGNAL minute e
                    out[v][which + 2][rows] = a[2][inv]
        drop(coin)
        log(coin, "rewalked", len(m))
    return out


def bot_read(P, per):
    took = RD.one_position(P, "w35", priority="prio")
    T = P[took]
    tko = RD.one_position(P, "w35", side_col="_opp", priority="prio")
    To = P[tko]
    a, b = PER_SPAN[per]
    days = (b - a) / DAY
    res = {"trades": len(T), "per_day": len(T) / days, "mean_roe": T.w35_roe.mean(),
           "mean_roe_pb": (T.w35_roe + PB35).mean(), "win": (T.w35_roe > 0).mean(), "flip_trades": len(To),
           "flip_mean_roe": To.w35_opp_roe.mean(), "stop_share": (T.w35_why == 0).mean(),
           "long_share": (T.side > 0).mean()}
    if per in ("CONF", "FWD") and len(T) >= 10:
        gb = RD.goal_bootstrap(T.assign(w35_roe=T.w35_roe + PB35), "w35", margin=0.4, days=PER_SPAN[per], n_boot=4000)
        res.update({"px6_m04_pb": gb["p_target"], "pl50_m04_pb": gb["p_lose50_first"],
                    "pl90_m04_pb": gb["p_lose90_first"], "med_m04_pb": gb["median_final_x"]})
        m_opt, x_opt = growth_opt(T.w35_roe.to_numpy() + PB35, res["per_day"])
        res["gopt_margin_pb"], res["gopt_30d_x_pb"] = m_opt, x_opt
    return res


def main():
    t0 = time.time()
    specs = g_specs()
    log("G cells", len(specs))
    p = os.path.join(SH, "G_rows.pkl")
    if os.path.exists(p):
        S = pd.read_pickle(p)
    else:
        S = bot_rows(specs)
        S.to_pickle(p)
    log("rows", len(S), f"{time.time() - t0:.0f}s")
    rows = []
    # 1. reproduce the study's own read
    for per in ("SEL", "CONF", "LATE", "FWD"):
        o, T = read(S, per)
        rows.append({"variant": "study_read", "period": per, **{k: o[k] for k in ("trades", "per_day", "mean_roe",
                     "mean_roe_pb", "win", "opp_mean_roe")}})
        if per == "CONF":
            gb = RD.goal_bootstrap(T.assign(w35_roe=T.w35_roe + PB35), "w35", margin=0.4, days=PER_SPAN[per], n_boot=4000)
            rows[-1].update({"px6_m04_pb": gb["p_target"], "pl50_m04_pb": gb["p_lose50_first"],
                             "pl90_m04_pb": gb["p_lose90_first"], "med_m04_pb": gb["median_final_x"]})
        print(rows[-1])
    # 2. re-walk
    W = rewalk(S)
    base_r = W["base"][0]
    d = np.nanmax(np.abs(base_r - S.w35_r.to_numpy()))
    dk = int((W["base"][1] != S.w35_k.to_numpy()).sum())
    do = np.nanmax(np.abs(W["base"][3] - S.w35_opp_r.to_numpy()))
    log("base re-walk vs grid: max |r diff|", d, "opp", do, "k mismatches", dk)
    for v in VARS:
        r, k, w, ro, ko, wo = W[v]
        P0 = S.assign(w35_r=r, w35_roe=35 * r, w35_k=k, w35_why=w, w35_opp_r=ro, w35_opp_roe=35 * ro, w35_opp_k=ko,
                      w35_opp_why=wo)
        ok = np.isfinite(r) & np.isfinite(ro) & (w != 3) & (wo != 3)
        P0 = P0[ok]
        for per in ("SEL", "CONF", "LATE", "FWD"):
            P = period_rows(P0, per)
            res = bot_read(P, per)
            # signal-level (all rows, no one-position): with side vs twin
            res.update({"sig_n": len(P), "sig_mean": P.w35_roe.mean(), "sig_opp": P.w35_opp_roe.mean()})
            rows.append({"variant": v, "period": per, **res})
            print(v, per, {k_: (round(x, 5) if isinstance(x, float) else x) for k_, x in res.items()})
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(MY, "xc_gbot_costs.csv"), index=False, float_format="%.5g")
    log("done", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
