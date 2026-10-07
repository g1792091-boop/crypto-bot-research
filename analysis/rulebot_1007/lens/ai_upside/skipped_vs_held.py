#!/usr/bin/env python3
"""Signals an account SKIPPED because it was in position: the skipped signal alone vs the rest of the held trade.

    python3 -I skipped_vs_held.py <export_dir> <out_dir>

v3b / v4 (live_bars): skipped signal = its replay alone (rules_signals.csv base, fresh $5,000); held trade = the
account's real trade open at that step. switch_gain (equity fraction) = new_pnl/5000 - (held_final_pnl -
held_pnl_if_closed_at_step_open)/held_equity_before. Closing the held trade costs taker + slippage (in the formula).
v3a (no live_bars): only the nightly 'skipped' shadow ROE vs the same account's entered trades' ROE.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True
import site  # noqa: E402
sys.path.append(site.getusersitepackages())
import json  # noqa: E402
import os  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MIN = 60_000
RUNS = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
TAKER, SLIP = 0.0005, 0.0002


def kind_of(aid):
    s = aid.split("@")[0]
    if s.startswith("RANDOM_"):
        return "random"
    if s.startswith("REEL"):
        return "reel"
    if s[:1] == "F" and "_" in s and s.split("_")[0][1:].isdigit():
        return "ds200"
    return "strategy"


def cl_stats(d, cl, rng, B=5000):
    u, inv = np.unique(cl, return_inverse=True)
    sums = np.bincount(inv, weights=d)
    cnt = np.bincount(inv)
    k = len(u)
    if k < 3:
        return {"clusters": k}
    idx = rng.integers(0, k, size=(B, k))
    bs = sums[idx].sum(1) / cnt[idx].sum(1)
    null = rng.choice([-1.0, 1.0], size=(B, k)) @ sums / len(d)
    return {"clusters": k, "ci_lo": np.percentile(bs, 2.5), "ci_hi": np.percentile(bs, 97.5),
            "p_two": (np.sum(np.abs(null) >= abs(d.mean()) - 1e-15) + 1) / (B + 1)}


def main():
    exp, out = sys.argv[1:3]
    rng = np.random.default_rng(5)
    RS = pd.read_csv(os.path.join(out, "rules_signals.csv"))
    rows, detail = [], []
    for run, rs in RUNS.items():
        p = os.path.join(exp, run)
        o = pd.read_csv(os.path.join(p, "outcomes.csv"))
        t = pd.read_csv(os.path.join(p, "trades.csv"))
        sk = o[(o["status"] == "SKIPPED") & (o["reason"] == "in position")].copy()
        sk["kind"] = sk["account_id"].map(kind_of)
        sk = sk[sk["kind"].isin(["strategy", "ds200", "random"]) & ~sk["account_id"].str.endswith("@5m")]
        t["kind"] = t["account_id"].map(kind_of)
        if rs == "v3a":
            sh = pd.read_csv(os.path.join(p, "d3_shadows.csv"))
            sh = sh[sh["kind"] == "skipped"].drop_duplicates("key")
            parts = sh["key"].str.split("|", expand=True)
            sh["bc"] = pd.to_numeric(parts[3])
            sk["bc"] = sk["sig_ts"] + 1
            m = sk.merge(sh[["account_id", "symbol", "bc", "roe", "resolved"]], on=["account_id", "symbol", "bc"],
                         how="left")
            m["tf"] = m["account_id"].str.split("@").str[-1]
            for (kind, tf), g in m.groupby(["kind", "tf"]):
                ent = t[(t["kind"] == kind) & (t["timeframe"] == tf)]
                gg = g[g["roe"].notna()]
                rows.append({"run": rs, "kind": kind, "tf": tf, "n_skipped_in_pos": len(g), "n_with_shadow": len(gg),
                             "mean_roe_skipped_alone": gg["roe"].mean(), "mean_roe_entered": ent["roe"].mean(),
                             "n_entered": len(ent)})
            continue
        bars = pd.read_csv(os.path.join(p, "live_bars.csv"), usecols=["ts", "symbol", "open"])
        px = {(int(a), b): c for a, b, c in zip(bars["ts"], bars["symbol"], bars["open"])}
        rr = RS[RS["run"] == run][["account_id", "symbol", "bar_close", "base_status", "base_R", "base_pnl"]]
        sk["bar_close"] = sk["sig_ts"] + 1
        m = sk.merge(rr, on=["account_id", "symbol", "bar_close"], how="left")
        t = t.sort_values("entry_time")
        tg = {a: g for a, g in t.groupby("account_id")}
        for r in m.itertuples(index=False):
            g = tg.get(r.account_id)
            if g is None:
                continue
            h = g[(g["entry_time"] <= r.step_ts) & (g["exit_time"] >= r.step_ts)]
            if not len(h) or not (r.base_status in ("TRADED", "UNRESOLVED")):
                continue
            h = h.iloc[0]
            o_px = px.get((int(r.step_ts), h["symbol"]))
            if o_px is None:
                continue
            side, qty, entry = int(h["side"]), float(h["qty"]), float(h["entry_price"])
            exit_px = o_px * (1 - side * SLIP)
            entry_fee = qty * entry * TAKER
            pnl_close_now = side * qty * (exit_px - entry) - entry_fee - qty * exit_px * TAKER
            eq0 = float(h["equity_after"]) - float(h["pnl"])
            dist = abs(entry - float(h["stop_initial"])) if h["stop_initial"] == h["stop_initial"] else np.nan
            held_rest = (float(h["pnl"]) - pnl_close_now) / eq0
            new = float(r.base_pnl) / 5000.0
            same_sym_opp = (h["symbol"] == r.symbol) and (int(r.sig_side) == -side)
            detail.append({"run": rs, "account_id": r.account_id, "kind": r.kind,
                           "tf": r.account_id.split("@")[-1], "step_ts": r.step_ts, "symbol": r.symbol,
                           "held_symbol": h["symbol"], "same_symbol_opposite": same_sym_opp,
                           "same_symbol_same_side": (h["symbol"] == r.symbol) and (int(r.sig_side) == side),
                           "held_unrealized_R_at_skip": side * (o_px - entry) / dist if dist else np.nan,
                           "held_final_R": float(h["pnl"]) / (qty * dist) if dist else np.nan,
                           "new_R": r.base_R, "new_eq": new, "held_rest_eq": held_rest,
                           "switch_gain_eq": new - held_rest})
    D = pd.DataFrame(detail)
    D["cl"] = D["run"] + "|" + (D["step_ts"] // (60 * MIN)).astype(str)
    D.to_csv(os.path.join(out, "skipped_vs_held_detail.csv"), index=False)
    srows = []
    for run_s in ["v3b", "v4", "ALL"]:
        Dr = D if run_s == "ALL" else D[D["run"] == run_s]
        for kind in ["strategy", "ds200", "random"]:
            for tf in ["15m", "30m", "1h", "4h", "ALL"]:
                for sub in ["all", "same_symbol_opposite", "same_symbol_same_side", "held_under_water"]:
                    g = Dr[(Dr["kind"] == kind) & ((Dr["tf"] == tf) if tf != "ALL" else True)]
                    if sub == "same_symbol_opposite":
                        g = g[g["same_symbol_opposite"]]
                    elif sub == "same_symbol_same_side":
                        g = g[g["same_symbol_same_side"]]
                    elif sub == "held_under_water":
                        g = g[g["held_unrealized_R_at_skip"] < 0]
                    if len(g) < 5:
                        continue
                    d = g["switch_gain_eq"].to_numpy(float)
                    srows.append({"run": run_s, "kind": kind, "tf": tf, "subset": sub, "n": len(g),
                                  "mean_new_R": g["new_R"].mean(), "mean_new_eq_pct": 100 * g["new_eq"].mean(),
                                  "mean_held_rest_eq_pct": 100 * g["held_rest_eq"].mean(),
                                  "mean_switch_gain_eq_pct": 100 * d.mean(),
                                  "share_switch_better": float(np.mean(d > 0)),
                                  **{k: (100 * v if k in ("ci_lo", "ci_hi") else v)
                                     for k, v in cl_stats(d, g["cl"].to_numpy(), rng).items()}})
    S = pd.DataFrame(srows)
    S = pd.concat([S, pd.DataFrame(rows)], ignore_index=True)
    S.to_csv(os.path.join(out, "skipped_vs_held.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(S[(S["kind"] != "random")].round(3).to_string())


if __name__ == "__main__":
    main()
