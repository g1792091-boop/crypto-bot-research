#!/usr/bin/env python3
"""(a) What each rule saved vs what it killed (trade-off decomposition), (b) the value of an exit-now decision at the
AI's own decision points (k bars of the signal's timeframe after entry), by the state visible on the chart then.

    python3 -I state_exit.py <out_dir>      (reads <out_dir>/rules_signals.csv)

exit-now R at k bars = unrealized R at that bar close - (entry fee + exit fee + exit slippage) in R
(taker 0.0005, slippage 0.0002, funding ignored); hold value = the base trade's final R (open-at-end marked).
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True
import site  # noqa: E402
sys.path.append(site.getusersitepackages())
import os  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MIN = 60_000
RUNS = {"run-20261005T183457Z": "v3b", "current": "v4"}
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
TAKER, SLIP = 0.0005, 0.0002
B = 5000


def cl_ci(d, cl, rng):
    u, inv = np.unique(cl, return_inverse=True)
    sums = np.bincount(inv, weights=d)
    cnt = np.bincount(inv)
    k = len(u)
    if k < 3:
        return np.nan, np.nan, np.nan
    idx = rng.integers(0, k, size=(B, k))
    bs = sums[idx].sum(1) / cnt[idx].sum(1)
    signs = rng.choice([-1.0, 1.0], size=(B, k))
    null = signs @ sums / len(d)
    p_two = (np.sum(np.abs(null) >= abs(d.mean()) - 1e-15) + 1) / (B + 1)
    return np.percentile(bs, 2.5), np.percentile(bs, 97.5), p_two


def main():
    out = sys.argv[1]
    R = pd.read_csv(os.path.join(out, "rules_signals.csv"))
    R = R[R["base_status"].isin(["TRADED", "UNRESOLVED"]) & R["kind"].isin(["strategy", "ds200"])].copy()
    R["run_s"] = R["run"].map(RUNS)
    R["tfm"] = R["timeframe"].map(TFM)
    R["cl"] = R["run_s"] + "|" + (R["bar_close"] // (np.maximum(R["tfm"], 60) * MIN)).astype(str)
    stop_frac = (R["base_entry_price"] - R["base_stop_initial"]).abs() / R["base_entry_price"]
    R["cost_now_R"] = (2 * TAKER + SLIP) / stop_frac
    rng = np.random.default_rng(7)

    # (a) trade-off decomposition per rule
    rows = []
    for rule in ["BE05", "NP4", "NP8", "TP1", "CUT05", "OPP", "OPPH"]:
        for (kind, tf), g in R.groupby(["kind", "timeframe"]):
            d = g[f"{rule}_R"] - g["base_R"]
            ch = d.abs() > 1e-9
            helped = d > 1e-9
            hurt = d < -1e-9
            rows.append({"rule": rule, "kind": kind, "tf": tf, "n": len(g), "changed": int(ch.sum()),
                         "helped": int(helped.sum()), "hurt": int(hurt.sum()),
                         "gain_helped_R_sum": d[helped].sum(), "loss_hurt_R_sum": d[hurt].sum(),
                         "mean_gain_per_helped": d[helped].mean() if helped.any() else np.nan,
                         "mean_loss_per_hurt": d[hurt].mean() if hurt.any() else np.nan,
                         "net_per_signal": d.mean(),
                         "breakeven_precision": (-d[hurt].mean()) / (d[helped].mean() - d[hurt].mean())
                         if helped.any() and hurt.any() else np.nan,
                         "actual_precision": helped.sum() / max(ch.sum(), 1)})
    TO = pd.DataFrame(rows)
    TO.to_csv(os.path.join(out, "rule_tradeoff.csv"), index=False)

    # (b) exit-now value at k bars by visible state
    srows = []
    for kb in (1, 2, 4):
        c_unr, c_mfe = f"p_unr_{kb}bar_R", f"p_mfe_{kb}bar_R"
        c_lock = f"p_lock_{kb}bar"
        g0 = R[R[c_unr].notna()].copy()
        g0["exit_now_R"] = g0[c_unr] - g0["cost_now_R"]
        g0["hold_minus_exit"] = g0["base_R"] - g0["exit_now_R"]
        bins = [-9, -0.5, -0.2, 0.0, 0.3, 0.6, 99]
        labels = ["<-0.5", "-0.5..-0.2", "-0.2..0", "0..0.3", "0.3..0.6", ">=0.6"]
        g0["state"] = pd.cut(g0[c_unr], bins=bins, labels=labels, right=False)
        g0["lock"] = g0[c_lock].astype(str)
        for kind in ("strategy", "ds200"):
            for tf in ("15m", "30m", "1h"):
                gk = g0[(g0["kind"] == kind) & (g0["timeframe"] == tf)]
                if not len(gk):
                    continue
                for st in labels + ["ALL"]:
                    g = gk if st == "ALL" else gk[gk["state"] == st]
                    if len(g) < 5:
                        continue
                    d = g["hold_minus_exit"].to_numpy(float)
                    lo, hi, p = cl_ci(d, g["cl"].to_numpy(), rng)
                    row = {"k_bars": kb, "kind": kind, "tf": tf, "state_unrealized_R": st, "n": len(g),
                           "share_of_open": len(g) / len(gk), "mean_exit_now_R": g["exit_now_R"].mean(),
                           "mean_hold_R": g["base_R"].mean(), "hold_minus_exit": d.mean(), "ci_lo": lo, "ci_hi": hi,
                           "p_two": p, "share_lock_armed": (g["lock"] == "True").mean()}
                    for rs in ("v3b", "v4"):
                        gg = g[g["run_s"] == rs]
                        row[f"n_{rs}"] = len(gg)
                        row[f"hold_minus_exit_{rs}"] = gg["hold_minus_exit"].mean() if len(gg) else np.nan
                    srows.append(row)
    ST = pd.DataFrame(srows)
    # BH over the state cells (excluding ALL)
    m = (ST["state_unrealized_R"] != "ALL") & ST["p_two"].notna()
    p = ST.loc[m, "p_two"].to_numpy()
    o = np.argsort(p)
    q = p[o] * len(p) / np.arange(1, len(p) + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    qq = np.empty(len(p))
    qq[o] = np.minimum(q, 1)
    ST["bh_q"] = np.nan
    ST.loc[m, "bh_q"] = qq
    ST.to_csv(os.path.join(out, "exit_now_by_state.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(TO.round(3).to_string())
    print(ST.round(3).to_string())


if __name__ == "__main__":
    main()
