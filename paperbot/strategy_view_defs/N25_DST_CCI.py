"""Chart view for N25_DST_CCI: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import fg_fast
from strategies import cross_above, cross_below, _b, _f


def _arr_n23(x):
    """float ndarray of len(df); NaN kept."""
    return _f(x)


def _bool_n23(x):
    return np.asarray(x, dtype=bool)


def view_N25_DST_CCI(df, tf):
    # locked: strategies.n25_double_supertrend_cci -- supertrend_v2(10, 6) and (20, 6), fg_fast.cci(df, 20)
    #   long  = trend_long | (range_long & ~trend_short)          which reduces to
    #           CCI crosses above -100  AND  NOT (both supertrends down)
    #   short = CCI crosses below +100  AND  NOT (both supertrends up)
    #   (the two CCI crosses can never happen on one bar, so the "& ~long" parts never bind.)
    fast_line, fast_up = fg_fast.supertrend_v2(df, 10, 6.0)
    slow_line, slow_up = fg_fast.supertrend_v2(df, 20, 6.0)
    fast_up, slow_up = _b(fast_up), _b(slow_up)
    c = fg_fast.cci(df, 20)
    c_up = cross_above(c, -100.0)
    c_down = cross_below(c, 100.0)
    return {
        "overlays": [
            {"name": "슈퍼트렌드 빠른선 (10, 6)", "values": _arr_n23(fast_line)},
            {"name": "슈퍼트렌드 느린선 (20, 6)", "values": _arr_n23(slow_line)},
        ],
        "panes": [
            {"name": "CCI 20", "series": [{"name": "CCI", "values": _arr_n23(c)}], "levels": [-100, 100]},
        ],
        "long": [
            ("두 슈퍼트렌드 중 하나 이상 상승", _bool_n23(fast_up | slow_up)),
            ("CCI가 -100 위로(이번 봉)", _bool_n23(c_up)),
        ],
        "short": [
            ("두 슈퍼트렌드 중 하나 이상 하락", _bool_n23((~fast_up) | (~slow_up))),
            ("CCI가 100 아래로(이번 봉)", _bool_n23(c_down)),
        ],
    }
