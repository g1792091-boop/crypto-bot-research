"""Chart view for DS_F4_FAN: DeepSeek-200 definition F4_FAN (F4 EMA 눌림·정렬), its lines and entry conditions.

Rule (PREREG_DEEPSEEK200.md section 5, F4): the Fibonacci EMA ribbon 8 / 13 / 21 / 34 / 55. Long on the first bar
where the ribbon is fully stacked upward (EMA8 > EMA13 > EMA21 > EMA34 > EMA55) and the previous bar was not; short
on the first bar fully stacked downward. The chart shows the five EMAs and a pane with the ribbon order score
(+1 for each pair in up order, -1 for each pair in down order: +4 = fully up, -4 = fully down).

Same rules as research/deepseek200/lib_c.py ``entries()`` (the live signal is paperbot/dssig.py), written again with
the vendored pine_indicators; lib_c is not imported here. lib_c drops both sides when long and short fire on one
bar; here the sides exclude each other (EMA8 above vs below EMA13), so that rule never acts and is not a line.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 6,697 / short 6,682; live frames long 9,664 / short 10,085; 0 differing bars.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1}
tests/test_strategy_views_ds_f4_f7.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
import pine_indicators as pi

_LENS = (8, 13, 21, 34, 55)


def _ga(k):
    """Korean subject particle after the number k as read aloud (34 -> 삼십사가, 13 -> 십삼이)."""
    return "가" if k % 10 in (2, 4, 5, 9) else "이"


def _prevb(x, k=1):
    """Boolean value of the bar k bars back (False where there is none)."""
    x = np.asarray(x, bool)
    out = np.zeros(len(x), bool)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def view_DS_F4_FAN(df, tf):
    """F4_FAN: first bar of a fully stacked EMA 8/13/21/34/55 ribbon. Exact."""
    c = np.asarray(df["close"], dtype=float)
    em = [pi.pine_ema(c, k) for k in _LENS]
    pairs = list(zip(_LENS[:-1], em[:-1], _LENS[1:], em[1:]))
    with np.errstate(invalid="ignore"):
        ups = [a > b for _ka, a, _kb, b in pairs]
        dns = [a < b for _ka, a, _kb, b in pairs]
        fan_up = np.logical_and.reduce(ups)
        fan_dn = np.logical_and.reduce(dns)
        score = np.sum([u.astype(float) - d.astype(float) for u, d in zip(ups, dns)], axis=0)
        score = np.where(np.isfinite(em[-1]), score, np.nan)
    long = [(f"EMA{ka}{_ga(ka)} EMA{kb} 위", u) for (ka, _a, kb, _b), u in zip(pairs, ups)]
    long.append(("직전 봉은 정배열 아님(이번 봉에 처음 완성)", ~_prevb(fan_up)))
    short = [(f"EMA{ka}{_ga(ka)} EMA{kb} 아래", d) for (ka, _a, kb, _b), d in zip(pairs, dns)]
    short.append(("직전 봉은 역배열 아님(이번 봉에 처음 완성)", ~_prevb(fan_dn)))
    return {
        "overlays": [{"name": f"EMA{k}", "values": e} for k, e in zip(_LENS, em)],
        "panes": [
            {"name": "리본 정렬 점수(+4 정배열 · -4 역배열)",
             "series": [{"name": "정렬 점수", "values": np.asarray(score, float)}],
             "levels": [-4, 0, 4]},
        ],
        "long": [(k, np.asarray(a, bool)) for k, a in long],
        "short": [(k, np.asarray(a, bool)) for k, a in short],
    }
