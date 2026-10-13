"""candleague 데이터 점검, server side: candleague/dataq.py (league.json key ``dataq``) written by runner.write_snapshots (via screens3.add_blocks, last).

Hand-made snapshot dicts: the status word and sentence (정상 / 늦음 / 확인 필요 and their limits: 30 and 60 minutes, catching up, an error key, a missing
wallet, a trade time that cannot be), every check with its word (정상 / 주의 / 확인 필요 / 확인 못 함: a thing the snapshot cannot show is 확인 못 함 and
never a guess), the warnings that do not change the status, DeepSeek (a hidden wallet is never judged missing; no money in the block), JSON without NaN,
deterministic, what to do text, hygiene, and the snapshot hook (the data check sees the errors the other blocks left)."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_riskview as RT  # noqa: E402
from candleague import dataq as DQ  # noqa: E402
from candleague import runner as RN  # noqa: E402

T0, H, MIN = RT.T0, RT.H, RT.MIN
DONE = T0 + 3 * 86_400_000


def snap(**kw):
    d = {"generated_ms": DONE + 6 * MIN, "done_ms": DONE, "lag_s": 360, "catching": False, "start_ms": T0, "notes": [],
         "server": {"load": [0.4, 0.5, 0.5], "cpus": 4, "rss_mb": 400.0, "pass_s": 12.0},
         "accounts": [RT.row("a-fq", "fq"), RT.row("a-ld", "ld"), RT.row("ds-fq", "fq", kind="ds", wallet=None)]}
    d.update(kw)
    return d


BOOK = {"a-fq": [RT.tr(1, DONE - 3 * H, DONE - 2 * H, 5.0, "BTCUSDT"), RT.tr(-1, DONE - 5 * H, DONE - 4 * H, -3.0, "ETHUSDT")], "ds-fq": [RT.tr(1, DONE - 5 * H, DONE - H, 88888.0)]}
LU = [dict(RT.LU[0], accounts=2), dict(RT.LU[5], accounts=1)]


def check(out, cid):
    return next(c for c in out["checks"] if c["id"] == cid)


def test_healthy_says_ok_with_the_reason_and_nothing_to_do():
    out = DQ.dataq_views(snap(), BOOK, LU, False)
    assert out["status"] == "ok" and out["status_ko"] == "정상" and out["headline_ko"].startswith("정상: 엔진이 ")
    assert "6분 늦습니다" in out["reason_ko"] and "계좌 3개" in out["reason_ko"] and out["errors"] == []
    assert out["todo_ko"] == DQ.todo_ko("ok") and "아무것도 하지 않아도" in out["todo_ko"][0]
    words = {c["id"]: c["word_ko"] for c in out["checks"]}
    assert words["done"] == words["lag"] == words["catching"] == words["errors"] == words["accounts"] == words["wallets"] == words["trade_time"] == "정상"
    assert words["prices"] == "확인 못 함" and check(out, "prices")["level"] == "unknown"             # the snapshot has no per-coin price: never claimed
    assert all(c["word_ko"] == DQ.WORD[c["level"]] and c["value_ko"] for c in out["checks"])         # every row has a word and a value, never colour alone
    assert out["counts"]["unknown"] == 1 and "확인 못 한 항목 1개" in out["headline_ko"]
    assert check(out, "coins")["value_ko"] == "2개 (BTC · ETH)" and check(out, "accounts")["value_ko"] == "3개"


def test_late_and_the_limits():
    s = lambda lag, **k: DQ.dataq_views(snap(lag_s=lag, **k), BOOK, LU, False)   # noqa: E731
    assert s(30 * 60)["status"] == "ok" and s(30 * 60 + 1)["status"] == "late"
    late = s(45 * 60)
    assert late["status_ko"] == "늦음" and late["headline_ko"].startswith("늦음: ") and "45분 늦습니다" in late["reason_ko"] and "10~20분" in late["todo_ko"][0]
    assert s(60 * 60)["status"] == "late" and s(60 * 60 + 1)["status"] == "check"
    assert "한 시간" not in s(60 * 60 + 1)["reason_ko"] and "1시간" in s(60 * 60 + 1)["reason_ko"]
    c = s(100, catching=True)
    assert c["status"] == "late" and "따라잡는 중" in c["reason_ko"] and check(c, "catching")["word_ko"] == "주의"
    nolag = DQ.dataq_views(snap(lag_s=None), BOOK, LU, False)
    assert check(nolag, "lag")["value_ko"] == "6분"                                                    # from generated - done when lag_s is absent


def test_check_needed_for_errors_missing_values_and_impossible_times():
    e = DQ.dataq_views(snap(risk_error="ValueError: boom", conditions_error="x"), BOOK, LU, False)
    assert e["status"] == "check" and e["status_ko"] == "확인 필요" and [x["key"] for x in e["errors"]] == ["conditions_error", "risk_error"]
    assert "risk_error" in check(e, "errors")["value_ko"] and "개발자에게 보내" in e["todo_ko"][0]
    assert DQ.dataq_views(snap(dataq_error="mine"), BOOK, LU, False)["status"] == "ok"                 # its own failure is not counted twice
    rows = snap()["accounts"]
    rows[0]["wallet"] = None
    w = DQ.dataq_views(snap(accounts=rows), BOOK, LU, False)
    assert w["status"] == "check" and check(w, "wallets")["value_ko"] == "1개 계좌"
    future = dict(BOOK, **{"a-ld": [RT.tr(1, DONE + 1, DONE + 10 * MIN, 1.0)]})
    t = DQ.dataq_views(snap(), future, LU, False)
    assert t["status"] == "check" and check(t, "trade_time")["level"] == "bad"
    back = dict(BOOK, **{"a-ld": [RT.tr(1, DONE - H, DONE - 2 * H, 1.0)]})
    assert check(DQ.dataq_views(snap(), back, LU, False), "trade_time")["level"] == "bad"
    for bad in (snap(done_ms=None), snap(accounts=[])):
        assert DQ.dataq_views(bad, BOOK, LU, False)["status"] == "check"
    mism = DQ.dataq_views(snap(), BOOK, [dict(LU[0], accounts=9)], False)
    assert check(mism, "accounts")["word_ko"] == "주의" and "종류별 합계 9개" in check(mism, "accounts")["value_ko"] and mism["status"] == "check"


def test_other_warnings_do_not_change_the_status_but_are_counted():
    s = snap(notes=["복원 메모"], server={"load": [9.0, 1, 1], "cpus": 4, "rss_mb": 1250.0, "pass_s": 400.0})
    s["accounts"][0]["bust"] = True
    out = DQ.dataq_views(s, BOOK, LU, False)
    assert out["status"] == "ok" and out["engine_notes"] == ["복원 메모"] and "참고할 주의" in out["headline_ko"]
    for cid in ("notes", "load", "memory", "pass", "bust"):
        assert check(out, cid)["word_ko"] == "주의" and check(out, cid)["core"] is False, cid
    quiet = DQ.dataq_views(snap(done_ms=DONE + 2 * 86_400_000, lag_s=5), BOOK, LU, False)
    assert check(quiet, "recent")["word_ko"] == "주의" and quiet["status"] == "ok"
    none = DQ.dataq_views(snap(), {}, LU, False)
    assert check(none, "recent")["word_ko"] == "확인 못 함" and check(none, "coins")["word_ko"] == "확인 못 함"
    young = DQ.dataq_views(snap(start_ms=DONE - H), {}, LU, False)
    assert check(young, "recent")["word_ko"] == "정상" and check(young, "recent")["value_ko"] == "아직 없음"
    absent = DQ.dataq_views(snap(server=None), BOOK, LU, False)
    assert [check(absent, c)["word_ko"] for c in ("load", "memory", "pass")] == ["확인 못 함"] * 3


def test_deepseek_wallet_hidden_is_not_missing_and_no_money_leaks_json_and_order():
    out = DQ.dataq_views(snap(), BOOK, LU, False)
    assert check(out, "wallets")["word_ko"] == "정상"                                                  # the ds row has wallet None by design
    assert "88888" not in json.dumps(out) and check(out, "coins")["value_ko"] == "2개 (BTC · ETH)"
    on = DQ.dataq_views(snap(), BOOK, LU, True)
    assert "88888" not in json.dumps(on) and check(on, "trade_time")["word_ko"] == "정상"               # counts and times only, never an amount
    json.dumps(out, allow_nan=False)
    a = json.dumps(DQ.dataq_views(snap(), BOOK, LU, False), sort_keys=True)
    assert a == json.dumps(DQ.dataq_views(snap(accounts=list(reversed(snap()["accounts"]))), dict(reversed(list(BOOK.items()))), LU, False), sort_keys=True)
    txt = " ".join(out["todo_ko"] + out["note_ko"])
    assert "5,000" not in txt and "추천" not in txt and "확인 못 함" in " ".join(out["note_ko"]) + " ".join(c["word_ko"] for c in out["checks"])


def test_module_hygiene():
    src = open(os.path.join(ROOT, "candleague", "dataq.py"), encoding="utf-8").read()
    for bad in ("import time\n", "import random", "time.time()", "os.environ", "open(", "5000", "5,000", "import sqlite3", "datetime.now", "utcnow"):
        assert bad not in src, bad


def test_write_snapshots_carries_dataq_last_and_reads_the_other_blocks_errors(tmp_path, monkeypatch):
    lg = RT.fake_league(tmp_path)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, RT.NOW, ds_money=False)
    saved = json.load(open(tmp_path / "snap" / "league.json"), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    q = saved["dataq"]
    assert q == doc["dataq"] and "dataq_error" not in doc and q["status"] == "ok" and q["errors"] == [] and q["done_ms"] == doc["done_ms"]
    assert list(doc).index("dataq") > list(doc).index("timeline") > list(doc).index("coins") > list(doc).index("conditions")
    lg2 = RT.fake_league(tmp_path, owner=False, name="b.db")
    d2 = RN.write_snapshots(str(tmp_path / "snap2"), lg2, RT.NOW, ds_money=True)
    assert "dataq" not in d2 and "dataq_error" not in d2
    lg3 = RT.fake_league(tmp_path, name="c.db")
    monkeypatch.setattr(DQ, "dataq_views", lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
    d3 = RN.write_snapshots(str(tmp_path / "snap3"), lg3, RT.NOW, ds_money=True)
    assert "dataq" not in d3 and d3["dataq_error"].startswith("KeyError") and "coins" in d3 and os.path.exists(tmp_path / "snap3" / "trades.json")
