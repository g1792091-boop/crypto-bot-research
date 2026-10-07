#!/usr/bin/env python3
"""Strategy x timeframe notes (JSON) from headroom_rank.csv for the report.
    python3 -I gen_notes.py <out_dir>"""
import sys
sys.dont_write_bytecode = True
import site
sys.path.append(site.getusersitepackages())
import json
import os
import numpy as np
import pandas as pd
out = sys.argv[1]
D = pd.read_csv(os.path.join(out, "headroom_rank.csv"))
f = lambda x, d=2: ("na" if x != x else f"{x:+.{d}f}")  # noqa: E731
notes = []
for r in D.itertuples(index=False):
    if r.tf not in ("15m", "30m", "1h", "4h"):
        continue
    sig_n = 0 if r.sig_n != r.sig_n else int(r.sig_n)
    tr_n = 0 if r.tr_n != r.tr_n else int(r.tr_n)
    if r.tf in ("1h", "4h") and r.grade == "N":
        continue
    if r.tf in ("15m", "30m") and r.grade == "N" and sig_n < 8 and tr_n < 8:
        continue
    base_both_pos = (r.kind == "strategy" and r.sig_n_v3b == r.sig_n_v3b and r.sig_n_v3b >= 5 and r.sig_n_v4 >= 5
                     and r.sig_mean_R_v3b >= 0 and r.sig_mean_R_v4 >= 0)
    pc = lambda x: "na" if x != x else f"{100*x:.0f}%"  # noqa: E731
    nv = lambda x: 0 if x != x else int(x)  # noqa: E731
    nums = (f"sig n{sig_n} (v3b {nv(r.sig_n_v3b)}/v4 {nv(r.sig_n_v4)}) R {f(r.sig_mean_R)} (v3b {f(r.sig_mean_R_v3b)}, v4 {f(r.sig_mean_R_v4)}); "
            f"trades n{tr_n} R {f(r.tr_mean_R)}; UB {f(r.exit_headroom_ub)}; +0.5R->SL {pc(r.sig_gb05_SL)}; dead {pc(r.sig_dead_share_losers)}; "
            f"CUT05 {f(r.d_CUT05)} NP4 {f(r.d_NP4)} BE05 {f(r.d_BE05)} TP1 {f(r.d_TP1)}; flip {f(r.sideflip_excess_R)}")
    g = r.grade
    if r.base_hopeless:
        note = "Losing entries, no side-flip edge: exits could only trim losses; not an AI candidate on this evidence."
    elif g.startswith("H1"):
        note = (f"Exit rules gained in every run it has ({r.consistent_exit_rules}); per-cell gains do not replicate in general and "
                "track bad entries: shadow-test as code, not a reason for an AI.")
    elif g == "H2":
        note = "Exit room on paper only; no pre-declared rule captured it in both runs."
    elif g == "L":
        note = "Little exit room; any AI value would have to come from entries/skips."
    else:
        note = "Too few signals to grade."
    if base_both_pos:
        note += " Base R >= 0 in both v3b and v4 (rare; small n)."
    if r.kind == "ds200":
        note += " v4 only (no OOS run)."
    notes.append({"strategy": f"{r.strategy} ({r.kind})", "timeframe": r.tf,
                  "grade": g + (" / hopeless base" if r.base_hopeless else ""), "numbers": nums, "note": note})
json.dump(notes, open(os.path.join(out, "strategy_notes.json"), "w"), indent=1)
print(len(notes))
print(pd.Series([n["grade"] for n in notes]).value_counts())
