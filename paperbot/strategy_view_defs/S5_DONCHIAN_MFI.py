"""Chart view for S5_DONCHIAN_MFI: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_fast
import fg_indicators as fg
from strategies import recent, gt, lt, ge, le, cross_above, cross_below, _f


def view_S5_DONCHIAN_MFI(df, tf):
    # locked: fg.donchian_channel(df, 20, shift_previous=True), fg.mfi(df, 14), sync 3
    upper, _middle, lower = fg.donchian_channel(df, 20, shift_previous=True)
    m = fg.mfi(df, 14)
    close = df["close"]
    breakout_up = gt(close, upper) & le(close.shift(1), upper.shift(1))
    breakout_down = lt(close, lower) & ge(close.shift(1), lower.shift(1))
    mfi_up = cross_above(m, 30.0)
    mfi_down = cross_below(m, 70.0)
    sync = 3
    return {
        "overlays": [
            {"name": "돈치안 상단 (20봉 최고가)", "values": _f(upper)},
            {"name": "돈치안 하단 (20봉 최저가)", "values": _f(lower)},
        ],
        "panes": [
            {"name": "MFI 14", "series": [{"name": "MFI", "values": _f(m)}], "levels": [30, 70]},
        ],
        "long": [
            ("종가가 직전 20봉 최고가 위", gt(close, upper)),
            ("MFI 30 위", gt(m, 30.0)),
            ("최고가 돌파 최근 3봉 내", recent(breakout_up, sync)),
            ("MFI 30 상향 최근 3봉 내", recent(mfi_up, sync)),
            ("이번 봉 돌파 또는 MFI 상향", np.asarray(breakout_up | mfi_up, dtype=bool)),
        ],
        "short": [
            ("종가가 직전 20봉 최저가 아래", lt(close, lower)),
            ("MFI 70 아래", lt(m, 70.0)),
            ("최저가 이탈 최근 3봉 내", recent(breakout_down, sync)),
            ("MFI 70 하향 최근 3봉 내", recent(mfi_down, sync)),
            ("이번 봉 이탈 또는 MFI 하향", np.asarray(breakout_down | mfi_down, dtype=bool)),
        ],
    }
