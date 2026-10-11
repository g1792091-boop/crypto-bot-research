"""research/altpump (PREREG_ALTPUMP.md section 18) on synthetic data only. No real market data is read anywhere here.

- fixed lists: 191 exclusions in their groups, 14 renames, 28 variants with section 5's ids, caps of section 7;
- worst-order fills on daily bars (6.7): a gap through the stop fills at the open, a gap beyond liquidation loses the
  margin, a bar reaching an add level and the stop fills every reached add first and exits at the moved stop (long and
  short; a second reached add too), a bar reaching no add level stops at once; the stop-fill haircut (a touched stop
  fills f of the way to the bar's extreme; a fill beyond liquidation liquidates; buy-stop adds mirror it);
- no look-ahead: changing every value of day d+1 onward (the fill open aside) leaves every day-d signal, indicator and
  the entry's size unchanged;
- lives: listing day 0 (P3 K1 / K7), archive-start lives, rename successors (within / beyond 60 days), relisting after
  30 days without a bar, a 7..29-day pause ends a life (the restart is no listing), delisting closes at the last
  bar's close, a position closes at the close before a day without a bar inside a life, partial days (archive holes)
  are not ranked by P4, zero-volume padding is no bar; no 1- or 7-day return and no TR reads across a gap;
- the volume floor point in time (a later spike does not make an earlier day tradable), the stable filter;
- the pyramiding stop formula (P0, P0 + 0.667 D0, P0 + 1.25 D0 with full units), leverage choice and the 1.5x rule,
  risk cap, n_max, liquidity cut, D0 cap, lapse, period end, hold exit, chandelier, funding (the exit day included);
- bootstrap p (size under a skewed null), rank p and BH on known inputs; selection (groups, K, none eligible);
  controls (a) and (b): (b) moves the whole signal calendar by common offsets (same-day signals of different symbols
  stay together, the pick's count is kept), a zero-edge pick clustered within or across symbols is not favoured and
  the control opens as many positions; the positions validity check; the squeeze stress read;
- goal-board arithmetic: fresh $1,000 months, thresholds, bust; adds and add skips on every board row; the luck
  reference (random days, the pick's side) beside the coin flip;
- values outside a step's window are never loaded (select unchanged when they change);
- pin refusals (the running code must be the pinned code; the data file must be the PREREG's), run-once guards
  (test, board, pass2 outputs pinned when written; a rerun needs a DEVIATIONS entry naming the old sha256; pass2
  needs a pinned test.json; --accept-missing needs each missing month listed); the second pass (5m slots in time
  order, mark-price liquidation, funding events and the fixed fallback, a day without 5m data runs on the daily bar,
  file converters);
- the whole select -> test -> board pipeline on a small synthetic universe.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import zipfile

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.altpump import altpump as AP  # noqa: E402

DAY = AP.DAY_MS
BASE = "2021-01-01"
G0 = AP.gday(BASE)
NOEX = frozenset()
TAKER, SLIP, F8 = AP.COSTS["base"]


# ------------------------------------------------------------------ helpers
def frame(bars: dict) -> pd.DataFrame:
    """bars: symbol -> list of (day offset from BASE, open, high, low, close, quote volume); volume 0 = padding."""
    rows = []
    for sym, bl in bars.items():
        for d, o, h, l, c, qv in bl:
            rows.append((sym, (G0 + d) * DAY, o, h, l, c, (qv / c if qv > 0 else 0.0), qv))
    return pd.DataFrame(rows, columns=["symbol", "open_time", "open", "high", "low", "close", "volume",
                                       "quote_volume"])


def flat(d0: int, d1: int, px: float = 100.0, rng: float = 1.0, qv: float = 1e9) -> list:
    """Days d0..d1-1 of a flat bar: o = c = px, h = px + rng, l = px - rng (TR = 2 rng)."""
    return [(d, px, px + rng, px - rng, px, qv) for d in range(d0, d1)]


def market(bars: dict, start_off: int, end_off: int, warmup: int = 60, excluded=NOEX) -> AP.Market:
    raw = AP.Raw(frame(bars))
    return AP.Market(raw, AP.day_str(G0 + start_off), AP.day_str(G0 + end_off), excluded=excluded, warmup=warmup)


def local(mk: AP.Market, off: int) -> int:
    return G0 + off - mk.w0g


def sig(mk, items) -> AP.Sig:
    """items: (day offset, symbol, side)."""
    ix = {s: i for i, s in enumerate(mk.syms)}
    d = np.asarray([local(mk, a) for a, _, _ in items], np.int64)
    s = np.asarray([ix[b] for _, b, _ in items], np.int64)
    sd = np.asarray([c for _, _, c in items], np.int64)
    o = mk.order(d, s)
    return AP.Sig(d[o], s[o], sd[o])


VM = {"id": "TEST_M", "exit": "M", "hold": 0, "side": 1}
VH = {"id": "TEST_H", "exit": "H", "hold": 7, "side": 1}


def one_pos(bars, after, side=1, v=VM, r=0.02, end_off=None, **kw):
    """A flat history (days 0..39, ATR = 2 at 100) then ``after`` (list of (o, h, l, c) from day 40 on); one signal on
    day 39 for symbol AAAUSDT (entry at day 40's open = 100, D0 = 4)."""
    b = flat(0, 40)
    for i, (o, h, l, c) in enumerate(after):
        b.append((40 + i, o, h, l, c, 1e9))
    bars = dict(bars or {})
    bars["AAAUSDT"] = b
    end = end_off or (40 + len(after))
    mk = market(bars, 30, end)
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", side)]), v, r=r, **kw)
    return mk, out


# ------------------------------------------------------------------ fixed lists
def test_fixed_lists():
    assert (len(AP.EXCL_INDEX), len(AP.EXCL_STABLE), len(AP.EXCL_COMMOD), len(AP.EXCL_ETF), len(AP.EXCL_US),
            len(AP.EXCL_ASIA), len(AP.EXCL_PREIPO), len(AP.EXCL_BATCH)) == (6, 1, 10, 31, 103, 17, 6, 17)
    assert len(AP.EXCLUDED) == 191 and len(AP.TRADFI) == 184
    assert len(AP.RENAMES) == 14
    ids = [v["id"] for v in AP.VARIANTS]
    assert len(ids) == len(set(ids)) == 28
    fam = {f: sum(v["family"] == f for v in AP.VARIANTS) for f in ("P1", "P2", "P3", "P4")}
    assert fam == {"P1": 6, "P2": 6, "P3": 8, "P4": 8}
    want = ([f"P1_X{x}_{e}" for x in (20, 30, 50) for e in ("M", "H7")]
            + [f"P2_X{x}_{e}" for x in (20, 30, 50) for e in ("M", "H7")]
            + [f"P3{s}_K{k}_{e}" for s in "LS" for k in (1, 7) for e in ("M", "H28")]
            + [f"P4{s}_N{n}_{e}" for s in "LS" for n in (5, 10) for e in ("M", "H28")])
    assert ids == want
    assert {v["group"] for v in AP.VARIANTS} == {"P1", "P2", "P3L", "P3S", "P4L", "P4S"}
    assert AP.caps(0.005) == (6, 0.02) and AP.caps(0.02) == (6, 0.08)
    assert AP.caps(0.05) == (4, pytest.approx(0.20)) and AP.caps(0.10) == (4, pytest.approx(0.40))
    assert AP.caps(0.20) == (3, pytest.approx(0.60))
    assert all(v["hold"] == (7 if v["family"] in ("P1", "P2") else 28) for v in AP.VARIANTS if v["exit"] == "H")


# ------------------------------------------------------------------ 6.7 worst order (daily)
def _rec(out, i=0):
    rf, ri = out.rf[i], out.ri[i]
    return rf, ri


def test_entry_sizing_and_leverage():
    mk, out = one_pos({}, [(100, 100.5, 99.5, 100)] * 3)
    rf, ri = _rec(out)
    # U = 2% of 1000 = 20, D0 = 2 x ATR(2) = 4 -> q = 5; N4 = 2000 > B x 10 -> fallback L = largest with 1/L - 5% >= 6%
    assert rf[AP.R_U] == pytest.approx(20.0)
    assert rf[AP.R_RISK1] == pytest.approx(1.0)
    assert rf[AP.R_LEV] == 9
    assert rf[AP.R_D0F] == pytest.approx(0.04)
    assert rf[AP.R_P0] == 100.0
    assert ri[AP.RI_REASON] == AP.EX_PEND
    assert rf[AP.R_XPX] == 100.0                                     # period end: marked at the close, no costs


def test_gap_through_stop_fills_at_open_long_and_short():
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (95, 95.5, 94.5, 95)])
    rf, ri = _rec(out)
    assert ri[AP.RI_REASON] == AP.EX_GAP and rf[AP.R_XPX] == pytest.approx(95 * (1 - SLIP))
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (105, 105.5, 104.5, 105)], side=-1)
    rf, ri = _rec(out)
    assert ri[AP.RI_REASON] == AP.EX_GAP and rf[AP.R_XPX] == pytest.approx(105 * (1 + SLIP))


def test_gap_beyond_liquidation_loses_the_margin():
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (80, 80.5, 79.5, 80)])
    rf, ri = _rec(out)
    margin = 5 * 100 * (1 + SLIP) / 9
    assert ri[AP.RI_REASON] == AP.EX_LIQ
    assert rf[AP.R_PRICE] == pytest.approx(-margin)


def test_add_before_stop_in_the_same_bar():
    # 6.7 rule 3 (second review): a bar that reaches both the next add level and the stop fills the add first, moves
    # the stop to S_req and exits there with the haircut (the worse order, as PREREG_HUNT 7.6 step 4). Long: P0 100,
    # D0 4, stop 96, add level 104; the bar runs 95.5 .. 105
    f = AP.STOP_HC
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 105, 95.5, 100)])
    rf, ri = _rec(out)
    ref = 104 + f * (105 - 104)
    sreq = (5 * 100 + 5 * ref - 20) / 10
    assert ri[AP.RI_REASON] == AP.EX_STOP and ri[AP.RI_ADDS] == 1 and ri[AP.RI_TRIED] == 1
    assert ri[AP.RI_SRC] == AP.SRC_ADD
    assert rf[AP.R_XPX] == pytest.approx((sreq - f * (sreq - 95.5)) * (1 - SLIP))
    # short mirror: stop 104, add level 96; the bar runs 95 .. 104.5
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 104.5, 95, 100)], side=-1)
    rf, ri = _rec(out)
    ref = 96 - f * (96 - 95)
    sreq = (5 * 100 + 5 * ref + 20) / 10
    assert ri[AP.RI_REASON] == AP.EX_STOP and ri[AP.RI_ADDS] == 1
    assert rf[AP.R_XPX] == pytest.approx((sreq + f * (104.5 - sreq)) * (1 + SLIP))
    # the add-first order never loses less than the stop-first one: compare with a bar that reaches the stop only
    _, stop_only = one_pos({}, [(100, 100.5, 99.5, 100), (100, 103.9, 95.5, 100)])
    _, both = one_pos({}, [(100, 100.5, 99.5, 100), (100, 105, 95.5, 100)])
    assert stop_only.ri[0, AP.RI_ADDS] == 0 and both.rf[0, AP.R_PNL] < stop_only.rf[0, AP.R_PNL]
    for f0 in (0.0, 0.5):                                             # f = 0: only the extra costs; f > 0: more
        _, a = one_pos({}, [(100, 100.5, 99.5, 100), (100, 103.9, 95.5, 100)], stop_hc=f0)
        _, b = one_pos({}, [(100, 100.5, 99.5, 100), (100, 105, 95.5, 100)], stop_hc=f0)
        assert b.ri[0, AP.RI_ADDS] == 1 and b.rf[0, AP.R_PNL] < a.rf[0, AP.R_PNL]
    # a bar that reaches the stop and no add level: the stop at once, no add tried
    rf, ri = _rec(stop_only)
    assert ri[AP.RI_REASON] == AP.EX_STOP and ri[AP.RI_TRIED] == 0
    assert rf[AP.R_XPX] == pytest.approx((96 - f * (96 - 95.5)) * (1 - SLIP))


def test_every_reached_add_fills_before_the_moved_stop_exit():
    # 6.7 rule 3, case B: after add 1 fills, the bar also reaches add level 2; both fill before the stop is checked
    # (the draft exited after add 1). r = 0.5% leaves margin for the adds: q = 1.25, D0 = 4, levels 104 then ref1 + 4
    f = AP.STOP_HC
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 112, 99, 100)], r=0.005)
    rf, ri = _rec(out)
    ref1 = 104 + f * (112 - 104)
    ref2 = (ref1 + 4) + f * (112 - (ref1 + 4))
    assert ref1 + 4 <= 112 < ref2 + 4                                 # level 2 reached, level 3 not
    sreq = (100 + ref1 + ref2 - 4) / 3                                # (sum q ref - U) / sum q, U = q D0
    assert ri[AP.RI_ADDS] == 2 and ri[AP.RI_TRIED] == 2 and ri[AP.RI_REASON] == AP.EX_STOP
    assert rf[AP.R_XPX] == pytest.approx((sreq - f * (sreq - 99)) * (1 - SLIP))
    # worse than the draft's exit after add 1 at its moved stop (101 at f = 0.25: (100 + 106 - 4) / 2)
    s1 = (100 + ref1 - 4) / 2
    draft_price = 1.25 * ((s1 - f * (s1 - 99)) * (1 - SLIP) * 2 - 100 * (1 + SLIP) - ref1 * (1 + SLIP))
    assert rf[AP.R_PRICE] < draft_price
    # short mirror: the bar runs 88 .. 101; levels 96 and ref1 - 4
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 101, 88, 100)], side=-1, r=0.005)
    rf, ri = _rec(out)
    ref1 = 96 - f * (96 - 88)
    ref2 = (ref1 - 4) - f * ((ref1 - 4) - 88)
    sreq = (100 + ref1 + ref2 + 4) / 3
    assert ri[AP.RI_ADDS] == 2 and ri[AP.RI_REASON] == AP.EX_STOP
    assert rf[AP.R_XPX] == pytest.approx((sreq + f * (101 - sreq)) * (1 + SLIP))


def test_add_then_moved_stop_exit_same_day():
    # f = 0: add 1 at 104 (full unit) moves the stop to P0 = 100; the day's low 99.9 reaches it -> exit at 100
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 104.5, 99.9, 102)], stop_hc=0.0)
    rf, ri = _rec(out)
    assert ri[AP.RI_ADDS] == 1 and ri[AP.RI_REASON] == AP.EX_STOP and ri[AP.RI_SRC] == AP.SRC_ADD
    assert rf[AP.R_XPX] == pytest.approx(100 * (1 - SLIP))
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 100.1, 95.5, 98)], side=-1, stop_hc=0.0)
    rf, ri = _rec(out)
    assert ri[AP.RI_ADDS] == 1 and ri[AP.RI_REASON] == AP.EX_STOP
    assert rf[AP.R_XPX] == pytest.approx(100 * (1 + SLIP))
    # f = 0.25: the add fills at 104 + f x (104.5 - 104); the moved stop S_req = (5 x 100 + 5 x ref - 20) / 10; the
    # exit fills f of the way from that stop to the low 99.9
    f = 0.25
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 104.5, 99.9, 102)], stop_hc=f)
    rf, ri = _rec(out)
    ref = 104 + f * 0.5
    sreq = (500 + 5 * ref - 20) / 10
    assert ri[AP.RI_ADDS] == 1 and ri[AP.RI_REASON] == AP.EX_STOP
    assert rf[AP.R_XPX] == pytest.approx((sreq - f * (sreq - 99.9)) * (1 - SLIP))


def test_add_fills_at_gapped_open_and_next_level_from_it():
    # open 106 is beyond add level 104: add 1 fills at the open (ref 106); next level = 106 + 4 = 110
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (106, 109, 105.5, 108), (108, 110.5, 107, 110)])
    rf, ri = _rec(out)
    assert ri[AP.RI_ADDS] == 2 and ri[AP.RI_TRIED] == 2


def test_pyramiding_stop_formula_full_units():
    for side in (1, -1):
        ps = np.zeros((1, AP.NF))
        pi = np.zeros((1, AP.NPI), np.int64)
        P0, D0, q = 100.0, 4.0, 5.0
        U = q * D0
        pi[0, AP.P_SIDE] = side
        ps[0, AP.F_Q] = ps[0, AP.F_Q1] = q
        ps[0, AP.F_COST] = q * P0
        ps[0, AP.F_REFQ] = q * P0
        ps[0, AP.F_U] = U
        ps[0, AP.F_D0] = D0
        ps[0, AP.F_STOP] = P0 - side * D0
        ps[0, AP.F_LEV] = 1.0
        ps[0, AP.F_B] = 1e12
        ps[0, AP.F_MED7] = 1e15
        ps[0, AP.F_MARGIN] = q * P0
        acc = np.array([1e9, q * P0, 0.0, 0.0])
        cnt = np.zeros(AP.NCNT, np.int64)
        stops = []
        for n in (1, 2, 3):
            ok = AP._try_add(0, P0 + side * n * D0, ps, pi, acc, 0.0, 1e12, 0.0, 0.0, 0.0, 1.0, cnt,
                             AP.BR_CAP, np.zeros(4))
            assert ok
            stops.append(ps[0, AP.F_STOP])
            risk = side * (ps[0, AP.F_REFQ] - ps[0, AP.F_Q] * ps[0, AP.F_STOP])
            assert risk == pytest.approx(U)                          # open risk held at one unit
        want = [P0, P0 + side * 2 / 3 * D0, P0 + side * 1.25 * D0]
        assert stops == pytest.approx(want)


def test_add_skipped_when_liquidation_not_beyond_moved_stop():
    ps = np.zeros((1, AP.NF))
    pi = np.zeros((1, AP.NPI), np.int64)
    pi[0, AP.P_SIDE] = 1
    ps[0, AP.F_Q] = ps[0, AP.F_Q1] = 5.0
    ps[0, AP.F_COST] = ps[0, AP.F_REFQ] = 500.0
    ps[0, AP.F_U], ps[0, AP.F_D0], ps[0, AP.F_STOP] = 20.0, 4.0, 96.0
    ps[0, AP.F_LEV], ps[0, AP.F_B], ps[0, AP.F_MED7] = 10.0, 1e9, 1e15
    acc = np.array([1e9, 50.0, 0.0, 0.0])
    cnt = np.zeros(AP.NCNT, np.int64)
    # at 10x with mmr 5% the liquidation (avg x 0.95 = 96.9) lies above the moved stop P0 = 100? no: 96.9 < 100 -> ok
    assert AP._try_add(0, 104.0, ps, pi, acc, 0.0, 1e9, 0.0, 0.0, 0.0, 1.0, cnt, AP.BR_CAP, AP.BR_MMR)
    # a mmr of 9% at 10x puts liquidation at avg x 0.99 > the moved stop -> skipped and counted
    ps2 = ps.copy()
    ps2[0, AP.F_Q] = ps2[0, AP.F_Q1] = 5.0
    ps2[0, AP.F_COST] = ps2[0, AP.F_REFQ] = 500.0
    ps2[0, AP.F_STOP] = 96.0
    pi2 = np.zeros((1, AP.NPI), np.int64)
    pi2[0, AP.P_SIDE] = 1
    assert not AP._try_add(0, 104.0, ps2, pi2, acc, 0.0, 1e9, 0.0, 0.0, 0.0, 1.0, cnt, AP.BR_CAP, np.full(4, 0.09))
    assert cnt[AP.A_LIQBEYOND] == 1


def test_choose_leverage_and_liquidation_distance():
    # (iii): 1/L - 5% >= 1.5 x 4% -> L <= 9; (ii) N4 / L <= B: N4 = 2000, B = 500 -> L >= 4
    assert AP._choose_lev(2000.0, 500.0, 0.04, 10, 1.5, AP.BR_CAP, AP.BR_LEV, AP.BR_MMR) == 4
    # (ii) impossible -> the largest L meeting (i) and (iii)
    assert AP._choose_lev(2000.0, 100.0, 0.04, 10, 1.5, AP.BR_CAP, AP.BR_LEV, AP.BR_MMR) == 9
    # bracket (i): N4 = 50,000 -> 5x max, mmr 10%
    assert AP._choose_lev(50_000.0, 1e9, 0.01, 10, 1.5, AP.BR_CAP, AP.BR_LEV, AP.BR_MMR) == 1
    assert AP._choose_lev(50_000.0, 10_000.0, 0.01, 10, 1.5, AP.BR_CAP, AP.BR_LEV, AP.BR_MMR) == 5
    # the D0 cap at 50% always leaves L = 1 (1 - 25% >= 1.5 x 50%)
    assert AP._choose_lev(1e7, 1.0, 0.5, 10, 1.5, AP.BR_CAP, AP.BR_LEV, AP.BR_MMR) == 1
    for L in range(1, 11):
        for d0f in (0.01, 0.05, 0.1, 0.3, 0.5):
            Lc = AP._choose_lev(1000.0, 1.0, d0f, 10, 1.5, AP.BR_CAP, AP.BR_LEV, AP.BR_MMR)
            liq = AP._liq_price(1, 1.0, Lc, 0.05)
            assert 1.0 - liq >= 1.5 * d0f - 1e-12
    assert AP._liq_price(1, 100.0, 10, 0.05) == pytest.approx(95.0)
    assert AP._liq_price(-1, 100.0, 10, 0.05) == pytest.approx(105.0)


def test_d0_cap_at_half_the_price():
    b = [(d, 100, 150, 60, 100, 1e9) for d in range(0, 40)]          # TR 90 -> 2 x ATR = 180 > 50
    b += [(40, 100, 100.5, 99.5, 100, 1e9), (41, 100, 100.5, 99.5, 100, 1e9)]
    mk = market({"AAAUSDT": b}, 30, 42)
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM)
    assert out.rf[0, AP.R_D0F] == pytest.approx(0.5) and out.ri[0, AP.RI_D0CAP] == 1
    assert out.cnt[AP.C_D0CAP] == 1


def test_lapse_when_no_bar_on_the_fill_day():
    b = flat(0, 40) + flat(41, 45)                                   # day 40 has no bar
    mk = market({"AAAUSDT": b}, 30, 45)
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM)
    assert len(out.rf) == 0 and out.cnt[AP.C_LAPSE] == 1


def test_hold_exit_at_the_close_of_the_hth_bar_and_funding():
    after = [(100, 100.5, 99.5, 100)] * 10
    _, out = one_pos({}, after, v=VH)
    rf, ri = _rec(out)
    assert ri[AP.RI_REASON] == AP.EX_HOLD
    assert ri[AP.RI_TOUT] - ri[AP.RI_TIN] == 6                       # entry day = bar 1, exit at bar 7's close
    assert rf[AP.R_XPX] == pytest.approx(100 * (1 - SLIP))
    # 0.09% a day at the closes of the six bars before the exit bar, plus 08:00 and 16:00 of the exit day (2 x 8h)
    assert rf[AP.R_FUND] == pytest.approx((6 * 3 + 2) * F8 * 5 * 100)
    fees = TAKER * 5 * 100 * (1 + SLIP) + TAKER * 5 * 100 * (1 - SLIP)
    assert rf[AP.R_FEES] == pytest.approx(fees)
    assert rf[AP.R_PNL] == pytest.approx(rf[AP.R_PRICE] - fees - rf[AP.R_FUND])


def test_close_before_a_day_without_bar_inside_a_life():
    # 6.8: days 41-42 have no bar (an archive hole); the position closes at day 40's close (unknown path ahead), pays
    # the exit day's 2 x 8h, and nothing is held through the hole
    b = flat(0, 40) + [(40, 100, 100.5, 99.5, 101, 1e9)] + [(d, 100, 100.5, 99.5, 100, 1e9) for d in range(43, 46)]
    mk = market({"AAAUSDT": b}, 30, 46)
    t40 = local(mk, 40)
    assert mk.pregap[0, t40] and not mk.delist[0, t40] and mk.lid[0, local(mk, 43)] == mk.lid[0, t40]
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM)
    rf, ri = _rec(out)
    assert ri[AP.RI_REASON] == AP.EX_HOLE and ri[AP.RI_TOUT] == t40
    assert rf[AP.R_XPX] == pytest.approx(101 * (1 - SLIP))
    assert rf[AP.R_FUND] == pytest.approx(2 * F8 * 5 * 101)
    # a hold variant too, and a short
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", -1)]), VH)
    assert out.ri[0, AP.RI_REASON] == AP.EX_HOLE and len(out.rf) == 1


def test_funding_on_the_exit_day():
    # intraday stop on day 41: day 40's close (3 x 8h) + day 41's 08:00 and 16:00 (2 x 8h at the exit price)
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 100.5, 95.5, 96), (96, 97, 95, 96)], stop_hc=0.0)
    rf, ri = _rec(out)
    assert ri[AP.RI_REASON] == AP.EX_STOP and ri[AP.RI_TOUT] - ri[AP.RI_TIN] == 1
    assert rf[AP.R_FUND] == pytest.approx(3 * F8 * 5 * 100 + 2 * F8 * 5 * 96)
    # a gap through the stop at day 41's open: only day 40's close charge (its 00:00 was in it)
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (95, 95.5, 94.5, 95)])
    rf, ri = _rec(out)
    assert ri[AP.RI_REASON] == AP.EX_GAP and rf[AP.R_FUND] == pytest.approx(3 * F8 * 5 * 100)
    # a stop on the entry day: the 2 x 8h of that day
    _, out = one_pos({}, [(100, 100.5, 95, 96), (96, 97, 95, 96)], stop_hc=0.0)
    rf, ri = _rec(out)
    assert ri[AP.RI_TOUT] == ri[AP.RI_TIN] and rf[AP.R_FUND] == pytest.approx(2 * F8 * 5 * 96)


def test_chandelier_tightens_from_the_next_bar():
    # strong rise: highest high 130, ATR ~ grows; the chandelier ends the trade on a pullback, never loosens
    after = [(100, 100.5, 99.5, 100)] + [(100 + 3 * i, 101 + 3 * i, 99.8 + 3 * i, 100 + 3 * i) for i in range(1, 11)]
    after += [(130, 130.5, 115, 116)]
    _, out = one_pos({}, after)
    rf, ri = _rec(out)
    assert ri[AP.RI_SRC] == AP.SRC_CHAND and ri[AP.RI_REASON] == AP.EX_STOP
    assert 115 < rf[AP.R_XPX] / (1 - SLIP) < 130


def test_delisting_closes_at_the_last_bar_close_and_padding_is_no_bar():
    b = flat(0, 40) + [(40, 100, 100.5, 99.5, 100, 1e9), (41, 100, 100.5, 99.5, 101, 1e9)]
    b += [(d, 101, 101, 101, 101, 0.0) for d in range(42, 60)]       # zero-volume padding after the last bar
    other = flat(0, 60)
    mk = market({"AAAUSDT": b, "BBBUSDT": other}, 30, 60)
    ia = list(mk.syms).index("AAAUSDT")
    assert not mk.bar[ia, local(mk, 45)] and mk.delist[ia, local(mk, 41)]
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM)
    rf, ri = _rec(out)
    assert ri[AP.RI_REASON] == AP.EX_DELIST and ri[AP.RI_TOUT] == local(mk, 41)
    assert rf[AP.R_XPX] == pytest.approx(101 * (1 - SLIP))


def test_period_end_marks_and_last_day_signal_does_not_count():
    mk = market({"AAAUSDT": flat(0, 60)}, 30, 50)
    v = {"id": "P3L_K1_M", "family": "P3", "side": 1, "k": 1, "exit": "M", "hold": 0}
    assert not mk._in_period()[mk.p1 - 1] and mk._in_period()[mk.p1 - 2]
    out = AP.run_account(mk, sig(mk, [(48, "AAAUSDT", 1)]), v)       # fill on day 49 = last day
    assert out.ri[0, AP.RI_REASON] == AP.EX_PEND and out.ri[0, AP.RI_TIN] == mk.p1 - 1


# ------------------------------------------------------------------ 7 portfolio
def test_risk_cap_n_max_and_same_day_order():
    bars = {f"S{i}USDT": [(d, 100, 101, 99, 100, 1e9 + i * 1e6) for d in range(0, 45)] for i in range(7)}
    mk = market(bars, 30, 45)
    items = [(39, f"S{i}USDT", 1) for i in range(7)]
    out = AP.run_account(mk, sig(mk, items), VM)
    # r = 2%: each full unit risks 2%, the cap is 8% -> four positions; the largest 7-day median volume first
    assert len(out.rf) == 4 and out.cnt[AP.C_RISK] == 3
    taken = sorted(mk.syms[out.ri[:, AP.RI_SYM]].tolist())
    assert taken == ["S3USDT", "S4USDT", "S5USDT", "S6USDT"]
    out = AP.run_account(mk, sig(mk, items), VM, r=0.005)            # cap 2%: four units of 0.5%
    assert len(out.rf) == 4
    # liquidity-cut units ($100 notional, risk $4 each) leave the risk cap slack: n_max = 6 binds
    bars = {f"S{i}USDT": [(d, 100, 101, 99, 100, 1e5) for d in range(0, 45)] for i in range(7)}
    mk = market(bars, 30, 45)
    out = AP.run_account(mk, sig(mk, items), VM)
    assert len(out.rf) == 6 and out.cnt[AP.C_NMAX] == 1 and out.cnt[AP.C_CUT_LIQ] == 6
    out = AP.run_account(mk, sig(mk, items), VM, r=0.20)             # r = 20%: n_max 3
    assert len(out.rf) == 3 and out.cnt[AP.C_NMAX] == 4


def test_liquidity_cut_and_minimum_notional():
    b = [(d, 100, 101, 99, 100, 2e5) for d in range(0, 45)]          # 0.1% of $200k = $200 a unit
    mk = market({"AAAUSDT": b}, 30, 45)
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM)
    assert out.rf[0, AP.R_RISK1] == pytest.approx(200 / 100 * 4 / 20)  # q = 2 instead of 5
    assert out.cnt[AP.C_CUT_LIQ] == 1
    b = [(d, 100, 101, 99, 100, 4e3) for d in range(0, 45)]          # $4 unit < $5
    mk = market({"AAAUSDT": b}, 30, 45)
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM)
    assert len(out.rf) == 0 and out.cnt[AP.C_MINNOT] == 1


def test_one_position_per_symbol():
    mk = market({"AAAUSDT": flat(0, 50)}, 30, 50)
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1), (40, "AAAUSDT", -1)]), VM)
    assert len(out.rf) == 1 and out.cnt[AP.C_HASPOS] == 1


# ------------------------------------------------------------------ 3.1 lives and listings, 3.3 universe
def test_lives_listing_rename_relist():
    bars = {
        "OLDUSDT": flat(0, 120),                                      # archive start: not a listing
        "NEWUSDT": flat(0, 1, qv=0.0) + flat(10, 120),                # listed day 10
        "MATICUSDT": flat(0, 51),
        "POLUSDT": flat(70, 120),                                     # 19 days after MATIC's last bar: successor
        "FTMUSDT": flat(0, 21),
        "SUSDT": flat(100, 120),                                      # 79 days after: a new listing
        "RELUSDT": flat(5, 31) + flat(61, 120),                       # 30 days without a bar -> relisting
        "GAPUSDT": flat(5, 31) + flat(60, 120),                       # 29 days -> a pause: new life, no listing
        "PAUUSDT": flat(5, 31) + flat(38, 120),                       # 7 days -> a pause
        "HOLUSDT": flat(5, 31) + flat(37, 120),                       # 6 days -> one life with a gap
    }
    raw = AP.Raw(frame(bars))
    lives = {raw.syms[s]: [] for s in range(len(raw.syms))}
    for i in range(len(raw.life_first)):
        lives[raw.syms[raw.life_sym[i]]].append((int(raw.life_first[i]), bool(raw.life_listing[i])))
    assert lives["OLDUSDT"] == [(0, False)]
    assert lives["NEWUSDT"] == [(10, True)]                           # the zero-volume row on day 0 is no bar
    assert lives["POLUSDT"] == [(70, False)] and raw.successor["POLUSDT"] == ("MATICUSDT", 20)
    assert lives["SUSDT"] == [(100, True)] and "SUSDT" not in raw.successor
    assert lives["RELUSDT"] == [(5, True), (61, True)]
    assert lives["GAPUSDT"] == [(5, True), (60, False)]               # 3.1: a 7..29-day pause restarts, no listing
    assert lives["PAUUSDT"] == [(5, True), (38, False)]
    assert lives["HOLUSDT"] == [(5, True)]
    ih = raw.sym_ix["HOLUSDT"]
    assert raw.pregap[ih, 30] and raw.pregap[ih].sum() == 1          # the bar before the 6-day gap
    assert not raw.pregap[raw.sym_ix["GAPUSDT"]].any()                # a pause ends the life instead
    # delisted lives: ended before the file's last day (the life before a pause too: closed at its last close)
    dl = {raw.syms[raw.life_sym[i]] for i in range(len(raw.life_first)) if raw.life_delist[i]}
    assert dl == {"MATICUSDT", "FTMUSDT", "RELUSDT", "GAPUSDT", "PAUUSDT"}
    mk = AP.Market(raw, AP.day_str(G0 + 3), AP.day_str(G0 + 120), excluded=NOEX, warmup=3)
    ir = list(mk.syms).index("RELUSDT")
    assert mk.lbi[ir, local(mk, 61)] == 0 and mk.lid[ir, local(mk, 61)] != mk.lid[ir, local(mk, 30)]
    assert mk.delist[ir, local(mk, 30)]
    k1 = {"family": "P3", "k": 1, "side": 1}
    k7 = {"family": "P3", "k": 7, "side": 1}
    s1, t1 = np.nonzero(mk.mask(k1))
    got = sorted((mk.syms[s], int(t + mk.w0g - G0)) for s, t in zip(s1, t1))
    assert got == sorted([("NEWUSDT", 10), ("RELUSDT", 5), ("RELUSDT", 61), ("SUSDT", 100), ("GAPUSDT", 5),
                          ("PAUUSDT", 5), ("HOLUSDT", 5)])
    s7, t7 = np.nonzero(mk.mask(k7))
    got7 = sorted((mk.syms[s], int(t + mk.w0g - G0)) for s, t in zip(s7, t7))
    assert ("NEWUSDT", 16) in got7 and ("POLUSDT", 76) not in got7 and ("OLDUSDT", 6) not in got7


def test_listing_day_young_atr_and_volume_median():
    bars = {"OLDUSDT": flat(0, 60), "NEWUSDT": [(30, 10, 14, 9, 12, 6e6)] + flat(31, 60, px=12, qv=6e6)}
    mk = market(bars, 20, 60, warmup=20)
    i = list(mk.syms).index("NEWUSDT")
    t = local(mk, 30)
    assert mk.atr[i, t] == pytest.approx(5.0)                         # first bar: high - low
    assert mk.med7[i, t] == pytest.approx(6e6) and mk.trad[i, t]      # young median = the listing day alone
    assert mk.lst_off[i, t] == 0
    sg = mk.signals({"family": "P3", "k": 1, "side": 1})
    assert [(int(d), mk.syms[s]) for d, s in zip(sg.day, sg.sym)] == [(t, "NEWUSDT")]


def test_volume_floor_point_in_time():
    qv = [1e6] * 30 + [1e8] * 10
    b = [(d, 100, 104, 96, 100 + 3 * (d % 2), qv[d]) for d in range(40)]       # moving closes: not a stable
    mk = market({"AAAUSDT": b}, 5, 40, warmup=5)
    tr = mk.trad[0]
    first = int(np.flatnonzero(tr)[0]) + mk.w0g - G0
    assert first == 33                                                # 4 of the 7 days d-6..d at $100M
    assert not tr[:local(mk, 33)].any()
    # the same file cut after day 31: identical tradable flags up to day 31
    mk2 = market({"AAAUSDT": b[:32]}, 5, 32, warmup=5)
    assert np.array_equal(mk2.trad[0], tr[:mk2.T])


def test_stable_filter_after_31_bars():
    rng = np.random.default_rng(1)
    px = 1.0 + rng.standard_normal(80) * 0.0005
    b = [(d, px[d], px[d] * 1.0005, px[d] * 0.9995, px[d], 1e8) for d in range(80)]
    mk = market({"PEGUSDT": b}, 1, 80, warmup=1)
    lbi = mk.lbi[0]
    assert mk.trad[0][(lbi >= 0) & (lbi < 30)].all()                  # skipped while the life has < 31 bars
    assert not mk.trad[0][lbi >= 40].any()


def test_p1_signal_rules():
    base = [(d, 100, 101, 99, 100, 1e7) for d in range(30)]
    pump = base + [(30, 100, 135, 99, 131, 4e7)]
    mk = market({"AAAUSDT": pump}, 25, 31, warmup=25)
    t = local(mk, 30)
    for x in (0.2, 0.3, 0.5):                                        # the period's last day: no fill day
        assert not mk.mask({"family": "P1", "x": x, "side": 1})[0, t]
    mk = market({"AAAUSDT": pump + [(31, 131, 132, 130, 131, 1e7)]}, 25, 32, warmup=25)
    t = local(mk, 30)
    got = {x: bool(mk.mask({"family": "P1", "x": x, "side": 1})[0, t]) for x in (0.2, 0.3, 0.5)}
    assert got == {0.2: True, 0.3: True, 0.5: False}
    weak = base + [(30, 100, 135, 99, 131, 2.5e7), (31, 131, 132, 130, 131, 1e7)]     # 2.5x volume: no
    mk = market({"AAAUSDT": weak}, 25, 32, warmup=25)
    assert not mk.mask({"family": "P1", "x": 0.2, "side": 1})[0, local(mk, 30)]
    for first, want in ((10, True), (11, False)):                    # day 30 = the 21st / the 20th bar of the life
        young = [(d, 100, 101, 99, 100, 1e7) for d in range(first, 30)] + [(30, 100, 135, 99, 131, 4e7),
                                                                            (31, 131, 132, 130, 131, 1e7)]
        mk = market({"AAAUSDT": young, "OLDUSDT": flat(0, 32)}, 25, 32, warmup=25)
        ia = list(mk.syms).index("AAAUSDT")
        assert bool(mk.mask({"family": "P1", "x": 0.2, "side": 1})[ia, local(mk, 30)]) is want


def test_p4_rank_breakout_event():
    S, T = 16, 5
    NOSKIP = np.zeros(T, np.bool_)
    trad = np.ones((S, T), np.bool_)
    r7 = np.tile(np.linspace(0.0, 0.15, S)[:, None], (1, T))          # symbol 15 has the best 7-day return
    c = np.full((S, T), 10.0)
    hh = np.full((S, T), 11.0)
    ll = np.full((S, T), 9.0)
    c[15, 2:] = 12.0                                                  # breaks out on day 2 and stays above
    c[0, 3] = 8.0                                                     # worst 7-day return breaks down on day 3
    cond = AP._p4_cond(trad, r7, c, hh, ll, 5, 1, NOSKIP)
    assert cond[15].tolist() == [False, False, True, True, True]
    ev = AP._event(cond, trad, np.zeros((S, T), np.int64), NOSKIP)
    assert ev[15].tolist() == [False, False, True, False, False]
    cs = AP._p4_cond(trad, r7, c, hh, ll, 5, -1, NOSKIP)
    assert cs[0].tolist() == [False, False, False, True, False]
    assert not AP._p4_cond(trad, r7, c, hh, ll, 6, 1, NOSKIP).any()           # 16 < 3 x 6 symbols with a 7-day return
    r7t = r7.copy()
    r7t[10:15] = r7[15, 0]                                            # ties: symbol order decides (10..14 first)
    assert not AP._p4_cond(trad, r7t, c, hh, ll, 5, 1, NOSKIP)[15].any()


# ------------------------------------------------------------------ no look-ahead
def test_no_look_ahead_signals_indicators_and_size():
    df = AP.synthetic_frame(40, start="2021-01-01", end="2021-12-31", seed=3, pump_rate=0.03)
    raw = AP.Raw(df)
    mk = AP.Market(raw, "2021-04-01", "2021-12-01", warmup=60)
    rng = np.random.default_rng(5)
    for dday in ("2021-06-15", "2021-09-01"):
        d = AP.gday(dday)
        t = d - mk.w0g
        df2 = df.copy()
        g = df2.open_time.values // DAY
        later = g > d
        fill = g == d + 1
        for col in ("high", "low", "close", "quote_volume"):
            df2.loc[later, col] = df2.loc[later, col].values * rng.uniform(0.3, 3.0, later.sum())
        df2.loc[later & ~fill, "open"] = df2.loc[later & ~fill, "open"].values * rng.uniform(0.3, 3.0,
                                                                                       (later & ~fill).sum())
        df2.loc[later, "volume"] = df2.loc[later, "volume"].values * 2.0
        mk2 = AP.Market(AP.Raw(df2), "2021-04-01", "2021-12-01", warmup=60)
        for name in ("atr", "r1", "r7", "vm20", "hh30", "ll30", "med7", "sd30", "trad"):
            a, b = getattr(mk, name)[:, :t + 1], getattr(mk2, name)[:, :t + 1]
            assert np.array_equal(a, b, equal_nan=True) if a.dtype != bool else np.array_equal(a, b), name
        for v in AP.VARIANTS:
            assert np.array_equal(mk.mask(v)[:, :t + 1], mk2.mask(v)[:, :t + 1]), v["id"]
        for fam in ("P1", "P3", "P4"):                                 # not vacuous: every family has signals by d
            assert sum(int(mk.mask(v)[:, :t + 1].sum()) for v in AP.VARIANTS if v["family"] == fam) > 0
        # the size of an entry decided on day d: the same U, first-unit risk, leverage and D0 when only d+1's open is
        # kept and everything else from d+1 on changes
        cand = np.flatnonzero(mk.trad[:, t] & mk.bar[:, t + 1])
        s = int(cand[0])
        one = AP.Sig(np.array([t], np.int64), np.array([s], np.int64), np.array([1], np.int64))
        o1 = AP.run_account(mk, one, VM)
        o2 = AP.run_account(mk2, one, VM)
        for f in (AP.R_U, AP.R_RISK1, AP.R_LEV, AP.R_P0, AP.R_D0F):
            assert o1.rf[0, f] == o2.rf[0, f]


# ------------------------------------------------------------------ 12-13 statistics
def test_bootstrap_rank_and_bh():
    rng = np.random.default_rng(0)
    assert AP.boot_p(np.full(10, 0.1), rng, 1000) == pytest.approx(1 / 1001)
    assert AP.boot_p(np.full(10, -0.1), rng, 1000) == pytest.approx(1.0)
    assert AP.boot_p([], rng) == 1.0
    p = AP.boot_p(np.array([0.1, -0.1]), np.random.default_rng(1), 20000)
    assert p >= 0.70                                                  # sign flip: P(mean* >= 0) = 3/4 for two months
    assert AP.boot_p(np.random.default_rng(2).standard_normal(26) + 1.5, np.random.default_rng(3), 2000) < 0.01
    assert AP.rank_p(0.5, [0.1, 0.2, 0.6, 0.7]) == pytest.approx(3 / 5)
    assert AP.rank_p(1.0, np.zeros(2000)) == pytest.approx(1 / 2001)
    assert AP.bh([0.01, 0.04, 0.03, 0.5], 0.10) == [True, True, True, False]
    assert AP.bh([0.01, 0.2, 0.3], 0.05) == [True, False, False]
    assert AP.bh([0.06, 0.07], 0.10) == [True, True]
    assert AP.bh([0.2, 0.3], 0.10) == [False, False]
    assert AP.bh([1.0, None, float("nan")], 0.10) == [False, False, False]


def test_judge_needs_every_comparison():
    def row(mean, pos, bust=False, p=0.001):
        return {"base": {"mean_ln": mean, "positions": pos, "bust": bust},
                "cmp": {c: {"p_boot": p, "p_rank": p} for c in "ab"}}
    rows = {"A": {"p2": row(0.1, 30), "p3": row(0.1, 20)},
            "B": {"p2": row(0.1, 30), "p3": row(-0.1, 20)},
            "C": {"p2": row(0.1, 25), "p3": row(0.1, 20)},
            "D": {"p2": row(0.1, 30), "p3": row(0.1, 20, p=0.2)}}
    res = AP.judge(rows)
    assert res["A"]["PASS"] and not res["B"]["PASS"] and not res["C"]["PASS"] and not res["D"]["PASS"]
    assert res["B"]["p_pick"] == 1.0 and res["C"]["p_pick"] == 1.0 and res["D"]["p_pick"] == 0.2


def test_choose_groups_k_and_none():
    def r(mean, med=0.0, pos=40, bust=False, x2=0.01):
        return {"base": {"mean_ln": mean, "median_ln": med, "positions": pos, "bust": bust},
                "x2": {"mean_ln": x2, "bust": False}}
    table = {v["id"]: r(-0.1) for v in AP.VARIANTS}
    table["P1_X20_M"] = r(0.20)
    table["P1_X30_M"] = r(0.30)                                       # same group P1: only the better one
    table["P2_X20_H7"] = r(0.10)
    table["P3L_K1_M"] = r(0.05)
    table["P3S_K7_H28"] = r(0.04)
    table["P4L_N5_M"] = r(0.03)
    table["P4S_N10_M"] = r(0.02)
    table["P4S_N5_M"] = r(0.50, pos=34)                               # too few positions
    table["P3L_K7_M"] = r(0.60, x2=-0.01)                             # fails at cost x2
    ch = AP.choose(table)
    assert ch["status"] == "picked"
    assert ch["picks"] == ["P1_X30_M", "P2_X20_H7", "P3L_K1_M", "P3S_K7_H28", "P4L_N5_M"]
    table2 = {v["id"]: r(-0.1) for v in AP.VARIANTS}
    table2["P4L_N10_H28"] = r(-0.01)
    ch = AP.choose(table2)
    assert ch["status"] == "no_pick_fail" and ch["picks"] == ["P4L_N10_H28"]
    t3 = {v["id"]: r(-0.1) for v in AP.VARIANTS}
    t3["P1_X20_M"] = r(0.1, med=0.01)
    t3["P1_X50_M"] = r(0.1, med=0.02)                                 # tie on mean: higher median wins
    assert AP.choose(t3)["picks"] == ["P1_X50_M"]


def test_controls_a_and_b():
    df = AP.synthetic_frame(30, start="2021-01-01", end="2021-12-31", seed=2, pump_rate=0.03)
    mk = AP.Market(AP.Raw(df), "2021-04-01", "2021-12-01")
    v = AP.VARIANT["P1_X20_M"]
    s = mk.signals(v)
    assert len(s) > 5
    a1 = AP.ctrl_a(s, AP.ctrl_seed("a", v["id"], "p2", 0.02, 0))
    a2 = AP.ctrl_a(s, AP.ctrl_seed("a", v["id"], "p2", 0.02, 0))
    assert np.array_equal(a1.side, a2.side) and np.array_equal(a1.day, s.day) and np.array_equal(a1.sym, s.sym)
    assert set(np.unique(a1.side)) <= {-1, 1}
    pools = mk.control_pools(v)
    st = {}
    b = AP.ctrl_b(mk, s, AP.ctrl_seed("b", v["id"], "p2", 0.02, 0), pools, st)
    for sym in np.unique(s.sym):
        pool = pools[sym]
        mine = np.sort(s.day[s.sym == sym])
        inpool = mine[np.isin(mine, pool)]
        got = np.sort(b.day[b.sym == sym])
        assert len(got) == len(inpool)                                # the pick's count on the symbol is kept
        assert set(got.tolist()) <= set(pool.tolist())
        assert (b.side[b.sym == sym] == 1).all()
    assert st["signals"] == len(b) and st["dropped"] == 0 and 0 < st["first_offset"] <= st["signals"]
    t = pools[int(s.sym[0])]
    assert mk.trad[int(s.sym[0]), t].all() and mk.bar[int(s.sym[0]), t + 1].all()
    assert (t >= mk.p0).all() and (t <= mk.p1 - 2).all() and (mk.lbi[int(s.sym[0]), t] >= 20).all()
    assert np.array_equal(np.lexsort((b.sym, -mk.med7[b.sym, b.day], b.day)), np.arange(len(b)))
    b2 = AP.ctrl_b(mk, s, AP.ctrl_seed("b", v["id"], "p2", 0.02, 0), pools)
    assert np.array_equal(b.day, b2.day) and np.array_equal(b.sym, b2.sym)          # seeded


def test_ctrl_b_common_offset_keeps_same_day_signals_together():
    # 12 (b), second review: one offset for the whole calendar. Six symbols trading the whole period: every signal
    # moves by the same k (mod D), so the three symbols that fired together on one day still fire together, and each
    # symbol's spacing is kept. A seventh symbol listed late: its signals whose k-day falls before its listing take
    # the next common offset that lands in its pool instead of being dropped
    def moving(d0, d1):                                               # not a stable (3.3 d): closes move
        return [(d, 100, 104, 96, 100 + 3 * (d % 2), 1e9) for d in range(d0, d1)]
    bars = {f"F{i}USDT": moving(0, 200) for i in range(6)}
    bars["LATEUSDT"] = moving(120, 200)
    mk = market(bars, 60, 200)
    v = AP.VARIANT["P1_X20_H7"]
    pools = mk.control_pools(v)
    lo, D = mk.p0, mk.p1 - 1 - mk.p0
    full = [list(mk.syms).index(f"F{i}USDT") for i in range(6)]
    assert all(np.array_equal(pools[i], np.arange(lo, lo + D)) for i in full)
    late = list(mk.syms).index("LATEUSDT")
    items = [(70, "F0USDT", 1), (70, "F1USDT", 1), (70, "F2USDT", 1), (71, "F0USDT", 1), (90, "F3USDT", 1),
             (95, "F4USDT", 1), (150, "LATEUSDT", 1), (152, "LATEUSDT", 1)]
    s = sig(mk, items)
    for seed in range(20):
        st = {}
        b = AP.ctrl_b(mk, s, AP.ctrl_seed("b", "X", "syn", 0.02, seed), pools, st)
        assert len(b) == len(s) and st["dropped"] == 0                 # the pick's count, nothing dropped
        orig = {}
        for d_, s_ in zip(s.day, s.sym):
            orig.setdefault(int(s_), []).append(int(d_))
        ks = set()
        for s_ in full:
            if s_ in orig:
                got = sorted(int(d_) for d_, x in zip(b.day, b.sym) if x == s_)
                k = (got[0] - sorted(orig[s_])[0]) % D
                ks.add(k)
                assert got == sorted(lo + (np.asarray(orig[s_]) - lo + k) % D)   # spacing kept (mod D)
        assert len(ks) == 1                                           # one common offset for every symbol
        k = ks.pop()
        on = lo + (local(mk, 70) - lo + k) % D
        assert {int(x) for d_, x in zip(b.day, b.sym) if d_ == on} >= {full[0], full[1], full[2]}
        got_late = sorted(int(d_) for d_, x in zip(b.day, b.sym) if x == late)
        assert len(got_late) == 2 and set(got_late) <= set(pools[late].tolist())
        assert (b.side == 1).all()


# ------------------------------------------------------------------ 14 goal board
def test_board_stats_arithmetic():
    M = np.array([0.05, 0.5, 1.0, 5.0, 10.0, 20.0, 30.0, 50.0, 100.0, 120.0])
    bust = M < 0.1
    st = AP.board_stats(M, bust)
    assert st["months"] == 10 and st["bust_share"] == pytest.approx(0.1)
    assert [st[f"share_ge_x{x}"] for x in AP.BOARD_X] == pytest.approx([0.7, 0.6, 0.5, 0.4, 0.3, 0.2])
    assert st["worst_multiple"] == pytest.approx(0.05) and st["median_multiple"] == pytest.approx(15.0)


def test_monthly_wallets_restart_at_1000_and_bust_stops_the_month():
    # three symbols in January 2021; signals on Jan 20, entries Jan 21; Jan 22 all open far below liquidation
    bars = {}
    for i in range(3):
        b = [(d, 100, 101, 99, 100, 1e9) for d in range(0, 20)]
        b += [(20, 100, 101, 99, 100, 1e9), (21, 60, 61, 59, 60, 1e9)]
        b += [(d, 60, 61, 59, 60, 1e9) for d in range(22, 59)]
        bars[f"S{i}USDT"] = b
    mk = market(bars, 0, 59, warmup=0)                                # Jan and Feb 2021
    items = [(19, f"S{i}USDT", 1) for i in range(3)] + [(40, "S0USDT", 1)]
    v = {"id": "X", "exit": "H", "hold": 3, "side": 1}
    out = AP.run_account(mk, sig(mk, items), v, r=0.20, monthly=True)
    M, bust = AP.month_multiples(out)
    assert out.m_start.tolist() == [1000.0, 1000.0]                   # each month a fresh wallet
    assert bust.tolist() == [True, False] and M[0] < 0.1
    assert (out.ri[:, AP.RI_REASON] == AP.EX_LIQ).sum() == 3
    assert out.ri[-1, AP.RI_MONTH] == 1                               # February trades from $1,000 again
    # continuous account: a bust stops it; later months are 'after bust' (state 2) and count 0 in month_ln
    out = AP.run_account(mk, sig(mk, items), v, r=0.20, monthly=False)
    assert out.m_state.tolist() == [1, 2] and AP.month_ln(out)[1] == 0.0
    assert len(out.rf) == 3 and out.cnt[AP.C_STOPPED] == 1


def test_month_end_closes_open_positions_in_board_mode():
    b = flat(0, 59)
    mk = market({"AAAUSDT": b}, 0, 59, warmup=0)
    out = AP.run_account(mk, sig(mk, [(25, "AAAUSDT", 1)]), VM, monthly=True)
    assert out.ri[0, AP.RI_REASON] == AP.EX_MEND and out.ri[0, AP.RI_TOUT] == local(mk, 30)
    assert out.rf[0, AP.R_XPX] == pytest.approx(100 * (1 - SLIP))


# ------------------------------------------------------------------ pin
def _fake_root(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "research", "altpump", "out"))
    shutil.copy(os.path.join(ROOT, AP.PREREG_REL), os.path.join(root, AP.PREREG_REL))
    shutil.copy(os.path.join(ROOT, AP.CODE_REL), os.path.join(root, AP.CODE_REL))
    return root


def test_pin_refusals(tmp_path):
    root = _fake_root(tmp_path)
    with pytest.raises(AP.PinError):
        AP.check_pin("select", root)                                  # not pinned
    AP.write_pin(root)
    with pytest.raises(AP.PinError):
        AP.write_pin(root)                                            # pinned once
    assert AP.check_pin("select", root)["files"] == 2
    with pytest.raises(AP.PinError):
        AP.check_pin("test", root)                                    # pick.json not pinned yet
    AP._write_json(os.path.join(root, AP.PICK_REL), {"picks": ["P1_X20_M"]})
    AP.append_pick_line(root)
    assert AP.check_pin("test", root)["files"] == 3
    with pytest.raises(AP.PinError):
        AP.check_pin("select", root)                                  # select ran
    with open(os.path.join(root, AP.PICK_REL), "a") as fh:
        fh.write(" ")
    with pytest.raises(AP.PinError):
        AP.check_pin("board", root)                                   # pick.json changed
    with open(os.path.join(root, AP.PREREG_REL), "a") as fh:
        fh.write("x")
    with pytest.raises(AP.PinError, match="changed research/altpump/PREREG_ALTPUMP.md"):
        AP.check_pin("pass2", root)


def test_pin_covers_the_running_code(tmp_path, monkeypatch):
    # 18, second review: check_pin hashed <root>/research/altpump/altpump.py, not the code that runs, so an edited
    # copy run with --root pointing at an intact pinned tree passed. Now the running module's own file must match
    import importlib.util
    root = _fake_root(tmp_path / "pinned")
    AP.write_pin(root)
    assert AP.check_pin("select", root)["code_sha256"] == AP.sha256_file(os.path.join(root, AP.CODE_REL))
    mod_dir = tmp_path / "modified"
    os.makedirs(mod_dir)
    src = open(os.path.join(ROOT, AP.CODE_REL)).read()
    assert src.count("STOP_HC = 0.25 ") == 1
    path = str(mod_dir / "altpump_modified.py")
    with open(path, "w") as fh:
        fh.write(src.replace("STOP_HC = 0.25 ", "STOP_HC = 0.0  "))
    spec = importlib.util.spec_from_file_location("altpump_modified_copy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.STOP_HC == 0.0
    with pytest.raises(mod.PinError, match="running code .* is not the pinned research/altpump/altpump.py"):
        mod.check_pin("select", root)
    monkeypatch.setattr(AP, "git_commit", lambda root=None: "stub")
    st = AP.stamp(root, None, "x")
    assert st["code_sha256"] == AP.running_code_sha256() == AP.sha256_file(os.path.join(ROOT, AP.CODE_REL))


def test_data_sha_must_be_the_prereg_file(tmp_path, monkeypatch):
    # 2, second review: the daily file was checked only against MANIFEST.json (not pinned): a rebuilt file with a
    # regenerated MANIFEST ran. Now the CLI also requires the sha256 that the pinned PREREG states in section 2
    assert AP.DATA_SHA256 == "ef52161f91188f53a39d0642c6857254816264e7cd3ae901e2b15d9730d38eb0"
    prereg = open(os.path.join(ROOT, AP.PREREG_REL)).read()
    line = next(x for x in prereg.splitlines() if "klines_1d.csv.gz" in x)          # bootstrap.sh reads this line
    assert AP.DATA_SHA256 in line
    root = _fake_root(tmp_path)
    os.makedirs(os.path.join(root, "data", "universe"))
    data = os.path.join(root, AP.DATA_REL)
    AP.synthetic_frame(3, start="2021-06-01", end="2021-08-31", seed=2).to_csv(data, index=False, compression="gzip")
    json.dump({"files": {"klines_1d.csv.gz": {"sha256": AP.sha256_file(data)}}},
              open(os.path.join(root, AP.MANIFEST_REL), "w"))            # a MANIFEST that matches the rebuilt file
    AP.write_pin(root)
    calls = []
    monkeypatch.setattr(AP, "step_select", lambda raw, **k: (calls.append(1), ({}, {}, {}))[1])   # no outcome
    with pytest.raises(RuntimeError, match="PREREG_ALTPUMP.md section 2"):
        AP.main(["--root", root, "select"])
    with pytest.raises(RuntimeError, match="PREREG_ALTPUMP.md section 2"):
        AP.main(["--root", root, "check"])
    assert not calls and len(AP.read_pin(root)) == 2                  # nothing ran, nothing pinned
    with pytest.raises(RuntimeError, match="section 2"):
        AP.load_raw(data, os.path.join(root, AP.MANIFEST_REL), want_sha=AP.DATA_SHA256)
    raw, sha = AP.load_raw(data, os.path.join(root, AP.MANIFEST_REL), want_sha=AP.sha256_file(data))
    assert sha == AP.sha256_file(data) and len(raw.syms) == 3


def test_data_checksum_against_manifest(tmp_path):
    p = os.path.join(str(tmp_path), "klines_1d.csv.gz")
    AP.synthetic_frame(3, start="2021-01-01", end="2021-02-01").to_csv(p, index=False, compression="gzip")
    man = os.path.join(str(tmp_path), "MANIFEST.json")
    json.dump({"files": {"klines_1d.csv.gz": {"sha256": AP.sha256_file(p)}}}, open(man, "w"))
    raw, sha = AP.load_raw(p, man)
    assert raw.n_days == 32 and len(raw.syms) == 3
    json.dump({"files": {"klines_1d.csv.gz": {"sha256": "0" * 64}}}, open(man, "w"))
    with pytest.raises(RuntimeError, match="sha256"):
        AP.load_raw(p, man)


# ------------------------------------------------------------------ 15 second pass (synthetic 5m slots)
def _sub_from_slots(mk, slots: dict, nb: int, fund=None, mark=None) -> AP.Sub:
    """slots: (sym index, local day) -> list of nb (o, h, l) tuples."""
    S, T = mk.S, mk.T
    off = np.full((S, T), -1, np.int64)
    n = len(slots)
    arr = np.full((6, max(1, n) * nb), np.nan)
    for i, (key, sl) in enumerate(sorted(slots.items())):
        off[key] = i * nb
        for j, (o, h, l) in enumerate(sl):
            arr[:3, i * nb + j] = (o, h, l)
            mo, mh, ml = (mark or {}).get((key, j), (o, h, l))
            arr[3:, i * nb + j] = (mo, mh, ml)
    fe_off = np.full((S, T), -1, np.int64)
    fe_cnt = np.zeros((S, T), np.int64)
    fs, fr, fm = [], [], []
    for (key, j), (rate, mkp) in sorted((fund or {}).items()):
        if fe_off[key] < 0:
            fe_off[key] = len(fs)
        fe_cnt[key] += 1
        fs.append(j)
        fr.append(rate)
        fm.append(mkp)
    slen = np.where(off >= 0, nb, 0).astype(np.int64)
    return AP.Sub(off, slen, arr[0], arr[1], arr[2], arr[3], arr[4], arr[5], nb, fe_off, fe_cnt,
                  np.asarray(fs, np.int64), np.asarray(fr, float), np.asarray(fm, float), 1 if fund is not None else 0)


def test_pass2_slots_in_time_order_beat_the_daily_worst_order():
    after = [(100, 100.5, 99.5, 100), (100, 105, 99.95, 104)]
    mk, daily = one_pos({}, after)
    assert daily.ri[0, AP.RI_REASON] == AP.EX_STOP and daily.ri[0, AP.RI_ADDS] == 1   # daily: add, then moved stop
    i = 0
    t40, t41 = local(mk, 40), local(mk, 41)
    slots = {(i, t): [(100, 100.5, 99.5), (np.nan, np.nan, np.nan), (100, 100.2, 99.9)] for t in range(mk.T)
             if mk.bar[i, t]}
    slots[(i, t41)] = [(100, 100.2, 99.95), (100.1, 105, 100.1), (104.5, 104.6, 103)]  # low first, then the add
    sub = _sub_from_slots(mk, slots, 3)
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM, sub=sub, stop_hc=0.0)
    assert out.ri[0, AP.RI_ADDS] == 1 and out.ri[0, AP.RI_REASON] == AP.EX_PEND
    # one slot per day equal to the daily bar reproduces the daily run exactly
    slots1 = {(i, t): [(mk.o[i, t], mk.h[i, t], mk.l[i, t])] for t in range(mk.T) if mk.bar[i, t]}
    sub1 = _sub_from_slots(mk, slots1, 1)
    sub1.fund_mode = 0
    o1 = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM, sub=sub1)
    assert np.allclose(o1.rf, daily.rf) and np.array_equal(o1.ri, daily.ri)
    assert t40 >= 0


def test_pass2_mark_price_liquidation_and_funding_events():
    after = [(100, 100.5, 99.5, 100), (100, 100.5, 99.5, 100), (100, 100.5, 99.5, 100)]
    mk, _ = one_pos({}, after)
    i = 0
    slots = {(i, t): [(100, 100.5, 99.5), (100, 100.5, 99.5)] for t in range(mk.T) if mk.bar[i, t]}
    t41 = local(mk, 41)
    # funding at slot 1 of day 41: +0.1% paid by the long on notional at mark 100; then mark wicks to 90 on day 42.
    # Every bar day carries an archived (zero) event so that no day falls back to the fixed charge.
    zero = {((i, t), 0): (0.0, 100.0) for t in range(mk.T) if mk.bar[i, t]}
    fund = {**zero, ((i, t41), 1): (0.001, 100.0)}
    sub = _sub_from_slots(mk, slots, 2, fund=fund, mark={((i, local(mk, 42)), 1): (100, 100.5, 90.0)})
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM, sub=sub)
    assert out.rf[0, AP.R_FUND] == pytest.approx(0.001 * 5 * 100)
    assert out.ri[0, AP.RI_REASON] == AP.EX_LIQ and out.ri[0, AP.RI_TOUT] == local(mk, 42)
    out_s = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", -1)]), VM, sub=_sub_from_slots(mk, slots, 2, fund=fund))
    assert out_s.rf[0, AP.R_FUND] == pytest.approx(-0.001 * 5 * 100)  # a short receives a positive rate
    # a symbol-day without any archived event pays the fixed charge (8): day 40 has none here
    fund2 = {k: v for k, v in fund.items() if k[0] != (i, local(mk, 40))}
    out2 = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", -1)]), VM, sub=_sub_from_slots(mk, slots, 2, fund=fund2))
    assert out2.rf[0, AP.R_FUND] == pytest.approx(-0.001 * 5 * 100 + 3 * F8 * 5 * 100)


def _kl_npz(path, rows):
    """rows: (epoch ms, o, h, l) 5m bars -> the cache format of convert_kline_zip."""
    a = np.asarray(rows, float)
    np.savez_compressed(path, t=a[:, 0].astype(np.int64), o=a[:, 1].astype(np.float32),
                        h=a[:, 2].astype(np.float32), l=a[:, 3].astype(np.float32), c=a[:, 1].astype(np.float32))


def test_pass2_day_without_5m_runs_on_the_daily_bar(tmp_path):
    # the daily file shows day 42 opening at 80 (beyond the 9x long's liquidation); its 5m bars are missing. The 5m
    # pass must not escape that move: day 42 runs on its daily bar and liquidates at the open, as the daily pass does
    after = [(100, 100.5, 99.5, 100), (100, 100.5, 99.5, 101), (80, 81, 70, 75)]
    mk, daily = one_pos({}, after)
    assert daily.ri[0, AP.RI_REASON] == AP.EX_LIQ and daily.ri[0, AP.RI_TOUT] == local(mk, 42)
    cache = str(tmp_path)
    rows = []
    for d in (40, 41):                                                # 2021-02-10 and 2021-02-11: one 5m bar each
        t = local(mk, d)
        rows.append(((G0 + d) * DAY, mk.o[0, t], mk.h[0, t], mk.l[0, t]))
    _kl_npz(os.path.join(cache, "klines_AAAUSDT_2021-02.npz"), rows)
    sub, rep = AP.load_sub5m(mk, cache, ["AAAUSDT"])
    t42 = local(mk, 42)
    assert sub.slen[0, local(mk, 40)] == AP.NB5 and sub.off[0, t42] < 0
    assert rep["days_on_5m"] == 2 and rep["days_on_daily_bar"] == 11      # days 30-39 and 42 of the period
    assert "AAAUSDT 2021-02" in rep["mark"] and "AAAUSDT 2021-02" in rep["funding"]
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM, sub=sub)
    assert out.ri[0, AP.RI_REASON] == AP.EX_LIQ and out.ri[0, AP.RI_TOUT] == t42
    assert out.rf[0, AP.R_PNL] == pytest.approx(daily.rf[0, AP.R_PNL])
    # the same through any Sub without sub-bars for that day (the engine falls back to the daily bar)
    slots = {(0, t): [(mk.o[0, t], mk.h[0, t], mk.l[0, t])] for t in range(mk.T) if mk.bar[0, t]}
    del slots[(0, t42)]
    out1 = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM, sub=_sub_from_slots(mk, slots, 1))
    assert out1.ri[0, AP.RI_REASON] == AP.EX_LIQ and out1.rf[0, AP.R_PNL] == pytest.approx(daily.rf[0, AP.R_PNL])
    # 5m bars that do not reach the daily low (a hole inside the day) -> the day runs on the daily bar
    after2 = [(100, 100.5, 99.5, 100), (100, 100.5, 95.0, 99)]
    mk2, daily2 = one_pos({}, after2)
    t41 = local(mk2, 41)
    _kl_npz(os.path.join(cache, "klines_AAAUSDT_2021-02.npz"),
            [((G0 + 40) * DAY, 100, 100.5, 99.5), ((G0 + 41) * DAY, 100, 100.5, 99.0)])
    sub2, rep2 = AP.load_sub5m(mk2, cache, ["AAAUSDT"])
    assert sub2.off[0, t41] < 0 and rep2["days_5m_short_of_daily_range"] == 1
    out2 = AP.run_account(mk2, sig(mk2, [(39, "AAAUSDT", 1)]), VM, sub=sub2)
    assert out2.ri[0, AP.RI_REASON] == daily2.ri[0, AP.RI_REASON] == AP.EX_STOP
    assert out2.cnt[AP.C_DAYBAR] == 1 and out2.rf[0, AP.R_XPX] == pytest.approx(daily2.rf[0, AP.R_XPX])


def _zip(name: str, text: str) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr(name, text)
    return bio.getvalue()


def test_pass2_converters_and_loader(tmp_path):
    t0 = AP.gday("2021-03-01") * DAY
    lines = [f"{t0 + j * 300000},{1 + j * 0.001},{1.1 + j * 0.001},{0.9},{1.0},10,0,10,1,0,0,0" for j in range(3)]
    for hdr in ("", "open_time,open,high,low,close,volume,close_time,quote_volume,count,tb,tbq,ignore\n"):
        k = AP.convert_kline_zip(_zip("x.csv", hdr + "\n".join(lines) + "\n"))
        assert k["t"].tolist() == [t0, t0 + 300000, t0 + 600000] and k["o"][1] == pytest.approx(1.001)
    f = AP.convert_funding_zip(_zip("f.csv", "calc_time,funding_interval_hours,last_funding_rate\n"
                                             f"{t0 + 8 * 3600000 + 3},8,0.0005\n"))
    assert f["t"][0] == t0 + 8 * 3600000 + 3 and f["rate"][0] == 0.0005
    bars = {"AAAUSDT": [(d, 1.0, 1.1, 0.9, 1.0, 1e9) for d in range(55, 65)]}
    mk = market(bars, 59, 65, warmup=4)                               # 2021-03-01 = day 59
    cache = str(tmp_path)
    np.savez_compressed(os.path.join(cache, "klines_AAAUSDT_2021-03.npz"), **k)
    np.savez_compressed(os.path.join(cache, "mark_AAAUSDT_2021-03.npz"), **k)
    np.savez_compressed(os.path.join(cache, "funding_AAAUSDT_2021-03.npz"), **f)
    sub, rep = AP.load_sub5m(mk, cache, ["AAAUSDT"])
    t = local(mk, 59)
    x = sub.off[0, t]
    assert x >= 0 and sub.nb == 288 and sub.o[x + 1] == pytest.approx(1.001, rel=1e-6) and np.isnan(sub.o[x + 3])
    assert sub.slen[0, t] == 288 and sub.fe_cnt[0, t] == 1 and sub.fe_slot[sub.fe_off[0, t]] == 96
    assert rep["days_on_5m"] == 1 and rep["days_on_daily_bar"] == 5               # days 60-64: daily bars
    assert sub.off[0, local(mk, 58)] < 0                              # warm-up days are never traded
    assert rep["klines"] == [] and "AAAUSDT 2021-02" not in rep["klines"]          # February is warm-up only
    test = {"verdict": {"A": {"PASS": True}, "B": {"PASS": False}},
            "traded_symbols": {"p2": {"A": ["XUSDT"], "B": ["YUSDT"]}, "p3": {"A": ["ZUSDT"]}}}
    plan = AP.pass2_plan(test)
    assert plan["passing"] == ["A"] and plan["symbols"] == {"p2": ["XUSDT"], "p3": ["ZUSDT"]}
    yms = sorted({f["ym"] for f in plan["files"] if f["sym"] == "XUSDT"})
    assert yms[0] == "2024-06" and yms[-1] == "2026-08" and len(yms) == 27
    assert {f["kind"] for f in plan["files"]} == {"klines", "mark", "funding"}


# ------------------------------------------------------------------ whole pipeline (synthetic)
def test_pipeline_select_test_board(tmp_path):
    df = AP.synthetic_frame(50, seed=11, pump_rate=0.02)
    raw = AP.Raw(df)
    table, choice, usize = AP.step_select(raw, min_pos=5)
    assert set(table) == set(AP.VARIANT) and usize["max"] > 0
    assert all("x2" in r and "base" in r for r in table.values())
    picks = choice["picks"]
    assert 1 <= len(picks) <= 5 and len({AP.VARIANT[p]["group"] for p in picks}) == len(picks)
    res = AP.step_test(raw, picks[:2], n_seeds=4, n_boot=50, log=lambda *_: None)
    for vid in picks[:2]:
        for p in AP.TEST_PERIODS:
            row = res["rows"][vid][p]
            assert set(row["cmp"]) == {"a", "b"} and 0 < row["cmp"]["a"]["p_rank"] <= 1
        assert "without_tradfi_exclusion" in res["extra"][vid]["p2"]
        assert set(res["verdict"][vid]) >= {"T0", "T1", "p_pick", "T3_bh_rejected", "PASS"}
    board = AP.step_board(raw, picks[:1], n_seeds=3, rs=(0.02, 0.20), log=lambda *_: None)
    row = board[picks[0]]["p2"]["r=0.2"]
    assert row["pick"]["months"] == 26 and row["coin_flip_pooled"]["months"] == 3 * 26
    for key in ("pick_machine", "coin_flip_machine"):
        assert set(row[key]) >= {"adds_per_position", "share_reaching_add", "add_skips", "entry_cuts"}
        assert set(row[key]["add_skips"]) == {AP.CNT_NAMES[i] for i in AP.ADD_SKIP_IX}
    for vid in picks[:2]:
        for p in AP.TEST_PERIODS:
            assert set(res["extra"][vid][p]["stop_fill_sensitivity"]) == {"f=0", "f=0.5"}
            cb = res["rows"][vid][p]["cmp"]["b"]
            assert cb["control_positions_mean"] is not None and cb["control_signals_dropped_share"] is not None
            if cb["pick_positions"]:
                assert cb["positions_comparable"] == (abs(cb["positions_ratio"] - 1) <= AP.POS_TOL + 1e-12)
            assert set(res["extra"][vid][p]["squeeze_stress"]) >= {"pick_worst_position_U", "pick_overruns",
                                                                   "control_overrun_rate", "p_this_few_overruns"}
        assert set(res["verdict"][vid]["controls_positions_comparable"]) == {"p2_a", "p2_b", "p3_a", "p3_b"}
    assert row["random_days_pooled"]["months"] == 3 * 26 and "label" in row["random_days_pooled"]
    assert set(table[picks[0]]["stop_fill_sensitivity"]) == {"f=0", "f=0.5"}
    assert row["caps"] == {"n_max": 3, "risk_cap": pytest.approx(0.6), "margin_budget_per_position": "equity / 3"}
    assert board[picks[0]]["p1"]["r=0.02"]["label"] == "chosen here"
    AP._write_json(os.path.join(str(tmp_path), "t.json"), {"select": table, "test": res, "board": board})


# ------------------------------------------------------------------ review fixes (2026-10-11): one regression test each
def test_stop_fill_haircut_long_short_and_liquidation():
    # 6.7: a touched stop fills f of the way from the stop to the bar's extreme beyond it
    for f in (0.0, 0.25, 0.5):
        _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 100.5, 94, 95)], stop_hc=f)
        assert out.ri[0, AP.RI_REASON] == AP.EX_STOP
        assert out.rf[0, AP.R_XPX] == pytest.approx((96 - f * 2) * (1 - SLIP))
        _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 105, 99.5, 101)], side=-1, stop_hc=f)
        assert out.ri[0, AP.RI_REASON] == AP.EX_STOP
        assert out.rf[0, AP.R_XPX] == pytest.approx((104 + f * 1) * (1 + SLIP))
    # a +60% squeeze through a short's stop at 104: f = 0 keeps the old optimistic fill (1.1 U); with f = 0.25 the fill
    # (118) lies beyond the 9x short's liquidation (100.1 x (1 + 1/9 - 5%) = 106.2): liquidated, the margin lost
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 160, 99, 150)], side=-1, stop_hc=0.0)
    assert out.ri[0, AP.RI_REASON] == AP.EX_STOP and out.rf[0, AP.R_XPX] == pytest.approx(104 * (1 + SLIP))
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 160, 99, 150)], side=-1)
    margin = 5 * 100 * (1 - SLIP) / 9
    assert out.ri[0, AP.RI_REASON] == AP.EX_LIQ and out.rf[0, AP.R_PRICE] == pytest.approx(-margin)
    # the same on a -60% day for a long (liquidation 93.98 < stop 96, fill 96 - 0.25 x 56 = 82)
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 100.5, 40, 50)])
    assert out.ri[0, AP.RI_REASON] == AP.EX_LIQ
    # the add fills f of the way above its level (buy stop), and the next level is measured from that fill
    ps = np.zeros((1, AP.NF))
    pi = np.zeros((1, AP.NPI), np.int64)
    pi[0, AP.P_SIDE] = 1
    ps[0, AP.F_Q] = ps[0, AP.F_Q1] = 5.0
    ps[0, AP.F_COST] = ps[0, AP.F_REFQ] = 500.0
    ps[0, AP.F_U], ps[0, AP.F_D0], ps[0, AP.F_STOP], ps[0, AP.F_NEXT] = 20.0, 4.0, 96.0, 104.0
    ps[0, AP.F_LEV], ps[0, AP.F_B], ps[0, AP.F_MED7], ps[0, AP.F_LIQ], ps[0, AP.F_EXT] = 1.0, 1e9, 1e15, 0.0, 100.0
    acc = np.array([1e9, 500.0, 0.0, 0.0])
    cnt = np.zeros(AP.NCNT, np.int64)
    bar = np.array([[101.0, 108.0, 101.5]]).T                       # o, h, l of one slot (low above the moved stop)
    code, _ = AP._slot(0, 0, True, bar[0], bar[1], bar[2], bar[0], bar[1], bar[2], ps, pi, acc, 0.0, 1e9, 0.0, 0.0,
                       0.0, 1.0, cnt, AP.BR_CAP, np.zeros(4), 1, 0.5)
    assert code == -1 and pi[0, AP.P_FILLED] == 1
    assert ps[0, AP.F_REFQ] == pytest.approx(500 + 5 * (104 + 0.5 * 4))
    assert ps[0, AP.F_NEXT] == pytest.approx(106 + 4) and ps[0, AP.F_STOP] == pytest.approx((1030 - 20) / 10)


def test_ctrl_b_pools_follow_the_variants_own_conditions():
    # 12 (b): young days (life < 21 bars for P1 / P2, < 31 for P4) are never control days; P3 keeps them; P4 also
    # needs 3N ranked symbols and a non-partial day
    df = AP.synthetic_frame(60, start="2021-01-01", end="2022-06-30", seed=5, pump_rate=0.02)
    mk = AP.Market(AP.Raw(df), "2021-06-01", "2022-06-01")
    young_trad = mk.trad & (mk.lbi >= 0) & (mk.lbi < 30)
    young_trad[:, :mk.p0] = False
    assert young_trad.any()                                            # not vacuous: listings inside the period
    for vid, lo in (("P1_X20_M", 20), ("P2_X30_H7", 20), ("P4L_N5_M", 30), ("P4S_N10_H28", 30)):
        v = AP.VARIANT[vid]
        pools = mk.control_pools(v)
        for s_, pool in enumerate(pools):
            if len(pool):
                assert (mk.lbi[s_, pool] >= lo).all(), vid
                if v["family"] == "P4":
                    assert (mk.n_ranked[pool] >= 3 * v["n"]).all() and not mk.partial[pool].any()
        sg = mk.signals(v)                                             # each pick signal with a fill bar is in the pool
        nxt = mk.bar[sg.sym, sg.day + 1]
        for d_, s_ in zip(sg.day[nxt], sg.sym[nxt]):
            assert d_ in set(pools[s_].tolist()), vid
    p3 = mk.control_pools(AP.VARIANT["P3L_K1_M"])
    assert any((mk.lbi[s_, pool] < 20).any() for s_, pool in enumerate(p3) if len(pool))


def _zero_world(S=24, seed=1, start="2021-01-01", end="2022-06-30"):
    rng = np.random.default_rng(seed)
    d0, d1 = AP.gday(start), AP.gday(end)
    T = d1 - d0 + 1
    sg = 0.05
    ret = rng.standard_normal((S, T)) * sg - 0.5 * sg * sg               # martingale prices: no edge anywhere
    c = 10.0 * np.exp(np.cumsum(ret, axis=1))
    o = np.concatenate([c[:, :1] * np.exp(-ret[:, :1]), c[:, :-1]], axis=1)
    h = np.maximum(o, c) * np.exp(np.abs(rng.standard_normal((S, T))) * sg * 0.5)
    l = np.minimum(o, c) * np.exp(-np.abs(rng.standard_normal((S, T))) * sg * 0.5)
    s_ix, t_ix = np.nonzero(np.ones((S, T), bool))
    names = np.asarray([f"Z{i:03d}USDT" for i in range(S)])
    return pd.DataFrame({"symbol": names[s_ix], "open_time": (d0 + t_ix).astype(np.int64) * DAY,
                         "open": o[s_ix, t_ix], "high": h[s_ix, t_ix], "low": l[s_ix, t_ix], "close": c[s_ix, t_ix],
                         "volume": 5e8 / c[s_ix, t_ix], "quote_volume": np.full(len(s_ix), 5e8)})


def test_ctrl_b_zero_edge_clustered_pick_is_not_favoured():
    # a multi-day pump fires on consecutive days and the repeats are skipped (one position per symbol), so a pick
    # with clustered signals opens far fewer positions than the same number of spread-out random days (the old
    # control (b)). The circular-shift control keeps the clusters: same positions, no edge for a no-skill pick.
    mk = AP.Market(AP.Raw(_zero_world()), "2021-03-01", "2022-06-01", excluded=frozenset())
    v = AP.VARIANT["P1_X20_H7"]
    pools = mk.control_pools(v)
    reps, seeds = 16, 30
    ratio_new, ratio_old, d, low_p = [], [], [], 0
    for rep in range(reps):
        rng = np.random.default_rng(700 + rep)
        D, Sy = [], []
        for s_ in range(mk.S):
            for a in rng.choice(np.arange(mk.p0 + 25, mk.p1 - 5), size=2, replace=False):
                D += [a, a + 1, a + 2]
                Sy += [s_] * 3
        key = np.unique(np.asarray(D) * 1000 + np.asarray(Sy))
        D, Sy = key // 1000, key % 1000
        o = mk.order(D, Sy)
        pick = AP.Sig(D[o], Sy[o], np.ones(len(o), np.int64))
        po = AP.run_account(mk, pick, v)
        lnm, npos_new, npos_old = [], [], []
        for i in range(seeds):
            r_ = AP.ctrl_seed("b", v["id"], f"syn{rep}", 0.02, i)
            co = AP.run_account(mk, AP.ctrl_b(mk, pick, r_, pools), v)
            lnm.append(AP.month_ln(co))
            npos_new.append(len(co.rf))
            # the old control: the same count per symbol on uniformly drawn days
            od, osy = [], []
            for s_ in np.unique(pick.sym):
                n = int((pick.sym == s_).sum())
                od.append(r_.choice(pools[s_], size=n, replace=False))
                osy.append(np.full(n, s_))
            od, osy = np.concatenate(od), np.concatenate(osy)
            oo = mk.order(od, osy)
            npos_old.append(len(AP.run_account(mk, AP.Sig(od[oo], osy[oo], np.ones(len(oo), np.int64)), v).rf))
        lnm = np.asarray(lnm)
        c = AP.compare(AP.month_ln(po), {"lnm": lnm, "means": lnm.mean(axis=1), "busts": 0,
                                         "side_u": np.zeros((seeds, 2)), "positions": np.asarray(npos_new)},
                       v["id"], f"syn{rep}", "b", 0.02, 999)
        ratio_new.append(np.mean(npos_new) / len(po.rf))
        ratio_old.append(np.mean(npos_old) / len(po.rf))
        d.append(c["mean_d"])
        low_p += c["p_rank"] < 0.10
    assert np.mean(ratio_old) > 1.5                                   # the old control traded far more (the bias)
    assert 0.9 < np.mean(ratio_new) < 1.1                             # the new one matches the pick's positions
    d = np.asarray(d)
    assert abs(d.mean()) < 3 * d.std(ddof=1) / np.sqrt(len(d)) + 1e-4  # no systematic edge for a no-skill pick
    assert low_p <= 4                    # p_rank < 0.10 in at most 4 of 16 reps (Binomial(16, 0.1): P(>= 5) = 0.017)


def _factor_world(seed, S=30, sf=0.03, se=0.03, mu=0.0, start="2021-01-01", end="2022-06-30"):
    """Zero-edge GBM alts with a common market factor (alts move together) and an optional common drift."""
    rng = np.random.default_rng(seed)
    d0, d1 = AP.gday(start), AP.gday(end)
    T = d1 - d0 + 1
    ret = ((rng.standard_normal(T) * sf)[None, :] + rng.standard_normal((S, T)) * se
           - 0.5 * (sf * sf + se * se) + mu)
    c = 10.0 * np.exp(np.cumsum(ret, axis=1))
    o = np.concatenate([c[:, :1] * np.exp(-ret[:, :1]), c[:, :-1]], axis=1)
    sg = float(np.hypot(sf, se))
    h = np.maximum(o, c) * np.exp(np.abs(rng.standard_normal((S, T))) * sg * 0.5)
    l = np.minimum(o, c) * np.exp(-np.abs(rng.standard_normal((S, T))) * sg * 0.5)
    s_ix, t_ix = np.nonzero(np.ones((S, T), bool))
    names = np.asarray([f"Z{i:03d}USDT" for i in range(S)])
    return pd.DataFrame({"symbol": names[s_ix], "open_time": (d0 + t_ix).astype(np.int64) * DAY,
                         "open": o[s_ix, t_ix], "high": h[s_ix, t_ix], "low": l[s_ix, t_ix], "close": c[s_ix, t_ix],
                         "volume": 5e8 / c[s_ix, t_ix], "quote_volume": np.full(len(s_ix), 5e8)})


def _old_ctrl_b(mk, s, rng, pools):
    """The draft's control (b), for comparison only: one circular offset per symbol over its own pool."""
    D, Sy = [], []
    for sym in np.unique(s.sym):
        pool = pools[sym]
        n = len(pool)
        days = s.day[s.sym == sym]
        pos = np.searchsorted(pool, days)
        k = int(rng.integers(0, n))
        D.append(pool[(pos + k) % n])
        Sy.append(np.full(len(days), sym))
    D, Sy = np.concatenate(D), np.concatenate(Sy)
    o = mk.order(D, Sy)
    return AP.Sig(D[o], Sy[o], np.ones(len(o), np.int64))


def test_ctrl_b_zero_edge_pick_clustered_across_symbols():
    # 12 (b), second review: a no-skill pick that fires on half the symbols at once on 15 event days (a market-wide
    # pump day). Same-day signals beyond n_max and the risk cap are cut, so the pick opens few positions. The draft's
    # per-symbol offset spread those signals over different days and opened ~3x as many (and paid ~3x the costs, a
    # bias toward the pick); the common offset keeps the busy days busy: about the pick's positions, and the null
    # rejects about as often as its nominal 5% over 100 zero-edge worlds with a common market factor
    v = AP.VARIANT["P1_X20_H7"]
    worlds, seeds = 100, 20
    ratio, ratio_old, pb, pr, d = [], [], [], [], []
    for w in range(worlds):
        mk = AP.Market(AP.Raw(_factor_world(4000 + w)), "2021-03-01", "2022-06-01", excluded=frozenset())
        pools = mk.control_pools(v)
        g = np.random.default_rng(9000 + w)
        D, Sy = [], []
        for e in g.choice(np.arange(mk.p0 + 5, mk.p1 - 5), size=15, replace=False):
            for s_ in np.flatnonzero(g.random(mk.S) < 0.5):
                D.append(e)
                Sy.append(s_)
        D, Sy = np.asarray(D, np.int64), np.asarray(Sy, np.int64)
        o = mk.order(D, Sy)
        pick = AP.Sig(D[o], Sy[o], np.ones(len(o), np.int64))
        po = AP.run_account(mk, pick, v)
        lnm, npos = [], []
        for i in range(seeds):
            co = AP.run_account(mk, AP.ctrl_b(mk, pick, AP.ctrl_seed("b", v["id"], f"xs{w}", 0.02, i), pools), v)
            lnm.append(AP.month_ln(co))
            npos.append(len(co.rf))
        lnm = np.asarray(lnm)
        c = AP.compare(AP.month_ln(po), {"lnm": lnm, "means": lnm.mean(axis=1), "busts": 0,
                                         "side_u": np.zeros((seeds, 2)), "positions": np.asarray(npos)},
                       v["id"], f"xs{w}", "b", 0.02, 499, pick_positions=len(po.rf))
        ratio.append(c["positions_ratio"])
        pb.append(c["p_boot"])
        pr.append(c["p_rank"])
        d.append(c["mean_d"])
        if w < 10:
            old = [len(AP.run_account(mk, _old_ctrl_b(mk, pick, np.random.default_rng(w * 100 + i), pools), v).rf)
                   for i in range(4)]
            ratio_old.append(np.mean(old) / len(po.rf))
    assert np.mean(ratio_old) > 2.0                                   # the draft's control: the bias is real here
    assert 0.9 < np.mean(ratio) < 1.1                                 # the common offset: the pick's positions
    assert np.mean(np.asarray(pb) < 0.05) <= 0.10 and np.mean(np.asarray(pr) < 0.05) <= 0.10
    d = np.asarray(d)
    assert abs(d.mean()) < 3 * d.std(ddof=1) / np.sqrt(len(d)) + 1e-4


def test_boot_p_size_under_a_skewed_null():
    # 13: under a true null (mean d = 0) at n = 19 months; the old percentile bootstrap rejected ~17% at nominal 5%
    # for left-skewed d (the short-side shape: many small wins, rare squeezes)
    rng = np.random.default_rng(11)
    B = 499

    def pct(d, r):
        m = d[r.integers(0, len(d), (B, len(d)))].mean(axis=1)
        return (1 + (m <= 0).sum()) / (B + 1)
    left = [-(rng.lognormal(0, 1.0, 19) - np.exp(0.5)) for _ in range(700)]
    norm = [rng.standard_normal(19) for _ in range(700)]
    new_left = np.mean([AP.boot_p(x, np.random.default_rng(k), B) < 0.05 for k, x in enumerate(left)])
    old_left = np.mean([pct(x, np.random.default_rng(k)) < 0.05 for k, x in enumerate(left)])
    new_norm = np.mean([AP.boot_p(x, np.random.default_rng(k), B) < 0.05 for k, x in enumerate(norm)])
    assert old_left > 0.13                                            # the problem is real in this setting
    assert new_left < 0.125 and new_left < old_left - 0.04
    assert new_norm < 0.075


def test_squeeze_stress_read():
    # 13, second review: a mean-zero short pick with rare squeeze months passes T2 whenever no squeeze lands in the
    # 19 / 26 test months. Reported beside the verdict: the pick's worst position in U and its stop overruns against
    # the control seeds' overrun rate on the same symbols and side
    from types import SimpleNamespace

    def acct(pnl_u, syms, sides):
        n = len(pnl_u)
        rf = np.zeros((n, AP.NRF))
        ri = np.zeros((n, AP.NRI), np.int64)
        rf[:, AP.R_U] = 20.0
        rf[:, AP.R_PNL] = np.asarray(pnl_u, float) * 20.0
        ri[:, AP.RI_SYM] = syms
        ri[:, AP.RI_SIDE] = sides
        return SimpleNamespace(rf=rf, ri=ri)
    pick = acct([0.3] * 29 + [-1.2], [1] * 30, [-1] * 30)             # 30 small wins and stops, no squeeze
    ctl = acct([0.3] * 18 + [-3.0, -2.0] + [-4.0] * 5, [1] * 20 + [2] * 5, [-1] * 19 + [1] + [-1] * 5)
    assert AP.overruns(ctl) == (25, 7)
    assert AP.overruns(ctl, [1], -1) == (19, 1)                       # same symbols and side only
    pos, over = AP.overruns(ctl, [1], -1)
    st = AP.stress_read(pick, [{"focus_positions": pos * 10, "focus_overruns": over * 10 + 20}])
    rate = (10 + 20) / 190
    assert st["pick_overruns"] == 0 and st["pick_worst_position_U"] == pytest.approx(-1.2)
    assert st["control_overrun_rate"] == pytest.approx(rate)
    assert st["expected_overruns_at_control_rate"] == pytest.approx(30 * rate)
    assert st["p_this_few_overruns"] == pytest.approx(np.exp(-30 * rate))
    assert AP.stress_read(acct([], [], []), [])["p_this_few_overruns"] is None
    assert AP._poisson_cdf(2, 3.0) == pytest.approx(np.exp(-3) * (1 + 3 + 4.5))


def test_values_outside_the_step_window_are_never_loaded(tmp_path):
    df = AP.synthetic_frame(40, seed=11, pump_rate=0.02)
    path = os.path.join(str(tmp_path), "k.csv.gz")
    df.to_csv(path, index=False, compression="gzip")
    win = AP.step_windows("select")
    assert win == [(AP.gday("2021-08-01") - 60, AP.gday("2024-07-01"))]
    assert AP.step_windows("test") == [(AP.gday("2024-07-01") - 60, AP.gday("2026-09-01")),
                                       (AP.gday("2020-01-01") - 60, AP.gday("2021-08-01"))]
    assert AP.step_windows("board") is None
    raw_w, _ = AP.load_raw(path, value_windows=win)
    g = AP.Raw(df).dix + AP.Raw(df).first_day
    outside = (g < win[0][0]) | (g >= win[0][1])
    assert np.isnan(raw_w.vals["close"][outside]).all() and np.isfinite(raw_w.vals["close"][~outside]).all()
    assert np.array_equal(raw_w.cal, AP.Raw(df).cal)                  # the calendar is whole
    with pytest.raises(RuntimeError, match="section 10"):
        AP.Market(raw_w, *AP.PERIODS["p2"])
    t_full = AP.step_select(AP.Raw(AP.read_frame(path)), min_pos=5)
    t_win = AP.step_select(raw_w, min_pos=5)
    assert json.dumps(t_full, sort_keys=True, default=str) == json.dumps(t_win, sort_keys=True, default=str)


def test_partial_days_are_not_ranked_and_the_event_looks_past_them():
    # 3.1: 11 of 12 lives lack a bar on day 30 -> a partial day; one symbol lacking day 40 alone is not
    bars = {f"S{i:02d}USDT": [b for b in flat(0, 60) if b[0] != 30] for i in range(11)}
    bars["S11USDT"] = [b for b in flat(0, 60) if b[0] != 40]
    raw = AP.Raw(frame(bars))
    assert raw.partial[30] and raw.partial.sum() == 1
    assert raw.pregap[raw.sym_ix["S00USDT"], 29] and raw.pregap[raw.sym_ix["S11USDT"], 39]
    # P4 on a partial day: no ranking; the event's 'previous bar' skips it
    S, T = 16, 5
    trad = np.ones((S, T), np.bool_)
    r7 = np.tile(np.linspace(0.0, 0.15, S)[:, None], (1, T))
    c = np.full((S, T), 10.0)
    c[15, 2:] = 12.0
    hh, ll = np.full((S, T), 11.0), np.full((S, T), 9.0)
    skip = np.array([False, False, True, False, False])
    cond = AP._p4_cond(trad, r7, c, hh, ll, 5, 1, skip)
    assert cond[15].tolist() == [False, False, False, True, True]
    ev = AP._event(cond, trad, np.zeros((S, T), np.int64), skip)
    assert ev[15].tolist() == [False, False, False, True, False]
    cond2 = AP._p4_cond(trad, r7, c, hh, ll, 5, 1, np.zeros(T, np.bool_))
    cond2[15, 3] = True
    ev2 = AP._event(cond2, trad, np.zeros((S, T), np.int64), skip)      # true before (day 1? no) and after the hole
    assert ev2[15].tolist() == [False, False, False, True, False]


def test_indicators_do_not_read_across_a_gap():
    # 4 / 3.1, second review: an archive hole of days 40-42 (11 of 12 symbols lack bars: partial days). S00 rises 7% a
    # day through it (no single day near +20%). Before the fix day 43's 1-day return was the 4-day move (+31%) and P1
    # X20 / X30 fired on it; the 7-day return of the next 7 bars spanned 10 days; the TR spanning the hole inflated ATR
    rows = {}
    for i in range(15):
        sym = f"S{i:02d}USDT"
        px, b = 100.0, []
        for d in range(60):
            qv = 4e8 if (i == 0 and d == 43) else 1e8
            o = px
            px = px * 1.07 if (i == 0 and 40 <= d <= 43) else px * (1.03 if d % 2 else 0.97)
            c = px
            if i < 11 and 40 <= d <= 42:
                continue
            b.append((d, o, max(o, c) * 1.01, min(o, c) * 0.99, c, qv))
        rows[sym] = b
    raw = AP.Raw(frame(rows))
    assert raw.partial[40:43].all() and raw.partial.sum() == 3
    mk = AP.Market(raw, AP.day_str(G0 + 30), AP.day_str(G0 + 60), excluded=NOEX, warmup=30)
    i0, i11 = list(mk.syms).index("S00USDT"), list(mk.syms).index("S11USDT")
    t39, t43 = local(mk, 39), local(mk, 43)
    assert np.isnan(mk.r1[i0, t43]) and np.isfinite(mk.r1[i0, local(mk, 44)])
    assert mk.trad[i0, t43] and mk.lbi[i0, t43] >= 20 and mk.qv[i0, t43] >= 3 * mk.vm20[i0, t43]   # only r1 decides
    for x in (20, 30):
        assert not mk.mask(AP.VARIANT[f"P1_X{x}_M"])[i0, t43]
    tr43 = mk.h[i0, t43] - mk.l[i0, t43]                               # no previous close across the hole
    assert mk.atr[i0, t43] == pytest.approx((13 * mk.atr[i0, t39] + tr43) / 14)
    r7 = mk.r7[i0]
    assert np.isnan(r7[local(mk, 43):local(mk, 50)]).all()            # the 7 bars whose lookback spans the hole
    assert r7[local(mk, 50)] == pytest.approx(mk.c[i0, local(mk, 50)] / mk.c[i0, t43] - 1)
    assert np.isfinite(mk.r7[i11, local(mk, 43):local(mk, 50)]).all()  # a symbol with bars through the hole: as before
    assert np.isfinite(mk.r1[i11, local(mk, 41)])
    # the stable filter's std skips the return over the hole
    t = local(mk, 45)
    days = [d for d in range(60) if mk.bar[i0, local(mk, d)] and d <= 45]
    lr = [np.log(mk.c[i0, local(mk, b)] / mk.c[i0, local(mk, a)]) for a, b in zip(days[:-1], days[1:]) if b - a == 1]
    k_rets = [np.log(mk.c[i0, local(mk, b)] / mk.c[i0, local(mk, a)]) for a, b in zip(days[:-1], days[1:])][-30:]
    want = [x for x, (a, b) in zip(k_rets, list(zip(days[:-1], days[1:]))[-30:]) if b - a == 1]
    assert len(want) == 29 and lr[-29:] == pytest.approx(want)
    assert mk.sd30[i0, t] == pytest.approx(np.std(want, ddof=1))
    # control (b) pools: no P1 / P2 day without a 1-day return, no P4 day without a 7-day return
    p1 = mk.control_pools(AP.VARIANT["P1_X20_M"])
    assert t43 not in set(p1[i0].tolist()) and local(mk, 44) in set(p1[i0].tolist())
    p4 = mk.control_pools({"family": "P4", "n": 1, "side": 1})       # 3 ranked symbols needed: S11..S14 have r7
    assert (mk.n_ranked[t43:local(mk, 50)] == 4).all()
    assert not set(p4[i0].tolist()) & set(range(t43, local(mk, 50))) and local(mk, 50) in set(p4[i0].tolist())
    assert set(range(t43, local(mk, 50))) <= set(p4[i11].tolist())


def test_pause_of_a_week_ends_the_life_and_closes_the_position():
    # 3.1 / 6.8: 10 days without a bar inside what used to be one life: the position closes at the last bar's close
    # (like a delisting) and the restart has fresh indicators and is not a P3 listing
    b = flat(0, 40) + [(40, 100, 100.5, 99.5, 102, 1e9)] + flat(51, 70)
    mk = market({"AAAUSDT": b, "BBBUSDT": flat(0, 70)}, 30, 70)
    i = list(mk.syms).index("AAAUSDT")
    t40, t51 = local(mk, 40), local(mk, 51)
    assert mk.delist[i, t40] and mk.lbi[i, t51] == 0 and mk.lst_off[i, t51] == -1
    assert np.isnan(mk.r1[i, t51]) and mk.atr[i, t51] == pytest.approx(2.0)
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM)
    assert out.ri[0, AP.RI_REASON] == AP.EX_DELIST and out.rf[0, AP.R_XPX] == pytest.approx(102 * (1 - SLIP))


def _guard_root(tmp_path, monkeypatch, passing=True):
    """A pinned fake root on SYNTHETIC data: select ran (pick.json pinned) and test ran (test.json pinned, as cmd_test
    pins it). The synthetic file is not the PREREG's daily file, so DATA_SHA256 is set to its sha256 here; git and
    every step that would compute an outcome are stubbed by the tests that run a step."""
    root = _fake_root(tmp_path)
    os.makedirs(os.path.join(root, "data", "universe"))
    data = os.path.join(root, AP.DATA_REL)
    AP.synthetic_frame(4, start="2024-05-01", end="2024-08-31", seed=1).to_csv(data, index=False, compression="gzip")
    json.dump({"files": {"klines_1d.csv.gz": {"sha256": AP.sha256_file(data)}}},
              open(os.path.join(root, AP.MANIFEST_REL), "w"))
    monkeypatch.setattr(AP, "DATA_SHA256", AP.sha256_file(data))
    monkeypatch.setattr(AP, "git_commit", lambda root=None: "stub")
    AP.write_pin(root)
    AP._write_json(os.path.join(root, AP.PICK_REL), {"status": "picked", "picks": ["P1_X20_M"]})
    AP.append_pick_line(root)
    AP._write_json(os.path.join(root, AP.OUT_REL, "test.json"),
                   {"verdict": {"P1_X20_M": {"PASS": passing}},
                    "traded_symbols": {"p2": {"P1_X20_M": ["S000USDT", "S001USDT"]}, "p3": {"P1_X20_M": []}}})
    AP.append_pin_line(root, AP.out_rel("test.json"))
    return root


def test_run_once_guards_for_test_board_and_pass2(tmp_path, monkeypatch):
    root = _guard_root(tmp_path, monkeypatch)
    out = os.path.join(root, AP.OUT_REL)
    with pytest.raises(AP.PinError, match="test.json exists"):
        AP.main(["--root", root, "test"])
    AP._write_json(os.path.join(out, "board.json"), {})
    with pytest.raises(AP.PinError, match="board.json exists"):
        AP.main(["--root", root, "board"])
    # pass2 run with an empty cache: the needed 5m months are missing -> refused (no --accept-missing, no DEVIATIONS)
    with pytest.raises(AP.PinError, match="no 5m klines"):
        AP.main(["--root", root, "pass2", "run", "--cache", os.path.join(root, "cache")])
    with pytest.raises(AP.PinError, match="no 5m klines"):
        AP.main(["--root", root, "pass2", "run", "--accept-missing", "--cache", os.path.join(root, "cache")])
    AP._write_json(os.path.join(out, "pass2.json"), {})
    for what in ("run", "fetch"):
        with pytest.raises(AP.PinError, match="pass2.json exists"):
            AP.main(["--root", root, "pass2", what, "--cache", os.path.join(root, "cache")])
    inv = AP.pass2_inventory(AP.Raw(AP.synthetic_frame(4, start="2024-05-01", end="2024-08-31", seed=1)),
                             {"symbols": {"p2": ["S000USDT"], "p3": ["S000USDT"]}}, os.path.join(root, "cache"))
    assert inv["klines"] and all(x.startswith("p2 S000USDT 2024-0") for x in inv["klines"])
    assert AP.cache_digest(os.path.join(root, "nothing"))["files"] == 0


def test_accept_missing_needs_each_missing_month_in_deviations(tmp_path, monkeypatch):
    # 15, second review: --accept-missing used to pass with any DEVIATIONS.md, even an empty one
    root = _guard_root(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(AP, "step_pass2", lambda raw, test, cache, **k: (calls.append(1), {})[1])   # no outcome
    cache = os.path.join(root, "cache")
    dev = os.path.join(root, AP.DEV_REL)
    open(dev, "w").close()                                            # an empty DEVIATIONS.md
    with pytest.raises(AP.PinError, match="Not in research/altpump/DEVIATIONS.md") as e:
        AP.main(["--root", root, "pass2", "run", "--accept-missing", "--cache", cache])
    assert "p2 S000USDT 2024-07" in str(e.value) and "no 5m klines" in str(e.value)
    with open(dev, "w") as fh:                                        # one of the two months listed: still refused
        fh.write("2026-10-20: 5m klines missing in the archive: p2 S000USDT 2024-07\n")
    with pytest.raises(AP.PinError, match="p2 S000USDT 2024-08"):
        AP.main(["--root", root, "pass2", "run", "--accept-missing", "--cache", cache])
    assert not calls
    with open(dev, "a") as fh:
        fh.write("p2 S000USDT 2024-08\np2 S001USDT 2024-07\np2 S001USDT 2024-08\n")
    with pytest.raises(AP.PinError, match="no 5m klines"):            # listed, but --accept-missing not given
        AP.main(["--root", root, "pass2", "run", "--cache", cache])
    AP.main(["--root", root, "pass2", "run", "--accept-missing", "--cache", cache])
    assert calls == [1]
    pinned = AP.read_pin(root)
    assert pinned[-1][1] == AP.out_rel("pass2.json")                  # the output is pinned when written
    assert pinned[-1][0] == AP.sha256_file(os.path.join(root, AP.OUT_REL, "pass2.json"))


def test_run_once_outputs_are_pinned_and_a_rerun_needs_a_deviation(tmp_path, monkeypatch):
    # 15 / 18, second review: moving out/test.json aside used to allow a second test run with no trace, and pass2
    # trusted whichever test.json was there. Now test / board / pass2 append their output's sha256 to the pin file
    root = _guard_root(tmp_path, monkeypatch)
    out = os.path.join(root, AP.OUT_REL)
    calls = []
    fake = {"verdict": {"P1_X20_M": {"PASS": True}},
            "traded_symbols": {"p2": {"P1_X20_M": ["S000USDT"]}, "p3": {"P1_X20_M": []}}}
    monkeypatch.setattr(AP, "step_test", lambda raw, picks, **k: (calls.append("test"), json.loads(json.dumps(fake)))[1])
    monkeypatch.setattr(AP, "step_board", lambda raw, picks, **k: (calls.append("board"), {})[1])
    h_old = AP.live_once_lines(root)[AP.out_rel("test.json")]
    os.rename(os.path.join(out, "test.json"), os.path.join(out, "test.json.old"))
    with pytest.raises(AP.PinError, match="missing research/altpump/out/test.json"):
        AP.main(["--root", root, "test"])                             # the pinned test.json must stay where it is
    with pytest.raises(AP.PinError, match="not pinned: run test first|missing research/altpump/out/test.json"):
        AP.main(["--root", root, "pass2", "plan"])
    with open(os.path.join(root, AP.DEV_REL), "w") as fh:            # a documented rerun after a bug fix (17)
        fh.write(f"2026-10-20: bug in X fixed; test rerun once; superseded test.json sha256 {h_old}\n")
    AP.main(["--root", root, "test"])
    assert calls == ["test"]
    lines = [r for r in AP.read_pin(root) if r[1] == AP.out_rel("test.json")]
    h_new = AP.sha256_file(os.path.join(out, "test.json"))
    assert [h for h, _ in lines] == [h_old, h_new] and AP.live_once_lines(root)[AP.out_rel("test.json")] == h_new
    assert AP.check_pin("pass2", root)["files"] == 5                  # prereg, code, pick, two test lines
    os.rename(os.path.join(out, "test.json"), os.path.join(out, "test.json.second"))
    with pytest.raises(AP.PinError, match="missing research/altpump/out/test.json"):
        AP.main(["--root", root, "test"])                             # a second rerun needs its own entry
    os.rename(os.path.join(out, "test.json.second"), os.path.join(out, "test.json"))
    good = open(os.path.join(out, "test.json"), "rb").read()
    with open(os.path.join(out, "test.json"), "a") as fh:            # an edited test.json: pass2 and board refuse
        fh.write(" ")
    for argv in (["pass2", "plan"], ["board"]):
        with pytest.raises(AP.PinError, match="changed research/altpump/out/test.json"):
            AP.main(["--root", root] + argv)
    with open(os.path.join(out, "test.json"), "wb") as fh:           # back to the pinned bytes
        fh.write(good)
    # board: pinned when written; a second run refused even after the file is moved aside
    AP.main(["--root", root, "board"])
    assert calls == ["test", "board"] and AP.out_rel("board.json") in AP.live_once_lines(root)
    os.rename(os.path.join(out, "board.json"), os.path.join(out, "board.json.old"))
    with pytest.raises(AP.PinError, match="missing research/altpump/out/board.json"):
        AP.main(["--root", root, "board"])


def test_board_luck_reference_keeps_the_pick_side():
    # 14, second review: every pick is one-sided, and coin-flip sides cancel the market's direction, so in a trending
    # month a no-skill one-sided rule beats the coin flip at reaching x1.5 / x2: the coin-flip table understated luck.
    # The board now puts control (b) beside the pick (the pick's signals on random days, its own side) as the luck
    # reference, and labels the coin flip 'luck without the market side'
    bars = {}
    for i in range(6):
        px, b_ = 10.0, []
        for d in range(0, 125):
            o = px
            px *= 1.03 if (d + i) % 2 else 1.01                       # every coin rises ~2% a day
            b_.append((d, o, max(o, px) * 1.005, min(o, px) * 0.995, px, 1e9))
        bars[f"U{i}USDT"] = b_
    mk = market(bars, 31, 120, warmup=31)                             # 2021-02-01 .. 2021-04-30: three months
    v = AP.VARIANT["P1_X20_H7"]
    items = [(d, f"U{i}USDT", 1) for d in (40, 41, 70, 71, 100, 101) for i in range(6)]
    row = AP.board_block(mk, sig(mk, items), v, "syn", 0.02, n_seeds=30)
    rd, cf, pk = row["random_days_pooled"], row["coin_flip_pooled"], row["pick"]
    assert rd["months"] == cf["months"] == 30 * 3 and pk["months"] == 3
    assert "luck reference" in rd["label"] and "without the market side" in cf["label"]
    # the same side carries the trend as the pick does; random sides give half of it away
    assert rd["median_multiple"] > cf["median_multiple"] + 0.05 and pk["median_multiple"] > cf["median_multiple"] + 0.05
    assert abs(rd["median_multiple"] - pk["median_multiple"]) < 0.25 * abs(cf["median_multiple"] - pk["median_multiple"])
    assert row["random_days_machine"]["positions"] > 0 and "coin_flip_machine" in row


def test_board_rows_report_adds_and_their_skips_at_high_r():
    # 14: three coins rising 10% a day with a 10% range; at r = 20% the margin budget (equity / 3) leaves no room for
    # adds, at r = 0.5% every add fills; both are on the board row
    bars = {}
    for i in range(3):
        b = [(d, 1.0, 1.05, 0.95, 1.0, 1e9) for d in range(31)]
        px = 1.0
        for k in range(27):
            c = px * 1.10
            b.append((31 + k, px, c * 1.025, px * 0.975, c, 1e9))
            px = c
        bars[f"C{i}USDT"] = b
    mk = market(bars, 31, 59, warmup=31)
    sg = sig(mk, [(30, f"C{i}USDT", 1) for i in range(3)])
    v = AP.VARIANT["P1_X20_M"]
    hi = AP.board_block(mk, sg, v, "syn", 0.20, n_seeds=2)
    lo = AP.board_block(mk, sg, v, "syn", 0.005, n_seeds=2)
    assert hi["pick_machine"]["adds_per_position"] < lo["pick_machine"]["adds_per_position"]
    assert lo["pick_machine"]["share_reaching_add"][0] == 1.0
    skips = hi["pick_machine"]["add_skips"]
    assert skips["add_skip_margin_budget"] + skips["add_skip_free_wallet"] > 0
    assert hi["caps"]["n_max"] == 3 and "coin_flip_machine" in hi
