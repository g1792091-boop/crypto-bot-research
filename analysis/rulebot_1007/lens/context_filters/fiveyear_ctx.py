#!/usr/bin/env python3
"""5-year external check of the live context candidates (written after the live scan; the 5-year outcomes were not
looked at before the contrasts below were fixed in fiveyear_tests.py).

Every signal of the 36 locked strategies, 15m and 30m, six coins, 2021-08-01 .. 2026-09-30 (Binance futures cache),
run ALONE under the paper v4 house rules: next-bar open + slippage, 2 ATR stop, v4 'normal' leverage group
(30x / 30% margin, then 20x / 20%; v3_settings sizing on a $5,000 account), stepped ladder lock, fees, funding
(research/strategy_profiles/profiles.py _scan, imported unchanged). Context per signal bar computed from closed bars:
EMA20 distance in ATR, trend age, Wilder DI+/DI-/ADX(14), efficiency ratio, box position (95/5 % quantiles over the
regime window), range position, higher-tf box position (closed 1h / 4h bars), stop % of price, KST hour, consensus /
conflict among the 36 at the same bar.

    python3 -I fiveyear_ctx.py <repo> <signals_dir> <out_dir> [procs]
"""
from __future__ import annotations

import os
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
REPO, SIGDIR, OUT = sys.argv[1:4]
PROCS = int(sys.argv[4]) if len(sys.argv) > 4 else 4
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "research", "strategy_profiles"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

COINS = ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"]
REGIME_N = {"15m": 64, "30m": 48}
HTF = {"15m": ("1h", 48, 60), "30m": ("4h", 42, 240)}
TF_MIN = {"15m": 15, "30m": 30}
EQUITY = 5000.0


def wilder(x, n=14):
    out = np.full(len(x), np.nan)
    x = np.asarray(x, float)
    if len(x) <= n:
        return out
    out[n] = np.nanmean(x[1:n + 1])
    a = 1.0 / n
    for i in range(n + 1, len(x)):
        out[i] = out[i - 1] * (1 - a) + a * x[i]
    return out


def features(b, tf):
    o, h, l, c, atr = (b[k].astype(float) for k in ("o", "h", "l", "c", "atr"))
    n = len(c)
    ema = pd.Series(c).ewm(span=20, adjust=False).mean().to_numpy()
    ema_dist = (c - ema) / atr
    above = c >= ema
    chg = np.r_[True, above[1:] != above[:-1]]
    grp = np.cumsum(chg)
    age = pd.Series(np.ones(n)).groupby(grp).cumsum().to_numpy()
    # Wilder DI / ADX
    up = np.r_[0, h[1:] - h[:-1]]
    dn = np.r_[0, l[:-1] - l[1:]]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.r_[h[0] - l[0], np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])]
    s_tr, s_p, s_m = wilder(tr), wilder(pdm), wilder(mdm)
    dip = 100 * s_p / s_tr
    dim = 100 * s_m / s_tr
    dx = 100 * np.abs(dip - dim) / (dip + dim)
    adx = np.full(n, np.nan)
    v = np.where(np.isfinite(dx))[0]
    if len(v) > 15:
        adx[v] = wilder(dx[v])
    N = REGIME_N[tf]
    hs, ls, cs = pd.Series(h), pd.Series(l), pd.Series(c)
    hi = hs.rolling(N).quantile(0.95, interpolation="linear").to_numpy()
    lo = ls.rolling(N).quantile(0.05, interpolation="linear").to_numpy()
    box_pos = (c - lo) / (hi - lo)
    rh, rl = hs.rolling(N).max().to_numpy(), ls.rolling(N).min().to_numpy()
    range_pos = (c - rl) / (rh - rl)
    path = pd.Series(np.abs(np.r_[0, np.diff(c)])).rolling(N - 1).sum().to_numpy()
    er = np.abs(c - cs.shift(N - 1).to_numpy()) / path
    # higher timeframe box from CLOSED htf bars
    _, HN, hmin = HTF[tf]
    ts = b["ts"].astype(np.int64)
    if ts.max() > 10 ** 15:                # the cache stores ns
        ts = ts // 1_000_000
    tfms = TF_MIN[tf] * 60_000
    hms = hmin * 60_000
    close_t = ts + tfms
    key = ts // hms
    df = pd.DataFrame({"k": key, "h": h, "l": l})
    g = df.groupby("k").agg(h=("h", "max"), l=("l", "min"), cnt=("h", "size"))
    g = g[g["cnt"] == hmin // TF_MIN[tf]]
    hh = g["h"].rolling(HN).quantile(0.95, interpolation="linear")
    ll = g["l"].rolling(HN).quantile(0.05, interpolation="linear")
    hk = g.index.to_numpy()
    # last htf bar fully closed at the signal bar's close: (k+1)*hms <= close_t  ->  k <= close_t//hms - 1
    want = close_t // hms - 1
    pos = np.searchsorted(hk, want, side="right") - 1
    okp = pos >= 0
    hhv = np.full(n, np.nan)
    llv = np.full(n, np.nan)
    hhv[okp] = hh.to_numpy()[pos[okp]]
    llv[okp] = ll.to_numpy()[pos[okp]]
    htf_pos = (c - llv) / (hhv - llv)
    kst_hour = ((close_t // 3_600_000) + 9) % 24
    return {"ema_dist": ema_dist, "age": age, "dip": dip, "dim": dim, "adx": adx, "box_pos": box_pos,
            "range_pos": range_pos, "er": er, "htf_pos": htf_pos, "kst_hour": kst_hour, "stop_pct": 200 * atr / c,
            "close_t": close_t}


def job(args):
    tf, coin = args
    import profiles as P
    import rules_bt as RB
    from paperbot import sweepsig
    from paperbot.config import v3_settings
    from paperbot.sizing import size_position
    S = v3_settings()
    L = sweepsig.lib()
    z = np.load(os.path.join(SIGDIR, f"sig_{tf}_{coin}.npz"))
    b = {k: z[k] for k in ("ts", "o", "h", "l", "c", "atr")}
    n = len(b["ts"])
    f_bar = RB.FUNDING_8H * L.tf_minutes(tf) / 480.0
    lo_all = RB.window_bounds(L, b, tf, "is")[0]
    n_end = RB.window_bounds(L, b, tf, "cf")[1]
    FT = features(b, tf)
    cache = {}

    def lev_liq(side, atr_frac):
        k = (side, float(f"{atr_frac:.4g}"))
        if k not in cache:
            raw = 100.0
            a = k[1] * raw
            fill = raw * (1 + side * S.slippage_frac)
            d = size_position(S, EQUITY, side, fill, raw - side * 2.0 * a, "normal", RB.BRACKETS, atr=a,
                              min_notional=RB.MIN_NOTIONAL)
            cache[k] = (d.leverage, side * (fill - d.liq_price) / fill) if d.ok else (0, np.nan)
        return cache[k]

    names = [k for k in z.files if k.startswith("s__")]
    sigmat = np.vstack([z[k] for k in names]).astype(np.int8)       # strategies x bars
    n_long = (sigmat > 0).sum(0)
    n_short = (sigmat < 0).sum(0)
    rows = []
    for si, key in enumerate(names):
        sg = sigmat[si]
        idx = np.nonzero(sg[lo_all:n_end - 1])[0] + lo_all
        a = b["atr"][idx]
        ok = np.isfinite(a) & (a > 0) & np.isfinite(b["o"][np.minimum(idx + 1, n - 1)])
        idx = idx[ok]
        if not len(idx):
            continue
        side = sg[idx].astype(int)
        raw = b["o"][idx + 1]
        ll = np.array([lev_liq(int(s), float(x)) for s, x in zip(side, b["atr"][idx] / raw)]).reshape(-1, 2)
        lev, liq_frac = ll[:, 0], ll[:, 1]
        sized = lev > 0
        roe = np.full(len(idx), np.nan)
        reason = np.full(len(idx), np.nan)
        held = np.full(len(idx), np.nan)
        todo = np.nonzero(sized)[0]
        for H in (64, 512, 4096):
            if not len(todo):
                break
            nxt = []
            step = max(32, 256_000 // H)
            for c0 in range(0, len(todo), step):
                sel = todo[c0:c0 + step]
                r = P._scan(b, idx[sel], side[sel], lev[sel], liq_frac[sel], H, n, f_bar, ladder=S.ladder)
                last = H == 4096
                keep = r["done"] | last | (idx[sel] + H >= n - 1)
                roe[sel[keep]] = r["roe"][keep]
                reason[sel[keep]] = r["reason"][keep]
                held[sel[keep]] = r["held"][keep]
                nxt.append(sel[~keep])
            todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
        fill = raw * (1 + side * S.slippage_frac)
        dist = np.abs(fill - (raw - side * 2.0 * b["atr"][idx]))
        R = np.where(sized, roe / (lev * dist / fill), np.nan)
        same = np.where(side > 0, n_long[idx], n_short[idx])
        opp = np.where(side > 0, n_short[idx], n_long[idx])
        d = {"strategy": np.full(len(idx), key[3:]), "coin": np.full(len(idx), coin), "tf": np.full(len(idx), tf),
             "bar": idx, "close_t": FT["close_t"][idx], "side": side, "lev": lev, "roe": roe, "R": R,
             "reason": reason, "held": held, "n_same": same, "n_opp": opp}
        for k2 in ("ema_dist", "age", "dip", "dim", "adx", "box_pos", "range_pos", "er", "htf_pos", "kst_hour",
                   "stop_pct"):
            d[k2] = FT[k2][idx]
        rows.append(pd.DataFrame(d))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def main():
    os.makedirs(OUT, exist_ok=True)
    jobs = [(tf, c) for tf in ("15m", "30m") for c in COINS]
    import multiprocessing as mp
    with mp.get_context("fork").Pool(PROCS) as pool:
        parts = pool.map(job, jobs)
    X = pd.concat(parts, ignore_index=True)
    X.to_csv(os.path.join(OUT, "fiveyear_signals.csv.gz"), index=False)
    print(X.groupby(["tf"]).agg(n=("R", "size"), sized=("R", lambda s: s.notna().sum()), mean_R=("R", "mean"),
                                 lev30=("lev", lambda s: (s == 30).mean())).to_string())


if __name__ == "__main__":
    main()
