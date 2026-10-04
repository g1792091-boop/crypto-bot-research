"""Drawdown and bust risk (agents/survival.py) and the backtest vs live gap (agents/btgap.py), owners' request
2026-10-04: the numbers on synthetic curves and trades, the Monte Carlo (deterministic, sane), the sizing k and
half-Kelly, the Friday 낙폭·파산 위험 회의 (team:risk, trigger risk_review), the compact numbers in the specialist's,
ranking and learning packets and the Sunday report, and the dashboard (schedule line, /api/profile live_risk,
strat.js)."""

import json
import math
import os
import re
import shutil
import subprocess

import numpy as np
import pytest

from paperbot.agents import btgap as BG
from paperbot.agents import digest as DG
from paperbot.agents import packets3 as P3
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.agents import survival as SV
from paperbot.agents import triggers as TR
from paperbot.models import TradeRecord

from test_new_meetings import bulk, due, tpol, world_run
from test_rooms import (DAY, HOUR, MIN, NOTE, QUIET, S, SPEC, START, QueueRunner, World, analysis, challenge, kst,
                        team_answer)

V45 = "V45_AMB"
THU = kst(2026, 10, 8, 11, 5)
FRI = kst(2026, 10, 9, 11, 5)            # Friday 11:05 KST
SAT = kst(2026, 10, 10, 11, 5)
SUN = kst(2026, 10, 11, 11, 5)
STATIC = os.path.join(os.path.dirname(__file__), "..", "paperbot", "dash", "static")


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def live(world, aid, roe, pnl, t, lev=50, equity_after=1000.0):
    """One closed trade with its own ROE (net, on margin) and P&L (they differ on purpose: units)."""
    strat, tf = aid.split("@")
    world.store.trade(aid, TradeRecord(
        strategy_id=strat, symbol="BTCUSDT", timeframe=tf, side=1, signal_ts=t - HOUR - 1, entry_time=t - HOUR,
        entry_price=100.0, exit_time=t, exit_price=100.0, exit_reason="LOCK" if pnl > 0 else "SL", qty=1.0,
        leverage=lev, tier="best", margin=50.0, stop_price=99.0, tp_price=0.0, liq_price=95.0, fees=0.1, funding=0.0,
        pnl=pnl, roe=roe, price_move=0.0, mae_price=99.0, mfe_price=101.0, equity_after=equity_after, score=0.0,
        context={}))


def curve(world, aid, values, t0, step=DAY):
    for k, v in enumerate(values):
        world.store.equity(aid, t0 + (k + 1) * step, float(v), 0.0)
    world.store.commit()


CARDS_DOC = {"meta": {"windows": {"is": ["2021-01-01", "2024-01-01"], "cf": ["2024-01-01", "2026-01-01"]}},
             "cards": [{"strategy": S, "name_ko": "켈트너·RSI", "trend_share": 0.5, "rows": [
                 {"tf": "15m", "signals_per_day": 1.0, "sized_share": 0.5, "win_rate": 0.6, "mean_roe": 0.02,
                  "mean_roe_t": 4.0},
                 {"tf": "1h", "signals_per_day": 1.0, "sized_share": 1.0, "win_rate": 0.5, "mean_roe": 0.0,
                  "mean_roe_t": None},
                 {"tf": "4h", "signals_per_day": 0.01, "sized_share": 1.0, "win_rate": 0.5, "mean_roe": 0.0,
                  "mean_roe_t": 1.0}]},
                 {"strategy": V45, "name_ko": "앰부시", "trend_share": 0.5, "rows": [
                     {"tf": "1h", "signals_per_day": 1.0, "sized_share": 1.0, "win_rate": 0.3, "mean_roe": -0.05,
                      "mean_roe_t": -5.0},
                     {"tf": "15m", "signals_per_day": 1.0, "sized_share": 1.0, "win_rate": 0.5, "mean_roe": 0.0,
                      "mean_roe_t": 1.0}]}]}


@pytest.fixture
def cards(tmp_path, monkeypatch):
    path = tmp_path / "cards.json"
    path.write_text(json.dumps(CARDS_DOC), encoding="utf-8")
    monkeypatch.setattr(P3, "CARDS", str(path))           # what btgap reads by default (agents.packets3.CARDS)
    return str(path)


def seed_gap(world, t=QUIET - DAY):
    """N17 15m: 40 trades, 8 wins (ROE +10%, $5) / 32 losses (-20%, -$10): far below its card (60%, +2%).
    N17 1h: 30 trades, 15 x +5% / 15 x -5%: like its card (50%, 0). V45 1h: 30 wins of +10%: far above its card
    (30%, -5%). V45 15m: 10 trades (5 wins): too few."""
    for k in range(40):
        win = k < 8
        live(world, f"{S}@15m", 0.10 if win else -0.20, 5.0 if win else -10.0, t - k * HOUR)
    for k in range(30):
        live(world, f"{S}@1h", 0.05 if k % 2 else -0.05, 2.0 if k % 2 else -2.0, t - k * HOUR - 1)
        live(world, f"{V45}@1h", 0.10, 4.0, t - k * HOUR - 2)
    for k in range(10):
        live(world, f"{V45}@15m", 0.05 if k % 2 else -0.05, 1.0 if k % 2 else -1.0, t - k * HOUR - 3)
    world.store.commit()


# ---------------------------------------------------------------- drawdown, streak, worst day
def test_curve_stats_on_a_synthetic_equity_series():
    ts = [k * DAY for k in range(7)]
    eq = [100, 120, 90, 110, 130, 104, 117]
    c = SV.curve_stats(ts, eq)
    assert c["max_dd_pct"] == pytest.approx(0.25) and c["max_dd_usd"] == pytest.approx(30.0)
    assert (c["max_dd_peak_ts"], c["max_dd_trough_ts"]) == (DAY, 2 * DAY)
    assert c["dd_now_pct"] == pytest.approx(0.1) and c["dd_now_usd"] == pytest.approx(13.0)
    assert c["peak"] == 130 and c["equity"] == 117 and c["change_pct"] == pytest.approx(0.17)
    assert c["days_since_peak"] == pytest.approx(2.0)                    # last peak on day 4
    assert c["longest_under_water_days"] == pytest.approx(3.0)           # day 1 -> day 4
    assert c["under_water_share"] == pytest.approx(4 / 7, abs=1e-3)
    assert c["week_max_dd_pct"] == pytest.approx(0.25)
    assert SV.curve_stats(ts, eq, now_ms=6 * DAY, week_ms=2 * DAY)["week_max_dd_pct"] == pytest.approx(0.2)
    flat = SV.curve_stats([0, DAY, 2 * DAY], [100, 110, 120])
    assert flat["max_dd_pct"] == 0 and flat["days_since_peak"] == 0 and flat["longest_under_water_days"] == 0
    assert SV.curve_stats([], []) == {"samples": 0}


def test_losing_streak_and_the_worst_kst_day():
    assert SV.losing_streak([5, -1, -2, 0, 3, -1, -1]) == {"longest": 3, "now": 2}
    assert SV.losing_streak([]) == {"longest": 0, "now": 0}
    # 23:00 and 00:30 KST are the same UTC day but two KST days
    rows = [(kst(2026, 10, 5, 1), -10.0), (kst(2026, 10, 5, 23), -5.0), (kst(2026, 10, 6, 0, 30), -12.0),
            (kst(2026, 10, 6, 9), 20.0)]
    assert SV.worst_day(rows) == {"day": "2026-10-05", "pnl": -15.0, "trades": 2}
    assert SV.worst_day([]) is None


def test_equity_returns_are_pnl_over_the_wallet_before_the_trade():
    r = SV.equity_returns([100.0, -50.0, -2000.0, 50.0], [1100.0, 1050.0, -10.0, 20.0])
    # a loss is floored at -100%; a trade without a positive wallet before it is left out
    assert r.tolist() == pytest.approx([0.1, -50 / 1100, -1.0])


# ---------------------------------------------------------------- Monte Carlo
def test_monte_carlo_is_deterministic_and_sane():
    rng = np.random.default_rng(7)
    r = np.where(rng.random(60) < 0.55, 0.03, -0.04)
    a = SV.simulate(r, 80, 5000.0, 10.0, seed=SV.account_seed("A@15m"))
    b = SV.simulate(r, 80, 5000.0, 10.0, seed=SV.account_seed("A@15m"))
    assert a == b and a["paths"] == SV.PATHS == 10_000 and a["n_trades"] == 80
    assert SV.account_seed("A@15m") != SV.account_seed("A@1h")
    assert 0.0 <= a["p_bust"] <= a["p_dd50"] <= a["p_dd30"] <= 1.0 and a["p5_end"] <= a["median_end"]
    # always winning: never busts, never down
    up = SV.simulate([0.02] * 25, 50, 5000.0, 10.0, seed=1)
    assert (up["p_bust"], up["p_dd30"], up["p_dd50"]) == (0.0, 0.0, 0.0)
    assert up["median_end"] == pytest.approx(5000 * 1.02 ** 50, rel=1e-4) and up["p5_end_pct"] > 0
    # heavy losses: busts almost always (from $5,000 to under $10 = 9 halvings net)
    down = SV.simulate([-0.5] * 15 + [0.05] * 5, 40, 5000.0, 10.0, seed=1)
    assert down["p_bust"] > 0.95 and down["p_dd50"] > 0.99
    # too few trades: no simulation; a wallet already under the line: busted
    assert SV.simulate([0.01] * 19, 30, 5000.0, 10.0) == {"too_few": True, "trades": 19, "min_trades": 20}
    assert SV.simulate([0.01] * 30, 30, 9.0, 10.0)["busted"] is True
    assert SV.bust_line() == 10.0                                          # config.v3_settings().bust_below


def test_block_draws_are_exact_and_agree_with_a_plain_bootstrap():
    lr = np.array([0.1, -0.2, 0.05], dtype=np.float32)
    s, m = SV.block_tables(lr, 2)
    assert s.tolist() == pytest.approx([lr[i] + lr[j] for i in range(3) for j in range(3)])
    assert m.tolist() == pytest.approx([min(lr[i], lr[i] + lr[j]) for i in range(3) for j in range(3)])
    s3, m3 = SV.block_tables(lr, 3)
    assert len(s3) == 27 and m3[1 * 9 + 1 * 3 + 0] == pytest.approx(-0.4)   # -0.2, -0.2, +0.1: low after two
    rng = np.random.default_rng(3)
    for n in (6, 30, 120):                                                   # blocks of 4, 3 and 2 trades
        r = np.where(rng.random(n) < 0.6, rng.normal(0.03, 0.01, n), rng.normal(-0.06, 0.03, n))
        got = SV.simulate(r, 80, 5000.0, 10.0, seed=1, min_trades=1)
        idx = np.random.default_rng(99).integers(0, n, size=(20_000, 80))
        cum = np.cumsum(np.log1p(r)[idx], axis=1)
        low = np.minimum(cum.min(axis=1), 0.0)
        assert got["p_dd30"] == pytest.approx(float((low <= math.log(0.7)).mean()), abs=0.025)
        assert got["median_end"] == pytest.approx(5000 * math.exp(float(np.median(cum[:, -1]))), rel=0.03)


# ---------------------------------------------------------------- sizing and Kelly
def test_sizing_k_is_monotonic_and_matches_a_brute_force_search():
    rng = np.random.default_rng(11)
    r = np.where(rng.random(60) < 0.6, rng.normal(0.03, 0.01, 60), rng.normal(-0.08, 0.03, 60))
    z = SV.sizing(r, seed=5)
    assert z["label"] == "설명용, 판정 아님" and z["paths"] == SV.SIZING_PATHS and z["trades"] == 100
    idx_t = np.random.default_rng(6).integers(0, 60, size=(100, SV.SIZING_PATHS), dtype=np.int32)
    ks = np.round(np.arange(0.02, 4.0, 0.02), 2)
    ps = [SV.p_drop(r, k, idx_t) for k in ks]
    assert all(a <= b for a, b in zip(ps, ps[1:]))                         # a bigger position: never safer
    best = max(k for k, p in zip(ks, ps) if p < 0.01)
    assert z["k"] == pytest.approx(best, abs=0.025)
    assert SV.p_drop(r, z["k"], idx_t) < 0.01
    # twice the risk per trade: half the k (the same paths)
    assert SV.sizing(2 * r, seed=5)["k"] == pytest.approx(z["k"] / 2, abs=0.012)
    heavy = SV.sizing(np.where(rng.random(40) < 0.5, 0.05, -0.25), seed=1)
    assert heavy["k"] < 1 and heavy["smaller"] is True and heavy["k_ko"].startswith("지금 크기의 0.")
    safe = SV.sizing([0.01] * 30, seed=1)
    assert safe["capped"] is True and safe["k"] == SV.SIZING_K_MAX and safe["k_ko"] == "지금 크기의 4.0배 이상"
    assert SV.sizing([0.01] * 19)["too_few"] is True


def test_half_kelly_and_no_edge():
    k = SV.kelly([0.04] * 6 + [-0.02] * 4)                                 # p .6, payoff 2: f = .6 - .4 / 2 = .4
    assert k["kelly"] == pytest.approx(0.4) and k["half_kelly"] == pytest.approx(0.2)
    assert k["half_kelly_x_now"] == pytest.approx(10.0) and "no_edge" not in k
    n = SV.kelly([0.02] * 5 + [-0.04] * 5)                                 # p .5, payoff .5: f = -.5
    assert n["kelly"] == pytest.approx(-0.5) and n["half_kelly"] == 0.0 and n["no_edge"] is True
    assert "no edge" in n["note"]
    assert SV.kelly([0.01] * 5)["kelly"] is None and SV.kelly([-0.01] * 5)["no_edge"] is True


# ---------------------------------------------------------------- paper3.db: accounts, strategies, timeframes
def test_table_per_account_strategy_and_timeframe(world):
    now = QUIET
    curve(world, f"{S}@15m", [5200, 4680, 5000, 4800], START)
    curve(world, f"{S}@1h", [5000, 5100, 5100, 5000], START)
    for k in range(25):                                                     # 25 trades: simulated
        world.trade(f"{S}@15m", 20.0 if k % 3 else -30.0, now - (k + 1) * HOUR)
    world.trade(f"{S}@1h", -10.0, now - 30 * HOUR)
    world.store.put_state("accounts", now, {"engines": {f"{V45}@1h": {"wallet": 4.0, "bust": True},
                                                        f"{S}@15m": {"wallet": 4900.0, "bust": False}}})
    world.store.commit()
    tab = SV.table(world.paper(), now)
    a = tab["accounts"][f"{S}@15m"]
    assert a["curve"]["max_dd_pct"] == pytest.approx(0.1) and a["wallet"] == 4900.0 and a["trades"] == 25
    days = (now - START) / DAY
    assert a["trades_per_30d"] == round(25 * 30 / days)
    assert a["mc"]["n_trades"] == a["trades_per_30d"] and a["mc"]["start"] == 4900.0 and "k" in a["sizing"]
    assert a["losing_streak"]["longest"] == 1
    one = tab["accounts"][f"{S}@1h"]
    assert one["mc"]["too_few"] is True and one["sizing"]["too_few"] is True
    assert tab["accounts"][f"{V45}@1h"]["bust"] is True and tab["busted"] == [f"{V45}@1h"]
    assert tab["accounts"][f"{V45}@1h"]["mc"] == {"busted": True, "trades": 0}
    # N17 = the sum of its two accounts: 10,000 at the start, 10,200, 9,780, 10,100, 9,800
    g = tab["strategies"][S]
    assert g["curve"]["max_dd_pct"] == pytest.approx(420 / 10200, abs=1e-4) and g["curve"]["peak"] == 10200
    assert g["curve"]["dd_now_pct"] == pytest.approx(400 / 10200, abs=1e-4) and g["trades"] == 26
    assert g["simulated"] == 1 and g["too_few"] == 1 and g["p_bust_max"]["timeframe"] == "15m"
    assert tab["strategies"][V45]["busted"] == [f"{V45}@1h"]
    assert tab["timeframes"]["15m"]["accounts"] == 2 and tab["coin_flips"]["accounts"] == 1
    assert SV.table(world.paper(), now)["accounts"][f"{S}@15m"]["mc"] == a["mc"]          # deterministic


# ---------------------------------------------------------------- backtest vs live
def test_backtest_gap_flags_units_and_summary(world, cards):
    seed_gap(world)
    got = BG.load_cards(cards)
    assert got[S]["15m"]["trades_approx"] == round(1.0 * 1826 * 0.5)               # signals/day x days x sized share
    assert got[S]["15m"]["mean_se"] == pytest.approx(0.005)                         # |mean / t|
    assert got[S]["1h"]["mean_se"] is None                                  # no t-value: live sd only
    tab = BG.gap_table(world.paper(), QUIET, cards=got)
    s15 = tab["strategies"][S]["by_tf"]["15m"]
    # units: per-trade net ROE on margin (trades.roe), not P&L / equity (-$10 on $1,000 would be -1%)
    assert s15["live_mean_roe"] == pytest.approx((8 * 0.10 - 32 * 0.20) / 40)
    assert s15["live_win_rate"] == 0.2 and s15["win_rate_diff_pp"] == pytest.approx(-40.0)
    assert s15["flag"] == "worse" and s15["flag_ko"] == "실전이 백테스트보다 유의하게 나쁨" and s15["win_rate_p"] < 1e-6
    assert tab["strategies"][S]["by_tf"]["1h"]["flag"] == "similar"
    assert tab["strategies"][V45]["by_tf"]["1h"]["flag"] == "better"
    assert tab["strategies"][V45]["by_tf"]["1h"]["flag_ko"] == "유의하게 좋음"
    assert tab["strategies"][V45]["by_tf"]["15m"]["flag"] == "too_few"                  # 10 live trades
    small_bt = tab["strategies"][S]["by_tf"]["4h"]                                       # no live trades either
    assert small_bt["flag"] == "too_few" and small_bt["bt_trades_approx"] == 18
    # pooled per strategy: N17 expected 40 x .6 + 30 x .5 = 39 wins, got 23; V45 expected 30 x .3 + 10 x .5 = 14, got 35
    assert tab["strategies"][S]["total"]["flag"] == "worse" and tab["strategies"][S]["total"]["live_trades"] == 70
    assert tab["strategies"][S]["total"]["bt_win_rate"] == pytest.approx(39 / 70, abs=1e-4)
    assert tab["strategies"][V45]["total"]["flag"] == "better" and tab["strategies"][V45]["total"]["live_trades"] == 40
    sm = tab["summary"]
    assert (sm["strategies_tested"], sm["strategies_worse"], sm["strategies_better"]) == (2, 1, 1)
    assert sm["strategies_worse_share"] == 0.5 and sm["trust_warning"] is True
    assert "그대로 믿으면 안 됨" in sm["statement_ko"] and "2개 중 1개" in sm["statement_ko"]
    assert sm["cells"]["tested"] == 3 and sm["cells"]["worse"] == 1 and sm["cells"]["too_few"] >= 2
    pk = BG.packet(world.paper(), QUIET, names_ko={S: "켈트너·RSI"})                   # the default cards (monkeypatched)
    assert [r["strategy"] for r in pk["flagged"]] == [S, V45] and pk["flagged"][0]["name_ko"] == "켈트너·RSI"
    assert "증거금 대비 순 ROE" in pk["how_to_read"] and pk["flags"][S]["total"] == "worse"
    assert BG.strategy_flags(world.paper(), S, QUIET)["total"]["flag"] == "worse"
    assert BG.packet(world.paper(), QUIET, cards_path=str(cards) + ".missing")["error"]


def test_backtest_gap_few_strategies_worse_is_no_warning(world, cards):
    for k in range(30):
        live(world, f"{S}@1h", 0.05 if k % 2 else -0.05, 2.0 if k % 2 else -2.0, QUIET - k * HOUR)
    world.store.commit()
    sm = BG.gap_table(world.paper(), QUIET)["summary"]
    assert sm["strategies_tested"] == 1 and sm["strategies_worse"] == 0 and sm["trust_warning"] is False
    assert BG.gap_table(world.paper(), 0)["summary"]["trust_warning"] is None                      # no trades yet


def test_tests_agree_with_scipy():
    st = pytest.importorskip("scipy.stats")
    for k, n, p in ((3, 20, 0.5), (8, 40, 0.6), (30, 30, 0.3), (12, 25, 0.48), (0, 21, 0.1)):
        assert BG.binom_two_sided(k, n, p) == pytest.approx(st.binomtest(k, n, p).pvalue, rel=1e-6, abs=1e-12)
    assert BG.norm_two_sided(1.96) == pytest.approx(0.05, abs=1e-3)
    assert BG.flag_of(0.01, -0.1, 0.5, 0.01) == ("worse", False)
    assert BG.flag_of(0.01, -0.1, 0.01, 0.02) == ("similar", True)          # opposite ways: mixed
    assert BG.flag_of(0.2, 0.1, 0.3, 0.02) == ("similar", False)


def test_the_real_cards_hold_what_the_gap_needs():
    """research/strategy_profiles/out_binance/cards.json is in the repository (installed with the code tree)."""
    got = BG.load_cards()
    assert len(got) == 36 and P3.CARDS.endswith(os.path.join("out_binance", "cards.json"))
    row = got["N17_KC_RSI"]["1h"]
    assert 0 < row["win_rate"] < 1 and row["mean_se"] and row["trades_approx"] > 30


# ---------------------------------------------------------------- packets
def test_survival_packet_worst_first_with_the_backtest_gap(world, cards):
    seed_gap(world)
    curve(world, f"{S}@15m", [5200, 3900, 4000], START)
    curve(world, f"{S}@1h", [5000, 5000, 5000], START)
    curve(world, f"{V45}@1h", [5100, 5000, 5300], START)
    curve(world, f"{V45}@15m", [5000, 5000, 5000], START)
    pk = SV.survival_packet(world.paper(), QUIET)
    assert pk["label"] == "설명용, 판정 아님" and pk["bust_below"] == 10.0 and pk["settings"]["paths"] == 10_000
    assert [r["strategy"] for r in pk["strategies"]] == [S, V45]                       # deepest first
    n17 = pk["strategies"][0]
    assert n17["max_dd_pct"] == pytest.approx(1300 / 10200, abs=1e-3) and n17["bt"] == "worse"
    assert set(n17["by_tf"]) == {"15m", "1h"} and "pb" in n17["by_tf"]["15m"] and "k" in n17["by_tf"]["15m"]
    assert pk["strategies"][1]["bt"] == "better"
    assert pk["backtest_gap"]["summary"]["trust_warning"] is True and "flags" not in pk["backtest_gap"]
    assert pk["summary"]["accounts_simulated"] == 3 and pk["summary"]["accounts_too_few"] == 1
    assert "몬테카를로" in pk["how_to_read"]
    assert len(json.dumps(pk, ensure_ascii=False)) < 15_000


# ---------------------------------------------------------------- the Friday meeting: trigger
def test_risk_review_is_off_by_default_and_on_with_the_server_policy():
    assert TR.TriggerPolicy().risk_review_hour_kst == -1
    assert TR.ANALYSES["risk_review"] == (4, "team:risk") and TR.ANALYSIS_KO["risk_review"] == "낙폭·파산 위험 회의"
    assert TR.TRIGGER_CLASS["risk_review"] == "weekly" and TR.PRIORITY["risk_review"] == 4
    assert "risk_review" in RM.RoomsPolicy().paced_triggers and RM.TRIGGER_KO["risk_review"] == "낙폭·파산 위험 회의"
    p = RM.policy_from_env({})
    assert p.triggers.risk_review_hour_kst == 11
    assert RM.policy_from_env({"AGENTS_RISK_REVIEW_HOUR": "off"}).triggers.risk_review_hour_kst == -1
    assert RM.policy_from_env({"AGENTS_RISK_REVIEW_HOUR": "10"}).triggers.risk_review_hour_kst == 10
    with pytest.raises(ValueError):
        RM.policy_from_env({"AGENTS_RISK_REVIEW_HOUR": "24"})
    h = RM.schedule_hours(p)
    assert h["risk_review"] == 11 and h["analysis_weekdays"]["risk_review"] == 4
    assert RM.schedule_hours(RM.RoomsPolicy())["risk_review"] == -1
    assert RM._PROBE["risk_review"] == "team:risk" and RM.MEETING_FILE["risk_review"] == "rooms_meeting_risk.md"
    assert "survival" in RM.CODE_ROOTS and "risk_review" in RM.LEAD_HYPOTHESIS_MEETINGS
    assert RM.MEETING_PACKETS["risk_review"][0] == "survival"


def test_risk_review_meets_on_friday_only_with_enough_data(world):
    bulk(world, 120, FRI - HOUR)
    pol = tpol(enabled=("risk_review",), risk_review_hour_kst=11)
    assert due(world, FRI, TR.TriggerPolicy(enabled=("risk_review",))) == []          # off in TriggerPolicy()
    assert due(world, FRI, pol) == []                                                 # 120 < 200 in the week
    st = TR.skipped_status(world.paper(), FRI, pol)["risk_review"]
    assert st["ok"] is False and "최소 200건" in st["why"] and st["slot"] == "2026-10-09"
    bulk(world, 100, FRI - 2 * HOUR, aid=f"{V45}@1h")
    assert due(world, THU, pol) == []                                                 # Thursday: not its day
    assert due(world, FRI - 10 * MIN, pol) == []                                      # 10:55: not yet
    [d] = due(world, FRI, pol)
    assert (d.room_id, d.trigger, d.data["key"], d.data["class"]) == ("team:risk", "risk_review",
                                                                      "risk_review:2026-10-09", "weekly")
    assert "낙폭·파산 위험 회의 (11:00)" in d.data["summary_ko"] and d.data["trades"] == 220
    world_run(world, d, FRI)
    assert due(world, FRI + HOUR, pol) == [] and due(world, SAT, pol) == []           # once a week


def test_risk_review_extra_run_with_twice_the_data_two_days_later_at_most_twice_a_week(world):
    bulk(world, 250, FRI - HOUR)
    pol = tpol(enabled=("risk_review",), risk_review_hour_kst=11)
    [d] = due(world, FRI, pol)
    world_run(world, d, FRI)
    bulk(world, 400, SAT - HOUR, step=MIN)                                           # 2 x 200 by Saturday ...
    assert due(world, SAT, pol) == []                                                # ... but one day after Friday
    assert "뒤 1일(최소 2일)" in TR.skipped_status(world.paper(), SAT, pol, world.agents)["risk_review"]["extra"]["why"]
    [x] = due(world, SUN, pol)
    assert x.data["key"] == "risk_review:extra:2026-10-11" and x.data["extra_run"] is True
    world_run(world, x, SUN)
    bulk(world, 800, SUN + 5 * HOUR, step=MIN)
    assert due(world, SUN + 6 * HOUR, pol) == []                                     # never a third in the week
    assert [y.data["key"] for y in due(world, FRI + 7 * DAY, pol)] == ["risk_review:2026-10-16"]


# ---------------------------------------------------------------- the Friday meeting: end to end
def test_risk_review_meeting_speakers_packet_and_hypotheses(world, cards):
    bulk(world, 250, FRI - HOUR, aid=f"{V45}@15m")
    seed_gap(world, FRI - 30 * HOUR)
    curve(world, f"{S}@15m", [5200, 4000], FRI - 3 * DAY)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("risk_review",), risk_review_hour_kst=11))
    pred = {"metric": "win_rate", "timeframe": "15m", "direction": "below", "value": 0.5, "after_trades": 50}
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [],
            "hypotheses": [{"strategy": S, "text": "실전 승률이 백테스트보다 낮은 상태가 이어짐", "how_to_confirm": "50건",
                            "prediction": pred}]}
    runner = QueueRunner({"risk_officer": [team_answer("r", "survival.strategies.0.max_dd_pct")],
                          "validator": [team_answer("v", "survival.backtest_gap.summary.strategies_worse")],
                          "team_lead": [lead]})
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
                  policy=pol, now_ms=FRI, clock_ms=lambda: FRI)
    assert [(r["room_id"], r["trigger"], r["status"], r["class"]) for r in out["rounds"]] == [
        ("team:risk", "risk_review", "done", "weekly")]
    assert runner.roles() == ["risk_officer", "validator", "team_lead"] and out["rounds"][0]["calls"] == 3
    pk = runner.calls[0]["packet"]
    assert pk["survival"]["label"] == "설명용, 판정 아님"
    assert pk["survival"]["backtest_gap"]["summary"]["strategies_worse"] >= 1
    assert pk["survival"]["strategies"][0]["strategy"] == S and "league" in pk["board"]
    assert "survival" in runner.calls[1]["packet"] and set(runner.calls[1]["packet"]["board"]) <= {"meta"}
    sysp = runner.calls[1]["system"]
    assert "낙폭·파산 위험 회의" in sysp and "백테스트와 실전의 차이" in sysp and "30일" in sysp
    assert "hypotheses" in runner.calls[2]["system"]
    said = {m["role"]: m["text"] for m in R.room_messages(world.agents, "team:risk", limit=50)}
    assert "[사실]" in said["risk_officer"] and "[사실]" in said["validator"]            # survival.* is code's
    rows = R.trial_history(world.agents, kinds=("hypothesis",), limit=5)
    assert rows[0]["strategy"] == S and rows[0]["room_id"] == "team:risk"
    d = TR.Due("team:risk", "risk_review", 0, {}, "risk_review")
    assert RM.round_min_calls(d, pol) == RM.round_max_calls(d, pol) == 3 <= pol.max_calls_team_round
    assert [r for r, _t in RM.team_plan(d)] == ["risk_officer", "validator", "team_lead"]


# ---------------------------------------------------------------- the other packets
def test_a_specialist_sees_its_own_drawdown_bust_risk_and_backtest_gap(world, cards):
    seed_gap(world, QUIET - 2 * DAY)
    curve(world, f"{S}@15m", [5300, 4000, 4100], START)
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE)], f"spec_{V45}": [analysis(NOTE)],
                          "devils_advocate": [challenge("agree")] * 2})
    world.tick(runner, QUIET, policy=RM.RoomsPolicy(triggers=tpol(enabled=("loss_cluster",))))
    [call] = [c for c in runner.calls if c["role"] == SPEC]
    sv = call["packet"]["specialist"]["survival"]
    # the summed curve: only the accounts with equity samples (15m here: its own start, $5,000)
    assert sv["total"]["max_dd_pct"] == pytest.approx(1300 / 5300, abs=1e-3) and set(sv["by_tf"]) == {"15m", "1h"}
    assert "p_bust" in sv["by_tf"]["15m"] and "k" in sv["by_tf"]["15m"] and "half_kelly" in sv["by_tf"]["15m"]
    assert sv["backtest_gap"]["total"]["flag"] == "worse" and V45 not in json.dumps(sv)
    assert "설명용" in sv["note"]


def test_the_ranking_review_has_drawdown_and_bust_risk_for_the_picked_strategies(world):
    seed_gap(world)
    t = kst(2026, 10, 7, 14, 5)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("ranking",), ranking_hour_kst=14))
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}
    runner = QueueRunner({"performance": [team_answer("f")], "pnl_reviewer": [team_answer("p")],
                          "risk_officer": [team_answer("r")], "team_lead": [lead]})
    world.tick(runner, t, policy=pol)
    pk = runner.calls[0]["packet"]["ranking"]
    sv = pk["survival"]["strategies"]
    assert set(sv) == {r["strategy"] for r in pk["picked"]} and "p_bust_max" in sv[S] and "max_dd_pct" in sv[S]


def test_the_learning_packet_has_the_backtest_gap(world, cards):
    bulk(world, 250, SAT - HOUR, aid=f"{V45}@15m")
    seed_gap(world, SAT - 3 * HOUR)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("learning_review",), learning_review_hour_kst=11))
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [], "lessons": {}}
    runner = QueueRunner({"performance": [team_answer("p")], "learning": [team_answer("l")], "team_lead": [lead]})
    RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
            policy=pol, now_ms=SAT, clock_ms=lambda: SAT)
    bg = runner.calls[0]["packet"]["learning"]["backtest_gap"]
    assert bg["summary"]["strategies_worse"] == 1 and bg["worse"] == [S] and bg["better"] == [V45]
    assert "learning.backtest_gap" in runner.calls[1]["system"]


def test_the_weekly_report_has_one_drawdown_line(world, cards):
    sunday = kst(2026, 10, 11, 21, 5)
    seed_gap(world, sunday - 2 * DAY)
    curve(world, f"{S}@15m", [5000] * 18 + [5500, 4400, 5000], START)              # -20% in the last week
    curve(world, f"{S}@1h", [5000] * 21, START)
    curve(world, f"{V45}@1h", [5000] * 18 + [5100, 5000, 5200], START)
    curve(world, f"{V45}@15m", [5000] * 21, START)
    rep = DG.week_report(world.paper(), world.agents, sunday)
    deep = rep["survival"]["deepest"]
    assert [r["strategy"] for r in deep] == [S, V45]
    assert deep[0]["week_max_dd_pct"] == pytest.approx(1100 / 10500, abs=1e-3)
    assert rep["survival"]["backtest"] == {"tested": 2, "worse": 1}
    text = DG.compose_week(rep)
    line = [x for x in text.splitlines() if "가장 깊은 낙폭" in x]
    assert line == ["가장 깊은 낙폭: 켈트너·RSI -10%"] and "5년 시험보다 나쁜 매매법 1/2" in text
    assert DG.survival_line(rep["survival"]) == \
        "- 이번 주 가장 깊은 낙폭 켈트너·RSI -10% · V4.5 -1% / 5년 시험보다 유의하게 나쁜 매매법 1/2"
    assert len(text) <= 4000
    assert DG.survival_line(None) == "" and DG.survival_line({"deepest": [], "backtest": {"tested": 0}}) == ""


# ---------------------------------------------------------------- dashboard
def test_the_risk_room_schedule_names_the_friday_meeting():
    from paperbot.dash.app import _trigger_defaults, room_schedule_ko
    line = room_schedule_ko("team:risk")
    assert "금요일 11:00 낙폭·파산 위험 회의(자료가 쌓인 뒤부터). 자료가 많이 쌓인 주에는 한 번 더(주 2번까지)." in line
    assert "화요일 11:00 조합·동시 손실 회의" in line and line.endswith("그 밖에는 두 분 글에 답합니다.")
    assert "금요일" not in room_schedule_ko("team:risk", {"risk_review": -1}) and "화요일" in room_schedule_ko(
        "team:risk", {"risk_review": -1})
    assert room_schedule_ko("team:risk", {"risk_review": 10, "combo_review": -1}).startswith("금요일 10:00 낙폭·파산")
    assert room_schedule_ko("team:risk", {"risk_review": -1, "combo_review": -1}).startswith("정해진 회의는 없고")
    assert _trigger_defaults()["risk_review_hour_kst"] == 11


def test_the_profile_endpoint_carries_live_risk(world):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from paperbot.dash.app import create_app, hash_password
    import time as _t
    now = int(_t.time() * 1000)
    for k in range(25):
        world.trade(f"{S}@15m", 20.0 if k % 3 else -30.0, now - (k + 1) * HOUR)
    curve(world, f"{S}@15m", [5200, 4680, 5000], now - 4 * HOUR, step=HOUR)
    curve(world, f"{S}@1h", [5000, 5000, 5000], now - 4 * HOUR, step=HOUR)
    c = TestClient(create_app(world.paths["paper"], hash_password("pw"), b"x" * 32))
    assert c.post("/api/login", json={"password": "pw"}).status_code == 200
    p = c.get(f"/api/profile/{S}").json()
    lr = p["live_risk"]
    assert lr["max_dd_pct"] == pytest.approx(520 / 10200, abs=1e-3) and lr["p_bust_tf"] == "15m"
    assert 0 <= lr["p_bust"] <= 1 and lr["simulated"] == 1 and lr["min_trades"] == 20
    assert c.get("/api/profile/NOPE").status_code == 404


def test_the_strategy_tab_shows_max_drawdown_and_bust_probability():
    with open(os.path.join(STATIC, "strat.js"), encoding="utf-8") as fh:
        src = fh.read()
    assert "최대 낙폭" in src and "파산 확률" in src and "riskSpans(lr)" in src
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    fn = re.search(r"^function riskSpans\(.*?^}$", src, re.S | re.M).group(0)
    body = """const TF_KO = {"15m": "15분"};
console.log(JSON.stringify({a: riskSpans({max_dd_pct: 0.3125, max_dd_usd: 3125.4, max_dd_at: "10/03 14시", p_bust: 0.004,
  p_bust_tf: "15m", paths: 10000}), b: riskSpans({max_dd_pct: 0.1}), c: riskSpans(null), e: riskSpans({max_dd_pct: 0}),
  d: riskSpans({error: "x"})}));"""
    r = subprocess.run([node, "-e", fn + "\n" + body], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert "최대 낙폭 <b class=\"down\">-31%</b>" in got["a"] and "$3,125" in got["a"] and "바닥 10/03 14시" in got["a"]
    assert "파산 확률 <b class=\"\">0.4%</b>" in got["a"] and "15분" in got["a"] and "10,000번" in got["a"]
    assert "최대 낙폭 <b class=\"\">-10%</b>" in got["b"] and "파산 확률" not in got["b"]       # < 20 trades: none
    assert got["c"] == "" and got["d"] == "" and "최대 낙폭 <b class=\"\">0%</b>" in got["e"]
