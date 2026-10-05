import os

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot import Bar, Brackets, Signal  # noqa: E402
from paperbot.accounts import AccountBook  # noqa: E402
from paperbot.config import V3_SYMBOLS, v3_settings  # noqa: E402
from paperbot.dash.app import check_password, create_app, hash_password, make_token, token_ok  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

MIN = 60_000
S = v3_settings()
SECRET = b"x" * 32


def _store(path):
    store = Store3(path)
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store, equity_every_ms=MIN)
    book.open_accounts([{"strategy": "A", "timeframe": "15m", "kind": "strategy"},
                        {"strategy": "RANDOM_1", "timeframe": "15m", "kind": "random"}], 0)
    flat = lambda i, lo=99.95: {s: Bar(s, i * MIN, i * MIN + MIN - 1, 100.0, 100.05, lo, 100.0) for s in V3_SYMBOLS}
    book.step(0, flat(0))
    book.submit("A@15m", Signal(ts=MIN - 1, symbol="BTCUSDT", timeframe="15m", strategy_id="A", side=1,
                                stop_price=0.0, tier="best", atr=0.2, meta={"stop_dist": 0.4}))
    book.step(MIN, flat(1))
    book.step(2 * MIN, flat(2, lo=99.0))        # stop hit: one losing trade
    store.log_signals([{"bar_close": MIN, "timeframe": "15m", "strategy": "A", "symbol": "BTCUSDT", "side": 1,
                        "atr": 0.2, "ref_price": 100.0, "ref_time": MIN + 5000, "delay_ms": 5000,
                        "status": "SUBMITTED"}])
    store.put_state("heartbeat", 123, {"steps": 3})
    store.commit()
    return store


@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "p.db")
    _store(db).close()
    app = create_app(db, hash_password("correct horse battery"), SECRET,
                     candles=lambda s, i, n: [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}])
    return TestClient(app)


def test_password_and_token():
    h = hash_password("abc")
    assert check_password("abc", h) and not check_password("abd", h)
    t = make_token(SECRET, now=1000)
    assert token_ok(SECRET, t, now=1001)
    assert not token_ok(SECRET, t, now=1000 + 8 * 86400)
    assert not token_ok(b"y" * 32, t, now=1001)
    assert not token_ok(SECRET, t[:-1] + ("0" if t[-1] != "0" else "1"), now=1001)


def test_login_required(client):
    assert client.get("/api/board").status_code == 401
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/login?next=/"     # back to '/' after the login
    r = client.get("/v3", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/login?next=/v3"
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401


def test_board_account_status(client):
    assert client.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    b = client.get("/api/board").json()
    by = {a["account_id"]: a for a in b["accounts"]}
    assert by["A@15m"]["trades"] == 1 and by["A@15m"]["wallet"] < 5000
    assert by["RANDOM_1@15m"]["wallet"] == 5000 == b["initial"]
    assert by["A@15m"]["beats_random"] is False
    a = client.get("/api/account/A@15m").json()
    assert a["trades"][0]["exit_reason"] == "SL" and a["signals"]["ENTERED"] == 1
    assert client.get("/api/account/nope").status_code == 404
    st = client.get("/api/status").json()
    assert st["heartbeat"][0] == 123
    assert client.get("/api/signals?tf=15m").json()[0]["strategy"] == "A"
    assert client.get("/api/candles?symbol=BTCUSDT&interval=15m").status_code == 200
    assert client.get("/api/candles?symbol=EVIL&interval=15m").status_code == 400
    assert "text/html" in client.get("/").headers["content-type"]


def test_login_rate_limit(client):
    for _ in range(10):
        client.post("/api/login", json={"password": "no"})
    assert client.post("/api/login", json={"password": "correct horse battery"}).status_code == 429


def test_loss_cards_and_profile(client):
    client.post("/api/login", json={"password": "correct horse battery"})
    assert client.get("/api/cards").json() == []                       # last 30 days: nothing (1970 data)
    cards = client.get("/api/cards", params={"days": 0}).json()
    assert len(cards) == 1
    c = cards[0]
    assert c["account_id"] == "A@15m" and c["reason_ko"] == "손절" and c["side_ko"] == "롱"
    assert c["if_stop"] == {} and isinstance(c["tags"], list)
    assert client.get("/api/cards", params={"days": 0, "strategy": "B"}).json() == []
    st = client.get("/api/cards/stats", params={"days": 0}).json()
    assert st["trades"] == 1 and st["losses"] == 1 and len(st["tags"]) >= 5
    p = client.get("/api/profile/N17_KC_RSI").json()
    assert p["name_ko"] == "켈트너·RSI" and len(p["rows"]) == 5
    assert client.get("/api/profile/NOPE").status_code == 404


def test_strategy_list(client):
    client.post("/api/login", json={"password": "correct horse battery"})
    lst = client.get("/api/strategies").json()
    assert len(lst) == 36 and {"strategy", "name_ko", "style", "hold", "rare"} <= set(lst[0])
    assert next(x for x in lst if x["strategy"] == "N17_KC_RSI")["style"] == "되돌림 노리기"


# ---------------------------------------------------------------------------- extra accounts on the dashboard
def _extras_db(path, n_accounts=4, losses=(3, 2)):
    """V45_AMB@15m (strategy) and its copy V45_AMB@15m~c1 with losing trades, plus filler accounts."""
    import json as _json
    import time as _time
    store = Store3(path)
    now = int(_time.time() * 1000)
    store.add_account("V45_AMB@15m", "V45_AMB", "15m", "strategy", now - 3_600_000, "paper-v3")
    store.add_account("V45_AMB@15m~c1", "V45_AMB", "15m", "copy", now - 3_600_000, "paper-v3", "V45_AMB@15m",
                      {"v": 1, "kind": "copy", "label_ko": "복제 c1", "rule": {"template": "stop_atr", "k": 2.5}})
    for k in range(n_accounts):
        store.add_account(f"F{k}@30m", f"F{k}", "30m", "strategy", now - 3_600_000, "paper-v3")
    for aid, n in zip(("V45_AMB@15m", "V45_AMB@15m~c1"), losses):
        for i in range(n):
            t = {"strategy_id": "V45_AMB", "timeframe": "15m", "symbol": "BTCUSDT", "side": 1, "qty": 1.0,
                 "leverage": 40, "entry_price": 100.0, "exit_price": 99.0, "entry_time": now - 1_800_000 - i,
                 "exit_time": now - 60_000 - i, "exit_reason": "SL", "roe": -0.4, "pnl": -5.0, "fees": 0.1,
                 "funding": 0.0, "equity_after": 4995.0, "signal_ts": now - 1_900_000 - i, "stop_initial": 99.0,
                 "best_roe": 0.0, "meta": {}}
            store.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, "
                               "pnl, roe, equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (aid, "BTCUSDT", t["entry_time"], t["exit_time"], "SL", 40, -5.0, -0.4, 4995.0,
                                _json.dumps(t)))
    store.commit()
    return store


def test_board_reads_the_trades_table_once(tmp_path):
    """The per-account stats come from one GROUP BY over trades, not one per account (the stream calls board()
    every 3 s per open tab)."""
    from paperbot.dash.app import Data
    db = str(tmp_path / "x.db")
    _extras_db(db, n_accounts=40).close()
    data = Data(db)
    seen = []
    real = data.conn

    def conn():
        c = real()
        c.set_trace_callback(seen.append)
        return c
    data.conn = conn
    b = data.board()
    assert len(b["accounts"]) == 42
    assert sum(1 for q in seen if "FROM trades GROUP BY account_id" in q) == 1
    rows = {r["account_id"]: r for r in b["accounts"]}
    assert rows["V45_AMB@15m"]["trades"] == 3 and rows["V45_AMB@15m~c1"]["trades"] == 2


def test_strategy_cards_and_stats_leave_out_its_copy_accounts(tmp_path):
    """The strategy tab's loss cards and 30-day tag shares are the strategy's own accounts: a copy carries the
    parent's strategy name but follows another rule (its cards are shown with the copy)."""
    from paperbot.dash.app import Data
    db = str(tmp_path / "c.db")
    _extras_db(db).close()
    data = Data(db)
    cards = data.cards("V45_AMB", None, 30, 40)
    assert len(cards) == 3 and {c["account_id"] for c in cards} == {"V45_AMB@15m"}
    assert data.card_stats("V45_AMB", None, 30)["trades"] == 3
    assert {c["account_id"] for c in data.cards(None, None, 30, 40)} == {"V45_AMB@15m", "V45_AMB@15m~c1"}


def test_status_signals_are_the_originals_only(tmp_path):
    """A new-strategy account's own signal rows (strategy NL<n>, written after the originals' compute) stay out of the
    status panel's 24-hour counts and average delay."""
    import time as _time
    from paperbot.dash.app import Data
    db = str(tmp_path / "s.db")
    store = Store3(db)
    now = int(_time.time() * 1000) - 600_000
    rows = [{"bar_close": now, "timeframe": "1h", "strategy": s, "symbol": "BTCUSDT", "side": 1, "atr": 0.2,
             "ref_price": 100.0, "ref_time": now + d, "delay_ms": d, "status": "SUBMITTED"}
            for s, d in (("V4.5", 2_000), ("NL1", 20_000), ("NL12", 30_000))]
    store.log_signals(rows)
    store.commit()
    store.close()
    sig = Data(db).status()["signals_24h"]
    assert sig == [{"timeframe": "1h", "status": "SUBMITTED", "n": 1, "avg_delay": 2000.0}]


def test_timeframe_summary_counts_an_extra_once_and_never_against_the_coin_flips(tmp_path):
    """An extra account's open position is counted in the '추가 계좌' line only (not again in its timeframe's
    line), and the board does not compare a late-started extra with coin-flip accounts running since day 0."""
    import json as _json
    import os
    import re
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static",
                        "app.js")
    src = open(path, encoding="utf-8").read()
    parts = ["const state = {board: null, group: 'main'}; let INITIAL = 5000;",
             "const esc = (s) => String(s ?? ''); const name = (a) => a.label_ko || a.account_id; const stratKo = (s) => s;"]
    for n in ("TF_KO", "TRADE_TFS", "EXTRA_KINDS", "fmt", "cls", "KIND_GROUP", "groupOf", "GROUP_ROW_KO", "REF_NOTE"):
        parts.append(re.search(r"^const %s = .*?;$" % n, src, re.M).group(0))
    for n in ("median", "inView", "tfSummary"):
        parts.append(re.search(r"^function %s\(.*?^}$" % n, src, re.S | re.M).group(0))
    body = """
const pos = {symbol: "BTCUSDT", side: 1};
state.board = {accounts: [
  {account_id: "V45_AMB@15m", strategy: "V45_AMB", timeframe: "15m", kind: "strategy", wallet: 5000, position: null},
  {account_id: "RANDOM_1@15m", strategy: "RANDOM_1", timeframe: "15m", kind: "random", wallet: 5100, position: null},
  {account_id: "V45_AMB@15m~c1", strategy: "V45_AMB", timeframe: "15m", kind: "copy", label_ko: "c1", wallet: 5200,
   position: pos, beats_random: true}]};
const rows = tfSummary().split("<tr>").slice(2).map((r) => r.split("</td>").map((c) => c.replace(/<[^>]+>/g, "").trim()));
console.log(JSON.stringify(rows));"""
    r = subprocess.run([node, "-e", "\n".join(parts) + "\n" + body], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    rows = {row[0]: row for row in _json.loads(r.stdout)}
    assert rows["기존 36 · 15분"][1:3] == ["1", "0"]    # one strategy account, no position in the 15m line
    assert rows["추가 계좌"][1:3] == ["1", "1"]         # the copy's position, counted once
    assert rows["추가 계좌"][7] == "—"
    # the board API: no coin-flip comparison for an extra
    from paperbot.dash.app import Data
    db = str(tmp_path / "b.db")
    store = _extras_db(db)
    store.put_state("accounts", 1, {"last_ts": 0, "engines": {
        "V45_AMB@15m": {"wallet": 5000.0, "bust": False}, "V45_AMB@15m~c1": {"wallet": 9000.0, "bust": False},
        "RANDOM_1@15m": {"wallet": 6000.0, "bust": False}}})
    store.add_account("RANDOM_1@15m", "RANDOM_1", "15m", "random", 0, "paper-v3")
    store.commit()
    store.close()
    got = {a["account_id"]: a for a in Data(db).board()["accounts"]}
    assert got["V45_AMB@15m~c1"]["beats_random"] is None and got["V45_AMB@15m"]["beats_random"] is False


def test_strategy_list_best_wallet_leaves_out_copy_accounts():
    """The strategy list shows the best of the strategy's own 5 accounts; a copy account (listed on its own) must
    not lift it."""
    import json as _json
    import os
    import re
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static",
                        "strat.js")
    src = open(path, encoding="utf-8").read()
    fn = re.search(r"^function bestWallet\(.*?^}$", src, re.S | re.M).group(0)
    body = """
const state = {board: {accounts: [
  {account_id: "V45_AMB@15m", strategy: "V45_AMB", kind: "strategy", wallet: 5100},
  {account_id: "V45_AMB@1h", strategy: "V45_AMB", kind: "strategy", wallet: 4900},
  {account_id: "V45_AMB@15m~c1", strategy: "V45_AMB", kind: "copy", wallet: 9000}]}};
const INITIAL = 5000;
console.log(JSON.stringify(bestWallet("V45_AMB")));"""
    r = subprocess.run([node, "-e", fn + "\n" + body], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert _json.loads(r.stdout) == 5100


def test_ticker_endpoint_is_the_websocket_fallback(tmp_path):
    """Where the browser cannot reach Binance's WebSocket, the page polls /api/ticker (served by the server)."""
    db = str(tmp_path / "p.db")
    _store(db).close()
    app = create_app(db, hash_password("correct horse battery"), SECRET, ticker=lambda: {"BTCUSDT": {"c": 1.5, "p": 2.0}})
    c = TestClient(app)
    assert c.get("/api/ticker").status_code == 401
    assert c.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    assert c.get("/api/ticker").json() == {"BTCUSDT": {"c": 1.5, "p": 2.0}}
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static",
                           "app.js"), encoding="utf-8").read()
    assert 'api("/api/ticker")' in js and "function closeIn(tf)" in js and "if (mwsOk) return;" in js


def test_summary_and_csv_exports(client):
    assert client.get("/api/summary").status_code == 401
    assert client.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    s = client.get("/api/summary").json()
    assert s["period_days"] == 30 and "today" in s and set(s["today"]) >= {"trades", "pnl", "wins", "liquidations"}
    if s["start"] is not None:
        assert s["day"] >= 1 and s["next_checkpoint"]["ts"] > s["now"] and "observe_until" in s
    b = client.get("/api/export/board.csv")
    assert b.status_code == 200 and b.headers["content-type"].startswith("text/csv")
    assert b.text.startswith("﻿계좌,종류,매매법") and "attachment" in b.headers["content-disposition"]
    t = client.get("/api/export/trades.csv")
    assert t.status_code == 200 and t.text.startswith("﻿계좌,종류,코인")
    one = client.get("/api/export/trades.csv", params={"account": "nope@1h"})
    assert one.text.count("\n") == 1                      # header only


def test_chart_position_box_and_strategy_shortcuts(client):
    """The trade chart draws this coin's positions as lines with live % and $; tables link to strategy and chart."""
    assert client.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    for a in client.get("/api/board").json()["accounts"]:
        assert {"account_id", "kind", "strategy", "timeframe"} <= set(a)     # what the buttons carry
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")
    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(static, "app.js"), encoding="utf-8").read()
    sj = open(os.path.join(static, "strat.js"), encoding="utf-8").read()
    assert 'id="pl-toggle"' in html and "function renderPosLines()" in js and "renderPosLines();" in js
    assert "state.entryLine.applyOptions({title: entryTitle(" in js          # live % on the entry line
    assert "data-strat=" in js and "data-chart=" in js and "function openStrategy(name, tf, sym)" in sj


def test_page_scripts_do_not_redeclare_each_others_globals():
    """The page's scripts share one global scope: a second top-level function with the same name silently replaces
    the first (rooms.js once replaced the trade screen's renderSide), a second const/let stops the whole file."""
    import re
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")
    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    seen: dict = {}
    for src in re.findall(r'<script src="/static/([a-z0-9_]+\.js)"', html):
        js = open(os.path.join(static, src), encoding="utf-8").read()
        for name in re.findall(r"^(?:const|let|var|function|async function|class)\s+([A-Za-z_$][\w$]*)", js, re.M):
            seen.setdefault(name, []).append(src)
    assert {k: v for k, v in seen.items() if len(v) > 1} == {}


def test_levels_depth_and_ghcoin_board_endpoints(tmp_path):
    import json
    from paperbot import sweepsig
    db = str(tmp_path / "p.db")
    _store(db).close()
    L = sweepsig.lib()
    df = L.synth_ohlcv(4100, "5m", seed=3, start="2026-04-01")[["ts", "open", "high", "low", "close", "volume"]]
    app = create_app(db, hash_password("correct horse battery"), SECRET, frames=lambda s, tf, n: df.tail(n).reset_index(drop=True),
                     depth=lambda s: {"bids": [[1.0, 2.0]], "asks": [[1.1, 3.0]], "T": 1})
    c = TestClient(app)
    assert c.get("/api/levels").status_code == 401
    assert c.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    r = c.get("/api/levels", params={"symbol": "BTCUSDT", "tf": "15m"}).json()
    assert r["levels"] and {x["side"] for x in r["levels"]} <= {"support", "resistance"}
    assert all((x["price"] > r["close"]) == (x["side"] == "resistance") for x in r["levels"]) and all(x["ko"] for x in r["levels"])
    assert c.get("/api/levels", params={"symbol": "BTCUSDT", "tf": "1d"}).json()["levels"] == []
    assert c.get("/api/levels", params={"symbol": "BTCUSDT", "tf": "5m"}).json()["levels"] == []   # a chart interval only
    assert c.get("/api/levels", params={"symbol": "NOPE"}).status_code == 400
    assert c.get("/api/depth", params={"symbol": "ETHUSDT"}).json()["asks"] == [[1.1, 3.0]]
    assert c.get("/api/ghcoin/board").json() == {"coins": {}, "alive": False}
    os.makedirs(tmp_path / "ghcoin")
    (tmp_path / "ghcoin" / "board.json").write_text(json.dumps({"ts": 1, "coins": {"BTCUSDT": {"state": "long", "side": 1}},
                                                                 "errors": {"BCHUSDT": "HTTP 418"}}))
    g = c.get("/api/ghcoin/board").json()
    assert g["coins"]["BTCUSDT"]["side"] == 1 and g["alive"] is False
    assert g["errors"] == {"BCHUSDT": "HTTP 418"}            # the panel says '가격 못 받음' for that coin


def test_positions_view_is_wired():
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")
    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(static, "pos.js"), encoding="utf-8").read()
    assert 'data-v="pos"' in html and 'id="v-pos"' in html and '/static/pos.js' in html
    assert "function posCard(" in js and "@depth20@500ms" in js and "/api/depth?symbol=" in js
    assert "order" not in re_buttons(js)                                   # no order buttons on a paper screen


def re_buttons(js: str) -> str:
    import re
    return " ".join(re.findall(r"<button[^>]*>([^<]*)</button>", js)).lower()


def test_market_liquidations_and_next_events(tmp_path):
    import sqlite3
    import time as _t
    from paperbot import liqstream
    db = str(tmp_path / "p.db")
    _store(db).close()
    c = TestClient(create_app(db, hash_password("correct horse battery"), SECRET))
    assert c.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    assert c.get("/api/liq", params={"symbol": "BTCUSDT"}).json()["recorder"] is False      # no liq.db yet
    now = int(_t.time() * 1000)
    q = sqlite3.connect(str(tmp_path / "liq.db"))
    q.executescript(liqstream.SCHEMA)
    for ts, side, px, qty in ((now - 60_000, "SELL", 100.0, 2.0), (now - 30_000, "BUY", 101.0, 1.0),
                              (now - 7_200_000, "SELL", 90.0, 5.0)):
        q.execute("INSERT INTO liq VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (ts, ts, "BTCUSDT", side, "LIMIT", "IOC", qty, px, px, "FILLED", qty, qty, ts))
    q.commit()
    q.close()
    r = c.get("/api/liq", params={"symbol": "BTCUSDT", "minutes": 60}).json()
    assert r["recorder"] and r["n"] == 2 and r["long_usd"] == 200.0 and r["short_usd"] == 101.0
    assert [x["liquidated"] for x in r["rows"]] == ["short", "long", "long"]                 # newest first
    assert c.get("/api/liq", params={"symbol": "NOPE"}).status_code == 400
    assert isinstance(c.get("/api/summary").json()["events"], list)


def test_trade_screen_lower_panels_are_wired():
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")
    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(static, "panels.js"), encoding="utf-8").read()
    assert 'id="watch2-body"' in html and 'id="side2-body"' in html and "/static/panels.js" in html
    assert "/api/liq?symbol=" in js and "/api/ghcoin/board" in js and "bookHtml(state.sym" in js


def test_board_carries_wins_losses_and_gross_for_the_live_record(client):
    assert client.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    accts = client.get("/api/board").json()["accounts"]
    assert accts
    for a in accts:
        assert {"wins", "losses", "gross_win", "gross_loss"} <= set(a)
        assert a["wins"] + a["losses"] <= a["trades"] and a["gross_win"] >= 0 >= a["gross_loss"]
        assert abs(a["gross_win"] + a["gross_loss"] - a["pnl"]) < 1e-6
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")
    sj = open(os.path.join(static, "strat.js"), encoding="utf-8").read()
    assert "function liveRec(" in sj and "renderLive();" in sj and 'id="s-live"' in open(os.path.join(static, "index.html"), encoding="utf-8").read()


def test_price_alerts_api_sets_the_direction_from_the_price_and_shows_the_senders_state(tmp_path):
    import json
    db = str(tmp_path / "p.db")
    _store(db).close()
    inbox = str(tmp_path / "inbox.db")
    app = create_app(db, hash_password("correct horse battery"), SECRET, inbox_db=inbox,
                     ticker=lambda: {"BTCUSDT": {"c": 65_000.0}})
    c = TestClient(app)
    assert c.get("/api/price-alerts").status_code == 401
    assert c.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    h = {"origin": "http://testserver"}
    r = c.post("/api/price-alerts", json={"symbol": "BTCUSDT", "price": 60_000, "note": "지지"}, headers=h).json()
    assert r["direction"] == "below"
    assert c.post("/api/price-alerts", json={"symbol": "BTCUSDT", "price": "70,000"}, headers=h).status_code == 400
    assert c.post("/api/price-alerts", json={"symbol": "BTCUSDT", "price": 70_000}, headers=h).json()["direction"] == "above"
    assert c.post("/api/price-alerts", json={"symbol": "NOPE", "price": 1}, headers=h).status_code == 400
    assert c.post("/api/price-alerts", json={"symbol": "BTCUSDT", "price": -1}, headers=h).status_code == 400
    got = c.get("/api/price-alerts").json()
    assert [a["direction"] for a in got["alerts"]] == ["below", "above"] and all(a["armed"] for a in got["alerts"])
    assert got["sender_alive"] is False
    # the sender fired the first one: the page shows it, and it can be armed again
    import time as _t
    first = got["alerts"][0]["id"]
    (tmp_path / "price_alerts.json").write_text(json.dumps({"fired": {str(first): int(_t.time() * 1000)},
                                                             "hb": int(_t.time() * 1000)}))
    got = c.get("/api/price-alerts").json()
    assert got["sender_alive"] is True and got["alerts"][0]["armed"] is False and got["alerts"][0]["fired_ts"]
    _t.sleep(0.01)
    assert c.post(f"/api/price-alerts/{first}/rearm", headers=h).json() == {"ok": True}
    assert c.get("/api/price-alerts").json()["alerts"][0]["armed"] is True
    assert c.post(f"/api/price-alerts/{first}/delete", headers=h).json() == {"ok": True}
    assert len(c.get("/api/price-alerts").json()["alerts"]) == 1
    assert c.post(f"/api/price-alerts/{first}/delete", headers=h).status_code == 404
    assert c.post("/api/price-alerts/1/explode", headers=h).status_code == 404
    assert c.post("/api/price-alerts", json={"symbol": "BTCUSDT", "price": 1},
                  headers={"origin": "http://evil.example"}).status_code == 403


def test_market_endpoint_each_source_on_its_own(tmp_path):
    from paperbot.dash import app as A
    db = str(tmp_path / "p.db")
    _store(db).close()
    A._MARKET_CACHE.clear()
    fng = {"data": [{"value": str(20 + i), "value_classification": "Fear", "timestamp": str(1_790_000_000 - i * 86400)}
                    for i in range(8)]}
    yahoo = {"chart": {"result": [{"meta": {"regularMarketPrice": 101.0, "chartPreviousClose": 90.0, "gmtoffset": 0,
                                            "regularMarketTime": 1_790_100_000},
                                   "timestamp": [1_790_000_000, 1_790_003_600, 1_790_086_400],
                                   "indicators": {"quote": [{"close": [99.0, 100.0, 101.0]}]}}]}}

    def get(url):
        if "alternative.me" in url:
            return fng
        if "coingecko" in url:
            raise OSError("down")
        return yahoo
    m = A.fetch_market(get)
    assert m["fng"]["now"]["value"] == 20 and m["fng"]["now"]["label_ko"] == "공포" and m["fng"]["week"]["value"] == 27
    assert m["global"] == {"error": "OSError"}
    ix = m["indexes"][0]
    assert ix["name"] == "나스닥" and ix["price"] == 101.0 and ix["prev"] == 100.0 and abs(ix["chg"] - 0.01) < 1e-12
    A._MARKET_CACHE.clear()
    app = create_app(db, hash_password("correct horse battery"), SECRET, market=lambda: {"fng": {}, "global": {}, "indexes": []})
    c = TestClient(app)
    assert c.get("/api/market").status_code == 401
    assert c.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    r = c.get("/api/market").json()
    assert set(r) >= {"fng", "global", "indexes", "events", "events_total"}
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")
    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    assert 'data-v="market"' in html and 'id="v-market"' in html and "/static/market.js" in html


def test_events_endpoint_and_chart_markers(client, tmp_path, monkeypatch):
    """2026-10-03: the trade chart marks the registered US releases (CPI · FOMC · NFP · PCE)."""
    import time

    from paperbot import events as EV
    now = int(time.time() * 1000)
    iso = lambda ms: EV.datetime.fromtimestamp(ms / 1000, EV.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    p = tmp_path / "macro_events.csv"
    p.write_text("ts_utc,kind,source_url\n"
                 f"{iso(now - 3 * 86_400_000)},CPI,https://www.bls.gov/x\n"
                 f"{iso(now + 5 * 86_400_000)},FOMC,https://www.federalreserve.gov/x\n"
                 f"{iso(now - 90 * 86_400_000)},NFP,https://www.bls.gov/y\n", encoding="utf-8")
    monkeypatch.setattr(EV, "PATH", p)
    EV.reset()
    try:
        assert client.get("/api/events").status_code == 401
        assert client.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
        got = client.get("/api/events").json()
        assert [e["kind"] for e in got["events"]] == ["CPI", "FOMC"] and got["problems"] == []
        assert [e["kind"] for e in client.get("/api/events?days_back=120&days_ahead=0").json()["events"]] == ["NFP", "CPI"]
    finally:
        EV.reset()
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")
    js = open(os.path.join(static, "app.js"), encoding="utf-8").read()
    assert "/api/events?days_back=" in js and "macroMarks(t0)" in js
    assert 'id="ev-toggle"' in open(os.path.join(static, "index.html"), encoding="utf-8").read()


# ---------------------------------------------------------------- 2026-10-03 ops review
STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")


def _static(name):
    return open(os.path.join(STATIC, name), encoding="utf-8").read()


def _node(src: str) -> str:
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    r = subprocess.run([node, "-e", src], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_page_ids_are_unique_so_the_signals_buttons_reload_the_signals():
    """The 신호 tab's timeframe buttons had the 매매법 tab's id: a tap changed the strategy tab instead."""
    import re
    ids = re.findall(r'\bid="([^"]+)"', _static("index.html"))
    assert sorted({i for i in ids if ids.count(i) > 1}) == []
    assert 'seg("sig-tf", "tf", (v) => { state.sigTf = v; loadSignals(); });' in _static("app.js")


def test_board_and_positions_name_strategies_in_korean(client):
    import json
    import re

    from paperbot.agents.roster3 import STRATEGY_KO
    client.post("/api/login", json={"password": "correct horse battery"})
    b = client.get("/api/board").json()
    assert b["strategy_ko"] == STRATEGY_KO
    src = _static("app.js")
    parts = ["const state = {board: null};", "const EXTRA_KINDS = ['copy', 'newlab'];", "const extraLabel = () => null;"]
    for n in ("TF_KO", "stratKo", "name"):
        parts.append(re.search(r"^const %s = .*?;$" % n, src, re.S | re.M).group(0))
    out = _node("\n".join(parts) + """
state.board = {strategy_ko: %s};
console.log(JSON.stringify([name({strategy: "S2_ST_ROC", timeframe: "15m", kind: "strategy"}),
  name({strategy: "RANDOM_1", timeframe: "1h", kind: "random"}), name({strategy: "X", timeframe: "5m", label_ko: "복제 c1"}),
  stratKo("NOT_KNOWN")]));""" % json.dumps(STRATEGY_KO))
    assert json.loads(out) == [f"{STRATEGY_KO['S2_ST_ROC']} · 15분", "동전 봇 1 · 1시간", "복제 c1", "NOT_KNOWN"]
    assert 'title="${esc(a.account_id)}">${esc(name(a))}' in src            # the code stays in a tooltip
    for f in ("summary.js", "checkpoint.js", "breakdown.js"):
        assert "idName(" in _static(f), f


def test_checkpoint_card_shows_progress_before_the_first_verdict():
    """Paper v4: the judged accounts of each verdict family (the 36 and DeepSeek on 15m / 30m / 1h, the reel on 5m;
    4h, the coin flips and a leftover 5m account of the 36 are not judged), counts only."""
    import json
    out = _node("""
const els = {}; const $ = (id) => (els[id] = els[id] || {textContent: "", innerHTML: ""});
const api = async () => ({ready: false});
const document = {querySelectorAll: () => []};
const setInterval = () => 0;
const TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"};
const JUDGED_BY_GROUP = {core: ["15m", "30m", "1h"], ds200: ["15m", "30m", "1h"], reel: ["5m"]};
const esc = (s) => String(s); const fmt = (x) => String(x); const idName = (id) => id;
const acct = (tf, trades, kind) => ({account_id: "S@" + tf, timeframe: tf, trades, kind: kind || "strategy"});
const state = {board: {accounts: [acct("15m", 31), acct("15m", 29), acct("30m", 30), acct("1h", 0), acct("4h", 80),
  acct("15m", 90, "random"), acct("5m", 50), acct("15m", 40, "ds200"), acct("4h", 50, "ds200"), acct("5m", 35, "reel"),
  acct("5m", 99, "random")]}};
""" + _static("checkpoint.js") + """
setTimeout(() => console.log(JSON.stringify(els["ckpt-body"].innerHTML.replace(/\\s+/g, " "))), 20);""")
    html = json.loads(out)
    assert "진행 상황, 판정 아님:" in html
    assert "판정 대상 6개" in html and "30건 이상인 계좌 <b>4개</b>" in html
    assert "기존 36 <b>2/4</b> (15분 1 · 30분 1 · 1시간 0)" in html
    assert "딥시크 <b>1/1</b> (15분 1 · 30분 0 · 1시간 0)" in html and "5분봉 단타 <b>1/1</b> (5분 1)" in html
    assert "합격" in html and "보류" in html and "$" not in html          # says how the verdict is made, no preview


def test_trade_reading_digests_are_reused_for_ten_minutes(client, monkeypatch):
    import time as _time

    import paperbot.dash.app as A
    clock = [_time.time()]
    monkeypatch.setattr(A.time, "time", lambda: clock[0])
    client.post("/api/login", json={"password": "correct horse battery"})
    first = client.get("/api/digest/tf").json()["computed_at"]
    clock[0] += 180                                  # the digest tab polls every 2 minutes
    assert client.get("/api/digest/tf").json()["computed_at"] == first
    clock[0] += A.TRADES_TTL_S
    stale = client.get("/api/digest/tf").json()          # expired: answered at once, recomputed in the background
    assert stale["computed_at"] == first and stale["stale"] is True
    for _ in range(200):
        got = client.get("/api/digest/tf").json()
        if got["computed_at"] > first:
            break
        _time.sleep(0.01)
    assert got["computed_at"] > first and "stale" not in got
    # the 순위표's breakdown card (every closed trade) refreshes only while it is on screen
    assert ('setInterval(() => { if (state.view === "board" && document.visibilityState === "visible") load(); }, 600000);'
            in _static("breakdown.js"))


def test_dashboard_timeframes_and_run_shape_come_from_the_accounts_table(client):
    """Paper v4: the run shape (/api/board 'run_shape') is counted from the accounts table (groups.shape_from_db), never
    typed in; the 36's timeframes stay 15m-4h (no 5m filter for them), 5m is traded by the reel and its coin flips only,
    and the page's defaults before /api/board are the v4 rule's (config.V4_*)."""
    import json
    import re

    import paperbot.dash.app as A
    from paperbot.config import (V3_JUDGED_TFS, V3_TRADE_TFS, V4_ACCOUNTS, V4_GROUP_ACCOUNTS, V4_GROUP_JUDGED, V4_GROUPS,
                                 V4_JUDGED_ACCOUNTS)
    assert A.CORE_TFS == tuple(V3_TRADE_TFS) and "5m" not in A.CORE_TFS and A.LEVEL_TFS == A.CORE_TFS
    assert A.TRADE_TFS == ("5m",) + tuple(V3_TRADE_TFS) and "5m" in A.CANDLE_INTERVALS
    client.post("/api/login", json={"password": "correct horse battery"})
    shape = client.get("/api/board").json()["run_shape"]            # the fixture: A@15m (the 36) + RANDOM_1@15m
    assert shape["source"] == "accounts_table" and shape["accounts"] == 2 and shape["strategy_accounts"] == 1
    assert shape["trade_tfs"] == ["15m"] and shape["core_tfs"] == ["15m"] and shape["judged_tfs"] == list(V3_JUDGED_TFS)
    assert shape["q1_family"] == 1 == shape["judged"] and set(shape["groups"]) == {"core", "flip"}
    assert client.get("/api/strategy/V45_AMB", params={"tf": "5m"}).status_code == 400
    # app.js: its defaults match config's v4 rule before /api/board arrives, and the board refills them in place
    src = _static("app.js")
    parts = [re.search(r"^const %s = .*?;$" % n, src, re.M).group(0)
             for n in ("TRADE_TFS", "CORE_TFS", "JUDGED_TFS", "RUN", "JUDGED_BY_GROUP", "RUN_GROUPS")]
    parts.append(re.search(r"^function applyRunShape\(.*?^}$", src, re.S | re.M).group(0))
    out = json.loads(_node("\n".join(parts) + """
const before = [TRADE_TFS.slice(), CORE_TFS.slice(), JUDGED_TFS.slice(), Object.assign({}, RUN), JSON.parse(JSON.stringify(JUDGED_BY_GROUP))];
const ref = [TRADE_TFS, CORE_TFS];
applyRunShape({trade_tfs: ["5m", "1h"], core_tfs: ["1h"], judged_tfs: ["1h"], accounts: 7, judged_by_group: {reel: ["5m"]},
  groups: {reel: {accounts: 1}}});
console.log(JSON.stringify([before, ref[0] === TRADE_TFS && ref[1] === CORE_TFS, TRADE_TFS, CORE_TFS, JUDGED_TFS, RUN.accounts, RUN_GROUPS]));"""))
    assert out[0] == [["5m"] + list(V3_TRADE_TFS), list(V3_TRADE_TFS), list(V3_JUDGED_TFS),
                      {"accounts": V4_ACCOUNTS, "strategy_accounts": V4_GROUP_ACCOUNTS["core"], "q1_family": V4_GROUP_JUDGED["core"],
                       "judged": V4_JUDGED_ACCOUNTS},
                      {g: list(V4_GROUPS[g]["judged"]) for g in ("core", "ds200", "reel")}]
    assert out[1:] == [True, ["5m", "1h"], ["1h"], ["1h"], 7, {"reel": {"accounts": 1}}]
    # the account filters: the board's timeframe buttons are built per group at run time (5m only where a group
    # trades it), the signals tab offers 5m (the reel's signals), the strategy tab (the 36) never does
    html = _static("index.html")
    def tfs_of(seg):
        block = re.search(r'id="%s">(.*?)</div>' % seg, html, re.S).group(1)
        return [t for t in re.findall(r'data-tf="([^"]*)"', block) if t and t != "1d"]
    assert tfs_of("s-tf") == list(V3_TRADE_TFS) and tfs_of("f-tf") == list(V3_TRADE_TFS)
    assert tfs_of("sig-tf") == ["5m"] + list(V3_TRADE_TFS)
    assert 'id="f-group"' in html and 'id="gcards"' in html
    kinds = re.findall(r'data-k="([^"]*)"', re.search(r'id="f-kind"[^>]*>(.*?)</div>', html, re.S).group(1))
    assert kinds == ["", "copy", "newlab"]                     # the group switch replaced strategy / coin-flip kinds
    assert 'data-tf="5m"' in re.search(r'id="tf-seg">(.*?)</div>', html, re.S).group(1)
    assert "buildTfSeg(TRADE_TFS.filter((tf) => view.some((a) => a.timeframe === tf)))" in src
    # no static file hard-codes an old run's counts or the old banner
    for f in os.listdir(STATIC):
        if f.endswith((".js", ".html")):
            s = _static(f)
            assert not re.search(r"(?<![0-9])(195|180|156)개", s), f
            assert "5분봉 제외" not in s, f
    assert "state.board.run_shape" in src and 'tf: "15m"' in src            # the trade chart opens on 15m
    for f in ("strat.js", "digest.js"):                                     # the 36's tabs: their own timeframes only
        assert "CORE_TFS" in _static(f) and "TRADE_TFS" not in _static(f), f


def test_the_timeframe_summary_has_a_line_per_group_and_timeframe_with_accounts():
    """Paper v4: one line per (group, timeframe) that has accounts in the chosen view, never an empty line (a 5m line
    only where a group trades 5m: the reel), and an unknown account kind is left out (fail safe), without throwing."""
    import json
    import re
    src = _static("app.js")
    parts = ["const state = {board: null, group: 'main'}; let INITIAL = 5000;",
             "const esc = (s) => String(s ?? ''); const name = (a) => a.label_ko || a.account_id; const stratKo = (s) => s;"]
    for n in ("TF_KO", "TRADE_TFS", "EXTRA_KINDS", "fmt", "cls", "KIND_GROUP", "groupOf", "GROUP_ROW_KO", "REF_NOTE"):
        parts.append(re.search(r"^const %s = .*?;$" % n, src, re.M).group(0))
    for n in ("median", "inView", "tfSummary"):
        parts.append(re.search(r"^function %s\(.*?^}$" % n, src, re.S | re.M).group(0))
    out = json.loads(_node("\n".join(parts) + """
state.board = {accounts: [
  {account_id: "REEL_H1@5m", strategy: "REEL_H1", timeframe: "5m", kind: "reel", group: "reel", wallet: 4000, position: null},
  {account_id: "A@15m", strategy: "A", timeframe: "15m", kind: "strategy", wallet: 5000, position: null},
  {account_id: "F9_FVG@15m", strategy: "F9_FVG", timeframe: "15m", kind: "ds200", group: "ds200", wallet: 5000, position: null},
  {account_id: "X@15m", strategy: "X", timeframe: "15m", kind: "mystery", wallet: 5000, position: null}]};
const firsts = () => tfSummary().split("<tr>").slice(2).map((r) => r.split("</td>")[0].replace(/<[^>]+>/g, "").trim());
const main = firsts(); state.group = "ds200"; const ds = firsts();
console.log(JSON.stringify([main, ds, tfSummary().includes("참고")]));"""))
    assert out == [["기존 36 · 15분", "5분봉 단타 · 5분"], ["딥시크 · 15분"], True]


def test_an_account_holding_a_position_opens(tmp_path):
    """Paper v3's ladder exits leave an open position's tp_price NaN in the saved engine state (engine.py); the
    account view must still answer (JSON has no NaN: it answered 500 for every account holding a position)."""
    import math
    db = str(tmp_path / "p.db")
    store = Store3(db)
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store, equity_every_ms=MIN)
    book.open_accounts([{"strategy": "A", "timeframe": "15m", "kind": "strategy"}], 0)
    flat = lambda i: {s: Bar(s, i * MIN, i * MIN + MIN - 1, 100.0, 100.05, 99.95, 100.0) for s in V3_SYMBOLS}  # noqa: E731
    book.step(0, flat(0))
    book.submit("A@15m", Signal(ts=MIN - 1, symbol="BTCUSDT", timeframe="15m", strategy_id="A", side=1,
                                stop_price=0.0, tier="best", atr=0.2, meta={"stop_dist": 0.4}))
    book.step(MIN, flat(1))
    book.save(MIN)
    assert math.isnan(book.engines["A@15m"].position.tp_price)
    store.close()
    c = TestClient(create_app(db, hash_password("correct horse battery"), SECRET, candles=lambda s, i, n: []))
    assert c.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    r = c.get("/api/account/A@15m")
    assert r.status_code == 200
    pos = r.json()["state"]["position"]
    assert pos["symbol"] == "BTCUSDT" and pos["tp_price"] is None and r.json()["position_why"]["leverage"]


def test_the_dashboard_imports_scipy_before_serving(monkeypatch):
    """Two first imports of scipy from two request threads at once left it half initialised (500 until a restart):
    create_app imports the lazily used packages once, up front."""
    from paperbot.dash import app as A
    seen = []
    monkeypatch.setattr(A, "warm_imports", lambda: seen.append(1))
    create_app(":memory:", None, SECRET)
    assert seen == [1] and "scipy" in A.WARM_IMPORTS and "scipy.signal" in A.WARM_IMPORTS
    assert A.json_finite({"x": [float("nan"), float("inf"), 1.5], "y": (2,)}) == {"x": [None, None, 1.5], "y": [2]}


def test_phone_layout_fixes_stay():
    """Phone width (390 px): position cards no wider than the screen, a trade's 'why' line kept in view, and the
    account's open position keeps its 'why this leverage' line through the 1 s refresh."""
    st = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")
    css = open(os.path.join(st, "style.css"), encoding="utf-8").read()
    js = open(os.path.join(st, "app.js"), encoding="utf-8").read()
    assert ".pcards { grid-template-columns: minmax(0, 1fr); }" in css and "tr.why-row td .why { position: sticky" in css
    assert ("renderAcctPos(state.account.state && state.account.state.position, state.account.position_why, "
            "state.account.account.exits)") in js


def test_account_equity_is_downsampled_keeping_first_last_and_extremes(tmp_path):
    """/api/account/<id> (review 2026-10-04, M-6): 30 days of 5-minute equity (8,640 points, ~400 KB) reach the browser
    as at most EQUITY_MAX_POINTS points in time order, with the first and last points and every bucket's low and high
    (the deepest trough and the peak stay on the chart); a short series is sent whole."""
    import json
    import math
    import sqlite3

    from paperbot.dash.app import EQUITY_MAX_POINTS, downsample
    db = str(tmp_path / "p.db")
    _store(db).close()
    c = sqlite3.connect(db)
    cols = [r[1] for r in c.execute("PRAGMA table_info(equity)")]
    t0 = 10 * 86_400_000
    n = 30 * 288
    vals = [5000 + 400 * math.sin(i / 50) + (i % 7) for i in range(n)]
    vals[4321], vals[6000] = 1234.5, 9876.5                         # a trough and a peak inside one bucket each
    rows = [{"account_id": "A@15m", "ts": t0 + i * 300_000, "equity": v, "drawdown": 0.0} for i, v in enumerate(vals)]
    c.executemany(f"INSERT INTO equity ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                  [tuple(r.get(k, 0) for k in cols) for r in rows])
    c.commit()
    c.close()
    cl = TestClient(create_app(db, hash_password("correct horse battery"), SECRET, candles=lambda s, i, k: []))
    cl.post("/api/login", json={"password": "correct horse battery"})
    a = cl.get("/api/account/A@15m").json()
    eq = a["equity"]
    assert a["equity_points"] >= n and len(eq) <= EQUITY_MAX_POINTS
    assert len(json.dumps(eq)) < 80_000
    ts = [p["t"] for p in eq]
    assert ts == sorted(set(ts))                                     # strictly increasing (the chart needs it)
    assert eq[-1] == {"t": rows[-1]["ts"], "v": rows[-1]["equity"]}
    got = {p["v"] for p in eq}
    assert 1234.5 in got and 9876.5 in got
    short = [{"t": i, "v": float(i)} for i in range(EQUITY_MAX_POINTS)]
    assert downsample(short) is short
    assert len(downsample([{"t": i, "v": float(i % 13)} for i in range(100_000)])) <= EQUITY_MAX_POINTS
