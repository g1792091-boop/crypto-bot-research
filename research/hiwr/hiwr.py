"""Track 2 (고승률 · 낙폭 한도) command line: research/hiwr/PREREG_HIWR.md section 17.1. Read-only research code: public
Binance prices in, files out. No key of any kind, no order, no database of the bots.

    python -m research.hiwr.hiwr datapin   --kit KIT
    python -m research.hiwr.hiwr datacheck --kit KIT --fg1m DIR [--hunt5m DIR]
    python -m research.hiwr.hiwr pinlist
    python -m research.hiwr.hiwr select    --kit KIT --work DIR [--procs N] [--private DIR] [--eligibility all|lazy]
    python -m research.hiwr.hiwr test      --kit KIT --kit-test DIR --work DIR [--procs N] [--private DIR]
    python -m research.hiwr.hiwr reads     --kit KIT --kit-test DIR --work DIR [--private DIR] [--reads-hours H]
    python -m research.hiwr.hiwr ledger    [--private DIR] [--ledger-extra FILE] [--hunt-private FILE]
    python -m research.hiwr.hiwr report    [--private DIR]

Steps (section numbers are PREREG_HIWR.md's):
* datapin (3): research/hiwr/data_manifest_sel.json from the practice kit (2020-01 .. 2023-12): per coin its span and
  the content sha256 of every array, each recomputed from the files (data.content_sha).
* datacheck (3): research/hiwr/data_check_sel.json, the two cross-checks before the pin, on data cut at 2024-01-01:
  (i) the old six against the full grid's 1m archive; (ii) all coins resampled to 5m against the hunt's pinned 5m files
  (each file's content hash checked against research/hunt/data_manifest.json first) or, where those files are not on
  the machine, three seeded months per coin of the archive's own 5m files.
* pinlist (17.3): the files the pin must list, computed in a fresh process (``required_files``).
* select (9, 10): refuses unless the pin matches (``check_pin``). Loads the practice kit only, checks every array's
  hash, cuts every 1m array at 2024-01-01 before any other use, builds the chart frames from the cut arrays in its own
  frame folder, the exit-event tables per coin and timeframe (walk.py), then the grid: a task is a (cell, combo chunk),
  coins outer and combos inner (the indicator memo works per coin); per pair only float64 sums are kept (17.2,
  ``SUM_NAMES``). Then per cell: B, the exit plateau with thinned neighbours (Q21), the number plateau, the plateau
  score, the account and f* (acct.py) and the SEL coin-flip check (10.3 e); one pick per cell (10.5). Writes
  out/select.json, research/hiwr/picks.json and appends the picks line to the pin (10.6).
* test (11-13): refuses unless the picks line is in the pin. Only then is the confirm kit (2024-01 .. 2026-09)
  downloaded (a marker with the picks' hash is written into the kit folder first, and a kit folder holding files
  without that marker is refused); its manifest line and the reads module line are appended to the pin before
  test.json exists. Per pick, once: T0-T6 with both controls (100,000 seeds each), p_boot, BH over all picks, the
  verdict, the program-wide ledger (13). Then the reads.
* reads (14): research/hiwr/reads.py ``run(ctx)``, only after test.json; reported, never a pass. The picks run in
  parallel, one file each in the work folder (a restart skips the picks done); ``--reads-hours`` stops starting new
  picks after that long and writes reads.json with the picks done (the rest listed as missing).
* ledger (13): the program-wide ledger again from test_private.json (its sha256 checked against test.json), the hunt's
  published test files and the list of the program's other hypotheses; never touches test.json or a verdict. It is
  'incomplete' (no BH / Holm count published) while any hypothesis or source is missing.
* report: out/RESULTS_KO.md in plain Korean (DeepSeek rows: labels and counts only, D11).

DeepSeek (D11, section 18): every repository output shows DeepSeek rows as counts, shares and labels only; their other
figures (mean r, DD, f*, margin, monthly returns, p-values) go to ``--private`` (outside the repository) and the
private file's sha256 is written in the public one. ``d11_problems`` checks every public file before it is written.
Choices this file makes where PREREG_HIWR leaves room are listed in ``CHOICES`` (written into every output).
"""

from __future__ import annotations

import os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ.setdefault(_v, "1")     # one thread per worker process: the pool is the parallelism

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import glob  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402

import numpy as np  # noqa: E402

try:
    from numba import njit
except ImportError:  # pragma: no cover  the server installs numba; the tests skip without it
    def njit(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hiwr import acct as A  # noqa: E402
from research.hiwr import data as D  # noqa: E402
from research.hiwr import walk as W  # noqa: E402

R = D.fg_run()                       # research/fullgrid/run.py, read-only

# ------------------------------------------------------------------ registered numbers
TFS = ("15m", "30m", "1h", "4h")
SYMBOLS = D.SYMBOLS                  # coin priority order (section 4)
N_SEEDS = 100_000                    # 11: seeds per control
N_ACCT_SEEDS = 1_000                 # 11: seeds 1..1,000 also run the account at f*
N_PBOOT = 100_000                    # 12: p_boot resamples
N_F95 = A.N_BOOT                     # 8.4: 10,000 week-block paths
N_FLIP_SEL = 200                     # 10.3 (e)
Q_FLIP = 0.95
MIN_SEL = A.MIN_N                    # 10.2: 150
THIN_MIN = 50                        # 10.3 (b), Q21
ACCT_MIN = 100                       # 10.3 (d)
MIN_TEST = 100                       # T0
T5_ALPHA = 0.05
BH_Q = 0.10                          # T6, 13
HOLM_ALPHA = 0.05                    # 13
TIME_MIN_BARS = 20                   # 11 (b): fewer takeable bars -> the at-least-one-member fallback
SUM_COLS = (W.S_N, W.S_WIN, W.S_SUM, W.S_N2, W.S_SUM2, W.S_WIN2)
SUM_NAMES = ("n", "wins", "sum_r", "n_x2", "sum_r_x2", "wins_x2")
GRID_WEIGHT = {"15m": 16, "30m": 8, "1h": 4, "4h": 1}
ELIG_PAIRS = {"15m": 8, "30m": 16, "1h": 32, "4h": 64}      # pairs per eligibility task (mode "all")
MIN_FREE = 1024 ** 3                 # stop below 1 GB free (as the hunt)

CHOICES = [
    "17.2: six per-pair sums (n, wins, sum r, n at cost x2, sum r at cost x2, wins at cost x2); the cost-x2 mean is "
    "sum r x2 / n x2 (acct.stats_from_sums): a trade resolved at cost x1 can be open at the end at cost x2.",
    "A combo whose signal code raises on any coin is recorded as failed for the whole cell: it has no trades, passes "
    "nothing, and as a number neighbour (10.3 c) it exists and fails B. Out of memory and operating-system errors are "
    "never recorded as a failed combo: the task stops and is redone.",
    "10.3 (b) and 10.4: an exit neighbour with fewer than 50 trades counts as not existing for the plateau score too; "
    "one with 50-149 trades counts as 0 in the score.",
    "Seeds (8.4, 12, 3): f95 draws sha256('hiwr|f95|<period>|<pick id>|f95') (acct.py), p_boot sha256('hiwr|boot|"
    "<period>|<pick id>|boot'), the (ii) data-check months sha256('hiwr|datacheck|SEL|<symbol>|months').",
    "p_boot (12) resamples the weeks that hold trades (as research/fullgrid/run.boot_mean_p); a resample whose mean is "
    "<= 0 counts against the pick.",
    "Coin-flip control (11 a): heads (0) keeps the group's side, tails (1) reverses it; a seed's mean is over the trades "
    "its sides take (the trade-list rules decide), NaN when it takes none (never counted as >= the pick); a pick "
    "without a TEST trade gets p = 1 and T5 false.",
    "Random-time control (11 b): clusters are drawn in time order of their original close; 'without replacement' is "
    "per seed across its clusters (rejection sampling from a seeded uniform stream, an explicit scan after 32 "
    "rejections); a cluster with no unused bar left is dropped for that seed (counted).",
    "10.6: select.json counts the pairs passing (d) and (e) among the pairs that pass (a)-(c); with --eligibility lazy "
    "only the plateau groups down to the pick are evaluated (the pick is the same; the counts are then marked partial). "
    "The eligibility files of the two modes live in separate folders.",
    "8.4: f_path and f* are 0.01 below the first failing grid size (an upward scan, acct.sizes), not a bisection.",
    "The account of a pick (8.2) walks the 1m bars of its period from one day before the period start (so the entry "
    "minute of a signal closing at the period start is the kernel's), and no minute at or after the period end.",
    "Coins whose practice-kit data ended inside SEL (TOMO) are not downloaded for the confirm kit.",
    "13: the program-wide ledger publishes BH / Holm counts only when every hypothesis of the program has a p; "
    "otherwise it is 'incomplete' and lists what is missing (``hiwr ledger`` completes it later; no verdict changes).",
]


# ------------------------------------------------------------------ paths (tests point STATE at a temporary folder)
STATE = [ROOT]                       # where the files this study writes live (the repository by default)
PREREG_REL = "research/hiwr/PREREG_HIWR.md"
PIN_REL = "research/hiwr/PREREG_HIWR.sha256"
PICKS_REL = "research/hiwr/picks.json"
MANIFEST_SEL_REL = "research/hiwr/data_manifest_sel.json"
CHECK_SEL_REL = "research/hiwr/data_check_sel.json"
MANIFEST_TEST_REL = "research/hiwr/data_manifest_test.json"
OUT_REL = "research/hiwr/out"
READS_RELS = ("research/hiwr/reads.py",)
FG_FILES = tuple(f"research/fullgrid/{f}" for f in ("grid.py", "ds_defs.py", "kernel.py", "run.py", "memo.py",
                                                      "data.py", "exchange.json"))
FIXED_FILES = ("research/entry_study/DEFS_BC.sha256", "research/hunt/universe30.json", "research/hunt/exchange30.json")
HUNT_MANIFEST_REL = "research/hunt/data_manifest.json"
# The hunt's test files: where its push publishes them (research/hunt/bootstrap.sh pack/push: results.tgz unpacked
# under research/hunt/results/ on the hunt-results branch), then where its own server writes them.
HUNT_TESTS = (("hunt v1", ("research/hunt/results/hunt/v1/test.json", "research/hunt/out/v1/test.json")),
              ("hunt wide", ("research/hunt/results/hunt/wide/test.json", "research/hunt/out/wide/test.json")))
LEDGER_EXTRA_REL = "research/hiwr/ledger_extra.json"       # the program's other test-period hypotheses (13), if given
TEST_KIT_MARK = "hiwr_test_kit.json"


def _state_rel(rel: str) -> bool:
    return rel in (PIN_REL, PICKS_REL, MANIFEST_SEL_REL, CHECK_SEL_REL, MANIFEST_TEST_REL) or rel.startswith(OUT_REL)


def rpath(rel: str) -> str:
    """Absolute path of a repository-relative file: the study's own outputs under STATE, everything else the repo."""
    return os.path.join(STATE[0] if _state_rel(rel) else ROOT, rel)


def out_path(name: str) -> str:
    return rpath(f"{OUT_REL}/{name}")


def PER(name: str) -> tuple:
    return tuple(D.PERIODS[name])        # read at call time (tests set short synthetic periods)


# ------------------------------------------------------------------ small helpers
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return [_jsonable(v) for v in o.tolist()]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (np.floating, float)):
        x = float(o)
        return x if math.isfinite(x) else None
    return o


def write_json(path: str, doc) -> str:
    """Atomic JSON write; returns the file's sha256."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        json.dump(_jsonable(doc), fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    return sha256_file(path)


def load_json(path: str):
    with open(path) as fh:
        return json.load(fh)


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def iso(ms_: int) -> str:
    return dt.datetime.fromtimestamp(int(ms_) / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def log(msg: str) -> None:
    print(f"[hiwr {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def disk_check(path: str) -> None:
    p = path
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    free = shutil.disk_usage(p or "/").free
    if free < MIN_FREE:
        raise SystemExit(f"disk: {free / 1024 ** 3:.2f} GB free under {p}, below 1 GB; stopping")


def _f(x):
    return None if x is None or not np.isfinite(x) else float(x)


def is_ds(row: dict) -> bool:
    return row.get("kind") == "ds"


def exit_configs() -> list:
    return W.exit_configs("net")


def pick_id(name: str, tf: str, row: int, cfg: dict) -> str:
    """Section 11: '<strategy>|<tf>|<combo index>|L<tier>|TP<price>|<stop>|<fill>'."""
    return f"{name}|{tf}|{int(row)}|{W.exit_label(cfg)}"


@__import__("functools").lru_cache(maxsize=1)
def CX() -> dict:
    return A.exchange30()


# ------------------------------------------------------------------ pin (17.3)
class PinError(RuntimeError):
    pass


def read_pin() -> list:
    path = rpath(PIN_REL)
    if not os.path.exists(path):
        raise PinError(f"{PIN_REL} does not exist: the study is not pinned")
    rows = []
    with open(path) as fh:
        for line in fh:
            if not line.strip():
                continue
            parts = line.rstrip("\n").split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                raise PinError(f"{PIN_REL}: bad line {line!r} (want '<sha256>  <path>')")
            rows.append((parts[0], parts[1].strip()))
    return rows


def append_pin(rel: str) -> str:
    """Append '<sha256>  <rel>' to the pin (the picks line, the confirm manifest line, the reads lines)."""
    h = sha256_file(rpath(rel))
    with open(rpath(PIN_REL), "a") as fh:
        fh.write(f"{h}  {rel}\n")
    log(f"pin: appended {rel} ({h[:12]})")
    return h


def _repo_py_loaded() -> list:
    """Repository .py files of every loaded module (tests and hidden folders excluded), as the hunt lists them."""
    out = set()
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None) or ""
        if not f.endswith(".py"):
            continue
        a = os.path.abspath(f)
        try:
            if os.path.commonpath([a, ROOT]) != ROOT:
                continue
        except ValueError:
            continue
        rel = os.path.relpath(a, ROOT)
        if rel.startswith(("tests" + os.sep, ".")) or os.sep + "site-packages" + os.sep in a:
            continue
        out.add(rel.replace(os.sep, "/"))
    return sorted(out)


def _synthetic_frame(seed: int, n: int, tf: str):
    import pandas as pd
    rng = np.random.default_rng(seed)
    c = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    ts = D.ms("2021-03-01") + np.arange(n, dtype=np.int64) * R.TF_MS[tf]
    df = pd.DataFrame({"ts": pd.to_datetime(ts, unit="ms", utc=True), "open": o, "high": h, "low": lo, "close": c,
                       "volume": rng.lognormal(0, 1, n) * 100.0})
    df.attrs["tf"] = tf
    return df


def probe_files() -> list:
    """Run every definition once on each of its timeframes on short synthetic bars (no real price), load the bracket
    tables and the monthly bounds (lazy imports of acct.py), then list the repository Python files loaded. Called in a
    fresh process by ``required_files``."""
    for kind, name, tf in R.cells():
        df, btc = _synthetic_frame(1, 1200, tf), _synthetic_frame(2, 1200, tf)
        combo = R.default_combo(kind, name)
        if kind == "core":
            R.core_module(name).signals(df, tf, **combo)
        else:
            R.ds_module().signals(df, tf, name, ctx={"BTCUSD": btc}, coin="ETHUSD", cache={}, **combo)
    CX()
    A.month_bounds(D.PERIODS["SEL"])
    return _repo_py_loaded()


_REQUIRED: list = []


def required_files() -> list:
    """The files the pin must list (17.3), the later lines (picks, confirm manifest, reads) excluded: the prereg, every
    research/hiwr module the command imports, the hiwr tests, every repository Python file the signal code loads (a
    fresh process runs each definition once on synthetic bars), the full grid's files, DEFS_BC.sha256, the hunt's
    universe and bracket files and the practice kit's manifest and data check. Sorted; the same in any process."""
    if _REQUIRED:
        return list(_REQUIRED)
    code = ("import json, sys; sys.path.insert(0, %r); from research.hiwr import hiwr as H; "
            "print('HIWR_PROBE ' + json.dumps(H.probe_files()))" % ROOT)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST", "COV_"))}
    res = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env=env,
                         timeout=1800)
    line = [x for x in res.stdout.splitlines() if x.startswith("HIWR_PROBE ")]
    if res.returncode != 0 or not line:
        raise PinError(f"pinlist probe failed: {res.stderr[-2000:]}")
    loaded = json.loads(line[-1][len("HIWR_PROBE "):])
    tests = sorted(os.path.relpath(p, ROOT).replace(os.sep, "/")
                   for p in glob.glob(os.path.join(ROOT, "tests", "test_hiwr_*.py")))
    need = set(loaded) | {PREREG_REL, *FG_FILES, *FIXED_FILES, MANIFEST_SEL_REL, CHECK_SEL_REL, *tests}
    need -= set(READS_RELS)            # appended later (17.3), never imported by select
    _REQUIRED[:] = sorted(need)
    return list(_REQUIRED)


def content_problems() -> list:
    """The pinned result files must say pass (3): the data check passes and ran on the pinned manifest."""
    bad = []
    if not os.path.exists(rpath(CHECK_SEL_REL)) or not os.path.exists(rpath(MANIFEST_SEL_REL)):
        return [f"{CHECK_SEL_REL} or {MANIFEST_SEL_REL} missing"]
    chk = load_json(rpath(CHECK_SEL_REL))
    if chk.get("pass") is not True:
        bad.append(f"{CHECK_SEL_REL} does not say pass")
    if chk.get("data_manifest_sha256") != sha256_file(rpath(MANIFEST_SEL_REL)):
        bad.append(f"{CHECK_SEL_REL} checked other data than {MANIFEST_SEL_REL}")
    return bad


def check_pin(step: str) -> dict:
    """Refuse (PinError) unless every listed file matches its line, every required file is listed and the data check
    passes; select also needs no picks line, test (and reads) need it."""
    rows = read_pin()
    listed = {p for _h, p in rows}
    last = {}
    for h, p in rows:
        last[p] = h
    bad, superseded = [], []
    cur: dict = {}
    for h, p in rows:
        full = rpath(p)
        if p not in cur:
            cur[p] = sha256_file(full) if os.path.exists(full) else None
        if cur[p] is None:
            bad.append(f"missing {p}")
        elif cur[p] != h:
            if p in READS_RELS and last[p] == cur[p]:
                superseded.append(p)       # an older line of a fixed reads module: post hoc (DEVIATIONS.md)
            else:
                bad.append(f"changed {p}")
    for p in required_files():
        if p not in listed:
            bad.append(f"not pinned {p}")
    bad += content_problems()
    if step == "select" and PICKS_REL in listed:
        bad.append(f"{PICKS_REL} is already pinned: select ran; the picks do not change")
    if step in ("test", "reads") and PICKS_REL not in listed:
        bad.append(f"{PICKS_REL} is not pinned: run select first")
    if bad:
        raise PinError(f"{PIN_REL} does not match: " + "; ".join(sorted(set(bad))))
    out = {"pin_file": PIN_REL, "pin_sha256": sha256_file(rpath(PIN_REL)), "lines": len(rows)}
    if superseded:
        out["superseded_reads_lines"] = sorted(set(superseded))
        log(f"pin: older lines of {out['superseded_reads_lines']} are superseded (post hoc, DEVIATIONS.md)")
    return out


def stamp(pin: dict | None) -> dict:
    try:
        head = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        head = ""
    code = {}
    for m in ("hiwr.py", "data.py", "walk.py", "acct.py"):
        code[f"research/hiwr/{m}"] = sha256_file(os.path.join(HERE, m))
    return {"pin": pin, "commit": head, "code": code, "written_utc": now_utc(), "choices": CHOICES}


# ------------------------------------------------------------------ private files (D11)
def private_dir(args) -> str:
    base = getattr(args, "private", None) or os.path.join(getattr(args, "work", None) or ".", "hiwr_private")
    path = os.path.abspath(base)
    if os.path.commonpath([path, os.path.abspath(ROOT)]) == os.path.abspath(ROOT):
        raise SystemExit("--private must be outside the repository (D11)")
    os.makedirs(path, exist_ok=True)
    return path


def write_private(args, name: str, doc) -> str:
    path = os.path.join(private_dir(args), name)
    disk_check(path)
    return write_json(path, doc)


DS_FLOAT_KEYS = ("win", "win_x2", "win_rate")
DS_DEF_KEYS = ("exit", "combo", "cap", "choices")     # a pick's definition and the rule numbers: labels, not results


def d11_problems(obj, ds_ids: set, path: str = "out", under: bool = False) -> list:
    """D11 check of a public document: no float under a dict that names a DeepSeek row (kind 'ds', or an id / key of a
    DeepSeek pick), except win rates and shares (``DS_FLOAT_KEYS``, keys starting with 'share') and the pick's own
    definition (``DS_DEF_KEYS``: combo numbers, exit, cap)."""
    bad = []
    if isinstance(obj, dict):
        names = under or obj.get("kind") == "ds" or str(obj.get("id", "")) in ds_ids
        for k, v in obj.items():
            hit = names or str(k) in ds_ids
            if hit and str(k) in DS_DEF_KEYS:
                continue
            if hit and isinstance(v, float) and not (str(k) in DS_FLOAT_KEYS or str(k).startswith("share")):
                bad.append(f"{path}.{k}")
            else:
                bad += d11_problems(v, ds_ids, f"{path}.{k}", hit)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            if under and isinstance(v, float):
                bad.append(f"{path}[{i}]")
            else:
                bad += d11_problems(v, ds_ids, f"{path}[{i}]", under)
    return bad


def write_public(path: str, doc, ds_ids: set) -> str:
    bad = d11_problems(_jsonable(doc), ds_ids)
    if bad:
        raise RuntimeError(f"D11: DeepSeek figures in a public file {path}: {bad[:5]}")
    return write_json(path, doc)


# ------------------------------------------------------------------ strategies (read-only through run.py)
def cells_all() -> list:
    return [c for c in R.cells() if c[2] in TFS]


def cell_grid(kind: str, name: str) -> tuple:
    return R.cell_grid(kind, name)


def combo_neighbours(kind: str, name: str) -> list:
    return R.combo_neighbours(kind, name)


def raw_signals(kind: str, name: str, sym: str, tf: str, combo: dict) -> tuple:
    return R.signals("hiwr", kind, name, sym, tf, combo)


def cell_key(kind: str, name: str, tf: str) -> str:
    return f"{kind}_{name}_{tf}"


_FRAMES = [None]
_ATR: dict = {}


def use_frames(fdir: str) -> None:
    """Point run.frame / run.signals at one of hiwr's frame folders (built from period-cut arrays only)."""
    if _FRAMES[0] != fdir:
        D.use_frames(fdir)
        R._LAST_SERIES[0] = None
        R._DS_CACHE.clear()
        _ATR.clear()
        _FRAMES[0] = fdir


def frame(sym: str, tf: str) -> tuple:
    return R.frame("hiwr", sym, tf)


def frame_atr(sym: str, tf: str) -> tuple:
    """(close ms, ATR14) of the active frame folder's chart bars."""
    key = (_FRAMES[0], sym, tf)
    if key not in _ATR:
        if len(_ATR) > 8:
            _ATR.clear()
        df, close = frame(sym, tf)
        _ATR[key] = (close, R._vendor_fg().atr(df, 14).to_numpy(float))
    return _ATR[key]


# ------------------------------------------------------------------ data: kits, markets, frames, tables
def load_period_arrays(sym: str, period_name: str, kits: dict) -> dict | None:
    """One coin's 1m arrays for a period's computations, every array's hash checked against its manifest and every
    array cut at the period's end (section 9) right after loading. SEL and EXTRA read the practice kit only; TEST joins
    the practice kit and the confirm kit."""
    man_sel = kits["man_sel"]["coins"]
    if sym not in man_sel:
        return None
    end = PER(period_name)[1]
    if period_name in ("SEL", "EXTRA"):
        return D.load_kit(kits["kit"], sym, end, want=man_sel[sym]["content_sha256"])
    man_test = kits["man_test"]["coins"]
    dirs, wants = [kits["kit"]], [man_sel[sym]["content_sha256"]]
    if sym in man_test:
        dirs.append(kits["kit_test"])
        wants.append(man_test[sym]["content_sha256"])
    return D.load_cut(dirs, sym, end, wants)


MKEYS = ("ts", "o", "h", "l", "c", "mo", "mh", "ml", "fund")


class Market:
    """The 1m bars of every coin over [period start - 1 day, period end): the account's minute store (acct.Store,
    coin end per coin) and per-coin views for the exit tables. Coins without a minute in the period are left out;
    coin order stays the universe order (priority, section 4)."""

    def __init__(self, name: str, arrays_of, syms):
        self.name = name
        self.period = PER(name)
        lo, hi = self.period[0] - D.DAY, self.period[1]
        segs, self.syms, self.ended = [], [], []
        for s in syms:
            a = arrays_of(s)
            if a is None or not len(a["ts"]):
                continue
            i0, i1 = int(np.searchsorted(a["ts"], lo)), int(np.searchsorted(a["ts"], hi))
            if i1 <= i0 or a["ts"][i1 - 1] < self.period[0]:
                continue
            segs.append({k: np.ascontiguousarray(a[k][i0:i1]) for k in MKEYS})
            self.syms.append(s)
            self.ended.append(bool(segs[-1]["ts"][-1] < hi - D.END_GAP))
            del a
        self.store = A.Store.from_coins(segs, self.ended)
        self.fund = np.concatenate([s["fund"] for s in segs]) if segs else np.zeros(0)
        del segs
        self.coins = [CX()[s] for s in self.syms]
        self.idx = {s: i for i, s in enumerate(self.syms)}

    def arrays(self, i: int) -> dict:
        o0, o1 = int(self.store.off[i]), int(self.store.off[i + 1])
        out = {k: getattr(self.store, k)[o0:o1] for k in MKEYS if k != "fund"}
        out["fund"] = self.fund[o0:o1]
        return out

    def minutes(self) -> int:
        return int(len(self.store.ts))


CTX: dict = {}                       # markets and folders of this process (inherited by forked workers)


def _frames_job(args) -> str:
    sym, period_name, kits, fdir, tfs = args
    if all(os.path.exists(D.frame_path(fdir, sym, tf)) for tf in tfs):
        return ""
    a = load_period_arrays(sym, period_name, kits)
    if a is None:
        return f"{sym}: no data"
    D.make_frames(a, sym, tfs, fdir)
    return f"{sym}: frames"


def frames_stage(period_name: str, kits: dict, fdir: str, tfs, procs: int) -> None:
    """Chart frames (run.build_frame) of every coin from the period-cut arrays, in hiwr's own frame folder."""
    os.makedirs(fdir, exist_ok=True)
    items = [(s, period_name, kits, fdir, tuple(tfs)) for s in SYMBOLS]
    for msg in R.run_pool(_frames_job, items, procs, f"frames {period_name}",
                          done=lambda it: all(os.path.exists(D.frame_path(fdir, it[0], tf)) for tf in tfs)):
        if msg:
            log(f"[frames {period_name}] {msg}")


TABLE_ATTRS = ("bars", "close", "atr", "ent", "ent_ms", "p0", "weekend", "fc", "ts", "liqd", "tp_t", "tp_m")


def save_tables(T, d: str) -> None:
    tmp = f"{d}.{os.getpid()}.part"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for k in TABLE_ATTRS:
        np.save(os.path.join(tmp, f"{k}.npy"), np.asarray(getattr(T, k)))
    for cm, X in T.x.items():
        for k in W.Tables.KEYS:
            np.save(os.path.join(tmp, f"x{cm}_{k}.npy"), X[k])
    with open(os.path.join(tmp, "meta.json"), "w") as fh:
        json.dump({"end": int(T.end), "coin_end": bool(T.coin_end), "pierce": float(T.pierce),
                   "costs": sorted(T.x)}, fh)
    if os.path.exists(d):
        shutil.rmtree(tmp, ignore_errors=True)
        return
    os.replace(tmp, d)


def load_tables(d: str):
    """A walk.Tables restored from ``save_tables``; None when the coin has no bars in the period."""
    if not os.path.exists(d):
        if os.path.exists(d + ".none"):
            return None
        raise FileNotFoundError(d)
    T = object.__new__(W.Tables)
    for k in TABLE_ATTRS:
        setattr(T, k, np.load(os.path.join(d, f"{k}.npy")))
    meta = load_json(os.path.join(d, "meta.json"))
    T.end, T.coin_end, T.pierce = int(meta["end"]), bool(meta["coin_end"]), float(meta["pierce"])
    T.x = {cm: {k: np.load(os.path.join(d, f"x{cm}_{k}.npy")) for k in W.Tables.KEYS} for cm in meta["costs"]}
    return T


def table_dir(tdir: str, sym: str, tf: str) -> str:
    return os.path.join(tdir, f"{tf}_{sym}")


def _tables_job(args) -> str:
    period_name, sym, tf, fdir, tdir = args
    d = table_dir(tdir, sym, tf)
    if os.path.exists(d) or os.path.exists(d + ".none"):
        return ""
    mk = CTX[period_name]
    if sym not in mk.idx or not os.path.exists(D.frame_path(fdir, sym, tf)):
        open(d + ".none", "w").close()
        return f"{sym} {tf}: no bars"
    t0 = time.time()
    use_frames(fdir)
    i = mk.idx[sym]
    close, atr = frame_atr(sym, tf)
    T = W.build_tables(mk.arrays(i), close, atr, mk.period, mk.ended[i], CX()[sym]["br"], cfgs=exit_configs(),
                       warmup=R.WARMUP_BARS)
    disk_check(tdir)
    save_tables(T, d)
    return f"{sym} {tf}: {len(T.bars)} bars, {time.time() - t0:.0f}s"


def tables_stage(period_name: str, fdir: str, tdir: str, tfs, procs: int) -> None:
    """Exit-event tables (walk.py) of every coin and timeframe over the period's bars, at cost x1 and x2."""
    os.makedirs(tdir, exist_ok=True)
    order = {tf: i for i, tf in enumerate(TFS)}
    items = [(period_name, s, tf, fdir, tdir) for tf in sorted(tfs, key=order.get) for s in SYMBOLS]
    for msg in R.run_pool(_tables_job, items, procs, f"tables {period_name}",
                          done=lambda it: os.path.exists(table_dir(tdir, it[1], it[2]))
                          or os.path.exists(table_dir(tdir, it[1], it[2]) + ".none")):
        if msg:
            log(f"[tables {period_name}] {msg}")


def rowmap_of(T, n_bars: int) -> np.ndarray:
    m = getattr(T, "_rowmap", None)
    if m is None or len(m) != n_bars:
        m = np.full(n_bars, -1, np.int64)
        ok = T.bars < n_bars
        m[T.bars[ok]] = np.flatnonzero(ok)
        T._rowmap = m
    return m


def cand_rows(T, lo, sh, weekend_rule: bool = True) -> tuple:
    """(rows of T, sides 0 long / 1 short) of the candidates (5): every bar whose long (short) array is true; with the
    weekend rule (2.4) a signal-bar close from Saturday 00:00 to Monday 00:00 UTC is dropped."""
    m = rowmap_of(T, len(lo))
    il = m[np.flatnonzero(np.asarray(lo, bool))]
    is_ = m[np.flatnonzero(np.asarray(sh, bool))]
    il, is_ = il[il >= 0], is_[is_ >= 0]
    rows = np.r_[il, is_].astype(np.int64)
    sides = np.r_[np.zeros(len(il), np.int64), np.ones(len(is_), np.int64)]
    if weekend_rule:
        keep = ~T.weekend[rows]
        rows, sides = rows[keep], sides[keep]
    return rows, sides


def acct_pieces(T, rows, sides, x: dict, cfg: dict, seg: int, flipped_ok: bool = False) -> dict:
    """The account's candidates of one coin from its trade list (as acct.candidates_from_tables): every candidate with
    an entry (skip 4 excluded) whose stop is wider than the TP (skip 2 excluded, unless ``flipped_ok``: the account
    redoes that check itself)."""
    keep = x["skip"] != 4
    if not flipped_ok:
        keep &= x["skip"] != 2
    rr, ss = np.asarray(rows)[keep], np.asarray(sides)[keep]
    fam, v = W.STOPS[cfg["k"]]
    return {"coin": np.full(len(rr), seg, np.int64), "e": T.ent[rr], "side": np.where(ss == 0, 1, -1),
            "D": v * (T.atr[rr] if fam == "atr" else T.p0[rr]), "atr": T.atr[rr], "fill": T.ent_ms[rr]}


def candidates_of(parts: list) -> dict:
    cat = lambda k, dtp: np.concatenate([p[k] for p in parts]).astype(dtp) if parts else np.zeros(0, dtp)  # noqa
    c = cat("coin", np.int64)
    return A.candidates(c, c, cat("e", np.int64), cat("side", np.int64), cat("D", float), cat("atr", float),
                        cat("fill", np.int64))


# ------------------------------------------------------------------ grid (17.2)
def grid_tasks(cells: list) -> list:
    tasks = []
    for kind, name, tf in cells:
        n = len(cell_grid(kind, name)[2])
        ch = R.CHUNK_OF.get(name, R.CHUNK)
        for c0 in range(0, n, ch):
            tasks.append((kind, name, tf, c0, min(n, c0 + ch)))
    return sorted(tasks, key=lambda t: (-(t[4] - t[3]) * GRID_WEIGHT[t[2]] * R.COST.get(t[1], 1.0), t))


def sums_path(work: str, t: tuple) -> str:
    kind, name, tf, c0, _c1 = t
    return os.path.join(work, "sums", cell_key(kind, name, tf), f"c{c0:05d}")


def b_mask(S: np.ndarray) -> np.ndarray:
    """10.2 on stored sums (..., 6): n >= 150, win rate >= 70.0%, mean > 0, cost-x2 mean > 0."""
    n, w, s, n2, s2 = S[..., 0], S[..., 1], S[..., 2], S[..., 3], S[..., 4]
    with np.errstate(invalid="ignore", divide="ignore"):
        return (n >= MIN_SEL) & (w >= A.MIN_WIN * n) & (s > 0) & (n2 > 0) & (s2 > 0)


def _grid_job(args) -> str:
    work, t = args
    path = sums_path(work, t)
    if os.path.exists(path + ".json"):
        return ""
    kind, name, tf, c0, c1 = t
    t0 = time.time()
    try:
        use_frames(CTX["dirs"]["frames_SEL"])
        cfgs = exit_configs()
        tt, tm, _ti = W.tp_sets(cfgs)
        ca = W.cfg_arrays(cfgs, tt, tm)
        combos = cell_grid(kind, name)[2][c0:c1]
        nc, ncfg = len(combos), len(cfgs)
        acc = np.zeros((nc, ncfg, len(SUM_COLS)))
        accw = np.zeros((nc, ncfg, len(SUM_COLS)))
        fails: dict = {}
        cand = np.zeros(2, np.int64)                      # weekday candidates, weekend-dropped candidates
        tmp = np.zeros((ncfg, W.NSUM))
        cols = list(SUM_COLS)
        for sym in SYMBOLS:
            T = load_tables(table_dir(CTX["dirs"]["tables_SEL"], sym, tf))
            if T is None:
                continue
            for k, combo in enumerate(combos):
                if k in fails:
                    continue
                try:
                    lo, sh = raw_signals(kind, name, sym, tf, combo)
                except Exception as exc:  # noqa: BLE001  a combination the rule cannot compute: no trades
                    fails[k] = f"{sym}: {type(exc).__name__}: {exc}"[:200]
                    continue
                rows, sides = cand_rows(T, lo, sh, weekend_rule=False)
                wk = T.weekend[rows]
                cand += (int((~wk).sum()), int(wk.sum()))
                tmp[:] = 0.0
                W.pair_sums(T, rows[~wk], sides[~wk], ca, tmp)
                acc[k] += tmp[:, cols]
                tmp[:] = 0.0
                W.pair_sums(T, rows[wk], sides[wk], ca, tmp)
                accw[k] += tmp[:, cols]
            del T
        for k in fails:
            acc[k] = np.nan
            accw[k] = np.nan
        with_we = b_mask(acc + accw)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        disk_check(path)
        np.save(path + ".tmp.npy", acc)
        os.replace(path + ".tmp.npy", path + ".npy")
        write_json(path + ".json", {"c0": c0, "c1": c1, "fails": {str(c0 + k): v for k, v in fails.items()},
                                    "with_weekends_pass_B": int(with_we.sum()),
                                    "with_weekends_pass_B_pairs": [[c0 + int(r), int(e)]
                                                                   for r, e in np.argwhere(with_we)][:2000],
                                    "candidates_weekday": int(cand[0]), "candidates_weekend_dropped": int(cand[1]),
                                    "seconds": round(time.time() - t0, 1)})
        return f"{kind} {name} {tf} {c0}-{c1}: {time.time() - t0:.0f}s" + (f", {len(fails)} failed" if fails else "")
    except Exception:  # noqa: BLE001  one broken task must not stop the run: logged, a rerun picks it up
        return f"ERROR {kind} {name} {tf} {c0}: " + traceback.format_exc()[-1500:]


def grid_stage(work: str, cells: list, procs: int) -> int:
    allt = grid_tasks(cells)
    todo = [t for t in allt if not os.path.exists(sums_path(work, t) + ".json")]
    log(f"[grid] {len(todo)} of {len(allt)} tasks to do")
    t0, k = time.time(), 0
    for msg in R.run_pool(_grid_job, [(work, t) for t in todo], procs, "grid",
                          done=lambda a: os.path.exists(sums_path(a[0], a[1]) + ".json")):
        k += 1
        if msg:
            el = time.time() - t0
            log(f"[grid {k}/{len(todo)} {el / 3600:.2f}h, ~{el / k * (len(todo) - k) / 3600:.1f}h left] {msg}")
    missing = [t for t in allt if not os.path.exists(sums_path(work, t) + ".json")]
    return len(missing)


def cell_sums(work: str, kind: str, name: str, tf: str) -> tuple:
    """(sums (combos, 162, 6), failed combo rows, task metas) of one cell, pooled over coins (the tasks hold every
    coin)."""
    n = len(cell_grid(kind, name)[2])
    S = np.zeros((n, len(exit_configs()), len(SUM_COLS)))
    fails, metas = set(), []
    for t in grid_tasks([(kind, name, tf)]):
        p = sums_path(work, t)
        S[t[3]:t[4]] = np.load(p + ".npy")
        m = load_json(p + ".json")
        fails |= {int(k) for k in m["fails"]}
        metas.append(m)
    return S, sorted(fails), metas


# ------------------------------------------------------------------ selection: B, plateaus (10.2-10.4)
def exit_neighbours(cfgs: list) -> list:
    """Per exit config, its exit neighbours (10.3 b): the TP one step up and down within the tier, the stop one step
    narrower and wider within its family; same tier and fill."""
    idx = {(c["Li"], c["step"], c["k"], c["fill"]): i for i, c in enumerate(cfgs)}
    out = []
    for c in cfgs:
        nb = []
        for d in (-1, 1):
            j = idx.get((c["Li"], c["step"] + d, c["k"], c["fill"]))
            if j is not None:
                nb.append(j)
        fam = W.STOPS[c["k"]][0]
        for d in (-1, 1):
            k2 = c["k"] + d
            if 0 <= k2 < len(W.STOPS) and W.STOPS[k2][0] == fam:
                j = idx.get((c["Li"], c["step"], k2, c["fill"]))
                if j is not None:
                    nb.append(j)
        out.append(nb)
    return out


def cell_pairs(S: np.ndarray, cnb: list, cfgs: list) -> dict:
    """10.2-10.4 on one cell's sums: B, the exit plateau with thinned neighbours (Q21), the number plateau, and for
    every pair passing (a)-(c) its plateau score. Pure function of the sums (tests call it directly)."""
    n, s, n2, s2 = S[..., 0], S[..., 2], S[..., 3], S[..., 4]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n > 0, s / n, np.nan)
    B = b_mask(S)
    with np.errstate(invalid="ignore"):
        weak = (n >= THIN_MIN) & (s > 0) & (n2 > 0) & (s2 > 0)       # B(iii) and B(iv) only
    nf = np.nan_to_num(n)
    exnb = exit_neighbours(cfgs)
    ok_b = B.copy()
    for ci, nbs in enumerate(exnb):
        for j in nbs:
            nn = nf[:, j]
            ok_b[:, ci] &= np.where(nn >= MIN_SEL, B[:, j], np.where(nn >= THIN_MIN, weak[:, j], True))
    cnt_ex = np.zeros(n.shape, np.int64)
    cnt_ok = np.zeros(n.shape, np.int64)
    for q in cnb:
        ex = q >= 0
        cnt_ex += ex[:, None]
        cnt_ok += np.where(ex[:, None], B[np.maximum(q, 0)], False)
    ok_c = (cnt_ex == 0) | (2 * cnt_ok >= cnt_ex)
    abc = B & ok_b & ok_c
    val150 = np.where(nf >= MIN_SEL, np.nan_to_num(mean), 0.0)
    pairs = []
    for r, ci in np.argwhere(abc):
        vals = [mean[r, ci]]
        for j in exnb[ci]:
            if nf[r, j] >= THIN_MIN:
                vals.append(val150[r, j])
        for q in cnb:
            if q[r] >= 0:
                vals.append(val150[q[r], ci])
        pairs.append({"row": int(r), "ci": int(ci), "plateau": float(np.median(vals)), "n": int(n[r, ci]),
                      "win": float(S[r, ci, 1] / n[r, ci]), "mean": float(mean[r, ci]),
                      "mean_x2": float(s2[r, ci] / n2[r, ci])})
    return {"pairs_total": int(n.size), "with_150": int((nf >= MIN_SEL).sum()), "pass_B": int(B.sum()),
            "pass_b": int((B & ok_b).sum()), "pass_c": int((B & ok_c).sum()), "pass_abc": int(abc.sum()),
            "abc": pairs}


def plateau_order(pairs: list) -> list:
    return sorted(pairs, key=lambda p: (-p["plateau"], p["row"], p["ci"]))


def choose_pick(results: list) -> dict | None:
    """10.5: the eligible pair with the highest plateau score; ties to the higher SEL account mean monthly ln M at f*,
    then grid order (combo index, then tier, TP step, stop, fill: the exit config index)."""
    el = [r for r in results if r.get("eligible")]
    if not el:
        return None
    return sorted(el, key=lambda r: (-r["plateau"], -r["d"]["mean_ln"], r["row"], r["ci"]))[0]


# ------------------------------------------------------------------ controls (11), p_boot (12), BH, Holm (13)
def flip_groups(close_ms, side01) -> tuple:
    """Groups of candidates sharing a signal-bar close and an original side (11 a): (group of each, number)."""
    key = np.asarray(close_ms, np.int64) * 2 + np.asarray(side01, np.int64)
    uniq, grp = np.unique(key, return_inverse=True)
    return grp.astype(np.int64), int(len(uniq))


def flip_draw(G: int, period_name: str, pid: str, s) -> np.ndarray:
    """One fair coin per group: 0 keeps the group's side, 1 reverses it for every member."""
    return A.rng_for("a", period_name, pid, s).integers(0, 2, G).astype(np.int64)


def flip_sides(grp, side01, G: int, period_name: str, pid: str, s) -> np.ndarray:
    return np.asarray(side01, np.int64) ^ flip_draw(G, period_name, pid, s)[grp]


def flip_control(r_keep, r_rev, grp, G: int, period_name: str, pid: str, seeds) -> dict:
    """Per seed the trade-list mean r, win rate and trade count with the sides of ``flip_draw`` (11 a). r_keep / r_rev:
    each candidate's r on its original / reversed side (NaN where the trade-list rules do not take it). A seed's sums
    are the original sums plus its flipped groups' differences. 'obs' is the original mean in the same arithmetic."""
    rk, rv = np.asarray(r_keep, float), np.asarray(r_rev, float)
    ok_k, ok_v = np.isfinite(rk), np.isfinite(rv)
    sk = np.bincount(grp, np.where(ok_k, rk, 0.0), G)
    ck = np.bincount(grp, ok_k.astype(float), G)
    wk = np.bincount(grp, (ok_k & (np.nan_to_num(rk) > 0)).astype(float), G)
    sv = np.bincount(grp, np.where(ok_v, rv, 0.0), G)
    cv = np.bincount(grp, ok_v.astype(float), G)
    wv = np.bincount(grp, (ok_v & (np.nan_to_num(rv) > 0)).astype(float), G)
    dS, dC, dW = sv - sk, cv - ck, wv - wk
    S0, C0, W0 = sk.sum(), ck.sum(), wk.sum()
    seeds = list(seeds)
    mean, win, cnt = np.empty(len(seeds)), np.empty(len(seeds)), np.empty(len(seeds))
    chunk = max(1, min(len(seeds), 4_000_000 // max(G, 1)))
    for a in range(0, len(seeds), chunk):
        F = np.stack([flip_draw(G, period_name, pid, s) for s in seeds[a:a + chunk]]).astype(float)
        sm, c, w = S0 + F @ dS, C0 + F @ dC, W0 + F @ dW
        with np.errstate(invalid="ignore", divide="ignore"):
            mean[a:a + chunk] = np.where(c > 0, sm / np.maximum(c, 1), np.nan)
            win[a:a + chunk] = np.where(c > 0, w / np.maximum(c, 1), np.nan)
        cnt[a:a + chunk] = c
    with np.errstate(invalid="ignore", divide="ignore"):
        obs = S0 / C0 if C0 > 0 else float("nan")
    return {"mean": mean, "win": win, "n": cnt, "obs": float(obs)}


def p_seeds(seed_means: np.ndarray, obs: float) -> float:
    """11: (1 + seeds whose mean r is at least the pick's) / (seeds + 1)."""
    m = np.asarray(seed_means, float)
    return float((1 + int(np.sum(np.isfinite(m) & (m >= obs)))) / (len(m) + 1))


@njit(cache=True)
def _time_seed(lists, loff, set_of, mem, moff, take, rr, u, used, stamp, chosen):
    """One random-time seed (11 b): each cluster j (in time order) takes a bar from its list (loff[set_of[j]] ..),
    uniformly, never a bar an earlier cluster of this seed took (``used`` == stamp). Returns (sum r, trades, wins,
    dropped members, dropped clusters, 1 when the uniform stream ran out)."""
    pos = 0
    nu = len(u)
    s = 0.0
    n = 0
    w = 0
    dm = 0
    dc = 0
    for j in range(len(set_of)):
        a = loff[set_of[j]]
        b = loff[set_of[j] + 1]
        L = b - a
        g = -1
        tries = 0
        while L > 0:
            if pos >= nu:
                return s, n, w, dm, dc, 1
            k = a + int(u[pos] * L)
            pos += 1
            if k >= b:
                k = b - 1
            if used[lists[k]] != stamp:
                g = lists[k]
                break
            tries += 1
            if tries >= 32:
                cnt = 0
                for q in range(a, b):
                    if used[lists[q]] != stamp:
                        cnt += 1
                if cnt == 0:
                    break
                if pos >= nu:
                    return s, n, w, dm, dc, 1
                pick = int(u[pos] * cnt)
                pos += 1
                if pick >= cnt:
                    pick = cnt - 1
                for q in range(a, b):
                    if used[lists[q]] != stamp:
                        if pick == 0:
                            g = lists[q]
                            break
                        pick -= 1
                break
        chosen[j] = g
        if g < 0:
            dc += 1
            dm += moff[j + 1] - moff[j]
            continue
        used[g] = stamp
        for m in range(moff[j], moff[j + 1]):
            cs = mem[m]
            if take[cs, g]:
                x = rr[cs, g]
                s += x
                n += 1
                if x > 0:
                    w += 1
            else:
                dm += 1
    return s, n, w, dm, dc, 0


def time_setup(clusters: list, take: np.ndarray) -> dict:
    """Bar lists of the random-time control (11 b). ``clusters``: per cluster (time order) its members as row indices
    of ``take`` (coin x 2 + side). A member set's list = the bars where every member is takeable; when fewer than 20,
    the bars where at least one is (the others are dropped for that draw). Identical member sets share one list."""
    sets, set_of, lists, fallback = {}, [], [], []
    for mem in clusters:
        key = tuple(sorted(int(x) for x in mem))
        if key not in sets:
            sub = take[list(key)]
            strict = np.flatnonzero(sub.all(axis=0))
            if len(strict) >= TIME_MIN_BARS:
                lists.append(strict.astype(np.int64))
                fallback.append(False)
            else:
                lists.append(np.flatnonzero(sub.any(axis=0)).astype(np.int64))
                fallback.append(True)
            sets[key] = len(lists) - 1
        set_of.append(sets[key])
    loff = np.r_[0, np.cumsum([len(x) for x in lists])].astype(np.int64)
    mem = np.concatenate([np.asarray(m, np.int64) for m in clusters]) if clusters else np.zeros(0, np.int64)
    moff = np.r_[0, np.cumsum([len(m) for m in clusters])].astype(np.int64)
    set_of = np.asarray(set_of, np.int64)
    return {"lists": np.concatenate(lists) if lists else np.zeros(0, np.int64), "loff": loff, "set_of": set_of,
            "mem": mem, "moff": moff, "fallback_clusters": int(sum(fallback[k] for k in set_of)),
            "fallback_sets": int(sum(fallback))}


def time_control(setup: dict, take: np.ndarray, rr: np.ndarray, period_name: str, pid: str, seeds,
                 keep_chosen: int = 0) -> dict:
    """Per seed the trade-list mean r, win rate and trade count of the moved clusters (11 b); the bars drawn by the
    first ``keep_chosen`` seeds (for their accounts)."""
    seeds = list(seeds)
    C = len(setup["set_of"])
    G = take.shape[1]
    used = np.full(G, -1, np.int64)
    out = {k: np.full(len(seeds), np.nan) for k in ("mean", "win", "n", "dropped_members", "dropped_clusters")}
    chosen_keep = np.full((min(keep_chosen, len(seeds)), C), -1, np.int64)
    chosen = np.empty(C, np.int64)
    rr0 = np.where(take, np.nan_to_num(rr), 0.0)
    stamp_ = 0                                     # a fresh stamp per call: ``used`` never needs clearing
    for i, s in enumerate(seeds):
        m = max(64, 4 * C)
        while True:
            u = A.rng_for("b", period_name, pid, s).random(m)     # a longer stream keeps the same first numbers
            sm, n, w, dm, dc, more = _time_seed(setup["lists"], setup["loff"], setup["set_of"], setup["mem"],
                                                 setup["moff"], take, rr0, u, used, np.int64(stamp_), chosen)
            stamp_ += 1
            if not more:
                break
            m *= 4
        out["n"][i], out["dropped_members"][i], out["dropped_clusters"][i] = n, dm, dc
        if n > 0:
            out["mean"][i], out["win"][i] = sm / n, w / n
        if i < len(chosen_keep):
            chosen_keep[i] = chosen
    out["chosen"] = chosen_keep
    return out


def p_boot(close_ms, r, period_name: str, pid: str, n_boot: int | None = None) -> float:
    """12: one-sided week-block bootstrap p of mean r > 0; trades grouped by the UTC week (Monday) of their
    signal-bar close; (1 + resamples with mean <= 0) / (n + 1)."""
    n_boot = N_PBOOT if n_boot is None else n_boot
    x = np.asarray(r, float)
    if not len(x):
        return 1.0
    wk = (np.asarray(close_ms, np.int64) - W.MONDAY0) // W.WEEK
    _w, inv = np.unique(wk, return_inverse=True)
    nw = int(inv.max()) + 1
    s, c = np.bincount(inv, x, nw), np.bincount(inv, None, nw)
    rng = A.rng_for("boot", period_name, pid, "boot")
    bad, done = 0, 0
    while done < n_boot:
        m = min(max(1, 2_000_000 // nw), n_boot - done)
        pick = rng.integers(0, nw, size=(m, nw))
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = s[pick].sum(1) / c[pick].sum(1)
        bad += int((~(mean > 0)).sum())
        done += m
    return float((1 + bad) / (n_boot + 1))


def bh(pvals: list, q: float = BH_Q) -> list:
    return R.bh(pvals, q)                 # research/fullgrid/run.bh (Benjamini-Hochberg step-up), read-only


def holm(pvals: list, alpha: float = HOLM_ALPHA) -> list:
    """Holm step-down at ``alpha`` over the p-values that are not None."""
    ix = [i for i, p in enumerate(pvals) if p is not None]
    m = len(ix)
    out = [False] * len(pvals)
    for r, i in enumerate(sorted(ix, key=lambda i: pvals[i])):
        if pvals[i] <= alpha / (m - r):
            out[i] = True
        else:
            break
    return out


# ------------------------------------------------------------------ one pair on one period (both stages)
def pair_trades(T, rows, sides, cfg: dict, seg: int) -> dict:
    """A pair's trade list on one coin (8.1), the reversed sides' trade list (control a) and its account candidates."""
    x = W.trade_list(T, rows, sides, cfg)
    xv = W.trade_list(T, rows, 1 - np.asarray(sides, np.int64), cfg)
    has = x["skip"] != 4
    return {"close": T.close[rows][has], "coin": np.full(int(has.sum()), seg, np.int64), "side": sides[has],
            "r": x["r"][has], "r2": x["r2"][has], "oneR": x["oneR"][has], "rv": xv["r"][has], "skip": x["skip"][has],
            "kind": x["kind"][has], "entry_ms": x["entry_ms"][has], "exit_ms": x["exit_ms"][has],
            "acct": acct_pieces(T, rows, sides, x, cfg, seg), "acct_all": acct_pieces(T, rows, sides, x, cfg, seg,
                                                                                      flipped_ok=True)}


def cat_trades(parts: list) -> dict:
    keys = ("close", "coin", "side", "r", "r2", "oneR", "rv", "skip", "kind", "entry_ms", "exit_ms")
    if not parts:
        return {k: np.zeros(0) for k in keys} | {"acct": [], "acct_all": []}
    out = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    out["acct"] = [p["acct"] for p in parts]
    out["acct_all"] = [p["acct_all"] for p in parts]
    return out


def list_stats(tr: dict) -> dict:
    ok = tr["skip"] == 0
    st = A.trade_stats(tr["r"][ok], tr["r2"][ok], tr["oneR"][ok])
    st["liq"] = int((tr["kind"][ok] == W.X_LIQ).sum())
    st["coin_end"] = int((tr["kind"][ok] == W.X_COIN_END).sum())
    st["candidates"] = int(len(tr["skip"]))
    for code, nm in W.SKIP_NAMES.items():
        if code:
            st[f"skip_{nm.replace(' ', '_')}"] = int((tr["skip"] == code).sum())
    return st


def account_summary(res: dict) -> dict:
    mo = A.monthly(res)
    return {"f": res["f"], "trades": res["n"], "final_x": res["final"] / res["w0"], "dd": res["dd"],
            "dd_real": res["dd_real"], "worst_loss": res["worst_loss"], "bust": res["bust"],
            "open_at_end": res["open_at_end"], "cut": res["n_cut"], "counts": res["counts"], "monthly": mo}


def size_pair(mk: Market, cand: dict, cfg: dict, tf: str, pid: str, period_name: str = "SEL") -> dict:
    per = PER(period_name)
    draws = A.boot_draws(per, pid, period_name, N_F95)
    return A.sizes(lambda f: A.account(mk.store, cand, mk.coins, cfg, f, per), A.CAP[tf], float(cfg["L"]), per, draws)


def eval_pairs(kind: str, name: str, tf: str, pairs: list) -> list:
    """(d) and (e) of 10.3 for pairs of one cell on SEL: per pair its trade list from the SEL tables (checked against
    the stored sums), the one-at-a-time account sized by 8.4 (f_path, f*) and the coin-flip check of seeds 1-200."""
    mk = CTX["SEL"]
    use_frames(CTX["dirs"]["frames_SEL"])
    cfgs = exit_configs()
    combos = cell_grid(kind, name)[2]
    by_row: dict = {}
    for p in pairs:
        by_row.setdefault(p["row"], []).append(p["ci"])
    parts = {(p["row"], p["ci"]): [] for p in pairs}
    failed = set()
    for c, sym in enumerate(mk.syms):
        T = load_tables(table_dir(CTX["dirs"]["tables_SEL"], sym, tf))
        if T is None:
            continue
        for row, cis in by_row.items():
            if row in failed:
                continue
            try:
                lo, sh = raw_signals(kind, name, sym, tf, combos[row])
            except Exception:  # noqa: BLE001
                failed.add(row)
                continue
            rows, sides = cand_rows(T, lo, sh, weekend_rule=True)
            for ci in cis:
                parts[(row, ci)].append(pair_trades(T, rows, sides, cfgs[ci], c))
        del T
    out = []
    for p in pairs:
        cfg = cfgs[p["ci"]]
        pid = pick_id(name, tf, p["row"], cfg)
        res = dict(p, id=pid)
        if p["row"] in failed:
            res.update(eligible=False, d={"ok": False, "mean_ln": -math.inf}, e={"ok": False})
            out.append(res)
            continue
        tr = cat_trades(parts[(p["row"], p["ci"])])
        st = list_stats(tr)
        res["list_check"] = abs(st["mean"] - p["mean"]) if st["n"] else None
        if st["n"] != p["n"] or (st["n"] and abs(st["mean"] - p["mean"]) > 1e-9):
            raise RuntimeError(f"{pid}: trade list ({st['n']}, {st['mean']}) differs from the stored sums "
                               f"({p['n']}, {p['mean']})")
        cand = candidates_of(tr["acct"])
        sz = size_pair(mk, cand, cfg, tf, pid)
        fs = sz["f_star"]
        mean_ln = fs["monthly"]["mean_ln"] if fs["monthly"] else -math.inf
        d_ok = bool(fs["f"] > 0 and fs["trades"] >= ACCT_MIN and mean_ln > 0)
        grp, G = flip_groups(tr["close"], tr["side"])
        fl = flip_control(tr["r"], tr["rv"], grp, G, "SEL", pid, range(1, N_FLIP_SEL + 1))
        q95 = float(np.nanquantile(fl["mean"], Q_FLIP)) if np.isfinite(fl["mean"]).any() else math.inf
        e_ok = bool(np.isfinite(q95) and fl["obs"] > q95)
        res.update(d={"ok": d_ok, "f_star": fs["f"], "f_path": sz["f_path"]["f"], "f_realized": sz["f_realized"],
                      "trades": fs["trades"], "mean_ln": mean_ln, "sizes": sz},
                   e={"ok": e_ok, "obs": fl["obs"], "q95": q95, "seed_mean": float(np.nanmean(fl["mean"]))},
                   eligible=bool(d_ok and e_ok), list_stats=st)
        out.append(res)
    return out


def _elig_job(args) -> str:
    work, kind, name, tf, k, pairs, mode = args
    path = os.path.join(work, "elig", f"{cell_key(kind, name, tf)}_{k:04d}.json")
    if os.path.exists(path):
        return ""
    t0 = time.time()
    try:
        if mode == "all":
            res = eval_pairs(kind, name, tf, pairs)
        else:                              # lazy: plateau groups in order until one holds an eligible pair
            res = []
            order = plateau_order(pairs)
            i = 0
            while i < len(order):
                j = i
                while j < len(order) and order[j]["plateau"] == order[i]["plateau"]:
                    j += 1
                res += eval_pairs(kind, name, tf, order[i:j])
                if any(r["eligible"] for r in res[-(j - i):]):
                    break
                i = j
        disk_check(path)
        write_json(path, {"results": res, "seconds": round(time.time() - t0, 1), "mode": mode})
        return f"{kind} {name} {tf} part {k}: {len(res)} pairs, {time.time() - t0:.0f}s"
    except Exception:  # noqa: BLE001
        return f"ERROR {kind} {name} {tf} part {k}: " + traceback.format_exc()[-1500:]


def elig_tasks(work: str, cell_rows: list, mode: str) -> list:
    tasks = []
    for (kind, name, tf), pr in cell_rows:
        if not pr["abc"]:
            continue
        if mode == "lazy":
            tasks.append((work, kind, name, tf, 0, pr["abc"], mode))
            continue
        rows = sorted({p["row"] for p in pr["abc"]})
        for k, a in enumerate(range(0, len(rows), ELIG_CHUNK)):
            keep = set(rows[a:a + ELIG_CHUNK])
            tasks.append((work, kind, name, tf, k, [p for p in pr["abc"] if p["row"] in keep], mode))
    return sorted(tasks, key=lambda t: -len(t[5]) * GRID_WEIGHT[t[3]])


def elig_path(t: tuple) -> str:
    work, kind, name, tf, k = t[:5]
    return os.path.join(work, "elig", f"{cell_key(kind, name, tf)}_{k:04d}.json")


# ------------------------------------------------------------------ select (9, 10)
def kits_of(args, with_test: bool = False) -> dict:
    man = load_json(rpath(MANIFEST_SEL_REL))
    kits = {"kit": args.kit, "man_sel": man}
    if with_test:
        kits["kit_test"] = args.kit_test
        kits["man_test"] = load_json(rpath(MANIFEST_TEST_REL))
    return kits


def work_dir(args, tag: str) -> str:
    if not getattr(args, "work", None):
        raise SystemExit("--work DIR needed (outside the repository)")
    path = os.path.abspath(os.path.join(args.work, tag))
    if os.path.commonpath([path, os.path.abspath(ROOT)]) == os.path.abspath(ROOT):
        raise SystemExit("--work must be outside the repository")
    os.makedirs(path, exist_ok=True)
    return path


def check_kit_manifest(kits: dict) -> None:
    man = kits["man_sel"]
    if list(man.get("months", [])) != list(D.KIT_SEL):
        raise SystemExit(f"{MANIFEST_SEL_REL} is not the practice kit {D.KIT_SEL}")
    missing = [s for s in SYMBOLS if s not in man["coins"]]
    if missing:
        raise SystemExit(f"{MANIFEST_SEL_REL} lacks {missing}")


def market(period_name: str, kits: dict, syms=None) -> Market:
    t0 = time.time()
    mk = Market(period_name, lambda s: load_period_arrays(s, period_name, kits), syms or SYMBOLS)
    log(f"[{period_name}] market: {len(mk.syms)} coins, {mk.minutes():,} minutes, {time.time() - t0:.0f}s")
    return mk


def cmd_select(args) -> int:
    pin = check_pin("select")
    t0 = time.time()
    kits = kits_of(args)
    check_kit_manifest(kits)
    work = work_dir(args, f"select_{pin['pin_sha256'][:16]}")
    disk_check(work)
    procs = max(1, args.procs)
    cells = cells_all()
    tfs = sorted({c[2] for c in cells}, key=TFS.index)
    dirs = {"frames_SEL": os.path.join(work, "frames"), "tables_SEL": os.path.join(work, "tables")}
    CTX["dirs"] = dirs
    frames_stage("SEL", kits, dirs["frames_SEL"], tfs, procs)
    CTX["SEL"] = market("SEL", kits)
    tables_stage("SEL", dirs["frames_SEL"], dirs["tables_SEL"], tfs, procs)
    missing = grid_stage(work, cells, procs)
    if missing:
        raise SystemExit(f"[grid] {missing} tasks missing (see the ERROR lines); run select again to resume")
    cfgs = exit_configs()
    cell_rows = []
    for kind, name, tf in cells:
        S, fails, metas = cell_sums(work, kind, name, tf)
        pr = cell_pairs(S, combo_neighbours(kind, name), cfgs)
        pr.update(combos=int(S.shape[0]), failed_combos=len(fails),
                  with_weekends_pass_B=int(sum(m["with_weekends_pass_B"] for m in metas)),
                  candidates_weekday=int(sum(m["candidates_weekday"] for m in metas)),
                  candidates_weekend_dropped=int(sum(m["candidates_weekend_dropped"] for m in metas)))
        cell_rows.append(((kind, name, tf), pr))
    log(f"[pairs] {sum(len(p['abc']) for _c, p in cell_rows)} pairs pass (a)-(c) in "
        f"{sum(1 for _c, p in cell_rows if p['abc'])} cells")
    tasks = elig_tasks(work, cell_rows, args.eligibility)
    todo = [t for t in tasks if not os.path.exists(elig_path(t))]
    for msg in R.run_pool(_elig_job, todo, procs, "eligibility", done=lambda t: os.path.exists(elig_path(t))):
        if msg:
            log(f"[eligibility] {msg}")
    if [t for t in tasks if not os.path.exists(elig_path(t))]:
        raise SystemExit("[eligibility] tasks missing (see the ERROR lines); run select again to resume")
    res_of: dict = {}
    for t in tasks:
        res_of.setdefault((t[1], t[2], t[3]), []).extend(load_json(elig_path(t))["results"])
    doc, picks, priv_rows, priv_picks = finish_select(cell_rows, res_of, args.eligibility, cfgs)
    ds_ids = {p["id"] for p in picks if is_ds(p)}
    priv_sha = write_private(args, "select_private.json", {"cells": priv_rows})
    picks_priv_sha = write_private(args, "picks_private.json", {"picks": priv_picks})
    st = stamp(pin)
    sel = {"stamp": st, "what": "PREREG_HIWR 10: per cell the pairs passing each test and the pick (SEL only)",
           "period": {"SEL": [iso(x) for x in PER("SEL")]}, "rule": rule_text(), "cells": doc,
           "picks": [p["id"] for p in picks], "eligibility_mode": args.eligibility,
           "data": {"coins": CTX["SEL"].syms, "minutes": CTX["SEL"].minutes()},
           "private_sha256": priv_sha, "seconds": round(time.time() - t0, 1)}
    write_public(out_path("select.json"), sel, ds_ids)
    write_public(rpath(PICKS_REL), {"stamp": st, "picks": picks, "private_sha256": picks_priv_sha,
                                    "what": "PREREG_HIWR 10.6: each pick's full definition and its SEL f* "
                                            "(DeepSeek: f* in the private file, D11)"}, ds_ids)
    append_pin(PICKS_REL)
    log(f"select done: {len(picks)} picks from {len(cells)} cells in {time.time() - t0:.0f}s")
    return 0


def rule_text() -> dict:
    return {"B": "n >= 150, win rate >= 70.0%, mean r > 0, cost-x2 mean r > 0 (10.2)",
            "b": "every exit neighbour passes B; 50-149 trades: mean > 0 and cost-x2 mean > 0; < 50: not existing (Q21)",
            "c": "at least half of the existing number neighbours pass B",
            "d": "f* > 0; at f* the SEL account takes >= 100 trades and its mean monthly ln M > 0",
            "e": "SEL mean r above the 95th percentile of coin-flip seeds 1-200",
            "pick": "highest plateau score; ties: higher SEL mean monthly ln M at f*, then grid order; one per cell"}


def pick_record(kind, name, tf, r: dict, cfgs: list) -> dict:
    cfg = cfgs[r["ci"]]
    combo = cell_grid(kind, name)[2][r["row"]]
    return {"id": r["id"], "kind": kind, "name": name, "tf": tf, "row": int(r["row"]),
            "combo": {k: (list(v) if isinstance(v, tuple) else v) for k, v in combo.items()},
            "exit": {k: cfg[k] for k in ("Li", "L", "step", "roe", "k", "stop", "fill", "fill_name", "t", "reading")},
            "ci": int(r["ci"]), "cap": A.CAP[tf]}


def finish_select(cell_rows: list, res_of: dict, mode: str, cfgs: list) -> tuple:
    doc, picks, priv_rows, priv_picks = [], [], [], {}
    for (kind, name, tf), pr in cell_rows:
        res = res_of.get((kind, name, tf), [])
        pk = choose_pick(res)
        row = {"kind": kind, "name": name, "tf": tf, "combos": pr["combos"], "failed_combos": pr["failed_combos"],
               "pairs": pr["pairs_total"], "with_150_trades": pr["with_150"], "pass_B": pr["pass_B"],
               "pass_b": pr["pass_b"], "pass_c": pr["pass_c"], "pass_abc": pr["pass_abc"],
               "evaluated_d_e": len(res), "pass_d": sum(1 for r in res if r["d"]["ok"]),
               "pass_e": sum(1 for r in res if r["e"]["ok"]), "eligible": sum(1 for r in res if r["eligible"]),
               "counts_partial": bool(mode == "lazy" and len(res) < pr["pass_abc"]),
               "with_weekends_pass_B": pr["with_weekends_pass_B"],
               "candidates_weekday": pr["candidates_weekday"],
               "candidates_weekend_dropped": pr["candidates_weekend_dropped"],
               "pick": pk["id"] if pk else "none"}
        full = dict(row, abc=pr["abc"], results=[{k: v for k, v in r.items() if k != "d"} | {
            "d": {k: v for k, v in r["d"].items() if k != "sizes"}} for r in res])
        if pk:
            rec = pick_record(kind, name, tf, pk, cfgs)
            sz = pk["d"]["sizes"]
            nums = {"plateau": pk["plateau"], "n": pk["n"], "win": pk["win"], "mean": pk["mean"],
                    "mean_x2": pk["mean_x2"], "mean_R": pk["list_stats"].get("mean_R"),
                    "f_star": sz["f_star"]["f"], "f_path": sz["f_path"]["f"], "f_realized": sz["f_realized"],
                    "margin_pct_f_star": sz["f_star"]["margin_pct"], "margin_pct_f_path": sz["f_path"]["margin_pct"],
                    "boot_q95_f_star": sz["f_star"]["boot_q95"], "boot_share_over_cap_f_star":
                        sz["f_star"]["boot_share_over_cap"], "boot_share_over_cap_f_path":
                        sz["f_path"]["boot_share_over_cap"], "account_trades_f_star": sz["f_star"]["trades"],
                    "monthly_f_star": sz["f_star"]["monthly"], "monthly_f_path": sz["f_path"]["monthly"],
                    "dd_f_star": sz["f_star"]["dd"], "flip_q95": pk["e"]["q95"], "flip_seed_mean": pk["e"]["seed_mean"]}
            priv_picks[rec["id"]] = dict(rec, sel=nums)
            full["pick_numbers"] = nums
            if is_ds(rec):
                rec.update(sel="private (D11)", f_star=None, private=True,
                           sel_counts={"n": pk["n"], "win": pk["win"], "account_trades_f_star":
                                       sz["f_star"]["trades"]})
                row["pick_counts"] = {"n": pk["n"], "win": pk["win"]}
            else:
                rec.update(sel=nums, f_star=sz["f_star"]["f"], private=False)
                row["pick_numbers"] = nums
            picks.append(rec)
        priv_rows.append(full)
        doc.append(row)
    return doc, picks, priv_rows, priv_picks


def load_picks(args) -> list:
    """picks.json with each pick's f* (DeepSeek f* from the private file, whose sha256 picks.json holds)."""
    doc = load_json(rpath(PICKS_REL))
    picks = doc["picks"]
    if any(p.get("private") for p in picks):
        path = os.path.join(private_dir(args), "picks_private.json")
        if not os.path.exists(path) or sha256_file(path) != doc["private_sha256"]:
            raise PinError(f"{path} is missing or not the file picks.json names (D11 figures of the DeepSeek picks)")
        priv = load_json(path)["picks"]
        picks = [dict(p, f_star=priv[p["id"]]["sel"]["f_star"]) if p.get("private") else p for p in picks]
    return picks


# ------------------------------------------------------------------ test (11, 12, 13)
def fetch_test_kit(d: str, syms: list) -> None:
    """The confirm kit: 2024-01 .. 2026-09 monthly 1m klines, mark klines and funding (data.py), then the build."""
    D.download(d, *D.KIT_TEST, symbols=tuple(syms))
    D.build(d, *D.KIT_TEST, symbols=tuple(syms))


def test_symbols(man_sel: dict) -> list:
    """Coins whose practice-kit data did not end inside the practice kit (TOMO ended 2023-11)."""
    return [s for s in SYMBOLS if s in man_sel["coins"] and not man_sel["coins"][s].get("ended")]


def ensure_test_kit(d: str, picks_sha: str, pin: dict, man_sel: dict) -> None:
    """10.6: TEST data is downloaded only here, after the picks line is in the pin. The kit folder gets a marker with the
    picks' hash first; a folder that already holds files without that marker is refused."""
    mark = os.path.join(d, TEST_KIT_MARK)
    if os.path.exists(mark):
        if load_json(mark).get("picks_sha256") != picks_sha:
            raise PinError(f"{d} was made for other picks")
    else:
        if os.path.isdir(d) and any(os.scandir(d)):
            raise PinError(f"{d} holds files from before the picks were hashed: refused (10.6)")
        os.makedirs(d, exist_ok=True)
        write_json(mark, {"picks_sha256": picks_sha, "pin_sha256": pin["pin_sha256"], "started_utc": now_utc()})
    if not os.path.exists(os.path.join(d, "build.json")):
        disk_check(d)
        fetch_test_kit(d, test_symbols(man_sel))


def test_manifest(d: str) -> dict:
    m = D.manifest(d)
    for s, v in m["coins"].items():
        a = D.load(d, s)
        got = D.content_sha(a)
        if got != v["content_sha256"]:
            raise D.DataMismatch(f"{s}: build.json hash differs from the file")
    return {"what": "PREREG_HIWR 3: the confirm kit's identity (2024-01 .. 2026-09)", "written_utc": now_utc(),
            "build_sha256": sha256_file(os.path.join(d, "build.json")), **m}


def _test_job(args) -> tuple:
    pick, = args
    try:
        return pick["id"], test_pick(pick), ""
    except Exception:  # noqa: BLE001
        return pick["id"], None, traceback.format_exc()[-2000:]


def test_pick(pick: dict) -> dict:
    """One pick on TEST, once (12): its trade list (T0, T1, T3, T4), the account at its SEL f* (T2), both controls with
    N_SEEDS seeds (T5; seeds 1..1,000 also run the account), p_boot and p = max(p_boot, p_a, p_b) for T6."""
    mk = CTX["TEST"]
    per = PER("TEST")
    use_frames(CTX["dirs"]["frames_TEST"])
    cfgs = exit_configs()
    cfg = cfgs[pick["ci"]]
    tf = pick["tf"]
    combo = cell_grid(pick["kind"], pick["name"])[2][pick["row"]]
    parts, grids, coin_rows = [], [], []
    for c, sym in enumerate(mk.syms):
        T = load_tables(table_dir(CTX["dirs"]["tables_TEST"], sym, tf))
        if T is None:
            coin_rows.append(None)
            continue
        lo, sh = raw_signals(pick["kind"], pick["name"], sym, tf, combo)
        rows, sides = cand_rows(T, lo, sh, weekend_rule=True)
        parts.append(pair_trades(T, rows, sides, cfg, c))
        allrows = np.flatnonzero(~T.weekend & (T.ent >= 0)).astype(np.int64)
        xl = W.trade_list(T, allrows, np.zeros(len(allrows), np.int64), cfg)
        xs = W.trade_list(T, allrows, np.ones(len(allrows), np.int64), cfg)
        grids.append((c, T.close[allrows], xl, xs))
        coin_rows.append({"close": T.close[allrows], "rows": allrows, "ent": T.ent[allrows], "atr": T.atr[allrows],
                          "p0": T.p0[allrows], "ent_ms": T.ent_ms[allrows]})
        del T
    tr = cat_trades(parts)
    st = list_stats(tr)
    pid = pick["id"]
    f = float(pick["f_star"])
    cand = candidates_of(tr["acct"])
    acc = A.account(mk.store, cand, mk.coins, cfg, f, per)
    cap = A.CAP[tf]
    ok = tr["skip"] == 0
    # control (a): coin-flip sides, one coin per (signal-bar close, original side)
    grp, G = flip_groups(tr["close"], tr["side"])
    fl = flip_control(tr["r"], tr["rv"], grp, G, "TEST", pid, range(1, N_SEEDS + 1))
    p_a = p_seeds(fl["mean"], fl["obs"])
    acc_a = []
    allc = cat_pieces(tr["acct_all"])
    for s in range(1, min(N_ACCT_SEEDS, N_SEEDS) + 1):
        sides = flip_sides(grp, tr["side"], G, "TEST", pid, s)
        acc_a.append(control_account(mk, allc, sides, cfg, f, per))
    # control (b): random times, whole clusters
    take, rr, gclose = time_grid(grids, len(mk.syms))
    clusters, cl_close = time_clusters(tr["close"][ok], tr["coin"][ok], tr["side"][ok])
    setup = time_setup(clusters, take)
    tc = time_control(setup, take, rr, "TEST", pid, range(1, N_SEEDS + 1), keep_chosen=N_ACCT_SEEDS)
    obs = st["mean"]
    p_b = p_seeds(tc["mean"], obs)
    acc_b = []
    for i in range(len(tc["chosen"])):
        acc_b.append(time_account(mk, clusters, tc["chosen"][i], gclose, take, coin_rows, cfg, f, per))
    pb = p_boot(tr["close"][ok], tr["r"][ok], "TEST", pid)
    t0_ok = st["n"] >= MIN_TEST
    checks = {"T0": bool(t0_ok), "T1": bool(st["n"] and st["win"] >= A.MIN_WIN),
              "T2": bool(acc["dd"] <= cap and not acc["bust"]), "T3": bool(st["n"] and st["mean"] > 0),
              "T4": bool(st["n"] and st.get("mean_x2", -1) > 0), "T5": bool(p_a < T5_ALPHA and p_b < T5_ALPHA)}
    p = float(max(pb, p_a, p_b)) if t0_ok else 1.0
    return {"id": pid, "kind": pick["kind"], "name": pick["name"], "tf": tf, "test": st,
            "account": account_summary(acc), "cap": cap,
            "controls": {"a": control_summary(fl["mean"], fl["win"], fl["n"], p_a, acc_a, cap) | {
                         "groups": G, "obs": fl["obs"]},
                         "b": control_summary(tc["mean"], tc["win"], tc["n"], p_b, acc_b, cap) | {
                         "clusters": len(clusters), "fallback_clusters": setup["fallback_clusters"],
                         "dropped_members_total": float(np.nansum(tc["dropped_members"])),
                         "dropped_clusters_total": float(np.nansum(tc["dropped_clusters"])),
                         "bars": int(take.shape[1])}},
            "p_boot": pb, "p_a": p_a, "p_b": p_b, "p": p, "checks": checks,
            "seed_means": {"a": float(np.nanmean(fl["mean"])), "b": float(np.nanmean(tc["mean"]))}}


def cat_pieces(pieces: list) -> dict:
    keys = ("coin", "e", "side", "D", "atr", "fill")
    if not pieces:
        return {k: np.zeros(0) for k in keys}
    return {k: np.concatenate([p[k] for p in pieces]) for k in keys}


def control_account(mk: Market, allc: dict, sides01: np.ndarray, cfg: dict, f: float, per: tuple) -> dict:
    """The account at f* of one coin-flip seed: the pick's candidates (every one with an entry, in the trade list's
    order) on the seed's sides; the account decides which are taken (8.2)."""
    sides01 = np.asarray(sides01, np.int64)
    if len(sides01) != len(allc["coin"]):
        raise RuntimeError("control account: candidate lists differ")
    side = np.where(sides01 == 0, 1, -1)
    c = A.candidates(allc["coin"], allc["coin"], allc["e"], side, allc["D"], allc["atr"], allc["fill"])
    res = A.account(mk.store, c, mk.coins, cfg, f, per)
    return {"dd": res["dd"], "bust": res["bust"], "final_x": res["final"] / res["w0"], "trades": res["n"],
            "mean_ln": A.monthly(res)["mean_ln"]}


def control_summary(means, wins, ns, p: float, accs: list, cap: float) -> dict:
    m = np.asarray(means, float)
    out = {"p": p, "seeds": int(len(m)), "seed_mean": _f(np.nanmean(m)) if np.isfinite(m).any() else None,
           "seed_q95": _f(np.nanquantile(m, 0.95)) if np.isfinite(m).any() else None,
           "seed_win_mean": _f(np.nanmean(wins)) if np.isfinite(wins).any() else None,
           "seeds_without_trades": int((~np.isfinite(m)).sum()), "seed_trades_median": _f(np.nanmedian(ns))}
    if accs:
        dd = np.array([a["dd"] for a in accs])
        bust = np.array([a["bust"] for a in accs])
        out["accounts"] = {"seeds": len(accs), "share_within_cap": float(((dd <= cap) & ~bust).mean()),
                           "share_bust": float(bust.mean()),
                           "median_final_x": float(np.median([a["final_x"] for a in accs])),
                           "median_mean_ln": float(np.median([a["mean_ln"] for a in accs]))}
    return out


def time_grid(grids: list, ncoins: int) -> tuple:
    """(takeable (coin x 2 + side, bars), r, bar closes) over the union of the coins' weekday bars of the period."""
    closes = np.unique(np.concatenate([g[1] for g in grids])) if grids else np.zeros(0, np.int64)
    take = np.zeros((2 * ncoins, len(closes)), bool)
    rr = np.full((2 * ncoins, len(closes)), np.nan)
    for c, cl, xl, xs in grids:
        pos = np.searchsorted(closes, cl)
        for s, x in ((0, xl), (1, xs)):
            ok = x["skip"] == 0
            take[2 * c + s, pos[ok]] = True
            rr[2 * c + s, pos[ok]] = x["r"][ok]
    return take, rr, closes


def time_clusters(close_ms, coin, side01) -> tuple:
    """11 (b): the pick's trades grouped by signal-bar close; a cluster is its set of (coin, side) as coin x 2 + side.
    Time order."""
    close_ms = np.asarray(close_ms, np.int64)
    order = np.argsort(close_ms, kind="stable")
    out, closes = [], []
    for t in np.unique(close_ms):
        m = order[close_ms[order] == t]
        out.append(sorted({int(2 * coin[i] + side01[i]) for i in m}))
        closes.append(int(t))
    return out, np.asarray(closes, np.int64)


def time_account(mk: Market, clusters: list, chosen: np.ndarray, gclose: np.ndarray, take: np.ndarray,
                 coin_rows: list, cfg: dict, f: float, per: tuple) -> dict:
    """The account at f* of one random-time seed: each cluster's takeable members at its drawn bar."""
    cs, es, sd, Ds, atrs, fills = [], [], [], [], [], []
    fam, v = W.STOPS[cfg["k"]]
    for mem, g in zip(clusters, chosen):
        if g < 0:
            continue
        for m in mem:
            if not take[m, g]:
                continue
            c, s = divmod(int(m), 2)
            info = coin_rows[c]
            j = int(np.searchsorted(info["close"], gclose[g]))
            cs.append(c)
            es.append(info["ent"][j])
            sd.append(1 if s == 0 else -1)
            Ds.append(v * (info["atr"][j] if fam == "atr" else info["p0"][j]))
            atrs.append(info["atr"][j])
            fills.append(info["ent_ms"][j])
    c = A.candidates(np.asarray(cs, np.int64), np.asarray(cs, np.int64), np.asarray(es, np.int64),
                     np.asarray(sd, np.int64), np.asarray(Ds, float), np.asarray(atrs, float),
                     np.asarray(fills, np.int64))
    res = A.account(mk.store, c, mk.coins, cfg, f, per)
    return {"dd": res["dd"], "bust": res["bust"], "final_x": res["final"] / res["w0"], "trades": res["n"],
            "mean_ln": A.monthly(res)["mean_ln"]}


def verdict(blocks: list) -> dict:
    """T6 and PASS over all picks (one family, core and DeepSeek): BH at q = 0.10 on p = max(p_boot, p_a, p_b), p = 1
    for a pick failing T0. 참고 (16): T0-T4 hold and the mean r is above both controls' seed means."""
    pv = [b["p"] if b["checks"]["T0"] else 1.0 for b in blocks]
    sig = bh(pv, BH_Q)
    passing, ref = [], []
    for b, s in zip(blocks, sig):
        c = b["checks"]
        c["T6"] = bool(s)
        c["PASS"] = bool(all(c[k] for k in ("T0", "T1", "T2", "T3", "T4", "T5", "T6")))
        sm = b["seed_means"]
        c["참고"] = bool(not c["PASS"] and all(c[k] for k in ("T0", "T1", "T2", "T3", "T4"))
                       and b["test"]["mean"] > max(x if x is not None and np.isfinite(x) else -math.inf
                                                   for x in (sm["a"], sm["b"])))
        (passing if c["PASS"] else ref if c["참고"] else []).append(b["id"])
    return {"passing": passing, "reference": ref, "picks": len(blocks), "bh_q": BH_Q,
            "family": "all picks (core and DeepSeek), p = max(p_boot, p_a, p_b); p = 1 when T0 fails"}


def redact_block(b: dict) -> dict:
    """D11: a DeepSeek pick's public block (counts, win rates, labels)."""
    st = b["test"]
    return {"id": b["id"], "kind": b["kind"], "name": b["name"], "tf": b["tf"], "checks": b["checks"],
            "test": {"n": st["n"], "win": st["win"], "liq": st["liq"], "candidates": st["candidates"]},
            "account": {"trades": b["account"]["trades"], "bust": b["account"]["bust"]},
            "note": "DeepSeek pick: figures in the private file (D11)"}


def ledger_external(extra_path: str | None = None, hunt_private: str | None = None) -> list:
    """The other test-period hypotheses of the program (13): the hunt's v1 and wide test.json where they exist (the
    hunt's DeepSeek p-values from its private file when given), plus rows of ``--ledger-extra`` (a JSON list of
    {id, source, p, deepseek}). A row without a p is listed as missing."""
    rows = []
    priv = load_json(hunt_private) if hunt_private and os.path.exists(hunt_private) else None
    for src, rel in HUNT_TESTS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            rows.append({"id": f"{src} (not run yet)", "source": rel, "p": None, "deepseek": False,
                         "status": "file missing"})
            continue
        doc = load_json(p)
        if "pick" in doc and "result" in doc:
            rows.append({"id": doc["pick"].get("id", src), "source": rel, "deepseek": False,
                         "p": (doc["result"].get("checks") or {}).get("p")})
        for pid, blk in (doc.get("results") or {}).items():
            chk = blk.get("checks") or {}
            pp = chk.get("p")
            ds = "p" not in chk                # the hunt's public file leaves the p of a DeepSeek pick out (D11)
            if pp is None and priv is not None:
                pp = (((priv.get("results") or {}).get(pid) or {}).get("checks") or {}).get("p")
            rows.append({"id": pid, "source": rel, "p": pp, "deepseek": bool(ds)})
    if extra_path:
        for r in load_json(extra_path):
            rows.append({"id": str(r["id"]), "source": r.get("source", extra_path), "p": r.get("p"),
                         "deepseek": bool(r.get("deepseek", False))})
    return rows


def ledger(own: list, extra_path=None, hunt_private=None) -> tuple:
    """13: a global BH at q = 0.10 and Holm at 0.05 over every test-period hypothesis of the program. Returns (public,
    private): public DeepSeek rows show labels only."""
    rows = [{"id": b["id"], "source": "hiwr v1 (this study)", "p": b["p"] if b["checks"]["T0"] else 1.0,
             "deepseek": is_ds(b)} for b in own] + ledger_external(extra_path, hunt_private)
    pv = [r["p"] for r in rows]
    sig_bh, sig_holm = bh(pv, BH_Q), holm(pv, HOLM_ALPHA)
    for r, a, b in zip(rows, sig_bh, sig_holm):
        r["bh_q10"] = bool(a) if r["p"] is not None else None
        r["holm_005"] = bool(b) if r["p"] is not None else None
    missing = [r["id"] for r in rows if r["p"] is None]
    head = {"what": "PREREG_HIWR 13: program-wide ledger (global BH q = 0.10, Holm 0.05)",
            "hypotheses": len(rows), "with_p": len(rows) - len(missing), "missing_p": missing,
            "bh_rejections": int(sum(1 for r in rows if r["bh_q10"])),
            "holm_rejections": int(sum(1 for r in rows if r["holm_005"])),
            "note": "Track 1 and track 2 use the same 33 test months: the chance that at least one pick of either passes "
                    "by luck is larger than for either alone. The verdicts are shown side by side and never merged."}
    public = dict(head, rows=[{k: v for k, v in r.items() if not (r["deepseek"] and k == "p")} for r in rows])
    return public, dict(head, rows=rows)


def cmd_test(args) -> int:
    pin = check_pin("test")
    picks = load_picks(args)
    if os.path.exists(out_path("test.json")):
        raise SystemExit("test.json exists: the confirm look happened (one look per version, 13)")
    kits = kits_of(args)
    check_kit_manifest(kits)
    picks_sha = sha256_file(rpath(PICKS_REL))
    ensure_test_kit(args.kit_test, picks_sha, pin, kits["man_sel"])
    listed = {p for _h, p in read_pin()}
    if MANIFEST_TEST_REL not in listed:
        write_json(rpath(MANIFEST_TEST_REL), test_manifest(args.kit_test))
        append_pin(MANIFEST_TEST_REL)
    for rel in READS_RELS:                     # 17.3: the reads modules are listed before test.json exists
        if rel not in listed and os.path.exists(rpath(rel)):
            append_pin(rel)
    pin = check_pin("test")
    t0 = time.time()
    kits = kits_of(args, with_test=True)
    work = work_dir(args, f"test_{picks_sha[:16]}")
    procs = max(1, args.procs)
    tfs = sorted({p["tf"] for p in picks}, key=TFS.index)
    dirs = {"frames_TEST": os.path.join(work, "frames_test"), "tables_TEST": os.path.join(work, "tables_test")}
    CTX["dirs"] = dirs
    if picks:
        frames_stage("TEST", kits, dirs["frames_TEST"], tfs, procs)
        CTX["TEST"] = market("TEST", kits)
        tables_stage("TEST", dirs["frames_TEST"], dirs["tables_TEST"], tfs, procs)
    blocks, errors = {}, {}
    for pid, blk, err in R.run_pool(_test_job, [(p,) for p in picks], procs, "test"):
        if err:
            errors[pid] = err
            log(f"[test] ERROR {pid}: {err}")
        else:
            blocks[pid] = blk
            log(f"[test] {pid} done")
    if errors:
        raise SystemExit(f"[test] {len(errors)} picks failed; nothing written. Fix and run test again.")
    order = [blocks[p["id"]] for p in picks]
    vd = verdict(order)
    ds_ids = {p["id"] for p in picks if is_ds(p)}
    lpub, lpriv = ledger(order, args.ledger_extra, args.hunt_private)
    lpriv_sha = write_private(args, "ledger_private.json", lpriv)
    priv_sha = write_private(args, "test_private.json", {"results": blocks, "verdict": vd})
    st = stamp(pin)
    public = {"stamp": st, "what": "PREREG_HIWR 12: each pick once on TEST (2024-01-01 .. 2026-10-01)",
              "picks": [p["id"] for p in picks], "verdict": vd,
              "results": {b["id"]: (redact_block(b) if is_ds(b) else b) for b in order},
              "rule": {"T0": f">= {MIN_TEST} trades", "T1": "win rate >= 70.0%", "T2": "account at SEL f*: max DD "
                       "within the cap, no bust", "T3": "mean r > 0", "T4": "cost-x2 mean r > 0",
                       "T5": "p_a < 0.05 and p_b < 0.05", "T6": "BH q = 0.10 on max(p_boot, p_a, p_b)"},
              "seeds": N_SEEDS, "private_sha256": priv_sha, "ledger_private_sha256": lpriv_sha,
              "data": {"coins": CTX["TEST"].syms if picks else [], "minutes": CTX["TEST"].minutes() if picks else 0},
              "seconds": round(time.time() - t0, 1)}
    write_public(out_path("test.json"), public, ds_ids)
    write_public(out_path("ledger.json"), dict(lpub, private_sha256=lpriv_sha), ds_ids)
    log(f"test done: {len(vd['passing'])} PASS, {len(vd['reference'])} 참고 of {len(picks)} picks, "
        f"{time.time() - t0:.0f}s")
    if not args.no_reads:
        try:                                  # the verdict stands whatever a read does
            run_reads(args, pin, picks, kits)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            log(f"[reads] FAILED: {type(e).__name__}: {e}. test.json is written and unchanged.")
    return 0


# ------------------------------------------------------------------ reads (14)
def reads_module():
    import importlib
    return importlib.import_module("research.hiwr.reads")


def run_reads(args, pin, picks, kits) -> dict:
    """14: research/hiwr/reads.py run(ctx), only after test.json; its public output is D11-checked; figures of
    DeepSeek picks go to the private file."""
    if not os.path.exists(out_path("test.json")):
        raise SystemExit("reads run only after test.json (14)")
    listed = {p for _h, p in read_pin()}
    for rel in READS_RELS:
        if rel not in listed:
            raise PinError(f"{rel} is not pinned: a read added after the test is post hoc (DEVIATIONS.md)")
    mod = reads_module()
    test_doc = load_json(out_path("test.json"))
    priv = load_json(os.path.join(private_dir(args), "test_private.json"))
    if sha256_file(os.path.join(private_dir(args), "test_private.json")) != test_doc["private_sha256"]:
        raise PinError("test_private.json is not the file test.json names")
    ctx = {"H": sys.modules[__name__], "picks": picks, "kits": kits, "args": args, "pin": pin,
           "test": priv["results"], "verdict": priv["verdict"], "log": log}
    public, private = mod.run(ctx)
    ds_ids = {p["id"] for p in picks if is_ds(p)}
    psha = write_private(args, "reads_private.json", private)
    write_public(out_path("reads.json"), dict(public, stamp=stamp(pin), private_sha256=psha), ds_ids)
    return public


def cmd_reads(args) -> int:
    pin = check_pin("reads")
    picks = load_picks(args)
    kits = kits_of(args, with_test=True)
    run_reads(args, pin, picks, kits)
    return 0


# ------------------------------------------------------------------ report (RESULTS_KO.md)
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}


def _pct(x, d=1) -> str:
    return "-" if x is None else f"{x * 100:.{d}f}%"


def report_text(sel: dict | None, test: dict | None, led: dict | None, reads: dict | None) -> str:
    """The owners' page: short, plain Korean. DeepSeek rows: labels and counts only (D11)."""
    L = ["# 2번 트랙 결과 (승률 70% + 낙폭 한도)", ""]
    if sel is None:
        return "\n".join(L + ["아직 연습 기간 계산(select)이 끝나지 않았습니다.", ""])
    cells = sel["cells"]
    L += ["## 연습 기간(2021~2023)에서 고른 것", "", "| 봉 | 칸 | 기준 1번 통과 설정 | 고원까지 통과 | 고른 칸 |",
          "|---|---|---|---|---|"]
    for tf in TFS:
        cs = [c for c in cells if c["tf"] == tf]
        if not cs:
            continue
        L.append(f"| {TF_KO[tf]} | {len(cs)} | {sum(c['pass_B'] for c in cs):,} | {sum(c['pass_abc'] for c in cs):,} "
                 f"| {sum(1 for c in cs if c['pick'] != 'none')} |")
    L += ["", f"고른 것: {len(sel['picks'])}개 (칸마다 최대 1개). 연습 기간 숫자는 많이 뒤져서 고른 것이라 좋아 보입니다.", ""]
    if test is None:
        L += ["확인 기간(2024-01~2026-09)은 아직 보지 않았습니다.", ""]
        return "\n".join(L)
    vd = test["verdict"]
    res = test["results"]
    L += ["## 확인 기간(2024-01~2026-09) 결과 (한 번만 봄)", "",
          f"* **정식 통과: {len(vd['passing'])}개**, 참고: {len(vd['reference'])}개, 고른 것 전체: {vd['picks']}개", ""]
    if res:
        L += ["| 매매법 | 봉 | 결과 | 매매 수 | 승률 | 평균(매매당) | 계좌 낙폭 | 동전·아무때 비교 |", "|---|---|---|---|---|---|---|---|"]
        for pid in test["picks"]:
            b = res[pid]
            c = b["checks"]
            lab = "통과" if c["PASS"] else "참고" if c.get("참고") else "실패"
            if b["kind"] == "ds":
                L.append(f"| {b['name']} (딥시크) | {TF_KO[b['tf']]} | {lab} | {b['test']['n']} | "
                         f"{_pct(b['test']['win'])} | 비공개 | 비공개 | {'넘음' if c['T5'] else '못 넘음'} |")
            else:
                L.append(f"| {b['name']} | {TF_KO[b['tf']]} | {lab} | {b['test']['n']} | {_pct(b['test']['win'])} | "
                         f"{_pct(b['test']['mean'], 3)} | {_pct(b['account']['dd'])} | "
                         f"{'넘음' if c['T5'] else '못 넘음'} |")
        L.append("")
    L += ["* 1번 트랙(추세 사냥)과 **같은 확인 기간**을 씁니다. 그래서 둘 중 하나라도 운으로 통과할 확률이 하나만 볼 때보다 큽니다. "
          "두 결과는 나란히만 보여 드리고 합치지 않습니다.", "* 딥시크 매매법은 규칙(D11)대로 통과 여부·건수·승률만 적습니다.", ""]
    if led:
        L += ["## 프로그램 전체 장부", "",
              f"* 확인 기간 가설 {led['hypotheses']}개 (p값 있는 것 {led['with_p']}개): BH(q 0.10) 통과 {led['bh_rejections']}개, "
              f"Holm(0.05) 통과 {led['holm_rejections']}개", ""]
    if reads and reads.get("summary_ko"):
        L += ["## 참고로 본 것 (통과 기준 아님)", ""] + [f"* {x}" for x in reads["summary_ko"]] + [""]
    return "\n".join(L)


def report_d11_problems(text: str) -> list:
    """D11 on the owners' page: a DeepSeek row shows its label, trade count and win rate; mean and DD say 비공개."""
    bad = []
    for line in text.splitlines():
        if "(딥시크)" in line and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 7 or cells[5] != "비공개" or cells[6] != "비공개":
                bad.append(line)
    return bad


def cmd_report(args) -> int:
    def get(name):
        p = out_path(name)
        return load_json(p) if os.path.exists(p) else None
    text = report_text(get("select.json"), get("test.json"), get("ledger.json"), get("reads.json"))
    bad = report_d11_problems(text)
    if bad:
        raise RuntimeError(f"D11: DeepSeek figures on the owners' page: {bad[:3]}")
    path = out_path("RESULTS_KO.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    print(path)
    return 0


# ------------------------------------------------------------------ datapin / datacheck (3)
def cmd_datapin(args) -> int:
    kit = args.kit
    m = D.manifest(kit)
    if list(m["months"]) != list(D.KIT_SEL):
        raise SystemExit(f"{kit} holds months {m['months']}, not the practice kit {D.KIT_SEL}")
    for s, v in m["coins"].items():
        a = D.load(kit, s)
        if len(a["ts"]) and a["ts"][-1] >= PER("SEL")[1]:
            raise SystemExit(f"{s}: the practice kit holds a minute at or after {iso(PER('SEL')[1])}")
        if D.content_sha(a) != v["content_sha256"]:
            raise D.DataMismatch(f"{s}: build.json hash differs from the file")
    doc = {"what": "PREREG_HIWR 3: the practice kit's identity (per coin and array, the hunt's content sha256)",
           "rule": "sha256 of 'name|dtype|shape' newline then the raw C-order bytes, per array (data.array_sha); 'all' "
                   "over every array in data.ARRAYS order", "written_utc": now_utc(),
           "build_sha256": sha256_file(os.path.join(kit, "build.json")), **m}
    write_json(rpath(MANIFEST_SEL_REL), doc)
    print(MANIFEST_SEL_REL)
    return 0


def archive_5m_months(sym: str, first_ms: int) -> list:
    """Three seeded months of SEL (2021-01 .. 2023-12) in which the coin has data for (ii)'s fallback."""
    ms_ = [m for m in D.months("2021-01", "2023-12") if D.month_end_ms(m) > first_ms]
    rng = A.rng_for("datacheck", "SEL", sym, "months")
    k = min(3, len(ms_))
    return sorted(rng.choice(ms_, size=k, replace=False).tolist()) if k else []


def archive_5m(kit: str, sym: str, months: list) -> dict:
    """The archive's own 5m klines of ``months`` (checksummed; read from KIT/raw5m)."""
    raw = os.path.join(kit, "raw5m")
    parts = []
    for m in months:
        rel = f"futures/um/monthly/klines/{sym}/5m/{sym}-5m-{m}.zip"
        if D.fetch(raw, rel) == "ok":
            parts.append(D.read_kline_zip(os.path.join(raw, rel)))
    if not parts:
        return {k: np.zeros(0) for k in ("ts", "o", "h", "l", "c", "v")}
    import pandas as pd
    x = pd.concat(parts, ignore_index=True).drop_duplicates("t").sort_values("t")
    return {"ts": x["t"].to_numpy(np.int64), "o": x["open"].to_numpy(float), "h": x["high"].to_numpy(float),
            "l": x["low"].to_numpy(float), "c": x["close"].to_numpy(float), "v": x["volume"].to_numpy(float)}


def cmd_datacheck(args) -> int:
    man = load_json(rpath(MANIFEST_SEL_REL))
    end = PER("SEL")[1]
    out = {"what": "PREREG_HIWR 3: cross-checks before the pin, on data cut at 2024-01-01 (counts only)",
           "data_manifest_sha256": sha256_file(rpath(MANIFEST_SEL_REL)), "written_utc": now_utc(),
           "fg1m": {}, "five": {}}
    six = [s for s in D.OLD_SIX if s in SYMBOLS]
    for s in six:
        mine = D.load_kit(args.kit, s, end, want=man["coins"][s]["content_sha256"])
        fg = D.load_kit(args.fg1m, s, end)
        out["fg1m"][s] = D.check_fg1m(mine, fg, end)
        del fg
        log(f"(i) {s}: {out['fg1m'][s]['differing']} of {out['fg1m'][s]['common_minutes']} minutes differ")
    hman = load_json(os.path.join(ROOT, HUNT_MANIFEST_REL)) if os.path.exists(os.path.join(ROOT, HUNT_MANIFEST_REL)) \
        else {"content": {}}
    for s in SYMBOLS:
        if s not in man["coins"]:
            continue
        mine = D.load_kit(args.kit, s, end, want=man["coins"][s]["content_sha256"])
        p5 = os.path.join(args.hunt5m, "5m", f"{s}.npz") if args.hunt5m else ""
        if p5 and os.path.exists(p5):
            with np.load(p5) as z:
                full = {k: z[k] for k in ("ts", "o", "h", "l", "c", "v", "qv")}
            sha = D.content_sha(full, ("ts", "o", "h", "l", "c", "v", "qv"))["all"]
            if sha != ((hman["content"].get(s) or {}).get("5m")):
                raise SystemExit(f"{p5} is not the hunt's pinned 5m file ({HUNT_MANIFEST_REL})")
            cut = int(np.searchsorted(full["ts"], end))
            h5 = {k: v[:cut] for k, v in full.items()}
            del full
            res = D.check_5m(mine, h5, end)
            res["source"] = "hunt 5m (pinned)"
        else:
            mo = archive_5m_months(s, int(mine["ts"][0]))
            h5 = archive_5m(args.kit, s, mo)
            res = D.check_5m(mine, h5, end)
            res.update(source="archive 5m, three seeded months", months=mo)
        out["five"][s] = res
        log(f"(ii) {s}: {res['matching']} of {res['common_bars']} 5m bars match ({res['source']})")
    out["pass_fg1m"] = all(v["pass"] for v in out["fg1m"].values()) and len(out["fg1m"]) == len(six) > 0
    out["pass_five"] = all(v["pass"] for v in out["five"].values()) and len(out["five"]) == len(man["coins"])
    out["pass"] = bool(out["pass_fg1m"] and out["pass_five"])
    write_json(rpath(CHECK_SEL_REL), out)
    print(CHECK_SEL_REL, "pass" if out["pass"] else "FAIL")
    return 0 if out["pass"] else 1


def cmd_pinlist(args) -> int:
    for p in required_files():
        print(p)
    return 0


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("datapin", "datacheck", "select", "test", "report", "reads", "pinlist"))
    ap.add_argument("--kit", help="the practice kit folder (data.py build output)")
    ap.add_argument("--kit-test", help="the confirm kit folder (made by test, after the picks line)")
    ap.add_argument("--fg1m", help="the full grid's 1m data folder (datacheck i)")
    ap.add_argument("--hunt5m", help="the hunt's data folder with 5m/<SYM>.npz (datacheck ii)")
    ap.add_argument("--work", help="work folder outside the repository")
    ap.add_argument("--private", help="DeepSeek figures and other private files, outside the repository (D11)")
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--eligibility", choices=("all", "lazy"), default="all")
    ap.add_argument("--ledger-extra", default=None, help="JSON list of other test-period hypotheses {id, source, p}")
    ap.add_argument("--hunt-private", default=None, help="the hunt's private test file (its DeepSeek p-values)")
    ap.add_argument("--no-reads", action="store_true")
    a = ap.parse_args(argv)
    try:
        return {"datapin": cmd_datapin, "datacheck": cmd_datacheck, "select": cmd_select, "test": cmd_test,
                "report": cmd_report, "reads": cmd_reads, "pinlist": cmd_pinlist}[a.cmd](a)
    except PinError as e:
        print(f"REFUSED: {e}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
