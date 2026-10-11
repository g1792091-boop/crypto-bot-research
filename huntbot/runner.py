"""huntbot-run: replay paper of every trend-hunt system from 2026-10-01, recomputed after every 5m bar.

    python -m huntbot run            the service: a cycle whenever the feed's completeness mark moves (and when the
                                     lineup file changes)
    python -m huntbot once           one cycle on what is stored, then exit
    python -m huntbot status         the last cycle's status line

Design (REPLAY PAPER, parity by construction). Each cycle takes every stored bar with open < complete_ms (the feed's
mark), builds the coins exactly as research/hunt/hunt.py ``load_coin`` does (``clean_5m``, ``Coin``; a coin that still
trades has no coin end, a coin that stopped trading ends at its last bar with volume), installs them with
``hunt.install`` and runs, for every system, the backtest's own calls on the window 2026-10-01 00:00 UTC .. the next
00:00 UTC after the data: ``Market`` -> ``system_signals`` -> ``bank_for`` -> ``build_cands`` -> ``simulate`` (the numba
engine) -> ``summarize``, with one $5,000 wallet per system at r = 0.5% (PREREG_HUNT 10). Nothing is carried from one
cycle to the next except two caches that never change a number:

* signal bars (``hunt.Series``: bars, ATR14, 장세 label) of a coin and timeframe are reused while no new bin of that
  timeframe has closed; the bars object itself is rebuilt every cycle (its fill-bar index moves with every 5m bar);
* entry events are computed when their timeframe gets a new bin and kept per (cell, coin) as the close times of the
  events; events of bars already seen are frozen (and written to events.db, the ledger): a definition that would
  repaint its past cannot change the record; the difference goes to the ledger's ``repaints`` table. A causal
  definition gives exactly what the batch backtest computes (tests/test_huntbot_parity.py).

Work order of a cycle: (1) events of the lineup's cells, (2) the lineup accounts (dashboard first screen and Telegram
are written right away), (3) events of every other cell, in a fork process pool (``HUNTBOT_PROCS``), (4) every system,
by cell, in the pool, (5) the full snapshot and the ledger's actions. Positions still open are marked at the last
close (the engine's period end). Outputs: <snap>/status.json, lineup.json, systems.json, positions.json, trades.json
(DeepSeek money never in them, D11), <private>/deepseek.json (DeepSeek money, never served), events.db, run.db.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import multiprocessing as mp
import os
import sqlite3
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from typing import Callable, Optional

import numpy as np

from research.hunt import hunt as H

from . import config as CFG
from . import engine as E
from . import systems as S
from .ledger import Ledger
from .store import Store

EW = H._ew()
TFS = tuple(H.TF_ORDER)
FIVE, DAY = CFG.FIVE, CFG.DAY
NO_END = 2 ** 62
_W: dict = {}                      # the parent's state, read by forked workers
SERIES_ATTRS = {"sym", "tf", "bars", "atr", "code"}
EMPTY = np.zeros(0, np.int64)


def ceil_day(ms: int) -> int:
    return -(-int(ms) // DAY) * DAY


def fgrid(ms) -> np.ndarray:
    return ((np.asarray(ms, np.int64) + 30_000) // FIVE) * FIVE


# ---------------------------------------------------------------- code identity
SIGNAL_GLOBS = (("research/hunt", ("entries_wide.py",)), ("research/fullgrid", None), ("research/entry_study/param_defs",
                None), ("research/deepseek200", ("lib_c.py",)), ("research/library", ("lib.py",)),
                ("research/search", ("search.py",)), ("third_party/sweep/harness", None),
                ("paperbot/dash/tools", ("regime5y.py",)))
SIGNAL_FILES = ("research/fullgrid/diag/watch_sel.json", "research/fullgrid/PREREG.sha256",
                "research/entry_study/DEFS_BC.sha256")


def signal_hash(root: str = CFG.ROOT) -> str:
    """sha256 over the code that decides entry events (entries, the full grid's definitions, the label) and the hunt
    functions that call it. A change starts a new ledger generation."""
    h = hashlib.sha256()
    files = []
    for d, names in SIGNAL_GLOBS:
        full = os.path.join(root, d)
        if not os.path.isdir(full):
            continue
        for dp, dn, fns in os.walk(full):
            dn[:] = sorted(x for x in dn if x != "__pycache__")
            for f in sorted(fns):
                if f.endswith(".py") and (names is None or f in names):
                    files.append(os.path.join(dp, f))
    files += [os.path.join(root, f) for f in SIGNAL_FILES if os.path.exists(os.path.join(root, f))]
    for p in files:
        h.update(os.path.relpath(p, root).encode() + b"\n")
        with open(p, "rb") as fh:
            h.update(fh.read())
    for fn in (H.entry_events, H.gate_mask, H.Series, H.cell_key):
        h.update(inspect.getsource(fn).encode())
    return h.hexdigest()


def engine_info(root: str = CFG.ROOT) -> dict:
    hunt = os.path.join(root, "research", "hunt", "hunt.py")
    ew = os.path.join(root, "research", "hunt", "entries_wide.py")
    out = {"hunt_sha256": CFG.sha256_file(hunt), "entries_wide_sha256": CFG.sha256_file(ew),
           "exchange30": CFG.sha256_file(os.path.join(root, "research", "hunt", "exchange30.json")), "pins": {}}
    for study, rel in (("v1", "research/hunt/PREREG_HUNT.sha256"), ("wide", "research/hunt/PREREG_HUNT_WIDE.sha256")):
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            out["pins"][study] = {"pinned": False, "note": "고정 파일 없음 (아직 고정 전)"}
            continue
        want = {}
        with open(p) as fh:
            for line in fh:
                parts = line.rstrip("\n").split("  ", 1)
                if len(parts) == 2:
                    want[parts[1].strip()] = parts[0]
        ok = (want.get("research/hunt/hunt.py") == out["hunt_sha256"]
              and want.get("research/hunt/entries_wide.py", out["entries_wide_sha256"]) == out["entries_wide_sha256"])
        out["pins"][study] = {"pinned": True, "same_code": bool(ok), "picks_line": any(k.endswith(("pick.json",
                              "picks.json")) for k in want)}
    try:
        import subprocess
        out["commit"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                                       timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        out["commit"] = None
    vp = os.path.join(root, "VERSION.json")
    if os.path.exists(vp):
        try:
            with open(vp) as fh:
                out["installed"] = json.load(fh)
        except ValueError:
            pass
    return out


# ---------------------------------------------------------------- run.db (the runner's own small state)
def open_run_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trades_seen (account TEXT NOT NULL, tkey TEXT NOT NULL, first_seen_ms INTEGER NOT NULL,
  engine TEXT, data TEXT NOT NULL, PRIMARY KEY (account, tkey)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS runs (started_ms INTEGER PRIMARY KEY, complete_ms INTEGER, seconds REAL, info TEXT);
""")
    conn.commit()
    return conn


def kv_get(conn, k, default=None):
    row = conn.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
    return json.loads(row[0]) if row else default


def kv_put(conn, k, v) -> None:
    conn.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, json.dumps(v)))


# ---------------------------------------------------------------- F1 entry values (events.db, for the judge)
def _f1_values(name: str, combo: dict, bars, j: int) -> Optional[dict]:
    h, lo, c, qv = bars.h, bars.l, bars.c, bars.qv
    try:
        if name == "E1":
            n = int(next(iter(combo.values()))) if combo else 55
            if j < max(n, 20):
                return None
            vm = float(np.mean(qv[j - 20:j]))
            return {"channel_high": float(np.max(h[j - n:j])), "channel_low": float(np.min(lo[j - n:j])),
                    "close": float(c[j]), "volume_ratio": float(qv[j] / vm) if vm > 0 else None}
        if name == "E2":
            win = int(next(iter(combo.values()))) if combo else 120
            if j < win + 21:
                return None
            bw = []
            for t in range(j - win - 1, j + 1):
                w = c[t - 19:t + 1]
                m, sd = float(np.mean(w)), float(np.std(w))
                bw.append((4.0 * sd) / m if m else np.nan)
            mid = float(np.mean(c[j - 19:j + 1]))
            sd = float(np.std(c[j - 19:j + 1]))
            return {"bandwidth_prev": bw[-2], "bandwidth_pct20": float(np.percentile(bw[:-1][-win:], 20.0)),
                    "upper": mid + 2 * sd, "lower": mid - 2 * sd, "close": float(c[j])}
        if name == "E3":
            if j < 21:
                return None
            return {"momentum_20": float(c[j] - c[j - 20]), "close": float(c[j])}
    except (ValueError, IndexError, StopIteration):
        return None
    return None


# ---------------------------------------------------------------- forked workers
def _task_events(task):
    cid, sym = task
    R = _W["runner"]
    cell = R.cells[cid]
    try:
        ser = H.series(sym, cell.tf)
        btc = H.series("BTCUSDT", cell.tf) if cell.kind == "ds" and sym != "BTCUSDT" and "BTCUSDT" in H._COINS \
            else None
        lg, sh = H.entry_events(cell.spec, sym, ser, btc)
        cm = ser.bars.close_ms
        fwd = cm >= R.fwd
        lg, sh = np.asarray(lg, bool), np.asarray(sh, bool)
        return (cid, sym, cm[lg & fwd].astype(np.int64), cm[sh & fwd].astype(np.int64),
                int(cm[-1]) if len(cm) else None, len(H.series("BTCUSDT", cell.tf).bars) if btc is not None else None,
                None)
    except Exception as e:  # noqa: BLE001  one bad cell never stops the others
        return (cid, sym, None, None, None, None, f"{type(e).__name__}: {e}"[:300])


def _slim(res: dict, keep_trades: bool = True) -> dict:
    s = res["summary"]
    keys = ("months", "M", "end_multiple", "max_dd", "bust", "bust_month", "n_positions", "months_with_position",
            "fees", "funding", "skipped", "cut", "adds_skipped", "time_at_cap", "win_share", "mean_pnl_U",
            "median_pnl_U", "exit_reasons", "exit_stop_source", "open_at_end", "leverage_median", "candidates",
            "signal_counts", "mean_lnM", "median_M", "share_add_level", "adds_per_month", "day_eq",
            "realized_unit_risk", "share_first_unit_cut")
    out = {"summary": {k: s.get(k) for k in keys}, "equity_now": res["equity_now"], "bust_t": res["bust_t"],
           "month_names": res["months"]}
    if keep_trades:
        out["trades"] = res["trades"]
    if "hourly" in res:
        out["hourly"] = res["hourly"]
    if "actions" in res:
        out["actions"] = res["actions"]
    return out


def _task_cell(task):
    cid, since = task
    R = _W["runner"]
    mk, last_step, var = _W["mk"], _W["last_step"], _W["r05"]
    cell = R.cells[cid]
    try:
        evs = R.load_cell_events(cid, mk)
        out = {}
        for spec in cell.systems:
            res = E.run_account(mk, [(spec, 0)], var, last_step, want_probe=not S.is_ds(spec),
                                action_events=evs if since is not None else None, since_ms=since)
            out[spec["id"]] = _slim(res)
        return cid, out, None
    except Exception as e:  # noqa: BLE001
        return cid, None, f"{type(e).__name__}: {e}"[:300] + " | " + traceback.format_exc(limit=3)[-600:]


def pool_map(fn: Callable, tasks: list, procs: int, chunk: int = 1) -> list:
    """[fn(t) for t in tasks] in ``procs`` forked workers (they inherit the parent's data); in order."""
    if procs <= 1 or len(tasks) <= 1:
        return [fn(t) for t in tasks]
    ctx = mp.get_context("fork")
    with ProcessPoolExecutor(min(procs, len(tasks)), mp_context=ctx) as ex:
        return list(ex.map(fn, tasks, chunksize=max(1, chunk)))


# ---------------------------------------------------------------- the runner
class Runner:
    def __init__(self, store: Store, ledger: Ledger, run_db: sqlite3.Connection, universe: list,
                 lineup_path: str, snap: str, private: str, procs: int = 1, warmup_ms: Optional[int] = None,
                 fwd_ms: int = CFG.FORWARD_START_MS, clock=time.time, log=print, notifier=None,
                 engine: Optional[dict] = None, universe_info: Optional[dict] = None, syms: Optional[list] = None):
        self.store, self.ledger, self.rdb = store, ledger, run_db
        self.universe, self.lineup_path = list(universe), lineup_path
        self.snap, self.private, self.procs = snap, private, max(1, int(procs))
        self.warmup_ms = CFG.warmup_start_ms() if warmup_ms is None else int(warmup_ms)
        self.fwd, self.clock, self.out, self.notifier = int(fwd_ms), clock, log, notifier
        self.engine = engine or {}
        self.universe_info = universe_info or {"symbols": self.universe}
        self.systems, self.aliases = S.system_list()
        self.by_id = {s["id"]: s for s in self.systems}
        self.cells = S.cells_of(self.systems)
        self.cell_of_sys = {s["id"]: cid for cid, c in self.cells.items() for s in c.systems}
        self.var = S.variants()
        self.fixed_syms = syms
        self.syms: list = []
        self.data: dict = {}
        self.funding: dict = {}
        self.coin_end: dict = {}
        self.last_ins = 0
        self.dirty: set = set()
        self.series: dict = {}
        self.book = ledger.load_book()
        self.book_btc: dict = {}
        self.retry: set = set()
        self.done_ms: Optional[int] = None
        self.lineup = {"accounts": [], "error": None, "path": lineup_path}
        self.cycles = 0
        self.errors: list = []
        self.reuse_series = True          # off for good if hunt.Series ever holds more than bars / ATR / label

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    # ------------------------------------------------------------ data
    def pick_syms(self) -> list:
        if self.fixed_syms is not None:
            return list(self.fixed_syms)
        cov = self.store.coverage()
        coins = self.store.coins()
        out = []
        for s in self.universe:
            c, info = cov.get(s), coins.get(s) or {}
            if not c or c["last_ms"] is None:
                continue
            end = info.get("end_ms")
            if end is not None and int(end) < self.fwd:
                continue
            if info.get("trading") == 1 or (end is not None and int(end) >= self.fwd) or c["last_ms"] >= self.fwd:
                out.append(s)
        return out

    def load_data(self) -> None:
        self.last_ins = self.store.max_ins()
        self.syms = self.pick_syms()
        for s in self.syms:
            self.data[s] = self.store.load_bars(s, self.warmup_ms)
            self.dirty.add(s)

    def sync_data(self) -> dict:
        """New rows since the last read; a row older than a coin's newest bar reloads the coin (late bar)."""
        stats = {"new": 0, "late": []}
        rows_by = self.store.bars_since(self.last_ins)
        mx = self.store.max_ins()
        for sym, rows in rows_by.items():
            if sym not in self.data:
                continue
            d = self.data[sym]
            ts_new = np.asarray([r[0] for r in rows], np.int64)
            keep = ts_new >= self.warmup_ms
            have = np.isin(ts_new, d["ts"])
            fresh = keep & ~have
            if not fresh.any():
                continue
            last = int(d["ts"][-1]) if len(d["ts"]) else -1
            if (ts_new[fresh] <= last).any():
                self.data[sym] = self.store.load_bars(sym, self.warmup_ms)
                self.dirty.add(sym)
                stats["late"].append(sym)
                continue
            arr = np.asarray([rows[i] for i in np.flatnonzero(fresh)], np.float64)
            d["ts"] = np.concatenate([d["ts"], ts_new[fresh]])
            for i, k in enumerate(("o", "h", "l", "c", "v", "qv"), start=1):
                d[k] = np.concatenate([d[k], arr[:, i]])
            stats["new"] += int(fresh.sum())
        self.last_ins = max(self.last_ins, mx)
        coins = self.store.coins()
        for s in self.syms:
            e = (coins.get(s) or {}).get("end_ms")
            self.coin_end[s] = int(e) if e is not None else None
            self.funding[s] = self.store.load_funding(s, self.fwd - DAY)
        return stats

    def build_coins(self, complete_ms: int) -> tuple:
        coins, fund = {}, {}
        for s in self.syms:
            d = self.data[s]
            n = int(np.searchsorted(d["ts"], complete_ms, "left"))
            (ts, o, h, lo, c, v, qv), counts = H.clean_5m(d["ts"][:n], d["o"][:n], d["h"][:n], d["l"][:n],
                                                          d["c"][:n], d["v"][:n], d["qv"][:n])
            end = self.coin_end.get(s)
            last_ms = int(end) if end is not None and end < complete_ms else NO_END
            coins[s] = H.Coin(s, ts, o, h, lo, c, v, qv, last_ms=last_ms, counts=counts)
            fts, rate = self.funding.get(s, (EMPTY, np.zeros(0)))
            k = fgrid(fts) <= complete_ms
            fund[s] = (np.asarray(fts, np.int64)[k], np.asarray(rate, np.float64)[k])
        return coins, fund

    def refresh_series(self) -> set:
        """Put every (coin, timeframe) Series into hunt's cache; returns the pairs with a new bin (recomputed)."""
        new = set()
        for s in self.syms:
            f = None
            for tf in TFS:
                old = self.series.get((s, tf))
                ser = None
                if old is not None and s not in self.dirty and self.reuse_series:
                    f = f or H._COINS[s].f64()
                    bars = EW.build_bars(f["ts"], f["o"], f["h"], f["l"], f["c"], f["v"], tf, f["qv"])
                    if len(bars) == len(old.bars) and (not len(bars) or bars.open_ms[-1] == old.bars.open_ms[-1]):
                        ser = object.__new__(H.Series)
                        ser.__dict__.update(old.__dict__)
                        ser.bars = bars
                if ser is None:
                    ser = H.Series(s, tf)
                    new.add((s, tf))
                    if not set(vars(ser)) <= SERIES_ATTRS:
                        self.reuse_series = False
                self.series[(s, tf)] = ser
                H._SERIES[(s, tf)] = ser
        self.dirty.clear()
        return new

    # ------------------------------------------------------------ events (the ledger)
    def stale_pairs(self, new_bins: set, cells: list) -> list:
        out = []
        for cid in cells:
            c = self.cells[cid]
            for s in self.syms:
                k = (cid, s)
                btc_new = c.kind == "ds" and s != "BTCUSDT" and ("BTCUSDT", c.tf) in new_bins
                if (s, c.tf) in new_bins or btc_new or k not in self.book or k in self.retry \
                        or (c.kind == "ds" and s != "BTCUSDT" and k not in self.book_btc):
                    out.append(k)
        return out

    def refresh_events(self, pairs: list) -> dict:
        """Compute the events of ``pairs`` (pool), freeze what was seen, append the new ones to the ledger."""
        if not pairs:
            return {"pairs": 0, "new": 0, "repaints": 0, "errors": 0}
        order = sorted(pairs, key=lambda p: (TFS.index(self.cells[p[0]].tf), p[0], p[1]))
        _W["runner"] = self
        res = pool_map(_task_events, order, self.procs, chunk=max(1, len(order) // (self.procs * 16) if
                                                                   self.procs > 1 else 1))
        rows, rep, progress, errs = [], [], [], 0
        for cid, sym, lms, sms, last, btc_n, err in res:
            if err:
                errs += 1
                self.retry.add((cid, sym))
                self.errors.append(f"{cid} {sym}: {err}")
                continue
            self.retry.discard((cid, sym))
            e = self.book.get((cid, sym))
            thr = e["through"] if e else self.fwd - 1
            old_l, old_s = (e["long"], e["short"]) if e else (EMPTY, EMPTY)
            for side, fresh, old in (("LONG", lms, old_l), ("SHORT", sms, old_s)):
                seen = fresh[fresh <= thr]
                for ms in np.setdiff1d(old, seen).tolist():
                    rep.append((cid, sym, side, ms, "vanished"))
                for ms in np.setdiff1d(seen, old).tolist():
                    rep.append((cid, sym, side, ms, "appeared"))
            new_l, new_s = lms[lms > thr], sms[sms > thr]
            through = max(thr, last) if last is not None else thr
            self.book[(cid, sym)] = {"through": int(through), "long": np.concatenate([old_l, new_l]),
                                     "short": np.concatenate([old_s, new_s])}
            if btc_n is not None:
                self.book_btc[(cid, sym)] = btc_n
            progress.append((cid, sym, int(through)))
            for side, arr in (("LONG", new_l), ("SHORT", new_s)):
                for ms in arr.tolist():
                    rows.append(self._event_row(cid, sym, side, int(ms)))
        n = self.ledger.add_events(rows)
        self.ledger.set_progress(progress)
        if rep:
            self.ledger.log_repaints(rep)
        self.ledger.commit()
        return {"pairs": len(pairs), "new": n, "repaints": len(rep), "errors": errs}

    def _event_row(self, cid: str, sym: str, side: str, ms: int) -> dict:
        c = self.cells[cid]
        ser = self.series[(sym, c.tf)]
        cm = ser.bars.close_ms
        j = int(np.searchsorted(cm, ms))
        row = {"cell": cid, "family": c.family, "name": c.name, "kind": c.kind, "tf": c.tf, "rank": c.rank,
               "sys_g1": c.sys_of("G1"), "sys_none": c.sys_of("NONE"), "symbol": sym, "side": side,
               "bar_close_ms": ms}
        if j < len(cm) and int(cm[j]) == ms:
            atr = float(ser.atr[j])
            code = int(ser.code[j])
            row.update({"regime_code": code, "gated": int(code == H.TREND), "close": float(ser.bars.c[j]),
                        "atr14": atr if np.isfinite(atr) else None,
                        "d0": H.D0_MULT[c.tf] * atr if np.isfinite(atr) else None})
            if c.kind == "hunt":
                row["entry_values"] = _f1_values(c.name, c.spec.get("combo") or {}, ser.bars, j)
        return row

    def dense(self, cid: str, sym: str, close_ms: np.ndarray) -> tuple:
        n = len(close_ms)
        lg, sh = np.zeros(n, bool), np.zeros(n, bool)
        e = self.book.get((cid, sym))
        if e is not None and n:
            for arr, out in ((e["long"], lg), (e["short"], sh)):
                if len(arr):
                    idx = np.searchsorted(close_ms, arr)
                    ok = idx < n
                    ok[ok] &= close_ms[idx[ok]] == arr[ok]
                    out[idx[ok]] = True
        return lg, sh

    def load_cell_events(self, cid: str, mk) -> dict:
        """Put the cell's frozen events into hunt's event cache (one cell at a time: bounded memory)."""
        cell = self.cells[cid]
        H._EVENTS.clear()
        H._SIGS.clear()
        evs = {}
        for s in mk.syms:
            ser = H.series(s, cell.tf)
            H._EVENTS[(cell.key, s)] = self.dense(cid, s, ser.bars.close_ms)
            e = self.book.get((cid, s))
            evs[s] = (e["long"], e["short"]) if e else (EMPTY, EMPTY)
        return evs

    # ------------------------------------------------------------ lineup
    def read_lineup(self) -> dict:
        lu = S.read_lineup(self.lineup_path, self.by_id, self.aliases)
        if lu["error"] and lu["error"] != (self.lineup or {}).get("error"):
            self.out(f"{CFG.TAG} lineup file error: {lu['error']}")
        return lu

    def run_lineup(self, mk, last_step: int) -> dict:
        res = {}
        for a in self.lineup["accounts"]:
            try:
                H._EVENTS.clear()
                H._SIGS.clear()
                for spec, _ in a["parts"]:
                    cid = self.cell_of_sys[spec["id"]]
                    cell = self.cells[cid]
                    for s in mk.syms:
                        H._EVENTS[(cell.key, s)] = self.dense(cid, s, H.series(s, cell.tf).bars.close_ms)
                r = E.run_account(mk, a["parts"], self.var[a["variant"]], last_step, want_probe=not a["ds"],
                                  want_hourly=True)
                res[a["id"]] = _slim(r)
            except Exception as e:  # noqa: BLE001
                self.errors.append(f"lineup {a['id']}: {type(e).__name__}: {e}"[:300])
        H._EVENTS.clear()
        H._SIGS.clear()
        return res

    # ------------------------------------------------------------ one cycle
    def cycle(self, complete_ms: int) -> dict:
        from . import snapshot as SN
        t0 = time.monotonic()
        started = self.now_ms()
        self.errors = []
        phase = {}
        if not self.data:
            self.load_data()
        sync = self.sync_data()
        if complete_ms is None or complete_ms <= self.fwd:
            SN.write_status(self, complete_ms, started, None, {"waiting": "자료가 10/01까지 아직 안 모임"})
            return {"skipped": True}
        coins, fund = self.build_coins(complete_ms)
        H.install(coins, fund)
        new_bins = self.refresh_series()
        phase["data_s"] = round(time.monotonic() - t0, 2)
        mk = H.Market(self.syms, (self.fwd, ceil_day(complete_ms)), name="forward")
        last_step = (complete_ms - self.fwd) // FIVE - 1
        for tf in TFS:
            H.bank_for(mk, (tf,))
        self.lineup = self.read_lineup()
        pri = sorted({c for a in self.lineup["accounts"] for c in a["cells"]})
        _W.update({"runner": self, "mk": mk, "last_step": last_step, "r05": self.var["r0.5"]})
        # (1) + (2): the lineup first
        t1 = time.monotonic()
        ev1 = self.refresh_events(self.stale_pairs(new_bins, pri))
        lineup_res = self.run_lineup(mk, last_step)
        caught_up = self.now_ms() - complete_ms < 30 * 60_000
        SN.write_lineup(self, mk, complete_ms, lineup_res)
        if self.notifier is not None:
            try:
                self.notifier.after_lineup(self, mk, complete_ms, lineup_res, caught_up)
            except Exception as e:  # noqa: BLE001  Telegram never stops the runner
                self.errors.append(f"telegram: {type(e).__name__}: {e}"[:200])
        phase["lineup_s"] = round(time.monotonic() - t1, 2)
        # (3) every other cell's events
        t2 = time.monotonic()
        rest = [c for c in self.cells if c not in set(pri)]
        ev2 = self.refresh_events(self.stale_pairs(new_bins, rest))
        phase["events_s"] = round(time.monotonic() - t2, 2)
        # (4) every system, one task per cell
        t3 = time.monotonic()
        pending = self.ledger.pending_since()
        tasks = [(cid, pending.get(cid)) for cid in self.cells]
        tasks.sort(key=lambda t: TFS.index(self.cells[t[0]].tf))
        res = pool_map(_task_cell, tasks, self.procs, chunk=max(1, len(tasks) // (self.procs * 8)))
        results, n_act = {}, 0
        for cid, out, err in res:
            if err:
                self.errors.append(f"cell {cid}: {err}")
                continue
            results.update(out)
            acts = {}
            cell = self.cells[cid]
            g1, nn = cell.sys_of("G1"), cell.sys_of("NONE")
            keys = set()
            for sid in (g1, nn):
                if sid and "actions" in out.get(sid, {}):
                    keys |= set(out[sid]["actions"])
            for k in keys:
                acts[k] = ((out.get(g1) or {}).get("actions", {}).get(k), (out.get(nn) or {}).get("actions", {}).get(k))
            if acts:
                n_act += self.ledger.set_actions(cid, acts)
        self.ledger.commit()
        phase["systems_s"] = round(time.monotonic() - t3, 2)
        # (5) the full snapshot
        t4 = time.monotonic()
        SN.write_all(self, mk, complete_ms, results, lineup_res)
        self.record_trades(results, lineup_res)
        phase["snapshot_s"] = round(time.monotonic() - t4, 2)
        self.done_ms = complete_ms
        self.cycles += 1
        self.last_results, self.last_lineup = results, lineup_res
        info = {"complete_ms": complete_ms, "seconds": round(time.monotonic() - t0, 2), "phase": phase,
                "new_bins": len(new_bins), "events_lineup": ev1, "events_rest": ev2, "systems": len(results),
                "actions": n_act, "sync": sync, "errors": self.errors[:20], "procs": self.procs,
                "lineup_accounts": len(self.lineup["accounts"]), "catching_up": not caught_up}
        self.rdb.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?)", (started, complete_ms, info["seconds"],
                                                                            json.dumps(info)))
        self.rdb.execute("DELETE FROM runs WHERE started_ms < ?", (started - 14 * DAY,))
        self.rdb.commit()
        self.ledger.heartbeat({"complete_ms": complete_ms, "seconds": info["seconds"]})
        self.ledger.commit()
        SN.write_status(self, complete_ms, started, info)
        if self.notifier is not None:
            try:
                self.notifier.after_cycle(self, info, caught_up)
            except Exception as e:  # noqa: BLE001
                self.out(f"{CFG.TAG} telegram failed: {type(e).__name__}")
        return info

    def record_trades(self, results: dict, lineup_res: dict) -> None:
        """Every closed trade the first time it is seen (run.db; the record cannot change silently after a code
        change: a later different version of the same trade is kept beside it)."""
        now = self.now_ms()
        eng = (self.engine.get("hunt_sha256") or "")[:16]
        rows = []
        for acct, res in list(results.items()) + [(f"lineup:{k}", v) for k, v in lineup_res.items()]:
            for t in res.get("trades", []):
                if t["open"]:
                    continue
                key = f"{t['coin']}|{t['side']}|{t['in_ms']}|{eng}"
                rows.append((acct, key, now, eng, json.dumps(t)))
        self.rdb.executemany("INSERT OR IGNORE INTO trades_seen VALUES (?, ?, ?, ?, ?)", rows)
        self.rdb.commit()

    # ------------------------------------------------------------ the service loop
    def run_forever(self, poll_s: float = 5.0) -> None:
        self.out(f"{CFG.TAG} runner: {len(self.systems)} systems in {len(self.cells)} cells, procs {self.procs}, "
                 f"ledger generation {self.ledger.gen}")
        last_lineup = None
        while True:
            try:
                comp = self.store.complete_ms()
                lsha = CFG.sha256_file(self.lineup_path)
                if comp is not None and (self.done_ms is None or comp > self.done_ms or lsha != last_lineup):
                    info = self.cycle(comp)
                    last_lineup = lsha
                    if not info.get("skipped"):
                        self.out(f"{CFG.TAG} cycle to {CFG.ms_str(comp)} UTC in {info['seconds']}s "
                                 f"({info['phase']}), {len(info['errors'])} error(s)")
            except Exception as e:  # noqa: BLE001  the service never dies on one bad cycle
                self.out(f"{CFG.TAG} cycle failed: {type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}")
                try:
                    self.ledger.conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(30)
            time.sleep(poll_s)


def make_runner(notifier=True, log=print) -> Runner:
    uni = CFG.load_universe()
    os.makedirs(CFG.data_dir(), exist_ok=True)
    store_path = CFG.path("store.db")
    store = Store(store_path, readonly=os.path.exists(store_path))
    sh = signal_hash()
    eng = engine_info()
    ledger = Ledger(CFG.path("events.db"), sh, (eng.get("hunt_sha256") or "")[:16])
    rdb = open_run_db(CFG.path("run.db"))
    nt = None
    if notifier:
        from .notify import Notifier
        nt = Notifier(rdb)
    eng["signal_hash"] = sh
    return Runner(store, ledger, rdb, uni["symbols"], CFG.lineup_file(), CFG.snap_dir(), CFG.private_dir(),
                  CFG.procs(), log=log, notifier=nt, engine=eng, universe_info=uni)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m huntbot run", description=__doc__.split("\n")[0])
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "once", "status"))
    a = ap.parse_args(argv)
    if a.cmd == "status":
        p = os.path.join(CFG.snap_dir(), "status.json")
        if not os.path.exists(p):
            print("no status yet")
            return 1
        with open(p) as fh:
            d = json.load(fh)
        run = d.get("run") or {}
        print(f"complete {CFG.ms_str(d.get('complete_ms'))} UTC, last cycle {run.get('seconds')}s, "
              f"errors {len(run.get('errors') or [])}, lineup {d.get('lineup', {}).get('accounts')}")
        return 0
    H._compile_probe()
    EW.fullgrid_pins()
    r = make_runner(log=lambda m: print(m, flush=True))
    if a.cmd == "once":
        comp = r.store.complete_ms()
        info = r.cycle(comp)
        print(json.dumps({k: v for k, v in info.items() if k != "errors"}, default=str), flush=True)
        return 0
    r.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
