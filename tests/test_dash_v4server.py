"""Paper v4 dashboard server (P10 second pass): '/' serves the v4 page and '/v3' the old one, the login comes back to
the page that sent it (same-origin ``next`` only), strict JSON on the live stream, the board cache and GZip, the
DeepSeek / reel strategy views, research cards and loss cards, /api/v4/curves, /api/v4/server, the agents feed with
its rooms, the operations alerts and signals per group, the health card's liquidations per group, the alert history
filters, the always-'normal' leverage line and the five group specialists."""

import gzip
import json
import math
import os
import sqlite3
import sys
import time

import numpy as np
import pytest

fastapi = pytest.importorskip("fastapi")
import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import paperbot.dash.app as A  # noqa: E402
from paperbot.dash import analysis as AN  # noqa: E402
from paperbot.dash.app import Data, create_app, hash_password  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_dash import SECRET, _node, _static  # noqa: E402
from test_dash_v4groups import NOW, PW, _pos, _trade, _world  # noqa: E402


def _frame(n: int, tf_min: int, seed: int = 1, end_ms: int = NOW) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    open_ = np.r_[close[0], close[:-1]]
    hi = np.maximum(open_, close) * (1 + rng.uniform(0, 0.003, n))
    lo = np.minimum(open_, close) * (1 - rng.uniform(0, 0.003, n))
    step = tf_min * 60_000
    ts = pd.to_datetime((end_ms // step - n + np.arange(n)) * step, unit="ms", utc=True)
    return pd.DataFrame({"ts": ts, "open": open_, "high": hi, "low": lo, "close": close,
                         "volume": rng.uniform(10, 100, n)})


def _client(db, **kw):
    c = TestClient(create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [], **kw))
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    return c


# ---------------------------------------------------------------- G1: entry point, login next, names
def test_root_is_the_v4_dashboard_and_the_old_one_moves_to_v3(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db, trades=False).close()
    anon = TestClient(create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: []))
    for path, nxt in (("/", "/"), ("/v3", "/v3"), ("/v4", "/v4")):
        r = anon.get(path, follow_redirects=False)
        assert r.status_code in (302, 307) and r.headers["location"] == f"/login?next={nxt}"
    assert anon.get("/api/board").status_code == 401                       # the API still answers 401, no redirect
    c = _client(db)
    root = c.get("/").text
    assert 'src="/static/v4/core/main.js"' in root and "<title>Paper v4</title>" in root
    assert c.get("/v4").text == root
    old = c.get("/v3").text
    assert 'src="/static/app.js"' in old and "Paper v4" in old and "Paper v3" not in old
    assert c.get("/static/v4/index.html").status_code == 200


def test_the_login_redirect_keeps_only_same_origin_paths():
    assert A.login_redirect("/", "") == "/login?next=/"
    assert A.login_redirect("/v3", "tab=board") == "/login?next=/v3%3Ftab%3Dboard"
    for bad in ("//evil.example/x", "/\\evil.example", "/login", "/api/board", "/x\nSet-Cookie: a=b", "", "http://x"):
        assert A.login_redirect(bad, "") == "/login?next=/", bad
        assert not A.safe_next(bad)
    assert A.safe_next("/#/board") and A.safe_next("/static/v4/index.html")


def test_login_page_follows_next_only_to_a_same_origin_path():
    html = _static("login.html") + _static("login.js")      # #88: the script moved out of the page (CSP)
    assert "<title>Paper v4 로그인</title>" in html and "<h1>Paper v4</h1>" in html and "Paper v3" not in html
    assert "location.href = nextPath()" in html
    fn = html[html.index("function nextPath()"):html.index("document.getElementById(\"f\")")]
    cases = {"/": "/", "/%23/board": "/#/board", "/v3": "/v3", "//evil.example": "/", "/%5Cevil.example": "/",
             "https://evil.example": "/", "/login": "/", "javascript:alert(1)": "/", "": "/", "/api/board": "/"}
    out = _node("const location = {search: ''};\n" + fn.replace("location.search", "globalThis.__q") + "\n"
                + "const r = {};\n" + "".join(f"globalThis.__q = '?next={k}'; r[{json.dumps(k)}] = nextPath();\n"
                                               for k in cases) + "console.log(JSON.stringify(r));")
    assert json.loads(out) == cases
    man = json.loads(_static("manifest.json"))
    assert man["name"] == "Paper v4 대시보드" and man["short_name"] == "Paper v4" and man["start_url"] == "/"
    assert 'location.href = "/login?next=" + encodeURIComponent(location.pathname + location.hash)' in _static("app.js")


# ---------------------------------------------------------------- G12 / G17: strict stream JSON, board cache, gzip
def test_the_stream_event_is_strict_json_when_positions_and_trades_hold_nan(tmp_path):
    db = str(tmp_path / "p.db")
    store = _world(db)
    st = store.get_state("accounts")[1]
    st["engines"]["A@15m"]["position"]["stop_price"] = float("nan")         # every float of a position may be NaN
    st["engines"]["REEL_H1@5m"]["position"]["tp_price"] = float("inf")
    store.put_state("accounts", NOW + 1, st)
    store.commit()
    store.close()
    data = Data(db)
    rooms = A.Rooms(None, None, paper_db=db)
    cur = {"trade_id": 0, "alert_row": 0, "room_msg": 0, "last_board": None}
    ev = A.stream_event(data, rooms, cur)
    assert ev.startswith("data: ") and ev.endswith("\n\n")
    reject = lambda x: (_ for _ in ()).throw(ValueError(x))  # noqa: E731
    p = json.loads(ev[len("data: "):], parse_constant=reject)
    assert p["changed"]["A@15m"][3]["stop"] is None and p["changed"]["REEL_H1@5m"][3]["tp"] is None
    assert len(p["trades"]) == 5 and cur["trade_id"] == p["trades"][-1]["id"]
    again = json.loads(A.stream_event(data, rooms, cur)[len("data: "):], parse_constant=reject)
    assert again["changed"] == {} and again["trades"] == []                # NaN no longer reads as "changed"


def test_the_board_is_computed_again_only_when_the_database_changed(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db).close()
    data = Data(db)
    b1 = data.board()
    assert data.board() is b1 and A.BOARD_TTL_S == 2.0                      # nothing changed: the same result
    store = Store3(db)
    _trade(store, "A@15m", -3.0)
    store.commit()
    assert data.board() is b1                                               # within 2 s: not even the marks are read
    data.board_ttl_s = 0                                                    # (the 2 s are over)
    b2 = data.board()
    assert b2 is not b1 and {a["account_id"]: a["trades"] for a in b2["accounts"]}["A@15m"] == 2
    st = store.get_state("accounts")[1]
    st["engines"]["A@15m"]["wallet"] = 4000.0
    store.put_state("accounts", NOW + 5, st)
    store.commit()
    store.close()
    assert {a["account_id"]: a["wallet"] for a in data.board()["accounts"]}["A@15m"] == 4000.0
    assert all(math.isfinite(a["position"]["tp"]) for a in data.board()["accounts"]
               if a["position"] and a["position"]["tp"] is not None)
    # the route adds 'orphan' to copies of the rows, never to the shared board
    c = _client(db)
    assert all("orphan" in a for a in c.get("/api/board").json()["accounts"])
    assert not any("orphan" in a for a in data.board()["accounts"])


def test_big_answers_are_gzipped_and_the_live_stream_never_is(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db).close()
    c = _client(db)
    r = c.get("/api/board", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip" and r.json()["accounts"]
    assert c.get("/api/time", headers={"Accept-Encoding": "gzip"}).headers.get("content-encoding") is None   # small
    assert A.NO_GZIP_PATHS == ("/api/stream", "/api/v4/ticks")   # the board stream and the sound's market trades
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["path"])
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        await send({"type": "http.response.body", "body": b"data: x\n\n" * 500, "more_body": False})
    mw = A.GZipExceptStream(inner)
    sent = []

    async def send(m):
        sent.append(m)

    async def receive():
        return {"type": "http.request"}
    import asyncio
    scope = {"type": "http", "path": "/api/stream", "headers": [(b"accept-encoding", b"gzip")], "method": "GET"}
    asyncio.run(mw(scope, receive, send))
    assert dict(sent[0]["headers"]).get(b"content-encoding") is None and sent[1]["body"].startswith(b"data: x")
    assert gzip.decompress(gzip.compress(b"x")) == b"x"


# ---------------------------------------------------------------- G2 / G3 / G4: DeepSeek and reel views, cards
def test_deepseek_and_reel_views_load_with_their_own_windows_and_btc(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db).close()
    calls = []
    frames = {"5m": _frame(6000, 5), "1h": _frame(3200, 60, 2), "15m": _frame(6000, 15, 3)}

    def fake(symbol, tf, n):
        calls.append((symbol, tf, n))
        return frames[tf].tail(n).reset_index(drop=True)
    c = _client(db, frames=fake)
    assert A.view_bars("15m", "F9_FVG") == 5763 and A.view_bars("30m", "F9_FVG") == 2883
    assert A.view_bars("1h", "F9_FVG") == 3000 and A.view_bars("4h", "F9_FVG") == 2400
    from paperbot.config import REEL_WINDOW_5M
    assert A.view_bars("5m", "REEL_H1") == REEL_WINDOW_5M
    v = c.get("/api/strategy/F9_FVG", params={"tf": "1h", "symbol": "ETHUSDT"})
    assert v.status_code == 200 and v.json()["strategy"] == "F9_FVG" and v.json()["conditions"]["long"]
    assert calls[-1] == ("ETHUSDT", "1h", 3000)
    r = c.get("/api/strategy/REEL_H1", params={"tf": "5m", "symbol": "BTCUSDT"})
    assert r.status_code == 200 and calls[-1] == ("BTCUSDT", "5m", REEL_WINDOW_5M)
    assert c.get("/api/strategy/REEL_H1", params={"tf": "15m"}).status_code == 400
    assert c.get("/api/strategy/F9_FVG", params={"tf": "1h", "symbol": "XRPUSDT"}).status_code == 400   # no XRP
    assert c.get("/api/strategy/F15_ASIA_BRK", params={"tf": "4h"}).status_code == 400
    calls.clear()
    s = c.get("/api/strategy/F14_SMT", params={"tf": "15m", "symbol": "ETHUSDT"})
    assert s.status_code == 200 and ("BTCUSDT", "15m", 5763) in calls and ("ETHUSDT", "15m", 5763) in calls
    # the 36 keep their window and XRP
    calls.clear()
    assert c.get("/api/strategy/V45_AMB", params={"tf": "1h", "symbol": "XRPUSDT"}).status_code in (200, 404)
    # Binance unreachable: 503, never a 500
    def broken(symbol, tf, n):
        raise OSError("down")
    assert _client(db, frames=broken).get("/api/strategy/F9_FVG", params={"tf": "1h"}).status_code == 503


def test_research_cards_strategy_list_and_loss_cards_cover_deepseek_and_the_reel(tmp_path):
    from paperbot import ds_profiles
    db = str(tmp_path / "p.db")
    _world(db).close()
    c = _client(db)
    if ds_profiles.profile("F9_FVG") is not None:
        p = c.get("/api/profile/F9_FVG")
        assert p.status_code == 200 and p.json()["strategy"] == "F9_FVG" and "live_risk" in p.json()
        card = p.json()["card"]                                             # profile_card's shape (ds_profiles.card)
        assert card["strategy"] == "F9_FVG" and card["rows"] and {"tf", "trades_per_day"} <= set(card["rows"][0])
    if ds_profiles.profile("REEL_H1") is not None:
        assert c.get("/api/profile/REEL_H1").json()["strategy"] == "REEL_H1"
    assert c.get("/api/profile/NOPE").status_code == 404
    assert len(c.get("/api/strategies").json()) == 36                       # the default stays the 36
    full = c.get("/api/strategies", params={"all": 1}).json()
    assert len(full) == 36 + 44 + 1
    by = {x["strategy"]: x for x in full}
    assert by["F9_FVG"]["kind"] == "ds200" and by["F9_FVG"]["family"] == "F9" and by["F9_FVG"]["tfs"] == ["15m", "30m", "1h", "4h"]
    assert by["F15_ASIA_BRK"]["tfs"] == ["15m", "30m", "1h"] and by["REEL_H1"]["tfs"] == ["5m"]
    assert by["REEL_H1"]["name_ko"].startswith("릴스") and full[0]["kind"] == "strategy"
    cards = c.get("/api/cards", params={"strategy": "F9_FVG"}).json()
    assert [x["account_id"] for x in cards] == ["F9_FVG@15m"] and cards[0]["pnl"] == -40.0
    assert A.strategy_kind("REEL_H1") == "reel" and A.strategy_kind("V45_AMB") == "strategy"
    assert A.names_ko()["F9_FVG"].startswith("딥시크") and A.names_ko()["V45_AMB"]


# ---------------------------------------------------------------- G13: curves, server, feed, status
def test_curves_median_per_kind_and_total_carried_forward(tmp_path):
    db = str(tmp_path / "p.db")
    store = _world(db, trades=False)
    h = 3_600_000
    pts = {"A@15m": (5000, 5100, None), "RANDOM_1@15m": (5000, 4900, 4800), "F9_FVG@15m": (5000, None, 5200),
           "REEL_H1@5m": (5000, 5050, 5060), "RANDOM_1@5m": (5000, 5010, None), "A@15m~c1": (9000, 9000, 9000)}
    for aid, vals in pts.items():
        for k, v in enumerate(vals):
            if v is not None:
                store.equity(aid, NOW - 3_600_000 + k * h // 2, float(v), 0.0)
    store.commit()
    store.close()
    data = Data(db)
    now = NOW - 3_600_000 + h + 1
    v = data.curves(3_600_000, now_ms=now)
    assert v["step"] == 3_600_000 and v["keys"] == ["strategy", "ds200", "reel", "random", "random_5m"]
    assert v["t"] == sorted(v["t"]) and v["t"][-1] == now and len(v["t"]) == len(v["total"])
    last = {k: s[-1] for k, s in v["median"].items()}
    assert last["strategy"] == 5100 and last["ds200"] == 5200 and last["reel"] == 5060
    assert last["random"] == (4800 + 5010) / 2 and last["random_5m"] == 5010                # carried forward
    assert v["total"][-1] == 5100 + 4800 + 5060 + 5010           # the copy is not in it, nor DeepSeek (F9_FVG, D11)
    assert data.curves(3_600_000, now_ms=now) == v                                        # incremental = the same
    assert data.curves(1, now_ms=now)["step"] == 300_000   # the nearest allowed step (5 min since fill-home)
    c = _client(db)
    assert c.get("/api/v4/curves").json()["keys"][0] == "strategy"
    empty = str(tmp_path / "e.db")
    Store3(empty).close()
    assert Data(empty).curves()["t"] == []


def test_server_facts_signal_time_and_telegram_count(tmp_path):
    db = str(tmp_path / "p.db")
    store = _world(db, trades=False)
    rows = [{"bar_close": NOW - 600_000, "timeframe": "5m", "strategy": "REEL_H1", "symbol": "BTCUSDT", "side": 0,
             "atr": None, "ref_price": None, "ref_time": None, "delay_ms": 9_000, "status": "NO_SIGNAL", "data": {}},
            {"bar_close": NOW - 300_000, "timeframe": "5m", "strategy": "REEL_H1", "symbol": "BTCUSDT", "side": 0,
             "atr": None, "ref_price": None, "ref_time": None, "delay_ms": 12_000, "status": "NO_SIGNAL", "data": {}},
            {"bar_close": NOW - 900_000, "timeframe": "15m", "strategy": "F9_FVG", "symbol": "BTCUSDT", "side": 1,
             "atr": 1.0, "ref_price": 100.0, "ref_time": NOW, "delay_ms": 30_000, "status": "ENTERED", "data": {}}]
    store.log_signals(rows)
    store.conn.execute("CREATE TABLE tg_sends (day TEXT, kind TEXT, n INTEGER)")
    import datetime
    day = datetime.datetime.fromtimestamp(time.time(), datetime.timezone(datetime.timedelta(hours=9))).date()
    store.conn.executemany("INSERT INTO tg_sends VALUES (?,?,?)", [(day.isoformat(), "trade", 5), (day.isoformat(), "liq", 2),
                                                                 ((day - datetime.timedelta(days=3)).isoformat(), "trade", 4),
                                                                 ((day - datetime.timedelta(days=9)).isoformat(), "trade", 50)])
    store.commit()
    store.close()
    c = _client(db)
    v = c.get("/api/v4/server").json()
    assert set(v) >= {"cpu", "mem", "disk", "db", "signal_time", "telegram", "services", "limits"}
    if os.path.exists("/proc/stat"):
        assert 0 <= v["cpu"]["pct"] <= 100 and v["cpu"]["cores"] >= 1
        assert 0 < v["mem"]["used_mb"] <= v["mem"]["total_mb"]
    assert v["disk"]["total_gb"] > 0 and v["db"]["paper3_mb"] > 0 and v["db"]["agents3_mb"] is None
    st = {x["tf"]: x for x in v["signal_time"]}
    assert st["5m"]["max_delay_ms"] == 12_000 and st["5m"]["limit_ms"] == 60_000 and st["5m"]["bar_close"] == NOW - 300_000
    assert st["15m"]["limit_ms"] == 180_000 and list(st) == ["5m", "15m"]
    assert v["telegram"] == {"today": 7, "week": 11}
    s = c.get("/api/status").json()
    g = {(x["group"], x["timeframe"], x["status"]): x for x in s["signals_by_group"]}
    assert g[("reel", "5m", "NO_SIGNAL")]["n"] == 2 and g[("reel", "5m", "NO_SIGNAL")]["max_delay"] == 12_000
    assert g[("ds200", "15m", "ENTERED")]["avg_delay"] == 30_000
    assert sum(x["n"] for x in s["signals_24h"]) == 3                       # the old per-timeframe rows as before


def test_status_keeps_operations_alerts_apart_from_account_lines(tmp_path):
    db = str(tmp_path / "p.db")
    store = _world(db, trades=False)
    store.alert(NOW - 5000, "WARN", "signal workers did not answer within 120s; signals skipped at B for 15m")
    for k in range(80):
        store.alert(NOW - 4000 + k, "CRITICAL", f"[F9_FVG@15m] LIQUIDATED BTCUSDT 30x lost margin {k}.00")
    store.commit()
    store.close()
    s = _client(db).get("/api/status").json()
    assert len(s["alerts"]) == 50 and all("LIQUIDATED" in a["text"] for a in s["alerts"])   # as before
    assert [a["text"][:14] for a in s["ops_alerts"]] == ["signal workers"]
    assert A.account_line("[A@15m] BUST: wallet below") == "A@15m" and A.account_line("data gap 3 min") is None


def test_agents_feed_carries_room_round_and_speaker(tmp_path):
    p = str(tmp_path / "agents3.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, room_id TEXT, round_id INTEGER,"
              " meeting TEXT, role TEXT, speaker_name TEXT, kind TEXT, text TEXT, data TEXT, evidence TEXT)")
    for k in range(5):
        c.execute("INSERT INTO messages (ts, room_id, round_id, meeting, role, speaker_name, kind, text) "
                  "VALUES (?,?,?,?,?,?,?,?)", (NOW + k, "team:ds_structure", 7, "group_loss", "spec_ds_structure",
                                               "구조·유동성 담당", "analysis", f"m{k}"))
    c.commit()
    c.close()
    rows = A.agent_feed(p, 10)
    assert [r["text"] for r in rows] == ["m4", "m3", "m2", "m1", "m0"]
    assert rows[0]["room_id"] == "team:ds_structure" and rows[0]["round_id"] == 7 and rows[0]["speaker_name"]
    assert [r["text"] for r in A.agent_feed(p, 10, after_id=3)] == ["m4", "m3"]
    old = str(tmp_path / "old.db")                                         # the v3 pipelines' table: no room columns
    c = sqlite3.connect(old)
    c.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, ts INTEGER, meeting TEXT, role TEXT, kind TEXT, "
              "text TEXT, data TEXT)")
    c.execute("INSERT INTO messages VALUES (1, 1, 'm', 'r', 'k', 't', NULL)")
    c.commit()
    c.close()
    assert A.agent_feed(old)[0]["room_id"] is None


# ---------------------------------------------------------------- G14 / G15 / #9 / G16
def test_health_counts_liquidations_per_group_and_alert_history_filters(tmp_path):
    db = str(tmp_path / "p.db")
    store = _world(db, trades=False)
    store.put_state("heartbeat", int(time.time() * 1000), {"last_step": int(time.time() * 1000)})
    now = int(time.time() * 1000)
    for k in range(30):
        store.alert(now - 10_000 + k, "CRITICAL", f"[F9_FVG@15m] LIQUIDATED BTCUSDT 30x lost margin {k}.00")
    store.alert(now - 9_000, "CRITICAL", "[RANDOM_1@5m] LIQUIDATED ETHUSDT 30x lost margin 1.00")
    store.alert(now - 8_000, "INFO", "[A@15m] ENTER BTCUSDT")
    store.alert(now - 7_000, "WARN", "[F9_FVG@15m] BUST: wallet below the minimum")
    store.commit()
    data = Data(db)
    rooms = A.Rooms(None, None, paper_db=db)
    h = AN.health(data, rooms, None, None, None, now_ms=now, failalert_dir=str(tmp_path / "fa"))
    assert h["bot"]["liquidations_24h"] == {"ds200": 30, "flip": 1} and h["bot"]["critical_other_24h"] == 0
    assert not any("긴급" in p or "강제청산" in p for p in h["problems"])
    assert any("강제청산 딥시크 30건 · 동전 1건" in w for w in h["warnings"])
    store.alert(now - 6_000, "CRITICAL", "[REEL_H1@5m] LIQUIDATED BTCUSDT 30x lost margin 3.00")
    store.alert(now - 5_000, "CRITICAL", "paper3.db write failed")
    store.commit()
    store.close()
    h = AN.health(data, rooms, None, None, None, now_ms=now, failalert_dir=str(tmp_path / "fa"))
    assert any("강제청산 1건 (5분 단타 1건)" in p for p in h["problems"]) and any("강제청산 빼고" in p for p in h["problems"])
    assert h["level"] == "bad"
    # a bust is WARN (engine.py) and still counted: DeepSeek's a warning line, the 36's / the reel's a problem
    assert h["bot"]["busts_24h"] == {"ds200": 1} and any("파산 딥시크 1건" in w for w in h["warnings"])
    assert not any("파산" in p for p in h["problems"])
    s2 = Store3(db)
    s2.alert(now - 4_000, "WARN", "[A@15m] BUST: wallet below the minimum")
    s2.alert(now - 3_000, "CRITICAL", "[A@15m~c1] LIQUIDATED BTCUSDT 30x lost margin 2.00")   # an extra: a line only
    s2.commit()
    s2.close()
    h = AN.health(data, rooms, None, None, None, now_ms=now, failalert_dir=str(tmp_path / "fa"))
    assert any(p.startswith("지난 24시간 파산 1건 (매매법 1건)") for p in h["problems"]), h["problems"]
    assert h["bot"]["liquidations_24h"].get("extra") == 1
    assert any("강제청산 추가 계좌 1건 · 딥시크 30건 · 동전 1건" in w for w in h["warnings"]), h["warnings"]
    every = AN.alert_history(data, rooms, None, None, failalert_dir=str(tmp_path / "fa"))["bot"]
    assert any(r["level"] == "INFO" for r in every)
    warn = AN.alert_history(data, rooms, None, None, level="WARN", failalert_dir=str(tmp_path / "fa"))["bot"]
    assert [r["level"] for r in warn] == ["WARN", "WARN"]
    noinfo = AN.alert_history(data, rooms, None, None, exclude_info=True, limit=500, failalert_dir=str(tmp_path / "fa"))["bot"]
    assert noinfo and all(r["level"] != "INFO" for r in noinfo) and len(noinfo) == 36
    c = _client(db)
    assert all(r["level"] == "WARN" for r in c.get("/api/analysis/alerts", params={"level": "warn"}).json()["bot"])
    assert len(c.get("/api/analysis/alerts", params={"exclude_info": 1}).json()["bot"]) == 36


def test_levwhy_says_deepseek_and_5m_accounts_always_trade_at_normal(tmp_path):
    db = str(tmp_path / "p.db")
    store = _world(db, trades=False)
    st = store.get_state("accounts")[1]
    st["engines"]["F9_FVG@15m"]["position"] = _pos(99.0, float("nan"))
    st["engines"]["RANDOM_1@5m"]["position"] = _pos(98.0, 103.0, end=NOW + 1000)
    store.put_state("accounts", NOW + 1, st)
    store.commit()
    store.close()
    pos = Data(db).position_why()["positions"]
    for aid in ("REEL_H1@5m", "F9_FVG@15m", "RANDOM_1@5m"):
        assert pos[aid]["short_ko"] == A.FIXED_NORMAL_KO and pos[aid]["fixed"] == "normal", aid
    assert pos.get("A@15m", {}).get("fixed") is None


def test_the_account_page_trades_say_the_same_for_deepseek_and_the_reel(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db).close()
    data = Data(db)
    for aid in ("F9_FVG@15m", "REEL_H1@5m"):
        tr = data.account(aid)["trades"]
        assert tr and all(t["why"]["short_ko"] == A.FIXED_NORMAL_KO and t["why"]["fixed"] == "normal" for t in tr)
    assert all((t["why"] or {}).get("fixed") is None for t in data.account("A@15m")["trades"])


def test_the_five_group_specialists_have_names_schedules_and_office_zones(tmp_path):
    from paperbot import groups as G
    rooms = A.Rooms(None, None)
    for key, ko, _f, _i in G.V4_ROLES:
        r = rooms._role(f"spec_{key}")
        assert r["label"] == ko and r["team"] == "specialist" and r["group_role"] == key
        assert A.group_role_of_room(f"team:{key}") == key
        text = A.room_schedule_ko(f"team:{key}")
        assert text.startswith(ko) and "파산" in text and "남는 몫" in text
    assert "5분봉 동전 3개" in A.room_schedule_ko("team:reel_5m") and "딥시크" in A.room_schedule_ko("team:ds_trend")
    assert A.group_role_of_room("team:market") is None and A.room_schedule_ko("team:market")
    assert rooms._role("spec_V45_AMB").get("group_role") is None
    if any(s["room_id"] == "team:ds_structure" for s in A.Rooms(None, None).specs.values()):
        zones = {z["room_id"]: z for z in rooms.office()["zones"]}
        assert zones["team:ds_structure"]["group_role"] == "ds_structure" and zones["team:market"]["group_role"] is None
    assert "4개 봉 계좌" in A.room_schedule_ko("strat:V45_AMB") or "봉 비교" not in A.room_schedule_ko("strat:V45_AMB")


def test_the_restart_banner_states_the_verdict_method_from_the_checkpoint(tmp_path):
    from paperbot import checkpoint as CP
    b = A.restart_banner(NOW, NOW)
    assert b["n_bots"] == CP.N_BOTS and b["family_alpha"] == CP.FAMILY_ALPHA
    assert f"{CP.N_BOTS:,}개" in b["method_ko"] and "2,000" not in b["method_ko"]
    # one method text (G18): the checkpoint's own line, the same one the agents' facts carry
    from paperbot.agents import facts as F
    assert b["method_ko"] == CP.method_ko() == F.facts()["method_ko"]
