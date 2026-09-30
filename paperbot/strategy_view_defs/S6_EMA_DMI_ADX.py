"""Chart view for S6_EMA_DMI_ADX: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_fast
import fg_indicators as fg
from strategies import recent, gt, lt, ge, le, cross_above, cross_below, _f


def view_S6_EMA_DMI_ADX(df, tf):
    # locked: fg.ema(close, 20), fg.dmi_adx(df, 14, 14), ADX >= 25, sync 2
    e = fg.ema(df["close"], 20)
    plus, minus, adx = fg.dmi_adx(df, 14, 14)
    close = df["close"]
    price_up = cross_above(close, e)
    price_down = cross_below(close, e)
    di_up = cross_above(plus, minus)
    di_down = cross_above(minus, plus)
    sync = 2
    return {
        "overlays": [
            {"name": "EMA 20", "values": _f(e)},
        ],
        "panes": [
            {"name": "DMI 14 / ADX",
             "series": [{"name": "+DI", "values": _f(plus)},
                        {"name": "-DI", "values": _f(minus)},
                        {"name": "ADX", "values": _f(adx)}],
             "levels": [25]},
        ],
        "long": [
            ("ADX 25 이상 (추세 강함)", ge(adx, 25.0)),
            ("종가가 EMA20 위", gt(close, e)),
            ("+DI가 -DI 위", gt(plus, minus)),
            ("EMA20·DI 상향교차 2봉 내", recent(di_up, sync) & recent(price_up, sync)),
            ("이번 봉에 상향교차 발생", np.asarray(price_up | di_up, dtype=bool)),
        ],
        "short": [
            ("ADX 25 이상 (추세 강함)", ge(adx, 25.0)),
            ("종가가 EMA20 아래", lt(close, e)),
            ("-DI가 +DI 위", gt(minus, plus)),
            ("EMA20·DI 하향교차 2봉 내", recent(di_down, sync) & recent(price_down, sync)),
            ("이번 봉에 하향교차 발생", np.asarray(price_down | di_down, dtype=bool)),
        ],
    }
