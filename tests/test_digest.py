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
    runner = QueueRunner({SPEC: [analysis(NOTE)], "devils_advocate": [challenge("agree")]})
    out = world.tick(runner, TF_AT, policy=pol)
    assert [(r["room_id"], r["trigger"], r["status"]) for r in out["rounds"]] == [(ROOM, "tf_split", "done")]
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
    first = {**team_answer("p"), "ask_next": "하위 3개의 손실이 박스권에 몰렸나요?"}
    second = {**team_answer("r"), "responds_to": {"role": "pnl_reviewer", "stance": "disagree",
                                                  "point": "비용이 더 커 보임"}}
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [], "open_disagreement": "장세 vs 비용"}
    world.tick(QueueRunner({"pnl_reviewer": [first], "risk_officer": [second], "team_lead": [lead]}), t, policy=pol)
    world.losses(t=t + HOUR)
    world.tick(QueueRunner({SPEC: ["not json", "not json"]}), t + HOUR)
    return t


def test_day_digest_lists_every_meeting_with_replies_and_lead_lines(world):
    t = _two_meetings(world)
    d = DG.day_digest(world.agents, R.kst_day(t))
    assert d["n"] == 2 and d["disagreements"] == 1
    m = d["meetings"][0]
    assert (m["room_id"], m["trigger"], m["trigger_ko"], m["status"]) == ("team:review", "ranking", "순위 검토", "done")
    assert [s["role"] for s in m["speakers"]] == ["pnl_reviewer", "risk_officer", "team_lead"]
    assert m["replies"] == [{"from": "risk_officer", "from_name": R.role_name("risk_officer"), "to": "pnl_reviewer",
                             "to_name": R.role_name("pnl_reviewer"), "stance": "disagree", "point": "비용이 더 커 보임"}]
    assert m["asks"][0]["text"].startswith("하위 3개") and m["lead"] == ["a", "b", "c"]
    assert m["open_disagreement"] == "장세 vs 비용" and m["calls"] == 3
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
    assert text.startswith("📊 주간 성적표 (10/11") and "+$80" in text and "▲1" in text and "파산 1개" in text
    assert "체크포인트" in text and len(text) <= 4000


def test_weekly_report_goes_out_on_sunday_once_and_retries_a_refused_send(world):
    pol = RM.RoomsPolicy(triggers=TR.TriggerPolicy(enabled=()), weekly_report_hour_kst=21)
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
    for k in range(5):
        world.tick(QueueRunner({}), nxt + k * 15 * MIN, policy=pol, notifier=bad)
    assert len(bad.messages) == RM.WEEKLY_REPORT_TRIES and R.get_cursor(world.agents, "telegram:weekly_report:2026-10-18") is None


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
