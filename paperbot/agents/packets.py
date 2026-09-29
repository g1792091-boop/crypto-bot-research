"""Data packets the agents read. Built by code from the ledger only.

Agents never query anything themselves: every number they may cite is in
their packet, and every claim must point at the packet path it came from.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Optional, Sequence

from ..analyze import analyze
from ..config import Settings
from ..ledger import SCHEMA, BarStore, load_trades
from ..metrics import standard_metrics
from ..models import TradeRecord
from ..sessions import kst

DAY_MS = 86_400_000
BOOKS = ("owner", "recommended")


def _trade_row(t: TradeRecord, tag: dict) -> dict:
    return {
        "symbol": t.symbol, "strategy": t.strategy_id, "tf": t.timeframe,
        "side": "LONG" if t.side > 0 else "SHORT", "tier": t.tier, "leverage": t.leverage,
        "entry_kst": kst(t.entry_time), "exit_kst": kst(t.exit_time),
        "exit_reason": t.exit_reason, "pnl": round(t.pnl, 4), "roe": round(t.roe, 4),
        "net_r": None if tag["net_r"] is None else round(tag["net_r"], 3),
        "mfe_r": None if tag["mfe_r"] is None else round(tag["mfe_r"], 3),
        "class": tag["class"], "primary_cause": tag["primary"],
        "secondary": tag["secondary"], "entry_tags": tag["pre"], "outcome_tags": tag["post"],
        "regime": t.context.get("regime"), "htf_regime": t.context.get("htf_regime"),
    }


def _bars_near_trades(store: BarStore, trades: Sequence[TradeRecord]) -> dict:
    """Only the 1m bars the tagger and what-if lab can use: from each entry
    to 7 days later (what-if cap) or 21 minutes after the exit, whichever
    is later. Overlapping windows are merged."""
    out: dict = {}
    by_sym: dict[str, list[tuple[int, int]]] = {}
    for t in trades:
        end = max(t.entry_time + 10_082 * 60_000, t.exit_time + 21 * 60_000)
        by_sym.setdefault(t.symbol, []).append((t.entry_time, end))
    for sym, spans in by_sym.items():
        spans.sort()
        merged = [list(spans[0])]
        for a, b in spans[1:]:
            if a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        bars = []
        for a, b in merged:
            bars.extend(store.load(sym, a, b))
        out[sym] = bars
    return out


def _equity(conn: sqlite3.Connection, book: str) -> dict:
    row = conn.execute(
        "SELECT ts, equity, drawdown FROM equity WHERE run_id LIKE ? ORDER BY ts DESC LIMIT 1",
        (f"%-{book}",)).fetchone()
    mdd = conn.execute("SELECT MAX(drawdown) FROM equity WHERE run_id LIKE ?",
                       (f"%-{book}",)).fetchone()[0]
    if not row:
        return {"available": False}
    return {"available": True, "as_of_kst": kst(row[0]), "equity": row[1],
            "drawdown": row[2], "max_drawdown": mdd}


def _ops(conn: sqlite3.Connection, start: int, end: int, symbols: Sequence[str]) -> dict:
    sig = conn.execute(
        "SELECT run_id, status, reason, COUNT(*) FROM signals WHERE step_ts >= ? AND step_ts < ? "
        "GROUP BY run_id, status, reason", (start, end)).fetchall()
    signals = [{"run": r[0], "status": r[1], "reason": r[2], "count": r[3]} for r in sig]
    alerts = conn.execute("SELECT ts, level, text FROM alerts WHERE ts >= ? AND ts < ? ORDER BY ts",
                          (start, end)).fetchall()
    levels = Counter(a[1] for a in alerts)
    bars = {}
    minutes = (end - start) // 60_000
    for s in symbols:
        n = conn.execute("SELECT COUNT(*) FROM bars1m WHERE symbol = ? AND open_time >= ? "
                         "AND open_time < ?", (s, start, end)).fetchone()[0]
        bars[s] = {"recorded": n, "expected": minutes, "missing": max(0, minutes - n)}
    return {
        "signals": signals,
        "alerts": {"by_level": dict(levels), "count": len(alerts),
                   "last": [{"kst": kst(a[0]), "level": a[1], "text": a[2][:300]}
                            for a in alerts[-30:]]},
        "bars_1m": bars,
    }


def _compact_whatif(w: dict) -> dict:
    keep = ("policy", "group", "n", "win_rate", "mean_ret", "compounded", "liquidations",
            "over_cap", "paired_n", "verdict", "p_holm")
    pols = {}
    for p in w["policies"]:
        row = {k: p.get(k) for k in keep if k in p and k != "policy"}
        d = p.get("delta")
        if d:
            row["delta_mean"] = d["mean"]
            row["delta_ci"] = [d["lo"], d["hi"]]
        pols[p["policy"]] = row
    return {"policies": pols, "reproduction_ok": w["reproduction"]["ok"],
            "reproduction_mismatches": len(w["reproduction"]["mismatches"]),
            "skipped": w["skipped"], "method": w["method"]}


def evening_packet(ledger: str, now_ms: int, settings: Optional[Settings] = None,
                   books: Sequence[str] = BOOKS, min_n: int = 30, boot: int = 1000,
                   window_ms: int = DAY_MS) -> dict:
    """Last ``window_ms`` (default 24h) plus cumulative results per book."""
    s = settings or Settings()
    start = now_ms - window_ms
    conn = sqlite3.connect(ledger)
    conn.executescript(SCHEMA)
    store = BarStore(ledger)
    out: dict = {
        "meta": {
            "pipeline": "evening", "generated_kst": kst(now_ms),
            "window_kst": [kst(start), kst(now_ms)], "min_n": min_n,
            "rules": {
                "both": "same signals; stop price comes from the strategy; one position at a "
                        "time across all symbols (later signals are SKIPPED while in a position); "
                        "isolated margin; fills at next 1m open with slippage; stop first if a "
                        "bar touches stop and target",
                "owner": {
                    "tiers": [f"{t.name}: margin {t.margin_frac:.0%} of equity x "
                              f"{'/'.join(str(x) for x in t.leverages)}x" for t in s.tiers],
                    "max_loss_per_trade": f"{s.max_loss_frac:.0%} of ACCOUNT EQUITY at the stop, "
                                          f"fees and slippage included (not of margin); a "
                                          f"signal is downgraded a tier or rejected if over",
                    "take_profit": f"ROE {s.default_tp_roe:.0%} on margin unless the strategy "
                                   f"sets its own ROE target",
                    "drawdown": f"warn at {', '.join(f'-{x:.0%}' for x in s.dd_warn_levels)}, "
                                f"halt at -{s.dd_halt:.0%}",
                    "daily_loss_stop": "none (owners' decision)",
                },
                "recommended": {
                    "size": "risk 1% of equity per trade; leverage derived, at most 10x "
                            "(tier label is kept but leverage differs from the owner book)",
                    "take_profit": "strategy's own target price, else 2R",
                    "daily_loss_stop": "-3% from the UTC-day start equity (00:00 UTC = 09:00 KST)",
                    "consecutive_losses": "after 5 losses in a row: 24h pause, then the count "
                                          "restarts from 0 (so longer loss runs across a pause "
                                          "are expected)",
                    "blocked_signals": "appear in ops.signals as REJECTED with reason 'guard: ...'",
                },
            },
            "paths": "evidence paths are dotted; dict keys by name "
                     "(books.owner.whatif.policies.TP_ROE30.verdict), list items by 0-based index "
                     "(books.owner.trades_today.0.primary_cause)",
            "note": "paper trading; no real orders. Past results describe, they do not prove.",
        },
        "books": {},
    }
    for book in books:
        all_t = load_trades(ledger, book=book)
        today = [t for t in all_t if start <= t.exit_time < now_ms]
        bars = _bars_near_trades(store, all_t)
        rep = analyze(all_t, bars, s, min_n=min_n, boot=boot) if all_t else None
        tags_by_id = {}
        if rep:
            for t, tag in zip(all_t, rep["tags"]["per_trade"]):
                tags_by_id[id(t)] = tag
        out["books"][book] = {
            "today": standard_metrics(today),
            "cumulative": standard_metrics(all_t),
            "equity": _equity(conn, book),
            "trades_today": [_trade_row(t, tags_by_id[id(t)]) for t in today],
            "causes_cumulative": rep["tags"]["primary_counts"] if rep else {},
            "entry_tag_table": rep["tags"]["entry_tag_table"] if rep else [],
            "whatif": _compact_whatif(rep["whatif"]) if rep else None,
            "sessions": ({"primary": {f"{c['day']}_{c['session']}": {k: v for k, v in c.items()
                                                                     if k not in ("day", "session")}
                                      for c in rep["sessions"]["primary"]},
                          "windows": {x["window"]: {"inside": x["inside"], "outside": x["outside"]}
                                      for x in rep["sessions"]["windows"]}} if rep else None),
        }
    out["ops"] = _ops(conn, start, now_ms, s.symbols)
    conn.close()
    store.close()
    return out


def slice_for(packet: dict, keys: Sequence[str]) -> dict:
    """Sub-packet with only the named paths (dotted, '*' = every book)."""
    out: dict = {"meta": packet["meta"]}
    for key in keys:
        parts = key.split(".")
        if parts[0] == "books" and len(parts) >= 3:
            books = packet["books"] if parts[1] == "*" else {parts[1]: packet["books"][parts[1]]}
            for b, data in books.items():
                out.setdefault("books", {}).setdefault(b, {})[parts[2]] = data.get(parts[2])
        else:
            cur = packet
            for p in parts:
                cur = cur.get(p) if isinstance(cur, dict) else None
            node = out
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = cur
    return out
