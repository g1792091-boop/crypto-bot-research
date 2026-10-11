"""research/hunt/reads_a.py: the Phase-A reads of the trend hunt (R1 goal board, continuous-account reads, the
leverage read, R15, R12 / R13 basics, the paper lineup class, D11). Synthetic paths and synthetic bars only; no real
price is read.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt import reads_a as RA  # noqa: E402

DAY = H.DAY_MS
FIVE = H.FIVE


# ------------------------------------------------------------------ windows and machines
def test_window_counts_match_the_panel():
    a, b = (H.day_ms(x) for x in H.PERIODS["test"])
    assert len(RA.rolling_windows(a, b)) == 975
    assert RA.rolling_windows(a, b)[0] == (a, a + 30 * DAY)
    assert RA.rolling_windows(a, b)[-1] == (H.day_ms("2026-09-01"), b)
    assert len(RA.calendar_windows(a, b)) == 33
    a, b = (H.day_ms(x) for x in H.PERIODS["select"])
    assert len(RA.rolling_windows(a, b)) == 1066
    assert len(RA.calendar_windows(a, b)) == 36


def test_windows_from_a_first_label_day():
    a, b = (H.day_ms(x) for x in H.PERIODS["extra"])
    first = H.day_ms("2020-07-03") + 3_600_000              # rounded up to the next UTC day
    roll = RA.rolling_windows(a, b, first_ms=first)
    assert roll[0][0] == H.day_ms("2020-07-04")
    assert len(roll) == (b - H.day_ms("2020-07-04")) // DAY - 30 + 1
    cal = RA.calendar_windows(a, b, first_ms=first)
    assert cal[0] == (H.day_ms("2020-08-01"), H.day_ms("2020-09-01")) and len(cal) == 5


def test_goal_mode_caps_copied_from_altpump():
    assert RA.goal_mode_caps(0.05) == (pytest.approx(0.20), 4)
    assert RA.goal_mode_caps(0.10) == (pytest.approx(0.40), 4)
    assert RA.goal_mode_caps(0.20) == (pytest.approx(0.60), 3)   # 0.6 / 0.2 = 2.9999999999999996 in floats
    with pytest.raises(ValueError):
        RA.goal_mode_caps(0.02)


def test_machine_a_at_half_percent_is_the_tested_machine():
    m = RA.machine_spec("A", H.R_BASE)
    assert m["risk_cap"] == pytest.approx(H.RISK_CAP) and m["b_div"] == pytest.approx(H.B_DIV)
    assert m["max_pos"] == H.MAX_POS and m["lev_max"] == H.LEV_MAX
    m = RA.machine_spec("A", 0.05)                          # W 7: cap 40%, B = equity / 6 x 10
    assert m["risk_cap"] == pytest.approx(0.40) and m["b_div"] == pytest.approx(0.6)
    b = RA.machine_spec("B", 0.20)
    assert b["max_pos"] == 3 and b["b_div"] == 3.0 and b["goal_brackets"]
    cells = RA.board_cells()
    assert len(cells) == 9 and ("B", 0.02) not in cells and ("B", 0.05) in cells


def test_rolling_control_seeds_guard():
    assert RA.rolling_control_seeds(0.01) == 100
    assert RA.rolling_control_seeds(0.031) == 50


# ------------------------------------------------------------------ one window
def test_touch_and_window_record():
    eq = [1100, 2100, 1800, 5200, 4000, 3000]               # daily marked path of a fresh $1,000
    rec = RA.window_from_path(eq, DAY, pnl=[1500, 600, -100, 1000])
    assert rec["touch"][:3] == [True, True, False] and not any(rec["touch"][2:])
    assert rec["days_to"][0] == 2.0 and rec["days_to"][1] == 4.0
    assert rec["end_ge"][:2] == [True, False]
    assert rec["m_end"] == 3.0 and rec["peak_m"] == 5.2
    assert rec["give_back"] == pytest.approx((5200 - 3000) / 5200)
    assert rec["n80"] is None                                # ends below x5
    assert rec["resolution"] == "daily" and not rec["bust"]


def test_window_closed_end_and_eighty_percent_count():
    eq = [3000, 7000, 9000]
    rec = RA.window_from_path(eq, FIVE, end_closed=8800.0, pnl=[5000, 2000, 900, -100])
    assert rec["m_end"] == pytest.approx(8.8) and rec["m_marked"] == 9.0
    assert rec["resolution"] == "5m" and rec["days_to"][0] == pytest.approx(FIVE / DAY)
    assert rec["days_to"][1] == pytest.approx(2 * FIVE / DAY)
    # gain 7,800: 80% = 6,240 -> 5,000 + 2,000 = 7,000 reaches it with 2 positions
    assert rec["n80"] == 2


def test_n_positions_for_share():
    assert RA.n_positions_for_share([500, 300, 200, -100], 900) == 2
    assert RA.n_positions_for_share([100, 100], 1000) is None   # never reached
    assert RA.n_positions_for_share([1, 2], -5) is None


def test_bust_window():
    rec = RA.window_from_path([800, 90, 90], DAY)
    assert rec["bust"] and rec["m_end"] == pytest.approx(0.09)


# ------------------------------------------------------------------ intervals
def test_clopper_pearson_known_values():
    lo, hi = RA.clopper_pearson(0, 33)
    assert lo == 0.0 and hi == pytest.approx(1 - 0.025 ** (1 / 33), abs=1e-9) and round(hi, 3) == 0.106
    lo, hi = RA.clopper_pearson(33, 33)
    assert hi == 1.0 and lo == pytest.approx(0.025 ** (1 / 33), abs=1e-9)
    lo, hi = RA.clopper_pearson(5, 20)
    assert lo == pytest.approx(0.0866, abs=1e-4) and hi == pytest.approx(0.4910, abs=1e-4)
    assert RA.clopper_pearson(0, 0) == (None, None)


def test_block_bootstrap_shapes_and_determinism():
    idx = RA.block_indices(100, 30, 50, seed=7)
    assert idx.shape == (50, 100)
    d = np.diff(idx, axis=1)
    assert (d[:, :29] == 1).all()                            # each row starts with a run of 30 consecutive starts
    assert (RA.block_indices(100, 30, 50, seed=7) == idx).all()
    assert not (RA.block_indices(100, 30, 50, seed=8) == idx).all()
    v = np.ones(100)
    assert RA.boot_ci(v, idx, 0.9) == (1.0, 1.0)
    one = RA.block_indices(10, 30, 5, seed=1)                # block longer than the series: the series itself
    assert (one == np.arange(10)).all()


def test_goal_seed_parts():
    assert RA.goal_seed("F2:X:1h:G1", "test", "B", 0.05) == H.seed_int("hunt-wide", "goalboard", "F2:X:1h:G1",
                                                                        "test", "B", 0.05, "boot")


# ------------------------------------------------------------------ board cell, controls, headline, size fix
def _recs(ms, bust=None):
    return [RA.window_from_path([m * 1000.0], DAY) if bust is None or not bust[i]
            else RA.window_from_path([50.0], DAY) for i, m in enumerate(ms)]


def test_board_cell_calendar():
    recs = _recs([1.0, 2.5, 6.0, 0.5, 1.2])
    c = RA.board_cell(recs, "calendar")
    assert c["n_windows"] == 5
    assert c["shares"]["end_ge_x2"] == pytest.approx(0.4) and c["shares"]["end_ge_x5"] == pytest.approx(0.2)
    assert c["shares"]["touch_x2"] == pytest.approx(0.4)
    assert c["ci"]["end_ge_x2"] == pytest.approx(RA.clopper_pearson(2, 5))
    assert c["median_m"] == 1.2 and c["worst_m"] == 0.5 and c["best_m"] == 6.0
    assert c["mean_ln_m"] == pytest.approx(np.mean(np.log([1.0, 2.5, 6.0, 0.5, 1.2])))
    assert c["n_touch_x5"] == 1 and c["n_end_ge_x5"] == 1


def test_board_cell_rolling_uses_block_bootstrap():
    recs = _recs(list(np.linspace(0.5, 3.0, 60)))
    c = RA.board_cell(recs, "rolling", seed=11)
    lo, hi = c["ci"]["end_ge_x2"]
    assert lo <= c["shares"]["end_ge_x2"] <= hi and c["note"] == RA.INDEPENDENT_LINE
    assert c == RA.board_cell(recs, "rolling", seed=11)


def test_control_columns():
    pick = _recs([3, 3, 3, 1])                               # 3 of 4 windows end >= x2
    ctl = [_recs([3, 1, 1, 1]), _recs([1, 1, 1, 1])]          # seed shares 0.25 and 0.0
    c = RA.control_columns(pick, ctl, "calendar", seed=5)
    col = c["columns"]["end_ge_x2"]
    assert col["pick"] == 0.75 and col["control_pooled"] == pytest.approx(0.125)
    assert col["control_p5"] == pytest.approx(0.0125) and col["control_p95"] == pytest.approx(0.2375)
    assert col["pick_minus_control"] == pytest.approx(0.625)
    lo, hi = col["ci90"]
    assert lo <= 0.625 <= hi
    with pytest.raises(ValueError):
        RA.control_columns(pick, [_recs([1, 1])], "calendar", seed=5)


def test_headline_cell():
    recs = _recs([6, 1, 1, 1])
    board = {("test", "calendar", "B", 0.05): {"cell": RA.board_cell(recs, "calendar"),
                                                "controls": {"a": RA.control_columns(recs, [_recs([1, 1, 1, 1])],
                                                                                     "calendar", 1),
                                                             "b": RA.control_columns(recs, [_recs([6, 6, 1, 1])],
                                                                                     "calendar", 2)}}}
    h = RA.headline(board)
    assert h["share"] == 0.25 and h["control_a"] == 0.0 and h["control_b"] == 0.5 and h["n_windows"] == 4
    assert h["ci"] == pytest.approx(RA.clopper_pearson(1, 4))
    assert RA.headline({}) is None


def test_size_fixed_on_select():
    def cell(mean_ln, bust):
        return {"n_windows": 36, "mean_ln_m": mean_ln, "shares": {"bust": bust}}
    cells = {("A", 0.005): cell(0.01, 0.0), ("A", 0.05): cell(0.20, 0.10),     # best mean but bust 10% -> out
             ("B", 0.05): cell(0.08, 0.05), ("A", 0.02): cell(0.08, 0.0), ("B", 0.10): cell(0.05, 0.0)}
    assert RA.size_fixed_on_select(cells) == ("A", 0.02)    # tie at 0.08: lower r first
    cells[("A", 0.02)] = cell(0.08, 0.06)
    assert RA.size_fixed_on_select(cells) == ("B", 0.05)
    assert RA.size_fixed_on_select({("A", 0.005): cell(0.1, 0.5)}) is None


def test_effective_risk_columns():
    q1 = np.array([1.0, 1.0, 0.5, 0.25])
    d0 = np.array([2.0, 2.0, 2.0, 2.0])
    U = np.array([2.0, 2.0, 2.0, 2.0])
    cut = np.array([0, 2, 2, 4])                             # margin budget, margin budget, free wallet
    e = RA.effective_risk(0.10, q1, d0, U, cut, [0, 1, 2, 3], [5, 10, 10, 20])
    assert e["effective_r"] == pytest.approx(0.10 * 0.75)
    assert e["share_first_unit_cut"] == 0.75
    assert e["share_first_unit_cut_by"] == {"liquidity": 0.0, "margin_budget": 0.5, "free_wallet": 0.25}
    assert e["share_add_level"] == [0.75, 0.5, 0.25] and e["median_leverage"] == 10.0


# ------------------------------------------------------------------ continuous-account reads
def test_best_runup_inside_30_days():
    t0 = H.day_ms("2024-01-01")
    # 1,000 -> 600 (day 10) -> 1,500 (day 30): x2.5 inside 20 days; the climb to 4,000 by day 80 starts at 1,000
    # on day 45, i.e. x4 over 35 days, which is outside one 30-day window (inside: 1,000 -> 3,000 by day 75)
    vals = {0: 1000, 10: 600, 30: 1500, 45: 1000, 75: 3000, 80: 4000}
    days = np.arange(81)
    eq = np.interp(days, list(vals), list(vals.values()))
    t = t0 + days * DAY
    r = RA.best_runup(t, eq)
    w = 30
    want = max(eq[j] / eq[max(0, j - w):j + 1].min() for j in range(len(eq)))
    assert r["multiple"] == pytest.approx(want)
    assert r["days"] <= 30
    assert r["multiple"] < 4.0


def test_drawdown_and_longest_under_water():
    t0 = H.day_ms("2024-01-01")
    eq = np.array([100, 120, 90, 60, 100, 125, 110, 130, 129, 128.0])
    t = t0 + np.arange(len(eq)) * DAY
    d = RA.drawdown_recovery(t, eq)
    assert d["max_dd"] == pytest.approx(0.5)
    assert d["dd_peak_day"] == "2024-01-02" and d["dd_trough_day"] == "2024-01-04"
    assert d["dd_recover_day"] == "2024-01-06" and d["dd_recover_days"] == 4.0 and not d["dd_recover_open"]
    assert d["longest_under_water_days"] == 4.0 and not d["under_water_open"]
    eq2 = np.array([100, 80, 70, 75, 90, 95.0])              # never recovers: open stretch to the end
    d2 = RA.drawdown_recovery(t0 + np.arange(6) * DAY, eq2)
    assert d2["dd_recover_open"] and d2["under_water_open"] and d2["longest_under_water_days"] == 5.0


def test_continuous_reads():
    t0 = H.day_ms("2024-01-01")
    day_eq = [5100, 5200, 4900, 5300]
    lnM = [math.log(1.1), math.log(0.9), math.log(1.2)]
    c = RA.continuous_reads(t0, 5000.0, day_eq, DAY, lnM, 5300.0, max_dd_5m=0.12)
    assert c["resolution"] == "daily" and c["whole_period_multiple"] == pytest.approx(1.06)
    assert c["geo_mean_monthly_return"] == pytest.approx((1.1 * 0.9 * 1.2) ** (1 / 3) - 1)
    assert c["max_dd"] == 0.12 and c["max_dd_path"] == pytest.approx(300 / 5200)
    assert c["best_30d_runup"]["multiple"] == pytest.approx(5300 / 4900)


# ------------------------------------------------------------------ leverage read
def _fallback_br():
    br = H.load_brackets(["ZZZFAKEUSDT"])                     # not in exchange30.json -> the fallback table
    assert br["flags"]["ZZZFAKEUSDT"] == "fallback"
    return br


def test_rulebot_unit_sizes_and_checks():
    br = _fallback_br()
    u = RA.rulebot_unit(20, 1000.0, 1000.0, 100.0, 1, 2.0, 1.0, br, 0)
    fill = 100 * (1 + RA.H.COSTS["base"][1])
    assert u["margin"] == pytest.approx(200.0) and u["notional"] == pytest.approx(4000.0)
    assert u["q"] == pytest.approx(4000.0 / fill)
    # liquidation at 20x, mmr 2.5%: about 2.5% below the fill; the stop is 2% below: buffer 0.5% < 1 ATR (1%) -> skip
    assert not u["ok"] and u["reason"] == "liq_buffer"
    want = (u["notional"] - u["margin"] - 0.0) / (u["q"] * (1 - 0.025))
    assert u["liq"] == pytest.approx(want)
    u = RA.rulebot_unit(20, 1000.0, 1000.0, 100.0, 1, 1.0, 0.2, br, 0)   # stop 1% away, ATR 0.2 -> buffer 0.2%
    assert u["ok"] and u["wallet_risk_per_stop"] == pytest.approx(u["q"] * 1.0 / 1000.0)
    assert RA.rulebot_unit(30, 1000.0, 1000.0, 100.0, 1, 1.0, 0.2, br, 0)["reason"] == "bracket"  # fallback: 20x max
    assert RA.rulebot_unit(20, 1000.0, 150.0, 100.0, 1, 1.0, 0.2, br, 0)["reason"] == "free_wallet"
    assert RA.rulebot_unit(20, 1.0, 1.0, 100.0, 1, 1.0, 0.2, br, 0)["reason"] == "min_notional"
    s = RA.rulebot_unit(20, 1000.0, 1000.0, 100.0, -1, 1.0, 0.2, br, 0)   # short mirror
    assert s["ok"] and s["liq"] > s["stop"] > 100.0


def test_rulebot_unit_uses_a_real_bracket_table():
    br = {"n": np.array([2]), "cap": np.array([[50_000.0, np.inf]]), "lev": np.array([[50, 20]]),
          "mmr": np.array([[0.004, 0.01]]), "cum": np.array([[0.0, 300.0]]), "min_notional": np.array([5.0])}
    u = RA.rulebot_unit(40, 1000.0, 1000.0, 100.0, 1, 1.0, 0.2, br, 0)   # 16,000 notional, tier 0 allows 50x
    assert u["tier"] == 0 and u["ok"]
    u = RA.rulebot_unit(40, 10_000.0, 10_000.0, 100.0, 1, 1.0, 0.2, br, 0)  # 160,000 notional: tier 1, 20x only
    assert u["reason"] == "bracket"


def test_wallet_risk_table():
    d = np.array([0.01, 0.02, 0.03])
    t = RA.wallet_risk_table(d)
    slip = H.COSTS["base"][1]
    assert set(t) == {"20", "30", "40"}
    assert t["20"]["notional_over_equity"] == 4.0 and t["40"]["notional_over_equity"] == 16.0
    assert t["20"]["median"] == pytest.approx(4.0 / (1 + slip) * 0.02)
    assert t["40"]["median"] == pytest.approx(16.0 / (1 + slip) * 0.02)
    assert t["40"]["median_with_costs"] > t["40"]["median"]
    assert t["40"]["share_over_wallet"] == 0.0
    assert RA.wallet_risk_table([0.08])["40"]["share_over_wallet"] == 1.0


# ------------------------------------------------------------------ R15
def test_signal_rate_counts():
    a = H.day_ms("2024-01-01")
    b = a + 3 * DAY
    close = np.r_[np.full(12, a + 3_600_000), [a + DAY + 7_200_000] * 3, [a + DAY + 10_800_000], [b + 5]]
    gated = np.r_[np.ones(12, bool), [False, False, True], [True], [True]]
    r = RA.signal_rate(close, gated, a, b)
    assert r["events"] == 16 and r["gated"] == 14 and r["gate_blocked"] == 2      # the one at b is outside
    assert r["per_day_all"]["max"] == 12.0 and r["per_day_all"]["mean"] == pytest.approx(16 / 3)
    assert r["per_day_N"]["max"] == 2.0
    assert r["per_close_all"]["max"] == 12 and r["per_close_all"]["closes_with_events"] == 3
    assert r["per_close_all"]["share_closes_gt_10"] == pytest.approx(1 / 3)
    assert r["per_close_all"]["share_closes_gt_20"] == 0.0
    assert r["per_hour_all"]["max"] == 12
    assert r["by_month_G"] == {"2024-01": 14} and r["by_year_N"] == {"2024": 2}


def test_union_events_total_and_distinct():
    e1 = {"coin": [0, 1], "side": [1, -1], "close_ms": [10, 20], "gated": [True, False]}
    e2 = {"coin": [0, 2], "side": [1, 1], "close_ms": [10, 20], "gated": [False, False]}
    u = RA.union_events([e1, e2])
    assert len(u["total"]["close_ms"]) == 4 and len(u["distinct"]["close_ms"]) == 3
    g = dict(zip(zip(u["distinct"]["close_ms"].tolist(), u["distinct"]["coin"].tolist()),
                 u["distinct"]["gated"].tolist()))
    assert g[(10, 0)] is True and g[(20, 1)] is False


def test_taken_dropped_and_judge_budget():
    a = H.day_ms("2024-01-01")
    b = H.day_ms("2024-03-01")
    ms = [a + DAY, a + 2 * DAY, H.day_ms("2024-02-03"), H.day_ms("2024-02-04")]
    st = [0, 1, 0, 7]                                         # taken, coin_has_position, taken, risk_cap
    td = RA.taken_dropped(ms, st, a, b)
    assert td["total"]["taken"] == 2 and td["total"]["coin_has_position"] == 1 and td["total"]["risk_cap"] == 1
    assert td["by_month"]["taken"] == {"2024-01": 1, "2024-02": 1}
    rate = RA.signal_rate(np.r_[np.full(30, a + 5), np.full(4, H.day_ms("2024-02-10"))],
                          np.ones(34, bool), a, b)
    jb = RA.judge_budget(rate, 0.5)
    assert jb["usd_per_month_max"] == pytest.approx(15.0) and jb["months_over_stop"] == 0
    assert jb["usd_per_day_max"] == pytest.approx(15.0)
    assert RA.judge_budget(rate, 30.0)["months_over_stop"] == 1     # 30 calls x $30 = $900 > $665
    assert RA.judge_budget(rate, None)["cost_per_call"] is None


# ------------------------------------------------------------------ R12 / R13 basics
def test_concentration():
    pnl = np.array([1000.0, 200, 100, -50, -50, 30, 20, 10, 5, -5, 300])
    U = np.full(len(pnl), 50.0)
    lnM = np.log([1.5, 0.9, 1.1, 1.0])
    c = RA.concentration(pnl, U, lnM)
    gross = pnl[pnl > 0].sum()
    assert c["top10pct_share_of_profit"] == pytest.approx((1000 + 300) / gross)     # ceil(1.1) = 2 positions
    assert c["share_of_profit_ge_10R"] == pytest.approx(1000 / gross)             # 1000 / 50 = 20R
    assert c["top_month_index"] == 0
    assert c["top_month_share_of_log_gain"] == pytest.approx(math.log(1.5) / lnM.sum())
    assert RA.concentration([], [], [math.log(0.9)])["top_month_share_of_log_gain"] is None


def test_signal_and_time_overlap():
    a = {"coin": np.array([0, 0, 1]), "side": np.array([1, -1, 1]), "close_ms": np.array([0, 100, 200])}
    b = {"coin": np.array([0, 1]), "side": np.array([1, 1]), "close_ms": np.array([50, 900])}
    assert RA.signal_overlap(a, b, 60) == pytest.approx(1 / 3)
    assert RA.signal_overlap(a, b, 1000) == pytest.approx(2 / 3)
    assert RA.time_overlap(([0], [9]), ([5], [20]), 30) == pytest.approx(5 / 10)
    assert RA.time_overlap(([0], [-1]), ([0], [4]), 10) == pytest.approx(5 / 10)     # open at end: through T-1
    assert RA.corr([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert RA.corr([1, 1, 1], [1, 2, 3]) is None
    m = RA.overlap_matrix({"x": {"events": a, "tf_ms": 60, "iv": ([0], [9]), "lnM": [0.1, 0.2, -0.1]},
                           "y": {"events": b, "tf_ms": 1000, "iv": ([5], [20]), "lnM": [0.2, 0.4, -0.2]}}, 30)
    assert m["signal_overlap"]["x|y"] == pytest.approx(2 / 3) and m["corr_monthly_lnM"]["x|y"] == pytest.approx(1.0)


# ------------------------------------------------------------------ lineup, D11
def test_lineup_class():
    base = {"mean_lnM": 0.02, "median_M": 1.01, "max_dd": 0.3, "bust": False}
    cost2 = {"mean_lnM": 0.01}
    assert RA.lineup_class(True, {}, {}, None, None, None)["class"] == "정식"
    assert RA.lineup_class(False, base, cost2, 0.01, 0.02, 0.3)["class"] == "참고"
    x = RA.lineup_class(False, base, cost2, 0.01, -0.01, 0.3)
    assert x["class"] == "excluded" and not x["conditions"]["beats_b"]
    assert RA.lineup_class(False, base, cost2, 0.01, 0.02, 0.5)["class"] == "excluded"   # top month = 50%
    assert RA.lineup_class(False, {**base, "max_dd": 0.5}, cost2, 0.01, 0.02, 0.3)["class"] == "excluded"


def test_d11_split_keeps_labels_and_counts_only():
    cell = RA.board_cell(_recs([3, 1, 6]), "calendar")
    row = {"id": "F3:DS1:1h:G1", "label": "pick", "r": 0.05, "machine": "B", "cell": cell,
           "skipped": {"no_leverage": 3, "liq_buffer": 1}, "n_positions": 12, "multiple": 4.2}
    pub, priv = RA.split_public_private({"F3:DS1:1h:G1": row, "F2:X:1h:G1": dict(row, id="F2:X:1h:G1")},
                                        {"F3:DS1:1h:G1": True})
    p = pub["F3:DS1:1h:G1"]
    assert p["id"] == "F3:DS1:1h:G1" and p["r"] == 0.05 and p["n_positions"] == 12
    assert p["skipped"] == {"no_leverage": 3, "liq_buffer": 1} and "multiple" not in p
    assert p["cell"] == {"windows": "calendar", "n_windows": 3}
    assert "D11" in p["note"]
    assert pub["F2:X:1h:G1"]["cell"]["shares"]                 # a non-DeepSeek row passes unchanged
    assert priv["F3:DS1:1h:G1"]["multiple"] == 4.2
