"""Verifier: re-walk w35 and a2 at the WOO X Pro MEASURED cost (fee 4.21 + slippage 4.37 = 8.58 bp per side, from
analysis/review1024/costs/REPORT_KO.md, 11-12 live trades) -> 0.1716 % round trip; saved as variant 'xw' in the same
walk_<coin>.npz files (adds keys)."""
import os, sys, json, time
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O
from oscore import *
from frdeep import walk3
from frloss import walk2
VC = "/dev/shm/claude_verify_cost"
CW = 2 * 0.000858


def run(coin):
    G = RD._grid(coin); g = grid(coin); n = g["n"]
    o, h, l, c = g["o"], g["h"], g["l"], g["c"]; cumf = np.cumsum(g["fund"])
    W = dict(np.load(os.path.join(VC, f"walk_{coin}.npz")))
    valid = W["valid15"]; e = (np.arange(len(valid), dtype=np.int64) + 1) * 15; ev = e[valid]; flag = np.zeros(1, bool)
    for lab, s in (("L", 1), ("S", -1)):
        a = walk3(o, h, l, c, cumf, ev, s, 35.0, CW, FL, STEP, GAP, -0.50, 9.0, 0.01, 0, flag, False, c, o, 0.0, n)
        r = np.full(len(valid), np.nan, np.float32); k = np.full(len(valid), -1, np.int32); w = np.full(len(valid), -1, np.int8)
        r[valid], k[valid], w[valid] = a[0], a[1], a[2]
        W[f"w35xw_{lab}_r"], W[f"w35xw_{lab}_k"], W[f"w35xw_{lab}_w"] = r, k, w
    for tf in ("15m", "30m", "1h"):
        kk = TF_MIN[tf]; nb = n // kk; jt = np.arange(nb, dtype=np.int64); et = (jt + 1) * kk
        vt = (jt * kk >= g["first"]) & (et < n)
        atr = G[f"atr14_{tf}"]; atr = atr[:nb] if len(atr) >= nb else np.r_[atr, np.full(nb - len(atr), np.nan)]
        ok = vt & np.isfinite(atr); es = et[ok]; atrd = np.ascontiguousarray(2.0 * atr[ok] / o[es])
        for lab, s in (("L", 1), ("S", -1)):
            a = walk2(o, h, l, c, cumf, es, s, 30.0, CW, FL, STEP, GAP, atrd, -1.0, n)
            r = np.full(nb, np.nan, np.float32); k = np.full(nb, -1, np.int32); w = np.full(nb, -1, np.int8)
            r[ok], k[ok], w[ok] = a[0], a[1], a[2]
            W[f"a2xw_{tf}_{lab}_r"], W[f"a2xw_{tf}_{lab}_k"], W[f"a2xw_{tf}_{lab}_w"] = r, k, w
    np.savez(os.path.join(VC, f"walk_{coin}.npz"), **W)
    drop(coin); RD._GR.pop(coin, None)
    log(coin, "xw done")
    return coin


if __name__ == "__main__":
    from multiprocessing import get_context
    with get_context("fork").Pool(2) as pool:
        list(pool.imap_unordered(run, list(O.COINS)))
