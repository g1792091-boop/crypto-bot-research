"""Chart view for N15_KC_AO: its indicators (same parameters as the locked code) and entry conditions.

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


def view_N15_KC_AO(df, tf):
    """Keltner(EMA20, ATR10, x2) re-entry + Awesome Oscillator(5,34). Exact."""
    h, l, c = _f(df["high"]), _f(df["low"]), _f(df["close"])
    up, _mid, lo = fg.keltner_channel(df, 20, 10, 2.0)
    upf, lof = _f(up), _f(lo)
    ao = _f(fg.awesome_oscillator(df, 5, 34))
    ao1 = _sh(ao, 1)
    with np.errstate(invalid="ignore"):
        long_c = [
            ("직전 봉 켈트너 하단 아래", _sh(l, 1) < _sh(lof, 1)),
            ("종가 켈트너 하단 위로 복귀", c > lof),
            ("AO 직전 봉보다 상승", ao > ao1),
            ("AO 0 위", ao > 0),
        ]
        short_c = [
            ("직전 봉 켈트너 상단 위", _sh(h, 1) > _sh(upf, 1)),
            ("종가 켈트너 상단 아래로 복귀", c < upf),
            ("AO 직전 봉보다 하락", ao < ao1),
            ("AO 0 아래", ao < 0),
        ]
    return {
        "overlays": [
            {"name": "켈트너 상단", "values": upf},
            {"name": "켈트너 하단", "values": lof},
        ],
        "panes": [
            {"name": "AO 5/34", "series": [{"name": "AO", "values": ao}], "levels": [0]},
        ],
        "long": long_c,
        "short": short_c,
    }
