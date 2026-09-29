"""Numpy re-implementations of the slow (row-loop / rolling-apply) FINGRAD
indicators.  Semantics are identical to fg_indicators (verified by
test_fg_fast.py); only the execution speed differs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

import fg_indicators as fg


def supertrend(df: pd.DataFrame, atr_length: int = 10, multiplier: float = 3.0):
    """FINGRAD supertrend: flips compare close against the CURRENT final bands."""
    atr = fg.atr(df, atr_length).to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr
    n = len(df)
    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    direction = np.full(n, np.nan)
    line = np.full(n, np.nan)
    for i in range(1, n):
        if not np.isfinite(atr[i]):
            continue
        prev_close = close[i - 1]
        fu_prev = final_upper[i - 1]
        fl_prev = final_lower[i - 1]
        if (not np.isfinite(fu_prev)) or (basic_upper[i] < fu_prev or prev_close > fu_prev):
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = fu_prev
        if (not np.isfinite(fl_prev)) or (basic_lower[i] > fl_prev or prev_close < fl_prev):
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = fl_prev
        prev_dir = direction[i - 1]
        if not np.isfinite(prev_dir):
            prev_dir = 1.0 if close[i] >= final_lower[i] else -1.0
        if prev_dir < 0 and close[i] > final_upper[i]:
            cur = 1.0
        elif prev_dir > 0 and close[i] < final_lower[i]:
            cur = -1.0
        else:
            cur = prev_dir
        direction[i] = cur
        line[i] = final_lower[i] if cur > 0 else final_upper[i]
    idx = df.index
    return (
        pd.Series(line, index=idx),
        pd.Series(direction, index=idx),
        pd.Series(final_upper, index=idx),
        pd.Series(final_lower, index=idx),
    )


def supertrend_v2(df: pd.DataFrame, atr_length: int = 10, multiplier: float = 3.0):
    line, direction, _u, _l = supertrend(df, atr_length, multiplier)
    return line, direction.fillna(0.0) > 0.0


def parabolic_sar(df: pd.DataFrame, acceleration=0.02, acceleration_step=0.02, acceleration_max=0.2):
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)
    sar = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    if n < 2:
        return pd.Series(sar, index=df.index), pd.Series(direction, index=df.index)
    uptrend = bool(close[1] >= close[0])
    ep = float(high[:2].max() if uptrend else low[:2].min())
    cur = float(low[:2].min() if uptrend else high[:2].max())
    af = float(acceleration)
    sar[1] = cur
    direction[1] = 1.0 if uptrend else -1.0
    for i in range(2, n):
        cur = cur + af * (ep - cur)
        if uptrend:
            cur = min(cur, low[i - 1], low[i - 2])
            if low[i] < cur:
                uptrend = False
                cur = ep
                ep = low[i]
                af = float(acceleration)
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(float(acceleration_max), af + float(acceleration_step))
        else:
            cur = max(cur, high[i - 1], high[i - 2])
            if high[i] > cur:
                uptrend = True
                cur = ep
                ep = high[i]
                af = float(acceleration)
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(float(acceleration_max), af + float(acceleration_step))
        sar[i] = cur
        direction[i] = 1.0 if uptrend else -1.0
    return pd.Series(sar, index=df.index), pd.Series(direction, index=df.index)


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    n = len(df)
    ha_close = (o + h + l + c) / 4.0
    ha_open = np.full(n, np.nan)
    if n:
        ha_open[0] = (o[0] + c[0]) / 2.0
        for i in range(1, n):
            ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0
    out = pd.DataFrame(index=df.index)
    out["ha_close"] = ha_close
    out["ha_open"] = ha_open
    out["ha_high"] = np.nanmax(np.vstack([h, ha_open, ha_close]), axis=0)
    out["ha_low"] = np.nanmin(np.vstack([l, ha_open, ha_close]), axis=0)
    return out


def aroon(df: pd.DataFrame, length: int = 25):
    length = max(2, int(length))
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(df)
    up = np.full(n, np.nan)
    down = np.full(n, np.nan)
    if n >= length:
        wh = sliding_window_view(high, length)[:, ::-1]
        wl = sliding_window_view(low, length)[:, ::-1]
        idx_up = np.argmax(wh, axis=1)
        idx_dn = np.argmin(wl, axis=1)
        up[length - 1 :] = 100.0 * (length - idx_up) / length
        down[length - 1 :] = 100.0 * (length - idx_dn) / length
        # NaN windows -> NaN (pandas rolling gives NaN when window has NaN)
        bad = np.isnan(wh).any(axis=1) | np.isnan(wl).any(axis=1)
        up[length - 1 :][bad] = np.nan
        down[length - 1 :][bad] = np.nan
    return pd.Series(up, index=df.index), pd.Series(down, index=df.index)


def cci(df: pd.DataFrame, length: int = 20) -> pd.Series:
    typical = ((df["high"] + df["low"] + df["close"]) / 3.0).to_numpy(dtype=float)
    n = len(df)
    out = np.full(n, np.nan)
    if n >= length:
        w = sliding_window_view(typical, length)
        mean = w.mean(axis=1)
        md = np.abs(w - mean[:, None]).mean(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            val = (typical[length - 1 :] - mean) / (0.015 * np.where(md == 0, np.nan, md))
        out[length - 1 :] = val
    return pd.Series(out, index=df.index)
