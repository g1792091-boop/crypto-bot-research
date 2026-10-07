"""Stage 1: per cell (strategy x tf) every unique signal of the 5 parameter sets, its filter flags and its outcome
under 3 stops x 3 exits. Output: ../work/cells/<strategy>_<tf>.npz and a parity log.

    python3 -I stage1.py [--procs 4] [--only NAME_TF,...]
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cvlib as C  # noqa: E402
import numpy as np  # noqa: E402

OUT = os.path.join(C.WORK, "work", "cells")


def cell(args):
    name, tf = args
    path = os.path.join(OUT, f"{name}_{tf}.npz")
    if os.path.exists(path):
        return name, tf, "cached", 0.0, {}
    t0 = time.time()
    src, fam, _var = C.STRATS[name]
    tfns = C.TF_MIN[tf] * 60 * 10**9
    cols = {x: [] for x in ("coin", "idx", "ts", "side", "pmask", "fmask", "done", "held", "rnet", "rgross", "npct",
                            "exit_close", "stop_pct")}
    info = {"parity": {}, "signals_by_p": [0] * 5, "unique": 0}
    ds_par = None
    if src == "ds":
        ds_par = json.load(open(os.path.join(C.WORK, "work", "ds_parity.json")))
    for ci, coin in enumerate(C.COINS):
        b, z = C.load_npz(tf, coin)
        df = C.frame(b, tf)
        n = len(b["ts"])
        sigs = [C.strategy_signal(name, k, df, tf) for k in range(5)]
        if src == "pd":
            ref = z[f"s__{name}"].astype(np.int8)
            mism = int((sigs[0] != ref).sum())
        else:
            mism = ds_par[f"{name}|{tf}|{coin}"]["mismatch"]
        info["parity"][coin] = mism
        if mism:
            raise SystemExit(f"default parity failed {name} {tf} {coin}: {mism}")
        lo = int(np.searchsorted(b["ts"], C.START))
        okbar = np.zeros(n, bool)
        okbar[lo:n - 1] = True
        okbar &= np.isfinite(b["atr"]) & (b["atr"] > 0)
        keys = set()
        per = []
        for k, sg in enumerate(sigs):
            ii = np.flatnonzero((sg != 0) & okbar)
            info["signals_by_p"][k] += len(ii)
            per.append(set(zip(ii.tolist(), sg[ii].tolist())))
            keys |= per[-1]
        keys = sorted(keys)
        if not keys:
            continue
        idx = np.array([x[0] for x in keys], np.int64)
        side = np.array([x[1] for x in keys], np.int64)
        pm = np.zeros((len(idx), 5), bool)
        for k in range(5):
            pm[:, k] = [kk in per[k] for kk in keys]
        fl = C.filter_flags(df, b, tf, fam)
        fm = np.zeros((len(idx), 4), bool)
        for j, f in enumerate(C.FILTERS[1:]):
            lgok, shok = fl[f]
            fm[:, j] = np.where(side == 1, lgok[idx], shok[idx])
        D, Hd, RN, RG, NP, EC = (np.zeros((len(idx), 9), t) for t in (bool, np.int32, np.float32, np.float32,
                                                                          np.float32, np.int64))
        SP = np.zeros((len(idx), 3), np.float32)
        for si, k in enumerate(C.STOPS):
            raw = b["o"][idx + 1]
            fill = raw * (1 + side * C.SLIP)
            SP[:, si] = np.abs(fill - (raw - side * k * b["atr"][idx])) / fill
            for xi, mode in enumerate(C.EXITS):
                j = si * 3 + xi
                dn, hd, rn, rg, npct = C.outcomes(b, idx, side, tf, k, mode)
                D[:, j], Hd[:, j] = dn, hd
                RN[:, j], RG[:, j], NP[:, j] = rn, rg, npct
                EC[:, j] = b["ts"][np.minimum(idx + hd, n - 1)] + tfns
        for key, val in (("coin", np.full(len(idx), ci, np.int8)), ("idx", idx), ("ts", b["ts"][idx]),
                         ("side", side.astype(np.int8)), ("pmask", pm), ("fmask", fm), ("done", D), ("held", Hd),
                         ("rnet", RN), ("rgross", RG), ("npct", NP), ("exit_close", EC), ("stop_pct", SP)):
            cols[key].append(val)
    arr = {k: np.concatenate(v) for k, v in cols.items()}
    o = np.argsort(arr["ts"], kind="stable")
    arr = {k: v[o] for k, v in arr.items()}
    info["unique"] = int(len(arr["ts"]))
    info["undone_share"] = [float(1 - arr["done"][:, j].mean()) for j in range(9)]
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(path + ".tmp.npz", **arr)
    os.replace(path + ".tmp.npz", path)
    json.dump(info, open(os.path.join(OUT, f"{name}_{tf}.json"), "w"))
    return name, tf, "done", time.time() - t0, info


if __name__ == "__main__":
    import argparse
    from multiprocessing import Pool
    ap = argparse.ArgumentParser()
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    C.check_prereg()
    jobs = [(s, tf) for s in C.STRATS for tf in C.TFS]
    if a.only:
        want = set(a.only.split(","))
        jobs = [j for j in jobs if f"{j[0]}_{j[1]}" in want]
    # biggest first
    with Pool(a.procs) as p:
        for r in p.imap_unordered(cell, jobs):
            print(r[0], r[1], r[2], "%.0fs" % r[3], r[4].get("unique"), r[4].get("signals_by_p"), flush=True)
