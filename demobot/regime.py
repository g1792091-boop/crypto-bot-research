"""Market regime per coin and 15m bar (CONTRACT 8.5), from closed bars only (no look-ahead):

* trend: 4h bars built from 15m bars (complete groups of 16); EMA50 of the 4h closes; slope = EMA50 now minus 6 bars
  ago, divided by the 4h ATR14 (Wilder). up > +0.5, down < -0.5, else range. A 15m bar uses the last 4h bar that
  closed before it opened.
* volatility: 15m ATR14 / close, against its own previous 90 days (thresholds per UTC day from the 90 days before
  that day): high above the 70th percentile, low below the 30th, else normal.

Codes: trend -1 down, 0 range, 1 up; vol 0 low, 1 normal, 2 high; 9 = not enough history.
"""
from __future__ import annotations

import numpy as np

from . import accounts as A
from . import grid as G

M15 = 15 * 60 * 1000
H4 = 4 * 3600 * 1000
DAY = 86400 * 1000
UNK = 9
TREND_KEY = {1: "up", -1: "down", 0: "range"}
VOL_KEY = {2: "high", 1: "normal", 0: "low"}
TREND_KO = {"up": "상승 추세", "down": "하락 추세", "range": "횡보"}
VOL_KO = {"high": "변동 큼", "normal": "보통", "low": "변동 작음"}
SLOPE_T = 0.5
EMA_N, SLOPE_K, ATR_N = 50, 6, 14
VOL_DAYS = 90


def _wilder(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = np.nanmean(x[:n])
    for i in range(n, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    a = 2.0 / (n + 1)
    out[n - 1] = x[:n].mean()
    for i in range(n, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _tr(h, l, c):
    pc = np.concatenate([[c[0]], c[:-1]])
    return np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))


def coin_regime(b: dict) -> tuple:
    """(trend codes, vol codes, slope, atr_pct) per 15m bar of ``b`` (the engine's 15m arrays)."""
    ts = np.asarray(b["ts"], np.int64)
    n = len(ts)
    trend = np.full(n, UNK, np.int8)
    vol = np.full(n, UNK, np.int8)
    slope_b = np.full(n, np.nan)
    if n < 2:
        return trend, vol, slope_b, np.full(n, np.nan)
    h, l, c = (np.asarray(b[k], float) for k in ("h", "l", "c"))
    # 4h bars: complete groups of 16 consecutive 15m bars
    g = ts // H4
    starts = np.flatnonzero(np.concatenate([[True], g[1:] != g[:-1]]))
    ends = np.concatenate([starts[1:], [n]])
    full = (ends - starts == 16) & (ts[ends - 1] - ts[starts] == 15 * M15)
    s4, e4 = starts[full], ends[full]
    if len(s4) > EMA_N + SLOPE_K:
        h4 = np.array([h[a:z].max() for a, z in zip(s4, e4)])
        l4 = np.array([l[a:z].min() for a, z in zip(s4, e4)])
        c4 = c[e4 - 1]
        ema = _ema(c4, EMA_N)
        atr4 = _wilder(_tr(h4, l4, c4), ATR_N)
        slope = np.full(len(c4), np.nan)
        slope[SLOPE_K:] = (ema[SLOPE_K:] - ema[:-SLOPE_K]) / atr4[SLOPE_K:]
        close4 = g[s4] * H4 + H4                      # when each 4h bar closed
        j = np.searchsorted(close4, ts, side="right") - 1      # last 4h bar closed at/before the 15m open
        ok = j >= 0
        sv = np.full(n, np.nan)
        sv[ok] = slope[j[ok]]
        fin = np.isfinite(sv)
        slope_b = sv
        trend[fin] = np.where(sv[fin] > SLOPE_T, 1, np.where(sv[fin] < -SLOPE_T, -1, 0))
    atr = _wilder(_tr(h, l, c), ATR_N)
    atrp = atr / c
    # the regime of a bar uses the bar before it (its ATR includes the bar's own range otherwise)
    prev = np.concatenate([[np.nan], atrp[:-1]])
    day = ts // DAY
    for d in np.unique(day):
        m = day == d
        lo = (d - VOL_DAYS) * DAY
        hist = atrp[(ts >= lo) & (ts < d * DAY)]
        hist = hist[np.isfinite(hist)]
        if len(hist) < 30 * 96:
            continue
        p30, p70 = np.percentile(hist, [30, 70])
        v = prev[m]
        code = np.where(v > p70, 2, np.where(v < p30, 0, 1)).astype(np.int8)
        code[~np.isfinite(v)] = UNK
        vol[m] = code
    return trend, vol, slope_b, prev


def compute(eng) -> dict:
    """{coin: (ts, trend, vol, slope, atr_pct)} for every coin."""
    out = {}
    for coin in G.COINS:
        b = eng.b15.get(coin)
        if b is None or not len(b["ts"]):
            continue
        tr, vo, sl, ap = coin_regime(b)
        out[coin] = (np.asarray(b["ts"], np.int64), tr, vo, sl, ap)
    return out


def at(reg: dict, coin: str, entry_ms: int) -> tuple:
    """(trend key, vol key) for an entry at entry_ms: the regime of the last closed 15m bar before it."""
    r = reg.get(coin)
    if r is None:
        return None, None
    ts, tr, vo = r[0], r[1], r[2]
    i = int(np.searchsorted(ts, entry_ms, side="left")) - 1
    if i < 0:
        return None, None
    return TREND_KEY.get(int(tr[i])), VOL_KEY.get(int(vo[i]))


def annotate(reg: dict, res: dict) -> None:
    for r in res.values():
        for sim in r["lines"].values():
            for t in sim["trades"]:
                t["trend"], t["vol"] = at(reg, t["coin"], t["entry_ms"])


def _bucket(trades: list, key: str, vals) -> dict:
    out = {}
    for v in vals:
        tt = [t for t in trades if t.get(key) == v and t["status"] == "closed"]
        n = len(tt)
        out[v] = dict(n=n, mean_R=(sum(t["R"] for t in tt) / n if n else None), pnl=sum(t["pnl"] for t in tt))
    return out


def snapshot(reg: dict, res: dict, live0: int, now_ms: int) -> dict:
    now_rows, hist = [], []
    for coin in G.COINS:
        r = reg.get(coin)
        if r is None:
            continue
        ts, tr, vo, sl, ap = r
        lo = int(np.searchsorted(ts, (live0 or now_ms) - 7 * DAY))
        pts = []
        prev = None
        for i in range(lo, len(ts)):
            cur = (int(tr[i]), int(vo[i]))
            if cur != prev:
                pts.append([int(ts[i]), TREND_KEY.get(cur[0]), VOL_KEY.get(cur[1])])
                prev = cur
        hist.append(dict(coin=coin, points=pts[-800:]))
        k = len(ts) - 1
        since = int(ts[k])
        while k > 0 and tr[k - 1] == tr[len(ts) - 1] and vo[k - 1] == vo[len(ts) - 1]:
            k -= 1
            since = int(ts[k])
        now_rows.append(dict(coin=coin, trend=TREND_KEY.get(int(tr[-1])), vol=VOL_KEY.get(int(vo[-1])),
                             slope=(float(sl[-1]) if np.isfinite(sl[-1]) else None),
                             atr_pct=(float(ap[-1]) * 100 if np.isfinite(ap[-1]) else None), since_ms=since))
    lines = []
    for a in A.current_accounts():
        rr = res.get(a.id)
        if rr is None:
            continue
        for L, sim in rr["lines"].items():
            ts_ = sim["trades"]
            if not any(t["status"] == "closed" for t in ts_):
                continue
            lines.append(dict(id=a.id, name=a.name, L=int(L), trend=_bucket(ts_, "trend", ("up", "down", "range")),
                              vol=_bucket(ts_, "vol", ("high", "normal", "low"))))
    return dict(generated_ms=now_ms, labels_ko=dict(trend=TREND_KO, vol=VOL_KO), now=now_rows, history=hist,
                lines=lines)
