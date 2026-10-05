"""Chart view for DS_F5_BOX (DeepSeek-200 F5_BOX, F5 박스권): its lines and entry conditions.

Rule (PREREG_DEEPSEEK200.md section 5, F5): the box is the highest high and the lowest low of the previous 48 bars
(t-48 .. t-1), width = top - bottom. The box counts only when ADX(14) < 20 (fg.dmi_adx(14, 14): no trend) and the
width is at least 3 x ATR14 (fg.atr). pos = (close - bottom) / width.
Long: the box counts, 0 <= pos <= 0.15 (close in the bottom 15%) and a green candle (C > O).
Short: the box counts, 0.85 <= pos <= 1 and a red candle (C < O). A close outside the box (pos < 0 or > 1,
a breakout) gives no signal.
Long and short need opposite ends of the box, so they never fire on one bar.

The chart draws the box (top, bottom) and its 15% zones (the line 15% above the bottom, the line 15% below the top);
the panes show ADX(14) against 20 and the box width in ATRs against 3.

Same rules as research/deepseek200/lib_c.py ``entries()`` (the live signal is paperbot/dssig.py),
written again with numpy / pandas and the vendored fg_indicators; lib_c is not imported here.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 895 / short 2,017; live frames long 1,401 / short 3,040; 0 differing
bars. "signals" = lib_c signals of that series (live: summed over its 24 frames).
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_long_signals": 521, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "BTC15m_short_signals": 1124, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_long_signals": 76, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "ETH1h_short_signals": 258, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_long_signals": 43, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "SOL4h_short_signals": 85, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_long_signals": 255, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "DOGE30m_short_signals": 550, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_long_signals": 391, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "BTC15m_live_short_signals": 732, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_long_signals": 102, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "ETH1h_live_short_signals": 384, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_long_signals": 121, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1, "LTC4h_live_short_signals": 414, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_long_signals": 212, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "BCH30m_live_short_signals": 398, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_long_signals": 206, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "SOL1h_live_short_signals": 340, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_long_signals": 369, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1, "DOGE15m_live_short_signals": 772}
tests/test_strategy_views_ds_f1_f8.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
import pandas as pd
import fg_indicators as fg

BOX = 48            # bars of the box (t-48 .. t-1)
EDGE = 0.15         # the bottom (top) 15% of the box


def _col(df, k):
    return np.asarray(df[k], dtype=float)


def _box(df):
    """Box lines and filters exactly as lib_c computes them: top, bottom, width, ATR14, ADX14, pos."""
    n = len(df)
    h, l, c = (_col(df, k) for k in ("high", "low", "close"))
    top = pd.Series(h).rolling(BOX).max().shift(1).to_numpy()
    bot = pd.Series(l).rolling(BOX).min().shift(1).to_numpy()
    width = top - bot
    if n:
        atr = fg.atr(df, 14).to_numpy(float)
        adx = fg.dmi_adx(df, 14, 14)[2].to_numpy(float)
    else:
        atr, adx = np.zeros(0), np.zeros(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        pos = (c - bot) / width
    return top, bot, width, atr, adx, pos


def _box_lines(top, bot, width):
    """The box and its 15% zones as four lines."""
    return [
        {"name": "박스 위(직전 48봉 최고가)", "values": top},
        {"name": "숏 구역 시작(위 15%)", "values": top - EDGE * width},
        {"name": "롱 구역 끝(아래 15%)", "values": bot + EDGE * width},
        {"name": "박스 아래(직전 48봉 최저가)", "values": bot},
    ]


def view_DS_F5_BOX(df, tf):
    """F5_BOX: a candle closing in the right 15% edge of a sideways 48-bar box, coloured away from the edge. Exact."""
    o, c = _col(df, "open"), _col(df, "close")
    top, bot, width, atr, adx, pos = _box(df)
    with np.errstate(invalid="ignore", divide="ignore"):
        flat = adx < 20
        wide = width >= 3 * atr
        low_zone = (pos >= 0) & (pos <= EDGE)
        high_zone = (pos >= 1 - EDGE) & (pos <= 1)
        ratio = width / atr
    return {
        "overlays": _box_lines(top, bot, width),
        "panes": [
            {"name": "ADX 14 (20 미만 = 횡보)", "levels": [20], "series": [{"name": "ADX 14", "values": adx}]},
            {"name": "박스 폭 ÷ ATR (3 이상)", "levels": [3],
             "series": [{"name": "박스 폭 ÷ ATR", "values": ratio}]},
        ],
        "long": [
            ("횡보장(ADX 20 미만)", flat),
            ("박스 폭이 ATR의 3배 이상", wide),
            ("종가가 박스 아래쪽 15% 안", low_zone),
            ("양봉 마감", c > o),
        ],
        "short": [
            ("횡보장(ADX 20 미만)", flat),
            ("박스 폭이 ATR의 3배 이상", wide),
            ("종가가 박스 위쪽 15% 안", high_zone),
            ("음봉 마감", c < o),
        ],
    }
