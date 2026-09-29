"""Aggregate trade files into pooled (strategy x exit) statistics and apply the
pre-registered selection rule."""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

from engine import leverage_layer, summarize

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "results")

RULE = dict(min_trades=100, min_pf=1.2, min_pos_symbols=3)


def pooled(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (strat, ex), g in trades.groupby(["strategy", "exit"]):
        g = g.sort_values("entry_ts")
        s = summarize(g)
        s.update(strategy=strat, exit=ex)
        per_sym = g.groupby("symbol")["net"].sum()
        s["symbols_pos"] = int((per_sym > 0).sum())
        s["symbols"] = int(len(per_sym))
        s["worst_symbol_pct"] = float(per_sym.min() * 100)
        s["best_symbol_pct"] = float(per_sym.max() * 100)
        # monthly consistency (pooled net by entry month)
        m = g.groupby(pd.to_datetime(g["entry_ts"], utc=True).dt.strftime("%Y-%m"))["net"].sum()
        s["months"] = int(len(m))
        s["months_pos"] = int((m > 0).sum())
        rows.append(s)
    return pd.DataFrame(rows)


def apply_rule(p: pd.DataFrame) -> pd.DataFrame:
    ok = (p["trades"] >= RULE["min_trades"]) & (p["pf"] >= RULE["min_pf"]) & (p["exp_net_pct"] > 0) \
         & (p["symbols_pos"] >= RULE["min_pos_symbols"])
    p = p.copy()
    p["pass"] = ok
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="IS")
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    tag = f"_{args.tag}" if args.tag else ""
    t = pd.read_csv(os.path.join(OUT, f"trades_{args.window}_{args.tf}{tag}.csv"))
    p = apply_rule(pooled(t))
    p = p.sort_values(["pass", "pf"], ascending=[False, False])
    p.to_csv(os.path.join(OUT, f"pooled_{args.window}_{args.tf}{tag}.csv"), index=False)
    cols = ["strategy", "exit", "trades", "wr", "pf", "exp_net_pct", "exp_gross_pct", "payoff", "avg_hold",
            "symbols_pos", "months_pos", "months", "eq_L10", "mdd_L10", "eq_L50", "mdd_L50", "liq_L50", "pass"]
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print(p[cols].round(3).to_string(index=False))
    print("\nPASS count:", int(p["pass"].sum()), "of", len(p))
    # best exit per strategy
    best = p.sort_values("pf", ascending=False).groupby("strategy").head(1).sort_values("pf", ascending=False)
    print("\nBest exit per strategy:")
    print(best[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
