"""Chart view for S4_BB_BBP: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
from strategies import recent, gt, lt, ge, le, shift_bool


def _arr(x):
    """float ndarray of len(df); NaN kept."""
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def view_S4_BB_BBP(df, tf):
    # locked: ports12.s4 -> Bollinger(20, 2.0), squeeze = bandwidth <= rolling 100-bar 20th pct
    # on any of the previous 5 bars, close crosses the band, Bull/Bear Power(13) sign
    close = df["close"]
    up, _mid, lo, bw = fg.bollinger_bands(close, 20, 2.0)
    thr = fg.rolling_percentile_threshold(bw, 100, 0.2)
    sq = le(bw, thr)
    sq_prev = recent(shift_bool(sq, 1), 5)          # any of t-1..t-5
    _bu, _be, bbp = fg.bull_bear_power(df, 13)
    brk_up = gt(close, up) & le(close.shift(1), up.shift(1))
    brk_dn = lt(close, lo) & ge(close.shift(1), lo.shift(1))
    return {
        "overlays": [
            {"name": "볼린저 상단(20, 2)", "values": _arr(up)},
            {"name": "볼린저 하단(20, 2)", "values": _arr(lo)},
        ],
        "panes": [
            {"name": "볼린저 밴드폭",
             "series": [{"name": "밴드폭", "values": _arr(bw)},
                        {"name": "수축 기준(하위 20%)", "values": _arr(thr)}],
             "levels": []},
            {"name": "불베어 파워 13",
             "series": [{"name": "파워", "values": _arr(bbp)}],
             "levels": [0]},
        ],
        "long": [
            ("밴드 수축(직전 5봉 내)", sq_prev),
            ("이번 봉 볼린저 상단 돌파", np.asarray(brk_up, dtype=bool)),
            ("불베어 파워 0 위", gt(bbp, 0.0)),
        ],
        "short": [
            ("밴드 수축(직전 5봉 내)", sq_prev),
            ("이번 봉 볼린저 하단 이탈", np.asarray(brk_dn, dtype=bool)),
            ("불베어 파워 0 아래", lt(bbp, 0.0)),
        ],
    }
