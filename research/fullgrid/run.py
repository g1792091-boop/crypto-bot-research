"""Full-grid custom-value study runner (research/fullgrid/PREREG.md, DESIGN_KO.md). Read-only research: public price
data in, files out. No exchange key, no order, no database of the bots.

    python3 research/fullgrid/run.py outcomes --data DATA --out OUT [--procs N] [--exchange FILE | --allow-example]
    python3 research/fullgrid/run.py grid     --data DATA --out OUT [--procs N] [--only core|ds] [--names A,B] [--tfs ..]
    python3 research/fullgrid/run.py select   --out OUT
    python3 research/fullgrid/run.py confirm  --data DATA --out OUT [--procs N]
    python3 research/fullgrid/run.py report   --out OUT
    python3 research/fullgrid/run.py pack     --out OUT          # OUT/results: the files to bring home
    python3 research/fullgrid/run.py all      --data DATA --out OUT [--procs N] [--exchange FILE]
    python3 research/fullgrid/run.py status   --out OUT

Stages (every stage skips work whose output file exists, so a stopped run continues where it stopped):
1. outcomes  every chart bar of every coin and timeframe as a signal, each side, alone, through kernel.py (the paper
             engine's rules on 1m bars, $5,000 wallet), once for the "best" leverage group and once for "normal":
             OUT/outcomes/<tf>_<SYMBOL>.npz. Every grid combination then only looks its trades up.
2. grid      every combination of every cell (strategy x timeframe), every coin: signals (the pinned definitions:
             research/entry_study/param_defs for the 36, ds_defs.py for DeepSeek), each signal one trade (the core
             strategies' group from their strength at the signal bar, levrule as live; DeepSeek always "normal"), and
             per period (select / test / extra) the trade count, sum, sum of squares and wins:
             OUT/cells/<kind>/<name>/<tf>/<SYMBOL>_<first>.npz.
3. select    pooled over coins; per cell the plateau score on the select period (PREREG 6.1), top 3: OUT/select.json.
4. confirm   the picks and each cell's default: per-trade results on the test and extra periods, week-block bootstrap,
             Benjamini-Hochberg over every pick, the pass rule (PREREG 6.2-6.4), and for every pick that passes, the
             real account (one position at a time over the six coins, compounding, bust): OUT/confirm.json.
5. report    OUT/RESULTS_KO.md, OUT/candidates.csv, OUT/cells.csv.
"""

from __future__ import annotations

import os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ.setdefault(_v, "1")     # one thread per worker process: the pool is the parallelism

import argparse
import functools
import hashlib
import importlib.util
import itertools
import json
import math
import sys
import time
import traceback
import warnings
from multiprocessing import Pool

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
warnings.filterwarnings("ignore")


def _load(name: str, path: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


DATA = _load("fullgrid_data", os.path.join(HERE, "data.py"))
G = _load("fullgrid_grid", os.path.join(HERE, "grid.py"))
K = _load("fullgrid_kernel", os.path.join(HERE, "kernel.py"))
M = _load("fullgrid_memo", os.path.join(HERE, "memo.py"))

TFS = ("15m", "30m", "1h", "4h")
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
SYMBOLS = DATA.SYMBOLS
PERIODS = (("select", "2021-01-01", "2024-01-01"), ("test", "2024-01-01", "2026-10-01"),
           ("extra", "2020-01-01", "2021-01-01"))
P_SELECT, P_TEST, P_EXTRA = 0, 1, 2
WARMUP_BARS = 300                # a coin's first chart bars only warm the indicators up
MIN_SELECT, MIN_TEST, MIN_EXTRA = 150, 100, 20
TOP_PER_CELL = 3
FDR_Q = 0.10
N_BOOT = 2000
EQUITY = 5000.0
WEEK_MS = 7 * 86_400_000
MONDAY0 = 4 * 86_400_000         # 1970-01-05 was a Monday
PARAM_DEFS = os.path.join(ROOT, "research", "entry_study", "param_defs")
# Combinations per task. A whole cell per coin, so a cached indicator (memo.py) serves the whole grid; split only where
# the cost is the rule's own per-bar loop, not shared indicators (the longest tasks then stay under ~1 hour on 15m).
CHUNK_OF = {"V39_ALL": 729, "V45_AMB": 729, "DOGE": 1701}
CHUNK = 10 ** 6


def _p_ms(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").value // 1_000_000)


PERIOD_MS = [(name, _p_ms(a), _p_ms(b)) for name, a, b in PERIODS]


# ------------------------------------------------------------------ strategies
@functools.lru_cache(maxsize=None)
def core_names() -> tuple:
    from paperbot import sweepsig
    sweepsig.lib()
    names = sorted(f[:-3] for f in os.listdir(PARAM_DEFS) if f.endswith(".py") and not f.startswith("_"))
    return tuple(names)


@functools.lru_cache(maxsize=None)
def core_module(name: str):
    """research/entry_study/param_defs/<name>.py, only when its bytes match DEFS_BC.sha256 (PREREG 3)."""
    from paperbot.entry_marks import locked_defs
    path = os.path.join(PARAM_DEFS, f"{name}.py")
    want = locked_defs().get(f"param_defs/{name}.py")
    if want != _sha(path):
        raise RuntimeError(f"param_defs/{name}.py does not match DEFS_BC.sha256")
    mod = _load(f"fullgrid_pd_{name}", path)
    M.install([mod])
    return mod


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


CODE_FILES = ("data.py", "grid.py", "kernel.py", "memo.py", "ds_defs.py", "run.py")


def code_stamp() -> dict:
    """The code that produced OUT: git commit and the hash of every file that decides a number."""
    import subprocess
    try:
        head = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        head = ""
    files = {f: _sha(os.path.join(HERE, f)) for f in CODE_FILES}
    files["PREREG.md"] = _sha(os.path.join(HERE, "PREREG.md"))
    return {"commit": head, "files": files}


def check_stamp(out: str) -> None:
    """Refuse to continue an OUT made by other code (old and new results must never mix)."""
    path = os.path.join(out, "code_stamp.json")
    now = code_stamp()
    if os.path.exists(path):
        old = json.load(open(path))
        if old["files"] != now["files"]:
            raise SystemExit(f"코드가 바뀌었습니다({old.get('commit', '')[:10]} -> {now['commit'][:10]}). 예전 결과와 섞이지 않게 "
                             f"멈춥니다: rm -rf {out} 후 다시 실행하세요.")
        return
    os.makedirs(out, exist_ok=True)
    _write_json(path, now)


def preflight() -> list[str]:
    """Every definition loads from its pinned bytes; every core strength definition loads (a refused one would
    silently size every signal 'normal'). Returns problems."""
    from paperbot.entry_marks import strength_module
    bad = []
    for n in core_names():
        try:
            core_module(n)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"param_defs {n}: {exc}")
        try:
            strength_module(n)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"strength_defs {n}: {exc}")
    try:
        ds_module()
    except Exception as exc:  # noqa: BLE001
        bad.append(f"ds_defs: {exc}")
    try:
        import numba  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        bad.append(f"numba: {exc}")
    return bad


@functools.lru_cache(maxsize=None)
def ds_module():
    return _load("fullgrid_ds_defs", os.path.join(HERE, "ds_defs.py"))


def cells(only: str = "") -> list[tuple[str, str, str]]:
    """(kind, name, tf) of every cell."""
    out = []
    if only in ("", "core"):
        out += [("core", n, tf) for n in core_names() for tf in TFS]
    if only in ("", "ds"):
        D = ds_module()
        out += [("ds", n, tf) for n in D.DEFS for tf in TFS if tf in D.TFS_OF[n]]
    return out


def params_of(kind: str, name: str) -> list:
    return core_module(name).PARAMS if kind == "core" else ds_module().DEFS[name]


@functools.lru_cache(maxsize=None)
def cell_grid(kind: str, name: str) -> tuple:
    """(params, value lists, combos as dicts) in G.grid order (the last parameter changes fastest)."""
    ps = params_of(kind, name)
    if not ps:
        return (), (), ({},)
    vals = tuple(tuple(map(_hashable, G.values(name, p))) for p in ps)
    combos = tuple(G.grid(name, ps))
    return tuple(ps), vals, combos


def _hashable(v):
    return tuple(v) if isinstance(v, list) else v


def default_combo(kind: str, name: str) -> dict:
    return {p["name"]: p["default"] for p in params_of(kind, name)}


# ------------------------------------------------------------------ data
@functools.lru_cache(maxsize=1)
def minute_data(data_dir: str, sym: str) -> dict:
    return DATA.load(data_dir, sym)


FRAME_DIR = [None]               # OUT/frames once a stage has started: workers read chart bars from there


@functools.lru_cache(maxsize=8)
def frame(data_dir: str, sym: str, tf: str) -> tuple:
    """(chart bars, close ms), built once from the 1m bars and kept in OUT/frames."""
    path = os.path.join(FRAME_DIR[0], f"{tf}_{sym}.pkl") if FRAME_DIR[0] else None
    if path and os.path.exists(path):
        df = pd.read_pickle(path)
        df.attrs["tf"] = tf
        return df, (df["ts"].astype("int64").to_numpy() // 1_000_000) + TF_MS[tf]
    df, close = build_frame(data_dir, sym, tf)
    if path:
        os.makedirs(FRAME_DIR[0], exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"             # two workers may build the same frame at once
        df.to_pickle(tmp)
        os.replace(tmp, path)
    return df, close


def build_frame(data_dir: str, sym: str, tf: str) -> tuple:
    """UTC-aligned bins of the 1m bars; the first bin dropped when the coin's data starts after its open, the last
    when the data ends before its close; a bin with missing minutes is kept (as research/binance_data/build.py keeps
    bins partial from data gaps)."""
    d = minute_data(data_dir, sym)
    ts = d["ts"]
    step = TF_MS[tf]
    b = ts // step
    cut = np.flatnonzero(np.diff(b)) + 1
    st = np.r_[0, cut]
    en = np.r_[cut, len(ts)]
    o = d["o"][st]
    h = np.maximum.reduceat(d["h"], st)
    lo = np.minimum.reduceat(d["l"], st)
    c = d["c"][en - 1]
    v = np.add.reduceat(d["v"], st)
    open_ms = b[st] * step
    keep = np.ones(len(st), bool)
    if len(st) and ts[0] > open_ms[0]:
        keep[0] = False
    if len(st) and ts[-1] < open_ms[-1] + step - 60_000:
        keep[-1] = False
    df = pd.DataFrame({"ts": pd.to_datetime(open_ms[keep], unit="ms", utc=True), "open": o[keep], "high": h[keep],
                       "low": lo[keep], "close": c[keep], "volume": v[keep]})
    df.attrs["tf"] = tf
    return df, open_ms[keep] + step


def period_ids(close_ms: np.ndarray) -> np.ndarray:
    pid = np.full(len(close_ms), -1, np.int8)
    for k, (_n, a, b) in enumerate(PERIOD_MS):
        pid[(close_ms >= a) & (close_ms < b)] = k
    pid[:WARMUP_BARS] = -1
    return pid


def _vendor_fg():
    from paperbot import sweepsig
    sweepsig.lib()
    import fg_indicators
    return fg_indicators


# ------------------------------------------------------------------ exchange numbers
def exchange(path: str | None, allow_example: bool) -> dict:
    """{symbol: (bracket rows, qty_step, min_notional)} from research/fullgrid/exchange.json (made on the paper bot
    server by dump_exchange.py: Binance leverageBracket + exchangeInfo), or the example table when allowed."""
    from paperbot.margin import Brackets
    if path:
        with open(path) as fh:
            doc = json.load(fh)
        by = {p["symbol"]: Brackets.from_binance(p) for p in doc["brackets"]}
        return {s: (K.bracket_arrays(by[s]), float(doc["specs"][s]["qty_step"]), float(doc["specs"][s]["min_notional"]))
                for s in SYMBOLS}
    if not allow_example:
        raise SystemExit("leverage brackets: pass --exchange research/fullgrid/exchange.json (or --allow-example for a "
                         "timing run only)")
    return {s: (K.bracket_arrays(Brackets.example()), 0.001, 5.0) for s in SYMBOLS}


# ------------------------------------------------------------------ worker pool
def run_pool(fn, items: list, procs: int, label: str, done=lambda it: False, max_restarts: int = 5):
    """Map ``fn`` over ``items`` in ``procs`` processes, yielding results as they finish. A worker that dies (out of
    memory, killed) breaks the pool: it is rebuilt and the unfinished items are sent again (``done`` tells which
    finished: their output files exist), at most ``max_restarts`` times."""
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from concurrent.futures.process import BrokenProcessPool
    todo = [it for it in items if not done(it)]
    ctx = mp.get_context("fork")                    # workers inherit the loaded modules (and a test's patches)
    for attempt in range(max_restarts + 1):
        try:
            with ProcessPoolExecutor(procs, mp_context=ctx) as ex:
                futs = [ex.submit(fn, it) for it in todo]
                for f in as_completed(futs):
                    yield f.result()
            return
        except BrokenProcessPool:
            todo = [it for it in todo if not done(it)]
            procs = max(1, procs * 3 // 4)              # fewer workers: less memory at once
            print(f"[{label}] a worker died; {len(todo)} left, restarting with {procs} workers "
                  f"({attempt + 1}/{max_restarts})", flush=True)
    raise SystemExit(f"[{label}] workers keep dying (memory?): stopped")


# ------------------------------------------------------------------ stage 1: outcomes
def outcome_path(out: str, sym: str, tf: str) -> str:
    return os.path.join(out, "outcomes", f"{tf}_{sym}.npz")


EXIT_CHUNK = 6


def outcome_part(out: str, sym: str, tf: str, e0: int) -> str:
    return os.path.join(out, "outcomes", "parts", f"{tf}_{sym}_{e0:02d}.npz")


def outcomes_job(args) -> str:
    """Exit variants e0 .. e0+EXIT_CHUNK of one coin and timeframe, both leverage groups."""
    data_dir, out, sym, tf, ex, e0 = args
    path = outcome_part(out, sym, tf, e0)
    if os.path.exists(path) or os.path.exists(outcome_path(out, sym, tf)):
        return ""
    t0 = time.time()
    from paperbot.config import V3_STOP_ATR
    d = minute_data(data_dir, sym)
    df, close = frame(data_dir, sym, tf)
    atr = _vendor_fg().atr(df, 14).to_numpy(float)
    br, step, mn = ex[sym]
    S = K.settings_vector()
    assert K.EXITS[0][1] == V3_STOP_ATR and K.EXITS[0][3] and not K.EXITS[0][2]     # index 0 = the live rule
    exits = K.EXITS[e0:e0 + EXIT_CHUNK]
    n = len(close)
    res = {}
    for g, flag in (("best", True), ("normal", False)):
        f = np.full(n, flag)
        pnl = np.full((len(exits), n, 2), np.nan, np.float32)
        rs = np.zeros((len(exits), n, 2), np.int8)
        for k, (_name, k_stop, tp_mult, ladder) in enumerate(exits):
            p, _exi, r, _lv = K.outcomes(S, br, d["ts"], d["o"], d["h"], d["l"], d["mo"], d["mh"], d["ml"], d["fund"],
                                         close.astype(np.int64), atr, f, f, EQUITY, step, mn, k_stop, tp_mult, ladder)
            pnl[k], rs[k] = p, r
        res.update({f"pnl_{g}": pnl, f"reason_{g}": rs})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez(path + ".tmp.npz", close=close, atr=atr, **res)
    os.replace(path + ".tmp.npz", path)
    return f"{tf} {sym} exits {e0}-{e0 + len(exits) - 1}: {n:,} bars in {time.time() - t0:.0f}s"


def merge_outcomes(out: str, sym: str, tf: str) -> None:
    final = outcome_path(out, sym, tf)
    if os.path.exists(final):
        return
    parts = [np.load(outcome_part(out, sym, tf, e0)) for e0 in range(0, len(K.EXITS), EXIT_CHUNK)]
    res = {k: np.concatenate([z[k] for z in parts]) for k in ("pnl_best", "pnl_normal", "reason_best", "reason_normal")}
    np.savez(final + ".tmp.npz", close=parts[0]["close"], atr=parts[0]["atr"],
             exits=np.array([e[0] for e in K.EXITS]), **res)
    os.replace(final + ".tmp.npz", final)
    for e0 in range(0, len(K.EXITS), EXIT_CHUNK):
        os.remove(outcome_part(out, sym, tf, e0))


def stage_outcomes(data_dir: str, out: str, procs: int, ex: dict) -> None:
    for tf in TFS:                                  # chart frames first, once (workers then only read them)
        for sym in SYMBOLS:
            frame(data_dir, sym, tf)
    jobs = [(data_dir, out, s, tf, ex, e0) for tf in TFS for s in SYMBOLS for e0 in range(0, len(K.EXITS), EXIT_CHUNK)]
    jobs.sort(key=lambda j: {"15m": 0, "30m": 1, "1h": 2, "4h": 3}[j[3]])
    for msg in run_pool(outcomes_job, jobs, procs, "outcomes",
                        done=lambda j: os.path.exists(outcome_part(out, j[2], j[3], j[5]))
                        or os.path.exists(outcome_path(out, j[2], j[3]))):
        if msg:
            print("[outcomes]", msg, flush=True)
    for tf in TFS:
        for sym in SYMBOLS:
            merge_outcomes(out, sym, tf)


@functools.lru_cache(maxsize=2)
def outcome_table(out: str, sym: str, tf: str) -> dict:
    with np.load(outcome_path(out, sym, tf)) as z:                 # the exit reasons stay on disk
        return {k: z[k] for k in ("close", "atr", "pnl_best", "pnl_normal")}


# ------------------------------------------------------------------ leverage group (levrule.quality_group, vectorised)
@functools.lru_cache(maxsize=8)
def best_flags(data_dir: str, name: str, sym: str, tf: str) -> tuple:
    """(best_long, best_short): the bar's entry-quality tier is 'best' (mean quintile of the strategy's strength
    features against paperbot/quality_edges.json >= 4), as levrule.quality_group on the live strength record."""
    from paperbot import levrule
    from paperbot.entry_marks import strength_module
    df, _c = frame(data_dir, sym, tf)
    n = len(df)
    no = (np.zeros(n, bool), np.zeros(n, bool))
    try:
        smod = strength_module(name)
    except Exception:  # noqa: BLE001  live: a refused definition sizes 'normal'
        return no
    cell = levrule.edges().get(f"{name}|{tf}")
    if smod is None or not cell:
        return no
    try:
        arrays = smod.strength(df.copy(), tf)
    except Exception:  # noqa: BLE001  live: a failed strength sizes 'normal'
        return no
    out = []
    for k in (0, 1):
        tot, cnt = np.zeros(n), np.zeros(n)
        for f in smod.FEATURES:
            e = cell.get(f["name"])
            if e is None:
                continue
            v = np.asarray(arrays[f["name"]][k], float)
            ok = np.isfinite(v)
            sv = np.where(ok, v if e["higher_is_stronger"] else -v, 0.0)
            q = 1 + np.searchsorted(np.asarray(e["edges"], float), sv, side="right")
            tot += np.where(ok, q, 0)
            cnt += ok
        with np.errstate(invalid="ignore", divide="ignore"):
            out.append((cnt > 0) & (tot / np.maximum(cnt, 1) >= 4))
    return tuple(out)


def trade_table(data_dir: str, out: str, kind: str, name: str, sym: str, tf: str) -> np.ndarray:
    """(exit variants, n bars, 2 sides) P&L / equity of a signal on that bar (NaN: not sized, still open at the data
    end, no ATR), with this strategy's leverage group per bar and side."""
    O = outcome_table(out, sym, tf)
    if kind == "ds":
        return O["pnl_normal"]
    bl, bs = best_flags(data_dir, name, sym, tf)
    P = O["pnl_normal"].copy()
    P[:, bl, 0] = O["pnl_best"][:, bl, 0]
    P[:, bs, 1] = O["pnl_best"][:, bs, 1]
    return P


# ------------------------------------------------------------------ signals
_DS_CACHE: dict = {}
_LAST_SERIES: list = [None]


def signals(data_dir: str, kind: str, name: str, sym: str, tf: str, combo: dict) -> tuple:
    key = (kind, name, sym, tf)
    if _LAST_SERIES[0] != key:
        M.clear()
        _DS_CACHE.clear()
        _LAST_SERIES[0] = key
    df, _c = frame(data_dir, sym, tf)
    if kind == "core":
        lo, sh = core_module(name).signals(df, tf, **combo)
    else:
        coin = sym[:-1]
        ctx = None if sym == "BTCUSDT" else {"BTCUSD": frame(data_dir, "BTCUSDT", tf)[0]}
        lo, sh = ds_module().signals(df, tf, name, ctx=ctx, coin=coin, cache=_DS_CACHE, **combo)
    return np.asarray(lo, bool), np.asarray(sh, bool)


def exit_stats(P: np.ndarray, pid: np.ndarray, lo: np.ndarray, sh: np.ndarray) -> np.ndarray:
    """(exit variants, 3 periods, [n, sum, sumsq, wins]) of one combination's signals, every exit variant at once."""
    il, is_ = np.flatnonzero(lo), np.flatnonzero(sh)
    X = np.concatenate([P[:, il, 0], P[:, is_, 1]], axis=1).astype(np.float64)
    pt = np.r_[pid[il], pid[is_]]
    ok = np.isfinite(X)
    Xz = np.where(ok, X, 0.0)
    out = np.zeros((P.shape[0], 3, 4))
    for k in range(3):
        m = ok & (pt == k)[None, :]
        xk = np.where(m, Xz, 0.0)
        out[:, k, 0] = m.sum(1)
        out[:, k, 1] = xk.sum(1)
        out[:, k, 2] = (xk * xk).sum(1)
        out[:, k, 3] = (m & (Xz > 0)).sum(1)
    return out


def per_trade(P: np.ndarray, lo: np.ndarray, sh: np.ndarray) -> tuple:
    """(bar index, side +1/-1, P&L) of the sized and closed trades of one exit variant (P: n bars x 2), by bar."""
    il, is_ = np.flatnonzero(lo), np.flatnonzero(sh)
    idx = np.r_[il, is_]
    side = np.r_[np.ones(len(il), np.int8), -np.ones(len(is_), np.int8)]
    x = np.r_[P[il, 0], P[is_, 1]]
    ok = np.isfinite(x)
    o = np.argsort(idx[ok], kind="stable")
    return idx[ok][o], side[ok][o], x[ok][o]


# ------------------------------------------------------------------ stage 2: grid
def cell_dir(out: str, kind: str, name: str, tf: str) -> str:
    return os.path.join(out, "cells", kind, name, tf)


def plan(only: str = "", names=None, tfs=TFS) -> list[tuple]:
    tasks = []
    for kind, name, tf in cells(only):
        if (names and name not in names) or tf not in tfs:
            continue
        n = len(cell_grid(kind, name)[2])
        ch = CHUNK_OF.get(name, CHUNK)
        for sym in SYMBOLS:
            for c0 in range(0, n, ch):
                tasks.append((kind, name, tf, sym, c0, min(n, c0 + ch)))
    weight = {"15m": 16, "30m": 8, "1h": 4, "4h": 1}
    return sorted(tasks, key=lambda t: -(t[5] - t[4]) * weight[t[2]] * COST.get(t[1], 1.0))


# relative cost per combination (scheduling order only: longest first), from the 2026-10-10 timing runs
COST = {"V39_ALL": 15.0, "V45_AMB": 12.0, "DOGE": 5.0, "N05_PSAR_POC": 2.0, "N01_ST_EMA": 2.0, "N25_DST_CCI": 2.0}


def task_path(out: str, t: tuple) -> str:
    kind, name, tf, sym, c0, _c1 = t
    return os.path.join(cell_dir(out, kind, name, tf), f"{sym}_{c0:05d}.npz")


def grid_job(args) -> str:
    data_dir, out, t = args
    path = task_path(out, t)
    if os.path.exists(path):
        return ""
    kind, name, tf, sym, c0, c1 = t
    t0 = time.time()
    try:
        df, close = frame(data_dir, sym, tf)
        pid = period_ids(close)
        P = trade_table(data_dir, out, kind, name, sym, tf)
        combos = cell_grid(kind, name)[2][c0:c1]
        stats = np.zeros((len(combos), P.shape[0], 3, 4), np.float32)
        fails = []
        for k, combo in enumerate(combos):
            try:
                lo, sh = signals(data_dir, kind, name, sym, tf, combo)
            except Exception as exc:  # noqa: BLE001  a combination the rule cannot compute: recorded, no trades
                fails.append([c0 + k, f"{type(exc).__name__}: {exc}"[:200]])
                stats[k] = np.nan
                continue
            stats[k] = exit_stats(P, pid, lo, sh)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez(path + ".tmp.npz", stats=stats, c0=c0, c1=c1, fails=json.dumps(fails), seconds=time.time() - t0)
        os.replace(path + ".tmp.npz", path)
        return f"{kind} {name} {tf} {sym} {c0}-{c1}: {time.time() - t0:.0f}s" + (f", {len(fails)} failed" if fails else "")
    except Exception:  # noqa: BLE001  one broken task must not stop the night: logged, rerun picks it up
        return f"ERROR {kind} {name} {tf} {sym} {c0}: " + traceback.format_exc()[-1500:]


def stage_grid(data_dir: str, out: str, procs: int, only: str = "", names=None, tfs=TFS) -> int:
    """Returns the number of tasks still missing afterwards (errors are logged and retried by the next call)."""
    allt = plan(only, names, tfs)
    tasks = [t for t in allt if not os.path.exists(task_path(out, t))]
    print(f"[grid] {len(tasks)} of {len(allt)} tasks to do", flush=True)
    t0 = time.time()
    k = 0
    for msg in run_pool(grid_job, [(data_dir, out, t) for t in tasks], procs, "grid",
                        done=lambda a: os.path.exists(task_path(out, a[2]))):
        k += 1
        if msg:
            el = time.time() - t0
            print(f"[grid {k}/{len(tasks)} {el / 3600:.2f}h, ~{el / k * (len(tasks) - k) / 3600:.1f}h left] {msg}",
                  flush=True)
    missing = [t for t in allt if not os.path.exists(task_path(out, t))]
    if missing:
        print(f"[grid] {len(missing)} tasks still missing, e.g. {missing[:3]}", flush=True)
    return len(missing)


def cell_fails(out: str, kind: str, name: str, tf: str) -> int:
    """Combinations whose signals raised (on any coin)."""
    n = len(cell_grid(kind, name)[2])
    ch = CHUNK_OF.get(name, CHUNK)
    bad = set()
    for sym in SYMBOLS:
        for c0 in range(0, n, ch):
            p = task_path(out, (kind, name, tf, sym, c0, min(n, c0 + ch)))
            if os.path.exists(p):
                with np.load(p) as z:
                    bad |= {int(r) for r, _m in json.loads(str(z["fails"]))}
    return len(bad)


def cell_stats(out: str, kind: str, name: str, tf: str) -> np.ndarray | None:
    """Pooled over coins: (combinations, exit variants, 3 periods, [n, sum, sumsq, wins]); None when a task is
    missing."""
    n = len(cell_grid(kind, name)[2])
    ch = CHUNK_OF.get(name, CHUNK)
    tot = np.zeros((n, len(K.EXITS), 3, 4))
    for sym in SYMBOLS:
        for c0 in range(0, n, ch):
            p = task_path(out, (kind, name, tf, sym, c0, min(n, c0 + ch)))
            if not os.path.exists(p):
                return None
            with np.load(p) as z:
                tot[c0:c0 + z["stats"].shape[0]] += z["stats"]
    return tot


# ------------------------------------------------------------------ stage 3: select
def exit_neighbours() -> list[list[int]]:
    """For each exit variant, the variants with the same take-profit rule and the next narrower / wider stop."""
    out = []
    for name, k, m, lk in K.EXITS:
        same = sorted((kk, j) for j, (_n, kk, mm, ll) in enumerate(K.EXITS) if mm == m and ll == lk)
        ks = [kk for kk, _j in same]
        i = ks.index(k)
        out.append([same[i + d][1] for d in (-1, 1) if 0 <= i + d < len(same)])
    return out


def combo_neighbours(kind: str, name: str) -> list[np.ndarray]:
    """Per parameter and direction, each combination's grid neighbour row (-1 where none: an edge or a combination
    grid.valid removed)."""
    ps, vals, combos = cell_grid(kind, name)
    if not ps:
        return []
    names = [p["name"] for p in ps]
    keys = [tuple(vals[j].index(_hashable(c[nm])) for j, nm in enumerate(names)) for c in combos]
    pos = {key: r for r, key in enumerate(keys)}
    out = []
    for j in range(len(names)):
        for dlt in (-1, 1):
            out.append(np.array([pos.get(key[:j] + (key[j] + dlt,) + key[j + 1:], -1) for key in keys], np.int64))
    return out


def plateau_scores(kind: str, name: str, st: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(mean per trade on the select period, plateau score), each (combinations, exit variants). Plateau = median over
    the pair and its neighbours (one number one step up or down, same exit; or the next narrower / wider stop, same
    take-profit rule and numbers) of the select mean, a neighbour with fewer than MIN_SELECT trades counting as 0; NaN
    where the pair itself has fewer than MIN_SELECT trades."""
    n_sel, s_sel = st[:, :, P_SELECT, 0], st[:, :, P_SELECT, 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n_sel > 0, s_sel / n_sel, np.nan)
    ok = n_sel >= MIN_SELECT
    val = np.where(ok, mean, 0.0)                      # a neighbour's contribution
    cols = [mean]
    for q in combo_neighbours(kind, name):
        cols.append(np.where((q >= 0)[:, None], val[np.maximum(q, 0)], np.nan))
    stack = np.stack(cols, axis=-1)                    # (combos, exits, 1 + combo neighbours)
    ex_nb = exit_neighbours()
    width = max(len(v) for v in ex_nb)
    ex_cols = np.full(mean.shape + (width,), np.nan)
    for e, nb in enumerate(ex_nb):
        for i, f in enumerate(nb):
            ex_cols[:, e, i] = val[:, f]
    allv = np.concatenate([stack, ex_cols], axis=-1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plat = np.nanmedian(allv, axis=-1)
    plat[~ok] = np.nan
    return mean, plat


def default_row(kind: str, name: str) -> int:
    d = {k: _hashable(v) for k, v in default_combo(kind, name).items()}
    for r, c in enumerate(cell_grid(kind, name)[2]):
        if {k: _hashable(v) for k, v in c.items()} == d:
            return r
    raise RuntimeError(f"{name}: default not in the grid")


def stage_select(out: str, only: str = "") -> dict:
    picks, cells_out, missing = [], [], []
    for kind, name, tf in cells(only):
        st = cell_stats(out, kind, name, tf)
        if st is None:
            missing.append(f"{kind}/{name}/{tf}")
            continue
        mean, plat = plateau_scores(kind, name, st)
        r0 = default_row(kind, name)
        d_plat = float(plat[r0, 0]) if np.isfinite(plat[r0, 0]) else 0.0      # live numbers, live exit
        good = np.argwhere(np.isfinite(plat) & (plat > 0) & (plat > d_plat))
        order = sorted(map(tuple, good), key=lambda re: (-plat[re], -mean[re], re[0], re[1]))[:TOP_PER_CELL]
        combos = cell_grid(kind, name)[2]
        n_sel = st[:, :, P_SELECT, 0]
        cells_out.append({"kind": kind, "name": name, "tf": tf, "combos": len(combos), "exits": len(K.EXITS),
                          "with_min_trades": int(np.nansum(n_sel >= MIN_SELECT)),
                          "plateau_positive": int((np.isfinite(plat) & (plat > 0)).sum()),
                          "default": {"row": r0, "n": int(np.nan_to_num(n_sel[r0, 0])), "mean": _f(mean[r0, 0]),
                                      "plateau": d_plat},
                          "failed_combos": cell_fails(out, kind, name, tf),
                          "default_numbers_best_exit": _best_exit(mean[r0], plat[r0]),
                          "best_plateau": _f(np.nanmax(plat)) if np.isfinite(plat).any() else None,
                          "picks": [[int(r), int(e)] for r, e in order]})
        for rank, (r, e) in enumerate(order, 1):
            picks.append({"kind": kind, "name": name, "tf": tf, "row": int(r), "exit_index": int(e),
                          "exit": K.EXITS[e][0], "rank": rank, "combo": _jsonable(combos[r]),
                          "select_n": int(np.nan_to_num(n_sel[r, e])), "select_mean": _f(mean[r, e]),
                          "plateau": _f(plat[r, e]),
                          "default_select_mean": _f(mean[r0, 0]), "default_plateau": d_plat})
    doc = {"picks": picks, "cells": cells_out, "missing": missing, "exits": [e[0] for e in K.EXITS],
           "code": code_stamp(), "rule": {
        "min_select": MIN_SELECT, "top_per_cell": TOP_PER_CELL,
        "plateau": "median of self and +-1-step neighbours (numbers, stop width)"}}
    _write_json(os.path.join(out, "select.json"), doc)
    print(f"[select] {len(picks)} picks from {len(cells_out)} cells ({len(missing)} cells missing)", flush=True)
    return doc


def _best_exit(mean_row: np.ndarray, plat_row: np.ndarray) -> dict | None:
    """With the live numbers, the exit variant with the highest plateau (for the report; not a pass rule)."""
    if not np.isfinite(plat_row).any():
        return None
    e = int(np.nanargmax(plat_row))
    return {"exit": K.EXITS[e][0], "plateau": _f(plat_row[e]), "mean": _f(mean_row[e])}


def _f(x):
    return None if x is None or not np.isfinite(x) else float(x)


def _jsonable(c: dict) -> dict:
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in c.items()}


def _write_json(path: str, doc) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    os.replace(path + ".tmp", path)


# ------------------------------------------------------------------ stage 4: confirm
def boot_mean_p(week: np.ndarray, x: np.ndarray, n_boot: int, seed: int) -> float | None:
    """One-sided p that the mean per trade is <= 0 (paperbot/agents/newlab.py boot_mean_p): whole weeks resampled."""
    x = np.asarray(x, float)
    if not len(x):
        return None
    weeks, inv = np.unique(np.asarray(week), return_inverse=True)
    W = len(weeks)
    s, c = np.bincount(inv, x, W), np.bincount(inv, None, W)
    rng = np.random.default_rng(seed)
    bad, done = 0, 0
    while done < n_boot:
        m = min(10_000, n_boot - done)
        pick = rng.integers(0, W, size=(m, W))
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = s[pick].sum(1) / c[pick].sum(1)
        bad += int((~(mean > 0)).sum())
        done += m
    return (1 + bad) / (n_boot + 1)


def bh(pvals: list, q: float = FDR_Q) -> list[bool]:
    """Benjamini-Hochberg step-up (research/levstop/levstop.py bh)."""
    ix = [i for i, p in enumerate(pvals) if p is not None]
    m = len(ix)
    out = [False] * len(pvals)
    order = sorted(ix, key=lambda i: pvals[i])
    k = 0
    for r, i in enumerate(order, 1):
        if pvals[i] <= q * r / m:
            k = r
    for i in order[:k]:
        out[i] = True
    return out


def _seed(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


TRADE_KEYS = ("close", "coin", "side", "x", "pid", "best", "atr")


def cell_trades(data_dir: str, out: str, kind: str, name: str, tf: str, specs: list) -> list[dict]:
    """For each (combination, exit variant) of one cell, all coins: per trade the signal close (ms), coin index,
    side, P&L / equity, period, leverage-group flag, ATR. Coins outermost, so a coin's indicator memo serves every
    combination."""
    rows = [{k: [] for k in TRADE_KEYS} for _ in specs]
    for ci, sym in enumerate(SYMBOLS):
        df, close = frame(data_dir, sym, tf)
        P_all = trade_table(data_dir, out, kind, name, sym, tf)
        pid_all = period_ids(close)
        atr = outcome_table(out, sym, tf)["atr"]
        bl, bs = best_flags(data_dir, name, sym, tf) if kind == "core" else (None, None)
        for i, (combo, e) in enumerate(specs):
            lo, sh = signals(data_dir, kind, name, sym, tf, combo)
            idx, side, x = per_trade(P_all[e], lo, sh)
            best = np.where(side > 0, bl[idx], bs[idx]) if kind == "core" else np.zeros(len(idx), bool)
            for k, v in (("close", close[idx]), ("coin", np.full(len(idx), ci)), ("side", side), ("x", x),
                         ("pid", pid_all[idx]), ("best", best), ("atr", atr[idx])):
                rows[i][k].append(v)
    return [{k: np.concatenate(v) for k, v in r.items()} for r in rows]


def combo_trades(data_dir: str, out: str, kind: str, name: str, tf: str, combo: dict, e: int = 0) -> dict:
    """``cell_trades`` for one combination and exit variant."""
    return cell_trades(data_dir, out, kind, name, tf, [(combo, e)])[0]


def _combo(p: dict) -> dict:
    return {k: (tuple(v) if isinstance(v, list) else v) for k, v in p["combo"].items()}


def period_summary(T: dict, k: int, tag: str) -> dict:
    m = T["pid"] == k
    x = T["x"][m]
    week = (T["close"][m] - MONDAY0) // WEEK_MS
    return {"n": int(len(x)), "mean": _f(x.mean()) if len(x) else None, "win": _f((x > 0).mean()) if len(x) else None,
            "sum": _f(x.sum()), "p": boot_mean_p(week, x, N_BOOT, _seed(tag, k)) if len(x) else None}


def account_run(data_dir: str, T: dict, ex: dict, lo_ms: int, hi_ms: int, e: int = 0) -> dict:
    """The real account over [lo_ms, hi_ms) with exit variant ``e``: $5,000, one position at a time over the six
    coins, compounding, bust."""
    _n, k_stop, tp_mult, ladder = K.EXITS[e]
    sel = (T["close"] >= lo_ms) & (T["close"] < hi_ms)
    cat, starts, ends = all_minutes(data_dir)
    em = []
    for q in np.flatnonzero(sel):
        c = T["coin"][q]
        tsc = cat["ts"][starts[c]:ends[c]]
        j0 = np.searchsorted(tsc, T["close"][q] - 60_000)
        em.append(int(tsc[j0 + 1]) if j0 + 1 < len(tsc) else 2 ** 62)
    qs = np.flatnonzero(sel)
    order = np.lexsort((T["coin"][qs], np.asarray(em, np.int64))) if len(qs) else np.zeros(0, int)
    qs = qs[order]
    st, pnl, ext, rs, lv, wallet = K.account(
        K.settings_vector(), np.stack([ex[s][0] for s in SYMBOLS]) if _same_shape(ex) else _pad(ex), cat["ts"],
        cat["o"], cat["h"], cat["l"], cat["mo"], cat["mh"], cat["ml"], cat["fund"], np.array(starts, np.int64),
        np.array(ends, np.int64), T["coin"][qs].astype(np.int64), T["close"][qs].astype(np.int64),
        T["side"][qs].astype(np.int64), T["atr"][qs], T["best"][qs], np.array([ex[s][1] for s in SYMBOLS]),
        np.array([ex[s][2] for s in SYMBOLS]), k_stop, tp_mult, ladder)
    done = (st == 1) & (rs != K.R_OPEN)
    eq = EQUITY + np.cumsum(pnl[done])
    peak = np.maximum.accumulate(np.r_[EQUITY, eq])
    dd = float(np.max(1 - np.r_[EQUITY, eq] / peak)) if len(eq) else 0.0
    return {"trades": int(done.sum()), "final": float(wallet), "max_dd_at_closes": dd,
            "bust": bool(wallet < 10.0), "skipped": int((st == 0).sum()), "liquidations": int((rs[done] == K.R_LIQ).sum())}


@functools.lru_cache(maxsize=1)
def all_minutes(data_dir: str) -> tuple:
    """The six coins' 1m arrays concatenated (kernel.account's layout) and each coin's [start, end)."""
    cat = {k: [] for k in ("ts", "o", "h", "l", "mo", "mh", "ml", "fund")}
    starts, ends, pos = [], [], 0
    for sym in SYMBOLS:
        d = DATA.load(data_dir, sym)
        for k in cat:
            cat[k].append(d[k])
        starts.append(pos)
        pos += len(d["ts"])
        ends.append(pos)
    return {k: np.concatenate(v) for k, v in cat.items()}, starts, ends


def _same_shape(ex: dict) -> bool:
    return len({ex[s][0].shape for s in SYMBOLS}) == 1


def _pad(ex: dict) -> np.ndarray:
    """Bracket tables of different lengths padded with their last row (never reached: its cap is the largest)."""
    m = max(ex[s][0].shape[0] for s in SYMBOLS)
    return np.stack([np.vstack([ex[s][0]] + [ex[s][0][-1:]] * (m - ex[s][0].shape[0])) for s in SYMBOLS])


def confirm_cell_job(args) -> tuple:
    """The test and extra periods of one cell's picks and of its default (live numbers, live exit)."""
    data_dir, out, key, picks = args
    kind, name, tf = key
    specs = [(default_combo(kind, name), 0)] + [(_combo(p), p["exit_index"]) for p in picks]
    Ts = cell_trades(data_dir, out, kind, name, tf, specs)
    tag0 = f"{key}|default"
    dflt = {"test": period_summary(Ts[0], P_TEST, tag0), "extra": period_summary(Ts[0], P_EXTRA, tag0)}
    rows = []
    for p, T in zip(picks, Ts[1:]):
        tag = f"{key}|{p['row']}|{p['exit_index']}"
        rows.append({**p, "test": period_summary(T, P_TEST, tag), "extra": period_summary(T, P_EXTRA, tag),
                     "default_test": dflt["test"], "default_extra": dflt["extra"]})
    return key, rows


def account_job(args) -> tuple:
    """The real accounts of one candidate and its cell's default, 2021-01 .. 2026-09 and the test period alone."""
    data_dir, out, ex, r = args
    kind, name, tf = r["kind"], r["name"], r["tf"]
    T0, T = cell_trades(data_dir, out, kind, name, tf, [(default_combo(kind, name), 0), (_combo(r), r["exit_index"])])
    span, test = (PERIOD_MS[P_SELECT][1], PERIOD_MS[P_TEST][2]), (PERIOD_MS[P_TEST][1], PERIOD_MS[P_TEST][2])
    e = r["exit_index"]
    return (kind, name, tf, r["row"], e), {
        "pick": account_run(data_dir, T, ex, *span, e=e), "default": account_run(data_dir, T0, ex, *span),
        "pick_test": account_run(data_dir, T, ex, *test, e=e), "default_test": account_run(data_dir, T0, ex, *test)}


def stage_confirm(data_dir: str, out: str, ex: dict, procs: int = 1) -> dict:
    sel = json.load(open(os.path.join(out, "select.json")))
    by_cell: dict = {}
    for p in sel["picks"]:
        by_cell.setdefault((p["kind"], p["name"], p["tf"]), []).append(p)
    jobs = [(data_dir, out, key, ps) for key, ps in by_cell.items()]
    got = {}
    for key, rows in run_pool(confirm_cell_job, jobs, procs, "confirm"):
        got[key] = rows
        print(f"[confirm] {key[0]} {key[1]} {key[2]}: " + ", ".join(f"#{r['rank']} test n={r['test']['n']}" for r in rows),
              flush=True)
    rows = [r for key in by_cell for r in got[key]]          # select.json order: reproducible
    # every pick is in the family; one with too few test trades counts with p = 1 (it cannot pass)
    sig = bh([r["test"]["p"] if r["test"]["n"] >= MIN_TEST and r["test"]["p"] is not None else 1.0 for r in rows])
    for r, s in zip(rows, sig):
        t, e, dt_ = r["test"], r["extra"], r["default_test"]
        checks = {"test_trades": t["n"] >= MIN_TEST, "test_positive": (t["mean"] or 0) > 0,
                  "test_beats_default": (t["mean"] or 0) > (dt_["mean"] if dt_["mean"] is not None else -math.inf),
                  "test_fdr": bool(s), "extra_trades": e["n"] >= MIN_EXTRA, "extra_positive": (e["mean"] or 0) > 0}
        r["checks"] = checks
        r["pass"] = all(checks.values())
    passing = [r for r in rows if r["pass"]]
    if passing:
        acc = {}
        # each account worker holds the six coins' minutes (~2 GB): fewer workers here
        for key, res in run_pool(account_job, [(data_dir, out, ex, r) for r in passing], max(1, min(procs, 8)),
                                 "accounts"):
            acc[key] = res
        for r in passing:
            r["account"] = acc[(r["kind"], r["name"], r["tf"], r["row"], r["exit_index"])]
    doc = {"rows": rows, "passed": len(passing), "family": len(rows), "fdr_q": FDR_Q, "code": code_stamp()}
    _write_json(os.path.join(out, "confirm.json"), doc)
    print(f"[confirm] {doc['passed']} of {doc['family']} picks pass", flush=True)
    return doc


# ------------------------------------------------------------------ status
def stage_status(out: str, only: str = "") -> None:
    tasks = plan(only)
    done = [t for t in tasks if os.path.exists(task_path(out, t))]
    secs = []
    for t in done[-400:]:
        try:
            with np.load(task_path(out, t)) as z:
                secs.append(float(z["seconds"]))
        except Exception:  # noqa: BLE001
            pass
    print(f"grid tasks done {len(done)} / {len(tasks)}")
    oc = sum(os.path.exists(outcome_path(out, s, tf)) for s in SYMBOLS for tf in TFS)
    print(f"outcome tables {oc} / {len(SYMBOLS) * len(TFS)}")
    for f in ("select.json", "confirm.json", "RESULTS_KO.md"):
        print(f"{f}: {'yes' if os.path.exists(os.path.join(out, f)) else 'not yet'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=("outcomes", "grid", "select", "confirm", "report", "pack", "all", "status"))
    ap.add_argument("--data")
    ap.add_argument("--out", required=True)
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--exchange")
    ap.add_argument("--allow-example", action="store_true")
    ap.add_argument("--only", default="", choices=("", "core", "ds"))
    ap.add_argument("--names", default="")
    ap.add_argument("--tfs", default=",".join(TFS))
    a = ap.parse_args(argv)
    names = set(a.names.split(",")) if a.names else None
    tfs = tuple(a.tfs.split(","))
    FRAME_DIR[0] = os.path.join(a.out, "frames")
    if a.stage == "status":
        stage_status(a.out, a.only)
        return 0
    if a.stage in ("outcomes", "grid", "select", "confirm", "all"):
        check_stamp(a.out)
    if a.stage in ("outcomes", "all"):
        bad = preflight()
        if bad:
            print("[preflight] " + "; ".join(bad), flush=True)
            return 2
        stage_outcomes(a.data, a.out, a.procs, exchange(a.exchange, a.allow_example))
    if a.stage in ("grid", "all"):
        if stage_grid(a.data, a.out, a.procs, a.only, names, tfs):
            return 3
    if a.stage in ("select", "all"):
        stage_select(a.out, a.only)
    if a.stage in ("confirm", "all"):
        stage_confirm(a.data, a.out, exchange(a.exchange, a.allow_example), a.procs)
    sys.modules.setdefault("fullgrid_run", sys.modules[__name__])
    rep = _load("fullgrid_report", os.path.join(HERE, "report.py"))
    if a.stage in ("report", "all"):
        rep.write(a.out)
    if a.stage in ("pack", "all"):
        print("[pack]", rep.pack(a.out, sys.modules[__name__]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
