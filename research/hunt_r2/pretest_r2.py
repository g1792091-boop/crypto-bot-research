"""Hunt round 2 select-only reads (PREREG_HUNT_R2.md section 6), written after ``picks.json`` is hashed and before
``test.json`` exists. This file holds the CSCV / PBO read over the real Stage 0 and Stage A runs; the other section-6
reads are added here before the code pin.

CSCV (6, as W R4 (2)): the 36 select months in 12 blocks of 3 consecutive months; all C(12, 6) = 924 half / half
splits; in each split Stage 0 and Stage A are replayed on the in-sample (IS) half with the same rules (position
minimum 36 instead of 72), from the real runs' monthly series only (no null run, no new run). Per split: the replay's
rank-1 candidate peak and its top-10 candidate peaks, their out-of-sample (OOS) relative rank among the selectable
systems (omega = average rank / (N + 1)), PBO = share of splits whose rank-1 omega <= 1/2 (logit <= 0), and the slope
of the rank-1 peak's OOS score on its IS score. The hurdle is not replayed.

Runs that do not exist cannot be replayed: Stage A ran only at each name's real anchor. ``mode="strict"`` (the
default): a split whose IS anchor of a name is not the real anchor gives that name no Stage A (no candidate), counted
per name as ``anchor_moved``; ``mode="fixed"``: Stage A on the real anchor's lattice whatever the IS anchor (printed
beside, labelled). See the DEVIATIONS proposal in the code-review notes.

IS quantities of a run (one system's 36 monthly ln M at base cost and at cost x2, positions opened per month, bust
month): S = mean ln M over the IS months, S2 the same at cost x2, n = positions opened in IS months, bust = the bust
month is an IS month, median_M = median of exp(ln M) over the IS months. OOS score = mean ln M over the OOS months.
"""

from __future__ import annotations

import itertools
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt_r2 import lattice as L  # noqa: E402
from research.hunt_r2 import select_r2 as SR  # noqa: E402

N_BLOCKS, BLOCK_MONTHS, CSCV_MIN_POS, TOP = 12, 3, 36, 10


def splits(n_blocks: int = N_BLOCKS, block: int = BLOCK_MONTHS) -> np.ndarray:
    """(924, 36) bool: the IS months of every half / half split, in itertools.combinations order."""
    out = []
    for c in itertools.combinations(range(n_blocks), n_blocks // 2):
        m = np.zeros(n_blocks * block, bool)
        for b in c:
            m[b * block:(b + 1) * block] = True
        out.append(m)
    return np.asarray(out)


def _is_stats(lnM: np.ndarray, pos: np.ndarray, bust_m: np.ndarray, IS: np.ndarray) -> tuple:
    """Per system (rows) and split (columns): IS mean ln M, IS positions, IS bust, OOS mean ln M."""
    w = IS.astype(float)
    k = w.sum(axis=1)
    S = lnM @ w.T / k
    O = lnM @ (1.0 - w).T / (IS.shape[1] - k)
    n = pos @ w.T
    bust = np.zeros(S.shape, bool)
    has = bust_m >= 0
    bust[has] = IS[:, bust_m[has]].T
    return S, n, bust, O


def omega(x: float, pool: np.ndarray) -> float:
    """Relative rank of x in the pool (x included in it): average rank / (N + 1)."""
    lt = float((pool < x).sum())
    eq = float((pool == x).sum())
    return (lt + (eq + 1.0) / 2.0) / (len(pool) + 1.0)


def cscv(units: dict, names_order: list, mode: str = "strict", top: int = TOP) -> dict:
    """``units`` = the real search's ``select_r2.name_unit(real=True)`` results by name."""
    IS = splits()
    nsp = len(IS)
    prep, pool_O = {}, []
    for nm in names_order:
        u = units[nm]
        lat = L.coarse(nm)
        rows = u["stage0"]
        r_lnM = np.asarray([r["lnM"] for r in rows], float)
        r_pos = np.asarray([r["pos_month"] for r in rows], float)
        r_bm = np.asarray([r["bust_month"] for r in rows], np.int64)
        rS, rn, rb, rO = _is_stats(r_lnM, r_pos, r_bm, IS)
        r_med = np.stack([np.median(np.exp(r_lnM[:, m]), axis=1) for m in IS], axis=1)
        ex = np.asarray(u["exists"], bool)
        npt = len(lat)
        lnM = np.zeros((npt, IS.shape[1]))
        lnM2 = np.zeros((npt, IS.shape[1]))
        pos = np.zeros((npt, IS.shape[1]))
        bm = np.full(npt, -1, np.int64)
        for i in np.flatnonzero(ex):
            lnM[i], lnM2[i], pos[i], bm[i] = u["lnM"][i], u["lnM2"][i], u["pos_month"][i], u["bust_month"][i]
        S, n, bust, O = _is_stats(lnM, pos, bm, IS)
        S2 = lnM2 @ IS.astype(float).T / IS.sum(axis=1)
        prep[nm] = dict(rows=rows, rS=rS, rn=rn, rb=rb, r_med=r_med, S=S, S2=S2, n=n, bust=bust, O=O, ex=ex, lat=lat)
        pool_O.append(rO)                                         # Stage 0: every default system
        sel = ex.copy()
        sel[lat.default] = False                                   # the default point is the Stage 0 system there
        pool_O.append(O[sel])
    pool = np.concatenate(pool_O, axis=0)                          # (N systems, splits)
    w1, w10, is1, oos1, top1 = [], [], [], [], []
    moved = {nm: 0 for nm in names_order}
    for s in range(nsp):
        anchors, per = {}, {}
        for nm in names_order:
            p = prep[nm]
            rows = [{"tf": r["tf"], "gate": r["gate"], "S": p["rS"][i, s], "n": p["rn"][i, s],
                     "bust": bool(p["rb"][i, s]), "median_M": p["r_med"][i, s], "min_pos": CSCV_MIN_POS}
                    for i, r in enumerate(p["rows"])]
            a = SR.anchor_slot(rows)
            if a != units[nm]["anchor"]:
                moved[nm] += 1
                if mode == "strict":
                    continue
            anchors[nm] = (units[nm]["anchor_tf"], units[nm]["anchor_gate"])
        fm = SR.foreign_masks(names_order, anchors)
        cands = []
        for nm in anchors:
            p = prep[nm]
            st = SR.stage_a(p["lat"], p["S"][:, s], p["n"][:, s], p["bust"][:, s], p["ex"], S2=p["S2"][:, s],
                            default_eff=units[nm]["default_eff"], foreign=fm.get(nm), min_pos=CSCV_MIN_POS)
            if st["candidate"]:
                cands.append({"name": nm, "family": p["lat"].family, "P": st["P_peak"], "P2": st["P2_peak"],
                              "peak": st["peak"]})
            per[nm] = st
        ranked = SR.rank_candidates(cands)
        if not ranked:
            continue
        col = pool[:, s]
        oms = [omega(prep[c["name"]]["O"][c["peak"], s], col) for c in ranked[:top]]
        c1 = ranked[0]
        w1.append(oms[0])
        w10.append(float(np.mean(oms)))
        is1.append(float(prep[c1["name"]]["S"][c1["peak"], s]))
        oos1.append(float(prep[c1["name"]]["O"][c1["peak"], s]))
        top1.append(c1["name"])
    w1a = np.asarray(w1)
    with np.errstate(divide="ignore"):
        lam = np.log(w1a / (1.0 - w1a)) if len(w1a) else w1a
    slope = intercept = None
    if len(is1) >= 2 and np.ptp(is1) > 0:
        slope, intercept = (float(x) for x in np.polyfit(np.asarray(is1), np.asarray(oos1), 1))
    return {"mode": mode, "splits": nsp, "splits_with_candidate": len(w1), "systems": int(pool.shape[0]),
            "pbo": float((lam <= 0).mean()) if len(lam) else None,
            "median_omega_rank1": float(np.median(w1a)) if len(w1a) else None,
            "mean_omega_top10": float(np.mean(w10)) if w10 else None,
            "slope_oos_on_is": slope, "intercept": intercept, "anchor_moved": moved,
            "rank1_names": {nm: top1.count(nm) for nm in sorted(set(top1))},
            "per_split": {"omega_rank1": w1, "mean_omega_top10": w10, "is_rank1": is1, "oos_rank1": oos1}}
