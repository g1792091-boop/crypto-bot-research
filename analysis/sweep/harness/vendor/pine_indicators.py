"""Pine-faithful indicator ports used by the V4.5 / V3.9 / OBV strategies.

Every function mirrors the Pine v6 source in the handover package
(01_STRATEGY_SOURCE).  Seeding follows Pine semantics: ta.ema / ta.rma are
seeded with the SMA of the first `length` finite values, exactly like
TradingView, so a long warm-up is not needed for parity.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------
def _first_full_window(x: np.ndarray, length: int) -> int:
    """Index of the first bar whose trailing window of `length` values is all finite."""
    finite = np.isfinite(x).astype(np.int64)
    if len(x) < length:
        return -1
    csum = np.concatenate([[0], np.cumsum(finite)])
    window_sum = csum[length:] - csum[:-length]  # sum over [i-length+1, i]
    idx = np.where(window_sum == length)[0]
    return int(idx[0] + length - 1) if len(idx) else -1


def _recursive_ma(x: np.ndarray, length: int, alpha: float) -> np.ndarray:
    n = len(x)
    out = np.full(n, np.nan)
    s = _first_full_window(x, length)
    if s < 0:
        return out
    out[s] = np.mean(x[s - length + 1 : s + 1])
    for i in range(s + 1, n):
        v = x[i]
        if np.isfinite(v):
            out[i] = alpha * v + (1.0 - alpha) * out[i - 1]
        else:
            out[i] = out[i - 1]  # nz(sum[1]) behaviour
    return out


def pine_ema(x: np.ndarray, length: int) -> np.ndarray:
    return _recursive_ma(np.asarray(x, dtype=float), int(length), 2.0 / (length + 1.0))


def pine_rma(x: np.ndarray, length: int) -> np.ndarray:
    return _recursive_ma(np.asarray(x, dtype=float), int(length), 1.0 / float(length))


def pine_sma(x: np.ndarray, length: int) -> np.ndarray:
    s = pd.Series(np.asarray(x, dtype=float))
    return s.rolling(int(length), min_periods=int(length)).mean().to_numpy()


def pine_highest(x: np.ndarray, length: int) -> np.ndarray:
    s = pd.Series(np.asarray(x, dtype=float))
    return s.rolling(int(length), min_periods=int(length)).max().to_numpy()


def pine_lowest(x: np.ndarray, length: int) -> np.ndarray:
    s = pd.Series(np.asarray(x, dtype=float))
    return s.rolling(int(length), min_periods=int(length)).min().to_numpy()


def shift1(x: np.ndarray) -> np.ndarray:
    out = np.empty_like(x, dtype=float)
    out[0] = np.nan
    out[1:] = x[:-1]
    return out


def crossover(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    pa, pb = shift1(a), shift1(b)
    with np.errstate(invalid="ignore"):
        return (a > b) & (pa <= pb)


def crossunder(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    pa, pb = shift1(a), shift1(b)
    with np.errstate(invalid="ignore"):
        return (a < b) & (pa >= pb)


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = shift1(close)
    prev_close[0] = close[0]  # nz(close[1], close)
    return np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))


# ---------------------------------------------------------------------------
# exchange-style SuperTrend (V4.5 / V3.9 f_exchangeSuperTrend, RMA mode)
# ---------------------------------------------------------------------------
def exchange_supertrend(high, low, close, atr_length: int, multiplier: float):
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(close)
    tr = true_range(high, low, close)
    atr = pine_rma(tr, atr_length)
    hl2 = (high + low) / 2.0
    basic_lower = hl2 - multiplier * atr
    basic_upper = hl2 + multiplier * atr
    lower = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    direction = np.ones(n, dtype=np.int8)
    line = np.full(n, np.nan)
    for i in range(n):
        bl, bu = basic_lower[i], basic_upper[i]
        prev_lower = lower[i - 1] if i > 0 and np.isfinite(lower[i - 1]) else bl
        prev_upper = upper[i - 1] if i > 0 and np.isfinite(upper[i - 1]) else bu
        prev_close = close[i - 1] if i > 0 else np.nan
        if np.isfinite(bl):
            lower[i] = max(bl, prev_lower) if (i > 0 and prev_close > prev_lower) else bl
        if np.isfinite(bu):
            upper[i] = min(bu, prev_upper) if (i > 0 and prev_close < prev_upper) else bu
        d = direction[i - 1] if i > 0 else 1
        if d == -1 and np.isfinite(prev_upper) and close[i] > prev_upper:
            d = 1
        elif d == 1 and np.isfinite(prev_lower) and close[i] < prev_lower:
            d = -1
        direction[i] = d
        line[i] = lower[i] if d == 1 else upper[i]
    return line, direction


# ---------------------------------------------------------------------------
# TradingView Chop Zone angle (f_chopAngle)
# ---------------------------------------------------------------------------
def chop_angle(high, low, close, ema_length: int = 34, range_length: int = 30, range_scale: float = 25.0):
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    avg = (high + low + close) / 3.0
    hh = pine_highest(high, range_length)
    ll = pine_lowest(low, range_length)
    price_range = hh - ll
    with np.errstate(divide="ignore", invalid="ignore"):
        span = np.where(price_range != 0.0, range_scale / price_range * ll, 0.0)
        ema = pine_ema(close, ema_length)
        ema_prev = shift1(ema)
        delta_y = np.where(avg != 0.0, (ema_prev - ema) / avg * span, 0.0)
    hyp = np.sqrt(1.0 + delta_y * delta_y)
    abs_angle = np.round(180.0 * np.arccos(1.0 / hyp) / math.pi)
    angle = np.where(delta_y > 0.0, -abs_angle, abs_angle)
    # Pine: na propagates when ema/hh/ll are na
    angle = np.where(np.isfinite(ema_prev) & np.isfinite(hh) & np.isfinite(ll), angle, np.nan)
    return angle


# ---------------------------------------------------------------------------
# shayankm STC (f_stc)
# ---------------------------------------------------------------------------
def stc(close, cycle_length: int = 12, fast_length: int = 26, slow_length: int = 50, factor: float = 0.5):
    close = np.asarray(close, dtype=float)
    n = len(close)
    macd = pine_ema(close, fast_length) - pine_ema(close, slow_length)
    macd_lowest = pine_lowest(macd, cycle_length)
    macd_range = pine_highest(macd, cycle_length) - macd_lowest
    first_stoch = np.zeros(n)
    first_smooth = np.zeros(n)
    second_stoch = np.zeros(n)
    result = np.zeros(n)
    for i in range(n):
        prev_fs = first_stoch[i - 1] if i > 0 else 0.0
        if np.isfinite(macd_range[i]) and macd_range[i] > 0.0:
            first_stoch[i] = (macd[i] - macd_lowest[i]) / macd_range[i] * 100.0
        else:
            first_stoch[i] = prev_fs
        if i == 0:
            first_smooth[i] = first_stoch[i]
        else:
            first_smooth[i] = first_smooth[i - 1] + factor * (first_stoch[i] - first_smooth[i - 1])
    fs_lowest = pine_lowest(first_smooth, cycle_length)
    fs_range = pine_highest(first_smooth, cycle_length) - fs_lowest
    for i in range(n):
        prev_ss = second_stoch[i - 1] if i > 0 else 0.0
        if np.isfinite(fs_range[i]) and fs_range[i] > 0.0:
            second_stoch[i] = (first_smooth[i] - fs_lowest[i]) / fs_range[i] * 100.0
        else:
            second_stoch[i] = prev_ss
        if i == 0:
            result[i] = second_stoch[i]
        else:
            result[i] = result[i - 1] + factor * (second_stoch[i] - result[i - 1])
    return result


# ---------------------------------------------------------------------------
# DMI / ADX (f_dmi, f_adx)
# ---------------------------------------------------------------------------
def dmi(high, low, close, length: int):
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    tr = true_range(high, low, close)
    up_move = high - shift1(high)
    down_move = shift1(low) - low
    with np.errstate(invalid="ignore"):
        plus_mv = np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0)
        minus_mv = np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0)
    str_ = pine_rma(tr, length)
    plus_r = pine_rma(plus_mv, length)
    minus_r = pine_rma(minus_mv, length)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = np.where(str_ != 0.0, 100.0 * plus_r / str_, 0.0)
        minus_di = np.where(str_ != 0.0, 100.0 * minus_r / str_, 0.0)
    plus_di = np.where(np.isfinite(str_), plus_di, np.nan)
    minus_di = np.where(np.isfinite(str_), minus_di, np.nan)
    return plus_di, minus_di


def adx(high, low, close, di_length: int, adx_length: int):
    plus_di, minus_di = dmi(high, low, close, di_length)
    s = plus_di + minus_di
    with np.errstate(divide="ignore", invalid="ignore"):
        dx = np.where(s != 0.0, 100.0 * np.abs(plus_di - minus_di) / s, 0.0)
    dx = np.where(np.isfinite(s), dx, np.nan)
    return pine_rma(dx, adx_length)


# ---------------------------------------------------------------------------
# oscillators
# ---------------------------------------------------------------------------
def pine_macd(close, fast: int, slow: int, signal: int):
    close = np.asarray(close, dtype=float)
    line = pine_ema(close, fast) - pine_ema(close, slow)
    sig = pine_ema(line, signal)
    return line, sig, line - sig


def pine_rsi(close, length: int):
    close = np.asarray(close, dtype=float)
    delta = np.diff(close, prepend=np.nan)
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    up[0] = np.nan
    down[0] = np.nan
    au = pine_rma(up, length)
    ad = pine_rma(down, length)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = au / ad
        out = np.where(ad == 0.0, 100.0, np.where(au == 0.0, 0.0, 100.0 - 100.0 / (1.0 + rs)))
    return np.where(np.isfinite(au) & np.isfinite(ad), out, np.nan)


def pine_stoch(close, high, low, length: int):
    close = np.asarray(close, dtype=float)
    hh = pine_highest(np.asarray(high, dtype=float), length)
    ll = pine_lowest(np.asarray(low, dtype=float), length)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 * (close - ll) / (hh - ll)
    return np.where(np.isfinite(out), out, np.nan)


def stoch_kd(close, high, low, length: int, k_smooth: int, d_smooth: int):
    raw = pine_stoch(close, high, low, length)
    k = pine_sma(raw, k_smooth)
    d = pine_sma(k, d_smooth)
    return k, d


def stoch_rsi_kd(close, rsi_length: int, stoch_length: int, k_smooth: int, d_smooth: int):
    r = pine_rsi(close, rsi_length)
    lo = pine_lowest(r, stoch_length)
    hi = pine_highest(r, stoch_length)
    rng = hi - lo
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.where(rng != 0.0, 100.0 * (r - lo) / rng, 0.0)
    raw = np.where(np.isfinite(rng), raw, np.nan)
    k = pine_sma(raw, k_smooth)
    d = pine_sma(k, d_smooth)
    return k, d


def ao_ac(high, low, fast: int = 5, slow: int = 34, ac_len: int = 5):
    hl2 = (np.asarray(high, dtype=float) + np.asarray(low, dtype=float)) / 2.0
    ao = pine_sma(hl2, fast) - pine_sma(hl2, slow)
    ac = ao - pine_sma(ao, ac_len)
    return ao, ac


def obv(close, volume):
    close = np.asarray(close, dtype=float)
    volume = np.nan_to_num(np.asarray(volume, dtype=float))
    change = np.diff(close, prepend=np.nan)
    sign = np.sign(np.nan_to_num(change))
    return np.cumsum(sign * volume)
