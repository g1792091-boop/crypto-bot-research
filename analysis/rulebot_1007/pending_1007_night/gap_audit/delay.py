"""Delay analysis for the AI-trader attach plan (gap audit, 10/8).

    python3 -I delay.py <export_root> <rb_analyze_dir> <repo> <out_dir>

For every SUBMITTED house-exit signal (15m/30m/1h/4h) of v3b and v4:
- rule twin at signal time  = the signal alone through the repo engine at its logged ref_price (what the rule
  account got: bookTicker ask/bid read right after the compute, ref_time = boundary + delay_ms);
- AI twin at answer time    = the same signal (same 2 ATR stop distance, same leverage rule) entered at the OPEN of
  the 1m bar after the minute that holds the answer time t_ans = ref_time + L (design v2 5-3 rule 7), L = AI latency.
delay cost = R(AI twin) - R(rule twin). Price gap = side x (open(t_fill) - ref) / stop_dist (R units).
Cluster SE by bar_close (signals at one boundary share the price path).
"""
import bisect
import json
import os
import sys

import site
sys.path.append(site.getusersitepackages())
import numpy as np
import pandas as pd

root, rbdir, repo, out = sys.argv[1:5]
sys.path.insert(0, repo)
sys.path.insert(0, rbdir)
sys.dont_write_bytecode = True
import analyze as A  # noqa: E402

MIN = 60_000
LAT = (5, 10, 20, 40)          # AI latency after ref_time, seconds (20 = the deadline; 40 = a late answer)
RUNS = {"run-20261005T183457Z": "v3b", "current": "v4"}
TFS = ("15m", "30m", "1h", "4h")


def cl_se(x, g):
    x = np.asarray(x, float)
    g = np.asarray(g)
    ok = ~np.isnan(x)
    x, g = x[ok], g[ok]
    n = len(x)
    if n < 3:
        return np.nan, n, 0
    m = x.mean()
    s = pd.Series(x - m).groupby(g).sum().to_numpy()
    k = len(s)
    if k < 2:
        return np.nan, n, k
    return float(np.sqrt((s ** 2).sum() * k / (k - 1)) / n), n, k


def Rof(o):
    if o.get("status") == "TRADED":
        return o.get("R", np.nan)
    if o.get("status") == "UNRESOLVED":
        return o.get("mark_R", np.nan)
    return np.nan


rows_all, delay_rows, fill_rows, lag_rows = [], [], [], []
for name, tag in RUNS.items():
    run = A.Run(root, name)
    rule, taker = A.detect_rule(run), A.implied_taker(run)
    brackets, _ = A.make_brackets(None)
    specs = A.infer_specs(run.trades)
    S = A.replay_settings(rule, taker)
    # 1) delay of every SUBMITTED row, by timeframe and group
    sig = run.sig.copy()
    acc = run.accounts.set_index("account_id")
    sig["aid"] = sig["strategy"] + "@" + sig["timeframe"]
    sig["group"] = sig["aid"].map(acc["group"]).fillna("other")
    sub = sig[sig["status"] == "SUBMITTED"]
    for (tf, grp), g in sub.groupby(["timeframe", "group"]):
        d = g["delay_ms"].astype(float) / 1000
        delay_rows.append({"run": tag, "tf": tf, "group": grp, "n": len(d), "mean_s": d.mean(), "median_s": d.median(),
                           "p90_s": d.quantile(0.9), "p95_s": d.quantile(0.95), "max_s": d.max()})
    d = sub["delay_ms"].astype(float) / 1000
    # per boundary (what a dashboard average over signals vs over boundaries means)
    pb = sub.groupby("bar_close")["delay_ms"].first().astype(float) / 1000
    delay_rows.append({"run": tag, "tf": "ALL", "group": "ALL", "n": len(d), "mean_s": d.mean(), "median_s": d.median(),
                       "p90_s": d.quantile(0.9), "p95_s": d.quantile(0.95), "max_s": d.max(),
                       "boundaries": len(pb), "mean_s_per_boundary": pb.mean()})
    # 2) feed lag: when a closed 1m bar was processed (live_bars.processed_at - close_time)
    if run.bars is not None and "processed_at" in run.bars:
        lag = (run.bars["processed_at"] - run.bars["close_time"]).astype(float) / 1000
        lag = lag[(lag > 0) & (lag < 120)]
        lag_rows.append({"run": tag, "n": len(lag), "mean_s": lag.mean(), "median_s": lag.median(),
                         "p90_s": lag.quantile(0.9)})
    # 3) the rule account's fill = ref_price x (1 +- slippage)?
    o = run.out[run.out["status"] == "ENTERED"].copy()
    fill = o["detail"].map(lambda s: A.jload(s).get("fill"))
    exp = o["ref_price"] * (1 + o["sig_side"] * S.slippage_frac)
    ok = (fill.astype(float) / exp - 1).abs() < 1e-9
    has_ref = o["ref_price"].notna()
    fill_rows.append({"run": tag, "entered": len(o), "with_ref_price": int(has_ref.sum()),
                      "fill_eq_ref_x_slip": int(ok.sum()),
                      "entry_time_eq_bar_close": int((o["step_ts"] == o["sig_ts"] + 1).sum())})
    # 4) twins
    rates, _ = A.infer_funding(run.trades, run.bars)
    ts_list, ssteps = A.build_steps(run.bars, rates)
    strength = A.load_ctx_strength(run.ctx_path)
    A._G.clear()
    A._G.update(ssteps=ssteps, ts_list=ts_list, settings=S, brackets=brackets, specs=specs)
    opens = {(int(r.ts), r.symbol): float(r.open) for r in run.bars[["ts", "symbol", "open"]].itertuples(index=False)}
    hs = sub[sub["timeframe"].isin(TFS) & (sub["aid"].map(acc["exits"]).fillna("house") == "house")]
    for r in hs.itertuples(index=False):
        if not (r.atr == r.atr and r.atr > 0 and r.ref_price == r.ref_price and r.ref_time == r.ref_time):
            continue
        d = {"bar_close": int(r.bar_close), "timeframe": r.timeframe, "strategy": r.strategy, "symbol": r.symbol,
             "side": int(r.side), "atr": float(r.atr), "ref_price": float(r.ref_price), "ref_time": int(r.ref_time),
             "delay_ms": int(r.delay_ms)}
        ctx = strength.get(int(r.id))
        d["data"] = {"ctx": ctx} if ctx else {}
        base = A._sim(d)
        rec = {"run": tag, "group": r.group, "tf": r.timeframe, "strategy": r.strategy, "symbol": r.symbol,
               "side": int(r.side), "bar_close": int(r.bar_close), "delay_s": r.delay_ms / 1000,
               "stop_dist": 2 * float(r.atr), "ref": float(r.ref_price), "st0": base.get("status"), "R0": Rof(base),
               "lev0": base.get("leverage")}
        for L in LAT:
            t_ans = int(r.ref_time) + L * 1000
            t_fill = (t_ans // MIN + 1) * MIN
            px = opens.get((t_fill, r.symbol))
            rec[f"wait{L}_s"] = (t_fill - int(r.bar_close)) / 1000
            if px is None:
                rec[f"st{L}"] = "NO_BAR"
                continue
            d2 = dict(d, bar_close=t_fill, ref_price=px)
            tw = A._sim(d2)
            rec[f"st{L}"] = tw.get("status")
            rec[f"R{L}"] = Rof(tw)
            rec[f"gap{L}"] = int(r.side) * (px - float(r.ref_price)) / (2 * float(r.atr))
            rec[f"gapbp{L}"] = int(r.side) * (px / float(r.ref_price) - 1) * 1e4
        rows_all.append(rec)

T = pd.DataFrame(rows_all)
T.to_csv(os.path.join(out, "delay_twins.csv.gz"), index=False, compression="gzip")
summ = []
for (tag, tf), g in list(T.groupby(["run", "tf"])) + [(("ALL", t), T[T.tf == t]) for t in TFS]:
    row = {"run": tag, "tf": tf, "n_signals": len(g), "delay_mean_s": g["delay_s"].mean(),
           "delay_median_s": g["delay_s"].median(), "stop_bp_median": (g["stop_dist"] / g["ref"] * 1e4).median()}
    for L in LAT:
        both = g[g["st0"].isin(["TRADED", "UNRESOLVED"]) & g[f"st{L}"].isin(["TRADED", "UNRESOLVED"])]
        dR = both[f"R{L}"] - both["R0"]
        se, n, k = cl_se(dR, both["bar_close"])
        gse, _, _ = cl_se(g[f"gap{L}"], g["bar_close"])
        row.update({f"L{L}_fill_after_close_s_median": g[f"wait{L}_s"].median(),
                    f"L{L}_share_fill_120s_or_later": float((g[f"wait{L}_s"] >= 120).mean()),
                    f"L{L}_gapR_mean": g[f"gap{L}"].mean(), f"L{L}_gapR_se": gse,
                    f"L{L}_absgapR_mean": g[f"gap{L}"].abs().mean(), f"L{L}_absgapbp_median": g[f"gapbp{L}"].abs().median(),
                    f"L{L}_dR_n": n, f"L{L}_dR_clusters": k, f"L{L}_dR_mean": dR.mean(), f"L{L}_dR_se": se,
                    f"L{L}_dR_sd": dR.std(), f"L{L}_absdR_mean": dR.abs().mean(),
                    f"L{L}_status_changed": int((g["st0"] != g[f"st{L}"]).sum())})
    summ.append(row)
SM = pd.DataFrame(summ)
SM.to_csv(os.path.join(out, "delay_summary.csv"), index=False)
res = {"delay_by_tf_group": pd.DataFrame(delay_rows).round(2).to_dict("records"),
       "feed_lag_1m": pd.DataFrame(lag_rows).round(2).to_dict("records"),
       "rule_fill_check": fill_rows,
       "twins": SM.round(4).to_dict("records")}
with open(os.path.join(out, "delay_results.json"), "w") as fh:
    json.dump(res, fh, indent=1, default=float)
print(json.dumps({"fill": fill_rows, "lag": res["feed_lag_1m"]}, default=float))
print(pd.DataFrame(delay_rows).round(1).to_string())
cols = ["run", "tf", "n_signals", "delay_mean_s"] + [c for c in SM.columns if c.startswith(("L10_", "L20_"))]
print(SM[cols].round(3).T.to_string())
