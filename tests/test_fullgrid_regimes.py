"""research/fullgrid/regimes.py: the KST weekend and the 15m state each trade falls in."""

from __future__ import annotations

import datetime as dt
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "fullgrid"))

import regimes as RG  # noqa: E402


def _ms(s: str) -> int:
    return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def test_weekend_is_kst():
    # 2026-10-10 is a Saturday; it starts at 2026-10-09 15:00 UTC in KST and ends at 2026-10-11 15:00 UTC (Monday KST)
    t = np.array([_ms("2026-10-09T14:59:00"), _ms("2026-10-09T15:00:00"), _ms("2026-10-11T14:59:00"),
                  _ms("2026-10-11T15:00:00")])
    assert RG.weekend(t).tolist() == [False, True, True, False]


def test_tag_reads_the_signal_bar_the_15m_bar_and_yesterday():
    M15, DAY, Y = RG.M15, RG.DAY, RG.Y
    t0 = _ms("2026-10-05T00:00:00")                          # a Monday
    ts = t0 + M15 * np.arange(8)
    vol = np.array([9, 2, 1, 0, 2, 1, 0, 9], np.int8)
    close = t0 + M15 * np.arange(1, 9)                        # a 15m chart: bar k closes at t0 + (k + 1) x 15 min
    code = np.array([Y.UNKNOWN, Y.TREND, Y.RANGE, Y.SHOCK, Y.NORMAL, Y.TREND, Y.RANGE, Y.SHOCK], np.int8)
    day = np.array([t0 // DAY - 2, t0 // DAY - 1])           # Saturday above its EMA200, Sunday below
    st0 = {"close": close, "code": code, "ts15": ts, "vol": vol, "day": day, "above": np.array([1.0, 0.0])}
    st1 = {"close": close + 5 * M15, "code": code, "ts15": ts + 5 * M15, "vol": vol, "day": day[:1],
           "above": np.array([1.0])}                         # coin 1 starts later and misses Sunday
    T = {"close": np.array([t0 + M15, t0 + 3 * M15, t0 + 8 * M15, t0 + M15, t0 + 6 * M15]),
         "coin": np.array([0, 0, 0, 1, 1])}
    lab = RG.tag(T, [st0, st1])
    assert lab["장세"].tolist() == [None, "횡보장", "급변장", None, None]
    assert lab["변동성"].tolist() == ["큼", "작음", None, None, "큼"]
    assert lab["큰 흐름"].tolist() == ["아래", "아래", "아래", None, None]
    assert lab["요일"].tolist() == ["평일"] * 5
