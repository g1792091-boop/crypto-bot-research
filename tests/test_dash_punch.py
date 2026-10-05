"""터미널 살아 있게 (owners 10/06 03:48: "빛나거나 막 움직이는 게 안 보인다, 화면이 부족하다"), dashboard only.

- 실시간 큰 체결 (dash/more/ticks.py Big + the relay): the aggTrades of one taker order (same coin, side and trade ms)
  are added up; an order at or above its coin's threshold (BTC $150k, ETH $80k, others $30k) is kept with time, coin,
  side (the aggTrade 'm' flag), price and notional, 고래 from 4 times the threshold; at most 40 kept; the 5-minute buy /
  sell sums drop what is older; with a fake socket (no network);
- the SSE answer: the first message carries the kept list and the thresholds, later messages only new rows; the sound
  layer's message shape ({state, ev}) is unchanged;
- the page: the feed is labelled as the whole market's trades (not our bots), carries no money of our accounts (and
  nothing per DeepSeek account), every light answers a real relay message (no timer, nothing under reduced motion or on
  a hidden page), the stream closes when the page is hidden or the screen is left, tokens only.
"""
import json
import os
import re
import threading
import time

from fastapi.testclient import TestClient

from paperbot.dash.app import create_app, hash_password
from paperbot.dash.more import ticks as T
from paperbot.store3 import Store3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SECRET = b"x" * 32
PW = "correct horse battery"
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT")


def _src(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _code(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'`])//.*$", r"\1", src)


def msg(sym="BTCUSDT", p=100.0, usd=1000.0, m=False, t=1) -> str:
    d = {"e": "aggTrade", "E": t, "s": sym, "a": 1, "p": str(p), "q": str(usd / p), "f": 1, "l": 1, "T": t, "m": m}
    return json.dumps({"stream": sym.lower() + "@aggTrade", "data": d})


def trade(sym, usd, buy=True, ms=1, p=100.0):
    return (sym, buy, float(usd), float(p), ms)


# ---------------------------------------------------------------- thresholds and aggregation
def test_thresholds_per_coin():
    assert T.big_usd("BTCUSDT") == 150_000 and T.big_usd("ETHUSDT") == 80_000
    for s in ("SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT"):
        assert T.big_usd(s) == 30_000
    assert T.WHALE_X == 4 and T.BIG_KEEP == 40 and T.FLOW_S == 300


def test_one_taker_order_is_added_up_and_kept_only_above_its_coins_threshold():
    b = T.Big(burst_s=0.25)
    b.reset(0.0)
    # BTC: three aggTrades of ONE taker buy (same trade ms) sweeping three prices = $160k -> one row
    assert b.add(trade("BTCUSDT", 60_000, True, 1000, 100.0), 0.00) == []
    assert b.add(trade("BTCUSDT", 50_000, True, 1000, 100.5), 0.01) == []
    assert b.add(trade("BTCUSDT", 50_000, True, 1000, 101.0), 0.02) == []
    rows = b.add(trade("BTCUSDT", 1_000, True, 1001, 101.0), 0.03)        # the next order closes it
    assert len(rows) == 1
    r = rows[0]
    assert r == {"t": 1000, "s": "BTCUSDT", "side": "buy", "p": 101.0, "usd": 160_000, "n": 3, "x": 1.1, "w": 0}
    # BTC $140k: under the threshold -> nothing; ETH $85k sell: kept; SOL $31k: kept
    b.add(trade("BTCUSDT", 140_000, False, 2000), 0.04)
    b.add(trade("ETHUSDT", 85_000, False, 2000), 0.05)
    b.add(trade("SOLUSDT", 31_000, True, 2000), 0.06)
    rows = b.flush(0.40)                                                     # their aggTrades have all arrived
    assert sorted((x["s"], x["side"]) for x in rows) == [("ETHUSDT", "sell"), ("SOLUSDT", "buy")]
    # the side change of the same coin and ms is another order; 4x the threshold is a whale
    b.add(trade("DOGEUSDT", 125_000, True, 3000), 1.0)
    rows = b.add(trade("DOGEUSDT", 20_000, False, 3000), 1.01)
    assert len(rows) == 1 and rows[0]["w"] == 1 and rows[0]["x"] == 4.2 and rows[0]["side"] == "buy"
    assert b.flush(2.0) == []                                                # the $20k sell stays under $30k


def test_sums_cover_the_last_five_minutes_and_say_their_span():
    b = T.Big(burst_s=0.0, flow_s=300)
    b.reset(0.0)
    b.add(trade("SOLUSDT", 40_000, True, 1), 10.0)
    b.flush(10.0)
    b.add(trade("SOLUSDT", 50_000, False, 2), 200.0)
    b.flush(200.0)
    s = b.sums(200.0)
    assert s == {"buy": 40_000, "sell": 50_000, "n": 2, "span": 200}
    s = b.sums(320.0)                                                        # the first one is over 5 minutes old
    assert s == {"buy": 0, "sell": 50_000, "n": 1, "span": 300}
    b.reset(400.0)                                                           # a new connection: the span starts over
    assert b.sums(410.0)["span"] == 10


class FakeWS:
    def __init__(self, msgs=(), gap=0.001):
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


def _until(cond, s=4.0):
    end = time.time() + s
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_relay_keeps_the_last_40_large_orders_with_the_m_flag_as_the_side():
    feed = []
    for i in range(60):                                   # 60 large SOL orders, two aggTrades each (same ms)
        sell = bool(i % 3 == 0)
        feed += [msg("SOLUSDT", 100 + i, 20_000, m=sell, t=1000 + i), msg("SOLUSDT", 100.1 + i, 20_000, m=sell, t=1000 + i)]
        feed.append(msg("BTCUSDT", 60_000, 500, m=False, t=1000 + i))     # small trades between them
    r = T.TickRelay(SYMS, connect=lambda url: FakeWS(feed), linger_s=0.2, window_s=0.05)
    tok = r.subscribe()
    assert _until(lambda: r.snapshot()["big"] >= 59)
    bseq, rows, sums = r.big_after(0)
    assert len(rows) == T.BIG_KEEP == 40 and bseq >= 59
    assert all(x["s"] == "SOLUSDT" and x["usd"] == 40_000 and x["n"] == 2 for x in rows)
    assert {x["side"] for x in rows} == {"buy", "sell"}
    assert all((x["side"] == "sell") == ((x["t"] - 1000) % 3 == 0) for x in rows)   # m=true -> a taker SELL
    assert sums["n"] >= 40 and sums["buy"] > 0 and sums["sell"] > 0
    assert r.big_after(bseq)[1] == []                                     # nothing new after the newest
    r.unsubscribe(tok)
    r.stop()


def _app(tmp_path):
    db = str(tmp_path / "p.db")
    Store3(db).close()
    return create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [])


def test_sse_first_message_carries_the_kept_list_and_later_ones_only_new_rows(tmp_path):
    app = _app(tmp_path)
    relay = app.state.more["ticks"]["relay"]
    feed = []
    for i in range(1500):
        feed.append(msg(SYMS[i % 7], 50 + i % 9, 900, m=bool(i % 2), t=10_000 + i))
        if i % 50 == 0:
            feed.append(msg("ETHUSDT", 2000, 90_000, m=bool(i % 100), t=20_000 + i))
    relay.connect = lambda url: FakeWS(feed, gap=0.0005)
    relay.stream_max_s = 1.5
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": PW}).status_code == 200
        msgs = [json.loads(x[6:]) for x in c.get("/api/v4/ticks").text.splitlines() if x.startswith("data: ")]
        first = msgs[0]
        assert first["ev"] == [] and "big" in first
        assert first["big"]["min"] == {s: T.big_usd(s) for s in relay.syms} and first["big"]["whale_x"] == 4
        assert set(first["big"]) >= {"rows", "buy", "sell", "n", "span"}
        rows = [r for m in msgs[1:] if "big" in m for r in m["big"]["rows"]]
        assert rows and all(set(r) == {"t", "s", "side", "p", "usd", "n", "x", "w"} for r in rows)
        assert all(r["s"] == "ETHUSDT" and r["usd"] >= 80_000 and r["side"] in ("buy", "sell") for r in rows)
        assert len({(r["t"], r["usd"], r["side"]) for r in rows}) == len(rows)        # no row twice in one answer
        assert all(set(m) <= {"state", "ev", "big"} for m in msgs)               # the sound layer's shape is unchanged
        assert all(isinstance(m["ev"], list) for m in msgs)
        # a second page gets the kept list (real past orders with their own times) in its first message
        again = [json.loads(x[6:]) for x in c.get("/api/v4/ticks").text.splitlines() if x.startswith("data: ")]
        assert again[0]["big"]["rows"] and again[0]["big"]["rows"][0]["s"] == "ETHUSDT"
    assert relay.stopping


# ---------------------------------------------------------------- the page
FILES = ["terminal.js", "terminal-live.js", "terminal-feed.js", "terminal-top.js", "terminal-chart.js", "terminal-side.js",
         "terminal-kit.js", "terminal.css"]


def test_feed_is_labelled_the_whole_market_and_carries_no_money_of_ours():
    live = _src("screens", "terminal-live.js")
    assert 'BIG_LABEL = "바이낸스 시장 전체 체결 (우리 봇 아님)"' in live
    assert "sub: BIG_LABEL" in live and 'h("b", null, BIG_LABEL)' in live            # head and footer
    assert '"고래"' in live and "실시간 큰 체결" in live
    code = _code(live)
    for word in ("pnl", "roe", "account", "equity", "acctLabel", "ui.assume"):
        assert word not in code, word                                            # market orders only, never our money
    side = _src("screens", "terminal-side.js")
    assert "바이낸스 시장 전체 · 우리 봇 아님" in side                              # 이 코인 포지션's market rows say so too
    # DeepSeek / coin flips stay counts only in our fills feed (unchanged rule)
    feed = _src("screens", "terminal-feed.js")
    assert 'FOLD = new Set(["ds", "coin"])' in feed
    fold = feed[feed.index("const what = "):feed.index("function render()")]
    assert "pnl" not in fold.replace("m.one", "")


def test_every_light_answers_a_real_message_and_respects_reduced_motion_and_hidden_pages():
    live, kit, js = _src("screens", "terminal-live.js"), _src("screens", "terminal-kit.js"), _src("screens", "terminal.js")
    # the one-shots skip reduced motion and a hidden page
    assert "const live = () => motion.visible() && !motion.reduced();" in live and "if (!el || !tone || !live()) return el;" in live
    assert "motion.reduced() || !motion.visible()" in kit and "PING_GAP_MS = 1200" in kit
    # no timer animates anything: no setInterval in the new code, ctx.every only the known cadences
    for f in ("terminal-live.js", "terminal-kit.js"):
        assert "setInterval" not in _src("screens", f) and "ctx.every(" not in _src("screens", f), f
    # the stream: opened only while visible, closed when hidden and when the screen is left
    assert "document.hidden" in live and 'ctx.listen(document, "visibilitychange"' in live and "ctx.track(close)" in live
    assert 'new ES("/api/v4/ticks")' in live
    # the lights are driven from the relay's own messages
    assert "ticks.on((m) =>" in js and "watch.onTick(ev)" in js and "top.onTick(ev)" in js and "chart.onTick(ev)" in js
    assert "top.onRelay(m)" in js and "big.onMsg(m)" in js
    assert "motion.pulseLive(liveDot)" in _src("screens", "terminal-top.js")
    assert "ROW_GAP_MS = 500" in _src("screens", "terminal-feed.js")                  # a row lights at most ~2 a second
    # the first message's list is the past: drawn without motion
    assert "if (!m.first) fresh.add(k);" in live
    css = _src("screens", "terminal.css")
    rm = css[css.rindex("@media (prefers-reduced-motion: reduce)"):]
    for sel in (".term-uline.run::after", ".term-px[data-hit]", ".term-wr[data-hit]", ".term-ptag[data-hit]"):
        assert sel in rm, sel
    assert "infinite" not in css[css.index("터미널 살아 있게"):]                       # no new loop


def test_tokens_only_and_both_skins():
    for f in FILES:
        src = _code(_src("screens", f))
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), f
        assert not re.search(r"\b(rgba?|hsla?)\(\s*\d", src), f
        assert "innerHTML" not in src and "toLocaleString" not in src, f
    css = _src("screens", "terminal.css")
    assert ':root:not([data-skin="classic"]) .term-p' in css                        # the neon edge is the AI skin's
    assert "--tglow" in css and "var(--accent-glow)" in css


def test_sound_hint_shows_only_while_the_sound_is_off_or_waits_and_uses_the_header_switch():
    top = _src("screens", "terminal-top.js")
    assert "const off = !sound.cfg.on, wait = sound.waiting();" in top and "sndHint.hidden = !(off || wait);" in top
    assert 'document.getElementById("sndbtn")' in top and 'ctx.on("sound:cfg", paintSnd)' in top
    assert "AudioContext" not in top                                              # no sound of its own


def test_inventory_and_contract_name_the_new_section():
    inv = _src("INVENTORY.md")
    assert "## 터미널 살아 있게" in inv and "실시간 큰 체결" in inv and "/api/v4/ticks" in inv


def test_liq_feed_declares_fresh_once():
    """Review 10/06: a second `let fresh` inside liqFeed's try block put the first `if (fresh)` in its temporal dead
    zone (a ReferenceError on every answer), so 시장 강제청산 showed "불러오지 못했습니다" whenever the recorder ran."""
    feed = _code(_src("screens", "terminal-feed.js"))
    body = feed[feed.index("export function liqFeed("):]
    body = body[:body.index("ctx.every(10000, load")]
    assert len(re.findall(r"\b(?:let|const|var)\b[^;]*\bfresh\s*=", body)) == 1     # the coin-switch flag, nothing else
    assert "isNew = !fresh && !seen.has(k)" in body and "if (isNew) nNew++;" in body


def test_big_and_liq_share_one_place_on_every_pc_window_while_the_recorder_runs():
    """Review 10/06: with the recorder on, four stacked panels left our fills ~1.5 rows and the big-order feed 1-2 rows
    at 1920x1080; the 큰 체결 · 청산 switch now applies to every PC height (not only windows under 940 px)."""
    css = _src("screens", "terminal.css")
    i = css.index("@media (min-width: 1200px) {\n  .term-left.has-liq .term-duoseg { display: inline-flex; }")
    block = css[i:css.index("\n}\n", i)]
    assert '.term-left.has-liq[data-duo="big"] .term-liqp, .term-left.has-liq[data-duo="liq"] .term-bigp { display: none; }' in block
    assert "flex-basis: 26%" not in css

