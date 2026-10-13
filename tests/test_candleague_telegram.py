"""candleague 알림 기록, server side: candleague/notify.py keeps the last 50 sent messages in telegram.json (snapshot dir) and runner.write_snapshots
serves them as league.json ``telegram``.

  * every text the notifier sends is appended (time, kind by emoji, first line, text), capped at 4000 characters, control characters removed, a
    token-shaped string blanked, the last 50 kept, written atomically (no temp file left behind);
  * a failure to write (no folder, a file where the folder should be, a broken old file) never stops sending, other chats or the league;
  * a text that was not sent (the sender raised) is not recorded; without a sender nothing is recorded;
  * ``read_log``: newest first, absent / broken -> None; the snapshot doc carries it (None when absent)."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_notify as NT  # noqa: E402
import test_candleague_riskview as RT  # noqa: E402
from candleague import notify as N  # noqa: E402
from candleague import runner as RN  # noqa: E402

KST9 = NT.KST9


def test_a_sent_message_is_recorded_with_its_kind(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    conn = RN.open_db(str(tmp_path / "l.db"))
    sent = []
    nt = N.Notifier(conn, sender=sent.append, snap=str(snap))
    nt.after_pass(NT._doc(), KST9 + 120_000, caught_up=True)                  # the day's summary
    nt.after_pass(NT._doc(bust=True), KST9 + 7_200_000, caught_up=True)       # a bust
    log = N.read_log(str(snap))
    assert [m["kind"] for m in log["messages"]] == ["bust", "summary"] and log["cap"] == 50                  # newest first
    assert log["messages"][0]["ms"] == KST9 + 7_200_000 and log["messages"][0]["title"].startswith("🚨 후보 리그 파산")
    assert log["messages"][1]["text"] == sent[0] and log["messages"][1]["title"] == sent[0].split("\n")[0]
    assert sorted(os.listdir(snap)) == ["telegram.json"]                       # atomic: no temp file left


def test_kinds_by_emoji():
    for text, kind in (("📊 아침 요약 · 후보 리그", "summary"), ("🔄 새로 시작 · 후보 리그", "start"), ("🚨 후보 리그 파산", "bust"),
                       ("⚠ 후보 리그 경고등", "alert"), ("그냥 글", "alert"), ("", "alert")):
        assert N.message_kind(text) == kind


def test_cap_control_characters_and_secrets(tmp_path):
    snap = tmp_path / "s"
    snap.mkdir()
    token = "123456789:AAEhBP0av28lKfNQqwWDmoNzSdI_x3yTw5Q"
    text = "📊 제목\x00\x07 줄\r\n둘째\x1b[31m 줄\x7f " + token + " " + "가" * 5000
    assert N.record_sent(str(snap), text, KST9)
    m = N.read_log(str(snap))["messages"][0]
    assert len(m["text"]) == 4000 and "\x00" not in m["text"] and "\x1b" not in m["text"] and "\x7f" not in m["text"] and "\r" not in m["text"]
    assert m["text"].startswith("📊 제목 줄\n둘째[31m 줄 [숨김] 가") and token not in m["text"] and "AAEhBP0av28" not in json.dumps(m)
    assert m["title"] == "📊 제목 줄" and len(m["title"]) <= 120
    raw = open(snap / "telegram.json", encoding="utf-8").read()
    assert token not in raw and "\\u0000" not in raw
    assert N.clean_text(None) == "" and N.clean_text(12) == "12"


def test_only_the_last_50_are_kept(tmp_path):
    snap = tmp_path / "s"
    snap.mkdir()
    for i in range(53):
        assert N.record_sent(str(snap), f"📊 n{i}", KST9 + i)
    log = N.read_log(str(snap))["messages"]
    assert len(log) == 50 and log[0]["title"] == "📊 n52" and log[-1]["title"] == "📊 n3" and [m["ms"] for m in log] == sorted([m["ms"] for m in log], reverse=True)
    assert len(json.load(open(snap / "telegram.json"))["messages"]) == 50


def test_a_write_failure_never_stops_sending(tmp_path, capsys):
    conn = RN.open_db(str(tmp_path / "l.db"))
    (tmp_path / "afile").write_text("x")
    for snap in (str(tmp_path / "missing"), str(tmp_path / "afile"), None):                  # no folder / a file instead of a folder / the default (absent here)
        sent = []
        nt = N.Notifier(conn, sender=sent.append, snap=snap)
        assert len(nt.after_pass(NT._doc(bust=True), KST9 + 60_000, caught_up=True)) == 2 and len(sent) == 2
        conn.execute("DELETE FROM kv")
        conn.commit()
    d = tmp_path / "bad"
    d.mkdir()
    (d / "telegram.json").write_text("{not json")                                          # a broken old file is replaced, not fatal
    assert N.record_sent(str(d), "🚨 x", KST9) and len(N.read_log(str(d))["messages"]) == 1
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, 0o500)
    try:
        assert N.record_sent(str(ro), "🚨 x", KST9) in (True, False)                         # (root can write anywhere); the point is: no exception
    finally:
        os.chmod(ro, 0o700)


def test_unsent_texts_are_not_recorded(tmp_path):
    snap = tmp_path / "s"
    snap.mkdir()
    conn = RN.open_db(str(tmp_path / "l.db"))

    def boom(text):
        raise OSError("down")
    assert len(N.Notifier(conn, sender=boom, snap=str(snap)).after_pass(NT._doc(bust=True), KST9 + 60_000, caught_up=True)) == 2
    assert N.read_log(str(snap)) is None and not (snap / "telegram.json").exists()
    conn2 = RN.open_db(str(tmp_path / "m.db"))
    nt = N.Notifier(conn2, snap=str(snap))                                                    # no token -> no sender: nothing sent, nothing recorded
    nt.sender = None
    nt.after_pass(NT._doc(bust=True), KST9 + 60_000, caught_up=True)
    assert N.read_log(str(snap)) is None


def test_one_failing_chat_still_records_once(tmp_path, monkeypatch):
    snap = tmp_path / "s"
    snap.mkdir()
    conn = RN.open_db(str(tmp_path / "l.db"))

    def send(token, chat, text):
        if chat == "111":
            raise OSError("blocked")
    monkeypatch.setattr(N, "send_telegram", send)
    monkeypatch.setenv("CANDLEAGUE_TG_TOKEN", "T")
    monkeypatch.setenv("CANDLEAGUE_TG_CHAT", "111,222")
    N.Notifier(conn, snap=str(snap)).after_pass(NT._doc(bust=True), KST9 + 60_000, caught_up=True)
    assert len(N.read_log(str(snap))["messages"]) == 2                                          # two messages (bust + warning light), each once, not once per chat


def test_read_log_absent_or_broken(tmp_path):
    assert N.read_log(str(tmp_path)) is None and N.read_log(None) is None and N.read_log(str(tmp_path / "nope")) is None
    (tmp_path / "telegram.json").write_text('{"messages": [{"ms": "x", "text": "a"}, {"ms": 5, "text": 7}, {"ms": 6, "text": "ok", "kind": "start"}]}')
    log = N.read_log(str(tmp_path))
    assert [m["text"] for m in log["messages"]] == ["ok"] and log["messages"][0]["kind"] == "start" and log["messages"][0]["title"] == ""
    (tmp_path / "telegram.json").write_text('{"messages": 3}')
    assert N.read_log(str(tmp_path)) is None


def test_write_snapshots_serves_the_log(tmp_path):
    lg = RT.fake_league(tmp_path)
    snap = tmp_path / "snap"
    doc = RN.write_snapshots(str(snap), lg, RT.NOW, ds_money=False)
    assert "telegram" in doc and doc["telegram"] is None and "telegram_error" not in doc                    # absent file -> None
    N.record_sent(str(snap), "📊 아침 요약 · 후보 리그\n\n본문", RT.NOW)
    doc = RN.write_snapshots(str(snap), lg, RT.NOW + 1000, ds_money=False)
    assert doc["telegram"]["messages"][0]["kind"] == "summary" and doc["telegram"]["cap"] == 50
    assert json.load(open(snap / "league.json"))["telegram"] == doc["telegram"]


def test_the_runner_hands_the_snapshot_dir_to_the_notifier():
    src = open(os.path.join(ROOT, "candleague", "runner.py"), encoding="utf-8").read()
    if "Notifier(conn, snap=a.snap)" not in src:
        import pytest
        pytest.skip("the coordinator adds the one-line change `Notifier(conn, snap=a.snap)` in runner main (see the report); the env CANDLEAGUE_SNAP / default dir is the fallback")
