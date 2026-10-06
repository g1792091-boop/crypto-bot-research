"""장세 스위치 generator (paperbot/dash/tools/regime5y.py): the pure pieces on tiny synthetic arrays.

Look-ahead (a regime at bar t never changes when later bars change), the period splits (no 30-day account crosses a
period edge), the rule chosen on the pick period only, the coin-flip null (no edge -> no survivors), BH, the switch.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from paperbot.dash.tools import regime5y as G


def walk(n=3000, seed=0, vol=None):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.004 if vol is None else 1, n)
    if vol is not None:
        r = r * vol
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, n)))
    return h, lo, c


def test_regimes_are_causal():
    h, lo, c = walk(2400, 1)
    full = G.regimes(h, lo, c, 240, vol_days=60, vol_min_days=20)
    for t in (700, 1200, 1900):
        h2, l2, c2 = h.copy(), lo.copy(), c.copy()
        h2[t + 1:] *= 3.0          # change only the future bars
        l2[t + 1:] *= 0.5
        c2[t + 1:] *= 1.7
        cut = G.regimes(h2, l2, c2, 240, vol_days=60, vol_min_days=20)
        assert np.array_equal(full["code"][:t + 1], cut["code"][:t + 1])
        for k in ("adx", "slope", "atrp", "vol_q"):
            np.testing.assert_allclose(full[k][:t + 1], cut[k][:t + 1], equal_nan=True)


def test_regime_labels_and_precedence():
    # a steady climb, then a calm flat stretch, then a violent stretch (bar ranges vary a little, as real bars do)
    rng = np.random.default_rng(2)
    up = np.linspace(100, 200, 500)
    flat = 200 + 0.05 * np.sin(np.arange(500))
    wild = 200 + 15 * np.sin(np.arange(500) * 1.7)
    c = np.r_[up, flat, wild]
    spread = np.r_[np.full(500, 0.005), np.full(500, 0.0005), np.full(500, 0.02)] * rng.uniform(0.8, 1.2, 1500)
    h, lo = c * (1 + spread), c * (1 - spread)
    r = G.regimes(h, lo, c, 240, vol_days=60, vol_min_days=10)    # 6 bars a day: 60 bars before the threshold exists
    code = r["code"]
    assert (code[:59] == G.UNKNOWN).all()
    assert (code[100:480] == G.TREND).mean() > 0.6                # ADX high and EMA50 rising (the rest: its own top 20%)
    assert (code[1000:1200] == G.SHOCK).mean() > 0.8              # ATR% far above the calm months before
    calm = code[700:1000]
    assert (calm == G.RANGE).mean() > 0.9 and not (calm == G.TREND).any()
    assert set(np.unique(code)) <= {G.UNKNOWN, G.TREND, G.RANGE, G.SHOCK, G.NORMAL}
    # shock beats trend: where the ATR% test is on, the label is shock whatever ADX says
    on = np.nan_to_num(r["atrp"]) >= np.nan_to_num(r["vol_q"], nan=np.inf)
    known = code != G.UNKNOWN
    assert (code[on & known] == G.SHOCK).all() and (on[100:480] & (r["adx"][100:480] >= 25)).any()


def test_atr_is_wilder():
    h, lo, c = walk(400, 3)
    _adx, atr = G.adx_atr(h, lo, c)
    tr = np.maximum.reduce([h[1:] - lo[1:], np.abs(h[1:] - c[:-1]), np.abs(lo[1:] - c[:-1])])
    want = [tr[:14].mean()]
    for x in tr[14:]:
        want.append(want[-1] + (x - want[-1]) / 14)
    np.testing.assert_allclose(atr[14:], want, rtol=1e-12)
    assert np.isnan(atr[:14]).all()


def test_windows_never_cross_periods():
    w = G.period_windows()
    edges = {G.day_ns(b) for _k, _a, b in G.PERIODS} | {G.day_ns(a) for _k, a, _b in G.PERIODS}
    for key, w0, w1 in w:
        p = next(p for p in G.PERIODS if p[0] == key)
        assert G.day_ns(p[1]) <= w0 < w1 <= G.day_ns(p[2])
        assert w1 - w0 <= G.WINDOW_DAYS * G.NS_DAY
        assert not any(w0 < e < w1 for e in edges)
    assert [k for k, *_ in w].count("pick") >= 18
    # a short tail under 10 days is dropped, 10 days or more is kept
    assert G.windows(0, 35 * G.NS_DAY) == [(0, 30 * G.NS_DAY)]
    assert G.windows(0, 41 * G.NS_DAY)[-1] == (30 * G.NS_DAY, 41 * G.NS_DAY)


def test_window_pnl_compounds():
    R, mf = np.array([0.5, -0.5]), np.array([0.2, 0.2])
    p = G.window_pnl(R, mf, 1000.0)
    assert p.tolist() == pytest.approx([100.0, -110.0])


def test_choose_rule_uses_only_given_trades_and_needs_enough():
    reg = np.array([G.TREND] * 40 + [G.RANGE] * 40 + [G.NORMAL] * 10 + [G.UNKNOWN] * 5)
    R = np.r_[np.full(40, 0.3), np.full(40, -0.2), np.full(10, 0.0), np.full(5, 9.0)]
    assert G.choose_rule(reg, R) == [G.TREND]                    # normal has only 10 trades; unknown never counts
    # the mean to beat is every known pick-period trade's, the small regime's too (docs/regime5y.md)
    R2 = R.copy()
    R2[80:90] = 5.0
    assert G.choose_rule(reg, R2) is None
    assert G.choose_rule(reg[:40], R[:40]) is None               # one regime only: nothing beats its own mean
    assert G.choose_rule(np.array([G.TREND] * 50), np.zeros(50)) is None
    assert G.choose_rule(np.array([G.UNKNOWN] * 50), np.ones(50)) is None
    # all four above the mean is impossible; four candidates with one below gives the other three
    reg4 = np.repeat([G.TREND, G.RANGE, G.SHOCK, G.NORMAL], 30)
    R4 = np.r_[np.full(30, 1.0), np.full(30, 1.0), np.full(30, 1.0), np.full(30, -3.0)]
    assert G.choose_rule(reg4, R4) == [G.TREND, G.RANGE, G.SHOCK]


def _cell(rng, edge):
    def side(n, e):
        reg = rng.choice([G.TREND, G.RANGE, G.SHOCK, G.NORMAL], n)
        R = rng.normal(-0.05, 0.6, n) + e * (reg == G.TREND)
        return reg.astype(np.int8), R
    return {k: side(400, edge) for k in ("a", "b")}, {k: side(1200, 0.0) for k in ("a", "b")}


def test_null_gives_no_survivors_and_an_edge_does():
    rng = np.random.default_rng(7)
    cells = []
    for _ in range(144):
        base, flips = _cell(rng, 0.0)
        cells.append({"test": G.cell_test(base, flips, [G.TREND])})
    head = G.finish_tests(cells)
    assert head["tested"] == 144 and head["survivors"] <= 2
    ps = [c["test"]["p"] for c in cells]
    assert 0.3 < float(np.mean(ps)) < 0.7                         # roughly uniform under the null
    rng = np.random.default_rng(8)
    cells = []
    for i in range(20):
        base, flips = _cell(rng, 0.6 if i < 5 else 0.0)
        cells.append({"test": G.cell_test(base, flips, [G.TREND])})
    head = G.finish_tests(cells)
    assert head["survivors"] >= 4
    assert all(c["test"]["survivor"] for c in cells[:4])


def test_same_edge_for_coin_flips_is_not_a_finding():
    rng = np.random.default_rng(9)
    reg = rng.choice([G.TREND, G.RANGE], 2000).astype(np.int8)
    R = rng.normal(0, 0.5, 2000) + 0.5 * (reg == G.TREND)
    base = {"a": (reg[:1000], R[:1000]), "b": (reg[1000:], R[1000:])}
    flips = {"a": (reg[:1000].copy(), R[:1000] + rng.normal(0, 0.01, 1000)), "b": (reg[1000:].copy(), R[1000:].copy())}
    t = G.cell_test(base, flips, [G.TREND])
    assert t["status"] == "tested" and t["s"] > 0.3 and abs(t["s"] - t["f"]) < 0.05 and t["p"] > 0.2


def test_cell_test_states():
    e = (np.zeros(0, np.int8), np.zeros(0))
    assert G.cell_test({"a": e, "b": e}, {"a": e, "b": e}, None)["status"] == "norule"
    few = (np.array([G.TREND] * 10 + [G.RANGE] * 10, np.int8), np.zeros(20))
    assert G.cell_test({"a": few, "b": e}, {"a": few, "b": e}, [G.TREND])["status"] == "small"


def test_bh_matches_hand_computation():
    q = G.bh([0.01, 0.04, 0.03, 0.5])
    # sorted 0.01, 0.03, 0.04, 0.5 -> x 4/rank 0.04, 0.06, 0.0533, 0.5 -> running minimum from the top
    assert q == pytest.approx([0.04, 0.16 / 3, 0.16 / 3, 0.5], rel=1e-9)
    assert G.bh([]) == []
    assert all(0 <= x <= 1 for x in G.bh([0.9, 0.99, 1.0]))


def test_z_test_one_sided():
    z, p = G.z_test({"gap": 0.2, "var": 0.01}, {"gap": 0.0, "var": 0.0})
    assert z == pytest.approx(2.0) and p == pytest.approx(0.5 * math.erfc(2 / math.sqrt(2)))
    assert G.z_test({"gap": None, "var": None}, {"gap": 0.0, "var": 0.0}) == (None, None)


def test_mask_signals_switch():
    sig = np.array([1, -1, 1, 0, -1], np.int8)
    code = np.array([G.TREND, G.RANGE, G.UNKNOWN, G.TREND, G.SHOCK], np.int8)
    assert G.mask_signals(sig, code, [G.TREND, G.SHOCK]).tolist() == [1, 0, 0, 0, -1]
