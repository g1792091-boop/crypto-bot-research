"""Look-ahead / time-alignment / data verifier of the obvstoch study, INDEPENDENT of the study's and the data layer's
code: it reads the raw 1m files itself (fg1m npz to 2026-09-30, the Binance October daily kline zips, the rule bot's
live_bars.csv for the minutes after the daily files), builds its own bars with pandas resample, its own OBV / RSI /
Stoch RSI, its own higher-bar alignment (bar open + tf <= signal close), and its own 1m exit walk (w35: 35x, net ROE
-50 % stop, ladder +12 -> +10 then every 5 %, w35s20, w35s30; a2: 2 x ATR14 of the signal bar, 30x).

Outputs (this folder): indep_<coin>.npz (per entry tf: e, nb, srsi_kd, srsi_x, OBV states of the last closed htf bar,
and the walk results of both sides), data_check.json.

    python3 indep.py [coin ...]
"""
import os
import sys
import glob
import json
import zipfile
import time

import numpy as np
import pandas as pd
import numba

S = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
FG = f"{S}/fg1m/1m"
KL = f"{S}/newlive/data/klines"
LB = f"{S}/review1024_roles/verify_la_x/live_bars.csv"
HERE = os.path.dirname(os.path.abspath(__file__))
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
T0 = int(pd.Timestamp("2020-01-01", tz="UTC").value // 10**6)
MIN = 60_000
COST = 2 * (0.00042 + 0.0002)
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
HTF_OF = {"15m": ("1h", "4h"), "30m": ("1h", "4h"), "1h": ("4h",)}


# ------------------------------------------------------------------ raw minutes
def read_daily(coin):
    out = []
    for f in sorted(glob.glob(f"{KL}/{coin}-1m-2026-10-*/*.zip")):
        z = zipfile.ZipFile(f)
        raw = z.open(z.namelist()[0])
        d = pd.read_csv(raw, header=None)
        if not str(d.iloc[0, 0]).isdigit():
            d = d.iloc[1:]
        d = d.iloc[:, :6].astype(float)
        d.columns = ["ts", "o", "h", "l", "c", "v"]
        d["ts"] = d.ts.astype(np.int64)
        out.append(d)
    return pd.concat(out, ignore_index=True)


def minutes(coin, LBdf):
    """{o,h,l,c,v,fund} on the minute grid T0 .. end (exclusive), missing minutes = flat bar at the previous close,
    volume 0; first = first minute with data; plus the data checks."""
    z = np.load(f"{FG}/{coin}.npz")
    A = pd.DataFrame({k: z[k] for k in ("ts", "o", "h", "l", "c", "v", "fund")})
    D = read_daily(coin)
    D["fund"] = 0.0
    L = LBdf[LBdf.symbol == coin][["ts", "open", "high", "low", "close", "volume"]].copy()
    L.columns = ["ts", "o", "h", "l", "c", "v"]
    L["fund"] = 0.0
    chk = {}
    # data check: October daily files vs the bot's own live bars on the overlap
    m = D.merge(L, on="ts", suffixes=("_d", "_l"))
    chk["daily_vs_live_overlap_min"] = int(len(m))
    for k in ("o", "h", "l", "c"):
        rel = np.abs(m[f"{k}_d"] / m[f"{k}_l"] - 1)
        chk[f"daily_vs_live_{k}_n_diff"] = int((rel > 1e-9).sum())
        chk[f"daily_vs_live_{k}_max_rel"] = float(rel.max()) if len(rel) else 0.0
    chk["daily_vs_live_v_max_rel"] = float(np.abs(m.v_d / m.v_l.replace(0, np.nan) - 1).max()) if len(m) else 0.0
    end_d = int(D.ts.max()) + MIN
    L = L[L.ts >= end_d]
    X = pd.concat([A, D, L], ignore_index=True).sort_values("ts")
    assert X.ts.is_unique, coin
    return X, chk


def to_grid(X, end):
    n = (end - T0) // MIN
    idx = ((X.ts.to_numpy(np.int64) - T0) // MIN)
    assert ((X.ts.to_numpy(np.int64) - T0) % MIN == 0).all()
    keep = idx < n
    g = {}
    for k in ("o", "h", "l", "c", "v", "fund"):
        a = np.full(n, np.nan)
        a[idx[keep]] = X[k].to_numpy(float)[keep]
        g[k] = a
    first = int(idx[keep].min())
    c = pd.Series(g["c"]).ffill().to_numpy()
    miss = np.isnan(g["o"]) & (np.arange(n) >= first)
    for k in ("o", "h", "l", "c"):
        g[k][miss] = c[miss] if k != "c" else c[miss]
    # a missing minute: flat bar at the previous close
    g["o"][miss] = np.r_[np.nan, c[:-1]][miss]
    g["h"][miss] = g["o"][miss]
    g["l"][miss] = g["o"][miss]
    g["c"][miss] = g["o"][miss]
    g["v"][miss] = 0.0
    g["fund"] = np.nan_to_num(g["fund"])
    g["first"], g["n"], g["n_missing"] = first, n, int(miss.sum())
    return g


def bars_resample(g, tf):
    """Bars by pandas resample (label = bar open, closed left), whole bars after the first minute only."""
    first = g["first"]
    idx = pd.to_datetime(T0 + np.arange(first, g["n"], dtype=np.int64) * MIN, unit="ms", utc=True)
    df = pd.DataFrame({k: g[k][first:] for k in ("o", "h", "l", "c", "v")}, index=idx)
    r = df.resample(f"{TFM[tf]}min", label="left", closed="left", origin=pd.Timestamp(T0, unit="ms", tz="UTC"))
    B = pd.DataFrame({"o": r.o.first(), "h": r.h.max(), "l": r.l.min(), "c": r.c.last(), "v": r.v.sum(),
                      "cnt": r.c.count()})
    B["ts"] = (B.index.view(np.int64) // 10**6).astype(np.int64)
    B = B[(B.cnt == TFM[tf]) & (B.ts >= T0 + first * MIN)].reset_index(drop=True)
    B["close_t"] = B.ts + TFM[tf] * MIN
    B["nb"] = np.arange(len(B))
    return B


# ------------------------------------------------------------------ my own indicators
def rma(x, n):
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    ok = np.isfinite(x)
    run = 0
    s = -1
    for i in range(len(x)):
        run = run + 1 if ok[i] else 0
        if run >= n:
            s = i
            break
    if s < 0:
        return out
    out[s] = x[s - n + 1:s + 1].mean()
    a = 1.0 / n
    for i in range(s + 1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1] if np.isfinite(x[i]) else out[i - 1]
    return out


def rsi(c, n=14):
    d = np.r_[np.nan, np.diff(c)]
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    up[0] = dn[0] = np.nan
    au, ad = rma(up, n), rma(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100 - 100 / (1 + au / ad)
    r = np.where(ad == 0, 100.0, np.where(au == 0, 0.0, r))
    return np.where(np.isfinite(au) & np.isfinite(ad), r, np.nan)


def stochrsi(c):
    r = pd.Series(rsi(c, 14))
    lo, hi = r.rolling(14).min(), r.rolling(14).max()
    rng = hi - lo
    raw = np.where(rng.to_numpy() != 0, 100 * (r - lo) / rng.replace(0, np.nan), 0.0)
    raw = np.where(np.isfinite(rng.to_numpy()), raw, np.nan)
    k = pd.Series(raw).rolling(3).mean()
    d = k.rolling(3).mean()
    return k.to_numpy(), d.to_numpy()


def xup(a, b):
    a, b = np.asarray(a, float), np.full(len(a), b) if np.isscalar(b) else np.asarray(b, float)
    ap, bp = np.r_[np.nan, a[:-1]], np.r_[np.nan, b[:-1]]
    with np.errstate(invalid="ignore"):
        return (a > b) & (ap <= bp)


def obv_states(B):
    c, v = B.c.to_numpy(float), B.v.to_numpy(float)
    ob = np.cumsum(np.r_[0.0, np.sign(np.diff(c))] * v)
    S = {}
    for n in (20, 30, 50):
        sm = pd.Series(ob).rolling(n).mean().to_numpy()
        with np.errstate(invalid="ignore"):
            S[f"OBV{n}"] = np.where(ob > sm, 1, np.where(ob < sm, -1, 0)).astype(np.int8)
    prev = np.r_[np.full(10, np.nan), ob[:-10]]
    with np.errstate(invalid="ignore"):
        S["OBVSL10"] = np.where(ob > prev, 1, np.where(ob < prev, -1, 0)).astype(np.int8)
    for k in S:
        S[k][B.nb.to_numpy() < 300] = 0
    return S


def atr14(B):
    h, l, c = B.h.to_numpy(float), B.l.to_numpy(float), B.c.to_numpy(float)
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.c_[h - l, np.abs(h - pc), np.abs(l - pc)], axis=1)
    tr[0] = h[0] - l[0]
    return rma(tr, 14)


# ------------------------------------------------------------------ my own walk
@numba.njit
def walk(o, h, l, c, cumf, es, s, lev, cost, stop_roe, atrd, n):
    m = len(es)
    R = np.zeros(m)
    K = np.zeros(m, np.int64)
    W = np.zeros(m, np.int8)
    for q in range(m):
        e = es[q]
        p0 = o[e]
        f0 = cumf[e - 1]
        best = -1e9
        lock = np.nan
        i = e
        while True:
            if i >= n:
                R[q] = s * (c[n - 1] / p0 - 1) - cost - s * (cumf[n - 1] - f0)
                K[q] = n - 1 - e
                W[q] = 3
                break
            Fp = s * (cumf[i - 1] - f0)
            F = s * (cumf[i] - f0)
            lvl = stop_roe / lev + cost + Fp
            if atrd[q] > 0 and -atrd[q] > lvl:
                lvl = -atrd[q]
            why = 0
            if lock == lock:
                ll = lock / lev + cost + Fp
                if ll > lvl:
                    lvl = ll
                    why = 1
            if s > 0:
                adv = l[i] / p0 - 1
                fav = h[i] / p0 - 1
            else:
                adv = 1 - h[i] / p0
                fav = 1 - l[i] / p0
            if adv <= lvl:
                op = s * (o[i] / p0 - 1)
                fill = lvl if lvl < op else op
                R[q] = fill - cost - F
                K[q] = i - e
                W[q] = why
                break
            rb = lev * (fav - cost - F)
            if rb > best:
                best = rb
                if best >= 0.12 - 1e-12:
                    lock = 0.10 + 0.05 * np.floor((best - 0.12) / 0.05 + 1e-9)
            i += 1
        if R[q] < -1.0 / lev:
            R[q] = -1.0 / lev
    return R, K, W


def run(coin, LBdf, end):
    t0 = time.time()
    X, chk = minutes(coin, LBdf)
    g = to_grid(X, end)
    chk["n_missing_minutes"] = g["n_missing"]
    # data check against the shared grid (common.grid): must be identical where both exist
    sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
    import common as C
    G = C.grid(coin)
    nn = min(G["n"], g["n"])
    for k in ("o", "h", "l", "c", "v", "fund"):
        a, b = np.nan_to_num(G[k][g["first"]:nn]), np.nan_to_num(g[k][g["first"]:nn])
        chk[f"grid_vs_mine_{k}_n_diff"] = int((~np.isclose(a, b, rtol=1e-9, atol=1e-12)).sum())
    chk["grid_n"], chk["mine_n"] = int(G["n"]), int(g["n"])
    C.drop(coin)
    B = {tf: bars_resample(g, tf) for tf in ("15m", "30m", "1h", "4h")}
    H = {}
    for htf in ("1h", "4h"):
        H[htf] = (B[htf].close_t.to_numpy(np.int64), obv_states(B[htf]))
    cumf = np.cumsum(g["fund"])
    out = {}
    for tf in ("15m", "30m", "1h"):
        b = B[tf]
        t = b.close_t.to_numpy(np.int64)
        e = (t - T0) // MIN
        k, d = stochrsi(b.c.to_numpy(float))
        with np.errstate(invalid="ignore"):
            kd_l = xup(k, d) & (k < 20)
            kd_s = xup(d, k) & (k > 80) & ~kd_l
            x_l = xup(k, 20.0)
            x_s = xup(np.full(len(k), 80.0), k) & ~x_l
        kd = np.where(kd_l, 1, np.where(kd_s, -1, 0)).astype(np.int8)
        xx = np.where(x_l, 1, np.where(x_s, -1, 0)).astype(np.int8)
        kd[:300] = 0
        xx[:300] = 0
        pre = f"{tf}_"
        out[pre + "e"], out[pre + "nb"], out[pre + "kd"], out[pre + "x"] = e, b.nb.to_numpy(), kd, xx
        for htf in HTF_OF[tf]:
            cl, St = H[htf]
            j = np.searchsorted(cl, t, side="right") - 1          # last higher bar with close <= signal close
            jn = np.searchsorted(cl, t, side="left")              # LOOK-AHEAD probe: the first bar closing at/after t
            for nm, arr in St.items():
                out[f"{pre}{htf}_{nm}"] = np.where(j >= 0, arr[np.clip(j, 0, len(arr) - 1)], 0).astype(np.int8)
                # look-ahead probe: the higher bar that is still OPEN at t (its close > t), i.e. what a study would
                # read if it took the bar containing t
                jo = np.searchsorted(cl, t, side="right")         # first bar with close > t (still open at t)
                out[f"{pre}{htf}_{nm}_LA"] = np.where(jo < len(arr), arr[np.clip(jo, 0, len(arr) - 1)], 0).astype(np.int8)
                out[f"{pre}{htf}_{nm}_LAG"] = np.where(j >= 1, arr[np.clip(j - 1, 0, len(arr) - 1)], 0).astype(np.int8)
        ok = (e < g["n"]) & (e >= 1)
        ev = e[ok]
        atr = atr14(b)
        atrd = np.where(ok, 2.0 * atr / np.where(ok, g["o"][np.clip(e, 0, g["n"] - 1)], np.nan), np.nan)[ok]
        atrd = np.where(np.isfinite(atrd), atrd, -1.0)
        for X_, lev, stp, use_atr in (("w35", 35.0, -0.50, False), ("w35s30", 35.0, -0.30, False),
                                      ("w35s20", 35.0, -0.20, False), ("a2", 30.0, -1.0, True)):
            for lab, sd in (("L", 1), ("S", -1)):
                ad = atrd if use_atr else np.full(len(ev), -1.0)
                r, kk, w = walk(g["o"], g["h"], g["l"], g["c"], cumf, ev.astype(np.int64), sd, lev, COST, stp,
                                np.ascontiguousarray(ad), g["n"])
                rr = np.full(len(e), np.nan, np.float32)
                ww = np.full(len(e), -1, np.int8)
                rr[ok], ww[ok] = r, w
                if use_atr:
                    bad = ~np.isfinite(np.where(ok, 2.0 * atr, np.nan))
                    rr[bad] = np.nan
                    ww[bad] = -1
                out[f"{pre}{X_}_{lab}_r"], out[f"{pre}{X_}_{lab}_w"] = rr, ww
                out[f"{pre}{X_}_{lab}_k"] = np.where(ok, 0, -1).astype(np.int64)
                out[f"{pre}{X_}_{lab}_k"][ok] = kk
    np.savez(os.path.join("/dev/shm/claude_verify_la", f"indep_{coin}.npz"), **out)
    print(coin, f"{time.time() - t0:.0f}s", json.dumps(chk), flush=True)
    return coin, chk


if __name__ == "__main__":
    LBdf = pd.read_csv(LB, usecols=["ts", "symbol", "open", "high", "low", "close", "volume"])
    end = int(min(LBdf[LBdf.symbol == c].ts.max() for c in COINS)) + MIN
    coins = sys.argv[1:] or list(COINS)
    allc = {}
    for c in coins:
        allc[c] = run(c, LBdf, end)[1]
    allc["end"] = str(pd.Timestamp(end, unit="ms"))
    json.dump(allc, open(os.path.join(HERE, "data_check.json"), "w"), indent=1)
