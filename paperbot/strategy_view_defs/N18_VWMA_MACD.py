"""Chart view for N18_VWMA_MACD: its indicators (same parameters as the locked code) and entry conditions.

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


def view_N18_VWMA_MACD(df, tf):
    # locked: fg.vwma(df, 20), fg.macd(close, 12, 26, 9), synchronized 2
    v = fg.vwma(df, 20)
    ml, sl, h = fg.macd(df["close"], 12, 26, 9)
    up, down = cross_above(ml, sl), cross_below(ml, sl)
    above, below = gt(df["close"], v), lt(df["close"], v)
    hist_up, hist_down = gt(h, h.shift(1)), lt(h, h.shift(1))
    ml_pos, ml_neg = gt(ml, 0.0), lt(ml, 0.0)
    long_sync = synchronized([up, above, hist_up, ml_pos], 2)
    short_sync = synchronized([down, below, hist_down, ml_neg], 2)
    ready = np.isfinite(_arr(v)) & np.isfinite(_arr(h))   # all-False until VWMA and MACD signal exist
    return {
        "overlays": [
            {"name": "VWMA 20", "values": _arr(v)},
        ],
        "panes": [
            {"name": "MACD 12·26·9",
             "series": [{"name": "MACD", "values": _arr(ml)},
                        {"name": "시그널", "values": _arr(sl)},
                        {"name": "히스토그램", "values": _arr(h)}],
             "levels": [0]},
        ],
        "long": [
            ("골든크로스·0 위(최근 3봉)", _bool(recent(up, 3) & recent(ml_pos, 3) & ready)),
            ("종가가 VWMA 위(최근 3봉)", _bool(recent(above, 3) & ready)),
            ("히스토그램 커짐(최근 3봉)", _bool(recent(hist_up, 3) & ready)),
            ("모두 2봉 안에 함께", _bool(long_sync & ready)),
        ],
        "short": [
            ("데드크로스·0 아래(최근 3봉)", _bool(recent(down, 3) & recent(ml_neg, 3) & ready)),
            ("종가가 VWMA 아래(최근 3봉)", _bool(recent(below, 3) & ready)),
            ("히스토그램 작아짐(최근 3봉)", _bool(recent(hist_down, 3) & ready)),
            ("모두 2봉 안에 함께", _bool(short_sync & ready)),
            ("롱 신호와 겹치지 않음", _bool(~long_sync & ready)),
        ],
    }
