"""Agent rooms: regression tests from the third review round.

The 30-day verdict the staff read (checkpoint.db, not the old 3-coin-flip check), the owners' Telegram for a
copy proposal and for staff that stopped meeting, the reason line of a paced stop, and the Sunday report.
"""

import json

import pytest

from paperbot import checkpoint as CP
from paperbot.agents import actions as A
from paperbot.agents import packets3 as P3
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.agents import triggers as TR
from paperbot.notify import WARN, ListNotifier
from test_rooms import (DAY, HOUR, MIN, QUIET, ROOM, S, SPEC, START, TEST, QueueRunner, StubLab, World,  # noqa: F401
                        analysis, challenge, expert, team_answer)

DAY30 = START + 30 * DAY + HOUR                 # 2026-10-20 15:00 KST: only the day-30 checkpoint is due
LEAD = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}


def write_verdict(path, date, accounts):
    """A stored checkpoint verdict (the checkpoint job's table) with these account rows."""
    out = CP.open_out(path)
    counts = {k: sum(1 for r in accounts.values() if r["status"] == k) for k in CP.STATUSES}
    v = {"date": date, "cp_ts": CP.day_ms(date), "day": 30, "snapshot_sha256": "ab" * 32, "alpha": 0.1,
         "n_bots": 2000, "initial_equity": 5000.0, "groups": [], "warnings": [], "accounts": accounts,
         "tested": len(accounts), "luck_passed": counts[CP.PASS1], "lucky_expected": 0.1,
         "lucky_if_uncorrected": 0.4, "counts": counts, "text": "x"}
    out.execute("INSERT INTO verdicts VALUES (?,?,?,?)", (date, CP.day_ms(date), v["snapshot_sha256"], json.dumps(v)))
    out.commit()
    out.close()


def row(status, p, tf="15m"):
    return {"status": status, "stage": "1차", "timeframe": tf, "trades": 40, "equity": 5600.0, "pnl": 600.0,
            "p": p, "q": p * 2, "reason": "r"}


# ------------------------------------------------------------------ the 30-day verdict
def test_checkpoint_meeting_waits_for_the_verdict_and_the_staff_read_it(tmp_path):
    w = World(tmp_path)
    cpdb = str(tmp_path / "checkpoint.db")                  # next to paper3.db: where the checkpoint job writes
    assert RM.checkpoint_path(w.paths["paper"]) == cpdb
    # before the verdict is stored, the day-30 meeting does not open (it would discuss a guess)
    assert [r["trigger"] for r in w.tick(QueueRunner({}), DAY30)["rounds"]] == []
    write_verdict(cpdb, "2026-10-20", {"N17_KC_RSI@15m": row(CP.PASS1, 0.004), "N17_KC_RSI@1h": row(CP.FAIL, 0.6, "1h"),
                                       "V45_AMB@15m": row(CP.FAIL, 0.08), "V45_AMB@1h": row(CP.FAIL, 0.5, "1h")})
    runner = QueueRunner({"league_referee": [team_answer("ref")], "rule_keeper": [team_answer("rk")],
                          "team_lead": [LEAD]})
    out = w.tick(runner, DAY30 + 10 * MIN)
    assert [(r["room_id"], r["trigger"], r["status"]) for r in out["rounds"]] == [("team:lead", "checkpoint", "done")]
    ref = runner.calls[0]["packet"]["board"]
    cp = ref["checkpoint"]
    assert cp["ready"] and cp["date"] == "2026-10-20" and cp["counts"][CP.PASS1] == 1 and cp["next"] == "2026-11-19 09:00 KST"
    # only the passes and the accounts with p <= 0.10 (tokens), with the code's p and q
    assert [(r["account_id"], r["status"], r["p"]) for r in cp["rows"]] == [
        ("N17_KC_RSI@15m", CP.PASS1, 0.004), ("V45_AMB@15m", CP.FAIL, 0.08)]
    assert cp["rows_left_out"] == 2
    # the old 3-coin-flip check stays as a reference only: no 'first_pass' anywhere
    assert "first_pass" not in json.dumps(ref) and "참고용" in ref["pass_summary"]["note"]
    assert set(ref["pass_check"]["N17_KC_RSI@15m"]) >= {"status"} and \
        ref["pass_check"]["N17_KC_RSI@15m"]["status"] in ("small_sample", "above_3_coin_flips", "below")
    assert "checkpoint" in runner.calls[1]["packet"]["board"] and "checkpoint" in runner.calls[2]["packet"]["board"]
    # paper v4 (G18): the verdict method is the one text built from the checkpoint (agents/facts.method_ko)
    from paperbot.agents.facts import facts
    assert "board.checkpoint" in runner.calls[0]["system"] and facts()["method_ko"] in runner.calls[0]["system"]
    # the meeting is held once
    assert w.tick(QueueRunner({}), DAY30 + 30 * MIN)["rounds"] == []


def test_checkpoint_trigger_without_a_verdict_is_not_due(tmp_path):
    w = World(tmp_path)
    cpdb = str(tmp_path / "checkpoint.db")
    ro = R.open_ro(w.paths["paper"])
    try:
        due = lambda: [d for d in TR.find_due(ro, None, w.agents, None, DAY30, checkpoint_db=cpdb)  # noqa: E731
                       if d.trigger == "checkpoint"]
        assert due() == []                                   # no checkpoint.db yet
        write_verdict(cpdb, "2026-10-19", {})               # another day's verdict is not this one
        assert due() == []
        write_verdict(cpdb, "2026-10-20", {})
        [d] = due()
        assert d.data["verdict_date"] == "2026-10-20" and d.data["day"] == 30
    finally:
        ro.close()


def test_checkpoint_section_before_the_verdict_and_for_a_specialist():
    assert P3.checkpoint_section({"ready": False, "next": "2026-11-01 09:00 KST"}) == {
        "ready": False, "next": "2026-11-01 09:00 KST", "note": P3.checkpoint_section({"ready": False})["note"]}
    view = {"ready": True, "date": "2026-11-01", "rows": [
        {"account_id": "S1@15m", "status": CP.FAIL, "p": 0.9}, {"account_id": "S1@15m~c1", "status": CP.HOLD, "p": None},
        {"account_id": "S2@15m", "status": CP.PASS1, "p": 0.001}]}
    own = P3.checkpoint_section(view, "S1")
    assert [r["account_id"] for r in own["rows"]] == ["S1@15m", "S1@15m~c1"]          # all its own rows
    assert [r["account_id"] for r in P3.checkpoint_section(view)["rows"]] == ["S2@15m"]


def test_specialist_gets_its_own_checkpoint_rows(tmp_path):
    w = World(tmp_path)
    write_verdict(str(tmp_path / "checkpoint.db"), "2026-10-20",
                  {"N17_KC_RSI@15m": row(CP.FAIL, 0.7), "V45_AMB@15m": row(CP.PASS1, 0.001)})
    ctx = RM.RoundContext(agents_conn=w.agents, paper_ro=w.paper(), daily_ro=None, inbox_ro=None, runner=None,
                          lab=None, now_ms=DAY30, checkpoint_db=str(tmp_path / "checkpoint.db"))
    due = TR.Due("strat:N17_KC_RSI", "weekly", 4, {"summary_ko": "x"}, "weekly")
    rnd = RM._Round(due, ctx, 0, None, 6)
    base = RM._strategy_base(rnd)
    assert [r["account_id"] for r in base["specialist"]["checkpoint"]["rows"]] == ["N17_KC_RSI@15m"]
    ctx.paper_ro.close()


def test_roster_and_prompts_name_the_q1_verdict():
    from paperbot.agents.roster3 import ROLES, room_duty
    from paperbot.agents.facts import facts
    method = facts()["method_ko"]                  # paper v4 (G18): one verdict text, never a typed bot count
    assert method in room_duty("league_referee") and "참고용" in room_duty("league_referee")
    assert method in next(r[5] for r in ROLES if r[0] == "league_referee")
    assert "2,000" not in room_duty("league_referee")
    assert "board.checkpoint" in RM.system_prompt("league_referee", "team")
    assert "specialist.checkpoint" in RM.system_prompt("spec_N17_KC_RSI", "specialist")
    assert "pass_check.V45_AMB" not in RM.system_prompt("league_referee", "team")


# ------------------------------------------------------------------ a copy proposal waiting for the owners
@pytest.fixture
def good_lab(monkeypatch):
    lab = StubLab(good=True)
    monkeypatch.setattr(A, "_lab", lab)
    return lab


def test_a_copy_proposal_waiting_for_the_owners_sends_one_warn(tmp_path, good_lab):
    w = World(tmp_path)
    runner = QueueRunner({SPEC: [analysis(TEST), analysis(TEST, changes="그대로")],
                          "devils_advocate": [challenge("needs_test")], "entry_timing": [expert("needs_test")],
                          "validator": [{"pass_gate": True, "explanation": "두 기간 모두 개선"}],
                          "approver": [{"approve": True, "reason": "두 기간 모두 개선"}]})
    w.parent_trades()
    w.losses()
    tg = ListNotifier()
    w.tick(runner, QUIET, lab=object(), notifier=tg)
    [p] = R.list_proposals(w.agents)
    assert p["status"] == "awaiting_owner"
    [(level, text)] = tg.messages                      # the round itself sends nothing else
    assert level == WARN and text.startswith(f"승인 요청 · 복제 계좌 제안 #{p['id']}\n") and "\n원본: 켈트너·RSI 15분\n" in text
    assert "'추세 반대 진입' 진입 건너뛰기" in text and "5년 시험 통과 (시험 #" in text and "승인/거절" in text
    assert any(m["kind"] == "action" and "알림(텔레그램, WARN)" in m["text"] for m in w.messages())
    # never twice for the same proposal (the mark is written before the send)
    env = A.ActionEnv(conn=w.agents, room_id=ROOM, strategy=S, round_id=None, meeting="x", now_ms=QUIET, notifier=tg)
    assert RM.copy_alert(env, {"proposal_id": p["id"], "status": "awaiting_owner"}) is False
    assert len(tg.messages) == 1


def test_a_refused_copy_alert_says_so_in_the_room(tmp_path):
    w = World(tmp_path)

    class Refuses(ListNotifier):
        def send(self, level, text):
            return False
    env = A.ActionEnv(conn=w.agents, room_id=ROOM, strategy=S, round_id=None, meeting="x", now_ms=QUIET,
                      notifier=Refuses())
    assert RM.copy_alert(env, {"proposal_id": 7, "status": "awaiting_owner", "trial_id": 3}) is False
    assert "복제 제안 알림 전송 실패" in w.messages()[-1]["text"]


# ------------------------------------------------------------------ the staff stopped meeting
class Down:
    """A runner that never answers (the claude binary is gone): every meeting fails 'transient'."""

    def __init__(self):
        self.calls = 0

    def call(self, model, system_prompt, instruction, packet):
        self.calls += 1
        raise FileNotFoundError("claude")


def test_a_streak_of_runner_failures_sends_one_warn_a_day(tmp_path):
    w = World(tmp_path)
    w.say("team:lead", "질문", QUIET - 10 * MIN)
    tg, runner = ListNotifier(), Down()
    t = QUIET
    for gap in (0, 10, 20, 40):                      # the growing back-off: the same meeting fails 4 times in a row
        t += gap * MIN
        out = w.tick(runner, t, notifier=tg)
        assert [(r["status"], r["stopped"]) for r in out["rounds"]] == [("failed", "runner_error")], gap
        assert (len(tg.messages) == 1) == (gap == 40)
    level, text = tg.messages[0]
    assert level == WARN and "4번 연속 실패" in text and "FileNotFoundError" in text and "8-2·8-4" in text
    assert R.get_cursor(w.agents, RM.DOWN_CURSOR + R.kst_day(t)) is not None
    w.tick(runner, t + 80 * MIN, notifier=tg)                    # still down later the same day: no second WARN
    assert runner.calls == 5 and len(tg.messages) == 1


def test_the_down_warn_on_the_15_minute_timer_comes_after_90_minutes(tmp_path):
    w = World(tmp_path)
    w.say("team:lead", "질문", QUIET - 10 * MIN)
    tg, runner = ListNotifier(), Down()
    for k in range(8):                                            # every 15 minutes; the back-off skips some ticks
        w.tick(runner, QUIET + k * 15 * MIN, notifier=tg)
        if tg.messages:
            break
    assert k * 15 == 90 and runner.calls == RM.DOWN_ROUNDS
    assert tg.messages[0][1].startswith("직원 회의 멈춤 · 90분째\n\n회의 4번 연속 실패")


def test_no_down_warn_when_a_call_answered_during_the_streak(tmp_path):
    w = World(tmp_path)
    for k in range(RM.DOWN_ROUNDS):
        d = TR.Due("team:lead", "owner", 1, {"key": f"k{k}", "class": "owner"}, "owner")
        rid = TR.begin_round(w.agents, d, QUIET - (5 - k) * HOUR)
        TR.finish_round(w.agents, rid, "failed", QUIET - (5 - k) * HOUR + MIN,
                        {"transient": True, "error": "AgentCallError: timeout"}, 1, 0)
    w.agents.execute("INSERT INTO agent_calls VALUES (?,?,?,?,?,?,?)",
                     (QUIET - 2 * HOUR, R.kst_day(QUIET), "owner", "team_lead", "sonnet", 1, 1000))
    w.agents.commit()
    ctx = RM.RoundContext(agents_conn=w.agents, paper_ro=None, daily_ro=None, inbox_ro=None, runner=None, lab=None,
                          now_ms=QUIET, notifier=ListNotifier())
    assert RM.down_streak(w.agents)[0] == RM.DOWN_ROUNDS
    assert RM.check_runner_down(ctx) is False and ctx.notifier.messages == []
    w.agents.execute("DELETE FROM agent_calls")
    assert RM.check_runner_down(ctx) is True and len(ctx.notifier.messages) == 1


def test_a_refused_login_sends_one_warn_not_two(tmp_path, monkeypatch):
    """The pass exits 2 and the unit's OnFailure alert (paperbot.failalert) names the login refusal: the
    tick itself sends nothing more for it."""
    from paperbot import failalert as FA
    w = World(tmp_path)
    w.say("team:lead", "질문", QUIET - 10 * MIN)
    tg = ListNotifier()
    monkeypatch.setattr(RM, "AUTH_PREFLIGHT", lambda claude_bin: (False, "ANTHROPIC_API_KEY is set"))
    monkeypatch.setattr(RM, "_notifier", lambda: tg)
    rc = RM.main(["tick", "--paper-db", w.paths["paper"], "--daily-db", w.paths["daily"],
                  "--agents-db", w.paths["agents"], "--inbox-db", w.paths["inbox"]])
    assert rc == 2 and tg.messages == [] and R.get_cursor(w.agents, "tick:last")["why"] == "login"
    FA.main(["paperbot-agents.service"], env={"MONITOR_SERVICE_RESULT": "exit-code", "MONITOR_EXIT_STATUS": "2"},
            notifier=tg, state_dir=str(tmp_path / "failalert"))
    [(level, text)] = tg.messages
    assert level == WARN and "로그인" in text


def test_evening_numbers_say_the_coin_flips_are_in_the_pnl(tmp_path):
    w = World(tmp_path)
    ctx = RM.RoundContext(agents_conn=w.agents, paper_ro=None, daily_ro=None, inbox_ro=None, runner=None, lab=None,
                          now_ms=QUIET)
    text = RM.compose_evening(ctx, {"today": {"trades": 3, "net_pnl": -12.5, "wins": 1, "busts_total": 0}}, LEAD)
    assert "\n매매법 거래 3건 · 이긴 1건 · -$12 (동전 봇 포함)\n" in text


# ------------------------------------------------------------------ the reason line of a paced stop
def test_a_paced_stop_names_the_day_or_7_day_total_and_shows_its_tokens(tmp_path):
    w = World(tmp_path)
    # today: 1,149,000 tokens used of the old 2,000,000 total; the rest is kept: a weekly review stops there
    w.agents.execute("INSERT INTO agent_calls VALUES (?,?,?,?,?,?,?)",
                     (QUIET - HOUR, R.kst_day(QUIET), "owner", "x", "sonnet", 1, 1_149_000))
    w.agents.commit()
    caps = {"budgets": {**RM.DEFAULT_BUDGETS, "loss": (24, 700_000), "scheduled": (15, 450_000)},
            "total_budget": (80, 2_000_000), "week_budget": (420, 10_000_000)}
    ctx = RM.RoundContext(w.agents, None, None, None, QueueRunner({}), None, QUIET, policy=RM.RoomsPolicy(**caps),
                          clock_ms=lambda: QUIET)
    due = TR.Due(ROOM, "weekly", 4, {"class": "weekly"}, "weekly")
    with pytest.raises(RM.PacedKeepExceeded) as ei:
        RM.round_budget(due, ctx).check(0)
    detail = str(ei.value)
    assert "1,149,000/2,000,000 tokens" in detail                     # the token side, not only the calls
    why = RM.limit_why_ko(RM.stop_kind(ei.value), "weekly", detail)
    assert why.startswith("하루 전체 합계 중 두 분 글·파산·정기 회의 몫으로 남겨 둔 부분")
    assert "토큰 115만/200만" in why and "'주간" not in why              # not the class's own (40-call) share
    week = RM.limit_why_ko("budget_subcap", "weekly", "7-day cap: 560/1100 calls used, 9,000,000/10,000,000 tokens "
                                                      "used, the rest is kept for incidents")
    assert week.startswith("최근 7일 합계 중") and "호출 560/1100번" in week and "토큰 900만/1,000만" in week
    # a real sub-cap (the class minus its reserve) keeps its own wording
    assert RM.limit_why_ko("budget_subcap", "loss", "daily cap of loss (without its reserve): 39/40 calls").startswith(
        "'손실·파산 복기' 몫 중")
