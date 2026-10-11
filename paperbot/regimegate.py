"""장세 문지기 (regime gate) nightly look (research/regimegate/PREREG_REGIMEGATE.md 5.2). NOT a trading module: it
opens paper3.db read-only (when it exists), places no order, sends no Telegram of its own, and nothing on the trading
path imports it (it is in no runinfo hash set, so a change here restarts no 30-day window). It runs from its own code
copy (deploy/regimegate/install_regimegate.sh), never from the rule bot's tree.

    python -m paperbot.regimegate run  [--db FILE] [--out DIR] [--max-days N]
    python -m paperbot.regimegate show [--out DIR]                 the last one-line summary and the verdict lines
    python -m paperbot.regimegate selfcheck                        what the installer checks before it swaps the code

What it does. The pre-registered forward window: every default-number signal of the rule bot's 36 strategies, 15m 30m
1h 4h, six coins, whose bar closes in [2026-10-05 18:35 UTC (the v4 run's start), 2026-10-30 00:00 UTC), each its own
trade from a fixed $5,000 wallet: the live rules (config.v3_settings: the 2 x ATR14 stop, the stepped lock, the
quality_v1 leverage group from the signal bar's entry strength, fees, slippage, funding, isolated-margin liquidation on
mark price) in a PaperEngine of its own per signal, on Binance's final 1m bars with mark prices and real funding (as
paperbot/paramshadow.py replays its 'base'), with the leverage brackets and order-size rules of the pinned
research/fullgrid/exchange.json (no key needed). Signals: the chart frames as the live service builds them, the
hash-checked param_defs defaults, a signal submitted after the minute that ends at its bar's close (paramshadow's
chunk_signals and replay_day, unchanged). The number per signal is its P&L / $5,000; a signal the entry check refuses is
not a trade; a trade still open at the end of the processed days is counted and left out (at the window's end:
2026-10-30 24:00 UTC, as the PREREG says).

Market state at the signal bar: exactly research/fullgrid/regimes.py ``coin_states`` + ``tag`` (장세 on the
strategy's own chart by regime5y, 변동성 of the 15m bar the entry falls in by demobot.regime), computed here on chart
frames built from at least LABEL_DAYS of 5m bars before the window (the 365-day ATR% window and the indicators' warm-up
are inside it; every label at a bar uses bars up to that bar only). Classes, gates (G1, G2, the swapped G1s / G2s),
verdict lines, bootstraps, the coin-flip control and the condition-5 test are research/regimegate/gate.py's own
functions (``evaluate``), imported from the pinned file: this job refuses to run unless PREREG_REGIMEGATE.sha256
matches.

This is a LOOK, never the verdict: the verdict is ``gate.py forward`` on Binance's public daily files after 2026-10-31
(PREREG 5.2: the full grid's kernel, October funding 0, both reads). This look reads the live exit (ladder|2) only (the
engine has no 3R take-profit), uses real funding and the exchange's REST bars, so its numbers can differ slightly.

Days: one UTC day at a time from the window's first day (or the day after the last one done) to yesterday (from
01:05 UTC on: the 15m bar a midnight signal falls in must be final), at most ``--max-days`` per night, up to 2026-10-30
(the day that only finishes the open trades). Signals, trades and the open engines of a day are committed together, so
a stopped night resumes cleanly; other settings, definitions, engine, pinned files or window (fingerprint) start over
from the window's start.

Output (<out>, default /var/lib/paperbot/regimegate): regimegate.db (5m bar cache, signals with their state and result,
open engines, per-day rows), last.json (the look: gate.py's evaluation of the live exit, counts, parity with the real
accounts), last.txt (one Korean line), error.json (the last failure, removed by the next success). Exit status 0 = done
(also: nothing to do); 2 = it could not run (pin, definitions, bars): paperbot-failed@ sends one Korean warning.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import time
from dataclasses import asdict
from typing import Callable, Optional

import numpy as np

from . import paramshadow as PS
from .aggregate import TF_MS
from .config import V3_SYMBOLS, V3_TRADE_TFS, Settings, v3_settings
from .engine import PaperEngine, engine_state, restore_engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE_PY = os.path.join(ROOT, "research", "regimegate", "gate.py")
EXCHANGE_JSON = os.path.join(ROOT, "research", "fullgrid", "exchange.json")
DEFAULT_DB = "/var/lib/paperbot/paper3.db"
DEFAULT_OUT = "/var/lib/paperbot/regimegate"
LIVE_ROOT = "/opt/crypto-bot-research"     # the rule bot's own tree: its engine files are compared with this copy's
VERSION = 1                 # bump when the replay's meaning changes: the look is rebuilt from the window's start
MIN = 60_000
DAY = 86_400_000
MAX_DAYS = 30               # days replayed per night (the first night fills the window so far)
CHUNK_DAYS = 6              # days whose signals are computed in one pass
LABEL_DAYS = 430            # 5m history before the window for the labels: regime5y's 365-day ATR% window plus the
#                             4h EMA50 / ADX14 warm-up (~60 days); demobot's volatility needs 90 days
LABEL_PAD = 3_600_000       # bars after the last processed day, so the 15m bar opening at a midnight close exists
READ = "ladder|2"           # the live exit: the only read this look has (gate.py's second read needs the kernel)
STATES_TFS = ("15m", "4h")  # regimes.coin_states always reads the 15m (변동성) and 4h (큰 흐름) frames

TEXTS_KO = {
    "what": "규칙봇 36개 매매법의 기본값 신호 하나하나를 $5,000 계좌의 한 번 매매로 v4 시작(10/05 18:35 UTC)부터 다시 "
            "계산하고, 신호가 난 봉의 장세(추세장·횡보장·급변장·보통)와 변동성(큼·보통·작음)을 붙여, 장세 문지기가 들인 "
            "신호와 막은 신호를 비교합니다. 실제 계좌 · 주문 · 30일 판정은 그대로입니다.",
    "look": "밤마다 보는 참고 숫자입니다. 판정은 10/31(한국 오전 9시 이후) research/regimegate/gate.py forward가 "
            "바이낸스 공개 파일로 미리 정한 규칙대로 한 번 냅니다. 이 숫자는 지금 청산(2 ATR 손절 + 계단 익절)만 보고, "
            "펀딩은 실제 값이라 판정 숫자와 조금 다를 수 있습니다.",
    "gates": "G1 장세 문지기: 추세형·그 밖 매매법은 추세장에서만, 되돌림형은 횡보장에서만 들임. G2 변동성 문지기: "
             "추세형·그 밖은 변동성 큼에서만, 되돌림형은 작음에서만 들임. 급변장·보통은 G1이 모두 막습니다.",
    "pass": "통과 = 들인 신호와 막은 신호 각 30건 이상, 들인 평균이 막은 평균보다 높고(하루 묶음 부트스트랩 p < 0.05), 들인 "
            "평균이 비용 뒤 플러스, 같은 수를 무작위로 막은 1,000번보다 낫고, 그 평균보다 나은 몫이 하루 묶음으로 다시 뽑아도 "
            "남음(p < 0.05). 기간 중에는 '지금까지'일 뿐입니다.",
    "parity": "실제 계좌 재현 = 실제 계좌가 들어간 진입(코인 · 방향 · 진입 분) 중 이 재계산 신호에도 있는 비율. 많이 낮으면 이 "
              "숫자를 믿지 마세요.",
}


class RegimeGateError(RuntimeError):
    """The look cannot run (pin, definitions, bars, database): exit 2."""


# ====================================================================== the pinned gate code
def gate():
    """research/regimegate/gate.py, loaded by path (the classes, the gates, the label lookup and the statistics come
    from the pinned file, never from a copy)."""
    name = "regimegate_gate"
    if name in sys.modules:
        return sys.modules[name]
    if not os.path.exists(GATE_PY):
        raise RegimeGateError("research/regimegate/gate.py is missing")
    spec = importlib.util.spec_from_file_location(name, GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def window() -> tuple[int, int]:
    """[first bar close, last bar close) of the registered forward window (gate.py FWD_FROM, FWD_LAST_DAY 00:00)."""
    GT = gate()
    return int(GT.FWD_FROM), int(GT.ms(GT.FWD_LAST_DAY))


def pin_problems() -> list[str]:
    return gate().pin_problems()


def exchange_tables(path: str = EXCHANGE_JSON, symbols=V3_SYMBOLS) -> tuple[dict, dict]:
    """({symbol: Brackets}, {symbol: {qty_step, min_notional}}) of the pinned research/fullgrid/exchange.json: the
    numbers gate.py's forward run sizes with (PREREG 5.2: no other table)."""
    from .margin import Brackets
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        by = {p["symbol"]: Brackets.from_binance(p) for p in doc["brackets"]}
        specs = {s: {"qty_step": float(doc["specs"][s]["qty_step"]),
                     "min_notional": float(doc["specs"][s]["min_notional"])} for s in symbols}
        return {s: by[s] for s in symbols}, specs
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RegimeGateError(f"exchange.json brackets: {type(exc).__name__}: {exc}"[:300]) from None


# ====================================================================== labels (regimes.coin_states on given frames)
def open_ms(df) -> np.ndarray:
    return (df["ts"].astype("int64") // 1_000_000).to_numpy(np.int64)


def coin_states_from_frames(frames: dict, tf: str) -> dict:
    """research/fullgrid/regimes.py ``coin_states`` line for line, on chart frames already built (``frames``: tf ->
    DataFrame with ts (bar open), high, low, close; it needs ``tf``, "15m" and "4h"). ``coin_states`` builds the same
    frames from the 1m archive (run.frame); tests check both give the same arrays."""
    RG = gate().RG
    Y, G = RG.Y, RG.G
    df = frames[tf]
    close = open_ms(df) + TF_MS[tf]
    code = Y.regimes(df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float),
                     Y.TF_MIN[tf])["code"]
    d15 = frames["15m"]
    ts = open_ms(d15)
    b = {"ts": ts, "h": d15["high"].to_numpy(float), "l": d15["low"].to_numpy(float), "c": d15["close"].to_numpy(float)}
    _trend, vol, _s, _a = G.coin_regime(b)
    d4 = frames["4h"]
    close4 = open_ms(d4) + TF_MS["4h"]
    c4 = d4["close"].to_numpy(float)
    day = (close4 - 1) // DAY                                    # the UTC day each 4h bar belongs to
    days, first, count = np.unique(day, return_index=True, return_counts=True)
    full = count == 6
    dclose = c4[first + count - 1][full]
    ema = G._ema(dclose, RG.EMA_DAYS)
    return {"close": close, "code": code, "ts15": ts, "vol": vol, "day": days[full],
            "above": np.where(np.isfinite(ema), dclose > ema, np.nan)}


def label_states(lib, source, symbols, tfs, start: int, end: int) -> dict:
    """{(symbol, tf): coin_states} on the live service's chart frames from the 5m bars in [start, end)."""
    out = {}
    for sym in symbols:
        cols = source.load(sym, start, end)
        if len(cols[0]) < 2:
            continue
        frames = {tf: PS.chart_frame(lib, cols, tf) for tf in sorted(set(tfs) | set(STATES_TFS))}
        if any(len(frames[t]) < 2 for t in STATES_TFS):
            continue
        for tf in tfs:
            if len(frames[tf]) >= 2:
                out[(sym, tf)] = coin_states_from_frames(frames, tf)
    return out


# ====================================================================== store
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS days (day TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY, strategy TEXT NOT NULL, tf TEXT NOT NULL, symbol TEXT NOT NULL, side INTEGER NOT NULL,
    bar_close INTEGER NOT NULL, class TEXT NOT NULL, regime INTEGER NOT NULL, vol INTEGER NOT NULL,
    status TEXT NOT NULL, entry_time INTEGER, exit_time INTEGER, exit_reason TEXT, leverage INTEGER, tier TEXT,
    pnl REAL);
CREATE INDEX IF NOT EXISTS signals_cell ON signals (strategy, tf);
"""
# status: open (submitted, not finished at the last processed day), closed (a trade), not_sized (the entry check
# refused it: no trade, PREREG 1)


def open_store(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def reset_store(conn) -> None:
    for t in ("meta", "days", "signals"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()


def signal_id(strategy: str, tf: str, symbol: str, close: int, side: int) -> str:
    return f"{strategy}@{tf}|{symbol}|{int(close)}|{int(side):+d}"


def fingerprint(settings: Settings, manifest: dict, win: tuple, brackets_doc: bytes) -> str:
    """Changes when the look would give other numbers: settings, definitions, engine and replay code, the pinned gate
    files (rules, labels, classes), the window, the bracket table, VERSION."""
    GT = gate()
    h = hashlib.sha256(f"v{VERSION}|{win[0]}|{win[1]}".encode())
    h.update(json.dumps(asdict(settings), sort_keys=True, default=str).encode())
    h.update(json.dumps(manifest, sort_keys=True).encode())
    h.update(brackets_doc)
    # this file too: a label is stored once, so a change to the label or replay code here must not mix with old rows
    own = ("paperbot/paramshadow.py", "paperbot/regimegate.py")
    files = [os.path.join(ROOT, rel) for rel in PS.ENGINE_FILES + own]
    files += [os.path.normpath(os.path.join(GT.HERE, rel)) for rel in GT.PINNED]
    for p in files:
        h.update(os.path.relpath(p, ROOT).encode() + b"\0" + (open(p, "rb").read() if os.path.exists(p) else b"-"))
    return h.hexdigest()


def utc_day(ms: int) -> str:
    return PS.utc_day(ms)


def day_start(day: str) -> int:
    return PS.day_start(day)


# ====================================================================== one night
def run(paper_db: Optional[str], out_dir: str, source, rest, brackets: dict, specs: dict, now_ms: int,
        max_days: int = MAX_DAYS, strategies: Optional[list] = None, tfs=V3_TRADE_TFS, symbols=V3_SYMBOLS,
        fetch_steps: Optional[Callable] = None, log: Callable[[str], None] = print, win: Optional[tuple] = None,
        live_root: str = LIVE_ROOT, n_flip: Optional[int] = None, brackets_doc: bytes = b"") -> dict:
    """Replay the window's days not done yet, then write the look. Returns the summary dict."""
    from . import sweepsig
    from .entry_marks import strength_module
    from .sigservice import strategy_names
    GT = gate()
    win = tuple(win or window())
    last_day = utc_day(win[1])                       # the day that only finishes the open trades (PREREG 5.2)
    settings = v3_settings()
    if settings.initial_equity != GT.R.EQUITY:
        raise RegimeGateError(f"initial equity {settings.initial_equity} != the study's {GT.R.EQUITY}")
    lib = sweepsig.lib()
    names = list(strategies or GT.R.core_names())
    if strategies is None and sorted(names) != sorted(strategy_names(lib)):
        raise RegimeGateError("param_defs and the live strategy list differ")
    manifest = PS.defs_manifest()
    cells = {}
    for n in names:
        pmod = PS.param_module(n, manifest)
        try:
            smod = strength_module(n)
        except Exception as exc:  # noqa: BLE001  PREREG 10: a refused strength definition must not size 'normal'
            raise RegimeGateError(f"strength definition of {n} refused: {exc}") from None
        cells[n] = (pmod, smod, [{"key": "base", "ov": {}}])
    klass = {n: GT.style_class("core", n) for n in names}

    store = open_store(os.path.join(out_dir, "regimegate.db"))
    fp = fingerprint(settings, manifest, win, brackets_doc)
    meta = PS._get(store, "run") or {}
    if meta.get("fingerprint") != fp or meta.get("strategies") != sorted(names) or meta.get("tfs") != list(tfs):
        if meta:
            log("settings, definitions, engine, pinned files or window changed: starting over from the window start")
        reset_store(store)
        meta = {"fingerprint": fp, "window": list(win), "strategies": sorted(names), "tfs": list(tfs),
                "last_day": None, "started_ms": now_ms}
        PS._put(store, "run", meta)
        store.commit()

    engines: dict[str, PaperEngine] = {}
    for sid, st in (PS._get(store, "engines") or {}).items():
        e = PaperEngine(settings, brackets, symbol_specs=specs, book=sid)
        restore_engine(e, st)
        engines[sid] = e
    active = set(engines)

    # a day is replayed only once the bars after its end exist (the 15m bar a midnight signal falls in, LABEL_PAD):
    # a label is stored once and never recomputed, so a run just after midnight must not take that day yet
    yesterday = utc_day(now_ms - LABEL_PAD - 5 * MIN - DAY)
    first = utc_day(win[0]) if meta.get("last_day") is None else utc_day(day_start(meta["last_day"]) + DAY)
    todo = []
    d = first
    while d <= min(yesterday, last_day) and len(todo) < max_days:
        todo.append(d)
        d = utc_day(day_start(d) + DAY)
    notes: list[str] = []
    t0 = time.time()
    states: dict = {}
    if todo:
        label_from = day_start(utc_day(win[0])) - LABEL_DAYS * DAY      # fixed: labels never depend on the night
        states = label_states(lib, source, symbols, tfs, label_from, day_start(todo[-1]) + DAY + LABEL_PAD)
        log(f"labels: {len(states)} coin x timeframe series ({time.time() - t0:.0f} s)")
    for c0 in range(0, len(todo), CHUNK_DAYS):
        chunk = todo[c0:c0 + CHUNK_DAYS]
        a, b = day_start(chunk[0]), day_start(chunk[-1]) + DAY
        raw, _counts, sig_notes = PS.chunk_signals(lib, source, cells, symbols, tfs, a, b, win[0] - 1, log=log)
        notes += sig_notes
        by_close: dict[int, list] = {}
        for close, lst in raw.items():
            if not win[0] <= close < win[1]:
                continue
            for aid, sig in lst:
                strategy, tf, _key = PS.split_account(aid)
                sid = signal_id(strategy, tf, sig.symbol, close, sig.side)
                sig.meta["account"] = sid
                by_close.setdefault(close, []).append((sid, sig))
        try:
            fetch = fetch_steps or PS.make_fetcher(rest, list(symbols), a, b)
        except Exception as exc:  # noqa: BLE001
            raise RegimeGateError(f"1m bars / funding from {chunk[0]} unavailable: {type(exc).__name__}: {exc}"[:300]) \
                from None
        for day in chunk:
            s0 = day_start(day)
            try:
                steps = fetch(rest, list(symbols), s0, s0 + DAY)
            except Exception as exc:  # noqa: BLE001
                raise RegimeGateError(f"1m bars of {day} unavailable: {type(exc).__name__}: {exc}"[:300]) from None
            cover = {sym: 0 for sym in symbols}
            for _t, bars, _f in steps:
                for sym in bars:
                    if sym in cover:
                        cover[sym] += 1
            short = {sym: n for sym, n in cover.items() if n < PS.MIN_STEPS}
            if short:
                gap = ", ".join(f"{sym.replace('USDT', '')} {n}분" for sym, n in short.items())
                if s0 > day_start(yesterday) - PS.ACCEPT_AFTER_DAYS * DAY:
                    raise RegimeGateError(f"1m bars of {day}: {gap} (< {PS.MIN_STEPS} each), tried again next night")
                notes.append(f"{day}: 1분봉이 모자란 채로 계산함 ({gap}; {PS.ACCEPT_AFTER_DAYS}일을 기다려도 그대로)")
            day_sigs = {k: v for k, v in by_close.items() if s0 < k <= s0 + DAY}
            new_rows = new_signal_rows(day_sigs, states, klass, GT)
            for _close, lst in day_sigs.items():
                for sid, _sig in lst:
                    engines[sid] = PaperEngine(settings, brackets, symbol_specs=specs, book=sid)
            PS.replay_day(engines, active, day_sigs, steps, brackets)
            closed, refused = [], []
            for sid in list(engines):
                e = engines[sid]
                for t in e.trades:
                    closed.append((t.entry_time, t.exit_time, t.exit_reason, int(t.leverage), t.tier, float(t.pnl),
                                   sid))
                traded = bool(e.trades)
                e.trades.clear()
                e.outcomes.clear()
                if e.position is None and not e.pending:
                    if not traded:
                        refused.append((sid,))
                    del engines[sid]
                    active.discard(sid)
            store.executemany("INSERT OR REPLACE INTO signals VALUES (?,?,?,?,?,?,?,?,?,'open',NULL,NULL,NULL,NULL,"
                              "NULL,NULL)", new_rows)
            store.executemany("UPDATE signals SET status = 'closed', entry_time = ?, exit_time = ?, exit_reason = ?, "
                              "leverage = ?, tier = ?, pnl = ? WHERE id = ?", closed)
            store.executemany("UPDATE signals SET status = 'not_sized' WHERE id = ?", refused)
            store.execute("INSERT OR REPLACE INTO days VALUES (?,?,?)",
                          (day, now_ms, json.dumps({"steps": len(steps), "signals": len(new_rows),
                                                    "closed": len(closed), "not_sized": len(refused),
                                                    "open": len(engines), "short": short})))
            meta["last_day"] = day
            PS._put(store, "run", meta)
            PS._put(store, "engines", {sid: engine_state(e) for sid, e in engines.items()})
            store.commit()
            log(f"{day}: {len(steps)} minutes, {len(new_rows)} signals, {len(closed)} trades closed, "
                f"{len(engines)} open ({time.time() - t0:.0f} s)")
    through = meta.get("last_day")
    nxt = utc_day(win[0]) if through is None else utc_day(day_start(through) + DAY)
    stop = min(yesterday, last_day)
    remaining = max(0, (day_start(stop) - day_start(nxt)) // DAY + 1) if nxt <= stop else 0
    notes += live_code_notes(live_root)
    conn = None
    if paper_db and os.path.exists(paper_db):
        try:
            conn = PS.connect_ro(paper_db)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
        except sqlite3.Error as exc:                 # the look does not need it: parity is left empty
            if conn is not None:
                conn.close()
            notes.append(f"paper3.db를 읽지 못함({type(exc).__name__}): 실제 계좌와의 재현 비율은 비움")
            conn = None
    try:
        summ = summarize(store, conn, names, tfs, win, through, last_day, now_ms, settings, notes, remaining, n_flip)
    finally:
        if conn is not None:
            conn.close()
    PS.write_outputs(out_dir, summ)
    store.close()
    return summ


def new_signal_rows(day_sigs: dict, states: dict, klass: dict, GT) -> list[tuple]:
    """signals rows (status 'open') of one day, with the signal bar's 장세 and 변동성 codes (gate.py's label lookup)."""
    by: dict[tuple, list] = {}
    for close, lst in day_sigs.items():
        for sid, sig in lst:
            strategy, tf = sid.split("|", 1)[0].split("@", 1)
            by.setdefault((sig.symbol, tf), []).append((sid, strategy, tf, sig.symbol, int(sig.side), int(close)))
    rows = []
    for key, items in by.items():
        closes = np.array([it[5] for it in items], np.int64)
        st = states.get(key)
        if st is None:
            reg = vol = np.zeros(len(items), np.int8)
        else:
            reg, vol = GT.label_codes(closes, st)
        for it, r, v in zip(items, reg, vol):
            rows.append((*it, klass[it[1]], int(r), int(v)))
    return rows


def live_code_notes(live_root: str) -> list[str]:
    """A note when the rule bot's own tree runs other engine or signal code than this copy replays with."""
    if not live_root or not os.path.isdir(live_root) or os.path.realpath(live_root) == os.path.realpath(ROOT):
        return []
    diff = []
    for rel in PS.ENGINE_FILES + ("research/entry_study/DEFS_BC.sha256", "third_party/sweep/PREREG.sha256"):
        a, b = os.path.join(ROOT, rel), os.path.join(live_root, rel)
        ha = hashlib.sha256(open(a, "rb").read()).hexdigest() if os.path.exists(a) else None
        hb = hashlib.sha256(open(b, "rb").read()).hexdigest() if os.path.exists(b) else None
        if ha != hb:
            diff.append(rel)
    if not diff:
        return []
    return [f"규칙봇이 지금 돌리는 코드와 다른 파일로 다시 계산함: {', '.join(diff[:6])}"
            + (f" 외 {len(diff) - 6}개" if len(diff) > 6 else "") + " (설치 명령을 다시 돌리면 맞춰짐)"]


# ====================================================================== the look
def signal_table(store, GT, initial: float) -> tuple[dict, dict]:
    """(gate.py's per-signal table T of the closed trades, counts by status). x0 = P&L / $5,000 at the live exit; the
    second read (x1) does not exist here and stays NaN."""
    cell_ix = {(n, tf): i for i, (k, n, tf) in enumerate(GT.all_cells()) if k == "core"}
    rows = store.execute("SELECT strategy, tf, symbol, side, bar_close, regime, vol, status, pnl FROM signals "
                         "ORDER BY bar_close, id").fetchall()
    counts = {"signals": len(rows), "closed": 0, "open": 0, "not_sized": 0}
    cols = {k: [] for k in GT.COLS}
    for strategy, tf, sym, side, close, reg, vol, status, pnl in rows:
        counts[status] = counts.get(status, 0) + 1
        if status != "closed" or pnl is None:
            continue
        cols["cell"].append(cell_ix[(strategy, tf)])
        cols["coin"].append(GT.R.SYMBOLS.index(sym))
        cols["side"].append(side)
        cols["close"].append(close)
        cols["x0"].append(pnl / initial)
        cols["x1"].append(np.nan)
        cols["regime"].append(reg)
        cols["vol"].append(vol)
    dtypes = {**GT.DTYPES, "regime": np.int8, "vol": np.int8}
    T = {k: np.asarray(v, dtype=dtypes[k]) for k, v in cols.items()}
    T["open_at_end"] = [counts["open"], 0]
    return T, counts


def parity(store, conn, since: int, until: int) -> dict:
    """The real accounts' entries (coin, side, entry minute) that this look also has, per cell and overall."""
    if conn is None:
        return {"share": None, "real": 0, "found": 0, "cells": {}}
    real = PS.real_trades(conn, since, until)
    mine: dict[str, set] = {}
    for strategy, tf, sym, side, et in store.execute(
            "SELECT strategy, tf, symbol, side, entry_time FROM signals WHERE entry_time IS NOT NULL"):
        mine.setdefault(f"{strategy}@{tf}", set()).add((sym, int(side), int(et) // MIN))
    n_real = n_found = 0
    cells = {}
    for aid, trades in real.items():
        have = mine.get(aid, set())
        f = sum(1 for t in trades if (t["symbol"], int(t["side"]), int(t["entry_time"]) // MIN) in have)
        cells[aid] = {"real": len(trades), "found": f}
        n_real += len(trades)
        n_found += f
    return {"share": round(n_found / n_real, 4) if n_real else None, "real": n_real, "found": n_found, "cells": cells}


def summarize(store, conn, names, tfs, win, through, last_day, now_ms, settings, notes, remaining,
              n_flip=None) -> dict:
    GT = gate()
    T, counts = signal_table(store, GT, settings.initial_equity)
    doc = GT.evaluate(T, "forward", GT.all_cells(), n_flip=GT.N_FLIP if n_flip is None else n_flip)
    look = doc["reads"][READ]
    days = store.execute("SELECT COUNT(*) FROM days").fetchone()[0]
    end = day_start(through) + DAY if through else win[0]
    run_start = PS.run_start_ts(conn) if conn is not None else None
    if conn is None:
        if not any("paper3.db" in n for n in notes):
            notes = notes + ["paper3.db 없음: 실제 계좌와의 재현 비율은 비움"]
    elif run_start is not None and abs(run_start - win[0]) >= MIN:
        notes = notes + [f"규칙봇 실행 시작({PS._md(utc_day(run_start))} {run_start % DAY // 60_000 // 60:02d}:"
                         f"{run_start % DAY // 60_000 % 60:02d} UTC)이 미리 정한 시작과 다름: 기간은 미리 정한 그대로"]
    status = "done" if through == last_day else ("filling" if remaining else "ok")
    if through is None:
        status = "waiting"
    summ = {
        "version": VERSION, "status": status, "generated_ms": now_ms, "look": True, "verdict": False,
        "window": [win[0], win[1]], "last_day": last_day, "through_day": through, "days": days,
        "days_remaining": remaining, "read": READ, "run_start_ms": run_start,
        "settings": {"version": settings.version, "initial_equity": settings.initial_equity,
                     "taker_fee": settings.taker_fee, "slippage": settings.slippage_frac,
                     "leverage_rule": settings.leverage_rule, "brackets": "research/fullgrid/exchange.json"},
        "strategies": len(names), "tfs": list(tfs), "counts": counts,
        "evaluation": {"signals": look["signals"], "unknown_state": look["unknown_state"], "used": look["used"],
                       "open_at_end": look["open_at_end"], "lines": look["lines"], "states": look["states"]},
        "parity": parity(store, conn, win[0], end),
        "notes": notes[-50:], "texts_ko": TEXTS_KO,
    }
    summ["line_ko"] = summary_line(summ)
    return summ


def _md(day: Optional[str]) -> str:
    return PS._md(day)


def _pc(v) -> str:
    return "-" if v is None else f"{v * 100:+.2f}%"


def verdict_lines(s: dict) -> list[dict]:
    GT = gate()
    return [ln for ln in (s.get("evaluation") or {}).get("lines", [])
            if ln.get("role") == "verdict" and ln.get("gate") in GT.GATES]


def summary_line(s: dict) -> str:
    if s.get("status") == "waiting":
        return "장세 문지기(참고): 아직 계산한 날이 없음 (기간 10/05 18:35 UTC ~ 10/30)"
    ev = s.get("evaluation") or {}
    lines = {(ln["gate"], ln["group"]): ln for ln in verdict_lines(s)}
    head = f"장세 문지기(참고 · 판정 아님) {_md(s.get('through_day'))}까지 {s.get('days', 0)}일"
    if s.get("days_remaining"):
        head += f"(아직 {s['days_remaining']}일 채우는 중)"
    if s.get("status") == "done":
        head += "(기간 끝, 판정은 gate.py forward)"
    parts = [f"끝난 거래 {ev.get('used', 0):,}건(안 끝남 {ev.get('open_at_end', 0):,} · 장세 모름 "
             f"{ev.get('unknown_state', 0):,})"]
    for g in ("G1", "G2"):
        ln = lines.get((g, "pooled"))
        if ln is None:
            continue
        parts.append(f"{g} 들임 {ln['n_allowed']:,}건 {_pc(ln.get('mean_allowed'))} / 막음 {ln['n_blocked']:,}건 "
                     f"{_pc(ln.get('mean_blocked'))}")
    n_pass = sum(1 for ln in lines.values() if ln.get("pass"))
    parts.append(f"지금까지 통과 {n_pass}/{len(lines)}줄")
    par = (s.get("parity") or {}).get("share")
    if par is not None:
        parts.append(f"실제 계좌 재현 {par * 100:.0f}%")
    return f"{head}: " + " · ".join(parts)


def show_text(s: dict) -> str:
    """The one line and the eight verdict lines (gate x class), for `show`."""
    GT = gate()
    out = [s.get("line_ko") or summary_line(s)]
    for ln in verdict_lines(s):
        if not ln["checks"]["trades"]:
            word = "건수 부족"
        else:
            word = "지금은 통과" if ln["pass"] else "못 넘음"
        out.append(f"  {ln['gate']} {GT.CLASS_KO[ln['group']]}: 들임 {ln['n_allowed']:,}건 {_pc(ln.get('mean_allowed'))}"
                   f" · 막음 {ln['n_blocked']:,}건 {_pc(ln.get('mean_blocked'))} · p {_p(ln.get('p'))} · 무작위 p "
                   f"{_p(ln.get('control_p'))} · 묶음 p {_p(ln.get('within_p'))} · {word}")
    return "\n".join(out)


def _p(v) -> str:
    return "-" if v is None else f"{v:.3f}"


# ====================================================================== outputs and the command
ERROR_KO = (   # (words in the English reason, what the owners read); the first that matches
    (("PREREG_REGIMEGATE",), "장세 문지기 규칙 고정 파일(PREREG_REGIMEGATE.sha256) 확인에 실패했습니다. 개발자에게 알려 주세요"),
    (("1m bars", "5m klines", "no 5m bars"), "바이낸스 가격 자료를 다 받지 못했습니다. 다음 밤에 빠진 날부터 이어서 계산합니다"),
    (("exchange.json",), "레버리지 구간 표 파일을 읽지 못했습니다. 개발자에게 알려 주세요"),
    (("sha256", "locked", "DEFS_BC", "strength definition", "param_defs", "is missing"),
     "매매법 정의 파일 확인에 실패했습니다. 개발자에게 알려 주세요"),
    (("holds the lock",), "앞선 계산이 아직 돌고 있어 이번 실행은 건너뛰었습니다"),
)


def error_ko(msg: str) -> str:
    for words, ko in ERROR_KO:
        if any(w in msg for w in words):
            return ko
    return "예상하지 못한 문제로 멈췄습니다. 개발자에게 알려 주세요"


def write_error(out_dir: str, msg: str, now_ms: int) -> None:
    os.makedirs(out_dir, exist_ok=True)
    PS._atomic(os.path.join(out_dir, "error.json"),
               json.dumps({"generated_ms": now_ms, "error": msg[:500],
                           "line_ko": f"장세 문지기: 이번 밤 계산 못 함 · {error_ko(msg)}"}, ensure_ascii=False))


def read_summary(out_dir: str = DEFAULT_OUT) -> Optional[str]:
    return PS.read_summary(out_dir)


@contextlib.contextmanager
def _lock(out_dir: str):
    import fcntl
    os.makedirs(out_dir, exist_ok=True)
    fh = open(os.path.join(out_dir, "run.lock"), "w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RegimeGateError("another regimegate run holds the lock") from None
        yield
    finally:
        fh.close()


def foreign_modules(root: Optional[str] = None, live_root: Optional[str] = None) -> list[str]:
    """Loaded modules whose file is in the rule bot's tree instead of this copy. The venv's paperbot-app.pth puts that
    tree on sys.path after this copy's PYTHONPATH, so a path the installer did not copy would load from it silently."""
    root = ROOT if root is None else root
    live_root = LIVE_ROOT if live_root is None else live_root
    if not live_root or not os.path.isdir(live_root) or os.path.realpath(live_root) == os.path.realpath(root):
        return []
    base = os.path.realpath(live_root) + os.sep
    out = []
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if isinstance(f, str) and os.path.realpath(f).startswith(base):
            out.append(name)
    return sorted(out)


def selfcheck() -> str:
    """What the installer runs as the job's user before the swap: the pin, the definitions, the strength files, the
    style map covering the 36, the bracket table, the label code, the run's own imports (all from this copy). Raises
    on a problem."""
    from . import binance, dscheck, recorder, sweepsig  # noqa: F401  binance, dscheck, recorder: run()'s late imports
    from .entry_marks import strength_module
    from .sigservice import strategy_names
    bad = pin_problems()
    if bad:
        raise RegimeGateError("; ".join(bad))
    GT = gate()
    lib = sweepsig.lib()
    names = list(GT.R.core_names())
    if sorted(names) != sorted(strategy_names(lib)):
        raise RegimeGateError("param_defs and the live strategy list differ")
    man = PS.defs_manifest()
    for n in names:
        PS.param_module(n, man)
        strength_module(n)
        GT.style_class("core", n)
    exchange_tables()
    window()
    GT.RG.Y.regimes(np.ones(3), np.ones(3), np.ones(3), 15)
    foreign = foreign_modules()
    if foreign:
        raise RegimeGateError(f"loaded from {LIVE_ROOT}, not this copy (missing from the installer's CODE_PATHS?): "
                              + ", ".join(foreign[:8]))
    return f"selfcheck ok: {len(names)} strategies, window {_md(utc_day(window()[0]))} ~ {_md(utc_day(window()[1]))}"


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "show", "selfcheck"])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--max-days", type=int, default=MAX_DAYS)
    args = ap.parse_args(argv)
    if args.cmd == "show":
        try:
            with open(os.path.join(args.out, "last.json"), encoding="utf-8") as fh:
                print(show_text(json.load(fh)))
        except (OSError, ValueError):
            print(read_summary(args.out) or "결과 없음")
        return 0
    if args.cmd == "selfcheck":
        try:
            print(selfcheck())
        except Exception as exc:  # noqa: BLE001
            print(f"regimegate selfcheck failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        return 0
    now = int(time.time() * 1000)
    try:
        with _lock(args.out):
            bad = pin_problems()
            if bad:
                raise RegimeGateError("; ".join(bad))
            brackets, specs = exchange_tables()
            with open(EXCHANGE_JSON, "rb") as fh:
                bdoc = fh.read()
            from .binance import BinanceREST
            rest = BinanceREST()                      # public klines, mark klines and funding: no key
            source = PS.RestSource(os.path.join(args.out, "bars5m.db"), rest=rest)
            summ = run(args.db, args.out, source, rest, brackets, specs, now, max_days=args.max_days,
                       brackets_doc=bdoc)
    except RegimeGateError as exc:
        write_error(args.out, str(exc), now)
        print(f"regimegate could not run: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001  anything else: the same warning, with the reason kept in error.json
        write_error(args.out, f"{type(exc).__name__}: {exc}", now)
        print(f"regimegate failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(summ["line_ko"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
