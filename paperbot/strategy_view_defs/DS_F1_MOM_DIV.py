"""Chart view for DS_F1_MOM_DIV (DeepSeek-200 F1_MOM_DIV, F1 다이버전스): its lines and entry conditions.

Rule (PREREG_DEEPSEEK200.md section 5, F1): two confirmed swing lows in a row a < b (no confirmed swing low between
them, b - a <= 60 bars) where price makes a lower low (L[b] < L[a]) while momentum(10) = C[t] - C[t-10] makes a higher
low (I[b] > I[a]) -> long on bar b+3, the bar that confirms the swing at b. Two swing highs in a row with a higher
high (H[b] > H[a]) and a lower momentum (I[b] < I[a]) -> short. A swing low (high) is a bar whose low (high) is
strictly below (above) the 3 bars on each side; it is known 3 bars later. The indicator value is the swing bar's own;
an empty value gives no signal. A bar where both sides fire gives neither (lib_c drops both).

The chart joins the confirmed swing highs and the confirmed swing lows (the points a divergence compares) and draws
the last bearish and the last bullish divergence as a segment between its two swings, on price and on the
momentum pane. The checklist reads, on every bar, the swing that bar would confirm (3 bars back) against the last
confirmed swing of the same kind.

Same rules as research/deepseek200/lib_c.py ``entries()`` / ``pivots_conf()`` (the live signal is paperbot/dssig.py),
written again with numpy; lib_c is not imported here.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 4,363 / short 4,777; live frames long 6,572 / short 7,181; 0 differing
bars. "signals" = lib_c signals of that series (live: summed over its 24 frames).
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_long_signals": 2372, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "BTC15m_short_signals": 2618, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_long_signals": 627, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "ETH1h_short_signals": 712, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_long_signals": 169, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "SOL4h_short_signals": 155, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_long_signals": 1195, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "DOGE30m_short_signals": 1292, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_long_signals": 1627, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "BTC15m_live_short_signals": 1808, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_long_signals": 877, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "ETH1h_live_short_signals": 1019, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_long_signals": 673, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1, "LTC4h_live_short_signals": 796, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_long_signals": 861, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "BCH30m_live_short_signals": 924, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_long_signals": 957, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "SOL1h_live_short_signals": 957, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_long_signals": 1577, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1, "DOGE15m_live_short_signals": 1677}
tests/test_strategy_views_ds_f1_f8.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

SW = 3              # swing pivot: 3 bars on each side, known 3 bars later (PREREG section 4)
GAP = 60            # the two swings at most 60 bars apart


def _col(df, k):
    return np.asarray(df[k], dtype=float)


def _prev(x, k=1):
    """Value k bars back (NaN where there is none)."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def _indicator(c, v):
    """Momentum(10) = close - close 10 bars back (lib_c mom); NaN for the first 10 bars."""
    return c - _prev(c, 10)


def _pivots(h, l):
    """(ph, pl): True at bar t when bar t-3 is a confirmed swing high (low): its high strictly above (its low strictly
    below) the 3 bars on each side (lib_c.pivots_conf)."""
    n = len(h)
    ph, pl = np.zeros(n, bool), np.zeros(n, bool)
    if n >= 2 * SW + 1:
        wh = sliding_window_view(h, 2 * SW + 1)
        wl = sliding_window_view(l, 2 * SW + 1)
        with np.errstate(invalid="ignore"):
            ph[2 * SW:] = (wh[:, SW] > wh[:, :SW].max(1)) & (wh[:, SW] > wh[:, SW + 1:].max(1))
            pl[2 * SW:] = (wl[:, SW] < wl[:, :SW].min(1)) & (wl[:, SW] < wl[:, SW + 1:].min(1))
    return ph, pl


def _pairs(conf, price, ind, low):
    """Per bar t: the swing bar t would confirm (b = t-3) against the last swing of the same kind confirmed before t
    (a; lib_c pairs consecutive confirmed swings). Returns the bar a (-1 when none) and the flags: "near" (a exists,
    b - a <= 60), "price" (lows: L[b] < L[a]; highs: H[b] > H[a]), "ind" (lows: I[b] > I[a]; highs: I[b] < I[a])."""
    n = len(conf)
    t = np.arange(n)
    b = t - SW
    tc = np.flatnonzero(conf)
    a = np.full(n, -1)
    if len(tc):
        k = np.searchsorted(tc, t, side="left") - 1
        a = np.where(k >= 0, tc[np.clip(k, 0, None)] - SW, -1)
    has = (a >= 0) & (b >= 0)
    ia, ib = np.clip(a, 0, None), np.clip(b, 0, None)
    with np.errstate(invalid="ignore"):
        if low:
            pr, iv = price[ib] < price[ia], ind[ib] > ind[ia]
        else:
            pr, iv = price[ib] > price[ia], ind[ib] < ind[ia]
    return {"a": a, "near": has & (b - a <= GAP), "price": has & pr, "ind": has & iv}


def _joined(conf, x):
    """x on every confirmed swing bar (the chart joins them), NaN elsewhere."""
    out = np.full(len(x), np.nan)
    p = np.flatnonzero(conf) - SW
    out[p] = x[p]
    return out


def _last_pair(sig, a, x):
    """The last signal's two swings (a and b = t-3) as a 2-point segment, NaN elsewhere."""
    out = np.full(len(x), np.nan)
    s = np.flatnonzero(sig)
    if len(s):
        b = int(s[-1]) - SW
        out[[int(a[s[-1]]), b]] = x[[int(a[s[-1]]), b]]
    return out


def view_DS_F1_MOM_DIV(df, tf):
    """F1_MOM_DIV: price and 모멘텀 disagree between the last two confirmed swings. Exact."""
    h, l, c, v = (_col(df, k) for k in ("high", "low", "close", "volume"))
    ind = _indicator(c, v)
    ph, pl = _pivots(h, l)
    L = _pairs(pl, l, ind, True)
    S = _pairs(ph, h, ind, False)
    raw_l = pl & L["near"] & L["price"] & L["ind"]
    raw_s = ph & S["near"] & S["price"] & S["ind"]
    sig_l, sig_s = raw_l & ~raw_s, raw_s & ~raw_l
    return {
        "overlays": [
            {"name": "스윙 고점 잇기", "values": _joined(ph, h), "join": True},
            {"name": "스윙 저점 잇기", "values": _joined(pl, l), "join": True},
            {"name": "마지막 약세 다이버전스(가격 고점)", "values": _last_pair(sig_s, S["a"], h), "join": True},
            {"name": "마지막 강세 다이버전스(가격 저점)", "values": _last_pair(sig_l, L["a"], l), "join": True},
        ],
        "panes": [
            {"name": "모멘텀 10 (스윙끼리 비교)", "levels": [0], "series": [
                {"name": "모멘텀 10 (종가 - 10봉 전 종가)", "values": ind},
                {"name": "약세 다이버전스(모멘텀 고점)", "values": _last_pair(sig_s, S["a"], ind), "join": True},
                {"name": "강세 다이버전스(모멘텀 저점)", "values": _last_pair(sig_l, L["a"], ind), "join": True},
            ]},
        ],
        "long": [
            ("3봉 전 봉이 스윙 저점으로 확정(앞뒤 3봉보다 낮음)", pl),
            ("직전 스윙 저점과 60봉 이내", L["near"]),
            ("가격은 더 낮은 저점(직전 스윙 저점 아래)", L["price"]),
            ("모멘텀은 더 높은 저점(강세 다이버전스)", L["ind"]),
            ("같은 봉 숏 신호 없음", ~raw_s),
        ],
        "short": [
            ("3봉 전 봉이 스윙 고점으로 확정(앞뒤 3봉보다 높음)", ph),
            ("직전 스윙 고점과 60봉 이내", S["near"]),
            ("가격은 더 높은 고점(직전 스윙 고점 위)", S["price"]),
            ("모멘텀은 더 낮은 고점(약세 다이버전스)", S["ind"]),
            ("같은 봉 롱 신호 없음", ~raw_l),
        ],
    }
