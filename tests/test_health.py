import os
import socket

import pytest

from paperbot import Bar, Brackets
from paperbot.accounts import AccountBook
from paperbot.config import V3_SYMBOLS, v3_settings
from paperbot.health import DeadMan, sd_notify
from paperbot.live3 import Runner3
from paperbot.notify import INFO, WARN, Digest, ListNotifier, TelegramNotifier
from paperbot.sigservice import SignalService, SignalTimeout
from paperbot.store3 import Store3

MIN = 60_000


def test_deadman_pings_only_while_bars_are_fresh():
    sent = []
    dm = DeadMan("https://hc.example/abc", get=lambda url, t: sent.append(url))
    assert dm.beat(10 * MIN, 8 * MIN) is True           # bar 8 closed at 9: 1 min lag
    assert dm.beat(10 * MIN + 5000, 8 * MIN) is None     # not due yet
    assert dm.beat(20 * MIN, 12 * MIN) is False          # 7 min lag: stay silent
    assert dm.beat(21 * MIN, 19 * MIN) is True
    assert len(sent) == 2 and dm.last_ping == 21 * MIN


def test_deadman_off_without_url_and_survives_ping_errors():
    assert DeadMan(None).beat(0, 0) is None
    assert DeadMan("").beat(0, 0) is None

    def boom(url, t):
        raise OSError("down")
    dm = DeadMan("https://hc.example/abc", get=boom)
    assert dm.beat(2 * MIN, MIN) is False and dm.failures == 1


def test_sd_notify(tmp_path):
    assert sd_notify("WATCHDOG=1", env={}) is False
    path = str(tmp_path / "n.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    srv.bind(path)
    try:
        assert sd_notify("WATCHDOG=1", env={"NOTIFY_SOCKET": path}) is True
        assert srv.recv(100) == b"WATCHDOG=1"
    finally:
        srv.close()


def test_empty_warn_and_info_chats_fall_back_to_critical(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_CRITICAL", "111")
    monkeypatch.setenv("TELEGRAM_CHAT_WARN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_INFO", "")
    n = TelegramNotifier()
    assert n.chats == {"CRITICAL": "111", "WARN": "111", "INFO": "111"}
    monkeypatch.setenv("TELEGRAM_CHAT_INFO", "333")
    assert TelegramNotifier().chats["INFO"] == "333"


def test_digest_batches_into_one_silent_message():
    out = ListNotifier()
    d = Digest(out, every_ms=3_600_000, max_lines=2)
    assert d.flush(0) is None                     # first call only starts the clock
    d.add("[A@5m] BUST: wallet below 10")
    d.add("[B@5m] drawdown 31.0% (level 30%), equity 690.00")
    d.add("[C@1h] drawdown 52.0% (level 50%), equity 480.00")
    assert d.flush(1_000) is None and out.messages == []
    text = d.flush(3_600_000)
    assert out.messages == [(INFO, text)]
    assert text.startswith("알림 모음: 파산 1 · 낙폭 2") and "외 1건" in text
    assert d.items == [] and d.flush(7_300_000) is None


def _book(tmp_path, notifier, digest):
    store = Store3(str(tmp_path / "h.db"))
    book = AccountBook(v3_settings(), {s: Brackets.example() for s in V3_SYMBOLS}, store, notifier,
                       digest=digest)
    book.open_accounts([{"strategy": "S", "timeframe": "5m", "kind": "strategy"}], 0)
    return store, book


def test_account_warn_goes_to_digest_critical_goes_straight_out(tmp_path):
    out = ListNotifier()
    d = Digest(out)
    store, book = _book(tmp_path, out, d)
    eng = book.engines["S@5m"]
    eng.notifier.send(WARN, "[S@5m] BUST: x")
    eng.notifier.send("CRITICAL", "[S@5m] LIQUIDATED BTCUSDT 40x lost margin 10.00")
    eng.notifier.send(INFO, "[S@5m] trade closed")
    assert out.messages == [("CRITICAL", "[S@5m] LIQUIDATED BTCUSDT 40x lost margin 10.00")]
    assert d.items == ["[S@5m] BUST: x"]
    levels = [r[0] for r in store.conn.execute("SELECT level FROM alerts ORDER BY rowid")]
    assert levels == [WARN, "CRITICAL", INFO]


class HangingService:
    pool_restarts = 0

    def __init__(self):
        self.last = {}

    def add_5m(self, b):
        self.last[b.symbol] = b.open_time + 5 * MIN

    def complete(self, boundary):
        return True

    def due(self, boundary):
        return ["5m", "15m"]

    def compute(self, boundary, tf, now_ms, book):
        raise SignalTimeout("signal workers did not answer within 120s")


def test_runner_skips_hung_signals_and_records_health(tmp_path):
    out = ListNotifier()
    store, book = _book(tmp_path, out, Digest(out))
    pings = []
    dm = DeadMan("https://hc.example/abc", get=lambda url, t: pings.append(url))
    run = Runner3(book, HangingService(), store, out, V3_SYMBOLS, lambda: 16 * MIN,
                  lambda: {}, deadman=dm)
    steps = [(i * MIN, {s: Bar(s, i * MIN, i * MIN + MIN - 1, 100.0, 100.0, 100.0, 100.0, volume=1.0)
                        for s in V3_SYMBOLS}, {}) for i in range(15)]
    run.process(steps)
    assert run.signal_timeouts == 3                         # boundaries 5, 10, 15 min
    assert out.messages[0][0] == WARN and "5m, 15m" in out.messages[0][1]
    ts, h = store.get_state("health")
    assert h["last_bar"] == 14 * MIN and h["lag_ms"] == MIN and h["signal_timeouts"] == 3
    assert h["deadman"]["sent"] is True and pings


def _sleep(job):
    import time
    time.sleep(5)


@pytest.mark.skipif(os.cpu_count() is None or os.cpu_count() < 2, reason="needs processes")
def test_pool_timeout_kills_and_recreates_workers(monkeypatch):
    import paperbot.sigservice as ss
    svc = SignalService.__new__(SignalService)
    svc._procs, svc._pool, svc.timeout_s, svc.pool_restarts = 2, None, 0.5, 0
    monkeypatch.setattr(ss, "compute_last", _sleep)
    with pytest.raises(SignalTimeout):
        svc._map([1, 2])
    assert svc._pool is None and svc.pool_restarts == 1
