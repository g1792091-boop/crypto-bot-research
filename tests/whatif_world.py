"""A synthetic daily3.db of nightly shadows for the 만약 실험실 (tests/test_dash_whatif_ds5y.py and the ana7b screenshot
harness), built from a synthetic paper3.db (tests/anasyn_world.py): for every closed trade of the 36's accounts, the
15m-4h coin flips and the DeepSeek accounts, one ``base`` row (its P&L on equity) and one row per shadow variant
(paperbot/obsshadows.py names) with a deterministic shift, a few unresolved rows and a few 'not entered' rows, keyed
like the real job (``<kind>|<account>|<symbol>|<bar close>``, day = the trade's exit UTC day). The real daily3.py
schema; one report row per day, written at the next day's 00:20 UTC as the timer does, so with ``until_ms`` only the
days whose nightly check has already run by then get rows (today's trades have no shadow yet). Deterministic (``seed``).

    from whatif_world import build_daily
    info = build_daily(paper_db, daily_db)          # {"rows", "trades", "days"}
"""
from __future__ import annotations

import datetime as dt
import json
import random
import sqlite3

from paperbot.daily3 import SCHEMA

VARIANTS = ("lock15", "lock20", "lock30", "timestop", "lev10", "lev20", "lev30", "lev40", "lev50", "stopw1.5",
            "stopw2.5", "stopw3", "tp1R", "tp1.5R", "tp2R", "tp3R", "ladder_cap2R", "lev20m20", "lev30m30",
            "lev40m40", "lev50m50")
SHIFT = {"lock15": 0.002, "lock20": 0.003, "lock30": -0.001, "timestop": -0.002, "stopw1.5": -0.003, "stopw2.5": 0.001,
         "stopw3": 0.002, "tp1R": -0.001, "tp1.5R": 0.0, "tp2R": 0.001, "tp3R": 0.002, "ladder_cap2R": 0.0005}
SCALE = {"lev10": 0.4, "lev20": 0.6, "lev30": 0.9, "lev40": 1.2, "lev50": 1.4, "lev20m20": 0.6, "lev30m30": 0.9,
         "lev40m40": 1.2, "lev50m50": 1.7}


def _day(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def _report_ts(day: str) -> int:
    """When the nightly check of ``day`` (UTC) runs: the next day 00:20 UTC (deploy/paperbot-daily3.timer)."""
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp() * 1000) + 86_400_000 + 20 * 60_000


def build_daily(paper_db: str, daily_db: str, seed: int = 5, open_share: float = 0.03, until_ms: int | None = None) -> dict:
    """Shadows for every closed trade (exit before ``until_ms`` when given) of kinds strategy / random (15m-4h) / ds200."""
    rng = random.Random(seed)
    c = sqlite3.connect(paper_db)
    got = c.execute("SELECT t.account_id, t.symbol, t.exit_time, t.exit_reason, t.data, a.kind, a.timeframe FROM trades t "
                    "JOIN accounts a ON a.account_id = t.account_id ORDER BY t.id").fetchall()
    c.close()
    d = sqlite3.connect(daily_db)
    d.executescript(SCHEMA)
    rows, days, n = [], set(), 0
    for aid, sym, exit_t, reason, data, kind, tf in got:
        if kind not in ("strategy", "random", "ds200") or tf == "5m" or (until_ms is not None and exit_t >= until_ms):
            continue
        if until_ms is not None and _report_ts(_day(int(exit_t))) > until_ms:
            continue                                   # that day's nightly check has not run yet
        t = json.loads(data)
        before = float(t["equity_after"]) - float(t["pnl"])
        if before <= 0:
            continue
        pe = float(t["pnl"]) / before
        bc = int(t["signal_ts"]) + 1
        day = _day(int(exit_t))
        days.add(day)
        n += 1
        rows.append((f"base|{aid}|{sym}|{bc}", day, "base", aid, sym, tf, int(t["side"]), 1, float(t["roe"]), reason, 1,
                     json.dumps({"pnl_equity": pe, "actual_pnl_equity": pe})))
        for v in VARIANTS:
            key = f"{v}|{aid}|{sym}|{bc}"
            if rng.random() < open_share:
                rows.append((key, day, v, aid, sym, tf, int(t["side"]), 1, None, None, 0, "{}"))
                continue
            if v == "lev50m50" and rng.random() < 0.25:                      # sizing refused: not entered
                rows.append((key, day, v, aid, sym, tf, int(t["side"]), 0, None, None, 1, "{}"))
                continue
            pv = pe * SCALE[v] if v in SCALE else pe + SHIFT[v] + rng.gauss(0, 0.002)
            r = "TP" if v.startswith("tp") and pv > 0 else ("LIQ" if v in ("lev50", "lev50m50") and rng.random() < 0.02
                                                              else reason)
            rows.append((key, day, v, aid, sym, tf, int(t["side"]), 1, pv / 0.3, r, 1, json.dumps({"pnl_equity": pv})))
    d.executemany("INSERT INTO shadows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    for day in sorted(days):
        d.execute("INSERT INTO reports VALUES (?, ?, ?)", (day, _report_ts(day), json.dumps({"parity": {"accounts": 0}})))
    d.commit()
    d.close()
    return {"rows": len(rows), "trades": n, "days": sorted(days)}
