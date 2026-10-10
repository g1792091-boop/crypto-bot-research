"""research/fullgrid/edges.py: numbers at a range's end and what a second run would add."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "fullgrid"))

import edges as E  # noqa: E402
import run as R  # noqa: E402


def _pick(kind, name, tf, rank=1, **over):
    combo = {**R.default_combo(kind, name), **over}
    return {"kind": kind, "name": name, "tf": tf, "rank": rank, "exit": "ladder|2",
            "combo": {k: (list(v) if isinstance(v, tuple) else v) for k, v in combo.items()}}


def test_edges_and_what_to_add():
    hi = _pick("core", "S2_ST_ROC", "15m", st_mult=18.0)                 # the largest multiplier
    lo = _pick("core", "S2_ST_ROC", "15m", rank=2, st_atr_len=3)         # the shortest length above 2
    assert E.edges_of(hi) == [{"param": "st_mult", "kind": "mult", "side": "high", "value": 18.0,
                               "now": [2.0, 18.0], "add": [24.0, 30.0]}]
    assert [(e["param"], e["side"], e["add"]) for e in E.edges_of(lo)] == [("st_atr_len", "low", [2])]
    assert E.edges_of(_pick("core", "S2_ST_ROC", "15m")) == []           # the default is in the middle


def test_oscillator_end_is_not_added():
    p = _pick("core", "N14_ICHI_RSI", "1h", rsi_oversold=10.0)           # f = 2: RSI 10, next would be 0 or below
    (e,) = E.edges_of(p)
    assert (e["param"], e["side"], e["add"]) == ("rsi_oversold", "low", [])
    assert 0.0 not in E.extra_values("N14_ICHI_RSI", next(q for q in R.params_of("core", "N14_ICHI_RSI")
                                                         if q["name"] == "rsi_oversold"))


def test_plan_widens_only_where_it_can():
    cells = E.plan([_pick("core", "S2_ST_ROC", "15m", st_mult=18.0),
                    _pick("core", "N14_ICHI_RSI", "1h", rsi_oversold=10.0)])
    s2, n14 = cells["core|S2_ST_ROC|15m"], cells["core|N14_ICHI_RSI|1h"]
    assert s2["widen"] == {"st_mult": [24.0, 30.0]} and s2["top_pick_at_edge"]
    assert s2["combos_now"] == 729 and s2["combos_widened_max"] == 9 * 11 * 9
    assert n14["widen"] == {} and n14["top_pick_at_edge"]
    assert "S2_ST_ROC 15m: st_mult +24.0, 30.0" in E.report_ko(cells)
