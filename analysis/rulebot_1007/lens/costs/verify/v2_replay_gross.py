#!/usr/bin/env python3
"""Every-signal replay (pipeline replay_signals.csv): net, paper cost and pre-cost gross in R, with
cluster-size sensitivity, run split and de-duplication of identical (coin, bar, side) replays.

python3 -I v2_replay_gross.py <replay_signals.csv> <out_dir>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vboot  # noqa
import numpy as np
import pandas as pd

TFM = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


def cboot(x, cl, B=4000, seed=7):
    x = np.asarray(x, float)
    u, inv = np.unique(np.asarray(cl), return_inverse=True)
    k = len(u)
    if k < 3:
        return np.nan, np.nan, k
    s = np.bincount(inv, weights=x, minlength=k)
    c = np.bincount(inv, minlength=k).astype(float)
    rng = np.random.default_rng(seed)
    d = rng.integers(0, k, size=(B, k))
    m = s[d].sum(1) / c[d].sum(1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5), k


def main():
    src, out = sys.argv[1], sys.argv[2]
    R = pd.read_csv(src)
    R = R[R["status"].isin(["TRADED", "UNRESOLVED"])].copy()
    R["grp"] = R["kind"].map({"strategy": "core36", "ds200": "ds200", "random": "coinflip"})
    R["notional"] = R["qty"] * R["entry_price"]
    R["risk"] = R["qty"] * (R["entry_price"] - R["stop_initial"]).abs()
    R["stop_frac_fill"] = (R["entry_price"] - R["stop_initial"]).abs() / R["entry_price"]
    res = R["status"] == "TRADED"
    # exit notional from fees for taker exits (fees = taker*(N_in + N_out)); TP exits are maker (reel only, none here)
    n_out = np.where(res, R["fees"] / 0.0005 - R["notional"], R["notional"])
    stop_exit = R["exit_reason"].isin(["SL", "LOCK"]) | ~res
    slip = 0.0002 / 1.0002 * R["notional"] + np.where(stop_exit, 0.0002 / (1 - 0.0002) * n_out, 0)
    fees = np.where(res, R["fees"], 0.0005 * 2 * R["notional"])
    fund = np.where(res, R["funding"].fillna(0), 0)
    R["Rx"] = np.where(res, R["R"], R["mark_R"])
    R["cost_R"] = (fees + fund + slip) / R["risk"]
    R["gross_R"] = R["Rx"] + R["cost_R"]
    R["cost_bps"] = R["cost_R"] * R["stop_frac_fill"] * 1e4
    ts = (R["bar_close"] // 60000).astype(np.int64)
    for h in (1, 4, 12, 24):
        m = np.maximum(R["timeframe"].map(TFM), 60 * h).astype(np.int64)
        R[f"cl{h}h"] = R["run"] + "|" + (ts // m * m).astype(str)
    R["dupkey"] = R["run"] + "|" + R["symbol"] + "|" + R["bar_close"].astype(str) + "|" + R["timeframe"] + "|" + \
        R["side"].astype(str) + "|" + R["leverage"].astype(str)
    R.to_csv(os.path.join(out, "v2_replay_rows.csv"), index=False)
    pd.set_option("display.width", 260)
    rows = []
    for (g, tf), d in R.groupby(["grp", "timeframe"]):
        r = dict(grp=g, tf=tf, n=len(d), n_unres=int((d["status"] == "UNRESOLVED").sum()), net=d["Rx"].mean(),
                 net_resolved=d.loc[d.status == "TRADED", "R"].mean(), gross=d["gross_R"].mean(),
                 cost=d["cost_R"].mean(), cost_bps=d["cost_bps"].mean(), stop_med=d["stop_frac_fill"].median() * 100)
        for h in (1, 4, 12, 24):
            lo, hi, k = cboot(d["gross_R"], d[f"cl{h}h"])
            r[f"k{h}h"] = k
            r[f"ci{h}h"] = f"[{lo:+.3f},{hi:+.3f}]"
        dd = d.drop_duplicates("dupkey")
        r["n_dedup"] = len(dd)
        r["gross_dedup"] = dd["gross_R"].mean()
        lo, hi, k = cboot(dd["gross_R"], dd["cl4h"])
        r["ci_dedup4h"] = f"[{lo:+.3f},{hi:+.3f}]"
        rows.append(r)
    D = pd.DataFrame(rows)
    print(D.round(4).to_string(index=False))
    D.to_csv(os.path.join(out, "v2_replay_by_tf.csv"), index=False)
    # pooled core36+ds200
    rows = []
    for tf in ("15m", "30m", "1h", "4h"):
        d = R[R["grp"].isin(["core36", "ds200"]) & (R["timeframe"] == tf)]
        r = dict(tf=tf, n=len(d), net=d["Rx"].mean(), gross=d["gross_R"].mean(), cost=d["cost_R"].mean())
        for h in (1, 4, 12, 24):
            lo, hi, k = cboot(d["gross_R"], d[f"cl{h}h"])
            r[f"k{h}h"] = k
            r[f"ci{h}h"] = f"[{lo:+.3f},{hi:+.3f}]"
        dd = d.drop_duplicates("dupkey")
        lo, hi, k = cboot(dd["gross_R"], dd["cl4h"])
        r.update(n_dedup=len(dd), gross_dedup=dd["gross_R"].mean(), ci_dedup4h=f"[{lo:+.3f},{hi:+.3f}]")
        for run in ("run-20261005T183457Z", "current"):
            x = d[d["run"] == run]
            r[f"gross_{run[:7]}"] = x["gross_R"].mean()
            r[f"n_{run[:7]}"] = len(x)
        rows.append(r)
    P = pd.DataFrame(rows)
    print(P.round(4).to_string(index=False))
    P.to_csv(os.path.join(out, "v2_replay_pooled.csv"), index=False)


if __name__ == "__main__":
    main()
