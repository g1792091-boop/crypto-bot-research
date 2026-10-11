"""research/hunt/hunt.py: the trend-hunt machine (PREREG_HUNT 7-13, PREREG_HUNT_WIDE 2-7, 10). Synthetic bars only.

- intrabar order H 7.6: liquidation at the open, gap through the stop, stop before add, add then the moved stop hit in
  the same bar, gapped add, short mirror
- add-stop formula H 7.4 (P0, P0 + 0.667 D0, P0 + 1.25 D0), chandelier H 7.5 (never loosens, from the next bar)
- leverage choice H 7.3, caps H 8 (6 positions, 3 / 3 large group, total open risk), liquidity cut, min notional
- funding sign H 2, month marking and bust H 10, coin end, accounting identity
- signal -> candidate mapping (fill bar, D0 by timeframe, chandelier start), both-sides bars, same-close order
- controls (deterministic seeds), bootstrap p, seed rank, Benjamini-Hochberg, selection rules (v1 and wide), the
  scaled risk cap of the sizing read, refusal without a pin
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import types

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402

FIVE = H.FIVE
DAY = H.DAY_MS
START = H.day_ms("2022-03-01")
SLIP, TAKER = H.COSTS["base"][1], H.COSTS["base"][0]


# ------------------------------------------------------------------ synthetic helpers
def coin(sym, bars, start=START, n_before=288, base=100.0, qv=1e9, pad_to=None, last_ms=None):
    """``n_before`` flat bars at ``base`` before ``start``, then ``bars`` [(o, h, l, c)], then (``pad_to`` steps) flat
    bars at the last close."""
    bars = list(bars)
    if pad_to is not None and len(bars) < pad_to:
        c = bars[-1][3] if bars else base
        bars += [(c, c, c, c)] * (pad_to - len(bars))
    pre = [(base, base, base, base)] * n_before
    allb = np.asarray(pre + bars, float).reshape(-1, 4)
    n = len(allb)
    ts = start - n_before * FIVE + np.arange(n, dtype=np.int64) * FIVE
    q = np.full(n, float(qv))
    return H.Coin(sym, ts, allb[:, 0], allb[:, 1], allb[:, 2], allb[:, 3], q / allb[:, 3], q, last_ms=last_ms)


def market(coins: dict, days=1, funding=None, start=START):
    H.install(coins, funding or {})
    return H.Market(list(coins), (start, start + days * DAY), name="t")


def no_bank():
    return types.SimpleNamespace(s_ct=np.zeros(0, np.int64), s_h=np.zeros(0), s_l=np.zeros(0), s_atr=np.zeros(0))


def bank(ct, hh, ll, atr):
    return types.SimpleNamespace(s_ct=np.asarray(ct, np.int64), s_h=np.asarray(hh, float),
                                 s_l=np.asarray(ll, float), s_atr=np.asarray(atr, float))


def cands(mk, rows):
    """rows: dicts k, t, side, d0 (+ s0, s1 into the bank)."""
    c = {x: [] for x in ("t", "bi", "coin", "side", "d0", "s0", "s1", "prio", "src")}
    for r in rows:
        k = r["k"]
        seg = mk.b_t[mk.b_off[k]:mk.b_off[k + 1]]
        i = int(np.searchsorted(seg, r["t"]))
        assert seg[i] == r["t"]
        c["t"].append(r["t"])
        c["bi"].append(mk.b_off[k] + i)
        c["coin"].append(k)
        c["side"].append(r.get("side", 1))
        c["d0"].append(r.get("d0", 2.0))
        c["s0"].append(r.get("s0", 0))
        c["s1"].append(r.get("s1", 0))
        c["prio"].append(r.get("prio", 0.0))
        c["src"].append(0)
    return {x: np.asarray(v, np.float64 if x in ("d0", "prio") else np.int64) for x, v in c.items()}


def prm(**over):
    p = H.params()
    names = {"r": H.PR_R, "cap": H.PR_CAP, "bdiv": H.PR_BDIV, "adds": H.PR_NADDS, "bust": H.PR_BUST,
             "taker": H.PR_TAKER, "slip": H.PR_SLIP}
    for k, v in over.items():
        p[names[k]] = v
    return p


def sim(mk, rows, b=None, **over):
    return H.simulate(mk, b or no_bank(), cands(mk, rows), prm=prm(**over))


def rec(out, i=0):
    rf, ri = out[3], out[4]
    return rf[i], ri[i]


# ------------------------------------------------------------------ H 7.6 order inside a 5m bar
def test_stop_at_level_exact_pnl():
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.5, 99.5, 100), (100, 100.2, 97.5, 97.8)], pad_to=288)})
    out = sim(mk, [{"k": 0, "t": 0}])
    rf, ri = rec(out)
    q = 0.005 * 5000 / 2.0
    fill, xf = 100 * (1 + SLIP), 98 * (1 - SLIP)
    want = q * (xf - fill) - TAKER * q * (fill + xf)
    assert ri[H.RI_REASON] == H.EX_STOP and ri[H.RI_TOUT] == 1 and ri[H.RI_ADDS] == 0
    assert rf[H.RF_LEV] == 6                                  # N4 = 5000, B = 833.3 -> L = 6 (H 7.3)
    assert rf[H.RF_PNL] == pytest.approx(want, rel=1e-9)
    assert out[10][4] == pytest.approx(5000 + want, rel=1e-12)    # final equity


def test_gap_through_stop_exits_at_open():
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.5, 99.5, 100), (97, 97.5, 96.5, 97)], pad_to=288)})
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0}]))
    assert ri[H.RI_REASON] == H.EX_GAP
    assert rf[H.RF_XPX] == pytest.approx(97 * (1 - SLIP))


def test_liquidation_at_open_loses_whole_margin():
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.5, 99.5, 100), (80, 81, 79, 80)], pad_to=288)})
    out = sim(mk, [{"k": 0, "t": 0}])
    rf, ri = rec(out)
    q = 12.5
    margin = q * 100 * (1 + SLIP) / 6
    assert ri[H.RI_REASON] == H.EX_LIQ
    assert rf[H.RF_PRICE] == pytest.approx(-margin)
    assert rf[H.RF_PNL] == pytest.approx(-margin - TAKER * q * 100 * (1 + SLIP))


def test_add_comes_first_when_the_bar_reaches_a_level_and_the_old_stop():
    """H 7.6 step 4 (as reviewed): a bar reaching add level 102 and the old stop 98 adds first, then exits at the
    moved stop (P0 = 100), the worse order for the account."""
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.5, 99.5, 100.4), (100.4, 102.5, 97.9, 99)], pad_to=288)})
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0}]))
    assert ri[H.RI_REASON] == H.EX_STOP and ri[H.RI_ADDS] == 1 and ri[H.RI_TRIED] == 1 and ri[H.RI_TOUT] == 1
    assert ri[H.RI_SRC] == H.SRC_ADD
    assert rf[H.RF_XPX] == pytest.approx(100 * (1 - SLIP))
    q = 0.005 * 5000 / 2.0
    xf = 100 * (1 - SLIP)
    fills = (100 * (1 + SLIP), 102 * (1 + SLIP))
    want = sum(q * (xf - f) for f in fills) - TAKER * q * (sum(fills) + 2 * xf)
    assert rf[H.RF_PNL] == pytest.approx(want, rel=1e-9)
    assert rf[H.RF_PNL] < q * (98 * (1 - SLIP) - fills[0]) - TAKER * q * (fills[0] + 98 * (1 - SLIP))


def test_bar_reaching_no_add_level_exits_at_the_stop():
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.5, 99.5, 100.4), (100.4, 101.9, 97.9, 99)], pad_to=288)})
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0}]))
    assert ri[H.RI_REASON] == H.EX_STOP and ri[H.RI_ADDS] == 0 and ri[H.RI_TRIED] == 0
    assert rf[H.RF_XPX] == pytest.approx(98 * (1 - SLIP))


def test_short_add_comes_first_too():
    bars = [(100, 100.5, 99.5, 99.6), (99.6, 102.1, 97.5, 101)]
    mk = market({"AUSDT": coin("AUSDT", bars, pad_to=288)})
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0, "side": -1}]))
    assert ri[H.RI_ADDS] == 1 and ri[H.RI_TOUT] == 1 and rf[H.RF_XPX] == pytest.approx(100 * (1 + SLIP))


def test_add_then_moved_stop_hit_in_the_same_bar():
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.5, 99.5, 100.4), (100.4, 102.5, 99.9, 100.2)], pad_to=288)})
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0}], bdiv=5.5))
    assert ri[H.RI_ADDS] == 1 and ri[H.RI_REASON] == H.EX_STOP and ri[H.RI_TOUT] == 1
    assert ri[H.RI_SRC] == H.SRC_ADD
    assert rf[H.RF_XPX] == pytest.approx(100 * (1 - SLIP))         # moved stop = P0 after add 1


@pytest.mark.parametrize("n_adds,stop", [(2, 100 + 2 * 2 / 3), (3, 102.5)])
def test_add_stop_formula_full_units(n_adds, stop):
    """H 7.4: with full units the stop sits at P0, P0 + 0.667 D0, P0 + 1.25 D0 after adds 1, 2, 3 (P0 100, D0 2)."""
    bars = [(100, 100.5, 99.5, 100.4), (100.4, 102.5, 100.1, 102.3), (102.3, 104.5, 102.1, 104.2)]
    if n_adds == 3:
        bars.append((104.2, 106.5, 104.1, 106.2))
    bars.append((bars[-1][3], bars[-1][3] + 0.1, stop - 0.1, stop - 0.05))
    mk = market({"AUSDT": coin("AUSDT", bars, pad_to=288)})
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0}], bdiv=5.5))
    assert ri[H.RI_ADDS] == n_adds and ri[H.RI_REASON] == H.EX_STOP
    assert rf[H.RF_XPX] == pytest.approx(stop * (1 - SLIP), rel=1e-12)
    assert ri[H.RI_TOUT] == len(bars) - 1


def test_add_stop_after_one_add_is_p0():
    bars = [(100, 100.5, 99.5, 100.4), (100.4, 102.5, 100.1, 102.3), (102.3, 102.4, 99.95, 100.0)]
    mk = market({"AUSDT": coin("AUSDT", bars, pad_to=288)})
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0}], bdiv=5.5))
    assert ri[H.RI_ADDS] == 1 and rf[H.RF_XPX] == pytest.approx(100 * (1 - SLIP))


def test_gapped_add_fills_at_open_and_next_level_from_there():
    """Open beyond level 102 -> add at 103 (stop 100.5); level 2 = 105, so 104.6 adds nothing."""
    bars = [(100, 100.5, 99.5, 100.4), (103, 103.5, 102.8, 103.2), (103.2, 104.6, 103.0, 104.5),
            (104.5, 104.6, 100.4, 100.5)]
    mk = market({"AUSDT": coin("AUSDT", bars, pad_to=288)})
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0}], bdiv=5.5))
    assert ri[H.RI_ADDS] == 1 and ri[H.RI_TOUT] == 3
    assert rf[H.RF_XPX] == pytest.approx(100.5 * (1 - SLIP))


def test_short_mirror_add_and_stop():
    bars = [(100, 100.5, 99.5, 99.6), (99.6, 99.9, 97.5, 97.7), (97.7, 100.2, 97.6, 100.1)]
    mk = market({"AUSDT": coin("AUSDT", bars, pad_to=288)})
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0, "side": -1}], bdiv=5.5))
    assert ri[H.RI_SIDE] == -1 and ri[H.RI_ADDS] == 1 and ri[H.RI_TOUT] == 2
    assert rf[H.RF_XPX] == pytest.approx(100 * (1 + SLIP))          # short stop after add 1 = P0


def test_skipped_add_counts_as_filled_at_its_level():
    """B = equity / 100: no L meets (ii), so L = 18 (largest with (i) and (iii)), the first unit is cut to the budget
    and no add finds room. Levels 102, 104, 106 (a skipped add counts as filled at its level) are each tried once."""
    bars = [(100, 100.5, 99.5, 100.4), (100.4, 102.5, 100.1, 102.3), (102.3, 104.5, 102.1, 104.2),
            (104.2, 106.5, 104.1, 106.2), (106.2, 108.5, 106.1, 108.2)]
    mk = market({"AUSDT": coin("AUSDT", bars, pad_to=288)})
    out = sim(mk, [{"k": 0, "t": 0}], bdiv=100.0)
    rf, ri = rec(out)
    assert rf[H.RF_LEV] == 18 and ri[H.RI_CUT] & 2
    assert ri[H.RI_ADDS] == 0 and ri[H.RI_TRIED] == 3 and out[7][H.AS_MARGIN] == 3


# ------------------------------------------------------------------ H 7.5 chandelier
def test_chandelier_applies_from_next_bar_and_never_loosens():
    bars = [(100, 100.5, 99.5, 100), (100, 110, 106.5, 109), (108, 108.5, 107.5, 108), (107.8, 107.9, 106.9, 107)]
    mk = market({"AUSDT": coin("AUSDT", bars, pad_to=288)})
    b = bank([2, 3], [110, 105], [99, 99], [1.0, 10.0])          # signal bars closing at steps 2 and 3
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0, "s0": 0, "s1": 2}], b=b, adds=0))
    # step 1's low 106.5 is below 107 but the update (110 - 3 x 1) applies only from step 2;
    # step 3's update (110 - 3 x 10 = 80) would loosen and is ignored
    assert ri[H.RI_TOUT] == 3 and ri[H.RI_REASON] == H.EX_STOP and ri[H.RI_SRC] == H.SRC_CHAND
    assert rf[H.RF_XPX] == pytest.approx(107 * (1 - SLIP))


def test_chandelier_short():
    bars = [(100, 100.5, 99.5, 100), (100, 100.2, 90, 91), (91, 93.5, 90.5, 93)]
    mk = market({"AUSDT": coin("AUSDT", bars, pad_to=288)})
    b = bank([2], [101], [90], [1.0])
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0, "side": -1, "s0": 0, "s1": 1}], b=b, adds=0))
    assert ri[H.RI_TOUT] == 2 and rf[H.RF_XPX] == pytest.approx(93 * (1 + SLIP))


# ------------------------------------------------------------------ H 7.3 leverage
FB = H.load_brackets(["ZZZUSDT"])


@pytest.mark.parametrize("N4,B,d0,want", [(5000, 5000 / 6, 0.02, 6), (30000, 1000, 0.02, 10), (5000, 1000, 0.7, 0),
                                          (2000, 1000, 0.01, 2), (25000, 100, 0.02, 10), (600, 1000, 0.02, 1)])
def test_leverage_choice(N4, B, d0, want):
    assert FB["flags"]["ZZZUSDT"] == "fallback"
    L = H._choose_lev(float(N4), float(B), d0, 20, 1.5, FB["n"][0], FB["cap"][0], FB["lev"][0], FB["mmr"][0])
    assert L == want


def test_fallback_bracket_cum_is_continuous():
    cap, mmr, cum = FB["cap"][0], FB["mmr"][0], FB["cum"][0]
    for i in range(1, FB["n"][0]):
        lo = cap[i - 1]
        assert lo * mmr[i - 1] - cum[i - 1] == pytest.approx(lo * mmr[i] - cum[i])


# ------------------------------------------------------------------ H 8 caps, H 7.2 cuts
def test_six_positions_cap():
    mk = market({f"C{i}USDT": coin(f"C{i}USDT", [(100, 100.5, 99.5, 100)], pad_to=288) for i in range(7)})
    out = sim(mk, [{"k": i, "t": 0} for i in range(7)])
    assert len(out[4]) == 6 and out[5][H.SK_SIX] == 1


def test_large_group_direction_cap():
    mk = market({f"C{i}USDT": coin(f"C{i}USDT", [(100, 100.5, 99.5, 100)], pad_to=288) for i in range(5)})
    mk.large[:] = 1
    out = sim(mk, [{"k": i, "t": 0} for i in range(4)] + [{"k": 4, "t": 0, "side": -1}])
    sides = out[4][:, H.RI_SIDE]
    assert (sides > 0).sum() == 3 and (sides < 0).sum() == 1 and out[5][H.SK_DIR] == 1


def test_total_open_risk_cap_binds_at_one_percent():
    mk = market({f"C{i}USDT": coin(f"C{i}USDT", [(100, 100.5, 99.5, 100)], pad_to=288) for i in range(6)})
    out = sim(mk, [{"k": i, "t": 0} for i in range(6)], r=0.01)
    assert len(out[4]) == 4 and out[5][H.SK_RISK] == 2                # 4 x 1% = 4%


def test_risk_cap_does_not_bind_at_half_percent():
    mk = market({f"C{i}USDT": coin(f"C{i}USDT", [(100, 100.5, 99.5, 100)], pad_to=288) for i in range(6)})
    out = sim(mk, [{"k": i, "t": 0} for i in range(6)])
    assert len(out[4]) == 6 and out[5][H.SK_RISK] == 0


def test_coin_with_position_ignores_new_event():
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.5, 99.5, 100)] * 3, pad_to=288)})
    out = sim(mk, [{"k": 0, "t": 0}, {"k": 0, "t": 2, "side": -1}])
    assert len(out[4]) == 1 and out[5][H.SK_BUSY] == 1


def test_liquidity_cut_and_min_notional():
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.5, 99.5, 100)], pad_to=288, qv=1000.0),
                 "BUSDT": coin("BUSDT", [(100, 100.5, 99.5, 100)], pad_to=288, qv=10.0)})
    out = sim(mk, [{"k": 0, "t": 0}, {"k": 1, "t": 0}])
    rf, ri = rec(out)
    assert ri[H.RI_CUT] & 1 and rf[H.RF_Q1] == pytest.approx(0.001 * 288 * 1000 / 100)
    assert out[6][H.CUT_LIQ] == 2 and out[5][H.SK_MINNOT] == 1 and len(out[4]) == 1


# ------------------------------------------------------------------ funding, months, bust, coin end
@pytest.mark.parametrize("side", [1, -1])
def test_funding_sign(side):
    rate = 0.001
    calc = np.asarray([START + 10 * FIVE + 7, START + 3 * FIVE], np.int64)    # end of bar 9; before the entry
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.2, 99.8, 100)] * 20, pad_to=288)},
                funding={"AUSDT": (calc, np.asarray([rate, rate]))})
    rf, ri = rec(sim(mk, [{"k": 0, "t": 5, "side": side}]))
    assert rf[H.RF_FUND] == pytest.approx(-side * rate * 12.5 * 100)     # long pays a positive rate, short gets it


def test_funding_at_entry_open_not_charged():
    calc = np.asarray([START + 5 * FIVE], np.int64)                  # = the open of the entry bar
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.2, 99.8, 100)] * 20, pad_to=288)},
                funding={"AUSDT": (calc, np.asarray([0.01]))})
    rf, _ = rec(sim(mk, [{"k": 0, "t": 5}]))
    assert rf[H.RF_FUND] == 0.0


def test_month_marking_to_market():
    start = H.day_ms("2022-01-31")
    bars = [(100, 100.5, 99.5, 100)] + [(100 + 0.01 * i, 100 + 0.01 * i + 0.05, 100 + 0.01 * i - 0.05,
                                         100 + 0.01 * (i + 1)) for i in range(1, 576)]
    mk = market({"AUSDT": coin("AUSDT", bars, start=start)}, days=2, start=start)
    assert mk.months == ["2022-01", "2022-02"]
    out = sim(mk, [{"k": 0, "t": 0, "d0": 50.0}])
    q = 25 / 50.0
    fill = 100 * (1 + SLIP)
    eq_jan = 5000 - TAKER * q * fill + q * (bars[287][3] - fill)
    eq_feb = 5000 - TAKER * q * fill + q * (bars[575][3] - fill)
    s = H.summarize(mk, out)
    assert out[0][0] == pytest.approx(eq_jan) and out[0][1] == pytest.approx(eq_feb)
    assert s["M"][0] == pytest.approx(eq_jan / 5000) and s["M"][1] == pytest.approx(eq_feb / eq_jan)
    assert s["open_at_end"] == 1 and s["exit_reasons"]["period_end_marked"] == 1
    assert len(s["day_eq"]) == 2 and s["day_eq"][0] == pytest.approx(eq_jan, rel=1e-6)


def test_bust_closes_positions_and_freezes_later_months():
    start = H.day_ms("2022-01-31")
    cs = {}
    for i in range(6):
        b1 = (50, 51, 49, 50) if i < 5 else (100, 100.1, 99, 99)
        cs[f"C{i}USDT"] = coin(f"C{i}USDT", [(100, 100.5, 99.5, 100), b1], start=start, pad_to=576)
    mk = market(cs, days=2, start=start)
    out = sim(mk, [{"k": i, "t": 0} for i in range(6)], r=0.5, cap=10.0, bust=0.2)
    s = H.summarize(mk, out)
    reasons = out[4][:, H.RI_REASON]
    assert s["bust"] and s["bust_month"] == "2022-01"
    assert (reasons == H.EX_LIQ).sum() == 5 and (reasons == H.EX_BUST).sum() == 1
    assert s["M"][1] == 1.0
    assert out[6][H.CUT_MARGIN] >= 5                                  # r = 50% units are cut to the budget


def test_coin_end_closes_at_its_last_close():
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.5, 99.5, 100)] * 10 + [(100, 100.4, 99.6, 100.3)]),
                 "BUSDT": coin("BUSDT", [(100, 100.5, 99.5, 100)], pad_to=288)})
    assert mk.coin_end_t[0] == 10 and mk.coin_end_t[1] == -1
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0}]))
    assert ri[H.RI_REASON] == H.EX_COINEND and ri[H.RI_TOUT] == 10
    assert rf[H.RF_XPX] == pytest.approx(100.3 * (1 - SLIP))


def test_entry_decided_on_previous_close_state():
    """A position that stops out at step 1 still blocks a new event on its coin filling at step 1 (H 8, CHOICES)."""
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.5, 99.5, 100), (100, 100.2, 97.5, 97.8)], pad_to=288)})
    out = sim(mk, [{"k": 0, "t": 0}, {"k": 0, "t": 1, "side": -1}])
    assert len(out[4]) == 1 and out[5][H.SK_BUSY] == 1


# ------------------------------------------------------------------ signals -> candidates (real bars code)
def _wave_coin(sym, days, start, seed):
    rng = np.random.default_rng(seed)
    n = days * 288
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.001
    lo = np.minimum(o, c) * 0.999
    ts = start + np.arange(n, dtype=np.int64) * FIVE
    return H.Coin(sym, ts, o, h, lo, c, np.full(n, 1e6), np.full(n, 1e8))


@pytest.mark.parametrize("tf", ["15m", "30m", "1h", "4h"])
def test_signal_to_candidate_mapping(tf, monkeypatch):
    s0 = H.day_ms("2022-03-01")
    coins = {"AUSDT": _wave_coin("AUSDT", 6, s0, 1), "BUSDT": _wave_coin("BUSDT", 6, s0, 2)}
    H.install(coins)
    mk = H.Market(list(coins), (s0 + 3 * DAY, s0 + 5 * DAY), name="t")
    ser = H.series("AUSDT", tf)
    cm = ser.bars.close_ms
    inside = np.flatnonzero((cm >= mk.start) & (cm < mk.end))
    j_long, j_both = int(inside[3]), int(inside[5])
    before = int(np.flatnonzero(cm < mk.start)[-1])

    def fake(spec, sym, s, btc):
        lg = np.zeros(len(s.bars), bool)
        sh = np.zeros(len(s.bars), bool)
        if sym == "AUSDT":
            lg[[j_long, j_both, before]] = True
            sh[j_both] = True
        return lg, sh
    monkeypatch.setattr(H, "entry_events", fake)
    spec = {"id": "x", "family": "F2", "name": "X", "kind": "core", "tf": tf, "gate": "NONE", "combo": {}}
    sig = H.system_signals(mk, spec)
    assert sig["counts"]["both"] == 1 and list(sig["j"]) == [j_long] and list(sig["side"]) == [1]
    b = H.bank_for(mk, (tf,))
    c = H.build_cands(mk, b, [(sig, 0)])
    assert c["t"][0] == (cm[j_long] - mk.start) // FIVE                     # fill at the next 5m open
    assert c["d0"][0] == pytest.approx(H.D0_MULT[tf] * ser.atr[j_long])     # 2 x ATR14 (15m-1h), 1.5 x (4h)
    assert H.D0_MULT[tf] == (1.5 if tf == "4h" else 2.0)
    assert mk.b_t[c["bi"][0]] == c["t"][0] and mk.b_off[0] <= c["bi"][0] < mk.b_off[1]
    # chandelier starts at the bin holding the fill bar: its close is the first close after the fill
    assert b.s_ct[c["s0"][0]] * FIVE + mk.start == cm[j_long] + H.TF_MS[tf]
    a, e, lo = b.off[(tf, 0)]
    assert c["s1"][0] == e
    # G1 on these short series: no 장세 label is known yet -> nothing passes
    assert len(H.system_signals(mk, {**spec, "gate": "G1"})["k"]) == 0


def test_same_close_order_by_volume_then_pick():
    c = {"t": np.array([5, 5, 5, 3]), "prio": np.array([1.0, 9.0, 9.0, 0.0]), "src": np.array([2, 2, 1, 1]),
         "coin": np.array([0, 1, 2, 3]), "x": np.array([10, 11, 12, 13])}
    s = H.sort_cands(c)
    assert list(s["x"]) == [13, 12, 11, 10]


def test_accounting_identity_on_random_run(monkeypatch):
    """Final equity = start + sum of every position's net P&L (price P&L - fees + funding), marked at the end."""
    s0 = H.day_ms("2022-03-01")
    coins = {f"C{i}USDT": _wave_coin(f"C{i}USDT", 12, s0, 10 + i) for i in range(8)}
    fts = np.arange(s0, s0 + 12 * DAY, 8 * 3_600_000, dtype=np.int64)
    fund = {s: (fts, np.random.default_rng(i).normal(0.0002, 0.0005, len(fts))) for i, s in enumerate(coins)}
    H.install(coins, fund)
    mk = H.Market(list(coins), (s0 + 4 * DAY, s0 + 12 * DAY), name="t")
    mk.large[:, :4] = 1

    def fake(spec, sym, s, btc):
        rng = np.random.default_rng(int(sym[1:-4]))
        lg = rng.random(len(s.bars)) < 0.08
        sh = rng.random(len(s.bars)) < 0.08
        return lg, sh
    monkeypatch.setattr(H, "entry_events", fake)
    spec = {"id": "y", "family": "F2", "name": "Y", "kind": "core", "tf": "15m", "gate": "NONE", "combo": {}}
    sig = H.system_signals(mk, spec)
    b = H.bank_for(mk, ("15m",))
    c = H.build_cands(mk, b, [(sig, 0)])
    for r in (0.005, 0.05):
        out = H.simulate(mk, b, c, r=r, risk_cap=0.04 * r / 0.005)
        assert len(out[4]) > 5
        assert out[10][4] == pytest.approx(5000 + out[3][:, H.RF_PNL].sum(), rel=1e-9)
        s = H.summarize(mk, out)
        assert np.prod(s["M"]) == pytest.approx(s["end_multiple"], rel=1e-9)
        assert s["n_positions"] == len(out[4]) and sum(s["positions_by_month"]) == len(out[4])


# ------------------------------------------------------------------ controls, statistics (H 12, H 13, W 6)
def _sig():
    return {"tf": "1h", "k": np.array([0, 0, 0, 1, 1]), "j": np.array([10, 20, 30, 5, 6]),
            "side": np.array([1, 1, -1, -1, -1])}


def test_control_seeds_deterministic(monkeypatch):
    monkeypatch.setattr(H, "control_pool", lambda mk, tf, k: np.arange(100, 160) + 1000 * k)
    mk = types.SimpleNamespace(K=2)
    parts = H.control_seed_parts("wide", {"id": "F2:X:1h:G1"}, "a", "test", 0.005, 7)
    assert parts == ("hunt-wide", "F2:X:1h:G1", "a", "test", 0.005, 7)
    a1 = H.control_a(mk, _sig(), H.rng_of(*parts))
    a2 = H.control_a(mk, _sig(), H.rng_of(*parts))
    a3 = H.control_a(mk, _sig(), H.rng_of(*parts[:-1], 8))
    assert all(np.array_equal(a1[x], a2[x]) for x in ("k", "j", "side"))
    assert not np.array_equal(a1["j"], a3["j"])
    for k, nl, ns in ((0, 2, 1), (1, 0, 2)):                       # same count per coin and side
        sel = a1["k"] == k
        assert (a1["side"][sel] > 0).sum() == nl and (a1["side"][sel] < 0).sum() == ns
        assert len(set(a1["j"][sel])) == sel.sum()                  # without replacement, never both sides
    b1 = H.control_b(_sig(), H.rng_of("hunt", "b", "test", 0.005, 1))
    b2 = H.control_b(_sig(), H.rng_of("hunt", "b", "test", 0.005, 1))
    assert np.array_equal(b1["side"], b2["side"]) and np.array_equal(b1["j"], _sig()["j"])
    assert H.seed_int("hunt", "a", "test", 0.005, 1) == int.from_bytes(
        hashlib.sha256(b"hunt|a|test|0.005|1").digest()[:8], "little")


def test_bootstrap_p_formula():
    assert H.boot_p(np.full(33, 0.01), 1) == pytest.approx(1 / 10001)
    assert H.boot_p(np.full(33, -0.01), 1) == pytest.approx(1.0)
    d = np.random.default_rng(5).normal(0.01, 0.05, 33)
    rng = np.random.Generator(np.random.PCG64(123))
    means = d[rng.integers(0, 33, size=(10000, 33))].mean(axis=1)
    assert H.boot_p(d, 123) == pytest.approx((1 + (means <= 0).sum()) / 10001)


def test_seed_rank():
    assert H.seed_rank_p(0.5, np.zeros(100)) == pytest.approx(1 / 101)
    assert H.seed_rank_p(0.0, np.zeros(100)) == pytest.approx(1.0)
    s = np.arange(100) / 100
    assert H.seed_rank_p(0.955, s) == pytest.approx(5 / 101)        # 4 seeds >= pick: rank part passes
    assert H.seed_rank_p(0.945, s) == pytest.approx(6 / 101)


def test_benjamini_hochberg():
    assert H.bh([0.01, 0.02, 0.03, 0.04, 0.2], 0.10) == [True, True, True, True, False]
    assert H.bh([0.5, 0.04], 0.10) == [False, True]
    assert H.bh([0.2, 0.3], 0.10) == [False, False]
    assert H.bh([None, 0.001], 0.10) == [False, True]
    assert H.bh([0.06, 0.07, 0.08, 0.09, 0.1, 0.5, 0.5, 0.5, 0.5, 0.5], 0.10) == [False] * 10
    assert H.bh([0.009, 0.5, 0.019], 0.10) == [True, False, True]   # 0.019 <= 0.1 x 2/3


def test_judge_p2_split_and_checks():
    base = {"months": 3, "lnM": [0.1, 0.1, 0.1], "n_positions": 6, "share_months_with_position": 1.0,
            "bust": False, "median_M": 1.1, "mean_lnM": 0.1, "max_dd": 0.2}
    cost2 = {"median_M": 1.05, "mean_lnM": 0.02}
    ctl = {"a": np.zeros((100, 3)), "b": np.full((100, 3), 0.2)}
    j = H.judge(base, cost2, ctl, "wide", {"id": "F1:E1:1h:G1"}, "test", 0.005)
    assert j["P0"] and j["P1"] and j["P3"] and j["P4"]
    assert j["P2_a"] and j["rank_ok_a"] and not j["P2_b"] and not j["rank_ok_b"]
    assert j["p"] == max(j["p_a"], j["p_b"]) and j["p_b"] == 1.0


def test_p3_needs_mean_ln_m_above_zero_at_cost_x2():
    """H 13 P3 (as reviewed): cost x2 median monthly multiple >= 1.0 AND mean monthly ln M > 0."""
    base = {"months": 3, "lnM": [0.1, 0.1, 0.1], "n_positions": 6, "share_months_with_position": 1.0,
            "bust": False, "median_M": 1.1, "mean_lnM": 0.1, "max_dd": 0.2}
    assert not H.judge(base, {"median_M": 1.0, "mean_lnM": -0.01}, None, "v1", {}, "test", 0.005)["P3"]
    assert not H.judge(base, {"median_M": 0.99, "mean_lnM": 0.05}, None, "v1", {}, "test", 0.005)["P3"]
    assert H.judge(base, {"median_M": 1.0, "mean_lnM": 0.001}, None, "v1", {}, "test", 0.005)["P3"]


# ------------------------------------------------------------------ selection (H 11.2, W 5)
def _row(i, name, score, fam="F2", tf="1h", gate="G1", eligible=True, med=1.0, rank=None):
    return {"id": f"{fam}:{name}:{tf}:{gate}" + (f":r{rank}" if rank else ""), "family": fam, "name": name,
            "strategy": name, "tf": tf, "gate": gate, "eligible": eligible, "score": score, "median_M": med,
            "rank": rank}


def test_wide_choose_one_per_name_and_order():
    rows = [_row(0, "A", 0.05), _row(1, "A", 0.06, tf="4h"), _row(2, "B", 0.04), _row(3, "C", 0.07, eligible=False),
            _row(4, "D", 0.04, fam="F1", med=1.0), _row(5, "DOGE", 0.03, fam="F4", tf="15m", rank=1),
            _row(6, "DOGE", 0.02, fam="F2"), _row(7, "E", 0.04, med=1.2)]
    ch = H.wide_choose(rows, k_picks=10)
    assert ch["label"] == "picks"
    # A once (its 4h), then ties at 0.04: higher median (E), then family F1 (D) before F2 (B); the F4 DOGE row is a
    # read only (W 5), so DOGE enters through its F2 row
    assert ch["picks"] == ["F2:A:4h:G1", "F2:E:1h:G1", "F1:D:1h:G1", "F2:B:1h:G1", "F2:DOGE:1h:G1"]
    assert ch["batches"] == [ch["picks"]]
    # owners 2026-10-11 (b): batches of K fixed at select (1군, 2군, 3군), one per name over the whole walk
    two = H.wide_choose(rows, k_picks=2)
    assert two["picks"] == ["F2:A:4h:G1", "F2:E:1h:G1", "F1:D:1h:G1", "F2:B:1h:G1", "F2:DOGE:1h:G1"]
    assert two["batches"] == [["F2:A:4h:G1", "F2:E:1h:G1"], ["F1:D:1h:G1", "F2:B:1h:G1"], ["F2:DOGE:1h:G1"]]
    assert H.wide_choose(rows, k_picks=2, n_batches=1)["picks"] == ["F2:A:4h:G1", "F2:E:1h:G1"]
    none = H.wide_choose([_row(0, "A", -0.1, eligible=False), _row(1, "B", -0.05, eligible=False)])
    assert none == {"picks": ["F2:B:1h:G1"], "batches": [["F2:B:1h:G1"]], "label": "no pick, fail"}


def test_f4_is_never_a_pick_nor_the_fallback():
    """W 5 (review finding: the watch picks' numbers were chosen after the test period was seen): an F4 row is never a
    pick, also when it scores best, and never the 'no pick' fallback."""
    rows = [_row(0, "DOGE", 0.30, fam="F4", tf="15m", rank=1), _row(1, "X", 0.01)]
    assert H.wide_choose(rows)["picks"] == ["F2:X:1h:G1"]
    only_f4 = [_row(0, "DOGE", 0.30, fam="F4", tf="15m", rank=1)]
    assert H.wide_choose(only_f4) == {"picks": [], "batches": [], "label": "no pick, fail"}
    none = H.wide_choose([_row(0, "DOGE", 0.3, fam="F4", eligible=False, rank=1), _row(1, "B", -0.5, eligible=False)])
    assert none["picks"] == ["F2:B:1h:G1"]
    assert H.PICK_FAMILIES == ("F1", "F2", "F3", "F5")
    # F5 (the famous trend rules) are candidates; ties: F1 < F2 < F3 < F5
    f5 = [_row(0, "TURTLE20", 0.02, fam="F5"), _row(1, "B", 0.02)]
    assert H.wide_choose(f5)["picks"] == ["F2:B:1h:G1", "F5:TURTLE20:1h:G1"]


def test_wide_eligible():
    base = {"n_positions": 72, "months": 36, "mean_lnM": 0.01, "bust": False}
    assert H.wide_eligible(base, {"mean_lnM": 0.001}) == (True, [])
    assert H.wide_eligible({**base, "n_positions": 71}, {"mean_lnM": -0.1}) == (False, ["positions", "cost_x2"])


def test_v1_choose_plateau():
    def s(med, mean, n=80, bust=False):
        return {"median_M": med, "mean_lnM": mean, "n_positions": n, "months": 36, "bust": bust}
    rows = {}
    for i, spec in enumerate(H.v1_systems()):
        rows[spec["id"]] = {"main": s(1.0, -0.01), "lo": s(1.0, 0), "hi": s(1.0, 0), "one": s(1, 0)}
    rows["v1:E2:4h"] = {"main": s(1.02, 0.01), "lo": s(1.03, 0.0), "hi": s(0.5, 0.0, bust=True), "one": s(1, 0)}
    rows["v1:E1:1h"] = {"main": s(1.01, 0.02), "lo": s(1.01, 0.0), "hi": s(1.01, 0.0), "one": s(1, 0)}
    ch = H.v1_choose(rows)
    # E2-4h plateau = median(1.02, 1.03, 0 [bust]) = 1.02 > E1-1h 1.01
    assert ch["pick"] == "v1:E2:4h" and ch["label"] == "pick"
    for k in rows:
        rows[k]["main"]["mean_lnM"] = -0.01
    assert H.v1_choose(rows)["label"] == "no pick, fail"


def test_sizing_read_scales_the_risk_cap(monkeypatch):
    seen = []

    def fake(mk, parts, r, cost, risk_cap, detail=False, days=None, b_div=H.B_DIV):
        seen.append((r, risk_cap, b_div, detail))
        return {"mean_lnM": 0.0}
    monkeypatch.setattr(H, "run_signals", fake)
    out = H._sizing(None, [])
    assert seen == [(0.02, pytest.approx(0.16), pytest.approx(1.5), True),
                    (0.05, pytest.approx(0.40), pytest.approx(0.6), True)]
    assert out["0.05"]["margin_budget_of_equity"] == pytest.approx(10 / 6) and out["0.02"]["requested_r"] == 0.02


def test_sizing_read_takes_the_bet_it_names():
    """W 7 (review finding: with B = equity / 6 a '5%' bet was cut to under 1% and lost its adds). One coin, D0 = 1%
    of P0 at 4% wide stops: the first unit's realized risk is the requested r as far as the free wallet allows, and it
    is reported."""
    bars = [(100, 100.5, 99.5, 100.4)] + [(100.4, 100.6, 100.2, 100.4)] * 3
    mk = market({"AUSDT": coin("AUSDT", bars, pad_to=288)})
    raw = H.simulate(mk, no_bank(), cands(mk, [{"k": 0, "t": 0, "d0": 4.0}]), r=0.02, risk_cap=0.16,
                     b_div=H.B_DIV / 4)
    s = H.summarize(mk, raw, detail=False)
    assert s["realized_unit_risk"]["median"] == pytest.approx(0.02, rel=1e-9) and s["share_first_unit_cut"] == 0.0
    old = H.summarize(mk, H.simulate(mk, no_bank(), cands(mk, [{"k": 0, "t": 0, "d0": 4.0}]), r=0.02,
                                     risk_cap=0.16), detail=False)
    assert old["realized_unit_risk"]["median"] == pytest.approx(0.02, rel=1e-9)    # wide stop: B = E / 6 fits too
    tight = H.summarize(mk, H.simulate(mk, no_bank(), cands(mk, [{"k": 0, "t": 0, "d0": 0.5}]), r=0.05,
                                       risk_cap=0.40), detail=False)
    assert tight["realized_unit_risk"]["median"] < 0.01 and tight["share_first_unit_cut"] == 1.0   # B = E / 6 cuts
    scaled = H.summarize(mk, H.simulate(mk, no_bank(), cands(mk, [{"k": 0, "t": 0, "d0": 0.5}]), r=0.05,
                                        risk_cap=0.40, b_div=H.B_DIV / 10), detail=False)
    assert scaled["realized_unit_risk"]["median"] > tight["realized_unit_risk"]["median"] * 2


def test_month_starts():
    a, b = H.day_ms("2021-01-01"), H.day_ms("2024-01-01")
    ms = H.month_starts(a, b)
    assert len(ms) == 37 and ms[0] == a and ms[-1] == b
    assert H.month_starts(H.day_ms("2022-01-31"), H.day_ms("2022-02-02"))[1] == H.day_ms("2022-02-01")


def test_clean_5m_drops_duplicates_zero_volume_off_grid():
    ts = np.array([0, FIVE, FIVE, 2 * FIVE, 2 * FIVE + 7, 3 * FIVE], np.int64)
    o = np.array([1, 2, 3, 4, 5, 6], float)
    qv = np.array([1, 1, 1, 0, 1, 1], float)
    (t, oo, *_), cnt = H.clean_5m(ts, o, o, o, o, qv, qv)
    assert list(t) == [0, FIVE, 3 * FIVE] and list(oo) == [1, 3, 6]          # duplicate: last kept
    assert cnt["duplicates"] == 1 and cnt["zero_volume"] == 1 and cnt["off_grid"] == 1


# ------------------------------------------------------------------ pin (W 10)
CODE_SHA = {f: H.sha256_file(os.path.join(H.HERE, f)) for f in H.PARITY_CODE}


def _good_json(f):
    """Pinned result files that say pass (H 2, W 8)."""
    sha5 = {s: f"{i:064x}" for i, s in enumerate(H.OLD_SIX)}
    if f == H.PARITY_REL:
        return {"pass": True, "adapter_5m": "hunt 5m files", "syms": list(H.OLD_SIX), "code": dict(CODE_SHA)}
    if f == H.DATA_CHECK_REL:
        return {"pass": True, "coins": {s: {"content_sha256": sha5[s], "mismatch_share": 0.0} for s in H.OLD_SIX}}
    if f == H.DATA_MANIFEST_REL:
        return {"content": {s: {"5m": sha5[s], "funding": None} for s in H.OLD_SIX}, "manifest": {"symbols": []}}
    return None


def _pin_tree(tmp_path, monkeypatch, study="wide", patch=None):
    root = tmp_path
    (root / "research" / "hunt").mkdir(parents=True)
    files = list(H.PREREGS[study]) + ["research/hunt/hunt.py", H.UNIVERSE_REL] + list(H.PIN_EXTRA[study])
    for f in files:
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        doc = _good_json(f)
        if doc is not None and patch and f in patch:
            doc.update(patch[f])
        (root / f).write_text(json.dumps(doc) if doc is not None else f"content of {f}\n")
    lines = [f"{H.sha256_file(str(root / f))}  {f}" for f in files]
    (root / H.PIN[study]).write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(H, "ROOT", str(root))
    monkeypatch.setattr(H, "hunt_modules", lambda: ["research/hunt/hunt.py"])
    monkeypatch.setattr(H, "signal_path_files", lambda study: [])
    return root


def test_pin_matches_and_refusals(tmp_path, monkeypatch):
    root = _pin_tree(tmp_path, monkeypatch)
    n = len(H.PIN_EXTRA["wide"]) + 4
    assert H.check_pin("wide", "select")["files"] == n
    with pytest.raises(H.PinError, match="not pinned"):
        H.check_pin("wide", "test")                                       # no picks line yet
    picks = root / H.PICKS_REL["wide"]
    picks.parent.mkdir(parents=True, exist_ok=True)
    picks.write_text("{}\n")
    H.append_picks_line("wide")
    assert H.check_pin("wide", "test")["files"] == n + 1
    with pytest.raises(H.PinError, match="already pinned"):
        H.check_pin("wide", "select")
    picks.write_text('{"changed": 1}\n')
    with pytest.raises(H.PinError, match="changed"):
        H.check_pin("wide", "test")


def test_pin_refuses_changed_or_unlisted(tmp_path, monkeypatch):
    root = _pin_tree(tmp_path, monkeypatch, "v1")
    (root / "research/hunt/hunt.py").write_text("edited\n")
    with pytest.raises(H.PinError, match="changed research/hunt/hunt.py"):
        H.check_pin("v1", "select")
    monkeypatch.setattr(H, "hunt_modules", lambda: ["research/hunt/hunt.py", "research/hunt/entries_wide.py"])
    with pytest.raises(H.PinError, match="not pinned research/hunt/entries_wide.py"):
        H.check_pin("v1", "select")


def test_pin_requires_the_prereg_file_list(tmp_path, monkeypatch):
    """W 10: the wide pin must list parity.json, the full grid's inputs and regime5y.py; exchange30.json when present."""
    root = _pin_tree(tmp_path, monkeypatch, "wide")
    pin = root / H.PIN["wide"]
    pin.write_text("".join(x + "\n" for x in pin.read_text().splitlines() if "parity.json" not in x))
    with pytest.raises(H.PinError, match="not pinned research/hunt/out/wide/parity.json"):
        H.check_pin("wide", "select")
    root = _pin_tree(tmp_path / "b", monkeypatch, "v1")
    (root / H.EXCHANGE_REL).write_text("{}")
    with pytest.raises(H.PinError, match="not pinned research/hunt/exchange30.json"):
        H.check_pin("v1", "select")


@pytest.mark.parametrize("study,patch,msg", [
    ("wide", {H.PARITY_REL: {"pass": False}}, "parity.json does not say pass"),
    ("wide", {H.PARITY_REL: {"adapter_5m": "1m archive -> 5m"}}, "not run on the hunt 5m files"),
    ("wide", {H.PARITY_REL: {"code": {**CODE_SHA, "entries_wide.py": "0" * 64}}}, "another research/hunt/entries_wide"),
    ("wide", {H.PARITY_REL: {"syms": ["BTCUSDT"]}}, "parity.json is not on the old six"),
    ("v1", {H.DATA_CHECK_REL: {"pass": False}}, "data_check.json does not say pass"),
    ("v1", {H.DATA_CHECK_REL: {"coins": {s: {"content_sha256": "f" * 64} for s in H.OLD_SIX}}},
     "checked other BTCUSDT data"),
])
def test_pin_refuses_result_files_that_do_not_pass(tmp_path, monkeypatch, study, patch, msg):
    """Review finding: parity.json (and the H 2 data check) were pinned by hash only; a failing, stale or 1m-path file
    was accepted. Now their content must say pass for the current code and data."""
    _pin_tree(tmp_path, monkeypatch, study, patch=patch)
    with pytest.raises(H.PinError, match=msg):
        H.check_pin(study, "select")


def test_pin_lists_cover_the_signal_path():
    """Review findings: the v1 pin lacked regime5y.py; the wide pin lacked research/deepseek200/lib_c.py and
    research/fullgrid/memo.py. Both are now required, and the signal-path scan (each entry cell run once on synthetic
    bars) finds every repository file the definitions load, the vendored indicator code included."""
    assert "paperbot/dash/tools/regime5y.py" in H.PIN_EXTRA["v1"]
    for f in ("research/deepseek200/lib_c.py", "research/fullgrid/memo.py", H.DATA_MANIFEST_REL, H.DATA_CHECK_REL):
        assert f in H.PIN_EXTRA["wide"]
    files = set(H.signal_path_files("wide"))
    for f in ("research/deepseek200/lib_c.py", "research/fullgrid/memo.py", "research/fullgrid/ds_defs.py",
              "research/fullgrid/run.py", "research/hunt/entries_wide.py", "paperbot/dash/tools/regime5y.py",
              "paperbot/sweepsig.py", "research/entry_study/param_defs/N17_KC_RSI.py",
              "third_party/sweep/harness/vendor/fg_indicators.py"):
        assert f in files, f
    assert not any(f.startswith("tests/") for f in files)
    assert {"research/hunt/entries_wide.py", "paperbot/dash/tools/regime5y.py"} <= set(H.signal_path_files("v1"))


def test_cli_refuses_without_pin(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(H, "ROOT", str(tmp_path))
    assert H.main(["select", "--study", "wide", "--data", str(tmp_path)]) == 2
    assert H.main(["test", "--study", "v1", "--data", str(tmp_path)]) == 2
    assert "refused" in capsys.readouterr().err


def test_ds_rows_are_redacted():
    rows = [{"id": "F3:F9_FVG:1h:G1", "kind": "ds", "score": 0.1, "median_M": 1.2, "eligible": True, "fail": [],
             "n_positions": 90, "win_share": 0.4, "max_dd": 0.3},
            {"id": "F2:N01:1h:G1", "kind": "core", "score": 0.1, "median_M": 1.2}]
    pub, priv = H.redact_rows(rows)
    assert "score" not in pub[0] and "median_M" not in pub[0] and "max_dd" not in pub[0]
    assert pub[0]["n_positions"] == 90 and pub[1]["score"] == 0.1 and priv[0]["score"] == 0.1


def test_private_file_must_be_outside_repo(tmp_path):
    args = types.SimpleNamespace(private=os.path.join(H.ROOT, "research"), data=None)
    with pytest.raises(SystemExit):
        H.write_private(args, "x.json", {})
    args = types.SimpleNamespace(private=str(tmp_path), data=None)
    h = H.write_private(args, "x.json", {"a": 1})
    assert h == H.sha256_file(str(tmp_path / "x.json"))


# ------------------------------------------------------------------ select -> test -> report, end to end (synthetic)
E2E_SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "AAAUSDT", "BBBUSDT", "CCCUSDT")


def _e2e_setup(tmp_path, monkeypatch, force_pass=False):
    a = H.day_ms("2019-12-01")
    full = {s: H.synth_coin(s, a, H.day_ms("2020-10-01"), 50 + i, 20.0 * (i + 1)) for i, s in enumerate(E2E_SYMS)}
    fts = np.arange(a, H.day_ms("2020-10-01"), 8 * 3_600_000, dtype=np.int64)
    loaded = {}

    def fake_data(args, end_key):
        end = H.day_ms(H.PERIODS[end_key][1])
        cs = {}
        for s, c in full.items():
            k = c.ts < end
            cs[s] = H.Coin(s, c.ts[k], c.o[k], c.h[k], c.l[k], c.c[k], c.v[k], c.qv[k])
        H.install(cs, {s: (fts[fts < end], np.full((fts < end).sum(), 0.0001)) for s in cs})
        loaded[end_key] = max(int(c.ts[-1]) for c in cs.values())
        return str(tmp_path / "data"), list(E2E_SYMS), {s: {} for s in E2E_SYMS}

    def fake_events(spec, sym, ser, btc):
        rng = np.random.default_rng(abs(int(hashlib.sha256(f"{spec['name']}{sym}".encode()).hexdigest()[:8], 16)))
        n = len(ser.bars)
        return rng.random(n) < 0.04, rng.random(n) < 0.04

    def spec(fam, name, kind, tf, gate):
        return {"id": f"{fam}:{name}:{tf}:{gate}", "family": fam, "name": name, "strategy": name, "kind": kind,
                "tf": tf, "gate": gate, "combo": {}}
    systems = [spec(f, n, k, tf, g) for f, n, k, tf in (("F1", "E1", "hunt", "1h"), ("F1", "E3", "hunt", "4h"),
                                                        ("F2", "X", "core", "1h"), ("F3", "F9_FVG", "ds", "4h"),
                                                        ("F2", "X", "core", "4h"), ("F5", "TURTLE20", "famous", "1h"))
               for g in ("G1", "NONE")]
    monkeypatch.setattr(H, "PERIODS", {"extra": ("2020-06-01", "2020-07-01"), "select": ("2020-07-01", "2020-08-01"),
                                       "test": ("2020-08-01", "2020-10-01")})
    monkeypatch.setattr(H, "N_SEEDS", 3)
    monkeypatch.setattr(H, "N_BOOT", 200)
    monkeypatch.setattr(H, "POS_PER_MONTH", 0)
    monkeypatch.setattr(H, "_universe_and_data", fake_data)
    monkeypatch.setattr(H, "entry_events", fake_events)
    monkeypatch.setattr(H, "wide_systems", lambda: systems)
    monkeypatch.setattr(H, "check_pin", lambda study, step: {"pin_file": "x", "pin_sha256": "0" * 64, "files": 0})
    monkeypatch.setattr(H, "append_picks_line", lambda study: "0" * 64)
    monkeypatch.setattr(H, "READS_MODULES", ())                 # the reads hook is tested with its own fake module
    monkeypatch.setattr(H._ew(), "fullgrid_pins", lambda: {})
    out = tmp_path / "out"
    monkeypatch.setattr(H, "OUT_REL", {"v1": str(out / "v1"), "wide": str(out / "wide")})
    monkeypatch.setattr(H, "PICKS_REL", {"v1": str(out / "v1" / "pick.json"), "wide": str(out / "wide" / "picks.json")})
    if force_pass:
        monkeypatch.setattr(H, "wide_eligible", lambda base, cost2: (True, []))
        real = H.judge

        def judge(*a, **k):
            j = real(*a, **k)
            for x in ("P0", "P1", "P3", "P4", "rank_ok_a", "rank_ok_b", "P2", "P2_a", "P2_b"):
                j[x] = True
            if "p" in j:
                j["p"] = 0.001
            return j
        monkeypatch.setattr(H, "judge", judge)
    return out, loaded


def test_end_to_end_wide(tmp_path, monkeypatch):
    out, loaded = _e2e_setup(tmp_path, monkeypatch, force_pass=True)
    priv = tmp_path / "private"
    assert H.main(["select", "--study", "wide", "--procs", "2", "--data", "x", "--private", str(priv)]) == 0
    assert loaded["select"] < H.day_ms("2020-08-01")                 # select reads no test bar
    sel = json.load(open(out / "wide" / "select.json"))
    assert len(sel["rows"]) == 12 and sel["label"] == "picks"
    ds = [r for r in sel["rows"] if r["kind"] == "ds"]
    assert ds and all("score" not in r and "median_M" not in r and "metrics" not in r for r in ds)       # D11
    core = [r for r in sel["rows"] if r["kind"] != "ds"]
    assert all({"by_year", "by_side", "by_group", "q75_lnM"} <= set(r["metrics"]) for r in core)         # H 10
    assert all("day_eq" not in r["metrics"] for r in core)
    parts = list((priv / "parts").glob("wide_select_*/cell_*.json"))
    assert len(parts) == 6                                       # one part per entry cell (resume)
    assert sel["private_sha256"] == H.sha256_file(str(priv / "wide_select_private.json"))
    pk = json.load(open(out / "wide" / "picks.json"))
    picks = pk["picks"]
    assert [p["pick_no"] for p in picks] == list(range(1, len(picks) + 1))
    assert len({p["strategy"] for p in picks}) == len(picks) == 5        # one per name: E1 E3 X F9_FVG TURTLE20
    # batch membership fixed in picks.json at select (W 5): 5 names -> batch 1 only
    assert pk["batches"] == [[1, 2, 3, 4, 5]] and all(p["batch"] == 1 for p in picks)
    assert pk["batch_trigger"] == 5 and pk["batch_size"] == 10 and pk["batch_labels"][:2] == ["1군", "2군"]
    assert all(p.get("note") == H.F5_NOTE for p in picks if p["family"] == "F5")
    assert H.main(["test", "--study", "wide", "--procs", "2", "--data", "x", "--private", str(priv)]) == 0
    test = json.load(open(out / "wide" / "test.json"))
    assert test["verdict"]["wide_pass"] and len(test["verdict"]["passing"]) == 5
    assert test["verdict"]["batches_tested"] == [1] and test["verdict"]["untested"] == []
    assert test["verdict"]["batches"][0]["passes"] == 5 and not test["verdict"]["batches"][0]["opens_next"]
    assert "sizing" not in test                                  # replaced by the R1 goal board (reads, W 7)
    # W 12 lineup: every PASS is 정식; the live-readiness gate is written with the test (spec only)
    assert set(test["lineup"]["정식"]) == {p["id"] for p in picks} and test["lineup"]["rule"] == H.LINEUP_RULE
    assert test["live_gate_spec"] == H.LIVE_GATE
    for p in picks:
        c = test["results"][p["id"]]["checks"]
        assert c["PASS"] and c["bh_significant"] and c["batch"] == 1
        assert c["one_pct_also_passes"]
        assert test["results"][p["id"]]["coins_traded"]
        if p["kind"] == "ds":
            assert "p_a" not in c and "base" in test["results"][p["id"]]
            assert set(test["reads"][p["id"]]["r1_checks"]) <= H.DS_ALLOWED_CHECKS
            assert "mean_lnM" not in test["results"][p["id"]]["base"]
        else:
            r = test["reads"][p["id"]]
            assert set(r) == {"r1", "select_controls", "new24", "extra2020", "gate_diagnostics"}
            assert len(r["r1"]["controls"]["a_mean_lnM"]) == 3 == r["select_controls"]["controls"]["seeds"]
            # review finding: the other gate is a non-pick system; wide runs it in select only (W 6)
            assert all(set(g) == {"select"} for g in r["gate_diagnostics"].values())
    assert isinstance(test["basket"], str)                                      # holds a DeepSeek pick
    full = json.load(open(priv / "wide_test_private.json"))
    assert set(full["basket"]) == {"select", "test"}
    assert H.main(["report", "--study", "wide"]) == 0
    rep = (out / "wide" / "RESULTS_KO.md").read_text()
    assert "넓게 통과: 예" in rep and "1군" in rep and "정식" in rep


def test_end_to_end_v1(tmp_path, monkeypatch):
    out, loaded = _e2e_setup(tmp_path, monkeypatch)
    assert H.main(["select", "--study", "v1", "--data", "x", "--private", str(tmp_path / "p")]) == 0
    sel = json.load(open(out / "v1" / "select.json"))
    assert len(sel["rows"]) == 6 and set(sel["rows"]["v1:E1:1h"]) == {"main", "lo", "hi", "one"}
    pick = json.load(open(out / "v1" / "pick.json"))
    assert pick["pick"]["id"] == sel["choice"]["pick"]
    assert H.main(["test", "--study", "v1", "--data", "x", "--private", str(tmp_path / "p")]) == 0
    test = json.load(open(out / "v1" / "test.json"))
    c = test["result"]["checks"]
    assert {"P0", "P1", "P2", "P3", "P4", "p_a", "p_b", "rank_p_a", "rank_p_b"} <= set(c)
    assert set(test["verdict"]) == {"v1_pass", "label", "one_pct_also_passes", "carried_by_old_six"}
    assert set(test["lineup"]["picks"]) == {pick["pick"]["id"]} and len(test["result"]["controls"]["a_mean_lnM"]) == 3
    assert set(test["reads"]["gate_diagnostics"]) == {"NONE", "TS"}
    assert all(set(g) == {"select", "test"} for g in test["reads"]["gate_diagnostics"].values())       # H 14
    assert len(test["result"]["base"]["day_eq"]) == 61 and test["result"]["base"]["months"] == 2
    assert H.main(["report", "--study", "v1"]) == 0


def test_loader_on_synthetic_files(tmp_path, monkeypatch):
    """<data>/5m/<SYM>.npz (ts + float32 o h l c v qv mo mh ml mc), funding npz, manifest.json, universe.json."""
    d = tmp_path / "coins30"
    (d / "5m").mkdir(parents=True)
    (d / "funding").mkdir()
    n = 600
    ts = START + np.arange(n, dtype=np.int64) * FIVE
    p = np.linspace(100, 110, n).astype(np.float32)
    qv = np.full(n, 1e6, np.float32)
    qv[10] = 0                                                    # zero-volume bar: dropped
    ts[20] = ts[19]                                               # duplicate open time: last kept
    cols = {k: p for k in ("o", "h", "l", "c", "mo", "mh", "ml", "mc")}
    np.savez_compressed(d / "5m" / "AUSDT.npz", ts=ts, v=qv / p, qv=qv, **cols)
    np.savez_compressed(d / "funding" / "AUSDT.npz", ts=np.array([START + 8 * 3_600_000], np.int64),
                        rate=np.array([0.0001]))
    last = H.ms_str(int(ts[-1]))
    (d / "manifest.json").write_text(json.dumps({"symbols": [{"symbol": "AUSDT", "last_nonzero_volume_bar": last,
                                                              "missing_months_funding": ["2022-04"]}]}))
    (d / "universe.json").write_text(json.dumps({"universe": [f"S{i:02d}USDT" for i in range(29)] + ["AUSDT"]}))
    (d / "UNIVERSE.md").write_text("# rule\n")
    end = START + 300 * FIVE
    c = H.load_coin(str(d), "AUSDT", end, H._manifest(str(d)))
    assert c.ts.max() < end and c.o.dtype == np.float32 and c.f64()["o"].dtype == np.float64
    assert c.counts["zero_volume"] == 1 and c.counts["duplicates"] == 1 and len(c.ts) == 298
    # the manifest's coin end and missing month lie after ``end``: nothing of them is carried (review finding)
    assert c.last_ms == 2 ** 62 and c.counts["missing_months_funding"] == []
    assert c.counts["content_sha256"] == H.file_content_sha(str(d / "5m" / "AUSDT.npz"), "5m")
    full = H.load_coin(str(d), "AUSDT", H.day_ms("2022-05-01"), H._manifest(str(d)))
    assert full.last_ms == int(ts[-1])                            # the coin ends inside this span
    assert full.counts["missing_months_funding"] == []           # 2022-04 is after the coin end (2022-03-03)
    fts, rate = H.load_funding(str(d), "AUSDT", end)
    assert len(fts) == 1 and rate[0] == 0.0001
    with pytest.raises(FileNotFoundError):
        H.load_coin(str(d), "BUSDT", end)
    monkeypatch.setattr(H, "ROOT", str(tmp_path))
    (tmp_path / "research" / "hunt").mkdir(parents=True)
    assert H.load_universe(str(d))[-1] == "AUSDT"                 # no universe30.json yet: the data folder's list
    u = H.write_universe30(str(d))
    assert u["universe_md_sha256"] == H.sha256_file(str(d / "UNIVERSE.md")) and len(u["new"]) == 30
    assert H.load_universe(None) == u["symbols"]


# ------------------------------------------------------------------ H 2 data checks (review finding: not implemented)
def _npz5(path, ts, p, v=None, qv=None):
    p = np.asarray(p, np.float32)
    v = np.full(len(ts), 10.0, np.float32) if v is None else np.asarray(v, np.float32)
    qv = (v * p).astype(np.float32) if qv is None else np.asarray(qv, np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, ts=np.asarray(ts, np.int64), o=p, h=p * np.float32(1.001), l=p * np.float32(0.999),
                        c=p, v=v, qv=qv, mo=p, mh=p, ml=p, mc=p)


def test_select_carries_nothing_of_2024_from_the_manifest(tmp_path):
    """Review finding: select copied the manifest's later coin end and missing funding months (2025-07 ..) into
    select.json. Only what lies before the step's end is carried now."""
    d = tmp_path / "coins30"
    ts = H.day_ms("2023-12-25") + np.arange(16 * 288, dtype=np.int64) * FIVE          # to 2024-01-10
    _npz5(d / "5m" / "XUSDT.npz", ts, np.linspace(10, 11, len(ts)))
    man = {"XUSDT": {"symbol": "XUSDT", "last_nonzero_volume_bar": "2025-01-06 09:00",
                     "missing_months_funding": ["2025-07", "2025-08", "2026-09"]}}
    c = H.load_coin(str(d), "XUSDT", H.day_ms("2024-01-01"), man)
    assert c.ts.max() < H.day_ms("2024-01-01") and c.last_ms == 2 ** 62
    assert c.counts["missing_months_funding"] == []
    t = H.load_coin(str(d), "XUSDT", H.day_ms("2026-10-01"), man)
    assert t.last_ms == H.day_ms("2025-01-06") + 9 * 3_600_000
    assert t.counts["missing_months_funding"] == []              # all after the coin end (2025-01-06)
    man["XUSDT"]["missing_months_funding_while_trading"] = ["2024-11"]
    assert H.load_coin(str(d), "XUSDT", H.day_ms("2026-10-01"), man).counts["missing_months_funding"] == ["2024-11"]


def test_data_identity_stops_a_step(tmp_path, monkeypatch):
    d = tmp_path / "data"
    ts = START + np.arange(600, dtype=np.int64) * FIVE
    for s_ in ("AUSDT", "BUSDT"):
        _npz5(d / "5m" / f"{s_}.npz", ts, np.linspace(10, 11, 600))
    (d / "funding").mkdir()
    np.savez_compressed(d / "funding" / "AUSDT.npz", ts=np.array([START], np.int64), rate=np.array([1e-4]))
    (d / "manifest.json").write_text(json.dumps({"symbols": []}))
    (d / "universe.json").write_text(json.dumps({"universe": ["AUSDT", "BUSDT"]}))
    root = tmp_path / "repo"
    (root / "research" / "hunt").mkdir(parents=True)
    monkeypatch.setattr(H, "ROOT", str(root))
    args = types.SimpleNamespace(data=str(d), study="v1", private=str(tmp_path / "priv"))
    with pytest.raises(SystemExit, match="data_manifest.json missing"):
        H._universe_and_data(args, "select")
    assert H.main(["datapin", "--data", str(d)]) == 0
    dm = json.load(open(root / H.DATA_MANIFEST_REL))
    assert dm["content"]["AUSDT"]["funding"] and dm["content"]["BUSDT"]["funding"] is None
    _, syms, counts = H._universe_and_data(args, "select")
    assert syms == ["AUSDT", "BUSDT"] and counts["AUSDT"]["content_sha256"] == dm["content"]["AUSDT"]["5m"]
    p = np.linspace(10, 11, 600)
    p[599] = 12.0                                                  # one changed value
    _npz5(d / "5m" / "BUSDT.npz", ts, p)
    with pytest.raises(SystemExit, match="BUSDT 5m arrays differ"):
        H._universe_and_data(args, "select")


def test_disk_check_stops_under_one_gb(tmp_path, monkeypatch):
    H.disk_check(str(tmp_path))
    monkeypatch.setattr(H.shutil, "disk_usage", lambda p: types.SimpleNamespace(free=500 * 1024 ** 2))
    with pytest.raises(SystemExit, match="free disk"):
        H.disk_check(str(tmp_path / "not" / "yet"))


def test_cross_check_counts_and_pass_rule(tmp_path, monkeypatch):
    """H 2 cross-check on synthetic files: the 5m bars as read vs 1m binned to 5m; a value beyond tolerance is a
    mismatch; a zero-volume 5m bar is dropped (not compared); more than 0.1% of the bars mismatched fails."""
    n1 = 5 * 4000
    t1 = START + np.arange(n1, dtype=np.int64) * 60_000
    rng = np.random.default_rng(3)
    c1 = 100 * np.exp(np.cumsum(rng.normal(0, 1e-4, n1)))
    o1 = np.r_[c1[0], c1[:-1]]
    h1, l1, v1 = np.maximum(o1, c1) * 1.0002, np.minimum(o1, c1) * 0.9998, rng.uniform(1, 2, n1)
    fg = tmp_path / "fg1m"
    (fg / "1m").mkdir(parents=True)
    np.savez_compressed(fg / "1m" / "AUSDT.npz", ts=t1, o=o1, h=h1, l=l1, c=c1, v=v1)
    from research.hunt import entries_wide as EW
    t5, o5, h5, l5, c5, v5 = EW.resample_1m_to_5m(t1, o1, h1, l1, c1, v1)
    qv = (v5 * c5).astype(np.float32)
    qv[7] = 0                                                    # zero volume: dropped, so not compared
    c5b = c5.copy()
    c5b[100] *= 1.001                                            # beyond 1e-6
    d = tmp_path / "data"
    (d / "5m").mkdir(parents=True)
    np.savez_compressed(d / "5m" / "AUSDT.npz", ts=t5, o=o5.astype(np.float32), h=h5.astype(np.float32),
                        l=l5.astype(np.float32), c=c5b.astype(np.float32), v=v5.astype(np.float32), qv=qv)
    r = H.cross_check_coin(str(d / "5m" / "AUSDT.npz"), str(fg / "1m" / "AUSDT.npz"))
    assert r["common"] == 3999 and r["only_1m"] == 1 and r["mismatch"] == 1 and r["ohlc_mismatch"] == 1
    assert r["mismatch_share"] == pytest.approx(1 / 3999) and r["mismatch_share"] < H.XCHECK_MAX_SHARE * 3
    v5b = v5.astype(np.float32)
    v5b[200:210] *= 1.01                                         # 10 volume mismatches: 0.25% > 0.1%
    np.savez_compressed(d / "5m" / "AUSDT.npz", ts=t5, o=o5.astype(np.float32), h=h5.astype(np.float32),
                        l=l5.astype(np.float32), c=c5.astype(np.float32), v=v5b, qv=qv)
    r = H.cross_check_coin(str(d / "5m" / "AUSDT.npz"), str(fg / "1m" / "AUSDT.npz"))
    assert r["volume_mismatch"] == 10 and r["ohlc_mismatch"] == 0 and r["mismatch_share"] > H.XCHECK_MAX_SHARE
    monkeypatch.setattr(H, "OLD_SIX", ("AUSDT",))
    monkeypatch.setattr(H, "ROOT", str(tmp_path))
    (tmp_path / "research" / "hunt").mkdir(parents=True)
    assert H.main(["datacheck", "--data", str(d), "--fg1m", str(fg)]) == 1
    assert json.load(open(tmp_path / H.DATA_CHECK_REL))["pass"] is False


def test_pin_requires_data_build_files(tmp_path, monkeypatch):
    root = _pin_tree(tmp_path, monkeypatch, "v1")
    (root / H.DATA_BUILD_REL).mkdir(parents=True)
    (root / H.DATA_BUILD_REL / "c30.py").write_text("# builder\n")
    with pytest.raises(H.PinError, match="not pinned research/hunt/data_build/c30.py"):
        H.check_pin("v1", "select")
    (root / H.DATA_BUILDER_REL).write_text("# data kit\n")
    with pytest.raises(H.PinError, match="not pinned research/hunt/data_hunt.py"):
        H.check_pin("v1", "select")


# ------------------------------------------------------------------ robustness (review findings)
def _die_on_three(x):
    if x == 3 and not os.path.exists(_DIE_FLAG[0]):
        open(_DIE_FLAG[0], "w").close()
        os.kill(os.getpid(), 9)
    return x * x


_DIE_FLAG = [""]


def test_pmap_survives_a_killed_worker(tmp_path, capsys):
    """Review finding: Pool.map hung forever when a worker was killed. Now the pool is rebuilt and only unfinished
    tasks are sent again."""
    _DIE_FLAG[0] = str(tmp_path / "died")
    assert H.pmap(_die_on_three, list(range(8)), 2, label="t") == [x * x for x in range(8)]
    assert os.path.exists(_DIE_FLAG[0]) and "a worker died" in capsys.readouterr().out


def _always_die(x):
    os.kill(os.getpid(), 9)


def test_pmap_stops_when_workers_keep_dying(monkeypatch):
    monkeypatch.setattr(H, "MAX_RESTARTS", 1)
    with pytest.raises(SystemExit, match="workers keep dying"):
        H.pmap(_always_die, [1, 2, 3], 2, label="t")


def _boom(x):
    if x == 2:
        raise ValueError("bad cell")
    return x


def test_pmap_raises_a_task_error():
    with pytest.raises(ValueError, match="bad cell"):
        H.pmap(_boom, [1, 2, 3, 4], 2)


def test_wide_select_and_test_resume_from_parts(tmp_path, monkeypatch):
    """Review finding: a crash lost all finished work. Each entry cell (select) and each pick (test) is written to the
    private parts folder as soon as it is done; a rerun under the same pin computes only what is missing and gives
    the same picks and results."""
    out, _ = _e2e_setup(tmp_path, monkeypatch, force_pass=True)
    priv = tmp_path / "private"
    args = ["--procs", "1", "--data", "x", "--private", str(priv)]
    real = H._sel_task
    calls = []

    def flaky(task):
        calls.append(task[1][0]["id"])
        if len(calls) == 3:
            raise RuntimeError("crash in the third cell")
        return real(task)
    monkeypatch.setattr(H, "_sel_task", flaky)
    with pytest.raises(RuntimeError, match="third cell"):
        H.main(["select", "--study", "wide"] + args)
    assert len(list((priv / "parts").glob("wide_select_*/cell_*.json"))) == 2
    calls.clear()
    monkeypatch.setattr(H, "_sel_task", lambda task: (calls.append(task[1][0]["id"]), real(task))[1])
    assert H.main(["select", "--study", "wide"] + args) == 0
    assert len(calls) == 4                                     # only the four missing cells ran
    picks = json.load(open(out / "wide" / "picks.json"))["picks"]
    sel = json.load(open(out / "wide" / "select.json"))
    calls.clear()
    assert H.main(["select", "--study", "wide"] + args) == 0  # (the pin check is patched here) nothing recomputed
    assert calls == [] and json.load(open(out / "wide" / "picks.json"))["picks"] == picks
    assert json.load(open(out / "wide" / "select.json"))["rows"] == sel["rows"]
    real_block = H._pick_block
    n_block = []

    def counting(*a, **k):
        n_block.append(a[1]["id"])
        return real_block(*a, **k)
    monkeypatch.setattr(H, "_pick_block", counting)
    assert H.main(["test", "--study", "wide"] + args) == 0
    first = json.load(open(out / "wide" / "test.json"))
    done = len(n_block)
    assert H.main(["test", "--study", "wide"] + args) == 0
    assert len(n_block) == done                                # every pick taken from its part
    again = json.load(open(out / "wide" / "test.json"))
    assert again["results"] == first["results"] and again["verdict"] == first["verdict"]


# ------------------------------------------------------------------ engine read options (panel 2026-10-11): bit-identity
def _rand_sig(mk, tf, per_days, seed):
    """Random signals on bars with ATR14 > 0 and a fill bar in the period (no 장세 label needed: short series)."""
    rng = np.random.default_rng(seed)
    K, J, S = [], [], []
    for k in range(mk.K):
        ser = H.series(mk.syms[k], tf)
        cm = ser.bars.close_ms
        _, ok = H.fill_index(mk, k, ser)
        pool = np.flatnonzero((cm >= mk.start) & (cm < mk.end) & np.isfinite(ser.atr) & (ser.atr > 0) & ok)
        n = int((mk.end - mk.start) / H.DAY_MS / per_days)
        j = np.sort(rng.choice(pool, size=min(n, len(pool)), replace=False))
        K.append(np.full(len(j), k, np.int64))
        J.append(j.astype(np.int64))
        S.append(np.where(rng.random(len(j)) < 0.5, 1, -1).astype(np.int64))
    return {"tf": tf, "k": np.concatenate(K), "j": np.concatenate(J), "side": np.concatenate(S)}


def _golden_digest(**kw):
    """The engine on a seeded synthetic 8-coin case (coin end, funding, three timeframes and sizes): sha256 of every
    decision output. GOLDEN_DIGEST was computed with the reviewed engine (commit a43f36c) before the read options
    were added."""
    s0 = H.day_ms("2022-01-01")
    coins = {f"C{i}USDT": H.synth_coin(f"C{i}USDT", s0, s0 + 50 * DAY, 700 + i, 10.0 * (i + 1)) for i in range(8)}
    fund = {s: H.synth_funding(s0, s0 + 50 * DAY, 800 + i) for i, s in enumerate(coins)}
    coins["C2USDT"].last_ms = int(coins["C2USDT"].ts[len(coins["C2USDT"].ts) - 2000])
    H.install(coins, fund)
    mk = H.Market(list(coins), (s0 + 31 * DAY, s0 + 50 * DAY), name="g")
    h = hashlib.sha256()
    n = 0
    for tf, r, cost, cap, bdiv in (("15m", 0.005, "base", 0.04, 6.0), ("1h", 0.01, "x2", 0.04, 6.0),
                                   ("4h", 0.05, "base", 0.4, 0.6), ("30m", 0.02, "base", 0.16, 1.5)):
        sig = _rand_sig(mk, tf, 0.25, 21)
        b = H.bank_for(mk, (tf,))
        c = H.build_cands(mk, b, [(sig, 1)])
        p = H.params(r, cost, cap, 5000.0, bdiv)
        for k, v in kw.items():
            p[H.PR_INDEX[k]] = v
        raw = H.simulate(mk, b, c, prm=p)
        n += len(raw[4])
        for a in list(raw[:7]) + [raw[7][:4], raw[8], raw[9], raw[10][:7]]:
            h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest(), n


GOLDEN_DIGEST = ("d99d9b0110245102dcc440922accc3e697ad6d404b209e5e8b134a2200a76cca", 584)


def test_engine_bit_identical_at_default_params():
    """Panel: every engine export added for the reads leaves the decision path bit-identical at default params (and
    the per-bar equity path, being an export only, changes nothing either)."""
    assert _golden_digest() == GOLDEN_DIGEST
    assert _golden_digest(PR_EQPATH=1.0) == GOLDEN_DIGEST
    assert len(H.params()) == H.NPR and H.params()[H.PR_BPD] == 288


def test_equity_path_peak_and_close_at_end():
    s0 = H.day_ms("2022-03-01")
    coins = {f"C{i}USDT": _wave_coin(f"C{i}USDT", 40, s0, 30 + i) for i in range(4)}
    H.install(coins)
    mk = H.Market(list(coins), (s0 + 31 * DAY, s0 + 40 * DAY), name="t")     # crosses a month end
    sig = _rand_sig(mk, "15m", 0.1, 5)
    b = H.bank_for(mk, ("15m",))
    c = H.build_cands(mk, b, [(sig, 0)])
    p = H.params()
    p[H.PR_EQPATH] = 1
    raw = H.simulate(mk, b, c, prm=p)
    path, day_eq, month_eq, st = raw[11], raw[2], raw[0], raw[10]
    assert len(path) == mk.T and np.array_equal(path[287::288], day_eq)
    assert np.array_equal(path[mk.month_t0[1:] - 1], month_eq)
    assert st[7] == pytest.approx(max(5000.0, path.max())) and st[8] == path[-1] == st[4]
    open_end = int((raw[4][:, H.RI_REASON] == H.EX_END).sum())
    assert open_end > 0                                        # positions open at the end: marked, not closed
    p[H.PR_CLOSE_END] = 1
    rc = H.simulate(mk, b, c, prm=p)
    assert int((rc[4][:, H.RI_REASON] == H.EX_ENDCLOSE).sum()) == open_end and not (rc[4][:, H.RI_REASON] == H.EX_END).any()
    assert rc[10][8] == pytest.approx(st[4], rel=1e-12)         # the marked end is unchanged
    assert rc[10][4] < rc[10][8]                               # closing costs slippage and taker
    assert rc[10][4] == pytest.approx(5000 + rc[3][:, H.RF_PNL].sum(), rel=1e-9)
    assert rc[0][-1] == rc[10][4] and rc[2][-1] == rc[10][4]
    assert np.array_equal(rc[3][rc[4][:, H.RI_REASON] != H.EX_ENDCLOSE], raw[3][raw[4][:, H.RI_REASON] != H.EX_END])


def test_n4_uses_the_number_of_adds():
    """R5: N4 = (1 + n_adds) x q x P0 (= 4 q P0 as written). D0 = 0.5% of P0: with 3 adds the budget needs L >= 24,
    so (ii) fails and L = 20 (the cap meeting (i) and (iii)); with no adds L = ceil(5000 / 833.3) = 6."""
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.2, 99.8, 100)] * 3, pad_to=288)})
    assert rec(sim(mk, [{"k": 0, "t": 0, "d0": 0.5}]))[0][H.RF_LEV] == 20
    assert rec(sim(mk, [{"k": 0, "t": 0, "d0": 0.5}], adds=0))[0][H.RF_LEV] == 6


def test_goal_mode_bracket_rule_skips_an_add_past_the_tier():
    """R1 machine B: the bracket is looked up at the first unit's notional (20,000 < 25,000: 20x tier) and an add
    that would take the notional past that tier's cap is skipped ('bracket'). As written, the bracket of N4 = 80,000
    allows only 10x and the add fills."""
    bars = [(100, 100.4, 99.6, 100.2), (100.2, 101.5, 100.1, 101.2)] + [(101.2, 101.3, 101.1, 101.2)] * 3
    mk = market({"AUSDT": coin("AUSDT", bars, pad_to=288, qv=1e12)})
    rows = [{"k": 0, "t": 0, "d0": 1.0}]
    p = H.params(0.01, start=20000.0, b_div=4.0)
    out = H.simulate(mk, no_bank(), cands(mk, rows), prm=p)
    assert out[3][0, H.RF_LEV] == 10 and out[4][0, H.RI_ADDS] >= 1 and out[7][H.AS_BRACKET] == 0
    p[H.PR_BRK_Q1], p[H.PR_LEVMAX] = 1, 125
    out = H.simulate(mk, no_bank(), cands(mk, rows), prm=p)
    assert out[3][0, H.RF_LEV] == 16 and out[4][0, H.RI_ADDS] == 0 and out[7][H.AS_BRACKET] >= 1
    assert H.summarize(mk, out)["adds_skipped"]["bracket"] >= 1


def test_fixed_leverage_rule_bot_sizing_and_liquidation():
    """R24 (owners (f)): leverage L fixed, margin = L% of equity, q = margin x L / fill; a stop beyond the
    liquidation price is liquidated first (whole margin lost)."""
    bars = [(100, 100.2, 99.9, 100.0), (100.0, 100.1, 97.0, 97.2)] + [(97.2, 97.3, 97.1, 97.2)] * 3
    mk = market({"AUSDT": coin("AUSDT", bars, pad_to=288, qv=1e12)})
    p = H.params()
    p[H.PR_FIXLEV], p[H.PR_NADDS], p[H.PR_CAP], p[H.PR_MAXPOS] = 20, 0, 100.0, 5
    out = H.simulate(mk, no_bank(), cands(mk, [{"k": 0, "t": 0, "d0": 4.0}]), prm=p)
    rf, ri = rec(out)
    fill = 100 * (1 + SLIP)
    assert rf[H.RF_LEV] == 20 and rf[H.RF_Q1] == pytest.approx(0.2 * 5000 * 20 / fill)
    assert rf[H.RF_U] == pytest.approx(rf[H.RF_Q1] * 4.0)
    assert ri[H.RI_REASON] == H.EX_LIQ and rf[H.RF_PRICE] == pytest.approx(-0.2 * 5000)


def _mark_coin(bars, marks):
    c = coin("AUSDT", bars, pad_to=288, qv=1e12)
    n = len(c.ts)
    mo, mh, ml = c.o.copy(), c.h.copy(), c.l.copy()
    for i, (a, hh, ll) in marks.items():
        mo[288 + i], mh[288 + i], ml[288 + i] = a, hh, ll
    return H.Coin(c.sym, c.ts, c.o, c.h, c.l, c.c, c.v, c.qv, mark={"mo": mo[:n], "mh": mh[:n], "ml": ml[:n]})


def test_liquidation_on_mark_price_only_in_the_mark_read():
    """R19: with 1m / 5m mark bars and PR_LIQ_MARK a mark wick beyond the liquidation price liquidates although the
    last price stayed inside; the study (H 2: last price) does not."""
    bars = [(100, 100.2, 99.9, 100.0), (100.0, 100.1, 98.5, 99.0)] + [(99.0, 99.1, 98.9, 99.0)] * 3
    c = _mark_coin(bars, {1: (100.0, 100.1, 96.0)})
    H.install({"AUSDT": c})
    start = START
    p = H.params()
    p[H.PR_FIXLEV], p[H.PR_NADDS], p[H.PR_CAP] = 20, 0, 100.0
    rows = [{"k": 0, "t": 0, "d0": 4.0}]
    last = H.Market(["AUSDT"], (start, start + DAY), name="t")
    assert rec(H.simulate(last, no_bank(), cands(last, rows), prm=p))[1][H.RI_REASON] == H.EX_END
    mk = H.Market(["AUSDT"], (start, start + DAY), name="t", bars={"AUSDT": c}, mark=True, tag="mark")
    with pytest.raises(ValueError):
        H.simulate(last, no_bank(), cands(last, rows), prm=H.with_overrides(p, {"PR_LIQ_MARK": 1}))
    q = H.with_overrides(p, {"PR_LIQ_MARK": 1})
    assert rec(H.simulate(mk, no_bank(), cands(mk, rows), prm=q))[1][H.RI_REASON] == H.EX_LIQ
    assert rec(H.simulate(mk, no_bank(), cands(mk, rows), prm=p))[1][H.RI_REASON] == H.EX_END


def _as_1m(c):
    """Each 5m bar as five identical 1m bars (volume split in five): a 1m path whose 5m bars are exactly ``c``."""
    ts = (c.ts[:, None] + np.arange(5)[None, :] * 60_000).ravel()
    rep = lambda x: np.repeat(np.asarray(x, np.float64), 5)  # noqa: E731
    return H.Coin(c.sym, ts, rep(c.o), rep(c.h), rep(c.l), rep(c.c), rep(c.v) / 5, rep(c.qv) / 5, last_ms=c.last_ms)


def test_one_minute_bars_scale_every_time_length():
    """R19 fidelity engine: on 1m bars the day (1440 steps), the 24 h liquidity window, the funding grid, the coin end,
    the chandelier steps and the fill bar scale with the bar length. A 1m path made of five copies of each 5m bar
    gives the same positions, prices and equity as the 5m run (exit steps x 5)."""
    s0 = H.day_ms("2022-03-01")
    coins = {f"C{i}USDT": H.synth_coin(f"C{i}USDT", s0, s0 + 14 * DAY, 60 + i, 20.0 * (i + 1)) for i in range(3)}
    coins["C1USDT"].last_ms = int(coins["C1USDT"].ts[288 * 11 + 17])
    fund = {s: H.synth_funding(s0, s0 + 14 * DAY, 90 + i) for i, s in enumerate(coins)}
    H.install(coins, fund)
    span = (s0 + 5 * DAY, s0 + 14 * DAY)
    mk5 = H.Market(list(coins), span, name="t")
    mk1 = H.Market(list(coins), span, name="t", bar_ms=60_000, bars={s: _as_1m(c) for s, c in coins.items()},
                   tag="1m")
    assert mk1.T == 5 * mk5.T and mk1.bpd == 1440 and mk1.coin_end_t[1] == 5 * mk5.coin_end_t[1] + 4
    assert np.allclose(mk1.b_qv[::5][:50], mk5.b_qv[:50], rtol=1e-6)            # the same 24 h of quote volume
    for tf in ("15m", "1h"):
        sig = _rand_sig(mk5, tf, 0.2, 3)
        r5 = H.simulate(mk5, H.bank_for(mk5, (tf,)), H.build_cands(mk5, H.bank_for(mk5, (tf,)), [(sig, 0)]))
        r1 = H.simulate(mk1, H.bank_for(mk1, (tf,)), H.build_cands(mk1, H.bank_for(mk1, (tf,)), [(sig, 0)]))
        assert len(r5[4]) == len(r1[4]) > 5
        assert np.allclose(r1[3], r5[3], rtol=1e-9, atol=1e-9)
        for col in (H.RI_COIN, H.RI_SIDE, H.RI_ADDS, H.RI_REASON, H.RI_SRC):
            assert np.array_equal(r1[4][:, col], r5[4][:, col])
        assert np.array_equal(r1[4][:, H.RI_TIN], 5 * r5[4][:, H.RI_TIN])
        assert np.array_equal(r1[4][:, H.RI_TOUT] // 5, r5[4][:, H.RI_TOUT])
        assert np.allclose(r1[2], r5[2], rtol=1e-9) and np.allclose(r1[0], r5[0], rtol=1e-9)
        assert (r5[4][:, H.RI_REASON] == H.EX_COINEND).any() or tf == "15m"


# ------------------------------------------------------------------ batches, lineup, live gate, size rule, guards
def test_wide_batches_open_only_after_enough_passes(tmp_path, monkeypatch):
    """Owners (b): batch membership is fixed in picks.json at select; batch n+1 is tested only when >= trigger picks
    of batch n PASS; BH runs within each batch; untested members never run on the test period."""
    out, _ = _e2e_setup(tmp_path, monkeypatch, force_pass=True)
    monkeypatch.setattr(H, "K_PICKS", 2)
    monkeypatch.setattr(H, "BATCH_TRIGGER", 2)
    priv = tmp_path / "private"
    args = ["--procs", "1", "--data", "x", "--private", str(priv)]
    assert H.main(["select", "--study", "wide"] + args) == 0
    pk = json.load(open(out / "wide" / "picks.json"))
    assert pk["batches"] == [[1, 2], [3, 4], [5]] and [p["batch"] for p in pk["picks"]] == [1, 1, 2, 2, 3]
    fail_id = pk["picks"][2]["id"]                               # the first member of batch 2 fails P1
    forced = H.judge
    ran = []

    def judge(base, cost2, ctl, study, spec, period, r):
        ran.append(spec["id"])
        j = forced(base, cost2, ctl, study, spec, period, r)
        if spec["id"] == fail_id:
            j["P1"] = False
        return j
    monkeypatch.setattr(H, "judge", judge)
    assert H.main(["test", "--study", "wide"] + args) == 0
    test = json.load(open(out / "wide" / "test.json"))
    v = test["verdict"]
    assert v["batches_tested"] == [1, 2] and v["batches"][0]["opens_next"] and not v["batches"][1]["opens_next"]
    assert v["batches"][1]["passes"] == 1 and v["untested"] == [pk["picks"][4]["id"]]
    assert pk["picks"][4]["id"] not in ran and [p["id"] for p in test["picks"]] == [p["id"] for p in pk["picks"][:4]]
    assert v["wide_pass"] and len(v["passing"]) == 3 and test["results"][fail_id]["checks"]["PASS"] is False
    lu = test["lineup"]["picks"]
    assert lu[fail_id]["lineup"] in ("참고", "excluded") and "PASS" not in lu[fail_id]["why"]
    assert {i for i, d in lu.items() if d["lineup"] == "정식"} == set(v["passing"])


def _blk(lnM, mean_d=(0.01, 0.01), cost2_mean=0.01, dd=0.2, bust=False, med=1.01):
    lnM = list(lnM)
    return {"base": {"mean_lnM": float(np.mean(lnM)), "median_M": med, "max_dd": dd, "bust": bust, "lnM": lnM},
            "cost2": {"mean_lnM": cost2_mean}, "checks": {"mean_d_a": mean_d[0], "mean_d_b": mean_d[1]}}


def test_lineup_rule():
    """Owners (g): 정식 = PASS; 참고 = all seven conditions; else excluded (with the failing conditions)."""
    good = [0.05, 0.04, 0.03, 0.02, -0.01]
    assert H.lineup_of(_blk(good), "picks", True) == {"lineup": "정식", "why": []}
    assert H.lineup_of(_blk(good), "picks", False) == {"lineup": "참고", "why": []}
    assert H.lineup_of(_blk(good), "no pick, fail", False)["lineup"] == "excluded"
    cases = {"mean_lnM": _blk([-0.01, 0.0]), "median_M": _blk(good, med=0.99),
             "controls": _blk(good, mean_d=(0.01, -0.001)), "cost_x2": _blk(good, cost2_mean=-0.001),
             "max_dd": _blk(good, dd=0.5), "bust": _blk(good, bust=True), "top_month": _blk([0.30, 0.10, 0.05, 0.05])}
    for why, blk in cases.items():
        d = H.lineup_of(blk, "picks", False)
        assert d["lineup"] == "excluded" and why in d["why"], why
    assert H.lineup_of(_blk([0.20, 0.15, 0.10, 0.05]), "picks", False)["lineup"] == "참고"     # 0.20 < 0.25


def test_live_gate_size_rule_and_intervals():
    full = {"liquidations_mark": 0, "worst_position_loss_U_stopfill25": 2.5, "worst_rolling30_multiple": 0.8,
            "max_instant_loss_gap10": 0.2, "mean_lnM_impact_y1_live": 0.01, "mean_lnM_impact_y1_10x": 0.002,
            "forward_replay_share": 0.995, "forward_inside_band": True}
    g = H.evaluate_live_gate(full)
    assert g["live_ready"] and g["items"]["g"] == "not applicable"
    assert not H.evaluate_live_gate({**full, "worst_rolling30_multiple": 0.69})["live_ready"]
    assert H.evaluate_live_gate({**full, "ai_judge_used": True})["items"]["g"] == "not computed"
    assert H.evaluate_live_gate({})["label"] == "not live-ready at this size"
    cells = [{"machine": "A", "r": 0.005, "mean_ln_multiple": 0.01, "bust_share": 0.0},
             {"machine": "B", "r": 0.05, "mean_ln_multiple": 0.05, "bust_share": 0.03},
             {"machine": "B", "r": 0.10, "mean_ln_multiple": 0.05, "bust_share": 0.05},
             {"machine": "B", "r": 0.20, "mean_ln_multiple": 0.09, "bust_share": 0.06}]
    assert H.size_fixed_on_select(cells) == cells[1]                     # 20% busts too often; tie -> lower r
    assert H.size_fixed_on_select([cells[3]]) is None
    lo, hi = H.clopper_pearson(0, 33)
    assert lo == 0.0 and hi == pytest.approx(0.1058, abs=1e-3)              # panel: 0 of 33 allows up to 10.6%
    assert H.HEADLINE_CELL["r"] == 0.05 and H.HEADLINE_CELL["level"] == 5000.0
    assert H.HEADLINE_CELL["start_wallet"] == 1000.0 and H.HEADLINE_CELL["machine"].startswith("B")


def test_d11_check_of_public_reads():
    ds = {"F3:F9_FVG:4h:G1", "basket_batch1"}
    ok = {"rows": [{"row": "pick:F3:F9_FVG:4h:G1", "label": "x", "n": 3, "win_share": 0.4},
                   {"row": "pick:F2:X:1h:G1", "share_x5": 0.12}], "basket_batch1": {"positions": 12}}
    assert H.d11_problems(ok, ds) == []
    bad = {"rows": [{"row": "pick:F3:F9_FVG:4h:G1", "share_x5": 0.12}], "basket_batch1": {"multiple": 1.3},
           "by_id": {"F3:F9_FVG:4h:G1": {"cells": [0.1]}}}
    assert len(H.d11_problems(bad, ds)) == 3


class _FakeReads:
    """A stand-in reads module (the real reads_a.py is another agent's code): it uses the documented ctx."""

    def __init__(self, mode="ok"):
        self.mode, self.seen = mode, {}

    def run(self, ctx):
        self.seen = ctx
        assert ctx["api"] == 1 and ctx["seeds"]["pass"] == H.N_SEEDS
        assert {r["kind"] for r in ctx["rows"]} >= {"pick"}
        t0, t1 = ctx["periods"]["test"]
        w0 = t0 + 10 * DAY
        p = ctx["picks"][0]
        res = ctx["run"](p, w0, w0 + 20 * DAY, start_wallet=1000.0, path="5m", close_end=True)
        assert len(res["equity_path"]) == 20 * 288 and res["start"] == 1000.0
        assert res["peak"] >= res["equity_path"].max() - 1e-9 and res["multiple"] == pytest.approx(res["end"] / 1000)
        cs = ctx["control_signals"](p, "a", "test", 0.005, 1)
        r2 = ctx["run"]([(cs, 0)], w0, w0 + 20 * DAY, start_wallet=1000.0)
        assert r2["candidates"] <= len(cs["k"])
        ctx["out"]["rows"] = [{"row": r["row"], "kind": r["kind"], "n_members": len(r["members"])}
                              for r in ctx["rows"]]
        ctx["private"]["multiples"] = {p["id"]: res["multiple"]}
        if self.mode == "write":
            with open(os.path.join(H.ROOT, H.OUT_REL[ctx["study"]], "sneaky.json"), "w") as fh:
                fh.write("{}")
        if self.mode == "d11":
            ds = next(x for x in ctx["picks"] if x["is_ds"])
            ctx["out"][ds["id"]] = {"multiple": 1.5}


@pytest.mark.parametrize("mode", ["ok", "write", "d11", "unpinned"])
def test_reads_hook_ctx_guard_and_d11(tmp_path, monkeypatch, mode):
    out, _ = _e2e_setup(tmp_path, monkeypatch, force_pass=True)
    priv = tmp_path / "private"
    args = ["--procs", "1", "--data", "x", "--private", str(priv)]
    assert H.main(["select", "--study", "wide"] + args) == 0
    fake = _FakeReads(mode)
    monkeypatch.setattr(H, "READS_MODULES", ("reads_fake",))
    monkeypatch.setattr(H, "_reads_module", lambda name: fake)
    real_exists = os.path.exists
    monkeypatch.setattr(H.os.path, "exists", lambda p: True if str(p).endswith("reads_fake.py") else real_exists(p))
    monkeypatch.setattr(H, "sha256_file", (lambda f: (lambda p: "f" * 64 if str(p).endswith("reads_fake.py")
                                                      else f(p)))(H.sha256_file))
    monkeypatch.setattr(H, "reads_pinned_now", lambda study: {} if mode == "unpinned"
                        else {"research/hunt/reads_fake.py": "f" * 64})
    rc = H.main(["test", "--study", "wide"] + args)
    target = out / "wide" / "reads_fake.json"
    assert (out / "wide" / "test.json").exists()                  # the verdict is written before any read
    if mode == "ok":
        assert rc == 0 and target.exists()
        doc = json.load(open(target))
        assert doc["reads_line_predates_test_json"] is True and doc["out"]["rows"]
        assert doc["private_sha256"] == H.sha256_file(str(priv / "wide_reads_fake_private.json"))
        kinds = {r["kind"] for r in doc["out"]["rows"]}
        assert kinds == {"pick", "basket_batch1", "basket_passing"}
        target.unlink()                                            # the reads command runs the hook again
        assert H.main(["reads", "--study", "wide"] + args) == 0 and target.exists()
        assert H.main(["reads", "--study", "wide"] + args) == 0    # exists: skipped, not overwritten
    elif mode == "unpinned":
        assert rc == 0 and not target.exists() and not fake.seen
    else:
        assert rc == 2 and not target.exists()                     # ReadGuardError: nothing written


# ------------------------------------------------------------------ R19 fidelity and R23 October (synthetic files only)
def _write_1m(dirpath, coin_):
    c1 = _as_1m(coin_)
    (dirpath / "1m").mkdir(parents=True, exist_ok=True)
    f32 = lambda x: np.asarray(x, np.float32)  # noqa: E731
    np.savez_compressed(dirpath / "1m" / f"{coin_.sym}.npz", ts=c1.ts, o=f32(c1.o), h=f32(c1.h), l=f32(c1.l),
                        c=f32(c1.c), v=f32(c1.v), qv=f32(c1.qv), mo=f32(c1.o), mh=f32(c1.h), ml=f32(c1.l), mc=f32(c1.c))


def test_fidelity_read_on_one_minute_files(tmp_path, monkeypatch, capsys):
    out, _ = _e2e_setup(tmp_path, monkeypatch, force_pass=True)
    priv = tmp_path / "private"
    args = ["--procs", "1", "--data", "x", "--private", str(priv)]
    assert H.main(["select", "--study", "wide"] + args) == 0
    with pytest.raises(SystemExit):
        H.main(["fidelity", "--study", "wide", "--list-coins"] + args)       # no test.json yet
    assert H.main(["test", "--study", "wide"] + args) == 0
    capsys.readouterr()
    assert H.main(["fidelity", "--study", "wide", "--list-coins"] + args) == 0
    listed = capsys.readouterr().out.split()
    assert listed and set(listed) <= set(E2E_SYMS)
    d1 = tmp_path / "fid"
    for s in ("BTCUSDT", "ETHUSDT"):
        _write_1m(d1, H._COINS[s])
    assert H.main(["fidelity", "--study", "wide", "--data1m", str(d1)] + args) == 0
    doc = json.load(open(out / "wide" / "fidelity.json"))
    assert doc["bar_source"]["BTCUSDT"] == "1m" and doc["bar_source"]["AAAUSDT"] == "5m"
    test = json.load(open(out / "wide" / "test.json"))
    assert set(doc["picks"]) == {p["id"] for p in test["picks"]}
    for p in test["picks"]:
        row = doc["picks"][p["id"]]
        if p["kind"] == "ds":
            assert "note" in row and "1m_mark" not in row                  # D11
        else:
            assert set(row) >= {"5m", "1m", "1m_mark", "change_1m_mark_minus_5m", "median_control_seeds"}
            assert set(row["median_control_seeds"]) == {"a", "b"}
    assert doc["private_sha256"] == H.sha256_file(str(priv / "wide_fidelity_private.json"))


def _zip_csv(path, header, rows):
    import zipfile
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (header + "\n" if header else "") + "\n".join(",".join(str(x) for x in r) for r in rows) + "\n"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(path.name.replace(".zip", ".csv"), body)
    (path.parent / (path.name + ".CHECKSUM")).write_text(f"{H.sha256_file(str(path))}  {path.name}\n")


def _daily_archive(root, sym, day, ts, o, h, lo, c, v, qv, mark=True, micro=False):
    kl = root / "data/futures/um/daily/klines" / sym / "5m" / f"{sym}-5m-{day}.zip"
    t = [int(x) * (1000 if micro else 1) for x in ts]
    _zip_csv(kl, "open_time,open,high,low,close,volume,close_time,quote_volume,count,tbv,tbqv,ignore",
             [(t[i], o[i], h[i], lo[i], c[i], v[i], t[i] + 299_999, qv[i], 10, 0, 0, 0) for i in range(len(t))])
    if mark:
        mk = root / "data/futures/um/daily/markPriceKlines" / sym / "5m" / f"{sym}-5m-{day}.zip"
        _zip_csv(mk, None, [(int(ts[i]), o[i] * 1.001, h[i] * 1.001, lo[i] * 0.999, c[i], 0, int(ts[i]) + 299_999, 0,
                             0, 0, 0, 0) for i in range(len(ts))])


def test_daily_archive_loader(tmp_path):
    a = H.day_ms("2026-10-01")
    root = tmp_path / "oct"
    for d in range(2):
        ts = a + d * DAY + np.arange(288, dtype=np.int64) * FIVE
        p = 100 + np.arange(288) * 0.01 + d
        _daily_archive(root, "XUSDT", H.ms_str(int(ts[0]))[:10], ts, p, p + 0.05, p - 0.05, p + 0.01, np.full(288, 3.0),
                       np.full(288, 300.0), mark=(d == 0), micro=(d == 1))
    r = H.load_daily_archive(str(root), "XUSDT", a, a + 3 * DAY)
    arr, cnt = r["arrays"], r["counts"]
    assert len(arr["ts"]) == 576 and arr["ts"][0] == a and arr["ts"][-1] == a + 2 * DAY - FIVE   # microseconds -> ms
    assert arr["o"].dtype == np.float32 and arr["o"][0] == np.float32(100.0) and arr["qv"][5] == np.float32(300.0)
    assert np.isfinite(arr["mo"][:288]).all() and np.isnan(arr["mo"][288:]).all()
    assert arr["mo"][0] == np.float32(100.1)
    assert cnt["kline_days"] == 2 and cnt["mark_days"] == 1 and cnt["funding_zero_days"] == 3
    assert cnt["checksum_ok"] == 3 and len(r["arrays"]["funding"][0]) == 0
    bad = next((root / "data/futures/um/daily/klines/XUSDT/5m").glob("*.CHECKSUM"))
    bad.write_text("0" * 64 + "  x\n")
    with pytest.raises(SystemExit, match="CHECKSUM"):
        H.load_daily_archive(str(root), "XUSDT", a, a + 3 * DAY)


def test_october_read_on_synthetic_daily_files(tmp_path, monkeypatch):
    out, _ = _e2e_setup(tmp_path, monkeypatch, force_pass=True)
    monkeypatch.setattr(H, "OCT_PERIOD", ("2020-10-01", "2020-10-11"))
    priv = tmp_path / "private"
    args = ["--procs", "1", "--data", "x", "--private", str(priv)]
    assert H.main(["select", "--study", "wide"] + args) == 0
    root = tmp_path / "oct"
    with pytest.raises(SystemExit, match="only after the test step"):
        H.main(["october", "--study", "wide", "--data-oct", str(root)] + args)
    assert H.main(["test", "--study", "wide"] + args) == 0
    a = H.day_ms("2020-10-01")
    for i, s in enumerate(E2E_SYMS):
        last = float(H._COINS[s].c[-1])
        nc = H.synth_coin(s, a, a + 10 * DAY, 900 + i, last)
        for d in range(10):
            sl = slice(d * 288, (d + 1) * 288)
            _daily_archive(root, s, H.ms_str(a + d * DAY)[:10], nc.ts[sl], nc.o[sl], nc.h[sl], nc.l[sl], nc.c[sl],
                           nc.v[sl], nc.qv[sl])
    assert H.main(["october", "--study", "wide", "--data-oct", str(root)] + args) == 0
    doc = json.load(open(out / "wide" / "reads_october.json"))
    assert doc["note"] == H.OCT_NOTE and doc["period"] == ["2020-10-01", "2020-10-11"]
    test = json.load(open(out / "wide" / "test.json"))
    assert set(doc["picks"]) == {p["id"] for p in test["picks"]}
    for p in test["picks"]:
        row = doc["picks"][p["id"]]
        if p["kind"] == "ds":
            assert set(row) == {"note", "n_positions", "bust"}
        else:
            assert row["test_rolling_10d"]["windows"] == 61 - 10 + 1
            assert set(row["controls"]) == {"a", "b"} and row["controls"]["a"]["seeds"] == 3
    assert all(c["funding_zero_days"] == 10 and c["checksum_ok"] == 20 for c in doc["data_counts"].values())
