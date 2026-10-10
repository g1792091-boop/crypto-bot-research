"""candleague/watch.py: a fresh install waits an hour; a league whose processed time stops moving for an hour is reported
once, again only after 3 hours, and "다시 정상" once it moves; a stopped engine is reported at once; Telegram failures
never stop the check; the state file round-trips."""

from __future__ import annotations

import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from candleague import watch as W  # noqa: E402

M = 60_000
T0 = 1_791_600_000_000


def test_fresh_install_waits_then_a_stall_is_told_once_and_the_recovery():
    st, msgs = W.check({}, None, "active", T0)
    assert msgs == [] and st["first_ms"] == T0
    st, msgs = W.check(st, {"done_ms": 5}, "active", T0 + 10 * M)          # first snapshot: it moved
    assert msgs == []
    st, msgs = W.check(st, {"done_ms": 5}, "active", T0 + 69 * M)
    assert msgs == []                                                       # 59 minutes without a move: fine
    st, msgs = W.check(st, {"done_ms": 5}, "active", T0 + 70 * M)
    assert len(msgs) == 1 and "60분째" in msgs[0] and msgs[0].startswith(W.TAG)
    st, msgs = W.check(st, {"done_ms": 5}, "active", T0 + 80 * M)
    assert msgs == []                                                       # not every 10 minutes
    st, msgs = W.check(st, {"done_ms": 5}, "active", T0 + 70 * M + W.REPEAT_MS)
    assert len(msgs) == 1                                                   # again after 3 hours
    st, msgs = W.check(st, {"done_ms": 6}, "active", T0 + 70 * M + W.REPEAT_MS + 10 * M)
    assert len(msgs) == 1 and "다시 정상" in msgs[0]
    st, msgs = W.check(st, {"done_ms": 7}, "active", T0 + 70 * M + W.REPEAT_MS + 20 * M)
    assert msgs == []


def test_no_snapshot_for_an_hour_and_a_stopped_engine():
    st, msgs = W.check({}, None, "unknown", T0)
    st, msgs = W.check(st, None, "unknown", T0 + 60 * M)
    assert len(msgs) == 1 and "league.json" in msgs[0]
    st, msgs = W.check({}, {"done_ms": 1}, "failed", T0)
    assert len(msgs) == 1 and "failed" in msgs[0]


def test_service_state_and_send_never_raise():
    assert W.service_state(run=lambda *a, **k: (_ for _ in ()).throw(OSError("no systemctl"))) == "unknown"
    assert W.service_state(run=lambda *a, **k: types.SimpleNamespace(stdout="active\n")) == "active"
    sent = []

    def sender(token, chat, text):
        if chat == "bad":
            raise RuntimeError("telegram down")
        sent.append(chat)
    W.send(["x"], "tok", ["bad", "1", "2"], sender=sender)
    assert sent == ["1", "2"]
    W.send(["x"], None, ["1"], sender=sender)                              # no token: print only
    assert sent == ["1", "2"]


def test_main_keeps_its_state(tmp_path, monkeypatch):
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "league.json").write_text(json.dumps({"done_ms": 123}))
    state = tmp_path / "watch_state.json"
    for k in ("CANDLEAGUE_TG_TOKEN", "CANDLEAGUE_TG_CHAT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CANDLEAGUE_SNAP", str(snap))
    monkeypatch.setenv("CANDLEAGUE_WATCH_STATE", str(state))
    monkeypatch.setattr(W, "service_state", lambda: "active")
    assert W.main() == 0 and json.loads(state.read_text())["done_ms"] == 123
    monkeypatch.setenv("CANDLEAGUE_WATCH_STATE", str(tmp_path / "missing" / "s.json"))
    assert W.main() == 1
