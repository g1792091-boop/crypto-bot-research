"""Chart view for N22_VORTEX_PSAR: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1, "window300_500_lastbar_recall_precision": 1}
"""

import numpy as np
import pandas as pd

import fg_fast
import fg_indicators as fg
from strategies import recent, synchronized, gt, lt, ge, le, cross_above, cross_below, _b, _f


def _arr(x):
    return _f(x)


def _bool(x):
    return np.asarray(x, dtype=bool)


def view_N22_VORTEX_PSAR(df, tf):
    # locked: fg.vortex_indicator(df, 14), fg_fast.parabolic_sar(df, 0.02, 0.02, 0.20)
    plus, minus = fg.vortex_indicator(df, 14)
    psar, _d = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.20)
    up, down = cross_above(plus, minus), cross_below(plus, minus)
    above, below = gt(df["close"], psar), lt(df["close"], psar)
    ready = np.isfinite(_arr(psar)) & np.isfinite(_arr(plus)) & np.isfinite(_arr(minus))  # all-False during warm-up
    return {
        "overlays": [
            {"name": "파라볼릭 SAR", "values": _arr(psar)},
        ],
        "panes": [
            {"name": "보텍스 14",
             "series": [{"name": "VI+", "values": _arr(plus)},
                        {"name": "VI-", "values": _arr(minus)}],
             "levels": []},
        ],
        "long": [
            ("종가가 SAR 위", _bool(above & ready)),
            ("VI+가 위로 교차(이번 봉)", _bool(up & ready)),
        ],
        "short": [
            ("종가가 SAR 아래", _bool(below & ready)),
            ("VI+가 아래로 교차(이번 봉)", _bool(down & ready)),
        ],
    }
