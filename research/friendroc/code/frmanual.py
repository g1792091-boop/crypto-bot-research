"""After PREREG7 (not pre-registered; a read for the owners' manual trades of 10/24): their three DOGE trades on WOO X Pro (fills equal
Binance's 1m prices to a tick) were entries at a 15m close (or three minutes before it) where ROC9 crossed 0 with the 1h OR the 4h bar
agreeing, closed at the exchange screen's +10 % ROE (before fees) at about 35x. This replays that style: the friend's rule with the
1h-or-4h confirmation (P, frfamily.signals("15m")), a fixed take-profit at +10 % ROE before fees (price +10 % / leverage), the net ROE
-50 % stop, one position; 40x (the owners' figure) and 35x (what the history shows); with and without the bots' entry blocks;
six coins and DOGE only; the TetherMax payback 90 % added per trade.

    python3 -I frmanual.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import take, rnd
from frloss import PER, COST
from frfamily import signals
from frp30 import weekdays

TAKER = 0.00042


@numba.njit
def walk_tp(o, h, l, c, cumf, es, s, lev, cost, tp_gross, roe_stop, n):
    """Fixed take-profit at a price move of tp_gross / lev (the exchange's ROE before fees), the net ROE stop (frcore.walk's level);
    within one minute the stop is taken first (the high / low order is unknown). Returns net price return and exit offset."""
    m = len(es)
    ret = np.zeros(m)
    kk = np.zeros(m, np.int64)
    for q in range(m):
        e = es[q]
        p0 = o[e]
        f0 = cumf[e - 1]
        tpl = tp_gross / lev
        k = 0
        while True:
            i = e + k
            if i >= n:
                i = n - 1
                ret[q] = s * (c[i] / p0 - 1.0) - cost - s * (cumf[i] - f0)
                kk[q] = i - e
                break
            Fp = s * (cumf[i - 1] - f0)
            F = s * (cumf[i] - f0)
            level = roe_stop / lev + cost + Fp
            if s > 0:
                up = h[i] / p0 - 1.0
                dn = l[i] / p0 - 1.0
            else:
                up = 1.0 - l[i] / p0
                dn = 1.0 - h[i] / p0
            op = s * (o[i] / p0 - 1.0)
            if dn <= level:
                fill = level if level < op else op
                ret[q] = fill - cost - F
                kk[q] = k
                break
            if up >= tpl:
                fill = tpl if tpl > op else op
                ret[q] = fill - cost - F
                kk[q] = k
                break
            k += 1
        if ret[q] < -1.0 / lev:
            ret[q] = -1.0 / lev
    return ret, kk


def run(R, lev):
    r = np.zeros(len(R)); k = np.zeros(len(R), np.int64)
    for ci in range(6):
        g = grid(COINS[ci])
        cumf = np.cumsum(g["fund"])
        o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
        for side in (1, -1):
            m = ((R.coin == ci) & (R.side == side)).to_numpy()
            if m.any():
                r[m], k[m] = walk_tp(o, h, l, c, cumf, R.e.to_numpy(np.int64)[m], side, lev, COST, 0.10, -0.5, g["n"])
    return r, k


def main():
    A = signals("15m")
    out = {}
    for blocks in (True, False):
        R = A[A.block == ""].reset_index(drop=True) if blocks else A.reset_index(drop=True)
        t = R.t.to_numpy(np.int64)
        for lev in (40.0, 35.0):
            r, k = run(R, lev)
            refund = lev * 2 * TAKER * 0.9
            for coins in ("6", "DOGE"):
                use = np.ones(len(R), bool) if coins == "6" else (R.coin == COINS.index("DOGEUSDT")).to_numpy()
                key = f"{'blocks' if blocks else 'no blocks'} {int(lev)}x {coins}"
                row = {}
                for pn, (a, z) in PER.items():
                    idx = take(t, k, use & (t >= a) & (t < z))
                    roe = lev * r[idx] + refund
                    x = np.maximum(0.4 * roe, -1.0)
                    row[pn] = {"n": int(len(idx)), "per_weekday": rnd(len(idx) / weekdays(a, z), 2), "win": rnd((roe > 0).mean(), 4),
                               "avg_win_pct": rnd(roe[roe > 0].mean() * 100, 1), "avg_loss_pct": rnd(roe[roe <= 0].mean() * 100, 1),
                               "roe_pct": rnd(roe.mean() * 100, 2), "roe_pct_no_payback": rnd((roe - refund).mean() * 100, 2),
                               "mult40": rnd(float(np.prod(1 + x)), 4)}
                out[key] = row
                print(f"{key:20s}", " | ".join(f"{p[:4]} n{v['n']} {v['per_weekday']}/d w{v['win']} aw{v['avg_win_pct']} al{v['avg_loss_pct']} "
                                              f"roe{v['roe_pct']} (no pb {v['roe_pct_no_payback']}) x40 {v['mult40']}" for p, v in row.items()), flush=True)
    json.dump(out, open(os.path.join(RES_DIR, "results11.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
