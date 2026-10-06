"""paperbot/dash/tools/combo5y_core.py on tiny hand-made arrays: the Korea-time calendar, money per trade / day /
month, the monthly distribution, the entry-quality group (against paperbot/levrule.py itself), the merged signal rules
and their look-ahead, the statistics (clustered t, Benjamini-Hochberg, the shuffle null), the portfolio numbers and the
one shared account."""
from __future__ import annotations

import calendar
import math

import numpy as np
import pytest

from paperbot.dash.tools import combo5y_core as K

H = 3_600_000


# ---------------------------------------------------------------- calendar
def test_months_are_korea_time_and_cover_every_day():
    mons = K.months("2021-08", "2021-10")
    assert [m["label"] for m in mons] == ["2021-08", "2021-09", "2021-10"]
    # 2021-08-01 00:00 KST = 2021-07-31 15:00 UTC
    assert mons[0]["start"] == calendar.timegm((2021, 7, 31, 15, 0, 0)) * 1000
    assert mons[0]["end"] == mons[1]["start"]
    axis = K.day_axis(mons)
    assert len(axis) == 31 + 30 + 31
    sl = K.month_day_slices(mons, int(axis[0]))
    assert sl == [(0, 31), (31, 61), (61, 92)]
    assert K.kst_day(mons[0]["start"]) == axis[0]
    assert K.kst_day(mons[0]["start"] - 1) == axis[0] - 1          # one ms earlier is the day before (KST)


def test_year_slices_join_months_of_a_year():
    mons = K.months("2021-11", "2022-02")
    d0 = int(K.kst_day(mons[0]["start"]))
    ys = K.year_slices(mons, d0)
    assert ys == {2021: (0, 61), 2022: (61, 61 + 31 + 28)}


def test_bounds_in_uses_open_times_and_warmup():
    ts = np.arange(10, dtype=np.int64) * 100
    assert K.bounds_in(ts, 250, 700) == (3, 7)
    assert K.bounds_in(ts, 250, 700, warmup=5) == (5, 7)
    assert K.bounds_in(ts, 0, 10_000) == (0, 10)


# ---------------------------------------------------------------- money
def test_trade_pnl_compounds_like_rules_bt():
    # equity 1000: +50% on a 40% margin -> +200 (1200); -100% on a 50% margin -> -600 (600)
    p = K.trade_pnl(np.array([0.5, -1.0]), np.array([0.4, 0.5]), 1000.0)
    assert np.allclose(p, [200.0, -600.0])
    assert K.trade_pnl(np.zeros(0), np.zeros(0), 1000.0).shape == (0,)


def test_daily_month_and_elapsed():
    daily = np.zeros(6)
    K.daily_add(daily, np.array([0, 0, 2, 5, 9, -1]), np.array([1.0, 2.0, -4.0, 7.0, 100.0, 100.0]))
    assert daily.tolist() == [3.0, 0.0, -4.0, 0.0, 0.0, 7.0]       # outside the axis: dropped
    sl = [(0, 3), (3, 6)]
    assert K.month_sums(daily, sl).tolist() == [-1.0, 7.0]
    el = K.elapsed_matrix(daily, sl, days=4)
    assert el.tolist() == [[3.0, 3.0, -1.0, -1.0], [0.0, 0.0, 7.0, 7.0]]


def test_curve_mdd():
    dd, pk = K.curve_mdd(np.array([10.0, -30.0, 5.0]), 100.0)
    assert dd == pytest.approx(30.0) and pk == pytest.approx(30.0 / 110.0)
    assert K.curve_mdd(np.array([5.0, 5.0]), 100.0) == (0.0, 0.0)


def test_month_stats_and_rank():
    m = [0.1, -0.2, 0.05, 0.0]
    s = K.month_stats(m)
    assert s["n"] == 4 and s["best"] == 0.1 and s["worst"] == -0.2
    assert s["median"] == pytest.approx(0.025) and s["pos_share"] == 0.5
    r = K.rank_of(0.07, m)
    assert r == {"rank": 2, "of": 5, "below": 3, "n": 4, "share_below": 0.75}
    assert K.rank_of(0.5, m)["rank"] == 1 and K.rank_of(-1.0, m)["rank"] == 5
    assert K.month_stats([]) == {"n": 0}


# ---------------------------------------------------------------- the entry-quality group
def test_quality_best_equals_levrule_on_random_values():
    from paperbot.levrule import quality_group
    rng = np.random.default_rng(3)
    cell = {"a": {"higher_is_stronger": True, "edges": [0.0, 1.0, 2.0, 3.0]},
            "b": {"higher_is_stronger": False, "edges": [-3.0, -2.0, -1.0, 0.0]}}
    n = 400
    a = rng.normal(1.5, 1.5, n)
    b = rng.normal(1.5, 1.5, n)
    a[::17] = np.nan
    b[::23] = np.nan
    a[5], b[5] = 3.0, -0.0           # values exactly on an edge go up (bisect_right)
    a[6] = b[6] = np.nan             # nothing to score: normal
    got = K.quality_best({"a": a, "b": b}, cell)
    for i in range(n):
        st = {"features": [{"name": "a", "value": None if np.isnan(a[i]) else float(a[i])},
                           {"name": "b", "value": None if np.isnan(b[i]) else float(b[i])}]}
        want = quality_group(st, "X", "1h", cells={"X|1h": cell})["group"] == "best"
        assert bool(got[i]) == want, (i, a[i], b[i])
    assert not K.quality_best({"a": a}, None).any()                 # no edges: every signal normal


# ---------------------------------------------------------------- merged rules
def test_and_hand_case_and_no_look_ahead():
    ia, ib = np.array([5, 10]), np.array([4, 12])
    assert K.and_idx(ia, ib, 0).tolist() == []
    assert K.and_idx(ia, ib, 1).tolist() == [5]                    # A at 5, B one bar before
    assert K.and_idx(ia, ib, 3).tolist() == [5, 12]                # B at 12 with A at 10
    # B fires one bar AFTER A: the merged rule can only enter at B's bar, never at A's (that would see the future)
    got = K.and_idx(np.array([5]), np.array([6]), 1)
    assert got.tolist() == [6]
    assert K.and_idx(np.array([5]), np.zeros(0, int), 3).tolist() == []


def test_filter_uses_only_b_up_to_the_signal_bar():
    ia = np.array([10, 20])
    ib, bs = np.array([8, 19, 21]), np.array([1, -1, 1])
    # A10: B's latest by bar 10 is 8 (long, 2 bars back) -> kept; A20: B's latest by 20 is 19 (short) -> dropped,
    # B's long at 21 comes later and must not count
    assert K.filter_idx(ia, 1, ib, bs, 4).tolist() == [10]
    assert K.filter_idx(ia, 1, ib, bs, 1).tolist() == []            # 8 is 2 bars before 10: too old for N = 1
    assert K.filter_idx(np.array([21]), 1, ib, bs, 0).tolist() == [21]   # B on the same bar counts (known at its close)


def test_vote_sides_and_conflicts():
    st = np.array([[1, 1, -1, 0, 1],
                   [1, -1, -1, 0, -1],
                   [0, 1, -1, 1, 1]], np.int8)
    assert K.vote_sides(st, 2).tolist() == [1, 1, -1, 0, 1]
    assert K.vote_sides(st, 3).tolist() == [0, 0, -1, 0, 0]
    both = np.array([[1, 1], [1, 1], [-1, -1], [-1, -1]], np.int8)
    assert K.vote_sides(both, 2).tolist() == [0, 0]                 # both sides reach K: no entry


def test_mtf_only_closed_higher_bars():
    q = 900_000
    ts_lo = np.arange(8, dtype=np.int64) * q                         # 15m bars 00:00 .. 01:45
    ts_hi = np.arange(2, dtype=np.int64) * 4 * q                     # 1h bars 00:00, 01:00
    lc = K.closed_higher(ts_lo, "15m", ts_hi, "1h")
    # the 00:00 1h bar closes at 01:00 = the close of the 00:45 15m bar (index 3)
    assert lc.tolist() == [-1, -1, -1, 0, 0, 0, 0, 1]
    ih, hs = np.array([0]), np.array([1])                            # the 00:00 1h bar signals long
    assert K.mtf_idx(np.array([2, 3, 6]), 1, lc, ih, hs).tolist() == [3, 6]
    assert K.mtf_idx(np.array([2, 3, 6]), -1, lc, ih, hs).tolist() == []
    # 'recent': within max_age closed higher bars; at lower bar 7 the last closed 1h bar is 1, the signal is 1 bar old
    assert K.mtf_idx(np.array([7]), 1, lc, ih, hs, max_age=0).tolist() == []
    assert K.mtf_idx(np.array([7]), 1, lc, ih, hs, max_age=1).tolist() == [7]


def test_drop_conflicts_and_shift():
    il, is_ = K.drop_conflicts(np.array([1, 3, 5]), np.array([3, 7]))
    assert il.tolist() == [1, 5] and is_.tolist() == [7]
    s = K.shift_idx(np.array([0, 3, 9]), 2, 10)
    assert s.tolist() == [1, 2, 5]                                   # 9 + 2 wraps to 1; counts and spacing kept
    assert len(s) == 3


# ---------------------------------------------------------------- statistics
def test_cluster_t_hand_case():
    t, p = K.cluster_t(np.array([1.0, -1.0, 3.0, 1.0]), np.array([0, 0, 1, 1]))
    # mean 1; cluster sums of (v - mean): -2 and 2; se = sqrt(8)/4 * sqrt(2/1) = 1
    assert t == pytest.approx(1.0) and p == pytest.approx(0.5 * math.erfc(1 / math.sqrt(2)))
    assert K.cluster_t(np.array([1.0, 2.0]), np.array([0, 0])) == (None, None)   # one cluster: no error estimate


def test_bh():
    assert K.bh([0.01, 0.04, 0.03, 0.5, None], 0.05) == [True, False, False, False, False]
    assert K.bh([0.01, 0.02, 0.03], 0.05) == [True, True, True]
    assert K.bh([None, None]) == [False, False]


def test_rank_p():
    assert K.rank_p(5.0, [1.0, 2.0, 6.0]) == pytest.approx(0.5)
    assert K.rank_p(7.0, [1.0, 2.0, 6.0]) == pytest.approx(0.25)
    assert K.rank_p(None, [1.0]) is None


def test_shuffle_null_finds_a_planted_agreement_effect_and_not_noise():
    rng = np.random.default_rng(11)
    n = 20_000
    ia = np.sort(rng.choice(n, 600, replace=False))
    ib = np.sort(np.concatenate([ia[:300], rng.choice(n, 300, replace=False)]))   # B agrees with half of A
    agree = np.zeros(n, bool)
    agree[np.intersect1d(ia, ib)] = True
    planted = np.where(agree, 1.0, -0.2) + rng.normal(0, 0.1, n)
    noise = rng.normal(0, 1.0, n)

    def mean_of(eq, b_idx):
        e = K.and_idx(ia, b_idx, 0)
        return float(eq[e].mean())
    for eq, small in ((planted, True), (noise, False)):
        real = mean_of(eq, ib)
        null = [mean_of(eq, K.shift_idx(ib, int(f * n), n)) for f in np.random.default_rng(5).uniform(0.1, 0.9, 39)]
        rp = K.rank_p(real, null)
        assert (rp <= 0.05) == small, (rp, real)


# ---------------------------------------------------------------- portfolio numbers
def test_corr_tail_coloss_hand_cases():
    U = np.array([[-1.0, 0.0, -2.0, 1.0], [-1.0, -1.0, 0.0, 1.0], [2.0, 2.0, 2.0, 2.0]])
    C = K.corr_matrix(U)
    assert C[0, 1] == pytest.approx(np.corrcoef(U[0], U[1])[0, 1])
    assert np.isnan(C[0, 2]) and C[2, 2] == 1.0                      # a row that never moves
    CL = K.coloss(U)
    assert CL[0, 1] == pytest.approx(1 / 3)                         # both lost on day 0; either on days 0, 1, 2
    assert np.isnan(CL[2, 2])
    assert K.worst_days(np.array([-5.0, 0.0, -1.0, 3.0, -2.0]), 0.4).tolist() == [0, 4]
    assert K.worst_days(np.array([1.0, 2.0]), 0.5).tolist() == []    # no losing day among the worst: none
    rng = np.random.default_rng(2)
    x = rng.normal(0, 1, 400)
    T = K.tail_corr(np.vstack([x, x * 2.0, -x]), 0.05)
    assert T[0, 1] == pytest.approx(1.0) and T[0, 2] == pytest.approx(-1.0)


def test_all_scores_counts_every_combination():
    from paperbot.agents import synergy as SY
    rng = np.random.default_rng(0)
    U = rng.normal(0, 10, (5, 30))
    cap = np.full(5, 1000.0)
    sc = K.all_scores(U, cap, 2, 3, SY.curve_numbers, max_cells=50)  # tiny chunks
    assert len(sc) == math.comb(5, 2) + math.comb(5, 3)
    want = SY.curve_numbers(U[[0, 1]].sum(axis=0)[None, :], np.array([2000.0]))[3][0]
    assert sc[0] == pytest.approx(want)


def test_walk_forward_picks_on_year_n_only():
    from paperbot.agents import synergy as SY
    rng = np.random.default_rng(4)
    U = rng.normal(0, 10, (6, 20))
    cap = np.full(6, 1000.0)
    years = {2021: (0, 10), 2022: (10, 20)}
    srch = (lambda UU, cc: SY.search(UU, cc, keep=1))
    a = K.walk_forward(U, cap, years, srch, SY.curve_numbers)
    V = U.copy()
    V[:, 10:] = rng.normal(0, 50, (6, 10))                           # another year N+1: the pick must not move
    b = K.walk_forward(V, cap, years, srch, SY.curve_numbers)
    assert len(a) == 1 and a[0]["combo"] == b[0]["combo"] and a[0]["score_in"] == b[0]["score_in"]
    c = a[0]["combo"]
    want = SY.curve_numbers(U[c][:, 10:].sum(axis=0)[None, :], np.array([cap[c].sum()]))[3][0]
    assert a[0]["score_next"] == pytest.approx(want)
    assert 0.0 <= a[0]["beat_share"] <= 1.0 and a[0]["n_combos"] == sum(math.comb(6, k) for k in range(2, 6))


# ---------------------------------------------------------------- one shared account
def test_shared_month_one_position_per_coin_and_conflicts():
    calls = []

    def trade(payload, eq_share):
        calls.append((payload, eq_share))
        exit_t, pnl = payload
        return exit_t, pnl * eq_share / 100.0                         # pnl in % of the sizing share

    cands = [(0, 0, 0, 0, "BTC", 1, (10, 10.0)),     # opened: exits at 10, +10% of its share
             (5, 0, 0, 1, "BTC", -1, (20, 0.0)),     # BTC held long: opposite signal -> conflict
             (6, 0, 0, 1, "BTC", 1, (20, 0.0)),      # BTC held long: same side -> skipped
             (7, 1, 0, 0, "ETH", -1, (30, -50.0)),   # another coin: opened (share still 1000 / 2)
             (10, 0, 0, 0, "BTC", 1, (40, 0.0))]     # BTC free again at 10 (the first exit booked first)
    r = K.shared_month(cands, trade, 1000.0, 2)
    assert (r["signals"], r["entries"], r["same"], r["conflict"], r["refused"]) == (5, 3, 1, 1, 0)
    assert [c[1] for c in calls] == [500.0, 500.0, 525.0]            # after +50 booked: 1050 / 2
    assert r["final"] == pytest.approx(1000 + 50 - 250 + 0)
    assert r["wins"] == 1 and len(r["booked"]) == 3


def test_shared_month_refused_and_bust():
    r = K.shared_month([(0, 0, 0, 0, "BTC", 1, None)], lambda p, e: None, 100.0, 1)
    assert r["refused"] == 1 and r["entries"] == 0 and r["final"] == 100.0
    cands = [(0, 0, 0, 0, "BTC", 1, (1, -95.0)), (2, 0, 0, 0, "ETH", 1, (3, 0.0))]
    r = K.shared_month(cands, lambda p, e: (p[0], p[1]), 100.0, 1, bust_below=10.0)
    assert r["bust"] and r["entries"] == 1 and r["final"] == pytest.approx(5.0)


def test_r4():
    assert K.r4(1.234567) == 1.2346 and K.r4(float("nan")) is None and K.r4(None) is None
