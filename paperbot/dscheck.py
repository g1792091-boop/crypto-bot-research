"""DeepSeek nightly recompute check (paper v4, plan section 12, due D0 + 1). NOT a trading module: it opens paper3.db
read-only, places no order, sends no Telegram of its own, and nothing on the trading path imports it (it is in no
runinfo hash set; a change here restarts no window).

    python -m paperbot.dscheck run  [--db FILE] [--out DIR] [--day YYYY-MM-DD] [--bars-dir DIR] [--tfs 15m,1h]
    python -m paperbot.dscheck show [--out DIR]                     print the last one-line summary

What it checks (plan section 10 risk 3: look-ahead, window-start dependence, F14 misaligned with BTC). For one UTC day
(default: yesterday) it recomputes the 44 pinned definitions of research/deepseek200/lib_c.py from FULL history and
compares them with what the live service logged:

- lib_c is loaded the way shadow200 and dssig load it: its bytes are hashed first (lib_c.py against
  research/deepseek200/out/summary.json, PREREG_DEEPSEEK200.md against its .sha256, and every file in
  paperbot/ds_pins.json, the live wrapper's own pins), then executed from those very bytes under a private module name
  inside ``entry_marks._contained()`` (sys.path and the warnings filters are restored), its ``env()`` too, and hashed
  again afterwards. Any difference: exit 2, nothing compared.
- full history: for timeframe tf the recompute starts HISTORY_FACTOR (1.5) x config.DS_WINDOW_5M[tf] five-minute bars
  before the day, so every bar of the day is computed on half a live window MORE history than the live job had.
  Bars: Binance's final public 5m klines (no key), cached in <out>/bars5m.db (or research-layout files with
  --bars-dir). The chart frame is built by the documented rule (dssig's): 5m bars with exactly zero volume left out,
  the locked ``resample_ohlcv``, a partial bin at either end dropped. F14_SMT gets BTC's frame over the same span
  (lib_c matches it by timestamp; the live job sends only BTC's last 100 bars). The side of a bar is +1 when the long
  array fires, else -1 when the short one does (dssig's rule).
- live: paper3.db signal_log rows of the DeepSeek accounts (accounts.kind "ds200": strategy = definition id, its
  timeframe) whose bar closed in the day, from each account's creation on. signal_log holds only the definitions that
  fired, so a bar's "no signal" is the absence of a row. A (timeframe, boundary) with no DeepSeek row for any coin is
  "uncovered".
  The live job's own record decides first (paper3.db state "dsrun:<UTC day>", paperbot/live3.py ``_ds_record``):
  on a boundary recorded "ran", exactly its "ok" coins are compared (a missing row there is "no signal"); F14_SMT
  missing on a coin listed under "err" is excused (that coin's BTC context failed); a coin listed under "no", and
  every coin of a boundary recorded "timeout", "failed", "refused" or "incomplete", is uncovered with that reason
  ("excused" when the recompute fired there: counted, not a failure). A DeepSeek boundary of the day ABSENT from an
  existing record while DeepSeek accounts were open on that timeframe is ONE mismatch ("unrecorded": the runner
  never reached it). Only when the day has no record at all (a runner before the record existed) does the heuristic
  apply: a boundary with no DeepSeek row for any coin is uncovered, and where the recompute fired there it is ONE
  mismatch ("uncovered") unless the live service said why it skipped that boundary: an alert with its frozen DeepSeek
  timeout or failure text for that boundary (paperbot/sigservice.py DS_TIMEOUT_TEXT / DS_FAILED_TEXT, owners' G27)
  or the "5m history incomplete" alert ("excused"). An uncovered boundary where the recompute fired nothing is only
  counted.
- mismatches, on covered boundaries: "extra" (live fired, the recompute did not), "flip" (opposite sides), "missing"
  (the recompute fired, live logged nothing for that coin). The documented 1-bar data difference: the live service
  builds its 5m bars from the 1m bars it read live, which can differ from the final klines (an early kline, docs/
  signal-recording.md). When paper3.db live_bars holds every live minute of the signal's own chart bar (and of BTC's
  for F14_SMT) and they differ from the final bars there, the mismatch is "data" (reported, not a failure). Without
  the live minutes nothing is excused.
- per timeframe: a whole day with DeepSeek accounts on that timeframe but no DeepSeek row of it while the recompute
  fired there is "silent" (a failure; the one line names the timeframes).
- no paper3.db at all (a fresh server, or a run between the reset's move and the bot's start): "no_accounts", exit 0.

Output: <out>/last.txt (ONE line in Korean, for the 09:20 report to read), <out>/last.json and
<out>/days/<day>.json (the full report). Exit status: 0 = no mismatch beyond data differences and excused
boundaries (also: no DeepSeek account that day, or no paper3.db); 1 = a mismatch or a silent timeframe; 2 = the check
could not run (pins, bars, an unreadable database). The kline cache <out>/bars5m.db is regenerable: it is in no
backup or off-site list, and the reset keeps it in place while it archives the run's summaries. systemd's
OnFailure (deploy/paperbot-dscheck.service) sends the owners' one Korean warning for 1 and 2.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import re
import sqlite3
import sys
import time
import warnings
from pathlib import Path
from typing import Callable, Iterable, Optional

import numpy as np
import pandas as pd

from .config import DS200_TFS, DS_WINDOW_5M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEEP = os.path.join(ROOT, "research", "deepseek200")
LIB_C = os.path.join(DEEP, "lib_c.py")
SUMMARY = os.path.join(DEEP, "out", "summary.json")
PREREG = os.path.join(DEEP, "PREREG_DEEPSEEK200.md")
PREREG_SHA = os.path.join(DEEP, "PREREG_DEEPSEEK200.sha256")
PINS = os.path.join(ROOT, "paperbot", "ds_pins.json")
MODULE_NAME = "_paperbot_dscheck_lib_c"      # private: never the module object of dssig, shadow200 or the research
DEFAULT_DB = "/var/lib/paperbot/paper3.db"
DEFAULT_OUT = "/var/lib/paperbot/dscheck"

KIND = "ds200"
FIVE = 300_000
MIN = 60_000
DAY_MS = 86_400_000
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")     # lib_c.COINS (checked at load)
BTC = "BTCUSD"
F14 = "F14_SMT"
HISTORY_FACTOR = 1.5          # recompute history = 1.5 x the live window, ending at the day's end
SETTLE_MS = 60_000            # a 5m kline is final this long after its close
PRICE_RTOL = 1e-9             # live vs final bar: prices equal within this relative tolerance ...
VOLUME_RTOL = 1e-6            # ... volumes within this one
MAX_LISTED = 200              # mismatches written out in full (all are counted)
KST = dt.timezone(dt.timedelta(hours=9))
SIDE_KO = {1: "롱", -1: "숏", 0: "없음"}
# The live service's frozen DeepSeek texts (paperbot/sigservice.py DS_TIMEOUT_RE / DS_FAILED_RE, owners' G27; copied
# here so this check never imports the signal service; tests/test_dscheck.py checks they are the same) and the core
# runner's "history incomplete" alert (paperbot/live3.py: no group's signals at that boundary).
DS_TIMEOUT_RE = r"^\[ds200\] DeepSeek signal workers timed out after (\d+)s; DeepSeek signals skipped at (\d+) for (.+)$"
DS_FAILED_RE = r"^\[ds200\] DeepSeek signals failed at (\d+) \((.*)\); the other groups run on$"
INCOMPLETE_RE = r"^5m history incomplete at (\d+); signals skipped$"
DS_RUN_KEY = "dsrun:"                    # paperbot/live3.py: the DeepSeek job's own record of each boundary, per UTC day
EXCUSED_RUN = ("timeout", "failed", "refused", "incomplete")   # a record status that skips every coin, with reason


class DsCheckError(RuntimeError):
    """The check cannot run (pins, bars, database): exit 2."""


def symbol_of(coin: str) -> str:
    return coin + "T"                         # BTCUSD -> BTCUSDT (dssig.coin_key the other way)


def coin_of(symbol: str) -> Optional[str]:
    key = symbol[:-1] if symbol.endswith("USDT") else symbol
    return key if key in COINS else None


def history_5m(tf: str, windows: Optional[dict] = None) -> int:
    """5m bars of history before the day for ``tf``'s recompute."""
    return int(math.ceil(HISTORY_FACTOR * (windows or DS_WINDOW_5M)[tf]))


# ====================================================================== pins and the contained load
def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return _sha_bytes(fh.read())


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def wanted_pins() -> dict:
    """{absolute path: sha256} every file must have: lib_c.py as summary.json pins it (and ds_pins.json, which must
    agree), the PREREG as its .sha256, and the library / vendor files ds_pins.json pins."""
    try:
        with open(SUMMARY, encoding="utf-8") as fh:
            lib_c = str(json.load(fh)["code_sha256"]["lib_c.py"])
        with open(PREREG_SHA, encoding="utf-8") as fh:
            prereg = fh.read().split()[0].strip().lower()
        with open(PINS, encoding="utf-8") as fh:
            pins = json.load(fh)
        files = {os.path.join(ROOT, *rel.split("/")): str(sha) for rel, sha in pins["files"].items()}
        pin_lib_c = str(pins["lib_c.py"])
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise DsCheckError(f"DeepSeek pins unreadable: {type(exc).__name__}: {exc}"[:400]) from None
    if pin_lib_c != lib_c:
        raise DsCheckError(f"DeepSeek pins disagree: ds_pins.json lib_c.py {pin_lib_c[:12]} "
                           f"vs summary.json {lib_c[:12]}")
    return {LIB_C: lib_c, PREREG: prereg, **files}


def check_pins(want: Optional[dict] = None, lib_c_bytes: Optional[bytes] = None) -> dict:
    """{repo path: sha256}; raises DsCheckError naming every file that differs or is missing."""
    want = want or wanted_pins()
    got, bad = {}, []
    for path, sha in want.items():
        try:
            have = _sha_bytes(lib_c_bytes) if (path == LIB_C and lib_c_bytes is not None) else _sha(path)
        except OSError:
            bad.append(f"{_rel(path)} (missing)")
            continue
        got[_rel(path)] = have
        if have != sha:
            bad.append(f"{_rel(path)} ({have[:12]} != pinned {sha[:12]})")
    if bad:
        raise DsCheckError("DeepSeek code changed or missing: " + "; ".join(bad))
    return got


_C = None
_PINS: Optional[dict] = None


def load_lib_c():
    """The verified lib_c module of this process (hash, contained load of those bytes and its env(), hash again)."""
    global _C, _PINS
    if _C is not None:
        return _C
    from . import sweepsig
    from .entry_marks import _contained
    want = wanted_pins()
    try:
        with open(LIB_C, "rb") as fh:
            src = fh.read()
    except OSError as exc:
        raise DsCheckError(f"lib_c.py unreadable: {exc}"[:400]) from None
    check_pins(want, src)
    try:
        lib = sweepsig.lib()           # the locked library first, as the live service loads it (lib_c's env() uses it)
    except Exception as exc:  # noqa: BLE001
        raise DsCheckError(f"locked library unavailable: {type(exc).__name__}: {exc}"[:400]) from None
    spec = importlib.util.spec_from_file_location(MODULE_NAME, LIB_C)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = mod
    try:
        with _contained():
            exec(compile(src, LIB_C, "exec"), mod.__dict__)
            mod.env()
    except BaseException as exc:
        sys.modules.pop(MODULE_NAME, None)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise DsCheckError(f"lib_c failed to load: {type(exc).__name__}: {exc}"[:400]) from None
    got = check_pins(want)             # unchanged while it loaded
    if tuple(mod.COINS) != COINS:
        sys.modules.pop(MODULE_NAME, None)
        raise DsCheckError(f"lib_c.COINS {tuple(mod.COINS)} differs from dscheck.COINS")
    _C, _PINS = mod, got
    _C._dscheck_lib = lib
    return _C


def defs_for(C, tf: str) -> list[str]:
    return [d[0] for d in C.DEFS if tf in d[2]]


# ====================================================================== bars
def _cols(ts, o, h, l, c, v) -> tuple:
    return (np.asarray(ts, dtype=np.int64),) + tuple(np.asarray(a, dtype=float) for a in (o, h, l, c, v))


def _span(cols: tuple, start: int, end: int) -> tuple:
    keep = (cols[0] >= start) & (cols[0] < end)
    return tuple(a[keep] for a in cols)


class FrameSource:
    """5m bars from memory: {symbol: (ts ms, open, high, low, close, volume)} (tests)."""

    def __init__(self, data: dict):
        self.data = {s: _cols(*v) for s, v in data.items()}

    def load(self, symbol: str, start: int, end: int) -> tuple:
        if symbol not in self.data:
            raise DsCheckError(f"no 5m bars for {symbol}")
        return _span(self.data[symbol], start, end)


class CsvSource:
    """Research-layout files <coin>-5m.csv.gz (ts, open, high, low, close, volume), e.g. btcusd-5m.csv.gz."""

    def __init__(self, bars_dir: str):
        self.dir = bars_dir
        self._cache: dict = {}

    def load(self, symbol: str, start: int, end: int) -> tuple:
        if symbol not in self._cache:
            coin = coin_of(symbol) or symbol
            p = os.path.join(self.dir, f"{coin.lower()}-5m.csv.gz")
            if not os.path.exists(p):
                raise DsCheckError(f"no bar file {p}")
            d = pd.read_csv(p)
            t = (pd.to_datetime(d["ts"], utc=True).astype("int64") // 1_000_000).to_numpy(np.int64)
            order = np.argsort(t, kind="stable")
            self._cache[symbol] = _cols(t[order], *(d[k].to_numpy(float)[order]
                                                    for k in ("open", "high", "low", "close", "volume")))
        return _span(self._cache[symbol], start, end)


class RestSource:
    """Binance's public 5m klines (no key), final bars only, cached in a SQLite file. ``spans`` records the range of
    open times fetched completely per symbol, so a bar the exchange never had is not fetched again."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS bars5m (symbol TEXT NOT NULL, open_time INTEGER NOT NULL, open REAL NOT NULL,
      high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL,
      PRIMARY KEY (symbol, open_time)) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS spans (symbol TEXT PRIMARY KEY, lo INTEGER NOT NULL, hi INTEGER NOT NULL);
    """

    def __init__(self, cache_path: str, rest=None, now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                 pause: float = 0.3, sleep: Callable[[float], None] = time.sleep):
        if rest is None:
            from .binance import BinanceREST
            rest = BinanceREST()
        self.rest, self.now_ms, self.pause, self.sleep = rest, now_ms, pause, sleep
        os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
        self.conn = sqlite3.connect(cache_path, timeout=30)
        self.conn.executescript(self.SCHEMA)
        self.requests = 0

    def _fetch(self, symbol: str, a: int, b: int) -> None:
        t = a
        while t < b:
            raw = self.rest.klines(symbol, "5m", start_time=t, limit=1500)
            self.requests += 1
            now = self.now_ms()
            rows = [r for r in raw if int(r[0]) >= t and int(r[0]) < b and int(r[0]) + FIVE + SETTLE_MS <= now]
            if rows:
                self.conn.executemany("INSERT OR REPLACE INTO bars5m VALUES (?,?,?,?,?,?,?)",
                                      [(symbol, int(r[0]), *(float(x) for x in r[1:6])) for r in rows])
            if len(raw) < 1500 or not rows:
                break
            t = int(rows[-1][0]) + FIVE
            if self.pause:
                self.sleep(self.pause)

    def load(self, symbol: str, start: int, end: int) -> tuple:
        from .binance import BinanceError
        final = (self.now_ms() - SETTLE_MS) // FIVE * FIVE - FIVE     # the last open time that is final now
        end_ok = min(int(end), final + FIVE)
        r = self.conn.execute("SELECT lo, hi FROM spans WHERE symbol = ?", (symbol,)).fetchone()
        try:
            if r is None:
                self._fetch(symbol, start, end_ok)
                lo, hi = start, end_ok
            else:
                lo, hi = r
                if start < lo:
                    self._fetch(symbol, start, lo)
                    lo = start
                if end_ok > hi:
                    self._fetch(symbol, hi, end_ok)
                    hi = end_ok
        except (BinanceError, OSError, ValueError, IndexError, TypeError) as exc:
            self.conn.rollback()
            raise DsCheckError(f"5m klines of {symbol} unavailable: {type(exc).__name__}: {exc}"[:400]) from None
        self.conn.execute("INSERT OR REPLACE INTO spans VALUES (?,?,?)", (symbol, lo, hi))
        self.conn.commit()
        rows = self.conn.execute("SELECT open_time, open, high, low, close, volume FROM bars5m WHERE symbol = ? "
                                 "AND open_time >= ? AND open_time < ? ORDER BY open_time",
                                 (symbol, int(start), int(end))).fetchall()
        a = np.array(rows, dtype=float).reshape(-1, 6)
        return _cols(a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])


def frame(cols: tuple, tf: str, lib) -> pd.DataFrame:
    """Chart bars of ``tf`` from 5m bars (the documented rule, as paperbot/dssig.py ``frame``): 5m bars with exactly
    zero volume left out, the locked ``resample_ohlcv``, a partial bin at either end dropped."""
    ts, o, h, l, c, v = cols
    if not len(ts):
        return pd.DataFrame({"ts": pd.to_datetime(np.array([], np.int64), unit="ms", utc=True),
                             **{k: np.array([], float) for k in ("open", "high", "low", "close", "volume")}})
    traded = ~(v == 0.0)
    df5 = pd.DataFrame({"ts": pd.to_datetime(ts[traded], unit="ms", utc=True, cache=False), "open": o[traded],
                        "high": h[traded], "low": l[traded], "close": c[traded], "volume": v[traded]})
    r = lib.resample_ohlcv(df5, tf)
    t = (r["ts"].astype("int64") // 1_000_000).to_numpy(np.int64)
    keep = (t >= int(ts[0])) & (t + TF_MS[tf] <= int(ts[-1]) + FIVE)
    df = r.loc[keep].reset_index(drop=True)
    df.attrs["tf"] = tf
    return df


def _open_ms(df: pd.DataFrame) -> np.ndarray:
    return (df["ts"].astype("int64") // 1_000_000).to_numpy(np.int64)


# ====================================================================== recompute
def recompute(C, lib, bars: dict, tf: str, day_start: int, windows: Optional[dict] = None) -> tuple[dict, dict, list]:
    """({(bar_close, def, symbol): side} of every bar of ``tf`` that opens in the day, {symbol: why} of the coins not
    recomputed (history shorter than the live window), notes). ``bars``: {coin: 5m cols} from the history start."""
    day_end = day_start + DAY_MS
    start = day_start - history_5m(tf, windows) * FIVE
    need = (windows or DS_WINDOW_5M)[tf]
    defs = defs_for(C, tf)
    out: dict = {}
    unchecked: dict = {}
    notes: list = []
    btc_df = None
    if BTC in bars:
        btc_df = frame(_span(bars[BTC], start, day_end), tf, lib)
    for coin in COINS:
        sym = symbol_of(coin)
        if coin not in bars:
            unchecked[sym] = "no bars"
            continue
        cols = _span(bars[coin], start, day_end)
        before = int(np.count_nonzero(cols[0] < day_start))
        if before < need:
            unchecked[sym] = f"history {before} 5m bars < live window {need}"
            continue
        df = frame(cols, tf, lib)
        ctx = {BTC: btc_df} if (coin != BTC and btc_df is not None and len(btc_df)) else None
        if ctx is None and coin != BTC:
            notes.append(f"{sym} {tf}: no BTC bars, F14_SMT not checked")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                R = C.entries(df, tf, ctx, coin)
            except Exception as exc:  # noqa: BLE001
                if ctx is None:
                    raise DsCheckError(f"lib_c failed on {sym} {tf}: {type(exc).__name__}: {exc}"[:400]) from None
                notes.append(f"{sym} {tf}: F14_SMT context failed ({type(exc).__name__}: {exc})"[:300])
                R = C.entries(df, tf, None, coin)
        missing = [d for d in defs if d not in R]
        if missing:
            raise DsCheckError(f"lib_c gave no {tf} result for {missing}")
        opens = _open_ms(df)
        idx = np.flatnonzero((opens >= day_start) & (opens + TF_MS[tf] <= day_end))
        for d in defs:
            lg, sh = (np.asarray(a, dtype=bool) for a in R[d])
            for i in idx:
                side = 1 if lg[i] else (-1 if sh[i] else 0)
                if side:
                    out[(int(opens[i]) + TF_MS[tf], d, sym)] = side
    return out, unchecked, notes


# ====================================================================== live rows and live bars (paper3.db, read-only)
def connect_ro(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        raise DsCheckError(f"no database {path}")
    try:
        # an absolute file: URI (quoted), so no character of the path can drop the read-only mode
        conn = sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True, timeout=30)
        conn.execute("PRAGMA query_only = ON")
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.Error as exc:
        raise DsCheckError(f"cannot open {path} read-only: {exc}") from None
    return conn


def ds_accounts(conn: sqlite3.Connection) -> dict:
    """{(definition, timeframe): created_ts} of the DeepSeek accounts ({} for a database without them)."""
    try:
        rows = conn.execute("SELECT strategy, timeframe, MIN(created_ts) FROM accounts WHERE kind = ? "
                            "GROUP BY strategy, timeframe", (KIND,)).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such" in str(exc):
            return {}
        raise DsCheckError(f"accounts unreadable: {exc}") from None
    return {(s, tf): int(ts) for s, tf, ts in rows}


def live_rows(conn: sqlite3.Connection, accounts: dict, day_start: int, tfs: Iterable[str]) -> dict:
    """{(tf, bar_close, def, symbol): (side, status)} of the DeepSeek accounts' signal_log rows of the day."""
    tfs = list(tfs)
    try:
        rows = conn.execute(f"SELECT bar_close, timeframe, strategy, symbol, side, status FROM signal_log "
                            f"WHERE bar_close > ? AND bar_close <= ? AND timeframe IN ({','.join('?' * len(tfs))})",
                            [day_start, day_start + DAY_MS, *tfs]).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such" in str(exc):
            return {}
        raise DsCheckError(f"signal_log unreadable: {exc}") from None
    out = {}
    for bc, tf, s, sym, side, status in rows:
        if (s, tf) in accounts and coin_of(sym) and int(side):
            out[(tf, int(bc), s, sym)] = (1 if int(side) > 0 else -1, status)
    return out


def excused_boundaries(conn: Optional[sqlite3.Connection], day_start: int, tfs: Iterable[str]) -> dict:
    """{(tf, boundary): why} of the boundaries of the day the live service SAID it skipped for DeepSeek: its frozen
    timeout / failure alerts, the "history incomplete" alert, and its own run record (state "dsrun:<day>")."""
    tfs = list(tfs)
    out: dict = {}
    if conn is None:
        return out
    lo, hi = day_start, day_start + DAY_MS
    try:
        rows = conn.execute("SELECT text FROM alerts WHERE ts >= ? AND ts < ? AND (text LIKE '[ds200] DeepSeek signal%' "
                            "OR text LIKE '5m history incomplete at %')", (lo, hi + 3_600_000)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for (text,) in rows:
        m = re.match(DS_TIMEOUT_RE, text)
        if m:
            b = int(m.group(2))
            for tf in (t.strip() for t in m.group(3).split(",")):
                if tf in tfs and lo < b <= hi:
                    out[(tf, b)] = "DeepSeek timeout alert"
            continue
        m = re.match(DS_FAILED_RE, text) or re.match(INCOMPLETE_RE, text)
        if m:
            b = int(m.group(1))
            if lo < b <= hi:
                for tf in tfs:
                    if b % TF_MS[tf] == 0:
                        out[(tf, b)] = "DeepSeek failure alert" if text.startswith("[ds200]") else "history incomplete alert"
    for day in {dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%Y-%m-%d") for t in (lo, hi - 1)}:
        try:
            r = conn.execute("SELECT data FROM state WHERE k = ?", (DS_RUN_KEY + day,)).fetchone()
            rec = json.loads(r[0]) if r else {}
        except (sqlite3.OperationalError, ValueError, TypeError):
            rec = {}
        by_tf = rec.get("tfs") if isinstance(rec, dict) else None
        for tf, by_b in (by_tf.items() if isinstance(by_tf, dict) else ()):
            if tf not in tfs or not isinstance(by_b, dict):
                continue
            for b, entry in by_b.items():
                st = (entry or {}).get("s") if isinstance(entry, dict) else None
                if st in EXCUSED_RUN and str(b).isdigit() and lo < int(b) <= hi:
                    out.setdefault((tf, int(b)), f"live job record: {st}")
    return out


def run_record(conn: Optional[sqlite3.Connection], day_start: int, tfs: Iterable[str]) -> Optional[dict]:
    """{(tf, boundary): entry} of the live job's own record of the day (state "dsrun:<UTC day>", the day of the bar
    that closes at the boundary, so every boundary in (day_start, day_start + 1 day] is in that one record), or None
    when the day has no record at all (then the heuristic of ``excused_boundaries`` applies)."""
    if conn is None:
        return None
    day = dt.datetime.fromtimestamp(day_start / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
    try:
        r = conn.execute("SELECT data FROM state WHERE k = ?", (DS_RUN_KEY + day,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if r is None:
        return None
    try:
        rec = json.loads(r[0])
    except (ValueError, TypeError):
        rec = None
    by_tf = rec.get("tfs") if isinstance(rec, dict) and rec.get("v") == 1 else None
    if not isinstance(by_tf, dict):
        return None
    tfs = list(tfs)
    lo, hi = day_start, day_start + DAY_MS
    out: dict = {}
    for tf, by_b in by_tf.items():
        if tf not in tfs or not isinstance(by_b, dict):
            continue
        for b, entry in by_b.items():
            if str(b).isdigit() and lo < int(b) <= hi and isinstance(entry, dict):
                out[(tf, int(b))] = entry
    return out


def _agg(rows) -> Optional[tuple]:
    if not len(rows):
        return None
    a = np.asarray(rows, dtype=float)
    return (a[0, 1], a[:, 2].max(), a[:, 3].min(), a[-1, 4], float(np.nansum(a[:, 5])))


def data_difference(conn: sqlite3.Connection, bars: dict, symbol: str, tf: str, bar_close: int) -> tuple[bool, str]:
    """(True, what differs) when the live service's own 1m bars of this chart bar (paper3.db live_bars, every minute
    present) differ from the final 5m bars; (False, why not) otherwise."""
    bo = bar_close - TF_MS[tf]
    try:
        live = conn.execute("SELECT ts, open, high, low, close, volume FROM live_bars WHERE symbol = ? AND ts >= ? "
                            "AND ts < ? ORDER BY ts", (symbol, bo, bar_close)).fetchall()
    except sqlite3.OperationalError:
        live = []
    minutes = TF_MS[tf] // MIN
    if len({int(r[0]) for r in live}) < minutes:
        return False, f"live 1m bars of {symbol} recorded for {len(live)} of {minutes} minutes"
    coin = coin_of(symbol)
    cols = _span(bars[coin], bo, bar_close) if coin in bars else None
    if cols is None or not len(cols[0]):
        return False, f"no final 5m bars of {symbol}"
    fin = _agg(np.column_stack(cols))
    liv = _agg([tuple(0.0 if x is None else x for x in r) for r in live])
    names = ("open", "high", "low", "close", "volume")
    diff = [f"{n} live {a:.10g} final {b:.10g}" for n, a, b in zip(names, liv, fin)
            if not math.isclose(a, b, rel_tol=VOLUME_RTOL if n == "volume" else PRICE_RTOL, abs_tol=0.0)]
    if len(cols[0]) < TF_MS[tf] // FIVE:
        diff.append(f"final 5m bars {len(cols[0])} of {TF_MS[tf] // FIVE}")
    return (True, f"{symbol}: " + "; ".join(diff)) if diff else (False, f"{symbol}: live bar equals the final bar")


# ====================================================================== the check
def _kst(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, KST).strftime("%m-%d %H:%M")


def _record_why(entry: Optional[dict], sym: str) -> Optional[str]:
    """Record mode: None when the live job computed ``sym`` at this boundary (compare it), else why it did not."""
    if entry is None:
        return "boundary not in the live job's record (the runner never reached it)"
    st = entry.get("s")
    if st != "ran":
        return f"live job record: {st}"
    no = entry.get("no") or {}
    if sym in no and sym not in (entry.get("ok") or ()):
        return f"live job record: {sym} not computed ({no[sym]})"
    return None                     # computed (or, unlisted, compared as computed: the job ran)


def compare(live: dict, rec: dict, accounts: dict, conn: Optional[sqlite3.Connection], bars: dict,
            unchecked: dict, excused: Optional[dict] = None, record: Optional[dict] = None,
            until: Optional[int] = None, day_start: Optional[int] = None) -> dict:
    """Classify every (tf, bar_close, def, symbol) of the live rows and the recompute (see the module docstring).
    ``excused``: {(tf, boundary): why} of the boundaries the live service said it skipped (``excused_boundaries``;
    the heuristic, used only when ``record`` is None). ``record``: the live job's own record of the day
    (``run_record``): it decides which coins are compared. ``until``: the last boundary the record must hold."""
    excused = excused or {}
    covered = {(tf, bc) for tf, bc, _d, _s in live}
    keys = set(live) | set(rec)
    res = {"agree": 0, "checked": 0, "uncovered": 0, "before_start": 0, "unchecked_coin": 0,
           "mismatches": [], "data": [], "excused": []}
    uncovered_b: set = set()
    fired_b: dict = {}                  # uncovered (tf, boundary) -> [(def, symbol, side)] the recompute fired
    why_b: dict = {}                    # record mode: uncovered (tf, boundary) -> the record's reason
    for key in sorted(keys):
        tf, bc, d, sym = key
        created = accounts.get((d, tf))
        if created is None:
            continue
        if bc <= created:
            res["before_start"] += 1
            continue
        if sym in unchecked.get(tf, {}):
            res["unchecked_coin"] += 1
            continue
        lv = live.get(key, (0, None))
        rs = rec.get(key, 0)
        entry = None
        if record is not None:
            entry = record.get((tf, bc))
            why = _record_why(entry, sym)
            if why is not None:
                res["uncovered"] += 1
                uncovered_b.add((tf, bc))
                if entry is None:
                    continue                # the boundary-level "unrecorded" mismatch below, once per boundary
                if rs:
                    fired_b.setdefault((tf, bc), []).append((d, sym, rs))
                    why_b.setdefault((tf, bc), why)
                continue
        elif (tf, bc) not in covered:
            res["uncovered"] += 1
            uncovered_b.add((tf, bc))
            if rs:
                fired_b.setdefault((tf, bc), []).append((d, sym, rs))
            continue
        res["checked"] += 1
        if lv[0] == rs:
            res["agree"] += 1
            continue
        kind = "missing" if lv[0] == 0 else ("extra" if rs == 0 else "flip")
        row = {"tf": tf, "bar_close": bc, "def": d, "symbol": sym, "live": lv[0], "status": lv[1], "recomputed": rs,
               "kind": kind}
        if kind == "missing" and d == F14 and entry is not None and sym in (entry.get("err") or {}):
            row["data"] = f"live job record: {sym} reported {entry['err'][sym]}"
            res["excused"].append(row)      # F14_SMT lost on a coin whose BTC context failed (the job said so)
            continue
        if kind == "missing" and not any(k[0] == tf and k[1] == bc and k[3] == sym for k in live):
            row["note"] = "no DeepSeek row of this coin at this boundary (its live job may have failed)"
        explained, why = (False, "no live bars") if conn is None else data_difference(conn, bars, sym, tf, bc)
        if not explained and d == F14 and sym != symbol_of(BTC) and conn is not None:
            explained, why2 = data_difference(conn, bars, symbol_of(BTC), tf, bc)
            why = f"{why}; {why2}"
        row["data"] = why
        (res["data"] if explained else res["mismatches"]).append(row)
    for (tf, bc), fired in sorted(fired_b.items()):
        d, sym, side = fired[0]
        row = {"tf": tf, "bar_close": bc, "def": d, "symbol": sym, "live": 0, "status": None, "recomputed": side,
               "kind": "uncovered", "n": len(fired)}
        if record is not None:
            row["data"] = why_b[(tf, bc)]
            res["excused"].append(row)
        elif (tf, bc) in excused:
            row["data"] = excused[(tf, bc)]
            res["excused"].append(row)
        else:
            row["data"] = ("no DeepSeek row of any coin at this boundary while the recompute fired, and no DeepSeek "
                           "timeout / failure alert or job record for it")
            res["mismatches"].append(row)
    if record is not None:
        # every DeepSeek boundary of the day with an open account on its timeframe must be in the record
        days = ({day_start // DAY_MS} if day_start is not None else
                {(bc - 1) // DAY_MS for _tf, bc, _d, _s in keys} | {(b - 1) // DAY_MS for _tf, b in record})
        tfs = sorted({tf for _d, tf in accounts}, key=lambda t: TF_MS.get(t, 0))
        for day in sorted(days):
            lo = day * DAY_MS
            for tf in tfs:
                if tf not in TF_MS:
                    continue
                for bc in range(lo + TF_MS[tf], lo + DAY_MS + 1, TF_MS[tf]):
                    if (until is not None and bc > until) or (tf, bc) in record:
                        continue
                    if not any(t == tf and bc > ts for (_d, t), ts in accounts.items()):
                        continue
                    uncovered_b.add((tf, bc))
                    n = sum(1 for (t, b, d, _s), side in rec.items()
                            if t == tf and b == bc and side and (d, t) in accounts and bc > accounts[(d, t)])
                    res["mismatches"].append({"tf": tf, "bar_close": bc, "def": None, "symbol": None, "live": 0,
                                              "status": None, "recomputed": 0, "kind": "unrecorded", "n": n,
                                              "data": _record_why(None, "")})
    res["uncovered_boundaries"] = len(uncovered_b)
    return res


def _line(day: str, rep: dict) -> str:
    head = f"딥시크 밤 재계산 {day} (UTC)"
    if rep["status"] == "no_accounts":
        return f"{head}: 딥시크 계좌 없음 (확인할 것 없음)"
    if rep["status"] == "silent":
        tfs = rep.get("silent_tfs") or []
        n = sum((rep.get("recomputed_tf") or {}).get(tf, 0) for tf in tfs) or rep["recomputed"]
        return (f"{head}: {'·'.join(tfs)} 실시간 딥시크 신호 기록 0건인데 재계산은 {n}건 · 딥시크 신호가 멈췄는지 확인"
                + (f" · 불일치 {rep['n_mismatch']}건" if rep["n_mismatch"] else ""))
    tail = (f"일치 {rep['agree']:,}/{rep['checked']:,} · 자료 차이 {len(rep['data'])}건(설명됨) · "
            f"기록 없는 경계 {rep['uncovered_boundaries']}개")
    if rep.get("n_excused"):
        tail += f"(그중 알림 있는 건너뜀 {rep['n_excused']}개)"
    if rep["unchecked"]:
        tail += f" · 못 본 코인·봉 {sum(len(v) for v in rep['unchecked'].values())}개"
    if rep["n_mismatch"]:
        m = rep["mismatches"][0]
        if m.get("kind") == "uncovered":
            ex = (f"{m['tf']} {_kst(m['bar_close'])} KST 경계에 실시간 딥시크 기록 없음, 재계산 신호 {m.get('n', 1)}건, "
                  "건너뜀 알림 없음")
        elif m.get("kind") == "unrecorded":
            ex = f"{m['tf']} {_kst(m['bar_close'])} KST 경계가 실시간 딥시크 작업 기록에 없음 (봇이 그 경계를 못 지남)"
        else:
            ex = (f"{m['def']} {m['tf']} {m['symbol'][:-4]} {_kst(m['bar_close'])} KST 실시간 {SIDE_KO[m['live']]} / "
                  f"재계산 {SIDE_KO[m['recomputed']]}")
        return f"{head}: 불일치 {rep['n_mismatch']}건 (예: {ex}) · {tail}"
    return f"{head}: 불일치 0 · {tail}"


def run_check(conn: sqlite3.Connection, source, day_start: int, C=None, lib=None, tfs: Iterable[str] = DS200_TFS,
              windows: Optional[dict] = None, now_ms: Optional[int] = None) -> dict:
    """The whole check for the UTC day starting at ``day_start`` (ms). Returns the report (``status``: "ok",
    "mismatch", "silent" or "no_accounts"; ``line``: the one-line Korean summary)."""
    day = dt.datetime.fromtimestamp(day_start / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
    tfs = [tf for tf in tfs if tf in TF_MS]
    accounts = {k: v for k, v in ds_accounts(conn).items() if k[1] in tfs}
    rep: dict = {"day": day, "checked_at": int(now_ms if now_ms is not None else time.time() * 1000), "tfs": tfs,
                 "accounts": len(accounts), "history_5m": {tf: history_5m(tf, windows) for tf in tfs},
                 "live_rows": 0, "recomputed": 0, "agree": 0, "checked": 0, "uncovered": 0,
                 "uncovered_boundaries": 0, "before_start": 0, "unchecked": {}, "notes": [], "mismatches": [],
                 "n_mismatch": 0, "data": [], "pins": None, "silent_tfs": [], "recomputed_tf": {}, "excused": [],
                 "n_excused": 0}
    if not accounts or min(accounts.values()) >= day_start + DAY_MS:
        rep["status"] = "no_accounts"
        rep["line"] = _line(day, rep)
        return rep
    if C is None:
        C = load_lib_c()
        rep["pins"] = dict(_PINS or {})
    if lib is None:
        lib = getattr(C, "_dscheck_lib", None)
        if lib is None:
            from . import sweepsig
            lib = sweepsig.lib()
    live = live_rows(conn, accounts, day_start, tfs)
    rep["live_rows"] = len(live)
    start = day_start - max(history_5m(tf, windows) for tf in tfs) * FIVE
    bars = {coin: source.load(symbol_of(coin), start, day_start + DAY_MS) for coin in COINS}
    rec: dict = {}
    unchecked: dict = {}
    for tf in tfs:
        r, u, notes = recompute(C, lib, bars, tf, day_start, windows)
        rec.update({(tf, bc, d, s): side for (bc, d, s), side in r.items()})
        if u:
            unchecked[tf] = u
        rep["notes"] += notes
    counted = [(tf, bc, d) for (tf, bc, d, _s) in rec if (d, tf) in accounts and bc > accounts[(d, tf)]]
    rep["recomputed"] = len(counted)
    rep["recomputed_tf"] = {tf: sum(1 for t, _b, _d in counted if t == tf) for tf in tfs}
    rep["unchecked"] = unchecked
    record = run_record(conn, day_start, tfs)
    rep["record"] = record is not None
    now = rep["checked_at"]
    res = compare(live, rec, accounts, conn, bars, unchecked,
                  excused_boundaries(conn, day_start, tfs) if record is None else None,
                  record=record, until=now - SETTLE_MS * 10, day_start=day_start)
    for k in ("agree", "checked", "uncovered", "uncovered_boundaries", "before_start"):
        rep[k] = res[k]
    rep["n_mismatch"] = len(res["mismatches"])
    rep["mismatches"] = res["mismatches"][:MAX_LISTED]
    rep["data"] = res["data"][:MAX_LISTED]
    rep["n_excused"] = len(res["excused"])
    rep["excused"] = res["excused"][:MAX_LISTED]
    # the silent rule per timeframe: accounts on tf the whole day, no live DeepSeek row of tf, the recompute fired
    for tf in tfs:
        made = [ts for (d, t), ts in accounts.items() if t == tf]
        if (made and min(made) <= day_start and rep["recomputed_tf"].get(tf)
                and not any(k[0] == tf for k in live)):
            rep["silent_tfs"].append(tf)
    if rep["silent_tfs"]:
        rep["status"] = "silent"
    else:
        rep["status"] = "mismatch" if rep["n_mismatch"] else "ok"
    rep["line"] = _line(day, rep)
    return rep


def _write(path: str, text: str) -> None:
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_report(out_dir: str, rep: dict) -> None:
    """<out>/last.txt (the one line), <out>/last.json and <out>/days/<day>.json, each replaced atomically."""
    os.makedirs(os.path.join(out_dir, "days"), exist_ok=True)
    body = json.dumps(rep, ensure_ascii=False, indent=1, default=str)
    _write(os.path.join(out_dir, "days", f"{rep['day']}.json"), body)
    _write(os.path.join(out_dir, "last.json"), body)
    _write(os.path.join(out_dir, "last.txt"), rep["line"].replace("\n", " ") + "\n")


def read_summary(out_dir: str = DEFAULT_OUT) -> Optional[str]:
    """The last one-line summary (for the 09:20 report), or None when the check never ran."""
    try:
        with open(os.path.join(out_dir, "last.txt"), encoding="utf-8") as fh:
            return fh.readline().strip() or None
    except OSError:
        return None


def no_db_report(day_start: int, path: str, now_ms: int) -> dict:
    """The report when there is no paper3.db at all (a fresh server, or a check during a reset): nothing to check."""
    day = dt.datetime.fromtimestamp(day_start / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
    return {"day": day, "checked_at": now_ms, "status": "no_accounts", "accounts": 0, "db": path,
            "line": f"딥시크 밤 재계산 {day} (UTC): paper3.db 없음 ({path}) · 확인할 것 없음"}


def exit_code(rep: dict) -> int:
    return 1 if rep["status"] in ("mismatch", "silent") else 0


def _day_start(day: Optional[str], now_ms: int) -> int:
    if day:
        d = dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp() * 1000)
    return (now_ms // DAY_MS - 1) * DAY_MS


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m paperbot.dscheck", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="recompute one UTC day (default yesterday) and compare with the live rows")
    r.add_argument("--db", default=DEFAULT_DB, help="paper3.db (opened read-only)")
    r.add_argument("--out", default=DEFAULT_OUT, help="folder for last.txt / last.json / days/ and the bar cache")
    r.add_argument("--day", help="UTC day YYYY-MM-DD (default: yesterday)")
    r.add_argument("--bars-dir", help="research-layout <coin>-5m.csv.gz files instead of Binance klines")
    r.add_argument("--cache", help="5m kline cache (default <out>/bars5m.db)")
    r.add_argument("--tfs", default=",".join(DS200_TFS), help="timeframes to check (default all four)")
    s = sub.add_parser("show", help="print the last one-line summary")
    s.add_argument("--out", default=DEFAULT_OUT)
    a = p.parse_args(argv)
    if a.cmd == "show":
        line = read_summary(a.out)
        print(line or "딥시크 밤 재계산: 아직 실행 안 됨")
        return 0
    now = int(time.time() * 1000)
    try:
        day_start = _day_start(a.day, now)
        if day_start + DAY_MS > now:
            raise DsCheckError("the day has not ended yet")
        if not os.path.exists(a.db):      # review finding 3: no database is "nothing to check", never a warning
            rep = no_db_report(day_start, a.db, now)
        else:
            conn = connect_ro(a.db)
            source = CsvSource(a.bars_dir) if a.bars_dir else RestSource(a.cache or os.path.join(a.out, "bars5m.db"))
            rep = run_check(conn, source, day_start, tfs=[t for t in a.tfs.split(",") if t], now_ms=now)
    except Exception as exc:  # noqa: BLE001  (any failure: the one line says so, exit 2 -> the owners' warning)
        why = str(exc) if isinstance(exc, (DsCheckError, ValueError)) else f"{type(exc).__name__}: {exc}"
        line = f"딥시크 밤 재계산: 점검 못 함 ({why})"[:500]
        print(line, file=sys.stderr)
        try:
            os.makedirs(a.out, exist_ok=True)
            _write(os.path.join(a.out, "last.txt"), line + "\n")
        except OSError:
            pass
        return 2
    try:
        write_report(a.out, rep)
    except OSError as exc:            # exit 1 means "signals differ": a write failure is "could not run"
        print(f"{rep['line']}\n딥시크 밤 재계산: 결과 파일을 쓰지 못함 ({exc})", file=sys.stderr)
        return 2
    print(rep["line"])
    for m in rep.get("mismatches", [])[:20]:
        print(f"  {m['kind']}: {m['def']} {m['tf']} {m['symbol']} bar_close {m['bar_close']} live {m['live']} "
              f"recomputed {m['recomputed']} ({m['data']})")
    return exit_code(rep)


if __name__ == "__main__":
    raise SystemExit(main())
