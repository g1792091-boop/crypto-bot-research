"""Chart view for N08_ICHI_WR: its indicators (same parameters as the locked code) and entry conditions.

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


def view_N08_ICHI_WR(df, tf):
    # locked: strategies.n08_ichimoku_williams (no timeframe scaling)
    mom = fg.williams_r(df, 14)
    pane = {"name": "윌리엄스 %R 14",
            "series": [{"name": "%R", "values": _arr(mom)}],
            "levels": [-80, -20]}
    return _ichimoku_view(
        df, pane,
        cross_above(mom, -80.0), cross_below(mom, -20.0), gt(mom, -80.0), lt(mom, -20.0),
        {"le": "%R -80 상향교차(3봉 내)", "ls": "%R -80보다 위",
         "now_l": "두 교차 중 하나가 이번 봉",
         "se": "%R -20 하향교차(3봉 내)", "ss": "%R -20보다 아래",
         "now_s": "두 교차 중 하나가 이번 봉"})
