"""research/hunt/reads_a.py: the Phase-A reads of the trend hunt (R1 goal board, the leverage read, the continuous
account reads, R15, R12 / R13 basics, D11). Synthetic paths and synthetic bars only; no real price is read.

- pure functions: windows, caps, one window, bits, intervals, board cell, controls, headline, size-fix inputs,
  continuous reads, the rule-bot unit and its fixed point, wallet risk, signal rate, concentration, overlap, D11
- engine: machine A at r = 0.5% is the tested machine bit for bit; run(ctx) end to end through hunt.reads_context on
  synthetic coins (D11 check of the hook, determinism, counts)
"""

from __future__ import annotations

import math
import os
import sys
import types

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
    # a period that ends mid-month keeps whole months only
    assert RA.calendar_windows(H.day_ms("2024-01-01"), H.day_ms("2024-03-02")) == [
        (H.day_ms("2024-01-01"), H.day_ms("2024-02-01")), (H.day_ms("2024-02-01"), H.day_ms("2024-03-01"))]


def test_goal_mode_caps_copied_from_altpump():
    assert RA.goal_mode_caps(0.05) == (pytest.approx(0.20), 4)
    assert RA.goal_mode_caps(0.10) == (pytest.approx(0.40), 4)
    assert RA.goal_mode_caps(0.20) == (pytest.approx(0.60), 3)   # 0.6 / 0.2 = 2.9999999999999996 in floats
    with pytest.raises(ValueError):
        RA.goal_mode_caps(0.02)


def test_cell_overrides():
    r, ov = RA.cell_overrides("A", H.R_BASE)
    assert r == H.R_BASE and ov == {"PR_CAP": pytest.approx(H.RISK_CAP), "PR_BDIV": pytest.approx(H.B_DIV)}
    r, ov = RA.cell_overrides("A", 0.05)                      # W 7: cap 40%, B = equity / 6 x 10
    assert ov["PR_CAP"] == pytest.approx(0.40) and ov["PR_BDIV"] == pytest.approx(0.6)
    r, ov = RA.cell_overrides("B", 0.20)
    assert ov == {"PR_BRK_Q1": 1, "PR_CAP": pytest.approx(0.6), "PR_MAXPOS": 3, "PR_BDIV": 3.0, "PR_LEVMAX": 125}
    r, ov = RA.cell_overrides("L", 30)
    assert ov == {"PR_FIXLEV": 30, "PR_NADDS": 0, "PR_CAP": 100.0, "PR_MAXPOS": 3}
    assert set(ov) | {"PR_BRK_Q1", "PR_LEVMAX", "PR_BDIV"} <= set(H.PR_NAMES)
    cells = RA.board_cells()
    assert len(cells) == 9 and ("B", 0.02) not in cells and ("B", 0.05) in cells
    assert [RA.cell_key(*c) for c in cells[:2]] == ["A|0.5%", "A|1%"] and RA.cell_key("L", 20) == "L|20x"


def test_rolling_control_seeds_guard():
    assert RA.rolling_control_seeds(0.01) == 100
    assert RA.rolling_control_seeds(0.031) == 50


# ------------------------------------------------------------------ one window
def test_touch_and_window_record():
    eq = [1100, 2100, 1800, 5200, 4000, 3000]               # daily marked path of a fresh $1,000
    rec = RA.window_from_path(eq, DAY, pnl=[1500, 600, -100, 1000])
    cols = RA.cols_from_bits([rec["bits"]])
    assert cols["touch_x2"][0] == 1 and cols["touch_x5"][0] == 1 and cols["touch_x10"][0] == 0
    assert cols["end_ge_x2"][0] == 1 and cols["end_ge_x5"][0] == 0 and cols["bust"][0] == 0
    assert rec["days_to"][0] == 2.0 and rec["days_to"][1] == 4.0 and rec["days_to"][2] is None
    assert rec["m_end"] == 3.0 and rec["peak_m"] == 5.2
    assert rec["give_back"] == pytest.approx((5200 - 3000) / 5200)
    assert rec["n80"] is None                                # ends below x5
    assert rec["resolution"] == "daily"


def test_window_closed_end_and_eighty_percent_count():
    rec = RA.window_from_path([3000, 7000, 9000], FIVE, end_closed=8800.0, pnl=[5000, 2000, 900, -100])
    assert rec["m_end"] == pytest.approx(8.8) and rec["m_marked"] == 9.0
    assert rec["resolution"] == "5m" and rec["days_to"][0] == pytest.approx(FIVE / DAY)
    assert rec["days_to"][1] == pytest.approx(2 * FIVE / DAY)
    assert rec["n80"] == 2                                   # gain 7,800: 5,000 + 2,000 >= 6,240


def test_n_positions_for_share():
    assert RA.n_positions_for_share([500, 300, 200, -100], 900) == 2
    assert RA.n_positions_for_share([100, 100], 1000) is None   # never reached
    assert RA.n_positions_for_share([1, 2], -5) is None


def test_bust_window_and_bits():
    rec = RA.window_from_path([800, 90, 90], DAY)
    assert rec["bust"] and rec["m_end"] == pytest.approx(0.09)
    assert RA.cols_from_bits([rec["bits"]])["bust"][0] == 1
    b = RA.bits_of(100.0, 120.0, True)
    assert b == (1 << 7) - 1 | ((1 << 7) - 1) << 7 | 1 << 14 and b < 2 ** 15   # fits int16


# ------------------------------------------------------------------ intervals
def test_clopper_pearson_known_values():
    lo, hi = RA.clopper_pearson(0, 33)
    assert lo == 0.0 and hi == pytest.approx(1 - 0.025 ** (1 / 33), abs=1e-9) and round(hi, 3) == 0.106
    lo, hi = RA.clopper_pearson(33, 33)
    assert hi == 1.0 and lo == pytest.approx(0.025 ** (1 / 33), abs=1e-9)
    lo, hi = RA.clopper_pearson(5, 20)
    assert lo == pytest.approx(0.0866, abs=1e-4) and hi == pytest.approx(0.4910, abs=1e-4)
    assert RA.clopper_pearson(5, 20) == pytest.approx(H.clopper_pearson(5, 20))     # the engine's helper agrees
    assert RA.clopper_pearson(0, 0) == (None, None)


def test_block_bootstrap_shapes_and_determinism():
    idx = RA.block_indices(100, 30, 50, seed=7)
    assert idx.shape == (50, 100)
    d = np.diff(idx, axis=1)
    assert (d[:, :29] == 1).all()                            # each row starts with a run of 30 consecutive starts
    assert (RA.block_indices(100, 30, 50, seed=7) == idx).all()
    assert not (RA.block_indices(100, 30, 50, seed=8) == idx).all()
    assert RA.boot_ci(np.ones(100), idx, 0.9) == (1.0, 1.0)
    assert (RA.block_indices(10, 30, 5, seed=1) == np.arange(10)).all()   # block longer than the series


def test_goal_seed_parts():
    assert RA.goal_seed("hunt-wide", "pick:X", "test", "B", 0.05) == H.seed_int(
        "hunt-wide", "goalboard", "pick:X", "test", "B", 0.05, "boot")


# ------------------------------------------------------------------ board cell, controls, headline, size fix
def _recs(ms):
    return [RA.window_from_path([m * 1000.0], DAY) for m in ms]


def test_board_cell_calendar():
    c = RA.board_cell(_recs([1.0, 2.5, 6.0, 0.5, 1.2]), "calendar")
    assert c["n_windows"] == 5
    assert c["shares"]["end_ge_x2"] == pytest.approx(0.4) and c["shares"]["end_ge_x5"] == pytest.approx(0.2)
    assert c["shares"]["touch_x2"] == pytest.approx(0.4)
    assert c["ci"]["end_ge_x2"] == pytest.approx(RA.clopper_pearson(2, 5))
    assert c["median_m"] == 1.2 and c["worst_m"] == 0.5 and c["best_m"] == 6.0
    assert c["mean_ln_m"] == pytest.approx(np.mean(np.log([1.0, 2.5, 6.0, 0.5, 1.2])))
    assert c["n_touch_x5"] == 1 and c["n_end_ge_x5"] == 1 and c["median_days_to_x5"] == 1.0
    assert RA.board_cell([], "calendar") == {"windows": "calendar", "n_windows": 0, "resolution": []}


def test_board_cell_rolling_uses_block_bootstrap():
    recs = _recs(list(np.linspace(0.5, 3.0, 60)))
    c = RA.board_cell(recs, "rolling", seed=11)
    lo, hi = c["ci"]["end_ge_x2"]
    assert lo <= c["shares"]["end_ge_x2"] <= hi and c["note"] == RA.INDEPENDENT_LINE
    assert c == RA.board_cell(recs, "rolling", seed=11)


def test_control_columns():
    bits = lambda ms: [r["bits"] for r in _recs(ms)]  # noqa: E731
    pick = bits([3, 3, 3, 1])                                 # 3 of 4 windows end >= x2
    ctl = np.asarray([bits([3, 1, 1, 1]), bits([1, 1, 1, 1])])   # seed shares 0.25 and 0.0
    c = RA.control_columns(pick, ctl, "calendar", seed=5)
    col = c["columns"]["end_ge_x2"]
    assert c["n_seeds"] == 2 and col["pick"] == 0.75 and col["control_pooled"] == pytest.approx(0.125)
    assert col["control_p5"] == pytest.approx(0.0125) and col["control_p95"] == pytest.approx(0.2375)
    assert col["pick_minus_control"] == pytest.approx(0.625)
    lo, hi = col["ci90"]
    assert lo <= 0.625 <= hi
    with pytest.raises(ValueError):
        RA.control_columns(pick, np.asarray([bits([1, 1])]), "calendar", seed=5)


def test_headline_and_size_fix_inputs():
    recs = _recs([6, 1, 1, 1])
    bits = lambda ms: [r["bits"] for r in _recs(ms)]  # noqa: E731
    pb = [r["bits"] for r in recs]
    rb = {"test": {"calendar": {"B|5%": {
        "cell": RA.board_cell(recs, "calendar"),
        "controls": {"a": RA.control_columns(pb, np.asarray([bits([1, 1, 1, 1])]), "calendar", 1),
                     "b": RA.control_columns(pb, np.asarray([bits([6, 6, 1, 1])]), "calendar", 2)}}}}}
    h = RA.headline_of(rb)
    assert h["share"] == 0.25 and h["control_a"] == 0.0 and h["control_b"] == 0.5 and h["n_windows"] == 4
    assert h["ci"] == pytest.approx(RA.clopper_pearson(1, 4)) and h["control_seeds"] == 1
    assert RA.headline_of({}) is None
    RA.check_headline_spec(H.HEADLINE_CELL)                   # the engine's named cell is this module's cell
    with pytest.raises(ValueError):
        RA.check_headline_spec({**H.HEADLINE_CELL, "r": 0.10})
    sel = {"A|0.5%": RA.board_cell(_recs([1.1, 0.9]), "calendar"), "B|5%": RA.board_cell(_recs([3, 0.05]), "calendar")}
    inp = RA.size_fix_inputs(sel)
    assert [(x["machine"], x["r"]) for x in inp] == [("A", 0.005), ("B", 0.05)]
    assert inp[1]["bust_share"] == 0.5
    assert H.size_fixed_on_select(inp)["machine"] == "A"     # B busts in half the months


def test_effective_risk_columns():
    ratio = np.array([1.0, 1.0, 0.5, 0.25])
    cut = np.array([0, 2, 2, 4])                             # margin budget, margin budget, free wallet
    e = RA.effective_risk(0.10, ratio, cut, [0, 1, 2, 3], [5, 10, 10, 20], brk_skips=2)
    assert e["effective_r"] == pytest.approx(0.10 * 0.75)
    assert e["share_first_unit_cut"] == 0.75
    assert e["share_first_unit_cut_by"] == {"liquidity": 0.0, "margin_budget": 0.5, "free_wallet": 0.25}
    assert e["share_add_level"] == [0.75, 0.5, 0.25] and e["median_leverage"] == 10.0
    assert e["adds_skipped_bracket"] == 2
    assert RA.effective_risk(None, ratio, cut, [0] * 4, [20] * 4)["effective_r"] is None


# ------------------------------------------------------------------ continuous-account reads
def test_best_runup_inside_30_days():
    t0 = H.day_ms("2024-01-01")
    vals = {0: 1000, 10: 600, 30: 1500, 45: 1000, 75: 3000, 80: 4000}
    days = np.arange(81)
    eq = np.interp(days, list(vals), list(vals.values()))
    r = RA.best_runup(t0 + days * DAY, eq)
    want = max(eq[j] / eq[max(0, j - 30):j + 1].min() for j in range(len(eq)))
    assert r["multiple"] == pytest.approx(want) and r["days"] <= 30 and r["multiple"] < 4.0


def test_drawdown_and_longest_under_water():
    t0 = H.day_ms("2024-01-01")
    eq = np.array([100, 120, 90, 60, 100, 125, 110, 130, 129, 128.0])
    d = RA.drawdown_recovery(t0 + np.arange(len(eq)) * DAY, eq)
    assert d["max_dd"] == pytest.approx(0.5)
    assert d["dd_peak_day"] == "2024-01-02" and d["dd_trough_day"] == "2024-01-04"
    assert d["dd_recover_day"] == "2024-01-06" and d["dd_recover_days"] == 4.0 and not d["dd_recover_open"]
    assert d["longest_under_water_days"] == 4.0 and not d["under_water_open"]
    eq2 = np.array([100, 80, 70, 75, 90, 95.0])              # never recovers: open stretch to the end
    d2 = RA.drawdown_recovery(t0 + np.arange(6) * DAY, eq2)
    assert d2["dd_recover_open"] and d2["under_water_open"] and d2["longest_under_water_days"] == 5.0
    d3 = RA.drawdown_recovery(t0 + np.arange(4) * DAY, np.array([1.0, 2, 3, 4]))
    assert d3["max_dd"] == 0.0 and d3["longest_under_water_days"] == 0.0


def test_continuous_reads():
    t0 = H.day_ms("2024-01-01")
    lnM = [math.log(1.1), math.log(0.9), math.log(1.2)]
    c = RA.continuous_reads(t0, 5000.0, [5100, 5200, 4900, 5300], DAY, lnM, 5300.0, max_dd_5m=0.12)
    assert c["resolution"] == "daily" and c["whole_period_multiple"] == pytest.approx(1.06)
    assert c["geo_mean_monthly_return"] == pytest.approx((1.1 * 0.9 * 1.2) ** (1 / 3) - 1)
    assert c["max_dd"] == 0.12 and c["max_dd_path"] == pytest.approx(300 / 5200)
    assert c["best_30d_runup"]["multiple"] == pytest.approx(5300 / 4900)


# ------------------------------------------------------------------ leverage read
def _br(caps=(25_000.0, 100_000.0, np.inf), levs=(20, 10, 5), mmrs=(0.025, 0.05, 0.10)):
    cum, rows = 0.0, []
    for i, (c, lv, m) in enumerate(zip(caps, levs, mmrs)):
        if i:
            cum += caps[i - 1] * (m - mmrs[i - 1])
        rows.append((c, lv, m, cum))
    n = len(rows)
    return {"n": np.array([n]), "cap": np.array([[r[0] for r in rows]]), "lev": np.array([[r[1] for r in rows]]),
            "mmr": np.array([[r[2] for r in rows]]), "cum": np.array([[r[3] for r in rows]]),
            "min_notional": np.array([5.0])}


def test_effective_leverage_follows_the_engine_rule():
    br = _br()
    assert RA.effective_L(20, 1000.0, br, 0) == 20           # 4,000 notional: tier 0 allows 20x
    assert RA.effective_L(30, 1000.0, br, 0) == 20           # 9,000 at 30x not allowed -> 20x (tier 0 maximum)
    assert RA.effective_L(40, 10_000.0, br, 0) == 5          # 160,000 -> tier 2 (5x); 5% x 10,000 x 5 in tier 0
    br2 = _br(caps=(25_000.0, 100_000.0), levs=(20, 10), mmrs=(0.025, 0.05))
    assert RA.effective_L(20, 1_000_000.0, br2, 0) == 0      # notional above every tier: the engine skips it


def test_rulebot_unit_sizes_and_checks():
    br = _br()
    slip = H.COSTS["base"][1]
    u = RA.rulebot_unit(20, 1000.0, 100.0, 1, 2.0, 1.0, br, 0)
    assert u["margin"] == pytest.approx(200.0) and u["notional"] == pytest.approx(4000.0)
    assert u["q"] == pytest.approx(4000.0 / (100 * (1 + slip)))
    # liquidation at 20x, mmr 2.5%: about 2.6% below the fill; the stop is 2% below: gap 0.6 < 1 ATR (1.0) -> skip
    assert not u["ok"] and u["reason"] == "liq_buffer"
    assert u["liq"] == pytest.approx((u["notional"] - u["margin"]) / (u["q"] * (1 - 0.025)))
    u = RA.rulebot_unit(20, 1000.0, 100.0, 1, 1.0, 0.2, br, 0)   # stop 1% away, buffer max(0.2%, 0.2) -> ok
    assert u["ok"] and u["wallet_risk_per_stop"] == pytest.approx(u["q"] * 1.0 / 1000.0)
    s = RA.rulebot_unit(20, 1000.0, 100.0, -1, 1.0, 0.2, br, 0)  # short mirror
    assert s["ok"] and s["liq"] > s["stop"] > 100.0
    assert RA.rulebot_unit(20, 1e9, 100.0, 1, 1.0, 0.2, _br(caps=(25_000.0,), levs=(20,), mmrs=(0.025,)),
                           0)["reason"] == "bracket"
    ok = RA.lev_check(20, np.array([1000.0, 1000.0, 0.0]), np.array([100.0, 100.0, 100.0]), np.array([1, 1, 1]),
                      np.array([2.0, 1.0, 1.0]), np.array([1.0, 0.2, 0.2]), np.array([0, 0, 0]), br)
    assert ok.tolist() == [False, True, True]                 # a zero equity is left to the engine ('bad_price')


def test_run_lev_fixed_point():
    """Signal 2 passes the check at the start equity but not at the equity its fill sees once signal 1 has run
    (a higher tier): the second run drops it and the third confirms."""
    br = _br(caps=(20_000.0, np.inf), levs=(50, 50), mmrs=(0.004, 0.05))
    a = H.day_ms("2024-01-01")
    b = a + DAY
    sig = {"tf": "1h", "k": np.array([0, 0]), "j": np.array([1, 2]), "side": np.array([1, 1])}
    info = {"close": np.array([a, a + 19 * FIVE]), "fill": np.array([a, a + 20 * FIVE]),
            "P0": np.array([100.0, 100.0]), "atr": np.array([0.5, 0.5]), "d0": np.array([3.6, 3.6]),
            "k": np.array([0, 0]), "side": np.array([1, 1])}
    calls = []

    def run(sub, a_, b_, **kw):
        kept = sub[0][0]["j"].tolist()
        calls.append(kept)
        eqp = np.full((b_ - a_) // FIVE, 1000.0)
        if 1 in kept:
            eqp[10:] = 6000.0                                  # signal 1 made the wallet 6x by step 10
        return {"equity_path": eqp, "end": eqp[-1], "end_marked": eqp[-1], "peak": eqp.max(), "bust": False}

    # tier 0 (4,000 notional at $1,000): liquidation about 95.40, stop 96.4: gap 1.0 >= buffer 0.5 -> kept;
    # tier 1 (24,000 at $6,000, mmr 5%, cum 920): liquidation about 95.99: gap 0.41 < 0.5 -> skipped
    u0 = RA.rulebot_unit(20, 1000.0, 100.0, 1, 3.6, 0.5, br, 0)
    u1 = RA.rulebot_unit(20, 6000.0, 100.0, 1, 3.6, 0.5, br, 0)
    assert u0["ok"] and u0["tier"] == 0 and not u1["ok"] and u1["tier"] == 1 and u1["reason"] == "liq_buffer"
    res = RA.run_lev(run, [(sig, 1)], [info], a, b, 20, br, close_end=True)
    assert calls == [[1, 2], [1]] and res["lev_runs"] == 2 and res["lev_converged"]
    assert res["lev_buffer_skipped"] == 1


def test_wallet_risk_table():
    t = RA.wallet_risk_table(np.array([0.01, 0.02, 0.03]))
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
    assert r["per_day_all"]["max"] == 12 and r["per_day_all"]["mean"] == pytest.approx(16 / 3)
    assert r["per_day_all"]["p50"] == 4 and isinstance(r["per_day_all"]["p95"], int)
    assert r["per_day_N"]["max"] == 2
    assert r["per_close_all"]["max"] == 12 and r["per_close_all"]["closes_with_events"] == 3
    assert r["per_close_all"]["share_closes_gt_10"] == pytest.approx(1 / 3) and r["per_close_all"]["closes_gt_10"] == 1
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
    assert len(RA.union_events([])["distinct"]["close_ms"]) == 0


def test_taken_by_month_and_judge_budget():
    a = H.day_ms("2024-01-01")
    b = H.day_ms("2024-03-01")
    td = RA.taken_by_month([a + DAY, a + 2 * DAY, H.day_ms("2024-02-03")], [a + DAY], {"risk_cap": 1}, a, b)
    assert td["candidates_by_month"] == {"2024-01": 2, "2024-02": 1}
    assert td["dropped_by_month"] == {"2024-01": 1, "2024-02": 1} and td["skipped_by_reason_total"] == {"risk_cap": 1}
    rate = RA.signal_rate(np.r_[np.full(30, a + 5), np.full(4, H.day_ms("2024-02-10"))], np.ones(34, bool), a, b)
    jb = RA.judge_budget(rate, 0.5)
    assert jb["usd_per_month_max"] == pytest.approx(15.0) and jb["months_over_stop"] == 0
    assert jb["usd_per_day_max"] == pytest.approx(15.0)
    assert RA.judge_budget(rate, 30.0)["months_over_stop"] == 1     # 30 calls x $30 = $900 > $665
    assert RA.judge_budget(rate, None)["usd_per_call"] is None
    assert RA.judge_budget(rate, None, "all")["calls_per_month"]["max"] == 30


# ------------------------------------------------------------------ R12 / R13 basics
def test_concentration():
    pnl = np.array([1000.0, 200, 100, -50, -50, 30, 20, 10, 5, -5, 300])
    lnM = np.log([1.5, 0.9, 1.1, 1.0])
    c = RA.concentration(pnl, np.full(len(pnl), 50.0), lnM)
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


# ------------------------------------------------------------------ D11
def test_d11_split_keeps_labels_and_counts_only():
    cell = RA.board_cell(_recs([3, 1, 6]), "calendar")
    row = {"row": "pick:F3:DS1:1h:G1", "kind": "pick", "label": "pick", "members": ["F3:DS1:1h:G1"],
           "periods": {"test": {"calendar": {"B|5%": {"cell": {**cell, "skipped": {"no_leverage": 3}},
                                                       "machine": {"machine": "B", "r": 0.05}}}}},
           "n_positions": 12, "multiple": 4.2}
    pub, priv = RA.split_ds({"pick:F3:DS1:1h:G1": row, "pick:F2:X:1h:G1": dict(row, row="pick:F2:X:1h:G1")},
                            {"pick:F3:DS1:1h:G1": True})
    p = pub["pick:F3:DS1:1h:G1"]
    assert p["row"] == "pick:F3:DS1:1h:G1" and p["n_positions"] == 12 and "multiple" not in p
    c = p["periods"]["test"]["calendar"]["B|5%"]
    assert c["cell"] == {"windows": "calendar", "n_windows": 3, "resolution": ["daily"],
                         "skipped": {"no_leverage": 3}} and c["machine"] == {"machine": "B"}
    assert "D11" in p["note"] and priv["pick:F3:DS1:1h:G1"]["multiple"] == 4.2
    assert pub["pick:F2:X:1h:G1"]["periods"]["test"]["calendar"]["B|5%"]["cell"]["shares"]
    assert "pick:F2:X:1h:G1" not in priv
    assert H.d11_problems(pub, {"F3:DS1:1h:G1"}) == []
    assert RA.ints_only({"a": 1.5, "b": {"c": 2, "d": 0.1}, "e": [1, 2.0]}) == {"b": {"c": 2}, "e": [1]}


# ------------------------------------------------------------------ engine: machine A at 0.5% is the tested machine
S0 = H.day_ms("2023-05-01")
EXTRA = (H.day_ms("2023-12-01"), H.day_ms("2024-01-01"))
SELECT = (H.day_ms("2024-01-01"), H.day_ms("2024-02-01"))
TEST = (H.day_ms("2024-02-01"), H.day_ms("2024-03-02"))
SYMS = ["BTCUSDT", "ETHUSDT", "AAAUSDT"]


def _events(spec, sym, ser, btc):
    """Deterministic synthetic events (replaces entries_wide in these tests)."""
    n = len(ser.bars.close_ms)
    i = np.arange(n)
    off = (sum(map(ord, sym)) + sum(map(ord, spec["name"]))) % 13
    return (i % 29 == off), (i % 31 == (off + 7) % 31)


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    coins = {s: H.synth_coin(s, S0, TEST[1], 500 + i, 50.0 * (i + 1)) for i, s in enumerate(SYMS)}
    fund = {s: H.synth_funding(S0, TEST[1], 900 + i) for i, s in enumerate(SYMS)}
    H.install(coins, fund)
    orig = H.entry_events
    H.entry_events = _events
    mks = {"extra": H.Market(SYMS, EXTRA, name="extra"), "select": H.Market(SYMS, SELECT, name="select"),
           "test": H.Market(SYMS, TEST, name="test")}
    for m in mks.values():
        H._G["mk"][m.key] = m
    yield {"mks": mks, "tmp": tmp_path_factory.mktemp("reads_a")}
    H.entry_events = orig


def _spec(i, name, kind, family):
    return {"id": f"{family}:{name}:1h:NONE", "family": family, "name": name, "strategy": name, "kind": kind,
            "tf": "1h", "gate": "NONE", "combo": {}, "pick_no": i, "batch": 1, "rank": None}


def test_machine_a_at_half_percent_is_bit_identical(synth):
    mks = synth["mks"]
    spec = _spec(1, "AAA", "core", "F2")
    a, b = TEST
    r, ov = RA.cell_overrides("A", H.R_BASE)
    x = H.run_engine(spec, a, b, r=r, start_wallet=1000.0, overrides=ov, path="5m", mks=mks, universe=SYMS)
    y = H.run_engine(spec, a, b, r=r, start_wallet=1000.0, path="5m", mks=mks, universe=SYMS)
    assert x["metrics"]["n_positions"] > 0
    assert np.array_equal(x["equity_path"], y["equity_path"]) and x["end"] == y["end"]
    for k in x["trades"]:
        assert np.array_equal(np.asarray(x["trades"][k]), np.asarray(y["trades"][k]))


def _ctx(synth, monkeypatch):
    mks = synth["mks"]
    picks = [_spec(1, "AAA", "core", "F2"), _spec(2, "DSX", "ds", "F3")]
    test_doc = {"picks": picks, "verdict": {"passing": [], "label": "picks", "wide_pass": False},
                "results": {p["id"]: {} for p in picks}, "lineup": {}}
    args = types.SimpleNamespace(procs=1, private=str(synth["tmp"]), data=str(synth["tmp"]))
    ctx = H.reads_context("wide", args=args, pin=None, mks=mks, syms=SYMS, test_doc=test_doc, full=None,
                          reads_pin={"listed_before_test_json": True}, private_path=str(synth["tmp"] / "p.json"))
    ctx["rows"] = [r for r in ctx["rows"] if r["kind"] != "v1"]
    ctx["periods"] = {"extra": list(EXTRA), "select": list(SELECT), "test": list(TEST)}
    ctx["log"] = lambda m: None
    for k, v in (("CAL_CTL_SEEDS", 3), ("ROLL_CTL_SEEDS", 2), ("ROLL_CTL_SEEDS_SLOW", 2), ("LEV_CTL_SEEDS", 2),
                 ("MBB_N", 200)):
        monkeypatch.setattr(RA, k, v)
    return ctx


def test_run_end_to_end_on_synthetic_coins(synth, monkeypatch):
    ctx = _ctx(synth, monkeypatch)
    rows = {r["row"]: r for r in ctx["rows"]}
    assert set(rows) == {"pick:F2:AAA:1h:NONE", "pick:F3:DSX:1h:NONE", "basket_batch1"}
    RA.run(ctx)
    out, priv = ctx["out"], ctx["private"]
    ds_ids = {"F3:DSX:1h:NONE", "pick:F3:DSX:1h:NONE", "basket_batch1"}
    assert H.d11_problems(out, ds_ids) == []                  # the hook's own D11 check
    g = out["r1_goal_board"]["pick:F2:AAA:1h:NONE"]
    cal = g["periods"]["test"]["calendar"]
    assert set(cal) == {RA.cell_key(*c) for c in RA.board_cells()}
    assert cal["B|5%"]["cell"]["n_windows"] == 1 and cal["B|5%"]["controls"]["a"]["n_seeds"] == 3
    assert g["periods"]["test"]["rolling"]["A|0.5%"]["cell"]["n_windows"] == 1
    assert g["periods"]["select"]["rolling"]["A|0.5%"]["cell"]["n_windows"] == 2
    assert g["periods"]["select"]["rolling"]["A|0.5%"]["controls"]["b"]["n_seeds"] == 2
    assert g["periods"]["extra"]["calendar"]["A|1%"]["period_label"] == "extra 2020"
    assert g["headline"]["n_windows"] == 1 and g["headline"]["control_seeds"] == 3
    assert all(e["size_label"] in ("size fixed before the test", "forward-only evidence") for e in cal.values())
    if g["size_fixed_on_select"]:
        assert cal[g["size_fixed_on_select"]["cell"]]["size_label"] == "size fixed before the test"
    eff = cal["A|0.5%"]["cell"]["effective_risk"]
    assert eff["nominal_r"] == H.R_BASE and eff["n_positions"] >= 1
    lev = out["leverage"]["pick:F2:AAA:1h:NONE"]
    lc = lev["periods"]["test"]["calendar"]["L|20x"]
    assert lc["leverage"]["L"] == 20 and lc["controls"]["a"]["n_seeds"] == 2
    assert set(lev["wallet_risk_table_test_signals"]) == {"20", "30", "40"}
    # DeepSeek row and the basket that holds it: labels and counts in public, everything in private
    pd = out["r1_goal_board"]["pick:F3:DSX:1h:NONE"]
    assert pd["note"] == RA.DS_NOTE and "headline" not in pd
    assert priv["r1_goal_board"]["pick:F3:DSX:1h:NONE"]["headline"]["n_windows"] == 1
    assert out["r1_goal_board"]["basket_batch1"]["note"] == RA.DS_NOTE
    assert "basket_batch1" in priv["continuous"]
    # continuous reads, R12, R13, R15
    c = out["continuous"]["pick:F2:AAA:1h:NONE"]["periods"]["test"]
    k = "r=0.5% ($5,000, tested machine)"
    assert c[k]["resolution"] == "5m" and c[k]["best_30d_runup"]["multiple"] >= 1.0
    assert out["r12_basics"]["pick:F2:AAA:1h:NONE"]["periods"]["test"]["n_positions"] >= 1
    r15 = out["r15_signal_rate"]["rows"]["pick:F2:AAA:1h:NONE"]["test"]
    assert r15["gated_matches_signals"] and r15["gate_blocked"] == 0          # gate NONE blocks nothing
    assert r15["taken_dropped"]["taken"] == out["r12_basics"]["pick:F2:AAA:1h:NONE"]["periods"]["test"][
        "n_positions"]
    rds = out["r15_signal_rate"]["rows"]["pick:F3:DSX:1h:NONE"]["test"]
    assert isinstance(rds["events"], int) and "mean" not in rds["per_day_all"]
    assert out["r13_basics"]["test"]["ids"] == ["pick:F2:AAA:1h:NONE", "pick:F3:DSX:1h:NONE"]
    assert "pick:F2:AAA:1h:NONE|pick:F3:DSX:1h:NONE" in priv["r13_basics"]["test"]["signal_overlap"]
    assert "signal_overlap" not in out["r13_basics"]["test"]
    assert out["reads_line_before_test_json"] is True and out["constants"]["calendar_control_seeds"] == 3
    # determinism: a second run gives the same figures
    ctx2 = _ctx(synth, monkeypatch)
    RA.run(ctx2)
    strip = lambda d: {k: v for k, v in d.items() if k not in ("seconds", "constants")}  # noqa: E731
    assert repr(strip(ctx2["out"])) == repr(strip(out))
