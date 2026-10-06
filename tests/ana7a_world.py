"""A synthetic world for the ana7a analysis views (tests/test_dash_ana7a.py and the screenshot harness): the ana-syn
paper3.db (tests/anasyn_world.py: the v4 run shape, ``days`` of closed trades) plus, next to it,

- ``liq.db``          (paperbot/liqstream.SCHEMA) forced orders on the six coins from ``liq_from`` on: a quiet
                      background and bursts of large orders, a share of them placed a few minutes before real entries;
- ``ghcoin/calls.jsonl`` GH Coin calls (open + mirror, then close) every few hours per coin from ``gh_from`` on;
- ``market.db``       (paperbot/archive.SCHEMA) 5-minute bars of the six coins from ``market_days`` before the run start
                      to now (a random walk with volume) and the 8-hourly funding settlements.

Deterministic (``seed``). Nothing here is real market data.

    from ana7a_world import build_all
    info = build_all("/tmp/x", days=30)        # {"db", "start", "now", ...}
"""
from __future__ import annotations

import json
import math
import os
import random
import sqlite3

import numpy as np

from anasyn_world import BASE, DAY, HOUR, MIN, SYMS, build

FIVE = 5 * MIN


def write_market(path: str, lo: int, hi: int, seed: int = 5) -> dict:
    """market.db with kline5m [lo, hi) and funding settlements; returns {symbol: (open_time array, close array)}."""
    from paperbot.archive import SCHEMA
    rng = np.random.default_rng(seed)
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    lo = lo // FIVE * FIVE
    t = np.arange(lo, hi - FIVE + 1, FIVE, dtype=np.int64)
    out = {}
    for k, sym in enumerate(SYMS):
        n = len(t)
        drift = (k - 2.5) * 2e-6
        ret = rng.normal(drift, 0.0018, n)
        close = BASE[sym] * np.exp(np.cumsum(ret))
        open_ = np.r_[BASE[sym], close[:-1]]
        wig = np.abs(rng.normal(0, 0.0009, n))
        high = np.maximum(open_, close) * (1 + wig)
        low = np.minimum(open_, close) * (1 - wig)
        vol = rng.lognormal(3.0, 0.5, n) * (1 + 3 * (np.abs(ret) > 0.004))
        c.executemany("INSERT INTO kline5m VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      [(sym, int(a), float(b), float(h_), float(l_), float(cl), float(v), float(v * cl), 100, float(v / 2),
                        int(a) + FIVE, "fixture") for a, b, h_, l_, cl, v in zip(t, open_, high, low, close, vol)])
        ft = np.arange((lo // (8 * HOUR) + 1) * 8 * HOUR, hi, 8 * HOUR, dtype=np.int64)
        rates = np.round(rng.choice([0.0001, 0.0001, 0.0001, 0.00005, -0.00003, 0.00022], len(ft)), 6)
        c.executemany("INSERT INTO funding VALUES (?,?,?,?,?)",
                      [(sym, int(a), float(r), None, int(a)) for a, r in zip(ft, rates)])
        out[sym] = (t, close)
    c.commit()
    c.close()
    return out


def write_liq(path: str, entries: list, lo: int, hi: int, seed: int = 9) -> int:
    """liq.db forced orders in [lo, hi): background minutes plus bursts; a third of the bursts sit 1-50 minutes before
    one of ``entries`` [(time, symbol)]. Returns the row count."""
    from paperbot.liqstream import SCHEMA
    rng = random.Random(seed)
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    rows = []

    def add(ts, sym, side, usd):
        px = BASE[sym]
        q = usd / px
        rows.append((ts, ts, sym, side, "LIMIT", "IOC", q, px, px, "FILLED", q, q, ts + 200))

    for sym in SYMS:
        t = lo
        while t < hi:
            t += int(rng.expovariate(1 / (4 * MIN)))
            if t < hi:
                add(t, sym, rng.choice(("BUY", "SELL")), rng.lognormvariate(8.5, 1.0))
        for _ in range(max(2, int((hi - lo) / DAY * 6))):
            b = rng.randrange(lo, hi)
            side = rng.choice(("BUY", "SELL"))
            for k in range(rng.randint(3, 8)):
                add(b + k * 900, sym, side, rng.lognormvariate(12.0, 0.6))
    for e, sym in entries:
        if lo <= e - 50 * MIN and e < hi and rng.random() < 0.33:
            b = e - rng.randint(1, 50) * MIN - rng.randrange(0, 50_000)
            side = rng.choice(("BUY", "SELL"))
            for k in range(rng.randint(3, 6)):
                add(b + k * 700, sym, side, rng.lognormvariate(12.3, 0.5))
    c.executemany("INSERT OR IGNORE INTO liq VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    c.execute("INSERT INTO conn_log VALUES (?,?,?)", (lo, "connected", "{}"))
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM liq").fetchone()[0]
    c.close()
    return int(n)


def write_ghcoin(folder: str, lo: int, hi: int, seed: int = 13) -> int:
    """ghcoin/calls.jsonl (+ board.json): a call per coin every 6-40 hours, each with its mirror, closed 1-20 hours later
    (or still open at ``hi``). Returns the number of calls."""
    rng = random.Random(seed)
    os.makedirs(folder, exist_ok=True)
    ev = []
    seq = 0
    for sym in SYMS:
        t = lo + rng.randrange(0, 2 * HOUR)
        while t < hi:
            t = t // FIVE * FIVE
            seq += 1
            side = rng.choice((1, -1))
            px = BASE[sym]
            d = px * 0.006
            cid = f"{sym}-{t}-{seq}"
            call = {"ev": "open", "id": cid, "sym": sym, "side": side, "entry": px, "sl": px - side * d,
                    "tp1": px + side * 1.5 * d, "t": t, "cost_r": 0.02}
            mir = {"ev": "open", "id": cid + "-m", "of": cid, "mirror": True, "sym": sym, "side": -side, "entry": px,
                   "sl": px + side * d, "tp1": px - side * 1.5 * d, "t": t, "cost_r": 0.02}
            ev += [call, mir]
            end = t + rng.randint(1, 20) * HOUR
            if end < hi:
                r = rng.choice((1.5, -1.0, 0.4))
                ev.append({**call, "ev": "close", "result": "win" if r > 1 else "loss", "r": r, "net_r": r - 0.02,
                           "end": end})
                ev.append({**mir, "ev": "close", "result": "loss" if r > 1 else "win", "r": -r, "net_r": -r - 0.02,
                           "end": end})
            t += rng.randint(6, 40) * HOUR
    ev.sort(key=lambda e: (e.get("end", e["t"]) if e["ev"] == "close" else e["t"]))
    with open(os.path.join(folder, "calls.jsonl"), "w", encoding="utf-8") as fh:
        for e in ev:
            fh.write(json.dumps(e) + "\n")
    with open(os.path.join(folder, "board.json"), "w", encoding="utf-8") as fh:
        json.dump({"ts": hi, "coins": {s: {"state": "wait", "side": 0} for s in SYMS}, "commit": "fixture"}, fh)
    return seq


def build_all(folder: str, days: int = 30, seed: int = 11, start: int | None = None, liq_from_h: float = 6.0,
              gh_from_h: float = -48.0, market_days: int = 45, now: int | None = None, hours: int = 20) -> dict:
    """paper3.db (anasyn_world.build, ``hours`` into its last day) + liq.db + ghcoin/ + market.db in ``folder``."""
    os.makedirs(folder, exist_ok=True)
    db = os.path.join(folder, "paper3.db")
    for name in ("paper3.db", "liq.db", "market.db"):
        for ext in ("", "-wal", "-shm"):
            p = os.path.join(folder, name + ext)
            if os.path.exists(p):
                os.remove(p)
    info = build(db, days=days, seed=seed, start=start, hours_into_last=hours)
    s0, now = info["start"], info["now"] if now is None else now
    c = sqlite3.connect(db)
    entries = [(int(e), str(sym)) for e, sym in c.execute("SELECT entry_time, symbol FROM trades")]
    c.close()
    write_market(os.path.join(folder, "market.db"), s0 - market_days * DAY, now + FIVE, seed=seed + 1)
    nliq = write_liq(os.path.join(folder, "liq.db"), entries, int(s0 + liq_from_h * HOUR), now, seed=seed + 2)
    ncalls = write_ghcoin(os.path.join(folder, "ghcoin"), int(s0 + gh_from_h * HOUR), now, seed=seed + 3)
    return {**info, "db": db, "liq_rows": nliq, "gh_calls": ncalls, "liq_from": int(s0 + liq_from_h * HOUR)}


def fake_frames(seed: int = 3):
    """A stand-in for dash/app.fetch_frame: closed bars of a random walk ending now (no network)."""
    import time

    import pandas as pd
    sec = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}

    def frames(symbol, interval, limit):
        step = sec[interval] * 1000
        end = int(time.time() * 1000) // step * step
        rng = np.random.default_rng(abs(hash((symbol, interval, seed))) % (2 ** 32))
        n = int(limit)
        close = BASE.get(symbol, 100.0) * np.exp(np.cumsum(rng.normal(0, 0.004 * math.sqrt(step / 900_000), n)))
        open_ = np.r_[close[0], close[:-1]]
        t = end - step * np.arange(n, 0, -1)
        return pd.DataFrame({"ts": pd.to_datetime(t, unit="ms", utc=True), "open": open_,
                             "high": np.maximum(open_, close) * 1.001, "low": np.minimum(open_, close) * 0.999,
                             "close": close, "volume": rng.lognormal(3, 0.5, n)})
    return frames
