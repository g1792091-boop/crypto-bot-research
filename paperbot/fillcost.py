"""What a market order of the paper trade's size would really have cost (records only).

The paper engine fills every market and stop order at the reference price plus a fixed slippage
(``Settings.slippage_frac``, 0.02%). With $5,000 accounts at 20-50x an order is $20k-$100k of
notional, and on the smaller coins that eats several levels of the order book. This module
records, for every paper entry and exit, the order book at that moment and what the same order
would have paid walking it:

    slip_best   (VWAP - best price) / best, in the order's adverse direction
    slip_mid    (VWAP - mid) / mid           (includes half the spread)
    enough      whether the fetched depth (``limit`` levels a side) covered the whole order
    book        the walked side's levels [[price, qty], ...] up to 10x the order's size (``book_levels``; rows
                recorded before 2026-10-04 have none), for the nightly 2x/5x/10x walks (paperbot/slipcost.py)

Nothing here changes a fill: the engine is untouched, the rows only go to ``fill_costs`` in
paper3.db (the live runner is its writer) and to the nightly report.

Timing: the book is fetched when the runner handles the step, a few seconds after the minute
closed; a stop that triggered inside that minute was earlier. Steps replayed after a restart
(older than ``max_age_ms``) are recorded without a book (``status = 'stale'``). One request per
symbol with an event per minute (weight 5 at 100 levels), at most six a minute.

Only the original accounts' events request a book. An extra account's event (paperbot/extras.py) reuses a
book fetched for the 195 in the same step, else it is recorded as ``status = 'skipped'``: a request runs
before the 195's next signal compute and would move their reference prices and delays.

The bars live used (records only, option 3a of the 2026-10-03 parity diagnosis): the call that may fetch a book
(``fetch=True``, the 195's call in live3) also returns one ``event = 'bar'`` row per traded coin of the step,
with the 1m bar exactly as the accounts stepped on it (open/high/low/close/volume, mark OHLC) and
``processed_at`` (the runner's clock when it handled the step). Store3.fill_costs sends these rows to the
``live_bars`` table, never to ``fill_costs``. The nightly check replays the day on them to tell a 1m kline the
feed read before Binance had folded in the minute's last trades ("early_kline") from an engine problem
(paperbot/daily3.py). Building them is a few dicts per minute and can never raise into the runner.
"""

from __future__ import annotations

import statistics
from typing import Callable, Iterable, Optional

LIMIT = 100
# the walked side of the book kept with each row (``book``: [[price, qty], ...] best first), so the nightly check can
# walk 2x / 5x / 10x the size exactly (paperbot/slipcost.py): the levels up to and including the one that covers
# BOOK_KEEP_MULTIPLE x the order's notional, at most BOOK_KEEP_MAX levels (all that was fetched; on the big coins a
# handful of levels, so a row stays small). Fewer levels than that would make slipcost call a size 'too thin' that the
# fetched book did cover.
BOOK_KEEP_MULTIPLE = 10
BOOK_KEEP_MAX = LIMIT


def book_levels(levels: Iterable, notional: float, multiple: float = BOOK_KEEP_MULTIPLE,
                max_levels: int = BOOK_KEEP_MAX) -> list:
    """[[price, qty], ...] of ``levels`` (best first) until ``multiple`` x ``notional`` is covered, at most
    ``max_levels``. Recorded levels that do not cover a size make slipcost say 'book too thin' for it."""
    out, want, seen = [], float(multiple) * float(notional), 0.0
    for p, q in levels:
        if len(out) >= max_levels or seen >= want:
            break
        p, q = float(p), float(q)
        out.append([p, q])
        seen += p * q
    return out


def book_cost(levels: Iterable, notional: float, side: int, best: float, mid: float) -> dict:
    """Walk ``levels`` ([price, qty] best first: asks for a buy, bids for a sell) for ``notional``
    quote currency. ``side`` is the ORDER side (+1 buy, -1 sell)."""
    left, qty, cost = float(notional), 0.0, 0.0
    used = 0
    for p, q in levels:
        p, q = float(p), float(q)
        if left <= 0:
            break
        take = min(q, left / p)
        qty += take
        cost += take * p
        left -= take * p
        used += 1
    enough = left <= 1e-9 * max(1.0, notional)
    if qty <= 0:
        return {"vwap": None, "slip_best": None, "slip_mid": None, "levels": 0, "enough": False,
                "filled_notional": 0.0}
    vwap = cost / qty
    return {"vwap": vwap, "slip_best": side * (vwap - best) / best, "slip_mid": side * (vwap - mid) / mid,
            "levels": used, "enough": bool(enough), "filled_notional": cost}


BAR_FIELDS = ("open", "high", "low", "close", "volume", "mark_open", "mark_high", "mark_low", "mark_close")


def bar_rows(ts: int, bars: dict, now_ms: int) -> list[dict]:
    """One ``event = 'bar'`` row per coin of the step: the bar as the accounts stepped on it."""
    out = []
    for sym, b in bars.items():
        r = {"ts": ts, "event": "bar", "symbol": sym, "close_time": b.close_time, "processed_at": now_ms}
        for k in BAR_FIELDS:
            v = getattr(b, k, None)
            r[k] = None if v is None else float(v)
        out.append(r)
    return out


def _pos(e) -> Optional[tuple]:
    p = e.position
    return None if p is None else (p.symbol, p.side, p.qty, p.entry_time, p.entry_price)


class FillProbe:
    """``before(engines)`` just before the accounts' step, ``after(...)`` just after it: rows for the
    entries and exits of that step, priced on one order-book snapshot per symbol."""

    def __init__(self, depth: Callable[[str], dict], assumed_slip: float, limit: int = LIMIT,
                 max_age_ms: int = 180_000):
        self.depth = depth
        self.assumed_slip = float(assumed_slip)
        self.limit = limit
        self.max_age_ms = max_age_ms
        self.errors = 0
        self.bar_errors = 0

    def before(self, engines: dict) -> dict:
        return {aid: _pos(e) for aid, e in engines.items()}

    def events(self, ts: int, engines: dict, snap: dict, bars: dict) -> list[dict]:
        out = []
        for aid, e in engines.items():
            old, new = snap.get(aid), _pos(e)
            if old == new:
                continue
            if old is not None and (new is None or new[3] != old[3]):          # closed (maybe re-entered)
                sym, side, qty = old[0], old[1], old[2]
                px = bars[sym].close if sym in bars else old[4]
                out.append({"ts": ts, "account_id": aid, "symbol": sym, "event": "exit", "order_side": -side,
                            "qty": qty, "notional": qty * px})
            if new is not None and (old is None or new[3] != old[3]):          # opened
                out.append({"ts": ts, "account_id": aid, "symbol": new[0], "event": "entry", "order_side": new[1],
                            "qty": new[2], "notional": new[2] * new[4]})
        return out

    def after(self, ts: int, engines: dict, snap: dict, bars: dict, now_ms: int, books: Optional[dict] = None,
              fetch: bool = True) -> list[dict]:
        """Rows for ``engines``' entries and exits of the step. ``books`` (symbol -> fetched book) is filled in
        and may be shared between calls of the same step. ``fetch=False`` never requests a book: an event on a
        symbol without a book already fetched in this step is recorded as ``status = 'skipped'`` (the live
        runner uses it for the extra accounts, so they never add a request before the 195's next compute).

        The ``fetch=True`` call (the 195's) also returns the step's bars as ``event = 'bar'`` rows (``bar_rows``),
        after the entry / exit rows; the ``fetch=False`` call never does, so each bar is recorded once."""
        bar_recs: list[dict] = []
        if fetch:
            try:
                bar_recs = bar_rows(ts, bars, now_ms)
            except Exception:  # noqa: BLE001  (a record only: never stop the runner, never drop the fill rows)
                self.bar_errors += 1
                bar_recs = []
        rows = self.events(ts, engines, snap, bars)
        if not rows:
            return bar_recs
        stale = now_ms - ts > self.max_age_ms
        books = {} if books is None else books
        for r in rows:
            r["assumed_slip"] = self.assumed_slip
            if stale:
                r["status"] = "stale"
                continue
            sym = r["symbol"]
            if sym not in books and not fetch:
                r["status"] = "skipped"
                continue
            if sym not in books:
                try:
                    books[sym] = self.depth(sym)
                except Exception as exc:  # noqa: BLE001  (a record only: never stop the runner)
                    self.errors += 1
                    books[sym] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
            bk = books[sym]
            if "error" in bk or not bk.get("bids") or not bk.get("asks"):
                r["status"] = "no_book"
                r["error"] = bk.get("error")
                continue
            bid, ask = float(bk["bids"][0][0]), float(bk["asks"][0][0])
            best = ask if r["order_side"] > 0 else bid
            lv = bk["asks"] if r["order_side"] > 0 else bk["bids"]
            r.update(book_cost(lv, r["notional"], r["order_side"], best, (bid + ask) / 2),
                     best=best, spread=(ask - bid) / ((ask + bid) / 2), status="ok",
                     book_ts=bk.get("T") or bk.get("E"))
            try:                    # the levels walked, for the 2x/5x/10x walks of the nightly check (records only)
                r["book"] = book_levels(lv, r["notional"])
            except (TypeError, ValueError):
                pass
        return rows + bar_recs


def _pct(xs: list, q: float) -> Optional[float]:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def summary(rows: Iterable[dict]) -> dict:
    """Per symbol and event: orders, median / p90 / max adverse slippage from the best price,
    how often it exceeded the engine's fixed slippage, and orders the fetched depth did not cover."""
    by: dict = {}
    for r in rows:
        if r.get("status") != "ok" or r.get("slip_best") is None:
            continue
        by.setdefault((r["symbol"], r["event"]), []).append(r)
    out = []
    for (sym, ev), rs in sorted(by.items()):
        s = [x["slip_best"] for x in rs]
        n = [x["notional"] for x in rs]
        a = rs[0].get("assumed_slip")
        out.append({"symbol": sym, "event": ev, "orders": len(rs), "median_notional": statistics.median(n),
                    "slip_median": statistics.median(s), "slip_p90": _pct(s, 0.9), "slip_max": max(s),
                    "assumed": a, "over_assumed": sum(1 for x in s if a is not None and x > a),
                    "not_covered": sum(1 for x in rs if not x.get("enough"))})
    return {"rows": out, "note": "adverse slippage of a market order of the paper size vs the best price; "
                                 "the engine assumes 'assumed' on every fill"}
