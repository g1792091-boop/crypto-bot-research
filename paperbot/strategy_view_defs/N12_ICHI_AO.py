"""Chart view for N12_ICHI_AO: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
import fg_fast
from strategies import recent, shift_bool, cross_above, cross_below, gt, lt, ge, le


def _arr_n09(x):
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _bool_n09(x):
    if isinstance(x, pd.Series):
        x = x.fillna(False).to_numpy()
    return np.asarray(x).astype(bool)


def _ichi_view_n12(df, mom_pane, le_, se_, ls_, ss_, labels):
    # shared by N12 / N14: strategies._ichimoku_family with sync = 3
    tenkan, kijun, span_a, span_b = fg.ichimoku(df, 9, 26, 52, 26)
    tk_up, tk_down = cross_above(tenkan, kijun), cross_below(tenkan, kijun)
    cloud_green, cloud_red = gt(span_a, span_b), lt(span_a, span_b)
    le_, se_ = _bool_n09(le_), _bool_n09(se_)
    return {
        "overlays": [
            {"name": "전환선(9)", "values": _arr_n09(tenkan)},
            {"name": "기준선(26)", "values": _arr_n09(kijun)},
            {"name": "구름 A(선행스팬1)", "values": _arr_n09(span_a)},
            {"name": "구름 B(선행스팬2)", "values": _arr_n09(span_b)},
        ],
        "panes": [mom_pane],
        "long": [
            ("전환선 기준선 상향교차(3봉 내)", recent(tk_up, 3)),
            ("상승 구름(A가 B 위)", np.asarray(cloud_green, dtype=bool)),
            (labels["le"], recent(le_, 3)),
            (labels["ls"], _bool_n09(ls_)),
            ("두 신호 중 하나가 이번 봉", np.asarray(tk_up | le_, dtype=bool)),
        ],
        "short": [
            ("전환선 기준선 하향교차(3봉 내)", recent(tk_down, 3)),
            ("하락 구름(A가 B 아래)", np.asarray(cloud_red, dtype=bool)),
            (labels["se"], recent(se_, 3)),
            (labels["ss"], _bool_n09(ss_)),
            ("두 신호 중 하나가 이번 봉", np.asarray(tk_down | se_, dtype=bool)),
        ],
    }


def view_N12_ICHI_AO(df, tf):
    # locked: strategies.n12_ichimoku_ao (no timeframe scaling)
    mom = fg.awesome_oscillator(df, 5, 34)
    m1, m2 = mom.shift(1), mom.shift(2)
    le_ = cross_above(mom, 0.0) | (gt(mom, m1) & le(m1, m2))
    se_ = cross_below(mom, 0.0) | (lt(mom, m1) & ge(m1, m2))
    ls_ = gt(mom, 0.0) & gt(mom, m1)
    ss_ = lt(mom, 0.0) & lt(mom, m1)
    pane = {"name": "AO(어썸 오실레이터)",
            "series": [{"name": "AO", "values": _arr_n09(mom)}],
            "levels": [0]}
    return _ichi_view_n12(
        df, pane, le_, se_, ls_, ss_,
        {"le": "AO 0 돌파나 반등(3봉 내)", "ls": "AO 0 위에서 오르는 중",
         "se": "AO 0 이탈이나 꺾임(3봉 내)", "ss": "AO 0 아래서 내리는 중"})
