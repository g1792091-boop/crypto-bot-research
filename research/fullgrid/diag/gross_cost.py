"""Reference diagnostic (not pre-registered, after the results): default numbers, the live exit and tp3R|4, costs x0
vs x1, per core cell.

    python research/fullgrid/diag/gross_cost.py WORKROOT 4h,1h

WORKROOT holds fg1m/ (the run's 1m data), fgwork/frames/ and fgwork/ (outcome tables). Output:
WORKROOT/fgwork/gross_<tfs>.json, per cell and exit/cost: {period: [n, sum of P&L / equity]}.
"""

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
TFS = sys.argv[2].split(",")
R.FRAME_DIR[0] = os.path.join(SP, "fgwork", "frames")
EX = R.exchange(os.path.join(FG, "exchange.json"), False)
DATA = os.path.join(SP, "fg1m")
EXITS = {"ladder|2": 0, "tp3R|4": [e[0] for e in R.K.EXITS].index("tp3R|4")}
PERIODS = (("select", 0), ("test", 1), ("extra", 2))


def job(args):
    name, tf = args
    combo = R.default_combo("core", name)
    out = {}
    for ename, e in EXITS.items():
        for mult in (0.0, 1.0):
            S = CK.cost_vector(mult)
            xs, ps = [], []
            for sym in R.SYMBOLS:
                P = CK.cost_table(DATA, EX, "core", name, sym, tf, e, S)
                lo, sh = R.signals(DATA, "core", name, sym, tf, combo)
                idx, _s, x = R.per_trade(P, lo, sh)
                _d, close = R.frame(DATA, sym, tf)
                xs.append(x)
                ps.append(R.period_ids(close)[idx])
            x, pid = np.concatenate(xs), np.concatenate(ps)
            out[f"{ename}|x{mult:g}"] = {p: [int((pid == k).sum()), float(x[pid == k].sum())] for p, k in PERIODS}
    return name, tf, out


if __name__ == "__main__":
    res = []
    for name, tf, out in R.run_pool(job, [(n, tf) for tf in TFS for n in R.core_names()], 3, "gross"):
        res.append({"name": name, "tf": tf, **out})
        print(name, tf, flush=True)
    json.dump(res, open(os.path.join(SP, "fgwork", f"gross_{'_'.join(TFS)}.json"), "w"))
    print("done", flush=True)
