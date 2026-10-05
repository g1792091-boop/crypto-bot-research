"""The 24-hour debate room service (paperbot/agents/debate.py): a fake HTTP transport is injected everywhere, there is
no network and no real key. Rounds, the answer's checks, cost and the cap, every kind of API failure and the backoff,
the Telegram warning once an hour per cause, the key never leaking, SIGTERM, the dry run and the dashboard route."""
import json
import os
import signal
import sqlite3
import subprocess
import sys

import pytest

from debate_world import make_world
from paperbot.agents import debate as D
from paperbot.agents import debate_packet as P
from paperbot.notify import ListNotifier

KEY = "sk-ant-api03-FAKEKEYFAKEKEYFAKEKEY-abcdefghijklmnopqrstuvwxyz0123456789"
DAY = 86_400_000
NOW = 1_791_158_400_000 + 10 * DAY          # 2026-10-15 00:00 UTC = 09:00 KST


def answer(turns=4, hyps=None, ideas=None, note="표본이 작아 결론은 아직 없다."):
    roles = ["낙관론자", "비관론자", "회의론자", "퀀트", "리스크 책임자"][:turns]
    return {"turns": [{"speaker": r, "text": f"{r}의 말: 표본 작음."} for r in roles], "note": note,
            "hypotheses": hyps if hyps is not None else [], "ideas": ideas if ideas is not None else []}


def ok_body(ans, usage=None):
    usage = usage or {"input_tokens": 3000, "output_tokens": 700, "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0}
    return 200, {"request-id": "req_1"}, json.dumps({"content": [{"type": "text", "text": json.dumps(ans, ensure_ascii=False)}],
                                                     "usage": usage, "stop_reason": "end_turn"}).encode()


def err_body(status, etype, message, headers=None):
    return status, headers or {}, json.dumps({"type": "error", "error": {"type": etype, "message": message}}).encode()


class Fake:
    """Scripted transport: answers in order (the last one repeats); records every request."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, dict(headers), json.loads(body), timeout))
        a = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]
        if isinstance(a, Exception):
            raise a
        return a


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def world(tmp_path):
    return make_world(tmp_path, NOW, days=10, per_day=60)


def make(tmp_path, world, *answers, key=KEY, clock=None, **cfg_over):
    cfg = D.Config(api_key=key, paper_db=world["paper"], daily_db=world["daily"], agents_db=str(tmp_path / "no_agents.db"),
                   checkpoint_db=str(tmp_path / "no_cp.db"), debate_dir=str(tmp_path / "debate"), **cfg_over)
    db = D.DB(cfg.debate_db)
    tg, logs, clk = ListNotifier(), [], clock or Clock()
    fake = Fake(*answers)
    svc = D.Service(cfg, db, tg, transport=fake, clock=clk, sleep=lambda s: None, out=logs.append)
    svc.beat_s = 0.001
    svc.start()
    svc.clk, svc.fake, svc.tg, svc.logs = clk, fake, tg, logs
    return svc


def rows(svc, sql, *a):
    return svc.db.conn.execute(sql, a).fetchall()


# ---------------------------------------------------------------- a successful round
def test_a_round_writes_messages_round_hypotheses_and_ideas(tmp_path, world):
    hyps = [{"speaker": "퀀트", "kind": "best_vs_normal", "params": {"n": 100}},
            {"speaker": "비관론자", "kind": "buy_the_dip", "params": {}}]
    ideas = [{"text": "시간대별로 좋은 자리 비율을 본다", "tag": "시간대"}, {"text": "같은 아이디어", "tag": "x"}]
    svc = make(tmp_path, world, ok_body(answer(4, hyps, ideas)))
    assert svc.tick(force=True) == "round"
    msgs = rows(svc, "SELECT round_id, speaker, stance, topic, text FROM debate_messages ORDER BY id")
    assert [m[1] for m in msgs] == ["낙관론자", "비관론자", "회의론자", "퀀트", "정리"]
    assert msgs[0][2] == "낙관" and msgs[-1][2] == "정리" and msgs[0][3] == "좋은 자리 vs 보통 레버리지 묶음"
    assert {m[0] for m in msgs} == {1}
    rd = rows(svc, "SELECT in_tokens, out_tokens, cost_usd, status, error, model, turns, topic FROM debate_rounds")[0]
    assert rd[:2] == (3000, 700) and rd[3] == "ok" and rd[4] is None and rd[5] == D.DEFAULT_MODEL and rd[6] == 4
    assert rd[2] == pytest.approx(3000 * 1.0 / 1e6 + 700 * 5.0 / 1e6)
    hy = rows(svc, "SELECT speaker, kind, status, outcome, horizon, params_json FROM debate_hypotheses ORDER BY id")
    assert hy[0][:3] == ("퀀트", "best_vs_normal", "open") and "다음 100건" in hy[0][4]
    assert json.loads(hy[0][5])["params"]["base_id"] > 0                    # the baseline code read now
    assert hy[1][:3] == ("비관론자", "buy_the_dip", "dropped") and "메뉴에 없는 종류" in hy[1][3]
    assert [r[0] for r in rows(svc, "SELECT text FROM debate_ideas")] == ["시간대별로 좋은 자리 비율을 본다", "같은 아이디어"]
    assert svc.db.spent(NOW)["month"] == pytest.approx(rd[2]) and svc.db.get("round_seq") == 1
    run = svc.db.get("run")
    assert run["state"] == "running" and svc.db.get("heartbeat") == NOW and svc.db.get("last_usage")["in"] == 3000
    # the request: Messages API, key only in the header, stable system prefix cached, packet in the user message
    url, headers, body, timeout = svc.fake.calls[0]
    assert url == "https://api.anthropic.com/v1/messages" and headers["anthropic-version"] == "2023-06-01"
    assert headers["x-api-key"] == KEY and KEY not in json.dumps(body)
    assert body["model"] == D.DEFAULT_MODEL and body["max_tokens"] == 900 and timeout == 45.0
    sysb = body["system"][0]
    assert sysb["cache_control"] == {"type": "ephemeral", "ttl": "1h"}      # 20-minute rounds: the 1-hour cache
    assert "30일 체크포인트" in sysb["text"] and "가설 메뉴" in sysb["text"] and "D+10" not in sysb["text"]
    user = body["messages"][0]["content"]
    assert "D+10" in user and "낙관론자, 비관론자, 회의론자, 리스크 책임자" in user and "회차 0번" in user


def test_roles_rotate_and_topics_do_not_repeat(tmp_path, world):
    assert D.roles_for(0, 4) == ["낙관론자", "비관론자", "회의론자", "리스크 책임자"]
    assert D.roles_for(1, 3) == ["비관론자", "회의론자", "리스크 책임자"] and D.roles_for(4, 3) == ["퀀트", "낙관론자", "비관론자"]
    svc = make(tmp_path, world, ok_body(answer()))
    seen = []
    for i in range(3):
        svc.clk.t += 21 * 60_000
        assert svc.tick(force=True) == "round"
        seen.append(rows(svc, "SELECT topic FROM debate_rounds ORDER BY round_id DESC LIMIT 1")[0][0])
    assert len(set(seen)) == 3                                               # the agenda rotates
    last = svc.fake.calls[-1][2]["messages"][0]["content"]
    assert "previous_debate_notes" in last and "표본이 작아 결론은 아직 없다" in last   # the earlier note is in the next packet


def test_the_packet_is_small_and_has_the_required_sections(tmp_path, world):
    b = P.build(world["paper"], world["daily"], None, None, NOW, round_no=1)
    pk = b["packet"]
    assert b["tokens"] <= P.MAX_PACKET_TOKENS and b["topic"] == "rank"
    for k in ("meta", "league", "totals", "last_24h", "alerts", "nightly", "hypothesis_scoreboard" if False else "meta"):
        assert k in pk, k
    assert pk["meta"]["run_day"] == "D+10" and pk["meta"]["accounts_in_tables"] == 156
    assert "2026-10-26" in pk["meta"]["observation"] and pk["meta"]["groups"] == {"core": 144, "flip": 12}
    assert pk["rank"]["accounts_top"] and all("small_sample" in r for r in pk["rank"]["accounts_top"])
    assert pk["nightly"]["parity"]["accounts"] == 156
    for i in range(len(P.TOPICS)):                                           # every agenda topic builds, within budget
        assert P.build(world["paper"], world["daily"], None, None, NOW, round_no=i)["tokens"] <= P.MAX_PACKET_TOKENS


def test_an_unusual_thing_jumps_the_agenda_but_not_forever(tmp_path, world):
    con = sqlite3.connect(world["paper"])
    eng = json.loads(con.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()[0])
    eng["engines"]["N01_ST_EMA@1h"]["bust"] = True
    con.execute("UPDATE state SET data = ? WHERE k = 'accounts'", (json.dumps(eng),))
    con.commit()
    con.close()
    b = P.build(world["paper"], world["daily"], None, None, NOW, round_no=0)
    assert b["topic"] == "risk" and "파산" in b["why"] and b["packet"]["unusual"]
    assert P.build(world["paper"], world["daily"], None, None, NOW, round_no=0, recent_topics=("risk", "risk"))["topic"] == "lev"


# ---------------------------------------------------------------- the answer is checked
def test_parse_answer_checks_shape_and_keeps_what_was_paid_for():
    order = ["낙관론자", "비관론자", "회의론자"]
    good = D.parse_answer("```json\n" + json.dumps(answer(3), ensure_ascii=False) + "\n```", order)
    assert len(good["turns"]) == 3 and good["note"] and not good["truncated"]
    mixed = D.parse_answer('설명입니다 {"turns": [{"speaker": "아무개", "text": "a b"}, {"speaker": "퀀트", "text": "x"}]} 끝', order)
    assert [t["speaker"] for t in mixed["turns"]] == ["낙관론자", "퀀트"]          # an unknown speaker takes the slot's role
    cut = ('{"turns": [{"speaker": "낙관론자", "text": "하나 \\"둘\\""}, {"speaker": "비관론자", "text": "셋"}, '
           '{"speaker": "회의론자", "text": "잘리는 중')
    got = D.parse_answer(cut, order)
    assert got["truncated"] and [t["text"] for t in got["turns"]] == ['하나 "둘"', "셋"] and got["hypotheses"] == []
    for bad in ("", "not json", '{"turns": "x"}', '{"turns": [{"speaker": "퀀트", "text": "하나뿐"}]}'):
        with pytest.raises(D.ApiError) as e:
            D.parse_answer(bad, order)
        assert e.value.kind == "output"
    long = D.parse_answer(json.dumps({"turns": [{"speaker": "퀀트", "text": "가" * 5000}] * 6, "note": "나" * 5000,
                                      "ideas": [{"text": "다" * 5000, "tag": "t" * 99}] * 5}), order)
    assert len(long["turns"]) == 5 and len(long["turns"][0]["text"]) == D.MAX_TURN_CHARS
    assert len(long["note"]) == D.MAX_NOTE_CHARS and len(long["ideas"]) == 2 and len(long["ideas"][0]["tag"]) == 40


def test_a_bad_answer_is_paid_for_recorded_and_never_stored_as_a_debate(tmp_path, world):
    svc = make(tmp_path, world, ok_body({"nothing": 1}))
    assert svc.tick(force=True) == "error"
    r = rows(svc, "SELECT status, error, cost_usd FROM debate_rounds")[0]
    assert r[0] == "error" and "output" in r[1] and r[2] > 0                  # the call cost money: counted
    assert svc.db.spent(NOW)["month"] == pytest.approx(r[2]) and not rows(svc, "SELECT 1 FROM debate_messages")
    for _ in range(2):                                                         # three in a row: a pause and one warning
        svc.clk.t += 21 * 60_000
        svc.tick(force=True)
    assert svc.db.get("fail:cause") == "output" and [m[0] for m in svc.tg.messages] == ["WARN"]


def test_hypotheses_over_the_limits_are_dropped_and_recorded(tmp_path, world):
    hyps = [{"speaker": "퀀트", "kind": "strategy_roe_sign", "params": {"strategy": "N17_KC_RSI", "tf": "1h", "op": "<", "n": 20}},
            {"speaker": "퀀트", "kind": "parity_streak", "params": {"days": 99}},
            {"speaker": "퀀트", "kind": "busts_by_day", "params": {"day": 25, "max_busts": 1}}]
    svc = make(tmp_path, world, ok_body(answer(3, hyps)))
    svc.tick(force=True)
    st = rows(svc, "SELECT status, outcome FROM debate_hypotheses ORDER BY id")
    assert [s[0] for s in st] == ["open", "dropped", "dropped"]
    assert "범위 밖" in st[1][1] and "2개까지" in st[2][1]


# ---------------------------------------------------------------- money
def test_cost_comes_from_the_usage_fields_with_overridable_prices():
    cfg = D.Config(model="claude-haiku-4-5-20251001", every_min=20)
    u = {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 2000, "cache_creation_input_tokens": 3000}
    # 1h cache writes cost 2x, reads 0.1x: (1000 + 2000*0.1 + 3000*2) * $1 + 500 * $5 per million
    assert D.cost_of(u, cfg) == pytest.approx((1000 + 200 + 6000) / 1e6 + 2500 / 1e6)
    cfg5 = D.Config(every_min=3)
    assert D.cost_of(u, cfg5) == pytest.approx((1000 + 200 + 3000 * 1.25) / 1e6 + 2500 / 1e6)
    split = {**u, "cache_creation": {"ephemeral_5m_input_tokens": 1000, "ephemeral_1h_input_tokens": 2000}}
    assert D.cost_of(split, cfg) == pytest.approx((1000 + 200 + 1000 * 1.25 + 2000 * 2) / 1e6 + 2500 / 1e6)
    assert D.Config(model="claude-sonnet-5-5").prices() == (2.0, 10.0)
    assert D.Config(model="claude-haiku-4-5-20251001", price_in=1.5, price_out=7.0).prices() == (1.5, 7.0)
    assert D.Config(model="some-new-model").prices() == D.UNKNOWN_PRICE        # counted high on purpose
    env = D.config_from_env({"ANTHROPIC_API_KEY": KEY, "DEBATE_PRICE_IN": "3", "DEBATE_PRICE_OUT": "15"})
    assert env.prices() == (3.0, 15.0) and env.every_min == 20 and env.monthly_cap == 40.0 and env.model == D.DEFAULT_MODEL
    for bad in ({"DEBATE_EVERY_MIN": "0"}, {"DEBATE_EVERY_MIN": "x"}, {"DEBATE_MONTHLY_USD_CAP": "-1"},
                {"DEBATE_TURNS": "9"}, {"DEBATE_THINKING": "yes"}):
        with pytest.raises(ValueError):
            D.config_from_env(bad)


def test_the_monthly_cap_warns_at_80_stops_at_95_and_resumes_next_month(tmp_path, world):
    svc = make(tmp_path, world, ok_body(answer()), monthly_cap=10.0)
    svc.db.put("spend:month:2026-10", 7.9)
    assert svc.tick(force=True) == "round" and svc.tg.messages == []         # below 80%
    svc.db.put("spend:month:2026-10", 8.0)
    svc.clk.t += 21 * 60_000
    assert svc.tick(force=True) == "round"                                    # 80%: one warning, still running
    assert [m[0] for m in svc.tg.messages] == ["WARN"] and "80%" in svc.tg.messages[0][1]
    svc.clk.t += 21 * 60_000
    svc.tick(force=True)
    assert len(svc.tg.messages) == 1                                          # once, not at every round
    svc.db.put("spend:month:2026-10", 9.5)
    n = len(svc.fake.calls)
    svc.clk.t += 21 * 60_000
    assert svc.tick(force=True) == "cap" and len(svc.fake.calls) == n          # 95%: no call at all
    assert "한도에 닿았습니다" in svc.tg.messages[-1][1] and svc.db.get("run")["state"] == "paused"
    svc.clk.t += 21 * 60_000
    assert svc.tick(force=True) == "cap" and len(svc.tg.messages) == 2        # one stop warning per month
    s = D.summary(svc.cfg.debate_db, svc.clk.t)
    assert s["state"] == "paused" and "한도" in s["reason"] and s["spend"]["pct"] == pytest.approx(95.0, abs=3)
    svc.clk.t = NOW + 18 * DAY                                                # November (KST): a new month, a fresh counter
    assert svc.tick(force=True) == "round" and svc.db.spent(svc.clk.t)["month"] < 0.1


def test_a_round_whose_worst_case_would_pass_the_cap_never_starts(tmp_path, world):
    svc = make(tmp_path, world, ok_body(answer()), monthly_cap=10.0)
    svc.db.put("spend:month:2026-10", 9.4995)         # under 95%? no: 94.995% -> only the worst-case rule can stop it
    svc.cfg.price_out = 5.0
    svc.cfg.max_tokens = 2000
    svc.cfg.price_in = 1.0
    svc.db.put("spend:month:2026-10", 9.4995)
    assert svc.check_cap(NOW, in_tokens=2_000_000) == "cap"                    # 2M tokens would cost $4 more
    assert svc.check_cap(NOW, in_tokens=0) is None


def test_hourly_and_daily_guards(tmp_path, world):
    svc = make(tmp_path, world, ok_body(answer()), monthly_cap=24.0, daily_cap=0.5)       # hourly guard = $1
    svc.db.conn.execute("INSERT INTO debate_rounds (ts, status, cost_usd) VALUES (?, 'ok', 1.2)", (NOW - 60_000,))
    svc.db.conn.commit()
    assert svc.tick(force=True) == "hour" and not svc.fake.calls
    svc.clk.t += 61 * 60_000                                                  # the hour has passed
    assert svc.tick(force=True) == "round"
    svc.db.put("spend:day:2026-10-15", 0.6)
    svc.clk.t += 61 * 60_000
    svc.db.put(f"spend:day:{D.kst_day(svc.clk.t)}", 0.6)
    assert svc.tick(force=True) == "day"


# ---------------------------------------------------------------- failures, backoff, warnings
@pytest.mark.parametrize("answers,cause,wording", [
    ([err_body(401, "authentication_error", "invalid x-api-key")], "auth", "키가 거부"),
    ([err_body(403, "permission_error", "forbidden")], "auth", "키가 거부"),
    ([err_body(400, "invalid_request_error", "Your credit balance is too low to access the Anthropic API")], "credit", "API 잔액 부족 — 콘솔에서 충전하면 저절로 이어집니다"),
    ([err_body(400, "invalid_request_error", "model: not found")], "bad_request", "요청이 거절"),
    ([err_body(500, "api_error", "boom")] * 3, "server", "서버 오류"),
    ([err_body(529, "overloaded_error", "Overloaded")] * 3, "server", "서버 오류"),
    ([OSError("connection reset")] * 3, "network", "인터넷 연결"),
    ([err_body(429, "rate_limit_error", "slow down", {"retry-after": "7"})] * 3, "rate", "429"),
])
def test_every_kind_of_failure_is_recorded_backed_off_and_warned_once(tmp_path, world, answers, cause, wording):
    svc = make(tmp_path, world, *answers)
    sleeps = []
    svc.sleep = sleeps.append
    assert svc.tick(force=True) == "error"
    r = rows(svc, "SELECT status, error, cost_usd FROM debate_rounds")[0]
    assert r[0] == "error" and r[1].startswith(cause) and r[2] == 0
    assert svc.db.get("fail:cause") == cause and svc.db.get("backoff:level") == 1
    assert svc.db.get("backoff:until") >= NOW + 60_000                         # a minute at least, exponential from there
    assert len(svc.tg.messages) == 1 and svc.tg.messages[0][0] == "WARN" and wording in svc.tg.messages[0][1]
    assert svc.tg.messages[0][1].startswith("⚠ 24시간 토론방 멈춤: ")
    retried = cause in ("server", "network", "rate")
    assert len(svc.fake.calls) == (3 if retried else 1)                        # bounded retries, only where it can help
    if cause == "rate":
        assert svc.db.get("backoff:until") >= NOW + 60_000 and sum(sleeps) >= 7 * 2   # retry-after honoured in the call
    assert D.summary(svc.cfg.debate_db, NOW)["state"] == "paused"


def test_backoff_grows_to_30_minutes_and_the_warning_comes_once_an_hour_per_cause(tmp_path, world):
    svc = make(tmp_path, world, err_body(401, "authentication_error", "bad key"))
    waits = []
    for i in range(8):
        assert svc.tick(force=True) == "error"
        waits.append((svc.db.get("backoff:until") - svc.clk.t) // 1000)
        svc.clk.t += 5 * 60_000
    assert waits[:5] == [60, 120, 240, 480, 960] and waits[5:] == [1800, 1800, 1800]
    assert len(svc.tg.messages) == 1                                           # 40 minutes of failures: one warning
    svc.clk.t += 25 * 60_000                                                   # more than an hour after the first
    svc.tick(force=True)
    assert len(svc.tg.messages) == 2
    svc.fake.answers = [err_body(500, "api_error", "boom")]                    # another cause: its own warning at once
    svc.fake.calls.clear()
    svc.clk.t += 1000
    svc.tick(force=True)
    assert len(svc.tg.messages) == 3 and "서버 오류" in svc.tg.messages[-1][1]


def test_the_loop_waits_out_the_backoff_then_recovers_with_one_info(tmp_path, world):
    svc = make(tmp_path, world, err_body(400, "invalid_request_error", "credit balance is too low"), ok_body(answer()))
    assert svc.tick() == "error"
    n = len(svc.fake.calls)
    svc.clk.t += 30_000
    assert svc.tick() == "idle" and len(svc.fake.calls) == n                   # inside the backoff: nothing is sent
    svc.fake.answers = [ok_body(answer())]
    svc.clk.t += 40 * 60_000
    assert svc.tick() == "round"
    assert [m[0] for m in svc.tg.messages] == ["WARN", "INFO"] and "다시 시작" in svc.tg.messages[1][1]
    assert svc.db.get("fail:cause") is None and svc.db.get("backoff:level") == 0 and svc.db.get("backoff:until") is None
    svc.clk.t += 21 * 60_000
    svc.tick(force=True)
    assert len(svc.tg.messages) == 2                                           # no second INFO


def test_no_key_idles_without_calls_and_says_so_once_an_hour(tmp_path, world):
    svc = make(tmp_path, world, ok_body(answer()), key="")
    for _ in range(3):
        assert svc.tick() == "no_key"
        svc.clk.t += 30_000
    assert not svc.fake.calls and len(svc.tg.messages) == 1 and "API 키가 없습니다" in svc.tg.messages[0][1]
    assert D.summary(svc.cfg.debate_db, svc.clk.t)["state"] == "no_key"
    assert D.summary(svc.cfg.debate_db, svc.clk.t)["state_ko"] == "키 없음"


def test_a_missing_bot_database_is_a_state_not_a_crash(tmp_path, world):
    os.remove(world["paper"])
    svc = make(tmp_path, world, ok_body(answer()))
    assert svc.tick(force=True) == "error" and not svc.fake.calls
    assert svc.db.get("fail:cause") == "packet" and "봇 데이터를 읽지 못했습니다" in svc.tg.messages[0][1]


# ---------------------------------------------------------------- the key stays secret
def test_the_key_never_appears_in_logs_the_database_notifications_or_errors(tmp_path, world):
    leak = f"boom with {KEY} in it"
    svc = make(tmp_path, world, OSError(leak), err_body(401, "authentication_error", f"invalid x-api-key {KEY}"),
               err_body(500, "api_error", f"echo {KEY}"), ok_body(answer()))
    for i in range(4):
        svc.tick(force=True)
        svc.fake.answers = svc.fake.answers[1:] or [ok_body(answer())]
        svc.fake.calls.clear()
        svc.clk.t += 5 * 60_000
    dump = "\n".join(svc.db.conn.iterdump())
    text = "\n".join(svc.logs) + dump + "\n".join(m[1] for m in svc.tg.messages)
    assert KEY not in text and "FAKEKEYFAKEKEY" not in text
    assert D.redact(f"x-api-key: {KEY} and {KEY[:20]}") .count("***") >= 1 and KEY not in D.redact(f"a {KEY} b", KEY)
    with pytest.raises(D.ApiError) as e:
        D.call_api(D.Config(api_key=KEY, retries=0), "s", "u", Fake(OSError(leak)))
    assert KEY not in str(e.value) and e.value.kind == "network"
    e2 = D.classify(401, f'{{"error": {{"type": "x", "message": "{KEY}"}}}}'.encode(), {}, KEY)
    assert KEY not in str(e2)
    # the status command, the dashboard view and the dry run print nothing of it either
    out = []
    D.main(["status"], environ={"ANTHROPIC_API_KEY": KEY, "DEBATE_DIR": str(tmp_path / "debate")}, out=out.append)
    assert KEY not in "\n".join(out) and KEY not in json.dumps(D.summary(svc.cfg.debate_db, svc.clk.t), ensure_ascii=False)


def test_the_key_is_read_only_from_the_environment():
    src = open(D.__file__, encoding="utf-8").read()
    assert src.count("with open(") == 1 and "open(PROMPT" in src            # the one file it opens is its prompt
    assert 'env.get("ANTHROPIC_API_KEY")' in src
    for f in ("debate_packet.py", "debate_grade.py"):
        assert "ANTHROPIC" not in open(os.path.join(os.path.dirname(D.__file__), f), encoding="utf-8").read()


# ---------------------------------------------------------------- skipping, restarts, SIGTERM
def test_a_round_is_skipped_for_free_when_nothing_relevant_changed(tmp_path, world):
    svc = make(tmp_path, world, ok_body(answer()))
    assert svc.tick() == "round"
    svc.clk.t += 21 * 60_000
    n = len(svc.fake.calls)
    assert svc.tick() == "skipped" and len(svc.fake.calls) == n
    r = rows(svc, "SELECT status, error, cost_usd FROM debate_rounds ORDER BY round_id DESC LIMIT 1")[0]
    assert r[0] == "skipped" and r[1].startswith("unchanged:") and r[2] == 0
    s = D.summary(svc.cfg.debate_db, svc.clk.t)
    assert s["skipped_24h"] == 1 and s["rounds"][0]["status"] == "skipped"
    # 10 new closed trades: relevant
    from paperbot.models import TradeRecord
    from paperbot.store3 import Store3
    st = Store3(world["paper"])
    for i in range(10):
        st.trade("N01_ST_EMA@1h", TradeRecord(strategy_id="N01_ST_EMA", symbol="BTCUSDT", timeframe="1h", side=1, signal_ts=1,
                 entry_time=1, entry_price=1.0, exit_time=NOW - 1000 + i, exit_price=1.0, exit_reason="SL", qty=1.0,
                 leverage=20, tier="normal", margin=100.0, stop_price=1.0, tp_price=0.0, liq_price=0.5, fees=0.0,
                 funding=0.0, pnl=-1.0, roe=-0.01, price_move=0.0, mae_price=1.0, mfe_price=1.0, equity_after=4999.0,
                 score=0.0, context={}))
    st.commit()
    st.conn.close()
    svc.clk.t += 21 * 60_000
    assert svc.tick() == "round"
    # nothing changed again, but six hours without a debate: one runs anyway
    svc.clk.t += 21 * 60_000
    assert svc.tick() == "skipped"
    svc.clk.t += 6 * 3_600_000
    assert svc.tick() == "round"
    ch, why = P.changed({"trade_id": 5, "alert_ts": 1, "nightly_day": "a", "busts": 0}, {"trade_id": 3}, 10)
    assert ch and "새로 시작" in why                                            # a replaced database is a change


def test_restart_does_not_burst_and_closes_a_round_cut_off_in_the_middle(tmp_path, world):
    svc = make(tmp_path, world, ok_body(answer()))
    svc.tick()
    svc.db.conn.execute("INSERT INTO debate_rounds (ts, status) VALUES (?, 'running')", (NOW,))
    svc.db.conn.commit()
    svc.db.close()
    db2 = D.DB(svc.cfg.debate_db)
    svc2 = D.Service(svc.cfg, db2, ListNotifier(), transport=svc.fake, clock=Clock(NOW + 60_000), sleep=lambda s: None,
                     out=lambda s: None)
    svc2.start()
    assert rows(svc2, "SELECT status FROM debate_rounds WHERE status = 'running'") == []
    assert rows(svc2, "SELECT error FROM debate_rounds WHERE status = 'aborted'")[0][0] == "서비스가 도중에 멈춤"
    n = len(svc.fake.calls)
    assert svc2.tick() == "idle" and len(svc.fake.calls) == n                  # the schedule survived the restart


def test_sigterm_finishes_the_call_in_progress_commits_and_exits(tmp_path, world):
    svc = make(tmp_path, world, ok_body(answer(5)))

    def term_during_call(url, headers, body, timeout):          # SIGTERM arrives while the API call is in flight
        svc.stop.set()
        return svc.fake.answers[0]
    svc.transport = term_during_call
    assert svc.run() == 0
    c = sqlite3.connect(svc.cfg.debate_db)                                  # (the loop closed its connection on the way out)
    assert c.execute("SELECT COUNT(*) FROM debate_messages").fetchone()[0] == 6    # the answer was stored whole
    assert c.execute("SELECT status, turns FROM debate_rounds").fetchone() == ("ok", 5)


def test_the_signal_handler_only_sets_a_lock_free_flag():
    stop, restore = D.stop_on_sigterm()
    try:
        assert not stop.is_set()
        os.kill(os.getpid(), signal.SIGTERM)
        assert stop.wait(1.0) and stop.is_set()
        assert type(stop).__name__ == "StopFlag" and not hasattr(stop, "_lock")
    finally:
        restore()


def test_the_service_process_exits_cleanly_on_sigterm(tmp_path, world):
    """The real process, with no key (it never calls the API): starts, writes its heartbeat, stops on SIGTERM."""
    env = {**os.environ, "DEBATE_DIR": str(tmp_path / "d"), "DEBATE_PAPER_DB": world["paper"], "DEBATE_DAILY_DB": world["daily"]}
    env.pop("ANTHROPIC_API_KEY", None)
    p = subprocess.Popen([sys.executable, "-m", "paperbot.agents.debate", "run"], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        import time
        end = time.time() + 20
        while time.time() < end and not os.path.exists(str(tmp_path / "d" / "debate.db")):
            time.sleep(0.1)
        time.sleep(1.0)
        p.send_signal(signal.SIGTERM)
        out, _ = p.communicate(timeout=20)
    finally:
        if p.poll() is None:
            p.kill()
    assert p.returncode == 0, out
    s = D.summary(str(tmp_path / "d" / "debate.db"))
    assert s["state"] in ("no_key", "off") and "정리하고 끝냅니다" in out


def test_old_rows_are_pruned_and_text_is_capped(tmp_path, world):
    svc = make(tmp_path, world, ok_body(answer()))
    c = svc.db.conn
    c.execute("INSERT INTO debate_messages (ts, speaker, text) VALUES (?, 'x', 'old')", (NOW - 61 * DAY,))
    c.execute("INSERT INTO debate_messages (ts, speaker, text) VALUES (?, 'x', 'new')", (NOW - 59 * DAY,))
    c.execute("INSERT INTO debate_hypotheses (ts, status) VALUES (?, 'open')", (NOW - 400 * DAY,))
    c.commit()
    svc.db.prune(NOW)
    assert [r[0] for r in c.execute("SELECT text FROM debate_messages")] == ["new"]
    assert c.execute("SELECT COUNT(*) FROM debate_hypotheses").fetchone()[0] == 1       # an open claim is never pruned
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"                    # the dashboard reads it read-only


# ---------------------------------------------------------------- dry run: no API, no key, no files
def test_dry_run_builds_the_packet_and_prints_tokens_and_cost_without_any_call(tmp_path, world, monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network call")))
    out = []
    env = {"DEBATE_PAPER_DB": world["paper"], "DEBATE_DAILY_DB": world["daily"], "DEBATE_DIR": str(tmp_path / "never"),
           "DEBATE_AGENTS_DB": str(tmp_path / "a.db"), "DEBATE_CHECKPOINT_DB": str(tmp_path / "c.db")}
    code = D.main(["once", "--dry-run"], environ=env, transport=Fake(AssertionError("transport used")), out=out.append)
    text = "\n".join(out)
    assert code == 0 and "입력 토큰 추정" in text and "출력 토큰 추정" in text and "회당 약 $" in text
    for model in ("Haiku 4.5", "Sonnet 5.5"):
        for iv in ("10분", "20분", "30분", "60분"):
            assert any(l.startswith(model) and iv in l for l in text.splitlines()), (model, iv)
    assert "API 호출 없음, 키 필요 없음" in text and "콘솔에서 다시 확인" in text
    assert not os.path.exists(str(tmp_path / "never"))                         # nothing was created
    out2 = []
    assert D.main(["once", "--dry-run"], environ={**env, "DEBATE_PAPER_DB": str(tmp_path / "none.db")}, out=out2.append) == 1
    assert "패킷을 만들지 못했습니다" in out2[0]
    rows_ = D.cost_table(3000, 800)
    h20 = next(r for r in rows_ if r["model"] == "Haiku 4.5" and r["every_min"] == 20)
    assert h20["per_round"] == pytest.approx(3000 / 1e6 + 800 * 5 / 1e6) and h20["rounds_month"] == 2160
    assert h20["month_skip"] == pytest.approx(h20["month_no_skip"] * 0.7, abs=0.01)
    s20 = next(r for r in rows_ if r["model"] == "Sonnet 5.5" and r["every_min"] == 20)
    assert s20["per_round"] == pytest.approx(3000 * 2 / 1e6 + 800 * 10 / 1e6)


def test_once_without_a_key_refuses_and_calls_nothing(tmp_path, world, capsys):
    env = {"DEBATE_PAPER_DB": world["paper"], "DEBATE_DIR": str(tmp_path / "d")}
    assert D.main(["once"], environ=env, transport=Fake(AssertionError("no"))) == 2
    assert "ANTHROPIC_API_KEY가 없습니다" in capsys.readouterr().err
    assert D.main(["once"], environ={**env, "DEBATE_EVERY_MIN": "abc"}) == 2


def test_once_runs_one_round_with_the_injected_transport(tmp_path, world):
    out = []
    env = {"ANTHROPIC_API_KEY": KEY, "DEBATE_PAPER_DB": world["paper"], "DEBATE_DAILY_DB": world["daily"],
           "DEBATE_DIR": str(tmp_path / "d")}
    assert D.main(["once"], environ=env, transport=Fake(ok_body(answer())), out=out.append) == 0
    text = "\n".join(out)
    assert "결과: round" in text and "이번 달" in text and KEY not in text
    s = D.summary(str(tmp_path / "d" / "debate.db"))
    assert s["ready"] and len(s["rounds"]) == 1 and s["rounds"][0]["messages"][0]["speaker"] == "낙관론자"


# ---------------------------------------------------------------- the dashboard
def test_dashboard_route_with_and_without_debate_db(tmp_path, world):
    from paperbot.dash import analysis as AN
    off = AN.debate(str(tmp_path / "nothing" / "debate.db"))
    assert off["ready"] is False and off["state_ko"] == "꺼짐" and off["rounds"] == [] and "꺼짐" in off["note"]
    assert AN.debate(None)["state"] == "off"
    svc = make(tmp_path, world, ok_body(answer(4, [{"speaker": "퀀트", "kind": "parity_streak", "params": {"days": 3}}],
                                                [{"text": "아이디어", "tag": "시간대"}])))
    svc.tick(force=True)
    svc.db.close()
    path = svc.cfg.debate_db
    before = os.path.getmtime(path)
    d = AN.debate(path)
    assert d["ready"] and d["messages"][-1]["speaker"] == "정리" and d["state_ko"] in ("돌고 있음", "꺼짐")
    assert os.path.getmtime(path) == before and not os.path.exists(path + "-wal") and not os.path.exists(path + "-journal")
    s = D.summary(path, NOW + 30_000)
    assert s["state_ko"] == "돌고 있음" and s["rounds"][0]["messages"][0]["speaker"] == "낙관론자"
    assert s["hypotheses"][0]["claim"] == "앞으로 밤 점검 3번이 모두 재계산 불일치 0개다" and s["hypotheses"][0]["status_ko"] == "채점 대기"
    assert s["ideas"][0]["tag"] == "시간대" and s["spend"]["cap"] == 40.0 and s["caution"]
    stale = D.summary(path, NOW + 10 * 60_000)                                  # no heartbeat for 10 minutes: the service is off
    assert stale["state"] == "off" and stale["state_ko"] == "꺼짐" and "마지막 신호" in stale["reason"]


def test_dashboard_page_and_api_through_the_app(tmp_path, world, monkeypatch):
    from paperbot.dash.app import create_app
    from fastapi.testclient import TestClient
    import hashlib
    from paperbot.dash.app import hash_password
    svc = make(tmp_path, world, ok_body(answer()))
    svc.tick(force=True)
    svc.db.close()
    app = create_app(world["paper"], hash_password("pw"), b"s" * 32, debate_db=svc.cfg.debate_db)
    c = TestClient(app)
    r = c.post("/api/login", json={"password": "pw"})
    assert r.status_code == 200
    j = c.get("/api/debate").json()
    assert j["ready"] and j["rounds"] and j["spend"]["cap"] == 40.0
    import shutil
    os.makedirs(tmp_path / "other")
    shutil.copy(world["paper"], tmp_path / "other" / "paper3.db")
    app2 = create_app(str(tmp_path / "other" / "paper3.db"), hash_password("pw"), b"s" * 32)
    c2 = TestClient(app2)
    c2.post("/api/login", json={"password": "pw"})
    assert c2.get("/api/debate").json()["state"] == "off"                        # the default path has no debate.db
    _ = hashlib
    from paperbot.dash import app as appmod
    import inspect
    assert '"debate", "debate.db"' in inspect.getsource(appmod.create_app)


# ---------------------------------------------------------------- the owners' settings: Sonnet 5.5, 30 min, $30, effort low
SONNET_ENV = {"ANTHROPIC_API_KEY": KEY, "DEBATE_MODEL": "claude-sonnet-5-5", "DEBATE_EVERY_MIN": "30",
              "DEBATE_MONTHLY_USD_CAP": "30", "DEBATE_EFFORT": "low"}


def thinking_body(ans, usage):
    """A Sonnet 5.5 answer: an (empty, display omitted) thinking block before the text; output_tokens include it."""
    return 200, {"request-id": "req_t"}, json.dumps({"content": [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": json.dumps(ans, ensure_ascii=False)}], "usage": usage,
        "stop_reason": "end_turn"}).encode()


def test_sonnet_55_effort_low_is_sent_and_its_thinking_is_in_the_cost_and_the_cap(tmp_path, world):
    """D1: the owners' settings reach the request as the API wants them for Sonnet 5.5 (effort inside output_config,
    no 'thinking' field: adaptive by default, never 'disabled', which is a 400 there), the ceiling leaves room for the
    thinking (max_tokens holds thinking + answer), and the thinking tokens, billed inside usage.output_tokens, are in
    the round's cost, the month's spend and the cap's worst case."""
    cfg = D.config_from_env({**SONNET_ENV, "DEBATE_PAPER_DB": world["paper"], "DEBATE_DAILY_DB": world["daily"],
                             "DEBATE_DIR": str(tmp_path / "d")})
    assert (cfg.model, cfg.every_min, cfg.monthly_cap, cfg.effort, cfg.thinking) == ("claude-sonnet-5-5", 30, 30.0,
                                                                                      "low", "")
    assert cfg.max_tokens == D.THINKING_MAX_TOKENS == 1500 and cfg.prices() == (2.0, 10.0) and cfg.cache_ttl() == "1h"
    usage = {"input_tokens": 1500, "output_tokens": 1100, "cache_read_input_tokens": 1700,
             "cache_creation_input_tokens": 0}
    svc = make(tmp_path, world, thinking_body(answer(4), usage), model=cfg.model, every_min=30, monthly_cap=30.0,
               effort="low", max_tokens=cfg.max_tokens)
    assert svc.tick(force=True) == "round"
    _, _, body, _ = svc.fake.calls[0]
    assert body["output_config"] == {"effort": "low"} and "thinking" not in body
    assert body["model"] == "claude-sonnet-5-5" and body["max_tokens"] == 1500
    assert body["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "temperature" not in body and body["messages"][-1]["role"] == "user"           # no sampling, no prefill
    want = (1500 * 2.0 + 1100 * 10.0 + 1700 * 2.0 * 0.1) / 1e6
    rd = rows(svc, "SELECT out_tokens, cost_usd, status, turns FROM debate_rounds")[0]
    assert rd == (1100, pytest.approx(want), "ok", 4)                       # the thinking is in out_tokens and cost
    assert svc.db.spent(NOW)["month"] == pytest.approx(want)
    assert svc.db.get("last_usage")["thinking_blocks"] == 1 and "생각 블록 1개" in svc.logs[-1]
    assert [m[0] for m in rows(svc, "SELECT speaker FROM debate_messages")][:2] == ["낙관론자", "비관론자"]
    assert svc.worst_case_usd(3300) == pytest.approx((3300 * 2.0 * 2.0 + 1500 * 10.0) / 1e6)   # max_tokens bounds it
    run = svc.db.get("run")
    assert run["effort"] == "low" and run["thinking"] == "adaptive(기본)" and run["max_tokens"] == 1500
    s = D.summary(svc.cfg.debate_db, NOW)
    out = []
    D.print_status(s, out.append)
    assert "모델 claude-sonnet-5-5 (effort low) (생각 adaptive(기본)), 30분 간격" in out[1]


def test_settings_a_model_would_refuse_stop_the_service_at_start():
    """A setting the API answers with a 400 every round is refused at start (exit 2), with the fix in Korean."""
    def err(**over):
        with pytest.raises(ValueError) as e:
            D.config_from_env({**SONNET_ENV, **over})
        return str(e.value)
    assert "between_tools" in err(DEBATE_THINKING="disabled")
    assert "Sonnet 5.5 전용" in err(DEBATE_MODEL="claude-sonnet-5", DEBATE_THINKING="between_tools")
    assert "받지 않습니다" in err(DEBATE_MODEL="claude-haiku-4-5-20251001")                    # effort on Haiku
    assert D.main(["status"], environ={**SONNET_ENV, "DEBATE_THINKING": "disabled"}) == 2
    off = D.config_from_env({**SONNET_ENV, "DEBATE_THINKING": "between_tools"})
    assert off.max_tokens == 900 and D.request_body(off, "s", "u")["thinking"] == {"type": "between_tools"}
    assert D.config_from_env({**SONNET_ENV, "DEBATE_MAX_TOKENS": "1200"}).max_tokens == 1200      # the env wins
    haiku = D.config_from_env({"DEBATE_MODEL": "claude-haiku-4-5-20251001"})
    assert haiku.max_tokens == 900 and "output_config" not in D.request_body(haiku, "s", "u")
    assert not D.model_thinks("claude-haiku-4-5-20251001") and D.model_thinks("claude-sonnet-5-5")
    assert not D.model_thinks("claude-sonnet-5-5", "between_tools") and D.model_thinks("claude-opus-5-5")


def test_the_debate_room_runs_on_the_v4_shape(tmp_path, monkeypatch):
    """D1: on the 331-account run every topic builds within the data cap; the packet says which accounts its tables
    count (the 36 and their coin flips) and gives the real group counts; DeepSeek, reel and 5m accounts never enter the
    rank lists; a group's frozen line ('[ds200] signal code refused', CRITICAL) is shown but is no account emergency
    (the agenda does not jump for it); the hypothesis menu keeps to the 36; the dry run works without a key."""
    import urllib.request
    from paperbot.config import DS200_IDS, REEL_NAME, V4_GROUP_ACCOUNTS
    w = make_world(tmp_path, NOW, days=10, per_day=200, v4=True)
    for i in range(len(P.TOPICS)):
        b = P.build(w["paper"], w["daily"], None, None, NOW, round_no=i)
        pk = b["packet"]
        assert b["tokens"] <= P.MAX_PACKET_TOKENS, b["topic"]
        assert pk["meta"]["groups"] == V4_GROUP_ACCOUNTS and pk["meta"]["accounts_in_tables"] == 156
        assert "딥시크" in pk["meta"]["tables_scope"] and "331" in pk["meta"]["observation"]
        assert b["topic"] == P.TOPICS[i][0] and pk["unusual"] == []         # the group line jumps nothing
        assert any(a["text"].startswith("[ds200] signal code refused") for a in pk.get("alerts", []))
        assert not any("[F9_FVG@15m]" in a["text"] for a in pk.get("alerts", []))    # a DeepSeek account: counted
        if b["topic"] == "rank":
            ids = [r["account"] for k in ("accounts_top", "accounts_bottom") for r in pk["rank"][k]]
            ids += [r["strategy"] for k in ("strategies_top", "strategies_bottom") for r in pk["rank"][k]]
            assert ids and not [x for x in ids if x.split("@")[0] in set(DS200_IDS) | {REEL_NAME}]
            assert not [x for x in ids if x.endswith("@5m")]
    # a core account's liquidation still jumps the agenda
    con = sqlite3.connect(w["paper"])
    con.execute("INSERT INTO alerts (ts, level, text) VALUES (?, 'CRITICAL', ?)",
                (NOW - 60_000, "[S2_ST_ROC@15m] LIQUIDATED BTCUSDT 30x lost margin 1500.00"))
    con.commit()
    con.close()
    b = P.build(w["paper"], w["daily"], None, None, NOW, round_no=0)
    assert b["topic"] == "risk" and b["why"] == "이상 징후: 긴급 알림 1건"
    # the hypothesis menu: a DeepSeek or reel account is not a strategy account
    paper = P.open_ro(w["paper"])
    try:
        for aid in (f"{DS200_IDS[0]}@15m", f"{REEL_NAME}@5m"):
            s_, tf = aid.split("@")
            got = D.G.validate({"kind": "strategy_roe_sign", "params": {"strategy": s_, "tf": tf, "op": "<", "n": 5}},
                               paper, None, NOW)
            assert got[0] is None, aid
        assert D.G.validate({"kind": "parity_streak", "params": {"days": 2, "accounts": 331}}, paper, None, NOW)[0]
        assert D.G.run_start(paper) == w["start"]
    finally:
        paper.close()
    # a whole round on the v4 world with the owners' settings, then the dry run (no key, no network)
    cfg_env = {"DEBATE_PAPER_DB": w["paper"], "DEBATE_DAILY_DB": w["daily"], "DEBATE_DIR": str(tmp_path / "d"),
               "DEBATE_AGENTS_DB": str(tmp_path / "a.db"), "DEBATE_CHECKPOINT_DB": str(tmp_path / "c.db")}
    svc = make(tmp_path, w, thinking_body(answer(4), {"input_tokens": 3300, "output_tokens": 900}),
               model="claude-sonnet-5-5", every_min=30, monthly_cap=30.0, effort="low", max_tokens=1500)
    assert svc.tick(force=True) == "round"
    user = svc.fake.calls[0][2]["messages"][0]["content"]
    assert '"groups":{"core":144,"ds200":171,"flip":15,"reel":1}' in user
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    out = []
    env = {k: v for k, v in SONNET_ENV.items() if k != "ANTHROPIC_API_KEY"}
    assert D.main(["once", "--dry-run"], environ={**env, **cfg_env}, out=out.append) == 0
    text = "\n".join(out)
    assert "설정 모델 claude-sonnet-5-5" in text and "(월 한도 $30)" in text and "상한 1,500" in text
    assert "생각(thinking)" in text and "effort low" in text and "캐시가 잡히면" in text
    assert not os.path.exists(str(tmp_path / "d" / "debate.db"))

