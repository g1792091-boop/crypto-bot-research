"""⏳ → 결과 (owners 10/19): once the paper bot has restated a break wait (paperbot/combo.py _restate: BROKE with its entry
signal and the engine's outcome, or FILTERED with its why), the watcher writes the result into the same ⏳ message
(paperbot/livecheck.py wait_result_pass; Telegram editMessageText through the ids wait_pass kept in tg_ids), one line
after a blank line, once per wait, never a new message, given up quietly after 48 hours, off with the waits
(PAPERBOT_LIVE_WAIT_MSGS=0). A notifier without message ids (a fake, the dry run, the console) keeps today's behaviour."""
from __future__ import annotations

import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot import events  # noqa: E402
from paperbot import livecheck as LC  # noqa: E402
from paperbot.models import Signal, SignalOutcome  # noqa: E402
from paperbot.notify import INFO, telegram_text  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402
from test_livecheck_wait import T0W, Note, world  # noqa: E402

NOW, MIN, H = W.NOW, W.MIN, W.H
MEMBER = W._label("N03_ADX_GC", "15m")                 # the world's WAITING row: BCH long, N03_ADX_GC 15m, bar T0W
KEY = f"{MEMBER}|BCHUSDT|{T0W}"
ENTRY = NOW + 3 * MIN                                  # the break at NOW + 2 min: the entry minute after it
NO_TG = {"base": None, "over": None, "over_exists": False, "over_mtime": None}     # never the server's env files
LAPSED = "→ ⌛ 시간 지남 · 진입 없음"


@pytest.fixture(autouse=True)
def _no_release(tmp_path, monkeypatch):
    f = tmp_path / "macro.csv"
    f.write_text("ts_utc,kind,source_url\n", encoding="utf-8")
    monkeypatch.setattr(events, "PATH", f)
    events.reset()
    monkeypatch.delenv(LC.WAIT_MSGS_ENV, raising=False)
    monkeypatch.delenv(LC.PAUSE_MSGS_ENV, raising=False)
    yield
    events.reset()


class TG:
    """The Telegram notifier's shape: send, send_ids ({chat id: message id}) and edit (``edit_ok`` False: refused)."""

    def __init__(self, edit_ok: bool = True):
        self.sent, self.edits, self.edit_ok = [], [], edit_ok

    def send(self, level, text):
        self.sent.append((level, text))
        return True

    def send_ids(self, level, text):
        self.sent.append((level, text))
        return {"111": 500 + len(self.sent), "222": 900 + len(self.sent)}

    def edit(self, level, ids, text):
        self.edits.append((level, dict(ids), text))
        return self.edit_ok


def restate(paper: str, status: str, why: str, bar_close: int = T0W) -> None:
    """paperbot/combo.py _restate: a later status of the logged row and its why."""
    c = sqlite3.connect(paper)
    q = "FROM signal_log WHERE bar_close = ? AND strategy = ? AND symbol = 'BCHUSDT'"
    data = json.loads(c.execute(f"SELECT data {q}", (bar_close, MEMBER)).fetchone()[0])
    data["why"] = why
    c.execute(f"UPDATE signal_log SET status = ?, data = ? {q.removeprefix('FROM signal_log')}",
              (status, json.dumps(data), bar_close, MEMBER))
    c.commit()
    c.close()


def broke(paper: str, outcome: str = None, reason: str = "ok", filtered: str = None) -> None:
    """paperbot/combo.py _breaks: the wait BROKE and its entry signal (a SUBMITTED row at the entry minute); then the
    engine's outcome for COMBO@mix, or the entry minute's own filter (``filtered``: its why)."""
    restate(paper, "BROKE", f"돌파 확인: {ENTRY} 분에 진입 신호")
    s = Store3(paper)
    s.log_signals([{"bar_close": ENTRY, "timeframe": "15m", "strategy": MEMBER, "symbol": "BCHUSDT", "side": 1, "atr": 1.0,
                    "ref_price": 100.0, "ref_time": ENTRY, "delay_ms": 0, "status": "SUBMITTED",
                    "data": {"source": "custom", "strategy": "N03_ADX_GC", "why": "돌파 확인"}}])
    if outcome:
        sig = Signal(ts=ENTRY - 1, symbol="BCHUSDT", timeframe="15m", strategy_id="N03_ADX_GC", side=1, stop_price=0.0,
                     meta={"member": MEMBER})
        s.outcome(W.ACCOUNT, SignalOutcome(sig, outcome, reason, ENTRY, {}))
    s.commit()
    s.conn.close()
    if filtered:
        restate(paper, "FILTERED", filtered, bar_close=ENTRY)


def sent_wait(tmp_path, tg=None):
    """A world whose wait was told through ``tg`` (TG) at NOW: (paper, src, conn, tg, the wait's text)."""
    p, _rule, src = world(tmp_path)
    conn = LC.open_out(src.db)
    tg = tg or TG()
    (kind, key, level, text), = LC.wait_pass(src, conn, NOW, tg.send, send_ids=tg.send_ids)
    assert (kind, key, level) == ("wait", KEY, INFO)
    return p["paper"], src, conn, tg, text


def result_row(conn):
    return conn.execute("SELECT sent_ts IS NOT NULL, text FROM trade_msgs WHERE key = ? AND kind = 'wait_result'",
                        (KEY,)).fetchone()


def test_the_wait_message_turns_into_its_result_once(tmp_path):
    paper, src, conn, tg, text = sent_wait(tmp_path)
    assert json.loads(conn.execute("SELECT ids_json FROM tg_ids WHERE key = ? AND kind = 'wait'", (KEY,)).fetchone()[0]) \
        == {"111": 501, "222": 901}
    assert LC.wait_result_pass(src, conn, NOW + MIN, tg.edit) == [] and tg.edits == []        # still waiting
    restate(paper, "FILTERED", "돌파 없음(신호봉 시간 안에)")
    new = f"{text}\n\n{LAPSED}"
    assert LC.wait_result_pass(src, conn, T0W + 16 * MIN, tg.edit) == [("wait_result", KEY, INFO, new)]
    assert tg.edits == [(INFO, {"111": 501, "222": 901}, new)]                # the same message in both chats
    assert len(tg.sent) == 1                                                  # never a second message
    assert LC.wait_result_pass(src, conn, T0W + 17 * MIN, tg.edit) == [] and len(tg.edits) == 1     # once
    assert result_row(conn) == (1, new)
    assert telegram_text(INFO, new) == (INFO, new)                            # quiet, worded as it is
    conn.close()


CASES = [
    ("entered", lambda p: broke(p, "ENTERED"), f"→ ✅ 돌파! {LC.kst(ENTRY)}에 진입했어요 (🟢 진입 알림 참고)"),
    ("in position", lambda p: broke(p, "SKIPPED", "in position"), "→ 돌파했지만 진입 안 함: 이미 포지션 있음"),
    ("lost the minute", lambda p: broke(p, "SKIPPED", "lower score than entered signal"),
     "→ 돌파했지만 진입 안 함: 같은 때 다른 신호가 먼저 들어감"),
    ("late", lambda p: broke(p, "REJECTED", "late"), "→ 돌파했지만 진입 안 함: 신호가 늦음"),
    ("halted", lambda p: broke(p, "REJECTED", "halted: drawdown"), "→ 돌파했지만 진입 안 함: 페이퍼 계좌 멈춤 중"),
    ("weekend at entry", lambda p: broke(p, filtered="주말(한국 시간 토·일) 진입 안 함"), "→ 돌파했지만 진입 안 함: 주말이라 진입 쉼"),
    ("macro at entry", lambda p: broke(p, filtered="경제 발표 앞뒤 30분: 소비자물가(CPI) 2026-10-19T12:30:00Z"),
     "→ 돌파했지만 진입 안 함: 경제 발표 앞뒤라 진입 쉼"),
    ("off bucket", lambda p: broke(p, filtered="끈 구간: hr=5"), "→ 돌파했지만 진입 안 함: 끈 구간에 걸림"),
    ("no break", lambda p: restate(p, "FILTERED", "돌파 없음(신호봉 시간 안에)"), LAPSED),
    ("bar size", lambda p: restate(p, "FILTERED", "연구 조건 밖: 신호봉 크기"), "→ 진입 안 함: 신호봉 크기가 연구 조건 밖"),
    ("unreadable", lambda p: restate(p, "FILTERED", "연구 조건을 못 읽음: RuntimeError: no 1m bars of the signal bar"),
     "→ 진입 안 함: 연구 조건을 못 읽음"),
    ("late break", lambda p: restate(p, "FILTERED", "돌파 확인이 늦음(재시작 따라잡기)"),
     "→ 진입 안 함: 돌파 확인이 늦음(봇 재시작 따라잡기)"),
]


@pytest.mark.parametrize("name,make,line", CASES, ids=[c[0] for c in CASES])
def test_each_result_in_plain_korean(tmp_path, name, make, line):
    paper, src, conn, tg, text = sent_wait(tmp_path)
    make(paper)
    pc = LC.open_ro(paper)
    assert LC.wait_result(pc, KEY) == line
    pc.close()
    (_k, _key, _lv, new), = LC.wait_result_pass(src, conn, ENTRY + 2 * MIN, tg.edit)
    assert new == f"{text}\n\n{line}" and new.split("\n")[-2:] == ["", line]
    conn.close()


def test_a_break_waits_for_its_entry_outcome(tmp_path):
    paper, src, conn, tg, text = sent_wait(tmp_path)
    broke(paper)                                                              # BROKE, the entry minute not stepped yet
    pc = LC.open_ro(paper)
    assert LC.wait_result(pc, KEY) is None
    pc.close()
    assert LC.wait_result_pass(src, conn, ENTRY, tg.edit) == [] and result_row(conn) is None
    s = Store3(paper)
    s.outcome(W.ACCOUNT, SignalOutcome(Signal(ts=ENTRY - 1, symbol="BCHUSDT", timeframe="15m", strategy_id="N03_ADX_GC",
                                              side=1, stop_price=0.0, meta={"member": "another@15m#9~x"}),
                                       "SKIPPED", "in position", ENTRY, {}))         # another setting's: not this one
    s.outcome(W.FLIP, SignalOutcome(Signal(ts=ENTRY - 1, symbol="BCHUSDT", timeframe="15m", strategy_id="N03_ADX_GC",
                                           side=-1, stop_price=0.0, meta={"member": MEMBER}), "ENTERED", "ok", ENTRY, {}))
    s.commit()
    s.conn.close()
    assert LC.wait_result_pass(src, conn, ENTRY + MIN, tg.edit) == []        # the coin-flip twin's: not the account's
    broke(paper, "ENTERED")
    (_k, _key, _lv, new), = LC.wait_result_pass(src, conn, ENTRY + 2 * MIN, tg.edit)
    assert new.endswith(f"\n\n→ ✅ 돌파! {LC.kst(ENTRY)}에 진입했어요 (🟢 진입 알림 참고)") and LC.kst(ENTRY) == "19:03"
    conn.close()


def test_a_refused_edit_is_logged_recorded_once_and_never_sent_as_a_new_message(tmp_path, capsys):
    paper, src, conn, tg, text = sent_wait(tmp_path, TG(edit_ok=False))      # the owners deleted it, say
    restate(paper, "FILTERED", "돌파 없음(신호봉 시간 안에)")
    assert LC.wait_result_pass(src, conn, T0W + 16 * MIN, tg.edit) == []
    assert len(tg.edits) == 1 and len(tg.sent) == 1
    assert f"⏳ 대기 메시지에 결과를 못 씀(새 메시지는 안 보냄): {KEY}" in capsys.readouterr().err
    assert result_row(conn) == (0, f"{text}\n\n{LAPSED}")
    assert LC.wait_result_pass(src, conn, T0W + 17 * MIN, tg.edit) == [] and len(tg.edits) == 1      # not again
    conn.close()


def test_waits_older_than_48_hours_are_given_up_quietly(tmp_path, capsys):
    paper, src, conn, tg, _text = sent_wait(tmp_path)
    restate(paper, "FILTERED", "돌파 없음(신호봉 시간 안에)")
    assert LC.wait_result_pass(src, conn, NOW + 48 * H + MIN, tg.edit) == [] and tg.edits == []
    assert result_row(conn) == (0, None) and capsys.readouterr().err == ""
    assert LC.wait_result_pass(src, conn, NOW + 48 * H + 2 * MIN, tg.edit) == []
    conn.close()
    (tmp_path / "b").mkdir()
    paper, src, conn, tg, _text = sent_wait(tmp_path / "b")
    restate(paper, "FILTERED", "돌파 없음(신호봉 시간 안에)")
    assert len(LC.wait_result_pass(src, conn, NOW + 47 * H, tg.edit)) == 1    # within 48 hours: edited
    conn.close()


def test_off_with_the_waits_and_without_message_ids(tmp_path, monkeypatch):
    paper, src, conn, tg, text = sent_wait(tmp_path)
    restate(paper, "FILTERED", "돌파 없음(신호봉 시간 안에)")
    monkeypatch.setenv(LC.WAIT_MSGS_ENV, "0")
    assert LC.wait_result_pass(src, conn, T0W + 16 * MIN, tg.edit) == [] and result_row(conn) is None
    monkeypatch.delenv(LC.WAIT_MSGS_ENV)
    assert len(LC.wait_result_pass(src, conn, T0W + 17 * MIN, tg.edit)) == 1
    conn.close()
    # a notifier without ids (a fake, the console): the wait is told as before and never edited
    (tmp_path / "b").mkdir()
    p, _rule, src = world(tmp_path / "b")
    conn = LC.open_out(src.db)
    note = Note()
    assert [k for k, *_ in LC.wait_pass(src, conn, NOW, note.send)] == ["wait"]
    assert conn.execute("SELECT COUNT(*) FROM tg_ids").fetchone() == (0,)
    restate(p["paper"], "FILTERED", "돌파 없음(신호봉 시간 안에)")
    tg = TG()
    assert LC.wait_result_pass(src, conn, T0W + 16 * MIN, tg.edit) == [] and tg.edits == [] and result_row(conn) is None
    conn.close()


def test_the_watcher_keeps_the_ids_and_edits_and_the_dry_run_only_says_so(tmp_path):
    p, _rule, src = world(tmp_path)
    tg = TG()
    kw = dict(units=lambda unit: ("active", "enabled"), exists=lambda path: False, tg=NO_TG)
    out = LC.run_watch(src, now_ms=NOW, notifier=tg, **kw)
    (_k, key, _lv, text), = [x for x in out if x[0] == "wait"]
    assert key == KEY and (INFO, text) in tg.sent
    restate(p["paper"], "FILTERED", "돌파 없음(신호봉 시간 안에)")
    dry = LC.run_watch(src, now_ms=T0W + 16 * MIN, dry_run=True, **kw)
    assert [x for x in dry if x[0] == "wait_result"] == [("wait_result", KEY, INFO, f"{text}\n\n{LAPSED}")]
    assert tg.edits == [] and result_row(sqlite3.connect(src.db)) is None   # the dry run wrote and edited nothing
    out = LC.run_watch(src, now_ms=T0W + 16 * MIN, notifier=tg, **kw)
    assert [x for x in out if x[0] == "wait_result"] == [("wait_result", KEY, INFO, f"{text}\n\n{LAPSED}")]
    assert [(lv, ids) for lv, ids, _t in tg.edits] == [(INFO, {"111": 501, "222": 901})]
    assert not any(t.endswith(LAPSED) for _lv, t in tg.sent)                 # edited, never sent


def test_an_older_livecheck_db_gets_the_ids_table_and_keeps_its_columns(tmp_path):
    path = str(tmp_path / "livecheck.db")
    old = sqlite3.connect(path)
    old.executescript(LC.TRADE_SCHEMA + LC.STATE_SCHEMA)
    old.execute("INSERT INTO trade_msgs VALUES ('k', 'wait', 1, 1, 'INFO', 'x')")
    old.commit()
    old.close()
    conn = LC.open_out(path)
    assert [r[1] for r in conn.execute("PRAGMA table_info(trade_msgs)")] == ["key", "kind", "first_ts", "sent_ts", "level",
                                                                             "text"]
    assert [r[1] for r in conn.execute("PRAGMA table_info(tg_ids)")] == ["key", "kind", "ids_json", "ts"]
    assert conn.execute("SELECT * FROM trade_msgs").fetchall() == [("k", "wait", 1, 1, "INFO", "x")]
    assert LC.wait_result_pass(LC.Sources(db=path, paper_db=str(tmp_path / "none.db")), conn, NOW, TG().edit) == []
    conn.close()
