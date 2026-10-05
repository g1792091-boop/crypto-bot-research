"""Chart view for DS_F15_OPEN0000 (DeepSeek-200 F15_OPEN0000, F15 시가 편향): its line and entry conditions.

Rule (research/deepseek200/PREREG_DEEPSEEK200.md sections 4 and 5, F15): US Eastern wall clock (ET; EDT = UTC-4 from
the second Sunday of March 07:00 UTC to the first Sunday of November 06:00 UTC, EST = UTC-5 otherwise). Reference time
T = 00:00 ET (midnight). Reference bar of ET date D = the bar containing the reference time (open <= T < open + bar
length); reference price = its open. Judging bar = the first bar from the reference bar on that closes at or after T +
60 minutes (15m: the 00:45 bar, 30m: the 00:30 bar, 1h: the reference bar itself). Long when the judging bar closes
above the reference price, short when below (equal: none); one a day; no signal that day when a bar is missing between
the reference bar and the judging bar. 15m / 30m / 1h bars only. In Korean time: T = 13:00 KST (winter 14:00), judged
on the bar closing at or after 14:00 KST (winter 15:00). The chart draws the reference price from the reference bar
until the next day's reference bar.

Same rules as research/deepseek200/lib_c.py ``session_signals()`` (the live signal is paperbot/dssig.py), written
again with numpy / pandas; lib_c is not imported here. lib_c drops both sides when long and short fire on one bar; a
close cannot be above and below the reference price at once, so that rule never acts and is not a line.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored). Bars:
Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars), ETH 1h
(50,351), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last config.DS_WINDOW_5M[tf] closed 5m bars
resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes per series (first full window .. 2026-09) for BTC
15m, ETH 1h, BCH 30m, SOL 1h, DOGE 15m (120 frames). Signals checked: full series long 3,190 / short 3,088; live
frames long 5,215 / short 5,074; 0 differing bars. On 4h (any bars other than 15m / 30m / 1h) the first line stays
off, as lib_c gives no signal there (checked on SOL 4h full series and LTC 4h live frames: AND never on). Synthetic
bars across both DST changes, with bars and a whole day missing: also 0 differing bars.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1}
tests/test_strategy_views_ds_f15.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import datetime as _dt

import numpy as np
import pandas as pd

_SES_MIN = {"15m": 15, "30m": 30, "1h": 60}      # ET session rules exist on these bars only


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


def _open_bias(df, tf, tref):
    """Reference price (held until the next day's reference bar) and the per-bar flags of the open-bias rule."""
    o, _h, _l, c = _cols(df)
    n = len(c)
    ref = np.full(n, np.nan)
    has_ref, judge, nogap = np.zeros(n, bool), np.zeros(n, bool), np.zeros(n, bool)
    tfm = _SES_MIN.get(tf, 0)
    day, mins = _et_clock(df) if n else (np.zeros(0, np.int64), np.zeros(0, np.int64))
    held = np.nan
    for _d, a, b in (_days(day) if tfm else []):
        m = mins[a:b]
        ref[a:b] = held
        r = np.flatnonzero((m <= tref) & (tref < m + tfm))
        if not len(r):
            continue
        r0 = int(r[0])
        held = float(o[a + r0])
        ref[a + r0:b] = held
        has_ref[a + r0:b] = True
        nogap[a + r0:b] = (m[r0:] - m[r0]) == np.arange(b - a - r0) * tfm
        cand = np.flatnonzero((np.arange(b - a) >= r0) & (m + tfm >= tref + 60))
        if len(cand):
            judge[a + int(cand[0])] = True
    with np.errstate(invalid="ignore"):
        return ref, has_ref, judge, nogap, c > ref, c < ref


def view_DS_F15_OPEN0000(df, tf):
    """F15_OPEN0000: close of the first bar ending at or after 01:00 ET vs the open of the 00:00 ET bar.
    Exact (lib_c.session_signals)."""
    ref, has_ref, judge, nogap, above, below = _open_bias(df, tf, 0)
    first = [
        ("오늘 기준 봉 있음(미국 동부 자정 봉, 한국 13시, 겨울 14시)", has_ref),
        ("판단 봉(자정에서 1시간 지나 마감하는 첫 봉)", judge),
        ("기준 봉부터 빠진 봉 없음", nogap),
    ]
    return {
        "overlays": [{"name": "기준 가격(미국 동부 자정 봉의 시가)", "values": ref}],
        "panes": [],
        "long": first + [("종가가 기준 가격 위", above)],
        "short": first + [("종가가 기준 가격 아래", below)],
    }
