"""candleague/league.py on the custom-value shadow's synthetic bars: the default account gets exactly the shadow's
signals (same machinery), a candidate gets the shadow's same-numbers signals with its own stop width, a coin flip
trades its candidate's times with seeded sides, a structure exit carries its level, and a day replays."""

from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_paramshadow as TP  # noqa: E402  (synthetic 5m bars, 1m steps, brackets)
from candleague import candidates as C  # noqa: E402
from candleague import exits as X  # noqa: E402
from candleague import league as L  # noqa: E402
from paperbot import paramshadow as PS  # noqa: E402
from paperbot import sweepsig  # noqa: E402

data = {s: TP._synth5(i + 3, TP.P0[s]) for i, s in enumerate(TP.SYMS)}    # the shadow tests' bars
NAME, TF = "S2_ST_ROC", "15m"
START, END = TP.D0, TP.D0 + TP.DAY


def _accts(exit_="tp1.5R|1.5", **over):
    combo = {**C.default_combo("core", NAME), **over}
    cand = {"id": "core-S2-15m-1", "kind": "core", "name": NAME, "tf": TF, "combo": {k: C._plain(v)
            for k, v in combo.items()}, "exit": exit_, "source": {}}
    return C.accounts([cand])


def _shadow_signals():
    pmod = PS.param_module(NAME)
    smod = L.Strategies().strength(NAME)
    by_close, _counts, _notes = PS.chunk_signals(sweepsig.lib(), PS.FrameSource(data), {NAME: (pmod, smod,
                                                 PS.variants_of(pmod))}, TP.SYMS, (TF,), START, END, TP.RUN_START)
    out = {}
    for close, items in by_close.items():
        for aid, sig in items:
            out.setdefault(aid.split("#")[1], []).append((close, sig.symbol, sig.side, sig.meta["stop_dist"],
                                                          sig.meta["ctx"]["strength"]))
    return out


def _league_signals(accts):
    by_close, notes = L.chunk_signals(sweepsig.lib(), PS.FrameSource(data), accts, TP.SYMS, START, END, TP.RUN_START)
    out = {}
    for close, items in by_close.items():
        for aid, sig in items:
            out.setdefault(aid, []).append((close, sig.symbol, sig.side, sig.meta["stop_dist"],
                                            sig.meta["ctx"]["strength"], sig.meta.get("tp_struct")))
    return out, notes


def test_base_and_candidate_follow_the_shadow():
    sh = _shadow_signals()
    default = C.default_combo("core", NAME)
    accts = _accts(st_mult=default["st_mult"] * 1.25)
    lg, _ = _league_signals(accts)
    base = sorted(x[:5] for x in lg["base-core-S2_ST_ROC-15m"])
    assert base == sorted(sh["base"]) and len(base) > 3
    cand = sorted(lg["core-S2-15m-1"])
    want = sorted(sh["st_multx1.25"])
    assert [x[:3] for x in cand] == [x[:3] for x in want]
    assert all(abs(a[3] / b[3] - 1.5 / 2.0) < 1e-12 for a, b in zip(cand, want))      # its own stop: 1.5 ATR
    assert [x[4] for x in cand] == [x[4] for x in want]                                   # same strength record


def test_flip_trades_its_candidates_times_with_seeded_sides():
    accts = _accts()
    lg, _ = _league_signals(accts)
    cand, flip = sorted(lg["core-S2-15m-1"]), sorted(lg["core-S2-15m-1-flip"])
    assert [x[:2] for x in cand] == [x[:2] for x in flip]
    assert [x[2] for x in flip] == [L.flip_side("core-S2-15m-1-flip", c) for c, *_ in flip]
    assert {x[2] for x in flip} == {1, -1}


def test_structure_exit_carries_its_level():
    lg, _ = _league_signals(_accts(exit_="swing3|2"))
    rows = lg["core-S2-15m-1"]
    assert rows and all(r[5] is not None for r in rows)                  # set on every signal (NaN: no level)
    assert any(np.isfinite(r[5]) for r in rows)
    assert all(r[5] is None for r in lg["base-core-S2_ST_ROC-15m"])        # the live exit has no level


def test_a_day_replays_through_each_accounts_exit():
    accts = _accts(exit_="tp1R|1")
    by_close, _ = L.chunk_signals(sweepsig.lib(), PS.FrameSource(data), accts, TP.SYMS, START, END, TP.RUN_START)
    engines = L.make_engines(accts, TP.BRACKETS, TP.SPECS)
    steps = TP._steps_from(data)(None, list(TP.SYMS), START, END + TP.DAY)
    PS.replay_day(engines, set(), by_close, steps, TP.BRACKETS)
    reasons = {a: {t.exit_reason for t in engines[a].trades} for a in engines}
    assert engines["core-S2-15m-1"].trades and "TP" in reasons["core-S2-15m-1"]           # 1R take-profits fill
    assert "TP" not in reasons["base-core-S2_ST_ROC-15m"]                                  # the live exit has none
    assert isinstance(engines["core-S2-15m-1"], X.PaperEngine)
