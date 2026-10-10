"""Reference report, second pass (after the results): per strategy x timeframe, at the default numbers (live exit)
and at the cell's rank-1 pick: calendar years 2020-2026, the account's worst stretch per period (live size: longest
losing run, worst month, longest time under water, liquidations) and the account at 1/4 size, and the chosen side vs
the opposite side at the same entries per period.

    python research/fullgrid/diag/strat_deep.py WORKROOT [PROCS] [RESULTS_BRANCH_DIR]

Output: WORKROOT/fgwork/ana/strat_deep.json (DeepSeek money figures inside; the Korean report hides them, D11).
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
import sizing as SZ  # noqa: E402

SP = sys.argv[1]
PROCS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
RES = os.path.join(SP, "fgresults", sys.argv[3] if len(sys.argv) > 3 else "fullgrid-results-20261010-1602")
WORK = os.path.join(SP, "fgwork")
DATA = os.path.join(SP, "fg1m")
R.FRAME_DIR[0] = os.path.join(WORK, "frames")
EXITS = [e[0] for e in R.K.EXITS]
PERIODS = (("select", R.P_SELECT), ("test", R.P_TEST), ("extra", R.P_EXTRA))
YEARS = range(2020, 2027)
_ex: list = []


def ex() -> dict:
    if not _ex:
        _ex.append(R.exchange(os.path.join(FG, "exchange.json"), False))
    return _ex[0]


def years(T: dict) -> dict:
    y = np.asarray(T["close"], "datetime64[ms]").astype("datetime64[Y]").astype(int) + 1970 if len(T["x"]) else []
    out = {}
    for yr in YEARS:
        x = T["x"][np.asarray(y) == yr] if len(T["x"]) else np.zeros(0)
        x = x[np.isfinite(x)]
        out[str(yr)] = {"n": int(len(x)), "win": float((x > 0).mean()) if len(x) else None,
                        "mean": float(x.mean()) if len(x) else None, "sum": float(x.sum())}
    return out


def sides(kind: str, name: str, tf: str, combo: dict, e: int) -> dict:
    acc = {pn: [0, 0.0, 0.0, 0] for pn, _k in PERIODS}
    for sym in R.SYMBOLS:
        P = R.trade_table(DATA, WORK, kind, name, sym, tf)[e]
        _d, close = R.frame(DATA, sym, tf)
        pid = R.period_ids(close)
        lo, sh = R.signals(DATA, kind, name, sym, tf, combo)
        for mask, s in ((np.asarray(lo, bool), 0), (np.asarray(sh, bool), 1)):
            idx = np.flatnonzero(mask)
            ch, op = P[idx, s], P[idx, 1 - s]
            ok = np.isfinite(ch) & np.isfinite(op)
            for pn, k in PERIODS:
                m = ok & (pid[idx] == k)
                a = acc[pn]
                a[0] += int(m.sum())
                a[1] += float(ch[m].sum())
                a[2] += float(op[m].sum())
                a[3] += int((ch[m] > op[m]).sum())
    return {pn: {"n": a[0], "chosen": a[1] / a[0] if a[0] else None, "opposite": a[2] / a[0] if a[0] else None,
                 "chosen_better": a[3] / a[0] if a[0] else None} for pn, a in acc.items()}


def accounts(T: dict, e: int) -> dict:
    out = {}
    quarter = SZ.size_vector(0.25)
    for pn, k in PERIODS:
        lo, hi = R.PERIOD_MS[k][1], R.PERIOD_MS[k][2]
        if not (T["pid"] == k).any():
            out[pn] = None
            continue
        w = CK.worst(DATA, T, ex(), e, lo, hi)
        q = SZ.account_trades(DATA, T, ex(), lo, hi, e, quarter)
        w["quarter"] = {"final_x": q["final_x"], "max_dd": q["max_dd"], "bust": q["bust"], "trades": q["trades"]}
        out[pn] = w
    return out


def job(item):
    kind, name, tf, pick = item
    specs = [("default", R.default_combo(kind, name), 0)]
    if pick:
        combo = {k: (tuple(v) if isinstance(v, list) else v) for k, v in json.loads(pick["combo"]).items()}
        specs.append(("pick", combo, EXITS.index(pick["exit"])))
    Ts = R.cell_trades(DATA, WORK, kind, name, tf, [(c, e) for _l, c, e in specs])
    rec = {"kind": kind, "name": name, "tf": tf}
    for (lab, combo, e), T in zip(specs, Ts):
        rec[lab] = {"years": years(T), "accounts": accounts(T, e), "sides": sides(kind, name, tf, combo, e)}
    return rec


def items() -> list:
    picks = {(r["kind"], r["name"], r["tf"]): r for r in csv.DictReader(open(os.path.join(RES, "candidates.csv")))
             if r["rank"] == "1"}
    out = [(c["kind"], c["name"], c["tf"], picks.get((c["kind"], c["name"], c["tf"])))
           for c in csv.DictReader(open(os.path.join(RES, "cells.csv")))]
    order = {"4h": 0, "1h": 1, "30m": 2, "15m": 3}
    return sorted(out, key=lambda it: order[it[2]])


if __name__ == "__main__":
    its = items()
    print(len(its), "cells", flush=True)
    res = []
    for k, rec in enumerate(R.run_pool(job, its, PROCS, "deep")):
        res.append(rec)
        print(k, rec["kind"], rec["name"], rec["tf"], flush=True)
        if k % 20 == 0:
            json.dump(res, open(os.path.join(WORK, "ana", "strat_deep.part.json"), "w"))
    json.dump(res, open(os.path.join(WORK, "ana", "strat_deep.json"), "w"))
    print("done", flush=True)
