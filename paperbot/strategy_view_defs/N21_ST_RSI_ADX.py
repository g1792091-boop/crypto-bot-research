"""Chart view for N21_ST_RSI_ADX: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": null, "BTC15m_long_precision": null, "BTC15m_short_recall": null, "BTC15m_short_precision": null, "SOL1h_long_recall": null, "SOL1h_long_precision": null, "SOL1h_short_recall": null, "SOL1h_short_precision": null, "ETH5m_long_recall": null, "ETH5m_long_precision": null, "ETH5m_short_recall": null, "ETH5m_short_precision": null, "full_history_long_recall": 1, "full_history_long_precision": 1}
"""

import numpy as np
import pandas as pd

import fg_fast
import fg_indicators as fg
from strategies import recent, synchronized, gt, lt, ge, le, cross_above, cross_below, _b, _f


def _arr(x):
    return _f(x)


def _bool(x):
    return np.asarray(x, dtype=bool)


def _rsi_ready(close, length=14):
    """True once fg.rsi has its Wilder averages (before that the locked RSI reads 0, a warm-up artifact)."""
    return (close.diff().notna().cumsum() >= length).to_numpy()


def view_N21_ST_RSI_ADX(df, tf):
    # locked: fg_fast.supertrend_v2(df, 10, 6.0), fg.rsi(close, 14), fg.adx_dmi(df, 14), ADX cross below 25
    line, up = fg_fast.supertrend_v2(df, 10, 6.0)
    up = _b(up)
    r = fg.rsi(df["close"], 14)
    adx_line, _p, _m = fg.adx_dmi(df, 14)
    adx_cross_down = cross_below(adx_line, 25.0)
    rsi_rising = gt(r, r.shift(1))
    rsi_falling = lt(r, r.shift(1))
    rsi_ok = _rsi_ready(df["close"], 14)
    ready = np.isfinite(_arr(line)) & np.isfinite(_arr(adx_line)) & rsi_ok  # all-False during warm-up
    return {
        "overlays": [
            {"name": "슈퍼트렌드 (10, 6)", "values": _arr(line)},
        ],
        "panes": [
            {"name": "RSI 14", "series": [{"name": "RSI", "values": np.where(rsi_ok, _arr(r), np.nan)}],
             "levels": [30, 70]},
            {"name": "ADX 14", "series": [{"name": "ADX", "values": _arr(adx_line)}], "levels": [25]},
        ],
        "long": [
            ("슈퍼트렌드 상승", _bool(up & ready)),
            ("ADX가 25 밑으로(이번 봉)", _bool(adx_cross_down & ready)),
            ("RSI 30 아래", _bool(lt(r, 30.0) & ready)),
            ("RSI 전 봉보다 상승", _bool(rsi_rising & ready)),
        ],
        "short": [
            ("슈퍼트렌드 하락", _bool(~up & ready)),
            ("ADX가 25 밑으로(이번 봉)", _bool(adx_cross_down & ready)),
            ("RSI 70 위", _bool(gt(r, 70.0) & ready)),
            ("RSI 전 봉보다 하락", _bool(rsi_falling & ready)),
        ],
    }
