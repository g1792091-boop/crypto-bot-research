"""frfinal2's live rule (original friend signal, 35x, net ROE -50 % stop, ladder 10 / 5, margin 40 %) with and without the TetherMax
payback, over 9/1 .. 10/23, October and the last 19 days (a read for the bot guide; the paper bot itself never adds the payback).

    python3 -I frfinal2_pb.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import take, rnd
from frloss import PER, FL
from frfamily import signals
from frmanual2 import LEV, REFUND
from frladder35 import outcomes

WIN = {"9/1 ~ 10/23": (ms("2026-09-01") - KST, PER["oct2026"][1]), "10월": PER["oct2026"], "19일": PER["last19"]}


def main():
    A = signals("15m")
    R = A[A.block == ""].reset_index(drop=True)
    R = R[R.t.to_numpy(np.int64) >= ms("2026-08-20") - KST].reset_index(drop=True)
    O = outcomes(R, -0.50, FL)
    t = R.t.to_numpy(np.int64)
    out = {}
    for wn, (a, z) in WIN.items():
        idx = take(t, O["k"], (t >= a) & (t < z))
        for pn, rf in (("페이백 포함", REFUND), ("페이백 없음", 0.0)):
            roe = LEV * O["r"][idx] + rf
            eq = np.cumprod(1 + np.maximum(0.4 * roe, -1.0))
            dd = float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min())
            w, lo = roe[roe > 0], roe[roe <= 0]
            out[(wn, pn)] = (len(idx), (roe > 0).mean(), roe.mean() * 100, w.sum() / -lo.sum() if len(lo) else None, eq[-1], dd, int((O["why"][idx] == 0).sum()))
            print(f"{wn:12s} {pn:6s} n{len(idx)} win {(roe > 0).mean():.3f} roe/trade {roe.mean() * 100:+.2f}% PF {w.sum() / -lo.sum():.2f} "
                  f"x40 {eq[-1]:.3f} maxdd {dd:+.3f} stops {int((O['why'][idx] == 0).sum())}", flush=True)


if __name__ == "__main__":
    main()
