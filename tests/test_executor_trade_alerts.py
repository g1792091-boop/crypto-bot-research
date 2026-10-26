"""``trade_alerts`` (owners 10-26: "투비트 진입알림 텔레그램 알림 안뜨는거 같은데"): the executor tells its own trades on
Telegram. The live watcher (paperbot/livecheck.py) tells only the combo bots' COMBO@mix trades, so the Toobit executor,
which follows the rule bot's V39_ALL@1h in paper3.db, had no entry message at all. With the option the executor sends
(INFO, silent) its entry (🟢), its first lock (🔒), each exit (✅ / ❌) and each planned skip (⏸), plus one 🔔 line at
start; without it nothing changes. On the fake Toobit (tests/faketoobit.py) with the real executor. No network."""

from __future__ import annotations

import json
import socket

import pytest

from paperbot import executor as E
from paperbot.executor import ExecConfig, main
from paperbot.ladder import roe_price
from paperbot.notify import INFO
from paperbot.testnet import round_stop
from test_toobit import BTC, World
from test_toobit_plan_options import FIXED, LADDER, MIN, OPEN_JAN15, RT, TEMPLATE, events

PREFIX = "[투비트 실거래 실행기]"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def told(w, mark=None):
    """The INFO messages the executor sent (``mark``: only those starting with it after the prefix)."""
    out = [t for lv, t in w.note.messages if lv == INFO]
    return [t for t in out if mark is None or t.startswith(f"{PREFIX} {mark}")]


def ladder_world(tmp_path, **kw):
    return World(tmp_path, ladder_from="own", ladder=LADDER, leverage_by_symbol=FIXED, **kw)


def test_without_the_option_no_trade_is_told(tmp_path):
    """Every executor as before: the entry, the lock and the exit stay in the database only."""
    w = ladder_world(tmp_path)
    w.paper(stop=99.0)
    w.loop()
    w.fake.set_price(BTC, roe_price(1, 100.0, 40, 0.155, RT))
    w.loop()
    w.fake.set_price(BTC, 99.0)
    w.loop(2)
    assert events(w, "entry") and events(w, "own_lock") and events(w, "exit")
    assert told(w) == []


def test_the_start_entry_first_lock_and_a_winning_exit_are_told(tmp_path):
    w = ladder_world(tmp_path, trade_alerts=True)
    assert told(w) == [f"{PREFIX} {E.TRADE_ALERTS_ON_KO}"]
    w.paper(stop=99.0)
    w.loop()
    (_lv, entry_text, _d), = events(w, "entry")
    assert told(w, "🟢") == [f"{PREFIX} 🟢 {entry_text}"]
    assert entry_text.startswith("진입 BTCUSDT 롱 ") and "40배" in entry_text and "손절 99" in entry_text
    w.fake.set_price(BTC, roe_price(1, 100.0, 40, 0.155, RT))       # the first lock: +13 %
    w.loop()
    lock = round_stop(roe_price(1, 100.0, 40, 0.13, RT), 0.1, 1)
    assert w.ex.trade["own"]["lock"] == pytest.approx(0.13) and w.stops() == [(lock, 5.0)]
    (_lv, lock_text, d), = events(w, "own_lock")
    assert d["first"] is True
    assert told(w, "🔒") == [f"{PREFIX} 🔒 {lock_text}"]
    w.fake.set_price(BTC, roe_price(1, 100.0, 40, 0.215, RT))       # the next steps: recorded, not told
    w.loop()
    assert len(events(w, "own_lock")) >= 2 and all(d["first"] is False for _lv, _t, d in events(w, "own_lock")[1:])
    assert len(told(w, "🔒")) == 1
    (cur, _q), = w.stops()
    assert cur > lock
    w.fake.set_price(BTC, cur - 0.01)                                # the locked stop fires: a winning exit
    w.loop(2)
    assert w.ex.trade is None and w.fake.amt(BTC) == 0
    (_lv, exit_text, d), = events(w, "exit")
    assert d["pnl"] > 0
    assert told(w, "✅") == [f"{PREFIX} ✅ {exit_text}"] and not told(w, "❌")
    assert len(told(w)) == 4                                         # 🔔, 🟢, 🔒, ✅: nothing else


def test_a_losing_exit_is_told_red(tmp_path):
    w = World(tmp_path, trade_alerts=True)
    w.paper(stop=99.0)
    w.loop()
    w.fake.set_price(BTC, 98.9)                                      # the first stop fires
    w.loop(2)
    assert w.ex.trade is None
    (_lv, exit_text, d), = events(w, "exit")
    assert d["pnl"] < 0
    assert told(w, "❌") == [f"{PREFIX} ❌ {exit_text}"] and not told(w, "✅") and not told(w, "🔒")


def test_the_entry_message_goes_out_after_the_stop_is_on_the_exchange(tmp_path):
    """The entry's message is held with the protective work: a slow Telegram never delays the stop."""
    w = World(tmp_path, trade_alerts=True)
    seen = []

    class Watching:
        def send(self, level, text):
            seen.append((text, len(w.fake.live_stops(BTC))))
            w.note.send(level, text)
    w.ex.notifier = Watching()
    w.paper(stop=99.0)
    w.loop()
    (n_stops,) = [n for text, n in seen if text.startswith(f"{PREFIX} 🟢")]
    assert n_stops == 1


def test_a_planned_skip_is_told_and_still_no_alarm(tmp_path):
    w = World(tmp_path, trade_alerts=True, us_open_pre_min=30, us_open_pause_min=30)
    w.clock.t = OPEN_JAN15 - 3_000
    w.paper(stop=99.0)
    w.loop(3)
    assert w.ex.trade is None and w.fake.amt(BTC) == 0
    (lv, text, _d), = events(w, "us_open_skip")
    assert lv == "INFO"
    assert told(w, "⏸") == [f"{PREFIX} ⏸ {text}"]                   # once, silent (INFO), never a WARN
    assert not [t for lv, t in w.note.messages if lv != INFO and "나스닥" in t]


def test_the_liq_guard_skip_is_told(tmp_path):
    w = World(tmp_path, trade_alerts=True, liq_guard=True, liq_guard_mmr=0.005, leverage_by_symbol=FIXED)
    w.paper(stop=97.0)                                               # 3 % away at 40x: beyond the ~2 % liquidation
    w.loop()
    (_lv, text, _d), = events(w, "liq_skip")
    assert told(w, "⏸") == [f"{PREFIX} ⏸ {text}"]


@pytest.mark.parametrize("kind,data,mark", [
    ("entry", {}, "🟢 "), ("exit", {"pnl": 0.01}, "✅ "), ("exit", {"pnl": 0.0}, "❌ "), ("exit", {"pnl": -1}, "❌ "),
    ("exit", None, "❌ "), ("own_lock", {"first": True}, "🔒 "), ("own_lock", {"first": False}, None),
    ("own_lock", {"first": True, "closed": True}, None), ("own_lock", {}, None), ("liq_skip", {}, "⏸ "),
    ("macro_skip", {}, "⏸ "), ("us_open_skip", {}, "⏸ "), ("start", {}, None), ("own_prices", {}, None),
    ("stop_fired", {}, None)])
def test_which_events_are_told(kind, data, mark):
    assert E.trade_alert_mark(kind, data) == mark


def test_the_config_value_is_checked_and_the_template_has_it_on(tmp_path, capsys):
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert raw["trade_alerts"] is True
    raw["trade_alerts"] = "yes"
    assert "trade_alerts는 true 또는 false입니다" in ExecConfig.from_dict(raw).problems()
    assert main(["check-config", "--config", str(TEMPLATE)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "준비됨" and E.TRADE_ALERTS_LINE_KO in lines
    assert ExecConfig.from_dict({k: v for k, v in json.loads(TEMPLATE.read_text(encoding="utf-8")).items()
                                 if k != "trade_alerts"}).trade_alerts is False


def test_the_other_executor_templates_leave_it_off():
    """Only the Toobit executor needs it: the others' trades are told by the live watcher."""
    root = TEMPLATE.parent
    for p in sorted(root.glob("executor.live-*.json")):
        if p.name != "executor.live-toobit.json":
            assert "trade_alerts" not in json.loads(p.read_text(encoding="utf-8")), p.name


def test_a_service_without_telegram_says_so_in_its_journal(tmp_path, monkeypatch, capsys):
    """cmd_run's first line when the unit's environment has no Telegram: the alerts reach only the journal."""
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_CRITICAL"):
        monkeypatch.delenv(k, raising=False)
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    raw["db"] = str(tmp_path / "missing" / "x.db")
    raw["risk"]["kill_file"] = str(tmp_path / "STOP")
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(E, "ExecStore", lambda *a, **k: (_ for _ in ()).throw(OSError("no db")))
    with pytest.raises(OSError):
        main(["run", "--config", str(cfg)])
    err = capsys.readouterr().err
    assert "텔레그램 설정(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_CRITICAL)이 이 서비스 환경에 없어 알림은 이 기록(journal)에만" in err
