"""Chart view for N19_FIB_CHOP: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg


def _f(x):
    if isinstance(x, pd.Series):
        x = x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _sh(x, k=1):
    x = _f(x)
    out = np.full(len(x), np.nan)
    if k > 0:
        out[k:] = x[:-k]
    else:
        out[:] = x
    return out


def _roll_min(x, n):
    return pd.Series(_f(x)).rolling(n, min_periods=n).min().to_numpy()


def _roll_max(x, n):
    return pd.Series(_f(x)).rolling(n, min_periods=n).max().to_numpy()


def view_N19_FIB_CHOP(df, tf):
    """50% level of the 34-bar range that ends 3 bars ago + Chop Zone slope (EMA34 / ATR14). Exact."""
    o, h, l, c = (_f(df[k]) for k in ("open", "high", "low", "close"))
    a = _f(fg.atr(df, 14))
    hh = _sh(_roll_max(h, 34), 3)
    ll = _sh(_roll_min(l, 34), 3)
    mid = ll + 0.5 * (hh - ll)
    base = fg.ema(df["close"], 34)
    slope = _f((base - base.shift(3)) / fg.atr(df, 14).replace(0, np.nan))
    with np.errstate(invalid="ignore"):
        long_c = [
            ("저가가 50% 선 근처 터치", l <= mid + 0.2 * a),
            ("종가 50% 선 위", c > mid),
            ("양봉 마감", c > o),
            ("추세 기울기 0.2 이상(상승)", slope >= 0.20),
        ]
        short_c = [
            ("고가가 50% 선 근처 터치", h >= mid - 0.2 * a),
            ("종가 50% 선 아래", c < mid),
            ("음봉 마감", c < o),
            ("추세 기울기 -0.2 이하(하락)", slope <= -0.20),
        ]
    return {
        "overlays": [
            {"name": "34봉 고점", "values": hh},
            {"name": "34봉 저점", "values": ll},
            {"name": "피보 50% 선", "values": mid},
        ],
        "panes": [
            {"name": "초프존 기울기(EMA34)", "series": [{"name": "기울기", "values": slope}],
             "levels": [-0.2, 0.2]},
        ],
        "long": long_c,
        "short": short_c,
    }
