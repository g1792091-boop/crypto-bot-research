"""Chart view for N04_ST_KLINGER: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
import fg_fast
from strategies import recent, gt, lt, cross_above, cross_below


def _arr(x):
    """float ndarray of len(df); NaN kept."""
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _lag(x, k):
    """x shifted k bars into the past (NaN for the first k bars); never looks forward."""
    x = _arr(x)
    out = np.full(len(x), np.nan)
    if k > 0:
        out[k:] = x[:-k]
    else:
        out[:] = x
    return out


def view_N04_ST_KLINGER(df, tf):
    # locked: ports12.n04 -> fg_fast.supertrend(df, 10, 6.0), Klinger(34, 55, 13), sync 2
    _line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    line = _arr(_line)
    d = _arr(direction)
    kl, ks = fg.klinger_oscillator(df, 34, 55, 13)
    up, dn = cross_above(kl, ks), cross_below(kl, ks)
    dp = _lag(d, 1)
    with np.errstate(invalid="ignore"):
        flip_up = (d > 0) & (dp <= 0)
        flip_down = (d < 0) & (dp >= 0)
    st_up, st_down = gt(d, 0), lt(d, 0)
    return {
        "overlays": [
            {"name": "슈퍼트렌드(상승)", "values": np.where(st_up, line, np.nan)},
            {"name": "슈퍼트렌드(하락)", "values": np.where(st_down, line, np.nan)},
        ],
        "panes": [
            {"name": "클링어 (34, 55, 13)",
             "series": [{"name": "클링어", "values": _arr(kl)},
                        {"name": "신호선", "values": _arr(ks)}],
             "levels": [0]},
        ],
        "long": [
            ("슈퍼트렌드 상승", st_up),
            ("클링어 신호선 상향교차(2봉 내)", recent(up, 2)),
            ("교차 또는 상승전환이 이번 봉", np.asarray(up | flip_up, dtype=bool)),
        ],
        "short": [
            ("슈퍼트렌드 하락", st_down),
            ("클링어 신호선 하향교차(2봉 내)", recent(dn, 2)),
            ("교차 또는 하락전환이 이번 봉", np.asarray(dn | flip_down, dtype=bool)),
        ],
    }
