"""Chart view for N23_HA_ST: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_fast
from strategies import gt, lt, le, shift_bool, _b, _f


def _arr_n23(x):
    """float ndarray of len(df); NaN kept."""
    return _f(x)


def _bool_n23(x):
    return np.asarray(x, dtype=bool)


def view_N23_HA_ST(df, tf):
    # locked: strategies.n23_heikin_supertrend
    #   Heikin-Ashi candle, wick <= 2 % of the HA candle range, fg_fast.supertrend_v2(df, 10, 6.0),
    #   signal only on the first bar the three conditions hold together (fresh).
    ha = fg_fast.heikin_ashi(df)
    line, up = fg_fast.supertrend_v2(df, 10, 6.0)
    up = _b(up)
    rng = (ha["ha_high"] - ha["ha_low"]).replace(0, np.nan)
    body_min = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).min(axis=1)
    body_max = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).max(axis=1)
    no_lower = le((body_min - ha["ha_low"]) / rng, 0.02)
    no_upper = le((ha["ha_high"] - body_max) / rng, 0.02)
    green = gt(ha["ha_close"], ha["ha_open"])
    red = lt(ha["ha_close"], ha["ha_open"])
    long_ok = green & no_lower & up
    short_ok = red & no_upper & (~up)
    body = _arr_n23(ha["ha_close"]) - _arr_n23(ha["ha_open"])
    # green and red are exclusive, so a fresh short can never coincide with a fresh long:
    # the locked "fresh_short & ~fresh_long" equals fresh_short.
    return {
        "overlays": [
            {"name": "슈퍼트렌드 (10, 6)", "values": _arr_n23(line)},
        ],
        "panes": [
            {"name": "하이킨아시 캔들 몸통",
             "series": [{"name": "몸통(+양봉/−음봉)", "values": body}],
             "levels": [0]},
        ],
        "long": [
            ("하이킨아시 양봉", _bool_n23(green)),
            ("하이킨아시 아래꼬리 거의 없음", _bool_n23(no_lower)),
            ("슈퍼트렌드 상승", _bool_n23(up)),
            ("새로 충족(직전 봉은 아님)", _bool_n23(~shift_bool(long_ok, 1))),
        ],
        "short": [
            ("하이킨아시 음봉", _bool_n23(red)),
            ("하이킨아시 위꼬리 거의 없음", _bool_n23(no_upper)),
            ("슈퍼트렌드 하락", _bool_n23(~up)),
            ("새로 충족(직전 봉은 아님)", _bool_n23(~shift_bool(short_ok, 1))),
        ],
    }
