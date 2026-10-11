"""Backtest engine on the live days: 36 core x 4 tf, default numbers, live exit (exit 0), data 2026-03-01 .. 2026-10-10
(Binance public archive; October from the daily files, October funding not in the archive -> 0).
Per cell: every signal's outcome (per-signal mean, like the full grid) and the one-position account path from LIVE_D0."""
import datetime as dt
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

import data as DATA  # noqa: E402
import kernel as K  # noqa: E402
import run as R  # noqa: E402
import sizing as SZ  # noqa: E402

SP = sys.argv[3] if len(sys.argv) > 3 else os.environ["WORKROOT"]
OLD = os.path.join(SP, "fg1m")
LD = os.path.join(SP, "interim", "ld")
LW = os.path.join(SP, "interim", "lw")
FROM = int(pd.Timestamp("2026-03-01", tz="UTC").value // 1_000_000)
DAYS = [str(dt.date(2026, 10, d)) for d in range(1, int(os.environ.get("LAST_DAY", "9")) + 1)]
LIVE_D0 = int(pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2026-10-05 00:00", tz="UTC").value // 1_000_000)
END = int(pd.Timestamp(str(dt.date(2026, 10, int(os.environ.get("LAST_DAY", "9")) + 1)), tz="UTC").value // 1_000_000)
PROCS = int(sys.argv[2]) if len(sys.argv) > 2 else 3


def build_data():
    raw = os.path.join(LD, "raw")
    for sym in DATA.SYMBOLS:
        out = os.path.join(LD, "1m", f"{sym}.npz")
        if os.path.exists(out):
            continue
        old = DATA.load(OLD, sym)
        m = old["ts"] >= FROM
        base = {k: v[m] for k, v in old.items()}
        kl, mk = [], []
        for d in DAYS:
            for kind, acc in (("klines", kl), ("markPriceKlines", mk)):
                rel = DATA.rel_daily(kind, sym, d)
                if DATA.fetch(raw, rel) != "ok":
                    raise SystemExit(f"missing {rel}")
                acc.append(DATA.read_kline_zip(os.path.join(raw, rel)))
        k = pd.concat(kl).drop_duplicates("t", keep="last").sort_values("t").reset_index(drop=True)
        k = k[k["volume"] > 0].reset_index(drop=True)
        mkd = pd.concat(mk).drop_duplicates("t", keep="last").set_index("t").reindex(k["t"].to_numpy(np.int64))
        no_mark = mkd["open"].isna().to_numpy()
        new = {"ts": k["t"].to_numpy(np.int64), "fund": np.zeros(len(k))}
        for a, b in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")):
            new[a] = k[b].to_numpy(float)
        for a, b, fall in (("mo", "open", "o"), ("mh", "high", "h"), ("ml", "low", "l"), ("mc", "close", "c")):
            new[a] = np.where(no_mark, new[fall], mkd[b].to_numpy(float))
        assert new["ts"][0] > base["ts"][-1], sym
        allv = {key: np.concatenate([base[key], new[key]]) for key in base}
        os.makedirs(os.path.dirname(out), exist_ok=True)
        np.savez(out, **allv)
        print(sym, "minutes", len(allv["ts"]), "oct", len(new["ts"]), "mark filled", int(no_mark.sum()),
              "last", pd.Timestamp(int(allv["ts"][-1]), unit="ms"), flush=True)


def outcome_job(args):
    sym, tf, ex = args
    path = R.outcome_path(LW, sym, tf)
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
        p, _exi, r, _lv = K.outcomes(S, br, d["ts"], d["o"], d["h"], d["l"], d["mo"], d["mh"], d["ml"], d["fund"],
                                     close.astype(np.int64), atr, f, f, R.EQUITY, step, mn, *K.exit_args(0),
                                     *R.exit_levels(LD, sym, tf, 0, n))
        res[f"pnl_{g}"] = p[None].astype(np.float32)
        res[f"reason_{g}"] = r[None]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez(path + ".tmp.npz", close=close, atr=atr, exits=np.array([K.EXITS[0][0]]), **res)
    os.replace(path + ".tmp.npz", path)
    return f"{tf} {sym} {n} bars {time.time() - t0:.0f}s"


def cell_job(c):
    name, tf = c
    ex = R.exchange(os.path.join(FG, "exchange.json"), False)
    T = R.cell_trades(LD, LW, "core", name, tf, [(R.default_combo("core", name), 0)])[0]
    m = (T["close"] >= LIVE_D0 - 86_400_000 * 4) & np.isfinite(T["x"])
    sig = [[int(T["close"][i]), int(T["coin"][i]), int(T["side"][i]), float(T["x"][i]), bool(T["best"][i])]
           for i in np.flatnonzero(m)]
    a = SZ.account_trades(LD, T, ex, LIVE_D0, END, 0, K.settings_vector())
    return {"name": name, "tf": tf, "signals": sig,
            "account": {"exit_ms": a["exit_ms"].tolist(), "ret": a["ret"].tolist(), "final_x": a["final_x"],
                        "max_dd": a["max_dd"], "trades": a["trades"], "bust": a["bust"]}}


if __name__ == "__main__":
    build_data()
    R.FRAME_DIR[0] = os.path.join(LW, "frames")
    ex = R.exchange(os.path.join(FG, "exchange.json"), False)
    for tf in R.TFS:
        for sym in R.SYMBOLS:
            R.frame(LD, sym, tf)
    for msg in R.run_pool(outcome_job, [(s, tf, ex) for tf in R.TFS for s in R.SYMBOLS], PROCS, "out"):
        if msg:
            print(msg, flush=True)
    cells = [(n, tf) for n in R.core_names() for tf in R.TFS]
    res = []
    for k, r in enumerate(R.run_pool(cell_job, cells, PROCS, "cells")):
        res.append(r)
        print(k, r["name"], r["tf"], len(r["signals"]), r["account"]["trades"], flush=True)
    json.dump({"live_d0": LIVE_D0, "end": END, "cells": res}, open(os.path.join(SP, "interim", "live_bt.json"), "w"))
    print("done")
