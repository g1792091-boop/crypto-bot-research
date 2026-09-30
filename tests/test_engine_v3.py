"""Paper v3 rules in the engine: stepped profit lock, stop distance and
reference price from the signal, no drawdown halt, bust; and trade-by-trade
parity with the research simulator that chose the stop."""

import math
import os
import sys

import numpy as np
import pytest

from paperbot import Bar, Brackets, PaperEngine, Signal
from paperbot.config import v3_settings
from paperbot.ladder import roe_price
from paperbot.notify import ListNotifier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "paper_rules"))

MIN = 60_000
# Mechanics are pinned at the research scale ($1,000, as rules_bt): with the example brackets
# a $5,000 account's top tier does not fit the 50x bracket (test_v3_start_equity_and_bracket_fallback).
S = v3_settings(initial_equity=1000.0)
SLIP = S.slippage_frac
RT = S.round_trip_cost


def bar(i, o, h, l, c, sym="BTCUSDT"):
    return Bar(sym, i * MIN, i * MIN + MIN - 1, o, h, l, c)


def sig(i, side=1, dist=0.5, sym="BTCUSDT", **meta):
    return Signal(ts=i * MIN + MIN - 1, symbol=sym, timeframe="1m", strategy_id="s",
                  side=side, stop_price=0.0, tier="best", atr=dist / 2,
                  meta={"stop_dist": dist, **meta})


def engine(settings=S):
    n = ListNotifier()
    return PaperEngine(settings, {s: Brackets.example() for s in settings.symbols}, notifier=n), n


def test_stop_from_distance_and_no_take_profit():
    e, _ = engine()
    e.submit(sig(0))
    e.step({"BTCUSDT": bar(1, 100, 100.1, 99.9, 100)})
    p = e.position
    assert p.stop_price == pytest.approx(99.5) and p.stop_initial == pytest.approx(99.5)
    assert math.isnan(p.tp_price) and p.leverage == 50


def test_ref_price_fill_and_stop():
    e, _ = engine()
    e.submit(sig(0, side=-1, ref_price=101.0))
    e.step({"BTCUSDT": bar(1, 100, 100.1, 99.9, 100)})
    p = e.position
    assert p.entry_price == pytest.approx(101.0 * (1 - SLIP))
    assert p.stop_price == pytest.approx(101.5)


def test_lock_steps_up_and_exits_as_lock():
    e, _ = engine()
    e.submit(sig(0))
    e.step({"BTCUSDT": bar(1, 100, 100.1, 99.9, 100)})
    p = e.position
    fill, lev = p.entry_price, p.leverage
    # best net ROE reaches ~+19.5%: arms the 15% lock after this bar
    e.step({"BTCUSDT": bar(2, 100, 100.55, 100.0, 100.5)})
    assert p.lock_roe == pytest.approx(0.15)
    lock_px = roe_price(1, fill, lev, 0.15, RT)
    assert p.stop_price == pytest.approx(lock_px)
    # a lower high never lowers the lock
    e.step({"BTCUSDT": bar(3, 100.5, 100.51, 100.49, 100.5)})
    assert p.lock_roe == pytest.approx(0.15)
    e.step({"BTCUSDT": bar(4, 100.5, 100.51, 100.0, 100.1)})
    t = e.trades[-1]
    assert t.exit_reason == "LOCK" and t.lock_roe == pytest.approx(0.15)
    assert t.exit_price == pytest.approx(lock_px * (1 - SLIP))
    assert t.roe == pytest.approx(0.15, abs=0.015)


def test_lock_not_armed_by_entry_bar_with_ref_price():
    e, _ = engine()
    e.submit(sig(0, ref_price=100.0))
    e.step({"BTCUSDT": bar(1, 99.8, 101.0, 99.6, 100.0)})  # high before the fill
    assert e.position.lock_roe is None


def test_no_drawdown_halt_then_bust():
    e, n = engine()
    i = 0
    while not e.bust and i < 400:
        e.submit(sig(i))
        e.step({"BTCUSDT": bar(i + 1, 100, 100.05, 99.95, 100)})
        e.step({"BTCUSDT": bar(i + 2, 100, 100.05, 99.0, 99.2)})  # stop hit
        i += 2
    assert e.bust and e.halted and e.wallet < 10.0
    assert e.max_drawdown > 0.5          # went far past the old 50% halt
    assert not any("ENGINE HALTED" in m for _, m in n.messages)
    e.submit(sig(i))
    e.step({"BTCUSDT": bar(i + 1, 100, 100.05, 99.95, 100)})
    assert e.position is None and e.outcomes[-1].status == "REJECTED"


# ---------------------------------------------------------------------------------------------
# parity with research/paper_rules/rules_bt.simulate
# ---------------------------------------------------------------------------------------------
class _L:
    @staticmethod
    def tf_minutes(tf):
        return 15


def _synthetic(n, seed):
    rng = np.random.default_rng(seed)
    r = rng.standard_t(4, n) * 0.004
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[100.0, c[:-1]] * (1 + rng.normal(0, 0.0003, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    tr = np.maximum(h - lo, np.maximum(abs(h - np.r_[c[0], c[:-1]]), abs(lo - np.r_[c[0], c[:-1]])))
    atr = np.convolve(tr, np.ones(14) / 14)[:n]
    ts = (np.arange(n, dtype=np.int64) * 15 * MIN) * 1_000_000
    return dict(ts=ts, o=o, h=h, l=lo, c=c, atr=atr)


def test_engine_matches_research_simulator(monkeypatch):
    import rules_bt as R
    monkeypatch.setattr(R, "FUNDING_8H", 0.0)
    n = 1500
    coins = R.COINS
    syms = {c: c + "T" for c in coins}
    bars = {c: _synthetic(n, 10 + k) for k, c in enumerate(coins)}
    rng = np.random.default_rng(3)
    sigs = {c: np.where(rng.random(n) < 0.02, np.where(rng.random(n) < 0.5, 1, -1), 0).astype(np.int8)
            for c in coins}
    bounds = {c: (20, n) for c in coins}
    ref = R.simulate(bars, sigs, bounds, 2.0, "15m", _L, keep_trades=True)["trade_table"]
    assert len(ref) > 20

    settings = v3_settings(symbols=tuple(syms.values()), symbol_priority=tuple(syms.values()),
                           initial_equity=R.INITIAL)
    e, _ = engine(settings)
    for i in range(n):
        step = {}
        for c in coins:
            b = bars[c]
            step[syms[c]] = Bar(syms[c], i * 15 * MIN, (i + 1) * 15 * MIN - 1,
                                b["o"][i], b["h"][i], b["l"][i], b["c"][i])
        e.step(step)
        if i < 20 or i >= n - 1:
            continue
        for c in coins:
            s = int(sigs[c][i])
            if s:
                a = bars[c]["atr"][i]
                e.submit(Signal(ts=(i + 1) * 15 * MIN - 1, symbol=syms[c], timeframe="15m",
                                strategy_id="x", side=s, stop_price=0.0, tier="best", atr=a,
                                meta={"stop_dist": 2.0 * a}))
    got = e.trades
    m = len(ref) - 1            # the simulator closes the last one at the window end
    assert len(got) >= m
    for k in range(m):
        r, t = ref.iloc[k], got[k]
        assert syms[coins[int(r["coin"])]] == t.symbol
        assert int(r["i"]) + 1 == t.entry_time // (15 * MIN)
        assert int(r["exit_j"]) == t.exit_time // (15 * MIN)
        assert int(r["lev"]) == t.leverage
        assert r["R"] == pytest.approx(t.roe, abs=1e-9)


def test_v3_start_equity_and_bracket_fallback():
    """Accounts start with $5,000. A 40% x 50x position is then $100k notional, over the example
    50x bracket ($50k), so sizing steps down the owners' tiers (40x also too big) to 30% x 30x."""
    from paperbot.sizing import size_position
    s5 = v3_settings()
    assert s5.initial_equity == 5000.0
    d = size_position(s5, s5.initial_equity, +1, 100.0, 99.5, "best", Brackets.example())
    assert d.ok and (d.tier, d.leverage) == ("good", 30)
    d1 = size_position(S, S.initial_equity, +1, 100.0, 99.5, "best", Brackets.example())
    assert d1.ok and (d1.tier, d1.leverage) == ("best", 50)
