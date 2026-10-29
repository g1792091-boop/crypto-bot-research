"""The friend's chart-mix indicator ("차트 믹스": 하늘·보라 · EMA RSI 밴드 · 찹존 · 슈퍼트렌드, owners 10-29) as trend votes (PLAN.md 1).

Four votes on a closed bar, +1 up / -1 down / 0 sideways:
  line    the sky / purple line: ROC 9 · RSI 26 · MOM 10 summed, above its EMA 9 signal = sky (paperbot/mixchop.line_gold)
  ema     the EMA RSI band's middle-line colour: EMA RSI >= 50 green (the default '가격 · EMA 거리' mode, EMA 21 / 52, EMA 3)
  chop    the chop zone 9 band: zones +1 .. +4 up, -1 .. -4 down, 0 (yellow) sideways
  st      the supertrend average (ATR 14, factors 6 and 3): both up / both down, mixed (yellow) sideways
trend: two or more sideways -> 0 (no entry); else the side with two or more votes and more than the other (2-2 -> 0).

The Pine helpers come from paperbot/mixchop.py (EMA, RSI, population stdev, zsq, ROC, MOM, ATR, supertrend: the friend bot's,
matched to TradingView); the rest (SMA, highest / lowest, OBV, MACD, parabolic SAR, Ichimoku, the chop-zone angle) follows the
Pine source and TradingView's documented built-ins line by line. Research code: nothing here trades.
"""
from __future__ import annotations

import math
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from paperbot import mixchop as M  # noqa: E402


def _nz(x, d: float = 0.0) -> np.ndarray:
    x = np.asarray(x, float)
    return np.where(np.isfinite(x), x, d)


def _tanh(x) -> np.ndarray:
    """The script's tanh: exp of 2 x clamped to +-10."""
    with np.errstate(invalid="ignore"):
        return np.tanh(np.clip(np.asarray(x, float), -10, 10))


def _clamp1(x) -> np.ndarray:
    return np.clip(_nz(x), -1.0, 1.0)


def sma(x, n: int) -> np.ndarray:
    return M.sma(x, n)


def highest(x, n: int) -> np.ndarray:
    return pd.Series(np.asarray(x, float)).rolling(n, min_periods=n).max().to_numpy()


def lowest(x, n: int) -> np.ndarray:
    return pd.Series(np.asarray(x, float)).rolling(n, min_periods=n).min().to_numpy()


def lag(x, k: int) -> np.ndarray:
    x = np.asarray(x, float)
    return np.r_[np.full(k, np.nan), x[:-k]] if k > 0 else x


def obv(close, volume) -> np.ndarray:
    """ta.obv = ta.cum(math.sign(ta.change(close)) * volume); the first bar adds nothing."""
    c, v = np.asarray(close, float), np.asarray(volume, float)
    return np.cumsum(_nz(np.sign(np.r_[np.nan, np.diff(c)]) * v))


def sar(high, low, close, start: float = 0.02, inc: float = 0.02, mx: float = 0.2) -> np.ndarray:
    """ta.sar as TradingView documents it (the Pine reference implementation)."""
    h, l, c = (np.asarray(a, float) for a in (high, low, close))
    n = len(c)
    out = np.full(n, np.nan)
    result = max_min = acc = math.nan
    below = False
    for i in range(1, n):
        first = False
        if i == 1:
            if c[1] > c[0]:
                below, max_min, result = True, h[1], l[0]
            else:
                below, max_min, result = False, l[1], h[0]
            first, acc = True, start
        result = result + acc * (max_min - result)
        if below:
            if result > l[i]:
                first, below = True, False
                result, max_min, acc = max(h[i], max_min), l[i], start
        else:
            if result < h[i]:
                first, below = True, True
                result, max_min, acc = min(l[i], max_min), h[i], start
        if not first:
            if below:
                if h[i] > max_min:
                    max_min, acc = h[i], min(acc + inc, mx)
            else:
                if l[i] < max_min:
                    max_min, acc = l[i], min(acc + inc, mx)
        if below:
            result = min(result, l[i - 1])
            if i > 1:
                result = min(result, l[i - 2])
        else:
            result = max(result, h[i - 1])
            if i > 1:
                result = max(result, h[i - 2])
        out[i] = result
    return out


def chop_zone(o, h, l, c, v) -> np.ndarray:
    """종합 찹존 9 (all nine on, sensitivity 1.0, smoothing 3): zones +4 .. -4, 0 = 횡보 (yellow)."""
    o, h, l, c, v = (np.asarray(a, float) for a in (o, h, l, c, v))
    atr = M.atr(h, l, c, 14)
    atr_ok = np.isfinite(atr) & (atr > 0)
    hlc3 = (h + l + c) / 3.0
    # 1. chop zone: the EMA 34 slope as an angle
    hh, ll = highest(h, 30), lowest(l, 30)
    with np.errstate(invalid="ignore", divide="ignore"):
        span = np.where(hh - ll > 0, 25.0 / (hh - ll) * ll, 0.0)
        e34 = M.ema(c, 34)
        prev = np.where(np.isfinite(lag(e34, 1)), lag(e34, 1), e34)
        y2 = np.where(hlc3 > 0, (prev - e34) / hlc3 * span, 0.0)
        ang1 = np.floor(180.0 * np.arccos(1.0 / np.sqrt(1.0 + y2 * y2)) / math.pi + 0.5)
        angle = np.where(y2 > 0, -ang1, ang1)
    s1 = _clamp1(angle / 5.0)
    # 2 · 3. AC / AO
    hl2 = (h + l) / 2.0
    ao = sma(hl2, 5) - sma(hl2, 34)
    ac = ao - sma(ao, 5)
    s2, s3 = M.zsq(ac, 100), M.zsq(ao, 100)
    # 4. RSI 14
    s4 = _clamp1((_nz(M.rsi(c, 14), 50.0) - 50.0) / 50.0)
    # 5. OBV against its EMA 20
    ob = obv(c, v)
    s5 = M.zsq(ob - M.ema(ob, 20), 100) if np.nansum(v) > 0 else np.zeros(len(c))
    # 6. EMA 21 / 52
    with np.errstate(invalid="ignore", divide="ignore"):
        s6 = np.where(atr_ok, _tanh((M.ema(c, 21) - M.ema(c, 52)) / (2.0 * atr)), 0.0)
    # 7. MACD 12 / 26 / 9: the line and the histogram
    ml = M.ema(c, 12) - M.ema(c, 26)
    mh = ml - M.ema(ml, 9)
    s7 = (M.zsq(ml, 100) + M.zsq(mh, 100)) / 2.0
    # 8. parabolic SAR
    with np.errstate(invalid="ignore", divide="ignore"):
        s8 = np.where(atr_ok, _tanh((c - sar(h, l, c)) / (2.0 * atr)), 0.0)
    # 9. Ichimoku 9 / 26 / 52, the cloud 26 bars on (the values 25 bars back)
    def don(n):
        return (highest(h, n) + lowest(l, n)) / 2.0
    conv, base, spb = don(9), don(26), don(52)
    spa = (conv + base) / 2.0
    a25, b25 = lag(spa, 25), lag(spb, 25)
    with np.errstate(invalid="ignore", divide="ignore"):
        top, bot = np.fmax(a25, b25), np.fmin(a25, b25)
        top = np.where(np.isfinite(a25) & np.isfinite(b25), top, np.nan)
        bot = np.where(np.isfinite(a25) & np.isfinite(b25), bot, np.nan)
        cloud = np.where(c > top, _tanh((c - top) / (2.0 * atr)), np.where(c < bot, -_tanh((bot - c) / (2.0 * atr)), 0.0))
        tk = np.where(atr_ok, _tanh((conv - base) / atr), 0.0)
        s9 = np.where(atr_ok, 0.6 * _nz(cloud) + 0.4 * _nz(tk), 0.0)
    total = sum(_nz(s) for s in (s1, s2, s3, s4, s5, s6, s7, s8, s9))
    score = M.ema(total / 9.0, 3)
    sc = score * 1.0
    zone = np.zeros(len(c), np.int8)
    for lim, z in ((0.60, 4), (0.40, 3), (0.25, 2), (0.10, 1)):
        zone = np.where((zone == 0) & (sc >= lim), z, zone)
    for lim, z in ((-0.60, -4), (-0.40, -3), (-0.25, -2), (-0.10, -1)):
        zone = np.where((zone == 0) & (sc <= lim), z, zone)
    return zone.astype(np.int8)


def ema_rsi(c) -> np.ndarray:
    """EMA RSI ('가격 · EMA 거리' mode): EMA 3 of 50 + 50 x the mean of three zsq'd distances."""
    c = np.asarray(c, float)
    e1, e2 = M.ema(c, 21), M.ema(c, 52)
    sc = (_nz(M.zsq(c - e1, 100)) + _nz(M.zsq(c - e2, 100)) + _nz(M.zsq(e1 - e2, 100))) / 3.0
    return M.ema(50.0 + 50.0 * sc, 3)


def votes(o, h, l, c, v) -> dict:
    """The four votes and the trend per bar (each from that bar's close: use the last closed bar)."""
    line = np.where(M.line_gold(c), 1, -1).astype(np.int8)
    er = ema_rsi(c)
    ema = np.where(er >= 50, 1, -1).astype(np.int8)
    chop = np.sign(chop_zone(o, h, l, c, v)).astype(np.int8)
    _, up6 = M.supertrend(h, l, c, 14, 6.0)
    _, up3 = M.supertrend(h, l, c, 14, 3.0)
    st = np.where(up6 & up3, 1, np.where(~up6 & ~up3, -1, 0)).astype(np.int8)
    V = np.vstack([line, ema, chop, st])
    nu, nd, ns = (V == 1).sum(0), (V == -1).sum(0), (V == 0).sum(0)
    trend = np.where(ns >= 2, 0, np.where((nu >= 2) & (nu > nd), 1, np.where((nd >= 2) & (nd > nu), -1, 0))).astype(np.int8)
    return {"line": line, "ema": ema, "chop": chop, "st": st, "trend": trend, "ema_rsi": er}
