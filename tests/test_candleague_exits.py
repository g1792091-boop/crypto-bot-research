"""candleague/exits.py: the same 84 exit rules as the study's kernel, and PaperEngine set up by make_engine gives the
kernel's trade for every take-profit rule (the study's own parity test, with the league's engine factory)."""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_fullgrid_kernel as TK  # noqa: E402  (synthetic bars, the kernel, the study's helpers)
from candleague import exits as X  # noqa: E402

K = TK.K


def test_same_rules_as_the_kernel():
    assert X.EXITS == K.EXITS
    assert X.STRUCT_LOOKBACK == K.STRUCT_LOOKBACK and X.LIVE_EXIT == "ladder|2"
    assert X.exit_ko("tp1.5R|2.5") == "고정 익절 1.5R · 손절 2.5 ATR"


@pytest.mark.parametrize("k", [3, 10])
def test_structure_level_equals_the_kernel(k):
    rng = np.random.default_rng(k)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 900)))
    h, lo = c * (1 + rng.uniform(0, 0.006, 900)), c * (1 - rng.uniform(0, 0.006, 900))
    tl, ts = K.structure_levels(h, lo, c, k, K.STRUCT_LOOKBACK)
    for i in rng.integers(0, 900, 120):
        a, b = X.structure_level(h, lo, c, int(i), k, 1), X.structure_level(h, lo, c, int(i), k, -1)
        assert (math.isnan(a) and math.isnan(tl[i])) or a == tl[i], (i, a, tl[i])
        assert (math.isnan(b) and math.isnan(ts[i])) or b == ts[i], (i, b, ts[i])
        # only bars up to i are needed (what a live account has at the signal bar's close)
        assert (math.isnan(a) and math.isnan(X.structure_level(h[:i + 1], lo[:i + 1], c[:i + 1], int(i), k, 1))) \
            or a == X.structure_level(h[:i + 1], lo[:i + 1], c[:i + 1], int(i), k, 1)


def _replay(data, sigs, br, name, size=1.0):
    """tests/test_fullgrid_kernel.replay with the league's engine factory."""
    e = X.make_engine(name, br, {"BTCUSDT": TK.SPEC}, size=size)
    k_stop = X.spec(name)["stop_atr"]
    sigs = sorted(sigs, key=lambda x: x[1])
    q = 0
    for j, t in enumerate(data["ts"]):
        t = int(t)
        bars = {"BTCUSDT": TK.bars_at(data, "BTCUSDT", j)}
        fund = {"BTCUSDT": float(data["fund"][j])} if data["fund"][j] != 0 else None
        for sig in e.pending:
            if "ref_price" not in sig.meta:
                sig.meta["ref_price"] = float(bars["BTCUSDT"].open)
        e.step(bars, fund)
        while q < len(sigs) and sigs[q][1] <= t + TK.MIN:
            sym, close, side, atr, best, lvl = sigs[q]
            e.submit(TK.signal(sym, close, side, atr, best, k_stop, lvl))
            q += 1
    return e


@pytest.mark.parametrize("exit_", TK.EXIT_IDS)
def test_league_engine_gives_the_kernels_trade(exit_):
    name = K.EXITS[exit_][0]
    data = TK.synth_1m(30_000, seed=17)
    rng = np.random.default_rng(23)
    n = 0
    for _ in range(60):
        close = int(TK.T0 + rng.integers(5, 1900) * 15 * TK.MIN)
        side = int(rng.choice([1, -1]))
        atr = float(data["c"][(close - TK.T0) // TK.MIN] * rng.uniform(0.0008, 0.01))
        best = bool(rng.random() < 0.5)
        j = (close - TK.T0) // TK.MIN
        lvl = float(data["c"][j] * (1 + rng.choice([1, -1]) * rng.uniform(0.002, 0.04)))
        d, x, r, lev = TK.kernel_alone(data, close, side, atr, best, TK.WIDE, exit_=exit_, tp_struct=lvl)
        e = _replay(data, [("BTCUSDT", close, side, atr, best, lvl)], {"BTCUSDT": TK.WIDE}, name)
        if r in (K.R_REJECT, K.R_OPEN):
            assert not e.trades
            continue
        t = e.trades[0]
        assert (t.exit_time // TK.MIN * TK.MIN, TK.REASON[t.exit_reason], t.leverage) == (int(data["ts"][x]), r, lev)
        assert abs(t.pnl / 5000.0 - d) < 1e-12, (name, t.pnl, d * 5000)
        n += 1
    assert n >= 30


def test_quarter_size_keeps_the_leverage_and_takes_a_quarter_of_the_margin():
    full, quarter = X.settings_for("tp3R|4"), X.settings_for("tp3R|4", size=0.25)
    assert [(t.name, t.leverages) for t in quarter.tiers] == [(t.name, t.leverages) for t in full.tiers]
    assert [round(t.margin_frac, 6) for t in quarter.tiers] == [round(t.margin_frac / 4, 6) for t in full.tiers]
    data = TK.synth_1m(30_000, seed=17)
    rng = np.random.default_rng(29)
    n = 0
    for _ in range(40):
        close = int(TK.T0 + rng.integers(5, 1900) * 15 * TK.MIN)
        side = int(rng.choice([1, -1]))
        atr = float(data["c"][(close - TK.T0) // TK.MIN] * rng.uniform(0.0008, 0.004))
        sig = [("BTCUSDT", close, side, atr, False, float("nan"))]
        a = _replay(data, sig, {"BTCUSDT": TK.WIDE}, "tp3R|4")
        b = _replay(data, sig, {"BTCUSDT": TK.WIDE}, "tp3R|4", size=0.25)
        if not a.trades or not b.trades:
            continue
        ta, tb = a.trades[0], b.trades[0]
        # a smaller position can pass the 15%-of-wallet stop-loss cap at a higher tier (as sizing.size_vector)
        assert tb.leverage >= ta.leverage
        if tb.leverage != ta.leverage:
            continue
        assert (tb.exit_time, tb.exit_reason) == (ta.exit_time, ta.exit_reason)
        assert abs(tb.pnl - ta.pnl / 4) <= 0.03 * abs(ta.pnl) + 0.05
        n += 1
    assert n >= 10

