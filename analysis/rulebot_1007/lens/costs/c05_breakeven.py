#!/usr/bin/env python3
"""Break-even tables: how much gross edge (R) a 15m / 30m trade needs under each execution assumption, by coin and
by volatility (stop as % of price), from the every-signal base replay (v3b + v4, accounting on the base price path).

    python3 -I c05_breakeven.py <c04_replay_rows_rb.csv> <c03_exec_coin.csv> <c00_ticks.csv> <c07_5y_regime.csv> <out_dir>

Accounting (same exits as the base replay, only the charged costs differ):
  paper     actual fees + funding + the 2 bp entry and exit slippage the engine charged  (= R_zero - R_base)
  real      taker 5 bp x 2 + per-coin order-book walk at entry (fill_costs, ~$45k) + per-coin real stop slip (SL)
  real_bnb  as real with taker 4.5 bp (BNB fee discount)
  mk_entry  maker entry joining the other side of the spread (2 bp, no walk, one tick saved) + taker stop exit
            with real slip; this is the cost only: c04 shows fills are adversely selected (missed winners)
  maker2    2 bp + 2 bp: both legs resting (not possible for stop-market exits; a lower bound)
Cost R = cost bps / stop bps (stop = |fill - initial stop| / fill).  Gross R = R_base + paper cost R.
Cluster bootstrap CI (run x bar close floored to max(tf, 1h)).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def cboot(x, cl, B=4000, seed=11):
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    x, cl = x[ok], np.asarray(cl)[ok]
    if len(x) < 5:
        return np.nan, np.nan
    u, inv = np.unique(cl, return_inverse=True)
    s, c = np.bincount(inv, weights=x), np.bincount(inv)
    rng = np.random.default_rng(seed)
    d = rng.integers(0, len(u), size=(B, len(u)))
    m = s[d].sum(1) / c[d].sum(1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    rows_csv, exec_csv, ticks_csv, y5_csv, out = sys.argv[1:6]
    R = pd.read_csv(rows_csv)
    B = R[(R["scenario"] == "base") & (R["status"] == "TRADED") & R["grp"].isin(["core36", "ds200", "coinflip"])].copy()
    EC = pd.read_csv(exec_csv).set_index("symbol")
    B["notional"] = B["qty"] * B["entry_price"]
    B["stop_bps"] = B["stop_frac_own"] * 1e4
    stop_exit = B["exit_reason"].isin(["SL", "LOCK", "OPEN"])
    slip_usd = 0.0002 * B["qty"] * (B["entry_price"] / 1.0002) + np.where(stop_exit, 0.0002 * B["qty"] * B["exit_price"], 0)
    risk = B["qty"] * (B["entry_price"] - B["stop_initial"]).abs()
    B["cost_paper_R"] = (B["fees"] + B["funding"] + slip_usd) / risk
    B["gross_R"] = B["R_own"] + B["cost_paper_R"]
    B["fund_R"] = B["funding"] / risk
    e_slip = B["symbol"].map(EC["entry_slip_bps"])
    x_slip = B["symbol"].map(EC["exit_slip_bps"])
    tick = B["symbol"].map(EC["tick_bps"])
    B["cost_bps_paper"] = B["cost_paper_R"] * B["stop_bps"]
    B["cost_bps_real"] = 10 + e_slip + x_slip
    B["cost_bps_real_bnb"] = 9 + e_slip + x_slip
    B["cost_bps_mk_entry"] = 2 + 5 + x_slip - tick
    B["cost_bps_maker2"] = 4.0
    for k in ("real", "real_bnb", "mk_entry", "maker2"):
        B[f"cost_{k}_R"] = (B[f"cost_bps_{k}"]) / B["stop_bps"] + B["fund_R"]
    B.to_csv(os.path.join(out, "c05_base_accounting.csv"), index=False)

    def table(df, keys):
        rows = []
        for k, g in df.groupby(keys):
            k = k if isinstance(k, tuple) else (k,)
            lo, hi = cboot(g["gross_R"], g["cluster"])
            r = dict(zip(keys, k))
            r.update({"n": len(g), "clusters": g["cluster"].nunique(), "median_stop_pct": g["stop_frac_own"].median() * 100,
                      "net_R_paper": g["R_own"].mean(), "gross_R": g["gross_R"].mean(), "gross_ci_lo": lo, "gross_ci_hi": hi,
                      "cost_R_paper": g["cost_paper_R"].mean(), "cost_R_real": g["cost_real_R"].mean(),
                      "cost_R_real_bnb": g["cost_real_bnb_R"].mean(), "cost_R_mk_entry": g["cost_mk_entry_R"].mean(),
                      "cost_R_maker2": g["cost_maker2_R"].mean(), "cost_bps_real": g["cost_bps_real"].mean(),
                      "funding_R": g["fund_R"].mean()})
            r["ai_edge_needed_paper_if_gross0"] = r["cost_R_paper"]
            r["ai_edge_needed_real_if_gross0"] = r["cost_R_real"]
            r["ai_edge_needed_paper_vs_live_gross"] = r["cost_R_paper"] - r["gross_R"]
            rows.append(r)
        return pd.DataFrame(rows)

    T1 = table(B, ["grp", "timeframe"])
    B2 = B[B["grp"].isin(["core36", "ds200"])].assign(grp="core36+ds200")
    T1 = pd.concat([T1, table(B2, ["grp", "timeframe"])])
    T1.to_csv(os.path.join(out, "c05_breakeven_by_tf.csv"), index=False)
    T2 = table(B2, ["timeframe", "symbol"])
    T2.to_csv(os.path.join(out, "c05_breakeven_by_coin_tf.csv"), index=False)
    bins = [0, 40, 50, 60, 70, 80, 100, 125, 150, 200, 10000]
    B2 = B2.assign(stop_bin=pd.cut(B2["stop_bps"], bins).astype(str))
    T3 = table(B2, ["timeframe", "stop_bin"])
    T3.to_csv(os.path.join(out, "c05_breakeven_by_stopbin.csv"), index=False)

    # grid: required gross R = cost bps / stop bps, for the measured execution menus
    menus = {"paper taker 14bp": 14.0}
    for s in EC.index:
        menus[f"real taker {s[:-4]}"] = float(EC.loc[s, "rt_taker_real_bps"])
    menus["real taker BTC + BNB"] = float(EC.loc["BTCUSDT", "rt_taker_real_bps"]) - 1.0
    menus["maker entry + taker stop (BTC)"] = float(EC.loc["BTCUSDT", "rt_maker_entry_real_bps"])
    menus["maker entry + taker stop (SOL)"] = float(EC.loc["SOLUSDT", "rt_maker_entry_real_bps"])
    menus["maker both legs"] = 4.0
    stops = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.25, 1.5, 2.0, 3.0]
    G = pd.DataFrame({name: [c / (s * 100) for s in stops] for name, c in menus.items()}, index=[f"{s}%" for s in stops])
    G.index.name = "stop_pct"
    G.to_csv(os.path.join(out, "c05_breakeven_grid.csv"))
    pd.DataFrame([{"menu": k, "round_trip_bps": v} for k, v in menus.items()]).to_csv(
        os.path.join(out, "c05_menus.csv"), index=False)

    # AI leverage: cost per round trip as % of equity (paper 14 bp; real BTC/ETH ~10.1 bp)
    rows = []
    for lev in (10, 20, 30, 40, 50):
        for rule, mf in (("margin = leverage % (quality_v1)", lev / 100), ("margin 20% fixed", 0.20)):
            notional_x = lev * mf
            rows.append({"leverage": lev, "margin_rule": rule, "notional_x_equity": notional_x,
                         "cost_pct_equity_paper": 14e-4 * notional_x * 100,
                         "cost_pct_equity_real_btc": float(EC.loc["BTCUSDT", "rt_taker_real_bps"]) * 1e-4 * notional_x * 100,
                         "cost_pct_equity_3_trades_day_paper": 3 * 14e-4 * notional_x * 100,
                         "cost_pct_equity_per_30d_at_3_per_day_paper": 90 * 14e-4 * notional_x * 100})
    AL = pd.DataFrame(rows)
    AL.to_csv(os.path.join(out, "c05_ai_leverage_cost.csv"), index=False)

    pd.set_option("display.width", 250)
    cols = ["grp", "timeframe", "n", "clusters", "median_stop_pct", "net_R_paper", "gross_R", "gross_ci_lo", "gross_ci_hi",
            "cost_R_paper", "cost_R_real", "cost_R_real_bnb", "cost_R_mk_entry", "cost_R_maker2", "cost_bps_real",
            "funding_R", "ai_edge_needed_paper_vs_live_gross"]
    print(T1[cols].round(3).to_string(index=False))
    print(T2[["timeframe", "symbol"] + cols[2:]].round(3).to_string(index=False))
    print(T3[["timeframe", "stop_bin", "n", "net_R_paper", "gross_R", "gross_ci_lo", "gross_ci_hi", "cost_R_paper",
              "cost_R_real"]].round(3).to_string(index=False))
    print(G.round(3).to_string())
    print(AL.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
