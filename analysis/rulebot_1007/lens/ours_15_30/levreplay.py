#!/usr/bin/env python3
"""Replay our 36 strategies' 15m/30m SUBMITTED signals (v3b + v4, live_bars) alone at FIXED leverage with the house
2 ATR stop and the ROE-based ladder: lev10 (10x, 20% margin) and lev20m20 / lev30m30 / lev40m40 / lev50m50 (margin =
leverage %, the usual sizing checks, no fallback) = paperbot.obsshadows.variant_settings. Shows (1) how often each
leverage can be sized at all at 15m / 30m and (2) how R per signal changes with leverage under the ROE ladder.

usage: python3 -I -B levreplay.py <export_dir> <repo> <out_dir> [procs]
"""
import copy
import os
import site
import sys

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
HERE = os.path.dirname(os.path.abspath(__file__))
EXP, REPO, OUT = sys.argv[1:4]
PROCS = int(sys.argv[4]) if len(sys.argv) > 4 else 4
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rb_lib as L  # noqa: E402
from paperbot.obsshadows import variant_settings  # noqa: E402

VARS = ["live_rule", "lev10", "lev20m20", "lev30m30", "lev40m40", "lev50m50"]
brackets, _ = L.make_brackets(None)
parts = []
for name in ("run-20261005T183457Z", "current"):
    run = L.Run(EXP, name)
    taker = L.implied_taker(run)
    base = L.replay_settings("quality_v1", taker)
    specs = L.infer_specs(run.trades)
    r2 = copy.copy(run)
    acc = run.accounts.set_index("account_id")
    s = run.sig
    aid = s["strategy"] + "@" + s["timeframe"]
    keep = s["timeframe"].isin(["15m", "30m"]) & aid.map(acc["kind"]).eq("strategy")
    r2.sig = s[keep].copy()
    for v in VARS:
        S = base if v == "live_rule" else variant_settings(base, v)
        R, info = L.replay_run(r2, S, brackets, specs, PROCS, funding=True, flip=False)
        R["variant"] = v
        parts.append(R)
        print(name, v, info.get("signals"), R["status"].value_counts().to_dict(), flush=True)
X = pd.concat(parts, ignore_index=True)
X.to_csv(os.path.join(OUT, "levreplay_rows.csv"), index=False)

# summary per tf x variant: sized share, mean R of TRADED, mark-inclusive mean, paired vs live_rule on common signals
rows = []
key = ["run", "sig_id"]
live = X[X["variant"] == "live_rule"].set_index(key)
for (tf, v), g in X.groupby(["timeframe", "variant"]):
    tr = g[g["status"] == "TRADED"]
    un = g[g["status"] == "UNRESOLVED"]
    sized = g["status"].isin(["TRADED", "UNRESOLVED"])
    allR = pd.concat([tr["R"], un["mark_R"]]).dropna()
    gi = g.set_index(key)
    both = gi[(gi["status"] == "TRADED")].join(live[live["status"] == "TRADED"][["R"]], rsuffix="_live", how="inner")
    rows.append({"timeframe": tf, "variant": v, "signals": len(g), "sized_share": sized.mean(),
                 "rejected_sizing": int((g["status"] == "REJECTED_SIZING").sum()), "traded": len(tr),
                 "unresolved": len(un), "mean_R_traded": tr["R"].mean(), "win_pct": 100 * (tr["R"] > 0).mean(),
                 "mean_R_incl_unres_mark": allR.mean(), "mean_roe_traded": tr["roe"].mean(),
                 "paired_n_vs_live": len(both), "paired_diff_R_vs_live": (both["R"] - both["R_live"]).mean(),
                 "exit_mix": L.mix(tr["exit_reason"])})
Sm = pd.DataFrame(rows)
Sm.to_csv(os.path.join(OUT, "levreplay_summary.csv"), index=False)
print(Sm.round(3).to_string())
