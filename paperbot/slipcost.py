"""Realistic stop slippage and the cost at a larger size (descriptive records only).

Nothing here changes a fill: the paper engine keeps its fixed slippage (``Settings.slippage_frac``, 0.02%) on
every stop. The nightly check (paperbot/daily3.py) does the reading and writing; this module holds the pure
calculations and the agents' read-only reader (``week_packet``).

1. Stop slippage (``stop_fill``, ``stop_row``, ``summarize_stops``). For an SL / LOCK / LIQ exit the live executor
   would have had a STOP_MARKET order with ``workingType=CONTRACT_PRICE`` (docs/live-safety.md): it triggers on the
   first trade at or through the stop price and then sells (a long) or buys (a short) the position at market.
   From the public aggregate trades of the exit minute:
       first      the price of the first trade at or through the stop (the trigger)
       trades     a size-aware estimate: the trades after the trigger, within ``WINDOW_MS``, that took the same side
                  of the book our order would take (sells into bids for a long's exit), walked until their
                  quantities add up to the position size; when they do not, the rest is priced at the worst price
                  seen ("thin")
       book       when the live runner recorded an order-book read for this exit (fill_costs, a few seconds after
                  the minute), the trigger price moved by that read's adverse slippage of the same size
   The estimate (``est_px``) is the more adverse of the covered estimates (trades, book); with neither covered it
   is the thin trade walk. Basis points are adverse, against the stop price: paper_bps is what the paper exit
   assumed (2 bps in a minute, more on a gap at the open, the liquidation price for LIQ), real_bps the estimate.
   ``diff_usd`` = paper P&L - estimated real P&L of the exit (positive: a real stop would have cost that much
   more than paper). A LIQ's paper P&L is the lost margin; a real stop's loss is capped at the margin too.
2. Cost at a larger size (``walk_multiples``, ``size_cost_rows``, ``summarize_size_costs``). From the order-book
   reads in fill_costs: the adverse slippage from the best price if the order had been 2x / 5x / 10x the paper
   size. A row that carries the walked side of the book (``book``: [[price, qty], ...]) is walked exactly and
   marked ``book too thin`` when the recorded levels do not cover the size. The rows recorded so far keep only
   the walk of the paper size (paperbot/fillcost.py); for them what the record proves is used: too thin when the
   paper size itself was not covered or another order of the same read showed the whole recorded depth smaller
   than the size, bounds from other orders of the same read (the cost only grows with the size), else
   ``levels not recorded``.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from typing import Iterable, Optional, Sequence

from .fillcost import book_cost

WINDOW_MS = 5_000              # how long after the trigger the trades are walked
MULTIPLES = (2, 5, 10)
STOP_REASONS = ("SL", "LOCK", "LIQ")
THIN = "book too thin"
NOT_RECORDED = "levels not recorded"
BOUNDED = "bounded"


# ---------------------------------------------------------------- 1. stop slippage
def _through(p: float, side: int, stop: float) -> bool:
    return p <= stop if side > 0 else p >= stop


def _walk(trades: Sequence, qty: float, side: int) -> dict:
    """VWAP of ``trades`` [(ms, price, qty, buyer_is_maker)] taken in order until ``qty`` is filled; only the trades
    whose taker was on our exit order's side count (a long's exit sells: buyer is maker)."""
    want_m = side > 0
    left, cost, seen, worst, n = float(qty), 0.0, 0.0, None, 0
    for _t, p, q, m in trades:
        if bool(m) != want_m or q <= 0:
            continue
        take = min(q, left)
        cost += take * p
        seen += q
        left -= take
        n += 1
        worst = p if worst is None or side * (worst - p) > 0 else worst
        if left <= 1e-12 * max(1.0, qty):
            break
    covered = left <= 1e-12 * max(1.0, qty)
    return {"covered": covered, "qty_seen": seen, "trades": n, "worst": worst,
            "filled": float(qty) - max(left, 0.0), "cost": cost}


def _px(w: dict, qty: float, fallback: float) -> float:
    """The walk's average price for ``qty``; an uncovered rest at the worst price seen (or ``fallback``)."""
    rest = max(float(qty) - w["filled"], 0.0)
    worst = w["worst"] if w["worst"] is not None else fallback
    return (w["cost"] + rest * worst) / float(qty) if qty > 0 else fallback


def stop_fill(trades: Sequence, side: int, stop: float, qty: float, start_ms: int, window_ms: int = WINDOW_MS,
              depth_slip: Optional[float] = None, multiples: Sequence[int] = MULTIPLES) -> dict:
    """Where a STOP_MARKET (contract price) of ``qty`` for a ``side`` position (+1 long, -1 short) with ``stop``
    would have filled. ``trades``: [(ms, price, qty, buyer_is_maker)] oldest first; the trigger is searched from
    ``start_ms`` (the exit minute's start). ``depth_slip``: the recorded book read's adverse slippage for this
    size (fill_costs ``slip_best``), if any."""
    if not trades:
        return {"status": "no_trades"}
    k = next((i for i, (t, p, _q, _m) in enumerate(trades) if t >= start_ms and _through(p, side, stop)), None)
    if k is None:
        return {"status": "no_trade_through_stop", "trades": len(trades)}
    t0, first = trades[k][0], trades[k][1]
    after = [x for x in trades[k + 1:] if x[0] <= t0 + window_ms]
    w = _walk(after, qty, side)
    walk_px = _px(w, qty, first)
    depth_px = None if depth_slip is None else first * (1 - side * float(depth_slip))
    cands = ([("trades", walk_px)] if w["covered"] else []) + ([("book", depth_px)] if depth_px is not None else [])
    if cands:
        src, est = min(cands, key=lambda c: side * c[1])          # the more adverse (lower for a long's exit)
        thin = False
    else:
        src, est, thin = "trades (thin: rest at the worst price seen)", walk_px, True
    mult = {}
    for m in multiples:
        wm = _walk(after, m * qty, side)
        pm = _px(wm, m * qty, first)
        mult[str(m)] = {"px": pm, "bps": side * (stop - pm) / stop * 1e4, "covered": wm["covered"]}
    return {"status": "ok", "trigger": {"time": t0, "price": first, "ms_into_minute": t0 - start_ms},
            "first_px": first, "walk": {"px": walk_px, "covered": w["covered"], "qty_seen": w["qty_seen"],
                                        "trades": w["trades"], "window_ms": window_ms},
            "depth_px": depth_px, "depth_slip": depth_slip, "est_px": est, "est_source": src, "thin": thin,
            "multiples": mult}


def stop_row(t: dict, fill: dict, assumed_slip: float) -> dict:
    """One exit's record from its trade (paper3.db ``trades`` data) and ``stop_fill``'s result."""
    side, stop, qty = int(t["side"]), float(t["stop_price"]), float(t["qty"])
    exit_px, entry = float(t["exit_price"]), float(t["entry_price"])
    margin = float(t.get("margin") or 0.0)
    row = {"account_id": t.get("account_id"), "strategy": t.get("strategy_id"), "timeframe": t.get("timeframe"),
           "symbol": t["symbol"], "side": side, "exit_reason": t["exit_reason"], "exit_time": int(t["exit_time"]),
           "entry_time": int(t["entry_time"]), "qty": qty, "notional": qty * exit_px, "stop": stop,
           "paper_exit": exit_px, "assumed_bps": assumed_slip * 1e4,
           "paper_bps": side * (stop - exit_px) / stop * 1e4, "status": fill.get("status", "?")}
    if fill.get("status") != "ok":
        row.update({k: fill[k] for k in ("error",) if k in fill})
        return row
    est = float(fill["est_px"])
    paper_gross = -margin if t["exit_reason"] == "LIQ" and margin else side * qty * (exit_px - entry)
    real_gross = side * qty * (est - entry)
    if margin:
        real_gross = max(real_gross, -margin)                       # isolated margin: a loss stops at the margin
    row.update(first_px=fill["first_px"], first_bps=side * (stop - fill["first_px"]) / stop * 1e4, est_px=est,
               real_bps=side * (stop - est) / stop * 1e4, diff_usd=paper_gross - real_gross,
               est_source=fill["est_source"], thin=fill["thin"], trigger_ms=fill["trigger"]["ms_into_minute"],
               multiples={k: {"bps": v["bps"], "covered": v["covered"]} for k, v in fill["multiples"].items()},
               walk=fill["walk"], depth_px=fill["depth_px"], depth_slip=fill["depth_slip"])
    return row


def _q(xs: list, q: float) -> Optional[float]:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def _r(x: Optional[float], n: int = 2) -> Optional[float]:
    return None if x is None else round(float(x), n)


def stop_cell(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("status") == "ok"]
    real = [r["real_bps"] for r in ok]
    paper = [r["paper_bps"] for r in ok]
    diff = [r["diff_usd"] for r in ok]
    return {"exits": len(rows), "measured": len(ok),
            "paper_bps_median": _r(statistics.median(paper)) if paper else None,
            "real_bps_median": _r(statistics.median(real)) if real else None,
            "real_bps_p90": _r(_q(real, 0.9)), "real_bps_worst": _r(max(real)) if real else None,
            "extra_bps_median": _r(statistics.median([r["real_bps"] - r["paper_bps"] for r in ok])) if ok else None,
            "diff_usd_total": _r(sum(diff)) if diff else None, "diff_usd_worst": _r(max(diff)) if diff else None,
            "thin": sum(1 for r in ok if r.get("thin"))}


def summarize_stops(rows: list[dict], assumed_slip: Optional[float] = None, worst: int = 10) -> dict:
    """Overall and per strategy / timeframe / coin / exit reason: medians, p90 and worst of the estimated real
    slippage (bps), and the total $ a real stop would have cost beyond paper."""
    status: dict = {}
    for r in rows:
        status[r.get("status", "?")] = status.get(r.get("status", "?"), 0) + 1
    out = {"exits": len(rows), "status": status, "overall": stop_cell(rows)}
    for name, key in (("by_strategy", "strategy"), ("by_timeframe", "timeframe"), ("by_symbol", "symbol"),
                      ("by_reason", "exit_reason")):
        groups: dict = {}
        for r in rows:
            groups.setdefault(str(r.get(key)), []).append(r)
        out[name] = {k: stop_cell(v) for k, v in sorted(groups.items())}
    ok = sorted((r for r in rows if r.get("status") == "ok"), key=lambda r: -r["diff_usd"])
    out["worst"] = [{k: (_r(r[k]) if isinstance(r.get(k), float) else r.get(k))
                     for k in ("account_id", "symbol", "exit_reason", "exit_time", "notional", "paper_bps",
                               "real_bps", "diff_usd", "est_source")} for r in ok[:worst]]
    if assumed_slip is not None:
        out["assumed_bps"] = round(assumed_slip * 1e4, 3)
    out["note"] = ("estimate of a real STOP_MARKET (contract price) from the public trades after the trigger; "
                   "bps adverse against the stop; diff_usd > 0 = a real stop would have cost more than paper")
    return out


# ---------------------------------------------------------------- 2. cost at a larger size
def walk_multiples(levels, notional: float, order_side: int, best: float, mid: float,
                   multiples: Sequence[int] = MULTIPLES) -> dict:
    """Walk recorded book ``levels`` ([price, qty] best first, the side the order takes) for ``k`` x ``notional``.
    A size the levels do not cover is ``book too thin`` (its slippage is that of the covered part)."""
    out = {}
    for k in multiples:
        c = book_cost(levels, k * float(notional), order_side, best, mid)
        out[str(k)] = {"status": "ok" if c["enough"] else THIN, "slip_best": c["slip_best"],
                       "slip_mid": c["slip_mid"], "levels": c["levels"], "covered_notional": c["filled_notional"]}
    return out


def _snap_key(r: dict) -> tuple:
    return (r.get("ts"), r.get("symbol"), r.get("order_side"), r.get("book_ts"))


def size_cost_rows(rows: Iterable[dict], multiples: Sequence[int] = MULTIPLES) -> list[dict]:
    """For every fill_costs row with a book read (status ok): the cost at ``multiples`` x its size (see the module
    text). Rows: {symbol, event, account_id, notional, slip_best (1x), multiples: {k: {status, ...}}}."""
    ok = [r for r in rows if r.get("status") == "ok" and r.get("slip_best") is not None]
    snaps: dict = {}
    for r in ok:
        snaps.setdefault(_snap_key(r), []).append(r)
    out = []
    for r in ok:
        n = float(r["notional"])
        res: dict = {}
        book = r.get("book")
        if book:
            bid_ask_mid = r.get("mid") or (r["best"] * (1 - r["order_side"] * (r.get("spread") or 0) / 2))
            res = walk_multiples(book, n, int(r["order_side"]), float(r["best"]), float(bid_ask_mid), multiples)
        else:
            peers = snaps.get(_snap_key(r), [r])
            depth = min((float(p.get("filled_notional") or 0.0) for p in peers if not p.get("enough")), default=None)
            for k in multiples:
                size = k * n
                if not r.get("enough") or (depth is not None and size > depth * (1 + 1e-9)):
                    res[str(k)] = {"status": THIN, "recorded_depth": depth if depth is not None
                                   else r.get("filled_notional")}
                    continue
                lo = max(float(p["slip_best"]) for p in peers if float(p["notional"]) <= size * (1 + 1e-9))
                hi = [float(p["slip_best"]) for p in peers if p.get("enough") and float(p["notional"]) >= size]
                if hi:
                    res[str(k)] = {"status": BOUNDED, "slip_low": lo, "slip_high": min(hi)}
                else:
                    res[str(k)] = {"status": NOT_RECORDED, "slip_low": lo}
        out.append({"symbol": r["symbol"], "event": r.get("event"), "account_id": r.get("account_id"),
                    "timeframe": r.get("timeframe"), "notional": n, "slip_best": float(r["slip_best"]),
                    "multiples": res})
    return out


def summarize_size_costs(rows: Iterable[dict], tf_of: Optional[dict] = None,
                         multiples: Sequence[int] = MULTIPLES) -> dict:
    """Per coin and timeframe: for each multiple, how many orders were walked exactly (median / p90 adverse
    slippage from the best price), bounded, too thin for the recorded book, or not answerable."""
    tf_of = tf_of or {}
    rows = list(rows)
    for r in rows:
        if r.get("timeframe") is None:
            aid = r.get("account_id") or ""
            r["timeframe"] = tf_of.get(aid) or (aid.split("@", 1)[1] if "@" in aid else "?")
    sized = size_cost_rows(rows, multiples)
    groups: dict = {}
    for r in sized:
        groups.setdefault((r["symbol"], r["timeframe"]), []).append(r)
    out = []
    for (sym, tf), rs in sorted(groups.items()):
        cell = {"symbol": sym, "timeframe": tf, "orders": len(rs),
                "median_notional": _r(statistics.median([r["notional"] for r in rs])),
                "x1_slip_median": _r(statistics.median([r["slip_best"] for r in rs]), 6)}
        for k in multiples:
            ms = [r["multiples"][str(k)] for r in rs]
            exact = [m["slip_best"] for m in ms if m["status"] == "ok" and m.get("slip_best") is not None]
            hi = [m["slip_high"] for m in ms if m["status"] == BOUNDED]
            cell[f"x{k}"] = {"exact": len(exact), "slip_median": _r(statistics.median(exact), 6) if exact else None,
                             "slip_p90": _r(_q(exact, 0.9), 6), "bounded": len(hi),
                             "bounded_high_median": _r(statistics.median(hi), 6) if hi else None,
                             "too_thin": sum(1 for m in ms if m["status"] == THIN),
                             "not_recorded": sum(1 for m in ms if m["status"] == NOT_RECORDED)}
        out.append(cell)
    return {"rows": out, "multiples": list(multiples),
            "note": "adverse slippage from the best price of a market order k x the paper size on the recorded book "
                    "read; 'book too thin' = the recorded levels do not cover the size; 'not_recorded' = the read "
                    "kept only the paper size's walk (no levels)"}


# ---------------------------------------------------------------- the agents' reader (read-only)
def week_packet(daily_ro: Optional[sqlite3.Connection], paper_ro: Optional[sqlite3.Connection], since_ms: int,
                until_ms: int) -> dict:
    """For an agents' packet (the Monday cost meeting): the estimated real stop slippage of the exits in
    [since_ms, until_ms) from daily3.db ``stop_slips``, and the cost at 2x/5x/10x from paper3.db ``fill_costs``.
    Both connections read-only; a missing table gives a note, never an exception."""
    out: dict = {"window": {"from": since_ms, "to": until_ms}}
    rows = []
    if daily_ro is not None:
        try:
            rows = [json.loads(d) for (d,) in daily_ro.execute(
                "SELECT data FROM stop_slips WHERE exit_time >= ? AND exit_time < ?", (since_ms, until_ms))]
        except sqlite3.Error:
            rows = None
    if rows:
        s = summarize_stops(rows, worst=5)
        out["stop_slippage"] = {k: s[k] for k in ("exits", "status", "overall", "by_timeframe", "by_symbol",
                                                  "by_reason", "worst", "note")}
    else:
        out["stop_slippage"] = {"note": "기록 없음(daily3.db stop_slips가 없거나 이 기간의 손절 청산 없음)"}
    fc = []
    if paper_ro is not None:
        try:
            tf_of = {a: tf for a, tf in paper_ro.execute("SELECT account_id, timeframe FROM accounts")}
            fc = [json.loads(d) for (d,) in paper_ro.execute(
                "SELECT data FROM fill_costs WHERE ts >= ? AND ts < ? AND status = 'ok'", (since_ms, until_ms))]
        except sqlite3.Error:
            fc, tf_of = None, {}
    out["size_costs"] = (summarize_size_costs(fc, tf_of) if fc
                         else {"note": "기록 없음(fill_costs가 없거나 이 기간의 호가창 기록 없음)"})
    out["how_to_read"] = ("stop_slippage: 손절·잠금·강제청산 청산마다, 실제 STOP_MARKET(마지막 체결가 기준)이었다면 체결됐을 "
                          "가격을 바이낸스 공개 체결 기록으로 추정. bps는 손절가 대비 불리한 쪽(1bp = 0.01%), paper는 "
                          "보통 2bp를 가정. diff_usd > 0 = 실제였다면 paper보다 그만큼 더 잃음. size_costs: 같은 시각 "
                          "호가창 기록으로 주문이 2·5·10배였다면의 슬리피지(비율 0.001 = 0.1%). 'too_thin' = 기록된 "
                          "호가 100칸이 그 크기를 못 채움, 'not_recorded' = 호가 칸 자체는 저장되지 않아 답할 수 없음. "
                          "기록일 뿐 모의 체결은 바뀌지 않음")
    return out
