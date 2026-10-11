"""New-information batch runner (research/newinfo/PREREG_NEWINFO.md). Read-only research: public data in, files out.
No exchange key, no order, no database of the bots; the rule bot's trading path is not imported for anything but the
kernel's settings vector (research/fullgrid/kernel.py ``settings_vector``, read-only).

    python3 research/newinfo/run.py check   --data FG1M --work FGWORK --results PACK --ni NI_DATA --out OUT
    python3 research/newinfo/run.py grid    --data FG1M --work FGWORK --ni NI_DATA --out OUT [--procs 2]
    python3 research/newinfo/run.py select  --out OUT
    python3 research/newinfo/run.py confirm --data FG1M --work FGWORK --ni NI_DATA --out OUT
    python3 research/newinfo/run.py report  --out OUT
    python3 research/newinfo/run.py all     --data FG1M --work FGWORK --results PACK --ni NI_DATA --out OUT
    python3 research/newinfo/run.py smoke   --data FG1M --out SCRATCH     # 2020-01-01 .. 2020-01-03 only (PREREG 10)
    python3 research/newinfo/run.py status  --out OUT

FG1M: the full grid's 1m archive (1m/<SYMBOL>.npz, raw/ fundingRate zips). FGWORK: the full grid's work folder with
outcomes/<tf>_<SYMBOL>.npz (run.py stage 1). PACK: the full grid's results pack (data_build.json). NI_DATA: data.py's
folder (the two daily metrics files per coin and manifest.json). Every stage except ``smoke`` and ``status`` refuses
to run until PREREG_NEWINFO.sha256 pins the pre-registration and this folder's code (PREREG 10).

Stages (each skips work whose output exists; OUT/code_stamp.json stops a mix of code versions):
1. check    PREREG 2.1 and 2.5: the 1m archive against the pack's data_build.json, the full grid's kernel.py and
            run.py against PREREG.sha256, exchange.json, paperbot/config.py unchanged since f1e824f, the metrics files
            (data.py manifest), every outcome table's close times and 300 seeded entries recomputed: OUT/checks.json.
2. grid     every combination of every cell, all coins: signals (defs.py), each signal one trade read from the outcome
            table (``pnl_normal``, the six exits of PREREG 4), per period [n, sum, sum of squares, wins]:
            OUT/cells/<rule>_<tf>.npz.
3. select   plateau with section 4's neighbours, top 3 per cell (PREREG 6.1): OUT/select.json.
4. confirm  per pick: select / test / extra at normal and quarter size, coin-flip and same-side controls, week-block
            bootstrap, Benjamini-Hochberg over every pick, cost x2 and x3, the pass rule (6.2-6.4) and the reported
            figures of section 7 (accounts, market states, coins, sides, years): OUT/confirm.json.
5. report   OUT/RESULTS_KO.md (Korean; every pick, nothing hidden).
"""

from __future__ import annotations

import os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ.setdefault(_v, "1")     # one thread per process: the study uses at most 2 cores (PREREG 10)

import argparse  # noqa: E402
import functools  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
warnings.filterwarnings("ignore")
FG = os.path.join(ROOT, "research", "fullgrid")


def _load(name: str, path: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load("fullgrid_run", os.path.join(FG, "run.py"))          # the full grid's public functions, read-only
K = R.K
D = _load("newinfo_defs", os.path.join(HERE, "defs.py"))
NI = _load("newinfo_data", os.path.join(HERE, "data.py"))

SYMBOLS = D.SYMBOLS
assert tuple(SYMBOLS) == tuple(R.SYMBOLS)
TFS = ("30m", "1h", "4h")
SEC4 = ("ladder|2", "tp2R|2", "tp3R|1.5", "tp3R|2", "tp3R|3", "tp3R|4")    # PREREG 4, in this order
SEC4_NB = ((), (), (3,), (2, 4), (3, 5), (4,))                            # tp3R|1.5 - 2 - 3 - 4
EXIT_GLOBAL = tuple([e[0] for e in K.EXITS].index(n) for n in SEC4)       # their index in kernel.EXITS
PERIODS = {"price": (("select", "2021-01-01", "2024-01-01"), ("test", "2024-01-01", "2026-10-01"),
                     ("extra", "2020-01-01", "2021-01-01")),
           "metrics": (("select", "2021-12-01", "2024-01-01"), ("test", "2024-01-01", "2026-10-01"),
                       ("extra", "2020-09-01", "2021-12-01"))}
EXTRA_COINS = {"price": SYMBOLS, "metrics": ("BTCUSDT",)}                   # H3A and D06: BTC alone (PREREG 6)
P_SELECT, P_TEST, P_EXTRA = 0, 1, 2
PNAMES = ("select", "test", "extra")
WARMUP_BARS = D.WARMUP_BARS
MIN_SELECT, MIN_TEST, MIN_EXTRA = 150, 100, 20
TOP_PER_CELL = 3
FDR_Q = 0.10
N_BOOT = 2000
FLIP_SEEDS = 10
COST_IDX = (0, 1, 5, 19)          # taker fee, slippage, ladder round-trip cost, maker fee (PHASE2_PREREG 1)
QUARTER_IDX = (11, 13, 15, 17)    # every margin fraction (WATCH_PREREG 1 ``quarter``)
VERIFY_N = 300
EXCHANGE_SHA = "176e234b3f84a96eecd2a0ea4e6b3e1ffbb3a40bf7fa77dbd994e33144413ffa"
FG_COMMIT = "f1e824f"
MAX_PROCS = 2
CODE_FILES = ("data.py", "defs.py", "run.py")
PINS = os.path.join(HERE, "PREREG_NEWINFO.sha256")
SMOKE = ("2020-01-01", "2020-01-04")          # 2020-01-01 .. 2020-01-03 inclusive


def _ms(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").value // 1_000_000)


def group(rule: str) -> str:
    return "metrics" if D.RULES[rule]["info"] == "metrics" else "price"


def period_ms(rule: str) -> list:
    return [(n, _ms(a), _ms(b)) for n, a, b in PERIODS[group(rule)]]


def period_ids(rule: str, sym: str, close_ms: np.ndarray) -> np.ndarray:
    """0 select, 1 test, 2 extra (a metrics rule's extra period: BTC alone), -1 elsewhere and on warm-up bars."""
    close_ms = np.asarray(close_ms, np.int64)
    pid = np.full(len(close_ms), -1, np.int8)
    for k, (_n, a, b) in enumerate(period_ms(rule)):
        if k == P_EXTRA and sym not in EXTRA_COINS[group(rule)]:
            continue
        pid[(close_ms >= a) & (close_ms < b)] = k
    pid[:WARMUP_BARS] = -1
    return pid


def cells() -> list[tuple[str, str]]:
    return [(r, tf) for r in D.ORDER for tf in D.RULES[r]["tfs"]]


def pick_id(rule: str, tf: str, row: int, e: int) -> str:
    return f"{rule}|{tf}|{row}|{SEC4[e]}"


# ------------------------------------------------------------------ code pins and stamp
def _sha(path: str) -> str:
    return NI.sha256(path)


def pin_problems() -> list[str]:
    """PREREG 10: the pre-registration and the code files must be pinned (and match) before a real run."""
    if not os.path.exists(PINS):
        return ["PREREG_NEWINFO.sha256 does not exist yet: pin the reviewed files first"]
    pinned = {}
    for line in open(PINS):
        if line.strip():
            h, f = line.split(None, 1)
            pinned[f.strip()] = h
    bad = [f"{f} is not pinned" for f in ("PREREG_NEWINFO.md",) + CODE_FILES if f not in pinned]
    for f, h in pinned.items():
        p = os.path.join(HERE, f)
        if not os.path.exists(p) or _sha(p) != h:
            bad.append(f"{f} does not match PREREG_NEWINFO.sha256")
    return bad


def code_stamp() -> dict:
    try:
        head = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        head = ""
    files = {f: _sha(os.path.join(HERE, f)) for f in CODE_FILES + ("PREREG_NEWINFO.md",)}
    files.update({f"fullgrid/{f}": _sha(os.path.join(FG, f)) for f in ("kernel.py", "run.py")})
    return {"commit": head, "files": files}


def check_stamp(out: str) -> None:
    """Refuse to continue an OUT made by other code (old and new results must never mix)."""
    path = os.path.join(out, "code_stamp.json")
    now = code_stamp()
    if os.path.exists(path):
        with open(path) as fh:
            old = json.load(fh)
        if old["files"] != now["files"]:
            raise SystemExit(f"코드가 바뀌었습니다({old.get('commit', '')[:10]} -> {now['commit'][:10]}). 예전 결과와 "
                             f"섞이지 않게 멈춥니다: rm -rf {out} 후 다시 실행하세요.")
        return
    os.makedirs(out, exist_ok=True)
    _write_json(path, now)


def _write_json(path: str, doc) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False, default=_jdefault)
    os.replace(path + ".tmp", path)


def _jdefault(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def _f(x):
    return None if x is None or not np.isfinite(x) else float(x)


# ------------------------------------------------------------------ inputs
class Ctx:
    """Where everything is. ``ex``: {symbol: (bracket rows, qty_step, min_notional)} (research/fullgrid/exchange.json)."""

    def __init__(self, data: str, work: str, ni: str, out: str, exchange: str | None = None, ex: dict | None = None):
        self.data, self.work, self.ni, self.out = data, work, ni, out
        self.exchange = exchange or os.path.join(FG, "exchange.json")
        self._ex = ex

    @property
    def ex(self) -> dict:
        if self._ex is None:
            self._ex = R.exchange(self.exchange, False)
        return self._ex


_COIN: dict = {}
_FUND: dict = {}
_METR: dict = {}


def coin_inputs(ctx: Ctx, sym: str) -> dict:
    """One coin's chart bars on 30m / 1h / 4h (research/fullgrid run.frame), its UTC days (D05's 4h cell) and its
    daily VWAP on D10's timeframes. Small arrays, kept for the whole run (the 1m bars are read once)."""
    key = (ctx.data, sym)
    if key in _COIN:
        return _COIN[key]
    frames = {}
    for tf in TFS:
        df, close = R.frame(ctx.data, sym, tf)
        open_ms = df["ts"].astype("int64").to_numpy() // 1_000_000
        if not np.array_equal(open_ms + D.TF_MS[tf], close):
            raise SystemExit(f"{sym} {tf}: frame close times are not open + bar length")
        frames[tf] = {"open_ms": open_ms, **{k: df[c].to_numpy(float) for k, c in
                                             (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"),
                                              ("v", "volume"))}}
    d = R.minute_data(ctx.data, sym)
    day = D.bars(d["ts"], d["o"], d["h"], d["l"], d["c"], d["v"], D.DAY)
    vwap = {tf: D.daily_vwap(d["ts"], d["h"], d["l"], d["c"], d["v"], frames[tf]["open_ms"],
                             frames[tf]["open_ms"] + D.TF_MS[tf]) for tf in D.RULES["D10_VWAP_REVERT"]["tfs"]}
    _COIN[key] = {"frames": frames, "day": day, "vwap": vwap}
    return _COIN[key]


def funding(ctx: Ctx, sym: str) -> dict:
    if (ctx.data, sym) not in _FUND:
        _FUND[(ctx.data, sym)] = NI.funding(ctx.data, sym)
    return _FUND[(ctx.data, sym)]


def metrics(ctx: Ctx, sym: str) -> dict:
    if (ctx.ni, sym) not in _METR:
        _METR[(ctx.ni, sym)] = NI.metrics(ctx.ni, sym)
    return _METR[(ctx.ni, sym)]


def htf_of(ci: dict, tf: str) -> dict:
    h = D.HTF_OF[tf]
    f = ci["day"] if h == "1d" else ci["frames"][h]
    return {"close_ms": np.asarray(f["open_ms"], np.int64) + D.TF_MS[h], "c": f["c"]}


def market(ctx: Ctx, rule: str, tf: str, syms=SYMBOLS) -> "D.Market":
    """The coins of one cell with exactly the inputs the rule reads."""
    coins = []
    for sym in syms:
        ci = coin_inputs(ctx, sym)
        f = ci["frames"][tf]
        kw = {}
        if rule in ("H3A_CROWD_FADE", "D06_OI_DIVERGENCE"):
            kw["metrics"] = metrics(ctx, sym)
        if rule in ("D04_FUNDING_FADE", "D05_FUNDING_TREND"):
            kw["funding"] = funding(ctx, sym)
        if rule == "D05_FUNDING_TREND":
            kw["htf"] = htf_of(ci, tf)
        c = D.Coin(sym, tf, f["open_ms"], f["o"], f["h"], f["l"], f["c"], f["v"], **kw)
        if rule == "D10_VWAP_REVERT":
            c.memo[("vwap",)] = ci["vwap"][tf]
        coins.append(c)
    return D.Market(tf, coins)


# ------------------------------------------------------------------ outcome tables
_TABLE: dict = {}


def table(work: str, sym: str, tf: str) -> dict:
    """The six exits of PREREG 4 from OUT/outcomes/<tf>_<SYMBOL>.npz: close, atr, P (6, bars, 2) float32 P&L / $5,000
    at normal size (NaN: not a trade), and the file's sha256."""
    key = (work, sym, tf)
    if key not in _TABLE:
        path = R.outcome_path(work, sym, tf)
        with np.load(path) as z:
            names = [str(x) for x in z["exits"]]
            if names != [e[0] for e in K.EXITS]:
                raise SystemExit(f"{path}: exit list differs from kernel.EXITS")
            P = z["pnl_normal"][list(EXIT_GLOBAL)]
            _TABLE[key] = {"close": z["close"].astype(np.int64), "atr": z["atr"].astype(float), "P": P,
                           "sha256": _sha(path), "file": os.path.basename(path)}
    return _TABLE[key]


def table_hashes(work: str) -> dict:
    return {v["file"]: v["sha256"] for (w, _s, _t), v in sorted(_TABLE.items()) if w == work}


def settings(kind: str = "normal", cost: float = 1.0) -> np.ndarray:
    """kernel.settings_vector(): x ``cost`` on the cost entries; 'quarter' = every margin fraction x 1/4."""
    S = K.settings_vector().copy()
    for i in COST_IDX:
        S[i] *= cost
    if kind == "quarter":
        for i in QUARTER_IDX:
            S[i] *= 0.25
    return S


def recompute(ctx: Ctx, sym: str, tf: str, idx: np.ndarray, side: np.ndarray, e: int, S: np.ndarray) -> np.ndarray:
    """P&L / $5,000 of the given (bar, side) signals of one coin with exit e (of SEC4) and settings S, through
    kernel.outcomes (NaN: not a trade)."""
    if not len(idx):
        return np.zeros(0)
    T = table(ctx.work, sym, tf)
    d = R.minute_data(ctx.data, sym)
    br, step, mn = ctx.ex[sym]
    m = len(idx)
    f = np.zeros(m, bool)
    nan = np.full(m, np.nan)
    p, _x, _r, _l = K.outcomes(S, br, d["ts"], d["o"], d["h"], d["l"], d["mo"], d["mh"], d["ml"], d["fund"],
                               T["close"][idx].astype(np.int64), T["atr"][idx], f, f, R.EQUITY, step, mn,
                               *K.exit_args(EXIT_GLOBAL[e]), nan, nan)
    return np.where(np.asarray(side) > 0, p[:, 0], p[:, 1])


# ------------------------------------------------------------------ stage 1: check
def stage_check(ctx: Ctx, results: str, tables: bool = True) -> dict:
    """PREREG 2.1 and 2.5. Stops (SystemExit 2) on a file problem, (SystemExit 3) when a table fails only the
    recomputation (rebuild it with research/fullgrid/run.py outcomes first)."""
    files, rec = [], []
    with open(os.path.join(results, "data_build.json")) as fh:
        want = {s["symbol"]: s.get("sha256") for s in json.load(fh)["symbols"]}
    npz = {}
    for s in SYMBOLS:
        h = _sha(os.path.join(ctx.data, "1m", f"{s}.npz"))
        npz[s] = h
        if h != want.get(s):
            files.append(f"1m/{s}.npz sha256 differs from data_build.json")
    pins = {}
    for line in open(os.path.join(FG, "PREREG.sha256")):
        if line.strip():
            h, f = line.split(None, 1)
            pins[f.strip()] = h
    for f in ("kernel.py", "run.py"):
        if _sha(os.path.join(FG, f)) != pins.get(f):
            files.append(f"research/fullgrid/{f} does not match PREREG.sha256")
    if _sha(ctx.exchange) != EXCHANGE_SHA:
        files.append("exchange.json is not the file of commit f1e824f")
    diff = subprocess.run(["git", "-C", ROOT, "diff", FG_COMMIT, "--", "paperbot/config.py"], capture_output=True,
                          text=True, timeout=30)
    if diff.returncode != 0 or diff.stdout.strip():
        files.append("paperbot/config.py differs from commit f1e824f")
    man = NI.manifest(ctx.ni, ctx.data)
    files += man["problems"]
    for kind in ("orderflow", "daily"):
        for f, v in sorted(man[kind].items()):
            print(f"[check] metrics {f} sha256 {v['sha256']}", flush=True)
    tab = {}
    if tables:
        S = K.settings_vector()
        for sym in SYMBOLS:                      # coin outermost: its 1m bars are read once
            for tf in TFS:
                name = f"{tf}_{sym}"
                path = R.outcome_path(ctx.work, sym, tf)
                if not os.path.exists(path):
                    files.append(f"outcomes/{name}.npz missing")
                    continue
                T = table(ctx.work, sym, tf)
                f = coin_inputs(ctx, sym)["frames"][tf]
                tab[name] = {"sha256": T["sha256"]}
                print(f"[check] outcomes/{name}.npz sha256 {T['sha256']}", flush=True)
                if not np.array_equal(T["close"], f["open_ms"] + D.TF_MS[tf]):
                    files.append(f"outcomes/{name}.npz close times differ from the frame")
                    continue
                if not np.array_equal(T["atr"], D.atr14(f["h"], f["l"], f["c"]), equal_nan=True):
                    files.append(f"outcomes/{name}.npz ATR differs from the frame's ATR14")
                    continue
                ok = verify_table(ctx, sym, tf, S)
                tab[name]["recomputed_equal"] = ok
                if not ok:
                    rec.append(name)
    doc = {"npz": npz, "tables": tab, "metrics": man, "file_problems": files, "recompute_failed": rec,
           "code": code_stamp()}
    _write_json(os.path.join(ctx.out, "checks.json"), doc)
    if files:
        raise SystemExit(2)
    if rec:
        print(f"[check] tables failing the recomputation: {rec}; rebuild them with research/fullgrid/run.py outcomes",
              flush=True)
        raise SystemExit(3)
    print("[check] all inputs match", flush=True)
    return doc


def require_checks(out: str) -> dict:
    """PREREG 2.5: nothing runs before ``check`` passed on this OUT."""
    path = os.path.join(out, "checks.json")
    if not os.path.exists(path):
        raise SystemExit(f"{path} missing: run the check stage first")
    with open(path) as fh:
        doc = json.load(fh)
    if doc["file_problems"] or doc["recompute_failed"]:
        raise SystemExit("checks.json has problems: " + "; ".join(doc["file_problems"] + doc["recompute_failed"]))
    return doc


def tables_unchanged(ctx: Ctx, doc: dict) -> None:
    """Every outcome table read since must be the file ``check`` verified."""
    want = {f"{k}.npz": v["sha256"] for k, v in doc["tables"].items()}
    now = {os.path.basename(R.outcome_path(ctx.work, s, tf)): _sha(R.outcome_path(ctx.work, s, tf))
           for s in SYMBOLS for tf in TFS}             # the files themselves (grid workers keep their own cache)
    bad = [f for f, h in now.items() if want.get(f) != h]
    if bad:
        raise SystemExit(f"outcome tables changed since the check: {bad}")


def verify_table(ctx: Ctx, sym: str, tf: str, S: np.ndarray, n: int = VERIFY_N) -> bool:
    """PREREG 2.5: n seeded (bar, side, exit) entries among section 4's exits recomputed with kernel.outcomes equal
    the stored float32 values (NaN where NaN)."""
    T = table(ctx.work, sym, tf)
    rng = np.random.default_rng(R._seed("newinfo", "verify", f"{tf}_{sym}"))
    bars = rng.integers(0, len(T["close"]), n)
    sides = rng.integers(0, 2, n)
    exits = rng.integers(0, len(SEC4), n)
    for e in range(len(SEC4)):
        m = exits == e
        if not m.any():
            continue
        got = recompute(ctx, sym, tf, bars[m], np.where(sides[m] == 0, 1, -1), e, S).astype(np.float32)
        want = T["P"][e, bars[m], sides[m]]
        if not np.array_equal(got, want, equal_nan=True):
            return False
    return True


# ------------------------------------------------------------------ stage 2: grid
def cell_path(out: str, rule: str, tf: str) -> str:
    return os.path.join(out, "cells", f"{rule}_{tf}.npz")


def cell_job(args) -> str:
    ctx, rule, tf = args
    path = cell_path(ctx.out, rule, tf)
    if os.path.exists(path):
        return ""
    t0 = time.time()
    m = market(ctx, rule, tf)
    combos = D.grid(rule)
    stats = np.zeros((len(combos), len(SEC4), 3, 4))
    nsig = np.zeros((len(combos), 3), np.int64)
    for r, combo in enumerate(combos):
        sig = D.signals(rule, m, combo)
        for sym, (lo, sh) in sig.items():
            T = table(ctx.work, sym, tf)
            if len(T["close"]) != len(lo) or not np.array_equal(T["close"], m.coins[sym].close_ms):
                raise SystemExit(f"{rule} {tf} {sym}: outcome table and frame differ")
            pid = period_ids(rule, sym, T["close"])
            stats[r] += R.exit_stats(T["P"], pid, lo, sh)
            for k in range(3):
                nsig[r, k] += int((lo & (pid == k)).sum() + (sh & (pid == k)).sum())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez(path + ".tmp.npz", stats=stats, signals=nsig, seconds=time.time() - t0)
    os.replace(path + ".tmp.npz", path)
    return f"{rule} {tf}: {len(combos)} combinations in {time.time() - t0:.0f}s"


def stage_grid(ctx: Ctx, procs: int = 1) -> None:
    for sym in SYMBOLS:                     # inputs once, before the workers fork (they inherit them)
        coin_inputs(ctx, sym)
    jobs = [(ctx, r, tf) for r, tf in cells() if not os.path.exists(cell_path(ctx.out, r, tf))]
    procs = max(1, min(MAX_PROCS, procs))
    print(f"[grid] {len(jobs)} of {len(cells())} cells to do", flush=True)
    if procs == 1:
        for j in jobs:
            msg = cell_job(j)
            if msg:
                print(f"[grid] {msg}", flush=True)
        return
    for msg in R.run_pool(cell_job, jobs, procs, "grid", done=lambda j: os.path.exists(cell_path(ctx.out, j[1], j[2]))):
        if msg:
            print(f"[grid] {msg}", flush=True)


# ------------------------------------------------------------------ stage 3: select
def plateau(rule: str, st: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(select n, select mean, plateau), each (combinations, 6 exits). Plateau = median of the pair's select mean and
    its neighbours' (one number one step, same exit; the next narrower / wider stop of the same take-profit rule among
    section 4's exits, same numbers); a neighbour with < MIN_SELECT trades counts 0; NaN when the pair has fewer."""
    n, s = st[:, :, P_SELECT, 0], st[:, :, P_SELECT, 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n > 0, s / np.where(n > 0, n, 1), np.nan)
    ok = n >= MIN_SELECT
    val = np.where(ok, mean, 0.0)
    nb = D.neighbours(rule)
    plat = np.full(mean.shape, np.nan)
    for r in range(mean.shape[0]):
        for e in range(mean.shape[1]):
            if not ok[r, e]:
                continue
            xs = [mean[r, e]] + [val[q, e] for q in nb[r]] + [val[r, f] for f in SEC4_NB[e]]
            plat[r, e] = float(np.median(xs))
    return n, mean, plat


def choose(n: np.ndarray, mean: np.ndarray, plat: np.ndarray) -> list[tuple[int, int]]:
    """Top TOP_PER_CELL (row, exit) by plateau among plateau > 0; ties: higher select mean, grid order, exit order."""
    good = [(r, e) for r in range(plat.shape[0]) for e in range(plat.shape[1])
            if np.isfinite(plat[r, e]) and plat[r, e] > 0]
    return sorted(good, key=lambda re: (-plat[re], -mean[re], re[0], re[1]))[:TOP_PER_CELL]


def stage_select(out: str) -> dict:
    picks, cells_out, missing = [], [], []
    for rule, tf in cells():
        p = cell_path(out, rule, tf)
        if not os.path.exists(p):
            missing.append(f"{rule}/{tf}")
            continue
        with np.load(p) as z:
            st, nsig = z["stats"], z["signals"]
        n, mean, plat = plateau(rule, st)
        order = choose(n, mean, plat)
        combos = D.grid(rule)
        cells_out.append({"rule": rule, "tf": tf, "combos": len(combos), "exits": len(SEC4),
                          "with_min_trades": int((n >= MIN_SELECT).sum()),
                          "plateau_positive": int((np.isfinite(plat) & (plat > 0)).sum()),
                          "best_plateau": _f(np.nanmax(plat)) if np.isfinite(plat).any() else None,
                          "select_signals": [int(x) for x in nsig[:, P_SELECT]],
                          "picks": [[int(r), int(e)] for r, e in order]})
        for rank, (r, e) in enumerate(order, 1):
            picks.append({"id": pick_id(rule, tf, r, e), "rule": rule, "tf": tf, "row": int(r), "exit": SEC4[e],
                          "exit_index": int(e), "rank": rank, "combo": combos[r], "select_n": int(n[r, e]),
                          "select_mean": _f(mean[r, e]), "plateau": _f(plat[r, e])})
    doc = {"picks": picks, "cells": cells_out, "missing": missing, "exits": list(SEC4), "code": code_stamp(),
           "rule": {"min_select": MIN_SELECT, "top_per_cell": TOP_PER_CELL,
                    "plateau": "median of self and +-1-step neighbours (numbers; section 4's stop chain)"}}
    _write_json(os.path.join(out, "select.json"), doc)
    print(f"[select] {len(picks)} picks from {len(cells_out)} cells ({len(missing)} cells missing)", flush=True)
    return doc


# ------------------------------------------------------------------ stage 4: confirm
SIG_KEYS = ("coin", "idx", "side", "close", "pid", "x")


def pick_signals(ctx: Ctx, rule: str, tf: str, combo: dict, e: int, m=None) -> dict:
    """Every signal of the pick outside warm-up and outside the periods (pid >= 0), all coins, sorted by close then
    coin: coin index, bar index, side +1 / -1, close (ms), period, P&L at normal size (NaN: not a trade)."""
    m = m or market(ctx, rule, tf)
    sig = D.signals(rule, m, combo)
    rows = {k: [] for k in SIG_KEYS}
    for ci, sym in enumerate(SYMBOLS):
        if sym not in sig:
            continue
        lo, sh = sig[sym]
        T = table(ctx.work, sym, tf)
        pid = period_ids(rule, sym, T["close"])
        il, is_ = np.flatnonzero(lo & (pid >= 0)), np.flatnonzero(sh & (pid >= 0))
        idx = np.r_[il, is_]
        side = np.r_[np.ones(len(il), np.int8), -np.ones(len(is_), np.int8)]
        x = np.r_[T["P"][e, il, 0], T["P"][e, is_, 1]].astype(float)
        for k, v in (("coin", np.full(len(idx), ci)), ("idx", idx), ("side", side), ("close", T["close"][idx]),
                     ("pid", pid[idx]), ("x", x)):
            rows[k].append(v)
    out = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in rows.items()}
    o = np.lexsort((out["coin"], out["close"])) if len(out["close"]) else np.zeros(0, int)
    out = {k: v[o] for k, v in out.items()}
    for k in ("coin", "idx", "close"):
        out[k] = out[k].astype(np.int64)
    out["side"] = out["side"].astype(np.int8)
    out["pid"] = out["pid"].astype(np.int8)
    return out


def summary(x: np.ndarray) -> dict:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return {"n": int(len(x)), "mean": _f(x.mean()) if len(x) else None,
            "win": _f((x > 0).mean()) if len(x) else None, "sum": float(x.sum())}


def week_of(close_ms: np.ndarray) -> np.ndarray:
    return (np.asarray(close_ms, np.int64) - R.MONDAY0) // R.WEEK_MS


def flip_side(seed: int, pid_: str, sym: str, close_ms: int) -> int:
    """PREREG 6.2c: long when the first 8 hex digits of sha256("newinfo-flip|<seed>|<pick id>|<coin>|<close ms>")
    are even."""
    h = hashlib.sha256(f"newinfo-flip|{seed}|{pid_}|{sym}|{int(close_ms)}".encode()).hexdigest()
    return 1 if int(h[:8], 16) % 2 == 0 else -1


def flip_means(ctx: Ctx, p: dict, sig: dict) -> list:
    """Each seed's mean per trade of the pick's test-period signals with coin-flip sides (same table, exit, size)."""
    m = sig["pid"] == P_TEST
    out = []
    for s in range(FLIP_SEEDS):
        xs = []
        for q in np.flatnonzero(m):
            sym = SYMBOLS[sig["coin"][q]]
            side = flip_side(s, p["id"], sym, sig["close"][q])
            xs.append(table(ctx.work, sym, p["tf"])["P"][p["exit_index"], sig["idx"][q], 0 if side > 0 else 1])
        out.append(summary(np.asarray(xs, float))["mean"])
    return out


def same_side_mean(ctx: Ctx, p: dict, sig: dict) -> float | None:
    """PREREG 6.2c: the average over the pick's test trades of the mean P&L of every test-period bar of the same
    coin and timeframe on the same side with the pick's exit (warm-up and NaN left out)."""
    m = (sig["pid"] == P_TEST) & np.isfinite(sig["x"])
    if not m.any():
        return None
    base = {}
    vals = []
    for q in np.flatnonzero(m):
        key = (int(sig["coin"][q]), int(sig["side"][q]))
        if key not in base:
            sym = SYMBOLS[key[0]]
            T = table(ctx.work, sym, p["tf"])
            pid = period_ids(p["rule"], sym, T["close"])
            col = T["P"][p["exit_index"], pid == P_TEST, 0 if key[1] > 0 else 1].astype(float)
            base[key] = float(np.nanmean(col)) if np.isfinite(col).any() else np.nan
        vals.append(base[key])
    return _f(float(np.mean(vals)))


def boot_seed(p: dict) -> int:
    return R._seed("newinfo", p["rule"], p["tf"], p["row"], p["exit"], "test")


def recompute_all(ctx: Ctx, picks: list, sigs: dict) -> dict:
    """Cost x2 and x3 on each pick's test trades and quarter size on all its signals (kernel.outcomes), coin by coin
    so each coin's 1m bars are read once. {pick id: {"x2", "x3", "quarter": arrays aligned with its signals}}."""
    out = {p["id"]: {k: np.full(len(sigs[p["id"]]["x"]), np.nan) for k in ("x2", "x3", "quarter")} for p in picks}
    jobs = (("x2", settings("normal", 2.0), True), ("x3", settings("normal", 3.0), True),
            ("quarter", settings("quarter"), False))
    for ci, sym in enumerate(SYMBOLS):
        for p in picks:
            sig = sigs[p["id"]]
            here = sig["coin"] == ci
            trades = here & (sig["pid"] == P_TEST) & np.isfinite(sig["x"])
            for k, S, test_trades in jobs:
                q = np.flatnonzero(trades if test_trades else here)
                if len(q):
                    out[p["id"]][k][q] = recompute(ctx, sym, p["tf"], sig["idx"][q], sig["side"][q], p["exit_index"], S)
    return out


def account(ctx: Ctx, tf: str, sig: dict, e: int, S: np.ndarray, lo_ms: int, hi_ms: int) -> dict:
    """kernel.account (PREREG.md 6.4): $5,000, one position at a time over the six coins, coin priority, compounding,
    bust; every signal of the pick with close in [lo_ms, hi_ms). Final wallet, max drawdown at closes, worst calendar
    month (by exit: the month's wallet change against the wallet before its first close), liquidations, bust."""
    sel = np.flatnonzero((sig["close"] >= lo_ms) & (sig["close"] < hi_ms))
    cat, starts, ends = R.all_minutes(ctx.data)
    em = []
    for q in sel:
        c = sig["coin"][q]
        tsc = cat["ts"][starts[c]:ends[c]]
        j0 = np.searchsorted(tsc, sig["close"][q] - 60_000)
        em.append(int(tsc[j0 + 1]) if j0 + 1 < len(tsc) else 2 ** 62)
    order = np.lexsort((sig["coin"][sel], np.asarray(em, np.int64))) if len(sel) else np.zeros(0, int)
    qs = sel[order]
    ex = ctx.ex
    brs = np.stack([ex[s][0] for s in SYMBOLS]) if R._same_shape(ex) else R._pad(ex)
    atr = np.array([table(ctx.work, SYMBOLS[sig["coin"][q]], tf)["atr"][sig["idx"][q]] for q in qs], float)
    st, pnl, ext, rs, _lv, wallet = K.account(
        S, brs, cat["ts"], cat["o"], cat["h"], cat["l"], cat["mo"], cat["mh"], cat["ml"], cat["fund"],
        np.array(starts, np.int64), np.array(ends, np.int64), sig["coin"][qs].astype(np.int64),
        sig["close"][qs].astype(np.int64), sig["side"][qs].astype(np.int64), atr, np.zeros(len(qs), bool),
        np.array([ex[s][1] for s in SYMBOLS]), np.array([ex[s][2] for s in SYMBOLS]),
        *K.exit_args(EXIT_GLOBAL[e]), np.full(len(qs), np.nan))
    done = (st == 1) & (rs != K.R_OPEN)
    eq0 = float(S[10])
    path = eq0 + np.cumsum(pnl[done])
    walk = np.r_[eq0, path]
    peak = np.maximum.accumulate(walk)
    dd = float(np.max(1 - walk / peak)) if len(path) else 0.0
    return {"trades": int(done.sum()), "final": float(wallet), "max_dd_at_closes": dd,
            "worst_month": worst_month(ext[done], walk), "liquidations": int((rs[done] == K.R_LIQ).sum()),
            "bust": bool(S[9] > 0 and wallet < S[9]), "skipped": int((st == 0).sum())}


def worst_month(exit_ms: np.ndarray, walk: np.ndarray) -> dict | None:
    """The calendar month (UTC, by exit) with the lowest wallet after its last close / wallet before its first."""
    if not len(exit_ms):
        return None
    months = pd.to_datetime(np.asarray(exit_ms, np.int64), unit="ms", utc=True).strftime("%Y-%m").to_numpy()
    rows: dict = {}
    for k, mo in enumerate(months):
        rows.setdefault(mo, [walk[k], walk[k + 1]])[1] = walk[k + 1]
    chg = {mo: (b / a - 1 if a > 0 else -1.0) for mo, (a, b) in rows.items()}
    mo = min(chg, key=lambda m: (chg[m], m))
    return {"month": mo, "change": float(chg[mo])}


@functools.lru_cache(maxsize=None)
def regime_codes(data: str, sym: str, tf: str) -> np.ndarray:
    """PHASE2_PREREG 7 장세 of every chart bar (paperbot.dash.tools.regime5y on the strategy's own chart)."""
    from paperbot.dash.tools import regime5y as Y
    df, _c = R.frame(data, sym, tf)
    return Y.regimes(df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float),
                     Y.TF_MIN[tf])["code"]


STATES = ("추세장", "횡보장", "급변장", "보통", "모름")


def by_state(ctx: Ctx, p: dict, sig: dict) -> dict:
    from paperbot.dash.tools import regime5y as Y
    m = (sig["pid"] == P_TEST) & np.isfinite(sig["x"])
    lab = np.array([Y.RKO[int(regime_codes(ctx.data, SYMBOLS[sig["coin"][q]], p["tf"])[sig["idx"][q]])]
                    for q in np.flatnonzero(m)], object)
    x = sig["x"][m]
    return {s: summary(x[lab == s]) for s in STATES}


def breakdowns(sig: dict) -> dict:
    """Per period: per coin and per side; per calendar year (signal close, UTC) over all periods. Trades only."""
    t = np.isfinite(sig["x"])
    out = {}
    for k, name in enumerate(PNAMES):
        m = t & (sig["pid"] == k)
        out[name] = {"coin": {s: summary(sig["x"][m & (sig["coin"] == ci)]) for ci, s in enumerate(SYMBOLS)},
                     "side": {"long": summary(sig["x"][m & (sig["side"] > 0)]),
                              "short": summary(sig["x"][m & (sig["side"] < 0)])}}
    years = pd.to_datetime(sig["close"], unit="ms", utc=True).year.to_numpy() if len(sig["close"]) else np.zeros(0)
    out["year"] = {str(y): summary(sig["x"][t & (years == y)]) for y in range(2020, 2027)}
    return out


def confirm_pick(ctx: Ctx, p: dict, sig: dict, rc: dict) -> dict:
    """Everything of PREREG 6.2-6.3 and 7 for one pick except BH (over the family) and the accounts. ``rc``: its
    recomputed arrays (recompute_all)."""
    x = sig["x"]
    per = {name: summary(x[sig["pid"] == k]) for k, name in enumerate(PNAMES)}
    tm = (sig["pid"] == P_TEST) & np.isfinite(x)
    p_test = R.boot_mean_p(week_of(sig["close"][tm]), x[tm], N_BOOT, boot_seed(p)) if tm.any() else None
    flips = flip_means(ctx, p, sig)
    fl = [f for f in flips if f is not None]
    same = same_side_mean(ctx, p, sig)
    return {**p, **per, "test_p": p_test, "flip_means": flips, "flip_mean": float(np.mean(fl)) if fl else None,
            "same_side_mean": same, "test_long_share": _f(float((sig["side"][tm] > 0).mean())) if tm.any() else None,
            "cost": {k: summary(rc[k][tm]) for k in ("x2", "x3")},
            "quarter": {name: summary(rc["quarter"][sig["pid"] == k]) for k, name in enumerate(PNAMES)},
            "by_state_test": by_state(ctx, p, sig), "breakdowns": breakdowns(sig),
            "signals": {name: int((sig["pid"] == k).sum()) for k, name in enumerate(PNAMES)}}


def judge(rows: list) -> None:
    """6.2-6.4 in place: BH over every pick (fewer than MIN_TEST test trades: p = 1)."""
    ps = [r["test_p"] if r["test"]["n"] >= MIN_TEST and r["test_p"] is not None else 1.0 for r in rows]
    sig = R.bh(ps, FDR_Q)
    for r, p_used, s in zip(rows, ps, sig):
        t, e = r["test"], r["extra"]
        mean = t["mean"] if t["mean"] is not None else -math.inf
        x2 = r["cost"]["x2"]["mean"]
        r["bh_p"] = p_used
        r["checks"] = {"test_trades": t["n"] >= MIN_TEST, "test_positive": mean > 0,
                       "beats_flip": r["flip_mean"] is not None and mean > r["flip_mean"],
                       "beats_same_side": r["same_side_mean"] is not None and mean > r["same_side_mean"],
                       "test_fdr": bool(s), "cost_x2_positive": x2 is not None and x2 > 0,
                       "extra_trades": e["n"] >= MIN_EXTRA, "extra_positive": e["mean"] is not None and e["mean"] > 0}
        r["pass"] = all(r["checks"].values())


def stage_confirm(ctx: Ctx) -> dict:
    with open(os.path.join(ctx.out, "select.json")) as fh:
        sel = json.load(fh)
    picks = sel["picks"]
    sigs = {}
    for rule, tf in cells():
        ps = [p for p in picks if p["rule"] == rule and p["tf"] == tf]
        if ps:
            m = market(ctx, rule, tf)
            for p in ps:
                sigs[p["id"]] = pick_signals(ctx, rule, tf, p["combo"], p["exit_index"], m)
    rc = recompute_all(ctx, picks, sigs)
    rows = []
    for p in picks:
        rows.append(confirm_pick(ctx, p, sigs[p["id"]], rc[p["id"]]))
        print(f"[confirm] {p['id']}: test n={rows[-1]['test']['n']}", flush=True)
    judge(rows)
    for r in rows:                             # PREREG 7: the account of every pick, normal and quarter size
        pm = period_ms(r["rule"])
        spans = {"span": (pm[P_SELECT][1], pm[P_TEST][2]), "test": (pm[P_TEST][1], pm[P_TEST][2])}
        r["account"] = {f"{k}_{w}": account(ctx, r["tf"], sigs[r["id"]], r["exit_index"], settings(k), *span)
                        for k in ("normal", "quarter") for w, span in spans.items()}
    passed = [r["id"] for r in rows if r["pass"]]
    doc = {"rows": rows, "passed": len(passed), "candidates": passed, "family": len(rows), "fdr_q": FDR_Q,
           "tables": table_hashes(ctx.work), "metrics": metric_hashes(ctx), "code": code_stamp()}
    _write_json(os.path.join(ctx.out, "confirm.json"), doc)
    print(f"[confirm] {len(passed)} of {len(rows)} picks pass", flush=True)
    return doc


def metric_hashes(ctx: Ctx) -> dict:
    p = os.path.join(ctx.ni, "manifest.json") if ctx.ni else ""
    if not p or not os.path.exists(p):
        return {}
    with open(p) as fh:
        m = json.load(fh)
    return {"orderflow": {k: v["sha256"] for k, v in m.get("orderflow", {}).items()},
            "daily": {k: v["sha256"] for k, v in m.get("daily", {}).items()}}


# ------------------------------------------------------------------ stage 5: report
TF_KO = {"30m": "30분", "1h": "1시간", "4h": "4시간"}
RULE_KO = {"H3A_CROWD_FADE": "H3A 군중 반대", "D04_FUNDING_FADE": "D04 펀딩비 반대", "D05_FUNDING_TREND": "D05 펀딩 눌림 추세",
           "D06_OI_DIVERGENCE": "D06 미결제약정 다이버전스", "D08_CROSS_COIN": "D08 코인 간 강약",
           "D10_VWAP_REVERT": "D10 VWAP 되돌림", "D01_VOL_SPIKE": "D01 거래량 급증"}
CHECK_KO = {"test_trades": "시험 100건", "test_positive": "시험 플러스", "beats_flip": "동전보다 나음",
            "beats_same_side": "같은 방향 아무 때보다 나음", "test_fdr": "우연 보정(BH 10%)",
            "cost_x2_positive": "비용 2배 플러스", "extra_trades": "추가 기간 20건", "extra_positive": "추가 기간 플러스"}
WEAK_NOTE = {"H3A_CROWD_FADE": "예전 주문 흐름·지정가 시험에서 이미 본 기간(약한 증거)",
             "D01_VOL_SPIKE": "예전 라이브러리 시험에서 이미 본 기간(약한 증거)"}


def pct(x, d=3) -> str:
    return "-" if x is None else f"{x * 100:+.{d}f}%"


def _n(s: dict) -> str:
    return f"{s['n']}건 {pct(s['mean'])}" if s and s.get("n") else "0건"


def write_report(out: str) -> str:
    with open(os.path.join(out, "select.json")) as fh:
        sel = json.load(fh)
    with open(os.path.join(out, "confirm.json")) as fh:
        con = json.load(fh)
    rows = con["rows"]
    L = ["# 새 정보 매매법 7개 시험 결과 (PREREG_NEWINFO.md)", ""]
    L += ["## 결론", ""]
    if con["candidates"]:
        L.append(f"고른 {con['family']}개 중 **{con['passed']}개가 후보**입니다: " +
                 ", ".join(f"`{c}`" for c in con["candidates"]) + ". 후보도 바로 실제 돈을 쓰지 않습니다: forward 모의"
                 " 계좌(후보 / 1/4 크기 / 동전)에서 C1·C2를 통과해야 두 분이 1/4 크기 이하를 검토합니다.")
    else:
        L.append(f"고른 {con['family']}개 중 후보는 **없음**입니다. 기준은 낮추지 않습니다(PREREG 6.5).")
    L += ["", "## 읽기 전에", "",
          "- 거래 1건 = 신호 하나를 $5,000 지갑에서 혼자 한 결과(계좌 대비 %). 크기는 규칙봇 '보통'(30배·30%, 안 되면 20배·20%).",
          "- 시험 기간(2024-01 ~ 2026-09)은 전체 격자(711개) 등 여러 시험이 이미 쓴 기간이라, 우연 보정은 이 묶음 안의 "
          "보정일 뿐입니다. 어느 것이 통과해도 깨끗한 증거는 forward 결과뿐입니다.",
          "- H3A는 고르는·시험 기간이, D01은 세 기간 모두 예전 시험에서 본 기간입니다(약한 증거).",
          "- H3A·D06의 추가 기간은 BTC 하나(2020-09 ~ 2021-11)라 다른 매매법보다 약한 확인입니다.",
          "- 장세별·코인별·방향별·연도별 숫자와 1/4 크기, 계좌는 참고용이며 판정에 쓰지 않습니다.", ""]
    L += ["## 칸별 요약 (고르는 기간)", "", "| 매매법 | 봉 | 조합 | 150건 이상 쌍 | 언덕 점수 > 0 | 최고 언덕 점수 | 고른 수 |",
          "|---|---|---|---|---|---|---|"]
    for c in sel["cells"]:
        L.append(f"| {RULE_KO[c['rule']]} | {TF_KO[c['tf']]} | {c['combos']} | {c['with_min_trades']} | "
                 f"{c['plateau_positive']} | {pct(c['best_plateau'])} | {len(c['picks'])} |")
    if sel["missing"]:
        L.append(f"\n빠진 칸: {', '.join(sel['missing'])}")
    L += ["", "## 고른 조합과 판정", "",
          "| 조합 | 고르기 | 시험 | 승률 | p | 동전(10번 평균) | 같은 방향 | 롱 비율 | 비용 2배 | 비용 3배 | 추가 기간 | 판정 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        bad = [CHECK_KO[k] for k, v in r["checks"].items() if not v]
        verdict = "**후보**" if r["pass"] else "참고용 (" + ", ".join(bad) + ")"
        note = f" ({WEAK_NOTE[r['rule']]})" if r["rule"] in WEAK_NOTE else ""
        extra_note = " (BTC 하나, 약한 확인)" if group(r["rule"]) == "metrics" else ""
        win = "-" if r["test"]["win"] is None else f"{r['test']['win'] * 100:.1f}%"
        p_txt = "-" if r["test_p"] is None else f"{r['test_p']:.3f}"
        longs = "-" if r["test_long_share"] is None else f"{r['test_long_share'] * 100:.0f}%"
        L.append(f"| `{r['id']}` {json.dumps(r['combo'], ensure_ascii=False)}{note} | {_n(r['select'])} | "
                 f"{_n(r['test'])} | {win} | {p_txt} | {pct(r['flip_mean'])} | {pct(r['same_side_mean'])} | {longs} | "
                 f"{_n(r['cost']['x2'])} | {_n(r['cost']['x3'])} | {_n(r['extra'])}{extra_note} | {verdict} |")
    L += ["", "## 동전 던지기 10번 (시험 기간, 씨앗별 평균)", ""]
    for r in rows:
        L.append(f"- `{r['id']}`: " + ", ".join(pct(f) for f in r["flip_means"]))
    L += ["", "## 1/4 크기 (참고용)", "", "| 조합 | 고르기 | 시험 | 추가 기간 |", "|---|---|---|---|"]
    for r in rows:
        q = r["quarter"]
        L.append(f"| `{r['id']}` | {_n(q['select'])} | {_n(q['test'])} | {_n(q['extra'])} |")
    L += ["", "## 계좌 ($5,000, 한 번에 한 포지션, 복리; 참고용)", "",
          "| 조합 | 크기 | 기간 | 거래 | 최종 | 최대 낙폭 | 최악의 달 | 강제청산 | 파산 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        for k, a in r["account"].items():
            size, w = k.split("_")
            wm = a["worst_month"]
            L.append(f"| `{r['id']}` | {'보통' if size == 'normal' else '1/4'} | {'고르기 시작~' if w == 'span' else '시험'} | "
                     f"{a['trades']} | ${a['final']:,.0f} | {a['max_dd_at_closes'] * 100:.1f}% | "
                     f"{(wm['month'] + ' ' + pct(wm['change'], 1)) if wm and wm['change'] is not None else '-'} | "
                     f"{a['liquidations']} | {'예' if a['bust'] else '아니오'} |")
    L += ["", "## 장세별 (시험 기간, 참고용)", "", "| 조합 | 추세장 | 횡보장 | 급변장 | 보통 | 모름 |", "|---|---|---|---|---|---|"]
    for r in rows:
        s = r["by_state_test"]
        L.append(f"| `{r['id']}` | " + " | ".join(_n(s[k]) for k in STATES) + " |")
    L += ["", "## 코인·방향·연도별 (참고용)", ""]
    for r in rows:
        b = r["breakdowns"]
        L.append(f"### `{r['id']}`")
        for per in PNAMES:
            L.append(f"- {per}: " + ", ".join(f"{s[:-4]} {_n(v)}" for s, v in b[per]["coin"].items()) +
                     f"; 롱 {_n(b[per]['side']['long'])}, 숏 {_n(b[per]['side']['short'])}")
        L.append("- 연도: " + ", ".join(f"{y} {_n(v)}" for y, v in b["year"].items()))
        L.append("")
    L += ["## 재현 정보", "", f"- 코드 커밋: `{con['code']['commit']}`"]
    L += [f"- `{f}`: `{h}`" for f, h in con["code"]["files"].items()]
    L += [f"- 거래 계산표 `{f}`: `{h}`" for f, h in con["tables"].items()]
    for k, v in con.get("metrics", {}).items():
        L += [f"- {k} `{f}`: `{h}`" for f, h in v.items()]
    text = "\n".join(L) + "\n"
    with open(os.path.join(out, "RESULTS_KO.md"), "w") as fh:
        fh.write(text)
    return text


# ------------------------------------------------------------------ smoke (PREREG 10)
def smoke(data: str, out: str) -> dict:
    """Prices and funding of 2020-01-01 .. 2020-01-03 only (inside every rule's warm-up: no signal of a real period
    can appear), metrics rules left to the synthetic tests. Checks that the bars of defs.bars equal run.build_frame on
    the slice and that every rule other than the metrics ones runs on real inputs; prints structure only."""
    lo, hi = _ms(SMOKE[0]), _ms(SMOKE[1])
    sl = os.path.join(out, "smoke_1m")
    os.makedirs(os.path.join(sl, "1m"), exist_ok=True)
    rep = {"bars": {}, "signals_outside_warmup": 0, "rules": [], "frames_equal": True, "coins": []}
    for sym in SYMBOLS:
        z = R.DATA.load(data, sym)
        m = (z["ts"] >= lo) & (z["ts"] < hi)
        if m.sum() >= 1440:                     # coins listed after the slice (SOL, DOGE) are left out
            np.savez(os.path.join(sl, "1m", f"{sym}.npz"), **{k: v[m] for k, v in z.items()})
            rep["coins"].append(sym)
    for tf in TFS:
        coins = {r: [] for r in D.ORDER if group(r) != "metrics" and tf in D.RULES[r]["tfs"]}
        for sym in rep["coins"]:
            d = R.DATA.load(sl, sym)
            b = D.bars(d["ts"], d["o"], d["h"], d["l"], d["c"], d["v"], D.TF_MS[tf])
            df, close = R.build_frame(sl, sym, tf)
            same = (np.array_equal(df["ts"].astype("int64").to_numpy() // 1_000_000, b["open_ms"]) and
                    all(np.array_equal(df[c].to_numpy(float), b[k]) for k, c in
                        (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume"))))
            rep["frames_equal"] &= bool(same)
            rep["bars"][f"{tf}_{sym}"] = int(len(close))
            if NI.funding_files(data, sym, ("2020-01",)):
                F = NI.funding(data, sym, months=("2020-01",))
                F = {k: v[F["t"] < hi] for k, v in F.items()}
            else:                                   # listed after 2020-01: no settlement in the slice
                F = {"calc": np.zeros(0, np.int64), "t": np.zeros(0, np.int64), "rate": np.zeros(0),
                     "hours": np.zeros(0), "f8": np.zeros(0)}
            day = D.bars(d["ts"], d["o"], d["h"], d["l"], d["c"], d["v"], D.DAY)
            for rule in coins:
                kw = {}
                if rule in ("D04_FUNDING_FADE", "D05_FUNDING_TREND"):
                    kw["funding"] = F
                if rule == "D05_FUNDING_TREND":
                    h = D.HTF_OF[tf]
                    hb = day if h == "1d" else D.bars(d["ts"], d["o"], d["h"], d["l"], d["c"], d["v"], D.TF_MS[h])
                    kw["htf"] = {"close_ms": hb["open_ms"] + D.TF_MS[h], "c": hb["c"]}
                if rule == "D10_VWAP_REVERT":
                    kw["minutes"] = {k: d[k] for k in ("ts", "h", "l", "c", "v")}
                coins[rule].append(D.Coin(sym, tf, b["open_ms"], b["o"], b["h"], b["l"], b["c"], b["v"], **kw))
        for rule, cs in coins.items():
            mk = D.Market(tf, cs)
            for combo in D.grid(rule):
                for sym, (lo_, sh_) in D.signals(rule, mk, combo).items():
                    pid = period_ids(rule, sym, mk.coins[sym].close_ms)
                    rep["signals_outside_warmup"] += int(((lo_ | sh_) & (pid >= 0)).sum() +
                                                         ((lo_ | sh_)[WARMUP_BARS:]).sum())
            rep["rules"].append(f"{rule} {tf}: {len(D.grid(rule))} combinations ran")
    print(json.dumps({k: v for k, v in rep.items() if k != "bars"}, ensure_ascii=False, indent=1))
    print("bars per frame:", sorted(set(rep["bars"].values())))
    return rep


# ------------------------------------------------------------------ status / main
def stage_status(out: str) -> None:
    done = [c for c in cells() if os.path.exists(cell_path(out, *c))]
    print(f"cells done {len(done)} / {len(cells())}")
    for f in ("checks.json", "select.json", "confirm.json", "RESULTS_KO.md"):
        print(f"{f}: {'yes' if os.path.exists(os.path.join(out, f)) else 'not yet'}")
    bad = pin_problems()
    print("pins: " + ("ok" if not bad else "; ".join(bad)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=("check", "grid", "select", "confirm", "report", "all", "smoke", "status"))
    ap.add_argument("--data")
    ap.add_argument("--work")
    ap.add_argument("--results")
    ap.add_argument("--ni")
    ap.add_argument("--out", required=True)
    ap.add_argument("--exchange", default=os.path.join(FG, "exchange.json"))
    ap.add_argument("--procs", type=int, default=MAX_PROCS)
    a = ap.parse_args(argv)
    if a.stage == "status":
        stage_status(a.out)
        return 0
    if a.stage == "smoke":
        rep = smoke(a.data, a.out)
        return 0 if rep["frames_equal"] and rep["signals_outside_warmup"] == 0 else 1
    bad = pin_problems()
    if bad:
        print("[pins] " + "; ".join(bad) + " (PREREG_NEWINFO 10: no real run before the code is pinned)", flush=True)
        return 2
    R.FRAME_DIR[0] = os.path.join(a.out, "frames")
    print(f"[code] {json.dumps(code_stamp())}", flush=True)
    check_stamp(a.out)
    ctx = Ctx(a.data, a.work, a.ni, a.out, a.exchange)
    if a.stage in ("check", "all"):
        stage_check(ctx, a.results)
    checked = require_checks(a.out)
    if a.stage in ("grid", "all"):
        stage_grid(ctx, a.procs)
        tables_unchanged(ctx, checked)
    if a.stage in ("select", "all"):
        stage_select(a.out)
    if a.stage in ("confirm", "all"):
        stage_confirm(ctx)
        tables_unchanged(ctx, checked)
    if a.stage in ("report", "all"):
        write_report(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
