"""The meetings added on 2026-10-04 (owners' choice): the four weekly analyses (Monday costs, Tuesday combinations,
Wednesday coins and regimes, Saturday learning), the review of a US release the day after it, the market team's
daily bull vs bear debate (agents/committee.py: the call recorded and graded by code, never traded), the timeframe
comparer and the performance analyst in the existing meetings, and the security line of the weekly report."""

import json
import os
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest

from paperbot import events as EV
from paperbot.agents import committee as CM
from paperbot.agents import digest as DG
from paperbot.agents import meetings as M
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.agents import triggers as TR

from test_rooms import DAY, HOUR, MIN, S, QueueRunner, World, kst, rec, team_answer  # noqa: F401

V45 = "V45_AMB"
MON = kst(2026, 10, 5, 11, 5)            # Monday 11:05 KST
TUE = kst(2026, 10, 6, 11, 5)
WED = kst(2026, 10, 7, 11, 5)
SAT = kst(2026, 10, 10, 11, 5)
NOON = kst(2026, 10, 7, 12, 5)           # Wednesday 12:05 KST


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def bulk(world, n, t_end, aid=f"{S}@15m", pnl=1.0, step=20 * MIN, **kw):
    """``n`` closed trades of ``aid`` ending before ``t_end`` (one commit)."""
    strat, tf = aid.split("@")
    for k in range(n):
        world.store.trade(aid, rec(strat, tf, pnl, t_end - (k + 1) * step, **kw))
    world.store.commit()


def tpol(**kw):
    return TR.TriggerPolicy(enabled=tuple(kw.pop("enabled", TR.TRIGGERS)), **kw)


def due(world, now, pol):
    return TR.find_due(world.paper(), None, world.agents, None, now, pol)


def fake_get(price=lambda sym, t: 100.0, calls=None):
    """Binance public data stand-in: 5m / 1h klines from ``price(symbol, t)``, premiumIndex."""
    def get(url):
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if calls is not None:
            calls.append(url)
        sym = q["symbol"]
        if u.path.endswith("premiumIndex"):
            return {"lastFundingRate": "0.0001", "markPrice": str(price(sym, 0)), "nextFundingTime": 0}
        step = {"5m": 5 * MIN, "1h": HOUR}[q["interval"]]
        limit = int(q.get("limit", 500))
        if "endTime" in q:
            last = int(q["endTime"]) // step * step
            opens = [last - i * step for i in range(limit)][::-1]
            if "startTime" in q:
                opens = [o for o in opens if o >= int(q["startTime"])]
        else:
            first = int(q["startTime"]) // step * step
            opens = [first + i * step for i in range(limit)]
        out = []
        for o in opens:
            c = price(sym, o + step)
            out.append([o, c, c * 1.001, c * 0.999, c, 10.0, o + step - 1])
        return out
    return get


# ---------------------------------------------------------------- the four weekly analyses: triggers
def test_weekly_analyses_are_off_by_default_and_on_with_the_server_policy():
    t = TR.TriggerPolicy()
    assert (t.cost_review_hour_kst, t.combo_review_hour_kst, t.coin_review_hour_kst, t.learning_review_hour_kst,
            t.event_review_hour_kst, t.bull_bear_hour_kst) == (-1,) * 6
    p = RM.policy_from_env({})
    assert (p.triggers.cost_review_hour_kst, p.triggers.learning_review_hour_kst) == (11, 11)
    assert p.triggers.event_review_hour_kst == 11 and p.triggers.bull_bear_hour_kst == 12
    off = RM.policy_from_env({"AGENTS_COMBO_REVIEW_HOUR": "off", "AGENTS_BULL_BEAR_HOUR": "13",
                              "AGENTS_ANALYSIS_MIN_TRADES": "50"})
    assert off.triggers.combo_review_hour_kst == -1 and off.triggers.bull_bear_hour_kst == 13
    assert off.triggers.analysis_min_trades == 50 and off.triggers.cost_review_hour_kst == 11
    for bad in ({"AGENTS_EVENT_REVIEW_HOUR": "24"}, {"AGENTS_COIN_REVIEW_HOUR": "noon"},
                {"AGENTS_ANALYSIS_MIN_TRADES": "0"}):
        with pytest.raises(ValueError):
            RM.policy_from_env(bad)
    # the classes: the analyses and the event review wait like weekly reviews (paced), the debate is scheduled
    assert {TR.TRIGGER_CLASS[k] for k in TR.ANALYSES} == {"weekly"} and TR.TRIGGER_CLASS["event_review"] == "weekly"
    assert TR.TRIGGER_CLASS["bull_bear"] == "scheduled" and "scheduled" in RM.RESERVED_CLASSES
    assert set(TR.ANALYSES) | {"event_review"} <= set(RM.RoomsPolicy().paced_triggers)
    assert "bull_bear" not in RM.RoomsPolicy().paced_triggers
    hours = RM.schedule_hours(p)
    assert hours["cost_review"] == 11 and hours["bull_bear"] == 12 and hours["analysis_weekdays"]["learning_review"] == 5
    assert RM.schedule_hours(RM.RoomsPolicy())["event_review"] == -1


def test_each_analysis_meets_on_its_weekday_from_its_hour_once_a_week(world):
    bulk(world, 250, MON - HOUR)
    pol = tpol(enabled=TR.ANALYSES, **{f"{k}_hour_kst": 11 for k in TR.ANALYSES})
    assert due(world, MON, TR.TriggerPolicy(enabled=tuple(TR.ANALYSES))) == []        # off in TriggerPolicy()
    assert due(world, MON - 10 * MIN, pol) == []                                      # 10:55: not yet
    [d] = due(world, MON, pol)
    assert (d.room_id, d.trigger, d.priority, d.data["class"]) == ("team:ops", "cost_review", 4, "weekly")
    assert d.data["trades"] == 250 and "비용·체결 회의 (11:00)" in d.data["summary_ko"]
    world_run(world, d, MON)
    assert due(world, MON + HOUR, pol) == []                                          # once a week
    [d2] = due(world, TUE, pol)                                                       # Tuesday: the combination one
    assert (d2.room_id, d2.trigger) == ("team:risk", "combo_review")
    assert [x.trigger for x in due(world, WED, pol)] == ["combo_review", "coin_review"]   # Tuesday's still waits
    assert [x for x in due(world, SAT, pol) if x.trigger == "learning_review"] == []   # 141 trades in its week
    bulk(world, 100, SAT - HOUR, aid=f"{V45}@1h")
    assert [x.room_id for x in due(world, SAT, pol) if x.trigger == "learning_review"] == ["team:lead"]
    # the next Monday: a new week (the data are the 7 days before that slot: none now)
    bulk(world, 250, MON + 7 * DAY - HOUR, aid=f"{V45}@1h")
    assert [x.trigger for x in due(world, MON + 7 * DAY, pol) if x.trigger == "cost_review"] == ["cost_review"]


def world_run(world, d, now, status="done"):
    rid = TR.begin_round(world.agents, d, now)
    TR.finish_round(world.agents, rid, status, now + 5 * MIN, decision={"action": "team_meeting"}, calls=3)
    return rid


def test_an_analysis_waits_for_enough_data_and_says_why(world, tmp_path):
    bulk(world, 120, MON - HOUR)                                                      # under 200 in the week
    pol = tpol(enabled=("cost_review",), cost_review_hour_kst=11)
    assert due(world, MON, pol) == []
    st = TR.skipped_status(world.paper(), MON, pol)["cost_review"]
    assert st["ok"] is False and st["trades"] == 120 and "최소 200건" in st["why"] and st["slot"] == "2026-10-05"
    # the tick keeps why (code only, no AI call)
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"],
                  QueueRunner({}), policy=RM.RoomsPolicy(triggers=pol), now_ms=MON, clock_ms=lambda: MON)
    assert out["rounds"] == []
    assert R.get_cursor(world.agents, TR.SKIPPED_CURSOR)["cost_review"]["trades"] == 120
    # a run that started 3 days before the slot is too young, whatever the trades
    os.makedirs(tmp_path / "young")
    young = World(tmp_path / "young", start=MON - 3 * DAY)
    bulk(young, 300, MON - HOUR)
    assert due(young, MON, pol) == []
    assert "실험 시작 뒤 3.0일" in TR.skipped_status(young.paper(), MON, pol)["cost_review"]["why"]


def test_an_analysis_stopped_by_the_budget_is_due_again_later_in_the_week(world):
    bulk(world, 250, MON - HOUR)
    pol = tpol(enabled=("cost_review",), cost_review_hour_kst=11)
    [d] = due(world, MON, pol)
    rid = TR.begin_round(world.agents, d, MON)
    TR.finish_round(world.agents, rid, "stopped_budget", MON + MIN, decision={"stopped": "budget_class"})
    assert due(world, MON + HOUR, pol) == []                                          # its class waits for tomorrow
    [again] = due(world, TUE, pol)                                                    # Tuesday: the same slot
    assert again.data["key"] == d.data["key"] and "(2026-10-05 회의를 미뤘던 것)" in again.data["summary_ko"]


# ---------------------------------------------------------------- the analysis packets (code numbers)
def test_cost_packet_numbers(world):
    bulk(world, 10, MON - HOUR, pnl=0.05)                                              # wins: up before and after costs
    bulk(world, 10, MON - HOUR, aid=f"{V45}@1h", pnl=-0.05)                            # down after costs only
    pk = M.cost_packet(world.paper(), MON)
    assert pk["trades"] == 20 and pk["assumed_slippage"] == pytest.approx(0.0002)
    h1 = pk["by_timeframe"]["1h"]
    # each loss: fees 0.1, funding 0, slippage 0.0002 x (100 + 99) = 0.0398 -> gross -0.05 + 0.1398 = +0.0898
    assert h1["fees"] == pytest.approx(1.0) and h1["slippage_est"] == pytest.approx(0.4)        # $, 2 decimals
    assert h1["gross_before_costs"] == pytest.approx(0.9) and h1["pnl"] == pytest.approx(-0.5)
    assert h1["flipped_by_costs"] == 1 and h1["up_before_costs"] == 1 and h1["up_after_costs"] == 0
    assert h1["cost_vs_gross"] == pytest.approx(1.398 / 0.898, abs=1e-3)
    assert pk["flipped_by_costs"]["accounts"] == 1 and pk["flipped_by_costs"]["list"][0]["account"] == f"{V45}@1h"
    m15 = pk["by_timeframe"]["15m"]
    assert m15["flipped_by_costs"] == 0 and m15["up_after_costs"] == 1
    assert {r["strategy"]: r["flipped_timeframes"] for r in pk["by_strategy"]} == {S: [], V45: ["1h"]}


def test_combo_packet_correlation_losses_together_and_consensus(world):
    for day in range(10):                                                          # ten days, the same pattern
        t = TUE - (day + 1) * DAY
        p = 5.0 if day % 2 else -5.0
        world.store.trade(f"{S}@15m", rec(S, "15m", p, t))
        world.store.trade(f"{V45}@1h", rec(V45, "1h", 2 * p, t + 10 * MIN))
    world.store.commit()
    pk = M.combo_packet(world.paper(), TUE, min_losers=2)
    c = pk["correlation"]
    assert c["strategies"] == 2 and c["top_pairs"][0]["r"] == pytest.approx(1.0)
    assert c["days"] == 10 and "small" not in c and len(c["clusters"]) == 1 and len(c["clusters"][0]) == 2
    lt = pk["losses_together"]
    assert lt["hours_found"] >= 1 and lt["hours"][0]["losing_strategies"] == 2
    cons = pk["consensus"]["by_strategies_agreeing"]
    # both strategies entered BTC long within 10 minutes: every trade of the last week is in the '2' group
    assert cons["2"]["trades"] > 0 and cons["1"]["trades"] == 0
    assert pk["coin_flips"] == {"trades": 0}


def test_coin_packet_marks_small_cells_and_best_coin(world):
    bulk(world, 12, WED - HOUR, pnl=4.0, context={"regime": "trend_up"})                  # BTC wins
    bulk(world, 3, WED - HOUR, pnl=-6.0, symbol="ETHUSDT", context={"regime": "box"}, step=7 * MIN)
    pk = M.coin_packet(world.paper(), WED)
    row = next(r for r in pk["strategies"] if r["strategy"] == S)
    assert row["coins"]["BTC"] == {"n": 12, "win_rate": 1.0, "mean_roe": pytest.approx(0.08), "pnl": 48.0}
    assert row["coins"]["ETH"]["small"] is True and row["coins"]["ETH"]["pnl"] == -18.0
    assert row["best_coin"] == "BTC" and row["best_worst_small"] is False
    assert row["regimes"]["상승 추세"]["n"] == 12 and row["regimes"]["박스권"]["small"] is True
    assert pk["all_strategies"]["by_coin"]["ETH"]["n"] == 3


def test_learning_packet_lists_grades_waiting_repeats_and_known_results(world):
    a = world.agents
    pred = {"metric": "win_rate", "timeframe": "15m", "direction": "above", "value": 0.5, "after_trades": 30}
    h1 = R.add_trial(a, f"strat:{S}", S, "hypothesis", {"text": "추세장 롱이 낫다", "prediction": pred, "by": f"spec_{S}"},
                     ts=SAT - 20 * DAY)
    R.add_trial_result(a, h1, "graded", {"status": "graded", "correct": True, "value": 0.6, "n": 30,
                                         "prediction": pred, "by": f"spec_{S}"}, ts=SAT - 2 * DAY)
    R.add_trial(a, f"strat:{S}", S, "hypothesis", {"text": "추세장 롱이 낫다!", "prediction": {**pred, "value": 0.4},
                                                   "by": "team_lead"}, ts=SAT - DAY)
    pk = M.learning_packet(a, SAT)
    g = pk["graded_this_week"]
    assert g["by_role"][f"spec_{S}"] == {"name": R.role_name(f"spec_{S}"), "graded": 1, "correct": 1, "expired": 0}
    assert g["list"][0]["correct"] is True and "승률" in g["list"][0]["prediction_ko"]
    assert pk["waiting_predictions"]["count"] == 1
    assert pk["repeats"]["same_text"] == [{"strategy": S, "trial_ids": [h1, h1 + 1]}]
    assert pk["already_known"]["entry_study"]["conclusion_ko"] and "2,000" in pk["already_known"]["library"]
    assert pk["debate_record"]["calls"] == 0


# ---------------------------------------------------------------- weekly analysis meetings end to end
def test_cost_review_meeting_speakers_packet_and_hypotheses(world):
    bulk(world, 250, MON - HOUR)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("cost_review",), cost_review_hour_kst=11))
    pred = {"metric": "mean_roe", "timeframe": "5m", "direction": "below", "value": 0.0, "after_trades": 50}
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [],
            "hypotheses": [{"strategy": S, "text": "5분봉은 비용이 움직임보다 큼", "how_to_confirm": "50건",
                            "prediction": pred}]}
    runner = QueueRunner({"exec_cost": [team_answer("e", "cost.by_timeframe.15m.costs")],
                          "ops_auditor": [team_answer("o")], "team_lead": [lead]})
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
                  policy=pol, now_ms=MON, clock_ms=lambda: MON)
    assert [(r["room_id"], r["trigger"], r["status"], r["class"]) for r in out["rounds"]] == [
        ("team:ops", "cost_review", "done", "weekly")]
    assert runner.roles() == ["exec_cost", "ops_auditor", "team_lead"]
    pk = runner.calls[0]["packet"]
    assert pk["cost"]["trades"] == 250 and "by_timeframe" in pk["cost"]
    assert "비용·체결 회의" in runner.calls[0]["system"] and "rooms_meeting" not in runner.calls[0]["system"]
    said = [m for m in R.room_messages(world.agents, "team:ops", limit=50) if m["role"] == "exec_cost"]
    assert said and "[사실]" in said[0]["text"]                                     # cost.* is code-computed
    rows = R.trial_history(world.agents, kinds=("hypothesis",), limit=5)
    assert rows[0]["strategy"] == S and rows[0]["room_id"] == "team:ops"


def test_learning_review_lessons_become_notes_of_the_lead_room(world):
    bulk(world, 250, SAT - HOUR)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("learning_review",), learning_review_hour_kst=11))
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [],
            "lessons": {"confirmed": ["5분봉은 비용에 먹힘"], "refuted": ["박스권 숏이 낫다는 예측 틀림"],
                        "do_not_retest": ["파라미터 조금 바꾸기(연구에서 이미 봄)", "x", "y", "z"]}}
    runner = QueueRunner({"performance": [team_answer("p")], "learning": [team_answer("l", "learning.repeats")],
                          "team_lead": [lead]})
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
                  policy=pol, now_ms=SAT, clock_ms=lambda: SAT)
    assert [r["trigger"] for r in out["rounds"]] == ["learning_review"]
    assert runner.roles() == ["performance", "learning", "team_lead"]
    assert "lessons" in runner.calls[2]["system"] and "learning" in runner.calls[0]["packet"]
    notes = [n["text"] for n in R.room_notes(world.agents, "team:lead", 20)]
    assert len(notes) == 5                                                      # 1 + 1 + 3 (at most 3 a kind)
    assert any(n.startswith("[학습 정리 2026-10-10] 확인됨: 5분봉") for n in notes)
    assert RM.check_lead(lead, {})[0].get("lessons") is None                    # only in the learning meeting


# ---------------------------------------------------------------- the day after a US release
@pytest.fixture
def calendar(tmp_path, monkeypatch):
    path = tmp_path / "macro.csv"
    path.write_text("ts_utc,kind,source_url\n2026-10-06T12:30:00Z,CPI,https://www.bls.gov/x\n", encoding="utf-8")
    monkeypatch.setattr(EV, "PATH", path)
    EV.reset()
    yield EV.parse_ts("2026-10-06T12:30:00Z")
    EV.reset()


def test_event_review_the_day_after_once_and_only_when_the_run_covered_it(world, calendar, tmp_path):
    ev = calendar                                                   # Tuesday 21:30 KST -> Wednesday 11:00 KST
    pol = tpol(enabled=("event_review",), event_review_hour_kst=11)
    assert due(world, WED, tpol(enabled=("event_review",))) == []               # off in TriggerPolicy()
    assert due(world, WED - 10 * MIN, pol) == []
    [d] = due(world, WED, pol)
    assert (d.room_id, d.trigger, d.priority, d.data["class"]) == ("team:market", "event_review", 4, "weekly")
    assert d.data["event"]["kind"] == "CPI"
    assert d.data["key"] == f"event:CPI:{ev}" and "소비자물가" in d.data["summary_ko"]
    assert due(world, WED + 30 * HOUR, pol)                                     # still due the next day
    assert due(world, WED + 36 * HOUR, pol) == []                               # the window is over
    world_run(world, d, WED)
    assert due(world, WED + HOUR, pol) == []                                    # once per event
    os.makedirs(tmp_path / "late")
    late = World(tmp_path / "late", start=ev - HOUR)                            # started inside the window
    assert due(late, WED, pol) == []
    assert TR.skipped_status(late.paper(), WED, pol)["event_review"][0]["event"].startswith("CPI")


def test_event_packet_compares_the_window_with_earlier_weekdays(world, calendar):
    ev = calendar
    for k in range(2):                       # entered 1h after the release (rec: entry = exit - 3h)
        world.store.trade(f"{S}@15m", rec(S, "15m", -20.0, ev + 4 * HOUR + k * MIN))
    for back in (1, 4, 5, 6, 7):             # Mon 10-05, Fri 10-02, Thu, Wed, Tue: the same hours
        world.store.trade(f"{S}@15m", rec(S, "15m", 5.0, ev - back * DAY + 4 * HOUR))
    world.store.commit()
    pk = M.event_packet(world.paper(), WED, {"kind": "CPI", "ts_ms": ev, "name_ko": "소비자물가(CPI)"},
                        get=fake_get(lambda s, t: 100.0 + (1.0 if t > ev else 0.0)))
    o = pk["ours"]
    assert o["event_window"]["entered"] == 2 and o["event_window"]["entered_pnl"] == -40.0
    assert o["baseline_days"] == 5 and o["baseline_mean"]["entered"] == 1 and o["baseline_mean"]["entered_pnl"] == 5.0
    assert pk["market"]["BTC"]["event_window"]["move"] == pytest.approx(0.01, abs=1e-3)
    # #88: no liq.db is "수집 안 됨" (not collected), never a silent gap or a zero
    assert pk["coin_flips"]["event_window"]["entered"] == 0
    assert pk["liquidations"]["BTC"]["event_window"]["collected"] is False
    assert pk["liquidations"]["BTC"]["event_window"]["status_ko"] == "수집 안 됨"
    assert M.event_packet(world.paper(), WED, {"kind": "CPI", "ts_ms": ev})["market"] == {"BTC": None, "ETH": None}


# ---------------------------------------------------------------- the daily bull vs bear debate
def test_bull_bear_trigger_daily_at_noon_rotating_coins(world):
    pol = tpol(enabled=("bull_bear",), bull_bear_hour_kst=12)
    assert due(world, NOON, tpol(enabled=("bull_bear",))) == []
    assert due(world, NOON - 10 * MIN, pol) == []
    [d] = due(world, NOON, pol)
    assert (d.room_id, d.trigger, d.priority, d.data["class"]) == ("team:market", "bull_bear", 3, "scheduled")
    assert d.data["symbol"] in TR.BULL_BEAR_COINS and "거래 없음" in d.data["summary_ko"]
    coins = [TR.bull_bear_coin(NOON + k * DAY) for k in range(6)]
    assert sorted(coins) == sorted(TR.BULL_BEAR_COINS)                               # each coin once in six days
    world_run(world, d, NOON)
    TR.advance_cursors(world.agents, d)
    assert due(world, NOON + HOUR, pol) == []                                        # once a day
    assert due(world, NOON + 5 * HOUR, pol) == []                                    # the 4h window is over
    assert due(world, NOON + DAY, pol)[0].data["symbol"] == TR.bull_bear_coin(NOON + DAY)


def _debate(world, lead, now=NOON, get=None):
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("bull_bear",), bull_bear_hour_kst=12))
    runner = QueueRunner({"bull": [team_answer("b", "committee.returns.24h")], "bear": [team_answer("x")],
                          "risk_officer": [team_answer("r")], "team_lead": [lead]})
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
                  policy=pol, now_ms=now, clock_ms=lambda: now, price_get=get)
    return out, runner


def test_bull_bear_meeting_records_the_call_and_grades_it_after_24_hours(world):
    sym = TR.bull_bear_coin(NOON)
    get = fake_get(lambda s, t: 100.0 if t <= NOON else 101.0)        # +1% a day later
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [],
            "call": {"direction": "상승", "confidence": 2}}
    out, runner = _debate(world, lead, get=get)
    assert [(r["trigger"], r["status"], r["class"]) for r in out["rounds"]] == [("bull_bear", "done", "scheduled")]
    assert runner.roles() == ["bull", "bear", "risk_officer", "team_lead"]
    pk = runner.calls[0]["packet"]["committee"]
    assert pk["symbol"] == sym and pk["reference"]["price"] == 100.0
    # #88: the bull and the bear argue without our positions and past calls; the chair sees them
    assert "track_record" not in pk and "ours" not in pk and pk["hidden"]
    assert runner.calls[3]["packet"]["committee"]["track_record"]["calls"] == 0
    assert "어떤 주문" in pk["note"] and "주문·계좌 변경으로도 이어지지 않" in runner.calls[3]["system"]
    assert '"call"' in runner.calls[3]["system"] and '"call"' not in runner.calls[0]["system"]
    [row] = world.q("SELECT status, direction, confidence, ref_price, due_ts FROM committee_calls")
    assert row[:4] == ("open", "상승", 2, 100.0) and row[4] == pk["reference"]["ts"] + DAY
    texts = [m["text"] for m in R.room_messages(world.agents, "team:market", limit=50)]
    assert any("판정 기록 #1" in t and "거래로 이어지지 않습니다" in t for t in texts)
    # 24 hours later the tick grades it (code only, no AI call)
    later = NOON + DAY + 10 * MIN
    RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], QueueRunner({}),
            policy=RM.RoomsPolicy(triggers=tpol(enabled=())), now_ms=later, clock_ms=lambda: later, price_get=get)
    [g] = world.q("SELECT status, correct, move FROM committee_calls")
    assert g[0] == "graded" and g[1] == 1 and g[2] == pytest.approx(0.01)
    assert any("판정 #1 채점" in m["text"] and "맞음" in m["text"]
               for m in R.room_messages(world.agents, "team:market", limit=50))
    tr = CM.track_record(world.agents)
    assert (tr["graded"], tr["correct"], tr["always_up_correct"], tr["p_vs_coin_flip"]) == (1, 1, 1, 0.5)
    assert DG.staff_board(world.agents, later, 7)["debate"]["graded"] == 1


def test_a_malformed_call_is_recorded_as_unreadable_and_never_graded(world):
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [],
            "call": {"direction": "오를 듯", "confidence": 5}}
    get = fake_get()
    out, _r = _debate(world, lead, get=get)
    assert out["rounds"][0]["status"] == "done"                                # the meeting itself is fine
    [row] = world.q("SELECT status, direction, data FROM committee_calls")
    assert row[0] == "unreadable" and row[1] is None and "direction" in json.loads(row[2])["why"]
    assert any("판정을 읽을 수 없어" in m["text"] for m in R.room_messages(world.agents, "team:market", limit=50))
    assert CM.grade_due(world.agents, NOON + 3 * DAY, get) == []
    assert CM.track_record(world.agents)["ungraded"] == {"unreadable": 1}


def test_no_price_means_no_grade_and_an_old_open_call_expires(world):
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [],
            "call": {"direction": "중립", "confidence": 1}}
    _debate(world, lead, get=None)
    assert world.q("SELECT status FROM committee_calls") == [("no_price",)]
    CM.record(world.agents, day="2026-10-08", symbol="ETHUSDT", round_id=None, call={"direction": "하락", "confidence": 3},
              why="", ref=(NOON, 50.0), now_ms=NOON)
    assert CM.grade_due(world.agents, NOON + 2 * DAY, None) == []               # price unknown: tried again later
    [e] = CM.grade_due(world.agents, NOON + 5 * DAY, None)
    assert e["status"] == "expired"


def test_call_parsing_and_grading_rules():
    assert CM.parse_call({"direction": "상승", "confidence": 3}) == ({"direction": "상승", "confidence": 3}, "")
    assert CM.parse_call({"direction": " 중립 ", "confidence": "1"})[0] == {"direction": "중립", "confidence": 1}
    for bad in (None, "상승", {"direction": "up", "confidence": 2}, {"direction": "하락", "confidence": 0},
                {"direction": "하락", "confidence": True}, {"direction": "하락"}):
        call, why = CM.parse_call(bad)
        assert call is None and why
    assert CM.judge("상승", 0.006) and not CM.judge("상승", 0.004) and CM.judge("하락", -0.005)
    assert CM.judge("중립", 0.0049) and not CM.judge("중립", -0.005)
    assert CM.p_at_least(1, 1) == 0.5 and CM.p_at_least(10, 10) == pytest.approx(1 / 1024)
    given = {"meeting": {"trigger": "bull_bear"}}
    clean, problems = RM.check_lead({"summary": ["a"], "call": {"direction": "옆", "confidence": 2}}, given)
    assert clean["call"] is None and "call_problem" in clean and problems
    assert "판정: 읽을 수 없음" in RM.render("lead", clean)
    ok, _p = RM.check_lead({"summary": ["a"], "call": {"direction": "하락", "confidence": 2}}, given)
    assert "판정(앞으로 24시간): 하락, 확신 2/3" in RM.render("lead", ok)


def test_the_debate_table_on_an_existing_agents_db(tmp_path):
    path = str(tmp_path / "agents3.db")
    old = R.open_agents(path)                                       # an agents3.db from before 2026-10-04
    assert old.execute("SELECT name FROM sqlite_master WHERE name = 'committee_calls'").fetchone() is None
    assert CM.track_record(old)["calls"] == 0 and CM.week_summary(old, 0, 1) is None    # no table: nothing, no error
    CM.ensure(old)
    CM.ensure(old)                                                  # idempotent
    rid = CM.record(old, day="2026-10-07", symbol="BTCUSDT", round_id=None, call={"direction": "상승", "confidence": 1},
                    why="", ref=(NOON, 1.0), now_ms=NOON)
    assert rid == 1 and CM.record(old, day="2026-10-07", symbol="BTCUSDT", round_id=None, call=None, why="x", ref=None,
                                  now_ms=NOON) is None              # once per day and coin
    # the trial kinds and their CHECK constraint are untouched
    assert R.TRIAL_KINDS == ("hypothesis", "test", "copy_proposal", "newlab")
    with pytest.raises(sqlite3.IntegrityError):
        old.execute("INSERT INTO trials (ts, room_id, kind, spec, spec_hash) VALUES (0, 'x', 'debate', '{}', 'h')")


# ---------------------------------------------------------------- speakers of the meetings
def test_speaking_orders_of_the_new_and_changed_meetings():
    def plan(trig, room):
        return [r for r, _t in RM.team_plan(TR.Due(room, trig, 0, {}, trig))]
    assert plan("ranking", "team:review") == ["performance", "pnl_reviewer", "risk_officer", "team_lead"]
    assert plan("cost_review", "team:ops") == ["exec_cost", "ops_auditor", "team_lead"]
    assert plan("combo_review", "team:risk") == ["combo_synergy", "risk_officer", "team_lead"]
    assert plan("coin_review", "team:review") == ["coin_compare", "regime_perf", "team_lead"]
    assert plan("learning_review", "team:lead") == ["performance", "learning", "team_lead"]
    assert plan("event_review", "team:market") == ["news_calendar", "macro_corr", "chart_regime", "team_lead"]
    assert plan("bull_bear", "team:market") == ["bull", "bear", "risk_officer", "team_lead"]
    p = RM.RoomsPolicy()
    for trig, (_wd, room) in TR.ANALYSES.items():
        d = TR.Due(room, trig, 0, {}, trig)
        assert RM.round_min_calls(d, p) == RM.round_max_calls(d, p) <= p.max_calls_team_round
    for trig in ("event_review", "bull_bear", "ranking"):
        assert RM.round_max_calls(TR.Due("team:market", trig, 0, {}, trig), p) == 4
    assert RM.round_min_calls(TR.Due(f"strat:{S}", "tf_split", 0, {}, "tf_split"), p) == 3
    for role in ("bull", "bear", "exec_cost", "combo_synergy", "coin_compare", "regime_perf", "learning",
                 "news_calendar", "macro_corr", "tf_compare", "performance"):
        info = RM.ROLE_INFO[role]
        assert info["duty"] and info["duty"] in RM.system_prompt(role, "expert" if role == "tf_compare" else "team")
    assert RM.ROLE_INFO["bull"]["team"] == "market" and RM.ROLE_INFO["bear"]["model"] == "sonnet"
    for trig in (*TR.ANALYSES, "event_review", "bull_bear"):
        assert trig in RM.TRIGGER_KO and trig in RM._PROBE and trig in RM.MEETING_FILE
    assert {"cost", "combo", "coins", "learning", "event", "committee"} <= set(RM.CODE_ROOTS)


def test_tf_split_meeting_keeps_six_calls_with_the_timeframe_comparer(world):
    from test_digest import TF_AT, split_trades
    from test_rooms import NOTE, TEST, StubLab, analysis, challenge
    split_trades(world)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("tf_split",), tf_split_hour_kst=18))
    tfc = {"headline": "다른 매매법도 5분봉에서 짐", "findings": [{"claim": "x", "kind": "fact",
                                                          "evidence": ["tf_split.cross.by_timeframe.1h.down"]}],
           "verdict": "needs_test", "suggestion": None}
    runner = QueueRunner({f"spec_{S}": [analysis(NOTE), analysis(TEST)], "tf_compare": [tfc],
                          "devils_advocate": [challenge("disagree")],
                          "validator": [{"pass_gate": True, "explanation": "통과"}],
                          "approver": [{"approve": False, "reason": "관찰"}]})
    RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
            lab=StubLab(True), policy=pol, now_ms=TF_AT, clock_ms=lambda: TF_AT)
    # specialist, comparer, advocate, revision: no second expert (the strategy meeting stays within 6 calls)
    assert runner.roles()[:4] == [f"spec_{S}", "tf_compare", "devils_advocate", f"spec_{S}"]
    assert "entry_timing" not in runner.roles()
    assert len(runner.calls) <= RM.RoomsPolicy().max_calls_strategy_round
    cross = runner.calls[1]["packet"]["tf_split"]["cross"]
    assert cross["by_timeframe"]["1h"]["down"] == 1 and cross["this"]["best_tf"] == "15m"


# ---------------------------------------------------------------- the weekly report: debate and security lines
def test_weekly_report_has_the_debate_and_the_security_line(world, tmp_path):
    CM.ensure(world.agents)
    CM.record(world.agents, day="2026-10-07", symbol="BTCUSDT", round_id=None, call={"direction": "상승", "confidence": 1},
              why="", ref=(NOON, 100.0), now_ms=NOON)
    CM.grade_due(world.agents, NOON + DAY + MIN, fake_get(lambda s, t: 99.0))
    secret = tmp_path / "live.env"
    secret.write_text("KEY=x")
    sec = DG.security_check(str(tmp_path), NOON, secret_files=(str(secret), str(tmp_path / "missing.env")),
                            secret_dirs=(str(tmp_path / "nodir"),))
    assert sec["secrets_checked"] == 3 and sec["secrets_readable"] == 1 and sec["db_files"] >= 4
    os.chmod(world.paths["paper"], 0o644)
    assert DG.security_check(str(tmp_path), NOON)["db_world_readable"] >= 1
    assert DG.store_security(world.agents, world.paths["paper"], NOON)["secrets_readable"] == 0     # the real paths
    assert DG.store_security(world.agents, world.paths["paper"], NOON + HOUR) is None                # once a day
    rep = DG.week_report(world.paper(), world.agents, kst(2026, 10, 11, 21, 5))
    assert rep["debate"]["all"]["graded"] == 1 and rep["debate"]["all"]["correct"] == 0
    text = DG.compose_week(rep)
    assert "낙관·비관 토론: 이번 주 0/1, 누적 0/1" in text
    assert ("보안 점검: 이상 없음" in text or "⚠ 보안 확인 필요: " in text) and "fail2ban" not in text   # long line: dashboard
    assert DG.security_line(sec, short=True).startswith("⚠ 보안 확인 필요: 비밀 파일 열림 1개")
    assert DG.security_line({**sec, "secrets_readable": 0, "db_world_readable": 0}, short=True) == "보안 점검: 이상 없음"
    line = DG.security_line(sec)
    assert "열림 1개 ⚠️ 확인 필요" in line and "KEY" not in line and str(tmp_path) not in line
    assert "점검 기록 없음" in DG.security_line(None)


def test_the_tick_stores_the_security_check_and_the_hours(world):
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"],
                  QueueRunner({}), policy=RM.policy_from_env({}), now_ms=kst(2026, 10, 7, 3, 0),
                  clock_ms=lambda: kst(2026, 10, 7, 3, 0))
    assert out["rounds"] == []
    assert R.get_cursor(world.agents, DG.SECURITY_CURSOR)["day"] == "2026-10-07"
    h = R.get_cursor(world.agents, RM.HOURS_CURSOR)
    assert (h["cost_review"], h["combo_review"], h["coin_review"], h["learning_review"]) == (11, 11, 11, 11)
    assert h["event_review"] == 11 and h["bull_bear"] == 12
    assert world.q("SELECT COUNT(*) FROM committee_calls") == [(0,)]                # the table exists


# ---------------------------------------------------------------- one extra weekly meeting (owners' decision 2026-10-04)
THU = kst(2026, 10, 8, 11, 5)
FRI = kst(2026, 10, 9, 11, 5)


def _cost_week(world):
    """The Monday cost meeting held (250 trades before it)."""
    bulk(world, 250, MON - HOUR)
    pol = tpol(enabled=("cost_review",), cost_review_hour_kst=11)
    [d] = due(world, MON, pol)
    world_run(world, d, MON)
    return pol


def test_an_extra_weekly_meeting_with_twice_the_minimum_of_new_trades(world):
    pol = _cost_week(world)
    bulk(world, 400, WED - HOUR, step=5 * MIN)                      # 2 x 200 new trades since Monday's meeting
    assert due(world, WED - 10 * MIN, pol) == []                    # Wednesday 10:55: not yet
    [d] = due(world, WED, pol)
    assert (d.room_id, d.trigger, d.data["key"], d.data["class"]) == ("team:ops", "cost_review",
                                                                      "cost_review:extra:2026-10-07", "weekly")
    assert d.data["extra_run"] is True and d.data["trades"] == 400 and "추가 회의" in d.data["summary_ko"]
    assert "새 거래 400건(기준 400건 이상)" in d.data["why_ko"]
    st = TR.skipped_status(world.paper(), WED, pol, world.agents)["cost_review"]["extra"]
    assert st["ok"] is True and st["new_trades"] == 400 and st["last_run"] == "2026-10-05"
    world_run(world, d, WED)
    assert due(world, WED + HOUR, pol) == []                         # once
    bulk(world, 800, FRI - HOUR, step=MIN)                           # plenty more on Friday: never a third time
    assert due(world, FRI, pol) == []
    st = TR.skipped_status(world.paper(), FRI, pol, world.agents)["cost_review"]["extra"]
    assert st["ok"] is False and "이번 주에 이미 2번" in st["why"]
    # the next week starts over: the Monday meeting is due again
    assert [x.data["key"] for x in due(world, MON + 7 * DAY, pol)] == ["cost_review:2026-10-12"]


def test_no_extra_meeting_with_less_data_within_two_days_or_on_its_own_weekday(world, tmp_path):
    pol = _cost_week(world)
    bulk(world, 399, WED - HOUR, step=5 * MIN)
    assert due(world, WED, pol) == []                                # one short of 2 x 200
    assert "399건(추가 회의는 400건 이상)" in TR.skipped_status(world.paper(), WED, pol, world.agents)["cost_review"]["extra"]["why"]
    bulk(world, 400, TUE - HOUR, aid=f"{V45}@1h", step=MIN)          # enough by Tuesday, but one day after Monday
    assert due(world, TUE, pol) == []
    assert "뒤 1일(최소 2일)" in TR.skipped_status(world.paper(), TUE, pol, world.agents)["cost_review"]["extra"]["why"]
    assert [x.data["key"] for x in due(world, WED, pol)] == ["cost_review:extra:2026-10-07"]
    # never on its own weekday (the next Monday is the regular meeting, not an extra one)
    os.makedirs(tmp_path / "w2")
    w2 = World(tmp_path / "w2")
    bulk(w2, 250, MON - 7 * DAY - HOUR)
    [d] = due(w2, MON - 7 * DAY, pol)
    world_run(w2, d, MON - 7 * DAY)
    bulk(w2, 600, MON - HOUR, step=MIN)
    keys = [x.data["key"] for x in due(w2, MON, pol)]
    assert keys == ["cost_review:2026-10-05"]


def test_the_weekly_cap_also_holds_back_a_late_regular_meeting(world):
    pol = tpol(enabled=("cost_review",), cost_review_hour_kst=11)
    bulk(world, 250, MON - HOUR)
    # two meetings already this KST week (e.g. last week's deferred one and an extra one): the regular one waits
    for k, key in enumerate(("cost_review:2026-09-28", "cost_review:extra:2026-10-05")):
        d = TR.Due("team:ops", "cost_review", 4, {"key": key, "class": "weekly", "cursors": {}}, "cost_review")
        world_run(world, d, MON - 5 * HOUR + k * HOUR)
    assert due(world, MON, pol) == []
