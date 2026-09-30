"""Chart view for N11_BREAKAWAY: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg


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


def view_N11_BREAKAWAY(df, tf):
    # locked: ports12.n11 (5-bar breakaway; bar 5 = this bar; sizes in ATR14; prior trend variant 0)
    o, h, l, c, a = _ohlca(df)
    b = c - o
    B1, B2, B3, B4, B5 = (_lag(b, k) for k in (4, 3, 2, 1, 0))
    O2, C1, C2 = _lag(o, 3), _lag(c, 4), _lag(c, 3)
    up_prior, dn_prior = _prior_trend(c, 4, 5)
    with np.errstate(invalid="ignore"):
        small34 = (np.abs(B3) <= 0.4 * a) & (np.abs(B4) <= 0.4 * a)
        l_bar1 = (B1 < 0) & (-B1 >= 0.8 * a)
        l_bar2 = (B2 < 0) & (O2 <= C1 + 0.05 * a)
        l_bar5 = (B5 > 0) & (B5 >= 0.8 * a) & (c > C2)
        s_bar1 = (B1 > 0) & (B1 >= 0.8 * a)
        s_bar2 = (B2 > 0) & (O2 >= C1 - 0.05 * a)
        s_bar5 = (B5 < 0) & (-B5 >= 0.8 * a) & (c < C2)
    return {
        "overlays": [],
        "panes": [],
        "long": [
            ("그 전 5봉 하락 흐름", np.asarray(dn_prior, bool)),
            ("4봉 전 큰 음봉", np.asarray(l_bar1, bool)),
            ("3봉 전 더 낮게 음봉", np.asarray(l_bar2, bool)),
            ("그 뒤 2봉은 작은 몸통", np.asarray(small34, bool)),
            ("이번 봉 큰 양봉 반등", np.asarray(l_bar5, bool)),
        ],
        "short": [
            ("그 전 5봉 상승 흐름", np.asarray(up_prior, bool)),
            ("4봉 전 큰 양봉", np.asarray(s_bar1, bool)),
            ("3봉 전 더 높게 양봉", np.asarray(s_bar2, bool)),
            ("그 뒤 2봉은 작은 몸통", np.asarray(small34, bool)),
            ("이번 봉 큰 음봉 하락", np.asarray(s_bar5, bool)),
        ],
    }
