"""#88: the eight agent-scoring improvements the owners approved on 2026-10-05 (the review of the friend's agents.js):
easy predictions earn nothing, 중립 is judged against simple answers, the chair states what would change its mind,
the bull and the bear argue blind to our positions (in an alternating order), the chair looks back at its last graded
call, the debate room's record is one room-wide number against a coin flip, each AI text records its model and prompt
version, and a stopped liquidation feed reads "수집 안 됨" instead of zero."""
import json
import re
import sqlite3
from types import SimpleNamespace

from paperbot import daily3
from paperbot.agents import committee as CM
from paperbot.agents import debate as D
from paperbot.agents import debate_grade as G
from paperbot.agents import rooms as RM
from paperbot.agents import triggers as TR
from paperbot.store3 import Store3

HOUR = 3_600_000
DAY = 86_400_000
NOW = 1_791_158_400_000 + 10 * DAY


# ---------------------------------------------------------------- 1 + 2: simple answers are the bar, not only 50%
def _rows(moves, direction="중립"):
    return [{"move": m, "correct": int(CM.judge(direction, m))} for m in moves]


def test_score_compares_with_always_up_neutral_and_down():
    rows = _rows([0.001, -0.002, 0.003, 0.0, 0.02])           # a quiet week: 중립 is right 4 days of 5 by itself
    sc = CM._score(rows)
    assert sc["correct"] == 4 and sc["always_neutral_correct"] == 4 and sc["always_up_correct"] == 1
    assert sc["always_down_correct"] == 0 and sc["best_simple"] == {"answer": "늘 중립", "correct": 4, "rate": 0.8}
    assert sc["vs_best_simple"] == 0                     # always saying 중립 earns as much: no skill shown
    assert sc["small_sample"] is True
    empty = CM._score([])
    assert "best_simple" not in empty and empty["hit_rate"] is None


def test_chair_call_keeps_what_would_change_its_mind_and_the_record_shows_it(tmp_path):
    call, why = CM.parse_call({"direction": "상승", "confidence": 2, "change_mind": "  7일 저가 아래로\n마감하면 하락 "})
    assert why == "" and call == {"direction": "상승", "confidence": 2, "change_mind": "7일 저가 아래로 마감하면 하락"}
    assert CM.parse_call({"direction": "중립", "confidence": 1})[0] == {"direction": "중립", "confidence": 1}
    c = sqlite3.connect(str(tmp_path / "agents3.db"))
    rid = CM.record(c, day="2026-10-06", symbol="BTCUSDT", round_id=1, call=call, why="", ref=(NOW, 100.0), now_ms=NOW)
    data = json.loads(c.execute("SELECT data FROM committee_calls WHERE id = ?", (rid,)).fetchone()[0])
    assert data["change_mind"] == "7일 저가 아래로 마감하면 하락"
    c.execute("UPDATE committee_calls SET status = 'graded', move = 0.01, correct = 1, graded_ts = ? WHERE id = ?",
              (NOW + DAY, rid))
    c.commit()
    tr = CM.track_record(c)
    assert tr["recent"][0]["change_mind"] == "7일 저가 아래로 마감하면 하락"
    assert tr["last_graded"]["correct"] is True and tr["last_graded"]["change_mind"].startswith("7일")
    assert "표본 작음" in tr["period_note"] and "늘 중립" in tr["rule"]
    assert tr["best_simple"]["answer"] == "늘 상승"


# ---------------------------------------------------------------- 3 + 4 + 5: the chair's format and a fair debate
def test_chair_format_asks_for_the_change_of_mind_and_the_look_back():
    sys_text = RM.system_prompt("team_lead", "lead", "bull_bear")
    assert '"change_mind"' in sys_text and '"retro"' in sys_text and "판단이 바뀌는 조건" in sys_text
    assert "중립이나 확신 1이 정직" not in sys_text          # the chair is no longer told "unsure: say 중립"
    assert "best_simple" in sys_text and "수집 안 됨" in sys_text


def test_lead_check_keeps_retro_and_flags_a_missing_change_of_mind():
    given = {"meeting": {"trigger": "bull_bear"}}
    out = {"summary": ["a", "b", "c"], "call": {"direction": "하락", "confidence": 1}, "retro": "지난 판정은 맞았지만 하루치"}
    clean, problems = RM.CHECKS["lead"](out, given)
    assert clean["call"] == {"direction": "하락", "confidence": 1} and clean["retro"] == "지난 판정은 맞았지만 하루치"
    assert any("change_mind" in p for p in problems)
    out["call"]["change_mind"] = "BTC가 1% 넘게 오르면 중립"
    clean, problems = RM.CHECKS["lead"](out, given)
    assert clean["call"]["change_mind"] == "BTC가 1% 넘게 오르면 중립" and not any("change_mind" in p for p in problems)


def test_room_line_shows_the_change_of_mind_and_the_look_back(tmp_path):
    posted = []
    c = sqlite3.connect(str(tmp_path / "agents3.db"))
    rnd = SimpleNamespace(ctx=SimpleNamespace(agents_conn=c, now_ms=NOW, clock=lambda: NOW), due=_due("2026-10-06"),
                          base={"committee": {"reference": {"ts": NOW, "price": 100.0}}}, round_id=7, spoke=["bull"],
                          post=lambda *a, **k: posted.append(a))
    lead = {"call": {"direction": "하락", "confidence": 1, "change_mind": "7일 고가를 넘으면 상승"},
            "retro": "어제 상승 판정은 맞았지만 하루치라 운일 수 있음"}
    RM.record_call(rnd, lead)
    text = posted[0][2]
    assert "판단이 바뀌는 조건: 7일 고가를 넘으면 상승" in text and "지난 판정 돌아보기(팀장): 어제" in text
    data = json.loads(c.execute("SELECT data FROM committee_calls").fetchone()[0])
    assert data["retro"].startswith("어제") and data["change_mind"] == "7일 고가를 넘으면 상승"


def _due(slot):
    return TR.Due(room_id="team:market", trigger="bull_bear", priority=1, data={"slot": slot, "symbol": "BTCUSDT"},
                  meeting="bull_bear:" + slot)


def test_who_speaks_first_alternates_by_day():
    a = [r for r, _ in RM.team_plan(_due("2026-10-06"))]
    b = [r for r, _ in RM.team_plan(_due("2026-10-07"))]
    assert a[2:] == b[2:] == ["risk_officer", "team_lead"]
    assert {a[0], a[1]} == {b[0], b[1]} == {"bull", "bear"} and a[0] != b[0]


def test_bull_and_bear_do_not_see_our_positions_or_past_calls():
    committee = {"coin": "BTC", "price": 1.0, "ours": {"open": {"long": 3}}, "track_record": {"graded": 4},
                 "track_record_coin": {"graded": 1}, "returns": {"24h": 0.01}}
    rnd = SimpleNamespace(ctx=SimpleNamespace(), due=_due("2026-10-06"), base={"committee": committee})
    for role in ("bull", "bear"):
        pk = RM._team_packet(rnd, role, {})
        assert set(pk["committee"]) == {"coin", "price", "returns", "hidden"}, role
        assert "ours" in rnd.base["committee"]                       # the shared base is not changed
    pk = RM._team_packet(rnd, "risk_officer", {})
    assert pk["committee"]["ours"] == {"open": {"long": 3}} and "hidden" not in pk["committee"]


# ---------------------------------------------------------------- 7: model and prompt version with each message
def test_each_ai_message_records_its_model_and_prompt_version():
    by = RM.written_by("sonnet", "같은 지시문", SimpleNamespace(meta={"model": "claude-sonnet-5-5"}))
    assert by["model"] == "sonnet" and re.fullmatch(r"[0-9a-f]{12}", by["prompt_version"])
    assert by["served_model"] == "claude-sonnet-5-5"
    assert RM.written_by("sonnet", "같은 지시문")["prompt_version"] == by["prompt_version"]
    assert RM.written_by("sonnet", "바뀐 지시문")["prompt_version"] != by["prompt_version"]
    assert "served_model" not in RM.written_by("haiku", "x", SimpleNamespace(meta={"model": "haiku"}))


def test_debate_rounds_store_the_prompt_version(tmp_path):
    path = str(tmp_path / "debate.db")
    old = sqlite3.connect(path)                          # a debate.db from before #88: no prompt_version column
    old.executescript(D.SCHEMA)
    old.close()
    db = D.DB(path)
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(debate_rounds)")}
    assert "prompt_version" in cols and re.fullmatch(r"[0-9a-f]{12}", D.prompt_version())
    db.close()
    D.DB(path).close()                                   # opening again keeps working


# ---------------------------------------------------------------- 1 + 6: easy claims, the room's record vs chance
def _paper(tmp_path, busts=0, n=3):
    paper = str(tmp_path / "paper3.db")
    st = Store3(paper)
    ids = [f"S{i}@15m" for i in range(n)]
    for a in ids:
        st.add_account(a, a.split("@")[0], "15m", "strategy", NOW - 10 * DAY, "paper-v4")
    st.put_state("accounts", NOW, {"engines": {a: {"bust": i < busts} for i, a in enumerate(ids)}})
    st.commit()
    return sqlite3.connect(f"file:{paper}?mode=ro", uri=True)


def _daily(tmp_path, nights, name="daily3.db"):
    path = str(tmp_path / name)
    d = sqlite3.connect(path)
    d.executescript(daily3.SCHEMA)
    for i, bad in enumerate(nights):
        d.execute("INSERT INTO reports (day, ts, data) VALUES (?, ?, ?)",
                  (f"2026-10-{i + 1:02d}", i, json.dumps({"parity": {"accounts": 3, "mismatched_accounts": bad}})))
    d.commit()
    return d


def test_settled_bust_claims_are_dropped(tmp_path):
    p = _paper(tmp_path, busts=2, n=3)
    c, why, _ = G.validate({"kind": "busts_by_day", "params": {"day": 20, "max_busts": 3}}, p, None, NOW)
    assert c is None and "쉬운 예측" in why
    c, why, _ = G.validate({"kind": "busts_by_day", "params": {"day": 20, "max_busts": 1}}, p, None, NOW)
    assert c is None and "이미 정해진" in why
    c, why, _ = G.validate({"kind": "busts_by_day", "params": {"day": 20, "max_busts": 2}}, p, None, NOW)
    assert c is not None and why == ""


def test_parity_claim_carries_its_base_rate(tmp_path):
    d = _daily(tmp_path, [0] * 9 + [1])                  # 9 clean nights of 10
    c, _, _ = G.validate({"kind": "parity_streak", "params": {"days": 2}}, None, d, NOW)
    assert c["params"]["base_rate"] == 0.81
    few = _daily(tmp_path, [0, 0], "few.db")
    c2, _, _ = G.validate({"kind": "parity_streak", "params": {"days": 2}}, None, few, NOW)
    assert "base_rate" not in c2["params"]               # too few nights: unknown, never guessed


def test_scoreboard_is_one_room_number_against_chance(tmp_path):
    db = D.DB(str(tmp_path / "debate.db"))

    def add(speaker, outcome, base=None):
        params = {"days": 1, **({"base_rate": base} if base is not None else {})}
        db.conn.execute("INSERT INTO debate_hypotheses (ts, speaker, kind, params_json, status, outcome) "
                        "VALUES (1, ?, 'parity_streak', ?, 'graded', ?)",
                        (speaker, json.dumps({"kind": "parity_streak", "params": params}), outcome))
    add("낙관론자", "hit", 0.95)                          # easy: kept out of the rate
    add("낙관론자", "hit", 0.9)
    add("비관론자", "miss", 0.3)
    add("퀀트", "hit")                                    # unknown base rate: 0.5
    db.conn.commit()
    sb = G.scoreboard(db.conn)
    assert sb["graded"] == 2 and sb["hit"] == 1 and sb["rate"] == 0.5
    assert sb["easy"] == {"graded": 2, "hit": 2, "rate_from": G.EASY_RATE}
    assert sb["expected_hits"] == 0.8 and sb["expected_rate"] == 0.4
    assert sb["coin_flip_rate"] == 0.5 and sb["p_vs_coin_flip"] == 0.75 and sb["small"] is True
    db.close()


# ---------------------------------------------------------------- 8: a stopped feed is "수집 안 됨", never zero
def _liq(tmp_path, rows):
    path = str(tmp_path / "liq.db")
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE liq (symbol TEXT, side TEXT, trade_ts INTEGER, qty REAL, price REAL, filled_qty REAL, "
              "avg_price REAL)")
    c.executemany("INSERT INTO liq VALUES (?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()
    return path


def test_liquidations_say_not_collected_when_the_feed_is_missing_or_stopped(tmp_path):
    gone = CM.liq_view(str(tmp_path / "none.db"), "BTCUSDT", NOW - DAY, NOW)
    assert gone["collected"] is False and gone["status_ko"] == "수집 안 됨" and "longs_liquidated" not in gone
    stale = _liq(tmp_path, [("ETHUSDT", "SELL", NOW - 5 * HOUR, 1, 100, 1, 100)])
    v = CM.liq_view(stale, "BTCUSDT", NOW - DAY, NOW)
    assert v["collected"] is False and "시간 전" in v["why"]


def test_liquidations_count_when_the_feed_is_live(tmp_path):
    live = _liq(tmp_path, [("BTCUSDT", "SELL", NOW - 2 * DAY, 1, 100, 1, 100),
                           ("BTCUSDT", "SELL", NOW - HOUR, 2, 100, 2, 100),
                           ("ETHUSDT", "BUY", NOW - 60_000, 1, 10, 1, 10)])
    v = CM.liq_view(live, "BTCUSDT", NOW - DAY, NOW)
    assert v["collected"] is True and v["longs_liquidated"] == 1 and v["longs_usd"] == 200 and "partial" not in v
    quiet = CM.liq_view(live, "SOLUSDT", NOW - DAY, NOW)  # the feed is live, this coin simply had none: a real zero
    assert quiet["collected"] is True and quiet["longs_liquidated"] == quiet["shorts_liquidated"] == 0
