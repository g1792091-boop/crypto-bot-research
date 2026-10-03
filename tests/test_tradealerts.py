import json
import sqlite3

from paperbot import tradealerts as TA
from paperbot.notify import ListNotifier


def _db(path, engines, trades):
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE accounts (account_id TEXT PRIMARY KEY, strategy TEXT, timeframe TEXT, kind TEXT);
        CREATE TABLE state (k TEXT PRIMARY KEY, ts INTEGER, data TEXT);
        CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, symbol TEXT, entry_time INTEGER,
            exit_time INTEGER, exit_reason TEXT, leverage INTEGER, pnl REAL, roe REAL, equity_after REAL, data TEXT);""")
    for aid, kind in (("N02_ST_KST@5m", "strategy"), ("RANDOM_3@15m", "random"), ("N05_PSAR_POC@1h", "strategy")):
        c.execute("INSERT INTO accounts VALUES (?,?,?,?)", (aid, aid.split("@")[0], aid.split("@")[1], kind))
    c.execute("INSERT INTO state VALUES ('accounts', 1, ?)", (json.dumps({"engines": engines}),))
    for t in trades:
        c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                  "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)", t)
    c.commit()
    c.close()


def _pos(sym, side, t):
    return {"position": {"symbol": sym, "side": side, "entry_price": 100.0, "entry_time": t, "leverage": 20,
                         "margin": 1000.0, "stop_price": 98.0, "liq_price": 95.0, "qty": 200.0}}


def test_first_pass_is_silent_then_new_entries_and_exits_go_in_one_silent_message(tmp_path):
    db = str(tmp_path / "p.db")
    _db(db, {"N02_ST_KST@5m": _pos("BTCUSDT", 1, 1)}, [("N02_ST_KST@5m", "BTCUSDT", 0, 1, "SL", 20, -300.0, -0.3, 4700, "{}")])
    n = ListNotifier()
    kinds = TA.kinds_for("strategy")
    st, text = TA.pass_once(db, None, kinds, n, 10, {})
    assert text is None and n.messages == [] and st["last_id"] == 1            # the past is not announced
    c = sqlite3.connect(db)
    eng = {"N02_ST_KST@5m": _pos("BTCUSDT", 1, 1), "N05_PSAR_POC@1h": _pos("ETHUSDT", -1, 5),
           "RANDOM_3@15m": _pos("SOLUSDT", 1, 5)}
    c.execute("UPDATE state SET data = ? WHERE k = 'accounts'", (json.dumps({"engines": eng}),))
    c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, "
              "data) VALUES ('N02_ST_KST@5m', 'BCHUSDT', 2, 3, 'LOCK', 30, 412.0, 0.33, 5400, ?)",
              (json.dumps({"side": -1, "lock_roe": 0.2}),))
    c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, "
              "data) VALUES ('RANDOM_3@15m', 'SOLUSDT', 2, 3, 'SL', 20, -50.0, -0.3, 4950, '{}')")
    c.commit()
    c.close()
    st2, text = TA.pass_once(db, st, kinds, n, 10, {"N05_PSAR_POC": "PSAR·POC 캔들"})
    assert len(n.messages) == 1 and n.messages[0][0] == "INFO"                  # INFO = silent
    assert "진입 1 · 청산 1" in text and "숏 ETH 20배" in text and "PSAR·POC 캔들 · 1시간" in text
    assert "+$412 (+33.0%) 익절 잠금 +20% · 숏 BCH 30배" in text and "SOL" not in text   # coin flips left out
    assert st2["last_id"] == 3
    st3, text = TA.pass_once(db, st2, kinds, n, 10, {})
    assert text is None and len(n.messages) == 1                                # nothing new, nothing sent
    st4, text = TA.pass_once(db, st2, TA.kinds_for("all"), n, 10, {})
    assert "동전 봇 3 · 15분" in text                                           # 'all' adds the coin flips


def test_a_failed_send_keeps_the_cursor_so_the_trades_go_next_time(tmp_path):
    db = str(tmp_path / "p.db")
    _db(db, {}, [])
    st, _ = TA.pass_once(db, None, TA.kinds_for("strategy"), ListNotifier(), 1, {})

    class Down:
        def send(self, level, text):
            return False
    c = sqlite3.connect(db)
    c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, "
              "data) VALUES ('N02_ST_KST@5m', 'BTCUSDT', 2, 3, 'SL', 20, -10.0, -0.01, 4990, '{}')")
    c.commit()
    c.close()
    st2, text = TA.pass_once(db, st, TA.kinds_for("strategy"), Down(), 1, {})
    assert st2 == st and text is None
    st3, text = TA.pass_once(db, st2, TA.kinds_for("strategy"), ListNotifier(), 1, {})
    assert "청산 1" in text and st3["last_id"] == 1


def test_long_bursts_are_capped_and_the_state_file_round_trips(tmp_path):
    exits = [{"id": i, "account_id": "N02_ST_KST@5m", "kind": "strategy", "symbol": "BTCUSDT", "exit_reason": "SL",
              "leverage": 20, "pnl": -float(i), "roe": -0.1, "side": 1} for i in range(1, 31)]
    text = TA.message([], exits, 0, 0, {}, min_usd=5)
    assert text.count("손절 · 롱 BTC") == TA.MAX_LINES and "외 10건" in text and "청산 합계 -$465" in text
    p = str(tmp_path / "s.json")
    TA.save_state(p, {"last_id": 7, "open": {"a": "k"}})
    assert TA.load_state(p) == {"last_id": 7, "open": {"a": "k"}}
    assert TA.load_state(str(tmp_path / "none.json")) is None


def test_price_alerts_fire_once_with_sound_and_again_after_a_rearm(tmp_path):
    from paperbot.agents import rooms_db as R
    from paperbot.notify import WARN
    inbox = str(tmp_path / "inbox.db")
    c = R.open_inbox_rw(inbox)
    a = R.add_price_alert(c, "BTCUSDT", "below", 65_000, "지지선", ts=1)
    b = R.add_price_alert(c, "ETHUSDT", "above", 4_000, ts=2)
    gone = R.add_price_alert(c, "SOLUSDT", "above", 1, ts=3)
    R.change_price_alert(c, gone, "delete", ts=4)
    n, st = ListNotifier(), {}
    prices = {"BTCUSDT": 65_500.0, "ETHUSDT": 3_900.0, "SOLUSDT": 150.0}
    assert TA.check_price_alerts(inbox, st, n, 10, lambda: prices) == [] and st["armed"] == 2
    prices["BTCUSDT"] = 64_990.0
    sent = TA.check_price_alerts(inbox, st, n, 20, lambda: prices)
    assert len(sent) == 1 and n.messages[0][0] == WARN and "BTC 65,000.0 아래로 도달" in sent[0] and "지지선" in sent[0]
    assert st["fired"] == {str(a): 20}
    assert TA.check_price_alerts(inbox, st, n, 30, lambda: prices) == []          # fired: off until re-armed
    R.change_price_alert(c, a, "rearm", ts=40)
    assert len(TA.check_price_alerts(inbox, st, n, 50, lambda: prices)) == 1
    # a failed send is tried again
    class Down:
        def send(self, level, text):
            return False
    prices["ETHUSDT"] = 4_001.0
    assert TA.check_price_alerts(inbox, st, Down(), 60, lambda: prices) == [] and str(b) not in st["fired"]
    assert len(TA.check_price_alerts(inbox, st, n, 70, lambda: prices)) == 1
    # nothing armed: no price request at all
    def boom():
        raise AssertionError("no request without an armed alert")
    R.change_price_alert(c, a, "delete", ts=80)
    assert TA.check_price_alerts(inbox, st, n, 90, boom) == [] and st["armed"] == 0
    # an old inbox.db without the tables, or none at all
    assert TA.check_price_alerts(str(tmp_path / "none.db"), {}, n, 1, boom) == []


def test_fetch_prices_reads_every_symbol():
    rows = [{"symbol": "BTCUSDT", "price": "65000.1", "time": 1}, {"symbol": "ETHUSDT", "price": "3000"}]
    assert TA.fetch_prices(get=lambda url: rows) == {"BTCUSDT": 65000.1, "ETHUSDT": 3000.0}
