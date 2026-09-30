"""Chart view for N10_HA_PSAR: its indicators (same parameters as the locked code) and entry conditions.

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


def view_N10_HA_PSAR(df, tf):
    # locked: strategies.n10_heikin_psar (no timeframe scaling), sync = 2
    ha = fg_fast.heikin_ashi(df)
    psar, pdir = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2)
    ha_green = gt(ha["ha_close"], ha["ha_open"])
    ha_red = lt(ha["ha_close"], ha["ha_open"])
    tol = (ha["ha_high"] - ha["ha_low"]).abs() * 0.02
    body_min = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).min(axis=1)
    body_max = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).max(axis=1)
    no_lower = le((body_min - ha["ha_low"]).abs(), tol)
    no_upper = le((ha["ha_high"] - body_max).abs(), tol)
    turn_green = ha_green & ~shift_bool(ha_green, 1)
    turn_red = ha_red & ~shift_bool(ha_red, 1)
    d = _arr_n09(pdir)
    dp = pd.Series(d).shift(1)
    flip_up = gt(d, 0) & le(dp, 0)
    flip_down = lt(d, 0) & ge(dp, 0)
    close = df["close"]
    sar = _arr_n09(psar)
    # Locked rule: SAR < close AND (SAR direction up OR SAR flipped up within 2 bars).
    # The direction part is folded into the one "SAR below price" item. It is NOT redundant:
    # on an outside-bar flip the new SAR can sit on the "wrong" side of the close (about 700 such
    # bars in the full BTC/ETH/SOL 5m-4h history), so it is kept to stay exact (short mirrors).
    sar_below = lt(sar, close) & (gt(d, 0) | recent(flip_up, 2))
    sar_above = gt(sar, close) & (lt(d, 0) | recent(flip_down, 2))
    body = _arr_n09(ha["ha_close"]) - _arr_n09(ha["ha_open"])
    return {
        "overlays": [
            {"name": "SAR 점(상승)", "values": np.where(gt(d, 0), sar, np.nan)},
            {"name": "SAR 점(하락)", "values": np.where(lt(d, 0), sar, np.nan)},
        ],
        "panes": [
            {"name": "하이킨아시 캔들 몸통",
             "series": [{"name": "몸통(+양봉/−음봉)", "values": body}],
             "levels": [0]},
        ],
        "long": [
            ("하이킨아시 양봉 전환(2봉 내)", recent(turn_green, 2)),
            ("하이킨아시 아래꼬리 없음", np.asarray(no_lower, dtype=bool)),
            ("SAR 점이 가격 아래", np.asarray(sar_below, dtype=bool)),
            ("두 전환 중 하나가 이번 봉", np.asarray(turn_green | flip_up, dtype=bool)),
        ],
        "short": [
            ("하이킨아시 음봉 전환(2봉 내)", recent(turn_red, 2)),
            ("하이킨아시 위꼬리 없음", np.asarray(no_upper, dtype=bool)),
            ("SAR 점이 가격 위", np.asarray(sar_above, dtype=bool)),
            ("두 전환 중 하나가 이번 봉", np.asarray(turn_red | flip_down, dtype=bool)),
        ],
    }
