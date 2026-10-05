"""Chart view for DS_F15_ORB (DeepSeek-200 F15_ORB, F15 시가 범위 돌파 = Opening Range Breakout): its lines and entry
conditions.

Rule (research/deepseek200/PREREG_DEEPSEEK200.md sections 4 and 5, F15): per UTC day (00:00 UTC = 09:00 KST, no
daylight saving), the opening range = high / low of the day's first 2 bars, which must be the bars opening at 00:00
UTC and 00:00 UTC + one bar (15m: 09:00-09:30 KST, 30m: 09:00-10:00, 1h: 09:00-11:00, 4h: 09:00-17:00). From the third
bar to the day's last bar, the first close above the range high -> long, the first close below the range low -> short;
one a day, the side that comes first. The two range bars never signal. All four timeframes. The chart draws the range
high / low as a box: growing over the two range bars, then held for the rest of the day.

Same rules as research/deepseek200/lib_c.py ``utc_day_signals()`` (ORB_BARS = 2; the live signal is
paperbot/dssig.py), written again with numpy / pandas; lib_c is not imported here. lib_c drops both sides when long
and short fire on one bar; a close cannot be above the high and below the low at once, so that rule never acts and is
not a line.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored). Bars:
Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars), ETH 1h
(50,351), DOGE 30m (100,701), SOL 4h (12,588), and (b) the live DeepSeek frames: the last config.DS_WINDOW_5M[tf]
closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes per series (first full window ..
2026-09) for BTC 15m, ETH 1h, BCH 30m, SOL 1h, DOGE 15m, LTC 4h (144 frames). Signals checked: full series long 3,978
/ short 3,915; live frames long 9,020 / short 8,666; 0 differing bars. Synthetic bars across both DST changes, with
bars and a whole day missing: also 0 differing bars.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1}
tests/test_strategy_views_ds_f15.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
import pandas as pd

_TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}
_NR = 2                                            # opening range = the day's first 2 bars (lib_c.ORB_BARS)


def _cols(df):
    return tuple(np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))


def _days(day):
    """(start, end) of each run of equal UTC dates."""
    if len(day) == 0:
        return []
    cut = np.flatnonzero(np.diff(day) != 0) + 1
    return list(zip(np.r_[0, cut].tolist(), np.r_[cut, len(day)].tolist()))


def view_DS_F15_ORB(df, tf):
    """F15_ORB: the day's first close outside the range of its first 2 bars (UTC day). Exact (lib_c.utc_day_signals)."""
    _o, h, l, c = _cols(df)
    n = len(c)
    tfm = _TF_MIN.get(tf, 0)
    hi, lo = np.full(n, np.nan), np.full(n, np.nan)
    ready, after, first = np.zeros(n, bool), np.zeros(n, bool), np.ones(n, bool)
    if n and tfm:
        ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
        dayd = ts.astype("datetime64[D]")
        mins = ((ts - dayd.astype("datetime64[ns]")) // np.timedelta64(1, "m")).astype(np.int64)
        for a, b in _days(dayd.astype(np.int64)):
            k = min(_NR, b - a)
            hi[a:a + k] = np.maximum.accumulate(h[a:a + k])
            lo[a:a + k] = np.minimum.accumulate(l[a:a + k])
            hi[a + k:b], lo[a + k:b] = hi[a + k - 1], lo[a + k - 1]
            after[a + _NR:b] = True
            if b - a >= _NR and np.array_equal(mins[a:a + _NR], np.arange(_NR) * tfm):
                ready[a + _NR - 1:b] = True
            with np.errstate(invalid="ignore"):
                ev = (after[a:b] & ((c[a:b] > hi[a:b]) | (c[a:b] < lo[a:b]))).astype(np.int64)
            first[a:b] = (np.cumsum(ev) - ev) == 0
    with np.errstate(invalid="ignore"):
        up, dn = c > hi, c < lo
    return {
        "overlays": [
            {"name": "시가 범위 고가(한국 오전 9시부터 첫 2봉)", "values": hi},
            {"name": "시가 범위 저가(한국 오전 9시부터 첫 2봉)", "values": lo},
        ],
        "panes": [],
        "long": [
            ("오늘 시가 범위 완성(한국 오전 9시부터 첫 2봉 모두 있음)", ready),
            ("범위 만드는 2봉이 지난 뒤(오늘 3번째 봉부터)", after),
            ("종가가 시가 범위 고가 위", up),
            ("오늘 첫 돌파(앞서 범위 밖 마감 없음)", first),
        ],
        "short": [
            ("오늘 시가 범위 완성(한국 오전 9시부터 첫 2봉 모두 있음)", ready),
            ("범위 만드는 2봉이 지난 뒤(오늘 3번째 봉부터)", after),
            ("종가가 시가 범위 저가 아래", dn),
            ("오늘 첫 돌파(앞서 범위 밖 마감 없음)", first),
        ],
    }
