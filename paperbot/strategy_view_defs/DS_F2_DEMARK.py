"""Chart view for DS_F2_DEMARK (DeepSeek-200 F2_DEMARK, F2 디마크 피벗): its lines and entry conditions.

Rule (PREREG_DEEPSEEK200.md section 5, F2): from the previous UTC calendar day's bars in the frame (O = first open,
H, L, C = last close): X = H + 2L + C when C < O, 2H + L + C when C > O, H + L + 2C when C = O; S1 = X/2 - H,
R1 = X/2 - L. Every bar of a day uses the day before's S1 / R1; when the day before has no bar, there are no levels and
no signal. Long: the low reaches S1 (L <= S1) and the close is back above it (C > S1). Short: the high reaches R1
(H >= R1) and the close is back below it (C < R1). A bar where both sides fire gives neither (lib_c drops both). The
UTC day starts at 09:00 KST, so the levels change every morning at 09:00 KST.

The chart draws S1 and R1 (stepping at each day's first bar).

Same rules as research/deepseek200/lib_c.py ``entries()`` / ``demark_levels()`` (the live signal is
paperbot/dssig.py), written again with numpy / pandas; lib_c is not imported here.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 10,465 / short 10,750; live frames long 19,499 / short 19,471; 0 differing
bars. "signals" = lib_c signals of that series (live: summed over its 24 frames).
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_long_signals": 3987, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "BTC15m_short_signals": 4167, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_long_signals": 2123, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "ETH1h_short_signals": 2302, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_long_signals": 1158, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "SOL4h_short_signals": 1159, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_long_signals": 3197, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "DOGE30m_short_signals": 3122, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_long_signals": 2703, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "BTC15m_live_short_signals": 2876, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_long_signals": 2998, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "ETH1h_live_short_signals": 3259, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_long_signals": 5406, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1, "LTC4h_live_short_signals": 5093, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_long_signals": 2131, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "BCH30m_live_short_signals": 2053, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_long_signals": 3260, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "SOL1h_live_short_signals": 3208, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_long_signals": 3001, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1, "DOGE15m_live_short_signals": 2982}
tests/test_strategy_views_ds_f1_f8.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
import pandas as pd


def _col(df, k):
    return np.asarray(df[k], dtype=float)


def _demark(df):
    """(S1, R1) of the previous UTC calendar day for every bar (lib_c.demark_levels); NaN when that day has no bar."""
    n = len(df)
    if n == 0:
        return np.zeros(0), np.zeros(0)
    o, h, l, c = (_col(df, k) for k in ("open", "high", "low", "close"))
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    day = ts.astype("datetime64[D]").astype(np.int64)
    ud, first = np.unique(day, return_index=True)
    last = np.r_[first[1:], n] - 1
    do, dc = o[first], c[last]
    dh, dl = np.maximum.reduceat(h, first), np.minimum.reduceat(l, first)
    x = np.where(dc < do, dh + 2 * dl + dc, np.where(dc > do, 2 * dh + dl + dc, dh + dl + 2 * dc))
    s1, r1 = x / 2 - dh, x / 2 - dl
    ps1, pr1 = np.full(len(ud), np.nan), np.full(len(ud), np.nan)
    ok = np.r_[False, np.diff(ud) == 1]
    ps1[1:] = np.where(ok[1:], s1[:-1], np.nan)
    pr1[1:] = np.where(ok[1:], r1[:-1], np.nan)
    inv = np.searchsorted(ud, day)
    return ps1[inv], pr1[inv]


def view_DS_F2_DEMARK(df, tf):
    """F2_DEMARK: a wick to yesterday's DeMark S1 (R1) with the close back on the right side. Exact."""
    h, l, c = (_col(df, k) for k in ("high", "low", "close"))
    s1, r1 = _demark(df)
    with np.errstate(invalid="ignore"):
        touch_s, back_s = l <= s1, c > s1
        touch_r, back_r = h >= r1, c < r1
    raw_l, raw_s = touch_s & back_s, touch_r & back_r
    return {
        "overlays": [
            {"name": "디마크 저항선 R1(전날 기준, 오전 9시 갱신)", "values": r1},
            {"name": "디마크 지지선 S1(전날 기준, 오전 9시 갱신)", "values": s1},
        ],
        "panes": [],
        "long": [
            ("저가가 디마크 지지선(S1)에 닿음", touch_s),
            ("종가는 지지선 위로 회복", back_s),
            ("같은 봉 숏 신호 없음", ~raw_s),
        ],
        "short": [
            ("고가가 디마크 저항선(R1)에 닿음", touch_r),
            ("종가는 저항선 아래로 밀림", back_r),
            ("같은 봉 롱 신호 없음", ~raw_l),
        ],
    }
