"""Chart view for N13_3OUTSIDE: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
from strategies import shift_bool


def _arr(x):
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _lag(x, k):
    """value of x k bars ago (NaN for the first k bars); past bars only."""
    x = _arr(x)
    out = np.full(len(x), np.nan)
    if k > 0:
        out[k:] = x[:-k]
    else:
        out[:] = x
    return out


def _ohlca(df):
    o, h, l, c = (_arr(df[k]) for k in ("open", "high", "low", "close"))
    a = _arr(fg.atr(df, 14))
    return o, h, l, c, a


def _prior_trend(c, first_lag, n=5):
    """ports12._prior_dir variant 0: close just before the pattern's first bar vs the close
    n bars before the pattern (pattern's first bar = first_lag bars ago)."""
    last = _lag(c, first_lag + 1)
    first = _lag(c, first_lag + n)
    with np.errstate(invalid="ignore"):
        return last > first, last < first


def _roll_max(x, n):
    return pd.Series(_arr(x)).rolling(n, min_periods=n).max().to_numpy()


def _roll_min(x, n):
    return pd.Series(_arr(x)).rolling(n, min_periods=n).min().to_numpy()


def view_N13_3OUTSIDE(df, tf):
    # locked: ports12.n13 (Three Outside Up/Down, prior trend variant 0, ATR14; breakout of the
    # 3-bar pattern high/low by a close 1 or 2 bars after the pattern)
    o, h, l, c, a = _ohlca(df)
    b = c - o
    up_prior, dn_prior = _prior_trend(c, 2, 5)
    B1, B2, B3 = _lag(b, 2), _lag(b, 1), b
    O1, C1, O2, C2 = _lag(o, 2), _lag(c, 2), _lag(o, 1), _lag(c, 1)
    with np.errstate(invalid="ignore"):
        bull = dn_prior & (B1 < 0) & (B2 > 0) & (B2 >= 0.5 * a) & (O2 <= C1) & (C2 >= O1) & (B3 > 0) & (c > C2)
        bear = up_prior & (B1 > 0) & (B2 < 0) & (-B2 >= 0.5 * a) & (O2 >= C1) & (C2 <= O1) & (B3 < 0) & (c < C2)
    ph3, pl3 = _roll_max(h, 3), _roll_min(l, 3)     # high / low of the 3 pattern bars
    # at most one pattern of each kind can finish inside any 3 consecutive bars, so the
    # level of "the" pattern finished 1 or 2 bars ago is well defined
    bull1, bull2 = shift_bool(bull, 1), shift_bool(bull, 2)
    bear1, bear2 = shift_bool(bear, 1), shift_bool(bear, 2)
    hi_lvl = np.where(bull1, _lag(ph3, 1), np.where(bull2, _lag(ph3, 2), np.nan))
    lo_lvl = np.where(bear1, _lag(pl3, 1), np.where(bear2, _lag(pl3, 2), np.nan))
    # chart line: the level drawn from the bar the pattern finishes through the 2-bar window
    hi_line = np.where(bull, ph3, hi_lvl)
    lo_line = np.where(bear, pl3, lo_lvl)
    c1 = _lag(c, 1)
    with np.errstate(invalid="ignore"):
        l_above = c > hi_lvl
        l_first = c1 <= hi_lvl
        s_below = c < lo_lvl
        s_first = c1 >= lo_lvl
    return {
        "overlays": [
            {"name": "상승 패턴 고점", "values": hi_line},
            {"name": "하락 패턴 저점", "values": lo_line},
        ],
        "panes": [],
        "long": [
            ("상승 장악형 3봉(1~2봉 전)", bull1 | bull2),
            ("종가가 패턴 고점 위", np.asarray(l_above, bool)),
            ("이번 봉에 처음 돌파", np.asarray(l_first, bool)),
        ],
        "short": [
            ("하락 장악형 3봉(1~2봉 전)", bear1 | bear2),
            ("종가가 패턴 저점 아래", np.asarray(s_below, bool)),
            ("이번 봉에 처음 이탈", np.asarray(s_first, bool)),
        ],
    }
