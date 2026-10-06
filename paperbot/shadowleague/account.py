"""The owners'-style virtual account of a shadow member (참고용, 판정 아님).

The rules are the study's, copied from research/search/search.py (``owners_book``; the step-by-step form is
lib_zoneflip.py ``owners_curve``): one position at a time across coins, 20 % of the equity as margin at 20x (= 4x
exposure), a loss is capped at the margin, and a 4.5 % adverse move (1/20 - 0.5 %) liquidates the position.

    sort the trades by (entry time, coin); a trade whose entry bar opens before the last taken trade's exit bar
    opens is not taken; a taken trade that was liquidated (-mae >= 4.5 %) costs the margin (20 %); otherwise equity
    is multiplied by 1 + max(4 x net, -20 %).

The study ran one account per timeframe (a cell); this module does the same per timeframe and additionally one account
over all four timeframes of a member ('all'). The equity is REALIZED: a trade counts when its exit bar has closed; an
open position is not marked to market. It starts at 5,000 USDT on the member's start day.

A taken trade that is still open blocks every later trade (its exit is not known, and any later entry is inside it).
The result is a pure function of the trade rows: it is recomputed from them, never accumulated, so a restart or a late
bar can not make it drift.
"""

from __future__ import annotations

from typing import Optional

START_EQUITY = 5000.0
OWN_EXPO, OWN_MARGIN, OWN_LIQ = 4.0, 0.20, 1 / 20 - 0.005      # research/search/search.py
DAY_MS = 86_400_000
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}


def run_account(trades: list[dict], start_equity: float = START_EQUITY, expo: float = OWN_EXPO,
                margin: float = OWN_MARGIN, liq: float = OWN_LIQ) -> list[dict]:
    """One result per trade, in entry order. Each trade dict needs trade_id, coin, entry_ms, exit_ms (None while open),
    net (a fraction at 1x, None while open) and mae (negative fraction, None while open).
    Returns dicts {trade_id, taken, why, liquidated, ret, multiple, equity}: ``ret`` is that trade's effect on the
    account (equity after / equity before - 1) and ``equity`` the account after it; both None when not taken or open."""
    order = sorted(trades, key=lambda t: (int(t["entry_ms"]), str(t["coin"]), str(t["trade_id"])))
    mult, last_exit, blocked = 1.0, None, False
    out = []
    for t in order:
        res = {"trade_id": t["trade_id"], "taken": False, "why": "", "liquidated": False, "ret": None,
               "multiple": None, "equity": None}
        if blocked or (last_exit is not None and int(t["entry_ms"]) < last_exit):
            res["why"] = "busy"                                   # the account already holds a position
            out.append(res)
            continue
        res["taken"] = True
        if t.get("exit_ms") is None or t.get("net") is None:
            blocked = True                                        # open: nothing after it can be taken yet
            res["why"] = "open"
            out.append(res)
            continue
        liquidated = -float(t["mae"]) >= liq
        before = mult
        mult *= 1 - margin if liquidated else 1 + max(expo * float(t["net"]), -margin)
        last_exit = int(t["exit_ms"])
        res.update(liquidated=liquidated, ret=mult / before - 1.0, multiple=mult, equity=start_equity * mult)
        out.append(res)
    return out


def day_start(ms: int) -> int:
    return (int(ms) // DAY_MS) * DAY_MS


def daily_equity(trades: list[dict], results: list[dict], start_ms: int, asof_ms: int,
                 start_equity: float = START_EQUITY) -> list[dict]:
    """Equity at the end of each UTC day from the start day to the day of ``asof_ms`` (the last row is as of ``asof_ms``:
    the time up to which every bar has been processed). A taken trade counts from the end of its exit bar.
    Rows: {day_ms, equity, ret_pct, taken, liquidated, asof_ms}; ``taken`` / ``liquidated`` are cumulative counts."""
    if asof_ms <= start_ms:
        return []
    by_id = {t["trade_id"]: t for t in trades}
    done = []                                                     # (settled_ms, equity, liquidated), in account order
    for r in results:
        if r["taken"] and r["equity"] is not None:
            t = by_id[r["trade_id"]]
            done.append((int(t["exit_ms"]) + TF_MS[t["tf"]], r["equity"], r["liquidated"]))
    done.sort(key=lambda x: x[0])
    rows, k, eq, taken, liqs = [], 0, start_equity, 0, 0
    d = day_start(start_ms)
    last_day = day_start(asof_ms - 1)
    while d <= last_day:
        edge = min(d + DAY_MS, int(asof_ms))
        while k < len(done) and done[k][0] <= edge:
            eq, taken, liqs = done[k][1], taken + 1, liqs + int(done[k][2])
            k += 1
        rows.append({"day_ms": d, "equity": eq, "ret_pct": 100.0 * (eq / start_equity - 1.0), "taken": taken,
                     "liquidated": liqs, "asof_ms": edge})
        d += DAY_MS
    return rows


def frontier_ms(series: list[dict], tf: Optional[str] = None) -> Optional[int]:
    """The time up to which every recording or erroring series (of one timeframe, or all) has been processed: the earliest
    close of the last processed bar. None when no series has processed a bar yet."""
    ends = [int(s["last_bar_ms"]) + TF_MS[s["tf"]] for s in series
            if s["last_bar_ms"] is not None and s["status"] in ("recording", "error") and (tf is None or s["tf"] == tf)]
    return min(ends) if ends else None
