"""Verifier (lens: costs, executability, overlap) for the claim on OBV20@4h > RSI14 30/70 cross @1h | a2.

Independent re-derivation from the 1m grid (common.grid = Binance USDT-M 1m + published funding):
  - own 1h / 4h bars, own OBV (+ SMA20), own Wilder RSI14, own Wilder ATR14
  - signal at a 1h close: RSI crosses up 30 -> long, crosses down 70 -> short; taken only when the OBV20 state of the
    last CLOSED 4h bar (close <= 1h close) has the same sign. Warm-up: 300 bars on each timeframe.
  - own numba walk of the a2 exit (2 x ATR14 of the signal bar, 30x, ladder +12 -> +10 then every 5 %, -100 % floor)
Variants (each a full re-walk): cost x1 / x2 / x3, funding on / off, entry 0 / 1 / 2 minutes late,
liquidation earlier than the -100 % floor (isolated 30x: distance 1/30 - MMR; MMR 0.5 % BTC/ETH, 1 % others, or all 1 %).
Writes rows_<variant>.csv.gz (one row per signal) and prints a summary. Run from this folder without -I:
    python3 vcell.py
"""
import os
import sys
import json

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import *            # noqa: E402,F401,F403
import numba                     # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LEV = 30.0
BASE_COST = 2 * (0.00042 + 0.0002)
PB = 2 * 0.9 * 0.00042
MMR_REAL = {"BTCUSDT": 0.005, "ETHUSDT": 0.005, "SOLUSDT": 0.01, "DOGEUSDT": 0.01, "LTCUSDT": 0.01, "BCHUSDT": 0.01}


def my_bars(g, k):
    n = g["n"] // k * k
    o = g["o"][:n:k]
    c = g["c"][k - 1:n:k]
    h = g["h"][:n].reshape(-1, k).max(1)
    lo = g["l"][:n].reshape(-1, k).min(1)
    v = g["v"][:n].reshape(-1, k).sum(1)
    j = np.arange(n // k, dtype=np.int64)
    ok = j * k >= g["first"]
    return j[ok], o[ok], h[ok], lo[ok], c[ok], v[ok]


def rma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    a = np.mean(x[:n])
    out[n - 1] = a
    for i in range(n, len(x)):
        a = (a * (n - 1) + x[i]) / n
        out[i] = a
    return out


def my_rsi(c, n=14):
    d = np.diff(c)
    up = np.maximum(d, 0.0)
    dn = np.maximum(-d, 0.0)
    ru, rd = rma(up, n), rma(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(rd == 0, 100.0, np.where(ru == 0, 0.0, 100.0 - 100.0 / (1.0 + ru / rd)))
    r = np.where(np.isfinite(ru) & np.isfinite(rd), r, np.nan)
    return np.r_[np.nan, r]


def my_atr(h, l, c, n=14):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    tr = np.r_[h[0] - l[0], tr]
    return rma(tr, n)


def my_obv(c, v):
    s = np.sign(np.r_[0.0, np.diff(c)])
    return np.cumsum(s * v)


def sma(x, n):
    cs = np.cumsum(np.r_[0.0, x])
    out = np.full(len(x), np.nan)
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


@numba.njit
def lockf(best):
    if best < 0.12 - 1e-12:
        return np.nan
    return 0.10 + 0.05 * np.floor((best - 0.12) / 0.05 + 1e-9)


@numba.njit
def walk(o, h, l, c, cumf, es, side, stopd, cost, lev, liqd, use_f, n):
    """Own a2 walk. stopd gross ATR distance; liqd gross liquidation distance (0 = only the -100 % net floor).
    Returns net price return r (ROE = lev r, floored -1/lev), minutes k, why (0 stop, 1 lock, 2 liq, 3 open)."""
    m = len(es)
    R = np.zeros(m)
    K = np.zeros(m, np.int64)
    W = np.zeros(m, np.int8)
    for q in range(m):
        e = es[q]
        s = side[q]
        p0 = o[e]
        f0 = cumf[e - 1]
        best = -1e9
        lk = np.nan
        k = 0
        while True:
            i = e + k
            if i >= n:
                i = n - 1
                F = s * (cumf[i] - f0) * use_f
                R[q] = s * (c[i] / p0 - 1.0) - cost - F
                K[q] = i - e
                W[q] = 3
                break
            Fp = s * (cumf[i - 1] - f0) * use_f
            lvl = -1.0 / lev + cost + Fp          # -100 % net floor
            if -stopd[q] > lvl:
                lvl = -stopd[q]
            liq_lvl = -1e9
            if liqd > 0:
                liq_lvl = -liqd
            locked = not np.isnan(lk)
            if locked:
                lv = lk / lev + cost + Fp
                if lv > lvl:
                    lvl = lv
            if s > 0:
                up = h[i] / p0 - 1.0
                dn = l[i] / p0 - 1.0
            else:
                up = 1.0 - l[i] / p0
                dn = 1.0 - h[i] / p0
            op = s * (o[i] / p0 - 1.0)
            F = s * (cumf[i] - f0) * use_f
            if dn <= lvl or dn <= liq_lvl:
                if liq_lvl > lvl and dn <= liq_lvl:      # exchange liquidates before the stop / floor: margin gone
                    R[q] = -1.0 / lev
                    K[q] = k
                    W[q] = 2
                    break
                fill = lvl if lvl < op else op
                R[q] = fill - cost - F
                K[q] = k
                W[q] = 1 if locked else 0
                break
            ru = lev * (up - cost - F)
            if ru > best:
                best = ru
                lk = lockf(best)
            k += 1
        if R[q] < -1.0 / lev:
            R[q] = -1.0 / lev
    return R, K, W


def coin_signals(coin):
    g = grid(coin)
    j1, o1, h1, l1, c1, v1 = my_bars(g, 60)
    j4, o4, h4, l4, c4, v4 = my_bars(g, 240)
    rsi = my_rsi(c1)
    atr = my_atr(h1, l1, c1)
    ob = my_obv(c4, v4)
    st4 = np.sign(ob - sma(ob, 20))
    st4[np.arange(len(st4)) < 300] = 0
    st4 = np.nan_to_num(st4)
    lo = (np.r_[np.nan, rsi[:-1]] <= 30) & (rsi > 30)
    sh = (np.r_[np.nan, rsi[:-1]] >= 70) & (rsi < 70)
    sig = np.where(lo, 1, np.where(sh, -1, 0))
    sig[:300] = 0
    close1 = T0 + (j1 + 1) * 60 * MIN                 # 1h close time (ms)
    close4 = T0 + (j4 + 1) * 240 * MIN
    idx = np.searchsorted(close4, close1, side="right") - 1
    trend = np.where(idx >= 0, st4[np.clip(idx, 0, len(st4) - 1)], 0)
    e = (j1 + 1) * 60                                 # entry minute index (open of the minute at the 1h close)
    m = (sig != 0) & (trend == sig) & (e + 2 < g["n"]) & np.isfinite(atr)
    return {"t": close1[m], "e": e[m], "side": sig[m].astype(np.int64), "atrd_abs": 2.0 * atr[m],
            "trend_against_all": int(((sig != 0) & (trend == -sig)).sum())}


VARIANTS = {  # name: (cost multiplier, funding on, entry delay minutes, liquidation mode)
    "base": (1.0, 1.0, 0, None),
    "nofund": (1.0, 0.0, 0, None),
    "cost2": (2.0, 1.0, 0, None),
    "cost3": (3.0, 1.0, 0, None),
    "delay1": (1.0, 1.0, 1, None),
    "delay2": (1.0, 1.0, 2, None),
    "liqreal": (1.0, 1.0, 0, "real"),
    "liq1pct": (1.0, 1.0, 0, 0.01),
    "cost2_liqreal_delay1": (2.0, 1.0, 1, "real"),
}


def run_coin(coin):
    S = coin_signals(coin)
    g = grid(coin)
    cumf = np.cumsum(g["fund"])
    out = {}
    for vn, (cm, uf, dl, lq) in VARIANTS.items():
        for s_lab, s_mul in (("sig", 1), ("opp", -1)):
            es = (S["e"] + dl).astype(np.int64)
            side = (S["side"] * s_mul).astype(np.int64)
            stopd = S["atrd_abs"] / g["o"][es]
            if lq is None:
                liqd = 0.0
            elif lq == "real":
                liqd = 1.0 / LEV - MMR_REAL[coin]
            else:
                liqd = 1.0 / LEV - lq
            R, K, W = walk(g["o"], g["h"], g["l"], g["c"], cumf, es, side, np.ascontiguousarray(stopd),
                           BASE_COST * cm, LEV, liqd, uf, g["n"])
            out[(vn, s_lab)] = (R, K, W)
    rows = []
    for vn in VARIANTS:
        R, K, W = out[(vn, "sig")]
        Ro, Ko, Wo = out[(vn, "opp")]
        df = pd.DataFrame({"variant": vn, "coin": coin, "t": S["t"], "e": S["e"] + VARIANTS[vn][2], "side": S["side"],
                           "r": R, "k": K, "why": W, "r_opp": Ro, "why_opp": Wo,
                           "stopd": S["atrd_abs"] / g["o"][S["e"]]})
        rows.append(df)
    drop(coin)
    return pd.concat(rows, ignore_index=True)


if __name__ == "__main__":
    allr = []
    for coin in COINS:
        allr.append(run_coin(coin))
        log(coin, "done")
    A = pd.concat(allr, ignore_index=True)
    A.to_csv(os.path.join(HERE, "rows_all.csv.gz"), index=False)
    log("rows", len(A))
