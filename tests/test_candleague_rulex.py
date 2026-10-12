"""candleague/rulex.py, the rule accounts of the 후보 리그 (PREREG_EXITFLEX 4, 5, 11): every family on hand-built 1m paths
(both sides), the step order (funding, RULE exit, entries, the engine's own exits), a stop and restart in the middle of a
position, chart records without look-ahead, the offered signals, the league end to end on the shadow's synthetic bars,
and the existing accounts unchanged. Synthetic data only; nothing here reads a market file."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import sqlite3
import sys
import types
from dataclasses import asdict, replace

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from candleague import candidates as C  # noqa: E402
from candleague import exits as X  # noqa: E402
from candleague import league as L  # noqa: E402
from candleague import rulex as RX  # noqa: E402
from candleague import runner as RN  # noqa: E402
from paperbot import paramshadow as PS  # noqa: E402
from paperbot import sweepsig  # noqa: E402
from paperbot.engine import PaperEngine, engine_state, restore_engine  # noqa: E402
from paperbot.margin import BracketTier, Brackets  # noqa: E402
from paperbot.models import Bar, Signal  # noqa: E402

MIN = 60_000
HOUR = 3_600_000
T0 = 1_704_067_200_000                      # 2024-01-01 00:00 UTC
P0, R, ATR = 40_000.0, 400.0, 200.0        # price, stop distance (2 ATR), ATR of the signal bar
SYM = "BTCUSDT"
WIDE = Brackets([BracketTier(300_000, 125, 0.004, 0.0), BracketTier(800_000, 100, 0.005, 300.0),
                 BracketTier(3_000_000, 50, 0.01, 4_300.0), BracketTier(1e12, 20, 0.025, 49_300.0)])
BR, SP = {SYM: WIDE}, {SYM: {"qty_step": 0.001, "min_notional": 5.0}}
RT, SLIP, TAKER = 0.0014, 0.0002, 0.0005
J0 = 120                                    # the signal bar closes at minute 120; the position fills at that minute's open
C0 = T0 + J0 * MIN


def cfg_of(rule, **kw):
    """A rule config for the core pool only (the DeepSeek pool runs its current exit): PREREG 11.2's accounts."""
    return RX.normalize_config({"pools": {"core": rule}, **kw})


def rules_doc(rule, **kw):
    """The text of an enabled rules.json for the core pool."""
    return json.dumps({"enabled": True, "pools": {"core": rule}, **kw})


def at(j: int) -> int:
    return T0 + j * MIN


def chk(k: int) -> int:
    """The k-th hourly check close after the signal bar (minute 120 + 60 k)."""
    return C0 + k * HOUR


# ---------------------------------------------------------------- hand-built paths in the favourable direction
class Path:
    """1m bars as offsets from P0 in the position's favourable direction (positive = in profit): the same path serves a
    long (price = P0 + off) and a short (price = P0 - off)."""

    def __init__(self, n: int = 600):
        self.n = n
        self.o, self.c, self.b, self.w = [0.0] * n, [0.0] * n, [0.0] * n, [0.0] * n
        self.fund: dict = {}
        self.mark_open: dict = {}
        self.missing: set = set()

    def hold(self, j0: int, off: float, j1=None) -> "Path":
        for j in range(j0, self.n if j1 is None else j1):
            self.o[j] = self.c[j] = self.b[j] = self.w[j] = off
        return self

    def bar(self, j: int, o=None, c=None, b=None, w=None) -> "Path":
        self.o[j] = self.o[j] if o is None else o
        self.c[j] = self.c[j] if c is None else c
        self.b[j] = max(self.o[j], self.c[j]) if b is None else b
        self.w[j] = min(self.o[j], self.c[j]) if w is None else w
        return self

    def steps(self, side: int) -> list:
        f = lambda off: P0 + side * off  # noqa: E731
        out = []
        for j in range(self.n):
            if j in self.missing:
                continue
            t = at(j)
            hi, lo = (f(self.b[j]), f(self.w[j])) if side > 0 else (f(self.w[j]), f(self.b[j]))
            mo = f(self.mark_open.get(j, self.o[j]))
            bar = Bar(SYM, t, t + MIN - 1, f(self.o[j]), hi, lo, f(self.c[j]), mark_open=mo, mark_high=max(hi, mo),
                      mark_low=min(lo, mo), mark_close=f(self.c[j]))
            out.append((t, {SYM: bar}, {SYM: self.fund[j]} if j in self.fund else {}))
        return out


def acct(rule, exit_="tp3R|2", tf="1h", size=1.0, role=RX.ROLE_RULE, aid="t"):
    return {"id": aid, "kind": "core", "name": "S2_ST_ROC", "tf": tf, "combo": {}, "exit": exit_, "role": role,
            "size": size, "rule": RX.parse_rule(rule) if rule else dict(RX.NO_RULE), "source": {}}


def sig(close=C0, side=1, rx0=None, lev="normal", aid="t", **extra):
    return Signal(ts=close - 1, symbol=SYM, timeframe="1h", strategy_id="S2_ST_ROC", side=side, stop_price=0.0,
                  tier="best", atr=ATR, meta={"stop_dist": R, "lev_group": lev, "rx0": rx0 or {}, "account": aid, **extra})


def rec(t, side, off, k="p", **kw):
    d = {"k": k, "sym": SYM, "t": int(t), "c": P0 + side * off}
    d.update(kw)
    return d


def swing(side, w, off):
    return {("sl" if side > 0 else "sh"): {str(w): P0 + side * off}}


def run(a, path, side, sigs=((C0, None),), recs=(), engine=None):
    """The league's own replay (paramshadow.replay_day) of one rule account over the path."""
    e = engine or RX.make_engine(a, BR, SP)
    by: dict = {}
    for close, s in sigs:
        s = replace(s, meta=copy.deepcopy(s.meta)) if s else sig(close, side, aid=a["id"])   # the engine writes into meta
        by.setdefault(close, []).append((a["id"], s))
    for r in recs:
        by.setdefault(r["t"], []).append((a["id"], RX.RuleClose(r)))
    PS.replay_day({a["id"]: e}, set(), by, path.steps(side), BR)
    return e


def fill_of(side):
    return P0 * (1 + side * SLIP)


def rn(side, off, f=0.0):
    """Net R at the price P0 + side x off, after the round-trip cost and the funding paid per unit of notional (PREREG 4)."""
    fl = fill_of(side)
    return (side * (P0 + side * off - fl) - fl * (RT + f)) / R


SIDES = pytest.mark.parametrize("side", [1, -1])


def exits_at(e, j, reason="RULE"):
    assert e.trades, "no trade closed"
    t = e.trades[0]
    assert (t.exit_reason, t.exit_time) == (reason, at(j)), (t.exit_reason, (t.exit_time - T0) / MIN)
    return t


# ---------------------------------------------------------------- the rule interface
def test_every_study_id_round_trips():
    ids = RX.study_ids()
    assert len(ids) == 82 and len(set(ids)) == 82            # F1-F10, F7h included (PREREG 5.3)
    for i in ids:
        r = RX.parse_rule(i)
        assert r["id"] == i and RX.parse_rule(r)["id"] == i
    assert RX.parse_rule("F5.P1.5.g25.a") == {"id": "F5.P1.5.g25.a", "family": "F5", "mode": "a", "q15": False,
                                              "P": 1.5, "g": 0.25}
    assert RX.parse_rule("F6.w2.d0.5")["mode"] == "a" and RX.parse_rule("F9.b.q15")["w"] == 3
    assert RX.parse_rule("F7h.H8.b") == {"id": "F7h.H8.b", "family": "F7h", "mode": "b", "q15": False, "H": 8}
    d = RX.parse_rule({"family": "F4", "m": 2, "mode": "b", "q15": True})
    assert d["id"] == "F4.m2.b.q15" and d["m"] == 2.0
    for bad in ("F2.n20.b.q15", "F6.w2.d0.b", "F13.a", "F1.w3", "F1.w0.a", "F9.a.q16", "X", "F4.m0.a", "F5.P1.g100.a", "F7h.H8",
                "F7h.N8.a", "F7h.H0.a", "F7h.H8.a.q15"):
        with pytest.raises(RX.RuleConfigError):
            RX.parse_rule(bad)
    with pytest.raises(RX.RuleConfigError):
        RX.parse_rule({"family": "F1", "mode": "a"})                    # w missing
    with pytest.raises(RX.RuleConfigError):
        RX.parse_rule({"family": "F7", "N": 2.5, "mode": "a"})


def test_q15_is_the_base_variant_on_15m_and_30m_picks():
    r = RX.parse_rule("F1.w3.a.q15")
    assert [RX.effective_q15(r, tf) for tf in ("15m", "30m", "1h", "4h")] == [False, False, True, True]
    assert [RX.sched_of(acct("F1.w3.a.q15", tf=tf)) for tf in ("15m", "30m", "1h", "4h")] == ["p", "p", "q", "q"]
    assert RX.make_engine(acct("F1.w3.a.q15", tf="30m"), BR, SP).rx_sched == "p"
    assert RX.make_engine(acct("F1.w3.a.q15", tf="4h"), BR, SP).rx_sched == "q"
    assert RX.make_engine(acct("F1.w3.a.q15", tf="4h"), BR, SP).rx_tf_ms == 4 * HOUR


# ---------------------------------------------------------------- the exit itself
@SIDES
def test_rule_exit_is_a_market_order_at_the_check_minutes_open(side):
    """F7 N=2: the check at the 2nd close after the signal bar acts at that minute's open, with slippage and taker fee."""
    a = acct("F7.N2.a")
    recs = [rec(chk(k), side, 0) for k in (1, 2, 3)]
    e = run(a, Path(), side, recs=recs)
    t = exits_at(e, J0 + 120)
    px = P0 * (1 - side * SLIP)
    assert t.exit_price == pytest.approx(px) and t.leverage == 30 and t.entry_time == C0
    assert t.entry_price == pytest.approx(fill_of(side))
    gross = side * t.qty * (px - t.entry_price)
    assert t.fees == pytest.approx(t.qty * t.entry_price * TAKER + t.qty * px * TAKER)
    assert t.pnl == pytest.approx(gross - t.fees)
    assert e.wallet == pytest.approx(5000 + t.pnl) and e.position is None


@SIDES
def test_nothing_fires_on_or_before_the_signal_bars_close(side):
    """A record at or before the signal bar's close is never a check; the first check is the next close."""
    a = acct("F3.a")
    flag = {"sf": True} if side > 0 else {"lf": True}
    early = [rec(C0, side, 0, **flag), rec(C0 - HOUR, side, 0, **flag)]
    e = run(a, Path(), side, recs=early)
    assert not e.trades and e.position is not None and e.position.signal.meta["rx"]["k"] == 0
    e = run(a, Path(), side, recs=[rec(chk(1), side, 0, **flag)])
    exits_at(e, J0 + 60)


# ---------------------------------------------------------------- F1 structure break
@SIDES
def test_f1_reference_only_moves_up_and_fires_below_it(side):
    a = acct("F1.w3.a")
    seed = {"ref": P0 - side * 200}
    recs = [rec(chk(1), side, 50, **swing(side, 3, -100)),            # a higher swing low: the reference rises to -100
            rec(chk(2), side, -50, **swing(side, 3, -300)),           # a lower one: no change
            rec(chk(3), side, -120)]                                  # below -100 (above the first reference -200)
    e = run(a, Path(), side, sigs=((C0, sig(C0, side, seed)),), recs=recs[:2])
    assert e.position.signal.meta["rx"]["ref"] == P0 - side * 100 and not e.trades
    e = run(a, Path(), side, sigs=((C0, sig(C0, side, seed)),), recs=recs)
    exits_at(e, J0 + 180)
    # without a reference and without a confirmed swing it does nothing
    e = run(a, Path(), side, sigs=((C0, sig(C0, side, {"ref": None})),), recs=[rec(chk(k), side, -300) for k in (1, 2, 3)])
    assert not e.trades and e.position.signal.meta["rx"]["ref"] is None
    # a close exactly at the reference does not break it
    e = run(a, Path(), side, sigs=((C0, sig(C0, side, seed)),), recs=[rec(chk(1), side, -200)])
    assert not e.trades


# ---------------------------------------------------------------- F2 moving-average break
@SIDES
def test_f2_arm(side):
    a = acct("F2.n20.b")
    ema = lambda off: {"ema": {"20": P0 + side * off}}  # noqa: E731
    recs = [rec(chk(1), side, -100, **ema(-50)),                     # below its average, not armed: nothing
            rec(chk(2), side, 100, **ema(0)),                         # above: armed
            rec(chk(3), side, -100, **ema(0))]                        # armed, now below: fires
    e = run(a, Path(), side, sigs=((C0, sig(C0, side, {"above": False})),), recs=recs[:2])
    assert not e.trades and e.position.signal.meta["rx"]["arm"] is True
    e = run(a, Path(), side, sigs=((C0, sig(C0, side, {"above": False})),), recs=recs)
    exits_at(e, J0 + 180)
    e = run(a, Path(), side, sigs=((C0, sig(C0, side, {"above": True})),), recs=recs)       # armed at entry
    exits_at(e, J0 + 60)
    e = run(a, Path(), side, sigs=((C0, sig(C0, side, {"above": False})),),
            recs=[rec(chk(1), side, -100, ema={"20": None}), rec(chk(2), side, 100, ema={"20": None})])
    assert not e.trades                                               # an undefined EMA: no arm, no fire


# ---------------------------------------------------------------- F3 opposite signal and the reversal
@SIDES
def test_f3_fires_on_the_opposite_flag_and_the_opposite_signal_reverses(side):
    a = acct("F3.a")
    opp = {"sf": True} if side > 0 else {"lf": True}
    same = {"lf": True} if side > 0 else {"sf": True}
    e = run(a, Path(), side, recs=[rec(chk(1), side, 0, **same), rec(chk(2), side, 0, **opp)])
    exits_at(e, J0 + 120)
    # the opposite signal of the same close is entered at that very open (exit first, then entries)
    rev = sig(chk(2), -side)
    e = run(a, Path(), side, sigs=((C0, None), (chk(2), rev)), recs=[rec(chk(1), side, 0), rec(chk(2), side, 0, **opp)])
    exits_at(e, J0 + 120)
    assert e.position is not None and e.position.side == -side and e.position.entry_time == at(J0 + 120)
    # both flags true on that bar, offered long first: a long re-enters long (no reversal), a short reverses to long
    both = {"lf": True, "sf": True}
    offered = ((C0, None), (chk(2), sig(chk(2), 1)), (chk(2), sig(chk(2), -1)))
    e = run(a, Path(), side, sigs=offered, recs=[rec(chk(2), side, 0, **both)])
    exits_at(e, J0 + 120)
    assert e.position.side == 1 and e.position.entry_time == at(J0 + 120)


# ---------------------------------------------------------------- F4 chandelier
@SIDES
def test_f4_level_is_the_extreme_minus_m_atr(side):
    a = acct("F4.m2.a")
    path = Path().hold(125, 600)                                       # X = +600 (the high of minute 125)
    recs = [rec(chk(1), side, 450, atr=100.0), rec(chk(2), side, 350, atr=100.0)]   # level = 600 - 2 x 100 = 400
    e = run(a, path, side, recs=recs[:1])
    assert not e.trades
    e = run(a, path, side, recs=recs)
    exits_at(e, J0 + 120)
    e = run(a, path, side, recs=[rec(chk(1), side, 400, atr=100.0)])    # exactly at the level: not below it
    assert not e.trades


@SIDES
def test_f4_atr_is_the_latest_bars_and_q15_checks_on_15m_closes(side):
    a = acct("F4.m2.b.q15")
    path = Path().hold(125, 600)
    # until a pick-timeframe bar closes, the ATR is the signal bar's (200): level = 600 - 2 x 200 = 200
    recs = [rec(C0 + 15 * MIN, side, 450, k="q"), rec(C0 + 30 * MIN, side, 250, k="q")]
    e = run(a, path, side, recs=recs)
    assert not e.trades
    # the hourly bar's ATR (100) replaces it at that close: level = 400, and the 15m close of 300 is below it
    e = run(a, path, side, recs=recs + [rec(chk(1), side, 300, k="p", atr=100.0), rec(chk(1), side, 300, k="q")])
    exits_at(e, J0 + 60)


# ---------------------------------------------------------------- F5 giveback, hand-computed net R
@SIDES
def test_f5_arms_at_the_peak_and_fires_on_the_giveback(side):
    a = acct("F5.P1.g50.b")
    path = Path().hold(130, 700)
    rpk = rn(side, 700)
    assert rpk == pytest.approx((700 - 8 - fill_of(side) * RT) / R) and rpk > 1.0         # 1.59: armed at P = 1
    e = run(a, path, side, recs=[rec(chk(1), side, 700), rec(chk(2), side, 400)])     # Rc 0.84 > 0.5 x 1.59 = 0.795
    assert not e.trades and e.position.signal.meta["rx"]["armed"] is True
    e = run(a, path, side, recs=[rec(chk(1), side, 700), rec(chk(2), side, 300)])     # Rc 0.59 <= 0.795
    exits_at(e, J0 + 120)
    e = run(a, path, side, recs=[rec(chk(1), side, 700), rec(chk(2), side, 400), rec(chk(3), side, 300)])
    exits_at(e, J0 + 180)
    # the peak never reached P: unarmed, a big drop does nothing
    low = Path().hold(130, 300)
    assert rn(side, 300) < 1.0
    e = run(a, low, side, recs=[rec(chk(1), side, 300), rec(chk(2), side, -100)])
    assert not e.trades and e.position.signal.meta["rx"]["armed"] is False


@SIDES
def test_f5_uses_the_funding_paid_before_the_minute_and_not_the_minutes_own(side):
    a = acct("F5.P1.g50.b")
    path = Path().hold(130, 700)
    rate, mo = 0.0005 * side, P0 + side * 700                         # the position pays
    path.fund[150] = rate                                             # paid at minute 150, before the check at 180
    f1 = side * rate * mo / fill_of(side)                             # paid / (qty x fill) > 0
    thr = lambda f: 0.5 * rn(side, 700, f)  # noqa: E731
    # a close whose Rc sits 0.01 above the threshold without funding and below it with funding
    target = thr(0.0) + 0.01
    c_off = target * R + fill_of(side) * RT + side * (fill_of(side) - P0)
    assert rn(side, c_off) == pytest.approx(target) and rn(side, c_off, f1) < thr(f1)
    e = run(a, path, side, recs=[rec(chk(1), side, c_off)])
    t = exits_at(e, J0 + 60)
    assert t.funding == pytest.approx(side * t.qty * mo * rate)          # paid at 150, held over
    # funding at the check minute itself is paid but is not part of that minute's decision
    path2 = Path().hold(130, 700)
    path2.fund[J0 + 60] = 0.01 * side
    e = run(a, path2, side, recs=[rec(chk(1), side, c_off)])
    assert not e.trades                                              # frozen state: no fire at 180
    e = run(a, path2, side, recs=[rec(chk(1), side, c_off), rec(chk(2), side, c_off)])
    t = exits_at(e, J0 + 120)                                        # the next check sees that funding
    assert t.funding == pytest.approx(side * t.qty * (P0 + side * 700) * 0.01 * side)


# ---------------------------------------------------------------- F6 early loss cut
@SIDES
def test_f6_fires_only_below_minus_d(side):
    seed = {"ref": P0 - side * 100}
    c = lambda off: rec(chk(1), side, off)  # noqa: E731
    d5, d0 = acct("F6.w3.d0.5"), acct("F6.w3.d0")
    assert -0.5 < rn(side, -120) < 0 and rn(side, -140) < -0.5
    for off, fires5 in ((-120, False), (-140, True)):                 # both break the reference (-100)
        e = run(d5, Path(), side, sigs=((C0, sig(C0, side, seed)),), recs=[c(off)])
        assert bool(e.trades) is fires5
    e = run(d0, Path(), side, sigs=((C0, sig(C0, side, seed)),), recs=[c(-101)])
    exits_at(e, J0 + 60)                                              # d = 0: any net loss
    e = run(d0, Path(), side, sigs=((C0, sig(C0, side, seed)),), recs=[c(-50)])
    assert not e.trades                                               # no break: nothing, though in a net loss
    # in profit it never fires, whatever the break
    e = run(d0, Path(), side, sigs=((C0, sig(C0, side, {"ref": P0 + side * 500})),), recs=[c(300)])
    assert not e.trades


# ---------------------------------------------------------------- F8 and F9
@SIDES
def test_f8_needs_the_arm_and_the_break(side):
    a = acct("F8.w3.P1.a")
    seed = {"ref": P0 - side * 100}
    armed = Path().hold(130, 700)
    e = run(a, armed, side, sigs=((C0, sig(C0, side, seed)),), recs=[rec(chk(1), side, -150)])
    exits_at(e, J0 + 60)                                              # armed and broken at the same close
    e = run(a, armed, side, sigs=((C0, sig(C0, side, seed)),), recs=[rec(chk(1), side, 50)])
    assert not e.trades and e.position.signal.meta["rx"]["armed"] is True
    e = run(a, Path().hold(130, 300), side, sigs=((C0, sig(C0, side, seed)),), recs=[rec(chk(1), side, -150)])
    assert not e.trades                                               # never reached P: unarmed


@SIDES
def test_f9_fires_on_either_side_of_its_rule_and_not_otherwise(side):
    a = acct("F9.a")
    seed = {"ref": P0 - side * 100}
    s = ((C0, sig(C0, side, seed)),)
    e = run(a, Path().hold(130, 700), side, sigs=s, recs=[rec(chk(1), side, -150)])
    exits_at(e, J0 + 60)                                              # after a gain of 1R, a structure break
    e = run(a, Path(), side, sigs=s, recs=[rec(chk(1), side, -140)])
    exits_at(e, J0 + 60)                                              # in a loss of more than 0.5R, a break
    e = run(a, Path(), side, sigs=s, recs=[rec(chk(1), side, -120)])
    assert not e.trades                                               # a small loss, no gain: nothing
    e = run(a, Path().hold(130, 700), side, sigs=s, recs=[rec(chk(1), side, 300)])
    assert not e.trades                                               # no break
    assert RX.parse_rule("F9.a")["w"] == 3 and RX.parse_rule("F9.a")["P"] == 1.0 and RX.parse_rule("F9.a")["d"] == 0.5


@SIDES
def test_q15_checks_on_15m_closes_against_the_pick_timeframes_levels(side):
    a = acct("F1.w3.a.q15")
    seed = {"ref": P0 - side * 200}
    s = ((C0, sig(C0, side, seed)),)
    recs = [rec(C0 + 15 * MIN, side, -50, k="q"), rec(C0 + 30 * MIN, side, -250, k="q")]
    e = run(a, Path(), side, sigs=s, recs=recs)
    exits_at(e, J0 + 30)                                              # the 15m close below the reference acts at once
    base = run(acct("F1.w3.a"), Path(), side, sigs=s, recs=[rec(chk(1), side, -250)])
    exits_at(base, J0 + 60)                                           # the base variant waits for the pick's own close
    # the hourly bar's swing raises the reference first, whatever the order of the records at one close
    hour = [rec(chk(1), side, -120, k="q"), rec(chk(1), side, 50, **swing(side, 3, -100))]
    e = run(a, Path(), side, sigs=s, recs=hour)
    exits_at(e, J0 + 60)
    e = run(a, Path(), side, sigs=s, recs=hour[::-1])
    exits_at(e, J0 + 60)


# ---------------------------------------------------------------- F7 and F10
@SIDES
def test_f7_counts_time_not_bins_and_f10_needs_profit_and_a_stall(side):
    a = acct("F7.N2.a")
    e = run(a, Path(), side, recs=[rec(chk(1), side, 0), rec(chk(3), side, 0)])    # the 2nd hour's bin is missing
    exits_at(e, J0 + 180)
    e = run(a, Path(), side, recs=[rec(chk(1), side, 0), rec(chk(2) - HOUR // 2, side, 0)])   # a bar closing earlier
    assert not e.trades
    # F10: a new extreme at the entry minute, profit, and no new extreme for N = 2 bars
    s10 = acct("F10.N2.b")
    path = Path().bar(J0, o=0, c=100, b=300, w=0).hold(J0 + 1, 100)
    assert rn(side, 100) > 0
    e = run(s10, path, side, recs=[rec(chk(1), side, 100), rec(chk(2), side, 100)])
    exits_at(e, J0 + 120)
    e = run(s10, path, side, recs=[rec(chk(1), side, 100)])
    assert not e.trades                                               # only 1 bar since the extreme
    losing = Path().bar(J0, o=0, c=-50, b=10, w=-50).hold(J0 + 1, -50)
    e = run(s10, losing, side, recs=[rec(chk(1), side, -50), rec(chk(2), side, -50), rec(chk(3), side, -50)])
    assert not e.trades                                               # stalled but not in profit


# ---------------------------------------------------------------- decisions never read the minute being decided
@SIDES
def test_the_decision_at_minute_j_ignores_minute_j_and_later(side):
    """The high (low) of minute j alone would change F4's level, F5's and F8's arm and F10's stall: the decision at j
    must not see it (state frozen before the minute); it is used from the next check."""
    j = J0 + 60
    seed = {"ref": P0 - side * 100}
    spike = lambda: Path().bar(j, o=0, c=0, b=1000, w=0)  # noqa: E731
    # F4: the level moves up with the spike only after minute j
    a = acct("F4.m2.b")
    path = Path().hold(125, 600).bar(j, o=600, c=600, b=5000, w=600)
    e = run(a, path, side, recs=[rec(chk(1), side, 450, atr=100.0)])
    assert not e.trades
    e = run(a, path, side, recs=[rec(chk(1), side, 450, atr=100.0), rec(chk(2), side, 450, atr=100.0)])
    exits_at(e, J0 + 120)
    # F5: unarmed at j although minute j's high alone would arm and then fire
    a = acct("F5.P1.g50.b")
    e = run(a, spike(), side, recs=[rec(chk(1), side, 0)])
    assert not e.trades and e.position.signal.meta["rx"]["armed"] is False
    e = run(a, spike(), side, recs=[rec(chk(1), side, 0), rec(chk(2), side, 0)])
    exits_at(e, J0 + 120)
    # F8: the same
    a = acct("F8.w3.P1.b")
    e = run(a, spike(), side, sigs=((C0, sig(C0, side, seed)),), recs=[rec(chk(1), side, -200)])
    assert not e.trades
    e = run(a, spike(), side, sigs=((C0, sig(C0, side, seed)),), recs=[rec(chk(1), side, -200), rec(chk(2), side, -200)])
    exits_at(e, J0 + 120)
    # F10: a new extreme at minute j itself does not reset the stall that has already lasted N bars
    a = acct("F10.N2.b")
    path = Path().bar(J0, o=0, c=100, b=300, w=0).hold(J0 + 1, 100).bar(J0 + 120, o=100, c=100, b=900, w=100)
    e = run(a, path, side, recs=[rec(chk(1), side, 100), rec(chk(2), side, 100)])
    exits_at(e, J0 + 120)
    # whatever happens from minute j on cannot change the decision at j: two different futures, one exit
    base = Path().bar(J0, o=0, c=100, b=300, w=0).hold(J0 + 1, 100)
    other = Path().bar(J0, o=0, c=100, b=300, w=0).hold(J0 + 1, 100).bar(J0 + 120, o=100, c=-300, b=2000, w=-390)
    for pth in (base, other):
        e = run(a, pth, side, recs=[rec(chk(1), side, 100), rec(chk(2), side, 100)])
        exits_at(e, J0 + 120)


# ---------------------------------------------------------------- step order and gaps
@SIDES
def test_step_order_is_funding_then_rule_exit_then_entries(side):
    a = acct("F7.N2.a")
    path = Path()
    path.fund[J0 + 120] = 0.0004
    nxt = sig(chk(2), side)                                            # a new signal of the same close
    e = run(a, path, side, sigs=((C0, None), (chk(2), nxt)), recs=[rec(chk(1), side, 0), rec(chk(2), side, 0)])
    t = e.trades[0]
    assert t.exit_reason == "RULE" and t.exit_time == at(J0 + 120)
    assert t.funding == pytest.approx(side * t.qty * P0 * 0.0004) and t.funding != 0         # held over the funding instant
    assert e.position is not None and e.position.entry_time == at(J0 + 120) and e.position.funding_paid == 0.0
    assert e.position.entry_price == pytest.approx(fill_of(side))
    assert e.wallet == pytest.approx(5000 + t.pnl - e.position.entry_fee)                    # exit pnl in before the entry fee


@SIDES
def test_a_gapped_open_leaves_the_exit_to_the_engine_and_the_minute_stays_blocked(side):
    a = acct("F7.N2.a")
    recs = [rec(chk(1), side, 0), rec(chk(2), side, 0)]
    other = ((C0, None), (chk(2), sig(chk(2), -side)))
    j = J0 + 120
    # a gap beyond the stop: SL at the open (slippage, taker), not RULE, and the signal of that close finds the account busy
    path = Path().bar(j, o=-500, c=-500)
    path.hold(j + 1, -500)
    e = run(a, path, side, sigs=other, recs=recs)
    t = exits_at(e, j, "SL")
    assert t.exit_price == pytest.approx((P0 - side * 500) * (1 - side * SLIP)) and e.position is None and len(e.trades) == 1
    # a gap beyond the take-profit (3R, mode a): TP at the open, maker; mode b: the rule takes it (RULE)
    path = Path().bar(j, o=1300, c=1300)
    path.hold(j + 1, 1300)
    e = run(a, path, side, sigs=other, recs=recs)
    t = exits_at(e, j, "TP")
    assert t.exit_price == pytest.approx(P0 + side * 1300) and e.position is None
    e = run(acct("F7.N2.b"), path, side, sigs=other, recs=recs)
    exits_at(e, j, "RULE")
    assert e.position is not None and e.position.side == -side                              # freed for the same open
    # liquidation first of all: the mark open is beyond liquidation while the last price is also beyond the stop
    path = Path().bar(j, o=-500, c=-500)
    path.hold(j + 1, -500)
    path.mark_open[j] = -3000
    e = run(a, path, side, sigs=other, recs=recs)
    exits_at(e, j, "LIQ")
    assert e.position is None


@SIDES
def test_a_missing_minute_waits_for_the_next_one(side):
    a = acct("F7.N2.a")
    path = Path()
    path.missing.add(J0 + 120)                                         # the check's minute has no bar
    e = run(a, path, side, recs=[rec(chk(1), side, 0), rec(chk(2), side, 0)])
    exits_at(e, J0 + 121)


@SIDES
def test_an_entry_and_a_rule_exit_of_one_close_land_on_the_same_minute_also_when_the_bins_last_minute_is_missing(side):
    a = acct("F7.N2.a")
    j = J0 + 120
    path = Path()
    path.missing.add(j - 1)                                            # the bin's last minute (the one that ends at the close)
    recs = [rec(chk(1), side, 0), rec(chk(2), side, 0)]
    e = run(a, path, side, sigs=((C0, None), (chk(2), sig(chk(2), -side))), recs=recs)
    exits_at(e, j + 1)                                                 # kernel._entry_index: the minute after the first one at the close
    assert e.position is not None and e.position.entry_time == at(j + 1) and e.position.side == -side


# ---------------------------------------------------------------- modes a and b
@SIDES
def test_mode_a_keeps_the_take_profit_and_mode_b_has_none_and_no_lock(side):
    path = Path().hold(130, 1500, 400).hold(400, 1500)
    a, b = acct("F7.N20.a"), acct("F7.N20.b")
    ea, eb = run(a, path, side), run(b, path, side)
    assert ea.trades and ea.trades[0].exit_reason == "TP"
    assert not eb.trades and math.isnan(eb.position.tp_price) and eb.s.tp_mode == "fixed"
    # mode b on a stepped-lock exit: the stop never moves (no lock); mode a keeps the lock
    lad = Path().hold(130, 700)
    eb = run(acct("F7.N20.b", exit_="ladder|2"), lad, side)
    ea = run(acct("F7.N20.a", exit_="ladder|2"), lad, side)
    assert eb.position.stop_price == eb.position.stop_initial and eb.position.lock_roe is None
    assert ea.position.lock_roe is not None and (ea.position.stop_price - ea.position.stop_initial) * side > 0
    # mode a on the net-ROE and R take-profit exits is the exit's own engine
    for name in ("tp3R|2", "tp2R|2.5", "roe50|4", "ladder_tp2R|3", "swing3|2", "ladder|2"):
        e, p = RX.make_engine(acct("F1.w3.a", exit_=name), BR, SP), X.make_engine(name, BR, SP)
        assert isinstance(e, RX.RuleMixin) and isinstance(e, type(p)) and e.s == p.s and type(e.policy) is type(p.policy)
        assert (getattr(e, "m", None), getattr(e, "struct", None)) == (getattr(p, "m", None), getattr(p, "struct", None))


# ---------------------------------------------------------------- the twins and the existing engines are untouched
def test_twins_and_existing_accounts_get_the_plain_engines():
    for name in X.BY_NAME:
        for size in (1.0, 0.25):
            t = RX.make_engine(acct(None, exit_=name, size=size), BR, SP)
            p = X.make_engine(name, BR, SP, size=size)
            assert type(t) is type(p) and not isinstance(t, RX.RuleMixin) and t.s == p.s
    cands = C.load()
    accts = C.accounts(cands)
    eng = L.make_engines(accts, BR, SP)
    assert len(eng) == len(accts) and not any(isinstance(e, RX.RuleMixin) for e in eng.values())
    assert all(type(e) in (PaperEngine, X.LadderTP) for e in eng.values())


def test_the_fingerprint_of_existing_accounts_is_what_it_was():
    accts = C.accounts(C.load())
    body = json.dumps([[a["id"], a["kind"], a["name"], a["tf"], a["combo"], a["exit"], a["role"], a.get("size", 1.0)]
                       for a in accts], sort_keys=True)
    assert RN.fingerprint(accts) == hashlib.sha256(f"{RN.VERSION}|{body}".encode()).hexdigest()
    cfg = cfg_of("F7.N12.a")
    r1 = RX.accounts(C.load(), cfg)
    r2 = RX.accounts(C.load(), cfg_of("F7.N24.a"))
    assert RN.fingerprint(r1) != RN.fingerprint(r2) != RN.fingerprint(accts) and len(RN.fingerprint(r1)) == 64


# ---------------------------------------------------------------- a stop and restart in the middle of a position
def test_state_lives_in_the_signal_meta_and_survives_the_engines_own_save(side=1):
    a = acct("F5.P1.g50.b")
    path = Path().hold(130, 700)
    e = run(a, path, side, recs=[rec(chk(1), side, 700)])
    st = json.loads(json.dumps(engine_state(e)))
    rx = st["position"]["signal"]["meta"]["rx"]
    assert rx["armed"] is True and rx["k"] == 1 and rx["x"] == pytest.approx(P0 + 700) and rx["c0"] == C0
    again = RX.make_engine(a, BR, SP)
    restore_engine(again, st)
    assert again.position.signal.meta["rx"] == e.position.signal.meta["rx"]
    assert again.position.mfe_price == e.position.mfe_price and again.position.funding_paid == e.position.funding_paid


def test_a_check_waiting_for_its_minute_survives_a_restart():
    a, side = acct("F7.N2.a"), 1
    steps, recs = Path().steps(side), [rec(chk(1), side, 0), rec(chk(2), side, 0)]
    closes = sorted({r["t"] for r in recs} | {C0})

    def play(restart_at):
        e = RX.make_engine(a, BR, SP)
        by = {C0: [sig(C0, side)]}
        for r in recs:
            by.setdefault(r["t"], []).append(RX.RuleClose(r))
        k, queued = 0, False
        for j, (t, bars, fund) in enumerate(steps):
            PS.stamp_ref(e, bars)
            e.step(bars, fund)
            for c in closes[k:]:
                if c <= t + MIN:
                    for o in by[c]:
                        e.submit(o)
                    k += 1
            if j == restart_at:
                st = json.loads(json.dumps(engine_state(e)))
                queued = bool(e.position.signal.meta["rx"]["q"]) if e.position else False
                trades, e = list(e.trades), RX.make_engine(a, BR, SP)
                restore_engine(e, st)
                e.trades = trades
        return [asdict(t) for t in e.trades], queued
    whole, _ = play(None)
    split, queued = play(J0 + 119)                                    # the record of the 2nd check was just handed in
    assert queued and split == whole and whole[0]["exit_reason"] == "RULE" and whole[0]["exit_time"] == at(J0 + 120)


# ---- a random world: 1m path, hourly chart records with their own naive indicators, signals of both sides
def _world(seed, n=6000):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.0006, n)
    c = P0 * np.exp(np.cumsum(r))
    o = np.r_[P0, c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0004, n)))
    fund = {j: float(rng.choice([-1, 1]) * rng.uniform(1e-5, 4e-4)) for j in range(0, n, 480)}
    steps = []
    for j in range(n):
        t = at(j)
        b = Bar(SYM, t, t + MIN - 1, float(o[j]), float(hi[j]), float(lo[j]), float(c[j]), mark_open=float(o[j]),
                mark_high=float(hi[j]), mark_low=float(lo[j]), mark_close=float(c[j]))
        steps.append((t, {SYM: b}, {SYM: fund[j]} if j in fund else {}))
    nb = n // 60
    H = np.array([hi[i * 60:(i + 1) * 60].max() for i in range(nb)])
    Lw = np.array([lo[i * 60:(i + 1) * 60].min() for i in range(nb)])
    Cl = np.array([c[i * 60 + 59] for i in range(nb)])
    tr = np.r_[H[0] - Lw[0], [max(H[i] - Lw[i], abs(H[i] - Cl[i - 1]), abs(Lw[i] - Cl[i - 1])) for i in range(1, nb)]]
    atr = np.zeros(nb)
    atr[0] = tr[0]
    for i in range(1, nb):
        atr[i] = (atr[i - 1] * 13 + tr[i]) / 14
    ema = np.zeros(nb)
    ema[0] = Cl[0]
    for i in range(1, nb):
        ema[i] = ema[i - 1] + (Cl[i] - ema[i - 1]) * 2 / 11
    w = 2
    sl = [None] * nb
    for i in range(nb):
        p = i - w
        if p >= w and all(Lw[p] < Lw[q] for q in range(p - w, p + w + 1) if q != p):
            sl[i] = float(Lw[p])
    sh = [None] * nb
    for i in range(nb):
        p = i - w
        if p >= w and all(H[p] > H[q] for q in range(p - w, p + w + 1) if q != p):
            sh[i] = float(H[p])
    lf, sf = rng.random(nb) < 0.18, rng.random(nb) < 0.18
    recs, sigs = [], []
    for i in range(14, nb):
        close = at((i + 1) * 60)
        d = {"k": "p", "sym": SYM, "t": close, "c": float(Cl[i]), "atr": float(atr[i]), "ema": {"10": float(ema[i])},
             "sl": {"2": sl[i]}, "sh": {"2": sh[i]}, "lf": bool(lf[i]), "sf": bool(sf[i])}
        recs.append(d)
        for k in (1, 2, 3):
            recs.append({"k": "q", "sym": SYM, "t": close - 60 * MIN + 15 * k * MIN, "c": float(c[(i + 1) * 60 - 60 + 15 * k - 1])}
                        if (i + 1) * 60 - 60 + 15 * k - 1 < n and k < 4 else None)
        for s in ([1] if lf[i] else []) + ([-1] if sf[i] else []):
            ref = None
            if s > 0:
                cands_ = [Lw[p] for p in range(max(0, i - 300), i - w + 1) if p >= w and all(Lw[p] < Lw[q] for q in range(p - w, p + w + 1) if q != p) and Lw[p] < Cl[i]]
                ref = float(max(cands_)) if cands_ else None
            else:
                cands_ = [H[p] for p in range(max(0, i - 300), i - w + 1) if p >= w and all(H[p] > H[q] for q in range(p - w, p + w + 1) if q != p) and H[p] > Cl[i]]
                ref = float(min(cands_)) if cands_ else None
            sigs.append((close, Signal(ts=close - 1, symbol=SYM, timeframe="1h", strategy_id="S2_ST_ROC", side=s,
                                       stop_price=0.0, tier="best", atr=float(atr[i]),
                                       meta={"stop_dist": float(atr[i]), "lev_group": "normal",
                                             "rx0": {"ref": ref, "above": bool((Cl[i] - ema[i]) * s > 0)}})))
    recs = [r for r in recs if r is not None and r["t"] > at(14 * 60)]
    return steps, recs, sigs


RANDOM_RULES = ("F1.w2.a", "F1.w2.b.q15", "F2.n10.b", "F3.a", "F4.m1.5.b", "F4.m2.b.q15", "F5.P1.g50.b", "F6.w2.d0",
                "F7.N2.a", "F8.w2.P1.b", "F9.b.q15", "F10.N2.b")


def _plain(t):
    """A trade as a dict with NaN as None (a trade without a take-profit): two NaNs are not equal, two Nones are."""
    return {k: (None if isinstance(v, float) and v != v else v) for k, v in asdict(t).items()}


def _play(a, world, every=None):
    steps, recs, sigs = world
    by: dict = {}
    for c, s in sigs:
        by.setdefault(c, []).append(s)
    for r in recs:
        by.setdefault(r["t"], []).append(RX.RuleClose(r))
    closes = sorted(by)
    e = RX.make_engine(a, BR, SP)
    trades, k, mid = [], 0, 0
    for j, (t, bars, fund) in enumerate(steps):
        PS.stamp_ref(e, bars)
        e.step(bars, fund)
        e.outcomes.clear()
        while k < len(closes) and closes[k] <= t + MIN:
            for o in by[closes[k]]:
                e.submit(o)
            k += 1
        if every and j % every == 0:
            st = json.loads(json.dumps(engine_state(e)))
            if e.position is not None and e.position.signal.meta.get("rx", {}).get("q"):
                mid += 1
            trades += e.trades
            e = RX.make_engine(a, BR, SP)
            restore_engine(e, st)
    trades += e.trades
    return [_plain(t) for t in trades], e.wallet, mid


@pytest.mark.parametrize("rule", RANDOM_RULES)
def test_stopping_and_restoring_in_the_middle_gives_identical_later_trades(rule):
    a = acct(rule, exit_="tp1R|1")
    total, rule_exits = 0, 0
    for seed in (1, 2, 3):
        world = _world(seed)
        whole, w_whole, _ = _play(a, world)
        for every in (1, 7):
            split, w_split, mid = _play(a, world, every=every)
            assert split == whole and w_split == w_whole, (rule, seed, every)
        total += len(whole)
        rule_exits += sum(t["exit_reason"] == "RULE" for t in whole)
        # every RULE exit is at the open of a check minute of the account's schedule, with slippage, after its entry
        sched = RX.sched_of(a)
        checks = {r["t"] for r in world[1] if r["k"] == sched}
        opens = {t: b[SYM].open for t, b, _f in world[0]}
        for t in whole:
            if t["exit_reason"] == "RULE":
                assert t["exit_time"] in checks and t["exit_time"] > t["entry_time"]
                assert t["exit_price"] == pytest.approx(opens[t["exit_time"]] * (1 - t["side"] * SLIP))
    assert total > 3 and rule_exits >= 1, (rule, total, rule_exits)


def test_restoring_at_every_minute_catches_a_check_waiting_in_the_queue():
    a = acct("F7.N2.a", exit_="tp1R|1")
    world = _world(5)
    whole, _, _ = _play(a, world)
    split, _, mid = _play(a, world, every=1)
    assert split == whole and mid > 0


# ---------------------------------------------------------------- chart records: swings, references, no look-ahead
def _naive_swings(h, l, w):
    n = len(h)
    ph, pl = np.zeros(n, bool), np.zeros(n, bool)
    for p in range(w, n - w):
        ph[p] = all(h[p] > h[q] for q in range(p - w, p + w + 1) if q != p)
        pl[p] = all(l[p] < l[q] for q in range(p - w, p + w + 1) if q != p)
    return ph, pl


@pytest.mark.parametrize("w", [2, 3, 5])
def test_swing_flags_and_the_starting_reference(w):
    rng = np.random.default_rng(w)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 700)))
    h = np.round(c * (1 + rng.uniform(0, 0.006, 700)), 2)                 # rounded: ties exist
    l = np.round(c * (1 - rng.uniform(0, 0.006, 700)), 2)
    ph, pl = RX.swing_flags(h, l, w)
    nph, npl = _naive_swings(h, l, w)
    assert (ph == nph).all() and (pl == npl).all() and ph.any() and pl.any()
    for i in rng.integers(0, 700, 80):
        i = int(i)
        for side in (1, -1):
            want = X.structure_level(h, l, c, i, w, -side)                 # long: the highest swing low below the close
            got = RX.start_ref(side, ph, pl, h, l, c, i, w)
            assert (got is None and math.isnan(want)) or got == want, (i, side, got, want)
    # the study's own numba kernel says the same
    pytest.importorskip("numba")
    import importlib.util
    spec = importlib.util.spec_from_file_location("fg_kernel_for_rulex", os.path.join(ROOT, "research", "fullgrid", "kernel.py"))
    kern = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kern)
    tl, ts = kern.structure_levels(h, l, c, w, 300)
    for i in rng.integers(0, 700, 80):
        got = RX.start_ref(1, ph, pl, h, l, c, int(i), w)
        assert (got is None and math.isnan(ts[i])) or got == ts[i]
        got = RX.start_ref(-1, ph, pl, h, l, c, int(i), w)
        assert (got is None and math.isnan(tl[i])) or got == tl[i]


import test_paramshadow as TP  # noqa: E402  (synthetic 5m bars, 1m steps, brackets)

DATA = {s: TP._synth5(i + 3, TP.P0[s]) for i, s in enumerate(TP.SYMS)}
START, DAY = TP.D0, TP.DAY
LIB = sweepsig.lib()


def _frame(tf, upto=None, sym="BTCUSDT"):
    cols = DATA[sym]
    keep = np.ones(len(cols[0]), bool) if upto is None else cols[0] < upto
    return PS.chart_frame(LIB, tuple(a[keep] for a in cols), tf)


def test_records_are_known_at_the_close_and_equal_a_frame_cut_there():
    """A record is the same whether the frame holds only the bars up to its close or more: nothing after the close is read."""
    df = _frame("1h")
    pack = RX.FramePack(LIB, df)
    needs = {"atr": True, "ema": [10, 50], "sw": [2, 3, 5], "flags": False, "xf": False}
    close = (df["ts"].astype("int64") // 1_000_000).to_numpy(np.int64) + 3_600_000
    full = {}
    for i in range(len(df) - 400, len(df) - 380):
        full[i] = RX.close_record(pack, i, "BTCUSDT", int(close[i]), needs)
    for i, want in full.items():
        cut = df.iloc[:i + 1].reset_index(drop=True)
        got = RX.close_record(RX.FramePack(LIB, cut), i, "BTCUSDT", int(close[i]), needs)
        assert got == want, i
    # what a record says: the swing low confirmed at close i is bar i - w's low, an EMA and ATR as the study's indicators
    i = len(df) - 390
    rec_ = full[i]
    lows = df["low"].to_numpy(float)
    for w in (2, 3, 5):
        p = i - w
        is_low = all(lows[p] < lows[q] for q in range(p - w, p + w + 1) if q != p)
        assert rec_["sl"][str(w)] == (lows[p] if is_low else None)
    assert rec_["atr"] == pytest.approx(LIB.fg.atr(df, 14).iloc[i]) and rec_["ema"]["50"] == pytest.approx(LIB.fg.ema(df["close"], 50).iloc[i])
    assert rec_["t"] == int(close[i]) and rec_["c"] == float(df["close"].iloc[i]) and rec_["k"] == "p"


# ---------------------------------------------------------------- signals and records per chunk
class StubStrategies:
    """Flags by bar number: longs every 9th bar, shorts every 6th except where a long is (no pick carries both flags, PREREG 3);
    ``both=True`` keeps the bars in common with both flags (the guard test)."""

    def __init__(self, both=False):
        self.calls, self.both = 0, both

    def signals(self, acct_, df, sym, frames_btc):
        self.calls += 1
        n = (df["ts"].astype("int64") // 1_000_000).to_numpy(np.int64) // L.TF_MS[acct_["tf"]]
        lo, sh = (n % 9 == 3), (n % 6 == 3)
        return lo, (sh if self.both else sh & ~lo)

    def strength(self, name):
        return None


def _rule_cands(tf="15m", exit_="tp3R|2"):
    c = {"id": f"core-S2-{tf}-1", "kind": "core", "name": "S2_ST_ROC", "tf": tf,
         "combo": {k: C._plain(v) for k, v in C.default_combo("core", "S2_ST_ROC").items()}, "exit": exit_, "source": {}}
    return [c]


def test_a_bar_with_both_flags_stops_the_run_and_a_coin_flip_takes_one_seeded_side():
    accts = RX.accounts(_rule_cands("15m"), cfg_of("F3.a"))
    with pytest.raises(RX.BothFlags):
        RX.chunk_rule(LIB, PS.FrameSource(DATA), accts, TP.SYMS, START, START + DAY, START, StubStrategies(both=True))
    # the twins alone (no rule family) are guarded the same way: they are the study's E0
    twins = [a for a in accts if a["rule"]["family"] is None]
    with pytest.raises(RX.BothFlags):
        RX.chunk_rule(LIB, PS.FrameSource(DATA), twins, TP.SYMS, START, START + DAY, START, StubStrategies(both=True))


def test_rule_accounts_are_offered_every_flag_and_a_coin_flip_one_seeded_side():
    cfg = cfg_of("F3.a")
    accts = RX.accounts(_rule_cands("15m"), cfg)
    by, notes = RX.chunk_rule(LIB, PS.FrameSource(DATA), accts, TP.SYMS, START, START + DAY, START,
                              StubStrategies())
    sigs = {}
    for close, items in by.items():
        for aid, o in items:
            if isinstance(o, Signal):
                sigs.setdefault((aid, o.symbol, close), []).append(o.side)
    rule_id = "core-S2-15m-1-nq"
    assert sigs and all(len(v) == 1 for v in sigs.values()) and {v[0] for v in sigs.values()} == {1, -1}      # one side per bar
    for aid in (rule_id, "core-S2-15m-1-n", "core-S2-15m-1-eq", "core-S2-15m-1-e"):
        assert {k[1:]: v for k, v in sigs.items() if k[0] == aid} == {k[1:]: v for k, v in sigs.items() if k[0] == rule_id}
    flip = {k[1:]: v for k, v in sigs.items() if k[0] == "core-S2-15m-1-nflip"}
    assert set(flip) == {k[1:] for k in sigs if k[0] == rule_id} and all(len(v) == 1 for v in flip.values())
    for (sym, close), v in flip.items():
        assert v == [L.flip_side("core-S2-15m-1-nflip", close)]
    # the stop is the pick's exit (2 ATR) and a rule account's signal carries its seed and its style
    some = next(o for c, items in by.items() for aid, o in items if aid == rule_id and isinstance(o, Signal))
    assert some.meta["stop_dist"] == pytest.approx(2 * some.atr) and some.meta["rx0"] == {} and some.meta["style"] == "rule:F3.a"
    # a record for every chart close of every coin, for the rule accounts only (the twins get none)
    recs = [(aid, o.d) for items in by.values() for aid, o in items if isinstance(o, RX.RuleClose)]
    assert {aid for aid, _ in recs} == {rule_id, "core-S2-15m-1-n", "core-S2-15m-1-nflip"}
    mine = [d for aid, d in recs if aid == rule_id]
    assert {d["sym"] for d in mine} == set(TP.SYMS) and len(mine) == 2 * 96 and all(d["k"] == "p" and "lf" in d for d in mine)
    assert all(START < d["t"] <= START + DAY for d in mine) and not notes


def test_q15_gets_15m_records_on_a_1h_pick_and_a_structure_rule_gets_its_seed():
    cfg = cfg_of("F1.w3.a.q15")
    accts = [a for a in RX.accounts(_rule_cands("1h"), cfg) if a["id"].endswith("-nq")]
    by, _ = RX.chunk_rule(LIB, PS.FrameSource(DATA), accts, TP.SYMS, START, START + DAY, START, StubStrategies())
    recs = [o.d for items in by.values() for aid, o in items if isinstance(o, RX.RuleClose) and o.d["sym"] == "BTCUSDT"]
    p, q = [d for d in recs if d["k"] == "p"], [d for d in recs if d["k"] == "q"]
    assert len(p) == 24 and len(q) == 96 and all("sl" in d and "sh" in d and "3" in d["sl"] for d in p)
    assert all(set(d) == {"k", "sym", "t", "c"} for d in q)
    df15 = _frame("15m")
    row = {int(t): float(c) for t, c in zip((df15["ts"].astype("int64") // 1_000_000).to_numpy(np.int64) + 900_000, df15["close"])}
    assert all(d["c"] == row[d["t"]] for d in q)
    # at a close both lists have a pick-timeframe record and a 15m record; the pick's comes first in the list
    t = p[3]["t"]
    kinds = [o.d["k"] for aid, o in by[t] if isinstance(o, RX.RuleClose) and o.d["sym"] == "BTCUSDT"]
    assert kinds == ["p", "q"]
    seeds = [o.meta["rx0"] for items in by.values() for aid, o in items if isinstance(o, Signal)]
    assert seeds and all(set(s) == {"ref"} for s in seeds) and any(s["ref"] is not None for s in seeds)
    # the seed is kernel.structure_levels' reference at the signal bar
    df = _frame("1h")
    pack = RX.FramePack(LIB, df)
    close = (df["ts"].astype("int64") // 1_000_000).to_numpy(np.int64) + 3_600_000
    for items in by.values():
        for aid, o in items:
            if isinstance(o, Signal) and o.symbol == "BTCUSDT":
                i = int(np.flatnonzero(close == o.ts + 1)[0])
                want = X.structure_level(pack.h, pack.l, pack.c, i, 3, -o.side)
                got = o.meta["rx0"]["ref"]
                assert (got is None and math.isnan(want)) or got == want


# ---------------------------------------------------------------- F11 / F12: the strategy's own exit (PREREG 5.2, Appendix A)
def nrec(t, side, off, nl=(), ns=(), **kw):
    """A pick-timeframe record with the tri-state values (1 true, 0 false, 2 unknown) of the long / short side's components."""
    return rec(t, side, off, nl=list(nl), ns=list(ns), **kw)


def nsig(side, ck, nv, inv=None, tgt=None, s0=None, c0px=P0, close=C0, aid="t"):
    """A signal of a strategy with components of kinds ``ck`` whose values at the signal bar are ``nv`` (the position's side)."""
    return sig(close, side, {"ck": list(ck), "nv": list(nv), "c0px": c0px}, aid=aid, native_inv=inv, native_tgt=tgt, native_s=s0 or side)


def key_of(side):
    return "nl" if side > 0 else "ns"


@SIDES
def test_f11_event_component_fires_where_true_and_a_state_component_after_it_has_been_false(side):
    k = key_of(side)
    # an event component: no arm, it fires at the first check where it is true
    a = acct("F11.a")
    e = run(a, Path(), side, sigs=((C0, nsig(side, ["event"], [0])),),
            recs=[nrec(chk(1), side, 0, **{k: [0]}), nrec(chk(2), side, 0, **{k: [1]}), nrec(chk(3), side, 0, **{k: [1]})])
    exits_at(e, J0 + 120)
    # a state component true at the signal bar is not armed (rule C3): true at the first check does not fire; it arms on the first false
    e = run(a, Path(), side, sigs=((C0, nsig(side, ["state"], [1])),),
            recs=[nrec(chk(1), side, 0, **{k: [1]}), nrec(chk(2), side, 0, **{k: [0]}), nrec(chk(3), side, 0, **{k: [1]})])
    exits_at(e, J0 + 180)
    # false at the signal bar: armed at once, fires at the first check where it is true
    e = run(a, Path(), side, sigs=((C0, nsig(side, ["state"], [0])),),
            recs=[nrec(chk(1), side, 0, **{k: [0]}), nrec(chk(2), side, 0, **{k: [1]})])
    exits_at(e, J0 + 120)
    # an unknown value (2) neither fires nor arms (rule C7): true after only unknowns, with an unarmed start, never fires
    e = run(a, Path(), side, sigs=((C0, nsig(side, ["state"], [1])),),
            recs=[nrec(chk(1), side, 0, **{k: [2]}), nrec(chk(2), side, 0, **{k: [1]}), nrec(chk(3), side, 0, **{k: [2]})])
    assert not e.trades and e.position is not None
    # the other side's components are not read
    other = "ns" if side > 0 else "nl"
    e = run(a, Path(), side, sigs=((C0, nsig(side, ["event"], [0])),),
            recs=[nrec(chk(1), side, 0, **{k: [0], other: [1]}), nrec(chk(2), side, 0, **{k: [0], other: [1]})])
    assert not e.trades
    # two components: any one fires, each with its own arm
    e = run(a, Path(), side, sigs=((C0, nsig(side, ["state", "state"], [0, 1])),),
            recs=[nrec(chk(1), side, 0, **{k: [0, 1]}), nrec(chk(2), side, 0, **{k: [0, 0]}), nrec(chk(3), side, 0, **{k: [0, 1]})])
    exits_at(e, J0 + 180)                                                        # the second component armed at check 2, fires at 3


@SIDES
def test_f11_merged_checks_walk_the_bars_in_time_order_and_fire_on_any_bar(side):
    """Two chart closes that reach one minute (a minute missing) are one check: arming and testing in time order, any bar fires."""
    k = key_of(side)
    path = Path()
    path.missing = set(range(J0 + 59, J0 + 120))                                 # no minute from the first close to the second: the checks merge
    a = acct("F11.a")
    e = run(a, path, side, sigs=((C0, nsig(side, ["state"], [1])),),
            recs=[nrec(chk(1), side, 0, **{k: [0]}), nrec(chk(2), side, 0, **{k: [1]})])
    assert e.trades and e.trades[0].exit_reason == "RULE"                       # false (arms) then true (fires) inside one check
    # the reverse order does not fire: true while unarmed, then false
    e = run(a, path, side, sigs=((C0, nsig(side, ["state"], [1])),),
            recs=[nrec(chk(1), side, 0, **{k: [1]}), nrec(chk(2), side, 0, **{k: [0]})])
    assert not e.trades


@SIDES
def test_f11_level_is_fixed_at_the_signal_bar_armed_by_a_close_not_beyond_it_and_tested_at_every_close(side):
    k = key_of(side)
    inv = P0 - side * 300
    a = acct("F11.a")
    # armed at the signal bar (its close is not beyond the level): the first close beyond it fires
    e = run(a, Path(), side, sigs=((C0, nsig(side, ["event"], [0], inv=inv)),),
            recs=[rec(chk(1), side, -200, **{k: [0]}), rec(chk(2), side, -400, **{k: [0]})])
    exits_at(e, J0 + 120)
    # a signal bar that already closed beyond the level does not arm it: it arms on the first close not beyond it
    e = run(a, Path(), side, sigs=((C0, nsig(side, ["event"], [0], inv=inv, c0px=P0 - side * 500)),),
            recs=[rec(chk(1), side, -400, **{k: [0]}), rec(chk(2), side, 0, **{k: [0]}), rec(chk(3), side, -400, **{k: [0]})])
    exits_at(e, J0 + 180)
    # a NaN level (None) is no level (rule C7)
    e = run(a, Path(), side, sigs=((C0, nsig(side, ["event"], [0], inv=None)),), recs=[rec(chk(1), side, -9000, **{k: [0]})])
    assert not e.trades


@SIDES
def test_f11_coin_flip_position_on_the_other_side_gets_the_mirrored_level_and_target(side):
    """The strategy is on side ``side``; the flip takes the other side: level and target mirrored around the flip's own fill."""
    flip = -side
    s_inv, s_tgt = P0 - side * 300, P0 + side * 900
    a = acct({"family": "F11", "mode": "b"})
    e = run(a, Path(), flip, sigs=((C0, nsig(flip, ["event"], [0], inv=s_inv, tgt=s_tgt, s0=side)),))
    rx, p = e.position.signal.meta["rx"], e.position
    f = p.entry_price
    inv2, tgt2 = RX.flip_levels(side, flip, f, s_inv, s_tgt)
    assert rx["lvl"] == pytest.approx(inv2) and rx["tgt"] == pytest.approx(tgt2)
    assert (rx["lvl"] - f) * flip < 0 and (rx["tgt"] - f) * flip > 0               # the level is against the flip, the target ahead of it
    assert p.tp_price == pytest.approx(tgt2)                                        # F11.b: a take-profit limit at the mirrored target
    # on the strategy's own side the values stand
    e = run(a, Path(), side, sigs=((C0, nsig(side, ["event"], [0], inv=s_inv, tgt=s_tgt)),))
    assert e.position.signal.meta["rx"]["lvl"] == s_inv and e.position.tp_price == s_tgt
    # a flip's own-side state component that is true at the signal bar waits for a false close (rule C3)
    k = key_of(flip)
    e = run(acct("F11.a"), Path(), flip, sigs=((C0, nsig(flip, ["state"], [1], s0=side)),),
            recs=[nrec(chk(1), flip, 0, **{k: [1]})])
    assert not e.trades


def test_flip_levels_are_the_kernels():
    assert RX.flip_levels(1, 1, 99.98, 99.0, 102.0) == (99.0, 102.0)
    inv, tgt = RX.flip_levels(1, -1, 99.98, 99.0, 102.0)
    assert inv == pytest.approx(99.98 + abs(99.98 - 99.0)) and tgt == pytest.approx(99.98 - (102.0 - 99.98))
    assert math.isnan(RX.flip_levels(1, -1, 99.98, 99.0, 99.5)[1])                  # a target at or behind the fill is no target
    inv, tgt = RX.flip_levels(1, -1, 99.98, float("nan"), float("nan"))
    assert math.isnan(inv) and math.isnan(tgt)
    inv, tgt = RX.flip_levels(-1, 1, 100.02, 101.0, 98.0)
    assert inv == pytest.approx(100.02 - abs(100.02 - 101.0)) and tgt == pytest.approx(100.02 + (98.0 - 100.02) * -1.0)


@SIDES
def test_f11_modes_a_keeps_the_picks_take_profit_and_b_the_strategys_native_target_beyond_the_fill(side):
    tgt = P0 + side * 900
    ea = run(acct("F11.a"), Path(), side, sigs=((C0, nsig(side, ["event"], [0], tgt=tgt)),))
    assert ea.position.tp_price == pytest.approx(P0 + side * 3 * R)                 # tp3R|2: the pick's own
    eb = run(acct("F11.b"), Path(), side, sigs=((C0, nsig(side, ["event"], [0], tgt=tgt)),))
    assert eb.position.tp_price == pytest.approx(tgt)
    for bad in (P0 - side * 50, P0 + side * 1, None):                               # behind the fill, at it (almost), or none
        eb = run(acct("F11.b"), Path(), side, sigs=((C0, nsig(side, ["event"], [0], tgt=bad)),))
        assert math.isnan(eb.position.tp_price)
    # the target is a maker limit: a minute that reaches it exits there at the maker fee; one that touches stop and target is the stop
    path = Path().bar(130, o=0, c=1000)
    eb = run(acct("F11.b"), path, side, sigs=((C0, nsig(side, ["event"], [0], tgt=tgt)),))
    assert eb.trades and eb.trades[0].exit_reason == "TP" and eb.trades[0].exit_price == pytest.approx(tgt)
    assert eb.trades[0].fees == pytest.approx(eb.trades[0].qty * eb.trades[0].entry_price * TAKER + eb.trades[0].qty * tgt * 0.0002)


@SIDES
def test_f12_records_every_component_that_fired_and_one_exit(side):
    a = acct("F12.b")
    assert a["rule"]["family"] == "F12" and (a["rule"]["w"], a["rule"]["n"], a["rule"]["H"], a["rule"]["N"]) == (3, 20, 8, 12)
    k = key_of(side)
    # F3 alone (the opposite flag), F11 alone (an event), and both at one check: one exit, the mask holds both bits
    opp = "sf" if side > 0 else "lf"
    for extra, want in (({opp: True}, RX.CB["F3"]), ({k: [1]}, RX.CB["F11"]), ({opp: True, k: [1]}, RX.CB["F3"] | RX.CB["F11"])):
        recs = [dict(nrec(chk(1), side, 0, lf=False, sf=False, atr=ATR, ema={"20": P0 + side * 0}, sl={"3": None}, sh={"3": None},
                          **{k: [0]}), **extra)]
        e = run(a, Path(), side, sigs=((C0, nsig(side, ["event"], [0])),), recs=recs)
        t = exits_at(e, J0 + 60)
        assert t.context["rx_comp"] == want, (extra, t.context.get("rx_comp"))
    # F7h at 8 hours alone ends a hold that nothing else ended: the first check at or after C0 + 8 h
    recs = [nrec(chk(h), side, 0, lf=False, sf=False, atr=ATR, ema={"20": None}, sl={"3": None}, sh={"3": None}, **{k: [0]})
            for h in range(1, 10)]
    e = run(a, Path(1200), side, sigs=((C0, nsig(side, ["event"], [0])),), recs=recs)
    t = exits_at(e, J0 + 480)
    assert t.context["rx_comp"] == RX.CB["F7h"]
    # a plain family writes no mask
    e = run(acct("F7.N2.a"), Path(), side, recs=[rec(chk(k_), side, 0) for k_ in (1, 2, 3)])
    assert "rx_comp" not in e.trades[0].context


def test_f11_and_f12_ids_and_the_study_ids():
    assert RX.native_ids() == ["F11.a", "F11.b", "F12.a", "F12.b"] and len(RX.study_ids()) + len(RX.native_ids()) == 86
    for i in RX.native_ids():
        r = RX.parse_rule(i)
        assert r["id"] == i and RX.parse_rule(r)["id"] == i and r["family"] in RX.NATIVE_FAMILIES
    assert RX.parse_rule("F12.a") == {"id": "F12.a", "family": "F12", "mode": "a", "q15": False, **RX.F12_PARAMS}
    assert "use_target" not in RX.parse_rule("F11.b")
    for bad in ("F11.a.q15", "F12.a.q15", "F12", "F11.c"):
        with pytest.raises(RX.RuleConfigError):
            RX.parse_rule(bad)
    assert RX.rule_needs(RX.parse_rule("F12.a")) == {"atr": True, "ema": [20], "sw": [3], "flags": True, "nat": True}
    assert RX.rule_needs(RX.parse_rule("F11.a"))["nat"] is True and RX.rule_needs(RX.parse_rule("F3.a"))["nat"] is False
    assert RX.rule_ko(RX.parse_rule("F12.b")) and RX.rule_ko(RX.parse_rule("F11.a"))
    # the pre-registered native bits are the kernel's
    sys.path.insert(0, os.path.join(ROOT, "research", "exitflex"))
    import kernel_x as KX
    assert RX.F12_PARAMS == KX.F12_PARAMS and RX.CB == {n: b for n, b in KX.COMP_NAMES}


def test_the_native_provider_is_checked_normalized_and_loaded_from_the_study_modules():
    saved = RX.NATIVE["provider"]
    try:
        RX.register_native(None)
        cfg = cfg_of("F11.a")
        cands = _rule_cands("15m")
        # no provider registered: the production one is loaded from research/exitflex (native.py, native_ds.py)
        try:
            prov = RX.native_provider()
        except RX.RuleConfigError as exc:
            pytest.skip(f"native exit modules not importable here: {exc}")
        assert callable(prov) and RX.native_hash() not in ("absent", "")
        assert RX.check(cands, cfg) == []
        n = 7
        ok = {"comp_long": [("state", np.array([1, 0, np.nan, 1, 0, 0, 1.0])), ("event", np.zeros(n, bool))], "comp_short": [],
              "lvl_long": np.full(n, 5.0), "lvl_short": None, "tgt_long": None, "tgt_short": None}
        nat = RX.normalize_native(ok, n)
        assert nat["kinds"] == {"l": ["state", "event"], "s": []} and [list(t) for t in nat["tri"]["l"]] == [[1, 0, 2, 1, 0, 0, 1], [0] * 7]
        assert np.isnan(nat["lvl"]["s"]).all() and (nat["lvl"]["l"] == 5.0).all()
        for bad in ({**ok, "comp_long": [("state", np.zeros(3))]}, {**ok, "comp_long": [("maybe", np.zeros(n))]},
                    {**ok, "comp_long": [("state", np.zeros(n))] * 7}, {**ok, "lvl_long": np.zeros(3)}):
            with pytest.raises(RX.RuleConfigError):
                RX.normalize_native(bad, n)
        a = RX.accounts(cands, cfg)[1]
        RX.register_native(lambda *args: ok)
        v = RN.fingerprint([a])
        assert RX.code_version(a["rule"]) == f"{RX.RULEX_VERSION}|{RX.native_hash()}" and len(v) == 64
        assert RX.code_version(RX.parse_rule("F3.a")) == str(RX.RULEX_VERSION)
    finally:
        RX.NATIVE["provider"] = saved


# ---------------------------------------------------------------- the config file and the accounts
def test_accounts_exist_only_with_an_enabled_config_and_follow_the_prereg(tmp_path):
    assert RX.load_config(str(tmp_path / "none.json")) is None
    assert RX.load_accounts(str(tmp_path / "none.json"), C.load()) is None
    cands = C.load()
    path = tmp_path / "rules.json"
    doc = {"pools": {"core": {"rule": "F7.N24.b", "label_ko": "24봉 시간 청산"}, "ds": None}}
    path.write_text(json.dumps(doc))                                               # a file alone starts nothing: it is not enabled
    assert RX.load_config(str(path))["enabled"] is False and RX.load_accounts(str(path), cands) is None
    path.write_text(json.dumps({**doc, "enabled": True}))
    accts = RX.load_accounts(str(path), cands)
    core, ds = [c for c in cands if c["kind"] == "core"], [c for c in cands if c["kind"] == "ds"]
    assert (len(core), len(ds)) == (23, 15) and len(accts) == 23 * 5 + 15 * 3 and len({a["id"] for a in accts}) == len(accts)
    assert all(C.ID_RE.match(a["id"]) for a in accts)
    by = {a["id"]: a for a in accts}
    pid = core[0]["id"]
    nq, n, flip, eq, e = (by[pid + s] for s in ("-nq", "-n", "-nflip", "-eq", "-e"))        # PREREG 11.2
    assert (nq["size"], n["size"], flip["size"], eq["size"], e["size"]) == (0.25, 1.0, 0.25, 0.25, 1.0)
    assert [x["role"] for x in (nq, n, flip, eq, e)] == [RX.ROLE_RULE, RX.ROLE_LIVE, RX.ROLE_FLIP, RX.ROLE_BASE, RX.ROLE_BASE_LIVE]
    assert nq["rule"]["id"] == "F7.N24.b" and n["rule"]["id"] == "F7.N24.b" and flip["rule"]["id"] == "F7.N24.b"
    assert eq["rule"]["family"] is None and e["rule"]["family"] is None and flip["of"] == nq["id"]
    assert all(x[k] == core[0][k] for x in (nq, n, flip, eq, e) for k in ("name", "tf", "combo", "exit"))
    assert nq["source"]["label_ko"] == "24봉 시간 청산" and "-f" not in "".join(a["id"] for a in accts if a["id"].endswith("-f"))
    # a pool with no new exit: its current exit only, with its own coin flip at live size
    did = ds[0]["id"]
    assert sorted(a["id"] for a in accts if a["pick"] == did) == sorted(did + s for s in ("-e", "-eq", "-eflip"))
    ef = by[did + "-eflip"]
    assert (ef["size"], ef["role"], ef["rule"]["family"], ef["of"]) == (1.0, RX.ROLE_FLIP, None, did + "-e")
    # both pools pass: 38 x 5; only DeepSeek passes: 15 x 5 + 23 x 3; the new exit may differ per pool
    both = RX.accounts(cands, RX.normalize_config({"pools": {"core": "F7.N24.b", "ds": "F5.P1.g50.a"}}))
    assert len(both) == 38 * 5 and {a["rule"]["id"] for a in both if a["kind"] == "ds" and a["role"] == RX.ROLE_RULE} == {"F5.P1.g50.a"}
    only_ds = RX.accounts(cands, RX.normalize_config({"pools": {"ds": "F9.a"}}))
    assert len(only_ds) == 15 * 5 + 23 * 3
    one = RX.accounts(cands, RX.normalize_config({"pools": {"core": "F1.w3.a"}, "picks": [pid]}))
    assert sorted(a["id"] for a in one) == sorted(pid + s for s in ("-n", "-nq", "-e", "-eq", "-nflip"))
    # no_entry_from_ms (the C1 script's output): only on the accounts of the new exit of that pool
    stop = 1_800_000_000_000
    cut = RX.accounts(cands, RX.normalize_config({"pools": {"core": "F1.w3.a", "ds": "F9.a"}, "no_entry_from_ms": {"ds": stop}}))
    assert {a["id"].rsplit("-", 1)[1] for a in cut if a.get("no_entry_from_ms")} == {"n", "nq", "nflip"}
    assert all(a["kind"] == "ds" and a["no_entry_from_ms"] == stop for a in cut if a.get("no_entry_from_ms"))
    assert RN.fingerprint(cut) != RN.fingerprint(RX.accounts(cands, RX.normalize_config({"pools": {"core": "F1.w3.a", "ds": "F9.a"}})))
    # refusals: a config that cannot be run says why
    for bad in ({"pools": {}}, {"pools": {"core": "F9.x"}}, {"pools": {"fx": "F9.a"}}, {"pools": {"core": "F2.n10.a.q15"}},
                {"pools": {"core": "F1.w3.a"}, "picks": ["nope"]}, {"pools": {"core": "F1.w3.a"}, "picks": 3},
                {"pools": {"core": "F1.w3.a"}, "enabled": "yes"}, {"pools": {"core": "F1.w3.a"}, "no_entry_from_ms": {"core": -5}},
                {"pools": {"core": "F1.w3.a"}, "no_entry_from_ms": {"x": 5}}, {"variants": ["F1.w3.a"]}, [1]):
        path.write_text(json.dumps(bad))
        with pytest.raises(RX.RuleConfigError):
            RX.load_config(str(path))
    path.write_text("not json")
    with pytest.raises(RX.RuleConfigError):
        RX.load_config(str(path))
    assert RX.rule_ko(RX.parse_rule("F5.P1.5.g25.a")) and RX.rule_ko(None) and RX.rule_ko(RX.parse_rule("F4.m2.b.q15"))


def test_the_command_line_checks_the_config(tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(rules_doc("F3.a"))
    assert RX.main(["check", "--rules", str(p)]) == 0 and "160 rule accounts" in capsys.readouterr().out
    assert RX.main(["check", "--rules", str(tmp_path / "none.json")]) == 0 and "no rule config" in capsys.readouterr().out
    p.write_text(json.dumps({"pools": {"core": "F3.a"}}))
    assert RX.main(["check", "--rules", str(p)]) == 0 and "not enabled" in capsys.readouterr().out
    p.write_text(rules_doc("F3.z"))
    assert RX.main(["check", "--rules", str(p)]) == 2
    assert RX.main(["ids"]) == 0 and capsys.readouterr().out.count("\n") == 82
    assert RX.main(["ids", "--all"]) == 0 and capsys.readouterr().out.count("\n") == 86


# ---------------------------------------------------------------- the league, end to end, on the shadow's synthetic bars
RULE = "F1.w2.a"


def _league(db, rule=RULE, tf="15m", exit_="tp1R|1", extra=(), start=START, cands=None, **kw):
    cands = cands or _rule_cands(tf, exit_)
    accts = list(extra) + RX.accounts(cands, cfg_of(rule))
    return RN.League(RN.open_db(str(db)), accts, TP.BRACKETS, TP.SPECS, LIB, PS.FrameSource(DATA),
                     TP._steps_from(DATA), TP.SYMS, start_ms=start, log=lambda s: None, **kw)


def _trades(lg, only=None):
    return [(a, json.loads(d)["entry_time"], json.loads(d)["exit_time"], json.loads(d)["exit_reason"],
             round(json.loads(d)["pnl"], 8)) for a, d in lg.conn.execute("SELECT account, data FROM trades ORDER BY account, exit_time, rowid")
            if only is None or a in only]


@pytest.fixture(scope="module")
def whole(tmp_path_factory):
    lg = _league(tmp_path_factory.mktemp("w") / "a.db", rule="F7.N2.a")
    lg.advance(START + 3 * DAY)
    return lg


def test_rule_exits_happen_in_the_league_and_the_twin_has_none(whole):
    rows = _trades(whole)
    by = {}
    for a, _e, _x, reason, _p in rows:
        by.setdefault(a, set()).add(reason)
    pid = "core-S2-15m-1"
    assert "RULE" in by[pid + "-nq"] and "RULE" in by[pid + "-n"] and "RULE" in by[pid + "-nflip"]
    assert "RULE" not in by.get(pid + "-eq", set()) and "RULE" not in by.get(pid + "-e", set())
    n = lambda a: sum(1 for r in rows if r[0] == a)  # noqa: E731
    assert n(pid + "-eq") > 0 and n(pid + "-nq") >= n(pid + "-eq") - 3                # leaving earlier frees the account
    # the rule accounts run at the sizes of the plan
    assert whole.engines[pid + "-nq"].s.tiers[0].margin_frac == pytest.approx(0.125) and whole.engines[pid + "-n"].s.tiers[0].margin_frac == 0.5
    t = next(json.loads(d) for a, d in whole.conn.execute("SELECT account, data FROM trades") if a == pid + "-nq")
    assert t["strategy_style"] == "rule:F7.N2.a"


def test_a_day_at_once_equals_five_minute_pieces_and_a_stop_equals_one_run(tmp_path, whole):
    many = _league(tmp_path / "b.db", rule="F7.N2.a")
    for t in range(START + RN.FIVE, START + 3 * DAY + 1, 11 * RN.FIVE):
        many.advance(t)
    many.advance(START + 3 * DAY)
    assert _trades(many) == _trades(whole) and len(_trades(whole)) > 20
    assert {a: e.wallet for a, e in many.engines.items()} == {a: e.wallet for a, e in whole.engines.items()}
    # a new process on the same database at awkward times, many times over
    lg = _league(tmp_path / "c.db", rule="F7.N2.a")
    t = START
    for step in (7, 3, 25, 1, 40, 13, 90, 5):
        t += step * RN.FIVE
        lg.advance(t)
        lg = _league(tmp_path / "c.db", rule="F7.N2.a")
        assert lg.done == t and lg.restore_notes == []
    lg.advance(START + 3 * DAY)
    assert _trades(lg) == _trades(whole)


def test_a_restore_in_the_middle_of_a_position_recomputes_its_state_from_the_bars(tmp_path):
    """F1 keeps a reference that moves with every swing: restart while a position is open, check the stored state equals
    the recomputation, then damage it and see the check correct it so that the later trades are the whole run's."""
    full = _league(tmp_path / "f.db")
    full.advance(START + 3 * DAY)
    want = _trades(full)
    assert any(r[3] == "RULE" for r in want)
    lg = _league(tmp_path / "g.db")
    held, t = None, START
    while t < START + 3 * DAY and held is None:
        t += 3 * RN.FIVE
        lg.advance(t)
        held = next((a for a in lg.rule_accts if lg.engines[a["id"]].position is not None and a["rule"]["family"]), None)
    assert held is not None
    aid = held["id"]
    rx = json.loads(json.dumps(lg.engines[aid].position.signal.meta["rx"]))
    again = _league(tmp_path / "g.db")
    assert again.restore_notes == [] and again.engines[aid].position.signal.meta["rx"] == rx
    # damage the stored reference and the extreme
    st = RN._get(lg.conn, "engines")
    meta = st[aid]["position"]["signal"]["meta"]["rx"]
    meta["ref"] = (meta["ref"] or 100.0) * 1.5
    meta["tx"] -= 7 * 3_600_000
    RN._put(lg.conn, "engines", st)
    lg.conn.commit()
    fixed = _league(tmp_path / "g.db")
    assert fixed.restore_notes and aid in fixed.restore_notes[0] and "ref" in fixed.restore_notes[0] and "tx" in fixed.restore_notes[0]
    got = fixed.engines[aid].position.signal.meta["rx"]
    assert got["ref"] == pytest.approx(rx["ref"]) and got["tx"] == rx["tx"] and got["x"] == pytest.approx(rx["x"])
    fixed.advance(START + 3 * DAY)
    assert _trades(fixed) == want
    assert any("고쳤" in n for n in fixed.meta.get("notes", [])) or fixed.restore_notes == []   # said once, in the next chunk's notes


def test_existing_accounts_are_unchanged_by_a_rule_league_next_to_them(tmp_path):
    cands = _rule_cands("15m", "tp1R|1")
    plain = C.accounts(cands)
    pure = RN.League(RN.open_db(str(tmp_path / "p.db")), plain, TP.BRACKETS, TP.SPECS, LIB, PS.FrameSource(DATA),
                     TP._steps_from(DATA), TP.SYMS, start_ms=START, log=lambda s: None)
    pure.advance(START + 2 * DAY)
    mixed = _league(tmp_path / "m.db", rule="F7.N2.a", extra=plain)
    mixed.advance(START + 2 * DAY)
    ids = {a["id"] for a in plain}
    assert _trades(pure) == _trades(mixed, ids) and len(_trades(pure)) > 5
    assert {a: pure.engines[a].wallet for a in ids} == {a: mixed.engines[a].wallet for a in ids}
    # and chunk_signals itself skips rule accounts, so a mixed list gives the plain accounts' signals only
    a1, _ = L.chunk_signals(LIB, PS.FrameSource(DATA), plain, TP.SYMS, START, START + DAY, START)
    a2, _ = L.chunk_signals(LIB, PS.FrameSource(DATA), mixed.accts, TP.SYMS, START, START + DAY, START)
    def flat(d):
        return sorted((c, aid, s.symbol, s.side, s.meta["stop_dist"]) for c, items in d.items() for aid, s in items)
    assert flat(a1) == flat(a2) and flat(a1)
    # the twin is the plain engine: replaying its own signals through candleague.exits.make_engine gives its trades
    by, _ = RX.chunk_rule(LIB, PS.FrameSource(DATA), mixed.rule_accts, TP.SYMS, START, START + 2 * DAY, START)
    twin = "core-S2-15m-1-eq"
    only = {c: [(aid, o) for aid, o in items if aid == twin and isinstance(o, Signal)] for c, items in by.items()}
    ref = X.make_engine("tp1R|1", TP.BRACKETS, TP.SPECS, book=twin, size=0.25)
    steps = TP._steps_from(DATA)(None, list(TP.SYMS), START, START + 2 * DAY)
    PS.replay_day({twin: ref}, set(), {c: v for c, v in only.items() if v}, steps, TP.BRACKETS)
    got = [(w[1], w[2], w[3], w[4]) for w in _trades(mixed, {twin})]
    assert got == [(t.entry_time, t.exit_time, t.exit_reason, round(t.pnl, 8)) for t in ref.trades] and got


def test_snapshots_of_the_rule_league(tmp_path, whole):
    doc = RN.write_snapshots(str(tmp_path / "snap"), whole, START + 3 * DAY + 60_000)
    rows = {r["id"]: r for r in doc["accounts"]}
    f = rows["core-S2-15m-1-nq"]
    assert f["rule"] == "F7.N2.a" and "시간 청산" in f["rule_ko"] and f["pick"] == "core-S2-15m-1" and f["size"] == 0.25
    assert f["exit_ko"] and rows["core-S2-15m-1-eq"]["rule"] == "E0" and "규칙 없음" in rows["core-S2-15m-1-eq"]["rule_ko"]
    book = json.load(open(tmp_path / "snap" / "trades.json"))
    assert any(t["exit_reason"] == "RULE" for t in book["core-S2-15m-1-nq"]["trades"])
    assert doc["judge"] == {}                                                    # the per-trade rule is for the cand accounts


# ---------------------------------------------------------------- a fresh start from the install time, the old database kept
def test_a_rule_league_starts_at_its_install_and_a_change_keeps_the_old_database(tmp_path):
    rules = tmp_path / "rules.json"
    NOW = START + 5 * 3_600_000 + 123_456
    main_db = tmp_path / "league.db"
    main = RN.League(RN.open_db(str(main_db)), C.accounts(_rule_cands("15m", "tp1R|1")), TP.BRACKETS, TP.SPECS, LIB,
                     PS.FrameSource(DATA), TP._steps_from(DATA), TP.SYMS, start_ms=START, log=lambda s: None, db_path=str(main_db))
    main.advance(START + DAY)
    before = _trades(main)
    args = dict(brackets=TP.BRACKETS, specs=TP.SPECS, lib=LIB, source=PS.FrameSource(DATA), fetch_steps=TP._steps_from(DATA),
                symbols=TP.SYMS, log=lambda s: None, clock=lambda: NOW)
    assert RN.make_rule_league(str(rules), _rule_cands("15m", "tp1R|1"), str(tmp_path / RX.DB_NAME), **args) is None
    assert not (tmp_path / RX.DB_NAME).exists()                                    # no config file: no rule league
    rules.write_text(rules_doc("F7.N2.a"))
    rl = RN.make_rule_league(str(rules), _rule_cands("15m", "tp1R|1"), str(tmp_path / RX.DB_NAME), **args)
    assert rl.reset and rl.start_ms == NOW // RN.FIVE * RN.FIVE and rl.done == rl.start_ms
    assert os.path.exists(tmp_path / "rule_league_start.json") and not list(tmp_path.glob("rule_league_from_*.db"))
    rl.advance(rl.start_ms + 2 * 3_600_000 * 12)
    rows = _trades(rl)
    assert rows and min(r[1] for r in rows) > rl.start_ms                          # nothing before the install
    # the rules change: the old database is copied next to it first, the league starts over from the same start
    rules.write_text(rules_doc("F7.N3.a"))
    rl2 = RN.make_rule_league(str(rules), _rule_cands("15m", "tp1R|1"), str(tmp_path / RX.DB_NAME), **args)
    assert rl2.reset and rl2.start_ms == rl.start_ms and _trades(rl2) == []
    copies = list(tmp_path.glob("rule_league_from_*.db"))
    assert len(copies) == 1
    c = sqlite3.connect(f"file:{copies[0]}?immutable=1", uri=True)
    assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == len(rows)
    c.close()
    # the main league's record and its own backup rule are untouched
    assert _trades(main) == before and not list(tmp_path.glob("league_from_*.db"))
    again = RN.make_rule_league(str(rules), _rule_cands("15m", "tp1R|1"), str(tmp_path / RX.DB_NAME), **args)
    assert not again.reset and again.start_ms == rl.start_ms                       # a plain restart continues
    # backup_if_reset for the install script works on the rule database too
    rules.write_text(rules_doc("F7.N4.a"))
    accts = RX.load_accounts(str(rules), _rule_cands("15m", "tp1R|1"))
    assert RN.plan_start(str(tmp_path / RX.DB_NAME), accts)[0] is True


def test_the_shared_fetch_asks_once_for_the_same_minutes():
    calls = []

    def fetch(rest, syms, s, e):
        calls.append((tuple(syms), s, e))
        return [(s, {}, {})]
    sf = RN.SharedFetch(fetch)
    sf.fresh(None, ["A", "B"], 1, 2)
    sf.reuse(None, ["A", "B"], 1, 2)
    sf.reuse(None, ["A"], 1, 2)                                   # another set of coins: asked again
    sf.fresh(None, ["A", "B"], 1, 2)                               # the main league always asks Binance
    assert calls == [(("A", "B"), 1, 2), (("A",), 1, 2), (("A", "B"), 1, 2)]


# ---------------------------------------------------------------- the service loop: both leagues, one failing never stops the other
def _main_env(monkeypatch, tmp_path, cands, now_ms):
    import paperbot.binance as BN

    class NoRest:
        def __init__(self, *a, **k):
            pass
    monkeypatch.setattr(BN, "BinanceREST", NoRest)
    monkeypatch.setattr(PS, "RestSource", lambda path, rest=None: PS.FrameSource(DATA))
    monkeypatch.setattr(PS, "make_fetcher", lambda rest, syms, s, e: TP._steps_from(DATA))
    monkeypatch.setattr(RN.C, "load", lambda path=None: cands)
    monkeypatch.setattr(RN, "load_exchange", lambda path, syms: (TP.BRACKETS, TP.SPECS, "test"))
    monkeypatch.setattr(sweepsig, "lib", lambda: LIB)
    import paperbot.config as PC
    monkeypatch.setattr(PC, "V3_SYMBOLS", TP.SYMS)
    real = RN.time
    clock = types.SimpleNamespace(time=lambda: now_ms / 1000, monotonic=real.monotonic, strftime=real.strftime,
                                  gmtime=real.gmtime, sleep=lambda s: None)
    monkeypatch.setattr(RN, "time", clock)
    for k in ("CANDLEAGUE_START", "CANDLEAGUE_RULES", "CANDLEAGUE_RULE_DB", "CANDLEAGUE_RULE_SNAP", "CANDLEAGUE_RULE_START"):
        monkeypatch.delenv(k, raising=False)


def test_the_service_runs_the_rule_league_next_to_the_main_one(tmp_path, monkeypatch, capsys):
    cands = _rule_cands("15m", "tp1R|1")
    NOW = START + 2 * DAY + 600_000 + 95_000
    _main_env(monkeypatch, tmp_path, cands, NOW)
    db, snap, rules = tmp_path / "league.db", tmp_path / "snap", tmp_path / "rules.json"
    iso = "2026-10-05T00:00Z"
    args = ["once", "--db", str(db), "--snap", str(snap), "--start", iso, "--rule-start", iso, "--rules", str(rules)]
    # no rule config: the main league alone, no rule database, no rule snapshot
    assert RN.main(args) == 0
    main_doc = json.load(open(snap / "league.json"))
    assert not (tmp_path / RX.DB_NAME).exists() and not (snap / "rule").exists() and main_doc["done_ms"] == START + 2 * DAY + 600_000
    only = _trades_of(db)
    # a config file: the rule league appears, with its own database, start file and snapshots
    rules.write_text(rules_doc("F7.N2.a"))
    assert RN.main(args) == 0
    assert (tmp_path / RX.DB_NAME).exists() and (tmp_path / "rule_league_start.json").exists()
    rdoc = json.load(open(snap / "rule" / "league.json"))
    assert rdoc["start_ms"] == START and rdoc["done_ms"] == main_doc["done_ms"] and len(rdoc["accounts"]) == 5
    assert any(t["exit_reason"] == "RULE" for t in json.load(open(snap / "rule" / "trades.json"))["core-S2-15m-1-nq"]["trades"])
    assert json.load(open(snap / "league.json"))["accounts"] == main_doc["accounts"]          # the main league did not move
    assert _trades_of(db) == only
    # a config that cannot be run never stops the main league
    rules.write_text(rules_doc("F2.n10.a.q15"))
    assert RN.main(args) == 0
    out = capsys.readouterr().out
    assert "규칙 리그를 열지 못했습니다" in out and _trades_of(db) == only
    # a rule league that fails in a pass is reopened from its database and the main league goes on
    rules.write_text(rules_doc("F7.N2.a"))
    boom = {"n": 0}
    orig = RX.chunk_rule

    def flaky(*a, **k):
        boom["n"] += 1
        raise RuntimeError("boom")
    monkeypatch.setattr(RX, "chunk_rule", flaky)
    later = START + 2 * DAY + 1_200_000 + 95_000                                 # ten minutes on
    monkeypatch.setattr(RN, "time", types.SimpleNamespace(time=lambda: later / 1000, monotonic=RN.time.monotonic,
                                                          strftime=RN.time.strftime, gmtime=RN.time.gmtime,
                                                          sleep=lambda s: None))
    assert RN.main(args) == 0
    out = capsys.readouterr().out
    assert boom["n"] >= 1 and "규칙 리그 처리 실패" in out
    assert json.load(open(snap / "league.json"))["done_ms"] == START + 2 * DAY + 1_200_000      # the main league moved on
    monkeypatch.setattr(RX, "chunk_rule", orig)


def _trades_of(db):
    c = sqlite3.connect(str(db))
    try:
        return c.execute("SELECT account, exit_time, data FROM trades ORDER BY account, exit_time, rowid").fetchall()
    finally:
        c.close()


def test_the_backup_command_copies_the_rule_database_before_a_change(tmp_path, monkeypatch, capsys):
    cands = _rule_cands("15m", "tp1R|1")
    _main_env(monkeypatch, tmp_path, cands, START + DAY)
    db, rules = tmp_path / "league.db", tmp_path / "rules.json"
    rules.write_text(rules_doc("F7.N2.a"))
    rl = RN.make_rule_league(str(rules), cands, str(tmp_path / RX.DB_NAME), TP.BRACKETS, TP.SPECS, LIB, PS.FrameSource(DATA),
                             TP._steps_from(DATA), TP.SYMS, log=lambda s: None, clock=lambda: START)
    rl.advance(START + 6 * 3_600_000)
    RN.open_db(str(db)).close()
    capsys.readouterr()
    assert RN.main(["backup", "--db", str(db), "--rules", str(rules)]) == 0
    assert "규칙 리그: 기록 복사 필요 없음" in capsys.readouterr().out and not list(tmp_path.glob("rule_league_from_*.db"))
    rules.write_text(rules_doc("F7.N3.a"))                        # the install changes the rules
    assert RN.main(["backup", "--db", str(db), "--rules", str(rules)]) == 0
    out = capsys.readouterr().out
    assert "규칙 리그: 새로 시작하기 전 기록 복사" in out and len(list(tmp_path.glob("rule_league_from_*.db"))) == 1
    assert RN.main(["backup", "--db", str(db), "--rules", str(rules)]) == 0          # a second run finds its copy
    assert "이미 복사해 두었습니다" in capsys.readouterr().out


def test_q15_on_a_1h_pick_in_the_league_checks_on_15m_closes_and_survives_restarts(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "Strategies", StubStrategies)
    cands = _rule_cands("1h", "tp1R|1")
    mk = lambda db: _league(db, rule="F1.w2.b.q15", tf="1h", exit_="tp1R|1", cands=cands)  # noqa: E731
    full = mk(tmp_path / "f.db")
    full.advance(START + 3 * DAY)
    rows = _trades(full)
    pid = "core-S2-1h-1-nq"
    rule_exits = [r for r in rows if r[0] == pid and r[3] == "RULE"]
    assert len(rows) > 20 and rule_exits
    off_hour = [r for r in rule_exits if (r[2] // 60_000) % 60 != 0]
    assert off_hour, "a 15m check never acted between two hourly closes"                  # the q15 schedule is in use
    base = _league(tmp_path / "b.db", rule="F1.w2.a", tf="1h", exit_="tp1R|1", cands=cands)
    base.advance(START + 3 * DAY)
    assert all((r[2] // 60_000) % 60 == 0 for r in _trades(base) if r[3] == "RULE")        # the base variant: hourly only
    lg, t = mk(tmp_path / "g.db"), START
    for step in (7, 3, 25, 1, 40, 13, 90, 5, 61, 2, 150):
        t += step * RN.FIVE
        lg.advance(t)
        lg = mk(tmp_path / "g.db")
        assert lg.restore_notes == [], (t, lg.restore_notes)
    lg.advance(START + 3 * DAY)
    assert _trades(lg) == rows
    # restarts right on 15m closes, with a position held: the check of that close is still waiting in the queue
    lg, t, queued = mk(tmp_path / "h.db"), START + 72 * RN.FIVE, 0
    lg.advance(t)
    for _ in range(200):
        t += 3 * RN.FIVE
        lg.advance(t)
        lg = mk(tmp_path / "h.db")
        assert lg.restore_notes == []
        queued += sum(1 for x in lg.rule_accts if lg.engines[x["id"]].position is not None
                      and lg.engines[x["id"]].position.signal.meta["rx"]["q"])
        if queued >= 3:
            break
    assert queued >= 3
    lg.advance(START + 3 * DAY)
    assert _trades(lg) == rows


def test_a_chunk_without_a_pick_close_still_gets_its_15m_records(monkeypatch):
    """The live pass is 5 minutes long: most chunks hold no hourly close, and q15 needs the 15m ones all the same."""
    cfg = cfg_of("F1.w3.a.q15")
    accts = [a for a in RX.accounts(_rule_cands("1h"), cfg) if a["id"].endswith("-nq")]
    lo, hi = START + 3 * HOUR + 5 * MIN, START + 3 * HOUR + 20 * MIN                  # one 15m close (03:15), no hourly one
    by, _ = RX.chunk_rule(LIB, PS.FrameSource(DATA), accts, TP.SYMS, lo, hi, START, StubStrategies())
    recs = [(c, o.d["k"], o.d["sym"]) for c, items in by.items() for _a, o in items if isinstance(o, RX.RuleClose)]
    assert sorted(recs) == sorted((START + 3 * HOUR + 15 * MIN, "q", s) for s in TP.SYMS)
    # a chunk with neither gives nothing, and the base variant gets no 15m record
    by, _ = RX.chunk_rule(LIB, PS.FrameSource(DATA), accts, TP.SYMS, lo, lo + 5 * MIN, START, StubStrategies())
    assert not by
    base = [a for a in RX.accounts(_rule_cands("1h"), cfg_of("F1.w3.a")) if a["id"].endswith("-nq")]
    by, _ = RX.chunk_rule(LIB, PS.FrameSource(DATA), base, TP.SYMS, lo, hi, START, StubStrategies())
    assert not by


def test_five_minute_pieces_equal_one_run_for_q15(tmp_path, monkeypatch):
    """The service's own pass is 5 minutes: around a 15m-check exit, pieces of 5 minutes give the run of one chunk."""
    monkeypatch.setattr(L, "Strategies", StubStrategies)
    cands = _rule_cands("1h", "tp1R|1")
    mk = lambda db: _league(db, rule="F1.w2.b.q15", tf="1h", exit_="tp1R|1", cands=cands)  # noqa: E731
    scout = mk(tmp_path / "s.db")
    scout.advance(START + 3 * DAY)
    first = min(r[2] for r in _trades(scout) if r[0] == "core-S2-1h-1-nq" and r[3] == "RULE" and (r[2] // MIN) % 60 != 0)
    a = (first - 4 * HOUR) // RN.FIVE * RN.FIVE                                       # four hours before it
    whole, pieces = mk(tmp_path / "w.db"), mk(tmp_path / "p.db")
    whole.advance(a)
    pieces.advance(a)
    whole.advance(a + 6 * HOUR)
    for t in range(a + RN.FIVE, a + 6 * HOUR + 1, RN.FIVE):
        pieces.advance(t)
    assert _trades(pieces) == _trades(whole) and any(r[2] == first for r in _trades(whole))
    assert RN._get(pieces.conn, "engines") == RN._get(whole.conn, "engines")
