"""Chart view for OBV_S: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import pine_indicators as pi
from strategies import _f


def _arr_n23(x):
    """float ndarray of len(df); NaN kept."""
    return _f(x)


def _bool_n23(x):
    return np.asarray(x, dtype=bool)


def _empty_view_n23(view):
    """Same layout with zero-length arrays (used for an empty frame)."""
    return {
        "overlays": [dict(o, values=o["values"][:0]) for o in view["overlays"]],
        "panes": [dict(p, series=[dict(s, values=s["values"][:0]) for s in p["series"]]) for p in view["panes"]],
        "long": [(lab, c[:0]) for lab, c in view["long"]],
        "short": [(lab, c[:0]) for lab, c in view["short"]],
    }


def view_OBV_S(df, tf):
    # locked: strategies.obv_s -- OBV vs SMA30 of OBV, AC from ao_ac(5, 34, 5), STC(12, 26, 50, 0.5) < 70 / > 30,
    #   stochastic %K = SMA4 of raw stoch, %D = SMA3 of %K for lengths 11, 15 and 9: any golden / dead cross.
    if len(df) == 0:  # pi.crossover -> pi.shift1 cannot index an empty array (the locked obv_s fails too)
        one = pd.DataFrame({c: [np.nan] for c in ("open", "high", "low", "close", "volume")})
        return _empty_view_n23(view_OBV_S(one, tf))
    high, low, close = _f(df["high"]), _f(df["low"]), _f(df["close"])
    vol = _f(df["volume"])
    o = pi.obv(close, vol)
    trend_ma = pi.pine_sma(o, 30)
    _ao, ac = pi.ao_ac(high, low, 5, 34, 5)
    stc_v = pi.stc(close, 12, 26, 50, 0.5)
    gcs, dcs = [], []
    for length in (11, 15, 9):
        raw = pi.pine_stoch(close, high, low, length)
        k = pi.pine_sma(raw, 4)
        d = pi.pine_sma(k, 3)
        gcs.append(pi.crossover(k, d) & np.isfinite(k) & np.isfinite(d))
        dcs.append(pi.crossunder(k, d) & np.isfinite(k) & np.isfinite(d))
    any_golden = np.logical_or.reduce(gcs)
    any_dead = np.logical_or.reduce(dcs)
    with np.errstate(invalid="ignore"):
        ac_pos, ac_neg = ac > 0.0, ac < 0.0
        stc_long_ok, stc_short_ok = stc_v < 70.0, stc_v > 30.0
        obv_up, obv_down = o > trend_ma, o < trend_ma
    # AC > 0 and AC < 0 are exclusive, so the locked "short & ~long" equals short.
    return {
        "overlays": [],
        "panes": [
            {"name": "OBV (거래량 흐름)",
             "series": [{"name": "OBV", "values": _arr_n23(o)},
                        {"name": "OBV 30봉 평균", "values": _arr_n23(trend_ma)}],
             "levels": []},
            {"name": "STC (12·26·50)",
             "series": [{"name": "STC", "values": _arr_n23(stc_v)}],
             "levels": [30, 70]},
        ],
        "long": [
            ("스토캐스틱 골든크로스(이번 봉)", _bool_n23(any_golden)),
            ("가속도(AC) 0 위", _bool_n23(ac_pos)),
            ("STC 70 아래(과열 아님)", _bool_n23(stc_long_ok)),
            ("OBV가 30봉 평균 위", _bool_n23(obv_up)),
        ],
        "short": [
            ("스토캐스틱 데드크로스(이번 봉)", _bool_n23(any_dead)),
            ("가속도(AC) 0 아래", _bool_n23(ac_neg)),
            ("STC 30 위(침체 아님)", _bool_n23(stc_short_ok)),
            ("OBV가 30봉 평균 아래", _bool_n23(obv_down)),
        ],
    }
