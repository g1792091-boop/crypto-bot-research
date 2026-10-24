"""Adversarial re-derivation (look-ahead / time alignment / data lens) of the cell OBV30@4h > SRSI_X@1h | a2.

Independent of oscore.py: bars are rebuilt with pandas resample from the raw 1m grid, OBV / SMA30 / RSI / Stoch RSI /
ATR are coded here from their formulas, the higher-bar lookup is done with explicit timestamps, and the a2 exit is walked
with a vectorised formulation (not frloss.walk2). Variants of the time alignment are computed next to the correct one:
  ok      : 4h bar with close <= signal bar close (the study's rule)
  la      : the 4h bar that CONTAINS the signal bar (still forming; look-ahead)
  late    : one more 4h bar back (the bar before the last closed one)
Writes rows_<variant>.csv.gz (per signal) in this folder.

    python3 vrebuild.py
"""
import os
import sys
import json

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import grid, drop, ms, T0, MIN, DAY, COINS, COST, PAYBACK, GRID_END, ext_end  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LEV = 30.0
FL, STEP, GAP = 0.10, 0.05, 0.02
WARM = 300


def resample(g, rule):
    n = g["n"]
    idx = pd.to_datetime(T0 + np.arange(n, dtype=np.int64) * MIN, unit="ms", utc=True)
    df = pd.DataFrame({"o": g["o"], "h": g["h"], "l": g["l"], "c": g["c"], "v": g["v"]}, index=idx)
    df = df.iloc[g["first"]:]
    r = df.resample(rule, label="left", closed="left")
    out = pd.DataFrame({"open": r.o.first(), "high": r.h.max(), "low": r.l.min(), "close": r.c.last(),
                        "volume": r.v.sum(), "cnt": r.c.count()})
    k = {"1h": 60, "4h": 240}[rule]
    out = out[out.cnt == k]                               # whole bars only
    out["ts"] = out.index.view("int64") // 10**6
    out["close_ts"] = out.ts + k * MIN
    return out.reset_index(drop=True)


def sma(x, n):
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    cs = np.cumsum(np.r_[0.0, x])
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def wilder_seeded(x, n):
    """Pine rma: seeded with the SMA of the first n finite values."""
    out = np.full(len(x), np.nan)
    f = np.flatnonzero(np.isfinite(x))
    s = f[0] + n - 1
    out[s] = np.mean(x[f[0]:s + 1])
    for i in range(s + 1, len(x)):
        out[i] = out[i - 1] + (x[i] - out[i - 1]) / n
    return out


def rsi(c, n=14):
    d = np.r_[np.nan, np.diff(c)]
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    up[0] = dn[0] = np.nan
    au, ad = wilder_seeded(up, n), wilder_seeded(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(ad == 0, 100.0, np.where(au == 0, 0.0, 100 - 100 / (1 + au / ad)))
    return np.where(np.isfinite(au) & np.isfinite(ad), r, np.nan)


def stoch_rsi_k(c):
    r = rsi(c, 14)
    s = pd.Series(r)
    lo = s.rolling(14, min_periods=14).min().to_numpy()
    hi = s.rolling(14, min_periods=14).max().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.where(hi - lo != 0, 100 * (r - lo) / (hi - lo), 0.0)
    raw = np.where(np.isfinite(hi - lo), raw, np.nan)
    k = pd.Series(raw).rolling(3, min_periods=3).mean().to_numpy()
    return k


def atr_pandas_rma(df, n=14):
    """fg.atr semantics: TR (bar 0 = h - l), ewm(alpha 1/n, adjust False, min_periods n)."""
    h, l, c = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.c_[h - l, np.abs(h - pc), np.abs(l - pc)], axis=1)
    out = np.empty(len(tr))
    a = 1.0 / n
    out[0] = tr[0]
    for i in range(1, len(tr)):
        out[i] = (1 - a) * out[i - 1] + a * tr[i]
    out[: n - 1] = np.nan
    return out


def obv(c, v):
    d = np.r_[0.0, np.diff(c)]
    return np.cumsum(np.sign(d) * v)


def lock_of(best):
    ft = FL + GAP
    with np.errstate(invalid="ignore"):
        n = np.floor((best - ft) / STEP + 1e-9)
    return np.where(best >= ft - 1e-12, FL + STEP * n, np.nan)


def walk_vec(o, h, l, c, cumf, e, s, atrd, nmin, chunk=4000):
    """Vectorised a2 walk: stop = max(-atrd, net ROE -100 %), lock from best net ROE of the PREVIOUS minutes, stop
    checked before the minute's own best. Returns (ret, k, why)."""
    p0 = o[e]
    f0 = cumf[e - 1]
    start = 0
    best_prev = -1e9
    while True:
        i0, i1 = e + start, min(e + start + chunk, nmin)
        if i0 >= nmin:
            i = nmin - 1
            return s * (c[i] / p0 - 1) - COST - s * (cumf[i] - f0), i - e, 3
        ii = np.arange(i0, i1)
        if s > 0:
            up, dn = h[ii] / p0 - 1, l[ii] / p0 - 1
        else:
            up, dn = 1 - l[ii] / p0, 1 - h[ii] / p0
        Fp = s * (cumf[ii - 1] - f0)
        F = s * (cumf[ii] - f0)
        rup = LEV * (up - COST - F)
        best_incl = np.maximum.accumulate(np.r_[best_prev, rup])     # [0] = before this chunk
        bprev = best_incl[:-1]                                         # best of minutes strictly before ii
        lk = lock_of(bprev)
        level = np.maximum(-1.0 / LEV + COST + Fp, -atrd)
        lv = lk / LEV + COST + Fp
        locked = np.isfinite(lk)
        level = np.where(locked & (lv > level), lv, level)
        hit = np.flatnonzero(dn <= level)
        if len(hit):
            q = hit[0]
            op = s * (o[ii[q]] / p0 - 1)
            fill = min(level[q], op)
            r = fill - COST - F[q]
            r = max(r, -1.0 / LEV)
            return r, ii[q] - e, (1 if locked[q] else 0)
        best_prev = best_incl[-1]
        start += chunk


def build(variant_list=("ok", "la", "late")):
    end = ext_end()
    allrows = {v: [] for v in variant_list}
    meta = {}
    for ci, coin in enumerate(COINS):
        g = grid(coin)
        nmin = g["n"]
        o, h, l, c = g["o"], g["h"], g["l"], g["c"]
        cumf = np.cumsum(g["fund"])
        b1 = resample(g, "1h")
        b4 = resample(g, "4h")
        # 4h trend: OBV vs SMA30 of OBV, zero for the first WARM 4h bars (by bar number since the coin's first bar)
        ob = obv(b4.close.to_numpy(), b4.volume.to_numpy())
        st4 = np.sign(ob - sma(ob, 30))
        st4 = np.where(np.isfinite(st4), st4, 0)
        nb4 = (b4.ts.to_numpy() - b4.ts.iloc[0]) // (240 * MIN)
        st4 = np.where(nb4 < WARM, 0, st4)
        # 1h timing
        k = stoch_rsi_k(b1.close.to_numpy())
        kp = np.r_[np.nan, k[:-1]]
        with np.errstate(invalid="ignore"):
            lg = (k > 20) & (kp <= 20)
            sh = (k < 80) & (kp >= 80) & ~lg
        nb1 = (b1.ts.to_numpy() - b1.ts.iloc[0]) // (60 * MIN)
        sig = np.where(lg, 1, np.where(sh, -1, 0))
        sig = np.where(nb1 < WARM, 0, sig)
        atr = atr_pandas_rma(b1.rename(columns={}), 14)
        t1 = b1.close_ts.to_numpy()
        c4 = b4.close_ts.to_numpy()
        o4 = b4.ts.to_numpy()
        idx_ok = np.searchsorted(c4, t1, side="right") - 1          # last 4h close <= t
        idx_la = np.searchsorted(o4, t1 - 1, side="right") - 1      # 4h bar containing the hour that just closed
        idx_late = idx_ok - 1
        meta[coin] = {"n1h": len(b1), "n4h": len(b4), "la_differs_share": float(np.mean(idx_la != idx_ok))}
        sel = np.flatnonzero((sig != 0) & (t1 >= ms("2020-03-01")) & (t1 < end))
        for v, idx in (("ok", idx_ok), ("la", idx_la), ("late", idx_late)):
            if v not in variant_list:
                continue
            for q in sel:
                j4 = idx[q]
                if j4 < 0:
                    continue
                if st4[j4] != sig[q]:
                    continue
                e = int((t1[q] - T0) // MIN)
                if e >= nmin or not np.isfinite(atr[q]):
                    continue
                atrd = 2.0 * atr[q] / o[e]
                rs = {}
                for lab, s in (("own", int(sig[q])), ("opp", -int(sig[q]))):
                    rs[lab] = walk_vec(o, h, l, c, cumf, e, s, atrd, nmin)
                allrows[v].append({"coin": coin, "t": int(t1[q]), "e": e, "side": int(sig[q]),
                                   "k_prev": float(kp[q]), "k": float(k[q]), "j4_open": int(o4[j4]),
                                   "j4_close": int(c4[j4]), "obv": float(ob[j4]), "atr": float(atr[q]),
                                   "p0": float(o[e]), "atrd": atrd,
                                   "r": rs["own"][0], "kk": rs["own"][1], "why": rs["own"][2],
                                   "r_opp": rs["opp"][0], "kk_opp": rs["opp"][1], "why_opp": rs["opp"][2]})
        drop(coin)
        print(coin, meta[coin], {v: len(allrows[v]) for v in variant_list}, flush=True)
    for v in variant_list:
        R = pd.DataFrame(allrows[v])
        R["roe"] = LEV * R.r
        R["roe_opp"] = LEV * R.r_opp
        R.to_csv(os.path.join(HERE, f"rows_{v}.csv.gz"), index=False)
    json.dump(meta, open(os.path.join(HERE, "rebuild_meta.json"), "w"), indent=1)


if __name__ == "__main__":
    build(tuple(sys.argv[1:]) or ("ok", "la", "late"))
