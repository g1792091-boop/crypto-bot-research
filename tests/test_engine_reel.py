"""The reel's own exits (paperbot/reel_engine.py, owners' D2 (ii)).

1. ``ReelEngine`` stepped on 1m bars built from 5m bars reproduces the PREREG's ``lib_reel5m.exit_trade`` trade by
   trade (stop first, the target at the previous 5m bar's upper band updated every 5m bar, gaps fill at the open, the
   96-bar time exit, the skip rules), except for the documented differences (reel_engine module docstring), each of
   which is classified here and also shown on a hand-built example.
2. ``simulate_exit`` equals ``ReelEngine`` exactly (the same exits on the 5m bars, a 1m path low first).
3. A restart in the middle of a trade (engine_state / restore_engine through JSON, and the AccountBook save / load)
   continues exactly: the target, the closes buffer and the time exit survive.
4. No ladder, the levrule "normal" tier, contract violations rejected; the shared engine files are unchanged for
   every other account (PaperEngine is not touched: tests/test_extras_parity.py and the engine tests stay green).
Synthetic data only.
"""

import importlib.util
import json
import math
import os
import sys
from dataclasses import asdict

import numpy as np
import pytest

from paperbot import Bar, Brackets, Signal
from paperbot import reel_engine as RE
from paperbot.config import v4_settings
from paperbot.engine import PaperEngine, engine_state, restore_engine
from paperbot.notify import ListNotifier
from paperbot.reel_engine import (FIVE_MS, SKIP_STOP, SKIP_TARGET, STATE_KEY, ReelEngine, simulate_exit,
                                  simulate_exit_1m, upper_band, upper_bands)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RD = os.path.join(ROOT, "research", "reel5m")
if RD not in sys.path:
    sys.path.insert(0, RD)
if "lib_reel5m" in sys.modules:
    R = sys.modules["lib_reel5m"]
else:
    _spec = importlib.util.spec_from_file_location("lib_reel5m", os.path.join(RD, "lib_reel5m.py"))
    R = importlib.util.module_from_spec(_spec)
    sys.modules["lib_reel5m"] = R
    _spec.loader.exec_module(R)

COST = R.env()["L"]._cost("5m", R.MAX_HOLD)
S = v4_settings()                       # the live rule set: $5,000, quality_v1, tp_mode "ladder" for the house
SLIP = S.slippage_frac
MIN = 60_000
T0 = (1_790_000_000_000 // FIVE_MS) * FIVE_MS
SYM = "BTCUSDT"
BRACKETS = {s: Brackets.example() for s in S.symbols}

# 1m paths through a 5m bar (open, high, low, close) of the five minutes
LOW_FIRST = "low_first"                 # open -> low -> high -> close: the PREREG's "stop first" order
HIGH_FIRST = "high_first"               # open -> high -> low -> close


def minutes(j, o, h, l, c, path=LOW_FIRST, sym=SYM):
    O, H, L, C = float(o[j]), float(h[j]), float(l[j]), float(c[j])
    if path == LOW_FIRST:
        q = [(O, O, L, L), (L, H, L, H), (H, H, C, C), (C, C, C, C), (C, C, C, C)]
    else:
        q = [(O, H, O, H), (H, H, L, L), (L, C, L, C), (C, C, C, C), (C, C, C, C)]
    t = T0 + j * FIVE_MS
    return [Bar(sym, t + k * MIN, t + (k + 1) * MIN - 1, a, b, d, e) for k, (a, b, d, e) in enumerate(q)]


def reel_signal(s, stop, tp, closes, ref, atr=None, strat="REEL_H1", sym=SYM, **meta):
    return Signal(ts=T0 + (s + 1) * FIVE_MS - 1, symbol=sym, timeframe="5m", strategy_id=strat, side=1,
                  stop_price=float(stop), tier="best", tp_price=float(tp), atr=None if atr is None else float(atr),
                  meta={"ref_price": float(ref), "reel": {"stop": float(stop), "up_band": float(tp),
                                                          "closes": [float(x) for x in closes]}, **meta})


def engine(settings=S, cls=ReelEngine):
    n = ListNotifier()
    return cls(settings, BRACKETS, notifier=n, book="REEL_H1@5m"), n


def drive(e, o, h, l, c, j0, j1, path=LOW_FIRST, drop=()):
    """Step 1m bars of the 5m bars j0..j1-1 until the position (entered at the first step) is closed."""
    first = True
    for j in range(j0, min(j1, len(c))):
        for k, b in enumerate(minutes(j, o, h, l, c, path)):
            if (j, k) in drop:
                continue
            e.step({SYM: b})
            if e.position is None and (first or e.trades):
                return
            first = False


def engine_trade(arr, s, stop, tp, path=LOW_FIRST, atr=None, closes=None, drop=()):
    o, h, l, c = arr
    e, _n = engine()
    closes = c[s - 18:s + 1] if closes is None else closes
    e.submit(reel_signal(s, stop, tp, closes, o[s + 1], atr=atr))
    drive(e, o, h, l, c, s + 1, s + 1 + RE.MAX_HOLD_5M + 1, path, drop)
    return e


def exit_idx_of(t):
    return (t.exit_time - T0) // FIVE_MS


def engine_px(raw, reason):
    """The engine's exit price of a raw simulate_exit level: slippage off stop and time exits, none off the target."""
    return raw if reason == "TP" else raw * (1 - SLIP)


# ------------------------------------------------------------------ synthetic world (the PREREG's own generator)
@pytest.fixture(scope="module")
def world():
    df = R.synth(16000, "5m", 11, vol=0.0015)
    ind = R.indicators(df)
    P = R.Prep(ind, "SMA200", "CLOSE", "LONG")
    trades, sigs, skips = R.simulate(P, COST, 300, len(df) - R.MAX_HOLD - 2)
    arr = (P.o, P.h, P.l, P.c)
    # the 5m coin flips' entries (D4): random signal bars, stop = lowest low of the last 12 bars - 0.05 x ATR14
    rng = np.random.default_rng(5)
    flips = []
    for s in sorted(rng.choice(np.arange(300, len(df) - R.MAX_HOLD - 2), 400, replace=False).tolist()):
        flips.append((s, float(P.l[s - 11:s + 1].min() - RE.STOP_BUF_ATR * P.atr[s])))
    reel = [(t["signal_idx"], float(t["stop_px"])) for t in trades]
    reel_sk = [(g["signal_idx"], float(g["stop_px"])) for g in sigs if g["signal_idx"] not in {t["signal_idx"] for t in trades}]
    return dict(df=df, ind=ind, P=P, arr=arr, trades=trades, sigs=sigs, skips=skips, flips=flips, reel=reel,
                reel_skipped=reel_sk)


def prereg_exit(w, s, stop):
    """lib_reel5m's decision for an entry at the open of s + 1 (simulate's skip rules, then exit_trade)."""
    P = w["P"]
    e = s + 1
    entry = P.o[e] * (1.0 + SLIP)
    if not entry - stop > 0:
        return None, None, "SKIP_STOP"
    if not P.up_prev[e] - entry > 0:
        return None, None, "SKIP_TARGET"
    tr = R.exit_trade(1, e, entry, stop, P.up_prev, P.o, P.h, P.l, P.c, COST)
    return tr["exit_idx"], tr["exit_px"], tr["reason"]


def classify(w, s, stop, want, got_raw):
    """Which documented difference explains a mismatch between the PREREG (``want``: exit_trade, engine prices) and
    simulate_exit (``got_raw``); None when none does."""
    P = w["P"]
    o, h, l = P.o, P.h, P.l
    e = s + 1
    wi, wp, wr = want
    gi, gp, gr = got_raw
    if wr == "SL" and gr == "TP" and gi == wi and gi > e and o[gi] > P.up_prev[gi] and l[gi] <= stop:
        return "1b gap above the target, stop in the same 5m bar"
    if wr == "SL" and gr == "SL" and wi == gi == e and o[e] < stop and wp == o[e] * (1 - SLIP) and gp == stop:
        return "1c stop on the entry bar fills at the stop"
    if wr == "TP" and h[wi] == P.up_prev[wi] and (gi is None or gi > wi or gr != "TP"):
        return "2 high equal to the target"
    return None


# ------------------------------------------------------------------ constants and band
def test_constants_equal_the_prereg_library():
    assert (RE.STOP_BUF_ATR, RE.MAX_HOLD_5M, RE.BB_LEN, RE.BB_K) == (R.STOP_BUF_ATR, R.MAX_HOLD, R.BB_LEN, R.BB_K)
    assert COST.max_hold == RE.MAX_HOLD_5M and COST.slip_side == SLIP     # the engine's slippage is the PREREG's
    assert RE.FIVE_MS == 300_000 and RE.SKIP_STOP.startswith("reel: ") and RE.SKIP_TARGET.startswith("reel: ")


def test_upper_band_is_the_library_band(world):
    up = upper_bands(world["P"].c)
    ref = world["ind"]["upper"]
    assert np.isnan(up[:19]).all() and np.isnan(ref[:19]).all()
    rel = np.abs(up[19:] / ref[19:] - 1.0)
    assert rel.max() < 1e-10                              # pandas' online rolling sums vs exact sums: rounding
    with pytest.raises(ValueError):
        upper_band([1.0] * 19)


# ------------------------------------------------------------------ 1. engine vs the PREREG
def _parity(w, cases, label):
    arr = w["arr"]
    P = w["P"]
    n_trades = n_diff = 0
    kinds = {}
    for s, stop in cases:
        want = prereg_exit(w, s, stop)
        sx = simulate_exit({"open": P.o, "high": P.h, "low": P.l, "close": P.c, "upper": w["ind"]["upper"]},
                           s + 1, P.o[s + 1] * (1 + SLIP), stop)
        e = engine_trade(arr, s, stop, w["ind"]["upper"][s], atr=P.atr[s])
        # the engine on the low-first 1m path == simulate_exit (prices: the later targets are the engine's exact-sum
        # band, the PREREG's are pandas': rounding only)
        if sx[2] in ("SKIP_STOP", "SKIP_TARGET"):
            assert not e.trades and e.position is None
            out = e.outcomes[-1] if e.outcomes else None
            assert out is not None and out.status == "SKIPPED"
            assert out.reason == (SKIP_STOP if sx[2] == "SKIP_STOP" else SKIP_TARGET)
        else:
            if not e.trades:          # the house sizing refused the stop (too far for 20x as well): no exit to compare
                assert e.outcomes and e.outcomes[-1].reason == "sizing", (label, s)
                continue
            t = e.trades[-1]
            assert len(e.trades) == 1 and t.exit_reason == sx[2] and exit_idx_of(t) == sx[0], (label, s, t, sx)
            assert t.exit_price == pytest.approx(engine_px(sx[1], sx[2]), rel=1e-10, abs=0), (label, s)
            assert t.entry_price == P.o[s + 1] * (1 + SLIP) and t.stop_price == stop and t.lock_roe is None
            n_trades += 1
        # simulate_exit vs exit_trade: identical, or one of the documented differences
        got = (sx[0], None if sx[1] is None else engine_px(sx[1], sx[2]), sx[2])
        if got != want:
            why = classify(w, s, stop, want, sx)
            assert why is not None, (label, s, stop, want, got)
            kinds[why] = kinds.get(why, 0) + 1
            n_diff += 1
    return n_trades, n_diff, kinds


def test_engine_reproduces_the_prereg_on_the_reel_signals(world):
    n, n_diff, kinds = _parity(world, world["reel"], "reel")
    assert n >= 40, n
    assert n_diff <= max(1, n // 50), kinds              # the documented differences are rare
    n2, _d, _k = _parity(world, world["reel_skipped"], "reel skipped")
    assert world["skips"]["stop"] + world["skips"]["target"] == len(world["reel_skipped"]) - world["skips"]["atr"]


def test_engine_reproduces_the_prereg_on_coin_flip_entries(world):
    n, n_diff, kinds = _parity(world, world["flips"], "flip")
    assert n >= 300, n
    assert n_diff <= max(2, n // 50), kinds
    reasons = {}
    for s, stop in world["flips"]:
        r = prereg_exit(world, s, stop)[2]
        reasons[r] = reasons.get(r, 0) + 1
    assert reasons.get("SL", 0) > 50 and reasons.get("TP", 0) > 50, reasons     # TIME: the hand-built test below


# ------------------------------------------------------------------ 2. simulate_exit == ReelEngine, exactly
def _gappy(seed, n=900):
    """A 5m series with frequent gaps between bars (opens far from the previous close), to reach every branch."""
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.0015, n) * (rng.random(n) < 0.3))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.002, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.002, n))
    return o, h, l, c


def test_simulate_exit_equals_the_engine_exactly():
    seen = {}
    for seed in (1, 2, 3):
        _exact_one(seed, seen)
    assert {"SL", "TP", "SL gap", "TP gap", "SKIP_TARGET"} <= set(seen), seen


def _exact_one(seed, seen):
    o, h, l, c = _gappy(seed)
    up = upper_bands(c)
    rng = np.random.default_rng(seed + 100)
    for s in rng.integers(25, len(c) - 120, 150):
        s = int(s)
        stop = float(l[s - 11:s + 1].min() - rng.uniform(0, 0.004) * c[s])
        sx = simulate_exit({"open": o, "high": h, "low": l, "close": c}, s + 1, o[s + 1] * (1 + SLIP), stop)
        assert sx == simulate_exit({"open": o, "high": h, "low": l, "close": c, "upper": up}, s + 1,
                                   o[s + 1] * (1 + SLIP), stop)
        e = engine_trade((o, h, l, c), s, stop, up[s])
        if sx[2].startswith("SKIP"):
            assert not e.trades and e.outcomes[-1].status == "SKIPPED"
            seen[sx[2]] = seen.get(sx[2], 0) + 1
            continue
        if not e.trades:
            assert e.outcomes[-1].reason == "sizing"
            continue
        t = e.trades[-1]
        assert (exit_idx_of(t), t.exit_reason, t.exit_price) == (sx[0], sx[2], engine_px(sx[1], sx[2])), (seed, s)
        gap = sx[0] > s + 1 and sx[1] == o[sx[0]]
        key = sx[2] + (" gap" if gap else "")
        seen[key] = seen.get(key, 0) + 1


def test_simulate_exit_input_checks():
    o, h, l, c = _gappy(4, 60)
    bars = {"open": o, "high": h, "low": l, "close": c}
    with pytest.raises(ValueError):
        simulate_exit(bars, 30, o[30], o[30] * 0.99, side=-1)
    with pytest.raises(ValueError):
        simulate_exit(bars, 0, o[0], o[0] * 0.99)
    with pytest.raises(ValueError):
        simulate_exit({"open": o, "high": h, "low": l}, 30, o[30], o[30] * 0.99)
    assert simulate_exit(bars, 10, o[10], o[10] * 0.99) == (None, None, "SKIP_TARGET")     # no band yet
    i, px, why = simulate_exit(bars, 50, o[50] * (1 + SLIP), o[50] * 0.5)                   # far stop: no exit in 10 bars
    assert why in ("EOD", "TP") and (why != "EOD" or (i, px) == (59, c[59]))


def _minutes_world(seed, k5=700):
    """Real-looking 1m bars (not built from 5m): gaps between minutes, missing minutes, mark-price wicks."""
    rng = np.random.default_rng(seed)
    n = k5 * 5
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.0009, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.0012, n) * (rng.random(n) < 0.05))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.0008, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.0008, n))
    ml = l * (1 - 0.03 * (rng.random(n) < 0.004))                      # rare mark-price wick of 3%
    mo = o.copy()
    t = T0 + np.arange(n, dtype=np.int64) * MIN
    gone = rng.random(n) < 0.03                                         # missing minutes
    for a in (o, h, l, c, ml, mo):
        a[gone] = np.nan
    close5 = np.full(k5, np.nan)                                        # 5m close = last present close of the bucket
    for j in range(k5):
        seg = c[j * 5:(j + 1) * 5]
        ok = seg[np.isfinite(seg)]
        close5[j] = ok[-1] if len(ok) else np.nan
    return dict(open_time=t, open=o, high=h, low=l, close=c, mark_open=mo, mark_low=ml), close5


def test_simulate_exit_1m_equals_the_engine_on_real_minutes():
    seen = {}
    for seed in (7, 8, 9):
        m, close5 = _minutes_world(seed)
        rng = np.random.default_rng(seed + 50)
        for s in rng.integers(30, len(close5) - 110, 120):
            s = int(s)
            iB = (s + 1) * 5
            win = close5[s - 19:s + 1]
            if not np.isfinite(m["open"][iB]) or not np.isfinite(win).all():
                continue
            closes, tp = win[1:], upper_band(win)
            ref = m["open"][iB]
            stop = float(ref * (1 - rng.uniform(0.001, 0.02)))
            e, _ = engine()
            e.submit(reel_signal(s, stop, tp, closes, ref))
            for i in range(iB, len(m["open"])):
                if not np.isfinite(m["open"][i]):
                    continue
                t = int(m["open_time"][i])
                e.step({SYM: Bar(SYM, t, t + MIN - 1, m["open"][i], m["high"][i], m["low"][i], m["close"][i],
                                 mark_open=m["mark_open"][i], mark_low=m["mark_low"][i])})
                if e.position is None:
                    break
            if not e.trades:
                out = e.outcomes[0]
                if out.status == "SKIPPED":
                    assert simulate_exit_1m(m, iB, ref * (1 + SLIP), stop, tp, closes)[2] == \
                        ("SKIP_STOP" if out.reason == SKIP_STOP else "SKIP_TARGET")
                else:
                    assert out.reason == "sizing"
                continue
            tr = e.trades[0]
            got = simulate_exit_1m(m, iB, tr.entry_price, stop, tp, closes, liq=tr.liq_price)
            assert ((tr.exit_time - T0) // MIN, tr.exit_reason) == (got[0], got[2]), (seed, s, tr, got)
            assert tr.exit_price == (got[1] if got[2] in ("TP", "LIQ") else got[1] * (1 - SLIP)), (seed, s)
            seen[got[2]] = seen.get(got[2], 0) + 1
    assert {"SL", "TP", "LIQ"} <= set(seen) and sum(seen.values()) > 250, seen


# ------------------------------------------------------------------ hand-built rules and the documented differences
def flat_world(n=140, px=100.0):
    """Opens 100, closes 99.5 / 100.5 in turn (mean 100, sd 0.5: the band is 101), highs <= 100.55, lows >= 99.45;
    callers edit single bars."""
    o = np.full(n, px)
    c = px + 0.5 * np.array([(-1) ** k for k in range(n)], float)
    h = np.maximum(o, c) + 0.05
    l = np.minimum(o, c) - 0.05
    return o, h, l, c


def _hand(o, h, l, c, s, stop, path=LOW_FIRST, drop=()):
    up = upper_bands(c)
    e = engine_trade((o, h, l, c), s, stop, up[s], path=path, drop=drop)
    return e, up


def test_target_moves_with_each_closed_5m_bar_and_restarts_from_the_signal_closes():
    o, h, l, c = flat_world()
    s = 25
    c[s - 18:s + 1] = np.linspace(99, 101, 19)
    o[s + 1] = 100.0
    up = upper_bands(c)
    e, _n = engine()
    e.submit(reel_signal(s, 97.0, up[s], c[s - 18:s + 1], o[s + 1]))
    bars = minutes(s + 1, o, h, l, c)
    for b in bars[:4]:
        e.step({SYM: b})
    assert e.position.tp_price == up[s]                         # during bar s+1: UP[s]
    e.step({SYM: bars[4]})
    assert e.position.tp_price == up[s + 1] == upper_band(c[s - 18:s + 2])
    st = e.position.signal.meta[STATE_KEY]
    assert st["closes"] == [float(x) for x in c[s - 17:s + 2]] and st["last"] is None
    assert st["bucket"] == T0 + (s + 2) * FIVE_MS and st["end"] == T0 + (s + 1 + 96) * FIVE_MS
    assert STATE_KEY not in e.outcomes[0].signal.meta          # the logged signal is not touched


def test_time_exit_at_the_close_of_the_96th_bar():
    o, h, l, c = flat_world(200)
    s = 30
    e, up = _hand(o, h, l, c, s, 97.0)
    t = e.trades[-1]
    assert t.exit_reason == "TIME" and exit_idx_of(t) == s + 96 and t.exit_time == T0 + (s + 97) * FIVE_MS - 1
    assert t.exit_price == c[s + 96] * (1 - SLIP)
    assert simulate_exit({"open": o, "high": h, "low": l, "close": c}, s + 1, o[s + 1] * (1 + SLIP), 97.0) == \
        (s + 96, c[s + 96], "TIME")
    entry = o[s + 1] * (1 + SLIP)
    tr = R.exit_trade(1, s + 1, entry, 97.0, np.r_[np.nan, up[:-1]], o, h, l, c, COST)
    assert (tr["exit_idx"], tr["reason"], tr["exit_px"]) == (s + 96, "TIME", t.exit_price)


def test_skip_rules():
    o, h, l, c = flat_world()
    s = 30
    up = upper_bands(c)
    e, _ = engine()
    e.submit(reel_signal(s, o[s + 1] * (1 + SLIP), up[s], c[s - 18:s + 1], o[s + 1]))     # stop == fill
    e.step({SYM: minutes(s + 1, o, h, l, c)[0]})
    assert e.position is None and e.outcomes[-1].status == "SKIPPED" and e.outcomes[-1].reason == SKIP_STOP
    e, _ = engine()
    e.submit(reel_signal(s, 97.0, o[s + 1] * (1 + SLIP), c[s - 18:s + 1], o[s + 1]))       # fill == first target
    e.step({SYM: minutes(s + 1, o, h, l, c)[0]})
    assert e.position is None and e.outcomes[-1].status == "SKIPPED" and e.outcomes[-1].reason == SKIP_TARGET
    assert e.outcomes[-1].detail["fill"] == o[s + 1] * (1 + SLIP)


def test_same_5m_bar_stop_and_target_takes_the_stop_on_the_low_first_path():
    o, h, l, c = flat_world()
    s = 30
    j = s + 3
    h[j], l[j] = 110.0, 96.0                       # reaches the band (~100.x) and the stop 97 in one 5m bar
    e, up = _hand(o, h, l, c, s, 97.0)
    t = e.trades[-1]
    assert (t.exit_reason, exit_idx_of(t), t.exit_price) == ("SL", j, 97.0 * (1 - SLIP))
    entry = o[s + 1] * (1 + SLIP)
    tr = R.exit_trade(1, s + 1, entry, 97.0, np.r_[np.nan, up[:-1]], o, h, l, c, COST)
    assert (tr["exit_idx"], tr["reason"], tr["exit_px"]) == (j, "SL", t.exit_price)
    # difference 1a: live, the minute order decides; a path that reaches the high first is a TP
    e2, _ = _hand(o, h, l, c, s, 97.0, path=HIGH_FIRST)
    t2 = e2.trades[-1]
    assert (t2.exit_reason, exit_idx_of(t2), t2.exit_price) == ("TP", j, up[j - 1])


def test_difference_1b_gap_above_the_target_fills_at_the_open():
    o, h, l, c = flat_world()
    s = 30
    j = s + 4
    o[j], h[j], l[j] = 103.0, 103.5, 96.0          # opens above the band, then falls through the stop 97
    e, up = _hand(o, h, l, c, s, 97.0)
    t = e.trades[-1]
    assert (t.exit_reason, exit_idx_of(t), t.exit_price, t.exit_time) == ("TP", j, 103.0, T0 + j * FIVE_MS)
    entry = o[s + 1] * (1 + SLIP)
    tr = R.exit_trade(1, s + 1, entry, 97.0, np.r_[np.nan, up[:-1]], o, h, l, c, COST)
    assert (tr["exit_idx"], tr["reason"]) == (j, "SL")                                  # the PREREG: the stop first
    assert simulate_exit({"open": o, "high": h, "low": l, "close": c}, s + 1, entry, 97.0) == (j, 103.0, "TP")
    o[j], c[j] = 103.0, 102.5
    h[j], l[j] = 103.5, 102.0                       # without the stop in that bar both agree: TP at the open
    tr = R.exit_trade(1, s + 1, entry, 97.0, np.r_[np.nan, up[:-1]], o, h, l, c, COST)
    assert (tr["exit_idx"], tr["reason"], tr["exit_px"]) == (j, "TP", 103.0)


def test_difference_1c_stop_on_the_entry_bar_fills_at_the_stop():
    o, h, l, c = flat_world()
    s = 30
    stop = o[s + 1] * (1 + SLIP / 2)               # above the open, below the fill (open + 0.02%)
    l[s + 1] = 99.0
    e, up = _hand(o, h, l, c, s, stop)
    t = e.trades[-1]
    assert (t.exit_reason, exit_idx_of(t), t.exit_price) == ("SL", s + 1, stop * (1 - SLIP))
    entry = o[s + 1] * (1 + SLIP)
    tr = R.exit_trade(1, s + 1, entry, stop, np.r_[np.nan, up[:-1]], o, h, l, c, COST)
    assert (tr["reason"], tr["exit_px"]) == ("SL", o[s + 1] * (1 - SLIP))              # the PREREG: min(open, stop)


def test_difference_2_high_equal_to_the_target_is_not_a_fill():
    o, h, l, c = flat_world()
    s = 30
    up = upper_bands(c)
    j = s + 2
    h[j] = up[j - 1]                                # touches the band exactly
    e, _ = _hand(o, h, l, c, s, 97.0)
    assert e.trades[-1].exit_reason == "TIME"
    entry = o[s + 1] * (1 + SLIP)
    tr = R.exit_trade(1, s + 1, entry, 97.0, np.r_[np.nan, up[:-1]], o, h, l, c, COST)
    assert (tr["exit_idx"], tr["reason"], tr["exit_px"]) == (j, "TP", up[j - 1])
    h[j] = np.nextafter(up[j - 1], 200.0)           # one tick through: a fill at the target
    e, _ = _hand(o, h, l, c, s, 97.0)
    t = e.trades[-1]
    assert (t.exit_reason, exit_idx_of(t), t.exit_price) == ("TP", j, up[j - 1])


def test_no_ladder_even_with_the_house_ladder_settings():
    assert S.tp_mode == "ladder"
    o, h, l, c = flat_world(200)
    s = 30
    for j in range(s + 2, s + 40):                  # far above the entry, below the (wide) band: a ladder would lock
        c[j] = o[j] = 100.0
    c[s - 18:s + 1] = np.r_[np.full(9, 90.0), np.full(10, 110.0)]   # wide band for the first targets
    up = upper_bands(c)
    o[s + 1] = 100.0
    h[s + 1:s + 40] = 101.5                         # +1.5% x 30x = +45% ROE on the high, every bar
    e, _ = engine()
    e.submit(reel_signal(s, 98.5, up[s], c[s - 18:s + 1], o[s + 1]))
    drive(e, o, h, l, c, s + 1, s + 6)
    p = e.position
    assert p is not None and p.stop_price == 98.5 and p.lock_roe is None
    assert p.leverage == 30 and p.tier == "normal"   # levrule: the reel is always "normal" (30x / 30% first)
    assert e.summary()["locks"] == 0


def test_contract_violations_are_rejected():
    o, h, l, c = flat_world()
    s = 30
    up = upper_bands(c)
    good = reel_signal(s, 97.0, up[s], c[s - 18:s + 1], o[s + 1])
    bad = [
        Signal(**{**asdict(good), "side": -1}),
        Signal(**{**asdict(good), "tp_price": None}),
        Signal(**{**asdict(good), "tp_price": float("nan")}),
        Signal(**{**asdict(good), "meta": {**good.meta, "stop_dist": 1.0}}),
        Signal(**{**asdict(good), "meta": {**good.meta, "reel": {"closes": [100.0] * 18}}}),
        Signal(**{**asdict(good), "meta": {"ref_price": 100.0}}),
        Signal(**{**asdict(good), "ts": good.ts - FIVE_MS}),                      # its next 5m bar has passed
    ]
    for sig in bad:
        e, _ = engine()
        e.submit(sig)
        e.step({SYM: minutes(s + 1, o, h, l, c)[0]})
        assert e.position is None and e.outcomes[-1].status == "REJECTED", sig
        assert e.outcomes[-1].reason.startswith("reel: "), e.outcomes[-1].reason
    e, _ = engine()
    e.submit(good)
    e.step({SYM: minutes(s + 1, o, h, l, c)[0]})
    assert e.position is not None and e.outcomes[-1].status == "ENTERED"
    assert e.outcomes[-1].detail["stop"] == 97.0 and e.outcomes[-1].detail["target"] == up[s]


def test_signal_while_in_position_is_skipped():
    o, h, l, c = flat_world()
    s = 30
    up = upper_bands(c)
    e, _ = engine()
    e.submit(reel_signal(s, 97.0, up[s], c[s - 18:s + 1], o[s + 1]))
    for b in minutes(s + 1, o, h, l, c):
        e.step({SYM: b})
    e.submit(reel_signal(s + 1, 97.0, up[s + 1], c[s - 17:s + 2], o[s + 2], sym="ETHUSDT"))
    e.step({SYM: minutes(s + 2, o, h, l, c)[0], "ETHUSDT": minutes(s + 2, o, h, l, c, sym="ETHUSDT")[0]})
    assert e.outcomes[-1].status == "SKIPPED" and e.outcomes[-1].reason == "in position"


# ------------------------------------------------------------------ missing 1m bars (live gaps)
def test_missing_last_minute_closes_the_5m_bar_with_the_last_close_seen():
    o, h, l, c = flat_world()
    s = 30
    c[s + 1] = 100.7
    e, _ = engine()
    up = upper_bands(c)
    e.submit(reel_signal(s, 97.0, up[s], c[s - 18:s + 1], o[s + 1]))
    bars = minutes(s + 1, o, h, l, c)
    for b in bars[:2]:                                # minutes 0 and 1 (closes at the high); 2..4 are missing
        e.step({SYM: b})
    nxt = minutes(s + 2, o, h, l, c)[0]
    e.step({SYM: nxt})
    want = upper_band(list(c[s - 18:s + 1]) + [h[s + 1]])
    assert bars[1].close == h[s + 1] != c[s + 1] and e.position.tp_price == want
    st = e.position.signal.meta[STATE_KEY]
    assert st["bucket"] == T0 + (s + 2) * FIVE_MS and st["last"] == nxt.close
    assert st["closes"] == [float(x) for x in c[s - 17:s + 1]] + [h[s + 1]]


def test_missing_5m_bar_adds_no_close_and_time_exit_in_a_gap():
    o, h, l, c = flat_world(220)
    s = 30
    up = upper_bands(c)
    e, _ = engine()
    e.submit(reel_signal(s, 97.0, up[s], c[s - 18:s + 1], o[s + 1]))
    drop = {(s + 3, k) for k in range(5)} | {(s + 96, 4)}     # a whole 5m bar, and the time exit's own minute
    drive(e, o, h, l, c, s + 1, s + 100, drop=drop)
    t = e.trades[-1]
    assert t.exit_reason == "TIME" and t.exit_time == T0 + (s + 97) * FIVE_MS     # at the next minute's open
    assert t.exit_price == o[s + 97] * (1 - SLIP)


# ------------------------------------------------------------------ 3. restart in the middle of a trade
def _long_trade_case(world):
    for s, stop in world["flips"]:
        sx = simulate_exit({"open": world["P"].o, "high": world["P"].h, "low": world["P"].l, "close": world["P"].c},
                           s + 1, world["P"].o[s + 1] * (1 + SLIP), stop)
        if sx[0] is not None and sx[0] - (s + 1) >= 30:
            return s, stop, sx
    raise AssertionError("no long trade in the synthetic world")


@pytest.mark.parametrize("cut", [1, 4, 5, 6, 37, 140])
def test_engine_state_round_trip_mid_trade(world, cut):
    s, stop, sx = _long_trade_case(world)
    P = world["P"]
    arr = (P.o, P.h, P.l, P.c)
    up = upper_bands(P.c)
    ref = engine_trade(arr, s, stop, up[s])
    want = ref.trades[-1]
    assert (exit_idx_of(want), want.exit_reason) == (sx[0], sx[2])
    bars = [b for j in range(s + 1, s + 1 + 97) for b in minutes(j, *arr)]
    e, _ = engine()
    e.submit(reel_signal(s, stop, up[s], P.c[s - 18:s + 1], P.o[s + 1]))
    for b in bars[:cut]:
        e.step({SYM: b})
    assert e.position is not None
    st = json.loads(json.dumps(engine_state(e)))
    e2, _ = engine()
    restore_engine(e2, st)
    assert e2.position.tp_price == e.position.tp_price and e2.position.stop_price == stop
    assert e2.position.signal.meta[STATE_KEY] == e.position.signal.meta[STATE_KEY]
    for b in bars[cut:]:
        e2.step({SYM: b})
        if e2.position is None:
            break
    assert len(e2.trades) == 1 and asdict(e2.trades[0]) == asdict(want)
    assert engine_state(e2) == {**engine_state(ref), "n_trades": 1}


def test_account_book_restart_mid_trade_keeps_target_and_stop(tmp_path, world):
    from paperbot.accounts import AccountBook
    from paperbot.store3 import Store3
    s, stop, sx = _long_trade_case(world)
    P = world["P"]
    arr = (P.o, P.h, P.l, P.c)
    up = upper_bands(P.c)
    defs = [{"strategy": "REEL_H1", "timeframe": "5m", "kind": "reel",
             "data": {"group": "reel", "family": None, "exits": "reel"}},
            {"strategy": "RANDOM_1", "timeframe": "5m", "kind": "random",
             "data": {"group": "flip", "family": None, "exits": "reel"}}]
    bars = [b for j in range(s + 1, s + 1 + 97) for b in minutes(j, *arr)]
    sig = reel_signal(s, stop, up[s], P.c[s - 18:s + 1], P.o[s + 1])
    flip = reel_signal(s, stop, up[s], P.c[s - 18:s + 1], P.o[s + 1], strat="RANDOM_1")

    def run(db, cut=None):
        book = AccountBook(S, BRACKETS, Store3(str(db)), ListNotifier())
        book.open_accounts(defs, T0)
        book.submit("REEL_H1@5m", sig)
        book.submit("RANDOM_1@5m", flip)
        for k, b in enumerate(bars):
            if k == cut:
                book.save(book.last_ts)
                mid = (book.engines["REEL_H1@5m"].position.tp_price,
                       dict(book.engines["REEL_H1@5m"].position.signal.meta[STATE_KEY]))
                book.store.close()
                book = AccountBook(S, BRACKETS, Store3(str(db)), ListNotifier())
                assert book.load()
                p = book.engines["REEL_H1@5m"].position
                assert type(book.engines["REEL_H1@5m"]) is ReelEngine
                assert (p.tp_price, p.signal.meta[STATE_KEY], p.stop_price) == (mid[0], mid[1], stop)
            book.step(b.open_time, {SYM: b})
        return book

    a = run(tmp_path / "a.db")
    b = run(tmp_path / "b.db", cut=83)
    for aid in ("REEL_H1@5m", "RANDOM_1@5m"):
        ta, tb = a.engines[aid].trades, b.engines[aid].trades
        assert len(ta) == 1 and [asdict(x) for x in tb] == [asdict(x) for x in ta]
        assert (exit_idx_of(ta[0]), ta[0].exit_reason) == (sx[0], sx[2])
    rows = a.store.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    assert rows == 2


# ------------------------------------------------------------------ 4. other accounts are untouched
def test_paper_engine_is_unchanged_for_house_accounts():
    """ReelEngine changes nothing on PaperEngine: the class has none of its methods, and a house engine's saved
    state has exactly the v3 keys (the byte-identity of every house account is tests/test_extras_parity.py)."""
    for name in ("_try_enter", "_handle_exit", "_raise_lock"):
        assert getattr(PaperEngine, name) is not getattr(ReelEngine, name)
        assert getattr(PaperEngine, name).__module__ == "paperbot.engine"
    pe = PaperEngine(S, BRACKETS)
    assert set(engine_state(pe)) == {"wallet", "peak_equity", "max_drawdown", "halted", "halt_reason", "bust",
                                     "warned", "last_mark", "position", "pending", "n_trades"}
    assert not math.isnan(upper_band([100.0] * 20)) and upper_band([100.0] * 20) == 100.0


@pytest.mark.parametrize("drop_time_minute", [False, True])
def test_simulate_exit_1m_time_exit_and_missing_minutes(drop_time_minute):
    o, h, l, c = flat_world(220)
    s = 30
    up = upper_bands(c)
    drop = {(s + 3, k) for k in range(5)} | {(s + 50, 3), (s + 50, 4)}
    if drop_time_minute:
        drop |= {(s + 96, 4)}
    e, _ = engine()
    e.submit(reel_signal(s, 97.0, up[s], c[s - 18:s + 1], o[s + 1]))
    drive(e, o, h, l, c, s + 1, s + 100, drop=drop)
    t = e.trades[-1]
    rows = [(j, k, b) for j in range(s + 1, s + 100) for k, b in enumerate(minutes(j, o, h, l, c))]
    nan = float("nan")
    m = {"open_time": [b.open_time for _j, _k, b in rows]}
    for f in ("open", "high", "low", "close"):
        m[f] = [nan if (j, k) in drop else getattr(b, f) for j, k, b in rows]
    got = simulate_exit_1m(m, 0, t.entry_price, 97.0, up[s], c[s - 18:s + 1], liq=t.liq_price)
    assert got[2] == t.exit_reason == "TIME" and got[1] * (1 - SLIP) == t.exit_price
    assert m["open_time"][got[0]] == (t.exit_time if drop_time_minute else t.exit_time + 1 - MIN)


def test_an_error_in_the_reel_code_halts_this_account_only(monkeypatch):
    o, h, l, c = flat_world()
    s = 30
    up = upper_bands(c)
    e, note = engine()
    e.submit(reel_signal(s, 97.0, up[s], c[s - 18:s + 1], o[s + 1]))

    def boom(_closes):
        raise RuntimeError("band broke")
    monkeypatch.setattr(RE, "upper_band", boom)
    for j in (s + 1, s + 2):
        for b in minutes(j, o, h, l, c):
            e.step({SYM: b})                       # never raises out of the engine
    assert e.halted and "reel engine error RuntimeError: band broke" in e.halt_reason
    crit = [m for m in note.messages if m[0] == "CRITICAL"]
    assert len(crit) == 1 and "REEL_H1@5m" in crit[0][1]
    st = json.loads(json.dumps(engine_state(e)))   # still saves
    assert st["halted"] and st["position"] is not None
