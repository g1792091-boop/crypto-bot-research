"""Risk-reward (손익비) numbers (agents/riskreward.py, owners' request 2026-10-04) on a small synthetic paper3.db and
daily3.db, the Thursday 손익비·청산 회의 (team:review, trigger rr_review), the compact numbers in the strategy
specialist's and the ranking review's packets, the dashboard's schedule line and the strategy tab's 본전 승률."""

import json
import os
import re
import shutil
import subprocess

import pytest

from paperbot.agents import riskreward as RR
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.agents import triggers as TR
from paperbot.ladder import roe_price
from paperbot.models import TradeRecord

from test_new_meetings import bulk, due, tpol, world_run
from test_rooms import (DAY, HOUR, MIN, NOTE, QUIET, S, SPEC, QueueRunner, World, analysis, challenge, kst,
                        team_answer)

V45 = "V45_AMB"
RT = 2 * (0.0005 + 0.0002)               # the World's taker fee + the v3 slippage, both sides
WED = kst(2026, 10, 7, 11, 5)
THU = kst(2026, 10, 8, 11, 5)            # Thursday 11:05 KST
FRI = kst(2026, 10, 9, 11, 5)
SAT = kst(2026, 10, 10, 11, 5)
STATIC = os.path.join(os.path.dirname(__file__), "..", "paperbot", "dash", "static")


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def trade(world, aid, roe, lev, reason, best, t, side=1, symbol="BTCUSDT", margin=50.0, mae=99.0, stop=None):
    """One closed trade with the given ROE, leverage, exit reason, best net ROE during it (mfe_price), worst price
    (mae_price) and initial stop (stop_initial)."""
    strat, tf = aid.split("@")
    mfe = roe_price(side, 100.0, lev, best, RT) if best is not None else 100.0
    world.store.trade(aid, TradeRecord(
        strategy_id=strat, symbol=symbol, timeframe=tf, side=side, signal_ts=t - 3 * HOUR - 1, entry_time=t - 3 * HOUR,
        entry_price=100.0, exit_time=t, exit_price=100.0, exit_reason=reason, qty=1.0, leverage=lev, tier="best",
        margin=margin, stop_price=99.0, tp_price=0.0, liq_price=95.0, fees=0.1, funding=0.0, pnl=roe * margin,
        roe=roe, price_move=0.0, mae_price=mae, mfe_price=mfe, equity_after=1000.0, score=0.0, context={},
        stop_initial=stop))


def seed(world, t=QUIET - DAY, v45=True):
    """N17 (S): 15m at 50x (40% margin): wins +10% +10% +20% (LOCK), losses -40% (SL, best +6%) and -100% (LIQ);
    1h at 20x (20%): win +30% (LOCK), loss -20% (SL, best +13%: past the first lock's trigger).
    Winners' worst prices: 15m 0.5%, 1%, 1.5% against with the stop 2% away, 1h 0.2% with the stop 1% away.
    V45 1h at 30x (30%): 6 wins +10%, 4 losses -20% (10 trades: not small; no initial stop recorded).
    A coin flip: one -50% loss."""
    for k, (roe, reason, best, mae) in enumerate(((0.10, "LOCK", 0.15, 99.5), (0.10, "LOCK", 0.12, 99.0),
                                                  (0.20, "LOCK", 0.25, 98.5), (-0.40, "SL", 0.06, 98.0),
                                                  (-1.0, "LIQ", None, 97.0))):
        trade(world, f"{S}@15m", roe, 50, reason, best, t - k * HOUR, mae=mae, stop=98.0)
    trade(world, f"{S}@1h", 0.30, 20, "LOCK", 0.33, t - 6 * HOUR, mae=99.8, stop=99.0)
    trade(world, f"{S}@1h", -0.20, 20, "SL", 0.13, t - 7 * HOUR, stop=99.0)
    if not v45:
        world.store.commit()
        return
    for k in range(10):
        trade(world, f"{V45}@1h", 0.10 if k < 6 else -0.20, 30, "LOCK" if k < 6 else "SL", 0.12 if k < 6 else 0.0,
              t - (8 + k) * HOUR)
    trade(world, "RANDOM_1@15m", -0.50, 40, "SL", 0.0, t - 20 * HOUR)
    world.store.commit()


# ---------------------------------------------------------------- the numbers
def test_equity_terms_by_leverage_tier():
    assert RR.pnl_equity(0.10, 50) == pytest.approx(0.04) and RR.pnl_equity(0.10, 40) == pytest.approx(0.04)
    assert RR.pnl_equity(0.10, 30) == pytest.approx(0.03) and RR.pnl_equity(0.10, 20) == pytest.approx(0.02)
    assert RR.pnl_equity(0.10, 10) == pytest.approx(0.02) and RR.pnl_equity(0.10, 25) is None
    from paperbot.obsshadows import MARGIN_FRAC
    assert RR.MARGIN_FRAC == MARGIN_FRAC                      # the same shares as the nightly shadows (section 4)


def test_payoff_breakeven_gap_exit_mix_giveback_and_buckets(world):
    seed(world)
    tab = RR.table(RR.closed(world.paper(), 0, QUIET), first_trigger=0.12)
    s = tab["strategies"][S]["all"]
    assert (s["trades"], s["wins"], s["losses"], s["win_rate"]) == (7, 4, 3, pytest.approx(4 / 7, abs=1e-4))
    # ROE: wins .10 .10 .20 .30 -> .175; losses -.40 -1.0 -.20 -> -.5333
    r = s["roe"]
    assert r["avg_win"] == pytest.approx(0.175) and r["avg_loss"] == pytest.approx(-0.5333, abs=1e-4)
    assert r["payoff"] == pytest.approx(0.175 / 0.53333, abs=1e-3)
    assert r["breakeven_win_rate"] == pytest.approx(0.53333 / 0.70833, abs=1e-4)
    # equity: wins .04 .04 .08 .06 -> .055; losses -.16 -.40 -.04 -> -.2
    e = s["equity"]
    assert e["avg_win"] == pytest.approx(0.055) and e["avg_loss"] == pytest.approx(-0.2)
    assert e["payoff"] == pytest.approx(0.275) and e["breakeven_win_rate"] == pytest.approx(0.2 / 0.255, abs=1e-4)
    assert e["gap_pp"] == pytest.approx((4 / 7 - 0.2 / 0.255) * 100, abs=0.06)
    assert e["expectancy"] == pytest.approx((0.22 - 0.60) / 7, abs=1e-4)
    assert (e["gap_pp"] < 0) == (e["expectancy"] < 0)         # same trades: gap and expectancy agree in sign
    assert s["exits"] == {"LOCK": 4, "SL": 2, "LIQ": 1, "other": 0}
    assert s["exit_share"]["LOCK"] == pytest.approx(4 / 7, abs=1e-3)
    g = s["giveback"]                                          # best .15 .12 .25 .33 vs realised .10 .10 .20 .30
    assert g["winners"] == 4 and g["mean_best_roe"] == pytest.approx(0.2125, abs=1e-4)
    assert g["mean_giveback_roe"] == pytest.approx(0.0375, abs=1e-4) and g["kept_share"] == pytest.approx(0.7 / 0.85, abs=1e-3)
    assert s["losers_reached_first_lock"]["n"] == 1 and s["losers_were_up_5pct"]["n"] == 2
    assert s["buckets"]["wins"] == {"0~5%": 0, "5~10%": 0, "10~15%": 2, "15~20%": 0, "20~30%": 1, "30~50%": 1, "50%+": 0}
    assert s["buckets"]["losses"]["-30~-50%"] == 1 and s["buckets"]["losses"]["-80% 이하"] == 1
    assert s["buckets"]["losses"]["-20~-30%"] == 1 and sum(s["buckets"]["losses"].values()) == 3
    # winners' adverse excursion: of the stop distance .25 .5 .75 (15m) and .2 (1h); of the entry .005 .01 .015 .002
    m = s["winners_mae"]
    assert m["winners"] == 4 and m["with_stop"] == 4 and m["median_pct"] == pytest.approx(0.0075)
    assert m["median_of_stop"] == pytest.approx(0.375) and m["p80_of_stop"] == pytest.approx(0.6)
    assert m["p90_of_stop"] == pytest.approx(0.675) and m["small"] is True
    assert m["within_of_stop"] == {"25%": 0.5, "50%": 0.75, "75%": 1.0}
    assert tab["strategies"][S]["by_tf"]["1h"]["winners_mae"]["median_of_stop"] == pytest.approx(0.2)
    # V45 recorded no initial stop: the excursion in % only
    vm = tab["strategies"][V45]["all"]["winners_mae"]
    assert vm["winners"] == 6 and vm["with_stop"] == 0 and vm["median_pct"] == pytest.approx(0.01)
    assert vm["within_of_stop"]["50%"] is None and vm["small"] is True                   # 6 winners
    # the losers' best ROE before they closed: .06, .13 and the liquidation's (entry price: minus the costs)
    lm = s["losers_mfe"]
    assert lm["losers"] == 3 and lm["median_best_roe"] == pytest.approx(0.06, abs=1e-4)
    # small samples: N17 (7 trades) and its timeframes are small, V45's 10 trades are not
    assert s["small"] is True and tab["strategies"][S]["by_tf"]["15m"]["small"] is True
    v = tab["strategies"][V45]["all"]
    assert "small" not in v and v["equity"]["payoff"] == pytest.approx(0.5)
    assert v["equity"]["breakeven_win_rate"] == pytest.approx(2 / 3, abs=1e-4) and v["equity"]["gap_pp"] == pytest.approx(-6.7)
    assert list(tab["strategies"][S]["by_tf"]) == ["15m", "1h"]
    assert tab["all"]["trades"] == 17                           # the coin flip is not a strategy account
    assert RR.stats([]) == {"trades": 0, "small": True}


def test_a_cell_without_losses_or_wins_has_no_breakeven():
    wins = [{"win": True, "roe": 0.1, "eq": 0.04, "exit": "LOCK", "mfe_roe": 0.12, "exit_time": 0}]
    s = RR.stats(wins)
    assert s["equity"]["payoff"] is None and s["equity"]["breakeven_win_rate"] is None and s["equity"]["gap_pp"] is None
    assert s["losers_reached_first_lock"]["share"] is None and s["small"] is True


def _shadow(world, kind, aid, bc, day, roe, eq, resolved=1, reason="LOCK", actual=None):
    world.daily.execute("INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (f"{kind}|{aid}|BTCUSDT|{bc}", day, kind, aid, "BTCUSDT", aid.split("@")[1], 1, None, roe,
                         None if roe is None else reason, resolved,
                         json.dumps({"pnl_equity": eq, "actual_pnl_equity": actual})))


def test_shadow_summary_per_strategy_against_the_base(world):
    a = f"{S}@15m"
    _shadow(world, "base", a, 1, "2026-10-06", 0.05, 0.02, actual=0.02)
    _shadow(world, "base", a, 2, "2026-10-06", -0.20, -0.08, reason="SL", actual=-0.08)
    _shadow(world, "lock15", a, 1, "2026-10-06", 0.075, 0.03)
    _shadow(world, "lock15", a, 2, "2026-10-06", -0.20, -0.08, reason="SL")
    _shadow(world, "lev10", a, 1, "2026-10-06", None, None)                   # sizing refused: not entered
    _shadow(world, "lev10", a, 2, "2026-10-06", -0.10, -0.02, reason="SL")
    _shadow(world, "timestop", a, 1, "2026-10-06", None, None, resolved=0)    # not finished yet
    _shadow(world, "lev20", a, 1, "2026-10-06", 0.05, 0.01)                    # lower leverage: positive on average
    _shadow(world, "lev20", a, 2, "2026-10-06", -0.025, -0.005, reason="SL")
    _shadow(world, "base", a, 3, "2026-09-25", 0.05, 0.02)                    # outside the last 7 days
    _shadow(world, "lock15", a, 3, "2026-09-25", -0.05, -0.02, reason="SL")
    _shadow(world, "base", "RANDOM_1@15m", 4, "2026-10-06", 0.05, 0.02)      # a coin flip: not a strategy
    _shadow(world, "stop1.5", a, 2, "2026-10-06", -0.10, None)               # the loss cards' stop shadows: not here
    world.daily.commit()
    now = kst(2026, 10, 8, 11, 0)
    sh = RR.shadow_summary(world.daily, world.paper(), now - 7 * DAY, now)
    assert sh["label"] == "설명용, 판정 아님" and list(sh["strategies"]) == [S]
    c = sh["strategies"][S]
    assert c["base"]["trades"] == 2 and c["base"]["mean_eq"] == pytest.approx(-0.03)
    l15 = c["lock15"]
    assert l15["trades"] == 2 and l15["mean_eq"] == pytest.approx(-0.025) and l15["vs_base_eq"] == pytest.approx(0.005)
    assert (l15["better_share"], l15["worse_share"], l15["small"]) == (0.5, 0.0, True)
    assert c["lev10"]["trades"] == 1 and c["lev10"]["not_entered"] == 1 and c["lev10"]["better_share"] == 1.0
    assert c["timestop"] == {"trades": 0, "open": 1}
    assert c["lock20"] == {"trades": 0}
    assert c["lev20"]["mean_eq"] == pytest.approx(0.0025) and c["lev20"]["base_mean_eq"] == pytest.approx(-0.03)
    turns = RR.leverage_turns(sh["strategies"])
    assert [x["strategy"] for x in turns["lev20"]["turns_positive"]] == [S] and turns["lev20"]["still_negative"] == []
    assert turns["lev10"] == {"turns_positive": [], "still_negative": [S]}           # -0.02 on its one trade
    brief = RR.shadow_brief(c)
    assert set(brief["lev20"]) >= {"mean_eq", "base_mean_eq", "vs_base_eq"} and "mean_eq" not in brief["lock15"]
    whole = RR.shadow_summary(world.daily, world.paper(), 0, now)
    assert whole["strategies"][S]["lock15"]["trades"] == 3 and whole["all"]["lock15"]["worse_share"] == pytest.approx(1 / 3, abs=1e-3)
    assert "error" in RR.shadow_summary(None, world.paper(), 0, now)


def test_meeting_packet_strategy_brief_and_ranking_brief(world):
    seed(world)
    now = QUIET
    pk = RR.rr_packet(world.paper(), world.daily, now)
    assert pk["trades"] == {"7d": 17, "since_start": 17} and pk["rules"]["first_trigger"] == pytest.approx(0.12)
    assert pk["lab_tests"]["lock_start"]["first_lock"] == (0.15, 0.20, 0.30) and "30일" in pk["rules"]["note"]
    assert pk["coin_flips"]["since_start"]["trades"] == 1 and pk["coin_flips"]["since_start"]["exits"]["SL"] == 1
    assert [x["strategy"] for x in pk["strategies"]] == [V45, S]                     # most trades first
    n17 = pk["strategies"][1]
    assert n17["since_start"]["payoff"] == pytest.approx(0.275) and n17["since_start"]["losers_reached_first_lock"] == 1
    assert n17["by_tf"]["15m"]["liq"] == 1 and n17["by_tf"]["15m"]["small"] is True
    assert n17["by_tf_7d"] == {} and "exit_share" not in n17["since_start"]          # small 7-day cells left out
    assert pk["strategies"][0]["by_tf_7d"]["1h"] == {"trades": 10, "gap_pp": pytest.approx(-6.7)}
    assert "liq" not in pk["strategies"][0]["by_tf"]["1h"]
    assert pk["shadows"]["label"] == "설명용, 판정 아님" and "본전" in pk["how_to_read"]
    assert len(json.dumps(pk, ensure_ascii=False)) < 12_000
    b = RR.strategy_brief(world.paper(), S, now)
    assert b["since_start"]["trades"] == 7 and b["7d"]["trades"] == 7 and set(b["by_tf"]) == {"15m", "1h"}
    assert b["since_start"]["breakeven_win_rate"] == pytest.approx(0.7843, abs=1e-4)
    assert RR.strategy_brief(world.paper(), S, now + 30 * DAY)["7d"] == {"trades": 0, "small": True}
    m = RR.brief_many(world.paper(), [S, V45, "NOPE"], now)
    assert m["strategies"][V45]["gap_pp"] == pytest.approx(-6.7) and m["strategies"]["NOPE"]["trades"] == 0
    assert m["coin_flips"]["trades"] == 1 and set(m["strategies"][S]["exit_share"]) == {"LOCK", "SL", "LIQ", "other"}


# ---------------------------------------------------------------- the Thursday meeting: trigger
def test_rr_review_is_off_by_default_and_on_with_the_server_policy():
    assert TR.TriggerPolicy().rr_review_hour_kst == -1
    assert TR.ANALYSES["rr_review"] == (3, "team:review") and TR.ANALYSIS_KO["rr_review"] == "손익비·청산 회의"
    assert TR.TRIGGER_CLASS["rr_review"] == "weekly" and TR.PRIORITY["rr_review"] == 4
    assert "rr_review" in RM.RoomsPolicy().paced_triggers and RM.TRIGGER_KO["rr_review"] == "손익비·청산 회의"
    p = RM.policy_from_env({})
    assert p.triggers.rr_review_hour_kst == 11
    assert RM.policy_from_env({"AGENTS_RR_REVIEW_HOUR": "off"}).triggers.rr_review_hour_kst == -1
    assert RM.policy_from_env({"AGENTS_RR_REVIEW_HOUR": "10"}).triggers.rr_review_hour_kst == 10
    with pytest.raises(ValueError):
        RM.policy_from_env({"AGENTS_RR_REVIEW_HOUR": "25"})
    h = RM.schedule_hours(p)
    assert h["rr_review"] == 11 and h["analysis_weekdays"]["rr_review"] == 3
    assert RM.schedule_hours(RM.RoomsPolicy())["rr_review"] == -1
    assert RM._PROBE["rr_review"] == "team:review" and RM.MEETING_FILE["rr_review"] == "rooms_meeting_rr.md"
    assert "rr" in RM.CODE_ROOTS and "rr_review" in RM.LEAD_HYPOTHESIS_MEETINGS


def test_rr_review_meets_on_thursday_only_with_enough_data(world):
    bulk(world, 120, THU - HOUR)
    pol = tpol(enabled=("rr_review",), rr_review_hour_kst=11)
    assert due(world, THU, TR.TriggerPolicy(enabled=("rr_review",))) == []            # off in TriggerPolicy()
    assert due(world, THU, pol) == []                                                 # 120 < 200 in the week
    st = TR.skipped_status(world.paper(), THU, pol)["rr_review"]
    assert st["ok"] is False and "최소 200건" in st["why"] and st["slot"] == "2026-10-08"
    bulk(world, 100, THU - 2 * HOUR, aid=f"{V45}@1h")
    assert [d for d in due(world, WED, pol)] == []                                    # Wednesday: not its day
    assert due(world, THU - 10 * MIN, pol) == []                                      # 10:55: not yet
    [d] = due(world, THU, pol)
    assert (d.room_id, d.trigger, d.data["key"], d.data["class"]) == ("team:review", "rr_review",
                                                                      "rr_review:2026-10-08", "weekly")
    assert "손익비·청산 회의 (11:00)" in d.data["summary_ko"] and d.data["trades"] == 220
    world_run(world, d, THU)
    assert due(world, THU + HOUR, pol) == [] and due(world, FRI, pol) == []           # once a week


def test_rr_review_extra_run_with_twice_the_data_two_days_later_at_most_twice_a_week(world):
    bulk(world, 250, THU - HOUR)
    pol = tpol(enabled=("rr_review",), rr_review_hour_kst=11)
    [d] = due(world, THU, pol)
    world_run(world, d, THU)
    bulk(world, 400, FRI - HOUR, step=MIN)                                           # 2 x 200 by Friday ...
    assert due(world, FRI, pol) == []                                                # ... but one day after Thursday
    assert "뒤 1일(최소 2일)" in TR.skipped_status(world.paper(), FRI, pol, world.agents)["rr_review"]["extra"]["why"]
    [x] = due(world, SAT, pol)
    assert x.data["key"] == "rr_review:extra:2026-10-10" and x.data["extra_run"] is True
    world_run(world, x, SAT)
    bulk(world, 800, SAT + DAY - HOUR, step=MIN)
    assert due(world, SAT + DAY, pol) == []                                          # never a third in the week
    assert [y.data["key"] for y in due(world, THU + 7 * DAY, pol)] == ["rr_review:2026-10-15"]


# ---------------------------------------------------------------- the Thursday meeting: end to end
def test_rr_review_meeting_speakers_packet_and_hypotheses(world):
    bulk(world, 250, THU - HOUR)
    seed(world, THU - 30 * MIN)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("rr_review",), rr_review_hour_kst=11))
    pred = {"metric": "win_rate", "timeframe": None, "direction": "below", "value": 0.7, "after_trades": 50}
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [],
            "hypotheses": [{"strategy": S, "text": "본전 승률이 실제 승률보다 높음", "how_to_confirm": "50건",
                            "prediction": pred}]}
    runner = QueueRunner({"exit_timing": [team_answer("x", "rr.all_strategies.since_start.exits.LOCK")],
                          "whatif": [team_answer("w")], "pnl_reviewer": [team_answer("p")], "team_lead": [lead]})
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
                  policy=pol, now_ms=THU, clock_ms=lambda: THU)
    assert [(r["room_id"], r["trigger"], r["status"], r["class"]) for r in out["rounds"]] == [
        ("team:review", "rr_review", "done", "weekly")]
    assert runner.roles() == ["exit_timing", "whatif", "pnl_reviewer", "team_lead"]
    assert out["rounds"][0]["calls"] == 4
    pk = runner.calls[0]["packet"]
    assert pk["rr"]["trades"]["7d"] == 267 and pk["rr"]["shadows"]["label"] == "설명용, 판정 아님"
    assert "board" in pk and "exits" in pk["board"]
    sysp = runner.calls[0]["system"]
    assert "손익비·청산 회의" in sysp and "30일" in sysp and "lock_start" in sysp and "stop_atr" in sysp
    assert "hypotheses" in runner.calls[3]["system"]
    said = [m for m in R.room_messages(world.agents, "team:review", limit=50) if m["role"] == "exit_timing"]
    assert said and "[사실]" in said[0]["text"]                                     # rr.* is code-computed
    rows = R.trial_history(world.agents, kinds=("hypothesis",), limit=5)
    assert rows[0]["strategy"] == S and rows[0]["room_id"] == "team:review"
    d = TR.Due("team:review", "rr_review", 0, {}, "rr_review")
    assert RM.round_min_calls(d, pol) == RM.round_max_calls(d, pol) == 4 <= pol.max_calls_team_round
    assert [r for r, _t in RM.team_plan(d)] == ["exit_timing", "whatif", "pnl_reviewer", "team_lead"]


def test_a_specialist_sees_its_own_risk_reward_only(world):
    seed(world, QUIET - 2 * DAY, v45=False)
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE)], "devils_advocate": [challenge("agree")]})
    world.tick(runner, QUIET, policy=RM.RoomsPolicy(triggers=tpol(enabled=("loss_cluster",))))
    rr = runner.calls[0]["packet"]["specialist"]["risk_reward"]
    assert rr["since_start"]["trades"] == 10 and set(rr["by_tf"]) == {"15m", "1h"}       # 7 seeded + 3 losses
    assert "본전" in rr["note"] and V45 not in json.dumps(rr) and "win_mae_p80_of_stop" in rr["by_tf"]["15m"]


def test_the_ranking_review_has_risk_reward_for_the_picked_strategies(world):
    seed(world)
    t = kst(2026, 10, 7, 14, 5)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("ranking",), ranking_hour_kst=14))
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}
    runner = QueueRunner({"performance": [team_answer("f")], "pnl_reviewer": [team_answer("p")],
                          "risk_officer": [team_answer("r")], "team_lead": [lead]})
    world.tick(runner, t, policy=pol)
    pk = runner.calls[0]["packet"]["ranking"]
    rr = pk["risk_reward"]
    picked = [r["strategy"] for r in pk["picked"]]
    assert set(rr["strategies"]) == set(picked) and rr["strategies"][V45]["payoff"] == pytest.approx(0.5)
    assert rr["coin_flips"]["trades"] == 1


# ---------------------------------------------------------------- dashboard
def test_the_review_room_schedule_names_the_thursday_meeting():
    from paperbot.dash.app import _trigger_defaults, room_schedule_ko
    line = room_schedule_ko("team:review")
    assert "목요일 11:00 손익비·청산 회의(자료가 쌓인 뒤부터)." in line and "수요일 11:00 코인·장세 회의" in line
    assert "목요일" not in room_schedule_ko("team:review", {"rr_review": -1})
    assert "목요일 10:00 손익비·청산 회의" in room_schedule_ko("team:review", {"rr_review": 10})
    assert _trigger_defaults()["rr_review_hour_kst"] == 11


def test_the_strategy_tab_shows_the_breakeven_win_rate():
    with open(os.path.join(STATIC, "strat.js"), encoding="utf-8") as fh:
        src = fh.read()
    assert "본전 승률" in src
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    fn = re.search(r"^function liveRec\(.*?^}$", src, re.S | re.M).group(0)
    body = """console.log(JSON.stringify({a: liveRec([{trades: 7, wins: 4, losses: 3, pnl: -19, gross_win: 110, gross_loss: -150},
  {trades: 3, wins: 2, losses: 1, pnl: 30, gross_win: 50, gross_loss: -20}]), b: liveRec([{trades: 2, wins: 2, losses: 0,
  gross_win: 10, gross_loss: 0}]), c: liveRec([])}));"""
    r = subprocess.run([node, "-e", fn + "\n" + body], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    # avg win 160/6, avg loss -170/4: breakeven = 42.5 / (26.67 + 42.5)
    assert got["a"]["ratio"] == pytest.approx((160 / 6) / 42.5) and got["a"]["be"] == pytest.approx(42.5 / (160 / 6 + 42.5))
    assert got["b"]["be"] is None and got["c"]["be"] is None
