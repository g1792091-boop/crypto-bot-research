"""Chart view for DS_F4_PULL: DeepSeek-200 definition F4_PULL (F4 EMA 눌림·정렬), its lines and entry conditions.

Rule (PREREG_DEEPSEEK200.md section 5, F4): long when, on the previous bar, the EMAs were stacked upward
(EMA9 > EMA50 > EMA200) and this bar dipped to EMA50 (low <= EMA50) but closed back above it (close > EMA50): a
pull-back into the trend that held. Short mirrored (EMA9 < EMA50 < EMA200, high >= EMA50, close < EMA50). The chart
shows the three EMAs (pine EMA, first value = mean of the first window, as lib_c).

Same rules as research/deepseek200/lib_c.py ``entries()`` (the live signal is paperbot/dssig.py), written again with
the vendored pine_indicators; lib_c is not imported here. lib_c drops both sides when long and short fire on one
bar; here the sides exclude each other (close above vs below EMA50), so that rule never acts and is not a line.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 11,663 / short 11,505; live frames long 16,047 / short 16,921; 0 differing bars.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1}
tests/test_strategy_views_ds_f4_f7.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
import pine_indicators as pi


def _cols(df):
    return tuple(np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))


def _prevb(x, k=1):
    """Boolean value of the bar k bars back (False where there is none)."""
    x = np.asarray(x, bool)
    out = np.zeros(len(x), bool)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def view_DS_F4_PULL(df, tf):
    """F4_PULL: EMA 9/50/200 stacked on the previous bar, this bar dips to EMA50 and closes back beyond it. Exact."""
    _o, h, l, c = _cols(df)
    e9, e50, e200 = (pi.pine_ema(c, k) for k in (9, 50, 200))
    with np.errstate(invalid="ignore"):
        long = [
            ("직전 봉 단기선 EMA9가 EMA50 위", _prevb(e9 > e50)),
            ("직전 봉 EMA50이 장기선 EMA200 위(정배열)", _prevb(e50 > e200)),
            ("이번 봉 저가가 EMA50까지 눌림", l <= e50),
            ("종가는 EMA50 위로 복귀", c > e50),
        ]
        short = [
            ("직전 봉 단기선 EMA9가 EMA50 아래", _prevb(e9 < e50)),
            ("직전 봉 EMA50이 장기선 EMA200 아래(역배열)", _prevb(e50 < e200)),
            ("이번 봉 고가가 EMA50까지 반등", h >= e50),
            ("종가는 EMA50 아래로 마감", c < e50),
        ]
    return {
        "overlays": [
            {"name": "EMA9 (단기선)", "values": e9},
            {"name": "EMA50 (눌림 기준선)", "values": e50},
            {"name": "EMA200 (장기선)", "values": e200},
        ],
        "panes": [],
        "long": [(k, np.asarray(a, bool)) for k, a in long],
        "short": [(k, np.asarray(a, bool)) for k, a in short],
    }
