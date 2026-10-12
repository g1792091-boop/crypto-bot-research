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



# ====================================================================================================== F13: the stepped lock added
# PREREG_EXITFLEX 5.2 (family F13): the pick's hard stop and the rule bot's stepped lock, with the pick's own fixed take-profit kept
# (mode a) or none (mode b). The 84 rules above are untouched; the lock exits are built from a pick's exit name.
import hashlib  # noqa: E402
import json  # noqa: E402

from paperbot.engine import engine_state, restore_engine  # noqa: E402

# sha256 of the 84 rules (EXITS, TP_RULES, STOPS, LIVE_EXIT, TP_KO, every exit_ko and every spec) as computed on the commit before F13 was added:
# "existing exit names and behaviour stay byte-identical"
EXITS_84_SHA256 = "72e99305821e2b43f6cd1908ae40ff68a236360d7c9b6af1d7452a681a8a7283"


def test_the_84_rules_are_byte_identical_after_the_f13_addition():
    body = json.dumps({"exits": [list(e) for e in X.EXITS], "tp_rules": [list(r) for r in X.TP_RULES],
                       "ko": [X.exit_ko(e[0]) for e in X.EXITS], "spec": [X.spec(e[0]) for e in X.EXITS],
                       "live": X.LIVE_EXIT, "stops": list(X.STOPS), "tp_ko": X.TP_KO}, sort_keys=True)
    assert hashlib.sha256(body.encode()).hexdigest() == EXITS_84_SHA256
    assert len(X.EXITS) == 84 == len(X.BY_NAME) == len(K.EXITS) and X.EXITS == K.EXITS


def test_lock_exit_builds_the_lock_plus_rule_from_a_picks_exit_name():
    lock = (True, 0.10, 0.05, 0.02)
    assert X.LOCK == (0.10, 0.05, 0.02) == tuple(K.TP_RULES[0][4:7]) and K.TP_RULES[0][0] == "ladder"
    got = {n: X.lock_exit(n, "a") for n in ("tp3R|4", "roe50|4", "tp2R|2", "tp1R|1", "tp1.5R|2.5", "roe10|3", "roe30|2", "roe20|1.5")}
    assert got == {"tp3R|4": "lock+tp3R|4", "roe50|4": "lock+roe50|4", "tp2R|2": "ladder_tp2R|2", "tp1R|1": "lock+tp1R|1",
                   "tp1.5R|2.5": "lock+tp1.5R|2.5", "roe10|3": "lock+roe10|3", "roe30|2": "lock+roe30|2", "roe20|1.5": "lock+roe20|1.5"}
    assert X.spec("lock+tp3R|4") == {"stop_atr": 4.0, "tp_kind": X.TP_R, "tp_val": 3.0, "ladder": True, "first_lock": 0.10, "step": 0.05, "gap": 0.02}
    assert X.spec("lock+roe50|4") == {"stop_atr": 4.0, "tp_kind": X.TP_ROE, "tp_val": 0.5, "ladder": True, "first_lock": 0.10, "step": 0.05,
                                      "gap": 0.02}
    for n, name in got.items():                                  # the pick's stop and take-profit stay; the lock is the engine's
        p, q = X.spec(n), X.spec(name)
        assert (q["stop_atr"], q["tp_kind"], q["tp_val"]) == (p["stop_atr"], p["tp_kind"], p["tp_val"])
        assert (q["ladder"], q["first_lock"], q["step"], q["gap"]) == lock
        assert X.known(name) and X.exit_ko(name)
    assert X.spec("ladder_tp2R|2") == X.spec("lock+tp2R|2")      # lock + 2R is one of the 84 already; the alias reads the same
    # mode b: the lock alone, the rule bot's exit, with the pick's stop
    for n in got:
        k = n.split("|")[1]
        assert X.lock_exit(n, "b") == f"ladder|{k}" and X.spec(f"ladder|{k}")["stop_atr"] == float(k) and not X.spec(f"ladder|{k}")["tp_kind"]
    # a pick that has the lock already keeps it; the 5% and 20% locks are replaced by the 10% one
    for n in ("ladder|2", "ladder_tp2R|2", "swing3|1", "swing10|4", "lock+tp3R|4"):
        assert X.lock_exit(n, "a") == n
    assert X.lock_exit("ladder5|3", "a") == "ladder|3" == X.lock_exit("ladder20|3", "a")
    for bad in ("tp3R|5", "tp9R|2", "ladder|2|3", "lock+ladder|2", "lock+tp3R|4.0", "lock+tp3R|x"):
        assert not X.known(bad)
        with pytest.raises((KeyError, ValueError)):
            X.spec(bad)
    with pytest.raises(ValueError):
        X.lock_exit("tp3R|4", "c")
    with pytest.raises(KeyError):
        X.lock_exit("lock+tp9R|2", "a")


F13_PICK_EXITS = ("tp3R|4", "roe50|4", "tp2R|2", "tp1.5R|2.5", "roe20|3")
F13_MINUTES = 12_000                  # a shorter path than the 84-rule test above keeps this test to a minute or two


def _kernel_alone_args(data, close, side, atr, best, br, args, equity=5000.0):
    """``TK.kernel_alone`` with explicit exit arguments (stop x ATR, tp kind, tp value, ladder, first lock, step, gap)."""
    S = K.settings_vector()
    pnl, ex, rs, lv = K.outcomes(S, K.bracket_arrays(br), data["ts"], data["o"], data["h"], data["l"], data["mo"], data["mh"], data["ml"],
                                 data["fund"], np.array([close], np.int64), np.array([atr]), np.array([best]), np.array([best]), equity,
                                 TK.SPEC["qty_step"], TK.SPEC["min_notional"], *args, np.array([np.nan]), np.array([np.nan]))
    k = 0 if side > 0 else 1
    return pnl[0, k], int(ex[0, k]), int(rs[0, k]), int(lv[0, k])


def _f13_args(pick_exit, mode):
    """The kernel's exit arguments of F13 on a pick whose own exit is ``pick_exit`` (kernel_x.exit_of_pick written out: the pick's stop,
    its take-profit in mode a and none in mode b, the lock of the engine)."""
    stop_atr, kind, val = K.exit_args(K.EXITS.index(next(e for e in K.EXITS if e[0] == pick_exit)))[:3]
    return (stop_atr, kind, val, True, 0.10, 0.05, 0.02) if mode == "a" else (stop_atr, K.TP_NONE, 0.0, True, 0.10, 0.05, 0.02)


def _random_signal(data, rng, bars=600):
    close = int(TK.T0 + rng.integers(5, bars) * 15 * TK.MIN)
    side = int(rng.choice([1, -1]))
    atr = float(data["c"][(close - TK.T0) // TK.MIN] * rng.uniform(0.0008, 0.01))
    return close, side, atr, bool(rng.random() < 0.5)


@pytest.mark.parametrize("mode", ["a", "b"])
@pytest.mark.parametrize("pick_exit", F13_PICK_EXITS)
def test_f13_engine_gives_the_kernels_trade(pick_exit, mode):
    """The league's engine for the lock exit built from the pick's exit name equals the kernel with the lock arguments, trade for
    trade (exit minute, reason, leverage, P&L), on random signals of a path with jumps and funding."""
    name = X.lock_exit(pick_exit, mode)
    args = _f13_args(pick_exit, mode)
    assert (X.spec(name)["stop_atr"], X.spec(name)["tp_kind"], X.spec(name)["tp_val"], X.spec(name)["ladder"]) == args[:4]
    data = TK.synth_1m(F13_MINUTES, seed=17)
    rng = np.random.default_rng(31 + len(pick_exit) + (mode == "b"))
    n = n_lock = n_tp = 0
    for _ in range(45):
        close, side, atr, best = _random_signal(data, rng)
        d, x, r, lev = _kernel_alone_args(data, close, side, atr, best, TK.WIDE, args)
        e = _replay(data, [("BTCUSDT", close, side, atr, best, float("nan"))], {"BTCUSDT": TK.WIDE}, name)
        if r in (K.R_REJECT, K.R_OPEN):
            assert not e.trades
            continue
        t = e.trades[0]
        assert (t.exit_time // TK.MIN * TK.MIN, TK.REASON[t.exit_reason], t.leverage) == (int(data["ts"][x]), r, lev), (name, close, side)
        assert abs(t.pnl / 5000.0 - d) < 1e-12, (name, t.pnl, d * 5000)
        n += 1
        n_lock += r == K.R_LOCK
        n_tp += r == K.R_TP
    assert n >= 25 and n_lock >= 3, (name, n, n_lock)
    if mode == "b":
        assert n_tp == 0                                                  # no fixed take-profit in mode b


def test_f13_lock_plus_a_roe_take_profit_reaches_the_take_profit_and_the_lock():
    """The lock with a take-profit at net ROE (the one combination that none of the 84 rules has): both exits occur and equal the kernel."""
    name, args = X.lock_exit("roe20|3", "a"), _f13_args("roe20|3", "a")
    data = TK.synth_1m(F13_MINUTES, seed=19)
    rng = np.random.default_rng(5)
    seen = set()
    for _ in range(60):
        close, side, atr, best = _random_signal(data, rng)
        d, x, r, lev = _kernel_alone_args(data, close, side, atr, best, TK.WIDE, args)
        e = _replay(data, [("BTCUSDT", close, side, atr, best, float("nan"))], {"BTCUSDT": TK.WIDE}, name)
        if r in (K.R_REJECT, K.R_OPEN):
            continue
        t = e.trades[0]
        assert (t.exit_time // TK.MIN * TK.MIN, TK.REASON[t.exit_reason], t.leverage) == (int(data["ts"][x]), r, lev)
        assert abs(t.pnl / 5000.0 - d) < 1e-12
        seen.add(r)
    assert {K.R_TP, K.R_LOCK} <= seen, seen


def test_f13_engine_state_restores_in_the_middle_of_a_locked_position():
    """A restart in the middle of a position whose lock has been raised (the engine state is saved and restored through json, as the
    league's database keeps it: the stop, ``lock_roe``, the funding paid) continues exactly: the trade equals the uninterrupted one."""
    data = TK.synth_1m(F13_MINUTES, seed=17)
    rng = np.random.default_rng(77)
    locked = checked = 0
    for pick_exit, mode in (("tp3R|4", "a"), ("roe50|4", "a"), ("tp2R|2", "b")):
        name = X.lock_exit(pick_exit, mode)
        k_stop = X.spec(name)["stop_atr"]
        for _ in range(40):
            close, side, atr, _best = _random_signal(data, rng)
            sig = [("BTCUSDT", close, side, atr, False, float("nan"))]
            ref = _replay(data, sig, {"BTCUSDT": TK.WIDE}, name)
            if not ref.trades or ref.trades[0].lock_roe is None:
                continue
            ends_at = ref.trades[0].exit_time
            e = X.make_engine(name, {"BTCUSDT": TK.WIDE}, {"BTCUSDT": TK.SPEC})
            q, restored, stopped_at = 0, False, None
            for j, t in enumerate(data["ts"]):
                t = int(t)
                if not restored and e.position is not None and e.position.lock_roe is not None and t < ends_at - 3 * TK.MIN:
                    snap = json.loads(json.dumps(engine_state(e)))      # the restart: a locked position is open and its state is saved
                    e = X.make_engine(name, {"BTCUSDT": TK.WIDE}, {"BTCUSDT": TK.SPEC})
                    restore_engine(e, snap)
                    restored, stopped_at = True, j
                    locked += 1
                bars = {"BTCUSDT": TK.bars_at(data, "BTCUSDT", j)}
                fund = {"BTCUSDT": float(data["fund"][j])} if data["fund"][j] != 0 else None
                for s_ in e.pending:
                    if "ref_price" not in s_.meta:
                        s_.meta["ref_price"] = float(bars["BTCUSDT"].open)
                e.step(bars, fund)
                while q < len(sig) and sig[q][1] <= t + TK.MIN:
                    sym, c_, sd, at, bs, lv = sig[q]
                    e.submit(TK.signal(sym, c_, sd, at, bs, k_stop, lv))
                    q += 1
                if e.trades:
                    break
            if restored:
                checked += 1
                a, b = ref.trades[0], e.trades[0]
                assert (a.exit_time, a.exit_reason, a.exit_price, a.pnl, a.lock_roe, a.stop_price) == \
                       (b.exit_time, b.exit_reason, b.exit_price, b.pnl, b.lock_roe, b.stop_price), (name, close, side, stopped_at)
    assert locked == checked and checked >= 5, (locked, checked)
