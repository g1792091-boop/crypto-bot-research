"""After PREREG6 (not pre-registered; a read for the owners' goal of 10/24: "2~3개월에 5000% 이상"): for six structures and margins
20 / 40 / 60 / 100 %, starting at every third trade of 2020-03 .. 2026-10 and looking 90 days ahead with every profit compounded, how
often the account touched x51, x10, x4, how often it fell to 10 % or less, the median end and the best peak. TetherMax payback 90 %.

    python3 -I frrun.py build     (once)
    python3 -I frshort.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import take
from frfamily import signals, outcomes, filt
from frpay import mask, REFUND
from frmore import merged
from frloss import LEV
rf = REFUND["p90"]; a, z = ms("2020-03-01"), ms("2026-10-23")
S = {}
for tf in ("15m", "30m", "4h"):
    R = signals(tf); S[tf] = R[R.block == ""].reset_index(drop=True)
R15, R30, R4 = S["15m"], S["30m"], S["4h"]
def run(R, st, fl, step, use):
    O = outcomes(R, st, fl, step)["own"]
    return R.t.to_numpy(np.int64)[use], O["k"][use], O["r"][use]
O15 = outcomes(R15, -0.75, 0.20, 0.10)["own"]; O30 = outcomes(R30, -0.75, 0.20, 0.10)["own"]; O4 = outcomes(R4, -0.5, 0.10, 0.05)["own"]
cands = {
 "P 친구 그대로": run(R15, -0.5, 0.10, 0.05, np.ones(len(R15), bool)),
 "필터 + 친구 청산": run(R15, -0.5, 0.10, 0.05, mask(R15, "F4+V")),
 "필터 + -75 20/10": run(R15, -0.75, 0.20, 0.10, mask(R15, "F4+V")),
 "필터 + -50 30/10": run(R15, -0.5, 0.30, 0.10, mask(R15, "F4+V")),
 "15+30+4h 합침": merged([(R15, O15, mask(R15, "F4+V")), (R30, O30, mask(R30, "F4+V")), (R4, O4, filt(R4, "F4"))]),
 "4h + ADX": run(R4, -0.5, 0.10, 0.05, filt(R4, "F4")),
}
for nm, (t, k, r) in cands.items():
    m = (t >= a) & (t < z)
    idx = take(t, k, m)
    roe = LEV * r[idx] + rf; tt = t[idx]
    for mg in (0.2, 0.4, 0.6, 1.0):
        lg = np.log(np.maximum(1 + mg * roe, 1e-9)); cs = np.r_[0, np.cumsum(lg)]
        hits = {51: 0, 10: 0, 4: 0}; ruin = 0; ends = []; best = 0; n = 0
        for s in range(0, len(idx), 3):
            e = np.searchsorted(tt, tt[s] + 90 * DAY)
            if tt[s] + 90 * DAY > z: break
            path = cs[s + 1:e + 1] - cs[s]
            if not len(path): continue
            n += 1; mx = path.max()
            for x in hits:
                if mx >= np.log(x): hits[x] += 1
            if path.min() <= np.log(0.1): ruin += 1
            ends.append(path[-1]); best = max(best, mx)
        ends = np.exp(np.array(ends))
        print(f"{nm:14s} m{int(mg*100):3d}% ({n} starts, 90 days): touch x51 {hits[51]/n:.2%} | x10 {hits[10]/n:.1%} | x4 {hits[4]/n:.1%} | "
              f"fell to 10% or less {ruin/n:.0%} | end median x{np.median(ends):.2f} | best peak x{np.exp(best):.1f}")
