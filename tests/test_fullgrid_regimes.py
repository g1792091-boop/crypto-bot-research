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


def test_tag_uses_the_15m_bar_the_entry_falls_in():
    M15 = RG.M15
    t0 = _ms("2026-10-05T00:00:00")                          # a Monday
    ts = t0 + M15 * np.arange(8)
    trend = np.array([9, 1, 0, -1, 1, 0, -1, 9], np.int8)
    vol = np.array([9, 2, 1, 0, 2, 1, 0, 9], np.int8)
    states = [(ts, trend, vol), (ts + 5 * M15, trend, vol)]    # coin 1 starts later
    T = {"close": np.array([t0 + M15, t0 + 3 * M15, t0 + 7 * M15, t0 + M15, t0 + 6 * M15]),
         "coin": np.array([0, 0, 0, 1, 1])}
    lab = RG.tag(T, states)
    assert lab["추세"].tolist() == ["상승", "하락", None, None, "상승"]
    assert lab["변동성"].tolist() == ["큼", "작음", None, None, "큼"]
    assert lab["요일"].tolist() == ["평일"] * 5
