"""Reference (after the results): every cell at the default numbers and the live exit with costs x0 (fees, slippage
and the ladder's round-trip cost set to zero; funding kept). Compared with the run's costs it shows how much of each
strategy's result is cost.

    python research/fullgrid/diag/gross_all.py WORKROOT [PROCS] [RESULTS_BRANCH_DIR]

Output: WORKROOT/fgwork/ana/gross_all.json, per cell {period: [n, sum of P&L / equity]} at x0 (DeepSeek money inside;
the Korean report shows only plus / minus for DeepSeek, D11).
"""

import csv
import json
import os
import sys

FG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)

import numpy as np  # noqa: E402

import checks as CK  # noqa: E402
import run as R  # noqa: E402

SP = sys.argv[1]
PROCS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
RES = os.path.join(SP, "fgresults", sys.argv[3] if len(sys.argv) > 3 else "fullgrid-results-20261010-1602")
WORK = os.path.join(SP, "fgwork")
DATA = os.path.join(SP, "fg1m")
R.FRAME_DIR[0] = os.path.join(WORK, "frames")
PERIODS = (("select", 0), ("test", 1), ("extra", 2))
_ex: list = []


def job(item):
    kind, name, tf = item
    if not _ex:
        _ex.append(R.exchange(os.path.join(FG, "exchange.json"), False))
    combo = R.default_combo(kind, name)
    S = CK.cost_vector(0.0)
    xs, ps = [], []
    for sym in R.SYMBOLS:
        lo, sh = R.signals(DATA, kind, name, sym, tf, combo)
        if not (np.asarray(lo, bool).any() or np.asarray(sh, bool).any()):
            continue
        P = CK.cost_table(DATA, _ex[0], kind, name, sym, tf, 0, S)
        idx, _s, x = R.per_trade(P, lo, sh)
        _d, close = R.frame(DATA, sym, tf)
        xs.append(x)
        ps.append(R.period_ids(close)[idx])
    x = np.concatenate(xs) if xs else np.zeros(0)
    pid = np.concatenate(ps) if ps else np.zeros(0, int)
    return {"kind": kind, "name": name, "tf": tf,
            "x0": {pn: [int((pid == k).sum()), float(x[pid == k].sum())] for pn, k in PERIODS}}


if __name__ == "__main__":
    order = {"4h": 0, "1h": 1, "30m": 2, "15m": 3}
    its = sorted([(c["kind"], c["name"], c["tf"]) for c in csv.DictReader(open(os.path.join(RES, "cells.csv")))],
                 key=lambda it: order[it[2]])
    part = os.path.join(WORK, "ana", "gross_all.part.json")
    res = json.load(open(part)) if os.path.exists(part) else []
    done = {(r["kind"], r["name"], r["tf"]) for r in res}
    its = [it for it in its if it not in done]
    for k, rec in enumerate(R.run_pool(job, its, PROCS, "gross0")):
        res.append(rec)
        print(k, rec["kind"], rec["name"], rec["tf"], flush=True)
        json.dump(res, open(part, "w"))
    json.dump(res, open(os.path.join(WORK, "ana", "gross_all.json"), "w"))
    print("done", flush=True)
