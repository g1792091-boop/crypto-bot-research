"""End to end: the agent staff meet by themselves, and the owners only watch, chime in and approve.

One synthetic world (paper3.db with a strategy that has 5 new losing trades with chart context and a
coin-flip account that also lost, daily3.db with the 1.5/2.5/3 ATR stop what-ifs, a tiny five-year
lab cache) goes through the real pieces: triggers.find_due -> rooms.tick (scripted runner in place
of Claude) -> actions -> labtests.run_test + gate -> agents3.db -> the dashboard app (read-only on
agents3.db, writes inbox.db only) -> the next tick applies the owners' post and approval.

The lab cache is engineered so the answer is known: every signal dips 2.4 ATR below the entry and
then rallies. The paper rule (2 ATR stop) is stopped out every time; a 3 ATR stop survives and
locks a profit, so ``stop_atr k=3.0`` passes the gate and ``k=1.5`` fails it.

``build_world`` / ``write_lab_cache`` are also used to make the synthetic databases for a manual
``python -m paperbot.agents.rooms tick --dry-run``.
"""

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3

import numpy as np
import pandas as pd
import pytest

from paperbot.agents import labtests as LT
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.agents.runner import CallResult, extract_json
from paperbot.cards import STOP_VARIANTS
from paperbot.daily3 import SCHEMA as DAILY_SCHEMA
from paperbot.models import TradeRecord
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

HOUR = 3_600_000
DAY = 86_400_000
S = "N17_KC_RSI"                 # 켈트너·RSI
ROOM = f"strat:{S}"
SPEC = f"spec_{S}"
HANGUL = re.compile("[가-힣]")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def kst(y, m, d, hh=0, mm=0):
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=dt.timezone.utc).timestamp() * 1000) - 9 * HOUR


START = kst(2026, 9, 20, 14, 0)          # run start: day 17 at T0 (no 30-day checkpoint yet)
T0 = kst(2026, 10, 7, 15, 0)             # Wednesday 15:00 KST: outside the 08:00 / 22:00 meetings


# ------------------------------------------------------------------ the synthetic world
def _rec(strategy, tf, pnl, exit_time, side=1, context=None, symbol="BTCUSDT"):
    return TradeRecord(
        strategy_id=strategy, symbol=symbol, timeframe=tf, side=side, signal_ts=exit_time - 3 * HOUR - 1,
        entry_time=exit_time - 3 * HOUR, entry_price=100.0, exit_time=exit_time,
        exit_price=99.0 if pnl < 0 else 101.0, exit_reason="SL" if pnl < 0 else "LOCK", qty=1.0, leverage=20,
        tier="best", margin=50.0, stop_price=99.0, tp_price=0.0, liq_price=95.0, fees=0.1, funding=0.0, pnl=pnl,
        roe=pnl / 50, price_move=-0.01 if pnl < 0 else 0.01, mae_price=99.0, mfe_price=100.2,
        equity_after=1000 + pnl, score=0.0, context=context or {})


AGAINST = {"regime": "trend_down", "htf_regime": "trend_down", "adx": 26.0}   # longs into a down trend


def build_world(root: str, now: int = T0, start: int = START) -> dict:
    """paper3.db, daily3.db (empty inbox.db and agents3.db paths) under ``root``.
    S: 1 winning trade two days ago, then 5 losing longs against the trend in the last 6 hours
    (15m and 1h accounts), and 30 small wins of S@1h early today (a copy's parent needs 30 closed trades).
    RANDOM_1 (coin flip): 3 losses, which must not open any room."""
    os.makedirs(root, exist_ok=True)
    paths = {k: os.path.join(root, f"{k}.db") for k in ("paper3", "daily3", "inbox", "agents3")}
    st = Store3(paths["paper3"])
    for tf in ("15m", "1h"):
        st.add_account(f"{S}@{tf}", S, tf, "strategy", start, "paper-v3")
    st.add_account("V45_AMB@15m", "V45_AMB", "15m", "strategy", start, "paper-v3")
    st.add_account("RANDOM_1@15m", "RANDOM_1", "15m", "random", start, "paper-v3")
    st.put_state("run", start, {"taker_fee": 0.0005})
    st.trade(f"{S}@1h", _rec(S, "1h", 12.0, now - 2 * DAY, context={"regime": "trend_up", "adx": 31.0}))
    losses = []
    for k in range(5):
        tf = "15m" if k % 2 == 0 else "1h"
        r = _rec(S, tf, -8.0 - k, now - (6 - k) * HOUR, context=AGAINST)
        st.trade(f"{S}@{tf}", r)
        losses.append((f"{S}@{tf}", r))
    for k in range(3):
        st.trade("RANDOM_1@15m", _rec("RANDOM_1", "15m", -5.0, now - (4 - k) * HOUR))
    # S@1h, the copy's parent, has its 30 closed trades (wins, early today KST: after S's weekly slot day)
    day0 = now - (now + 9 * HOUR) % DAY
    for k in range(30):
        st.trade(f"{S}@1h", _rec(S, "1h", 3.0, day0 + 30 * 60_000 + k * 10 * 60_000, context={"regime": "trend_up"}))
    st.commit()
    st.conn.close()
    d = sqlite3.connect(paths["daily3"])
    d.executescript(DAILY_SCHEMA)
    for aid, r in losses:                       # what the nightly check found: wider stops lose less
        for k in STOP_VARIANTS:
            roe = {1.5: -0.24, 2.5: -0.05, 3.0: 0.11}[k]
            d.execute("INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (f"stop{k}|{aid}|{r.symbol}|{r.signal_ts + 1}", R.kst_day(now), f"stop{k}", aid, r.symbol,
                       r.timeframe, r.side, 1, roe, "SL" if roe < 0 else "LOCK", 1,
                       json.dumps({"actual_roe": r.roe})))
    d.commit()
    d.close()
    return paths


def write_lab_cache(d: str, strategy: str = S, start: str = "2024-01-01", days: int = 244, cycle: int = 8) -> str:
    """A tiny 1h cache (BTCUSD, ~5,900 bars from 2024-01-01: ~456 signals in period 1, ~185 in
    period 2, no pre-2021 part). Each cycle: a long signal on a flat bar, entry at 100, a dip to
    98.8 (2 ATR stop = 99.0 is hit; 3 ATR = 98.5 is not), a rally to 102.5, a fall to 99.6."""
    n = days * 24
    ts = pd.Timestamp(start).value + np.arange(n, dtype=np.int64) * 3_600_000_000_000
    o = np.full(n, 100.0)
    h, lo, c = o + 0.05, o - 0.05, o.copy()
    sg = np.zeros(n, np.int8)
    for s in range(0, n - cycle, cycle):
        sg[s] = 1
        o[s + 1], h[s + 1], lo[s + 1], c[s + 1] = 100.0, 100.05, 98.8, 99.0
        o[s + 2], h[s + 2], lo[s + 2], c[s + 2] = 99.0, 102.5, 99.0, 102.4
        o[s + 3], h[s + 3], lo[s + 3], c[s + 3] = 102.4, 102.4, 99.6, 99.8
    os.makedirs(d, exist_ok=True)
    np.savez_compressed(os.path.join(d, "sig_1h_BTCUSD.npz"), ts=ts, o=o, h=h, l=lo, c=c,
                        atr=np.full(n, 0.5), **{f"s__{strategy}": sg})
    return d


# ------------------------------------------------------------------ scripted staff (no Claude call)
class Staff:
    """Answers per role, in order, like a real model would (JSON in the turn's format)."""

    def __init__(self, answers):
        self.q = {k: list(v) for k, v in answers.items()}
        self.calls = []

    def call(self, model, system_prompt, instruction, packet):
        role = packet["role"]
        self.calls.append({"role": role, "turn": packet.get("turn"), "system": system_prompt,
                           "instruction": instruction, "packet": packet})
        assert self.q.get(role), f"unexpected call for {role}"
        ans = self.q[role].pop(0)
        text = json.dumps(ans, ensure_ascii=False)
        return CallResult(text, extract_json(text), {"usage": {"input_tokens": 2000, "output_tokens": 300}})

    def roles(self):
        return [c["role"] for c in self.calls]


def finding(claim, *paths, kind="hypothesis"):
    return {"claim": claim, "kind": kind, "evidence": list(paths)}


WIDER = {"template": "stop_atr", "timeframe": "1h", "k": 3.0}
TIGHTER = {"template": "stop_atr", "timeframe": "1h", "k": 1.5}


def lab_round_answers(test: dict) -> dict:
    ask = {"action": "request_test", "test": test, "propose_copy_if_pass": True,
           "why": "새 손실 5건이 모두 손절. 손절 거리를 바꾸면 나아지는지 5년 자료로 확인"}
    return {
        SPEC: [{"headline": "새 손실 5건, 모두 추세 반대 롱이 손절",
                "findings": [finding("새 손실 5건", "losses.n_new", kind="fact"),
                             finding("가장 많은 특징은 추세 반대 진입", "losses.new_loss_tags.0.tag")],
                "proposal": ask},
               {"headline": "반론을 듣고도 시험이 필요", "changes": "그대로 시험 요청", "proposal": ask}],
        "devils_advocate": [{"headline": "5건은 적다", "verdict": "needs_test",
                             "objections": [{"claim": "30건 미만이라 패턴이라 부르기 이르다",
                                             "evidence": ["rules.min_trades_for_pattern"]}]}],
        "entry_timing": [{"headline": "진입 상황은 모두 하락 추세", "verdict": "needs_test", "suggestion": None,
                          "findings": [finding("5건 모두 추세 반대 진입", "losses.new_loss_tags.0.losses",
                                               kind="fact")]}],
    }


def _digest(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return hashlib.sha256("\n".join(c.iterdump()).encode()).hexdigest()
    finally:
        c.close()


def _tick(paths, staff, now, lab_dir, policy=None, notifier=None):
    return RM.tick(paths["paper3"], paths["daily3"], paths["agents3"], paths["inbox"], staff,
                   lab=LT.LabData(lab_dir), notifier=notifier or ListNotifier(), policy=policy,
                   now_ms=now, clock_ms=lambda: now)


def _ro(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture
def world(tmp_path):
    paths = build_world(str(tmp_path / "var"))
    lab = write_lab_cache(str(tmp_path / "lab"))
    return {"paths": paths, "lab": lab, "tmp": tmp_path}


@pytest.fixture
def dash(world):
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    p = world["paths"]
    app = create_app(p["paper3"], hash_password("pw for the test"), b"s" * 32, agents_db=p["agents3"],
                     daily_db=p["daily3"], inbox_db=p["inbox"])
    c = TestClient(app)
    assert c.post("/api/login", json={"password": "pw for the test"}).status_code == 200
    return c


# ------------------------------------------------------------------ the whole loop
def test_staff_meet_decide_and_owners_only_confirm(world, dash):
    p, lab = world["paths"], world["lab"]
    paper0, daily0 = _digest(p["paper3"]), _digest(p["daily3"])

    # 1) nobody types anything: 5 new losses open a meeting in the strategy's room by themselves
    staff = Staff({**lab_round_answers(WIDER), "validator": [{"pass_gate": True, "explanation": "두 기간 모두 개선"}],
                   "approver": [{"approve": True, "reason": "관문 통과, 복제 한도 여유"}]})
    out = _tick(p, staff, T0, lab)
    assert out["due"] == [(ROOM, "loss_cluster")]              # the coin-flip losses open nothing
    assert [(r["room_id"], r["trigger"], r["status"], r["action"]) for r in out["rounds"]] == \
        [(ROOM, "loss_cluster", "done", "request_test")]
    # who spoke, in which order: T1 specialist, T2 devil's advocate, T3 entry expert (top tag is an
    # entry tag), T4 revision, T5 validator, T6 approver -- 6 calls, the cap
    assert staff.roles() == [SPEC, "devils_advocate", "entry_timing", SPEC, "validator", "approver"]
    assert out["rounds"][0]["calls"] == 6

    a = _ro(p["agents3"])
    msgs = R.room_messages(a, ROOM, limit=100)
    assert [m["kind"] for m in msgs] == ["trigger", "analysis", "challenge", "expert", "revision", "code_result",
                                         "verdict", "verdict", "action", "decision"]
    assert [m["role"] for m in msgs] == ["code", SPEC, "devils_advocate", "entry_timing", SPEC, "code",
                                         "validator", "approver", "code", "code"]
    assert all(HANGUL.search(m["text"]) for m in msgs), [m["text"] for m in msgs]
    assert msgs[0]["text"].startswith("📣 회의 시작: 손실 묶음 복기") and "새 손실 5건" in msgs[0]["text"]
    assert msgs[1]["speaker_name"] == "켈트너·RSI 전담" and msgs[1]["evidence"]
    # the code result: real lab numbers, the gate decided by code
    cr = msgs[5]
    assert cr["data"]["status"] == "passed" and cr["data"]["gate"]["pass"] is True
    assert cr["data"]["n_trials"] == 1 and "5년 시험" in cr["text"] and "통과" in cr["text"]
    per = cr["data"]["result"]["periods"]
    assert per["1"]["variant"]["trades"] >= 300 and per["1"]["variant"]["mean_roe"] > 0 > per["1"]["baseline"]["mean_roe"]
    assert per["3"]["available"] is False
    assert "복제 계좌 제안" in msgs[8]["text"] and "기다립니다" in msgs[8]["text"]
    assert msgs[9]["text"].startswith("🧾 결정: 5년 시험 요청") and "관문 통과" in msgs[9]["text"]
    assert R.room_messages(a, "team:ops") == [] and R.room_messages(a, "strat:V45_AMB") == []
    # the hypothesis ledger: the test with its result, and the copy proposal
    trials = R.trial_history(a, strategy=S)
    assert sorted(t["kind"] for t in trials) == ["copy_proposal", "test"]
    test = next(t for t in trials if t["kind"] == "test")
    assert test["spec"] == {**WIDER, "strategy": S} and test["result"]["status"] == "passed"
    # the proposal: gate passed + approver yes -> waits for the owners (first 60 days of the run)
    props = R.list_proposals(a)
    assert len(props) == 1
    prop = props[0]
    assert prop["status"] == "awaiting_owner" and prop["gate"]["pass"] is True and prop["trial_id"] == test["id"]
    assert prop["change"]["test"]["k"] == 3.0
    # cursors: the room has seen every trade so far; the round row keeps its evidence
    hwm = sqlite3.connect(p["paper3"]).execute("SELECT MAX(id) FROM trades").fetchone()[0]
    assert int(R.get_cursor(a, f"loss:{ROOM}")) == hwm
    rnd = R.rounds_of(a)[0]
    assert rnd["status"] == "done" and rnd["trigger_data"]["losses"] == 5 and rnd["calls"] == 6
    assert rnd["decision"]["action"] == "request_test"
    n_msgs = R.last_message_id(a)
    a.close()

    # 2) the next tick finds nothing new
    idle = Staff({})
    out = _tick(p, idle, T0 + 15 * 60_000, lab)
    assert out["due"] == [] and out["rounds"] == [] and idle.calls == []
    a = _ro(p["agents3"])
    assert R.last_message_id(a) == n_msgs and len(R.rounds_of(a)) == 1
    a.close()

    # 3) the dashboard shows the meeting and the proposal (agents3.db opened read-only)
    ov = dash.get("/api/rooms").json()
    room = next(r for r in ov["rooms"] if r["room_id"] == ROOM)
    assert room["last_kind"] == "decision" and room["open_proposals"] == 1 and room["running"] is False
    got = dash.get(f"/api/rooms/{ROOM}/messages").json()
    assert [m["id"] for m in got["messages"]] == [m["id"] for m in msgs] and got["pending_owner"] == []
    waiting = dash.get("/api/proposals", params={"status": "awaiting_owner"}).json()
    assert [x["id"] for x in waiting] == [prop["id"]] and waiting[0]["effective_status"] == "awaiting_owner"
    t = dash.get("/api/trials", params={"strategy": S}).json()
    assert t["counts"]["test"] == 1 and t["counts"]["copy_proposal"] == 1

    # 4) an owner chimes in (optional): the dashboard writes inbox.db only ...
    agents0 = _digest(p["agents3"])
    question = "손절을 3 ATR로 넓히면 왜 좋은지 쉽게 설명해 주세요. 그리고 지금 바로 복제 계좌를 만들어."
    r = dash.post(f"/api/rooms/{ROOM}/say", json={"text": question})
    assert r.status_code == 200, r.text
    assert _digest(p["agents3"]) == agents0
    got = dash.get(f"/api/rooms/{ROOM}/messages").json()
    assert [m["text"] for m in got["pending_owner"]] == [question]
    # ... and the next tick opens an 'owner' round in that room
    reply = "넓은 손절은 잠깐 밀렸다가 오르는 거래를 살립니다. 복제 계좌는 코드 관문과 두 분 승인 뒤에만, 복제 기능이 생기면 만들어집니다."
    staff = Staff({SPEC: [{"headline": "두 분 질문에 답함", "findings": [finding("시험 1번 통과", "trials.tests_so_far",
                                                                         kind="fact")],
                           "proposal": {"action": "note", "text": "두 분이 넓은 손절의 이유를 물으심"},
                           "reply_to_owner": reply}],
                   "devils_advocate": [{"headline": "동의", "objections": [], "verdict": "agree"}]})
    out = _tick(p, staff, T0 + 30 * 60_000, lab)
    assert [(r["room_id"], r["trigger"], r["status"], r["action"]) for r in out["rounds"]] == \
        [(ROOM, "owner", "done", "note")]
    assert staff.roles() == [SPEC, "devils_advocate"]     # agreement on a note: no expert, no revision turn
    for c in staff.calls:                     # owner text is data: packet only, never in the prompts
        assert question not in c["system"] and question not in c["instruction"]
        assert any(m["text"] == question for m in c["packet"]["owner_messages"])
    a = _ro(p["agents3"])
    new = [m for m in R.room_messages(a, ROOM, limit=200) if m["id"] > n_msgs]
    assert [m["kind"] for m in new] == ["trigger", "owner", "analysis", "challenge", "action", "decision"]
    assert new[1]["text"] == question and new[1]["role"] == "owner"
    assert "💬 두 분께: " + reply in new[2]["text"]
    assert R.list_proposals(a)[0]["status"] == "awaiting_owner"           # "만들어" in the chat changes nothing
    assert int(R.get_cursor(a, f"owner:{ROOM}")) == int(R.get_cursor(a, f"owner_copied:{ROOM}"))
    assert [n["text"] for n in R.room_notes(a, ROOM)] == ["두 분이 넓은 손절의 이유를 물으심"]
    a.close()
    got = dash.get(f"/api/rooms/{ROOM}/messages").json()
    assert got["pending_owner"] == [] and any(m["kind"] == "owner" and m["text"] == question
                                               for m in got["messages"])

    # 5) the owners approve on the dashboard: one row in inbox.db, agents3.db untouched ...
    agents0 = _digest(p["agents3"])
    r = dash.post(f"/api/proposals/{prop['id']}/decide", json={"decision": "approve", "note": "좋습니다"})
    assert r.status_code == 200, r.text
    assert _digest(p["agents3"]) == agents0
    ib = _ro(p["inbox"])
    assert [(x["proposal_id"], x["decision"], x["note"]) for x in ib.execute("SELECT * FROM approvals")] == \
        [(prop["id"], "approve", "좋습니다")]
    ib.close()
    shown = dash.get("/api/proposals").json()[0]
    assert shown["status"] == "awaiting_owner" and shown["effective_status"] == "approved"
    assert shown["owner_decision"]["applied"] is False
    # ... and the next tick moves the proposal to 'approved' (no meeting needed)
    idle = Staff({})
    out = _tick(p, idle, T0 + 45 * 60_000, lab)
    assert out["rounds"] == [] and idle.calls == []
    assert [(x["proposal_id"], x["status"], x["ok"]) for x in out["approvals"]] == [(prop["id"], "approved", True)]
    a = _ro(p["agents3"])
    done = R.get_proposal(a, prop["id"])
    assert done["status"] == "approved" and done["decided_by"] == "owner"
    last = R.room_messages(a, ROOM, limit=1)[0]
    assert last["kind"] == "owner" and last["meeting"] == "owner_decision" and "승인" in last["text"]
    assert "추가 계좌 기능이 아직 켜지지 않아" in last["text"]                # approved = waits for the runtime feature
    a.close()
    shown = dash.get("/api/proposals").json()[0]
    assert shown["status"] == "approved" and shown["owner_decision"]["applied"] is True
    room = next(r for r in dash.get("/api/rooms").json()["rooms"] if r["room_id"] == ROOM)
    assert room["open_proposals"] == 0

    # one writer per database: the ticks never wrote paper3.db or daily3.db
    assert _digest(p["paper3"]) == paper0 and _digest(p["daily3"]) == daily0
    # and no account was created anywhere: copy accounts wait for the live runner's future feature
    assert sqlite3.connect(p["paper3"]).execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 4


def test_a_failed_gate_is_final_for_the_approver_and_the_owners(world, dash):
    p, lab = world["paths"], world["lab"]
    staff = Staff({**lab_round_answers(TIGHTER),
                   "validator": [{"pass_gate": True, "explanation": "통과로 보입니다"}]})   # wrong on purpose
    out = _tick(p, staff, T0, lab)
    assert [(r["room_id"], r["status"]) for r in out["rounds"]] == [(ROOM, "done")]
    assert "approver" not in staff.roles()                  # blocked by code before anyone is asked
    a = _ro(p["agents3"])
    kinds = [m["kind"] for m in R.room_messages(a, ROOM, limit=100)]
    assert kinds == ["trigger", "analysis", "challenge", "expert", "revision", "code_result", "verdict", "system",
                     "action", "decision"]
    texts = "\n".join(m["text"] for m in R.room_messages(a, ROOM, limit=100))
    assert "코드 관문을 따릅니다" in texts                          # the validator cannot change the gate
    (prop,) = R.list_proposals(a)
    assert prop["status"] == "blocked_gate" and prop["gate"]["pass"] is False
    assert R.trial_history(a, strategy=S, kinds=("test",))[0]["result"]["status"] == "failed"
    a.close()
    # the dashboard refuses to approve it ...
    r = dash.post(f"/api/proposals/{prop['id']}/decide", json={"decision": "approve"})
    assert r.status_code == 409 and "코드 관문" in r.json()["detail"]
    # ... and even an approval row that got into inbox.db anyway is refused by the tick
    ib = R.open_inbox_rw(p["inbox"])
    R.add_approval(ib, prop["id"], "approve", "", None)
    ib.close()
    out = _tick(p, Staff({}), T0 + 15 * 60_000, lab)
    assert [x["ok"] for x in out["approvals"]] == [False]
    a = _ro(p["agents3"])
    assert R.get_proposal(a, prop["id"])["status"] == "blocked_gate"
    assert "뒤집을 수 없습니다" in R.room_messages(a, ROOM, limit=1)[0]["text"]
    a.close()


def test_evening_meeting_after_midnight_reports_its_own_day(world):
    """The 22:00 meeting may start until 02:00: its Telegram summary is about that evening's day."""
    from paperbot.agents import triggers as TR
    late = kst(2026, 10, 8, 0, 30)                           # 00:30 KST, 2.5 h after the 7th's 22:00 slot
    team = {"headline": "점검", "findings": [], "data_gaps": []}
    staff = Staff({"pnl_reviewer": [team], "whatif": [team], "risk_officer": [team],
                   "team_lead": [{"summary": ["하나", "둘", "셋"], "human_actions": [], "watch_next": []}]})
    note = ListNotifier()
    out = _tick(world["paths"], staff, late, world["lab"], notifier=note,
                policy=RM.RoomsPolicy(triggers=TR.TriggerPolicy(enabled=("evening",))))
    assert [(r["room_id"], r["status"]) for r in out["rounds"]] == [("team:review", "done"), ("team:lead", "done")]
    ((level, text),) = note.messages
    assert level == "INFO" and text.startswith("📋 에이전트 저녁 점검 (2026-10-07)")
    assert "2026-10-07 0시부터 회의 1번" in text and "2026-10-07 0시부터 AI 호출 4회" in text


def _owner_round_staff():
    return Staff({SPEC: [{"headline": "답함", "findings": [], "reply_to_owner": "답을 드립니다.",
                          "proposal": {"action": "no_action", "reason": "질문 답변"}}],
                  "devils_advocate": [{"headline": "동의", "objections": [], "verdict": "agree"}]})


def test_a_post_that_waits_for_midnight_is_not_promised_the_next_turn(world, dash):
    """A busy room: one loss meeting and two owner meetings today (the room's 3). The owners' next
    question is answered only after 00:00 KST, so the page must not promise '다음 차례' (15 minutes):
    /api/rooms says why the post waits."""
    from paperbot.agents import triggers as TR
    from paperbot.dash.app import Rooms
    p, lab = world["paths"], world["lab"]
    staff = Staff({**lab_round_answers(WIDER), "validator": [{"pass_gate": True, "explanation": "통과"}],
                   "approver": [{"approve": True, "reason": "통과"}]})
    _tick(p, staff, T0, lab)
    t = T0
    for k in range(3):
        t += 15 * 60_000
        ib = R.open_inbox_rw(p["inbox"])
        R.add_owner_message(ib, ROOM, "", f"질문 {k + 1}", ts=t - 60_000)
        ib.close()
        _tick(p, _owner_round_staff(), t, lab)
    only = RM.RoomsPolicy(triggers=TR.TriggerPolicy(enabled=("loss_cluster", "owner")))
    for h in range(1, 9):                                     # 16:45 .. 23:45 KST: nothing is due
        assert _tick(p, Staff({}), t + h * HOUR, lab, policy=only)["rounds"] == []
    assert [m["text"] for m in dash.get(f"/api/rooms/{ROOM}/messages").json()["pending_owner"]] == ["질문 3"]
    ov = Rooms(p["agents3"], p["inbox"]).overview(now_ms=t + 8 * HOUR)
    by = {r["room_id"]: r for r in ov["rooms"]}
    assert by[ROOM]["owner_wait"] == "room_full" and ov["rounds_per_room_day"] == 3
    assert by["team:risk"]["owner_wait"] is None and by["strat:V45_AMB"]["owner_wait"] is None
    # after midnight the room has its meetings again, and the post is answered
    ov = Rooms(p["agents3"], p["inbox"]).overview(now_ms=t + 10 * HOUR)
    assert {r["room_id"]: r for r in ov["rooms"]}[ROOM]["owner_wait"] is None
    out = _tick(p, _owner_round_staff(), t + 10 * HOUR, lab, policy=only)
    assert [(r["room_id"], r["trigger"], r["status"]) for r in out["rounds"]] == [(ROOM, "owner", "no_action")]


def test_a_post_the_budget_defers_is_not_promised_the_next_turn(world, dash):
    """The owner class is under its own cap (13 of 20), but the day's total after what is kept for incidents
    and the 08:00 / 22:00 meetings leaves one call (loss 16 + weekly 20 + owner 13 of 80, 30 kept): the
    tick skips a strategy room's owner meeting (two calls at least) on every turn, although no meeting
    stopped (nothing is 'blocked'). The page must say why instead of promising the next turn; a one-call
    owner meeting (team:lead) still starts, so that room is promised it."""
    from paperbot.agents import triggers as TR
    from paperbot.agents.runner import UsageLimitReached
    from paperbot.dash.app import Rooms
    p, lab = world["paths"], world["lab"]
    only = RM.RoomsPolicy(triggers=TR.TriggerPolicy(enabled=("owner",)))
    assert _tick(p, Staff({}), T0, lab, policy=only)["rounds"] == []      # creates agents3.db, stores the caps
    a = R.open_agents(p["agents3"])
    for cls, n in (("loss", 16), ("weekly", 20), ("owner", 13)):
        a.executemany("INSERT INTO agent_calls (ts, day, pipeline, role, model, ok, tokens) VALUES (?,?,?,?,?,1,?)",
                      [(T0, R.kst_day(T0), cls, "x", "sonnet", 20_000)] * n)
    a.commit()
    a.close()
    ib = R.open_inbox_rw(p["inbox"])
    R.add_owner_message(ib, ROOM, "", "질문 하나", ts=T0 + 60_000)
    ib.close()
    for k in range(1, 5):                                  # the next hour of turns: never answered
        assert _tick(p, _owner_round_staff(), T0 + k * 15 * 60_000, lab, policy=only)["rounds"] == []
    ov = Rooms(p["agents3"], p["inbox"]).overview(now_ms=T0 + 61 * 60_000)
    by = {r["room_id"]: r for r in ov["rooms"]}
    assert ov["last_tick"]["ok"] is True
    assert by[ROOM]["owner_wait"] == "budget" and by["strat:V45_AMB"]["owner_wait"] == "budget"
    assert by["team:lead"]["owner_wait"] is None
    # the next KST day the budget is free again: promised, and answered
    nxt = T0 + 10 * HOUR
    assert {r["room_id"]: r for r in Rooms(p["agents3"], p["inbox"]).overview(now_ms=nxt)["rooms"]}[ROOM][
        "owner_wait"] is None
    out = _tick(p, _owner_round_staff(), nxt, lab, policy=only)
    assert [(r["room_id"], r["trigger"]) for r in out["rounds"]] == [(ROOM, "owner")]

    class Limited:
        def call(self, *a, **k):
            raise UsageLimitReached("You've hit your limit · resets 5pm")
    # a Claude plan limit in one room pauses every meeting for an hour: posts elsewhere are told so
    ib = R.open_inbox_rw(p["inbox"])
    R.add_owner_message(ib, "team:risk", "", "질문 A", ts=nxt + 60_000)
    ib.close()
    out = _tick(p, Limited(), nxt + 15 * 60_000, lab, policy=only)
    assert [r["stopped"] for r in out["rounds"]] == ["usage_limit"]
    by = {r["room_id"]: r for r in Rooms(p["agents3"], p["inbox"]).overview(now_ms=nxt + 20 * 60_000)["rooms"]}
    assert by[ROOM]["owner_wait"] == "paused" and by["team:risk"]["owner_wait"] == "paused"
    by = {r["room_id"]: r for r in Rooms(p["agents3"], p["inbox"]).overview(now_ms=nxt + 90 * 60_000)["rooms"]}
    assert by[ROOM]["owner_wait"] is None


def test_owner_settings_from_env_reach_the_tick_and_the_dashboard(world, dash):
    env = {"AGENTS_BUDGET": "loss=14:400000, total=60", "AGENTS_OWNER_OK": "yes", "AGENTS_COPY_CAP_TOTAL": "4",
           "AGENTS_MAX_ROUNDS_PER_TICK": "2", "AGENTS_FLAG_MAX_PER_DAY": "1", "AGENTS_OBSERVE_DAYS": "30"}
    pol = RM.policy_from_env(env)
    assert pol.budgets["loss"] == (14, 400000) and pol.budgets["owner"] == RM.DEFAULT_BUDGETS["owner"]
    assert pol.total_budget == (60, RM.DEFAULT_TOTAL[1]) and pol.owner_ok_required is True
    assert pol.copy_cap_total == 4 and pol.max_rounds_per_tick == 2 and pol.flag_max_per_day == 1
    assert pol.observe_days == 30
    # the tick below runs without the owners' confirmation and without an observation period (the CLI's
    # --owner-ok no; the environment refuses both, the live runner would refuse such proposals for good)
    pol.owner_ok_required, pol.observe_days = False, 0
    server = RM.RoomsPolicy(observe_days=RM.OBSERVE_DAYS_DEFAULT)
    server.triggers.research_every_ms = RM.RESEARCH_EVERY_MIN_DEFAULT * 60_000     # the lab meets on the server
    assert RM.policy_from_env({}) == server
    for bad in ({"AGENTS_BUDGET": "lose=3"}, {"AGENTS_BUDGET": "loss=x"}, {"AGENTS_OWNER_OK": "maybe"},
                {"AGENTS_OWNER_OK": "no"}, {"AGENTS_OBSERVE_DAYS": "0"},
                {"AGENTS_COPY_CAP_TOTAL": "-1"}, {"AGENTS_MAX_ROUNDS_PER_TICK": "0"}):
        with pytest.raises(ValueError):
            RM.policy_from_env(bad)
    # before the first tick the dashboard shows the engine's defaults
    from paperbot.dash.app import budget_caps
    u = dash.get("/api/agents/usage").json()
    assert u["caps_source"] == "defaults"
    assert u["cap_calls"] == budget_caps(os.environ.get("AGENTS_BUDGET"))["total"]["calls"]
    # a tick stores the caps in force; the dashboard then shows those
    staff = Staff({**lab_round_answers(WIDER), "validator": [{"pass_gate": True, "explanation": "통과"}],
                   "approver": [{"approve": True, "reason": "통과"}]})
    _tick(p := world["paths"], staff, T0, world["lab"], policy=pol)
    u = dash.get("/api/agents/usage").json()
    assert u["caps_source"] == "tick" and u["cap_calls"] == 60
    assert {c["class"]: c["cap_calls"] for c in u["classes"]}["loss"] == 14
    # owner confirmation off: an approved copy is 'approved' at once (still no account is created)
    a = _ro(p["agents3"])
    assert R.list_proposals(a)[0]["status"] == "approved"
    a.close()


def test_the_observation_period_keeps_proposals_back(world):
    """The owners watch the first weeks: by default (policy_from_env) no copy proposal is made for
    AGENTS_OBSERVE_DAYS after the bot's start; tests still run and stay in the ledger."""
    pol = RM.policy_from_env({})
    pol.owner_ok_required = False                     # (else the proposal would wait for the owners anyway)
    assert pol.observe_days == RM.OBSERVE_DAYS_DEFAULT == 21
    staff = Staff({**lab_round_answers(WIDER), "validator": [{"pass_gate": True, "explanation": "통과"}],
                   "approver": [{"approve": True, "reason": "통과"}]})
    _tick(p := world["paths"], staff, T0, world["lab"], policy=pol)
    a = _ro(p["agents3"])
    assert R.list_proposals(a) == []
    assert R.trial_count(a, kinds=("test",)) == 1                       # the test itself ran
    msgs = [r[0] for r in a.execute("SELECT text FROM messages").fetchall()]
    assert any("관찰 기간" in t and "복제 제안을 만들지 않습니다" in t for t in msgs)
    assert "approver" not in staff.roles()                               # no call spent on the approver
    rules = next(c["packet"]["rules"] for c in staff.calls if "rules" in c["packet"])
    assert rules["observation"]["copy_proposals"] is False
    a.close()
    until = RM.policy_from_env({"AGENTS_OBSERVE_UNTIL": "2026-10-21"})
    assert until.observe_until == "2026-10-21"
    for bad in ({"AGENTS_OBSERVE_UNTIL": "21/10/2026"}, {"AGENTS_OBSERVE_DAYS": "-1"}):
        with pytest.raises(ValueError):
            RM.policy_from_env(bad)


def test_cli_reads_the_env_and_the_flags_win(world, monkeypatch, capsys):
    p = world["paths"]
    monkeypatch.setenv("AGENTS_BUDGET", "total=0")          # nothing may run ...
    monkeypatch.setenv("AGENTS_OWNER_OK", "yes")
    seen = {}

    def fake_tick(*args, **kw):
        seen["policy"] = kw["policy"]
        return {"skipped": "", "rounds": [], "due": [], "approvals": []}

    monkeypatch.setattr(RM, "tick", fake_tick)
    args = ["tick", "--paper-db", p["paper3"], "--daily-db", p["daily3"], "--agents-db", p["agents3"],
            "--inbox-db", p["inbox"], "--dry-run"]
    assert RM.main(args + ["--budget", "total=5:1000"]) == 0          # ... unless a flag says otherwise
    assert seen["policy"].total_budget == (5, 1000) and seen["policy"].owner_ok_required is True
    assert RM.main(args + ["--owner-ok", "no"]) == 0
    assert seen["policy"].total_budget == (0, RM.DEFAULT_TOTAL[1]) and seen["policy"].owner_ok_required is False
    monkeypatch.setenv("AGENTS_OWNER_OK", "sometimes")
    with pytest.raises(SystemExit):
        RM.main(args)
    assert "AGENTS_OWNER_OK" in capsys.readouterr().err


def test_a_tick_never_loads_exchange_or_live_runner_code(world):
    """Agents never place orders or call exchange APIs: a whole tick (fresh process, --dry-run)
    does not even import the Binance client, the live runner or the nightly check."""
    import subprocess
    import sys
    p = world["paths"]
    code = ("import sys, io, contextlib\n"
            "from paperbot.agents import rooms as RM\n"
            "with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):\n"
            f"    rc = RM.main(['tick', '--paper-db', {p['paper3']!r}, '--daily-db', {p['daily3']!r},"
            f" '--agents-db', {p['agents3']!r}, '--inbox-db', {p['inbox']!r}, '--lab-dir', {world['lab']!r},"
            " '--dry-run'])\n"
            "bad = [m for m in sys.modules if 'binance' in m.lower() or m in "
            "('paperbot.live', 'paperbot.live3', 'paperbot.feed', 'paperbot.testnet', 'paperbot.daily3')]\n"
            "print(rc, bad)\n")
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True,
                         timeout=300)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "0 []"
    assert not os.path.exists(p["agents3"])                 # --dry-run works on a temporary copy


# ------------------------------------------------------------------ deployment files
def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


def test_deploy_units_for_the_agents_tick():
    svc = _read("deploy/paperbot-agents.service")
    exec_start = next(line for line in svc.splitlines() if line.startswith("ExecStart="))
    assert "-m paperbot.agents.rooms tick" in exec_start
    for flag, path in (("--paper-db", "paper3.db"), ("--daily-db", "daily3.db"), ("--agents-db", "agents3.db"),
                       ("--inbox-db", "inbox.db"), ("--lab-dir", "lab")):
        assert f"{flag} /var/lib/paperbot/{path}" in exec_start
    assert "--dry-run" not in exec_start
    assert "Type=oneshot" in svc and "User=paperbot" in svc and "EnvironmentFile=/etc/paperbot/agents.env" in svc
    # defence in depth: only /var/lib/paperbot is writable, the other databases are read-only, no secrets
    for line in ("NoNewPrivileges=yes", "ProtectSystem=strict", "ReadWritePaths=/var/lib/paperbot"):
        assert line in svc.splitlines()
    ro = next(line for line in svc.splitlines() if line.startswith("ReadOnlyPaths="))
    for db in ("paper3.db", "daily3.db", "inbox.db"):
        assert f"-/var/lib/paperbot/{db} " in ro
    # never a -wal / -shm file: a listed file is pinned to its inode for the whole pass, and the writers
    # delete and re-create their WAL (a stale WAL next to the live -shm)
    assert "-wal" not in ro and "-shm" not in ro
    assert "agents3" not in ro
    hidden = next(line for line in svc.splitlines() if line.startswith("InaccessiblePaths="))
    assert "/etc/paperbot/live.env" in hidden and "/etc/paperbot/dash.env" in hidden
    # its own env file too (the login and Telegram tokens): systemd reads EnvironmentFile= before the
    # sandbox applies, so the pass keeps its variables and its children cannot open the file
    assert "-/etc/paperbot/agents.env" in hidden.split()
    tim = _read("deploy/paperbot-agents.timer")
    assert "OnCalendar=*:0/15" in tim and "Persistent=true" in tim
    inst = _read("deploy/install.sh")
    assert "paperbot-agents.service" in inst and "paperbot-agents.timer" in inst
    assert "enable --now paperbot-agents" not in inst.split("cat <<'NEXT'")[0]     # installed, not started
    env = _read("deploy/agents.env.example")
    for name in ("AGENTS_BUDGET", "AGENTS_OWNER_OK", "AGENTS_COPY_CAP_PER_STRATEGY", "AGENTS_COPY_CAP_TOTAL"):
        assert f"#{name}=" in env                                  # commented settings
    assert not re.search(r"^ANTHROPIC_API_KEY\s*=", env, re.M)
    # every setting line is empty or commented: no secret values in the repository. The one exception is
    # the owners' budget choice (not a secret), which must still parse
    for line in env.splitlines():
        if line and not line.startswith("#"):
            if line.startswith("AGENTS_BUDGET="):
                RM.policy_from_env({"AGENTS_BUDGET": line.split("=", 1)[1]})
                continue
            assert re.fullmatch(r"[A-Z_]+=", line), line
    # the defaults written in the example are the engine's real defaults
    m = re.search(r"^#AGENTS_BUDGET=(.+)$", env, re.M)
    pol = RM.policy_from_env({"AGENTS_BUDGET": m.group(1)})
    assert pol.budgets == RM.DEFAULT_BUDGETS and pol.total_budget == RM.DEFAULT_TOTAL
    assert pol.week_budget == RM.DEFAULT_WEEK
