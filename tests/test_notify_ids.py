"""TelegramNotifier.send_ids / edit (owners 10-19: the live watcher's ⏳ message turns into its result in place): the ids
per chat come from sendMessage's answer (result.message_id); an edit is one editMessageText per chat, worded like a new
message and never ringing; neither ever raises, and ``send`` / ``send_once`` stay as they were. urllib is faked."""
import io
import json
import urllib.error
import urllib.parse

import pytest

from paperbot import notify
from paperbot.notify import CRITICAL, INFO, TelegramNotifier, telegram_text

WAIT = "⏳ 진입 대기 · BCH 롱 · N03_ADX_GC 15분\n101 위로 올라가면 진입"


@pytest.fixture(autouse=True)
def _no_counter(monkeypatch):
    monkeypatch.delenv("PAPERBOT_TG_SENDS_DB", raising=False)        # never count a test's sends on a real server
    monkeypatch.setattr(notify, "TG_SENDS_DB", "")


def env(chats="111,222", **kw):
    return {"TELEGRAM_BOT_TOKEN": "SECRET:TOKEN", "TELEGRAM_CHAT_CRITICAL": chats, **kw}


def no_sleep(s):
    raise AssertionError("send_ids / edit never wait")


def fake_tg(monkeypatch, fail=(), code=400, body=None, boom=None):
    """urlopen answering like Telegram: sendMessage -> {"ok": true, "result": {"message_id": 100 + request number}},
    editMessageText -> {"ok": true, "result": {...}}; a chat in ``fail`` gets HTTP ``code`` (429: retry after 3 s);
    ``body``: every answer; ``boom``: an exception raised for every request. Returns [(method, params)]."""
    calls = []

    class Resp:
        def __init__(self, raw):
            self.raw = raw

        def read(self):
            return self.raw

    def urlopen(url, data=None, timeout=None):
        method = url.rsplit("/", 1)[1]
        d = {k: v[0] for k, v in urllib.parse.parse_qs(data.decode()).items()}
        calls.append((method, d))
        if boom is not None:
            raise boom
        if d["chat_id"] in fail:
            raise urllib.error.HTTPError(url, code, "x", {"Retry-After": "3"},
                                         io.BytesIO(b'{"ok":false,"parameters":{"retry_after":3}}'))
        if body is not None:
            return Resp(body)
        if method == "sendMessage":
            return Resp(json.dumps({"ok": True, "result": {"message_id": 100 + len(calls), "text": d["text"]}}).encode())
        return Resp(json.dumps({"ok": True, "result": {"message_id": int(d["message_id"])}}).encode())
    monkeypatch.setattr(notify.urllib.request, "urlopen", urlopen)
    return calls


def test_send_ids_gives_the_message_id_of_each_chat_and_sends_like_send_once(monkeypatch):
    calls = fake_tg(monkeypatch)
    n = TelegramNotifier(env=env(TELEGRAM_SOUND="critical"), sleep=no_sleep)
    assert n.send_ids(INFO, WAIT) == {"111": 101, "222": 102}
    assert n.send_ids(CRITICAL, "plain") == {"111": 103, "222": 104}
    assert n.send_once(INFO, WAIT) == (True, None)
    assert [m for m, _d in calls] == ["sendMessage"] * 6
    assert calls[0][1] == calls[4][1] and calls[1][1] == calls[5][1]           # the same request as send_once
    assert calls[0][1] == {"chat_id": "111", "text": telegram_text(INFO, WAIT)[1], "disable_notification": "true"}
    assert calls[2][1]["text"] == "🚨 plain" and calls[2][1]["disable_notification"] == "false"   # CRITICAL rings
    fake_tg(monkeypatch)
    assert TelegramNotifier(env=env("111")).send_ids(INFO, WAIT) == {"111": 101}                    # one chat


def test_send_ids_with_a_chat_failing_a_429_or_an_unreadable_answer(monkeypatch, capsys, tmp_path):
    fake_tg(monkeypatch, fail={"111"})
    n = TelegramNotifier(env=env(), sleep=no_sleep)
    assert n.send_ids(INFO, WAIT) == {"222": 102}                       # the other chat still has it
    assert "telegram send failed (chat 1 of 2): HTTP 400" in capsys.readouterr().err
    calls = fake_tg(monkeypatch, fail={"111", "222"}, code=429)
    assert n.send_ids(INFO, WAIT) == {} and len(calls) == 2             # refused everywhere: {} and no wait
    assert "retry after 3s" in capsys.readouterr().err
    db = tmp_path / "tgsends.db"
    monkeypatch.setenv("PAPERBOT_TG_SENDS_DB", str(db))
    fake_tg(monkeypatch, body=b"not json")
    assert n.send_ids(INFO, WAIT) == {"111": None, "222": None}         # delivered, ids unknown: still accepted
    import sqlite3
    assert sqlite3.connect(str(db)).execute("SELECT kind, n FROM tg_sends").fetchall() == [("INFO", 1)]   # counted once
    fake_tg(monkeypatch, boom=ValueError("odd"))
    assert n.send_ids(INFO, WAIT) == {}                                 # never raises
    assert "SECRET" not in capsys.readouterr().err                      # the token is never printed


def test_edit_rewrites_the_message_in_each_chat_and_never_rings(monkeypatch):
    calls = fake_tg(monkeypatch)
    n = TelegramNotifier(env=env(TELEGRAM_SOUND="critical"), sleep=no_sleep)
    new = WAIT + "\n\n→ ⌛ 시간 지남 · 진입 없음"
    assert n.edit(INFO, {"111": 101, "222": 102}, new) is True
    assert calls == [("editMessageText", {"chat_id": "111", "message_id": "101", "text": telegram_text(INFO, new)[1]}),
                     ("editMessageText", {"chat_id": "222", "message_id": "102", "text": telegram_text(INFO, new)[1]})]
    calls.clear()
    assert n.edit(CRITICAL, {"111": 7}, "plain") is True                # worded like a new message (the level mark) ...
    assert calls == [("editMessageText", {"chat_id": "111", "message_id": "7", "text": "🚨 plain"})]    # ... never rings
    calls.clear()
    assert n.edit(INFO, {"111": None, "222": 5}, new) is True and [d["chat_id"] for _m, d in calls] == ["222"]
    calls.clear()
    assert n.edit(INFO, {}, new) is False and n.edit(INFO, None, new) is False and calls == []


def test_an_edit_refused_keeps_the_old_text_and_never_raises(monkeypatch, capsys):
    n = TelegramNotifier(env=env(), sleep=no_sleep)
    calls = fake_tg(monkeypatch, fail={"111"})                         # deleted in one chat ("message to edit not found")
    assert n.edit(INFO, {"111": 101, "222": 102}, "x") is True
    assert capsys.readouterr().err.count("telegram edit failed (chat 1 of 2): HTTP 400") == 1
    fake_tg(monkeypatch, fail={"111", "222"}, code=429)
    assert n.edit(INFO, {"111": 101, "222": 102}, "x") is False
    calls = fake_tg(monkeypatch, boom=OSError("down"))
    assert n.edit(INFO, {"111": 101}, "x") is False and len(calls) == 1
    assert n.edit(INFO, {"111": "not a number"}, "x") is False         # garbage ids: False, never an exception
    assert n.edit(INFO, "garbage", "x") is False
    assert "SECRET" not in capsys.readouterr().err
    assert all(m == "editMessageText" for m, _d in calls)               # nothing is ever sent as a new message
