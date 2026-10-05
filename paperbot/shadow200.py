"""Record-only forward test ("shadow") of the 342 pre-registered DeepSeek-200 configurations.

    python -m paperbot.shadow200 run      [--db FILE] [--bars-dir DIR]      the 15-minute job (deploy/paperbot-shadow200.*)
    python -m paperbot.shadow200 backfill [--db FILE] [--bars-dir DIR]      same, every bar and signal marked "backfill"
    python -m paperbot.shadow200 stage prune1|prune2|judge1|judge2 [--db FILE] [--bots N] [--dry-run]
    python -m paperbot.shadow200 interim  [--db FILE]                        survivors' numbers since day 60 (information only)
    python -m paperbot.shadow200 status   [--db FILE]                        health and counts, never a performance number
    python -m paperbot.shadow200 parity   [--pre-dir DIR] [--results CSV]    reproduce the 5-year period-3 numbers

What it is (research/deepseek200/FORWARD_PREREG.md, plan: FORWARD_TEST_PLAN.md): the signal code of
research/deepseek200/lib_c.py (read, never changed) is run on closed bars of six USDT-M coins on 15m, 30m, 1h and 4h; every
signal is stored once, immutably; hypothetical trades of the two exits X5_TRAIL2 and X2_SL15_TP3 are simulated with the locked
backtest engine (same costs as the 5-year test). No account, no order, no Telegram, no key: it reads public klines only, and
its only file is its own database. The job is idempotent: signals depend only on closed bars and a fixed anchor, trades are
recomputed from stored signals and bars, so a missed run is healed by the next one and a backfill gives the same values.

Pins: the job refuses to run when lib_c.py differs from the hash in research/deepseek200/out/summary.json, or when
PREREG_DEEPSEEK200.md / FORWARD_PREREG.md differ from their .sha256 files (``verify_pins``).

Stages (days from T0 = 2026-10-05 00:00 UTC; each one is computed once and stored in an append-only table):
    prune1 (day 30), prune2 (day 60), judge1 (day 120, days 60-120 only), judge2 (day 180, days 120-180 only).
``run`` executes a due stage by itself once every series has bars through its cutoff; the same stage can be run by hand.
One writer: the job holds a ``flock`` on the database file, a second job exits quietly.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import time
from typing import Callable, Iterable, Optional

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEEP = os.path.join(ROOT, "research", "deepseek200")
LIB_C = os.path.join(DEEP, "lib_c.py")
FORWARD_PREREG = os.path.join(DEEP, "FORWARD_PREREG.md")
FORWARD_SHA = os.path.join(DEEP, "FORWARD_PREREG.sha256")
PREREG0 = os.path.join(DEEP, "PREREG_DEEPSEEK200.md")
PREREG0_SHA = os.path.join(DEEP, "PREREG_DEEPSEEK200.sha256")
SUMMARY = os.path.join(DEEP, "out", "summary.json")
RESULTS = os.path.join(DEEP, "out", "results.csv")
PRE_DIR = os.path.join(ROOT, "data", "pre2021")
DEFAULT_DB = "/var/lib/paperbot/shadow200/shadow200.db"

MIN_MS = 60_000
DAY_MS = 86_400_000
T0_MS = int(dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc).timestamp() * 1000)          # day 0 = the live run's day 0
ANCHOR_MS = int(dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)       # fixed start of every series
COINS = {"BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT", "DOGEUSD": "DOGEUSDT",
         "LTCUSD": "LTCUSDT", "BCHUSD": "BCHUSDT"}
TFS = ("15m", "30m", "1h", "4h")
TF_MS = {"15m": 15 * MIN_MS, "30m": 30 * MIN_MS, "1h": 60 * MIN_MS, "4h": 240 * MIN_MS}
JUDGED_TFS = ("15m", "30m", "1h")          # 4h: observation only
SETTLE_MS = 8_000                           # a bar is read this long after its close
LIVE_GRACE_MS = 30 * MIN_MS                 # a bar first seen later than this after its close is a backfill bar
STALE_MS = 2 * 3_600_000                    # a series this far behind makes the run fail (alert)
STAGES = ("prune1", "prune2", "judge1", "judge2")


@dataclasses.dataclass(frozen=True)
class Params:
    """The pre-registered numbers (FORWARD_PREREG.md). Tests change them; the production database stores these."""
    stage_days: tuple = (30, 60, 120, 180)
    k_survivors: int = 30
    family_cap: int = 3
    def_tf_cap: int = 1
    p1_min_trades: int = 50
    p1_p: float = 0.01
    p2_min_trades: int = 30
    j_min_trades: int = 100
    coins_positive_min: int = 4
    coin_min_trades: int = 10
    alpha: float = 0.10
    j2_alpha: float = 0.05
    n_total: int = 498
    stress_extra: float = 0.0007            # round trip 0.14% -> 0.21%: 0.07 percentage points more per trade
    bots: int = 2000
    tfs: tuple = TFS
    coins: tuple = tuple(COINS)
    drop_no_trade: bool = True

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "Params":
        d = json.loads(text)
        for k in ("stage_days", "tfs", "coins"):
            d[k] = tuple(d[k])
        return cls(**d)


class PinError(RuntimeError):
    pass


class Busy(RuntimeError):
    pass


class StageError(RuntimeError):
    pass


# ====================================================================== pins
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha_listing(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read().split()[0].strip().lower()


def verify_pins(lib_c: str = LIB_C, summary: str = SUMMARY, prereg0: str = PREREG0, prereg0_sha: str = PREREG0_SHA,
                forward: str = FORWARD_PREREG, forward_sha: str = FORWARD_SHA) -> dict:
    """The three hashes this test stands on; raises PinError when one differs (or a file is missing)."""
    try:
        want_lib = json.load(open(summary, encoding="utf-8"))["code_sha256"]["lib_c.py"]
        got = {"lib_c": sha256_file(lib_c), "prereg0": sha256_file(prereg0), "forward": sha256_file(forward)}
        want = {"lib_c": want_lib, "prereg0": _sha_listing(prereg0_sha), "forward": _sha_listing(forward_sha)}
    except (OSError, KeyError, ValueError, IndexError) as exc:
        raise PinError(f"pin files unreadable: {type(exc).__name__}: {exc}") from exc
    bad = [k for k in got if got[k] != want[k]]
    if bad:
        raise PinError("hash differs from the pre-registration: " + ", ".join(
            f"{k} (is {got[k][:12]}, should be {want[k][:12]})" for k in bad))
    return got


_LIBC = None


def load_lib_c(path: str = LIB_C):
    """research/deepseek200/lib_c.py loaded from its file (no sys.path edit of ours); cached."""
    global _LIBC
    if _LIBC is None:
        spec = importlib.util.spec_from_file_location("lib_c_deepseek200", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["lib_c_deepseek200"] = mod
        spec.loader.exec_module(mod)
        _LIBC = mod
    return _LIBC


# ====================================================================== database
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bars (
  coin TEXT NOT NULL, tf TEXT NOT NULL, open_ms INTEGER NOT NULL,
  open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL,
  seen_ms INTEGER NOT NULL, backfill INTEGER NOT NULL, PRIMARY KEY (coin, tf, open_ms)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS signals (
  tf TEXT NOT NULL, def TEXT NOT NULL, coin TEXT NOT NULL, open_ms INTEGER NOT NULL, side INTEGER NOT NULL,
  atr REAL, computed_ms INTEGER NOT NULL, backfill INTEGER NOT NULL, code_sha TEXT,
  PRIMARY KEY (tf, def, coin, open_ms)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS marks (coin TEXT NOT NULL, tf TEXT NOT NULL, open_ms INTEGER NOT NULL, PRIMARY KEY (coin, tf));
CREATE TABLE IF NOT EXISTS trades (
  tf TEXT NOT NULL, def TEXT NOT NULL, exit TEXT NOT NULL, coin TEXT NOT NULL, signal_ms INTEGER NOT NULL,
  side INTEGER NOT NULL, entry_ms INTEGER NOT NULL, exit_ms INTEGER NOT NULL, entry_px REAL, exit_px REAL,
  gross REAL, fee REAL, funding REAL, net REAL NOT NULL, reason TEXT, hold INTEGER, backfill INTEGER NOT NULL,
  PRIMARY KEY (tf, def, exit, coin, signal_ms)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS open_trades (
  tf TEXT NOT NULL, def TEXT NOT NULL, exit TEXT NOT NULL, coin TEXT NOT NULL, signal_ms INTEGER NOT NULL,
  side INTEGER NOT NULL, entry_ms INTEGER NOT NULL, PRIMARY KEY (tf, def, exit, coin, signal_ms)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS snapshots (
  stage TEXT PRIMARY KEY, created_ms INTEGER NOT NULL, cutoff_ms INTEGER NOT NULL, input_sha TEXT NOT NULL,
  result_json TEXT NOT NULL, result_sha TEXT NOT NULL, code_sha TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, level TEXT NOT NULL, code TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, kind TEXT NOT NULL, pins TEXT, versions TEXT, note TEXT);
"""


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.executescript(SCHEMA)
    return conn


@contextlib.contextmanager
def writer_lock(path: str):
    """One writer: an exclusive flock on the database file itself (as paperbot.live3.single_runner_lock)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fh = os.fdopen(os.open(path, os.O_RDONLY | os.O_CREAT, 0o644), "rb")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise Busy(f"another shadow200 job holds {path}")
    try:
        yield
    finally:
        fh.close()


def event(conn: sqlite3.Connection, now_ms: int, level: str, code: str, detail: str = "") -> None:
    conn.execute("INSERT INTO events (ts, level, code, detail) VALUES (?,?,?,?)", (now_ms, level, code, detail[:500]))


def meta_get(conn, key: str) -> Optional[str]:
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else None


def init_meta(conn: sqlite3.Connection, prm: Params, t0_ms: int, anchor_ms: int, now_ms: int) -> None:
    """First run: write T0, anchor and the parameters. Later runs: they must be exactly the same."""
    have = meta_get(conn, "t0_ms")
    if have is None:
        conn.executemany("INSERT INTO meta VALUES (?,?)", [("t0_ms", str(t0_ms)), ("anchor_ms", str(anchor_ms)),
                                                           ("params", prm.to_json()), ("created_ms", str(now_ms))])
        conn.commit()
        return
    if (int(have), int(meta_get(conn, "anchor_ms")), meta_get(conn, "params")) != (t0_ms, anchor_ms, prm.to_json()):
        raise PinError("this database was made with other T0, anchor or parameters; start a new database "
                       "(a change of the pre-registration is a new test)")


def load_meta(conn: sqlite3.Connection) -> tuple[Params, int, int]:
    t0 = meta_get(conn, "t0_ms")
    if t0 is None:
        raise StageError("empty database: run `run` or `backfill` first")
    return Params.from_json(meta_get(conn, "params")), int(t0), int(meta_get(conn, "anchor_ms"))


# ====================================================================== bar sources
class BinanceSource:
    """Public klines (no key), closed bars only are used by the caller."""

    def __init__(self, rest=None):
        if rest is None:
            from .binance import BinanceREST
            rest = BinanceREST()
        self.rest = rest

    def klines(self, coin: str, tf: str, start_ms: int, limit: int = 1500) -> list:
        return self.rest.klines(COINS[coin], tf, start_time=start_ms, limit=limit)


class FrameSource:
    """Bars from DataFrames {(coin, tf): frame(ts, open, high, low, close, volume)} (tests, backfill from files)."""

    def __init__(self, frames: dict):
        self.rows = {}
        for key, df in frames.items():
            ts = pd.to_datetime(df["ts"], utc=True)
            ms = ((ts - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(np.int64)
            span = TF_MS[key[1]]
            order = np.argsort(ms, kind="stable")
            self.rows[key] = [[int(ms[i]), float(df["open"].iloc[i]), float(df["high"].iloc[i]), float(df["low"].iloc[i]),
                               float(df["close"].iloc[i]), float(df["volume"].iloc[i]), int(ms[i]) + span - 1]
                              for i in order]
            self.rows[key] = [r for k, r in enumerate(self.rows[key]) if k == 0 or r[0] != self.rows[key][k - 1][0]]
        self.starts = {k: np.array([r[0] for r in v], dtype=np.int64) for k, v in self.rows.items()}

    def klines(self, coin: str, tf: str, start_ms: int, limit: int = 1500) -> list:
        rows = self.rows.get((coin, tf), [])
        i = int(np.searchsorted(self.starts.get((coin, tf), np.zeros(0, np.int64)), start_ms, side="left"))
        return rows[i:i + limit]


def csv_source(bars_dir: str, coins: Iterable[str], tfs: Iterable[str]) -> FrameSource:
    """Bar files named <coin>-<tf>.csv.gz (the research layout: ts, open, high, low, close, volume)."""
    frames = {}
    for coin in coins:
        for tf in tfs:
            p = os.path.join(bars_dir, f"{coin.lower()}-{tf}.csv.gz")
            if os.path.exists(p):
                frames[(coin, tf)] = pd.read_csv(p)
    return FrameSource(frames)


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a))


def fetch_series(conn: sqlite3.Connection, source, coin: str, tf: str, anchor_ms: int, now_ms: int,
                 flag_all: bool = False, pause: float = 0.0, sleep: Callable[[float], None] = time.sleep) -> tuple[int, int]:
    """Closed bars since the last stored one (the last three are read again and compared: a differing bar is an event,
    the stored bar stays). Returns (new bars, revised bars)."""
    span = TF_MS[tf]
    last = conn.execute("SELECT MAX(open_ms) FROM bars WHERE coin=? AND tf=?", (coin, tf)).fetchone()[0]
    start = anchor_ms if last is None else max(anchor_ms, last - 2 * span)
    new = revised = 0
    while True:
        rows = source.klines(coin, tf, start, 1500)
        closed = [r for r in rows if int(r[6]) + SETTLE_MS <= now_ms and int(r[0]) >= start]
        for r in closed:
            o = int(r[0])
            cur = conn.execute("SELECT open, high, low, close, volume FROM bars WHERE coin=? AND tf=? AND open_ms=?",
                               (coin, tf, o)).fetchone()
            vals = tuple(float(x) for x in r[1:6])
            if cur is None:
                bf = 1 if (flag_all or now_ms - (o + span) > LIVE_GRACE_MS) else 0
                conn.execute("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?)", (coin, tf, o, *vals, now_ms, bf))
                new += 1
            elif not all(_same(a, b) for a, b in zip(cur, vals)):
                revised += 1
                event(conn, now_ms, "WARN", "bar_revised", f"{coin} {tf} {o}: stored {cur} now {vals}; stored bar kept")
        if len(rows) < 1500 or not closed:
            break
        start = int(closed[-1][0]) + span
        if pause:
            sleep(pause)
    conn.commit()
    return new, revised


def load_frame(conn: sqlite3.Connection, coin: str, tf: str, upto_close_ms: Optional[int] = None,
               drop_no_trade: bool = True) -> pd.DataFrame:
    """The series as lib_c wants it (ts, OHLCV; bars without trades dropped as in the 5-year bar files), plus open_ms."""
    span = TF_MS[tf]
    q = "SELECT open_ms, open, high, low, close, volume FROM bars WHERE coin=? AND tf=?"
    args: list = [coin, tf]
    if upto_close_ms is not None:
        q += " AND open_ms <= ?"
        args.append(upto_close_ms - span)
    rows = conn.execute(q + " ORDER BY open_ms", args).fetchall()
    a = np.array(rows, dtype=float).reshape(-1, 6)
    df = pd.DataFrame({"ts": pd.to_datetime(a[:, 0].astype(np.int64), unit="ms", utc=True), "open": a[:, 1], "high": a[:, 2],
                       "low": a[:, 3], "close": a[:, 4], "volume": a[:, 5], "open_ms": a[:, 0].astype(np.int64)})
    if drop_no_trade:
        df = df.loc[df["volume"].to_numpy(float) > 0].reset_index(drop=True)
    df.attrs["tf"] = tf
    return df


# ====================================================================== signals
def compute_entries(C, df: pd.DataFrame, btc: Optional[pd.DataFrame], coin: str, tf: str) -> tuple[dict, list]:
    """{definition: (long, short)} of lib_c on the whole anchored series. BTC is passed as a frame of its own timestamps
    (lib_c matches by timestamp); if it is empty or lib_c fails with it, F14_SMT alone is lost (reported), not the rest."""
    notes: list = []
    ctx = None
    if coin != "BTCUSD":
        if btc is not None and len(btc):
            ctx = {"BTCUSD": btc}
        else:
            notes.append("F14_SMT: no BTC bars")
    try:
        return C.entries(df, tf, ctx, coin), notes
    except Exception as exc:  # noqa: BLE001
        if ctx is None:
            raise
        notes.append(f"F14_SMT context failed ({type(exc).__name__}: {exc})"[:200])
        return C.entries(df, tf, None, coin), notes


def update_signals(conn: sqlite3.Connection, C, prm: Params, coin: str, tf: str, t0_ms: int, now_ms: int,
                   code_sha: str, flag_all: bool = False) -> tuple[int, bool]:
    """Store the signals of every bar since the series' watermark (bars from T0 on; immutable: INSERT OR IGNORE, and the
    last 300 stored bars are compared again, a difference is an event). Returns (new signal rows, whether new bars were seen)."""
    df = load_frame(conn, coin, tf, drop_no_trade=prm.drop_no_trade)
    if not len(df):
        return 0, False
    open_ms = df["open_ms"].to_numpy(np.int64)
    r = conn.execute("SELECT open_ms FROM marks WHERE coin=? AND tf=?", (coin, tf)).fetchone()
    wm = r[0] if r else None
    if wm is not None and open_ms[-1] <= wm:
        return 0, False
    btc = load_frame(conn, "BTCUSD", tf, drop_no_trade=prm.drop_no_trade) if coin != "BTCUSD" else None
    ent, notes = compute_entries(C, df, btc, coin, tf)
    for note in notes:
        event(conn, now_ms, "WARN", "signal_note", f"{coin} {tf}: {note}")
    atr = C.env()["fg"].atr(df, 14).to_numpy(float)
    in_fwd = open_ms >= t0_ms
    new_mask = in_fwd if wm is None else (in_fwd & (open_ms > wm))
    chk_mask = np.zeros(len(df), bool) if wm is None else (in_fwd & (open_ms <= wm) & (open_ms > wm - 300 * TF_MS[tf]))
    rows, seen = [], set()
    for name, (lg, sh) in ent.items():
        for i in np.flatnonzero((lg | sh) & new_mask):
            rows.append((tf, name, coin, int(open_ms[i]), 1 if lg[i] else -1,
                         float(atr[i]) if np.isfinite(atr[i]) else None, now_ms, 1 if flag_all or now_ms - (open_ms[i] + TF_MS[tf]) > LIVE_GRACE_MS else 0, code_sha))
        if chk_mask.any():
            for i in np.flatnonzero((lg | sh) & chk_mask):
                seen.add((name, int(open_ms[i]), 1 if lg[i] else -1))
    if chk_mask.any():
        lo_ms, hi_ms = int(open_ms[chk_mask][0]), int(open_ms[chk_mask][-1])
        have = {(d, o, s) for d, o, s in conn.execute(
            "SELECT def, open_ms, side FROM signals WHERE coin=? AND tf=? AND open_ms BETWEEN ? AND ?", (coin, tf, lo_ms, hi_ms))}
        if have != seen:
            event(conn, now_ms, "CRITICAL", "signal_changed",
                  f"{coin} {tf}: {len(have - seen)} stored signals not recomputed, {len(seen - have)} new in old bars; stored kept")
    conn.executemany("INSERT OR IGNORE INTO signals VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("INSERT OR REPLACE INTO marks VALUES (?,?,?)", (coin, tf, int(open_ms[-1])))
    conn.commit()
    return len(rows), True


def signal_arrays(conn: sqlite3.Connection, coin: str, tf: str, open_ms: np.ndarray, defs: Optional[set] = None) -> dict:
    """{definition: (long bool array, short bool array)} on the frame with this ``open_ms`` from the stored signals."""
    n = len(open_ms)
    out: dict = {}
    q = "SELECT def, open_ms, side FROM signals WHERE coin=? AND tf=?"
    for name, ms, side in conn.execute(q, (coin, tf)):
        if defs is not None and name not in defs:
            continue
        i = int(np.searchsorted(open_ms, ms))
        if i >= n or open_ms[i] != ms:
            continue
        lg, sh = out.setdefault(name, (np.zeros(n, bool), np.zeros(n, bool)))
        (lg if side > 0 else sh)[i] = True
    return out


# ====================================================================== trades (the locked engine)
def run_exits(C, df: pd.DataFrame, atr: np.ndarray, lg, sh, tf: str, lo: int, hi: Optional[int], exits: Optional[set] = None) -> dict:
    L = C.env()["L"]
    out = {}
    for xname, cfg, mh in C.exit_cfgs():
        if exits is None or xname in exits:
            out[xname] = L.run_backtest(df, atr, lg, sh, cfg, L._cost(tf, mh), lo, hi)
    return out


def _trade_rows(t: pd.DataFrame, open_ms: np.ndarray, tf: str, max_hold: int) -> pd.DataFrame:
    if not len(t):
        return pd.DataFrame()
    span = TF_MS[tf]
    ei, si = t["entry_idx"].to_numpy(int), t["signal_idx"].to_numpy(int)
    reason = t["reason"].to_numpy(object)
    closed = (reason != "EOD") | (t["hold"].to_numpy(int) >= max_hold)
    return pd.DataFrame({"side": t["side"].to_numpy(int), "signal_ms": open_ms[si], "sig_close_ms": open_ms[si] + span,
                         "entry_ms": open_ms[ei], "exit_ms": open_ms[t["exit_idx"].to_numpy(int)],
                         "entry_px": t["entry_px"].to_numpy(float), "exit_px": t["exit_px"].to_numpy(float),
                         "gross": t["gross"].to_numpy(float), "fee": t["fee"].to_numpy(float),
                         "funding": t["funding"].to_numpy(float), "net": t["net"].to_numpy(float), "reason": reason,
                         "hold": t["hold"].to_numpy(int), "closed": closed})


def update_trades(conn: sqlite3.Connection, C, prm: Params, coin: str, tf: str, t0_ms: int, now_ms: int) -> tuple[int, int]:
    """The continuous hypothetical trades of (coin, tf) from T0 (audit table; the stages recompute their own windows).
    Closed ones are stored once; open ones are kept in ``open_trades``. Returns (closed new, open)."""
    df = load_frame(conn, coin, tf, drop_no_trade=prm.drop_no_trade)
    n = len(df)
    if n < 2:
        return 0, 0
    open_ms = df["open_ms"].to_numpy(np.int64)
    arrays = signal_arrays(conn, coin, tf, open_ms)
    atr = C.env()["fg"].atr(df, 14).to_numpy(float)
    lo = int(np.searchsorted(open_ms, t0_ms, side="left"))
    conn.execute("DELETE FROM open_trades WHERE coin=? AND tf=?", (coin, tf))
    have = {(d, x, m): net for d, x, m, net in conn.execute("SELECT def, exit, signal_ms, net FROM trades WHERE tf=? AND coin=?", (tf, coin))}
    ins, opn = [], []
    for name, (lg, sh) in arrays.items():
        for xname, t in run_exits(C, df, atr, lg, sh, tf, lo, None).items():
            tr = _trade_rows(t, open_ms, tf, C.MAX_HOLD)
            for r in tr.itertuples(index=False):
                key = (name, xname, int(r.signal_ms))
                if r.closed:
                    if key not in have:
                        late = 1 if now_ms - (int(r.exit_ms) + TF_MS[tf]) > LIVE_GRACE_MS else 0
                        ins.append((tf, name, xname, coin, int(r.signal_ms), int(r.side), int(r.entry_ms), int(r.exit_ms),
                                    float(r.entry_px), float(r.exit_px), float(r.gross), float(r.fee), float(r.funding),
                                    float(r.net), str(r.reason), int(r.hold), late))
                    elif not _same(have[key], float(r.net)):
                        event(conn, now_ms, "CRITICAL", "trade_changed", f"{tf} {name} {xname} {coin} {int(r.signal_ms)}")
                else:
                    opn.append((tf, name, xname, coin, int(r.signal_ms), int(r.side), int(r.entry_ms)))
    conn.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ins)
    conn.executemany("INSERT OR REPLACE INTO open_trades VALUES (?,?,?,?,?,?,?)", opn)
    conn.commit()
    return len(ins), len(opn)


# ====================================================================== statistics
def cluster_stats(net: np.ndarray, entry_ms: np.ndarray) -> dict:
    """mean, entry-day clustered standard error and one-sided p (mean > 0): the same formula as research/search
    ``mean_test`` (tests compare them); plus the other side (mean < 0)."""
    from scipy.stats import norm
    n = len(net)
    if n == 0:
        return {"n": 0, "mean": None, "se": None, "t": None, "p_win": 1.0, "p_loss": 1.0}
    m = float(net.mean())
    day = np.asarray(entry_ms, np.int64) // DAY_MS
    g = pd.Series(net - m).groupby(day).sum().to_numpy()
    se = float(np.sqrt((g ** 2).sum()) / n)
    if se <= 0:
        return {"n": n, "mean": m, "se": se, "t": None, "p_win": 1.0, "p_loss": 1.0}
    z = m / se
    return {"n": n, "mean": m, "se": se, "t": float(z), "p_win": float(norm.sf(z)), "p_loss": float(norm.cdf(z))}


def bh_reject(p: Iterable[float], alpha: float, m_total: Optional[int] = None) -> np.ndarray:
    """Benjamini-Hochberg step-up: the k smallest p are rejected, k = max{i: p_(i) <= i alpha / m_total}.
    ``m_total`` (default: len(p)) can be larger than len(p): the missing hypotheses count as p = 1."""
    p = np.asarray(list(p), float)
    m = len(p) if m_total is None else int(m_total)
    rej = np.zeros(len(p), bool)
    if not len(p):
        return rej
    order = np.argsort(p, kind="mergesort")
    ok = np.flatnonzero(p[order] <= np.arange(1, len(p) + 1) * alpha / m)
    if len(ok):
        rej[order[: ok[-1] + 1]] = True
    return rej


def week_index(ms: np.ndarray) -> np.ndarray:
    return (np.asarray(ms, np.int64) // DAY_MS + 3) // 7                 # Monday-based UTC week


def config_id(tf: str, name: str, exit_: str) -> str:
    return f"{tf}|{name}|{exit_}"


def judged_configs(C, prm: Params) -> list[tuple[str, str, str]]:
    return [c for c in C.config_list() if c[0] in JUDGED_TFS and c[0] in prm.tfs]


def window_trades(conn: sqlite3.Connection, C, prm: Params, lo_ms: int, hi_ms: int, configs: Optional[set] = None):
    """Fresh hypothetical trades of the configs (ids "tf|def|exit"; default: the judged ones) whose signal bar closes in
    [lo_ms, hi_ms): the engine starts flat at lo_ms and sees only bars closed by hi_ms (a trade still open then is valued
    at the last close, costs included, and counts in the window it was entered in). Returns (trades DataFrame, contexts)."""
    wanted = {(c[0], c[1], c[2]) for c in judged_configs(C, prm)} if configs is None else {tuple(c.split("|")) for c in configs}
    parts, ctxs = [], {}
    for tf in sorted({w[0] for w in wanted}):
        defs = {w[1] for w in wanted if w[0] == tf}
        for coin in prm.coins:
            df = load_frame(conn, coin, tf, upto_close_ms=hi_ms, drop_no_trade=prm.drop_no_trade)
            n = len(df)
            if n < 2:
                continue
            open_ms = df["open_ms"].to_numpy(np.int64)
            lo = int(np.searchsorted(open_ms + TF_MS[tf], lo_ms, side="left"))
            atr = C.env()["fg"].atr(df, 14).to_numpy(float)
            arrays = signal_arrays(conn, coin, tf, open_ms, defs)
            ctxs[(tf, coin)] = {"df": df, "atr": atr, "lo": lo, "n": n, "arrays": arrays}
            for name, (lg, sh) in arrays.items():
                xs = {w[2] for w in wanted if w[0] == tf and w[1] == name}
                if not xs:
                    continue
                for xname, t in run_exits(C, df, atr, lg, sh, tf, lo, n, xs).items():
                    tr = _trade_rows(t, open_ms, tf, C.MAX_HOLD)
                    if len(tr):
                        tr.insert(0, "coin", coin)
                        tr.insert(0, "exit", xname)
                        tr.insert(0, "def", name)
                        tr.insert(0, "tf", tf)
                        parts.append(tr)
    cols = ["tf", "def", "exit", "coin", "side", "signal_ms", "sig_close_ms", "entry_ms", "exit_ms", "entry_px", "exit_px",
            "gross", "fee", "funding", "net", "reason", "hold", "closed"]
    return (pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)), ctxs


def trades_sha(tr: pd.DataFrame) -> str:
    """Hash of the trade list a stage used (sorted, numbers as text)."""
    h = hashlib.sha256()
    if len(tr):
        t = tr.sort_values(["tf", "def", "exit", "coin", "signal_ms"])
        for r in t[["tf", "def", "exit", "coin", "signal_ms", "side", "entry_ms", "exit_ms", "net"]].itertuples(index=False):
            h.update(("|".join(map(str, r)) + "\n").encode())
    return h.hexdigest()


def per_config(tr: pd.DataFrame) -> dict:
    out = {}
    if not len(tr):
        return out
    for (tf, name, x), g in tr.groupby(["tf", "def", "exit"], sort=True):
        out[config_id(tf, name, x)] = cluster_stats(g["net"].to_numpy(float), g["entry_ms"].to_numpy(np.int64))
    return out


def guards(g: pd.DataFrame, lo_ms: int, hi_ms: int, prm: Params) -> dict:
    """Breadth and cost checks of one config's trades in a fresh window (FORWARD_PREREG 5-4 items 1, 4, 5)."""
    net = g["net"].to_numpy(float)
    stress = float((net - prm.stress_extra).mean()) if len(net) else None
    per_coin = [(len(c) >= prm.coin_min_trades and float(c["net"].mean()) > 0) for _, c in g.groupby("coin")]
    mid = lo_ms + (hi_ms - lo_ms) // 2
    a, b = g[g["sig_close_ms"] < mid]["net"], g[g["sig_close_ms"] >= mid]["net"]
    halves = [float(a.mean()) if len(a) else None, float(b.mean()) if len(b) else None]
    best_week_removed = None
    if len(g):
        wk = week_index(g["entry_ms"].to_numpy(np.int64))
        sums = pd.Series(net).groupby(wk).sum()
        rest = net[wk != sums.idxmax()]
        best_week_removed = float(rest.mean()) if len(rest) else None
    return {"n_ok": len(g) >= prm.j_min_trades, "stress_mean": stress, "stress_ok": stress is not None and stress > 0,
            "coins_positive": int(sum(per_coin)), "coins_ok": sum(per_coin) >= prm.coins_positive_min,
            "halves": halves, "halves_ok": all(h is not None and h > 0 for h in halves),
            "best_week_removed_mean": best_week_removed, "week_ok": best_week_removed is not None and best_week_removed > 0}


def coin_flip_p(C, ctxs: dict, tf: str, name: str, exit_: str, cfg_mean: float, prm: Params, seed_text: str,
                bots: Optional[int] = None) -> Optional[float]:
    """Coin-flip luck test (as paperbot.checkpoint Q1): ``bots`` random-signal bots on the same bars, window, exit and costs.
    Each bar of each coin fires with the config's own signal frequency (signals / (coins x bars) in the window) and goes long
    with the config's own long share (the checkpoint's 50:50 would hand a long-biased config a free win in a rising window).
    p = (bots with a mean net per trade >= the config's + 1) / (bots + 1)."""
    L = C.env()["L"]
    B = prm.bots if bots is None else bots
    cfg = {x: (c, mh) for x, c, mh in C.exit_cfgs()}[exit_]
    use = []
    tot = nl = nb = 0
    for coin in prm.coins:
        cx = ctxs.get((tf, coin))
        if cx is None:
            continue
        arr = cx["arrays"].get(name)
        lo, n = cx["lo"], cx["n"]
        if n - 1 > lo:
            nb += n - 1 - lo
            if arr is not None:
                m = (arr[0] | arr[1])[lo:n - 1]
                tot += int(m.sum())
                nl += int(arr[0][lo:n - 1].sum())
        use.append(cx)
    if tot == 0 or nb == 0:
        return None
    rate, share = tot / nb, nl / tot
    rng = np.random.default_rng(int(hashlib.sha256(f"{C.SEED}|{seed_text}".encode()).hexdigest()[:8], 16))
    xc, mh = cfg
    cost = L._cost(tf, mh)
    vals = np.empty(B)
    for b in range(B):
        nets = []
        for cx in use:
            n = cx["n"]
            fire = rng.random(n) < rate
            lng = rng.random(n) < share
            t = L.run_backtest(cx["df"], cx["atr"], fire & lng, fire & ~lng, xc, cost, cx["lo"], n)
            nets.append(t["net"].to_numpy(float))
        allv = np.concatenate(nets) if nets else np.zeros(0)
        vals[b] = allv.mean() if len(allv) else -np.inf
    return float((np.count_nonzero(vals >= cfg_mean - 1e-12) + 1) / (B + 1))


# ====================================================================== stages
def _stage_window(stage: str, t0_ms: int, prm: Params) -> tuple[int, int]:
    d = prm.stage_days
    return {"prune1": (t0_ms, t0_ms + d[0] * DAY_MS), "prune2": (t0_ms, t0_ms + d[1] * DAY_MS),
            "judge1": (t0_ms + d[1] * DAY_MS, t0_ms + d[2] * DAY_MS), "judge2": (t0_ms + d[2] * DAY_MS, t0_ms + d[3] * DAY_MS)}[stage]


def get_snapshot(conn, stage: str) -> Optional[dict]:
    r = conn.execute("SELECT created_ms, cutoff_ms, input_sha, result_json, result_sha, code_sha FROM snapshots WHERE stage=?", (stage,)).fetchone()
    if r is None:
        return None
    if hashlib.sha256(r[3].encode()).hexdigest() != r[4]:
        raise StageError(f"snapshot {stage} was changed after it was stored")
    return {"created_ms": r[0], "cutoff_ms": r[1], "input_sha": r[2], "result": json.loads(r[3]), "code_sha": r[5]}


def data_ready(conn, prm: Params, cutoff_ms: int) -> list[str]:
    """Series that do not have a bar closing at or after the cutoff yet (a stage waits for them)."""
    missing = []
    for tf in prm.tfs:
        for coin in prm.coins:
            r = conn.execute("SELECT MAX(open_ms) FROM bars WHERE coin=? AND tf=?", (coin, tf)).fetchone()[0]
            if r is None or r + TF_MS[tf] < cutoff_ms:
                missing.append(f"{coin}@{tf}")
    return missing


def prune1_dropped(stats: dict, prm: Params) -> list[str]:
    """Day 30: a config with at least ``p1_min_trades`` trades, a negative mean and p_loss <= ``p1_p`` loses its candidacy."""
    return sorted(cid for cid, s in stats.items()
                  if s["n"] >= prm.p1_min_trades and s["mean"] is not None and s["mean"] < 0 and s["p_loss"] <= prm.p1_p)


def _select_survivors(stats: dict, dropped: set, prm: Params, family: Callable[[str], str]) -> tuple[list, int]:
    pool = [(cid, s) for cid, s in stats.items() if cid not in dropped and s["n"] >= prm.p2_min_trades
            and s["mean"] is not None and s["mean"] > 0 and s["t"] is not None]
    pool.sort(key=lambda x: (-x[1]["t"], x[0]))
    chosen, per_def, fam = [], {}, {}
    for cid, _s in pool:
        tf, name, _x = cid.split("|")
        f = family(name)
        if per_def.get((tf, name), 0) >= prm.def_tf_cap or fam.get(f, 0) >= prm.family_cap:
            continue
        chosen.append(cid)
        per_def[(tf, name)] = per_def.get((tf, name), 0) + 1
        fam[f] = fam.get(f, 0) + 1
        if len(chosen) >= prm.k_survivors:
            break
    return chosen, len(pool)


def run_stage(conn: sqlite3.Connection, C, stage: str, now_ms: int, code_sha: str = "", bots: Optional[int] = None,
              store: bool = True, check_ready: bool = True) -> dict:
    """Compute one pre-registered stage from the stored bars and signals only; store it (append-only) unless ``store`` is
    False. A stage can be stored once. Raises StageError when its predecessor is missing or its data is not there yet."""
    if stage not in STAGES:
        raise StageError(f"unknown stage {stage}")
    prm, t0, _anchor = load_meta(conn)
    if store and get_snapshot(conn, stage) is not None:
        raise StageError(f"{stage} is already stored (a stage is computed once); use --dry-run to look at it again")
    prev = {"prune1": None, "prune2": "prune1", "judge1": "prune2", "judge2": "judge1"}[stage]
    if prev and get_snapshot(conn, prev) is None:
        raise StageError(f"{stage} needs {prev} first")
    lo, hi = _stage_window(stage, t0, prm)
    if check_ready:
        miss = data_ready(conn, prm, hi)
        if miss:
            raise StageError(f"bars through {_iso(hi)} are not complete yet: {', '.join(miss[:8])}")
    family = lambda name: C.FAMILY[name]                                                   # noqa: E731
    judged = judged_configs(C, prm)
    all_ids = {config_id(*c) for c in judged}
    res: dict = {"stage": stage, "window_ms": [lo, hi], "window": [_iso(lo), _iso(hi)], "n_judged_configs": len(judged)}
    if stage in ("prune1", "prune2"):
        tr, _ = window_trades(conn, C, prm, lo, hi)
        stats = per_config(tr)
        res["stats"] = {cid: _round(stats.get(cid, cluster_stats(np.zeros(0), np.zeros(0, np.int64)))) for cid in sorted(all_ids)}
        if stage == "prune1":
            res["dropped"] = prune1_dropped(stats, prm)
        else:
            dropped = set(get_snapshot(conn, "prune1")["result"]["dropped"])
            chosen, npool = _select_survivors(stats, dropped, prm, family)
            res.update(survivors=chosen, pool_size=npool, dropped_before=sorted(dropped))
        input_sha = trades_sha(tr)
    else:
        if stage == "judge1":
            ids = list(get_snapshot(conn, "prune2")["result"]["survivors"])
            m_family = len(ids)
        else:
            ids = list(get_snapshot(conn, "judge1")["result"]["candidates"])
            m_family = len(ids)
        tr, ctxs = window_trades(conn, C, prm, lo, hi, set(ids))
        stats = per_config(tr)
        rows = {}
        for cid in ids:
            tf, name, x = cid.split("|")
            g = tr[(tr["tf"] == tf) & (tr["def"] == name) & (tr["exit"] == x)]
            s = stats.get(cid, cluster_stats(np.zeros(0), np.zeros(0, np.int64)))
            gd = guards(g, lo, hi, prm)
            p_cf = None
            if gd["n_ok"] and s["mean"] is not None:
                p_cf = coin_flip_p(C, ctxs, tf, name, x, s["mean"], prm, f"{cid}|{stage}", bots)
            rows[cid] = {**_round(s), "guards": _round(gd), "p_coin_flip": p_cf}
        usable = [cid for cid in ids if rows[cid]["guards"]["n_ok"] and rows[cid]["p_coin_flip"] is not None]
        p_t = [rows[c]["p_win"] if c in usable else 1.0 for c in ids]
        p_c = [rows[c]["p_coin_flip"] if c in usable else 1.0 for c in ids]
        if stage == "judge1":
            rej_t, rej_c = bh_reject(p_t, prm.alpha), bh_reject(p_c, prm.alpha)
            strong_t = bh_reject(p_t, prm.alpha, prm.n_total)
        else:
            lim = prm.j2_alpha / max(m_family, 1)
            rej_t, rej_c = np.array([p <= lim for p in p_t]), np.array([p <= lim for p in p_c])
            strong_t = np.zeros(len(ids), bool)
        cands, strong = [], []
        for k, cid in enumerate(ids):
            gd = rows[cid]["guards"]
            ok = (cid in usable and bool(rej_t[k]) and bool(rej_c[k]) and gd["stress_ok"] and gd["coins_ok"] and gd["halves_ok"] and gd["week_ok"])
            rows[cid]["pass_p"], rows[cid]["pass_coin_flip"], rows[cid]["candidate"] = bool(rej_t[k]), bool(rej_c[k]), bool(ok)
            rows[cid]["strong"] = bool(ok and strong_t[k])
            if ok:
                cands.append(cid)
            if rows[cid]["strong"]:
                strong.append(cid)
        res.update(family_size=m_family, rows=rows, candidates=cands)
        if stage == "judge1":
            res["strong"] = strong
            res["unjudgeable"] = [c for c in ids if not rows[c]["guards"]["n_ok"]]
            # explanation only: did the pruning predict anything? (survivors vs the other judged configs, same window)
            others = all_ids - set(ids)
            tr_o, _ = window_trades(conn, C, prm, lo, hi, others) if others else (pd.DataFrame(columns=tr.columns), None)
            res["pruning_check"] = {"survivors_mean": _mean(tr["net"]), "survivors_trades": int(len(tr)),
                                    "others_mean": _mean(tr_o["net"]), "others_trades": int(len(tr_o))}
        else:
            res["confirmed"] = list(cands)
        input_sha = trades_sha(tr)
    res = json.loads(json.dumps(res, default=_json_default))
    if store:
        text = json.dumps(res, sort_keys=True, separators=(",", ":"))
        conn.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)", (stage, now_ms, hi, input_sha, text,
                                                                         hashlib.sha256(text.encode()).hexdigest(), code_sha))
        event(conn, now_ms, "INFO", "stage_done", stage)
        conn.commit()
    res["input_sha"] = input_sha
    return res


def due_stages(conn, prm: Params, t0_ms: int, now_ms: int) -> list[str]:
    out = []
    for k, st in enumerate(STAGES):
        if now_ms >= t0_ms + prm.stage_days[k] * DAY_MS + 2 * 3_600_000 and get_snapshot(conn, st) is None:
            out.append(st)
    return out


def interim(conn, C, now_ms: int) -> dict:
    """Information only (day 90): the survivors' trades since day 60 up to the last whole day. Never stored, never used."""
    prm, t0, _ = load_meta(conn)
    snap = get_snapshot(conn, "prune2")
    if snap is None:
        raise StageError("interim needs prune2")
    lo = t0 + prm.stage_days[1] * DAY_MS
    hi = min(now_ms - now_ms % DAY_MS, t0 + prm.stage_days[2] * DAY_MS)
    ids = set(snap["result"]["survivors"])
    tr, _ = window_trades(conn, C, prm, lo, hi, ids)
    st = per_config(tr)
    return {"window": [_iso(lo), _iso(hi)], "note": "중간 점검: 정보일 뿐 판정·가지치기에 쓰지 않음",
            "stats": {c: _round(st.get(c, cluster_stats(np.zeros(0), np.zeros(0, np.int64)))) for c in sorted(ids)}}


def _mean(s) -> Optional[float]:
    s = np.asarray(s, float)
    return float(s.mean()) if len(s) else None


def _round(d: dict) -> dict:
    return {k: (round(v, 10) if isinstance(v, float) else ([round(x, 10) if isinstance(x, float) else x for x in v] if isinstance(v, list) else v))
            for k, v in d.items()}


def _json_default(o):
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    raise TypeError(type(o))


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ====================================================================== the job
def versions() -> str:
    import scipy
    return json.dumps({"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__})


def own_sha() -> str:
    return sha256_file(os.path.abspath(__file__))


def run_once(conn: sqlite3.Connection, C, prm: Params, t0_ms: int, anchor_ms: int, source, now_ms: int, pins: Optional[dict] = None,
             flag_all: bool = False, stages: bool = True, pause: float = 0.0, bots: Optional[int] = None,
             log: Callable[[str], None] = print) -> int:
    """One pass: bars -> signals -> hypothetical trades -> due stages. Returns 0, or 1 when a series is stale (the unit's failure
    alert); a fetch error alone is an event (the next pass heals it)."""
    init_meta(conn, prm, t0_ms, anchor_ms, now_ms)
    code_sha = own_sha()
    conn.execute("INSERT INTO runs (ts, kind, pins, versions, note) VALUES (?,?,?,?,?)",
                 (now_ms, "backfill" if flag_all else "run", json.dumps(pins or {}), versions(), code_sha))
    conn.commit()
    order = [c for c in prm.coins if c == "BTCUSD"] + [c for c in prm.coins if c != "BTCUSD"]
    for tf in prm.tfs:
        for coin in order:
            try:
                new, rev = fetch_series(conn, source, coin, tf, anchor_ms, now_ms, flag_all=flag_all, pause=pause)
                if new:
                    log(f"bars {coin}@{tf}: +{new}")
            except Exception as exc:  # noqa: BLE001  one series' network error never stops the others
                conn.rollback()
                event(conn, now_ms, "WARN", "fetch_error", f"{coin}@{tf}: {type(exc).__name__}: {exc}")
                conn.commit()
    for tf in prm.tfs:
        for coin in order:
            try:
                n, advanced = update_signals(conn, C, prm, coin, tf, t0_ms, now_ms, code_sha, flag_all)
                if advanced:
                    update_trades(conn, C, prm, coin, tf, t0_ms, now_ms)
                    log(f"signals {coin}@{tf}: +{n}")
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                event(conn, now_ms, "CRITICAL", "signal_error", f"{coin}@{tf}: {type(exc).__name__}: {exc}")
                conn.commit()
    if stages and not flag_all:
        for st in due_stages(conn, prm, t0_ms, now_ms):
            try:
                run_stage(conn, C, st, now_ms, code_sha, bots)
                log(f"stage {st} stored")
            except StageError as exc:
                log(f"stage {st} waits: {exc}")
                break
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                event(conn, now_ms, "CRITICAL", "stage_error", f"{st}: {type(exc).__name__}: {exc}")
                conn.commit()
                break
    stale = []
    for tf in prm.tfs:
        newest = ((now_ms - SETTLE_MS) // TF_MS[tf] - 1) * TF_MS[tf]
        for coin in prm.coins:
            last = conn.execute("SELECT MAX(open_ms) FROM bars WHERE coin=? AND tf=?", (coin, tf)).fetchone()[0]
            if last is None or newest - last > STALE_MS:
                stale.append(f"{coin}@{tf}")
    if stale:
        event(conn, now_ms, "CRITICAL", "stale", ", ".join(stale[:12]))
        conn.commit()
        log("stale series: " + ", ".join(stale))
        return 1
    return 0


def status_text(conn: sqlite3.Connection, now_ms: int) -> str:
    """Health and counts only. No mean, no p value, no profit: nothing is looked at before day 30 (FORWARD_PREREG 5-6)."""
    prm, t0, anchor = load_meta(conn)
    out = [f"T0 {_iso(t0)}  anchor {_iso(anchor)}  now {_iso(now_ms)}  day {(now_ms - t0) / DAY_MS:.1f}"]
    for tf in prm.tfs:
        row = []
        for coin in prm.coins:
            r = conn.execute("SELECT MAX(open_ms), COUNT(*) FROM bars WHERE coin=? AND tf=?", (coin, tf)).fetchone()
            row.append(f"{coin[:-3]} {'-' if r[0] is None else _iso(r[0] + TF_MS[tf])[5:16]}")
        out.append(f"bars {tf}: " + "  ".join(row))
    for tf in prm.tfs:
        s = conn.execute("SELECT COUNT(*), SUM(backfill) FROM signals WHERE tf=?", (tf,)).fetchone()
        t = conn.execute("SELECT COUNT(*) FROM trades WHERE tf=?", (tf,)).fetchone()[0]
        o = conn.execute("SELECT COUNT(*) FROM open_trades WHERE tf=?", (tf,)).fetchone()[0]
        out.append(f"{tf}: signals {s[0]} (backfill {s[1] or 0}), closed trades {t}, open {o}")
    for st in STAGES:
        snap = get_snapshot(conn, st)
        out.append(f"stage {st}: " + ("not yet" if snap is None else f"stored {_iso(snap['created_ms'])}, result sha {snap['input_sha'][:12]}"))
    ev = conn.execute("SELECT level, COUNT(*) FROM events GROUP BY level").fetchall()
    out.append("events: " + (", ".join(f"{a} {b}" for a, b in ev) if ev else "none"))
    for ts, lv, code, det in conn.execute("SELECT ts, level, code, detail FROM events WHERE level IN ('WARN','CRITICAL') ORDER BY id DESC LIMIT 5"):
        out.append(f"  {_iso(ts)} {lv} {code} {det[:120]}")
    return "\n".join(out)


def format_stage(res: dict) -> str:
    st = res["stage"]
    lines = [f"{st}: 구간 {res['window'][0]} ~ {res['window'][1]}, 판정 대상 설정 {res['n_judged_configs']}개"]
    if st == "prune1":
        lines.append(f"명백한 손실로 후보 자격을 잃은 설정: {len(res['dropped'])}개")
    elif st == "prune2":
        lines.append(f"조건을 채운 설정 {res['pool_size']}개 중 남긴 설정: {len(res['survivors'])}개")
        lines += ["  " + c for c in res["survivors"]]
    else:
        lines.append(f"보정 개수 m = {res['family_size']}, 후보 {len(res['candidates'])}개" + (
            f", 강한 후보 {len(res['strong'])}개" if "strong" in res else f", 확인된 후보 {len(res['confirmed'])}개"))
        lines += ["  " + c for c in res["candidates"]]
    return "\n".join(lines)


# ====================================================================== parity with the 5-year period 3
def parity(pre_dir: str = PRE_DIR, results_csv: str = RESULTS, tfs: Iterable[str] = TFS, defs: Optional[set] = None,
           log: Callable[[str], None] = print) -> dict:
    """Run the production path (bars -> database -> signals -> stored signals -> engine) on the real 2020-01..2021-08 bars and
    compare per configuration with the 5-year result's period 3 (``pre_n``, ``pre_mean_pct``). Nothing after 2021 is read."""
    C = load_lib_c()
    E = C.env()
    L, lib = E["L"], E["lib"]
    res = pd.read_csv(results_csv).set_index(["tf", "entry", "exit"])
    frames = {}
    for coin in COINS:
        for tf in tfs:
            src = "15m" if tf == "30m" else tf
            d = pd.read_csv(os.path.join(pre_dir, f"{coin.lower()}-{src}.csv.gz"))
            d["ts"] = pd.to_datetime(d["ts"], utc=True)
            d = d.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
            d = d[d["ts"] < lib.PRE[1] + pd.Timedelta(days=10)].reset_index(drop=True)
            if tf == "30m":
                d = L.resample_ohlcv(d, "30m")
            frames[(coin, tf)] = d
    start = int(dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    prm = Params(tfs=tuple(tfs), drop_no_trade=False)
    conn = connect(":memory:")
    far = int(dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    init_meta(conn, prm, start, start, far)
    src = FrameSource(frames)
    code_sha = own_sha()
    for tf in prm.tfs:
        for coin in prm.coins:
            fetch_series(conn, src, coin, tf, start, far, flag_all=True)
    for tf in prm.tfs:
        for coin in prm.coins:
            update_signals(conn, C, prm, coin, tf, start, far, code_sha, True)
    rows, bad = [], 0
    acc: dict = {}
    for tf in prm.tfs:
        for coin in prm.coins:
            df = load_frame(conn, coin, tf, drop_no_trade=False)
            lo, hi = C.window_idx(L, df, tf, *C.PERIODS["pre"])
            if hi <= lo:
                continue
            open_ms = df["open_ms"].to_numpy(np.int64)
            atr = E["fg"].atr(df, 14).to_numpy(float)
            for name, (lg, sh) in signal_arrays(conn, coin, tf, open_ms, defs).items():
                for xname, t in run_exits(C, df, atr, lg, sh, tf, lo, hi).items():
                    if len(t):
                        acc.setdefault((tf, name, xname), []).append(t["net"].to_numpy(np.float64))
    for key, r in res.iterrows():
        if defs is not None and key[1] not in defs:
            continue
        if key[0] not in prm.tfs:
            continue
        v = np.concatenate(acc[key]) if key in acc else np.zeros(0)
        n, mean = len(v), (100 * v.mean() if len(v) else float("nan"))
        ok = (n == int(r["pre_n"])) and (n == 0 or abs(mean - float(r["pre_mean_pct"])) < 1e-7)
        bad += 0 if ok else 1
        rows.append({"config": "|".join(key), "n_here": n, "n_5y": int(r["pre_n"]), "mean_here_pct": mean, "mean_5y_pct": float(r["pre_mean_pct"]), "same": ok})
    out = {"configs": len(rows), "same": len(rows) - bad, "different": bad, "rows": rows}
    log(f"parity (period 3, 2020-01..2021-08): {out['same']} of {out['configs']} configurations reproduce n and mean exactly")
    return out


# ====================================================================== command line
def _now_ms() -> int:
    return int(time.time() * 1000)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.shadow200", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "backfill"):
        p = sub.add_parser(name)
        p.add_argument("--db", default=DEFAULT_DB)
        p.add_argument("--bars-dir", help="read bars from <coin>-<tf>.csv.gz files instead of Binance")
        p.add_argument("--pause", type=float, default=0.2, help="seconds between two Binance requests")
        p.add_argument("--bots", type=int, default=None, help="coin-flip bots of a stage run by this job (tests only)")
        p.add_argument("--now-ms", type=int, default=None, help=argparse.SUPPRESS)
    p = sub.add_parser("stage")
    p.add_argument("stage", choices=STAGES)
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--bots", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="compute and print, store nothing")
    p.add_argument("--now-ms", type=int, default=None, help=argparse.SUPPRESS)
    for name in ("status", "interim"):
        p = sub.add_parser(name)
        p.add_argument("--db", default=DEFAULT_DB)
        p.add_argument("--now-ms", type=int, default=None, help=argparse.SUPPRESS)
    p = sub.add_parser("parity")
    p.add_argument("--pre-dir", default=PRE_DIR)
    p.add_argument("--results", default=RESULTS)
    p.add_argument("--tfs", default=",".join(TFS))
    a = ap.parse_args(argv)
    try:
        if a.cmd == "parity":
            verify_pins()
            out = parity(a.pre_dir, a.results, tuple(a.tfs.split(",")))
            for r in out["rows"]:
                if not r["same"]:
                    print("DIFFERENT", r)
            return 0 if out["different"] == 0 else 1
        if a.cmd == "status":
            conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
            print(status_text(conn, a.now_ms or _now_ms()))
            return 0
        pins = verify_pins()
        now = a.now_ms or _now_ms()
        C = load_lib_c()
        with writer_lock(a.db):
            conn = connect(a.db)
            if a.cmd in ("run", "backfill"):
                prm = Params()
                source = csv_source(a.bars_dir, prm.coins, prm.tfs) if a.bars_dir else BinanceSource()
                return run_once(conn, C, prm, T0_MS, ANCHOR_MS, source, now, pins, flag_all=a.cmd == "backfill",
                                stages=a.cmd == "run", pause=a.pause, bots=a.bots)
            if a.cmd == "stage":
                res = run_stage(conn, C, a.stage, now, own_sha(), a.bots, store=not a.dry_run)
                print(format_stage(res))
                print(("(저장하지 않음)" if a.dry_run else "저장함") + f"  입력 해시 {res['input_sha'][:16]}")
                return 0
            if a.cmd == "interim":
                print(json.dumps(interim(conn, C, now), ensure_ascii=False, indent=1))
                return 0
    except Busy as exc:
        print(f"{exc}; nothing to do")
        return 0
    except (PinError, StageError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
