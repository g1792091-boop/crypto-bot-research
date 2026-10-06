"""손실 크기 규칙 (paperbot/dash/tools/size5y.py) on tiny synthetic arrays: windows never cross a split edge, months
are Korea-time months, the sizes use only the equity before a trade (no look-ahead), the risk rules lose their r% at
the stop, the null (no edge, no cost) leaves every rule flat, busts stop an account, and the re-sized v4 30-day
accounts equal rules_bt.simulate's own finals on synthetic bars (parity with the engine)."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paperbot.dash.tools import size5y as G  # noqa: E402

NS_H = 3600 * 10 ** 9


# ---------------------------------------------------------------- windows, splits, months
def test_windows_never_cross_split_edges():
    wins = G.split_windows()
    edges = {k: (a, b) for k, a, b in G.split_bounds()}
    assert [k for k, _a, _b in G.split_bounds()] == ["p1", "p2", "p3"]
    for k, w0, w1 in wins:
        a, b = edges[k]
        assert a <= w0 < w1 <= b
        assert w1 - w0 <= G.WINDOW_DAYS * G.NS_DAY
        assert w1 - w0 >= G.MIN_TAIL_DAYS * G.NS_DAY
    for (_k1, _a1, b1), (_k2, a2, _b2) in zip(wins, wins[1:]):
        assert a2 >= b1                                      # consecutive, never overlapping
    # the splits start at Korea-time midnights
    assert G.split_bounds()[1][1] == G.day_ns("2023-01-01") - 9 * NS_H
    assert G.split_bounds()[0][1] == G.span()[0]


def test_windows_tail_rule():
    d = G.NS_DAY
    assert G.windows(0, 65 * d) == [(0, 30 * d), (30 * d, 60 * d)]          # 5 days left: dropped
    assert G.windows(0, 75 * d)[-1] == (60 * d, 75 * d)                        # 15 days left: kept


def test_month_edges_are_kst_months():
    t0, t1 = G.span()
    labels, ends = G.month_edges(t0, t1)
    assert labels[0] == "2021-03" and labels[-1] == "2026-09" and len(labels) == len(ends) == 67
    assert ends[0] == G.day_ns("2021-04-01") - 9 * NS_H and ends[-1] == t1
    assert all(b > a for a, b in zip(ends, ends[1:]))


def test_at_edges_uses_trades_closed_before_the_edge():
    times = np.array([10, 20, 30])
    eq = np.array([110.0, 90.0, 120.0])
    assert G.at_edges(times, eq, [5, 20, 21, 100], 100.0).tolist() == [100.0, 110.0, 90.0, 120.0]
    assert G.at_edges(np.zeros(0, int), np.zeros(0), [5, 6], 100.0).tolist() == [100.0, 100.0]


# ---------------------------------------------------------------- statistics
def test_drawdown_cagr_metrics():
    assert G.max_drawdown(np.array([110, 55, 120]), 100.0) == pytest.approx(0.5)
    assert G.max_drawdown(np.array([110, 120]), 100.0) == 0.0
    assert G.cagr(4.0, 2.0) == pytest.approx(1.0)
    assert G.cagr(0.0, 2.0) == -1.0
    t0 = G.kst_ns("2021-03-01")
    t1 = G.kst_ns("2021-06-01")
    times = np.array([G.kst_ns("2021-03-10"), G.kst_ns("2021-04-10"), G.kst_ns("2021-05-10")])
    m = G.metrics(times, np.array([110.0, 99.0, 108.9]), 100.0, t0, t1, False, 3, 0)
    assert m["mult"] == pytest.approx(1.089) and m["mdd"] == pytest.approx(0.1)
    assert m["worst_month"] == pytest.approx(-0.1) and m["pos_months"] == pytest.approx(2 / 3)
    assert m["months"].tolist() == pytest.approx([110.0, 99.0, 108.9])
    c = G.curve_metrics(np.array([110.0, 99.0, 108.9]), 100.0, t0, t1)
    assert c["mdd"] == pytest.approx(0.1) and c["worst_month"] == pytest.approx(-0.1)


# ---------------------------------------------------------------- per-trade returns
def test_trade_returns_from_R_and_from_the_gap_open():
    fee, slip, fb = 0.0005, 0.0002, 0.0
    fill = 100.0 * (1 + slip)
    x = 101.0 * (1 - slip)                               # a long's exit at 101 with slippage
    u = x / fill
    ret_true = (u - 1) - fee * (1 + u)
    lev = 30
    R = ret_true * lev
    ret, raw = G.trade_returns([1], [fill], [R], [lev], [False], [99.0], [5], fee, slip, fb)
    assert ret[0] == pytest.approx(ret_true) and raw[0] == pytest.approx(101.0)
    # capped at the margin (liquidation): the market exit is the gap open, filled with slippage
    ret, raw = G.trade_returns([1], [fill], [-1.0], [lev], [True], [90.0], [5], fee, slip, fb)
    u = 90.0 * (1 - slip) / fill
    assert raw[0] == 90.0 and ret[0] == pytest.approx((u - 1) - fee * (1 + u))
    # a short mirrors it
    ret, raw = G.trade_returns([-1], [100.0], [-1.0], [lev], [True], [110.0], [0], fee, slip, fb)
    u = 110.0 * (1 + slip) / 100.0
    assert ret[0] == pytest.approx(-(u - 1) - fee * (1 + u))


# ---------------------------------------------------------------- the rules
@pytest.fixture(scope="module")
def sizer():
    RB = G._rb()
    return G.Sizer(G.v4_settings(RB), RB.BRACKETS)


def test_risk_rules_lose_r_at_the_stop(sizer):
    E, fill, stop, atr = 5000.0, 100.0, 99.0, 0.5
    for rule, r in G.RISK.items():
        n, m, liq = sizer.size(rule, E, 1, fill, stop, atr, False)
        qty = n / fill
        assert qty * sizer.per_unit_loss(1, fill, stop) == pytest.approx(r * E)
        assert m <= 0.5 * E + 1e-9 and liq < stop - max(0.002 * fill, atr) + 1e-9
    # a stop so tight that r% would need more than the margin cap: the size shrinks to 50% margin at the leverage;
    # 30x x $2,500 = $75,000 is over the first bracket ($50,000 at up to 50x; then 25x), so 20x fits: $50,000
    n, m, _liq = sizer.size("r2", E, 1, 100.0, 99.95, 0.01, False)
    assert m == pytest.approx(0.5 * E) and n == pytest.approx(0.5 * E * 20)


def test_half_rule_halves_the_leverage(sizer):
    E, fill, stop, atr = 5000.0, 100.0, 99.0, 0.5
    n4, m4, _ = sizer.size("v4", E, 1, fill, stop, atr, False)       # normal: 30x with 30% margin
    nh, mh, _ = sizer.size("half", E, 1, fill, stop, atr, False)     # 15x with 30% margin
    assert m4 == pytest.approx(0.3 * E) and n4 == pytest.approx(30 * 0.3 * E)
    assert mh == pytest.approx(0.3 * E) and nh == pytest.approx(n4 / 2)
    assert [lev for _t, lev in sizer.sh.tier_chain("best")] == [25, 20, 15, 10]


def _trades(ret, n=None, side=1):
    n = len(ret) if n is None else n
    return {"ret": np.asarray(ret, float), "raw": np.full(n, 100.0), "side": np.full(n, side), "fill": np.full(n, 100.0),
            "stop": np.full(n, 99.0 if side == 1 else 101.0), "atr": np.full(n, 0.4), "best": np.zeros(n, bool),
            "t_out": np.arange(n) + 1}


def test_no_look_ahead_sizes_use_only_the_equity_before(sizer):
    rng = np.random.default_rng(1)
    ret = rng.normal(0, 0.004, 40)
    for rule in G.RULES:
        a = G.account(_trades(ret), rule, sizer, np.zeros(40, int))
        ret2 = ret.copy()
        ret2[25:] = rng.normal(0, 0.004, 15)              # change the future only
        b = G.account(_trades(ret2), rule, sizer, np.zeros(40, int))
        assert np.allclose(a["e_before"][:26], b["e_before"][:26])
        assert np.allclose(a["pnl"][:25], b["pnl"][:25])


def test_the_null_no_edge_no_cost_stays_flat(sizer):
    tr = _trades(np.zeros(30))
    for rule in G.RULES:
        res = G.account(tr, rule, sizer, np.zeros(30, int))
        eq = G.seg_equity(res, np.ones(30, bool))
        assert res["taken"].all() and np.allclose(eq, G.INITIAL) and not res["busts"]


def test_a_steady_cost_hurts_bigger_sizes_more(sizer):
    tr = _trades(np.full(200, -0.0014))                   # every trade pays the round trip and nothing else
    end = {}
    for rule in G.RULES:
        res = G.account(tr, rule, sizer, np.zeros(200, int))
        end[rule] = G.seg_equity(res, np.ones(200, bool))[-1]
    assert end["r05"] > end["r1"] > end["r2"] and all(v < G.INITIAL for v in end.values())
    assert end["half"] > end["v4"]


def test_segments_reset_and_a_bust_stops_the_account(sizer):
    ret = np.full(60, -0.03)                              # each trade loses 3% of notional: v4 dies fast
    seg = np.repeat([0, 1], 30)
    res = G.account(_trades(ret), "v4", sizer, seg)
    assert set(res["busts"]) == {0, 1}
    first = np.nonzero(res["taken"] & (seg == 1))[0][0]
    assert first == 30 and res["e_before"][first] == G.INITIAL      # a new account at the segment's first trade
    k = np.nonzero(res["taken"] & (seg == 0))[0][-1]
    assert res["e_before"][k] + res["pnl"][k] < G.BUST_BELOW and not res["taken"][k + 1:30].any()


def test_a_gap_past_the_liquidation_price_loses_the_margin(sizer):
    tr = _trades([-0.5])
    tr["raw"] = np.array([50.0])                          # opened far below any liquidation price
    res = G.account(tr, "v4", sizer, np.zeros(1, int))
    n, m, _liq = sizer.size("v4", G.INITIAL, 1, 100.0, 99.0, 0.4, False)
    assert res["pnl"][0] == pytest.approx(-m)


# ---------------------------------------------------------------- parity with the engine on synthetic bars
def _bars(n=6000, seed=3, step_min=15):
    rng = np.random.default_rng(seed)
    out = {}
    t0 = G.day_ns("2024-01-01")
    for ci, c in enumerate(G.COINS):
        lr = rng.normal(0, 0.003, n)
        c_ = 100.0 * (1 + ci) * np.exp(np.cumsum(lr))
        o = np.concatenate(([c_[0]], c_[:-1]))
        if ci == 2:
            o[3000] = o[3000] * 0.9                       # one big gap
        h = np.maximum(o, c_) * (1 + np.abs(rng.normal(0, 0.0015, n)))
        lo = np.minimum(o, c_) * (1 - np.abs(rng.normal(0, 0.0015, n)))
        tr = np.maximum(h - lo, np.abs(h - np.concatenate(([o[0]], c_[:-1]))))
        atr = np.convolve(tr, np.ones(14) / 14, mode="full")[:n]
        out[c] = {"ts": t0 + np.arange(n, dtype=np.int64) * step_min * 60 * 10 ** 9, "o": o, "h": h, "l": lo, "c": c_,
                  "atr": atr}
    return out


def test_resized_v4_30_day_accounts_equal_the_engine(sizer):
    RB, PW, L = G._rb(), G._power(), G._lib()
    bars = _bars()
    t0 = int(bars[G.COINS[0]]["ts"][0])
    t1 = int(bars[G.COINS[0]]["ts"][-1])
    wins = [("p1", a, b) for a, b in G.windows(t0, t1, days=10, min_tail_days=3)]
    sig = RB.random_signals(bars, None, 0.02, 7, "15m", L)
    old_warm = L.warmup_bars
    try:
        L.warmup_bars = lambda tf: 20                     # synthetic bars: a short warm-up
        tr = G.path_cell(RB, PW, L, bars, sig, "15m", wins, 11)
    finally:
        L.warmup_bars = old_warm
    assert len(tr["ret"]) > 50
    assert RB.INITIAL == 1000.0 and RB.BUST_BELOW == 10.0 # the engine's module values are restored
    res = G.account(tr, "v4", sizer, tr["w"].astype(int))
    fin = np.full(len(wins), G.INITIAL)
    for wi in range(len(wins)):
        e = G.seg_equity(res, tr["w"].astype(int) == wi)
        if len(e):
            fin[wi] = e[-1]
    p = G.parity_check(tr, res, fin, len(wins))
    assert p["windows"] >= 1 and p["max_diff"] < 1e-6 and p["skipped"] == 0
    # the same trades under the 1% rule: every losing stop costs about 1% of equity
    r1 = G.account(tr, "r1", sizer, np.zeros(len(tr["ret"]), int))
    lose = r1["taken"] & (r1["pnl"] < 0)
    frac = -r1["pnl"][lose] / r1["e_before"][lose]
    assert len(frac) and np.median(frac) < 0.0125
