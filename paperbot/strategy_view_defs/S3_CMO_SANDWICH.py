"""Chart view for S3_CMO_SANDWICH: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
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


def view_S3_CMO_SANDWICH(df, tf):
    # locked: ports12.s3 (variant 0) -> stick sandwich (3 bars, bodies >= 0.08 ATR14,
    # prior 5-close trend), CMO14 zero cross, sync 3, FRESH
    o, h, l, c = (_arr(df[k]) for k in ("open", "high", "low", "close"))
    a = _arr(fg.atr(df, 14))
    b = c - o
    b1, b2, b3 = _lag(b, 2), _lag(b, 1), b
    h1, h3, l1, l3 = _lag(h, 2), h, _lag(l, 2), l
    # prior direction (variant 0): close before the first pattern bar vs close 5 bars before it
    last, first = _lag(c, 3), _lag(c, 7)
    with np.errstate(invalid="ignore"):
        up_prior, dn_prior = last > first, last < first
        bodies = (np.abs(b1) >= 0.08 * a) & (np.abs(b2) >= 0.08 * a) & (np.abs(b3) >= 0.08 * a)
        bear = up_prior & bodies & (b1 > 0) & (b2 < 0) & (b3 > 0) & (np.abs(h1 - h3) <= 0.3 * a) \
            & (c <= np.maximum(h1, h3) + 0.075 * a)
        bull = dn_prior & bodies & (b1 < 0) & (b2 > 0) & (b3 < 0) & (np.abs(l1 - l3) <= 0.3 * a) \
            & (c >= np.minimum(l1, l3) - 0.075 * a)
    cm = fg.cmo(df["close"], 14)
    cmu, cmd = cross_above(cm, 0.0), cross_below(cm, 0.0)
    return {
        "overlays": [],
        "panes": [
            {"name": "CMO 14", "series": [{"name": "CMO", "values": _arr(cm)}], "levels": [0]},
        ],
        "long": [
            ("하락 뒤 음양음 패턴(3봉 내)", recent(bull, 3)),
            ("CMO 0 상향돌파(3봉 내)", recent(cmu, 3)),
            ("CMO 0 위", gt(cm, 0.0)),
            ("패턴 완성 또는 돌파가 이번 봉", np.asarray(bull | cmu, dtype=bool)),
        ],
        "short": [
            ("상승 뒤 양음양 패턴(3봉 내)", recent(bear, 3)),
            ("CMO 0 하향돌파(3봉 내)", recent(cmd, 3)),
            ("CMO 0 아래", lt(cm, 0.0)),
            ("패턴 완성 또는 돌파가 이번 봉", np.asarray(bear | cmd, dtype=bool)),
        ],
    }
