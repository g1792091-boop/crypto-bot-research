"""실거래 분석 팀 (paperbot/liveteam.py): when a meeting is due, what the members read, the order they speak in, what is
kept (messages, the lead's conclusion, ideas, usage), the budget that holds a meeting back, a member's failure, a plan
limit, the quiet week, and that no member is ever given a way to act (no tools, the fixed rules in every prompt).
The AI is FakeRunner (paperbot/agents/runner.py); the facts come from the hand-made live world (tests/livebots_world.py)."""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot import liveteam as T  # noqa: E402
from paperbot.agents import runner as R  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402

NOW = W.NOW
DAY, H = T.DAY, T.HOUR


class Note:
    def __init__(self):
        self.sent = []

    def send(self, level, text):
        self.sent.append((level, text))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    L._cache.clear()
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    yield


@pytest.fixture
def src(tmp_path, monkeypatch):
    d = str(tmp_path / "w")
    p = W.build_world(d)
    m = W.live_checks(p, d, rich=True)
    for k, v in {**W.env_of(p), **W.env_more_of(m)}.items():
        monkeypatch.setenv(k, v)
    return T.sources(NOW, p)


@pytest.fixture
def conn(tmp_path):
    c = T.connect(str(tmp_path / "team" / "liveteam.db"))
    yield c
    c.close()


LEAD = {"headline": "페이퍼 48번 중 31번 이김, 현실 범위 아래쪽", "verdict": "주의", "summary": ["하나", "둘", "셋"],
        "good": ["MEXC는 3번 모두 이김"], "worries": ["F4_FAN 10번 중 1번"], "watch_next": ["다음 20번"],
        "ideas": [{"idea": f"아이디어 {i}", "why": "숫자", "test": "2020-24로 고르고 2025-26 확인"} for i in range(5)]}


def fake(**over):
    answers = {"risk": {"headline": "리스크 한 줄", "points": ["바이비트 -8.35"], "worry": "MEXC 멈춤", "luck": "아직 우연이 큼"},
               "stats": {"headline": "통계 한 줄", "points": ["48번 중 31번"], "worry": None, "luck": "p=0.07"},
               "market": {"headline": "시장 한 줄", "points": ["횡보 8번"], "worry": None, "luck": "작음"}, "lead": LEAD}
    answers.update(over.pop("answers", {}))
    return R.FakeRunner(answers=answers, **over)


# ---------------------------------------------------------------- when
def test_budget_and_week_helpers():
    assert T.parse_budget(None) == T.BUDGET_DEFAULT
    assert T.parse_budget("day=3, week=9") == {**T.BUDGET_DEFAULT, "day": 3, "week": 9}
    for bad in ("day=x", "hour=3", "day"):
        with pytest.raises(ValueError):
            T.parse_budget(bad)
    m9 = T.monday_09(NOW)                                   # NOW = Monday 2026-10-19 19:00 KST
    assert m9 == W.T0 and T.monday_09(W.T0 + 6 * DAY + 14 * H) == W.T0       # Sunday 23:00 KST: still that week
    assert T.monday_09(W.T0 + 7 * DAY - 9 * H) == W.T0 + 7 * DAY             # next Monday 00:00 KST: the next week


def test_what_is_due_on_the_rich_world(src, conn):
    assert T.due_checkpoint(src) == ("checkpoint:40", {"paper_closed": 48, "milestone": 40, "last_k_wins": 25, "last_k_rate": 0.625})
    assert T.due_weekly(src) == ("weekly:2026-10-19", {"window": [W.T0 - 7 * DAY, W.T0]})
    early = {**src, "now": W.T0 + 30 * T.MIN}                                # Monday 09:30 KST: not yet
    assert T.due_weekly(early) is None
    assert [k for k, _key, _f in T.due(conn, src)] == ["checkpoint", "weekly"]


def test_a_losing_pair_of_a_live_executor_is_due_once(src):
    t = lambda key, pid, pnl, x: {"key": key, "exit_time": x, "pnl": pnl, "symbol": "ETHUSDT", "side": 1, "roe": pnl / 4,  # noqa: E731
                                  "paper": {"id": pid, "roe": -0.1}, "strategy_id": "N03_ADX_GC", "timeframe": "15m", "reason_ko": "손절"}
    rows = [t("a", 1, 2.0, NOW - 5 * H), t("b", 2, -3.0, NOW - 3 * H), t("c", 3, -1.0, NOW - H)]
    s = {"now": NOW, "trades": {"accts": {"bybit": {"rows": rows}, "mexc": {"rows": [rows[1], rows[2]]}}}}
    key, focus = T.due_loss(s)
    assert key == "loss:2+3" and focus["executor"] == "bybit" and [x["pnl"] for x in focus["losses"]] == [-3.0, -1.0]
    assert T.due_loss({**s, "now": NOW + 4 * DAY}) is None                  # an old pair when the team is turned on
    rows[2]["pnl"] = 0.5
    assert T.due_loss({"now": NOW, "trades": {"accts": {"bybit": {"rows": rows}}}}) is None


# ---------------------------------------------------------------- what they read
def test_the_packet_is_facts_only(src):
    pk = T.packet_for(src, "weekly", {"window": [NOW - 7 * DAY, NOW]})
    s = json.dumps(pk, ensure_ascii=False)
    # the rules as this world's configs say them (its paper bot ran the A+C config; its executors had the light and halts)
    rules = pk["fixed_rules"]
    assert rules == T.fixed_rules(src["bot"]["config"], src["bot"]["infos"]) and rules != list(T.FIXED)
    assert "증거금 잔고의 40%" in rules and "손절 3 ATR(안 맞으면 강제청산 안쪽으로 당김)" in rules
    assert any(r.startswith("3연패 멈춤 · 최고점에서 50% 빠지면 멈춤 · 비상 정지 파일") for r in rules)
    assert pk["bot"]["name"] == "A+C 합본" and pk["checkpoint_rule"] == T.CHECK_RULE_OLD
    assert pk["expect"]["honest_win"] == 0.7497 and pk["expect"]["fit_win"] == 0.9132
    kinds = {a["id"]: a["kind"] for a in pk["accounts"]}
    assert kinds == {"paper": "페이퍼(연습)", "bybit": "실거래(진짜 돈)", "mexc": "실거래(진짜 돈)"}
    assert pk["trades"] and all(set(t) >= {"coin", "side", "strategy", "roe", "exit", "live"} for t in pk["trades"])
    assert pk["loss_cards"] and {c["label"] for c in pk["loss_cards"]} and pk["costs"]["bybit"]["matched"] == 17
    assert any(x["strategy"] == "F4_FAN" and x["status"] == "확실히 나쁨" for x in pk["strategies"])
    for secret in ("TELEGRAM", "API_KEY", "SECRET", "executor.env", "OAUTH"):
        assert secret not in s, secret
    assert len(s) < 60_000


def test_every_prompt_keeps_the_team_off_the_controls():
    for role in T.ROLES:
        sp = T.system_prompt(role)
        assert "매매 권한이 없습니다" in sp and "고정 규칙" in sp and "패킷(JSON)에 있는 숫자만" in sp and "JSON 하나만" in sp
        assert f"{T.SMALL_N}번보다 적으면" in sp and "fit(맞춘 숫자, 낙관)" in sp
        assert "5년 기준표가 있을 때만" in sp and "지난 봇 숫자를 빌려 오지 않고" in sp
        assert "75%" not in sp and "91%" not in sp                    # no other bot's 5-year numbers in a prompt
    assert "시험해 볼 가설" in T.system_prompt("lead") and "ideas" in T.system_prompt("lead")
    assert '"--tools", ""' in open(R.__file__, encoding="utf-8").read()          # the runner gives no tool at all


# ---------------------------------------------------------------- a meeting
def test_a_meeting_speaks_in_order_and_keeps_everything(src, conn):
    run, note = fake(), Note()
    out = T.tick(conn, src, run, T.BUDGET_DEFAULT, notifier=note)
    assert out["state"] == "done" and out["key"] == "checkpoint:40" and out["calls"] == 4
    assert [c["role"] for c in run.calls] == ["risk", "stats", "market", "lead"]
    team = run.calls[-1]["packet"]["team"]
    assert [t["who"] for t in team] == ["방패(리스크 담당)", "저울(통계 담당)", "나침반(시장 담당)"] and "리스크 한 줄" in team[0]["text"]
    assert run.calls[0]["packet"]["facts"]["focus"]["milestone"] == 40
    m = conn.execute("SELECT state, headline, verdict, sent, calls FROM meetings").fetchone()
    assert m == ("done", LEAD["headline"], "주의", 1, 4)
    msgs = conn.execute("SELECT role, text, error FROM messages ORDER BY seq").fetchall()
    assert [r[0] for r in msgs] == ["risk", "stats", "market", "lead"] and all(r[2] is None for r in msgs)
    assert "걱정: MEXC 멈춤" in msgs[0][1] and msgs[3][1].startswith(LEAD["headline"])
    ideas = conn.execute("SELECT idea, status FROM ideas").fetchall()
    assert len(ideas) == T.IDEAS_MAX and all(s == "제안" for _i, s in ideas)
    assert conn.execute("SELECT SUM(calls) FROM usage").fetchone()[0] == 4
    (level, text), = note.sent
    assert level == "INFO" and text.startswith("🧭 [실거래 분석팀] 판단 회의 🟠 주의") and "결정은 두 분" in text and T.DASH_HINT in text
    nxt = T.tick(conn, src, fake(), T.BUDGET_DEFAULT)                       # the same checkpoint is never held twice
    assert nxt["key"] == "weekly:2026-10-19"


def test_the_quiet_week_and_the_budget(src, conn):
    paper = src["trades"]["accts"]["paper"]
    later = [r for r in paper["rows"] if r["exit_time"] >= W.T0]          # the rich world's four days before T0 left out
    early = {**src, "trades": {**src["trades"], "accts": {**src["trades"]["accts"], "paper": {**paper, "rows": later}}}}
    conn.execute("INSERT INTO meetings (kind, key, title, started_ts, state) VALUES ('checkpoint','checkpoint:40','x',0,'done')")
    out = T.tick(conn, early, fake(), T.BUDGET_DEFAULT)                      # the week before T0: no closed trade
    assert out == {"state": "quiet", "key": "weekly:2026-10-19", "why": "지난주 닫힌 거래가 없어 AI 회의 없이 넘어갑니다"}
    conn2 = T.connect(os.path.join(os.path.dirname(conn.execute("PRAGMA database_list").fetchone()[2]), "b.db"))
    run = fake()
    held = T.tick(conn2, src, run, {**T.BUDGET_DEFAULT, "day": 3})          # 4 calls do not fit 3
    assert held["state"] == "deferred" and "오늘 AI 호출 한도(3번)" in held["why"] and run.calls == []
    assert conn2.execute("SELECT COUNT(*) FROM meetings").fetchone()[0] == 0
    conn2.close()


def test_a_member_who_fails_and_a_plan_limit(src, conn):
    run = fake(fail={"stats": R.AgentCallError("exit 1: boom")})
    out = T.tick(conn, src, run, T.BUDGET_DEFAULT)
    assert out["state"] == "done" and [c["role"] for c in run.calls] == ["risk", "stats", "market", "lead"]
    err = conn.execute("SELECT text, error FROM messages WHERE role = 'stats'").fetchone()
    assert "(답 없음" in err[0] and "boom" in err[1]
    assert [t["who"] for t in run.calls[-1]["packet"]["team"]] == ["방패(리스크 담당)", "나침반(시장 담당)"]
    run2 = fake(fail={"risk": R.UsageLimitReached("5-hour limit reached")})
    out2 = T.tick(conn, src, run2, T.BUDGET_DEFAULT)
    assert out2["state"] == "failed" and "AI 사용 한도" in out2["why"] and [c["role"] for c in run2.calls] == ["risk"]


def test_the_leads_answer_is_kept_in_shape():
    r = T.lead_result({"headline": "x" * 900, "verdict": "매수", "summary": "한 줄", "ideas": [{"idea": ""}, {"idea": "가", "why": 1}]})
    assert len(r["headline"]) == T.TEXT_MAX and r["verdict"] == "지켜보기" and r["summary"] == ["한 줄"]
    assert r["ideas"] == [{"idea": "가", "why": "1", "test": ""}]
    assert T.lead_result(None)["headline"] == "(팀장 결론 없음)"


def test_status_and_the_command_line(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "t.db")
    assert T.main(["--db", db, "status"]) == 0
    assert "AI 사용: 오늘 0/12번" in capsys.readouterr().out
    monkeypatch.setenv(T.BUDGET_ENV, "day=zero")
    assert T.main(["--db", db, "status"]) == 2


# ---------------------------------------------------------------- 규칙봇 15 (from 10-20): the facts follow the running configs
def test_the_packet_describes_the_running_bot_live15(monkeypatch):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", os.path.join(root, "deploy", "combo.live15.json"))
    p = {"paper": "/nonexistent/live-ac.db", "bybit_db": "/nonexistent/b.db", "mexc_db": "/nonexistent/m.db",
         "bybit_config": os.path.join(root, "deploy", "executor.live-bybit.json"),
         "mexc_config": os.path.join(root, "deploy", "executor.live-mexc.json")}
    world = T.bot_world(p)
    assert world["ref_ko"]                                          # the A+C 5-year reference is another config's
    src = {"now": NOW, "bot": world}
    pk = T.facts(src, "weekly", window=(NOW - 7 * DAY, NOW))
    rules = pk["fixed_rules"]
    assert rules[:9] == ["매매법 15개", "BTC 40배 · 나머지 30배", "증거금 잔고의 40%", "한 번에 포지션 하나", "시장가 진입",
                         "손절 순ROE -50%(수수료·슬리피지 포함: 40배 가격 1.11%, 30배 가격 1.53%)",
                         "계단 익절(순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, 그 뒤 5%마다 (닿은 순ROE - 3%))",
                         "빠른 청산: 같은 매매법이 반대 신호를 내면 바로 청산(첫 잠금 전까지만)",
                         "추격 진입 막기 4개 매매법(롱은 7일 범위 위 20%·24시간 고점 쪽 10% 안이면, 숏은 아래쪽이면 진입 안 함)"]
    for r in ("나스닥 개장 뒤 30분 진입 없음", "연패·낙폭으로 저절로 멈추지 않음(비상 정지 파일 /var/lib/paperbot/STOP으로만 멈춤)",
              "손절 한 번 최대 잔고의 35%", "신호등 없음(실거래는 페이퍼의 모든 진입을 따라감)", "실거래 금액 바이비트 $100 · MEXC $100"):
        assert r in rules, r
    text = json.dumps(pk, ensure_ascii=False)
    for old in ("3연패", "50% 빠지면", "낙폭 50%", "3%씩", "3 ATR", "A+C", "신호등:", "88% 이상", "82~88%"):
        assert old not in text, old
    assert pk["checkpoint_rule"] == T.CHECK_RULE_NONE and pk["bot"]["name"] == "규칙봇 15"
    assert pk["bot"]["break_even"] == 0.833 and "58승 4패" in pk["bot"]["start_basis"]
    assert pk["expect"]["words"].startswith(world["ref_ko"]) and "5년 숫자(fit·honest)가 없습니다" in pk["expect"]["words"]
    rows = [{"key": k, "exit_time": NOW - (3 - i) * H, "pnl": -2.0, "symbol": "ETHUSDT", "side": 1, "roe": -0.5,
             "paper": {"id": i}, "strategy_id": "F3_BOS", "timeframe": "30m", "reason_ko": "손절"} for i, k in enumerate("ab")]
    _key, focus = T.due_loss({"now": NOW, "bot": world, "trades": {"accts": {"bybit": {"rows": rows}}}})
    assert focus["how_rare"] == T.HOW_RARE_NONE
    # a config that cannot be read: the owners' 10-19 decisions
    assert T.fixed_rules(None, None) == list(T.FIXED) and "신호등 없음(실거래는 페이퍼의 모든 진입을 따라감)" in T.FIXED
