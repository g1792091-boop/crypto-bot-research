"""Chart view for S1_EMA_RSI_CHOP: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": null, "ETH5m_long_precision": null, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
from strategies import recent, cross_above, cross_below


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


def view_S1_EMA_RSI_CHOP(df, tf):
    # locked: ports12.s1 -> EMA5/EMA20, RSI14, chop_zone_proxy(34, 1.0, 5.0, 14), sync 3, FRESH
    close = df["close"]
    e5, e20 = fg.ema(close, 5), fg.ema(close, 20)
    r = _arr(fg.rsi(close, 14))
    r1 = _lag(r, 1)
    _ang, cz, _st = fg.chop_zone_proxy(df, 34, 1.0, 5.0, 14)
    cz = _arr(cz)
    cz1 = _lag(cz, 1)
    # display only: fg.rsi reports 0 and the chop proxy reports 0 while they are still
    # warming up (first 14 / 34 bars); hide those bars on the chart. Conditions keep the locked values.
    r_show = r.copy()
    r_show[:14] = np.nan
    cz_show = np.where(np.isnan(_arr(_ang)), np.nan, cz)
    eu, ed = cross_above(e5, e20), cross_below(e5, e20)
    with np.errstate(invalid="ignore"):
        ru = (r1 < 30) & (r > r1)
        rd = (r1 > 70) & (r < r1)
        cu = (cz1 <= 0) & (cz > 0)
        cd = (cz1 >= 0) & (cz < 0)
        lst = (_arr(e5) > _arr(e20)) & (cz > 0)
        sst = (_arr(e5) < _arr(e20)) & (cz < 0)
    return {
        "overlays": [
            {"name": "EMA 5", "values": _arr(e5)},
            {"name": "EMA 20", "values": _arr(e20)},
        ],
        "panes": [
            {"name": "RSI 14", "series": [{"name": "RSI", "values": r_show}], "levels": [30, 70]},
            {"name": "찹존 (EMA34 기울기)",
             "series": [{"name": "방향(+2~-2)", "values": cz_show}],
             "levels": [0]},
        ],
        "long": [
            ("EMA 골든크로스(3봉 내)", recent(eu, 3)),
            ("RSI 30 밑 반등(3봉 내)", recent(ru, 3)),
            ("찹존 상승전환(3봉 내)", recent(cu, 3)),
            ("EMA5>EMA20, 찹존 상승", np.asarray(lst, dtype=bool)),
            ("세 신호 중 하나가 이번 봉", np.asarray(eu | ru | cu, dtype=bool)),
        ],
        "short": [
            ("EMA 데드크로스(3봉 내)", recent(ed, 3)),
            ("RSI 70 위 꺾임(3봉 내)", recent(rd, 3)),
            ("찹존 하락전환(3봉 내)", recent(cd, 3)),
            ("EMA5<EMA20, 찹존 하락", np.asarray(sst, dtype=bool)),
            ("세 신호 중 하나가 이번 봉", np.asarray(ed | rd | cd, dtype=bool)),
        ],
    }
