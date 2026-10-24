"""The owners' ask of 10/24 night: leverage 20 / 30 / 40 x net ROE stop -10 .. -70 %, margin 40 %, the ladder (12 -> 10, then 5 % steps),
from 2026-01-01 to 10-22 (KST) and the last 19 days, for the three readings of the friend's higher-bar check (frytd.py: ① 1h or 4h
RSI26 + ROC9, ② 1h or 4h ROC9 = the bot, ③ 1h RSI26 + ROC9); one position, the entry blocks, the TetherMax payback 90 % at each
leverage (and without). A read, not a test.

    python3 -I frgrid26.py        -> research/friendroc/results24.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import take, rnd
from frloss import PER, COST, FL, STEP, GAP
from frdeep import walk3
from frhtrend import raw15
from frhtrend2 import add_rsi

TAKER = 0.00042
WIN = {"2026": (ms("2026-01-01") - KST, ms("2026-10-23") - KST), "19일": PER["last19"]}
LEVS = (20, 30, 40)
STOPS = (-0.10, -0.20, -0.30, -0.40, -0.50, -0.60, -0.70)


def walk(R, lev, stop):
    bt = grid("BTCUSDT")
    bc_, bo_ = (np.ascontiguousarray(bt[x], dtype=np.float64) for x in ("c", "o"))
    r = np.zeros(len(R)); k = np.zeros(len(R), np.int64)
    for ci in range(6):
        g = grid(COINS[ci])
        cumf = np.cumsum(g["fund"])
        o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
        for side in (1, -1):
            m = ((R.coin == ci) & (R.side == side)).to_numpy()
            if m.any():
                a = walk3(o, h, l, c, cumf, R.e.to_numpy(np.int64)[m], side, float(lev), COST, FL, STEP, GAP, stop, 9.0, 0.0, 0,
                          np.zeros(1, bool), False, bc_, bo_, 0.0, g["n"])
                r[m], k[m] = a[0], a[1]
    return r, k


def stats(roe):
    if not len(roe):
        return {"n": 0}
    eq = np.cumprod(1 + np.maximum(0.4 * roe, -1.0))
    w, lo = roe[roe > 0], roe[roe <= 0]
    return {"n": int(len(roe)), "win": rnd(float((roe > 0).mean()), 3), "roe_pct": rnd(float(roe.mean() * 100), 2),
            "pf": rnd(float(w.sum() / -lo.sum()), 3) if len(lo) and lo.sum() < 0 else None, "mult40": rnd(float(eq[-1]), 4),
            "maxdd40": rnd(float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()), 3)}


def main():
    B = add_rsi(pd.concat([raw15(c) for c in COINS], ignore_index=True))
    B = B[B.t.to_numpy(np.int64) >= ms("2025-12-01") - KST]
    B = B.iloc[np.lexsort((B.coin.to_numpy(), B.t.to_numpy()))].reset_index(drop=True)
    B["block"] = [blocked(int(x)) for x in B.t.to_numpy()]
    B = B[B.block == ""].reset_index(drop=True)
    with np.errstate(invalid="ignore"):
        g = {k: B[k].to_numpy() > 0 for k in ("roc_1h", "roc_4h", "rsi_1h", "rsi_4h")}
    rules = {"①": (g["rsi_1h"] & g["roc_1h"]) | (g["rsi_4h"] & g["roc_4h"]), "②": g["roc_1h"] | g["roc_4h"],
             "③": g["rsi_1h"] & g["roc_1h"]}
    t = B.t.to_numpy(np.int64)
    rows = []
    for lev in LEVS:
        refund = lev * 2 * TAKER * 0.9
        for stop in STOPS:
            r, k = walk(B, lev, stop)
            for rn, m in rules.items():
                row = {"rule": rn, "lev": lev, "stop": stop}
                for wn, (a, z) in WIN.items():
                    idx = take(t, k, m & (t >= a) & (t < z))
                    roe = lev * r[idx]
                    row[wn] = stats(roe + refund)
                    row[wn + " 페이백 없음"] = stats(roe)
                rows.append(row)
                y, n19 = row["2026"], row["19일"]
                print(f"{rn} {lev}x stop {int(stop * 100):4d} | 2026 n{y['n']} w{y['win']} roe{y['roe_pct']} pf{y['pf']} x{y['mult40']} dd{y['maxdd40']} "
                      f"(no pb x{row['2026 페이백 없음']['mult40']}) | 19d n{n19['n']} w{n19['win']} roe{n19['roe_pct']} x{n19['mult40']} dd{n19['maxdd40']}",
                      flush=True)
    json.dump(rows, open(os.path.join(RES_DIR, "results24.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
