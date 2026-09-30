"""Chart view for N24_DMI: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import fg_indicators as fg
from strategies import ge, le, cross_above, _f


def _arr_n23(x):
    """float ndarray of len(df); NaN kept."""
    return _f(x)


def _bool_n23(x):
    return np.asarray(x, dtype=bool)


def view_N24_DMI(df, tf):
    # locked: strategies.n24_dmi -- fg.adx_dmi(df, 14); long: ADX >= 25 and +DI crosses above -DI;
    #   short: ADX <= 25 and -DI crosses above +DI (the two crosses can never happen on one bar).
    adx_line, plus, minus = fg.adx_dmi(df, 14)
    plus_up = cross_above(plus, minus)
    minus_up = cross_above(minus, plus)
    return {
        "overlays": [],
        "panes": [
            {"name": "DMI · ADX 14",
             "series": [{"name": "ADX(추세 강도)", "values": _arr_n23(adx_line)},
                        {"name": "+DI(상승 힘)", "values": _arr_n23(plus)},
                        {"name": "-DI(하락 힘)", "values": _arr_n23(minus)}],
             "levels": [25]},
        ],
        "long": [
            ("ADX 25 이상(추세 강함)", _bool_n23(ge(adx_line, 25.0))),
            ("+DI가 -DI 추월(이번 봉)", _bool_n23(plus_up)),
        ],
        "short": [
            ("ADX 25 이하(추세 약함)", _bool_n23(le(adx_line, 25.0))),
            ("-DI가 +DI 추월(이번 봉)", _bool_n23(minus_up)),
        ],
    }
