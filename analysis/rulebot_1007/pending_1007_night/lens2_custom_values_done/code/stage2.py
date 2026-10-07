"""Stage 2: walk-forward selection per cell (PREREG section 6). Output ../work/wf/<cell>.npz:
  day arrays (OOS calendar days x 225 combos): n, sum R net, sum R^2, sum net pct, sum R gross
  selections: for every method key, the combo used in each OOS week (-1 never happens; default = 3)
  decision diagnostics for the gates.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cvlib as C  # noqa: E402
import numpy as np  # noqa: E402

CELLS = os.path.join(C.WORK, "work", "cells")
METRIC = os.environ.get("CV_METRIC", "R")
OUT = os.path.join(C.WORK, "work", "wf" if METRIC == "R" else "wf_" + METRIC)
NS_DAY = 86400 * 10**9
NS_WEEK = 7 * NS_DAY
WEEK0 = np.datetime64("2021-02-01T00:00:00", "ns").astype(np.int64)
T0 = 26                                   # 2021-08-02
DATA_END = np.datetime64("2026-09-30T00:00:00", "ns").astype(np.int64)
NWEEK = int((DATA_END - WEEK0) // NS_WEEK)  # full weeks: 0..NWEEK-1
SPLIT_AB = np.datetime64("2024-07-01T00:00:00", "ns").astype(np.int64)
WINDOWS = (1, 4, 13, 26)
STEPS = (1, 4)
NC = 225
DEFAULT = ((0 * 5 + 0) * 3 + 1) * 3 + 0   # P0, F none, stop 2.0, house = 3
GATES = [(nmin, dl, z) for nmin in (30, 100, 300) for dl in (0.05, 0.15, 0.30) for z in (0.0, 2.0)]
MIN_NAIVE = 10


def combo(p, f, s, x):
    return ((p * 5 + f) * 3 + s) * 3 + x


RESTRICT = {
    "P": [combo(p, 0, 1, 0) for p in range(5)],
    "F": [combo(0, f, 1, 0) for f in range(5)],
    "S": [combo(0, 0, s, 0) for s in range(3)],
    "X": [combo(0, 0, 1, x) for x in range(3)],
}


def load(cellname):
    z = np.load(os.path.join(CELLS, cellname + ".npz"))
    a = {k: z[k] for k in z.files}
    m = len(a["ts"])
    pf = np.zeros((m, 25), np.float64)
    for p in range(5):
        for f in range(5):
            col = a["pmask"][:, p] if f == 0 else (a["pmask"][:, p] & a["fmask"][:, f - 1])
            pf[:, p * 5 + f] = col
    a["pf"] = pf
    return a


def combo_stats(pf, w, v):
    """pf (k x 25), w (k x 9 0/1 weights), v (k x 9 values) -> n, S, Q arrays of 225 combos."""
    n = pf.T @ w            # 25 x 9
    S = pf.T @ (w * v)
    Q = pf.T @ (w * v * v)
    # combo index = (pf * 3 + s) * 3 + x = pf * 9 + j  with j = s * 3 + x
    return n.reshape(-1), S.reshape(-1), Q.reshape(-1)


def select(TR, nweek_oos, gates=GATES, restrict=True):
    """Selections of every method for every scheme from the training arrays TR[W] (weeks x 2 halves x 3 x 225)."""
    sels = {}
    diag = {}
    trimps = {}
    for step in STEPS:
        dec_weeks = list(range(0, nweek_oos, step))
        for W in WINDOWS:
            tr = TR[W]
            key = f"s{step}_w{W}"
            out = {"naive": np.full(nweek_oos, DEFAULT, np.int16)}
            for r in (RESTRICT if restrict else {}):
                out[f"naive_{r}"] = np.full(nweek_oos, DEFAULT, np.int16)
            for g in gates:
                out[f"gate_{g[0]}_{g[1]}_{g[2]}"] = np.full(nweek_oos, DEFAULT, np.int16)
            gd = []
            trimp = np.full(nweek_oos, np.nan)
            for k in dec_weeks:
                h1, h2 = tr[k, 0], tr[k, 1]
                n = h1[0] + h2[0]
                S = h1[1] + h2[1]
                Q = h1[2] + h2[2]
                with np.errstate(invalid="ignore", divide="ignore"):
                    mean = np.where(n > 0, S / np.maximum(n, 1), np.nan)
                apply = slice(k, min(k + step, nweek_oos))

                def pick(cands, nmin):
                    cands = np.asarray(cands)
                    ok = n[cands] >= nmin
                    if not ok.any():
                        return DEFAULT
                    m_ = np.where(ok, mean[cands], -np.inf)
                    best = m_.max()
                    if DEFAULT in cands:
                        di = int(np.flatnonzero(cands == DEFAULT)[0])
                        if ok[di] and m_[di] >= best:
                            return DEFAULT
                    return int(cands[int(np.argmax(m_))])
                cn = pick(np.arange(NC), MIN_NAIVE)
                out["naive"][apply] = cn
                if n[DEFAULT] > 0:
                    trimp[k] = mean[cn] - mean[DEFAULT]
                for r, cs in (RESTRICT.items() if restrict else []):
                    out[f"naive_{r}"][apply] = pick(cs, MIN_NAIVE)
                nd, md = n[DEFAULT], mean[DEFAULT]
                vd = Q[DEFAULT] / nd - md * md if nd > 0 else np.nan
                for g in gates:
                    nmin, dl, zmin = g
                    c = pick(np.arange(NC), nmin)
                    adopt = False
                    if c != DEFAULT and nd > 1:
                        mc = mean[c]
                        vc = Q[c] / n[c] - mc * mc
                        imp = mc - md
                        se = np.sqrt(max(vc, 0) / n[c] + max(vd, 0) / nd)
                        zz = imp / se if se > 0 else np.inf
                        halves_ok = True
                        for hh in (h1, h2):
                            if hh[0][c] < nmin / 4 or hh[0][DEFAULT] < 1:
                                halves_ok = False
                                break
                            if hh[1][c] / hh[0][c] - hh[1][DEFAULT] / hh[0][DEFAULT] <= 0:
                                halves_ok = False
                                break
                        adopt = (imp >= dl) and halves_ok and (zz >= zmin)
                        if g == (100, 0.15, 2.0) or g == (30, 0.05, 0.0):
                            gd.append((k, g[0], c, float(imp), float(zz), bool(halves_ok), bool(adopt)))
                    if adopt:
                        out[f"gate_{g[0]}_{g[1]}_{g[2]}"][apply] = c
            for mk, v in out.items():
                sels[f"{key}|{mk}"] = v
            trimps[key] = trimp
            diag[key] = gd
    return sels, trimps, diag

def run_cell(cellname):
    t_start = time.time()
    a = load(cellname)
    ts = a["ts"]
    done = a["done"].astype(np.float64)
    rnet = np.nan_to_num(a["rnet"].astype(np.float64))
    rgr = np.nan_to_num(a["rgross"].astype(np.float64))
    if METRIC == "R2":     # AMENDMENTS A1: net result in units of the default 2.0 ATR stop
        scale = np.repeat(np.array(C.STOPS) / 2.0, 3)[None, :]
        rnet, rgr = rnet * scale, rgr * scale
    npct = np.nan_to_num(a["npct"].astype(np.float64))
    ec = a["exit_close"]
    pf = a["pf"]
    # ---------------- OOS day arrays (signal day), combos
    oos_lo = WEEK0 + T0 * NS_WEEK
    oos_hi = WEEK0 + NWEEK * NS_WEEK
    nday = int((oos_hi - oos_lo) // NS_DAY)
    sel_oos = (ts >= oos_lo) & (ts < oos_hi)
    io = np.flatnonzero(sel_oos)
    day = ((ts[io] - oos_lo) // NS_DAY).astype(np.int64)
    D = {k: np.zeros((nday, NC)) for k in ("n", "S", "Q", "P", "G")}
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    ends = np.r_[starts[1:], len(day)]
    for s0, e0 in zip(starts, ends):
        rows = io[s0:e0]
        w = done[rows]
        p_ = pf[rows]
        d = day[s0]
        D["n"][d] = (p_.T @ w).reshape(-1)
        D["S"][d] = (p_.T @ (w * rnet[rows])).reshape(-1)
        D["Q"][d] = (p_.T @ (w * rnet[rows] ** 2)).reshape(-1)
        D["P"][d] = (p_.T @ (w * npct[rows])).reshape(-1)
        D["G"][d] = (p_.T @ (w * rgr[rows])).reshape(-1)
    # weekly OOS aggregates from days
    nweek_oos = NWEEK - T0
    Wn = D["n"].reshape(nweek_oos, 7, NC).sum(1)
    WS = D["S"].reshape(nweek_oos, 7, NC).sum(1)
    # ---------------- training stats at every weekly decision t (T0..NWEEK-1), each window, two halves
    TR = {}
    for W in WINDOWS:
        arr = np.zeros((nweek_oos, 2, 3, NC))
        for k, t in enumerate(range(T0, NWEEK)):
            T = WEEK0 + t * NS_WEEK
            lo = T - W * NS_WEEK
            mid = T - W * NS_WEEK // 2
            i0, i1, i2 = np.searchsorted(ts, [lo, mid, T])
            for h, (x0, x1) in enumerate(((i0, i1), (i1, i2))):
                if x1 <= x0:
                    continue
                rows = slice(x0, x1)
                w = done[rows] * (ec[rows] < T)
                n_, S_, Q_ = combo_stats(pf[rows], w, rnet[rows])
                arr[k, h, 0], arr[k, h, 1], arr[k, h, 2] = n_, S_, Q_
        TR[W] = arr
    sels, trimps, diag = select(TR, nweek_oos)
    # ---------------- persistence (halves A / B by signal time)
    ab = {}
    for h, (lo, hi) in enumerate(((oos_lo, SPLIT_AB), (SPLIT_AB, oos_hi))):
        r = (ts >= lo) & (ts < hi)
        n_, S_, Q_ = combo_stats(pf[r], done[r], rnet[r])
        _, P_, _ = combo_stats(pf[r], done[r], npct[r])
        ab[h] = (n_, S_, Q_, P_)
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(os.path.join(OUT, cellname + ".npz"),
                        Dn=D["n"].astype(np.float32), DS=D["S"].astype(np.float32), DQ=D["Q"].astype(np.float32),
                        DP=D["P"].astype(np.float32), DG=D["G"].astype(np.float32),
                        sel_keys=np.array(list(sels.keys())), sel=np.stack(list(sels.values())),
                        abn=np.stack([ab[0][0], ab[1][0]]), abS=np.stack([ab[0][1], ab[1][1]]),
                        abQ=np.stack([ab[0][2], ab[1][2]]), abP=np.stack([ab[0][3], ab[1][3]]),
                        Wn=Wn, WS=WS, TR1=TR[1], TR4=TR[4], TR13=TR[13], TR26=TR[26], trimp_keys=np.array(list(trimps.keys())), trimp=np.stack(list(trimps.values())))
    json.dump({k: v for k, v in diag.items()}, open(os.path.join(OUT, cellname + "_diag.json"), "w"))
    return cellname, time.time() - t_start


if __name__ == "__main__":
    from multiprocessing import Pool
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    C.check_prereg()
    cells = [f"{s}_{tf}" for s in C.STRATS for tf in C.TFS]
    if a.only:
        cells = [c for c in cells if c in a.only.split(",")]
    with Pool(a.procs) as p:
        for r in p.imap_unordered(run_cell, cells):
            print(r[0], "%.0fs" % r[1], flush=True)
