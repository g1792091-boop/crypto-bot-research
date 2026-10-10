"""커스텀값 그림자 (custom-value shadow, owners' "2번", 2026-10-10). NOT a trading module: it opens paper3.db read-only,
places no order, sends no Telegram of its own, and nothing on the trading path imports it (it is in no runinfo hash
set, so a change here restarts no 30-day window).

    python -m paperbot.paramshadow run  [--db FILE] [--out DIR] [--max-days N] [--brackets FILE | --allow-example-brackets]
    python -m paperbot.paramshadow show [--out DIR]                  print the last one-line summary

What it does. The 36 locked strategies trade on their default numbers. This job replays, from the run's start, every
strategy x timeframe (15m, 30m, 1h, 4h) a second time with ONE number changed: each parameter of the pre-registered
parameter study (research/entry_study/param_defs/<NAME>.py, hash-checked against DEFS_BC.sha256, the same files the
2026-09-30 study ran) at x0.5, x0.75, x1.25 and x1.5 of its default. Next to them it replays the default the same way
("base"), so a variant is always compared with a default computed by the very same method. Each variant is its own
shadow account of the real rules: v4 settings (config.v3_settings, the run's taker fee), $5,000, the six coins, one
position at a time, the 2 x ATR14 stop, the ladder locks, the quality_v1 leverage group (the signal bar's entry
strength from strength_defs, as the live service records it), funding, liquidation and bust, on Binance's final 1m
bars with mark prices (daily3.fetch_steps), fills at the next minute's open plus slippage (no order book here).

- Signals: the chart frames are built as the live service builds them (recorder.build_frames on final 5m klines,
  at least the live window of 2 x warm-up bars of history before the first day). A signal of a bar that closed after
  the run started and inside the processed days is submitted after the minute that ends at its close, as daily3's
  replay does. param_defs ``signals()`` with no override equals the locked signal bar for bar (tests check it).
- Days: one UTC day at a time, from the day after the last one done (the run's start day on the first night) to
  yesterday, at most ``--max-days`` per night (the first night fills the run so far). Engine states, trades and the
  per-account signal counts of a day are committed together, so a stopped night resumes cleanly. A new run (another
  start), other settings, other definition files or another engine (fingerprint below) start over from the run start.
- Parity: the recomputed default is compared with the real account (paper3.db trades of "<strategy>@<tf>"): the share
  of entries (coin, side, entry minute) both have. Live fills at the order-book price, restarts and late signals mean
  it is never exactly 100%; a low share means the recomputation is not the live account and says so.
- Luck: a cell (strategy x timeframe) tests up to 16 variants, so some beat the default by chance. A variant gets a
  star only with >= MIN_TRADES trades on both sides, a mean per-trade return (P&L / equity before the trade) above
  the default's by more than z(1 - ALPHA / k) standard errors (k = the cell's distinct variants: Bonferroni), AND
  more P&L than the default in both halves of the period. Under "numbers do not matter" each cell stars with
  probability <= ALPHA, so up to ALPHA x cells stars are expected by luck; the summary says how many.

Output (<out>, default /var/lib/paperbot/paramshadow): paramshadow.db (5m kline cache, engine states, the shadow
trades, per-day rows), last.json (the summary the dashboard and the agents read), last.txt (one Korean line),
error.json (the last failure, removed by the next success). Exit status: 0 = done (also: nothing to do, no paper3.db);
2 = it could not run (bars, definitions, brackets): paperbot-failed@ sends the owners' one Korean warning.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import statistics
import sys
import time
import warnings
from dataclasses import asdict
from typing import Callable, Iterable, Optional

import numpy as np
import pandas as pd

from .accounts import DAY_MS, ORIGINAL_KINDS
from .aggregate import TF_MS
from .config import V3_STOP_ATR, V3_SYMBOLS, V3_TRADE_TFS, Settings, v3_settings
from .engine import PaperEngine, engine_state, restore_engine
from .models import Signal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = "/var/lib/paperbot/paper3.db"
DEFAULT_OUT = "/var/lib/paperbot/paramshadow"
VERSION = 1                 # bump when the replay's meaning changes: the shadow is rebuilt from the run start
MIN = 60_000
FIVE = 300_000
MAX_DAYS = 45               # days replayed per night (the first night fills the run so far)
CHUNK_DAYS = 10             # days whose signals are computed in one pass (bounds memory)
MIN_TRADES = 20             # trades a variant and the default each need before a star
ALPHA = 0.05                # per cell, Bonferroni over its distinct variants
MULTS = (0.5, 0.75, 1.25, 1.5)     # the study's multipliers (research/entry_study/analysis_bc.py MULTS)
DEFS_BC_MANIFEST_SHA256 = "185dbcf858e93f694d0775e12925c1904373d0db002a4df7bf3cfcefa3d56044"   # analysis_bc pin (520dad0)
ENGINE_FILES = ("paperbot/engine.py", "paperbot/ladder.py", "paperbot/margin.py", "paperbot/sizing.py",
                "paperbot/policy.py", "paperbot/levrule.py", "paperbot/quality_edges.json", "paperbot/config.py",
                "paperbot/models.py", "paperbot/recorder.py")     # this file's own meaning: VERSION

TEXTS_KO = {
    "what": "기존 36개 매매법을 숫자 하나만 바꿔(×0.5 · ×0.75 · ×1.25 · ×1.5) v4 시작부터 실제와 같은 규칙으로 다시 "
            "계산한 그림자 계좌입니다. 실제 계좌 · 주문 · 30일 판정은 그대로이고, 숫자가 저절로 바뀌는 일은 없습니다.",
    "base": "기본값(재계산) = 같은 방법으로 다시 계산한 기본값 계좌입니다. 변형은 이것과 비교합니다(실제 계좌는 호가로 체결해서 "
            "조금 다릅니다).",
    "parity": "재계산 일치 = 기본값 재계산과 실제 계좌의 진입(코인 · 방향 · 진입 분)이 같은 비율입니다. 실제는 호가로 체결하고 "
              "재시작 · 늦은 신호가 있어 100%는 아닙니다. 많이 낮으면 이 그림자를 믿지 마세요.",
    "luck": "변형을 여러 개 시험하면 우연히 좋아 보이는 것이 꼭 나옵니다. ★는 거래 {n}건 이상이고, 운 기준선(칸마다 시험한 변형 수만큼 "
            "엄격하게) 위이고, 기간 앞 · 뒤 절반 모두 기본값보다 번 변형에만 붙습니다.",
    "caution": "참고용입니다. 처음 몇 주는 거래가 적어 숫자가 많이 흔들립니다. 바꿀지는 두 분이 정합니다(30일 판정 뒤, 기존 계좌는 "
               "그대로 두고 새 계좌로).",
}


class ParamShadowError(RuntimeError):
    """The shadow cannot run (bars, definitions, brackets, database): exit 2."""


# ====================================================================== definitions (hash-checked)
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def defs_manifest() -> dict:
    """{"param_defs/<NAME>.py": sha256, ...} of DEFS_BC.sha256, after checking the manifest against its pin."""
    from . import entry_marks as EM
    data = open(EM.DEFS_SHA, "rb").read()
    if _sha(data) != DEFS_BC_MANIFEST_SHA256:
        raise ParamShadowError(f"DEFS_BC.sha256 sha256 {_sha(data)[:12]} != pinned {DEFS_BC_MANIFEST_SHA256[:12]}")
    return EM.locked_defs()


def param_module(name: str, manifest: Optional[dict] = None):
    """research/entry_study/param_defs/<name>.py, executed from the bytes that match DEFS_BC.sha256."""
    from . import entry_marks as EM
    rel = f"param_defs/{name}.py"
    path = os.path.join(EM.STUDY, rel)
    if not os.path.exists(path):
        raise ParamShadowError(f"{rel} is missing")
    data = open(path, "rb").read()
    want = (manifest or defs_manifest()).get(rel)
    if want != _sha(data):
        raise ParamShadowError(f"{rel}: sha256 {_sha(data)[:12]} != locked {str(want)[:12]}")
    return EM._load(f"_paperbot_paramshadow_{name}_{want[:8]}", path, data)


def variants_of(mod) -> list[dict]:
    """The base and the module's one-number variants: [{key, param, mult, value, default, kind, ov}]."""
    out = [{"key": "base", "param": None, "mult": 1.0, "value": None, "default": None, "kind": None, "ov": {}}]
    mults = tuple(getattr(mod, "MULTIPLIERS", getattr(mod, "MULTS", MULTS)))   # analysis_bc's rule
    if mults != MULTS:
        raise ParamShadowError(f"{mod.NAME}: multipliers {mults} != {MULTS}")
    for p in mod.PARAMS:
        ovs = mod.variants(p)
        if len(ovs) != len(MULTS) or any(list(ov) != [p["name"]] for ov in ovs):
            raise ParamShadowError(f"{mod.NAME}: variants of {p['name']} are not one override per multiplier")
        for m, ov in zip(MULTS, ovs):
            out.append({"key": f"{p['name']}x{m:g}", "param": p["name"], "mult": float(m), "value": ov[p["name"]],
                        "default": p["default"], "kind": p["kind"], "ov": ov})
    return out


def account_id(strategy: str, tf: str, key: str) -> str:
    return f"{strategy}@{tf}#{key}"


def split_account(aid: str) -> tuple[str, str, str]:
    cell, key = aid.split("#", 1)
    s, tf = cell.split("@", 1)
    return s, tf, key


def fingerprint(settings: Settings, manifest: dict) -> str:
    """Changes when the replay would give other numbers: settings, definition files, engine code, VERSION."""
    h = hashlib.sha256(f"v{VERSION}".encode())
    h.update(json.dumps(asdict(settings), sort_keys=True, default=str).encode())
    h.update(json.dumps(manifest, sort_keys=True).encode())
    for rel in ENGINE_FILES:
        p = os.path.join(ROOT, rel)
        h.update(rel.encode() + b"\0" + (open(p, "rb").read() if os.path.exists(p) else b"-"))
    return h.hexdigest()


# ====================================================================== the run (paper3.db, read-only)
def connect_ro(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn.execute("PRAGMA query_only = ON")
    return conn


def run_start_ts(conn) -> Optional[int]:
    """MIN(created_ts) of the run's ORIGINAL accounts (daily3.run_start_ts)."""
    try:
        r = conn.execute(f"SELECT MIN(created_ts) FROM accounts WHERE kind IN ({', '.join('?' * len(ORIGINAL_KINDS))})",
                         ORIGINAL_KINDS).fetchone()
    except sqlite3.OperationalError:
        return None
    return int(r[0]) if r and r[0] is not None else None


def run_taker_fee(conn) -> Optional[float]:
    try:
        r = conn.execute("SELECT data FROM state WHERE k = 'run'").fetchone()
    except sqlite3.OperationalError:
        return None
    return json.loads(r[0]).get("taker_fee") if r else None


def real_trades(conn, since: int, until: int) -> dict[str, list[dict]]:
    """{"<strategy>@<tf>": [trade]} of the core accounts (kind 'strategy') closed in [since, until)."""
    try:
        ids = {r[0] for r in conn.execute("SELECT account_id FROM accounts WHERE kind = 'strategy'")}
    except sqlite3.OperationalError:
        return {}
    out: dict[str, list[dict]] = {}
    q = ("SELECT account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, equity_after, data FROM trades "
         "WHERE exit_time >= ? AND exit_time < ? ORDER BY exit_time, id")
    for aid, sym, et, xt, why, lev, pnl, eq, data in conn.execute(q, (since, until)):
        if aid not in ids:
            continue
        try:
            side = int(json.loads(data or "{}").get("side", 0))
        except (ValueError, TypeError):
            side = 0
        out.setdefault(aid, []).append({"symbol": sym, "side": side, "entry_time": int(et), "exit_time": int(xt),
                                        "exit_reason": why, "leverage": lev, "pnl": float(pnl),
                                        "equity_after": float(eq)})
    return out


# ====================================================================== bars
class FrameSource:
    """5m bars from memory: {symbol: (ts ms, open, high, low, close, volume)} (tests)."""

    def __init__(self, data: dict):
        self.data = {s: tuple(np.asarray(a, dtype=np.int64 if i == 0 else float) for i, a in enumerate(v))
                     for s, v in data.items()}

    def load(self, symbol: str, start: int, end: int) -> tuple:
        if symbol not in self.data:
            raise ParamShadowError(f"no 5m bars for {symbol}")
        cols = self.data[symbol]
        keep = (cols[0] >= start) & (cols[0] < end)
        return tuple(a[keep] for a in cols)


class RestSource:
    """Binance's final public 5m klines (no key) through dscheck's SQLite cache class, in this job's own file."""

    def __init__(self, cache_path: str, rest=None):
        from .dscheck import RestSource as _Rest
        self._src = _Rest(cache_path, rest=rest)

    def load(self, symbol: str, start: int, end: int) -> tuple:
        from .dscheck import DsCheckError
        try:
            return self._src.load(symbol, start, end)
        except DsCheckError as exc:
            raise ParamShadowError(str(exc)) from None


def chart_frame(lib, cols: tuple, tf: str) -> pd.DataFrame:
    """The live service's chart frame (recorder.build_frames: forming bar and a partial first bin dropped)."""
    from .recorder import build_frames
    ts, o, h, l, c, v = cols
    df5 = pd.DataFrame({"ts": pd.to_datetime(np.asarray(ts, dtype=np.int64), unit="ms", utc=True), "open": o,
                        "high": h, "low": l, "close": c, "volume": v})
    if not len(df5):
        return df5
    return build_frames(lib, df5, [tf])[tf]


# ====================================================================== signals
def _strength_feats(st: Optional[dict], smod, i: int, side: int) -> Optional[dict]:
    """The signal bar's strength in the shape levrule.quality_score reads ({"side", "features": [{name, value}]})."""
    if smod is None:
        return None
    if st is None or "error" in st:
        return {"error": (st or {}).get("error", "strength failed")}
    feats = []
    for f in smod.FEATURES:
        long_v, short_v = st["arrays"][f["name"]]
        v = float((long_v if side > 0 else short_v)[i])
        feats.append({"name": f["name"], "value": v if math.isfinite(v) else None,
                      "higher_is_stronger": bool(f["higher_is_stronger"])})
    return {"side": int(side), "features": feats}


def chunk_signals(lib, source, cells: dict, symbols: Iterable[str], tfs: Iterable[str], start: int, end: int,
                  run_start: int, log: Callable[[str], None] = lambda s: None) -> tuple[dict, dict, list]:
    """Signals of every account whose bar closed in (start, end] and after ``run_start``.

    ``cells``: {strategy: (param module, strength module or None, [variants])}. Returns ({bar_close: [(aid, Signal)]},
    {UTC day: {aid: [n_signals, n_differing_from_base]}}, [data notes]); a bar closing at 00:00 belongs to the day
    before (its signal is replayed there)."""
    from .entry_marks import _contained
    from .sigservice import window_5m
    by_close: dict[int, list] = {}
    counts: dict[str, list] = {}
    notes: list[str] = []
    for tf in tfs:
        span, w = TF_MS[tf], lib.warmup_bars(tf)
        for sym in symbols:
            cols = source.load(sym, start - window_5m(lib, tf) * FIVE, end)
            df = chart_frame(lib, cols, tf)
            if len(df) <= w:
                notes.append(f"{sym} {tf}: 차트 봉 {len(df)}개(필요 {w + 1}개 이상), 이 구간 신호 없음")
                continue
            t_open = (df["ts"].astype("int64") // 1_000_000).to_numpy(np.int64)
            close = t_open + span
            idx = np.flatnonzero((close > max(start, run_start)) & (close <= end) & (np.arange(len(df)) >= w))
            if not len(idx):
                continue
            atr = lib.fg.atr(df, 14).to_numpy(float)
            days = np.array([utc_day(int(x) - 1) for x in close[idx]])
            day_set = sorted(set(days.tolist()))
            for strategy, (pmod, smod, variants) in cells.items():
                base_side = None
                st = None
                for v in variants:
                    with _contained(), warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        lo, sh = pmod.signals(df, tf, **v["ov"])
                    side = np.where(np.asarray(lo, bool), 1, np.where(np.asarray(sh, bool), -1, 0))[idx]
                    if base_side is None:
                        base_side = side
                    aid = account_id(strategy, tf, v["key"])
                    for d in day_set:
                        m = days == d
                        c = counts.setdefault(d, {}).setdefault(aid, [0, 0])
                        c[0] += int(np.count_nonzero(side[m]))
                        c[1] += int(np.count_nonzero(side[m] != base_side[m]))
                    hits = np.flatnonzero(side)
                    if not len(hits):
                        continue
                    if st is None and smod is not None:
                        try:
                            with _contained(), warnings.catch_warnings():
                                warnings.simplefilter("ignore")
                                st = {"arrays": smod.strength(df, tf)}
                        except Exception as exc:  # noqa: BLE001  live: a failed strength sizes 'normal'
                            st = {"error": f"{type(exc).__name__}: {exc}"[:200]}
                    for h in hits:
                        i = int(idx[h])
                        a = float(atr[i])
                        if not (math.isfinite(a) and a > 0):
                            continue                       # live: NO_ATR, never traded
                        s = int(side[h])
                        meta = {"stop_dist": V3_STOP_ATR * a, "account": aid,
                                "ctx": {"strength": _strength_feats(st, smod, i, s)}}
                        sig = Signal(ts=int(close[i]) - 1, symbol=sym, timeframe=tf, strategy_id=strategy, side=s,
                                     stop_price=0.0, tier="best", atr=a, meta=meta)
                        by_close.setdefault(int(close[i]), []).append((aid, sig))
        log(f"signals {tf}: {sum(len(v) for v in by_close.values())} so far")
    return by_close, counts, notes


# ====================================================================== replay
def replay_day(engines: dict, active: set, by_close: dict, steps, brackets) -> None:
    """One day of 1m steps. Only engines with a position or a pending signal are stepped: an idle engine's step
    changes nothing but its last-seen marks (equity stays its wallet), so skipping it gives the same trades."""
    for ts, bars, funding in steps:
        tb = {s: b for s, b in bars.items() if s in brackets}
        for aid in sorted(active):
            e = engines[aid]
            e.step(tb, funding)
            e.outcomes.clear()
            if e.position is None and not e.pending:
                active.discard(aid)
        for aid, sig in by_close.get(ts + MIN, ()):
            engines[aid].submit(sig)
            active.add(aid)


# ====================================================================== store
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS days (day TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trades (
    account TEXT NOT NULL, symbol TEXT NOT NULL, side INTEGER NOT NULL, signal_ts INTEGER NOT NULL,
    entry_time INTEGER NOT NULL, exit_time INTEGER NOT NULL, exit_reason TEXT NOT NULL, leverage INTEGER NOT NULL,
    tier TEXT, margin REAL NOT NULL, pnl REAL NOT NULL, roe REAL NOT NULL, equity_after REAL NOT NULL);
CREATE INDEX IF NOT EXISTS trades_acct ON trades (account, exit_time);
CREATE TABLE IF NOT EXISTS sigcounts (account TEXT PRIMARY KEY, n INTEGER NOT NULL, diff INTEGER NOT NULL);
"""


def open_store(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def _get(conn, k: str):
    r = conn.execute("SELECT data FROM meta WHERE k = ?", (k,)).fetchone()
    return json.loads(r[0]) if r else None


def _put(conn, k: str, v) -> None:
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (k, json.dumps(v, default=str)))


def reset_store(conn) -> None:
    for t in ("meta", "days", "trades", "sigcounts"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()


def utc_day(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def day_start(day: str) -> int:
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


# ====================================================================== one night
def run(paper_db: str, out_dir: str, source, rest, settings: Optional[Settings], brackets: dict, specs: dict,
        now_ms: int, max_days: int = MAX_DAYS, strategies: Optional[list] = None, tfs=V3_TRADE_TFS,
        symbols=V3_SYMBOLS, fetch_steps: Optional[Callable] = None, log: Callable[[str], None] = print,
        brackets_src: str = "") -> dict:
    """Replay the days not done yet, then write the summary. Returns the summary dict."""
    from . import sweepsig
    from .sigservice import strategy_names
    if not os.path.exists(paper_db):
        summ = {"status": "no_run", "generated_ms": now_ms, "line_ko": "커스텀값 그림자: 실행 중인 규칙봇 기록 없음"}
        write_outputs(out_dir, summ)
        return summ
    conn = connect_ro(paper_db)
    run_start = run_start_ts(conn)
    if run_start is None:
        summ = {"status": "no_run", "generated_ms": now_ms, "line_ko": "커스텀값 그림자: 계좌가 아직 없음"}
        write_outputs(out_dir, summ)
        return summ
    if settings is None:
        fee = run_taker_fee(conn)
        settings = v3_settings(**({"taker_fee": fee} if fee else {}))
    lib = sweepsig.lib()
    names = strategies or strategy_names(lib)
    manifest = defs_manifest()
    cells = {}
    for n in names:
        from .entry_marks import strength_module
        pmod = param_module(n, manifest)
        try:
            smod = strength_module(n)
        except Exception as exc:  # noqa: BLE001  live sizes such a strategy 'normal'
            log(f"{n}: strength definition refused ({exc}); its signals size as 'normal'")
            smod = None
        cells[n] = (pmod, smod, variants_of(pmod))
    accounts = [account_id(n, tf, v["key"]) for n in names for tf in tfs for v in cells[n][2]]

    store = open_store(os.path.join(out_dir, "paramshadow.db"))
    fp = fingerprint(settings, manifest)
    meta = _get(store, "run") or {}
    if (meta.get("run_start") != run_start or meta.get("fingerprint") != fp
            or sorted(meta.get("accounts") or []) != sorted(accounts)):
        if meta:
            log("run, settings, definitions, engine or account list changed: starting over from the run start")
        reset_store(store)
        meta = {"run_start": run_start, "fingerprint": fp, "accounts": accounts, "last_day": None,
                "started_ms": now_ms}
        _put(store, "run", meta)
        store.commit()

    engines: dict[str, PaperEngine] = {}
    saved = _get(store, "engines") or {}
    for aid in accounts:
        e = PaperEngine(settings, brackets, symbol_specs=specs, book=aid)
        if aid in saved:
            restore_engine(e, saved[aid])
        engines[aid] = e
    active = {aid for aid, e in engines.items() if e.position is not None or e.pending}

    yesterday = utc_day(now_ms - DAY_MS)
    first = utc_day(run_start) if meta.get("last_day") is None else utc_day(day_start(meta["last_day"]) + DAY_MS)
    todo = []
    d = first
    while d <= yesterday and len(todo) < max_days:
        todo.append(d)
        d = utc_day(day_start(d) + DAY_MS)
    if fetch_steps is None:
        from .daily3 import fetch_steps as _fs
        fetch_steps = _fs
    notes_all: list[str] = []
    t0 = time.time()
    for c0 in range(0, len(todo), CHUNK_DAYS):
        chunk = todo[c0:c0 + CHUNK_DAYS]
        a, b = day_start(chunk[0]), day_start(chunk[-1]) + DAY_MS
        by_close, counts, notes = chunk_signals(lib, source, cells, symbols, tfs, a, b, run_start, log=log)
        notes_all += notes
        for day in chunk:
            s0 = day_start(day)
            try:
                steps = fetch_steps(rest, list(symbols), s0, s0 + DAY_MS)
            except Exception as exc:  # noqa: BLE001
                raise ParamShadowError(f"1m bars of {day} unavailable: {type(exc).__name__}: {exc}"[:300]) from None
            day_sigs = {k: v for k, v in by_close.items() if s0 < k <= s0 + DAY_MS}
            replay_day(engines, active, day_sigs, steps, brackets)
            rows = []
            for aid, e in engines.items():
                for t in e.trades:
                    rows.append((aid, t.symbol, t.side, t.signal_ts, t.entry_time, t.exit_time, t.exit_reason,
                                 t.leverage, t.tier, t.margin, t.pnl, t.roe, t.equity_after))
                e.trades.clear()
            store.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            store.execute("INSERT OR REPLACE INTO days VALUES (?,?,?)",
                          (day, now_ms, json.dumps({"steps": len(steps), "trades": len(rows),
                                                    "signals": sum(len(v) for v in day_sigs.values())})))
            meta["last_day"] = day
            _put(store, "run", meta)
            _put(store, "engines", {aid: engine_state(e) for aid, e in engines.items()})
            store.executemany("INSERT INTO sigcounts VALUES (?,?,?) ON CONFLICT(account) DO UPDATE SET "
                              "n = n + excluded.n, diff = diff + excluded.diff",
                              [(aid, n, df_) for aid, (n, df_) in counts.get(day, {}).items()])
            store.commit()
            log(f"{day}: {len(steps)} minutes, {len(rows)} shadow trades ({time.time() - t0:.0f} s)")
    through = meta.get("last_day")
    nxt = utc_day(run_start) if through is None else utc_day(day_start(through) + DAY_MS)
    remaining = max(0, (day_start(yesterday) - day_start(nxt)) // DAY_MS + 1) if nxt <= yesterday else 0
    summ = summarize(store, conn, cells, tfs, run_start, through, now_ms, settings, engines, notes_all,
                     remaining=remaining, brackets_src=brackets_src)
    write_outputs(out_dir, summ)
    store.close()
    conn.close()
    return summ


# ====================================================================== summary
def _stats(rows: list[tuple], initial: float, mid: int) -> dict:
    """rows: (exit_time, pnl, equity_after) in exit order."""
    n = len(rows)
    rets, eq, peak, dd = [], initial, initial, 0.0
    h1 = h2 = 0.0
    wins = 0
    for xt, pnl, eq_after in rows:
        before = eq_after - pnl
        rets.append(pnl / before if before > 0 else 0.0)
        wins += pnl > 0
        if xt < mid:
            h1 += pnl
        else:
            h2 += pnl
        eq = eq_after
        peak = max(peak, eq)
        dd = max(dd, 1 - eq / peak if peak > 0 else 0.0)
    return {"trades": n, "wins": wins, "win_rate": wins / n if n else None, "pnl": round(sum(r[1] for r in rows), 2),
            "equity": round(eq, 2), "max_dd": round(dd, 4), "pnl_h1": round(h1, 2), "pnl_h2": round(h2, 2),
            "mean_ret": statistics.fmean(rets) if rets else None,
            "sd_ret": statistics.stdev(rets) if len(rets) > 1 else None}


def luck_test(v: dict, b: dict, k: int) -> dict:
    """Welch-type z of the mean per-trade return over the default's, against z(1 - ALPHA / k)."""
    z_need = statistics.NormalDist().inv_cdf(1 - ALPHA / max(1, k))
    if (v["trades"] < MIN_TRADES or b["trades"] < MIN_TRADES or v["sd_ret"] is None or b["sd_ret"] is None):
        return {"small": True, "z": None, "z_need": round(z_need, 3), "luck_pp": None, "ratio": None, "beyond": False}
    se = math.sqrt(v["sd_ret"] ** 2 / v["trades"] + b["sd_ret"] ** 2 / b["trades"])
    diff = v["mean_ret"] - b["mean_ret"]
    z = diff / se if se > 0 else 0.0
    return {"small": False, "z": round(z, 3), "z_need": round(z_need, 3), "luck_pp": round(z_need * se * 100, 4),
            "diff_pp": round(diff * 100, 4), "ratio": round(z / z_need, 3), "beyond": z > z_need}


def _parity(base_rows: list[tuple], real: list[dict]) -> dict:
    """Entries (coin, side, entry minute) both have / the real account's trades."""
    a = {(r[0], r[1], r[2] // MIN) for r in base_rows}
    b = {(t["symbol"], t["side"], t["entry_time"] // MIN) for t in real}
    same = len(a & b)
    return {"base_trades": len(a), "real_trades": len(b), "same": same,
            "share": round(same / max(len(a), len(b)), 4) if (a or b) else None}


def summarize(store, conn, cells: dict, tfs, run_start: int, through: Optional[str], now_ms: int,
              settings: Settings, engines: dict, notes: list, remaining: int = 0, brackets_src: str = "") -> dict:
    initial = settings.initial_equity
    end = day_start(through) + DAY_MS if through else run_start
    mid = run_start + (end - run_start) // 2
    rows_by: dict[str, list] = {}
    entries_by: dict[str, list] = {}
    for aid, sym, side, et, xt, pnl, eq in store.execute(
            "SELECT account, symbol, side, entry_time, exit_time, pnl, equity_after FROM trades "
            "ORDER BY exit_time, rowid"):
        rows_by.setdefault(aid, []).append((xt, pnl, eq))
        if aid.endswith("#base"):
            entries_by.setdefault(aid, []).append((sym, side, et))
    counts = {a: (n, d) for a, n, d in store.execute("SELECT account, n, diff FROM sigcounts")}
    real = real_trades(conn, run_start, end) if through else {}
    out_cells = []
    n_var = n_better = n_star = n_tested_cells = 0
    par_same = par_n = 0
    for strategy, (pmod, _smod, variants) in cells.items():
        params = [{"name": p["name"], "default": p["default"], "kind": p["kind"]} for p in pmod.PARAMS]
        for tf in tfs:
            base_id = account_id(strategy, tf, "base")
            b = _stats(rows_by.get(base_id, []), initial, mid)
            b["open"] = engines[base_id].position is not None if base_id in engines else False
            b["bust"] = bool(engines[base_id].bust) if base_id in engines else False
            r_rows = real.get(f"{strategy}@{tf}", [])
            rl = _stats([(t["exit_time"], t["pnl"], t["equity_after"]) for t in r_rows], initial, mid)
            par = _parity(entries_by.get(base_id, []), r_rows)
            if par["share"] is not None:
                par_same += par["same"]
                par_n += max(par["base_trades"], par["real_trades"])
            vs = []
            distinct = [v for v in variants[1:] if counts.get(account_id(strategy, tf, v["key"]), (0, 0))[1] > 0]
            k = len(distinct)
            for v in variants[1:]:
                aid = account_id(strategy, tf, v["key"])
                s = _stats(rows_by.get(aid, []), initial, mid)
                n_sig, n_diff = counts.get(aid, (0, 0))
                same = n_diff == 0
                e = engines.get(aid)
                row = {"key": v["key"], "param": v["param"], "mult": v["mult"], "value": v["value"],
                       "default": v["default"], "same_as_base": same, "signals": n_sig, "signals_diff": n_diff,
                       **{x: s[x] for x in ("trades", "wins", "win_rate", "pnl", "equity", "max_dd")},
                       "open": e.position is not None if e else False, "bust": bool(e.bust) if e else False,
                       "diff_pnl": round(s["pnl"] - b["pnl"], 2)}
                if not same:
                    lt = luck_test(s, b, k)
                    halves = s["pnl_h1"] > b["pnl_h1"] and s["pnl_h2"] > b["pnl_h2"]
                    row.update(luck=lt, both_halves=halves, star=bool(lt["beyond"] and halves))
                    n_var += 1
                    n_better += row["diff_pnl"] > 0
                    n_star += row["star"]
                else:
                    row.update(luck=None, both_halves=None, star=False)
                vs.append(row)
            if k and b["trades"] >= MIN_TRADES:
                n_tested_cells += 1
            out_cells.append({"strategy": strategy, "tf": tf, "params": params, "base": b, "real": rl,
                              "parity": par, "k": k, "variants": vs,
                              "better": sum(1 for x in vs if not x["same_as_base"] and x["diff_pnl"] > 0),
                              "stars": sum(1 for x in vs if x["star"]),
                              "best": max((x for x in vs if not x["same_as_base"]), key=lambda x: x["diff_pnl"],
                                          default=None)})
    for c in out_cells:
        if c["best"] is not None:
            c["best"] = {"key": c["best"]["key"], "diff_pnl": c["best"]["diff_pnl"], "star": c["best"]["star"]}
    days = store.execute("SELECT COUNT(*) FROM days").fetchone()[0]
    parity = round(par_same / par_n, 4) if par_n else None
    expected = round(ALPHA * n_tested_cells, 1)
    summ = {
        "version": VERSION, "status": "ok" if remaining == 0 else "filling", "generated_ms": now_ms,
        "run_start_ms": run_start, "through_day": through, "days": days, "days_remaining": remaining,
        "settings": {"version": settings.version, "initial_equity": initial, "taker_fee": settings.taker_fee,
                     "slippage": settings.slippage_frac, "leverage_rule": settings.leverage_rule,
                     "stop_atr": V3_STOP_ATR},
        "brackets_src": brackets_src, "multipliers": list(MULTS), "min_trades": MIN_TRADES,
        "alpha": ALPHA, "tfs": list(tfs),
        "overview": {"cells": len(out_cells), "variants": n_var, "better": n_better, "stars": n_star,
                     "cells_tested": n_tested_cells, "stars_by_luck": expected, "parity": parity},
        "cells": out_cells, "notes": notes[-50:],
        "texts_ko": {**TEXTS_KO, "luck": TEXTS_KO["luck"].format(n=MIN_TRADES)
                     + f" 모든 칸을 합치면 우연으로도 최대 약 {expected:g}칸에 ★가 붙을 수 있습니다."},
    }
    summ["line_ko"] = summary_line(summ)
    return summ


def _md(day: Optional[str]) -> str:
    return f"{int(day[5:7])}/{int(day[8:10])}" if day else "-"


def summary_line(s: dict) -> str:
    if s.get("status") == "no_run":
        return s.get("line_ko") or "커스텀값 그림자: 실행 중인 규칙봇 기록 없음"
    o = s.get("overview") or {}
    par = "-" if o.get("parity") is None else f"{o['parity'] * 100:.0f}%"
    head = f"커스텀값 그림자 {_md(s.get('through_day'))}까지 {s.get('days', 0)}일"
    if s.get("days_remaining"):
        head += f"(아직 {s['days_remaining']}일 채우는 중)"
    return (f"{head}: 변형 {o.get('variants', 0):,}개 중 기본값보다 번 것 {o.get('better', 0):,} · ★ {o.get('stars', 0)}"
            f"(우연으로도 최대 {o.get('stars_by_luck', 0):g}) · 기본값 재계산 일치 {par}")


# ====================================================================== outputs
def _atomic(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_outputs(out_dir: str, summ: dict) -> None:
    os.makedirs(out_dir, exist_ok=True)
    _atomic(os.path.join(out_dir, "last.json"), json.dumps(summ, ensure_ascii=False, default=str))
    _atomic(os.path.join(out_dir, "last.txt"), (summ.get("line_ko") or summary_line(summ)) + "\n")
    with contextlib.suppress(FileNotFoundError):
        os.remove(os.path.join(out_dir, "error.json"))


def write_error(out_dir: str, msg: str, now_ms: int) -> None:
    os.makedirs(out_dir, exist_ok=True)
    _atomic(os.path.join(out_dir, "error.json"),
            json.dumps({"generated_ms": now_ms, "error": msg[:500],
                        "line_ko": f"커스텀값 그림자: 이번 밤 계산 못 함 ({msg[:120]})"}, ensure_ascii=False))


def read_summary(out_dir: str = DEFAULT_OUT) -> Optional[str]:
    try:
        with open(os.path.join(out_dir, "last.txt"), encoding="utf-8") as fh:
            return fh.readline().strip() or None
    except OSError:
        return None


@contextlib.contextmanager
def _lock(out_dir: str):
    import fcntl
    os.makedirs(out_dir, exist_ok=True)
    fh = open(os.path.join(out_dir, "run.lock"), "w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ParamShadowError("another paramshadow run holds the lock") from None
        yield
    finally:
        fh.close()


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "show"])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--max-days", type=int, default=MAX_DAYS)
    ap.add_argument("--brackets")
    ap.add_argument("--allow-example-brackets", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "show":
        print(read_summary(args.out) or "결과 없음")
        return 0
    now = int(time.time() * 1000)
    try:
        with _lock(args.out):
            if not os.path.exists(args.db):
                summ = run(args.db, args.out, None, None, None, {}, {}, now)
                print(summ["line_ko"])
                return 0
            from .live import _rest, load_brackets
            rest = _rest()
            try:
                brackets, src = load_brackets(rest, list(V3_SYMBOLS), args.brackets, args.allow_example_brackets)
                specs = rest.exchange_info(list(V3_SYMBOLS))
            except SystemExit as exc:
                raise ParamShadowError(f"leverage brackets: {exc}") from None
            except Exception as exc:  # noqa: BLE001
                raise ParamShadowError(f"exchange data: {type(exc).__name__}: {exc}"[:300]) from None
            source = RestSource(os.path.join(args.out, "bars5m.db"), rest=rest)
            summ = run(args.db, args.out, source, rest, None, brackets, specs, now, max_days=args.max_days,
                       brackets_src=src)
    except ParamShadowError as exc:
        write_error(args.out, str(exc), now)
        print(f"paramshadow could not run: {exc}", file=sys.stderr)
        return 2
    print(summ["line_ko"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
