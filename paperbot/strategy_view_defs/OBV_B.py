"""Chart view for OBV_B: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import pine_indicators as pi
from strategies import _f, shift_bool


def _bool(x):
    return np.asarray(x, dtype=bool)


def _empty_view_obvb(view):
    """Same layout with zero-length arrays (used for an empty frame)."""
    return {
        "overlays": [dict(o, values=o["values"][:0]) for o in view["overlays"]],
        "panes": [dict(p, series=[dict(s, values=s["values"][:0]) for s in p["series"]]) for p in view["panes"]],
        "long": [(lab, c[:0]) for lab, c in view["long"]],
        "short": [(lab, c[:0]) for lab, c in view["short"]],
    }


def _one_nan_bar():
    return pd.DataFrame({c: [np.nan] for c in ("open", "high", "low", "close", "volume")})


def view_OBV_B(df, tf):
    # locked (strategies.obv_b, defaults on every timeframe): OBV vs its SMA 9 cross,
    # AC(5,34,5) > 0 and rising (long) / < 0 and falling (short), STC(12,26,50,0.5) < 70 / > 30
    if len(df) == 0:  # pi.shift1 cannot index an empty array (the locked obv_b fails too)
        return _empty_view_obvb(view_OBV_B(_one_nan_bar(), tf))
    high, low, close = _f(df["high"]), _f(df["low"]), _f(df["close"])
    vol = _f(df["volume"])
    o = pi.obv(close, vol)
    break_ma = pi.pine_sma(o, 9)
    _ao, ac = pi.ao_ac(high, low, 5, 34, 5)
    ac_p = pi.shift1(ac)
    stc_v = pi.stc(close, 12, 26, 50, 0.5)
    with np.errstate(invalid="ignore"):
        ac_pos_rising = (ac > 0.0) & (ac > ac_p)
        ac_neg_falling = (ac < 0.0) & (ac < ac_p)
        stc_long_ok = stc_v < 70.0
        stc_short_ok = stc_v > 30.0
    up, down = pi.crossover(o, break_ma), pi.crossunder(o, break_ma)
    return {
        "overlays": [],
        "panes": [
            {"name": "OBV (거래량 흐름)",
             "series": [{"name": "OBV", "values": _f(o)},
                        {"name": "9봉 평균", "values": _f(break_ma)}],
             "levels": []},
            {"name": "AC 가속도 (5·34·5)",
             "series": [{"name": "AC", "values": _f(ac)}],
             "levels": [0]},
        ],
        "long": [
            ("OBV가 9봉 평균 위로 교차", _bool(up)),
            ("AC 0 위, 전 봉보다 상승", _bool(ac_pos_rising)),
            ("STC 70 미만(과열 아님)", _bool(stc_long_ok)),
        ],
        "short": [
            ("OBV가 9봉 평균 아래로 교차", _bool(down)),
            ("AC 0 아래, 전 봉보다 하락", _bool(ac_neg_falling)),
            ("STC 30 초과(침체 아님)", _bool(stc_short_ok)),
        ],
    }
