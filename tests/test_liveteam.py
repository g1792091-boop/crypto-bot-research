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


# ---------------------------------------------------------------- the running bot's config: 규칙봇 15 (10-20), 추세판단 봇 (10-21)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXEC_RULES = ("연패·낙폭으로 저절로 멈추지 않음(비상 정지 파일 /var/lib/paperbot/STOP으로만 멈춤)", "손절 한 번 최대 잔고의 35%",
              "신호등 없음(실거래는 페이퍼의 모든 진입을 따라감)", "실거래 금액 바이비트 $100 · MEXC $100")


def _config_world(monkeypatch, name: str) -> tuple:
    """bot_world on the deploy config ``name`` (no paper database: the config file is the running config) and both
    deploy executor configs; (world, the config as JSON)."""
    path = os.path.join(ROOT, "deploy", name)
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", path)
    p = {"paper": "/nonexistent/live-ac.db", "bybit_db": "/nonexistent/b.db", "mexc_db": "/nonexistent/m.db",
         "bybit_config": os.path.join(ROOT, "deploy", "executor.live-bybit.json"),
         "mexc_config": os.path.join(ROOT, "deploy", "executor.live-mexc.json")}
    with open(path, encoding="utf-8") as fh:
        return T.bot_world(p), json.load(fh)


def _losing_pair(world, t0=NOW):
    rows = [{"key": k, "exit_time": t0 - (3 - i) * H, "entry_time": t0 - (4 - i) * H, "pnl": -2.0, "symbol": "ETHUSDT", "side": 1,
             "roe": -0.5, "paper": {"id": i}, "strategy_id": "F3_BOS", "timeframe": "30m", "reason_ko": "손절"} for i, k in enumerate("ab")]
    return {"now": t0, "bot": world, "trades": {"accts": {"bybit": {"rows": rows}}}}


def test_the_packet_describes_the_running_bot_live15(monkeypatch):
    world, cfg = _config_world(monkeypatch, "combo.live15.json")
    assert world["ref_ko"] and not T.is_trend(world)                # the A+C 5-year reference is another config's
    src = {"now": NOW, "bot": world}
    pk = T.facts(src, "weekly", window=(NOW - 7 * DAY, NOW))
    rules = pk["fixed_rules"]
    assert rules[:9] == [f"매매법 {len(cfg['members'])}개", "BTC 40배 · 나머지 30배", "증거금 잔고의 40%", "한 번에 포지션 하나", "시장가 진입",
                         "손절 순ROE -50%(수수료·슬리피지 포함: 40배 가격 1.11%, 30배 가격 1.53%)",
                         "계단 익절(순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, 그 뒤 5%마다 (닿은 순ROE - 3%))",
                         "빠른 청산: 같은 매매법이 반대 신호를 내면 바로 청산(첫 잠금 전까지만)",
                         f"추격 진입 막기 {sum(1 for m in cfg['members'] if m.get('no_chase'))}개 매매법"
                         "(롱은 7일 범위 위 20%·24시간 고점 쪽 10% 안이면, 숏은 아래쪽이면 진입 안 함)"]
    for r in ("나스닥 개장 뒤 30분 진입 없음",) + EXEC_RULES:
        assert r in rules, r
    text = json.dumps(pk, ensure_ascii=False)
    for old in ("3연패", "50% 빠지면", "낙폭 50%", "3%씩", "3 ATR", "A+C", "신호등:", "88% 이상", "82~88%"):
        assert old not in text, old
    assert pk["checkpoint_rule"] == T.CHECK_RULE_NONE and pk["bot"]["name"] == "규칙봇 15" and pk["meeting"] == "주간 보고"
    assert pk["bot"]["break_even"] == 0.833 and "58승 4패" in pk["bot"]["start_basis"] and "kind" not in pk["bot"]
    assert pk["expect"]["words"].startswith(world["ref_ko"]) and "5년 숫자(fit·honest)가 없습니다" in pk["expect"]["words"]
    for trend_only in ("owners_decisions", "trend_now", "replay", "whatif", "old_bot_trades", "추세", "가상"):
        assert trend_only not in text, trend_only
    _key, focus = T.due_loss(_losing_pair(world))
    assert focus["how_rare"] == T.HOW_RARE_NONE
    # a config that cannot be read: the owners' 10-19 decisions
    assert T.fixed_rules(None, None) == list(T.FIXED) and "신호등 없음(실거래는 페이퍼의 모든 진입을 따라감)" in T.FIXED


def test_the_packet_describes_the_running_bot_trend(monkeypatch):
    """The config the live side runs since 10/21 (deploy/combo.trend.json): the 추세판단 봇's own rules and the owners'
    decisions; no 5-year reference, no 40-trade rule. Without its database its start is not known: said, never guessed."""
    from paperbot.trendjudge import TrendRules
    world, cfg = _config_world(monkeypatch, "combo.trend.json")
    assert T.is_trend(world) and world["ref_ko"] == L.TREND_NO_REF_KO and "trend" not in world
    pk = T.facts({"now": NOW, "bot": world}, "weekly", window=(NOW - 7 * DAY, NOW))
    rules, said = pk["fixed_rules"], TrendRules.from_dict(cfg["trend"]).describe()
    assert rules[0] == ("진입 매매법 10개(30분 진입 7개는 끝난 1시간봉 추세, 1시간 진입 3개는 끝난 4시간봉 추세를 따름) · "
                        "판단만 하는 매매법 4개(V3.9 · EMA·DMI·ADX · OBV 추세형 · 일목·AO)는 진입 안 함")
    assert rules[1:6] == said and said[3] == "쉬기: 매매법 쉬기 없음 / 코인 쉬기 없음 / 하루 손실 한도 없음"
    assert said[4].endswith("시간 정리 없음") and "되돌림을 기다림" in said[2]
    for r in ("BTC 40배 · 나머지 30배", "증거금 잔고의 40%", "한 번에 포지션 하나", "진입: 되돌림 가격에 닿은 다음 분에 시장가(실행기도 그때 시장가로 따라감)",
              "손절 순ROE -50%(수수료·슬리피지 포함: 40배 가격 1.11%, 30배 가격 1.53%)",
              "빠른 청산: 같은 매매법이 반대 신호를 내면 바로 청산(첫 잠금 전까지만)",
              "추격 진입 막기 10개 매매법(롱은 7일 범위 위 20%·24시간 고점 쪽 10% 안이면, 숏은 아래쪽이면 진입 안 함)",
              "한국 시간 주말 진입 없음", "미국 경제 발표 앞뒤 30분 진입 없음", "나스닥 개장 앞 30분·뒤 30분 진입 없음",
              "전환 전 포지션 정리: 새 봇 시작 전에 예전 규칙으로 열린 포지션은 첫 잠금 전이면 바로 닫음", "청산 뒤 반대로 갈아타지 않음") + EXEC_RULES:
        assert r in rules, r
    assert "시장가 진입" not in rules and not any(r.startswith("매매법 ") for r in rules)
    # the owners' decisions, from the config: no TIME exit, no pauses, the Nasdaq window in Korea time (summer time ends 11/1)
    d = pk["owners_decisions"]
    assert d[0].startswith("규칙 고정: 새 봇 시작부터 2주는 규칙을 바꾸지 않고")
    assert "시간 정리 청산 없음(10/21 밤 '시간청산 빼줘'): 첫 잠금 전에는 손절(순ROE -50%)·추세 뒤집힘 감독 청산·빠른 청산만" in d
    assert "쉬기 없음: 손실 뒤 매매법·코인 쉬기 없음, 하루 손실 한도 없음(10/21 '쉬기는 빼주고', '10번은 없애고')" in d
    nas = next(x for x in d if x.startswith("나스닥 개장 앞 30분·뒤 30분 진입 없음"))
    assert "'나스닥 개장전 30분도 진입금지로 하자'" in nas and "지금은 한국 22:00~23:00, 11/02부터 23:00~24:00" in nas
    assert d[-1].startswith("실거래 크기: 각 실거래 지갑의 약 40%를 증거금으로")
    bot = pk["bot"]
    assert (bot["kind"], bot["name"], bot["reference"], bot["break_even"]) == ("trend", "추세판단 봇", L.TREND_NO_REF_KO, 0.833)
    assert bot["since_kst"] is None and "trend_since" in bot["since_note"] and "start_basis" not in bot
    assert len(bot["entry_members"]) == 10 and "N20_EMA9_CHOP@30m (숏만)" in bot["entry_members"]
    assert pk["checkpoint_rule"] == T.CHECK_RULE_TREND and pk["meeting"] == "주간 보고"
    assert "expect" not in pk and "strategies" not in pk and pk["tests_available"]["how"].startswith("그림자 봇")
    # the live site's answers not read here: said, never a zero
    assert pk["record"] == {"state": "missing", "reason": "읽지 않았어요"} and pk["replay"]["state"] == "missing"
    text = json.dumps(pk, ensure_ascii=False)
    for old in ("3연패", "50% 빠지면", "A+C", "신호등:", "88% 이상", "82~88%", "58승 4패", "fit_win", "honest_win", "5년 기준표 있음"):
        assert old not in text, old
    # a losing pair: no 5-year streak table for new rules; no checkpoint while its own trades cannot be told apart
    assert T.due_loss(_losing_pair(world))[1]["how_rare"] == T.HOW_RARE_TREND
    rows = [{"exit_time": NOW - i * H, "entry_time": NOW - i * H - 30 * T.MIN, "pnl": 1.0} for i in range(1, 82)]
    assert T.due_checkpoint({"now": NOW, "bot": world, "trades": {"accts": {"paper": {"n": 81, "rows": rows}}}}) is None
    assert T.due_checkpoint({"now": NOW, "bot": {**world, "trend": {"since": NOW - 100 * H}},
                             "trades": {"accts": {"paper": {"n": 81, "rows": rows}}}})[0] == "checkpoint:trend-2026-10-15:80"


# ---------------------------------------------------------------- 추세판단 봇 (10-21): its world, its packet, its meetings
def trend_world(tmp_path, monkeypatch):
    """The trend bot's world (tests/test_live_fresh_start.py _switch: its own code, TrendRunner with a fake judge, two
    executor databases): the bot before it opened a BTC long; the trend bot started after it (``since``) and closed it at
    once (SWITCH: the bot before it's trade); then the trend bot's own ETH long after its pullback, closed by the
    supervisor when ETH's 1h judgment turned (JUDGE). -> (world, since, paths, now)."""
    import test_live_fresh_start as FS
    import test_trendbot as TB
    for k in ("PAPERBOT_LIVE_CHECK_DB", "PAPERBOT_LIVE_IMPROVE_DB", T.DB_ENV):
        monkeypatch.setenv(k, str(tmp_path / f"{k.lower()}.db"))
    w, _b, _p, since, paths = FS._switch(tmp_path, monkeypatch)
    h1, h2 = TB.T0 + TB.HOUR, TB.T0 + 2 * TB.HOUR
    TB._to(w, since + 2 * T.MIN, h1)
    w.judge.j[("ETHUSDT", "1h")] = TB.J(close=2500.0, ema20=2498.0, atr=12.5)
    w.judge.s[("ETHUSDT", "30m")] = TB.S(ema20=2500.0, atr=7.5, rng=10.0)          # not a long bar: the 0.25 ATR pullback
    w.signal("N08_ICHI_WR", "ETHUSDT", 1, h1)
    w.step(h1)                                                    # waits for its pullback
    w.step(h1 + T.MIN, move={"ETHUSDT": -0.001})                 # touched
    w.step(h1 + 2 * T.MIN)                                        # entered
    assert w.engine().position.symbol == "ETHUSDT"
    w.judge.j[("ETHUSDT", "1h")] = TB.J(dir=-1, votes={"V39": -1, "S6": -1, "OBV": -1, "N12": 1}, close=2500.0, ema20=2502.0, atr=12.5)
    TB._to(w, h1 + 3 * T.MIN, h2 + 2 * T.MIN)                    # the 1h bar closing at h2 is down: the supervisor closes it
    w.store.commit()
    assert w.engine().position is None
    L._cache.clear()
    return w, since, paths, h2 + 3 * T.MIN


def trend_41(src: dict, since: int, now: int) -> dict:
    """``src`` with 41 closed trades of the trend bot's own and 30 of the bot before it's (entered before its start)."""
    rows = ([{"exit_time": now - i * T.MIN, "entry_time": since + i * T.MIN, "pnl": 1.0 if i % 4 else -1.0} for i in range(1, 42)]
            + [{"exit_time": since + i * T.MIN, "entry_time": since - 60 * T.MIN, "pnl": 1.0} for i in range(30)])
    paper = {**src["trades"]["accts"]["paper"], "rows": rows, "n": len(rows)}
    return {**src, "trades": {**src["trades"], "accts": {**src["trades"]["accts"], "paper": paper}},
            "trend": {**src["trend"], "record": {**src["trend"]["record"], "n": 41}}}


class Rec(R.FakeRunner):
    """FakeRunner that keeps the instructions each member was given."""

    def call(self, model, system_prompt, instruction, packet):
        self.calls_text = getattr(self, "calls_text", []) + [(packet.get("role"), system_prompt, instruction)]
        return super().call(model, system_prompt, instruction, packet)


def test_the_trend_packet_on_its_own_world(tmp_path, monkeypatch):
    w, since, paths, now = trend_world(tmp_path, monkeypatch)
    src = T.sources(now, paths)
    assert T.is_trend(src["bot"]) and src["bot"]["trend"]["since"] == since
    assert {src[k]["state"] for k in ("trend", "review", "replay")} == {"ok"}
    pk = T.packet_for(src, "weekly", {"window": [now - 7 * DAY, now]})
    bot = pk["bot"]
    assert (bot["kind"], bot["since_kst"], bot["review_kst"]) == ("trend", T.kst_text(since), T.kst_md(since + 14 * DAY))
    assert bot["old_bot"].startswith(f"규칙봇 15: 이 시각({T.kst_text(since)}) 전에 들어간 거래는 그 봇 것")
    # the record since its start only: the ETH trade is its own; the BTC long the bot before it opened is not
    rec = pk["record"]
    assert (rec["paper"]["n"], rec["paper"]["wins"], rec["flip"]["n"]) == (1, 0, 1) and "표본 적음" in rec["luck"]["ko"]
    assert [x["name"] for x in rec["execs"]] == ["바이비트", "WOO X Pro"] and all(x["n"] == 0 for x in rec["execs"])
    assert [b["exit"] for b in rec["by_exit"]] == ["감독: 추세 뒤집힘"]
    (t,) = pk["trades"]
    assert (t["coin"], t["side"], t["strategy"], t["exit"]) == ("ETHUSDT", "롱", "N08_ICHI_WR", "감독 청산(추세 뒤집힘)")
    assert t["entry_judge"].startswith("1시간 상승") and t["exit_why"].startswith("1시간 판단이 하락로")
    (o,) = pk["old_bot_trades"]
    assert (o["coin"], o["exit"], o["bot"]) == ("BTCUSDT", "전환 전 포지션 정리", "예전 봇(규칙봇 15): 이 봇 성적 아님")
    # its parts: the trend now, where the signals went, the supervisor, the members
    tn = pk["trend_now"]
    assert tn["coins"]["ETH"]["1h"].startswith("1시간 하락") and "ETH 30분 진입 숏만" in tn["taking_now"]
    assert pk["funnel"]["since_start"] == {"signals": 1, "passed": 1, "touched": 1, "entered": 1, "blocked": []}
    assert pk["funnel"]["window"] == {"signals": 1, "passed": 1, "touched": 1, "entered": 1}
    sup = pk["supervisor"]
    assert [(x["coin"], x["exit"], x["old_bot"]) for x in sup["exits_7d"]] == [("ETH", "감독 청산(추세 뒤집힘)", False)]
    assert [(x["coin"], x["exit"]) for x in sup["switch_closed_24h"]] == [("BTC", "전환 전 포지션 정리")]
    eth = next(m for m in pk["members"] if m["member"] == "N08_ICHI_WR@30m")
    assert (eth["role"], eth["trades"], eth["wins"], eth["last_exit"]) == ("눌림", 1, 0, "감독 청산(추세 뒤집힘)")
    assert {c["what"] for c in pk["signals_24h"]["counts"]} >= {"되돌림 확인 (진입 신호로 바뀜)"}
    # the costs against the replay, the replay's expectation and the what-ifs: 가상, said so
    c = pk["costs"]
    assert c["replay"]["label"].startswith("가상") and c["replay"]["cost"] == 0.0448 and c["replay_ko"].startswith("재현에서는")
    assert c["paper"]["of"] == 1 and c["paper"]["fee"] > 0 and [x["name"] for x in c["execs"]] == ["바이비트", "WOO X Pro"]
    rp = pk["replay"]
    assert rp["label"].startswith("가상") and rp["results"]["replay"]["n"] == 89 and rp["results"]["paper"]["n"] == 1
    assert "표본 적음" in rp["results"]["paper"]["verdict"] and rp["funnel"]["replay"][0] == {"stage": "신호", "n": 4923, "share": 1.0}
    assert pk["whatif"]["label"].startswith("가상") and [x["rule"] for x in pk["whatif"]["items"]][:3] == ["추세 판단", "진입 자리 검사",
                                                                                                         "되돌림 기다림 (버린 신호)"]
    # the size against each real wallet: 40 % x the paper wallet x qty_scale / the real wallet
    paper_wallet = next(a["wallet"] for a in pk["accounts"] if a["id"] == "paper")
    assert [x["margin_share_now"] for x in pk["sizing"]["execs"]] == [round(0.4 * paper_wallet * 0.1 / 90.0, 3)] * 2
    assert all("trades" not in a for a in pk["accounts"])                     # the accounts' all-time records are not shown
    text = json.dumps(pk, ensure_ascii=False)
    for old in ("A+C", "fit_win", "honest_win", "5년 기준표 있음", "88% 이상", "82~88%", "58승 4패", "start_basis"):
        assert old not in text, old
    for secret in ("TELEGRAM", "API_KEY", "SECRET", "executor.env", "OAUTH"):
        assert secret not in text, secret
    assert len(text) < 60_000


def test_the_trend_meetings(tmp_path, monkeypatch):
    """A 거래 점검 at its own 40th trade (no 88 % rule, the bot before it's trades never counted), the members' trend
    instructions, the conclusion's message; a loss meeting only on its own trades."""
    w, since, paths, now = trend_world(tmp_path, monkeypatch)
    src = T.sources(now, paths)
    assert T.due_checkpoint(src) is None and T.due_loss(src) is None             # one trade of its own, no live trade
    src41 = trend_41(src, since, now)
    rows = src41["trades"]["accts"]["paper"]["rows"]
    key, focus = T.due_checkpoint(src41)
    assert key == f"checkpoint:trend-{T.kst_date(since)}:40" and focus["milestone"] == 40 and focus["paper_closed_since_start"] == 41
    assert focus["last_k_wins"] == sum(1 for r in rows[:40] if r["pnl"] > 0)
    conn = T.connect(os.environ[T.DB_ENV])
    run, note = Rec(answers={"lead": LEAD}), Note()
    out = T.tick(conn, src41, run, T.BUDGET_DEFAULT, notifier=note)
    assert out["state"] == "done" and out["key"] == key and [c["role"] for c in run.calls] == ["risk", "stats", "market", "lead"]
    title, = conn.execute("SELECT title FROM meetings").fetchone()
    assert title.startswith("40번째 거래 점검 · ") and T.kind_ko("checkpoint", key) == "거래 점검"
    assert run.calls[0]["packet"]["facts"]["meeting"] == "40번째 거래 점검"
    assert run.calls[0]["packet"]["facts"]["checkpoint_rule"] == T.CHECK_RULE_TREND
    for role, sp, ins in run.calls_text:
        assert sp == T.system_prompt(role, True) and ins.startswith("40번째 거래 점검 회의입니다")
        assert "추세판단 봇" in sp and "되돌림" in sp and "감독" in sp and "가상" in sp and "5년 기준표가 없습니다" in sp
    assert "그림자 봇" in run.calls_text[-1][1] and "2주 검토" in run.calls_text[-1][1]
    (_level, msg), = note.sent
    assert msg.startswith("🧭 [실거래 분석팀] 40번째 거래 점검 🟠 주의")
    # a losing pair of a live executor: only trades entered since the start count
    def live(*entries):
        return {**src, "trades": {"accts": {"bybit": {"rows": [
            {"key": k, "entry_time": e, "exit_time": e + 30 * T.MIN, "pnl": -2.0, "symbol": "ETHUSDT", "side": 1, "roe": -0.5,
             "paper": {"id": k}, "strategy_id": "F3_BOS", "timeframe": "30m", "reason_ko": "손절"} for k, e in zip("ab", entries)]}}}}
    assert T.due_loss(live(since - H, since + T.MIN)) is None                  # the first one was the bot before it's
    key2, lf = T.due_loss(live(since + T.MIN, since + 2 * T.MIN))
    assert key2 == "loss:a+b" and [x["pnl"] for x in lf["losses"]] == [-2.0, -2.0]
    assert lf["how_rare"].startswith(T.HOW_RARE_TREND) and "참고(가상): 7/1~10/20 재현의 이긴 비율 49%" in lf["how_rare"]
    conn.close()


def test_the_trend_prompts_keep_the_team_off_the_controls():
    for role in T.ROLES:
        sp = T.system_prompt(role, True)
        assert sp != T.system_prompt(role) and T.ROLES_TREND[role]["focus"] in sp
        assert "매매 권한이 없습니다" in sp and "고정 규칙" in sp and "패킷(JSON)에 있는 숫자만" in sp and "JSON 하나만" in sp
        assert f"{T.SMALL_N}번보다 적으면" in sp and "두 분의 결정(owners_decisions" in sp and "2주 검토" in sp
        assert "지난 봇(규칙봇 15 · A+C) 숫자를 빌려 오지 않습니다" in sp and "'가상'이라고 붙입니다" in sp
        for part in ("추세 판단", "진입 전 검사", "되돌림", "감독", "비용"):
            assert part in sp, part
        for old in ("75%", "91%", "88%", "fit(맞춘 숫자", "2020-24"):
            assert old not in sp, old
    lead = T.system_prompt("lead", True)
    assert "시험해 볼 가설" in lead and "그림자 봇" in lead and "deploy/combo.shadow-trend-*.json" in lead and "채택은 두 분이 정합니다" in lead
    assert T.roles(True) is T.ROLES_TREND and T.roles() is T.ROLES and T.ROLES_TREND["lead"] == T.ROLES["lead"]
    assert [(T.ROLES_TREND[r]["name"], T.ROLES_TREND[r]["title"]) for r in T.ROLES] == [(T.ROLES[r]["name"], T.ROLES[r]["title"]) for r in T.ROLES]


def test_the_owners_preview_of_the_trend_packet(tmp_path, monkeypatch, capsys):
    """python -m paperbot.liveteam preview weekly on the trend bot: the packet and the members' trend instructions, no AI
    call, nothing written (no liveteam.db)."""
    w, _since, paths, _now = trend_world(tmp_path, monkeypatch)
    for k, env in (("paper", "PAPERBOT_LIVE_PAPER_DB"), ("bybit_db", "PAPERBOT_LIVE_BYBIT_DB"), ("mexc_db", "PAPERBOT_LIVE_MEXC_DB"),
                   ("bybit_config", "PAPERBOT_LIVE_BYBIT_CONFIG"), ("mexc_config", "PAPERBOT_LIVE_MEXC_CONFIG")):
        monkeypatch.setenv(env, paths[k])
    monkeypatch.setenv("PAPERBOT_LIVE_PAPER2_DB", str(tmp_path / "no-second.db"))
    db = str(tmp_path / "team" / "preview.db")
    assert T.main(["--db", db, "preview", "weekly"]) == 0
    out = capsys.readouterr().out
    pk = json.loads(out[:out.index("\n=====")])
    assert pk["bot"]["kind"] == "trend" and pk["replay"]["label"].startswith("가상") and "owners_decisions" in pk
    assert out.count("===== ") == 4 and T.system_prompt("lead", True) in out and "--- 주간 보고 회의입니다" in out
    assert not os.path.exists(db) and not os.path.exists(os.environ[T.DB_ENV])
