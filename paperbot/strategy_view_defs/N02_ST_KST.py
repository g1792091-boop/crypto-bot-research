"""Chart view for N02_ST_KST: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1, "window300_lastbar_BTC15m_short_recall": "56/57", "window300_lastbar_ETH5m_long_precision": "53/59", "window300_lastbar_ETH5m_short_recall": "51/58"}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
import fg_fast
from strategies import recent, cross_above, cross_below, gt, lt, ge, le


def _arr(x):
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def view_N02_ST_KST(df, tf):
    # locked: strategies.n02_supertrend_kst (no timeframe scaling)
    _line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    line = _arr(_line)
    d = _arr(direction)
    kline, ksig = fg.kst(df["close"], (10, 15, 20, 30), (10, 10, 10, 15), 9)
    up, down = cross_above(kline, ksig), cross_below(kline, ksig)
    dp = pd.Series(d).shift(1)
    flip_up = gt(d, 0) & le(dp, 0)
    flip_down = lt(d, 0) & ge(dp, 0)
    st_up = gt(d, 0)
    st_down = lt(d, 0)
    return {
        "overlays": [
            {"name": "슈퍼트렌드(상승)", "values": np.where(st_up, line, np.nan)},
            {"name": "슈퍼트렌드(하락)", "values": np.where(st_down, line, np.nan)},
        ],
        "panes": [
            {"name": "KST",
             "series": [{"name": "KST", "values": _arr(kline)},
                        {"name": "신호선", "values": _arr(ksig)}],
             "levels": []},  # rule is KST vs its signal line only; no fixed level
        ],
        "long": [
            ("슈퍼트렌드 상승", st_up),
            ("KST 신호선 상향교차(2봉 내)", recent(up, 2)),
            ("교차 또는 상승전환이 이번 봉", np.asarray(up | flip_up, dtype=bool)),
        ],
        "short": [
            ("슈퍼트렌드 하락", st_down),
            ("KST 신호선 하향교차(2봉 내)", recent(down, 2)),
            ("교차 또는 하락전환이 이번 봉", np.asarray(down | flip_down, dtype=bool)),
        ],
    }
