import json
import sqlite3

import pytest

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
    assert "진입 1 · 청산 1 · 합계 +$412" in text and "🔴 숏 · ETH 20배" in text and "📈 모의 진입 · PSAR·POC 캔들 1시간" in text
    assert "✅ 모의 이익 +$412 · N02_ST_KST 5분\n🔴 숏 · BCH 30배 · 익절 잠금(+20%)\nROE +33.0%\n남은 잔고 $5,400" in text
    assert "SOL" not in text                                                    # coin flips left out
    assert st2["last_id"] == 3
    st3, text = TA.pass_once(db, st2, kinds, n, 10, {})
    assert text is None and len(n.messages) == 1                                # nothing new, nothing sent
    st4, text = TA.pass_once(db, st2, TA.kinds_for("all"), n, 10, {})
    assert "동전 봇 3 15분" in text                                           # 'all' adds the coin flips


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
    assert text.startswith("❌ 모의 손실 -$10 · ") and st3["last_id"] == 1


def test_long_bursts_are_capped_and_the_state_file_round_trips(tmp_path):
    exits = [{"id": i, "account_id": "N02_ST_KST@5m", "kind": "strategy", "symbol": "BTCUSDT", "exit_reason": "SL",
              "leverage": 20, "pnl": -float(i), "roe": -0.1, "side": 1} for i in range(1, 31)]
    text = TA.message([], exits, 0, 0, {}, min_usd=5)
    assert text.count(" · BTC · -10.0% · ") == TA.MAX_LINES and "외 18건 — 대시보드 '오늘 체결'" in text
    assert "청산 30 · 합계 -$465" in text and "❌ 손실 30건 -$465" in text and "- N02_ST_KST 5분 · BTC · -10.0% · -$30" in text
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
    assert len(sent) == 1 and n.messages[0][0] == WARN and sent[0].startswith("🔔 가격 알림 · BTC 65,000 이탈\n\n지금 64,990.0")
    assert "\n메모: 지지선\n" in sent[0]
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


# ---------------------------------------------------------------- the owners' layout (2026-10-04)
NOW = 1791116100000            # 2026-10-04 12:15 UTC = 21:15 KST
NAMES = {"N14_ICHI_RSI": "일목·RSI", "N07_ICHI_CMO": "일목·CMO", "S2_ST_ROC": "슈퍼트렌드·ROC", "N01_ST_EMA": "슈퍼트렌드·EMA",
         "S5_DONCHIAN_MFI": "돈치안·MFI", "N24_DMI": "DMI"}


def E(aid, sym, side, entry, lev, margin, stop, kind="strategy", **kw):
    return (aid, {"symbol": sym, "side": side, "entry": entry, "entry_time": NOW, "leverage": lev, "margin": margin,
                  "stop": stop, "kind": kind, **kw})


def X(i, aid, sym, side, reason, lev, pnl, roe, eq, lock=None, kind="strategy"):
    return {"id": i, "account_id": aid, "symbol": sym, "exit_time": NOW, "exit_reason": reason, "leverage": lev,
            "pnl": pnl, "roe": roe, "kind": kind, "side": side, "lock_roe": lock, "equity_after": eq}


def test_one_entry_shows_the_ladder_prices_and_the_stop_distance():
    from paperbot.config import v3_settings
    from paperbot.ladder import roe_price
    rt = v3_settings().round_trip_cost
    text = TA.message([E("N14_ICHI_RSI@15m", "BTCUSDT", 1, 64210.5, 30, 1500.0, 63550.0)], [], 47, NOW, NAMES)
    assert text == ("📈 모의 진입 · 일목·RSI 15분\n🟢 롱 · BTC 30배\n진입가 64,210.5\n"
                    f"익절 잠금 시작 {TA.px(roe_price(1, 64210.5, 30, 0.12, rt))} (+12%)\n"
                    f"→ 손절을 {TA.px(roe_price(1, 64210.5, 30, 0.10, rt))}로 올림 (+10% 확보)\n"
                    "손절가 63,550.0 (-1.03%)\n증거금 $1,500\n10/04 21:15")
    assert "64,557.2 (+12%)" in text and "64,514.4로 올림" in text
    # a short at 50x; a copy with its own lock_start rule (first lock +20%: armed at +22%); margin share; best tier
    t = TA.message([E("S2_ST_ROC@1h~c1", "ETHUSDT", -1, 2400.0, 50, 2500.0, 2420.0, kind="copy", first_lock=0.2,
                      round_trip=rt, wallet=5000.0, tier="best")], [], 1, NOW, NAMES)
    lines = t.split("\n")
    assert lines[0] == "📈 모의 진입 · 복제 슈퍼트렌드·ROC 1시간" and lines[1] == "🔴 숏 · ETH 50배 · 좋은 자리"
    assert lines[3] == f"익절 잠금 시작 {TA.px(roe_price(-1, 2400.0, 50, 0.22, rt))} (+22%)"
    assert lines[4] == f"→ 손절을 {TA.px(roe_price(-1, 2400.0, 50, 0.20, rt))}로 내림 (+20% 확보)"
    assert lines[5] == "손절가 2,420.0 (+0.83%)" and lines[6] == "증거금 $2,500 (50%)"


def test_one_exit_shows_the_reason_roe_and_balance():
    win = TA.message([], [X(1, "N07_ICHI_CMO@30m", "BTCUSDT", 1, "LOCK", 20, 84.2, 0.097, 4896.4, 0.10)], 47, NOW, NAMES)
    assert win == "✅ 모의 이익 +$84 · 일목·CMO 30분\n🟢 롱 · BTC 20배 · 익절 잠금(+10%)\nROE +9.7%\n남은 잔고 $4,896\n10/04 21:15"
    loss = TA.message([], [X(2, "NL2@15m", "LTCUSDT", -1, "SL", 40, -147.0, -0.118, 4612, kind="newlab")], 1, NOW, NAMES)
    assert loss.split("\n")[:3] == ["❌ 모의 손실 -$147 · 새 매매법 NL2 15분", "🔴 숏 · LTC 40배 · 손절", "ROE -11.8%"]
    for reason, ko in (("LIQ", "강제청산"), ("BUST", "파산")):
        t = TA.message([], [X(3, "N24_DMI@30m", "BTCUSDT", 1, reason, 50, -500.0, -1.0, 9.0)], 0, NOW, NAMES)
        assert t.split("\n")[1] == f"🟢 롱 · BTC 50배 · {ko}"


def test_small_batch_has_a_header_blocks_and_the_open_count():
    text = TA.message([E("N14_ICHI_RSI@15m", "BTCUSDT", 1, 64210.5, 30, 1500.0, 63550.0),
                       E("S2_ST_ROC@1h", "ETHUSDT", -1, 2412.37, 20, 820.0, 2448.9)],
                      [X(1, "N07_ICHI_CMO@30m", "BTCUSDT", 1, "LOCK", 20, 84.2, 0.097, 4896, 0.10)], 47, NOW, NAMES)
    blocks = text.split("\n\n")
    assert blocks[0] == "📊 모의 거래 알림 10/04 21:15 · 진입 2 (롱 1·숏 1) · 청산 1 · 합계 +$84"
    assert blocks[1].startswith("📈 모의 진입 · 일목·RSI 15분\n") and blocks[2].startswith("📈 모의 진입 · 슈퍼트렌드·ROC 1시간\n🔴 숏")
    assert "익절 잠금 시작 2,394.5 (+12%)" in blocks[2] and not blocks[2].endswith("21:15")
    assert blocks[3].startswith("✅ 모의 이익 +$84 · 일목·CMO 30분") and blocks[-1] == "열린 포지션 47개"


def test_large_batch_is_grouped_by_side_and_coin_then_profit_and_loss():
    es = [E("N14_ICHI_RSI@15m", "BTCUSDT", 1, 64210.5, 30, 1500.0, 63550.0),
          E("N07_ICHI_CMO@15m", "BTCUSDT", 1, 64210.5, 30, 1420.0, 63480.0),
          E("N01_ST_EMA@30m", "BTCUSDT", 1, 64210.5, 20, 1310.0, 63320.0),
          E("S5_DONCHIAN_MFI@4h", "SOLUSDT", 1, 141.23, 40, 760.0, 136.80),
          E("S2_ST_ROC@1h", "ETHUSDT", -1, 2412.37, 20, 820.0, 2448.9)]
    xs = [X(1, "N07_ICHI_CMO@30m", "BTCUSDT", 1, "LOCK", 20, 84.2, 0.097, 4896, 0.10),
          X(2, "S5_DONCHIAN_MFI@4h", "LTCUSDT", -1, "SL", 50, -132.6, -0.118, 4612),
          X(3, "N24_DMI@30m", "DOGEUSDT", -1, "SL", 20, -34.1, -0.052, 3905),
          X(4, "N14_ICHI_RSI@1h", "SOLUSDT", 1, "LOCK", 30, 212.0, 0.148, 5640, 0.15)]
    text = TA.message(es, xs, 52, NOW, NAMES)
    assert text == "\n".join([
        "📊 모의 거래 알림 10/04 21:15 · 진입 5 (롱 4·숏 1) · 청산 4 · 합계 +$130", "",
        "🟢 롱 4건", "BTC · 진입 64,210.5", "- 일목·RSI 15분 · 30배 · 손절 63,550.0", "- 일목·CMO 15분 · 30배 · 손절 63,480.0",
        "- 슈퍼트렌드·EMA 30분 · 20배 · 손절 63,320.0", "SOL · 진입 141.23", "- 돈치안·MFI 4시간 · 40배 · 손절 136.80", "",
        "🔴 숏 1건", "ETH · 진입 2,412.4", "- 슈퍼트렌드·ROC 1시간 · 20배 · 손절 2,448.9", "",
        "✅ 이익 2건 +$296", "- 일목·RSI 1시간 · SOL · +14.8% · +$212 · 잔고 $5,640",
        "- 일목·CMO 30분 · BTC · +9.7% · +$84 · 잔고 $4,896", "",
        "❌ 손실 2건 -$167", "- 돈치안·MFI 4시간 · LTC · -11.8% · -$133 · 잔고 $4,612",
        "- DMI 30분 · DOGE · -5.2% · -$34 · 잔고 $3,905", "", "열린 포지션 52개"])


def test_sections_are_capped_at_12_lines():
    es = [E(f"N14_ICHI_RSI@15m", "BTCUSDT" if i % 2 else "ETHUSDT", 1, 100.0 + i, 20, 1000.0 - i, 99.0) for i in range(15)]
    text = TA.message(es, [], 15, NOW, NAMES)
    assert text.count("\n- ") == 12 and "외 3건 — 대시보드 포지션 탭" in text
    assert "BTC\n- " in text                                                  # entry prices differ: per line
    assert "· 진입 101.00 · 손절 99.00" in text


def test_read_takes_equity_after_and_the_copy_rule(tmp_path):
    db = str(tmp_path / "p.db")
    c = sqlite3.connect(db)
    c.executescript("""CREATE TABLE accounts (account_id TEXT PRIMARY KEY, strategy TEXT, timeframe TEXT, kind TEXT,
            data TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE state (k TEXT PRIMARY KEY, ts INTEGER, data TEXT);
        CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, symbol TEXT, entry_time INTEGER,
            exit_time INTEGER, exit_reason TEXT, leverage INTEGER, pnl REAL, roe REAL, equity_after REAL, data TEXT);""")
    c.execute("INSERT INTO accounts VALUES ('S2_ST_ROC@1h~c1', 'S2_ST_ROC', '1h', 'copy', ?)", (json.dumps({"first_lock": 0.3}),))
    c.execute("INSERT INTO accounts VALUES ('S2_ST_ROC@1h', 'S2_ST_ROC', '1h', 'strategy', '{}')")
    c.execute("INSERT INTO state VALUES ('run', 1, ?)", (json.dumps({"taker_fee": 0.0004}),))
    eng = {"S2_ST_ROC@1h~c1": dict(_pos("BTCUSDT", 1, 1), wallet=4000.0), "S2_ST_ROC@1h": _pos("ETHUSDT", -1, 1)}
    c.execute("INSERT INTO state VALUES ('accounts', 1, ?)", (json.dumps({"engines": eng}),))
    c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, "
              "data) VALUES ('S2_ST_ROC@1h', 'BTCUSDT', 0, 1, 'SL', 20, -10, -0.1, 4321.5, '{\"side\": 1}')")
    c.commit()
    c.close()
    pos, exits, top = TA.read(db, TA.kinds_for("strategy"), 0)
    assert pos["S2_ST_ROC@1h~c1"]["first_lock"] == 0.3 and pos["S2_ST_ROC@1h"]["first_lock"] == 0.10
    assert pos["S2_ST_ROC@1h~c1"]["round_trip"] == pytest.approx(2 * (0.0004 + 0.0002))      # the run's fee
    assert pos["S2_ST_ROC@1h~c1"]["wallet"] == 4000.0
    assert exits[0]["equity_after"] == 4321.5 and exits[0]["side"] == 1 and top == 1
    text = TA.message([("S2_ST_ROC@1h~c1", pos["S2_ST_ROC@1h~c1"])], [], 2, NOW, {})
    assert "(+32%)" in text and "(+30% 확보)" in text and "증거금 $1,000 (25%)" in text


# ---------------------------------------------------------------- paper v4: groups, the reel, '모의', dry run
from paperbot.config import REEL_NAME  # noqa: E402

T0 = 1791147600000            # 2026-10-04 21:00 UTC = 10/05 06:00 KST (a 5m boundary)
FIVE = 300_000
V4_ROWS = (("N14_ICHI_RSI@15m", "strategy", {"group": "core"}),
           ("F9_FVG@15m", "ds200", {"group": "ds200", "family": "F9", "exits": "house"}),
           (f"{REEL_NAME}@5m", "reel", {"group": "reel", "exits": "reel"}),
           ("RANDOM_1@5m", "random", {"group": "flip", "exits": "reel"}),
           ("RANDOM_2@15m", "random", {"group": "flip", "exits": "house"}),
           ("S2_ST_ROC@1h~c1", "copy", {"first_lock": 0.2}))


def _v4_db(path, engines, trades=(), run=None):
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE accounts (account_id TEXT PRIMARY KEY, strategy TEXT, timeframe TEXT, kind TEXT,
            data TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE state (k TEXT PRIMARY KEY, ts INTEGER, data TEXT);
        CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, symbol TEXT, entry_time INTEGER,
            exit_time INTEGER, exit_reason TEXT, leverage INTEGER, pnl REAL, roe REAL, equity_after REAL, data TEXT);""")
    for aid, kind, data in V4_ROWS:
        strat, _, tf = aid.partition("@")
        c.execute("INSERT INTO accounts VALUES (?,?,?,?,?)", (aid, strat, tf.split("~")[0], kind, json.dumps(data)))
    c.execute("INSERT INTO state VALUES ('accounts', ?, ?)", (T0, json.dumps({"engines": engines})))
    if run:
        c.execute("INSERT INTO state VALUES ('run', 1, ?)", (json.dumps(run),))
    for t in trades:
        c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                  "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)", t)
    c.commit()
    c.close()


def _house(sym, side, t, entry=100.0):
    return {"position": {"symbol": sym, "side": side, "entry_price": entry, "entry_time": t, "leverage": 30,
                         "margin": 1500.0, "stop_price": entry * (0.98 if side > 0 else 1.02), "tp_price": float("nan"),
                         "liq_price": 90.0, "qty": 450.0, "tier": "normal", "signal": {"ts": t - 1, "meta": {}}},
            "wallet": 5000.0}


def _reel(sym, t, entry=100.0, stop=99.2, target=101.0):
    b = t - t % FIVE
    st = {"closes": [entry] * 19, "bucket": b, "last": None, "end": b + 96 * FIVE}
    return {"position": {"symbol": sym, "side": 1, "entry_price": entry, "entry_time": t, "leverage": 30,
                         "margin": 1500.0, "stop_price": stop, "tp_price": target, "liq_price": 97.0, "qty": 450.0,
                         "tier": "normal", "signal": {"ts": t - 1, "meta": {"reel_exit": st}}},
            "wallet": 5000.0}


def _trade(aid, sym, t_in, t_out, reason, pnl, side=1, entry=100.0, stop=98.0, tp=None):
    d = {"side": side, "entry_price": entry, "margin": 1500.0, "stop_initial": stop, "stop_price": stop,
         "tier": "normal", "tp_price": tp, "equity_after": 5000.0 + pnl}
    return (aid, sym, t_in, t_out, reason, 30, pnl, pnl / 1500.0, 5000.0 + pnl, json.dumps(d))


def _first_lines(text):
    return text.split("\n")[0]


def test_modes_by_group_core_is_the_default_and_strategy_its_old_name():
    assert TA.mode_of(None) == TA.mode_of("strategy") == TA.mode_of(" Core ") == TA.mode_of("nonsense") == "core"
    assert TA.mode_of("ALL") == "all" and TA.mode_of("off") == "off"
    assert set(TA.kinds_for("core")) == {"strategy", "reel", "copy", "newlab"} == set(TA.kinds_for("strategy"))
    assert set(TA.kinds_for("all")) == {"strategy", "reel", "copy", "newlab", "ds200", "random"}
    assert set(TA.count_kinds_for("core")) == {"ds200", "random"} and TA.count_kinds_for("all") == ()


def test_one_account_per_group_default_names_core_reel_and_extras_and_counts_the_rest(tmp_path):
    db = str(tmp_path / "p.db")
    _v4_db(db, {})
    kinds, ck = TA.kinds_for("core"), TA.count_kinds_for("core")
    n = ListNotifier()
    st, _ = TA.pass_once(db, None, kinds, n, T0, NAMES, count_kinds=ck)
    eng = {"N14_ICHI_RSI@15m": _house("BTCUSDT", 1, T0), "F9_FVG@15m": _house("ETHUSDT", -1, T0),
           f"{REEL_NAME}@5m": _reel("SOLUSDT", T0), "RANDOM_1@5m": _reel("DOGEUSDT", T0, entry=0.2, stop=0.19,
                                                                          target=0.21),
           "RANDOM_2@15m": _house("LTCUSDT", 1, T0), "S2_ST_ROC@1h~c1": _house("BCHUSDT", -1, T0)}
    c = sqlite3.connect(db)
    c.execute("UPDATE state SET data = ? WHERE k = 'accounts'", (json.dumps({"engines": eng}),))
    c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
              "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)", _trade("F9_FVG@15m", "XRPUSDT", 1, 2, "SL", -321.0))
    c.commit()
    c.close()
    st2, text = TA.pass_once(db, st, kinds, n, T0 + 80_000, NAMES, count_kinds=ck)
    assert text.startswith("📊 모의 거래 알림 ") and "진입 3 " in _first_lines(text)        # core, reel, copy
    assert "일목·RSI 15분" in text and "릴스 5분 단타" in text and "복제 슈퍼트렌드·ROC 1시간" in text
    assert "딥시크" not in text.replace("그 밖에 딥시크", "") and "동전 봇" not in text and "-$321" not in text
    assert text.endswith("열린 포지션 3개\n그 밖에 딥시크 진입 1 · 청산 1 · 동전 진입 2 (개수만)")
    assert "counts" not in st2                                          # carried: nothing pending
    # 'all' names every group one by one, the 5m coin flip with the reel's exits
    st3, text = TA.pass_once(db, st, TA.kinds_for("all"), ListNotifier(), T0 + 80_000, NAMES)
    assert "딥시크 F9_FVG (FVG·오더 블록) 15분" in text and "동전 봇 1 5분" in text and "동전 봇 2 15분" in text
    assert "그 밖에" not in text and "진입 6 " in _first_lines(text)


def test_the_reel_entry_shows_its_stop_band_target_and_time_exit_and_no_ladder(tmp_path):
    db = str(tmp_path / "p.db")
    _v4_db(db, {f"{REEL_NAME}@5m": _reel("BTCUSDT", T0 + 9_000, entry=64210.5, stop=63550.0, target=64800.0)},
           run={"taker_fee": 0.0005})
    pos, _, _ = TA.read(db, TA.kinds_for("core"), 0)
    p = pos[f"{REEL_NAME}@5m"]
    assert p["exits"] == "reel" and p["tp"] == 64800.0 and p["time_exit"] == T0 + 96 * FIVE
    text = TA.message([(f"{REEL_NAME}@5m", p)], [], 1, T0 + 80_000, NAMES)
    assert text == ("📈 모의 진입 · 릴스 5분 단타 (볼린저 20·2 + 200선)\n🟢 롱 · BTC 30배\n진입가 64,210.5\n"
                    "익절 목표 64,800.0 (+0.92%) · 볼린저 윗선\n→ 5분마다 새 윗선으로 바뀜 (익절 잠금 없음)\n"
                    "손절가 63,550.0 (-1.03%)\n시간 청산 10/05 14:00 (8시간)\n증거금 $1,500 (30%)\n10/05 06:01")
    assert "5분" in text.split("\n")[0] and "익절 잠금 시작" not in text and "손절을" not in text
    # in a bundle of many entries: the stop and the target on its line
    many = [(f"{REEL_NAME}@5m", p)] + [E(f"N14_ICHI_RSI@{tf}", "ETHUSDT", -1, 2400.0, 30, 900.0, 2450.0)
                                       for tf in ("15m", "30m", "1h", "4h")]
    assert "- 릴스 5분 단타 (볼린저 20·2 + 200선) · 30배 · 손절 63,550.0 · 목표 64,800.0" in TA.message(many, [], 5, T0, NAMES)
    # a 5m coin flip with the reel's exits gets the same block
    flip = dict(p, kind="random")
    assert TA.entry_block("RANDOM_1@5m", flip, NAMES)[0] == "📈 모의 진입 · 동전 봇 1 5분"
    assert "익절 목표 64,800.0 (+0.92%) · 볼린저 윗선" in TA.entry_block("RANDOM_1@5m", flip, NAMES)
    # the reel's exit reasons
    for reason, ko in (("TP", "익절(볼린저 윗선)"), ("TIME", "시간 청산(8시간)"), ("SL", "손절")):
        x = X(1, f"{REEL_NAME}@5m", "BTCUSDT", 1, reason, 30, 50.0, 0.03, 5050, kind="reel")
        x["exits"] = "reel"
        assert TA.message([], [x], 0, NOW, NAMES).split("\n")[1] == f"🟢 롱 · BTC 30배 · {ko}"
    assert TA.REASON_KO["TIME"] == "시간 청산"


def test_counted_only_trades_wait_for_a_message_or_go_alone_after_an_hour(tmp_path):
    db = str(tmp_path / "p.db")
    _v4_db(db, {})
    kinds, ck = TA.kinds_for("core"), TA.count_kinds_for("core")
    n = ListNotifier()
    st, _ = TA.pass_once(db, None, kinds, n, T0, NAMES, count_kinds=ck)

    def add(*trades):
        c = sqlite3.connect(db)
        for t in trades:
            c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                      "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)", t)
        c.commit()
        c.close()
    add(_trade("F9_FVG@15m", "BTCUSDT", 1, 2, "SL", -40.0), _trade("RANDOM_2@15m", "ETHUSDT", 1, 2, "LOCK", 90.0))
    st, text = TA.pass_once(db, st, kinds, n, T0 + 60_000, NAMES, count_kinds=ck)
    assert text is None and n.messages == []
    assert st["counts"] == {"ds200": {"in": 0, "out": 1}, "flip": {"in": 0, "out": 1}}
    assert st["counts_since"] == T0 + 60_000
    TA.save_state(str(tmp_path / "s.json"), st)
    st = TA.load_state(str(tmp_path / "s.json"))                       # the pending counts survive a restart
    add(_trade("F9_FVG@15m", "BTCUSDT", 3, 4, "SL", -40.0))
    st, text = TA.pass_once(db, st, kinds, n, T0 + 30 * 60_000, NAMES, count_kinds=ck)
    assert text is None and st["counts"]["ds200"]["out"] == 2 and st["counts_since"] == T0 + 60_000

    class Down:
        def send(self, level, text):
            return False
    st_failed, text = TA.pass_once(db, st, kinds, Down(), T0 + 61 * 60_000, NAMES, count_kinds=ck)
    assert text is None and st_failed == st                              # not delivered: kept for the next pass
    st, text = TA.pass_once(db, st, kinds, n, T0 + 61 * 60_000, NAMES, count_kinds=ck)
    assert text == "📊 모의 거래 수 · 10/05 07:01 · 지난 1시간\n\n딥시크 청산 2\n동전 청산 1\n손익은 대시보드 그룹 화면에서"
    assert n.messages == [("INFO", text)] and "counts" not in st and "$" not in text


def test_every_paper_trade_message_says_moui_on_its_first_line():
    es = [E("N14_ICHI_RSI@15m", "BTCUSDT", 1, 64210.5, 30, 1500.0, 63550.0)]
    xs = [X(1, "N07_ICHI_CMO@30m", "BTCUSDT", 1, "LOCK", 20, 84.2, 0.097, 4896, 0.10),
          X(2, "N24_DMI@30m", "BTCUSDT", 1, "SL", 20, -84.2, -0.097, 4796)]
    texts = [TA.message(es, [], 1, NOW, NAMES), TA.message([], xs[:1], 1, NOW, NAMES),
             TA.message([], xs[1:], 1, NOW, NAMES), TA.message(es, xs, 1, NOW, NAMES),
             TA.message(es * 5, xs * 3, 1, NOW, NAMES), TA.count_message({"ds200": {"in": 1}}, NOW - 3_600_000, NOW)]
    for t in texts:
        assert "모의" in _first_lines(t), t


def test_dry_run_prints_the_messages_and_the_count_per_hour_and_writes_nothing(tmp_path, capsys):
    import os
    db = str(tmp_path / "p.db")
    trades = []
    for h in range(3):                       # three hours: core and reel trades each hour, DeepSeek and flips counted
        t = T0 - (3 - h) * 3_600_000
        trades += [_trade("N14_ICHI_RSI@15m", "BTCUSDT", t, t + 600_000, "SL", -30.0),
                   _trade(f"{REEL_NAME}@5m", "SOLUSDT", t + 5 * 60_000, t + 40 * 60_000, "TP", 55.0, tp=101.0),
                   _trade("F9_FVG@15m", "ETHUSDT", t, t + 900_000, "SL", -10.0),
                   _trade("RANDOM_1@5m", "DOGEUSDT", t, t + 300_000, "TIME", 5.0)]
    _v4_db(db, {"N14_ICHI_RSI@15m": _house("BTCUSDT", 1, T0 - 30 * 60_000)}, trades)
    before = (os.path.getmtime(db), sorted(os.listdir(tmp_path)))
    res = TA.dry_run(db, "core", 60, hours=4, names=NAMES, show=2)
    out = capsys.readouterr().out
    assert (os.path.getmtime(db), sorted(os.listdir(tmp_path))) == before            # read-only, no state file
    assert res["mode"] == "core" and res["end"] == T0 and res["messages"] == len(res["texts"]) > 0
    assert all("모의" in _first_lines(t) for t in res["texts"])
    joined = "\n".join(res["texts"])
    assert "릴스 5분 단타" in joined and "익절(볼린저 윗선)" in joined and "딥시크 F9_FVG" not in joined
    assert "그 밖에 딥시크" in joined and "동전 봇 1 5분" not in joined
    g = res["groups"]
    assert g["core"] == {"in": 4, "out": 3, "shown": True} and g["reel"] == {"in": 3, "out": 3, "shown": True}
    assert g["ds200"] == {"in": 3, "out": 3, "shown": False} and g["flip"]["shown"] is False
    assert sum(h["messages"] for h in res["per_hour"].values()) == res["messages"]
    assert out.startswith("모의 거래 알림 미리보기 (보내지 않음) · p.db · 모드 core · 60초마다")
    assert "시간(KST)" in out and "- 매매법: 진입 4 · 청산 3 · 건별 알림" in out and "- 딥시크: 진입 3 · 청산 3 · 개수만" in out
    assert out.count("\n----- ") == 2 and "(메시지 " in out
    # 'all' announces DeepSeek and the flips one by one: more messages, nothing counted
    res_all = TA.dry_run(db, "all", 60, hours=4, names=NAMES, show=0, out=lambda *_: None)
    assert res_all["messages"] >= res["messages"] and "딥시크 F9_FVG" in "\n".join(res_all["texts"])
    assert res_all["count_messages"] == 0 and all(v["shown"] for v in res_all["groups"].values())
    # the command line: --dry-run --db, nothing else needed
    assert TA.main(["--dry-run", "--db", db, "--hours", "4", "--show", "0"]) == 0
    assert "합계: 메시지" in capsys.readouterr().out


def test_dry_run_counts_a_lone_counted_hour_as_one_count_message(tmp_path):
    db = str(tmp_path / "p.db")
    trades = [_trade("F9_FVG@15m", "ETHUSDT", T0 - 3 * 3_600_000 + k * 60_000, T0 - 3 * 3_600_000 + k * 60_000 + FIVE,
                     "SL", -1.0) for k in range(10)]
    _v4_db(db, {}, trades)
    res = TA.dry_run(db, "core", 60, hours=4, names=NAMES, show=0, out=lambda *_: None)
    assert res["messages"] == res["count_messages"] == 1
    assert res["texts"][0].split("\n")[2] == "딥시크 진입 10 · 청산 10"
