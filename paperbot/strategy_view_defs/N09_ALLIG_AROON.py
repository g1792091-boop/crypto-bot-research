"""Chart view for N09_ALLIG_AROON: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
import fg_fast
from strategies import recent, shift_bool, cross_above, cross_below, gt, lt, ge, le


def _arr_n09(x):
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def view_N09_ALLIG_AROON(df, tf):
    # locked: strategies.n09_alligator_aroon (no timeframe scaling), sync = 2
    close = df["close"]
    lips, teeth, jaw = fg.sma(close, 5), fg.sma(close, 8), fg.sma(close, 13)
    lips_above = gt(lips, teeth) & gt(lips, jaw)
    lips_below = lt(lips, teeth) & lt(lips, jaw)
    a_up = lips_above & ~shift_bool(lips_above, 1)
    a_down = lips_below & ~shift_bool(lips_below, 1)
    up, down = fg_fast.aroon(df, 25)
    ar_up, ar_down = cross_above(up, down), cross_below(up, down)
    diff = _arr_n09(up) - _arr_n09(down)
    return {
        "overlays": [
            {"name": "입술선(5봉 평균)", "values": _arr_n09(lips)},
            {"name": "이빨선(8봉 평균)", "values": _arr_n09(teeth)},
            {"name": "턱선(13봉 평균)", "values": _arr_n09(jaw)},
        ],
        "panes": [
            {"name": "아룬 25",
             "series": [{"name": "아룬 상승", "values": _arr_n09(up)},
                        {"name": "아룬 하락", "values": _arr_n09(down)}],
             "levels": []},
        ],
        "long": [
            ("입술선이 이빨·턱선 위", np.asarray(lips_above, dtype=bool)),
            ("입술선이 위로 올라섬(2봉 내)", recent(a_up, 2)),
            ("아룬 상승이 하락 추월(2봉 내)", recent(ar_up, 2)),
            ("아룬 상승 ≥ 아룬 하락", ge(diff, 0.0)),
            ("두 신호 중 하나가 이번 봉", np.asarray(a_up | ar_up, dtype=bool)),
        ],
        "short": [
            ("입술선이 이빨·턱선 아래", np.asarray(lips_below, dtype=bool)),
            ("입술선이 아래로 내려감(2봉 내)", recent(a_down, 2)),
            ("아룬 하락이 상승 추월(2봉 내)", recent(ar_down, 2)),
            ("아룬 하락 ≥ 아룬 상승", ge(-diff, 0.0)),
            ("두 신호 중 하나가 이번 봉", np.asarray(a_down | ar_down, dtype=bool)),
        ],
    }
