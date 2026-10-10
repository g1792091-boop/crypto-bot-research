"""Reference report (after the results): every strategy x timeframe, at the default numbers with the live exit (what
the rule bot runs) and at the cell's rank-1 pick. Per spec: per period (select 2021-23, test 2024-26, extra 2020)
signals, win rate, average win / loss, payoff and mean P&L per trade; the account run per period (live sizing:
final multiple, max drawdown, trades, bust); per market state (장세, 큰 흐름, 변동성), per coin and per side over
2021-01 .. 2026-10.

    python research/fullgrid/diag/strat_report.py WORKROOT [PROCS] [RESULTS_BRANCH_DIR]

Output: WORKROOT/fgwork/ana/strat_report.json. DeepSeek money figures are computed but the Korean report hides them
(D11).
"""

import csv
import json
import os
import sys

FG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)

import numpy as np  # noqa: E402

import kernel as K  # noqa: E402
import regimes as RG  # noqa: E402
import run as R  # noqa: E402
import sizing as SZ  # noqa: E402
import teams as TM  # noqa: E402

SP = sys.argv[1]
PROCS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
RES = os.path.join(SP, "fgresults", sys.argv[3] if len(sys.argv) > 3 else "fullgrid-results-20261010-1602")
WORK = os.path.join(SP, "fgwork")
DATA = os.path.join(SP, "fg1m")
R.FRAME_DIR[0] = os.path.join(WORK, "frames")
EXITS = [e[0] for e in R.K.EXITS]
PERIODS = (("select", R.P_SELECT), ("test", R.P_TEST), ("extra", R.P_EXTRA))
_states: dict = {}
_ex: list = []


def stats(x: np.ndarray) -> dict:
    x = x[np.isfinite(x)]
    if not len(x):
        return {"n": 0}
    w, lo = x[x > 0], x[x <= 0]
    return {"n": int(len(x)), "win": float(len(w) / len(x)), "mean": float(x.mean()), "sum": float(x.sum()),
            "avg_win": float(w.mean()) if len(w) else None, "avg_loss": float(lo.mean()) if len(lo) else None,
            "payoff": float(w.mean() / -lo.mean()) if len(w) and len(lo) and lo.mean() < 0 else None}


def one(T: dict, kind: str, e: int, states_tf: list) -> dict:
    if not _ex:
        _ex.append(R.exchange(os.path.join(FG, "exchange.json"), False))
    out = {"periods": {pn: stats(T["x"][T["pid"] == k]) for pn, k in PERIODS}, "account": {}}
    S = K.settings_vector()
    for pn, k in PERIODS:
        lo, hi = R.PERIOD_MS[k][1], R.PERIOD_MS[k][2]
        if not ((T["pid"] == k).any()):
            out["account"][pn] = None
            continue
        a = SZ.account_trades(DATA, T, _ex[0], lo, hi, e, S)
        out["account"][pn] = {"final_x": a["final_x"], "max_dd": a["max_dd"], "trades": a["trades"],
                              "bust": a["bust"], "liquidations": a["liquidations"]}
    span = (T["pid"] == R.P_SELECT) | (T["pid"] == R.P_TEST)
    lab = RG.tag(T, states_tf) if len(T["x"]) else {d: [] for d in TM.DIMS}
    out["states"] = {}
    for d, states in TM.DIMS.items():
        st = np.array([s if s is not None else "모름" for s in lab[d]], object) if len(T["x"]) else np.array([], object)
        out["states"][d] = {s: stats(T["x"][span & (st == s)]) for s in states}
    out["coins"] = {sym: stats(T["x"][span & (T["coin"] == ci)]) for ci, sym in enumerate(R.SYMBOLS)}
    out["sides"] = {"long": stats(T["x"][span & (T["side"] > 0)]), "short": stats(T["x"][span & (T["side"] < 0)])}
    return out


def job(item):
    kind, name, tf, pick = item
    specs = [(R.default_combo(kind, name), 0)]
    if pick:
        specs.append(({k: (tuple(v) if isinstance(v, list) else v) for k, v in json.loads(pick["combo"]).items()},
                      EXITS.index(pick["exit"])))
    Ts = R.cell_trades(DATA, WORK, kind, name, tf, specs)
    if tf not in _states:
        _states[tf] = [RG.coin_states(DATA, s, tf) for s in R.SYMBOLS]
    rec = {"kind": kind, "name": name, "tf": tf, "default": one(Ts[0], kind, 0, _states[tf])}
    if pick:
        rec["pick"] = one(Ts[1], kind, specs[1][1], _states[tf])
        rec["pick"]["combo"] = pick["combo"]
        rec["pick"]["exit"] = pick["exit"]
        rec["pick"]["checks"] = {c: pick[c] == "True" for c in pick if c.startswith("check_")}
        rec["pick"]["test_p"] = float(pick["test_p"]) if pick["test_p"] else None
    return rec


def items() -> list:
    picks = {}
    for r in csv.DictReader(open(os.path.join(RES, "candidates.csv"))):
        if r["rank"] == "1":
            picks[(r["kind"], r["name"], r["tf"])] = r
    out = []
    for c in csv.DictReader(open(os.path.join(RES, "cells.csv"))):
        out.append((c["kind"], c["name"], c["tf"], picks.get((c["kind"], c["name"], c["tf"]))))
    order = {"4h": 0, "1h": 1, "30m": 2, "15m": 3}
    return sorted(out, key=lambda it: order[it[2]])


if __name__ == "__main__":
    its = items()
    print(len(its), "cells", flush=True)
    res = []
    for k, rec in enumerate(R.run_pool(job, its, PROCS, "report")):
        res.append(rec)
        print(k, rec["kind"], rec["name"], rec["tf"], flush=True)
        if k % 20 == 0:
            json.dump(res, open(os.path.join(WORK, "ana", "strat_report.part.json"), "w"))
    json.dump(res, open(os.path.join(WORK, "ana", "strat_report.json"), "w"))
    print("done", flush=True)
