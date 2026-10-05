"""Chart view for DS_F14_SMT (DeepSeek-200 F14_SMT, F14 SMT 다이버전스): its lines and entry conditions.

Rule: BTC is the reference. On bar t, BTC's high above the highest high of its previous 20 bars (BTC's own bars;
the BTC bar with the same open time) while this coin's high stays at or below its own previous 20-bar high -> short
this coin (it is the weaker one). BTC's low below its previous 20-bar low while this coin's low holds -> long. A bar
where both sides would fire gives neither. BTC itself never trades it.

BTC bars: ``view_DS_F14_SMT(df, tf, btc)`` or ``df.attrs["btc"]`` = BTCUSDT bars of the same timeframe with their own
timestamps (ts, high, low), as paperbot/dssig.py passes ``ctx["BTCUSD"]`` to lib_c (it sends the last 100 BTC chart
bars; F14 on a bar needs that bar and the 20 before it). Without them, or when ``df.attrs["symbol"]`` (or "coin") is
BTC itself, the BTC conditions stay off, as the live signal does. The chart draws this coin's previous 20-bar high
and low and, in a pane, BTC's high and low against its own previous 20-bar high and low.

Same rules as research/deepseek200/lib_c.py ``entries()`` (PREREG_DEEPSEEK200.md sections 4 and 5; the live signal is
paperbot/dssig.py), written again with numpy; lib_c is not imported here.

Checked against the locked signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded contained: sys.path and the warnings filters restored). Bars: Binance USDT-M, the live
DeepSeek windows (config.DS_WINDOW_5M closed 5m bars, resampled by dssig.frame) at 24 bar closes from 2021-06 to
2026-09 per series, plus the full 2021-01..2026-09 series. Series are coins other than BTC; BTC context = the last
100 BTC chart bars of the window (as dssig) and the whole window, passed as the argument and as df.attrs["btc"]; BTC
itself (attrs symbol BTCUSDT) is off in both. "signals" = lib_c signals in the full series.
Checks: {"ETH15m_long_recall": 1, "ETH15m_long_precision": 1, "ETH15m_long_signals": 7065, "ETH15m_short_recall": 1, "ETH15m_short_precision": 1, "ETH15m_short_signals": 8316, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_long_signals": 1804, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "SOL1h_short_signals": 2553, "LTC30m_long_recall": 1, "LTC30m_long_precision": 1, "LTC30m_long_signals": 3985, "LTC30m_short_recall": 1, "LTC30m_short_precision": 1, "LTC30m_short_signals": 4992, "DOGE4h_long_recall": 1, "DOGE4h_long_precision": 1, "DOGE4h_long_signals": 453, "DOGE4h_short_recall": 1, "DOGE4h_short_precision": 1, "DOGE4h_short_signals": 812}
"""

import numpy as np
import pandas as pd

N = 20              # previous bars of the new-high / new-low test
BTC_KEYS = ("BTCUSDT", "BTCUSD")


def _f(x):
    """float ndarray; NaN kept."""
    if isinstance(x, pd.Series):
        x = x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _utc_ns(s):
    return pd.to_datetime(pd.Series(s), utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")


def _prior_max(x):
    return pd.Series(x, dtype=float).rolling(N).max().shift(1).to_numpy()


def _prior_min(x):
    return pd.Series(x, dtype=float).rolling(N).min().shift(1).to_numpy()


def view_DS_F14_SMT(df, tf, btc=None):
    h, l = _f(df["high"]), _f(df["low"])
    n = len(h)
    if btc is None:
        btc = df.attrs.get("btc")
    if str(df.attrs.get("symbol") or df.attrs.get("coin") or "").upper() in BTC_KEYS:
        btc = None
    xmax, xmin = _prior_max(h), _prior_min(l)
    b_hi, b_max, b_lo, b_min = (np.full(n, np.nan) for _ in range(4))
    nh, nl = np.zeros(n, bool), np.zeros(n, bool)
    if btc is not None and len(btc) and n:
        bts, ts = _utc_ns(btc["ts"]), _utc_ns(df["ts"])
        bh, bl = _f(btc["high"]), _f(btc["low"])
        j = np.searchsorted(bts, ts)
        jj = np.minimum(j, len(bts) - 1)
        ok = (j < len(bts)) & (bts[jj] == ts)          # the BTC bar with the same open time (none: no signal)
        b_hi, b_max = np.where(ok, bh[jj], np.nan), np.where(ok, _prior_max(bh)[jj], np.nan)
        b_lo, b_min = np.where(ok, bl[jj], np.nan), np.where(ok, _prior_min(bl)[jj], np.nan)
        with np.errstate(invalid="ignore"):
            nh, nl = ok & (b_hi > b_max), ok & (b_lo < b_min)
    with np.errstate(invalid="ignore"):
        holds, fails = l >= xmin, h <= xmax
    lg, sh = nl & holds, nh & fails
    long = [
        ("BTC가 20봉 저점을 새로 깸", nl),
        ("이 코인은 20봉 저점을 지킴", holds),
        ("반대(숏) 신호와 겹치지 않음", ~sh),
    ]
    short = [
        ("BTC가 20봉 고점을 새로 넘음", nh),
        ("이 코인은 20봉 고점을 못 넘음", fails),
        ("반대(롱) 신호와 겹치지 않음", ~lg),
    ]
    return {
        "overlays": [
            {"name": "직전 20봉 고점", "values": xmax},
            {"name": "직전 20봉 저점", "values": xmin},
        ],
        "panes": [
            {"name": "BTC 같은 봉", "series": [
                {"name": "BTC 고가", "values": b_hi},
                {"name": "BTC 직전 20봉 고점", "values": b_max},
                {"name": "BTC 저가", "values": b_lo},
                {"name": "BTC 직전 20봉 저점", "values": b_min}], "levels": []},
        ],
        "long": [(k, np.asarray(v, bool)) for k, v in long],
        "short": [(k, np.asarray(v, bool)) for k, v in short],
    }
