"""Chart view for N01_ST_EMA: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_fast
import fg_indicators as fg
from strategies import recent, gt, lt, ge, le, cross_above, cross_below, _f


def view_N01_ST_EMA(df, tf):
    # locked: fg.ema(close, 5), fg.ema(close, 20), fg_fast.supertrend(df, 10, 6.0), sync 2
    ef = fg.ema(df["close"], 5)
    es = fg.ema(df["close"], 20)
    line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    up, down = cross_above(ef, es), cross_below(ef, es)
    d = _f(direction)
    dp = pd.Series(d).shift(1)
    flip_up = gt(d, 0) & le(dp, 0)
    flip_down = lt(d, 0) & ge(dp, 0)
    sync = 2
    return {
        "overlays": [
            {"name": "EMA 5", "values": _f(ef)},
            {"name": "EMA 20", "values": _f(es)},
            {"name": "슈퍼트렌드 (10, 6)", "values": _f(line)},
        ],
        "panes": [],
        "long": [
            ("슈퍼트렌드 상승", gt(direction, 0)),
            ("EMA5·20 상향교차(2봉 내)", recent(up, sync)),
            ("이번 봉 교차 또는 추세전환", np.asarray(up | flip_up, dtype=bool)),
        ],
        "short": [
            ("슈퍼트렌드 하락", lt(direction, 0)),
            ("EMA5·20 하향교차(2봉 내)", recent(down, sync)),
            ("이번 봉 교차 또는 추세전환", np.asarray(down | flip_down, dtype=bool)),
        ],
    }
