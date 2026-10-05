"""Chart view for DS_F5_BOX_RSI (DeepSeek-200 F5_BOX_RSI, F5 박스권): its lines and entry conditions.

Rule (PREREG_DEEPSEEK200.md section 5, F5): the box is the highest high and the lowest low of the previous 48 bars
(t-48 .. t-1), width = top - bottom. The box counts only when ADX(14) < 20 (fg.dmi_adx(14, 14): no trend) and the
width is at least 3 x ATR14 (fg.atr). pos = (close - bottom) / width.
Long: the box counts, 0 <= pos <= 0.15 and RSI(14) (pine_rsi) < 30 (no candle colour).
Short: the box counts, 0.85 <= pos <= 1 and RSI(14) > 70. A close outside the box gives no signal.
Long and short need opposite ends of the box, so they never fire on one bar.

The chart draws the box (top, bottom) and its 15% zones (the line 15% above the bottom, the line 15% below the top);
the panes show ADX(14) against 20 and RSI(14) against 30 / 70.

Same rules as research/deepseek200/lib_c.py ``entries()`` (the live signal is paperbot/dssig.py),
written again with numpy / pandas and the vendored fg_indicators / pine_indicators; lib_c is not imported here.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 131 / short 186; live frames long 224 / short 355; 0 differing
bars. "signals" = lib_c signals of that series (live: summed over its 24 frames).
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_long_signals": 65, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "BTC15m_short_signals": 92, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_long_signals": 28, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "ETH1h_short_signals": 48, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_long_signals": 5, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "SOL4h_short_signals": 9, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_long_signals": 33, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "DOGE30m_short_signals": 37, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_long_signals": 49, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "BTC15m_live_short_signals": 70, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_long_signals": 41, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "ETH1h_live_short_signals": 70, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_long_signals": 35, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1, "LTC4h_live_short_signals": 84, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_long_signals": 26, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "BCH30m_live_short_signals": 33, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_long_signals": 26, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "SOL1h_live_short_signals": 53, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_long_signals": 47, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1, "DOGE15m_live_short_signals": 45}
tests/test_strategy_views_ds_f1_f8.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
import pandas as pd
import fg_indicators as fg
import pine_indicators as pi

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


def view_DS_F5_BOX_RSI(df, tf):
    """F5_BOX_RSI: a close in the right 15% edge of a sideways 48-bar box with RSI(14) beyond 30 / 70. Exact."""
    c = _col(df, "close")
    top, bot, width, atr, adx, pos = _box(df)
    rsi = np.asarray(pi.pine_rsi(c, 14), dtype=float) if len(c) else np.zeros(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        flat = adx < 20
        wide = width >= 3 * atr
        low_zone = (pos >= 0) & (pos <= EDGE)
        high_zone = (pos >= 1 - EDGE) & (pos <= 1)
    return {
        "overlays": _box_lines(top, bot, width),
        "panes": [
            {"name": "ADX 14 (20 미만 = 횡보)", "levels": [20], "series": [{"name": "ADX 14", "values": adx}]},
            {"name": "RSI 14 (30 아래 롱 · 70 위 숏)", "levels": [30, 70],
             "series": [{"name": "RSI 14", "values": rsi}]},
        ],
        "long": [
            ("횡보장(ADX 20 미만)", flat),
            ("박스 폭이 ATR의 3배 이상", wide),
            ("종가가 박스 아래쪽 15% 안", low_zone),
            ("RSI 30 미만(과매도)", rsi < 30),
        ],
        "short": [
            ("횡보장(ADX 20 미만)", flat),
            ("박스 폭이 ATR의 3배 이상", wide),
            ("종가가 박스 위쪽 15% 안", high_zone),
            ("RSI 70 초과(과매수)", rsi > 70),
        ],
    }
