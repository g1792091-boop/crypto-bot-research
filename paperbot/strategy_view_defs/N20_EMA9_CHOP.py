"""Chart view for N20_EMA9_CHOP: its indicators (same parameters as the locked code) and entry conditions.

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


def view_N20_EMA9_CHOP(df, tf):
    """Short only: close crosses below EMA9 while ADX(14) < 20 (no strong trend). Exact."""
    c = _f(df["close"])
    e9 = _f(fg.ema(df["close"], 9))
    adx_line, _pdi, _mdi = fg.adx_dmi(df, 14)
    adx = _f(adx_line)
    with np.errstate(invalid="ignore"):
        short_c = [
            ("ADX 20 미만(추세 약함)", ~(adx >= 20)),
            ("종가 EMA9 아래", c < e9),
            ("직전 봉 종가는 EMA9 이상", _sh(c, 1) >= _sh(e9, 1)),
        ]
    return {
        "overlays": [
            {"name": "EMA 9", "values": e9},
        ],
        "panes": [
            {"name": "ADX 14", "series": [{"name": "ADX", "values": adx}], "levels": [20]},
        ],
        "long": [],
        "short": short_c,
    }
