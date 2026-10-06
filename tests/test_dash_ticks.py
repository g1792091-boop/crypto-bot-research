"""The sound layer's market trades (dash/more/ticks.py + core/sound.js), with a fake websocket (no network here).

- parse: the aggTrade 'm' flag is the side (m = the buyer was the maker = a taker SELL), other coins / junk are skipped;
- aggregation: at most one event per half second for every coin together (~2 a second), the coin furthest above its
  own usual, buy / sell by notional, size buckets ranked among recent events (none before there is a history), nothing
  for a quiet half second, a stale window dropped;
- the relay: ONE socket, opened by the first listener, closed a minute (here: a moment) after the last one left,
  reopened by a new one; a socket that cannot connect says "down" (the page falls back to /api/ticker) with a growing
  wait; stop() ends it; a full relay says "down";
- the route sits behind the login, streams state + events, is never gzipped, keeps connect-src 'self', and the app's
  shutdown stops the relay;
- sound.js: buy -> the upper notes, sell -> the lower, a bigger bucket is louder, the same layer (throttle / density);
  the ticker's price changes are heard only while the relay is not live; the EventSource opens only while the sound
  is on, unlocked and the page visible, and a refused one falls back and retries later.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time

import pytest

from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash import app as A  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import ticks as T  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SECRET = b"x" * 32
PW = "correct horse battery"
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT")


def msg(sym="BTCUSDT", p=100.0, q=1.0, m=False, t=1, wrap=True) -> str:
    d = {"e": "aggTrade", "E": t, "s": sym, "a": 1, "p": str(p), "q": str(q), "f": 1, "l": 1, "T": t, "m": m}
    return json.dumps({"stream": sym.lower() + "@aggTrade", "data": d} if wrap else d)


class FakeWS:
    """recv() hands out the queued messages (a little apart), then '' until shut down; never touches the network."""

    def __init__(self, msgs=(), gap=0.002):
        self.msgs, self.gap = list(msgs), gap
        self.down, self.closed = threading.Event(), False

    def recv(self):
        if self.down.is_set():
            raise ConnectionError("shut down")
        time.sleep(self.gap if self.msgs else 0.01)
        return self.msgs.pop(0) if self.msgs else ""

    def shutdown(self):
        self.down.set()

    def close(self):
        self.closed = True
        self.down.set()


def _until(cond, s=3.0):
    end = time.time() + s
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# ---------------------------------------------------------------- parse
def test_parse_side_from_the_m_flag_and_skips_junk():
    assert T.symbols() == A.TICKER_SYMBOLS == SYMS                      # the dashboard's 7 coins, /api/ticker's list
    assert T.stream_url(("BTCUSDT", "XRPUSDT")) == "wss://fstream.binance.com/market/stream?streams=btcusdt@aggTrade/xrpusdt@aggTrade"
    buy = T.parse(msg(m=False, p=200, q=0.5, t=7), SYMS)
    sell = T.parse(msg(m=True, wrap=False), SYMS)
    assert buy == ("BTCUSDT", True, 100.0, 200.0, 7) and sell[1] is False   # m = buyer is maker = a taker sell
    assert T.parse(msg(sym="ADAUSDT"), SYMS) is None                        # not one of ours
    for junk in ("", "{", "[]", json.dumps({"e": "trade"}), msg(p=0), msg(q="nan"), msg(p="inf"), b"x" * 70_000,
                 "x" * 70_000, None, 5):
        assert T.parse(junk, SYMS) is None, junk
    assert T.parse(msg().encode(), SYMS)[0] == "BTCUSDT"


# ---------------------------------------------------------------- aggregation
def _tr(sym, usd, buy=True, ms=1):
    return (sym, buy, float(usd), 1.0, ms)


def test_one_event_per_half_second_the_coin_furthest_above_its_usual():
    g = T.Agg(SYMS, 0.5)
    assert g.add(_tr("BTCUSDT", 1000), 0.0) is None                      # opens the first window
    g.add(_tr("BTCUSDT", 2000, buy=False), 0.1)
    g.add(_tr("ETHUSDT", 50), 0.2)
    ev = g.add(_tr("BTCUSDT", 10), 0.5)                                  # closes [0, 0.5)
    # no usual yet: every coin scores 1, the first in the list wins; more taker selling -> sell
    assert ev["s"] == "BTCUSDT" and ev["side"] == "sell" and ev["usd"] == 3000 and ev["n"] == 2 and ev["b"] == 1
    # BTC trades its usual, ETH ten times its usual: ETH is the event, although BTC traded more dollars
    t = 0.5
    for _ in range(5):
        g.add(_tr("BTCUSDT", 3000), t + 0.01)
        g.add(_tr("ETHUSDT", 50), t + 0.02)
        t += 0.5
        g.tick(t)
    g.add(_tr("BTCUSDT", 3000), t + 0.01)
    g.add(_tr("ETHUSDT", 500), t + 0.02)
    ev = g.tick(t + 0.5)
    assert ev["s"] == "ETHUSDT" and ev["side"] == "buy" and ev["usd"] == 500
    assert g.tick(t + 1.0) is None                                       # a half second without a trade: silent
    assert g.tick(t + 1.2) is None                                       # (and a window is closed only when it is due)


def test_throttle_is_two_a_second_for_every_coin_together():
    g = T.Agg(SYMS, 0.5)
    evs, t = [], 0.0
    for i in range(4000):                                                # 10 s of a busy market, all 7 coins
        t = i * 0.0025
        e = g.add(_tr(SYMS[i % 7], 100 + (i * 37) % 900, buy=bool(i % 3)), t)
        if e:
            evs.append(t)
    assert 18 <= len(evs) <= 21
    assert min(b - a for a, b in zip(evs, evs[1:])) >= 0.5 - 1e-9


def test_stale_window_is_dropped_and_buckets_need_a_history():
    g = T.Agg(SYMS, 0.5)
    g.add(_tr("BTCUSDT", 100), 0.0)
    g.add(_tr("BTCUSDT", 100), 0.1)
    assert g.add(_tr("BTCUSDT", 100), 5.0) is None                      # the socket was quiet 5 s: not "now"
    t, bs = 5.0, []
    for i in range(T.RANK_MIN + 30):                                     # usual flow: steady, small differences
        g.add(_tr("SOLUSDT", 100 + i % 3), t + 0.01)
        t += 0.5
        e = g.tick(t)
        bs.append(e["b"])
    assert set(bs[:T.RANK_MIN]) == {1}                                   # no history yet: never a loud guess
    g.add(_tr("SOLUSDT", 5000, buy=False), t + 0.01)                     # a burst 50x the usual
    e = g.tick(t + 0.5)
    assert e["b"] == 4 and e["side"] == "sell" and set(bs) <= {1, 2, 3, 4}
    assert len(g.scores) <= T.RANK_KEEP and set(g.acc) == set()          # bounded; the window was emptied


# ---------------------------------------------------------------- the relay (one socket, listeners, fallback)
def test_one_socket_opened_by_the_first_listener_and_closed_after_the_last():
    made = []

    def connect(url):
        assert url == T.stream_url(SYMS)
        ws = FakeWS([msg(s, 100, 1 + i % 5, m=bool(i % 2), t=i) for i in range(400) for s in (SYMS[i % 7],)])
        made.append(ws)
        return ws
    r = T.TickRelay(SYMS, connect=connect, linger_s=0.3, window_s=0.05)
    assert r.snapshot()["running"] is False and made == []              # nobody listens: no socket
    a, b = r.subscribe(), r.subscribe()                                  # two pages, ONE socket
    assert a and b and a != b
    assert _until(lambda: r.state == "live" and r.seq >= 5)
    state, seq, evs = r.after(0)
    assert state == "live" and len(made) == 1 and evs and all(e["side"] in ("buy", "sell") and 1 <= e["b"] <= 4 for e in evs)
    assert len(r.events) <= T.EVENTS_KEEP and r.after(seq)[2] == []
    r.unsubscribe(a)
    time.sleep(0.4)
    assert r.after(seq, b)[0] == "live"                                 # b's answer still looks for events
    assert r.snapshot()["running"] is True and not made[0].closed       # one page still listens
    r.unsubscribe(b)
    assert _until(lambda: made[0].closed and not r.snapshot()["running"], 3)   # a moment after the last one left
    assert r.subscribe() and _until(lambda: len(made) == 2 and r.state == "live")   # a new page: a new socket
    assert r.snapshot()["threads"] == 2
    r.stop()
    assert made[1].closed and r.state == "down" and r.subscribe() is None
    assert r.snapshot()["running"] is False


def test_cannot_connect_says_down_with_a_growing_wait_and_stops_at_once():
    tries = []

    def refuse(url):
        tries.append(time.time())
        raise OSError("blocked")
    r = T.TickRelay(SYMS, connect=refuse, linger_s=60)
    assert r.subscribe()
    assert _until(lambda: r.state == "down")                            # the page's sound layer falls back
    assert r.after(0) == ("down", 0, [])
    time.sleep(1.3)
    assert len(tries) == 2                                               # 1 s, then 2 s ... (never a tight loop)
    t0 = time.time()
    r.stop()
    assert time.time() - t0 < 1.0 and r.snapshot()["running"] is False and r.snapshot()["fails"] >= 2


def test_a_listener_that_stopped_looking_is_forgotten():
    socks = []
    r = T.TickRelay(SYMS, connect=lambda url: socks.append(FakeWS()) or socks[-1], linger_s=0.2, listener_ttl_s=0.3)
    assert r.subscribe() and _until(lambda: r.state == "live")          # a page whose answer never says goodbye
    assert _until(lambda: socks[0].closed and r.listeners == 0, 3)      # ttl + linger: the socket closes anyway
    r.stop()


def test_full_relay_and_dropped_socket():
    socks = []

    def connect(url):
        ws = FakeWS([msg()] * 3)
        socks.append(ws)
        if len(socks) == 1:
            ws.recv = lambda: (_ for _ in ()).throw(ConnectionError("dropped"))
        return ws
    r = T.TickRelay(SYMS, connect=connect, max_listeners=1, linger_s=60)
    r.max_backoff = 0.05
    assert r.subscribe() and r.subscribe() is None                       # full: that page is told "down"
    assert _until(lambda: len(socks) >= 2 and r.state == "live", 4)      # dropped -> reconnected
    assert socks[0].closed
    r.stop()


def test_a_server_that_accepts_and_drops_at_once_is_not_asked_every_second():
    tries = []

    class Drop:
        def recv(self):
            raise ConnectionError("closed by the server")

        def shutdown(self):
            pass

        def close(self):
            pass

    def connect(url):
        tries.append(time.time())
        return Drop()
    r = T.TickRelay(SYMS, connect=connect, linger_s=60)
    assert r.subscribe()
    time.sleep(3.6)
    r.stop()
    gaps = [b - a for a, b in zip(tries, tries[1:])]
    assert 2 <= len(tries) <= 3 and all(g >= 0.9 for g in gaps)          # 1 s, then 2 s: never back to 1 s a time
    assert len(gaps) < 2 or gaps[1] >= 1.8


def test_a_junk_trade_time_is_skipped_not_a_reconnect():
    d = json.loads(msg())
    d["data"]["T"] = d["data"]["E"] = "soon"
    assert T.parse(json.dumps(d), SYMS) is None


# ---------------------------------------------------------------- the route
def _app(tmp_path):
    db = str(tmp_path / "p.db")
    Store3(db).close()
    return create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [])


def test_route_needs_login_streams_state_and_events_and_stops_with_the_app(tmp_path):
    app = _app(tmp_path)
    relay = app.state.more["ticks"]["relay"]
    assert relay.snapshot()["running"] is False                          # nobody listens yet: no socket
    feed = [msg(SYMS[i % 7], 10 + i, 1, m=bool(i % 2), t=i) for i in range(3000)]
    relay.connect = lambda url: FakeWS(feed, gap=0.0005)
    relay.stream_max_s = 1.2
    with TestClient(app) as c:
        r = c.get("/api/v4/ticks")
        assert r.status_code == 401 and relay.snapshot()["running"] is False    # the login first, no socket
        assert c.post("/api/login", json={"password": PW}).status_code == 200
        r = c.get("/api/v4/ticks", headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert r.headers.get("content-encoding") is None                 # never gzipped (NO_GZIP_PATHS)
        assert "connect-src 'self'" in r.headers["content-security-policy"]      # the browser only talks to us
        assert r.text.startswith(f"retry: {T.RETRY_MS}\n\n")
        msgs = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
        assert msgs[0]["ev"] == [] and msgs[0]["state"] in ("connecting", "live")
        evs = [e for m in msgs for e in m["ev"]]
        assert any(m["state"] == "live" for m in msgs) and evs
        assert {e["side"] for e in evs} <= {"buy", "sell"} and all(e["s"] in SYMS for e in evs)
        assert len(evs) <= 2 * 1.2 + 2                                    # ~2 a second at most
        assert relay.listeners == 0                                        # the answer ended: the page left
        assert relay.snapshot()["running"] is True                        # (the socket lingers for the next page)
    assert relay.stopping and relay.snapshot()["running"] is False       # the app's shutdown stopped it
    assert "ticks" in A.NO_GZIP_PATHS[1] and "/api/v4/ticks" in A.NO_GZIP_PATHS


def test_route_says_down_when_the_socket_cannot_connect(tmp_path):
    app = _app(tmp_path)
    relay = app.state.more["ticks"]["relay"]

    def refuse(url):
        raise OSError("no network")
    relay.connect = refuse
    relay.stream_max_s = 0.8
    c = TestClient(app)
    c.post("/api/login", json={"password": PW})
    text = c.get("/api/v4/ticks").text
    msgs = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    assert msgs[-1]["state"] == "down" and not any(m["ev"] for m in msgs)
    relay.stop()


def test_a_turned_away_page_asks_again_in_a_minute(tmp_path):
    app = _app(tmp_path)
    relay = app.state.more["ticks"]["relay"]
    relay.max_listeners = 0                                              # full
    c = TestClient(app)
    c.post("/api/login", json={"password": PW})
    text = c.get("/api/v4/ticks").text
    assert text.startswith(f"retry: {T.BUSY_RETRY_MS}\n\n") and T.BUSY_RETRY_MS >= 60000
    assert json.loads(text.split("data: ")[1]) == {"state": "down", "ev": [], "why": "busy"}
    assert relay.snapshot()["running"] is False
    relay.stop()


def test_module_is_registered_and_never_calls_rest():
    from paperbot.dash import more
    assert "ticks" in more.MODULES
    with open(T.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert "urllib" not in src and "requests" not in src and "fapi/v1" not in src and "http://" not in src
    assert "https://" not in src and re.findall(r'"wss://[^"]*"', src) == ['"wss://fstream.binance.com/market/stream?streams="']
    assert "daemon=True" in src and "on_shutdown.append(relay.stop)" in src


# ---------------------------------------------------------------- sound.js
def _node(body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core = "file://" + os.path.join(V4, "core")
    script = (f"const sound = await import('{core}/sound.js');\n"
              "const log = [];\n"
              "sound._test.setSink((kind, a) => log.push({kind, f: a.f || null, fs: a.fs || null, v: a.v, src: a.src || null, key: a.key || null}));\n"
              "sound.cfg.on = true; sound.cfg.night = false; sound._test.unlock(true);\n"
              "const wait = (ms) => new Promise((r) => setTimeout(r, ms));\n" + body +
              "\nprocess.stdout.write(JSON.stringify(out) + '\\n', () => process.exit(0));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_trades_drive_the_same_layer_buy_high_sell_low_bigger_louder():
    out = _node("""
    const items = sound.tickItems([{s: "BTCUSDT", side: "buy", b: 1}, {s: "ETHUSDT", side: "sell", b: 4},
      {s: "ADAUSDT", side: "buy", b: 1}, {s: "SOLUSDT", side: "up", b: 1}, null], 1000);
    const notes = items.map((x) => sound.beepOf(x));
    const vols = [1, 2, 3, 4].map((b) => sound.beepOf(sound.tickItems([{s: "LTCUSDT", side: "buy", b}])[0]).v);
    const down = sound.onTicks({state: "down", ev: [{s: "BTCUSDT", side: "buy", b: 1}]});
    const liveA = sound.tradesLive();
    const fed = sound.onTicks({state: "live", ev: [{s: "BTCUSDT", side: "buy", b: 1}, {s: "XRPUSDT", side: "sell", b: 2}]});
    const liveB = sound.tradesLive(), stale = sound.tradesLive(Date.now() + sound.TICK_FRESH_MS + 1);
    await wait(300);
    const out = {items, notes, vols, down, liveA, fed: fed.length, liveB, stale, log};""")
    a, b = out["items"]
    assert len(out["items"]) == 2 and a["dir"] == 1 and b["dir"] == -1 and a["src"] == "trade" == b["src"]
    assert a["voice"] == 1 and b["voice"] == 3                         # sorted: the same voice as the ticker layer
    assert (out["notes"][0].get("f") or out["notes"][0]["fs"][0]) >= 659.26   # buy: starts in the upper four notes
    assert out["notes"][1]["fs"][0] <= 554.37 and len(out["notes"][1]["fs"]) == 3   # sell: lower, the top bucket a run
    assert out["vols"] == sorted(out["vols"]) and out["vols"][0] < out["vols"][-1]  # a bigger bucket is louder
    assert out["down"] == [] and out["liveA"] is False                 # not live: nothing from the relay
    assert out["fed"] == 2 and out["liveB"] is True and out["stale"] is False
    assert len(out["log"]) == 1 and out["log"][0]["src"] == "trade"    # the layer's spacing: the biggest first, one now


def test_ticker_is_the_fallback_and_the_layer_rules_are_unchanged():
    src = open(os.path.join(V4, "core", "sound.js"), encoding="utf-8").read()
    assert 'store.watch("ticker", (tk) => { ticksSync(); if (!tk) return; const mv = priceMoves(tk); if (!tradesLive()) feed(mv); })' in src
    assert 'new ES("/api/v4/ticks")' in src and "wss://" not in src and "binance.com" not in src   # only our server
    assert "export const MIN_GAP_MS = 500;" in src and 'normal: {ko: "보통", gap: 1333},' in src     # ~0.75 / s
    assert src.count("setInterval(") == 1


def test_event_source_opens_only_when_on_unlocked_visible_and_retries_when_refused():
    out = _node("""
    const made = [];
    globalThis.EventSource = class { constructor(u) { this.url = u; this.readyState = 0; this.closed = false; made.push(this); }
      close() { this.closed = true; this.readyState = 2; } };
    const out = {};
    sound._test.unlock(false); sound._test.ticksOpen(); out.locked = made.length;
    sound._test.unlock(true); sound.cfg.on = false; sound._test.ticksOpen(); out.off = made.length;
    globalThis.document = {hidden: true, visibilityState: 'hidden', addEventListener() {}, removeEventListener() {}};
    sound.cfg.on = true; sound._test.ticksOpen(); out.hidden = made.length;
    globalThis.document.hidden = false; globalThis.document.visibilityState = 'visible';
    sound._test.ticksOpen(); sound._test.ticksOpen(); out.open = made.length; out.url = made[0].url;
    out.st0 = sound._test.ticks.state;
    made[0].onmessage({data: JSON.stringify({state: "live", ev: []})}); out.st1 = sound._test.ticks.state;
    made[0].readyState = 2; made[0].onerror(); out.st2 = sound._test.ticks.state;
    out.retry = !!sound._test.ticks.retryT && sound._test.ticks.es === null && sound._test.ticks.retryMs === 60000;
    sound._test.ticksOpen(); out.waits = made.length;                  // the retry timer, not at once
    sound._test.ticksClose(); out.closed = {st: sound._test.ticks.state, t: sound._test.ticks.retryT};
    sound._test.ticksOpen(); made[1].onerror(); out.dropped = {st: sound._test.ticks.state, es: sound._test.ticks.es === made[1]};
    sound._test.reset(); out.reset = {closed: made[1].closed, st: sound._test.ticks.state};
    """)
    assert out["locked"] == 0 and out["off"] == 0 and out["hidden"] == 0      # no tap / off / hidden: no stream
    assert out["open"] == 1 and out["url"] == "/api/v4/ticks" and out["st0"] == "connecting"
    assert out["st1"] == "live" and out["st2"] == "down" and out["retry"] is True and out["waits"] == 1
    assert out["closed"] == {"st": "off", "t": None}
    assert out["dropped"] == {"st": "down", "es": True}               # the browser reconnects by itself (readyState 0)
    assert out["reset"] == {"closed": True, "st": "off"}


def test_the_night_mute_closes_the_stream_and_07_opens_it_again():
    out = _node("""
    const made = [];
    globalThis.EventSource = class { constructor(u) { this.url = u; this.readyState = 0; this.closed = false; made.push(this); }
      close() { this.closed = true; this.readyState = 2; } };
    const NIGHT = Date.UTC(2026, 9, 5, 18, 30), DAY = Date.UTC(2026, 9, 5, 22, 30);     // 03:30 / 07:30 KST
    const out = {};
    sound.cfg.night = true; Date.now = () => NIGHT;
    sound._test.ticksOpen(); sound._test.ticksSync(); out.night = made.length;
    Date.now = () => DAY; sound._test.ticksSync(); out.day = made.length;
    Date.now = () => NIGHT; sound._test.ticksSync(); out.closed = {c: made[0].closed, st: sound._test.ticks.state};
    sound.cfg.night = false; sound._test.ticksSync(); out.unticked = made.length;
    sound._test.reset();
    """)
    assert out["night"] == 0 and out["day"] == 1                         # muted night: no stream; 07:00: it opens
    assert out["closed"] == {"c": True, "st": "off"} and out["unticked"] == 2

