"""Chart view for N05_PSAR_POC: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
import fg_fast
from poc_fast import poc_series


def _arr(x):
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _lag(x, k):
    """value of x k bars ago (NaN for the first k bars); past bars only."""
    x = _arr(x)
    out = np.full(len(x), np.nan)
    if k > 0:
        out[k:] = x[:-k]
    else:
        out[:] = x
    return out


def _ohlca(df):
    o, h, l, c = (_arr(df[k]) for k in ("open", "high", "low", "close"))
    a = _arr(fg.atr(df, 14))
    return o, h, l, c, a


def view_N05_PSAR_POC(df, tf):
    # locked: ports12.n05 (POC 100 bars / 32 bins, PSAR 0.02/0.02/0.2, ATR14; no tf scaling)
    o, h, l, c, a = _ohlca(df)
    poc = poc_series(df, 100, 32)
    psar, pdir = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2)
    ps, pdr = _arr(psar), _arr(pdir)
    o1, c1 = _lag(o, 1), _lag(c, 1)
    with np.errstate(invalid="ignore"):
        support = (np.abs(l - poc) <= 0.2 * a) | ((l <= poc) & (poc <= c))
        resist = (np.abs(h - poc) <= 0.2 * a) | ((c <= poc) & (poc <= h))
        pierce = (c1 < o1) & (c > o) & (c >= (o1 + c1) / 2.0) & (c < o1)
        dark = (c1 > o1) & (c < o) & (c <= (o1 + c1) / 2.0) & (c > o1)
        above = c > ps
        below = c < ps
    return {
        "overlays": [
            {"name": "매물 집중 가격(POC)", "values": poc},
            {"name": "SAR(상승 중)", "values": np.where(pdr > 0, ps, np.nan)},
            {"name": "SAR(하락 중)", "values": np.where(pdr < 0, ps, np.nan)},
        ],
        "panes": [],
        "long": [
            ("저가가 POC 근처(지지)", np.asarray(support, bool)),
            ("음봉 절반 이상 되돌린 양봉", np.asarray(pierce, bool)),
            ("종가가 SAR 위", np.asarray(above, bool)),
        ],
        "short": [
            ("고가가 POC 근처(저항)", np.asarray(resist, bool)),
            ("양봉 절반 이상 밀린 음봉", np.asarray(dark, bool)),
            ("종가가 SAR 아래", np.asarray(below, bool)),
        ],
    }
