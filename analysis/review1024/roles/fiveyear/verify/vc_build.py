"""Cost / executability / overlap verifier, step 1: per coin, the 15m and 30m entry-role signals (as stack.py) with
the 1h judge votes (V4OF4) and the 4h / 1d held judge (DIR), plus walk3 outcomes recomputed from the raw 1m grid under
several cost / delay variants:

  base   0.062 % per side (taker 0.042 + slippage 0.02), entry at the open of the bar-close minute (the study's)
  woo    0.0858 % per side (WOO X Pro measured live: fee 4.21 bp + slippage 4.37 bp, other/REPORT_KO.md 4-2)
  x2     0.124 % per side (doubled cost)
  d1     base cost, entry one minute later (live executors lag ~75 s)
  d2     base cost, entry two minutes later

Output: /dev/shm/claude_vc/<tf>.parquet-like npz (RAM scratch).   python3 vc_build.py   (run from this folder, no -I)"""
import os
import sys
import time

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import numpy as np
import pandas as pd
import rolesdata as RD                                   # noqa: E402
from common import (COINS, COST, MIN, T0, GRID_END, FL, STEP, GAP, grid, drop, ms, last_closed, TF_MIN)  # noqa: E402
from frdeep import walk3                                 # noqa: E402

OUTD = "/dev/shm/claude_vc"
os.makedirs(OUTD, exist_ok=True)
ENTRY_ROLES = ["range", "pullback", "breakout", "reversal", "timing", "other"]
E0, E_END = ms("2021-01-01"), ms("2026-10-24 15:00")
VAR = {"base": (COST, 0), "woo": (2 * 0.000858, 0), "x2": (2 * COST, 0), "d1": (COST, 1), "d2": (COST, 2)}


def judge(S, htf):
    idx = RD.htf_index(S, htf)
    v4 = np.zeros(len(S), np.int8)
    d = np.zeros(len(S), np.int8)
    warm = np.zeros(len(S), bool)
    for ci, coin in enumerate(COINS):
        m = (S.coin.to_numpy() == ci) & (idx >= 1)
        if not m.any():
            continue
        Z = RD._states(coin, htf)
        ii = idx[m]
        warm[m] = Z["nb"][ii] >= 300
        v = (Z["j_V39"].astype(np.int16)[ii] + Z["j_S6"].astype(np.int16)[ii] + Z["j_OBV"].astype(np.int16)[ii]
             + Z["j_N12"].astype(np.int16)[ii])
        v4[m] = np.where(np.abs(v) == 4, np.sign(v), 0)
        d[m] = Z["j_dir"][ii].astype(np.int8)
    return v4, d, warm


def walks(coin, ent):
    """walk3 outcomes for the unique 15m-grid entry minutes `ent` (both sides) under every variant."""
    g = grid(coin)
    n = g["n"]
    o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
    cumf = np.cumsum(g["fund"])
    dummy = np.zeros(1, bool)
    out = {}
    for vn, (cost, dl) in VAR.items():
        es = (ent + dl).astype(np.int64)
        ok = es < n - 1
        for sn, s in (("L", 1), ("S", -1)):
            r = np.full(len(ent), np.nan)
            k = np.full(len(ent), -1, np.int64)
            w = np.full(len(ent), -1, np.int8)
            a = walk3(o, h, l, c, cumf, es[ok], s, 35.0, cost, FL, STEP, GAP, -0.50, 9.0, 0.01, 0, dummy, False, c, o,
                      0.0, n)
            r[ok], k[ok], w[ok] = a[0], a[1], a[2]
            out[(vn, sn)] = (r, k, w)
    drop(coin)
    return out


def main():
    t0 = time.time()
    for tf in ("15m", "30m"):
        parts = []
        for ci, coin in enumerate(COINS):
            S = RD.signals(roles_=ENTRY_ROLES, tfs=[tf], coins=[coin], period=(E0, E_END))
            S = RD.add_outcomes(S, ["w35"])
            S = S[(S.w35_why != 3) & (S.w35_opp_why != 3) & np.isfinite(S.w35_r)]
            S = S[["t", "e", "coin", "side", "sid", "w35_roe", "w35_opp_roe", "w35_k"]].reset_index(drop=True)
            S["tf"] = tf
            a, _, wa = judge(S, "1h")
            _, b, wb = judge(S, "4h")
            _, c_, wc = judge(S, "1d")
            S["v4_1h"], S["dir_4h"], S["dir_1d"] = a, b, c_
            S = S[wa & wb & wc].reset_index(drop=True)
            ent = np.unique(S.e.to_numpy(np.int64))
            W = walks(coin, ent)
            pos = np.searchsorted(ent, S.e.to_numpy(np.int64))
            side = S.side.to_numpy()
            for vn in VAR:
                for lab, sg in (("", 1), ("_opp", -1)):
                    rL, kL, wL = W[(vn, "L")]
                    rS, kS, wS = W[(vn, "S")]
                    lng = side * sg > 0
                    r = np.where(lng, rL[pos], rS[pos])
                    k = np.where(lng, kL[pos], kS[pos])
                    w = np.where(lng, wL[pos], wS[pos])
                    S[f"{vn}{lab}_roe"] = np.maximum(35.0 * r, -1.0)
                    S[f"{vn}{lab}_k"] = k
                    S[f"{vn}{lab}_why"] = w
            # check: the recomputed base walk equals the grid
            dif = np.nanmax(np.abs(S.base_roe.to_numpy() - S.w35_roe.to_numpy()))
            kd = int((S.base_k.to_numpy() != S.w35_k.to_numpy()).sum())
            print(time.strftime("%H:%M:%S"), tf, coin, len(S), "max|base-grid| roe", f"{dif:.2e}", "k diffs", kd,
                  f"{time.time() - t0:.0f}s", flush=True)
            parts.append(S)
            RD._GR.pop(coin, None)
            RD._SIG.pop(coin, None)
            for h in ("1h", "4h", "1d"):
                RD._STATES.pop((coin, h), None)
        S = pd.concat(parts, ignore_index=True)
        S.to_pickle(os.path.join(OUTD, f"{tf}.pkl"))
        print(tf, "saved", len(S), flush=True)


if __name__ == "__main__":
    main()
