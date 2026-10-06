"""Shared pieces of the ana7a analysis views (indranges, liqentry, holdcmp, ghagree): not a route module (it is not in
MODULES and has no ``register``).

- ``closed_trades``  the closed trades of one analysis group (dash/analysis.AN_GROUP_KINDS on its own timeframes,
                     dash/analysis.own_tfs) or of that group's coin flips, exited at or after the run start, as plain
                     dicts with every field the views read (from paper3.db ``trades.data``, the engine's TradeRecord).
- ``cell``           trades, win share (net P&L > 0) and mean net ROE of a list of trades.
- ``mirror_pnl``     the same trade the other way round (same entry and exit times and prices, same size), with the
                     fees paid again and the funding the other way; a loss is capped at the margin (isolated margin:
                     the position would have been liquidated there).
- ``strip``          an answer without money (DeepSeek, owners' D10 / D11): dash/analysis.no_money plus ``NO_MONEY``.

Read-only: connections come from dash/analysis.ro_connect (``mode=ro``).
"""
from __future__ import annotations

import json
import math
import sqlite3
from typing import Any, Optional

NO_MONEY = ("mean_roe", "roe", "mean_r", "r", "ret", "mirror_ret", "realized", "curve", "pnl_sum")
MIN_N = 10                     # a cell under this many trades carries small: true (표본 적음)
LABEL = "설명용, 판정 아님"


def r4(x: Any, n: int = 4) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, n) if math.isfinite(v) else None


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def scope(group: str, flips: bool = False) -> tuple[tuple, tuple]:
    """(kinds, timeframes) of a group (or of its coin flips: kind 'random' on the group's own timeframes)."""
    from ..analysis import AN_GROUP_KINDS, own_tfs
    return (("random",) if flips else AN_GROUP_KINDS[group]), own_tfs(group)


def closed_trades(c: sqlite3.Connection, kinds: tuple, tfs: tuple, since_ms: int,
                  until_ms: Optional[int] = None) -> list[dict]:
    """The closed trades of ``kinds`` on ``tfs`` exited in [since_ms, until_ms), oldest exit first."""
    q = ("SELECT t.account_id, a.kind, a.strategy, a.timeframe, t.symbol, t.entry_time, t.exit_time, t.exit_reason, "
         "t.leverage, t.pnl, t.roe, t.data FROM trades t JOIN accounts a ON a.account_id = t.account_id "
         f"WHERE a.kind IN ({','.join('?' * len(kinds))}) AND a.timeframe IN ({','.join('?' * len(tfs))}) "
         "AND t.exit_time >= ?")
    args: list = [*kinds, *tfs, int(since_ms)]
    if until_ms is not None:
        q += " AND t.exit_time < ?"
        args.append(int(until_ms))
    out = []
    for aid, kind, strat, tf, sym, entry, exit_, reason, lev, pnl, roe, data in c.execute(q + " ORDER BY t.exit_time, t.id",
                                                                                        args):
        try:
            d = json.loads(data) or {}
        except (TypeError, ValueError):
            d = {}
        if not isinstance(d, dict) or pnl is None:
            continue
        side = 1 if (_f(d.get("side")) or 0) > 0 else -1
        sig = _f(d.get("signal_ts"))
        out.append({"aid": aid, "kind": kind, "strategy": strat, "tf": tf or d.get("timeframe"),
                    "symbol": str(sym or d.get("symbol")), "side": side, "entry": int(entry), "exit": int(exit_),
                    "signal_ts": int(sig) if sig is not None else int(entry) - 1, "reason": str(reason or ""),
                    "lev": _f(lev) or _f(d.get("leverage")), "pnl": float(pnl), "roe": _f(roe),
                    "margin": _f(d.get("margin")), "qty": _f(d.get("qty")), "fees": _f(d.get("fees")) or 0.0,
                    "funding": _f(d.get("funding")) or 0.0, "entry_price": _f(d.get("entry_price")),
                    "exit_price": _f(d.get("exit_price")), "stop_initial": _f(d.get("stop_initial"))})
    return out


def cell(rows: list, min_n: int = MIN_N) -> dict:
    """{"n", "wr", "mean_roe", "small"} of a list of trades (net P&L > 0 = won)."""
    n = len(rows)
    if not n:
        return {"n": 0}
    roe = [r["roe"] for r in rows if r.get("roe") is not None]
    out = {"n": n, "wr": r4(sum(1 for r in rows if r["pnl"] > 0) / n, 4),
           "mean_roe": r4(sum(roe) / len(roe), 4) if roe else None}
    if n < min_n:
        out["small"] = True
    return out


def mirror_pnl(t: dict) -> Optional[float]:
    """Net P&L of the trade taken the other way at the same times and prices and the same size: the price move
    reversed, the fees paid again (both directions pay them), the funding the other way; never below -margin."""
    q, e, x, m = t.get("qty"), t.get("entry_price"), t.get("exit_price"), t.get("margin")
    if not q or not e or x is None:
        return None
    gross = -t["side"] * q * (x - e)
    if m is not None and gross < -m:
        return -m
    return gross - (t.get("fees") or 0.0) + (t.get("funding") or 0.0)


def strip(x: Any) -> Any:
    """``x`` without money: dash/analysis.no_money (pnl, equity, ...) and ``NO_MONEY`` (ROE, R, returns)."""
    from ..analysis import no_money
    x = no_money(x)
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if k not in NO_MONEY}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


def run_start_of(c: sqlite3.Connection) -> int:
    from ...agents.triggers import run_start
    return int(run_start(c) or 0)
