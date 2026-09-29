"""Signal recorder for the record-only cells (handover v2, case B).

No orders and no positions: for every record-only (②) cell and every
recorded coin it writes each signal to an append-only log, with what is
needed to evaluate it later on the fixed dates (2027-04-01, 2027-10-01).

Per run, for each coin:
1. Load all stored 5m bars from the coin's fixed anchor (the first stored
   bar; never moved, so results stay comparable day to day).
2. Build 15m..1d bars with ``sweep_lib.resample_ohlcv`` and drop the bar
   still forming (that function keeps it; a signal from it would use data
   that is not final yet).
3. ``sweep_lib.compute_signals`` for the cells of each timeframe, without
   extra frames, exactly as the backtest's gate runner called it.
   No signal inside the warm-up (``sweep_lib.warmup_bars``).
4. For each signal: ATR14 (the backtest's ``fg.atr``), the virtual entry at
   the next bar's open +-0.02%, the delay between signal bar close and that
   open, and (if the live runner recorded one) the best bid/ask right after
   the close.
5. Consistency check: every stored signal must come out again with the same
   side, and no signal may newly appear whose entry bar already existed at
   the previous run. Any difference is a mismatch and raises an alert.
The recorder never judges performance. Outcomes (4/16/64-bar moves and the
five exits) are recomputed from the stored bars on the fixed dates.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import uuid
import warnings
from typing import Callable, Iterable, Optional, Sequence

import numpy as np

from . import sweepsig
from .aggregate import TF_MS
from .archive import FIVE_MIN, MarketArchive
from .ledger import book_near, open_book_reader
from .notify import CRITICAL, WARN, Notifier

SLIP = 0.0002  # adverse slippage of the virtual market entry (handover 5.1)

SCHEMA = """
CREATE TABLE IF NOT EXISTS anchors (
    symbol TEXT PRIMARY KEY, anchor_open INTEGER NOT NULL, set_ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sweep_signals (
    signal_id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL, tf TEXT NOT NULL, symbol TEXT NOT NULL, side INTEGER NOT NULL,
    bar_open INTEGER NOT NULL, bar_close INTEGER NOT NULL, close REAL NOT NULL, atr14 REAL,
    cls TEXT NOT NULL,
    entry_time INTEGER NOT NULL, next_open REAL NOT NULL, virtual_entry REAL NOT NULL,
    latency_ms INTEGER NOT NULL,
    book_ts INTEGER, book_bid REAL, book_ask REAL, est_fill REAL,
    recorded_ts INTEGER NOT NULL, run_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sweep_signals_rec ON sweep_signals (recorded_ts);
CREATE TABLE IF NOT EXISTS sweep_runs (
    run_id TEXT PRIMARY KEY, started_ts INTEGER NOT NULL, finished_ts INTEGER,
    status TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sweep_mismatch (
    ts INTEGER NOT NULL, run_id TEXT NOT NULL, kind TEXT NOT NULL, signal_id TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


def code_commit() -> str:
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                              text=True, timeout=5).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _ms(series) -> np.ndarray:
    return (series.astype("int64") // 1_000_000).to_numpy(np.int64)


def build_frames(lib, df5, tfs: Iterable[str]) -> dict:
    """Chart frames per timeframe from 5m bars, without the forming bar at the
    end and without a partial bar at the start (a bin that opens before the
    first 5m bar). Both match the backtest's input files, which kept bins with
    open >= series start and open + length <= series end."""
    ts5 = _ms(df5["ts"])
    first_open, last_close = int(ts5[0]), int(ts5[-1]) + FIVE_MIN
    frames = {}
    for tf in tfs:
        if tf == "5m":
            df = df5
        else:
            r = lib.resample_ohlcv(df5, tf)
            t = _ms(r["ts"])
            keep = (t >= first_open) & (t + TF_MS[tf] <= last_close)
            df = r.loc[keep].reset_index(drop=True)
        df.attrs["tf"] = tf
        frames[tf] = df
    return frames


def signals_for_symbol(lib, symbol: str, df5, cells_by_tf: dict) -> tuple[list[dict], list[str], dict]:
    """All signals after warm-up for one coin, as dicts. Signals whose entry
    bar does not exist yet have entry_time None."""
    frames = build_frames(lib, df5, cells_by_tf)
    ts5 = _ms(df5["ts"])
    open5 = df5["open"].to_numpy(float)
    rows: list[dict] = []
    errors: list[str] = []
    stats: dict = {}
    for tf, names in cells_by_tf.items():
        df = frames[tf]
        w = lib.warmup_bars(tf)
        stats[tf] = {"bars": len(df), "warmup": w, "ready": len(df) > w}
        if len(df) <= w:
            continue
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            sigs = lib.compute_signals({symbol: df}, tf, names, strict=False)
        for wmsg in caught:
            text = str(wmsg.message)
            if text.split(" ", 1)[0] in names:
                errors.append(text[:300])
        ts = _ms(df["ts"])
        close = df["close"].to_numpy(float)
        atr = lib.fg.atr(df, 14).to_numpy(float)
        span = TF_MS[tf]
        for name in names:
            arr = sigs.get(name, {}).get(symbol)
            if arr is None:
                continue
            idx = np.flatnonzero(arr)
            for i in idx[idx >= w]:
                side = int(arr[i])
                bar_open = int(ts[i])
                bar_close = bar_open + span
                j = int(np.searchsorted(ts5, bar_close, side="left"))
                has_entry = j < len(ts5)
                a = float(atr[i]) if np.isfinite(atr[i]) else None
                rows.append({
                    "signal_id": f"{name}|{tf}|{symbol}|{bar_open}",
                    "strategy": name, "tf": tf, "symbol": symbol, "side": side,
                    "bar_open": bar_open, "bar_close": bar_close, "close": float(close[i]), "atr14": a,
                    "entry_time": int(ts5[j]) if has_entry else None,
                    "next_open": float(open5[j]) if has_entry else None,
                })
    return rows, errors, stats


def _cells_by_tf(cells: Sequence[tuple[str, str]]) -> dict:
    out: dict = {}
    for name, tf in cells:
        out.setdefault(tf, []).append(name)
    return {tf: out[tf] for tf in sweepsig.TF_ORDER if tf in out}


class Recorder:
    def __init__(self, archive: MarketArchive, ledger_path: Optional[str] = None,
                 notifier: Optional[Notifier] = None, clock_ms: Optional[Callable[[], int]] = None,
                 cells: Optional[Sequence[tuple[str, str]]] = None):
        self.archive = archive
        self.conn = archive.conn
        self.conn.executescript(SCHEMA)
        self.ledger_path = ledger_path
        self.notifier = notifier
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.cells = list(cells) if cells is not None else sweepsig.cells("2")

    def anchor(self, symbol: str) -> Optional[int]:
        r = self.conn.execute("SELECT anchor_open FROM anchors WHERE symbol = ?", (symbol,)).fetchone()
        if r:
            return int(r[0])
        first = self.archive.first_time("kline5m", symbol)
        if first is None:
            return None
        self.conn.execute("INSERT INTO anchors VALUES (?,?,?)", (symbol, first, self.clock_ms()))
        self.conn.commit()
        return int(first)

    def _previous_horizons(self) -> dict:
        r = self.conn.execute("SELECT data FROM sweep_runs WHERE status = 'ok' "
                              "ORDER BY finished_ts DESC LIMIT 1").fetchone()
        return json.loads(r[0]).get("horizons", {}) if r else {}

    def _book(self, reader, symbol: str, bar_close: int, side: int) -> dict:
        if reader is None:
            return {}
        b = book_near(reader, symbol, bar_close)
        if not b:
            return {}
        return {"book_ts": b["ts"], "book_bid": b["bid"], "book_ask": b["ask"],
                "est_fill": b["ask"] if side > 0 else b["bid"]}

    def run(self, symbols: Iterable[str]) -> dict:
        lib = sweepsig.lib()
        versions = sweepsig.verify()
        run_id = uuid.uuid4().hex[:12]
        started = self.clock_ms()
        self.conn.execute("INSERT INTO sweep_runs VALUES (?,?,?,?,?)",
                          (run_id, started, None, "running", "{}"))
        self.conn.commit()
        prev = self._previous_horizons()
        cells_by_tf = _cells_by_tf(self.cells)
        stored: dict = {}
        for sid, side, sym in self.conn.execute("SELECT signal_id, side, symbol FROM sweep_signals"):
            stored[sid] = (side, sym)
        new_rows, mismatches, errors = [], [], []
        horizons, stats, t_sym = {}, {}, {}
        for sym in symbols:
            t0 = time.time()
            anchor = self.anchor(sym)
            if anchor is None:
                errors.append(f"{sym}: no 5m bars stored")
                continue
            df5 = self.archive.load_5m(sym, start=anchor)
            if df5.empty:
                errors.append(f"{sym}: no 5m bars after anchor")
                continue
            horizon = int(_ms(df5["ts"])[-1]) + FIVE_MIN
            horizons[sym] = horizon
            rows, errs, st = signals_for_symbol(lib, sym, df5, cells_by_tf)
            errors += [f"{sym} {e}" for e in errs]
            stats[sym] = st
            recomputed = {r["signal_id"]: r for r in rows}
            for sid, (side, s_sym) in stored.items():
                if s_sym != sym:
                    continue
                r = recomputed.get(sid)
                if r is None:
                    mismatches.append(("disappeared", sid, {"stored_side": side}))
                elif r["side"] != side:
                    mismatches.append(("side_changed", sid, {"stored_side": side, "now": r["side"]}))
            ph = prev.get(sym)
            for sid, r in recomputed.items():
                if sid in stored or r["entry_time"] is None:
                    continue
                if ph is not None and r["entry_time"] < ph:
                    mismatches.append(("appeared_late", sid, {
                        "entry_time": r["entry_time"], "previous_horizon": ph}))
                new_rows.append(r)
            t_sym[sym] = round(time.time() - t0, 2)
        now = self.clock_ms()
        reader = open_book_reader(self.ledger_path) if self.ledger_path else None
        for r in new_rows:
            side = r["side"]
            b = self._book(reader, r["symbol"], r["bar_close"], side)
            self.conn.execute(
                "INSERT OR IGNORE INTO sweep_signals VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["signal_id"], r["strategy"], r["tf"], r["symbol"], side, r["bar_open"],
                 r["bar_close"], r["close"], r["atr14"], "2", r["entry_time"], r["next_open"],
                 r["next_open"] * (1 + side * SLIP), r["entry_time"] - r["bar_close"],
                 b.get("book_ts"), b.get("book_bid"), b.get("book_ask"), b.get("est_fill"),
                 now, run_id))
        if reader is not None:
            reader.close()
        for kind, sid, detail in mismatches:
            self.conn.execute("INSERT INTO sweep_mismatch VALUES (?,?,?,?,?)",
                              (now, run_id, kind, sid, json.dumps(detail)))
        status = "ok" if horizons else "error"
        by_tf: dict = {}
        for r in new_rows:
            by_tf[r["tf"]] = by_tf.get(r["tf"], 0) + 1
        data = {"horizons": horizons, "new_signals": len(new_rows), "new_by_tf": by_tf,
                "mismatches": len(mismatches), "errors": errors[:50], "n_errors": len(errors),
                "cells": len(self.cells), "symbols": list(horizons), "seconds_per_symbol": t_sym,
                "warmup": stats, "code_commit": code_commit(),
                "prereg_sha256_file": versions["prereg_sha256_file"],
                "source_commit": versions["source_commit"]}
        self.conn.execute("UPDATE sweep_runs SET finished_ts = ?, status = ?, data = ? WHERE run_id = ?",
                          (self.clock_ms(), status, json.dumps(data), run_id))
        self.conn.commit()
        self.archive.log_system("record_run", {"run_id": run_id, "status": status,
                                               "new": len(new_rows), "mismatches": len(mismatches),
                                               "errors": len(errors), "code_commit": data["code_commit"]})
        if self.notifier:
            if mismatches:
                kinds: dict = {}
                for k, _, _ in mismatches:
                    kinds[k] = kinds.get(k, 0) + 1
                self.notifier.send(CRITICAL, f"signal recorder: {len(mismatches)} past signals changed "
                                             f"on recompute {kinds}. Check data revisions and code.")
            if errors:
                self.notifier.send(WARN, f"signal recorder: {len(errors)} errors, first: {errors[0]}")
        return {"run_id": run_id, "status": status, **data}


def last_runs(conn: sqlite3.Connection, n: int = 5) -> list[dict]:
    conn.executescript(SCHEMA)
    out = []
    for run_id, st, fin, status, data in conn.execute(
            "SELECT run_id, started_ts, finished_ts, status, data FROM sweep_runs "
            "ORDER BY started_ts DESC LIMIT ?", (n,)):
        out.append({"run_id": run_id, "started": st, "finished": fin, "status": status,
                    **json.loads(data or "{}")})
    return out
