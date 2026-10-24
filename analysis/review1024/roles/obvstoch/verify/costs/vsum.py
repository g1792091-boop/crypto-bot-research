"""Summaries of vcost_<which>.csv.gz: per exit x cost variant x period, the family contrast (with - against), share of
cells > 0, family mean, coin-flip, trend-only, signal - trend-only; per signal and one position at a time."""
import sys, json, os
import pandas as pd, numpy as np
which = sys.argv[1]
C = pd.read_csv(f"vcost_{which}.csv.gz")
A = pd.read_csv(sys.argv[2])  # study all_cells.csv.gz
# check x1 against the study
S = A.set_index(["period", "tf", "htf", "trend", "timing", "exit"])
x1 = C[C["var"] == "x1"].set_index(["period", "tf", "htf", "trend", "timing", "exit"])
j = x1.join(S[["mean_roe", "mean_against", "mean_opp", "trend_only", "n", "n_against"]].add_prefix("S_"), how="inner")
print("rows matched", len(j), "max |with-study|", float((j.with_ - j.S_mean_roe).abs().max()),
      "max |against-study|", float((j.against - j.S_mean_against).abs().max()),
      "max |coin-study|", float((j.coin - j.S_mean_opp).abs().max()),
      "max |trendonly-study|", float((j.trend_only - j.S_trend_only).abs().max()),
      "n eq", bool((j.n_with == j.S_n).all() and (j.n_against == j.S_n_against).all()))
C["d"] = C.with_ - C.against
C["op_d"] = C.op_with - C.op_against
C["opc_d"] = C.opc_with - C.opc_against
C["sig_m_to"] = C.with_ - C.trend_only
C["op_sig_m_to"] = C.op_with - C.op_trend_only
C["opc_sig_m_to"] = C.opc_with - C.opc_trend_only
out = {}
grp = ["exit", "var", "period"] if which == "famA" else ["trend", "exit", "var", "period"]
g = C.groupby(grp)
T = pd.DataFrame({
    "cells": g.size(),
    "with": g.with_.mean() * 100, "against": g.against.mean() * 100, "d": g.d.mean() * 100,
    "d_pos": g.d.apply(lambda x: (x > 0).mean()), "coin": g.coin.mean() * 100, "trend_only": g.trend_only.mean() * 100,
    "sig-to": g.sig_m_to.mean() * 100,
    "OP_with": g.op_with.mean() * 100, "OP_against": g.op_against.mean() * 100, "OP_d": g.op_d.mean() * 100,
    "OP_d_pos": g.op_d.apply(lambda x: (x > 0).mean()), "OP_coin": g.op_coin.mean() * 100,
    "OP_to": g.op_trend_only.mean() * 100, "OP_sig-to": g.op_sig_m_to.mean() * 100,
    "OP_n_with_med": g.op_n_with.median(), "OP_with_perday": g.op_with_per_day.mean(),
    "OPc_d": g.opc_d.mean() * 100, "OPc_d_pos": g.opc_d.apply(lambda x: (x > 0).mean()),
    "OPc_sig-to": g.opc_sig_m_to.mean() * 100})
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 400)
print(T.round(3).to_string())
T.round(5).to_csv(f"vsum_{which}.csv")
# both exits pooled (w35 + a2), per cost variant
if which == "famA":
    for v in ("x1", "xw", "x2", "x0"):
        q = C[C["var"] == v]
        gg = q.groupby("period")
        print(v, pd.DataFrame({"d": gg.d.mean() * 100, "d_pos": gg.d.apply(lambda x: (x > 0).mean()),
              "with": gg.with_.mean() * 100, "trend_only": gg.trend_only.mean() * 100, "sig-to": gg.sig_m_to.mean() * 100,
              "OP_d": gg.op_d.mean() * 100, "OP_d_pos": gg.op_d.apply(lambda x: (x > 0).mean()),
              "OP_sig-to": gg.op_sig_m_to.mean() * 100, "OPc_d": gg.opc_d.mean() * 100,
              "OPc_sig-to": gg.opc_sig_m_to.mean() * 100}).round(3).to_string(), sep="\n")
