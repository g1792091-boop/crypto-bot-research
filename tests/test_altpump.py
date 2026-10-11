"""research/altpump (PREREG_ALTPUMP.md section 18) on synthetic data only. No real market data is read anywhere here.

- fixed lists: 191 exclusions in their groups, 14 renames, 28 variants with section 5's ids, caps of section 7;
- worst-order fills on daily bars (6.7): a gap through the stop fills at the open, a gap beyond liquidation loses the
  margin, the stop counts before an add in the same bar, an add then the moved stop exits the same day (long and short);
- no look-ahead: changing every value of day d+1 onward (the fill open aside) leaves every day-d signal, indicator and
  the entry's size unchanged;
- lives: listing day 0 (P3 K1 / K7), archive-start lives, rename successors (within / beyond 60 days), relisting after
  30 days without a bar (29 is a gap), delisting closes at the last bar's close, zero-volume padding is no bar;
- the volume floor point in time (a later spike does not make an earlier day tradable), the stable filter;
- the pyramiding stop formula (P0, P0 + 0.667 D0, P0 + 1.25 D0 with full units), leverage choice and the 1.5x rule,
  risk cap, n_max, liquidity cut, D0 cap, lapse, period end, hold exit, chandelier, funding;
- bootstrap p, rank p and BH on known inputs; selection (groups, K, none eligible); controls (a) and (b);
- goal-board arithmetic: fresh $1,000 months, thresholds, bust;
- pin refusals; the second pass (5m slots in time order, mark-price liquidation, funding events, file converters);
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


def test_stop_before_add_in_the_same_bar():
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 105, 95.5, 100)])
    rf, ri = _rec(out)
    assert ri[AP.RI_REASON] == AP.EX_STOP and ri[AP.RI_ADDS] == 0 and ri[AP.RI_TRIED] == 0
    assert rf[AP.R_XPX] == pytest.approx(96 * (1 - SLIP))
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 104.5, 95, 100)], side=-1)
    rf, ri = _rec(out)
    assert ri[AP.RI_REASON] == AP.EX_STOP and ri[AP.RI_ADDS] == 0
    assert rf[AP.R_XPX] == pytest.approx(104 * (1 + SLIP))


def test_add_then_moved_stop_exit_same_day():
    # add 1 at 104 (full unit) moves the stop to P0 = 100; the day's low 99.9 reaches it -> exit at 100
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 104.5, 99.9, 102)])
    rf, ri = _rec(out)
    assert ri[AP.RI_ADDS] == 1 and ri[AP.RI_REASON] == AP.EX_STOP and ri[AP.RI_SRC] == AP.SRC_ADD
    assert rf[AP.R_XPX] == pytest.approx(100 * (1 - SLIP))
    _, out = one_pos({}, [(100, 100.5, 99.5, 100), (100, 100.1, 95.5, 98)], side=-1)
    rf, ri = _rec(out)
    assert ri[AP.RI_ADDS] == 1 and ri[AP.RI_REASON] == AP.EX_STOP
    assert rf[AP.R_XPX] == pytest.approx(100 * (1 + SLIP))


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
    assert rf[AP.R_FUND] == pytest.approx(6 * 3 * F8 * 5 * 100)      # 0.09% a day on the bars before the exit bar
    fees = TAKER * 5 * 100 * (1 + SLIP) + TAKER * 5 * 100 * (1 - SLIP)
    assert rf[AP.R_FEES] == pytest.approx(fees)
    assert rf[AP.R_PNL] == pytest.approx(rf[AP.R_PRICE] - fees - rf[AP.R_FUND])


def test_funding_charged_on_gap_days_inside_a_life():
    b = flat(0, 40) + [(40, 100, 100.5, 99.5, 100, 1e9)] + [(d, 100, 100.5, 99.5, 100, 1e9) for d in range(43, 46)]
    mk = market({"AAAUSDT": b}, 30, 46)
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM)
    days = 46 - 40 - 1                                               # closes of days 40..44 (45 = period end: marked)
    assert out.rf[0, AP.R_FUND] == pytest.approx((days + 1) * 3 * F8 * 5 * 100)


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
        "GAPUSDT": flat(5, 31) + flat(60, 120),                       # 29 days -> one life with a gap
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
    assert lives["GAPUSDT"] == [(5, True)]
    # delisted lives: ended before the file's last day
    dl = {raw.syms[raw.life_sym[i]] for i in range(len(raw.life_first)) if raw.life_delist[i]}
    assert dl == {"MATICUSDT", "FTMUSDT", "RELUSDT"}
    mk = AP.Market(raw, AP.day_str(G0 + 3), AP.day_str(G0 + 120), excluded=NOEX, warmup=3)
    ir = list(mk.syms).index("RELUSDT")
    assert mk.lbi[ir, local(mk, 61)] == 0 and mk.lid[ir, local(mk, 61)] != mk.lid[ir, local(mk, 30)]
    assert mk.delist[ir, local(mk, 30)]
    k1 = {"family": "P3", "k": 1, "side": 1}
    k7 = {"family": "P3", "k": 7, "side": 1}
    s1, t1 = np.nonzero(mk.mask(k1))
    got = sorted((mk.syms[s], int(t + mk.w0g - G0)) for s, t in zip(s1, t1))
    assert got == [("NEWUSDT", 10), ("RELUSDT", 5), ("RELUSDT", 61), ("SUSDT", 100), ("GAPUSDT", 5)] or \
        sorted(got) == sorted([("NEWUSDT", 10), ("RELUSDT", 5), ("RELUSDT", 61), ("SUSDT", 100), ("GAPUSDT", 5)])
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
    for x, want in ((0.2, True), (0.3, True), (0.5, False)):
        assert bool(mk.mask({"family": "P1", "x": x, "side": 1})[0, t - 0]) is False  # last day: no fill day
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
    trad = np.ones((S, T), np.bool_)
    r7 = np.tile(np.linspace(0.0, 0.15, S)[:, None], (1, T))          # symbol 15 has the best 7-day return
    c = np.full((S, T), 10.0)
    hh = np.full((S, T), 11.0)
    ll = np.full((S, T), 9.0)
    c[15, 2:] = 12.0                                                  # breaks out on day 2 and stays above
    c[0, 3] = 8.0                                                     # worst 7-day return breaks down on day 3
    cond = AP._p4_cond(trad, r7, c, hh, ll, 5, 1)
    assert cond[15].tolist() == [False, False, True, True, True]
    ev = AP._event(cond, trad, np.zeros((S, T), np.int64))
    assert ev[15].tolist() == [False, False, True, False, False]
    cs = AP._p4_cond(trad, r7, c, hh, ll, 5, -1)
    assert cs[0].tolist() == [False, False, False, True, False]
    assert not AP._p4_cond(trad, r7, c, hh, ll, 6, 1).any()           # 16 < 3 x 6 symbols with a 7-day return
    r7t = r7.copy()
    r7t[10:15] = r7[15, 0]                                            # ties: symbol order decides (10..14 first)
    assert not AP._p4_cond(trad, r7t, c, hh, ll, 5, 1)[15].any()


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
    assert 0.70 < p < 0.80                                            # P(mean <= 0) = 3/4 for two months
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
    pools = mk.control_pools()
    b = AP.ctrl_b(mk, s, AP.ctrl_seed("b", v["id"], "p2", 0.02, 0), pools)
    for sym in np.unique(s.sym):
        n_pick = int((s.sym == sym).sum())
        got = b.day[b.sym == sym]
        assert len(got) == min(n_pick, len(pools[sym])) and len(set(got.tolist())) == len(got)
        assert set(got.tolist()) <= set(pools[sym].tolist())
        assert (b.side[b.sym == sym] == 1).all()
    t = pools[int(s.sym[0])]
    assert mk.trad[int(s.sym[0]), t].all() and mk.bar[int(s.sym[0]), t + 1].all()
    assert (t >= mk.p0).all() and (t <= mk.p1 - 2).all()
    assert np.array_equal(np.lexsort((b.sym, -mk.med7[b.sym, b.day], b.day)), np.arange(len(b)))


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
    return AP.Sub(off, arr[0], arr[1], arr[2], arr[3], arr[4], arr[5], nb, fe_off, fe_cnt,
                  np.asarray(fs, np.int64), np.asarray(fr, float), np.asarray(fm, float), 1 if fund is not None else 0,
                  1)


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
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM, sub=sub)
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
    # funding at slot 1 of day 41: +0.1% paid by the long on notional at mark 100; then mark wicks to 90 on day 42
    sub = _sub_from_slots(mk, slots, 2, fund={((i, t41), 1): (0.001, 100.0)},
                          mark={((i, local(mk, 42)), 1): (100, 100.5, 90.0)})
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM, sub=sub)
    assert out.rf[0, AP.R_FUND] == pytest.approx(0.001 * 5 * 100)
    assert out.ri[0, AP.RI_REASON] == AP.EX_LIQ and out.ri[0, AP.RI_TOUT] == local(mk, 42)
    out_s = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", -1)]), VM, sub=_sub_from_slots(
        mk, slots, 2, fund={((i, t41), 1): (0.001, 100.0)}))
    assert out_s.rf[0, AP.R_FUND] == pytest.approx(-0.001 * 5 * 100)  # a short receives a positive rate


def test_pass2_missing_5m_closes_at_last_daily_close():
    after = [(100, 100.5, 99.5, 100), (100, 100.5, 99.5, 101), (101, 101.5, 100.5, 101)]
    mk, _ = one_pos({}, after)
    slots = {(0, t): [(mk.o[0, t], mk.h[0, t], mk.l[0, t])] for t in range(mk.T) if mk.bar[0, t]}
    del slots[(0, local(mk, 42))]
    out = AP.run_account(mk, sig(mk, [(39, "AAAUSDT", 1)]), VM, sub=_sub_from_slots(mk, slots, 1))
    assert out.ri[0, AP.RI_REASON] == AP.EX_MISS and out.rf[0, AP.R_XPX] == pytest.approx(101 * (1 - SLIP))


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
    sub, missing = AP.load_sub5m(mk, cache, ["AAAUSDT"])
    t = local(mk, 59)
    x = sub.off[0, t]
    assert x >= 0 and sub.nb == 288 and sub.o[x + 1] == pytest.approx(1.001, rel=1e-6) and np.isnan(sub.o[x + 3])
    assert sub.fe_cnt[0, t] == 1 and sub.fe_slot[sub.fe_off[0, t]] == 96
    assert "AAAUSDT 2021-02" in missing
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
    assert row["caps"] == {"n_max": 3, "risk_cap": pytest.approx(0.6)}
    assert board[picks[0]]["p1"]["r=0.02"]["label"] == "chosen here"
    AP._write_json(os.path.join(str(tmp_path), "t.json"), {"select": table, "test": res, "board": board})
