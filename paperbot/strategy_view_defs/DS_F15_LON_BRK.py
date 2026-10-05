"""Chart view for DS_F15_LON_BRK (DeepSeek-200 F15_LON_BRK, F15 세션 레인지): its lines and entry conditions.

Rule (research/deepseek200/PREREG_DEEPSEEK200.md sections 4 and 5, F15): US Eastern wall clock (ET; EDT = UTC-4 from
the second Sunday of March 07:00 UTC to the first Sunday of November 06:00 UTC, EST = UTC-5 otherwise). The London
range of ET date D = high / low of the bars opening 02:00-05:00 ET of D (exactly 3h / bar length bars, else no signal
that day; the spring DST day has no 02:xx bars, so none then). Among the bars opening 05:00-12:00 ET of D, the first
close outside the range gives the signal in its direction (above = long, below = short); one a day. 15m / 30m / 1h
bars only. In Korean time: the range is 15:00-18:00 KST (winter 16:00-19:00), the breakout window 18:00-01:00 KST
(winter 19:00-02:00). The chart draws the range high / low as a box: growing while the range bars come in, then held
until the next day's range starts.

Same rules as research/deepseek200/lib_c.py ``session_signals()`` (the live signal is paperbot/dssig.py), written
again with numpy / pandas; lib_c is not imported here. lib_c drops both sides when long and short fire on one bar; a
close cannot be above the high and below the low at once, so that rule never acts and is not a line.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored). Bars:
Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars), ETH 1h
(50,351), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last config.DS_WINDOW_5M[tf] closed 5m bars
resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes per series (first full window .. 2026-09) for BTC
15m, ETH 1h, BCH 30m, SOL 1h, DOGE 15m (120 frames). Signals checked: full series long 2,787 / short 2,823; live
frames long 4,576 / short 4,543; 0 differing bars. On 4h (any bars other than 15m / 30m / 1h) the first line stays
off, as lib_c gives no signal there (checked on SOL 4h full series and LTC 4h live frames: AND never on). Synthetic
bars across both DST changes, with bars and a whole day missing: also 0 differing bars.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1}
tests/test_strategy_views_ds_f15.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import datetime as _dt

import numpy as np
import pandas as pd

_SES_MIN = {"15m": 15, "30m": 30, "1h": 60}      # ET session rules exist on these bars only
_R0, _R1, _W1 = 2 * 60, 5 * 60, 12 * 60           # London range 02:00-05:00 ET, breakout window 05:00-12:00 ET


def _cols(df):
    return tuple(np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))


def _nth_sunday(year, month, nth):
    d = _dt.date(year, month, 1)
    return d + _dt.timedelta(days=(6 - d.weekday()) % 7 + 7 * (nth - 1))


def _et_clock(df):
    """(ET date as days since 1970-01-01, minute of the ET day) at each bar open, the fixed US rule of lib_c.et_wall."""
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    off = np.full(len(ts), -300, np.int64)
    for y in np.unique(ts.astype("datetime64[Y]").astype(int) + 1970):
        a = np.datetime64(_nth_sunday(int(y), 3, 2).isoformat() + "T07:00", "ns")
        b = np.datetime64(_nth_sunday(int(y), 11, 1).isoformat() + "T06:00", "ns")
        off[(ts >= a) & (ts < b)] = -240
    wall = ts + (off * 60 * 10**9).astype("timedelta64[ns]")
    dayd = wall.astype("datetime64[D]")
    mins = ((wall - dayd.astype("datetime64[ns]")) // np.timedelta64(1, "m")).astype(np.int64)
    return dayd.astype(np.int64), mins


def _days(day):
    """(day, start, end) of each run of equal ET dates."""
    if len(day) == 0:
        return []
    cut = np.flatnonzero(np.diff(day) != 0) + 1
    return [(int(day[a]), int(a), int(b)) for a, b in zip(np.r_[0, cut], np.r_[cut, len(day)])]


def view_DS_F15_LON_BRK(df, tf):
    """F15_LON_BRK: the first close outside the London range (02-05 ET) in 05-12 ET. Exact (lib_c.session_signals)."""
    _o, h, l, c = _cols(df)
    n = len(c)
    hi, lo = np.full(n, np.nan), np.full(n, np.nan)
    ready, win, first = np.zeros(n, bool), np.zeros(n, bool), np.ones(n, bool)
    tfm = _SES_MIN.get(tf, 0)
    day, mins = _et_clock(df) if n else (np.zeros(0, np.int64), np.zeros(0, np.int64))
    held = (np.nan, np.nan)
    for _d, a, b in (_days(day) if tfm else []):
        m = mins[a:b]
        hi[a:b], lo[a:b] = held                         # yesterday's box until today's range starts
        k = np.flatnonzero((m >= _R0) & (m < _R1))
        win[a:b] = (m >= _R1) & (m < _W1)
        if len(k):
            hh, ll = np.maximum.accumulate(h[a + k]), np.minimum.accumulate(l[a + k])
            hi[a + k], lo[a + k] = hh, ll
            held = (float(hh[-1]), float(ll[-1]))
            hi[a + k[-1] + 1:b], lo[a + k[-1] + 1:b] = held
            if len(k) == 180 // tfm:
                ready[a + k[-1]:b] = True
        with np.errstate(invalid="ignore"):
            ev = (win[a:b] & ((c[a:b] > hi[a:b]) | (c[a:b] < lo[a:b]))).astype(np.int64)
        first[a:b] = (np.cumsum(ev) - ev) == 0
    with np.errstate(invalid="ignore"):
        up, dn = c > hi, c < lo
    return {
        "overlays": [
            {"name": "런던 레인지 고가(한국 15~18시, 겨울 16~19시)", "values": hi},
            {"name": "런던 레인지 저가(한국 15~18시, 겨울 16~19시)", "values": lo},
        ],
        "panes": [],
        "long": [
            ("런던 레인지 완성(한국 15~18시, 겨울 16~19시 봉 모두 있음)", ready),
            ("돌파 시간대 안(한국 18시~새벽 1시, 겨울 19시~새벽 2시)", win),
            ("종가가 런던 레인지 고가 위", up),
            ("오늘 첫 돌파(앞서 레인지 밖 마감 없음)", first),
        ],
        "short": [
            ("런던 레인지 완성(한국 15~18시, 겨울 16~19시 봉 모두 있음)", ready),
            ("돌파 시간대 안(한국 18시~새벽 1시, 겨울 19시~새벽 2시)", win),
            ("종가가 런던 레인지 저가 아래", dn),
            ("오늘 첫 돌파(앞서 레인지 밖 마감 없음)", first),
        ],
    }
