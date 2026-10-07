#!/usr/bin/env python3
"""The nightly d3 'limit' shadow (v4, final klines) joined with the pipeline's market replay of the same signals:
fill rate, what the MISSED signals did at market (missed winners vs losers), filled limit vs market, net per signal.

    python3 -I c08_limit_d3.py <export_dir> <rb replay_signals.csv> <out_dir>

d3 limit = limit 0.25 ATR better than the reference, valid one bar of the signal's timeframe (from the minute the
signal was ready), filled when a 1m bar trades through it; stop 2 ATR from the LIMIT price (shifted), same leverage
rules; ROE adjusted by daily3 for the maker fee and no entry slippage. ROE -> base-R units with the market trade's
leverage and stop distance: R = ROE / (leverage x stop_frac).  Unfilled = 0 for the net per signal.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MIN = 60_000
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}


def cboot(x, cl, B=4000, seed=7):
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    x, cl = x[ok], np.asarray(cl)[ok]
    if len(x) < 5:
        return np.nan, np.nan, np.nan
    u, inv = np.unique(cl, return_inverse=True)
    s, c = np.bincount(inv, weights=x), np.bincount(inv)
    rng = np.random.default_rng(seed)
    d = rng.integers(0, len(u), size=(B, len(u)))
    m = s[d].sum(1) / c[d].sum(1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)), float((m <= 0).mean())


def main():
    root, rep, out = sys.argv[1:4]
    L = pd.read_csv(os.path.join(root, "current", "d3_shadows.csv"))
    L = L[L["kind"] == "limit"].copy().rename(columns={"kind": "shadow_kind"})
    parts = L["key"].str.split("|", expand=True)
    L["bar_close"] = parts[3].astype(np.int64)
    P = pd.read_csv(rep)
    P = P[(P["run"] == "current") & (P["status"].isin(["TRADED", "UNRESOLVED"]))].copy()
    P["Rm"] = np.where(P["status"] == "TRADED", P["R"], P["mark_R"])
    P["sf"] = P["stop_frac"]
    # unresolved rows have no stop_frac: from entry / stop_initial
    miss = P["sf"].isna() & P["entry_price"].notna() & P["stop_initial"].notna()
    P.loc[miss, "sf"] = (P.loc[miss, "entry_price"] - P.loc[miss, "stop_initial"]).abs() / P.loc[miss, "entry_price"]
    P = P.drop_duplicates(["account_id", "symbol", "bar_close"])
    J = L.merge(P[["account_id", "symbol", "bar_close", "kind", "Rm", "sf", "leverage", "status"]],
                on=["account_id", "symbol", "bar_close"], how="inner")
    J = J[J["kind"].isin(["strategy", "ds200"]) & J["timeframe"].isin(list(TFM))]
    J["R_limit"] = J["roe"] / (J["leverage"] * J["sf"])
    J["R_net_signal"] = np.where(J["filled"] == 1, J["R_limit"], 0.0)
    m = J["timeframe"].map(TFM).clip(lower=60)
    J["cluster"] = (J["bar_close"] // MIN // m * m).astype(str)
    rows = []
    for keys, g in list(J.groupby(["kind", "timeframe"])) + [(("core+ds", "15m+30m"),
                                                            J[J["timeframe"].isin(["15m", "30m"])])]:
        f = g[(g["filled"] == 1) & g["R_limit"].notna()]
        u = g[g["filled"] == 0]
        ok = g[(g["filled"] == 0) | g["R_limit"].notna()]          # filled-and-unresolved d3 rows dropped
        d = ok["R_net_signal"] - ok["Rm"]
        lo, hi, p = cboot(d, ok["cluster"])
        rows.append({"kind": keys[0], "tf": keys[1], "signals_joined": len(g), "fill_rate": g["filled"].mean(),
                     "filled_resolved": len(f), "unfilled": len(u),
                     "market_R_all": ok["Rm"].mean(),
                     "market_R_unfilled (missed)": u["Rm"].mean(), "missed_winner_share": (u["Rm"] > 0).mean(),
                     "market_R_filled": f["Rm"].mean(), "limit_R_filled": f["R_limit"].mean(),
                     "gain_on_filled": (f["R_limit"] - f["Rm"]).mean(),
                     "net_per_signal_limit": ok["R_net_signal"].mean(),
                     "net_minus_market": d.mean(), "ci_lo": lo, "ci_hi": hi, "p_le0": p,
                     "clusters": ok["cluster"].nunique()})
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(out, "c08_limit_d3.csv"), index=False)
    pd.set_option("display.width", 250)
    print(T.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
