"""Real-trading readiness check (agents/readiness.py, owners approved 2026-10-04): the addendum's Q6 / Q3 conditions
quoted with their document lines, each account's ✅ / ❌ / '아직 판단 불가' with the numbers, the summary '실거래 조건:
충족 N개', that it only reads (never enables anything), and where it is shown: the lead's daily view
(board.readiness), the 30-day checkpoint meeting (packet root ``readiness``), the Friday risk packet and the
Sunday report's one line."""

import hashlib
import json
import os
import re

import pytest

from paperbot import checkpoint as CP
from paperbot.agents import digest as DG
from paperbot.agents import readiness as RD
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.store3 import Store3

from test_new_meetings import bulk, tpol
from test_rooms import DAY, MIN, START, QueueRunner, World, S, kst, team_answer
from test_rooms_round3 import DAY30, LEAD, write_verdict

V45 = "V45_AMB"
NOW = START + 31 * DAY
OK, NO, UNK = RD.OK, RD.NO, RD.UNKNOWN


def seed(w):
    """N17 (S): 15m 210 trades, plus in two regimes; 30m 40 trades, plus; 1h 5 trades. V45 15m: 50 losing trades."""
    w.store.add_account(f"{S}@30m", S, "30m", "strategy", START, "paper-v3")
    bulk(w, 120, NOW - DAY, aid=f"{S}@15m", pnl=2.0, step=10 * MIN, context={"regime": "trend_up"})
    bulk(w, 90, NOW - 3 * DAY, aid=f"{S}@15m", pnl=1.0, step=10 * MIN, context={"regime": "box"})
    bulk(w, 40, NOW - DAY, aid=f"{S}@30m", pnl=1.0, step=30 * MIN, context={"regime": "trend_up"})
    bulk(w, 5, NOW - DAY, aid=f"{S}@1h", pnl=3.0, step=HOUR_, context={"regime": "chop"})
    bulk(w, 50, NOW - DAY, aid=f"{V45}@15m", pnl=-1.0, step=10 * MIN, context={"regime": "trend_down"})
    w.store.fill_costs([{"ts": NOW - DAY, "account_id": f"{S}@15m", "symbol": "BTCUSDT", "event": "entry",
                         "status": "ok", "notional": 1000.0, "slip_best": 0.0004}])
    w.store.commit()


HOUR_ = 3_600_000


def verdict(tmp_path):
    path = str(tmp_path / "checkpoint.db")
    row = lambda st, p, tf="15m": {"status": st, "stage": "1차", "timeframe": tf, "trades": 40, "equity": 5600.0,  # noqa: E731
                                   "pnl": 600.0, "p": p, "q": None if p is None else p * 2, "reason": "r"}
    write_verdict(path, "2026-10-20", {f"{S}@15m": row(CP.PASS2, 0.0005), f"{V45}@15m": row(CP.FAIL, 0.6),
                                       f"{S}@30m": row(CP.HOLD, None, "30m")})
    return path


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_every_condition_quotes_its_document_line():
    root = os.path.join(os.path.dirname(__file__), "..")
    for c, (cid, _label, doc, raw) in zip(RD.conditions(), RD.CONDITIONS):
        assert c["id"] == cid and c["line"], c
        with open(os.path.join(root, doc), encoding="utf-8") as fh:
            assert raw in fh.read().splitlines()[c["line"] - 1]
    assert [n["line"] for n in RD.notes()] == [n["line"] for n in RD.notes() if n["line"]]
    assert {c["id"] for c in RD.conditions()} >= {"trades200", "q1_fdr", "regimes2", "neighbour_tf", "cost_ratio"}
    assert any("코드는 이 조건을 대신 판정하지 않습니다" in n["quote"] for n in RD.notes())


def test_each_account_condition_with_its_numbers(world, tmp_path):
    seed(world)
    full = RD.evaluate(world.paper(), NOW, RD.checkpoint_view(verdict(tmp_path)))
    acc = {r["account"]: r for r in full["accounts"]}
    a = acc[f"{S}@15m"]
    cs = a["conditions"]
    assert cs["day30"] == {"status": OK, "days": 31.0, "need": 30}
    assert cs["trades200"]["status"] == OK and cs["trades200"]["trades"] == 210
    assert cs["q1_fdr"]["status"] == OK and cs["q1_fdr"]["verdict"] == CP.PASS2 and cs["second_check"]["status"] == OK
    assert cs["regimes2"]["status"] == OK and set(cs["regimes2"]["plus"]) == {"상승 추세", "박스권"}
    assert cs["neighbour_tf"]["status"] == OK and cs["neighbour_tf"]["neighbours"]["30m"] == {"trades": 40, "pnl": 40.0}
    assert cs["cost_ratio"]["status"] == UNK and cs["cost_ratio"]["reference"] == {"orders": 1, "ratio": 1.286}
    assert cs["testnet"]["status"] == UNK
    assert a["marks"] == "✅✅✅✅✅✅??" and a["met"] == 6 and a["data_all_met"] and not a["all_met"]
    v = acc[f"{V45}@15m"]["conditions"]
    assert v["q1_fdr"]["status"] == NO and v["second_check"]["status"] == NO and v["trades200"]["status"] == NO
    assert v["regimes2"]["status"] == NO and v["regimes2"]["plus"] == []
    assert v["neighbour_tf"]["status"] == UNK                                  # no V45 5m / 30m account here
    h = acc[f"{S}@1h"]["conditions"]
    assert h["regimes2"]["status"] == UNK and "5건" in h["regimes2"]["why"] and h["neighbour_tf"]["status"] == UNK
    assert h["q1_fdr"]["status"] == UNK and "판정에 이 계좌가 없음" in h["q1_fdr"]["why"]
    assert acc[f"{S}@30m"]["conditions"]["q1_fdr"]["status"] == UNK                # 보류
    s = full["summary"]
    assert s["headline"] == "실거래 조건: 충족 0개" and s["met_all"] == 0 and s["data_met_all"] == 1
    assert s["by_condition"]["testnet"] == {OK: 0, NO: 0, UNK: 5} and "Q6-6" in s["q6_6"]
    assert full["accounts"][0]["account"] == f"{S}@15m"                            # closest first
    assert full["strategies"][0]["strategy"] == S and full["strategies"][0]["best"]["account"] == f"{S}@15m"


def test_before_the_first_verdict_and_the_4h_observation(world):
    seed(world)
    full = RD.evaluate(world.paper(), START + 10 * DAY, {"ready": False, "next": "2026-10-20 09:00 KST"})
    a = next(r for r in full["accounts"] if r["account"] == f"{S}@15m")
    assert a["conditions"]["day30"]["status"] == NO and a["conditions"]["q1_fdr"]["status"] == UNK
    assert "체크포인트 판정 전 (다음 2026-10-20 09:00 KST)" == a["conditions"]["q1_fdr"]["why"]
    q1, sec = RD._q1({"status": CP.OBSERVE, "p": None, "q": None}, {"ready": True, "date": "2026-10-20"})
    assert q1["status"] == NO and "관찰용" in q1["why"] and sec["status"] == NO
    q1, sec = RD._q1({"status": CP.PASS1, "p": 0.0005, "q": 0.03}, {"ready": True, "date": "2026-10-20"})
    assert q1["status"] == OK and sec["status"] == UNK and "2차" in sec["why"]
    assert RD.evaluate(None, NOW)["error"] == "paper3.db 없음"


def test_it_only_reads_and_enables_nothing(world, tmp_path):
    seed(world)
    path = verdict(tmp_path)
    digest = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()  # noqa: E731
    before = (digest(world.paths["paper"]), digest(path))
    RD.evaluate(world.paper(), NOW, RD.checkpoint_view(path))
    assert (digest(world.paths["paper"]), digest(path)) == before
    src = open(RD.__file__, encoding="utf-8").read()
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE INTO|set_cursor|put_state|commit)\b", src)
    assert not re.search(r"^\s*(from|import)\s+\S*(executor|live3|testnet|mainnet|binance|risk)\b", src, re.M)
    assert RD.LABEL == "표시만: 아무것도 켜거나 바꾸지 않음"


def test_compact_meeting_and_line_stay_small_with_180_accounts(tmp_path):
    from paperbot.agents.roster3 import STRATEGY_KO
    st = Store3(str(tmp_path / "paper.db"))
    t0 = START
    for s in STRATEGY_KO:
        for tf in RD.TFS:
            st.add_account(f"{s}@{tf}", s, tf, "strategy", t0, "paper-v3")
    st.commit()
    from test_rooms import rec
    for i, s in enumerate(STRATEGY_KO):
        for tf in RD.TFS:
            for k in range(35):
                st.trade(f"{s}@{tf}", rec(s, tf, 1.0 if (k + i) % 3 else -1.0, t0 + DAY + k * HOUR_,
                                          context={"regime": ("trend_up", "box", "chop")[k % 3]}))
    st.commit()
    full = RD.evaluate(R.open_ro(str(tmp_path / "paper.db")), NOW, {"ready": False})
    assert full["summary"]["accounts"] == 180 and len(full["strategies"]) == 36
    c = RD.compact(full)
    assert c["headline"] == "실거래 조건: 충족 0개" and len(c["closest"]) == 5 and len(c["by_condition"]) == 8
    assert len(json.dumps(c, ensure_ascii=False)) < 2_500
    m = RD.meeting(full)
    assert m["accounts_left_out"] == 172 and len(m["strategies"]) == 36 and m["strategies"][0]["marks"]
    assert len(json.dumps(m, ensure_ascii=False)) < 14_000
    assert RD.line(full).startswith("- 실거래 조건: 충족 0개 (계좌 180개)") and RD.line(None) == ""


# ---------------------------------------------------------------- where it is shown
def test_the_lead_and_the_checkpoint_meeting_see_it(world, tmp_path):
    seed(world)
    path = verdict(tmp_path)
    assert "readiness" in RM.TEAM_VIEW["team_lead"] and "readiness" in RM.CODE_ROOTS
    assert RM.MEETING_PACKETS["checkpoint"][0] == "readiness"
    runner = QueueRunner({"league_referee": [team_answer("ref", "readiness.summary.headline")],
                          "rule_keeper": [team_answer("rk")], "team_lead": [LEAD]})
    out = world.tick(runner, DAY30 + 10 * MIN, policy=RM.RoomsPolicy(triggers=tpol(enabled=("checkpoint",))))
    assert [(r["trigger"], r["status"]) for r in out["rounds"]] == [("checkpoint", "done")]
    pk = runner.calls[0]["packet"]["readiness"]
    assert pk["summary"]["headline"] == "실거래 조건: 충족 0개" and pk["conditions"][1]["quote"].startswith("후보 계좌")
    assert pk["power"]["lines_ko"] and pk["label"] == RD.LABEL
    assert pk["accounts"][0]["account"] == f"{S}@15m" and pk["accounts"][0]["conditions"]["q1_fdr"]["status"] == OK
    lead_board = runner.calls[2]["packet"]["board"]
    assert lead_board["readiness"]["headline"] == "실거래 조건: 충족 0개"
    assert "readiness" not in runner.calls[0]["packet"]["board"]                 # the referee's view: the verdict
    assert "readiness" in runner.calls[0]["system"] and os.path.exists(path)
    said = {m["role"]: m["text"] for m in R.room_messages(world.agents, "team:lead", limit=50)}
    assert "[사실]" in said["league_referee"]


def test_the_sunday_report_has_one_line(world, tmp_path):
    seed(world)
    verdict(tmp_path)
    sunday = kst(2026, 10, 25, 21, 5)
    rep = DG.week_report(world.paper(), world.agents, sunday)
    assert rep["readiness"]["summary"]["headline"] == "실거래 조건: 충족 0개"
    text = DG.compose_week(rep)
    [line] = [x for x in text.splitlines() if "실거래 조건" in x]
    assert line == "- 실거래 조건: 충족 0개 (계좌 5개) · 자료로 볼 수 있는 조건을 모두 채운 계좌 1개 · 표시만, 아무것도 켜지 않음"
    assert len(text) <= 4000
