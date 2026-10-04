"""Meeting digests (paperbot/agents/digest.py, owners' choice 2026-10-03): the timeframe-split meeting, one day's
meeting conclusions, the staff scorecard, the Sunday weekly report, and the dashboard's /api/digest/* views."""

import pytest

from paperbot.agents import digest as DG
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.agents import triggers as TR
from paperbot.notify import INFO, ListNotifier

from test_rooms import (DAY, HOUR, MIN, NOTE, ROOM, S, SPEC, QueueRunner, World, analysis, challenge, kst,  # noqa: F401
                        team_answer)

TF_AT = kst(2026, 10, 7, 18, 5)          # Wednesday 18:05 KST
SUNDAY = kst(2026, 10, 11, 21, 5)        # Sunday 21:05 KST


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def split_trades(world, t_end=TF_AT - HOUR):
    """N17 on 15m: 10 wins of +60; on 1h: 10 losses of -40 (spread 1,000 of a 5,000 start: a split)."""
    for k in range(10):
        world.trade(f"{S}@15m", 60.0, t_end - (20 - k) * HOUR, symbol="ETHUSDT")
        world.trade(f"{S}@1h", -40.0, t_end - (10 - k) * HOUR, side=-1)
    world.trade("V45_AMB@15m", 5.0, t_end - 30 * MIN)


def tf_policy(**kw):
    p = RM.RoomsPolicy(triggers=TR.TriggerPolicy(enabled=("tf_split",), tf_split_hour_kst=18), **kw)
    return p


# ---------------------------------------------------------------- timeframe split numbers
def test_tf_split_finds_the_strategy_whose_timeframes_disagree(world):
    split_trades(world)
    got = DG.tf_split(world.paper())
    assert got["split"] == [S] and got["initial"] == pytest.approx(5000.0)
    row = got["strategies"][0]
    assert row["strategy"] == S and (row["best_tf"], row["worst_tf"]) == ("15m", "1h")
    assert row["best_pnl"] == pytest.approx(600) and row["worst_pnl"] == pytest.approx(-400)
    assert row["spread"] == pytest.approx(1000) and row["split"] is True
    m15 = row["timeframes"]["15m"]
    assert m15["trades"] == 10 and m15["win_rate"] == 1.0 and m15["coins"] == {"ETH": {"trades": 10, "pnl": 600.0}}
    assert m15["cost_per_trade"] == pytest.approx(0.1) and m15["move_before_costs"] == pytest.approx(0.01)
    assert m15["exits"] == {"익절 잠금": 10} and m15["sides"]["롱"]["trades"] == 10
    assert row["timeframes"]["1h"]["sides"]["숏"]["pnl"] == pytest.approx(-400)
    v45 = next(r for r in got["strategies"] if r["strategy"] == "V45_AMB")
    assert v45["split"] is False and v45["timeframes"]["1h"] == {"trades": 0}
    # not enough trades on one side, or a spread under 10% of the start: no split
    assert DG.tf_split(world.paper(), min_trades=11)["split"] == []
    assert DG.tf_split(world.paper(), min_spread_pct=0.25)["split"] == []


def test_tf_split_meeting_at_18_in_the_strategy_room_with_the_numbers(world):
    split_trades(world)
    assert TR.find_due(world.paper(), None, world.agents, None, TF_AT, TR.TriggerPolicy(enabled=("tf_split",))) == []
    pol = tf_policy()
    assert TR.find_due(world.paper(), None, world.agents, None, TF_AT - 2 * HOUR, pol.triggers) == []   # before 18:00
    [due] = TR.find_due(world.paper(), None, world.agents, None, TF_AT, pol.triggers)
    assert (due.room_id, due.trigger, due.data["class"]) == (ROOM, "tf_split", "weekly")
    assert "봉 비교" in due.data["summary_ko"] and due.data["best_tf"] == "15m"
    runner = QueueRunner({SPEC: [analysis(NOTE)], "tf_compare": [{"headline": "5분봉 비용", "findings": [],
                                                                 "verdict": "agree", "suggestion": None}],
                          "devils_advocate": [challenge("agree")]})
    out = world.tick(runner, TF_AT, policy=pol)
    assert [(r["room_id"], r["trigger"], r["status"]) for r in out["rounds"]] == [(ROOM, "tf_split", "done")]
    # owners' choice 2026-10-04: the timeframe comparer speaks after the specialist, with the cross-strategy view
    assert runner.roles() == [SPEC, "tf_compare", "devils_advocate"]
    assert "cross" in runner.calls[1]["packet"]["tf_split"] and "tf_split.cross" in runner.calls[1]["system"]
    pk = runner.calls[0]["packet"]
    assert pk["meeting"]["trigger"] == "tf_split" and pk["tf_split"]["split"] is True
    assert pk["tf_split"]["timeframes"]["1h"]["trades"] == 10 and "how_to_read" in pk["tf_split"]
    assert "tf_split" in runner.calls[0]["system"]           # the specialist's prompt explains it
    # the same strategy waits three days; the meeting is daily
    assert world.tick(QueueRunner({}), TF_AT + 30 * MIN, policy=pol)["rounds"] == []
    assert world.tick(QueueRunner({}), TF_AT + DAY, policy=pol)["rounds"] == []
    assert [d.room_id for d in TR.find_due(world.paper(), None, world.agents, None, TF_AT + 3 * DAY,
                                           pol.triggers)] == [ROOM]


def test_server_policy_turns_on_the_tf_split_and_the_weekly_report():
    assert RM.RoomsPolicy().triggers.tf_split_hour_kst == -1 and RM.RoomsPolicy().weekly_report_hour_kst == -1
    p = RM.policy_from_env({})
    assert p.triggers.tf_split_hour_kst == RM.TF_SPLIT_HOUR_DEFAULT == 18
    assert p.weekly_report_hour_kst == RM.WEEKLY_REPORT_HOUR_DEFAULT == 21
    off = RM.policy_from_env({"AGENTS_TF_SPLIT_HOUR": "off", "AGENTS_WEEKLY_REPORT_HOUR": "OFF"})
    assert off.triggers.tf_split_hour_kst == -1 and off.weekly_report_hour_kst == -1
    assert RM.policy_from_env({"AGENTS_TF_SPLIT_HOUR": "19"}).triggers.tf_split_hour_kst == 19
    for bad in ("24", "-1", "6pm"):
        with pytest.raises(ValueError):
            RM.policy_from_env({"AGENTS_WEEKLY_REPORT_HOUR": bad})


def test_loss_packets_show_the_latest_wins_too(world):
    world.trade(f"{S}@15m", 30.0, kst(2026, 10, 7, 9, 0), context={"regime": "trend_up"})
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE)], "devils_advocate": [challenge("agree")]})
    world.tick(runner, kst(2026, 10, 7, 15, 0))
    wins = runner.calls[0]["packet"]["losses"]["recent_wins"]
    assert len(wins) == 1 and wins[0]["roe"] == pytest.approx(0.6) and wins[0]["regime"]
    assert "recent_wins" in runner.calls[0]["system"]


# ---------------------------------------------------------------- one day, the staff
def _two_meetings(world):
    """A team meeting with a reply and a question, and a strategy meeting with an unreadable answer."""
    t = kst(2026, 10, 7, 14, 5)
    pol = RM.RoomsPolicy()
    pol.triggers.ranking_hour_kst = 14
    pol.triggers.fresh_run_min_trades = 0       # no trades in this world (the fresh-run skip: test_fresh_run_*)
    first = {**team_answer("p"), "ask_next": "하위 3개의 손실이 박스권에 몰렸나요?"}
    second = {**team_answer("r"), "responds_to": {"role": "pnl_reviewer", "stance": "disagree",
                                                  "point": "비용이 더 커 보임"}}
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [], "open_disagreement": "장세 vs 비용"}
    world.tick(QueueRunner({"performance": [team_answer("f")], "pnl_reviewer": [first], "risk_officer": [second],
                            "team_lead": [lead]}), t, policy=pol)
    world.losses(t=t + HOUR)
    world.tick(QueueRunner({SPEC: ["not json", "not json"]}), t + HOUR)
    return t


def test_day_digest_lists_every_meeting_with_replies_and_lead_lines(world):
    t = _two_meetings(world)
    d = DG.day_digest(world.agents, R.kst_day(t))
    assert d["n"] == 2 and d["disagreements"] == 1
    m = d["meetings"][0]
    assert (m["room_id"], m["trigger"], m["trigger_ko"], m["status"]) == ("team:review", "ranking", "순위 검토", "done")
    assert [s["role"] for s in m["speakers"]] == ["performance", "pnl_reviewer", "risk_officer", "team_lead"]
    assert m["replies"] == [{"from": "risk_officer", "from_name": R.role_name("risk_officer"), "to": "pnl_reviewer",
                             "to_name": R.role_name("pnl_reviewer"), "stance": "disagree", "point": "비용이 더 커 보임"}]
    assert m["asks"][0]["text"].startswith("하위 3개") and m["lead"] == ["a", "b", "c"]
    assert m["open_disagreement"] == "장세 vs 비용" and m["calls"] == 4
    assert d["meetings"][1]["room_id"] == ROOM and d["meetings"][1]["status"] == "failed"
    assert DG.day_digest(world.agents, R.kst_day(t + DAY))["n"] == 0
    with pytest.raises(ValueError):
        DG.day_start_ms("10/07")


def test_staff_board_counts_turns_replies_and_unreadable_answers(world):
    t = _two_meetings(world)
    b = DG.staff_board(world.agents, t + 2 * HOUR, 7)
    by = {s["role"]: s for s in b["staff"]}
    assert by["risk_officer"]["replies"]["disagree"] == 1 and by["pnl_reviewer"]["replied_by"]["disagree"] == 1
    assert by["pnl_reviewer"]["asks"] == 1 and by["pnl_reviewer"]["turns"] == 1 and by["team_lead"]["meetings"] == 1
    assert by[SPEC]["unreadable"] == 1 and by[SPEC]["turns"] == 0
    assert by["pnl_reviewer"]["facts"] == 1 and by["pnl_reviewer"]["predictions"]["graded"] == 0
    assert DG.staff_board(world.agents, t + 10 * DAY, 7)["staff"] == []     # nothing in the window (no grades)


# ---------------------------------------------------------------- the week
def test_week_report_numbers_and_the_telegram_text(world):
    for k in range(4):                                            # this week
        world.trade(f"{S}@15m", 50.0, SUNDAY - (k + 1) * DAY)
        world.trade("V45_AMB@1h", -30.0, SUNDAY - (k + 1) * DAY)
    world.trade("RANDOM_1@15m", 10.0, SUNDAY - DAY)
    world.trade(f"{S}@1h", -100.0, SUNDAY - 9 * DAY)               # the week before
    world.store.alert(SUNDAY - 2 * DAY, "WARN", f"[{S}@15m] BUST: equity 0.00")
    world.store.commit()
    rep = DG.week_report(world.paper(), world.agents, SUNDAY)
    tot = rep["strategies_total"]
    assert (tot["pnl"], tot["trades"], tot["win_rate"]) == (80.0, 8, 0.5)
    assert rep["strategies_total_prev"]["pnl"] == -100.0
    assert [r["strategy"] for r in rep["top"]] == [S, "V45_AMB"] and rep["top"][0]["prev_rank"] == 2
    cf = rep["coin_flips"]
    assert cf["strategy_accounts"] == 4 and cf["strategy_accounts_beating_median"] == 1 and cf["mean_pnl"] == 10.0
    assert rep["timeframes"]["15m"]["pnl"] == 200.0 and len(rep["busts"]) == 1
    text = DG.compose_week(rep)
    assert text.split("\n")[0].startswith("📊 주간 성적표 · ") and text.split("\n")[0].endswith("~10/11") and "+$80" in text and "▲1" in text and "파산 1개" in text
    assert "체크포인트" in text and len(text) <= 4000


def test_weekly_report_goes_out_on_sunday_once_and_retries_a_refused_send(world):
    pol = RM.RoomsPolicy(triggers=TR.TriggerPolicy(enabled=(), fresh_run_min_trades=0), weekly_report_hour_kst=21)
    n = ListNotifier()
    world.tick(QueueRunner({}), SUNDAY - DAY, policy=pol, notifier=n)               # Saturday
    world.tick(QueueRunner({}), SUNDAY - 2 * HOUR, policy=pol, notifier=n)          # Sunday 19:05
    assert n.messages == []
    world.tick(QueueRunner({}), SUNDAY, policy=pol, notifier=n)
    world.tick(QueueRunner({}), SUNDAY + 30 * MIN, policy=pol, notifier=n)
    assert len(n.messages) == 1 and n.messages[0][0] == INFO and n.messages[0][1].startswith("📊 주간 성적표")
    assert world.tick(QueueRunner({}), SUNDAY, notifier=n)["rounds"] == [] and len(n.messages) == 1   # off by default

    class Refuses(ListNotifier):
        def send(self, level, text):
            super().send(level, text)
            return False
    bad = Refuses()
    nxt = SUNDAY + 7 * DAY
    for k in range(RM.WEEKLY_REPORT_TRIES + 3):
        world.tick(QueueRunner({}), nxt + k * 15 * MIN, policy=pol, notifier=bad)
    assert len(bad.messages) == RM.WEEKLY_REPORT_TRIES and R.get_cursor(world.agents, "telegram:weekly_report:2026-10-18") is None
    # a Telegram outage of up to 3 hours (12 ticks) still delivers the week's report that evening
    assert RM.WEEKLY_REPORT_TRIES * 15 * MIN <= 3 * HOUR < pol.weekly_report_window_ms


# ---------------------------------------------------------------- dashboard
def test_dashboard_digest_endpoints(world):
    from fastapi.testclient import TestClient

    from paperbot.dash.app import create_app, hash_password
    t = _two_meetings(world)
    split_trades(world)                                      # after the meetings (they would open a loss review)
    app = create_app(world.paths["paper"], hash_password("pw"), b"s" * 32, agents_db=world.paths["agents"],
                     inbox_db=str(world.paths["paper"]).replace("paper.db", "dash_inbox.db"))
    c = TestClient(app)
    assert c.get("/api/digest/day").status_code == 401
    assert c.post("/api/login", json={"password": "pw"}).status_code == 200
    day = c.get(f"/api/digest/day?day={R.kst_day(t)}").json()
    assert day["n"] == 2 and day["meetings"][0]["trigger_ko"] == "순위 검토"
    assert c.get("/api/digest/day?day=2026/10/07").status_code == 400
    assert c.get("/api/digest/day").json()["day"] == R.kst_day(int(__import__("time").time() * 1000))
    tf = c.get("/api/digest/tf").json()
    assert tf["split"] == [S] and "computed_at" in tf
    week = c.get("/api/digest/week").json()
    assert "telegram_text" in week and week["telegram_text"].startswith("📊 주간 성적표")
    staff = c.get("/api/digest/staff?days=999").json()
    assert staff["days"] == 60 and isinstance(staff["staff"], list)


def test_dashboard_has_the_digest_tab():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "paperbot" / "dash" / "static"
    html = (root / "index.html").read_text()
    assert 'data-v="digest"' in html and 'id="v-digest"' in html and "/static/digest.js" in html
    js = (root / "digest.js").read_text()
    for path in ("/api/digest/day", "/api/digest/staff", "/api/digest/week", "/api/digest/tf"):
        assert path in js
    assert 'v === "digest"' in (root / "app.js").read_text()


# ---------------------------------------------------------------- review fixes (2026-10-03)
def test_a_one_trade_outlier_does_not_hide_a_split(world):
    split_trades(world)
    world.store.add_account(f"{S}@4h", S, "4h", "strategy", TF_AT - 30 * DAY, "paper-v3")
    world.store.commit()
    world.trade(f"{S}@4h", 900.0, TF_AT - 2 * HOUR)               # one trade: the best timeframe, but too few
    row = DG.tf_split(world.paper())["strategies"][0]
    assert row["split"] is True and (row["best_tf"], row["worst_tf"]) == ("15m", "1h")


def test_tf_split_skips_a_full_room_and_takes_the_next_strategy(world):
    split_trades(world)
    for k in range(10):                                           # V45 splits too, less widely
        world.trade("V45_AMB@15m", 40.0, TF_AT - (30 - k) * HOUR)
        world.trade("V45_AMB@1h", -30.0, TF_AT - (20 - k) * HOUR)
    day0 = TR.kst_day_start(TF_AT)
    for k in range(3):                                            # N17's room used its 3 non-owner slots today
        world.agents.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, ended_ts, status) "
                             "VALUES (?, 'loss_cluster', '{}', ?, ?, 'done')", (ROOM, day0 + k * HOUR, day0 + k * HOUR + 1))
    world.agents.commit()
    pol = tf_policy()
    pol.triggers.tf_split_per_day = 1
    dues = TR.find_due(world.paper(), None, world.agents, None, TF_AT, pol.triggers)
    assert [d.room_id for d in dues] == ["strat:V45_AMB"]


def test_week_counts_each_test_once_and_only_strategy_busts(world):
    t = SUNDAY - DAY
    a = R.add_trial_with_result(world.agents, "team:lab", None, "newlab", {"x": 1}, "passed", {}, ts=t)
    R.add_trial_result(world.agents, a, "proposed", {}, ts=t + 1)        # the proposal row is not a second test
    R.add_trial_with_result(world.agents, "team:lab", None, "newlab", {"x": 2}, "failed", {}, ts=t)
    b = R.add_trial_with_result(world.agents, ROOM, S, "test", {"y": 1}, "no_data", {}, ts=t)
    R.add_trial_result(world.agents, b, "failed", {}, ts=t + 2)          # a re-run after no data: one test
    world.store.alert(t, "WARN", "[RANDOM_1@15m] BUST: equity 0.00")    # a coin flip: not a strategy bust
    world.store.alert(t, "WARN", f"[{S}@1h] BUST: equity 0.00")
    world.store.commit()
    rep = DG.week_report(world.paper(), world.agents, SUNDAY)
    st = rep["staff"]
    assert (st["lab_tests"], st["lab_passed"], st["tests"], st["tests_passed"]) == (2, 1, 1, 0)
    assert [x["account"] for x in rep["busts"]] == [f"{S}@1h"]


def test_coerced_verdicts_are_neither_disagreements_nor_unreadable(world):
    world.losses()
    bad = {"headline": "반론", "objections": [], "verdict": "maybe"}
    world.tick(QueueRunner({SPEC: [analysis(NOTE)] * 2, "devils_advocate": [bad], "entry_timing": [
        {"headline": "e", "findings": [], "verdict": "agree", "suggestion": None}]}), kst(2026, 10, 7, 15, 0))
    by = {s["role"]: s for s in DG.staff_board(world.agents, kst(2026, 10, 7, 16, 0), 7)["staff"]}
    assert by["devils_advocate"]["turns"] == 1 and by["devils_advocate"]["unreadable"] == 0
    assert by["devils_advocate"]["verdicts"] == {}
    day = DG.day_digest(world.agents, "2026-10-07")
    assert day["meetings"][0]["challenge"] == "unreadable"


def test_recent_grades_come_from_the_grade_rows(world):
    p = {"metric": "win_rate", "timeframe": None, "direction": "above", "value": 0.5, "after_trades": 30}
    old = R.add_trial(world.agents, ROOM, S, "hypothesis", {"text": "오래된 가설", "prediction": p, "by": SPEC}, ts=1000)
    for k in range(450):                                          # many newer hypotheses
        R.add_trial(world.agents, ROOM, S, "hypothesis", {"text": f"새 가설 {k}"}, ts=2000 + k)
    R.add_trial_result(world.agents, old, "graded", {"status": "graded", "correct": True, "value": 0.6, "n": 30,
                                                     "prediction": p, "by": SPEC}, ts=5000)
    g = DG.staff_board(world.agents, 6000, 7)["recent_grades"]
    assert [(x["trial_id"], x["correct"], x["name"]) for x in g] == [(old, True, R.role_name(SPEC))]


def test_a_malformed_reply_never_voids_a_good_answer(world):
    given = {"role": "risk_officer", "turn": "team", "this_round": {"team:pnl_reviewer": {"role": "pnl_reviewer"}}}
    for stance in (["agree"], {"a": 1}, 3, None):
        assert RM.check_dialog({"responds_to": {"role": "pnl_reviewer", "stance": stance, "point": "x"}}, given) == {}
    assert RM.compose_ranking({"picked": []}, None, 16) == "🏆 순위 검토 · 16:00"
    assert "tf_split" in RM.CODE_ROOTS and "ranking" in RM.CODE_ROOTS and "market_move" in RM.CODE_ROOTS
    assert "tf_split" in RM.RoomsPolicy().paced_triggers


# ---------------------------------------------------------------- audit fixes (2026-10-03)
def test_ranking_review_hypotheses_go_to_the_ledger_and_are_graded_later(world):
    t = kst(2026, 10, 7, 14, 5)
    pol = RM.RoomsPolicy()
    pol.triggers.ranking_hour_kst = 14
    pol.triggers.fresh_run_min_trades = 0       # no trades in this world
    pred = {"metric": "win_rate", "timeframe": "15m", "direction": "above", "value": 0.5, "after_trades": 30}
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [],
            "hypotheses": [{"strategy": S, "text": "상위는 15분봉 추세장 롱 덕분", "how_to_confirm": "30건 뒤 승률",
                            "prediction": pred},
                           {"strategy": "NOPE", "text": "모르는 매매법"},
                           {"strategy": "V45_AMB", "text": "예측 없는 가설"}]}
    runner = QueueRunner({"performance": [team_answer("f")], "pnl_reviewer": [team_answer("p")],
                          "risk_officer": [team_answer("r")], "team_lead": [lead]})
    world.tick(runner, t, policy=pol)
    rows = R.trial_history(world.agents, kinds=("hypothesis",), limit=10)
    assert sorted((r["strategy"], bool((r["spec"] or {}).get("prediction"))) for r in rows) == [(S, True), ("V45_AMB", False)]
    mine = next(r for r in rows if r["strategy"] == S)
    assert mine["room_id"] == "team:review" and mine["spec"]["by"] == "team_lead"
    assert "hypotheses" in runner.calls[3]["system"]
    texts = [m["text"] for m in world.messages("team:review")]
    assert any("가설 #" in x and "채점할 예측" in x for x in texts)
    # other meetings do not record them
    assert RM.check_lead({**lead}, {})[0]["hypotheses"] and len(RM.check_lead({**lead}, {})[0]["hypotheses"]) == 2


def test_an_owner_post_in_the_lab_starts_the_back_off_over(world):
    from test_newlab_room import lab_policy  # noqa: F401  (same lab policy as the lab tests)
    pol = RM.RoomsPolicy()
    pol.triggers.research_every_ms = HOUR
    t0 = kst(2026, 10, 8, 1, 0)
    for k in range(3):                                            # three empty research meetings in a row
        world.agents.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, ended_ts, status, decision) "
                             "VALUES ('team:lab', 'research', '{}', ?, ?, 'done', '{\"candidates\": 0}')",
                             (t0 + k * HOUR, t0 + k * HOUR + 1))
    world.agents.commit()
    st = TR._Rooms(world.agents, t0 + 4 * HOUR, pol.triggers)
    assert TR.research_gap(st, HOUR) == 4 * HOUR
    world.agents.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, ended_ts, status) "
                         "VALUES ('team:lab', 'owner', '{}', ?, ?, 'done')", (t0 + 3 * HOUR, t0 + 3 * HOUR + 1))
    world.agents.commit()
    assert TR.research_gap(TR._Rooms(world.agents, t0 + 4 * HOUR, pol.triggers), HOUR) == HOUR


def test_weekly_report_carries_the_ghcoin_recorder(world, tmp_path):
    import json
    gdir = tmp_path / "ghcoin"
    gdir.mkdir()
    ev = []
    for k, (r, mr) in enumerate([(1.5, -1.0), (-1.0, 1.5), (1.5, -1.0)]):
        t = SUNDAY - (k + 1) * DAY
        cid = f"BTCUSDT-{t}-{k}"
        ev += [{"ev": "open", "id": cid, "sym": "BTCUSDT", "side": 1, "entry": 100, "sl": 99, "t": t, "cost_r": 0.1},
               {"ev": "open", "id": cid + "-m", "of": cid, "mirror": True, "sym": "BTCUSDT", "side": -1, "entry": 100,
                "sl": 101, "t": t, "cost_r": 0.1},
               {"ev": "close", "id": cid, "of": None, "sym": "BTCUSDT", "result": "win" if r > 0 else "loss", "r": r,
                "net_r": r - 0.1, "end": t + HOUR},
               {"ev": "close", "id": cid + "-m", "of": cid, "mirror": True, "sym": "BTCUSDT",
                "result": "win" if mr > 0 else "loss", "r": mr, "net_r": mr - 0.1, "end": t + HOUR}]
    (gdir / "calls.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ev))
    rep = DG.week_report(world.paper(), world.agents, SUNDAY, ghcoin_dir=str(gdir))
    assert rep["ghcoin"]["week"]["calls"] == 3 and rep["ghcoin"]["all"]["calls"] == 3
    assert "GH Coin 기록: 7일 3타점" in DG.compose_week(rep)
    assert DG.week_report(world.paper(), world.agents, SUNDAY, ghcoin_dir=str(tmp_path / "none"))["ghcoin"] is None


# ---------------------------------------------------------------- third review round
def test_a_busted_timeframe_never_makes_a_split_and_a_real_split_gets_the_meeting(world):
    for k in range(10):                                           # N17: 15m +600, 1h busted at about -4,990
        world.trade(f"{S}@15m", 60.0, TF_AT - (30 - k) * HOUR)
        world.trade(f"{S}@1h", -499.0, TF_AT - (20 - k) * HOUR)
        world.trade("V45_AMB@15m", 40.0, TF_AT - (30 - k) * HOUR)  # V45: a genuine split, less wide
        world.trade("V45_AMB@1h", -30.0, TF_AT - (20 - k) * HOUR)
    world.store.alert(TF_AT - 10 * HOUR, "WARN", f"[{S}@1h] BUST: bust: equity 9.00 below 10.00")
    world.store.commit()
    got = DG.tf_split(world.paper())
    n17 = next(r for r in got["strategies"] if r["strategy"] == S)
    assert n17["timeframes"]["1h"]["bust"] is True and n17["split"] is False and n17["worst_tf"] == "15m"
    assert got["split"] == ["V45_AMB"]
    pol = tf_policy()
    assert [d.room_id for d in TR.find_due(world.paper(), None, world.agents, None, TF_AT, pol.triggers)
            if d.trigger == "tf_split"] == ["strat:V45_AMB"]


def test_tf_split_does_not_read_the_trades_once_the_days_meetings_are_held(world, monkeypatch):
    split_trades(world)
    pol = tf_policy()
    reads = []
    monkeypatch.setattr(DG, "tf_split", lambda *a, **k: reads.append(1) or {"strategies": [], "split": []})
    TR.find_due(world.paper(), None, world.agents, None, TF_AT, pol.triggers)
    assert reads == [1]
    for k in range(pol.triggers.tf_split_per_day):
        world.agents.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, ended_ts, status) "
                             "VALUES (?, 'tf_split', '{}', ?, ?, 'done')", (f"strat:x{k}", TF_AT - MIN, TF_AT - 1))
    world.agents.commit()
    assert TR.find_due(world.paper(), None, world.agents, None, TF_AT, pol.triggers) == []
    assert reads == [1]                      # every closed trade is read only while a meeting can still open


def _week_ctx(world, now, notifier, paper=True, min_trades=0):
    pol = RM.RoomsPolicy(triggers=TR.TriggerPolicy(enabled=(), fresh_run_min_trades=min_trades), weekly_report_hour_kst=21)
    return RM.RoundContext(agents_conn=world.agents, paper_ro=world.paper() if paper else None, daily_ro=None,
                           inbox_ro=None, runner=None, lab=None, now_ms=now, policy=pol, notifier=notifier)


def test_weekly_report_without_paper3_says_why_and_waits_for_the_numbers(world):
    n = ListNotifier()
    rep = DG.week_report(None, world.agents, SUNDAY)
    assert rep["error"] and "(거래 기록을 읽지 못함: paper3.db를 열지 못함)" in DG.compose_week(rep)
    assert RM.weekly_report_tick(_week_ctx(world, SUNDAY, n, paper=False)) is False and n.messages == []
    assert RM.weekly_report_tick(_week_ctx(world, SUNDAY + 15 * MIN, n)) is True       # readable again: sent
    assert len(n.messages) == 1 and "읽지 못함" not in n.messages[0][1]
    assert RM.weekly_report_tick(_week_ctx(world, SUNDAY + 30 * MIN, n)) is None and len(n.messages) == 1
    # unreadable for the whole run of tries: the last try sends the report with the reason
    n2, nxt = ListNotifier(), SUNDAY + 7 * DAY
    for k in range(RM.WEEKLY_REPORT_TRIES + 2):
        RM.weekly_report_tick(_week_ctx(world, nxt + k * 15 * MIN, n2, paper=False))
    assert len(n2.messages) == 1 and "paper3.db를 열지 못함" in n2.messages[0][1]


@pytest.mark.parametrize("first, step", [(4 * HOUR, 15 * MIN), (0, 35 * MIN)])   # restarted at 01:05; slow ticks
def test_unreadable_numbers_still_send_the_week_with_fewer_ticks(world, first, step):
    """Fewer than WEEKLY_REPORT_TRIES ticks in the 6-hour window: the second half sends the report with its
    reason instead of waiting for a try that never comes."""
    n, t = ListNotifier(), SUNDAY + first
    while RM.weekly_report_due(_week_ctx(world, t, n).policy, t):
        RM.weekly_report_tick(_week_ctx(world, t, n, paper=False))
        t += step
    assert len(n.messages) == 1 and "paper3.db를 열지 못함" in n.messages[0][1]


def test_a_two_hour_telegram_outage_still_delivers_the_week_once(world):
    class Down(ListNotifier):
        up = False

        def send(self, level, text):
            if not self.up:
                return False
            return super().send(level, text)
    n = Down()
    for k in range(8):                                            # 21:05 .. 22:50: Telegram refuses
        assert RM.weekly_report_tick(_week_ctx(world, SUNDAY + k * 15 * MIN, n)) is False
    n.up = True
    assert RM.weekly_report_tick(_week_ctx(world, SUNDAY + 8 * 15 * MIN, n)) is True
    assert RM.weekly_report_tick(_week_ctx(world, SUNDAY + 9 * 15 * MIN, n)) is None and len(n.messages) == 1


def test_the_second_week_has_no_partial_previous_week(tmp_path):
    w = World(tmp_path, start=kst(2026, 10, 2, 9, 0))              # the real start: 10/2 09:00 KST
    for k in range(3):
        w.trade(f"{S}@15m", -100.0, kst(2026, 10, 3, 12) + k * HOUR)    # in the 2.5 days before 10/4 21:05
        w.trade(f"{S}@15m", 50.0, SUNDAY - (k + 1) * DAY)
    rep = DG.week_report(w.paper(), w.agents, SUNDAY)
    assert rep["strategies_total_prev"]["trades"] == 0 and all(r["prev_rank"] is None for r in rep["top"])
    text = DG.compose_week(rep)
    assert "지난주" not in text and "▲" not in text and "▼" not in text
    # a later week (whole previous week inside the run) still compares
    w.trade(f"{S}@15m", 20.0, SUNDAY + 3 * DAY)
    assert DG.week_report(w.paper(), w.agents, SUNDAY + 7 * DAY)["strategies_total_prev"]["trades"] == 3


def test_fresh_run_without_trades_skips_the_sunday_report_and_says_why(world):
    """A fresh run (owners' restart 2026-10-04) with fewer than 10 closed strategy trades by the Sunday slot sends no
    report (nothing to report); the reason stays in meetings:skipped for that week. Decided as of the slot."""
    assert TR.TriggerPolicy().fresh_run_min_trades == 10
    n = ListNotifier()
    ctx = _week_ctx(world, SUNDAY, n, min_trades=10)
    assert RM.weekly_report_tick(ctx) is None and n.messages == []
    got = RM.store_skipped(world.agents, world.paper(), SUNDAY, ctx.policy)["weekly_report"]
    assert got["slot"] == "2026-10-11" and got["ok"] is False and got["trades"] == 0 and got["need"] == 10
    assert "새 실행 시작 뒤 매매법 계좌의 끝난 거래 0건(최소 10건)" == got["why"]
    assert R.get_cursor(world.agents, TR.SKIPPED_CURSOR)["weekly_report"] == got
    assert RM.weekly_report_skip(ctx.policy, world.paper(), SUNDAY + 3 * DAY)["slot"] == "2026-10-11"   # all week
    for k in range(10):                                   # closed after the slot: this week's answer stays
        world.trade(f"{S}@15m", 5.0, SUNDAY + k * MIN)
    assert RM.weekly_report_tick(_week_ctx(world, SUNDAY + HOUR, n, min_trades=10)) is None and n.messages == []
    assert RM.weekly_report_skip(ctx.policy, world.paper(), SUNDAY + 7 * DAY) is None                  # next week
    assert RM.weekly_report_tick(_week_ctx(world, SUNDAY + 7 * DAY, n, min_trades=10)) is True
    assert len(n.messages) == 1 and n.messages[0][1].startswith("📊 주간 성적표")
