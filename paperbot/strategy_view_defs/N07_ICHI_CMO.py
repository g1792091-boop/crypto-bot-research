"""Chart view for N07_ICHI_CMO: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
from strategies import recent, cross_above, cross_below, gt, lt


def _arr(x):
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _ichimoku_view(df, mom_pane, le_, se_, ls_, ss_, labels):
    # shared by N07 / N08: strategies._ichimoku_family with sync = 3
    tenkan, kijun, span_a, span_b = fg.ichimoku(df, 9, 26, 52, 26)
    tk_up, tk_down = cross_above(tenkan, kijun), cross_below(tenkan, kijun)
    cloud_green, cloud_red = gt(span_a, span_b), lt(span_a, span_b)
    return {
        "overlays": [
            {"name": "전환선(9)", "values": _arr(tenkan)},
            {"name": "기준선(26)", "values": _arr(kijun)},
            {"name": "구름 A(선행스팬1)", "values": _arr(span_a)},
            {"name": "구름 B(선행스팬2)", "values": _arr(span_b)},
        ],
        "panes": [mom_pane],
        "long": [
            ("전환선 기준선 상향교차(3봉 내)", recent(tk_up, 3)),
            ("상승 구름(A가 B 위)", cloud_green),
            (labels["le"], recent(le_, 3)),
            (labels["ls"], np.asarray(ls_, dtype=bool)),
            (labels["now_l"], np.asarray(tk_up | le_, dtype=bool)),
        ],
        "short": [
            ("전환선 기준선 하향교차(3봉 내)", recent(tk_down, 3)),
            ("하락 구름(A가 B 아래)", cloud_red),
            (labels["se"], recent(se_, 3)),
            (labels["ss"], np.asarray(ss_, dtype=bool)),
            (labels["now_s"], np.asarray(tk_down | se_, dtype=bool)),
        ],
    }


def view_N07_ICHI_CMO(df, tf):
    # locked: strategies.n07_ichimoku_cmo (no timeframe scaling)
    mom = fg.cmo(df["close"], 14)
    pane = {"name": "CMO 14",
            "series": [{"name": "CMO", "values": _arr(mom)}],
            "levels": [0]}
    return _ichimoku_view(
        df, pane,
        cross_above(mom, 0.0), cross_below(mom, 0.0), gt(mom, 0.0), lt(mom, 0.0),
        {"le": "CMO 0 상향교차(3봉 내)", "ls": "CMO 0보다 위",
         "now_l": "두 교차 중 하나가 이번 봉",
         "se": "CMO 0 하향교차(3봉 내)", "ss": "CMO 0보다 아래",
         "now_s": "두 교차 중 하나가 이번 봉"})
