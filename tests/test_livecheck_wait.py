"""⏳ 진입 대기 (owners 10/19 "진입 하기전 진입 할 가능성이 있어서 진입대기 같은거"): a break setting's signal waits one bar of its
timeframe for the price to trade beyond the signal bar's high (long) / low (short) (paperbot/combo.py _breaks). The
watcher (paperbot/livecheck.py pending_entries, wait_pass) and the 실거래 screen show that wait: the level (the signal
bar's 1m high / low in the rule bot's bars, as the bot takes it), the last price, how far to go, the deadline; one
quiet message per wait, never while a position is open or the bots pause, off with PAPERBOT_LIVE_WAIT_MSGS=0."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot import events  # noqa: E402
from paperbot import livecheck as LC  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402

NOW, MIN, H = W.NOW, W.MIN, W.H
T0W = NOW - 10 * MIN                                   # the world's WAITING row: BCH long, N03_ADX_GC 15m


class Note:
    def __init__(self):
        self.sent = []

    def send(self, level, text):
        self.sent.append((level, text))


@pytest.fixture(autouse=True)
def _no_release(tmp_path, monkeypatch):
    f = tmp_path / "macro.csv"
    f.write_text("ts_utc,kind,source_url\n", encoding="utf-8")
    monkeypatch.setattr(events, "PATH", f)
    events.reset()
    monkeypatch.delenv(LC.WAIT_MSGS_ENV, raising=False)
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    L._cache.clear()
    yield
    events.reset()


def world(tmp_path, position=False, high=None):
    d = tmp_path / "w"
    d.mkdir()
    p = W.build_world(str(d))
    if not position:
        W.paper_db(p["paper"] + ".2", with_position=False)
        os.replace(p["paper"] + ".2", p["paper"])
    rule = str(d / "paper3.db")
    hi = high or (lambda ts: 101.0 if T0W - 15 * MIN <= ts < T0W else 100.5)
    W.rule_bars(rule, "BCHUSDT", T0W - 20 * MIN, NOW, high=hi)
    src = LC.Sources(db=str(d / "livecheck.db"), paper_db=p["paper"], rule_db=rule, combo_config="-",
                     executors=W.exec_infos(p))
    return p, rule, src


def test_a_waiting_break_signal_and_its_level(tmp_path):
    p, rule, _src = world(tmp_path)
    pc, rc = LC.open_ro(p["paper"]), LC.open_ro(rule)
    w, = LC.pending_entries(pc, rc, NOW)
    pc.close(), rc.close()
    assert (w["symbol"], w["side"], w["tf"], w["strategy"]) == ("BCHUSDT", 1, "15m", "N03_ADX_GC")
    assert (w["t0"], w["until"]) == (T0W, T0W + 15 * MIN) and w["level"] == 101.0 and w["last"] == 100.0
    assert abs(w["to_go"] - 0.01) < 1e-12 and w["touched"] is False
    pc = LC.open_ro(p["paper"])
    assert LC.pending_entries(pc, None, T0W + 15 * MIN) == []                  # lapsed at its deadline
    nolevel, = LC.pending_entries(pc, None, NOW)                               # without the rule bot's bars: no level
    pc.close()
    assert nolevel["level"] is None and nolevel["to_go"] is None


def test_one_quiet_message_per_wait(tmp_path):
    _p, _rule, src = world(tmp_path)
    conn = LC.open_out(src.db)
    note = Note()
    out = LC.wait_pass(src, conn, NOW, note.send)
    assert [k for k, *_ in out] == ["wait"] and len(note.sent) == 1
    level, text = note.sent[0]
    assert level == "INFO" and text.startswith("⏳ 진입 대기 · BCH 롱 · N03_ADX_GC 15분")
    assert "101 위로 올라가면 진입 (지금 100 · 1.00% 남음)" in text and "까지 못 넘으면 진입 없음 · 5분 남음" in text
    assert LC.wait_pass(src, conn, NOW + MIN, note.send) == [] and len(note.sent) == 1       # never twice
    conn.close()


def test_no_message_while_a_position_is_open_paused_switched_off_or_already_beyond(tmp_path, monkeypatch):
    _p, _rule, src = world(tmp_path / "a" if (tmp_path / "a").mkdir() is None else tmp_path, position=True)
    conn = LC.open_out(src.db)
    assert LC.wait_pass(src, conn, NOW, Note().send) == []
    assert LC._msg_row(conn, f"{W._label('N03_ADX_GC', '15m')}|BCHUSDT|{T0W}", "wait") is None    # told when it closes
    conn.close()
    (tmp_path / "b").mkdir()
    _p, _rule, src = world(tmp_path / "b")
    conn = LC.open_out(src.db)
    monkeypatch.setenv(LC.WAIT_MSGS_ENV, "0")
    assert LC.wait_pass(src, conn, NOW, Note().send) == []
    monkeypatch.delenv(LC.WAIT_MSGS_ENV)
    sat = NOW + 4 * W.DAY + 6 * H                                              # Saturday 01:00 KST: the weekend pause
    assert LC._paused_now(sat) and not LC._paused_now(NOW)
    conn.close()
    (tmp_path / "c").mkdir()
    _p, _rule, src = world(tmp_path / "c", high=lambda ts: 101.0 if ts < T0W else 101.2)       # already beyond
    conn = LC.open_out(src.db)
    note = Note()
    assert LC.wait_pass(src, conn, NOW, note.send) == [] and note.sent == []
    assert LC._msg_row(conn, f"{W._label('N03_ADX_GC', '15m')}|BCHUSDT|{T0W}", "wait") is not None
    conn.close()


def test_the_screen_gets_the_waits_and_the_next_bar_closes(tmp_path, monkeypatch):
    p, rule, _src = world(tmp_path)
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", rule)
    w = L.whynow(p, NOW)
    pend = w["pending"]
    assert pend["state"] == "ok" and pend["rule_state"] == "ok" and len(pend["waits"]) == 1
    assert pend["waits"][0]["left_ms"] == 5 * MIN and pend["waits"][0]["level"] == 101.0
    assert [(c["tf"], c["now"], c["break"]) for c in pend["closes"]] == [("15m", 0, 1), ("30m", 1, 0), ("1h", 1, 0)]
    assert all(c["next_ms"] > NOW and c["next_ms"] % (15 * MIN) == 0 for c in pend["closes"])
    assert w["pending_blocked_ko"] is None and w["ready"] is False                # ready: the world's lights/halt say no
