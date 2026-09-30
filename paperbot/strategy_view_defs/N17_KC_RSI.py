"""Chart view for N17_KC_RSI: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1, "window300_500_lastbar_recall_precision": 1}
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


def view_N17_KC_RSI(df, tf):
    # locked: EMA20 +/- 2*ATR14 (Keltner), approach = 0.10*ATR, RSI14 <=30 / >=70, synchronized 2
    mid = fg.ema(df["close"], 20)
    a = fg.atr(df, 14)
    upper, lower = mid + a * 2.0, mid - a * 2.0
    r = fg.rsi(df["close"], 14)
    approach = 0.10 * a
    long_touch = le(df["low"], lower + approach)
    short_touch = ge(df["high"], upper - approach)
    long_rsi, short_rsi = le(r, 30.0), ge(r, 70.0)
    long_sync = synchronized([long_touch, long_rsi], 2)
    short_sync = synchronized([short_touch, short_rsi], 2)
    rsi_ok = _rsi_ready(df["close"], 14)
    ready = np.isfinite(_arr(upper)) & rsi_ok          # all-False until the bands and RSI exist
    return {
        "overlays": [
            {"name": "켈트너 상단", "values": _arr(upper)},
            {"name": "켈트너 하단", "values": _arr(lower)},
        ],
        "panes": [
            {"name": "RSI 14", "series": [{"name": "RSI", "values": np.where(rsi_ok, _arr(r), np.nan)}],
             "levels": [30, 70]},
        ],
        "long": [
            ("켈트너 하단 근처(최근 3봉)", _bool(recent(long_touch, 3) & ready)),
            ("RSI 30 이하(최근 3봉)", _bool(recent(long_rsi & rsi_ok, 3) & ready)),
            ("두 신호가 2봉 안에 함께", _bool(long_sync & ready)),
        ],
        "short": [
            ("켈트너 상단 근처(최근 3봉)", _bool(recent(short_touch, 3) & ready)),
            ("RSI 70 이상(최근 3봉)", _bool(recent(short_rsi & rsi_ok, 3) & ready)),
            ("두 신호가 2봉 안에 함께", _bool(short_sync & ready)),
            ("롱 신호와 겹치지 않음", _bool(~long_sync & ready)),
        ],
    }
