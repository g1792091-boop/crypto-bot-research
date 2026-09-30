"""Chart view for N16_BBRSI: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg


def _f(x):
    if isinstance(x, pd.Series):
        x = x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _sh(x, k=1):
    x = _f(x)
    out = np.full(len(x), np.nan)
    if k > 0:
        out[k:] = x[:-k]
    else:
        out[:] = x
    return out


def view_N16_BBRSI(df, tf):
    """RSI(14) mapped onto Bollinger(20, 2) price scale, signal EMA5.
    Entry = (band re-entry with signal cross  OR  pivot divergence) AND candle colour. Exact."""
    o, h, l, c = (_f(df[k]) for k in ("open", "high", "low", "close"))
    up, _mid, lo, _rsi, mp, sg = fg.mapped_rsi_bollinger(df, 20, 2.0, 14, 5, 2.0)
    upf, lof, mpf, sgf = _f(up), _f(lo), _f(mp), _f(sg)
    mp1, lo1, up1 = _sh(mpf, 1), _sh(lof, 1), _sh(upf, 1)
    sg1 = _sh(sgf, 1)
    with np.errstate(invalid="ignore"):
        xu = (mpf > sgf) & (mp1 <= sg1)          # RSI line crosses above its signal on this bar
        xd = (mpf < sgf) & (mp1 >= sg1)          # RSI line crosses below its signal on this bar
        reL = (mp1 < lo1) & (mpf >= lof) & xu    # back inside from below the lower band
        reS = (mp1 > up1) & (mpf <= upf) & xd    # back inside from above the upper band

    # Divergence on confirmed price pivots (3 bars left / 3 bars right, known 3 bars later).
    n = len(c)
    ls, hs = pd.Series(l), pd.Series(h)
    evL = np.zeros(n, bool); evH = np.zeros(n, bool)
    if n > 6:
        lmin = ls.rolling(7, min_periods=1).min().to_numpy()
        hmax = hs.rolling(7, min_periods=1).max().to_numpy()
        lp, hp = _sh(l, 3), _sh(h, 3)
        with np.errstate(invalid="ignore"):
            evL[6:] = (~np.isnan(lp[6:])) & (lp[6:] <= lmin[6:])
            evH[6:] = (~np.isnan(hp[6:])) & (hp[6:] >= hmax[6:])
    divL = np.zeros(n, bool); divS = np.zeros(n, bool)
    prev = None
    for i in np.where(evL)[0]:
        p = i - 3
        if prev is not None and 5 <= p - prev <= 60 and l[p] < l[prev] and mpf[p] > mpf[prev]:
            divL[i] = True
        prev = p
    prev = None
    for i in np.where(evH)[0]:
        p = i - 3
        if prev is not None and 5 <= p - prev <= 60 and h[p] > h[prev] and mpf[p] < mpf[prev]:
            divS[i] = True
        prev = p

    return {
        "overlays": [
            {"name": "볼린저 상단", "values": upf},
            {"name": "볼린저 하단", "values": lof},
            {"name": "RSI선(가격 환산)", "values": mpf},
            {"name": "RSI선 신호(EMA5)", "values": sgf},
        ],
        "panes": [],
        "long": [
            ("RSI 하단 반등 또는 다이버전스", reL | divL),
            ("양봉 마감", c > o),
        ],
        "short": [
            ("RSI 상단 꺾임 또는 다이버전스", reS | divS),
            ("음봉 마감", c < o),
        ],
    }
