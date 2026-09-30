"""Chart view for S2_ST_ROC: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_fast
import fg_indicators as fg
from strategies import recent, gt, lt, ge, le, cross_above, cross_below, _f


def view_S2_ST_ROC(df, tf):
    # locked: fg_fast.supertrend(df, 10, 6.0), fg.roc(close, 9)
    line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    r = fg.roc(df["close"], 9)
    d = _f(direction)
    dp = pd.Series(d).shift(1)
    flip_up = gt(d, 0) & le(dp, 0)
    flip_down = lt(d, 0) & ge(dp, 0)
    roc_up = cross_above(r, 0.0)
    roc_down = cross_below(r, 0.0)
    return {
        "overlays": [
            {"name": "슈퍼트렌드 (10, 6)", "values": _f(line)},
        ],
        "panes": [
            {"name": "ROC 9", "series": [{"name": "ROC", "values": _f(r)}], "levels": [0]},
        ],
        "long": [
            ("슈퍼트렌드 상승", gt(d, 0)),
            ("ROC 0 위", gt(r, 0)),
            ("이번 봉 추세전환/ROC 돌파", np.asarray(flip_up | roc_up, dtype=bool)),
        ],
        "short": [
            ("슈퍼트렌드 하락", lt(d, 0)),
            ("ROC 0 아래", lt(r, 0)),
            ("이번 봉 추세전환/ROC 이탈", np.asarray(flip_down | roc_down, dtype=bool)),
        ],
    }
