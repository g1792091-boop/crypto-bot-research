"""After PREREG9 (a read, not a test; the owners asked 10/24 night "추세가 이상한 거야, 진입 타점이 이상한 거야?"): every signal of the
owners' manual style (frmanual2 M: 15m friend signal, 1h OR 4h ROC9, 35x, screen +10 % / -20 %, entry blocks), each taken alone
(no one-position pass), split into
  1. direction: the price move with the trade's side 15 min, 1 h, 4 h and 24 h after the entry (before fees), and the share that went
     the trade's way; the same signals with the side flipped as the control;
  2. the bracket: the win rate of +10 % / -20 % with the real side against the flipped side (a driftless price touches +a before -2a
     two times in three);
  3. timing: of the stopped trades, the share whose price came back to the take-profit level within 4 h after the stop (the side was
     right, the entry or the stop too early), against the flipped side;
  4. the fees inside the screen's +10 %.

    python3 -I frwhy.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frloss import PER, COST
from frfamily import signals
from frmanual2 import walk_bracket, LEV, TP, SL

PERIODS = {"2020 ~ 2024": PER["select"], "2025 ~ 2026": PER["confirm"], "10월": PER["oct2026"]}
HORIZONS = {"15분": 15, "1시간": 60, "4시간": 240, "24시간": 1440}


def main():
    A = signals("15m")
    R = A[A.block == ""].reset_index(drop=True)
    t = R.t.to_numpy(np.int64)
    side = R.side.to_numpy()
    fwd = {h: np.full(len(R), np.nan) for h in HORIZONS}
    res = {s_: {"r": np.zeros(len(R)), "k": np.zeros(len(R), np.int64)} for s_ in ("own", "flip")}
    back = np.zeros(len(R), bool)
    for ci in range(6):
        g = grid(COINS[ci])
        cumf = np.cumsum(g["fund"])
        o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
        m = (R.coin == ci).to_numpy()
        e = R.e.to_numpy(np.int64)[m]
        for hn, mins in HORIZONS.items():
            j = np.minimum(e + mins - 1, g["n"] - 1)
            fwd[hn][m] = side[m] * (c[j] / o[e] - 1)
        for sn, sg in (("own", 1), ("flip", -1)):
            for sd in (1, -1):
                mm = m & (side * sg == sd)
                if mm.any():
                    rr, kk = walk_bracket(o, h, l, c, cumf, R.e.to_numpy(np.int64)[mm], sd, LEV, COST, TP, SL, True, g["n"])
                    res[sn]["r"][mm], res[sn]["k"][mm] = rr, kk
        # stopped own-side trades: back to the take-profit price within 4 h after the stop
        for q in np.flatnonzero(m):
            if LEV * res["own"]["r"][q] > 0:
                continue
            e0, s0 = int(R.e.iat[q]), int(side[q])
            x = e0 + int(res["own"]["k"][q]) + 1
            seg = slice(x, min(g["n"], x + 240))
            if seg.start >= seg.stop:
                continue
            best = (h[seg] / o[e0] - 1).max() if s0 > 0 else (1 - l[seg] / o[e0]).max()
            back[q] = best >= TP / LEV
    for pn, (a, z) in PERIODS.items():
        m = (t >= a) & (t < z)
        win_own = (LEV * res["own"]["r"][m] > 0).mean()
        win_flip = (LEV * res["flip"]["r"][m] > 0).mean()
        print(f"== {pn}: signals {int(m.sum())}")
        print(f"   bracket +10/-20 win rate: real side {win_own:.1%} | flipped side {win_flip:.1%} | driftless 66.7%")
        for hn in HORIZONS:
            v = fwd[hn][m] * 100
            print(f"   {hn:4s} after entry: mean with the side {np.nanmean(v):+.3f}% | went the trade's way {np.mean(v > 0):.1%}")
        lost = m & (LEV * res["own"]["r"] <= 0)
        print(f"   stopped {int(lost.sum())}: price reached the take-profit level within 4 h after the stop {back[lost].mean():.1%}")
    fee = LEV * COST * 100
    print(f"fees: round trip {COST * 100:.3f}% x {LEV:.0f} = {fee:.2f}% of the screen's +10 % ({fee / 10:.0%}); stop -20 % becomes {-20 - fee:.2f}%")


if __name__ == "__main__":
    main()
