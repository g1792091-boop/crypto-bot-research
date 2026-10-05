"""Chart view for DS_F15_ASIA_SWEEP (DeepSeek-200 F15_ASIA_SWEEP, F15 세션 레인지, Judas swing): its lines and entry
conditions.

Rule (research/deepseek200/PREREG_DEEPSEEK200.md sections 4 and 5, F15): US Eastern wall clock (ET; EDT = UTC-4 from
the second Sunday of March 07:00 UTC to the first Sunday of November 06:00 UTC, EST = UTC-5 otherwise). The Asia range
of ET date D = high / low of the bars opening 20:00-24:00 ET of D-1 (exactly 4h / bar length bars, else no signal that
day). In the bars opening 00:00-08:00 ET of D, the first sweep decides: high above the Asia high and close back below
it -> short; low below the Asia low and close back above it -> long. One signal a day, the side that comes first; a
bar that sweeps both sides gives none (and that day has no signal). 15m / 30m / 1h bars only. In Korean time: the
range is 09:00-13:00 KST (winter 10:00-14:00), the sweep window 13:00-21:00 KST (winter 14:00-22:00). The chart draws
the range high / low as a box (the swept levels): growing while the range bars come in, then held until the next range
starts.

Same rules as research/deepseek200/lib_c.py ``session_signals()`` (the live signal is paperbot/dssig.py), written
again with numpy / pandas; lib_c is not imported here. lib_c's rule that drops both sides on one bar never acts here
(a both-sided bar is excluded by the "같은 봉" line already).

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored). Bars:
Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars), ETH 1h
(50,351), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last config.DS_WINDOW_5M[tf] closed 5m bars
resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes per series (first full window .. 2026-09) for BTC
15m, ETH 1h, BCH 30m, SOL 1h, DOGE 15m (120 frames). Signals checked: full series long 2,324 / short 2,386; live
frames long 3,809 / short 3,812; 0 differing bars. On 4h (any bars other than 15m / 30m / 1h) the first line stays
off, as lib_c gives no signal there (checked on SOL 4h full series and LTC 4h live frames: AND never on). Synthetic
bars across both DST changes, with bars and a whole day missing: also 0 differing bars.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1}
tests/test_strategy_views_ds_f15.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import datetime as _dt

import numpy as np
import pandas as pd

_SES_MIN = {"15m": 15, "30m": 30, "1h": 60}      # ET session rules exist on these bars only
_RANGE_FROM, _WIN_END = 20 * 60, 8 * 60           # Asia range 20:00-24:00 ET (day before), window 00:00-08:00 ET


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


def _asia(df, tf):
    """Range box and session flags of the Asia range (ET 20:00-24:00 of the day before)."""
    o, h, l, c = _cols(df)
    n = len(c)
    hi, lo = np.full(n, np.nan), np.full(n, np.nan)
    ready, win = np.zeros(n, bool), np.zeros(n, bool)
    tfm = _SES_MIN.get(tf, 0)
    day, mins = _et_clock(df) if n else (np.zeros(0, np.int64), np.zeros(0, np.int64))
    blocks = _days(day) if tfm else []
    need = 240 // tfm if tfm else 0
    cur = (None, np.nan, np.nan, False)                 # (ET date it is for, high, low, complete)
    for d, a, b in blocks:
        m = mins[a:b]
        today = m < _RANGE_FROM                         # bars that trade today's range
        ok = cur[0] == d and cur[3]
        hi[a:b][today], lo[a:b][today] = cur[1], cur[2]
        ready[a:b][today] = ok
        win[a:b] = today & (m < _WIN_END)
        k = np.flatnonzero(~today)                      # tomorrow's range is being built (20:00-24:00 ET)
        if len(k):
            hh, ll = np.maximum.accumulate(h[a + k]), np.minimum.accumulate(l[a + k])
            hi[a + k], lo[a + k] = hh, ll
            done = len(k) == need
            ready[a + k] = done & (np.arange(1, len(k) + 1) == need)
            cur = (d + 1, float(hh[-1]), float(ll[-1]), done)
    return o, h, l, c, hi, lo, ready, win, blocks, mins >= _RANGE_FROM


def _first(flag, win, blocks, nxt):
    """True while no earlier bar of today's window had ``flag`` (today's one signal is still to come); from 20:00 ET on
    the next day's range is being built, so it is True again."""
    out = np.ones(len(flag), bool)
    ev = (flag & win).astype(np.int64)
    for _d, a, b in blocks:
        out[a:b] = (np.cumsum(ev[a:b]) - ev[a:b]) == 0
    return out | nxt


def view_DS_F15_ASIA_SWEEP(df, tf):
    """F15_ASIA_SWEEP: the first one-sided sweep of the Asia range (20-24 ET) that closes back inside, in 00-08 ET,
    traded against the sweep. Exact (lib_c.session_signals)."""
    _o, h, l, c, hi, lo, ready, win, blocks, nxt = _asia(df, tf)
    with np.errstate(invalid="ignore"):
        poke_hi, back_hi = h > hi, c < hi          # short: above the high, closed back below it
        poke_lo, back_lo = l < lo, c > lo          # long: below the low, closed back above it
    sw_hi, sw_lo = poke_hi & back_hi, poke_lo & back_lo
    first = _first(sw_hi | sw_lo, win, blocks, nxt)
    return {
        "overlays": [
            {"name": "아시아 레인지 고가(한국 09~13시, 겨울 10~14시)", "values": hi},
            {"name": "아시아 레인지 저가(한국 09~13시, 겨울 10~14시)", "values": lo},
        ],
        "panes": [],
        "long": [
            ("아시아 레인지 완성(한국 09~13시, 겨울 10~14시 봉 모두 있음)", ready),
            ("스윕 시간대 안(한국 13~21시, 겨울 14~22시)", win),
            ("저가가 아시아 저가 아래로 찌름", poke_lo),
            ("종가는 아시아 저가 위로 복귀", back_lo),
            ("같은 봉에서 고가 쪽 스윕 없음", ~sw_hi),
            ("오늘 첫 스윕(앞서 레인지 찌르고 복귀한 봉 없음)", first),
        ],
        "short": [
            ("아시아 레인지 완성(한국 09~13시, 겨울 10~14시 봉 모두 있음)", ready),
            ("스윕 시간대 안(한국 13~21시, 겨울 14~22시)", win),
            ("고가가 아시아 고가 위로 찌름", poke_hi),
            ("종가는 아시아 고가 아래로 복귀", back_hi),
            ("같은 봉에서 저가 쪽 스윕 없음", ~sw_lo),
            ("오늘 첫 스윕(앞서 레인지 찌르고 복귀한 봉 없음)", first),
        ],
    }
