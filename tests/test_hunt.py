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


def test_stop_counts_before_add_in_the_same_bar():
    mk = market({"AUSDT": coin("AUSDT", [(100, 100.5, 99.5, 100.4), (100.4, 102.5, 97.9, 99)], pad_to=288)})
    rf, ri = rec(sim(mk, [{"k": 0, "t": 0}]))
    assert ri[H.RI_REASON] == H.EX_STOP and ri[H.RI_ADDS] == 0 and ri[H.RI_TRIED] == 0
    assert rf[H.RF_XPX] == pytest.approx(98 * (1 - SLIP))


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
    cost2 = {"median_M": 1.05}
    ctl = {"a": np.zeros((100, 3)), "b": np.full((100, 3), 0.2)}
    j = H.judge(base, cost2, ctl, "wide", {"id": "F1:E1:1h:G1"}, "test", 0.005)
    assert j["P0"] and j["P1"] and j["P3"] and j["P4"]
    assert j["P2_a"] and j["rank_ok_a"] and not j["P2_b"] and not j["rank_ok_b"]
    assert j["p"] == max(j["p_a"], j["p_b"]) and j["p_b"] == 1.0


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
    # A once (its 4h), then ties at 0.04: higher median (E), then family F1 (D) before F2 (B); DOGE once (F4)
    assert ch["picks"] == ["F2:A:4h:G1", "F2:E:1h:G1", "F1:D:1h:G1", "F2:B:1h:G1", "F4:DOGE:15m:G1:r1"]
    assert H.wide_choose(rows, k_picks=2)["picks"] == ["F2:A:4h:G1", "F2:E:1h:G1"]
    none = H.wide_choose([_row(0, "A", -0.1, eligible=False), _row(1, "B", -0.05, eligible=False)])
    assert none == {"picks": ["F2:B:1h:G1"], "label": "no pick, fail"}


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

    def fake(mk, parts, r, cost, risk_cap, detail=False):
        seen.append((r, risk_cap))
        return {k: 0 for k in ("share_M_ge_2", "share_M_ge_10", "share_M_ge_30", "worst_month", "bust", "bust_month",
                               "mean_lnM", "median_M", "max_dd", "end_multiple", "n_positions", "cut",
                               "adds_skipped", "adds_cut", "skipped")}
    monkeypatch.setattr(H, "run_signals", fake)
    H._sizing(None, [])
    assert seen == [(0.02, pytest.approx(0.16)), (0.05, pytest.approx(0.40))]


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
def _pin_tree(tmp_path, monkeypatch, study="wide"):
    root = tmp_path
    (root / "research" / "hunt").mkdir(parents=True)
    files = list(H.PREREGS[study]) + ["research/hunt/hunt.py", H.UNIVERSE_REL] + list(H.PIN_EXTRA[study])
    for f in files:
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        (root / f).write_text(f"content of {f}\n")
    lines = [f"{H.sha256_file(str(root / f))}  {f}" for f in files]
    (root / H.PIN[study]).write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(H, "ROOT", str(root))
    monkeypatch.setattr(H, "hunt_modules", lambda: ["research/hunt/hunt.py"])
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
