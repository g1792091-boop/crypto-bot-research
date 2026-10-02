"""Where the paper accounts make or lose money: by coin, by weekday/weekend x session, by time windows and by
volatility at entry. Descriptive only (cells under ``min_n`` trades are marked, nothing is concluded from them);
read-only on paper3.db; no trading code reads it.

- by coin: the 180 strategy accounts against the 15 coin-flip accounts on the same coin, and the best strategies
  of each coin (at least ``min_top`` trades there);
- sessions: paperbot/sessions.py (entry time in Korea time: asia 09-16, europe 16-22, us 22-05, dawn 05-09;
  weekend = Sat/Sun KST; windows: funding +-10 min, US open +-60 min, 08:30 New York +-30 min);
- volatility spike: the entry signal's ATR as a share of its price (signal_log), against the same coin and
  timeframe's signals of the 30 days before: at or above the 90th percentile = "spike" (needs 50 earlier signals).
"""

from __future__ import annotations

import bisect
import json
import sqlite3
from dataclasses import fields
from typing import Optional

from .models import TradeRecord
from .sessions import session_report, time_features

SPIKE_PCT = 0.90
SPIKE_LOOKBACK_MS = 30 * 86_400_000
SPIKE_MIN_SAMPLES = 50
_FIELDS = {f.name for f in fields(TradeRecord)}


def _cell(rows: list[dict], min_n: int) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0, "status": f"insufficient (n<{min_n})"}
    return {"n": n, "win_rate": round(sum(r["pnl"] > 0 for r in rows) / n, 4),
            "mean_roe": round(sum(r["roe"] for r in rows) / n, 4), "pnl": round(sum(r["pnl"] for r in rows), 2),
            "status": "ok" if n >= min_n else f"insufficient (n<{min_n})"}


def load_trades(conn: sqlite3.Connection, since_ms: Optional[int] = None) -> list[dict]:
    """Closed trades of the original accounts (kind strategy or random) with their account and kind."""
    q = ("SELECT t.account_id, a.kind, t.symbol, t.entry_time, t.pnl, t.roe, t.data FROM trades t "
         "JOIN accounts a ON a.account_id = t.account_id WHERE a.kind IN ('strategy', 'random')")
    args: tuple = ()
    if since_ms is not None:
        q += " AND t.entry_time >= ?"
        args = (since_ms,)
    out = []
    for aid, kind, sym, et, pnl, roe, data in conn.execute(q, args):
        try:
            d = json.loads(data)
        except (TypeError, ValueError):
            d = {}
        out.append({"account_id": aid, "kind": kind, "symbol": sym, "entry_time": et, "pnl": pnl, "roe": roe,
                    "strategy": aid.split("@")[0], "timeframe": d.get("timeframe") or aid.split("@")[-1],
                    "signal_ts": d.get("signal_ts"), "data": d})
    return out


def _atr_share(conn: sqlite3.Connection) -> dict:
    """{(symbol, timeframe): ([bar_close...], [atr/price...])} from signal_log, sorted by time."""
    out: dict = {}
    for sym, tf, ts, atr, px in conn.execute(
            "SELECT symbol, timeframe, bar_close, atr, ref_price FROM signal_log "
            "WHERE atr > 0 AND ref_price > 0 ORDER BY bar_close"):
        ts_list, v = out.setdefault((sym, tf), ([], []))
        ts_list.append(int(ts))
        v.append(atr / px)
    return out


def vol_tag(series: dict, sym: str, tf: str, ts: Optional[int]) -> Optional[bool]:
    """True = spike, False = not, None = unknown (no signal row or too few earlier signals)."""
    s = series.get((sym, tf))
    if not s or ts is None:
        return None
    t, v = s
    bc = int(ts) + 1                      # a trade's signal_ts is its bar close - 1 (sigservice: ts=boundary - 1)
    i = bisect.bisect_left(t, bc)
    if i >= len(t) or t[i] != bc:
        return None
    lo = bisect.bisect_left(t, bc - SPIKE_LOOKBACK_MS)
    hist = sorted(v[lo:i])
    if len(hist) < SPIKE_MIN_SAMPLES:
        return None
    return v[i] >= hist[min(len(hist) - 1, int(SPIKE_PCT * len(hist)))]


def report(conn: sqlite3.Connection, since_ms: Optional[int] = None, min_n: int = 30, min_top: int = 10,
           top: int = 5) -> dict:
    rows = load_trades(conn, since_ms)
    strat = [r for r in rows if r["kind"] == "strategy"]
    coins = sorted({r["symbol"] for r in rows})
    by_coin = {}
    for sym in coins:
        s = [r for r in strat if r["symbol"] == sym]
        per: dict[str, list] = {}
        for r in s:
            per.setdefault(r["strategy"] + "@" + r["timeframe"], []).append(r)
        best = sorted(((k, _cell(v, min_n)) for k, v in per.items() if len(v) >= min_top),
                      key=lambda kv: kv[1]["pnl"], reverse=True)[:top]
        by_coin[sym] = {"strategies": _cell(s, min_n),
                        "coin_flips": _cell([r for r in rows if r["kind"] == "random" and r["symbol"] == sym], min_n),
                        "best": [{"account": k, **c} for k, c in best]}
    recs = [TradeRecord(**{k: v for k, v in r["data"].items() if k in _FIELDS}) for r in strat
            if _FIELDS <= set(r["data"])]
    sess = session_report(recs, min_n) if recs else None
    series = _atr_share(conn)
    tags = [(r, vol_tag(series, r["symbol"], r["timeframe"], r["signal_ts"])) for r in strat]
    vol = {"spike": _cell([r for r, v in tags if v is True], min_n),
           "normal": _cell([r for r, v in tags if v is False], min_n),
           "unknown": sum(v is None for _r, v in tags),
           "rule": f"entry ATR/price >= {int(SPIKE_PCT * 100)}th percentile of the coin+timeframe's signals of the "
                   f"previous 30 days (needs {SPIKE_MIN_SAMPLES})"}
    return {"trades": len(strat), "min_n": min_n, "by_coin": by_coin,
            "sessions": None if sess is None else {k: sess[k] for k in ("primary", "weekday", "windows")},
            "volatility": vol,
            "note": "descriptive only: cells under min_n are not conclusions; nothing here changes an account"}


def brief(rep: dict) -> dict:
    """The compact part for the agents' packet."""
    if not rep:
        return {}
    sess = rep.get("sessions") or {}
    return {"trades": rep["trades"], "min_n": rep["min_n"],
            "by_coin": {s: {"strategies": v["strategies"], "coin_flips": v["coin_flips"],
                            "best": [{"account": b["account"], "n": b["n"], "pnl": b["pnl"]} for b in v["best"][:3]]}
                        for s, v in rep["by_coin"].items()},
            "sessions": [{k: c.get(k) for k in ("day", "session", "n", "win_rate", "pnl", "status")}
                         for c in sess.get("primary", [])],
            "windows": [{"window": w["window"], "inside_n": w["inside"]["n"], "inside_pnl": w["inside"].get("pnl"),
                         "outside_n": w["outside"]["n"], "outside_pnl": w["outside"].get("pnl")}
                        for w in sess.get("windows", [])],
            "volatility": rep["volatility"], "note": rep["note"]}


def entry_tags(ts_ms: int) -> dict:
    """Weekday/weekend, session and windows of one entry time (for a card or a row)."""
    return time_features(ts_ms)
