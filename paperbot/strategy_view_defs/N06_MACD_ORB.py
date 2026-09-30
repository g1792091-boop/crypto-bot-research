"""Chart view for N06_MACD_ORB: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
from strategies import recent, cross_above, cross_below


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


def view_N06_MACD_ORB(df, tf):
    # locked: ports12.n06 (opening range = first bar of each UTC day = 09:00 KST; MACD 12/26/9; ATR14)
    o, h, l, c, a = _ohlca(df)
    ts = pd.to_datetime(df["ts"], utc=True)
    first = (~ts.dt.floor("D").duplicated()).to_numpy()
    orb_h = pd.Series(np.where(first, h, np.nan)).ffill().to_numpy()
    orb_l = pd.Series(np.where(first, l, np.nan)).ffill().to_numpy()
    orb_h[first] = np.nan
    orb_l[first] = np.nan                     # range is not finished on its own bar
    c1 = _lag(c, 1)
    with np.errstate(invalid="ignore"):
        brk_up = (c > orb_h) & (c1 <= orb_h)
        brk_dn = (c < orb_l) & (c1 >= orb_l)
    ml, sl, hist = fg.macd(df["close"], 12, 26, 9)
    x_up, x_dn = cross_above(ml, sl), cross_below(ml, sl)
    mlf, hs = _arr(ml), _arr(hist)
    hs1 = _lag(hs, 1)
    with np.errstate(invalid="ignore"):
        mom_up = (mlf > 0) & (hs > 0) & (hs >= hs1)
        mom_dn = (mlf < 0) & (hs < 0) & (hs <= hs1)
        near_up = (c - orb_h) <= 1.5 * a        # close at most 1.5 ATR above the first-bar high
        near_dn = (orb_l - c) <= 1.5 * a        # close at most 1.5 ATR below the first-bar low
    return {
        "overlays": [
            {"name": "첫 봉(09시) 고가", "values": orb_h},
            {"name": "첫 봉(09시) 저가", "values": orb_l},
        ],
        "panes": [
            {"name": "MACD 12·26·9",
             "series": [{"name": "MACD", "values": mlf},
                        {"name": "신호선", "values": _arr(sl)},
                        {"name": "히스토그램", "values": hs}],
             "levels": [0]},
        ],
        "long": [
            ("첫 봉 고가 돌파(2봉 내)", recent(brk_up, 2)),
            ("MACD 상향교차(2봉 내)", recent(x_up, 2)),
            ("MACD 0 위, 막대 커짐", np.asarray(mom_up, bool)),
            ("첫 봉 고가보다 너무 높지 않음", np.asarray(near_up, bool)),
            ("돌파나 교차가 이번 봉", np.asarray(brk_up | x_up, bool)),
        ],
        "short": [
            ("첫 봉 저가 이탈(2봉 내)", recent(brk_dn, 2)),
            ("MACD 하향교차(2봉 내)", recent(x_dn, 2)),
            ("MACD 0 아래, 막대 커짐", np.asarray(mom_dn, bool)),
            ("첫 봉 저가보다 너무 낮지 않음", np.asarray(near_dn, bool)),
            ("이탈이나 교차가 이번 봉", np.asarray(brk_dn | x_dn, bool)),
        ],
    }
