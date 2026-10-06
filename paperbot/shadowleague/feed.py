"""Where the shadow league's closed bars come from.

What the agents service has today (checked 2026-10-06):
  * paper3.db ``live_bars`` (the agents read it read-only, entrymoment.load_live_bars): the live runner's 1-minute bars,
    one row per coin per minute it stepped on, since the run's start and never pruned. That is days of history, not the
    33 days 200 bars of 4h need (and 300 bars of 4h are 50 days), so it cannot start this detector on 1h / 4h bars for
    weeks. It is therefore not used here.
  * market.db ``kline5m`` (the signal recorder's 5-minute archive, paperbot/archive.py, written by paperbot-record): bars
    since the recorder's first run on the server, not guaranteed to reach back 50 days for every coin and not readable
    from the agents tick's own paths; also not used.
  * public Binance USD-M klines, no key, which the agents tick already reads (committee.klines / committee.http_get,
    6 second timeout; rooms.fetch_market_moves, market_move meetings). The league reuses exactly that code through the
    ``get`` function the tick hands it (rooms.CM_HTTP_GET; tests give a fake, nothing here opens a socket itself).

New network use, and its limits:
  * one request per coin / timeframe only when a new closed bar is due (once per bar, never to "look"), the bars are
    kept in the league's own table (the cache), so a restart or a gap asks only for what is missing;
  * a bar is used only when it closed at least SETTLE_MS ago (the live feed's rule: a bar read in the first moments after
    its close can still be missing its last trades);
  * a request starts only while the tick still has its wall-time budget (the caller's deadline), at most MAX_PAGES pages
    per series per tick (the rest follows on the next tick), a failure is written down with its reason and the next try is
    not before BACKOFF_MS later;
  * a bad answer (an odd bar, a wrong grid, not numbers) rejects the whole page and says so: the series then reads
    'error', never 'nothing'.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Optional

from ..agents import committee as CM
from .store import Store

TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
SETTLE_MS = 20_000
HISTORY_BARS = 1000            # bars fetched before a member's start: the ATR settles, the profile and the clones have room
PAGE = 1500                    # Binance's limit per klines request
MAX_PAGES = 2                  # per series and tick
BACKOFF_MS = 5 * 60_000
REQUEST_S = 6.5                # committee.http_get's timeout (6 s) plus a little: a request starts only if it can end in time

Getter = Callable[[str], Any]


def symbol(coin: str) -> str:
    return f"{coin}USDT"


def latest_closed_open(now_ms: int, tf: str) -> int:
    """Open time of the newest bar that closed at least SETTLE_MS before ``now_ms``."""
    tfm = TF_MS[tf]
    return ((int(now_ms) - SETTLE_MS - tfm) // tfm) * tfm


def anchor_ms(start_ms: int, tf: str) -> int:
    """The first bar a series ever holds: HISTORY_BARS bars before the member's start bar. Fixed by the start date, so
    the ATR a series carries is the same whenever the league was first switched on."""
    tfm = TF_MS[tf]
    return (int(start_ms) // tfm) * tfm - HISTORY_BARS * tfm


def _bad(rows: list, tf: str) -> Optional[str]:
    tfm = TF_MS[tf]
    prev = None
    for r in rows:
        t, o, h, l, c, v, ct = r
        if not all(math.isfinite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0 or v < 0:
            return f"bar {t}: not a price"
        if h < max(o, c, l) or l > min(o, c, h):
            return f"bar {t}: high / low do not contain open and close"
        if t % tfm != 0 or ct != t + tfm - 1:
            return f"bar {t}: not on the {tf} grid"
        if prev is not None and t <= prev:
            return f"bar {t}: out of order"
        prev = t
    return None


def fetch_page(get: Optional[Getter], coin: str, tf: str, start_ms: int, end_ms: int, limit: int) -> tuple[list, str]:
    """(bars [t, o, h, l, c, v, close_time], '') or ([], reason). Uses committee.klines (public klines, closed bars only
    because ``end_ms`` is given); the reason of a failed request is kept instead of the empty list's silence."""
    if get is None:
        return [], "no price source (the tick has no public-klines getter)"
    seen: list[str] = []

    def rec(url: str) -> Any:
        try:
            return get(url)
        except Exception as exc:  # noqa: BLE001  (written down, then the same empty answer committee.klines gives)
            seen.append(f"{type(exc).__name__}: {str(exc)[:120]}")
            raise
    rows = CM.klines(rec, symbol(coin), tf, start_ms=int(start_ms), end_ms=int(end_ms), limit=int(limit))
    if not rows:
        return [], seen[-1] if seen else "the exchange gave no bars"
    return rows, ""


def sync_series(store: Store, coin: str, tf: str, get: Optional[Getter], now_ms: int, anchor: int,
                deadline_at: Optional[float] = None, clock: Callable[[], float] = time.monotonic,
                max_pages: int = MAX_PAGES) -> dict:
    """Bring the stored bars of one coin / timeframe up to the newest settled closed bar, if one is due.
    Returns {'state': 'idle' | 'ok' | 'error' | 'backoff' | 'budget', 'added', 'requests', 'reason'}."""
    tfm = TF_MS[tf]
    f = store.ensure_feed(coin, tf)
    t_max = latest_closed_open(now_ms, tf)
    next_t = anchor if f["last_bar_ms"] is None else int(f["last_bar_ms"]) + tfm
    out = {"state": "idle", "added": 0, "requests": 0, "reason": ""}
    if next_t > t_max:
        return out                                          # the next bar has not closed yet: nothing to ask
    if f["next_try_ms"] is not None and now_ms < int(f["next_try_ms"]):
        return {**out, "state": "backoff", "reason": f["error"] or ""}
    for _ in range(max_pages):
        if deadline_at is not None and clock() + REQUEST_S > deadline_at:
            out["state"] = "budget"                         # the rest of this series follows on the next tick
            return out
        limit = min(PAGE, (t_max - next_t) // tfm + 1)
        rows, why = fetch_page(get, coin, tf, next_t, t_max, limit)
        out["requests"] += 1
        if not rows:
            store.feed_error(coin, tf, now_ms, why, now_ms + BACKOFF_MS)
            return {**out, "state": "error", "reason": why}
        rows = [r for r in rows if r[0] >= next_t and r[0] <= t_max and r[6] + 1 + SETTLE_MS <= now_ms]
        if not rows:
            why = "the exchange's newest bars are not settled or not new"
            store.feed_error(coin, tf, now_ms, why, now_ms + BACKOFF_MS)
            return {**out, "state": "error", "reason": why}
        bad = _bad(rows, tf)
        if bad:
            store.feed_error(coin, tf, now_ms, "bad answer: " + bad, now_ms + BACKOFF_MS)
            return {**out, "state": "error", "reason": "bad answer: " + bad}
        with store.tx():
            got = store.ingest_bars(coin, tf, tfm, [r[:6] for r in rows], now_ms)
            store.feed_ok(coin, tf, now_ms)
        out["added"] += got["added"]
        next_t = int(rows[-1][0]) + tfm
        if next_t > t_max or len(rows) < limit:
            break
    out["state"] = "ok"
    return out
