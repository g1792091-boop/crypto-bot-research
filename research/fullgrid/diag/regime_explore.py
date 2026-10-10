"""Reference diagnostic (not pre-registered, after the results): do market-state "home" advantages chosen on the
select period persist in the test period? Default numbers (core 36 x 4 timeframes, the live exit and tp3R|4) and the
core picks with >= 100 test trades. States as teams.py (장세, 큰 흐름, 변동성); home states by teams.home_states.

    python research/fullgrid/diag/regime_explore.py WORKROOT [PROCS] [RESULTS_BRANCH_DIR]

Output: WORKROOT/fgwork/ana/regime_explore.json, per (tag, cell, exit) and view: home states and per state
[n, sum of P&L / equity] in the select and the test period.
"""

import csv
import json
import os
import sys

FG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)

import numpy as np  # noqa: E402

import regimes as RG  # noqa: E402
import run as R  # noqa: E402
import teams as TM  # noqa: E402

SP = sys.argv[1]
RES = os.path.join(SP, "fgresults", sys.argv[3] if len(sys.argv) > 3 else "fullgrid-results-20261010-1602")
WORK = os.path.join(SP, "fgwork")
DATA = os.path.join(SP, "fg1m")
R.FRAME_DIR[0] = os.path.join(WORK, "frames")
EXITS = [e[0] for e in R.K.EXITS]
I_TP = EXITS.index("tp3R|4")
_states: dict = {}


def one(T, states_tf, tag, name, tf, e):
    lab = RG.tag(T, states_tf)
    out = {"tag": tag, "name": name, "tf": tf, "exit": EXITS[e], "dims": {}}
    for d, states in TM.DIMS.items():
        st = np.array([s if s is not None else "모름" for s in lab[d]], object)
        per = {}
        for pid, pn in ((R.P_SELECT, "select"), (R.P_TEST, "test")):
            m = (T["pid"] == pid) & np.isfinite(T["x"])
            per[pn] = {s: [int(((st == s) & m).sum()), float(T["x"][(st == s) & m].sum())] for s in states}
        ms = (T["pid"] == R.P_SELECT) & (st != "모름") & np.isfinite(T["x"])
        out["dims"][d] = {"per": per, "home": TM.home_states(T["x"][ms], st[ms], states)}
    return out


def job(item):
    name, tf, specs = item
    Ts = R.cell_trades(DATA, WORK, "core", name, tf, [(c, e) for _t, c, e in specs])
    if tf not in _states:
        _states[tf] = [RG.coin_states(DATA, s, tf) for s in R.SYMBOLS]
    return [one(T, _states[tf], t, name, tf, e) for T, (t, _c, e) in zip(Ts, specs)]


def cells() -> list:
    out: dict = {}
    for tf in ("15m", "30m", "1h", "4h"):
        for n in R.core_names():
            c = R.default_combo("core", n)
            out.setdefault((n, tf), []).extend([("default|ladder", c, 0), ("default|tp3R4", c, I_TP)])
    for r in csv.DictReader(open(os.path.join(RES, "candidates.csv"))):
        if r["kind"] != "core" or not r["test_n"] or int(r["test_n"]) < 100:
            continue
        combo = {k: (tuple(v) if isinstance(v, list) else v) for k, v in json.loads(r["combo"]).items()}
        out.setdefault((r["name"], r["tf"]), []).append((f"pick|{r['rank']}", combo, EXITS.index(r["exit"])))
    return [(n, tf, sp) for (n, tf), sp in out.items()]


if __name__ == "__main__":
    items = cells()
    print(len(items), "cells", flush=True)
    res = []
    for k, outs in enumerate(R.run_pool(job, items, int(sys.argv[2]) if len(sys.argv) > 2 else 3, "regx")):
        res.extend(outs)
        print(k, outs[0]["name"], outs[0]["tf"], flush=True)
    json.dump(res, open(os.path.join(WORK, "ana", "regime_explore.json"), "w"))
    print("done", flush=True)
