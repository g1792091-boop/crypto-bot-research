"""신호 레이더: how many of each of the 36's entry conditions are on, on the last closed bar (read-only).

    GET /api/v4/radar?tf=1h&symbol=BTCUSDT          every one of the 36 with a chart view, on one coin and timeframe
    GET /api/v4/radar/strategy/<name>               one strategy: the 6 coins x 15m/30m/1h/4h matrix of on / of

The conditions are exactly the ones /api/strategy/<name> shows under '지금 조건' (paperbot/strategy_views.render on
the same closed bars, from the same bar fetcher, same window: dash/app.view_bars): the code's own check of its rules on
the bar that just closed. Not a forecast: 2/3 on does not mean the third comes next. ``fired`` is a real signal in
paper3.db signal_log on that bar (read-only), so a row says '신호!' only when the bot really logged one.

Cost (the server shares Binance's IP weight with the bot): one bar fetch per (timeframe, coin) per closed bar, shared
by all 36 (the fetcher's own 60 s cache sits under it); each strategy's conditions are computed at most once per bar
and kept until the next bar closes. Work runs in FastAPI's thread pool (plain ``def`` routes), one computation at a
time (``_WORK``); the matrix route fills at most ``MAX_NEW_CELLS`` new (timeframe, coin) cells per call and says how
many are still ``pending`` (the page asks again a few seconds later), so a first visit never bursts 24 fetches at once.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
import urllib.parse
from typing import Optional

from fastapi import HTTPException

TFS = ("15m", "30m", "1h", "4h")
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")      # the six traded coins
RETRY_S = 20.0            # after a bar closes, a fetch that still ends on the old bar is tried again this much later
MAX_NEW_CELLS = 3         # the matrix route: new (timeframe, coin) cells computed per call
SMT = "F14_SMT"           # compares with BTC's bars of the same timeframe (as /api/strategy does)


def names36() -> list:
    """The 36 in roster order that have a chart view (strategy_views.has_view)."""
    from ...agents.roster3 import STRATEGY_KO
    from ...strategy_views import has_view
    out = []
    for n in STRATEGY_KO:
        try:
            if has_view(n):
                out.append(n)
        except Exception:  # noqa: BLE001  (a view that fails to load: left out, never a 500)
            continue
    return out


def side_of(conds) -> dict:
    """[{name, on}] -> {on, of, names}."""
    names = [{"name": str(c.get("name")), "on": bool(c.get("on"))} for c in (conds or [])]
    return {"on": sum(1 for c in names if c["on"]), "of": len(names), "names": names}


def left_of(row: dict) -> Optional[int]:
    """How many conditions are still off on the closer side (None when neither side has conditions)."""
    best = None
    for side in ("long", "short"):
        s = row.get(side) or {}
        if s.get("of"):
            k = int(s["of"]) - int(s.get("on") or 0)
            best = k if best is None else min(best, k)
    return best


def closeness(row: dict) -> tuple:
    """Sort key, closest to firing first: a logged signal, then fewest conditions left, then the larger share on."""
    left = left_of(row)
    share = max(((row.get(s) or {}).get("on", 0) / (row.get(s) or {}).get("of", 1)) if (row.get(s) or {}).get("of") else 0
                for s in ("long", "short"))
    return (0 if row.get("fired") else 1, 99 if left is None else left, -share)


class Radar:
    def __init__(self, frames, db: Optional[str], now=time.time):
        self.frames = frames
        self.db = db
        self.now = now
        self.cells: dict = {}             # (tf, sym) -> {"ts", "bar_close", "df", "btc", "rows": {name: row}, "fired"}
        self.lock = threading.Lock()      # guards self.cells
        self.work = threading.Lock()      # one fetch / computation at a time
        self.retry: dict = {}             # (tf, sym) -> time before which a stale fetch is not tried again
        self.names: Optional[list] = None
        self.ko: dict = {}

    # ---------------------------------------------------------------- pieces
    def roster(self) -> list:
        if self.names is None:
            from ...agents.roster3 import STRATEGY_KO
            self.ko = dict(STRATEGY_KO)
            self.names = names36()
        return self.names

    def fresh(self, cell: Optional[dict]) -> bool:
        """True while no newer bar can have closed since this cell's bar (or a retry is pending)."""
        if cell is None:
            return False
        return self.now() * 1000 < cell["bar_close"] + cell["span"]

    def fired_on(self, tf: str, sym: str, open_ms: int, close_ms: int) -> dict:
        """{strategy: [sides]} of the signals logged for this coin and timeframe on that bar (read-only)."""
        if not self.db or not os.path.exists(self.db):
            return {}
        try:
            c = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(self.db))}?mode=ro", uri=True, timeout=5)
            try:
                rows = c.execute("SELECT strategy, side FROM signal_log WHERE timeframe = ? AND symbol = ? "
                                 "AND bar_close > ? AND bar_close <= ?", (tf, sym, open_ms, close_ms)).fetchall()
            finally:
                c.close()
        except sqlite3.Error:
            return {}
        out: dict = {}
        for s, side in rows:
            out.setdefault(s, set()).add(int(side))
        return {k: sorted(v) for k, v in out.items()}

    def cell(self, tf: str, sym: str) -> Optional[dict]:
        """The (tf, sym) cell with this bar's frames, fetched when a newer bar may have closed. None: no price data."""
        key = (tf, sym)
        with self.lock:
            c = self.cells.get(key)
        if self.fresh(c) or (c is not None and self.now() < self.retry.get(key, 0)):
            return c
        from ..app import view_bars
        n = view_bars(tf)
        try:
            df = self.frames(sym, tf, n)
        except Exception:  # noqa: BLE001  (Binance unreachable: keep what we have)
            self.retry[key] = self.now() + RETRY_S
            return c
        if df is None or len(df) < 50:
            self.retry[key] = self.now() + RETRY_S
            return c
        ts = str(df["ts"].iloc[-1])
        if c is not None and c["ts"] == ts:            # the fetcher still ends on the same bar: try again a bit later
            self.retry[key] = self.now() + RETRY_S
            return c
        import pandas as pd
        t = pd.to_datetime(df["ts"], utc=True)
        span = int((t.iloc[-1] - t.iloc[-2]).total_seconds() * 1000) if len(t) > 1 else TF_MS[tf]
        open_ms = int(t.iloc[-1].value // 10**6)
        new = {"ts": ts, "df": df, "btc": None, "span": span, "open": open_ms, "bar_close": open_ms + span,
               "rows": {}, "fired": self.fired_on(tf, sym, open_ms, open_ms + span), "at": int(self.now() * 1000)}
        with self.lock:
            self.cells[key] = new
        return new

    def row(self, c: dict, name: str, tf: str, sym: str) -> dict:
        """One strategy's conditions on the cell's bar, computed once per bar (as /api/strategy renders them)."""
        hit = c["rows"].get(name)
        if hit is not None:
            return hit
        from ...strategy_views import render
        btc = None
        if name == SMT and sym != "BTCUSDT":
            if c["btc"] is None:
                b = self.cell(tf, "BTCUSDT")
                c["btc"] = b["df"] if b is not None else False
            btc = c["btc"] if c["btc"] is not False else None
        try:
            v = render(name, c["df"], tf, symbol=sym, btc=btc)
            cond = v.get("conditions") or {}
            r = {"long": side_of(cond.get("long")), "short": side_of(cond.get("short"))}
        except Exception as exc:  # noqa: BLE001  (one view failing never hides the other 35)
            r = {"long": side_of([]), "short": side_of([]), "error": type(exc).__name__}
        sides = c["fired"].get(name) or []
        r["fired"] = {"long": 1 in sides, "short": -1 in sides} if sides else None
        r["left"] = left_of(r)
        c["rows"][name] = r
        return r

    # ---------------------------------------------------------------- routes
    def radar(self, tf: str, sym: str) -> dict:
        names = self.roster()
        with self.work:
            c = self.cell(tf, sym)
            if c is None:
                return {"tf": tf, "symbol": sym, "ready": False, "rows": [], "bar_close": None,
                        "next_close": None, "why": "가격 자료를 아직 받지 못했습니다"}
            rows = [{"strategy": n, "ko": self.ko.get(n, n), **self.row(c, n, tf, sym)} for n in names]
        rows.sort(key=closeness)
        return {"tf": tf, "symbol": sym, "ready": True, "bar_close": c["bar_close"], "next_close": c["bar_close"] + c["span"],
                "computed_at": c["at"], "n": len(rows), "rows": rows}

    def matrix(self, name: str) -> dict:
        if name not in self.roster():
            raise HTTPException(404, "레이더는 기존 36 매매법만 봅니다")
        cells, pending, new = [], 0, 0
        for tf in TFS:
            for sym in COINS:
                with self.lock:
                    c = self.cells.get((tf, sym))
                if not (self.fresh(c) or (c is not None and self.now() < self.retry.get((tf, sym), 0))):
                    if new < MAX_NEW_CELLS:
                        new += 1
                        with self.work:
                            c = self.cell(tf, sym)
                    else:
                        pending += 1          # the page asks again; a stale cell (older bar) still shows meanwhile
                if c is None:
                    cells.append({"tf": tf, "symbol": sym, "ready": False})
                    continue
                with self.work:
                    r = self.row(c, name, tf, sym)
                cells.append({"tf": tf, "symbol": sym, "ready": True, "bar_close": c["bar_close"],
                              "long": {"on": r["long"]["on"], "of": r["long"]["of"]},
                              "short": {"on": r["short"]["on"], "of": r["short"]["of"]},
                              "left": r["left"], "fired": r["fired"]})
        return {"strategy": name, "ko": self.ko.get(name, name), "tfs": list(TFS), "coins": list(COINS),
                "cells": cells, "pending": pending}


def register(app, ctx):
    from ..app import fetch_frame
    frames = getattr(ctx, "frames", None) or fetch_frame
    rd = Radar(frames, getattr(ctx, "db", None))

    @app.get("/api/v4/radar")
    def get_radar(tf: str = "1h", symbol: str = "BTCUSDT"):
        if tf not in TFS:
            raise HTTPException(400, "unknown timeframe")
        if symbol not in COINS:
            raise HTTPException(400, "unknown symbol")
        return rd.radar(tf, symbol)

    @app.get("/api/v4/radar/strategy/{name}")
    def get_radar_strategy(name: str):
        return rd.matrix(name)

    return rd
