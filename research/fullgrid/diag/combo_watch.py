"""Reference diagnostic (not pre-registered, after the results): the 38 watch accounts in watch_sel.json (16
strategies, one near-miss pick per cell). Per account: daily P&L and entries over 2021-01 .. 2026-10 (for overlap and
correlation), and for core accounts the account run of each period at the live size and at 1/4 size.

    python research/fullgrid/diag/combo_watch.py WORKROOT

Output: WORKROOT/fgwork/ana/combo_watch.json (summarised by combo_sum.py).
"""

import json
import os
import sys

FG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)

import checks as CK  # noqa: E402
import run as R  # noqa: E402
import sizing as SZ  # noqa: E402

SP = sys.argv[1]
WORK = os.path.join(SP, "fgwork")
DATA = os.path.join(SP, "fg1m")
R.FRAME_DIR[0] = os.path.join(WORK, "frames")
EX = R.exchange(os.path.join(FG, "exchange.json"), False)
EXITS = [e[0] for e in R.K.EXITS]
SEL = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "watch_sel.json")))
PER = {name: (a, b) for name, a, b in R.PERIOD_MS}


def job(r):
    combo = {k: (tuple(v) if isinstance(v, list) else v) for k, v in json.loads(r["combo"]).items()}
    e = EXITS.index(r["exit"])
    T = R.combo_trades(DATA, WORK, r["kind"], r["name"], r["tf"], combo, e)
    span = CK.in_span(T)
    out = {"id": f"{r['kind']}|{r['name']}|{r['tf']}|{r['rank']}", "kind": r["kind"], "tf": r["tf"],
           "daily": {int(k): v for k, v in CK.daily(span).items()},
           "entries": {k: span[k].tolist() for k in ("close", "coin", "side")}, "acct": {}}
    if r["kind"] == "core":
        for scale in (1.0, 0.25):
            S = SZ.size_vector(scale)
            for pname, (lo, hi) in PER.items():
                a = SZ.account_trades(DATA, T, EX, lo, hi, e, S)
                out["acct"][f"{scale}|{pname}"] = {"exit_ms": a["exit_ms"].tolist(), "ret": a["ret"].tolist(),
                                                   "final_x": a["final_x"], "max_dd": a["max_dd"],
                                                   "trades": a["trades"]}
    return out


if __name__ == "__main__":
    res = []
    for k, o in enumerate(R.run_pool(job, SEL, 3, "watch")):
        res.append(o)
        print(k, o["id"], flush=True)
    json.dump(res, open(os.path.join(WORK, "ana", "combo_watch.json"), "w"))
    print("done", flush=True)
