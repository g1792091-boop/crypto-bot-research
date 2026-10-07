"""Planted-improvement test of the search and the gates (power side; not in the PREREG grid, an added check).
For each cell, one random non-default combination (>= 30% of the default's trades) is shifted so that its true
OOS mean beats the default by exactly delta R (0.10 / 0.20 / 0.30) in every week; every other combination is
left as it is. Then the same selection code runs. Output ../out/planted.csv (per cell x delta x method) and
../out/planted_summary.csv.
"""
import os
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cvlib as C  # noqa: E402
import stage2 as S2  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

METRIC = os.environ.get("CV_METRIC", "R")
WF = os.path.join(C.WORK, "work", "wf" if METRIC == "R" else "wf_" + METRIC)
OUT = os.path.join(C.WORK, "out" if METRIC == "R" else "out_" + METRIC)
DEF = S2.DEFAULT
DELTAS = (0.10, 0.20, 0.30)


def job(cell):
    z = np.load(os.path.join(WF, cell + ".npz"))
    Dn, DS = z["Dn"].astype(float), z["DS"].astype(float)
    n = Dn.sum(0)
    m = DS.sum(0) / np.maximum(n, 1)
    rng = np.random.default_rng(zlib.crc32(cell.encode()))
    cands = np.flatnonzero((n >= 0.3 * n[DEF]) & (np.arange(225) != DEF))
    nwo = Dn.shape[0] // 7
    wk = np.arange(Dn.shape[0]) // 7
    rows = []
    for dl in DELTAS:
        c = int(rng.choice(cands))
        shift = dl - (m[c] - m[DEF])
        TR = {}
        for W in S2.WINDOWS:
            t = z[f"TR{W}"].astype(float).copy()
            n_, S_ = t[:, :, 0, c].copy(), t[:, :, 1, c].copy()
            t[:, :, 1, c] = S_ + shift * n_
            t[:, :, 2, c] = t[:, :, 2, c] + 2 * shift * S_ + shift * shift * n_
            TR[W] = t
        DSp = DS.copy()
        DSp[:, c] += shift * Dn[:, c]
        sels, _tr, _dg = S2.select(TR, nwo, gates=S2.GATES, restrict=False)
        for key, sel in sels.items():
            scheme, meth = key.split("|")
            sel = sel.astype(int)
            cd = sel[wk]
            ar = np.arange(len(cd))
            ns, Ss = Dn[ar, cd].sum(), DSp[ar, cd].sum()
            nd, Sd = Dn[:, DEF].sum(), DSp[:, DEF].sum()
            first = np.flatnonzero(sel == c)
            rows.append(dict(cell=cell, delta=dl, planted=c, planted_n=int(n[c]), scheme=scheme, method=meth,
                             adopt_share=float(np.mean(sel == c)),
                             wrong_share=float(np.mean((sel != c) & (sel != DEF))),
                             oos_delta=float(Ss / ns - Sd / nd), n_sel=int(ns), n_def=int(nd),
                             first_adopt_week=int(first[0]) if len(first) else -1))
    return rows


if __name__ == "__main__":
    from multiprocessing import Pool
    C.check_prereg()
    cells = [f"{s}_{tf}" for s in C.STRATS for tf in C.TFS]
    allr = []
    with Pool(4) as p:
        for rr in p.imap_unordered(job, cells):
            allr += rr
            print(rr[0]["cell"], flush=True)
    df = pd.DataFrame(allr)
    os.makedirs(OUT, exist_ok=True)
    df.to_csv(os.path.join(OUT, "planted.csv"), index=False)
    g = df.groupby(["delta", "scheme", "method"])
    sm = g.agg(cells=("cell", "count"), adopt_share=("adopt_share", "mean"), wrong_share=("wrong_share", "mean"),
               oos_delta_eqw=("oos_delta", "mean"),
               median_first_adopt_week=("first_adopt_week", lambda x: float(np.median(np.where(x < 0, 9999, x)))),
               cells_never_adopt=("first_adopt_week", lambda x: int((x < 0).sum()))).reset_index()
    sm["captured_share"] = sm["oos_delta_eqw"] / sm["delta"]
    sm.to_csv(os.path.join(OUT, "planted_summary.csv"), index=False)
    print(sm[sm.method.isin(["naive", "gate_100_0.15_2.0", "gate_300_0.15_2.0", "gate_30_0.05_0.0"])].to_string())
