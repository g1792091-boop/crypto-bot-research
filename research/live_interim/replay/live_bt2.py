"""Same live days, second part: (1) the 171 DeepSeek cells at their default numbers (labels are what gets reported);
(2) the 38 watch picks of the 후보 리그 as cand (pick numbers + pick exit, live size), quarter (1/4 margin),
exitonly (default numbers + pick exit) and base (default numbers + live exit), from LIVE_D0 and from 2026-10-01."""
import json
import os
import sys
import time

FG = "/home/user/crypto-bot-research/research/fullgrid"
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)
os.environ.setdefault("OMP_NUM_THREADS", "1")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import kernel as K  # noqa: E402
import run as R  # noqa: E402
import sizing as SZ  # noqa: E402

SP = os.environ["WORKROOT"]
LD = os.path.join(SP, "interim", "ld")
LW2 = os.path.join(SP, "interim", "lw2")
ms = lambda s: int(pd.Timestamp(s, tz="UTC").value // 1_000_000)  # noqa: E731
LIVE_D0 = ms(sys.argv[1])
END = ms(sys.argv[2])
OCT1 = ms("2026-10-01")
PROCS = int(sys.argv[3]) if len(sys.argv) > 3 else 4
CANDS = json.load(open("/home/user/crypto-bot-research/candleague/data/candidates.json"))["candidates"]
EXN = [e[0] for e in K.EXITS]
NEED = sorted({0} | {EXN.index(c["exit"]) for c in CANDS})


def outcome_job(args):
    sym, tf, ex = args
    path = R.outcome_path(LW2, sym, tf)
    if os.path.exists(path):
        return ""
    t0 = time.time()
    d = R.minute_data(LD, sym)
    df, close = R.frame(LD, sym, tf)
    atr = R._vendor_fg().atr(df, 14).to_numpy(float)
    br, step, mn = ex[sym]
    S = K.settings_vector()
    n = len(close)
    res = {}
    for g, flag in (("best", True), ("normal", False)):
        f = np.full(n, flag)
        pnl = np.full((len(K.EXITS), n, 2), np.nan, np.float32)
        for ei in NEED:
            p, _exi, _r, _lv = K.outcomes(S, br, d["ts"], d["o"], d["h"], d["l"], d["mo"], d["mh"], d["ml"], d["fund"],
                                          close.astype(np.int64), atr, f, f, R.EQUITY, step, mn, *K.exit_args(ei),
                                          *R.exit_levels(LD, sym, tf, ei, n))
            pnl[ei] = p
        res[f"pnl_{g}"] = pnl
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez(path + ".tmp.npz", close=close, atr=atr, exits=np.array(EXN), **res)
    os.replace(path + ".tmp.npz", path)
    return f"{tf} {sym} {n} bars, exits {NEED}, {time.time() - t0:.0f}s"


def acct(T, ex, lo, e, S):
    a = SZ.account_trades(LD, T, ex, lo, END, e, S)
    r = a["ret"]
    return {"trades": a["trades"], "win": float((r > 0).mean()) if len(r) else None,
            "mean": float(r.mean()) if len(r) else None, "final_x": a["final_x"], "max_dd": a["max_dd"],
            "bust": a["bust"], "exit_ms": a["exit_ms"].tolist(), "ret": r.tolist()}


def ds_job(c):
    _k, name, tf = c
    ex = R.exchange(os.path.join(FG, "exchange.json"), False)
    T = R.cell_trades(LD, LW2, "ds", name, tf, [(R.default_combo("ds", name), 0)])[0]
    m = (T["close"] >= LIVE_D0) & (T["close"] < END) & np.isfinite(T["x"])
    x = T["x"][m]
    return {"name": name, "tf": tf, "sig_n": int(m.sum()), "sig_win": float((x > 0).mean()) if len(x) else None,
            "sig_mean": float(x.mean()) if len(x) else None, "acct": acct(T, ex, LIVE_D0, 0, K.settings_vector())}


def cand_job(c):
    ex = R.exchange(os.path.join(FG, "exchange.json"), False)
    e = EXN.index(c["exit"])
    combo = {k: (tuple(v) if isinstance(v, list) else v) for k, v in c["combo"].items()}
    dflt = R.default_combo(c["kind"], c["name"])
    Tc, Tx, Tb = R.cell_trades(LD, LW2, c["kind"], c["name"], c["tf"], [(combo, e), (dflt, e), (dflt, 0)])
    out = {"id": c["id"], "kind": c["kind"], "name": c["name"], "tf": c["tf"], "exit": c["exit"]}
    for lab, lo in (("live", LIVE_D0), ("oct1", OCT1)):
        out[lab] = {"cand": acct(Tc, ex, lo, e, K.settings_vector()), "quarter": acct(Tc, ex, lo, e, SZ.size_vector(0.25)),
                    "exitonly": acct(Tx, ex, lo, e, K.settings_vector()), "base": acct(Tb, ex, lo, 0, K.settings_vector())}
    return out


if __name__ == "__main__":
    R.FRAME_DIR[0] = os.path.join(SP, "interim", "lw", "frames")
    ex = R.exchange(os.path.join(FG, "exchange.json"), False)
    for msg in R.run_pool(outcome_job, [(s, tf, ex) for tf in R.TFS for s in R.SYMBOLS], PROCS, "out2"):
        if msg:
            print(msg, flush=True)
    cands = []
    for k, r in enumerate(R.run_pool(cand_job, CANDS, PROCS, "cands")):
        cands.append(r)
        print("cand", k, r["id"], r["live"]["cand"]["trades"], flush=True)
    json.dump({"live_d0": LIVE_D0, "end": END, "cands": cands}, open(os.path.join(SP, "interim", "watch_preview.json"), "w"))
    ds = []
    for k, r in enumerate(R.run_pool(ds_job, R.cells("ds"), PROCS, "ds")):
        ds.append(r)
        print("ds", k, r["name"], r["tf"], r["sig_n"], flush=True)
    json.dump({"live_d0": LIVE_D0, "end": END, "cells": ds}, open(os.path.join(SP, "interim", "ds_replay.json"), "w"))
    print("done")
