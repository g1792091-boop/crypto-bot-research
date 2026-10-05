"""실시간 체결 바탕음 (v4 sound layer): real Binance USD-M market trades of the 7 dashboard coins, relayed to the page.

    GET /api/v4/ticks      server-sent events, behind the login like every /api route

The v6 chiptune's continuous layer (static/v4/core/sound.js) follows real market trades through this relay. ONE shared
WebSocket to Binance's public aggTrade streams of the 7 coins (wss://fstream.binance.com/stream?streams=btcusdt@aggTrade
/...; no API key, never a REST call: the bot owns this IP's REST weight) is aggregated into at most two events a second
for every page together. Every half second the coin whose traded notional in that half second ran furthest above its own
usual busy half second (an average over its recent half seconds that had trades) becomes one event:

    {"s": "BTCUSDT", "side": "buy" | "sell", "b": 1-4, "usd": 81234, "n": 17, "p": 64123.5, "t": <last trade ms>}

side: more taker-buy or more taker-sell notional (aggTrade ``m`` = the buyer was the maker = a taker SELL). b, the size
bucket: that half second's score (its notional over the coin's usual one) ranked among the scores of the last
``RANK_KEEP`` events: 1 below the median, 2 from the median, 3 from the 85th percentile, 4 from the 97th (the first
``RANK_MIN`` events are all 1: no history yet, no loud guess). A half second without a single trade sends nothing.

- The socket opens with the first listening page and closes a minute after the last one left (a reload keeps it);
  it reconnects with a growing wait (1 s up to 60 s; back to 1 s only after a connection that stayed up ``HEALTHY_S``,
  so a server that accepts and drops at once is never asked every second), when nothing arrives for ``IDLE_S`` and
  every 23 hours (Binance closes a connection after 24 h). A page the full relay turned away asks again in a minute.
- Bounded memory: seven accumulators, the last ``EVENTS_KEEP`` events, ``RANK_KEEP`` scores, at most ``MAX_LISTENERS``
  pages (one more is told "down" and its sound layer falls back; a page whose answer stopped looking for events for
  ``LISTENER_TTL_S`` no longer counts), messages over ``MAX_MSG_BYTES`` skipped.
- ``state`` in every answer: "connecting" (no socket yet), "live" (socket open), "down" (the last connect failed or
  the relay is full / stopped): the page's sound layer then uses /api/ticker price changes as before. The browser only
  talks to this server (CSP connect-src 'self').
- A daemon thread, stopped by the app's shutdown handler (never holds the process up). Read-only: no database.

실시간 큰 체결 (the 터미널's market feed, 10/06): the same socket ALSO keeps the last ``BIG_KEEP`` large market orders.
The aggTrades of one taker order (same coin, same side, same trade time: an order that swept several prices) are added
up; an order whose notional reaches its coin's ``BIG_USD`` (BTC $150k, ETH $80k, others $30k) is kept as

    {"t": <trade ms>, "s": "BTCUSDT", "side": "buy" | "sell", "p": <last price>, "usd": 412345, "n": <aggTrades>,
     "x": <notional / the coin's threshold, 1 decimal>, "w": 1 when at least ``WHALE_X`` times the threshold}

and the taker-buy / taker-sell notional of those orders over the last ``FLOW_S`` (5 minutes) is summed. An SSE message
that has something new for the page carries ``"big": {"rows": [new rows], "buy": usd, "sell": usd, "n": orders,
"span": seconds the sums really cover, "min": {coin: threshold}, "whale_x": 4}``; the first message of an answer
carries the whole kept list (real past orders with their own times). The whole market's trades, never our bots'.
"""
from __future__ import annotations

import asyncio
import bisect
import collections
import json
import math
import threading
import time
from typing import Callable, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

WS_BASE = "wss://fstream.binance.com/stream?streams="
WINDOW_S = 0.5            # one event per half second at most: ~2 a second for every page together
STALE_S = 3.0             # a window that stayed open this long (the socket went quiet) is not "now": dropped
LINGER_S = 60.0           # the socket stays this long after the last page left
IDLE_S = 20.0             # connect timeout, and no message at all for this long (7 coins trade every second): reconnect
MAX_CONN_S = 23 * 3600    # scheduled reconnect (Binance closes a connection after 24 h)
MAX_BACKOFF_S = 60.0
HEALTHY_S = 30.0          # the wait starts over at 1 s only after a connection that stayed up this long (a server
                          # that accepts and drops at once never gets a reconnect a second: the IP is the bot's too)
EVENTS_KEEP = 32          # the relay's ring of recent events (a slow page skips, never piles up)
RANK_KEEP = 240           # scores the size bucket is ranked among (~2 minutes of events)
RANK_MIN = 20             # fewer scores than this: bucket 1
BUCKET_AT = (0.5, 0.85, 0.97)   # percentile from which an event is bucket 2, 3, 4
EMA_A = 0.05              # the coin's usual busy half second: average over ~its last 20 windows with trades
MAX_LISTENERS = 16
LISTENER_TTL_S = 30.0     # a listener whose answer has not looked for events this long is gone (a leaked answer
                          # never holds the socket open or fills the relay)
MAX_MSG_BYTES = 65_536
POLL_S = 0.25             # how often a page's answer looks for new events
BEAT_S = 5.0              # an idle answer repeats the state this often (the page's freshness check)
STREAM_MAX_S = 600.0      # one answer lasts at most this long; the browser's EventSource reconnects by itself
RETRY_MS = 3000           # the EventSource reconnect wait (SSE 'retry:')
BUSY_RETRY_MS = 60000     # ... for a page the full relay turned away (no knock every 3 s)
# 실시간 큰 체결 (see the top)
BIG_USD = {"BTCUSDT": 150_000.0, "ETHUSDT": 80_000.0}
BIG_USD_OTHER = 30_000.0  # every other coin
WHALE_X = 4               # 고래: at least this many times the coin's threshold
BIG_KEEP = 40             # the kept list of large orders
BURST_S = 0.25            # one taker order's aggTrades arrive together: an open order closes this long after it began
FLOW_S = 300.0            # the buy / sell sums cover the last 5 minutes
FLOW_KEEP = 4000          # at most this many orders in those sums (bounded memory on a wild day)


def big_usd(sym: str) -> float:
    """The notional from which one market order of ``sym`` counts as large."""
    return BIG_USD.get(sym, BIG_USD_OTHER)


def symbols() -> tuple:
    """The dashboard's 7 coins (dash/app.py TICKER_SYMBOLS: the same list as /api/ticker)."""
    from ..app import TICKER_SYMBOLS
    return tuple(TICKER_SYMBOLS)


def stream_url(syms) -> str:
    return WS_BASE + "/".join(f"{s.lower()}@aggTrade" for s in syms)


def parse(raw, syms) -> Optional[tuple]:
    """One stream message -> (symbol, is_buy, usd, price, trade_ms), or None (not an aggTrade of our coins, bad)."""
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > MAX_MSG_BYTES:
            return None
        raw = raw.decode("utf-8", "replace")
    if not isinstance(raw, str) or not raw or len(raw) > MAX_MSG_BYTES:
        return None
    try:
        m = json.loads(raw)
    except ValueError:
        return None
    d = m.get("data", m) if isinstance(m, dict) else None       # combined-stream wrapper
    if not isinstance(d, dict) or d.get("e") != "aggTrade" or d.get("s") not in syms:
        return None
    try:
        p, q = float(d["p"]), float(d["q"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 < p < math.inf and 0 < q < math.inf):
        return None
    try:
        ms = int(d.get("T") or d.get("E") or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    return d["s"], d.get("m") is False, p * q, p, ms


class Agg:
    """Per-coin half-second windows -> at most one event per window (the coin furthest above its usual, see top)."""

    def __init__(self, syms, window_s: float = WINDOW_S):
        self.syms = tuple(syms)
        self.window_s = window_s
        self.t0: Optional[float] = None
        self.acc: dict = {}                    # symbol -> [buy usd, sell usd, n, last price, last ms, last is_buy]
        self.usual: dict = {}                  # symbol -> EMA of its busy windows' notional
        self.scores: collections.deque = collections.deque(maxlen=RANK_KEEP)

    def add(self, trade: tuple, now: float) -> Optional[dict]:
        """Count one parsed trade at ``now``; returns the event of the window it closed, if any."""
        ev = self.tick(now)
        s, buy, usd, p, ms = trade
        a = self.acc.get(s)
        if a is None:
            a = self.acc[s] = [0.0, 0.0, 0, 0.0, 0, True]
        a[0 if buy else 1] += usd
        a[2] += 1
        a[3], a[4], a[5] = p, ms, buy
        return ev

    def tick(self, now: float) -> Optional[dict]:
        """Close the window when it is ``window_s`` old: its event (or None: no trade, or stale)."""
        if self.t0 is None:
            self.t0 = now
            return None
        age = now - self.t0
        if age < self.window_s:
            return None
        self.t0 = now
        acc, self.acc = self.acc, {}
        best, best_score = None, -1.0
        for s in self.syms:                    # every coin's usual is kept up to date, the event is one coin
            a = acc.get(s)
            if not a or a[2] == 0:
                continue
            usd = a[0] + a[1]
            u = self.usual.get(s)
            score = usd / u if u else 1.0
            self.usual[s] = usd if u is None else u * (1 - EMA_A) + usd * EMA_A
            if score > best_score:
                best, best_score = s, score
        if best is None or age >= STALE_S:     # nothing traded, or the window waited on a quiet socket
            return None
        a = acc[best]
        hist = sorted(self.scores)
        self.scores.append(best_score)
        b = 1
        if len(hist) >= RANK_MIN:
            pct = bisect.bisect_right(hist, best_score) / len(hist)
            b = 1 + sum(pct >= x for x in BUCKET_AT)
        side = "buy" if a[0] > a[1] else "sell" if a[1] > a[0] else ("buy" if a[5] else "sell")
        return {"s": best, "side": side, "b": b, "usd": round(a[0] + a[1]), "n": a[2], "p": a[3], "t": a[4]}


class Big:
    """Large market orders: the aggTrades of one taker order (same coin, side and trade ms) added up; an order at or
    above its coin's threshold becomes a row. Plus the 5-minute taker buy / sell sums of those rows."""

    def __init__(self, burst_s: float = BURST_S, flow_s: float = FLOW_S):
        self.burst_s, self.flow_s = burst_s, flow_s
        self.open: dict = {}                   # symbol -> [is_buy, trade ms, usd, last price, n, began (clock)]
        self.flow: collections.deque = collections.deque(maxlen=FLOW_KEEP)   # (clock, is_buy, usd)
        self.since: Optional[float] = None     # when this connection began counting (the sums' real span)

    def reset(self, now: float) -> None:
        """A new connection: the old one's open orders are dropped (half an order is not an order)."""
        self.open = {}
        self.since = now

    def _close(self, s: str, now: float) -> Optional[dict]:
        o = self.open.pop(s, None)
        if o is None:
            return None
        buy, ms, usd, p, n, _ = o
        lim = big_usd(s)
        if usd < lim:
            return None
        self.flow.append((now, buy, usd))
        return {"t": ms, "s": s, "side": "buy" if buy else "sell", "p": p, "usd": round(usd), "n": n,
                "x": round(usd / lim, 1), "w": 1 if usd >= WHALE_X * lim else 0}

    def add(self, trade: tuple, now: float) -> list:
        """Count one parsed trade; returns the large orders this closed (the coin's previous order, old open ones)."""
        out = self.flush(now)
        s, buy, usd, p, ms = trade
        o = self.open.get(s)
        if o is not None and (o[0] != buy or o[1] != ms or not ms):
            r = self._close(s, now)
            if r:
                out.append(r)
            o = None
        if o is None:
            self.open[s] = [buy, ms, usd, p, 1, now]
        else:
            o[2] += usd
            o[3] = p
            o[4] += 1
        return out

    def flush(self, now: float) -> list:
        """Close the open orders that began ``burst_s`` ago (their aggTrades have all arrived)."""
        out = []
        for s in [k for k, o in self.open.items() if now - o[5] >= self.burst_s]:
            r = self._close(s, now)
            if r:
                out.append(r)
        return out

    def sums(self, now: float) -> dict:
        """Taker buy / sell notional of the large orders in the last ``flow_s``, and the seconds that really covers."""
        while self.flow and now - self.flow[0][0] > self.flow_s:
            self.flow.popleft()
        b = sum(u for _, buy, u in self.flow if buy)
        sl = sum(u for _, buy, u in self.flow if not buy)
        span = 0 if self.since is None else int(min(self.flow_s, max(0.0, now - self.since)))
        return {"buy": round(b), "sell": round(sl), "n": len(self.flow), "span": span}


class TickRelay:
    """ONE shared aggTrade socket for every page: opened on the first listener, closed ``linger_s`` after the last."""

    def __init__(self, syms=None, connect: Optional[Callable] = None, clock: Callable[[], float] = time.monotonic,
                 linger_s: float = LINGER_S, idle_s: float = IDLE_S, max_backoff: float = MAX_BACKOFF_S,
                 window_s: float = WINDOW_S, max_listeners: int = MAX_LISTENERS, max_conn_s: float = MAX_CONN_S,
                 listener_ttl_s: float = LISTENER_TTL_S):
        self.syms = tuple(syms or symbols())
        self.url = stream_url(self.syms)
        self.connect = connect or self._ws_connect
        self.clock = clock
        self.linger_s, self.idle_s, self.max_backoff = linger_s, idle_s, max_backoff
        self.window_s, self.max_listeners, self.max_conn_s = window_s, max_listeners, max_conn_s
        self.listener_ttl_s = listener_ttl_s
        self.healthy_s = HEALTHY_S
        self.stream_max_s = STREAM_MAX_S
        self.lock = threading.Lock()
        self.wake = threading.Event()          # set by stop(): ends a backoff wait at once
        self.thread: Optional[threading.Thread] = None
        self.ws = None
        self.subs: dict = {}                   # listener token -> when its answer last looked for events
        self.next_tok = 0
        self.left_at: Optional[float] = None
        self.stopping = False
        self.state = "connecting"
        self.seq = 0
        self.events: collections.deque = collections.deque(maxlen=EVENTS_KEEP)
        self.bigs: collections.deque = collections.deque(maxlen=BIG_KEEP)    # (big seq, row): the kept large orders
        self.bseq = 0
        self.big = Big()
        self.stats = {"connects": 0, "fails": 0, "msgs": 0, "events": 0, "threads": 0, "big": 0}

    def _ws_connect(self, url: str):
        import websocket  # websocket-client (requirements.txt), as paperbot/liqstream.py
        return websocket.create_connection(url, timeout=self.idle_s, enable_multithread=False)

    # ------------------------------------------------------------ listeners
    @property
    def listeners(self) -> int:
        return len(self.subs)

    def _prune(self, now: float) -> None:
        """(under the lock) Forget listeners that stopped looking; the last one gone starts the linger."""
        gone = [k for k, t in self.subs.items() if now - t >= self.listener_ttl_s]
        for k in gone:
            del self.subs[k]
        if gone and not self.subs and self.left_at is None:
            self.left_at = now

    def subscribe(self) -> Optional[int]:
        """A page starts listening: its token (None: stopped or full; that page's sound layer falls back)."""
        with self.lock:
            now = self.clock()
            self._prune(now)
            if self.stopping or len(self.subs) >= self.max_listeners:
                return None
            self.next_tok += 1
            tok = self.next_tok
            self.subs[tok] = now
            self.left_at = None
            if self.thread is None:
                if self.state != "down":
                    self.state = "connecting"
                self.stats["threads"] += 1
                self.thread = threading.Thread(target=self._run, name="dash-ticks", daemon=True)
                self.thread.start()
            return tok

    def unsubscribe(self, tok: Optional[int]) -> None:
        with self.lock:
            if self.subs.pop(tok, None) is not None and not self.subs:
                self.left_at = self.clock()

    def after(self, seq: int, tok: Optional[int] = None) -> tuple:
        """(state, newest seq, [events after ``seq``]) for one page's answer (its token: still listening)."""
        with self.lock:
            if tok in self.subs:
                self.subs[tok] = self.clock()
            return self.state, self.seq, [e for n, e in self.events if n > seq]

    def big_after(self, bseq: int) -> tuple:
        """(newest big seq, [large orders after ``bseq``], the 5-minute sums) for one page's answer."""
        with self.lock:
            sums = self.big.sums(self.clock()) if self.state == "live" else {"buy": 0, "sell": 0, "n": 0, "span": 0}
            return self.bseq, [r for n, r in self.bigs if n > bseq], sums

    def snapshot(self) -> dict:
        with self.lock:
            return {"state": self.state, "listeners": len(self.subs), "running": self.thread is not None,
                    "seq": self.seq, **self.stats}

    # ------------------------------------------------------------ the socket thread
    def _finished(self, me) -> bool:
        """Should this thread end now (stopped, or nobody has listened for ``linger_s``)? Decided under the lock, so
        a page that subscribes at the same moment starts a fresh thread."""
        with self.lock:
            if self.thread is not me:
                return True
            self._prune(self.clock())
            if self.stopping or (not self.subs and self.left_at is not None
                                 and self.clock() - self.left_at >= self.linger_s):
                self.thread = None
                if self.state == "live":
                    self.state = "connecting"
                return True
            return False

    def _publish(self, ev: Optional[dict]) -> None:
        if ev is None:
            return
        with self.lock:
            self.seq += 1
            self.events.append((self.seq, ev))
            self.stats["events"] += 1

    def _big(self, t: Optional[tuple], now: float) -> None:
        """One parsed trade (or None: a quiet moment) through the large-order counter; new rows are kept."""
        with self.lock:
            for r in self.big.add(t, now) if t else self.big.flush(now):
                self.bseq += 1
                self.bigs.append((self.bseq, r))
                self.stats["big"] += 1

    def _set_state(self, state: str) -> None:
        with self.lock:
            if not self.stopping:
                self.state = state

    def _run(self) -> None:
        me = threading.current_thread()
        backoff = 1.0
        while not self._finished(me):
            ws = opened = None
            try:
                ws = self.connect(self.url)
                with self.lock:
                    self.ws = ws
                    self.stats["connects"] += 1
                    if self.stopping:
                        continue                      # (finally closes it; the loop ends)
                    self.state = "live"
                agg = Agg(self.syms, self.window_s)
                opened = last = self.clock()
                with self.lock:
                    self.big.reset(opened)
                while not self._finished(me):
                    now = self.clock()
                    if now - opened >= self.max_conn_s:
                        break                         # scheduled reconnect
                    raw = ws.recv()                   # answers pings; raises on timeout or close
                    now = self.clock()
                    if raw in (None, "", b""):
                        if now - last >= self.idle_s:
                            raise TimeoutError("no message")
                        self._publish(agg.tick(now))
                        self._big(None, now)
                        continue
                    last = now
                    self.stats["msgs"] += 1
                    t = parse(raw, self.syms)
                    self._publish(agg.add(t, now) if t else agg.tick(now))
                    self._big(t, now)
                self._set_state("connecting")
                backoff = 1.0                         # (the scheduled reconnect: at once, the wait starts over)
            except Exception:  # noqa: BLE001  network errors, timeouts, closes, a blocked host
                with self.lock:
                    self.stats["fails"] += 1
                    if not self.stopping:
                        self.state = "down"
                if opened is not None and self.clock() - opened >= self.healthy_s:
                    backoff = 1.0                     # it worked for a while: a first quick retry
                if self._finished(me):
                    break
                self.wake.wait(backoff)
                backoff = min(self.max_backoff, backoff * 2)
            finally:
                with self.lock:
                    if self.ws is ws:
                        self.ws = None
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:  # noqa: BLE001
                        pass

    def stop(self, timeout: float = 2.0) -> None:
        """Close the socket and end the thread (the app's shutdown); no new listener is taken afterwards."""
        with self.lock:
            self.stopping = True
            self.state = "down"
            th, ws = self.thread, self.ws
            self.thread = None
        self.wake.set()
        if ws is not None:                            # unblock a pending recv()
            try:
                ws.shutdown()
            except Exception:  # noqa: BLE001
                pass
        if th is not None and th is not threading.current_thread():
            th.join(timeout)


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, separators=(",", ":")) + "\n\n"


def _big(rows: list, sums: dict, syms=None) -> dict:
    """The 'big' part of an SSE message: new large orders (newest last) and the 5-minute sums; the first one also says
    the thresholds."""
    out = {"rows": rows, **sums}
    if syms:
        out["min"] = {s: big_usd(s) for s in syms}
        out["whale_x"] = WHALE_X
    return out


def register(app, ctx) -> dict:
    relay = TickRelay()
    app.router.on_shutdown.append(relay.stop)

    @app.get("/api/v4/ticks")
    async def get_ticks(req: Request):
        """Real market trades of the 7 coins, at most ~2 events a second (server-sent events; see the module)."""
        async def gen():
            tok = relay.subscribe()
            if tok is None:                                 # full / stopped: the browser asks again in a minute
                yield f"retry: {BUSY_RETRY_MS}\n\n"
                yield _sse({"state": "down", "ev": [], "why": "busy"})
                return
            try:
                yield f"retry: {RETRY_MS}\n\n"
                state, seq, _ = relay.after(1 << 62, tok)     # from now on: no replay of older events
                bseq, rows, sums = relay.big_after(0)          # ... but the kept large orders (real, with their times)
                yield _sse({"state": state, "ev": [], "big": _big(rows, sums, relay.syms)})
                began = beat = time.monotonic()
                while not await req.is_disconnected():
                    await asyncio.sleep(POLL_S)
                    now = time.monotonic()
                    st, seq2, evs = relay.after(seq, tok)
                    bseq2, rows, sums2 = relay.big_after(bseq)
                    if evs or rows or st != state or now - beat >= BEAT_S:
                        out = {"state": st, "ev": evs}
                        if rows or sums2 != sums:
                            out["big"] = _big(rows, sums2)
                        state, seq, beat, bseq, sums = st, seq2, now, bseq2, sums2
                        yield _sse(out)
                    if now - began >= relay.stream_max_s or relay.stopping:
                        break
            finally:
                relay.unsubscribe(tok)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    return {"routes": ["/api/v4/ticks"], "relay": relay}
