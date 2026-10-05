"""Chart view for DS_F11_TSOUP (DeepSeek-200 F11_TSOUP, research/deepseek200/PREREG_DEEPSEEK200.md section 5):
what a trader draws for it and its entry conditions, worded for the owners.

Turtle soup (Raschke, 20 / 4 bars): the lowest low of the previous 20 bars, made at least 4 bars ago, is
pierced by this bar's low and the close is back above it (short mirrored with the 20-bar high). The chart draws the
previous 20-bar high and low.

Checked against the research signal (lib_c.entries of research/deepseek200/lib_c.py, loaded by path inside
entry_marks._contained(), so sys.path and the warnings filters are restored): AND of the long (short) conditions
equals the F11_TSOUP long (short) signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1}
Series: the full Binance USDT-M bar files 2021-01..2026-09 (BTC 15m 201,398 bars, ETH 1h 50,351, SOL 4h
12,588, DOGE 30m 100,701; signals checked: long 6,223, short 6,288) and 12 live-service frames
built from 5m bars as paperbot.dssig.frame does (config.DS_WINDOW_5M; BTC 15m, ETH 1h, LTC 4h, BCH 30m at
three end dates each; signals checked: long 722, short 772): recall = precision = 1 on all
24 live-frame sides too, 0 differing bars. tests/test_strategy_views_ds_f9_f11.py repeats the check.
"""

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


def _cols(df):
    return tuple(np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))


def view_DS_F11_TSOUP(df, tf):
    """F11_TSOUP: new 20-bar extreme whose previous extreme is 4+ bars old, closed back inside. Exact."""
    o, h, l, c = _cols(df)
    n = len(c)
    lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
    hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy()
    age_lo, age_hi = np.full(n, -1.0), np.full(n, -1.0)
    if n > 20:
        wl = sliding_window_view(l, 20)[:n - 20]
        wh = sliding_window_view(h, 20)[:n - 20]
        idx = np.arange(20, n)
        age_lo[20:] = idx - (np.arange(n - 20) + wl.argmin(1))   # earliest bar of the low (ties: the first)
        age_hi[20:] = idx - (np.arange(n - 20) + wh.argmax(1))
    with np.errstate(invalid="ignore"):
        lo_old, lo_hit, lo_back = age_lo >= 4, l < lo20, c > lo20
        hi_old, hi_hit, hi_back = age_hi >= 4, h > hi20, c < hi20
    raw_l, raw_s = lo_old & lo_hit & lo_back, hi_old & hi_hit & hi_back
    return {
        "overlays": [
            {"name": "직전 20봉 최고가", "values": hi20},
            {"name": "직전 20봉 최저가", "values": lo20},
        ],
        "panes": [],
        "long": [
            ("직전 20봉 최저가가 4봉 이상 전에 나옴", lo_old),
            ("저가가 그 최저가 아래로 찍음", lo_hit),
            ("종가는 그 최저가 위로 회복", lo_back),
            ("같은 봉 숏 신호 없음", ~raw_s),
        ],
        "short": [
            ("직전 20봉 최고가가 4봉 이상 전에 나옴", hi_old),
            ("고가가 그 최고가 위로 찍음", hi_hit),
            ("종가는 그 최고가 아래로 복귀", hi_back),
            ("같은 봉 롱 신호 없음", ~raw_l),
        ],
    }
