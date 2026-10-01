"""30-day checkpoint verdicts for the paper v3 run (docs/paper-v3-rules.md section 4, confirmed
addendum docs/paper-v3-rules-addendum.md Q1-Q3; the addendum's '확정 내용' table wins).

    python -m paperbot.checkpoint run  --db paper3.db --out checkpoint.db [--cache DIR] [--date YYYY-MM-DD]
        [--brackets FILE | --allow-example-brackets] [--bots 2000]
    python -m paperbot.checkpoint show --out checkpoint.db [--date YYYY-MM-DD]

When
    Checkpoints are 00:00 UTC (09:00 KST) on day 30, 60, 90, ... after the run start (the UTC
    date of the first account's creation in paper3.db). The job runs hourly and does nothing until
    a checkpoint is due and the live runner has saved its ``day:<date>`` state for it.

Q2 snapshot
    At the checkpoint the runner itself keeps the state of every account before the 00:00 step
    (``day:<date>``, paperbot/accounts.py). This job copies it, with the closed trades and the
    signal counts it needs, into one canonical JSON document, hashes it (sha256) and stores it in
    an append-only table of ``--out``. The verdict reads only that snapshot (hash checked).
    Evaluated equity = wallet + unrealised P&L at the mark price - estimated exit cost (taker fee
    + slippage on the current notional). A trade belongs to the period it was entered in: a
    position open at the checkpoint counts as a trade of the period that ends there, valued then.

Q3 schedule
    Each account (strategy x timeframe, and improved copies) gets its 1st verdict at the first
    checkpoint where it has >= 30 trades; 4h accounts and the live coin-flip accounts are
    observation only ('관찰용'). 1st pass = trades >= 30 and equity > starting equity and not bust
    and the Q1 luck test passed. A 1st pass is checked again on the next 30 days only (2nd check):
    >= 30 trades entered in them, positive P&L in them (scaled to the $5,000 start) and Q1 again on
    that window. A copy account's windows start at its own creation; it is judged at the run's
    checkpoints (so it shares their FDR family) once 30 days old.

Q1 luck test
    Per judged account, 2,000 coin-flip bots run over the same window with the same rules and the
    same starting equity; each coin and bar of the account's timeframe fires with probability = the
    account's own signal rate in that window (signals / (6 coins x bars)), side 50/50 (as
    research/paper_rules/rules_bt.py ``random_signals``). p = (bots >= account + 1) / (2,000 + 1).
    Benjamini-Hochberg at FDR 10% over every account tested at that checkpoint.

    The bots run on the real 1m bars of the window (last and mark price, real funding times and
    rates) from Binance's public REST API, cached per coin and UTC day under ``--cache``, through a
    vectorised copy of the paper engine (``simulate_bots``): signal at the timeframe close, entry
    at the next minute's open plus slippage, stop 2 x ATR14 of the signal bar, the owners' sizing
    tiers with the exchange brackets, coin priority, one position, stepped profit lock on 1m LAST
    high/low (applied from the next bar), liquidation on the mark price, bust below $10. A test
    checks it trade for trade against ``PaperEngine``. All bots of one timeframe and window run in
    one pass (each with its own account's rate), so no sharing of bots between accounts is needed.

The job never writes paper3.db (opened ``mode=ro``); everything goes to ``--out``.
Other code (agents, dashboard) reads results with ``latest_verdict``, ``account_status`` and
``statuses``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import sys
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .config import V3_STOP_ATR, V3_SYMBOLS, Settings, v3_settings
from .margin import Brackets
from .notify import INFO, WARN

MIN = 60_000
DAY_MS = 86_400_000
PERIOD_DAYS = 30
MIN_TRADES = 30
N_BOTS = 2000
ALPHA = 0.10
OBSERVE_TFS = ("4h",)
TF_MS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
ATR_PREFIX_BARS = 300          # TF bars before the window for ATR14 (Wilder; (13/14)^300 ~ 2e-10)
NO_VERDICT_DAYS = 180          # addendum Q3: still < 30 trades at day 180 -> '판정 불가'
SNAPSHOT_VERSION = 1

HOLD, PASS1, FAIL, PASS2, OBSERVE = "보류", "1차 합격", "불합격", "2차 통과", "관찰용"
STATUSES = (HOLD, PASS1, FAIL, PASS2, OBSERVE)
# signal_log statuses that are a strategy signal on a trade coin (RECORD = 1d / XRP only)
SIGNAL_STATUSES = ("SUBMITTED", "LATE", "NO_PRICE", "NO_ATR")

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    date TEXT PRIMARY KEY, cp_ts INTEGER NOT NULL, created_ts INTEGER NOT NULL,
    sha256 TEXT NOT NULL, data TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS snapshots_frozen_u BEFORE UPDATE ON snapshots
BEGIN SELECT RAISE(ABORT, 'checkpoint snapshots are frozen'); END;
CREATE TRIGGER IF NOT EXISTS snapshots_frozen_d BEFORE DELETE ON snapshots
BEGIN SELECT RAISE(ABORT, 'checkpoint snapshots are frozen'); END;
CREATE TABLE IF NOT EXISTS verdicts (
    date TEXT PRIMARY KEY, ts INTEGER NOT NULL, snapshot_sha256 TEXT NOT NULL, data TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS verdicts_frozen_u BEFORE UPDATE ON verdicts
BEGIN SELECT RAISE(ABORT, 'checkpoint verdicts are final'); END;
CREATE TRIGGER IF NOT EXISTS verdicts_frozen_d BEFORE DELETE ON verdicts
BEGIN SELECT RAISE(ABORT, 'checkpoint verdicts are final'); END;
CREATE TABLE IF NOT EXISTS verdict_accounts (
    date TEXT NOT NULL, account_id TEXT NOT NULL, status TEXT NOT NULL, stage TEXT,
    p REAL, q REAL, data TEXT NOT NULL, PRIMARY KEY (date, account_id));
CREATE TABLE IF NOT EXISTS job_log (ts INTEGER NOT NULL, date TEXT, text TEXT NOT NULL);
"""


# ====================================================================== small helpers
def ro_connect(path: str) -> sqlite3.Connection:
    """Read-only connection (the live runner is paper3.db's only writer)."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    uri = f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=30)


def day_str(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def day_ms(day: str) -> int:
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def floor_day(ms: int) -> int:
    return ms - ms % DAY_MS


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def checkpoint_ts(run_start: int, k: int) -> int:
    """00:00 UTC of day 30k after the run start."""
    return floor_day(run_start) + k * PERIOD_DAYS * DAY_MS


def due_checkpoints(run_start: int, now_ms: int) -> list[tuple[int, int]]:
    """[(k, cp_ts)] of checkpoints at or before now."""
    out, k = [], 1
    while checkpoint_ts(run_start, k) <= now_ms:
        out.append((k, checkpoint_ts(run_start, k)))
        k += 1
    return out


def open_value(side: int, qty: float, entry: float, margin: float, mark: float, s: Settings) -> float:
    """What closing an open position at ``mark`` adds to the wallet: gross P&L minus the
    estimated exit cost (taker fee and slippage on the notional). Beyond the isolated margin the
    position would be liquidated (the engine's ``_close`` rule): the margin is lost."""
    gross = side * qty * (mark - entry)
    if gross < -margin:
        return -margin
    return gross - qty * mark * (s.taker_fee + s.slippage_frac)


# ====================================================================== Q2 snapshot
def run_facts(conn: sqlite3.Connection) -> dict:
    """Run start (first account creation), starting equity and fee from the run state."""
    st = conn.execute("SELECT data FROM state WHERE k = 'run'").fetchone()
    run = json.loads(st[0]) if st else {}
    r = conn.execute("SELECT MIN(created_ts) FROM accounts WHERE parent IS NULL").fetchone()
    start = r[0] if r and r[0] is not None else None
    if start is None:
        r = conn.execute("SELECT MIN(started_ts) FROM runs").fetchone()
        start = r[0] if r else None
    return {"start_ts": None if start is None else int(start),
            "initial_equity": float(run.get("initial_equity", 5000.0)),
            "taker_fee": run.get("taker_fee"), "settings_version": run.get("settings")}


def _trading_changes(conn: sqlite3.Connection, upto: int) -> list[dict]:
    """Starts of the runner whose recorded changes touch fills, exits or sizing (Q5)."""
    from .runinfo import WATCHED
    trading = {k for k, _, t in WATCHED if t}
    out = []
    for ts, data in conn.execute("SELECT started_ts, data FROM runs WHERE started_ts < ? ORDER BY id", (upto,)):
        ch = [c for c in json.loads(data).get("changes", []) if c in trading]
        if ch:
            out.append({"ts": int(ts), "changes": ch})
    return out


def freeze_snapshot(conn: sqlite3.Connection, cp_ts: int, symbols=V3_SYMBOLS,
                    settings: Optional[Settings] = None) -> Optional[dict]:
    """The Q2 snapshot of every account at ``cp_ts`` (00:00 UTC), from the runner's own
    ``day:<date>`` state. None when the runner has not saved that state (yet)."""
    date = day_str(cp_ts)
    row = conn.execute("SELECT ts, data FROM state WHERE k = ?", ("day:" + date,)).fetchone()
    if row is None:
        return None
    facts = run_facts(conn)
    s = settings or v3_settings(**({"taker_fee": facts["taker_fee"]} if facts["taker_fee"] else {}))
    state = json.loads(row[1])
    engines = state.get("engines", {})
    trades: dict[str, list] = {}
    for aid, et, xt, pnl in conn.execute("SELECT account_id, entry_time, exit_time, pnl FROM trades "
                                         "WHERE exit_time < ? ORDER BY id", (cp_ts,)):
        trades.setdefault(aid, []).append([int(et), int(xt), round(float(pnl), 8)])
    sig: dict[tuple, dict] = {}
    q = ("SELECT strategy, timeframe, bar_close / 86400000 AS d, COUNT(*) FROM signal_log "
         f"WHERE bar_close < ? AND status IN ({','.join('?' * len(SIGNAL_STATUSES))}) "
         f"AND symbol IN ({','.join('?' * len(symbols))}) GROUP BY strategy, timeframe, d")
    for strat, tf, d, n in conn.execute(q, (cp_ts, *SIGNAL_STATUSES, *symbols)):
        sig.setdefault((strat, tf), {})[day_str(int(d) * DAY_MS)] = int(n)
    accounts = {}
    for aid, strat, tf, kind, created, parent in conn.execute(
            "SELECT account_id, strategy, timeframe, kind, created_ts, parent FROM accounts ORDER BY rowid"):
        e = engines.get(aid)
        if e is None or created >= cp_ts:
            continue
        pos = e.get("position")
        mark = None
        cpos = None
        equity = float(e["wallet"])
        if pos is not None:
            mark = float(e.get("last_mark", {}).get(pos["symbol"], pos["entry_price"]))
            cpos = {k: pos[k] for k in ("symbol", "side", "qty", "entry_price", "entry_time", "leverage",
                                        "margin", "entry_fee", "funding_paid")}
            equity += open_value(int(pos["side"]), float(pos["qty"]), float(pos["entry_price"]),
                                 float(pos["margin"]), mark, s)
        accounts[aid] = {
            "strategy": strat, "timeframe": tf, "kind": kind, "created_ts": int(created), "parent": parent,
            "wallet": round(float(e["wallet"]), 8), "bust": bool(e.get("bust")), "halted": bool(e.get("halted")),
            "position": cpos, "mark": mark, "equity": round(equity, 8),
            "trades": trades.get(aid, []), "signals": sig.get((strat, tf), {}),
        }
    return {
        "version": SNAPSHOT_VERSION, "date": date, "cp_ts": cp_ts,
        "source": {"state_key": "day:" + date, "state_ts": int(row[0]), "state_sha256": sha256_text(row[1])},
        "run": {"start_ts": facts["start_ts"], "initial_equity": facts["initial_equity"],
                "taker_fee": s.taker_fee, "slippage": s.slippage_frac, "settings_version": facts["settings_version"],
                "trading_changes": _trading_changes(conn, cp_ts)},
        "symbols": list(symbols), "accounts": accounts,
    }


def open_out(path: str) -> sqlite3.Connection:
    out = sqlite3.connect(path, timeout=30)
    out.execute("PRAGMA journal_mode=WAL")
    out.executescript(SCHEMA)
    out.commit()
    return out


def store_snapshot(out: sqlite3.Connection, snap: dict, now_ms: int) -> str:
    """Insert once (the table refuses updates and deletes). Returns the sha256."""
    text = canonical(snap)
    h = sha256_text(text)
    have = out.execute("SELECT sha256 FROM snapshots WHERE date = ?", (snap["date"],)).fetchone()
    if have is not None:
        return have[0]
    out.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)", (snap["date"], snap["cp_ts"], now_ms, h, text))
    out.commit()
    return h


class SnapshotTampered(RuntimeError):
    pass


def load_snapshot(out: sqlite3.Connection, date: str) -> Optional[tuple[dict, str]]:
    r = out.execute("SELECT sha256, data FROM snapshots WHERE date = ?", (date,)).fetchone()
    if r is None:
        return None
    if sha256_text(r[1]) != r[0]:
        raise SnapshotTampered(f"snapshot {date}: stored hash {r[0][:12]} does not match its data")
    return json.loads(r[1]), r[0]


# ====================================================================== period statistics
def period_stats(acct: dict, lo: int, hi: int, s: Settings, initial: float) -> dict:
    """Trades entered in [lo, hi) (closed before ``hi`` or still open at the snapshot ``hi``),
    their P&L (open one at the snapshot value), and the account's signal count in the window."""
    closed = [t for t in acct["trades"] if lo <= t[0] < hi and t[1] < hi]
    pnl = sum(t[2] for t in closed)
    n = len(closed)
    pos = acct.get("position")
    if pos is not None and lo <= pos["entry_time"] < hi:
        n += 1
        pnl += (open_value(pos["side"], pos["qty"], pos["entry_price"], pos["margin"], acct["mark"], s)
                - pos["entry_fee"] - pos["funding_paid"])
    lo_d, hi_d = day_str(lo), day_str(hi - 1)
    sigs = sum(v for d, v in acct["signals"].items() if lo_d <= d <= hi_d)
    return {"trades": n, "pnl": pnl, "signals": sigs}


def signal_rate(signals: int, tf: str, lo: int, hi: int, coins: int = 6) -> float:
    span = TF_MS[tf]
    first = -(-lo // span) * span
    bars = max(0, (hi - 1 - first) // span + 1) if hi > first else 0
    return signals / max(coins * bars, 1)


# ====================================================================== Q1 statistics
def luck_p(value: float, bots: np.ndarray) -> float:
    """p = (bots at or above the account + 1) / (bots + 1)."""
    bots = np.asarray(bots, float)
    return float((np.count_nonzero(bots >= value - 1e-9) + 1) / (len(bots) + 1))


def bh(pvals, alpha: float = ALPHA) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg: (q-values, rejected at FDR ``alpha``). q_i = min_{j>=i} p_(j) m / j."""
    p = np.asarray(pvals, float)
    m = len(p)
    if m == 0:
        return np.zeros(0), np.zeros(0, bool)
    order = np.argsort(p, kind="mergesort")
    ranked = p[order] * m / np.arange(1, m + 1)
    qs = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(m)
    q[order] = np.minimum(qs, 1.0)
    # the step-up rule itself: reject the k smallest, k = max{i: p_(i) <= i alpha / m}
    ok = np.nonzero(p[order] <= np.arange(1, m + 1) * alpha / m)[0]
    rej = np.zeros(m, bool)
    if len(ok):
        rej[order[: ok[-1] + 1]] = True
    return q, rej


# ====================================================================== 1m bars
@dataclass
class Minutes:
    """Aligned 1m bars of the trade coins: ``ts`` (T,) open times, every minute; prices (T, C)
    with NaN where a coin has no bar; ``fr`` (T, C) funding rate settled at that minute or NaN."""
    ts: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray  # noqa: E741
    c: np.ndarray
    mo: np.ndarray
    mh: np.ndarray
    ml: np.ndarray
    mc: np.ndarray
    fr: np.ndarray
    symbols: tuple

    def window(self, lo: int, hi: int) -> "Minutes":
        a, b = np.searchsorted(self.ts, lo), np.searchsorted(self.ts, hi)
        return Minutes(self.ts[a:b], *(getattr(self, k)[a:b] for k in
                                      ("o", "h", "l", "c", "mo", "mh", "ml", "mc", "fr")), self.symbols)


def empty_minutes(lo: int, hi: int, symbols) -> Minutes:
    ts = np.arange(lo, hi, MIN, dtype=np.int64)
    nan = lambda: np.full((len(ts), len(symbols)), np.nan)  # noqa: E731
    return Minutes(ts, *(nan() for _ in range(9)), tuple(symbols))


class BinanceMinutes:
    """1m last and mark price klines and funding from Binance's public REST API (no key), cached
    per coin and UTC day as .npz under ``cache_dir`` (only complete past days are cached)."""

    def __init__(self, rest, cache_dir: Optional[str], symbols=V3_SYMBOLS, pause: float = 0.15,
                 now_ms: Optional[Callable[[], int]] = None):
        self.rest, self.cache, self.symbols, self.pause = rest, cache_dir, tuple(symbols), pause
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.fetched_days = 0
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def _day(self, sym: str, d0: int) -> dict:
        path = os.path.join(self.cache, f"{sym}_{day_str(d0)}.npz") if self.cache else None
        if path and os.path.exists(path):
            z = np.load(path)
            return {k: z[k] for k in z.files}
        d1 = d0 + DAY_MS
        rows = [r for r in self.rest.klines(sym, "1m", start_time=d0, limit=1500) if int(r[0]) < d1]
        time.sleep(self.pause)
        marks = {int(r[0]): r for r in self.rest.mark_klines(sym, "1m", start_time=d0, limit=1500)
                 if int(r[0]) < d1}
        time.sleep(self.pause)
        fund = [r for r in self.rest.funding_rates(sym, start_time=d0, limit=20) if int(r["fundingTime"]) < d1]
        time.sleep(self.pause)
        t = np.array([int(r[0]) for r in rows], np.int64)
        last = np.array([[float(r[k]) for k in (1, 2, 3, 4)] for r in rows], float).reshape(-1, 4)
        mk = np.array([[float(marks[int(r[0])][k]) if int(r[0]) in marks else np.nan for k in (1, 2, 3, 4)]
                       for r in rows], float).reshape(-1, 4)
        out = {"t": t, "last": last, "mark": mk,
               "fts": np.array([int(r["fundingTime"]) for r in fund], np.int64),
               "frate": np.array([float(r["fundingRate"]) for r in fund], float)}
        self.fetched_days += 1
        if path and d1 <= self.now_ms() - 5 * MIN:
            tmp = path + ".part.npz"
            np.savez_compressed(tmp, **out)
            os.replace(tmp, path)
        return out

    def load(self, lo: int, hi: int) -> Minutes:
        m = empty_minutes(lo, hi, self.symbols)
        for k, sym in enumerate(self.symbols):
            d = floor_day(lo)
            while d < hi:
                got = self._day(sym, d)
                t = got["t"]
                keep = (t >= lo) & (t < hi)
                idx = (t[keep] - lo) // MIN
                for j, name in enumerate(("o", "h", "l", "c")):
                    getattr(m, name)[idx, k] = got["last"][keep, j]
                    getattr(m, "m" + name)[idx, k] = got["mark"][keep, j]
                ft = got["fts"]
                fk = (ft >= lo) & (ft < hi)
                m.fr[(ft[fk] - ft[fk] % MIN - lo) // MIN, k] = got["frate"][fk]
                d += DAY_MS
        return m


def tf_atr(m: Minutes, tf: str) -> tuple[np.ndarray, np.ndarray]:
    """ATR14 (Wilder, as the locked code's fg_indicators.atr) of every TF bar built from the 1m
    bars. Returns (close_times (B,), atr (B, C)): the ATR of the bar that closes at close_times."""
    import pandas as pd
    span = TF_MS[tf]
    per = span // MIN
    a0 = int(np.searchsorted(m.ts, -(-int(m.ts[0]) // span) * span))
    n = (len(m.ts) - a0) // per
    if n <= 0:
        return np.zeros(0, np.int64), np.zeros((0, len(m.symbols)))
    sl = slice(a0, a0 + n * per)
    shape = (n, per, len(m.symbols))
    with np.errstate(all="ignore"), _quiet():
        hi = np.nanmax(m.h[sl].reshape(shape), axis=1)
        lo = np.nanmin(m.l[sl].reshape(shape), axis=1)
        cc = m.c[sl].reshape(shape)
    # close = last present 1m close of the bin
    present = ~np.isnan(cc)
    last_idx = per - 1 - np.argmax(present[:, ::-1, :], axis=1)
    close = np.take_along_axis(cc, last_idx[:, None, :], axis=1)[:, 0, :]
    close[~present.any(axis=1)] = np.nan
    ends = m.ts[a0] + (np.arange(n, dtype=np.int64) + 1) * span
    out = np.full((n, len(m.symbols)), np.nan)
    for k in range(len(m.symbols)):
        ok = ~np.isnan(close[:, k])          # resample drops empty bins
        df = pd.DataFrame({"high": hi[ok, k], "low": lo[ok, k], "close": close[ok, k]})
        prev = df["close"].shift(1)
        tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()],
                       axis=1).max(axis=1)
        out[ok, k] = tr.ewm(alpha=1.0 / 14, adjust=False, min_periods=14).mean().to_numpy()
    return ends, out


class _quiet:
    def __enter__(self):
        import warnings
        self._w = warnings.catch_warnings()
        self._w.__enter__()
        warnings.simplefilter("ignore")

    def __exit__(self, *a):
        self._w.__exit__(*a)


# ====================================================================== the bots (vectorised engine)
@dataclass
class _BracketArrays:
    caps: np.ndarray
    maxlev: np.ndarray
    mmr: np.ndarray
    cum: np.ndarray

    @classmethod
    def of(cls, b: Brackets) -> "_BracketArrays":
        return cls(np.array([t.notional_cap for t in b.tiers], float), np.array([t.max_leverage for t in b.tiers]),
                   np.array([t.mmr for t in b.tiers], float), np.array([t.cum for t in b.tiers], float))


def size_vec(s: Settings, eq, side, fill, stop, atr, br: _BracketArrays, qty_step: float = 0.0,
             min_notional: float = 0.0) -> dict:
    """``sizing.size_position`` for many candidates of one coin at once (requested tier 'best',
    then lower; first passing candidate wins). Returns arrays ok, lev, qty, margin, liq, mmr, cum."""
    eq, side, fill, stop, atr = (np.asarray(x, float) for x in (eq, side, fill, stop, atr))
    n = len(eq)
    res = {k: np.zeros(n) for k in ("lev", "qty", "margin", "liq", "mmr", "cum")}
    todo = (eq > 0) & ((fill - stop) * side > 0)
    buffer = np.maximum(s.liq_buffer_min_frac * fill, s.liq_buffer_atr_mult * atr)
    dist = np.abs(fill - stop)
    exit_px = stop * (1 - side * s.slippage_frac)
    for tier, lev in s.tier_chain("best"):
        margin = eq * tier.margin_frac
        raw = margin * lev / fill
        qty = np.floor(raw / qty_step + 1e-9) * qty_step if qty_step > 0 else raw
        notional = qty * fill
        c = (qty > 0) & (notional >= min_notional)
        margin = notional / lev
        bi = np.minimum(np.searchsorted(br.caps, notional, side="left"), len(br.caps) - 1)
        c &= lev <= br.maxlev[bi]
        mmr, cum = br.mmr[bi], br.cum[bi]
        with np.errstate(all="ignore"):
            liq = np.maximum((margin + cum - side * qty * fill) / (qty * mmr - side * qty), 0.0)
        c &= (stop - liq) * side >= buffer
        loss = (qty * dist + qty * np.abs(stop - exit_px) + notional * s.taker_fee + qty * exit_px * s.taker_fee)
        c &= loss <= s.max_loss_frac * eq
        good = todo & c
        for k, v in (("lev", np.full(n, float(lev))), ("qty", qty), ("margin", margin), ("liq", liq),
                     ("mmr", mmr), ("cum", cum)):
            res[k][good] = v[good]
        todo &= ~good
    res["ok"] = res["lev"] > 0
    return res


def random_draws(rng: np.random.Generator):
    """Coin-flip signals as in rules_bt.random_signals: each coin and bar fires with the bot's
    rate, side 50/50."""
    def draw(ts: int, idx: np.ndarray, rates: np.ndarray, n_coins: int):
        fire = rng.random((len(idx), n_coins)) < rates[idx, None]
        side = np.where(rng.random((len(idx), n_coins)) < 0.5, 1, -1)
        return fire, side
    return draw


def simulate_bots(m: Minutes, tf: str, lo: int, hi: int, rates: np.ndarray, s: Settings,
                  brackets: dict, specs: Optional[dict] = None, seed=0, draw=None,
                  initial: Optional[float] = None, stop_atr: float = V3_STOP_ATR,
                  atr: Optional[tuple] = None) -> dict:
    """Coin-flip accounts on real 1m bars, the paper engine's rules (see the module docstring).

    ``m`` must start early enough for ATR14 of the first signal bar (``ATR_PREFIX_BARS``); the
    bots trade minutes in [lo, hi) and signals of bars closing at boundaries in [lo, hi). Each bot
    i fires with ``rates[i]``. Returns final evaluated equity per bot (``equity``), wallet, bust
    flags and entered-trade counts."""
    specs = specs or {}
    syms = m.symbols
    C = len(syms)
    N = len(rates)
    rates = np.asarray(rates, float)
    init = s.initial_equity if initial is None else initial
    span = TF_MS[tf]
    ends, atr_tab = atr if atr is not None else tf_atr(m, tf)
    atr_at = {int(t): atr_tab[i] for i, t in enumerate(ends)}
    draw = draw or random_draws(np.random.default_rng(seed))
    br = [_BracketArrays.of(brackets[x]) for x in syms]
    steps = [(specs.get(x, {}).get("qty_step", 0.0), specs.get(x, {}).get("min_notional", 0.0)) for x in syms]
    w = m.window(lo, hi)
    taker, slip, rt = s.taker_fee, s.slippage_frac, s.round_trip_cost
    lad = s.ladder
    first_trig = lad.first_lock + lad.trigger_gap

    wallet = np.full(N, float(init))
    bust = np.zeros(N, bool)
    inpos = np.zeros(N, bool)
    coin = np.zeros(N, np.int64)
    side = np.zeros(N)
    qty = np.zeros(N)
    entry = np.zeros(N)
    stop = np.zeros(N)
    lock = np.full(N, -np.inf)
    liq = np.zeros(N)
    margin = np.zeros(N)
    mmr = np.zeros(N)
    cum = np.zeros(N)
    efee = np.zeros(N)
    fpaid = np.zeros(N)
    mfe = np.zeros(N)
    lev = np.zeros(N)
    ntr = np.zeros(N, np.int64)
    last_mark = np.full(C, np.nan)
    allidx = np.arange(N)
    T = len(w.ts)
    bidx = np.nonzero(w.ts % span == 0)[0]      # minutes where signals arrive

    def close(j, px, liquidate):
        """Close positions j at prices px (liquidate: lose the isolated margin)."""
        gross = side[j] * qty[j] * (px - entry[j])
        liqd = liquidate | (gross < -margin[j])
        wallet[j] = np.where(liqd, wallet[j] - margin[j], wallet[j] + gross - qty[j] * px * taker)
        inpos[j] = False
        bust[j] |= wallet[j] < s.bust_below

    t = -1
    while True:
        t += 1
        if t >= T:
            break
        if not inpos.any():
            # nobody holds a position: nothing happens until the next signal minute
            nb = bidx[np.searchsorted(bidx, t):]
            if not len(nb) or bust.all():
                break
            t = int(nb[0])
        ts = int(w.ts[t])
        o, h, l, c = w.o[t], w.h[t], w.l[t], w.c[t]
        mo, mh, ml, mc = w.mo[t], w.mh[t], w.ml[t], w.mc[t]
        mo = np.where(np.isnan(mo), o, mo)
        mh = np.where(np.isnan(mh), h, mh)
        ml = np.where(np.isnan(ml), l, ml)
        mc = np.where(np.isnan(mc), c, mc)
        entered = None
        # ---- entries: signals of the TF bar that closed at this minute's open
        if ts % span == 0:
            free = allidx[~inpos & ~bust]
            a = atr_at.get(ts)
            if len(free) and a is not None:
                fire, sd = draw(ts, free, rates, C)
                got = np.zeros(len(free), bool)
                for k in range(C):            # coin priority; sizing failure -> next coin
                    if np.isnan(o[k]) or not (np.isfinite(a[k]) and a[k] > 0):
                        continue
                    cand = np.nonzero(fire[:, k] & ~got)[0]
                    if not len(cand):
                        continue
                    j = free[cand]
                    sdk = sd[cand, k].astype(float)
                    raw = o[k]
                    fill = raw * (1 + sdk * slip)
                    st = raw - sdk * stop_atr * a[k]
                    r = size_vec(s, wallet[j], sdk, fill, st, np.full(len(j), a[k]), br[k], *steps[k])
                    okc = r["ok"]
                    j = j[okc]
                    got[cand[okc]] = True
                    q_ = r["qty"][okc]
                    inpos[j] = True
                    coin[j] = k
                    side[j] = sdk[okc]
                    qty[j] = q_
                    entry[j] = fill[okc]
                    stop[j] = st[okc]
                    lock[j] = -np.inf
                    liq[j] = r["liq"][okc]
                    margin[j] = r["margin"][okc]
                    mmr[j] = r["mmr"][okc]
                    cum[j] = r["cum"][okc]
                    fee = q_ * fill[okc] * taker
                    wallet[j] -= fee
                    efee[j] = fee
                    fpaid[j] = 0.0
                    mfe[j] = fill[okc]
                    lev[j] = r["lev"][okc]
                    ntr[j] += 1
                entered = free[got]
        # ---- exits
        j = allidx[inpos]
        if len(j):
            k = coin[j]
            ok = ~np.isnan(o[k])
            j, k = j[ok], k[ok]
        if len(j):
            sd = side[j]
            bo, bh_, bl = o[k], h[k], l[k]
            mfe[j] = np.where(sd > 0, np.maximum(mfe[j], bh_), np.minimum(mfe[j], bl))
            eb = np.zeros(len(j), bool)
            if entered is not None and len(entered):
                eb = np.isin(j, entered)
            done = np.zeros(len(j), bool)
            # gaps at the open (not on the entry bar): liquidation on mark, then the stop on last
            g_liq = ~eb & ((mo[k] - liq[j]) * sd <= 0)
            if g_liq.any():
                close(j[g_liq], liq[j[g_liq]], True)
                done |= g_liq
            g_st = ~eb & ~done & ((bo - stop[j]) * sd <= 0)
            if g_st.any():
                jj = j[g_st]
                close(jj, bo[g_st] * (1 - sd[g_st] * slip), False)
                done |= g_st
            hit = ~done & np.where(sd > 0, bl <= stop[j], bh_ >= stop[j])
            if hit.any():
                jj = j[hit]
                close(jj, stop[jj] * (1 - side[jj] * slip), False)
                done |= hit
            hl = ~done & np.where(sd > 0, ml[k] <= liq[j], mh[k] >= liq[j])
            if hl.any():
                close(j[hl], liq[j[hl]], True)
                done |= hl
            # profit lock from the best price so far, effective from the next bar
            up = ~done & ~eb
            if up.any():
                jj = j[up]
                sj = side[jj]
                fund = fpaid[jj] / (qty[jj] * entry[jj])
                best = lev[jj] * (sj * (mfe[jj] / entry[jj] - 1.0) - rt - fund)
                armed = best >= first_trig - 1e-12
                nstep = np.floor((best - first_trig) / lad.step + 1e-9)
                lk = np.where(armed, lad.first_lock + lad.step * nstep, -np.inf)
                raise_ = armed & (lk > lock[jj] + 1e-12)
                if raise_.any():
                    jr = jj[raise_]
                    sr = side[jr]
                    px = entry[jr] * (1.0 + sr * (lk[raise_] / lev[jr] + rt + fund[raise_]))
                    stop[jr] = np.where(sr > 0, np.maximum(stop[jr], px), np.minimum(stop[jr], px))
                    lock[jr] = lk[raise_]
        # ---- funding at its real minute, on the mark open
        fr = w.fr[t]
        if not np.all(np.isnan(fr)):
            j = allidx[inpos]
            if len(j):
                k = coin[j]
                rate = fr[k]
                ok = ~np.isnan(rate) & ~np.isnan(o[k])
                j, k, rate = j[ok], k[ok], rate[ok]
                if len(j):
                    pay = side[j] * qty[j] * mo[k] * rate
                    wallet[j] -= pay
                    margin[j] -= pay
                    fpaid[j] += pay
                    sj = side[j]
                    with np.errstate(all="ignore"):
                        liq[j] = np.maximum((margin[j] + cum[j] - sj * qty[j] * entry[j])
                                            / (qty[j] * mmr[j] - sj * qty[j]), 0.0)
        if inpos.any():
            present = ~np.isnan(c)
            last_mark[present] = mc[present]

    # mark price of the last minute of the window (what the checkpoint snapshot holds)
    for k in range(C):
        mk_k = np.where(np.isnan(w.mc[:, k]), w.c[:, k], w.mc[:, k])
        ok_k = np.nonzero(~np.isnan(mk_k))[0]
        if len(ok_k):
            last_mark[k] = mk_k[ok_k[-1]]
    eq = wallet.copy()
    j = allidx[inpos]
    if len(j):
        mk = last_mark[coin[j]]
        gross = side[j] * qty[j] * (mk - entry[j])
        eq[j] += np.where(gross < -margin[j], -margin[j], gross - qty[j] * mk * (taker + slip))
    return {"equity": eq, "wallet": wallet, "bust": bust, "trades": ntr, "open": inpos}


# ====================================================================== the verdict
@dataclass
class Task:
    aid: str
    stage: str          # "1차" or "2차"
    tf: str
    lo: int
    hi: int
    value: float        # account statistic compared with the bots' final equity
    rate: float


def _prior(out: sqlite3.Connection, date: str) -> dict:
    """Latest decided state per account before ``date`` (from earlier verdicts)."""
    st = {}
    for d, aid, status, stage, data in out.execute(
            "SELECT date, account_id, status, stage, data FROM verdict_accounts WHERE date < ? ORDER BY date",
            (date,)):
        st[aid] = {"date": d, "status": status, "stage": stage, **json.loads(data)}
    return st


def plan(snap: dict, prior: dict, prev_snaps: dict, s: Settings) -> tuple[dict, list[Task]]:
    """Per-account decisions that need no bots, and the Q1 tasks for the rest."""
    cp = snap["cp_ts"]
    init = snap["run"]["initial_equity"]
    rows, tasks = {}, []
    for aid, a in snap["accounts"].items():
        tf = a["timeframe"]
        lo = a["created_ts"]
        st1 = period_stats(a, lo, cp, s, init)
        base = {"strategy": a["strategy"], "timeframe": tf, "kind": a["kind"], "equity": a["equity"],
                "bust": a["bust"], "trades_total": st1["trades"]}
        pr = prior.get(aid)
        if a["kind"] == "random":
            rows[aid] = {**base, "status": OBSERVE, "stage": None, "reason": "동전 봇 기준 계좌 (판정 안 함, 눈으로 보는 기준)"}
            continue
        if tf in OBSERVE_TFS or tf not in TF_MS:
            rows[aid] = {**base, "status": OBSERVE, "stage": None, "reason": "4시간봉은 처음부터 관찰용 (Q3)"}
            continue
        if pr and pr["status"] in (FAIL, PASS2):
            rows[aid] = {**base, "status": pr["status"], "stage": pr.get("stage"),
                         "reason": f"{pr.get('decided', pr['date'])} 판정 유지: {pr.get('reason', '')}",
                         "decided": pr.get("decided", pr["date"]), "p": pr.get("p"), "q": pr.get("q")}
            continue
        if pr and pr["status"] == PASS1:
            plo = pr["window"][1]
            prev = prev_snaps.get(day_str(plo))
            eq0 = prev["accounts"][aid]["equity"] if prev and aid in prev["accounts"] else None
            st2 = period_stats(a, plo, cp, s, init)
            scaled = st2["pnl"] * init / eq0 if eq0 and eq0 > 0 else st2["pnl"]
            r = {**base, "stage": "2차", "window": [plo, cp], "trades": st2["trades"], "pnl": st2["pnl"],
                 "pnl_scaled": scaled, "start_equity": eq0, "signals": st2["signals"],
                 "rate": signal_rate(st2["signals"], tf, plo, cp)}
            rows[aid] = r
            tasks.append(Task(aid, "2차", tf, plo, cp, init + scaled, r["rate"]))
            continue
        # not yet judged
        r = {**base, "stage": None, "window": [lo, cp], "trades": st1["trades"], "signals": st1["signals"],
             "pnl": a["equity"] - init}
        old_enough = cp >= floor_day(lo) + PERIOD_DAYS * DAY_MS
        if not old_enough or st1["trades"] < MIN_TRADES:
            why = "30일 미만 (복사 계좌는 자기 시작부터 셈)" if not old_enough else f"거래 {st1['trades']}건 < 30건"
            if old_enough and cp - floor_day(lo) >= NO_VERDICT_DAYS * DAY_MS:
                why += f" · {NO_VERDICT_DAYS}일까지 30건 미달: 판정 불가"
            rows[aid] = {**r, "status": HOLD, "reason": why}
            continue
        r.update(stage="1차", rate=signal_rate(st1["signals"], tf, lo, cp))
        rows[aid] = r
        tasks.append(Task(aid, "1차", tf, lo, cp, a["equity"], r["rate"]))
    return rows, tasks


def run_tasks(tasks: list[Task], minutes_for: Callable[[int, int], Minutes], s: Settings, brackets: dict,
              specs: dict, n_bots: int, seed_base: int, initial: float, log=None) -> tuple[dict, list[dict]]:
    """Q1 for every task: all tasks with the same timeframe and window share one vectorised pass
    (each account gets its own ``n_bots`` bots at its own rate). Returns ({aid: p}, groups)."""
    groups: dict[tuple, list[Task]] = {}
    for t in tasks:
        groups.setdefault((t.tf, t.lo, t.hi), []).append(t)
    pvals, info = {}, []
    for (tf, lo, hi), ts in sorted(groups.items(), key=lambda kv: (kv[0][1], TF_MS[kv[0][0]])):
        t0 = time.time()
        pre = ATR_PREFIX_BARS * TF_MS[tf]
        start = lo - lo % TF_MS[tf] - pre
        m = minutes_for(start, hi)
        rates = np.repeat([t.rate for t in ts], n_bots)
        seed = [seed_base, TF_MS[tf] // MIN, lo // MIN % 2**31]
        res = simulate_bots(m, tf, lo, hi, rates, s, brackets, specs, seed=seed, initial=initial)
        for i, t in enumerate(ts):
            bots = res["equity"][i * n_bots:(i + 1) * n_bots]
            pvals[t.aid] = {"p": luck_p(t.value, bots), "bots_median": float(np.median(bots)),
                            "bots_p90": float(np.quantile(bots, 0.9)),
                            "bots_bust": float(np.mean(res["bust"][i * n_bots:(i + 1) * n_bots])),
                            "bots_trades": float(np.mean(res["trades"][i * n_bots:(i + 1) * n_bots]))}
        sec = time.time() - t0
        info.append({"timeframe": tf, "window": [lo, hi], "accounts": len(ts), "bots": len(rates),
                     "seed": seed, "seconds": round(sec, 1)})
        if log:
            log(f"Q1 {tf} {day_str(lo)}~{day_str(hi)}: {len(ts)} accounts x {n_bots} bots, {sec:.0f}s")
    return pvals, info


def decide(snap: dict, rows: dict, tasks: list[Task], pvals: dict, alpha: float = ALPHA) -> dict:
    init = snap["run"]["initial_equity"]
    tested = [t for t in tasks if t.aid in pvals]
    q, rej = bh([pvals[t.aid]["p"] for t in tested], alpha)
    for t, qi, ri in zip(tested, q, rej):
        r = rows[t.aid]
        r.update(pvals[t.aid])
        r.update(q=float(qi), luck_pass=bool(ri))
        if t.stage == "1차":
            fails = []
            if r["equity"] <= init:
                fails.append(f"평가금 ${r['equity']:,.0f} ≤ 시작 ${init:,.0f}")
            if r["bust"]:
                fails.append("파산")
            if not ri:
                fails.append(f"우연 기준 미통과 (p {r['p']:.4f}, 보정 q {qi:.3f})")
            r["status"] = PASS1 if not fails else FAIL
            r["reason"] = ("거래 %d건, 평가금 $%s, p %.4f, q %.3f" % (r["trades"], f"{r['equity']:,.0f}", r["p"], qi)
                           if not fails else "1차: " + ", ".join(fails))
        else:
            fails = []
            if r["trades"] < MIN_TRADES:
                fails.append(f"2차 기간 거래 {r['trades']}건 < 30건")
            if r["pnl"] <= 0:
                fails.append(f"2차 기간 손익 ${r['pnl']:,.0f}")
            if not ri:
                fails.append(f"우연 기준 미통과 (p {r['p']:.4f}, 보정 q {qi:.3f})")
            r["status"] = PASS2 if not fails else FAIL
            r["reason"] = ("2차 통과: 실거래 검토 대상 (거래 %d건, 손익 $%s, q %.3f)" % (r["trades"], f"{r['pnl']:,.0f}", qi)
                           if not fails else "2차: " + ", ".join(fails))
        r["decided"] = snap["date"]
    for aid, r in rows.items():
        if r.get("stage") and "status" not in r:      # a task without a p (should not happen)
            r.update(status=HOLD, reason="우연 기준 계산 없음")
    m = len(tested)
    n_rej = int(rej.sum()) if m else 0
    counts = {k: sum(1 for r in rows.values() if r["status"] == k) for k in STATUSES}
    return {"tested": m, "luck_passed": n_rej,
            "lucky_expected": round(alpha * n_rej, 3),
            "lucky_if_uncorrected": round(alpha * m, 3),
            "counts": counts}


def verdict_text(v: dict) -> str:
    """The Telegram / log summary in Korean."""
    c = v["counts"]
    head = (f"[체크포인트 {v['day']}일 · {v['date']} 09:00 KST] 판정: 1차 합격 {c[PASS1]} · 2차 통과 {c[PASS2]} · "
            f"불합격 {c[FAIL]} · 보류 {c[HOLD]} · 관찰용 {c[OBSERVE]}")
    lines = [head,
             f"우연 기준(동전 봇 {v['n_bots']:,}개, FDR {int(v['alpha'] * 100)}%): 검정 {v['tested']}개 중 통과 "
             f"{v['luck_passed']}개, 우연으로 기대되는 합격 수 ≤ {v['lucky_expected']:.1f}개 "
             f"(보정 없이 p<{v['alpha']:.2f}였다면 {v['lucky_if_uncorrected']:.1f}개)"]
    new = [(aid, r) for aid, r in v["accounts"].items() if r.get("decided") == v["date"]]
    for st in (PASS2, PASS1):
        names = [f"{aid} (q {r['q']:.3f})" for aid, r in new if r["status"] == st]
        if names:
            lines.append(f"{st}: " + ", ".join(names[:12]) + (f" 외 {len(names) - 12}개" if len(names) > 12 else ""))
    if v.get("warnings"):
        lines += ["주의: " + w for w in v["warnings"]]
    lines.append(f"스냅샷 {v['snapshot_sha256'][:12]} · 대시보드 순위표 '체크포인트 판정'")
    return "\n".join(lines)


def judge(out: sqlite3.Connection, date: str, minutes_for, s: Settings, brackets: dict, specs: dict,
          n_bots: int = N_BOTS, alpha: float = ALPHA, log=None, now_ms: Optional[int] = None) -> dict:
    """The verdict for the snapshot of ``date`` (already stored). Stored once; returns it."""
    have = out.execute("SELECT data FROM verdicts WHERE date = ?", (date,)).fetchone()
    if have is not None:
        return json.loads(have[0])
    t0 = time.time()
    snap, sha = load_snapshot(out, date)
    init = snap["run"]["initial_equity"]
    s = _settings_of(snap, s)
    prior = _prior(out, date)
    prev_snaps = {}
    for aid, pr in prior.items():
        if pr["status"] == PASS1:
            d = day_str(pr["window"][1])
            if d not in prev_snaps:
                got = load_snapshot(out, d)
                prev_snaps[d] = got[0] if got else None
    rows, tasks = plan(snap, prior, prev_snaps, s)
    seed_base = int(snap["cp_ts"] // DAY_MS)
    pvals, groups = run_tasks(tasks, minutes_for, s, brackets, specs, n_bots, seed_base, init, log)
    summary = decide(snap, rows, tasks, pvals, alpha)
    start = snap["run"]["start_ts"]
    warnings = []
    for ch in snap["run"].get("trading_changes", []):
        if start is not None and ch["ts"] > start:
            warnings.append(f"{day_str(ch['ts'])} 재시작 때 체결·청산·사이즈 관련 변경({', '.join(ch['changes'])}). "
                            "Q5: 영향받는 계좌의 기간을 그날부터 다시 세야 하는지 규칙 관리자 확인 필요")
    v = {"date": date, "cp_ts": snap["cp_ts"], "day": int((snap["cp_ts"] - floor_day(start)) // DAY_MS) if start else None,
         "snapshot_sha256": sha, "alpha": alpha, "n_bots": n_bots, "initial_equity": init,
         "groups": groups, "warnings": warnings, "accounts": rows, **summary,
         "runtime_s": round(time.time() - t0, 1)}
    v["text"] = verdict_text(v)
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    with out:
        out.execute("INSERT INTO verdicts VALUES (?,?,?,?)", (date, now, sha, canonical(v)))
        out.executemany("INSERT OR REPLACE INTO verdict_accounts VALUES (?,?,?,?,?,?,?)",
                        [(date, aid, r["status"], r.get("stage"), r.get("p"), r.get("q"), canonical(r))
                         for aid, r in rows.items()])
    return v


def _settings_of(snap: dict, s: Settings) -> Settings:
    from dataclasses import replace
    return replace(s, taker_fee=snap["run"]["taker_fee"], slippage_frac=snap["run"]["slippage"],
                   initial_equity=snap["run"]["initial_equity"])


# ====================================================================== the job
def run_due(paper_db: str, out_path: str, minutes_for, s: Settings, brackets: dict, specs: dict,
            notifier=None, now_ms: Optional[int] = None, only: Optional[str] = None,
            n_bots: int = N_BOTS, log=print) -> list[dict]:
    """Freeze and judge every due checkpoint that has no verdict yet. paper3.db is read only."""
    conn = ro_connect(paper_db)
    out = open_out(out_path)
    done = []
    try:
        facts = run_facts(conn)
        if facts["start_ts"] is None:
            log("no run in this database yet")
            return done
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        for k, cp in due_checkpoints(facts["start_ts"], now):
            date = day_str(cp)
            if only and date != only:
                continue
            if out.execute("SELECT 1 FROM verdicts WHERE date = ?", (date,)).fetchone():
                continue
            if load_snapshot(out, date) is None:
                snap = freeze_snapshot(conn, cp, settings=s)
                if snap is None:
                    msg = (f"[체크포인트 {k * PERIOD_DAYS}일 · {date}] paper3.db에 그날 00:00 상태(day:{date})가 "
                           "아직 없습니다. 봇이 그 시각을 처리하면 다음 실행에서 판정합니다")
                    _log_once(out, date, msg, notifier, now)
                    log(msg)
                    break
                sha = store_snapshot(out, snap, now)
                log(f"snapshot {date} frozen: {len(snap['accounts'])} accounts, sha256 {sha}")
            v = judge(out, date, minutes_for, s, brackets, specs, n_bots=n_bots, log=log, now_ms=now)
            log(v["text"])
            if notifier is not None:
                notifier.send(INFO, v["text"])
            done.append(v)
    finally:
        conn.close()
        out.close()
    return done


def _log_once(out, date, msg, notifier, now) -> None:
    if out.execute("SELECT 1 FROM job_log WHERE date = ? AND text = ?", (date, msg)).fetchone():
        return
    out.execute("INSERT INTO job_log VALUES (?,?,?)", (now, date, msg))
    out.commit()
    if notifier is not None:
        notifier.send(WARN, msg)


# ====================================================================== read API (agents, dashboard)
def _ro_out(path: str) -> Optional[sqlite3.Connection]:
    if not path or not os.path.exists(path):
        return None
    try:
        return ro_connect(path)
    except sqlite3.Error:
        return None


def latest_verdict(path: str) -> Optional[dict]:
    """The newest checkpoint verdict (dict, see ``judge``), or None. Read-only."""
    c = _ro_out(path)
    if c is None:
        return None
    try:
        r = c.execute("SELECT data FROM verdicts ORDER BY date DESC LIMIT 1").fetchone()
        return None if r is None else json.loads(r[0])
    except sqlite3.OperationalError:
        return None
    finally:
        c.close()


def verdict(path: str, date: str) -> Optional[dict]:
    c = _ro_out(path)
    if c is None:
        return None
    try:
        r = c.execute("SELECT data FROM verdicts WHERE date = ?", (date,)).fetchone()
        return None if r is None else json.loads(r[0])
    except sqlite3.OperationalError:
        return None
    finally:
        c.close()


def statuses(path: str) -> dict[str, str]:
    """{account_id: status} from the newest verdict ('보류', '1차 합격', '불합격', '2차 통과', '관찰용')."""
    v = latest_verdict(path)
    return {} if v is None else {aid: r["status"] for aid, r in v["accounts"].items()}


def account_status(path: str, account_id: str) -> Optional[dict]:
    """One account's row in the newest verdict (status, stage, trades, p, q, reason ...)."""
    v = latest_verdict(path)
    if v is None or account_id not in v["accounts"]:
        return None
    return {"date": v["date"], "account_id": account_id, **v["accounts"][account_id]}


def dashboard_view(path: str) -> dict:
    """Compact JSON for the dashboard section (newest verdict, sorted rows)."""
    v = latest_verdict(path)
    if v is None:
        return {"ready": False}
    order = {PASS2: 0, PASS1: 1, FAIL: 2, HOLD: 3, OBSERVE: 4}
    rows = []
    for aid, r in v["accounts"].items():
        rows.append({"account_id": aid, "status": r["status"], "stage": r.get("stage"), "timeframe": r["timeframe"],
                     "trades": r.get("trades", r.get("trades_total")), "equity": r.get("equity"),
                     "pnl": r.get("pnl"), "p": r.get("p"), "q": r.get("q"), "reason": r.get("reason", "")})
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["q"] if r["q"] is not None else 2, r["account_id"]))
    return {"ready": True, "date": v["date"], "day": v.get("day"), "counts": v["counts"], "tested": v["tested"],
            "luck_passed": v["luck_passed"], "lucky_expected": v["lucky_expected"],
            "lucky_if_uncorrected": v["lucky_if_uncorrected"], "alpha": v["alpha"], "n_bots": v["n_bots"],
            "snapshot_sha256": v["snapshot_sha256"], "warnings": v.get("warnings", []), "rows": rows}


# ====================================================================== CLI
def _show(out_path: str, date: Optional[str]) -> int:
    v = verdict(out_path, date) if date else latest_verdict(out_path)
    if v is None:
        print("판정 없음")
        return 1
    print(v["text"])
    for aid, r in sorted(v["accounts"].items(), key=lambda kv: (STATUSES.index(kv[1]["status"]), kv[0])):
        p = "" if r.get("p") is None else f" p {r['p']:.4f} q {r['q']:.3f}"
        print(f"  {r['status']:6s} {aid:28s}{p}  {r.get('reason', '')}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "show"])
    ap.add_argument("--db", default="paper3.db")
    ap.add_argument("--out", default="checkpoint.db")
    ap.add_argument("--cache", default=None, help="1m bar cache directory (default: <out dir>/checkpoint_bars)")
    ap.add_argument("--date", help="only this checkpoint (YYYY-MM-DD)")
    ap.add_argument("--bots", type=int, default=N_BOTS)
    ap.add_argument("--brackets")
    ap.add_argument("--allow-example-brackets", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "show":
        return _show(args.out, args.date)
    from .live import _notifier, _rest, load_brackets
    rest = _rest()
    conn = ro_connect(args.db)
    fee = run_facts(conn)["taker_fee"]
    conn.close()
    s = v3_settings(**({"taker_fee": fee} if fee else {}))
    brackets, _ = load_brackets(rest, list(V3_SYMBOLS), args.brackets, args.allow_example_brackets)
    specs = rest.exchange_info(list(V3_SYMBOLS))
    cache = args.cache or os.path.join(os.path.dirname(os.path.abspath(args.out)), "checkpoint_bars")
    src = BinanceMinutes(rest, cache)
    run_due(args.db, args.out, src.load, s, brackets, specs, None if args.no_notify else _notifier(),
            only=args.date, n_bots=args.bots)
    return 0


if __name__ == "__main__":
    sys.exit(main())
