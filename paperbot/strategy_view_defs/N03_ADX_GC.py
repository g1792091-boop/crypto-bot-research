"""Chart view for N03_ADX_GC: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1, "window500_lastbar_SOL1h_long_precision": "1/2", "window500_lastbar_ETH5m_long_recall": "2/4", "window300_lastbar_ETH5m_long_recall": "1/4"}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
from strategies import recent, cross_above, cross_below, ge


def _arr(x):
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def view_N03_ADX_GC(df, tf):
    # locked: strategies.n03_adx_golden_cross (no timeframe scaling)
    ef = fg.ema(df["close"], 50)
    es = fg.ema(df["close"], 200)
    _p, _m, adx = fg.dmi_adx(df, 14, 14)
    gc, dc = cross_above(ef, es), cross_below(ef, es)
    adx_evt = cross_above(adx, 25.0)
    adx_ok = ge(adx, 25.0)
    adx_recent = recent(adx_evt, 3)
    return {
        "overlays": [
            {"name": "EMA 50", "values": _arr(ef)},
            {"name": "EMA 200", "values": _arr(es)},
        ],
        "panes": [
            {"name": "ADX 14",
             "series": [{"name": "ADX", "values": _arr(adx)}],
             "levels": [25]},
        ],
        "long": [
            ("EMA 골든크로스(3봉 내)", recent(gc, 3)),
            ("ADX 25 상향교차(3봉 내)", adx_recent),
            ("ADX 25 이상", adx_ok),
            ("두 교차 중 하나가 이번 봉", np.asarray(gc | adx_evt, dtype=bool)),
        ],
        "short": [
            ("EMA 데드크로스(3봉 내)", recent(dc, 3)),
            ("ADX 25 상향교차(3봉 내)", adx_recent),
            ("ADX 25 이상", adx_ok),
            ("두 교차 중 하나가 이번 봉", np.asarray(dc | adx_evt, dtype=bool)),
        ],
    }
