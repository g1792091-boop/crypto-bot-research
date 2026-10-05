"""Chart view for DS_F4_PULL_RSI: DeepSeek-200 definition F4_PULL_RSI (F4 EMA 눌림·정렬), its lines and entry conditions.

Rule (PREREG_DEEPSEEK200.md section 5, F4): long when EMA20 was above EMA50 on the previous bar (up-trend), the
close is above EMA50, and RSI(14) crosses up through 40 on this bar (RSI[t-1] <= 40 < RSI[t]): the dip ends inside
the trend. Short mirrored (EMA20 < EMA50, close < EMA50, RSI[t-1] >= 60 > RSI[t]). The chart shows EMA20 and EMA50
and an RSI pane with the 40 and 60 lines.

Same rules as research/deepseek200/lib_c.py ``entries()`` (the live signal is paperbot/dssig.py), written again with
the vendored pine_indicators; lib_c is not imported here. lib_c drops both sides when long and short fire on one
bar; here the sides exclude each other (close above vs below EMA50), so that rule never acts and is not a line.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 327 / short 307; live frames long 468 / short 465; 0 differing bars.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1}
tests/test_strategy_views_ds_f4_f7.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
import pine_indicators as pi


def _cols(df):
    return tuple(np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))


def _prev(x, k=1):
    """Value of the bar k bars back (NaN where there is none)."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def _prevb(x, k=1):
    """Boolean value of the bar k bars back (False where there is none)."""
    x = np.asarray(x, bool)
    out = np.zeros(len(x), bool)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def view_DS_F4_PULL_RSI(df, tf):
    """F4_PULL_RSI: EMA20 vs EMA50 trend on the previous bar, close on the trend side of EMA50, RSI14 crosses 40 / 60.
    Exact."""
    _o, _h, _l, c = _cols(df)
    e20, e50 = pi.pine_ema(c, 20), pi.pine_ema(c, 50)
    rsi = pi.pine_rsi(c, 14) if len(c) else np.zeros(0)
    r1 = _prev(rsi)
    with np.errstate(invalid="ignore"):
        long = [
            ("직전 봉 EMA20이 EMA50 위(상승 흐름)", _prevb(e20 > e50)),
            ("종가가 EMA50 위", c > e50),
            ("직전 봉 RSI 40 이하(눌림)", r1 <= 40),
            ("이번 봉 RSI 40 위로 올라섬", rsi > 40),
        ]
        short = [
            ("직전 봉 EMA20이 EMA50 아래(하락 흐름)", _prevb(e20 < e50)),
            ("종가가 EMA50 아래", c < e50),
            ("직전 봉 RSI 60 이상(반등)", r1 >= 60),
            ("이번 봉 RSI 60 아래로 내려옴", rsi < 60),
        ]
    return {
        "overlays": [
            {"name": "EMA20", "values": e20},
            {"name": "EMA50 (추세 기준선)", "values": e50},
        ],
        "panes": [
            {"name": "RSI 14", "series": [{"name": "RSI 14", "values": rsi}], "levels": [40, 60]},
        ],
        "long": [(k, np.asarray(a, bool)) for k, a in long],
        "short": [(k, np.asarray(a, bool)) for k, a in short],
    }
