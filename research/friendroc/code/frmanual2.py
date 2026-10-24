"""PREREG8.md: the owners' manual style (M): the friend's 15m signal with the 1h OR 4h confirmation (P), 35x, a resting take-profit at
the screen's +10 % ROE and a resting stop at the screen's -20 % ROE (both before fees: price +10 % / 35 and -20 % / 35 from the
entry), one position, margin 40 %; six coins and DOGE only, with and without the bots' entry blocks; when one 1m bar touches both,
the stop first (and, for reference, the take-profit first); the TetherMax payback 90 % added per trade.

    python3 -I frmanual2.py       -> research/friendroc/results12.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import take, rnd
from frloss import PER, COST
from frfamily import signals
from frp30 import weekdays
import hashlib

LEV = 35.0
TP, SL = 0.10, -0.20                                       # screen ROE before fees
TAKER = 0.00042
REFUND = LEV * 2 * TAKER * 0.9


@numba.njit
def walk_bracket(o, h, l, c, cumf, es, s, lev, cost, tp, sl, stop_first, n):
    m = len(es)
    ret = np.zeros(m)
    kk = np.zeros(m, np.int64)
    for q in range(m):
        e = es[q]
        p0 = o[e]
        f0 = cumf[e - 1]
        up_l, dn_l = tp / lev, sl / lev
        k = 0
        while True:
            i = e + k
            if i >= n:
                i = n - 1
                ret[q] = s * (c[i] / p0 - 1.0) - cost - s * (cumf[i] - f0)
                kk[q] = i - e
                break
            F = s * (cumf[i] - f0)
            if s > 0:
                up = h[i] / p0 - 1.0
                dn = l[i] / p0 - 1.0
            else:
                up = 1.0 - l[i] / p0
                dn = 1.0 - h[i] / p0
            op = s * (o[i] / p0 - 1.0)
            hit_dn = dn <= dn_l
            hit_up = up >= up_l
            if hit_dn and (stop_first or not hit_up or op <= dn_l):
                ret[q] = (dn_l if dn_l < op else op) - cost - F
                kk[q] = k
                break
            if hit_up:
                ret[q] = (up_l if up_l > op else op) - cost - F
                kk[q] = k
                break
            k += 1
        if ret[q] < -1.0 / lev:
            ret[q] = -1.0 / lev
    return ret, kk


def run(R, stop_first):
    r = np.zeros(len(R)); k = np.zeros(len(R), np.int64)
    for ci in range(6):
        g = grid(COINS[ci])
        cumf = np.cumsum(g["fund"])
        o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
        for side in (1, -1):
            m = ((R.coin == ci) & (R.side == side)).to_numpy()
            if m.any():
                r[m], k[m] = walk_bracket(o, h, l, c, cumf, R.e.to_numpy(np.int64)[m], side, LEV, COST, TP, SL, stop_first, g["n"])
    return r, k


def read(t, k, r, use):
    out = {}
    for pn, (a, z) in PER.items():
        idx = take(t, k, use & (t >= a) & (t < z))
        roe0 = LEV * r[idx]
        roe = roe0 + REFUND
        w, lo = roe[roe > 0], roe[roe <= 0]
        x = np.maximum(0.4 * roe, -1.0)
        eq = np.cumprod(1 + x)
        out[pn] = {"n": int(len(idx)), "per_weekday": rnd(len(idx) / weekdays(a, z), 2), "win": rnd((roe > 0).mean(), 4),
                   "avg_win_pct": rnd(w.mean() * 100, 1), "avg_loss_pct": rnd(lo.mean() * 100, 1),
                   "breakeven_win": rnd(-lo.mean() / (w.mean() - lo.mean()), 3) if len(w) and len(lo) else None,
                   "roe_pct": rnd(roe.mean() * 100, 2), "roe_pct_no_payback": rnd(roe0.mean() * 100, 2),
                   "mult40": rnd(eq[-1], 4), "maxdd40": rnd(float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()), 3)}
    # months from 1 and the 90-day goal (margin 40 %)
    idx = take(t, k, use & (t >= ms("2020-03-01")))
    roe = LEV * r[idx] + REFUND
    tt = t[idx]
    mon = np.asarray(pd.to_datetime(tt + KST, unit="ms").strftime("%Y-%m"))
    x = np.maximum(0.4 * roe, -1.0)
    v = np.array([np.prod(1 + x[mon == q]) for q in pd.period_range("2020-03", "2026-09", freq="M").strftime("%Y-%m")])
    v25 = v[-21:]
    out["months"] = {"median_all": rnd(np.median(v), 3), "up_all": int((v > 1).sum()), "n_all": len(v),
                     "median_2025": rnd(np.median(v25), 3), "up_2025": int((v25 > 1).sum()), "x2_all": int((v >= 2).sum()), "x4_all": int((v >= 4).sum())}
    lg = np.log(np.maximum(1 + 0.4 * roe, 1e-9)); cs = np.r_[0, np.cumsum(lg)]
    hits = {51: 0, 10: 0, 4: 0}; ruin = n = 0
    for s in range(0, len(idx), 3):
        if tt[s] + 90 * DAY > ms("2026-10-23"):
            break
        e = np.searchsorted(tt, tt[s] + 90 * DAY)
        path = cs[s + 1:e + 1] - cs[s]
        if not len(path):
            continue
        n += 1
        for xx in hits:
            hits[xx] += int(path.max() >= np.log(xx))
        ruin += int(path.min() <= np.log(0.1))
    out["goal90"] = {f"x{xx}": rnd(vv / n, 4) for xx, vv in hits.items()} | {"to_10pct_or_less": rnd(ruin / n, 3), "starts": n}
    return out


def main():
    want = open(os.path.join(RES_DIR, "PREREG8.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG8.md"), "rb").read()).hexdigest()
    assert sha == want, "PREREG8.md changed after it was frozen"
    A = signals("15m")
    res = {"prereg8_sha256": sha, "refund_net_roe_pct": rnd(REFUND * 100, 3)}
    for blocks in (True, False):
        R = (A[A.block == ""] if blocks else A).reset_index(drop=True)
        t = R.t.to_numpy(np.int64)
        for stop_first in (True, False):
            r, k = run(R, stop_first)
            for coins in ("6코인", "도지만"):
                use = np.ones(len(R), bool) if coins == "6코인" else (R.coin == COINS.index("DOGEUSDT")).to_numpy()
                key = f"{coins} · 진입 금지 {'있음' if blocks else '없음'} · {'손절 먼저' if stop_first else '익절 먼저'}"
                d = read(t, k, r, use)
                res[key] = d
                print(f"{key}", " | ".join(f"{p[:4]} n{v['n']} {v['per_weekday']}/d w{v['win']} be{v['breakeven_win']} aw{v['avg_win_pct']} al{v['avg_loss_pct']} "
                                          f"roe{v['roe_pct']} (no pb {v['roe_pct_no_payback']}) x40 {v['mult40']}" for p, v in d.items() if p in PER),
                      "| months", d["months"], "| goal90", d["goal90"], flush=True)
    base = res["6코인 · 진입 금지 있음 · 손절 먼저"]
    res["verdict"] = "과거 기록상 버는 방식" if base["select"]["roe_pct"] > 0 and base["confirm"]["roe_pct"] > 0 else "과거 기록상 잃는 방식"
    print("verdict", res["verdict"], flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results12.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
