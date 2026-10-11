"""Trend hunt (추세 사냥): the one-wallet simulator, selection, test, controls and report of
research/hunt/PREREG_HUNT.md (study ``v1``) and research/hunt/PREREG_HUNT_WIDE.md (study ``wide``).

    python -m research.hunt.hunt select --study {v1,wide} --data <coins30 dir> [--procs N] [--private DIR]
    python -m research.hunt.hunt test   --study {v1,wide} --data <coins30 dir> [--procs N] [--private DIR]
    python -m research.hunt.hunt report --study {v1,wide}
    python -m research.hunt.hunt universe --data <coins30 dir>        (writes research/hunt/universe30.json)
    python -m research.hunt.hunt datapin --data <coins30 dir>         (writes research/hunt/data_manifest.json, H 2)
    python -m research.hunt.hunt datacheck --data <coins30 dir> --fg1m <fg1m dir>   (research/hunt/data_check.json)
    python -m research.hunt.hunt pinlist --study {v1,wide}            (the files the study's pin must list)
    python -m research.hunt.hunt bench --out <timing.json> [--procs 2] (synthetic bars only, no real price)

``select`` and ``test`` refuse to run unless the study's pin file (PREREG_HUNT.sha256 / PREREG_HUNT_WIDE.sha256, one
line per file ``<sha256>  <path>``) matches every file it lists and lists every file of ``pinlist``: the prereg(s),
this file, the hunt tests, research/hunt/universe30.json, data_manifest.json and data_check.json (H 2), every
repository Python file the study's signal code loads (found by running each entry cell once on synthetic bars: the
full grid's code, research/deepseek200/lib_c.py, research/fullgrid/memo.py, the vendored indicator code, regime5y...),
and for wide parity.json, whose content must also say pass on the hunt 5m files under the current code (W 8). The
data check (H 2) must say pass on the old six, and the data read must equal data_manifest.json's array hashes. ``test``
also needs the picks line. ``select`` appends the picks line itself after writing the picks (PREREG_HUNT 11.3, WIDE 5)
and refuses when one is already there. Long steps keep finished parts under the private folder and resume from them
(same pin only); a worker that dies is replaced and its items sent again.

What runs where (section numbers "H n" = PREREG_HUNT.md, "W n" = PREREG_HUNT_WIDE.md):
* data (H 2, W 9): ``<data>/5m/<SYM>.npz`` (ts int64 ms; o h l c v qv float32, cast to float64 at use; duplicate open
  times dropped keeping the last, zero-quote-volume bars dropped, off-grid / non-finite rows dropped and counted; the
  mark-price columns are never read), ``<data>/funding/<SYM>.npz`` (ts, rate), ``<data>/manifest.json`` (coin end).
* signal bars, indicators, label, entries: research/hunt/entries_wide.py (H 4-6, W 3), imported read-only.
* the machine (H 7-10): ``_engine`` (numba), one wallet over a common 5m time axis of the period; the per-bar order is
  H 7.6; entries at a 5m open are decided on the state at the previous 5m close.
* select / test / controls / bootstrap / BH / reads: H 11-14, W 5-7.

Choices where the prereg leaves room are listed in ``CHOICES`` (also written into every output).
No absolute path is written here: data comes from ``--data`` (or $HUNT_DATA), the DeepSeek money file (W 11, D11)
goes to ``--private`` (default ``<data>/hunt_private``, outside the repository).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time

import numpy as np
from numba import njit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
OUT_ROOT = os.path.join(HERE, "out")

# ------------------------------------------------------------------ constants (H 7-13, W 2-7)
FIVE = 300_000
DAY_MS = 86_400_000
BARS_PER_DAY = 288
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
TF_ORDER = ("15m", "30m", "1h", "4h")
D0_MULT = {"15m": 2.0, "30m": 2.0, "1h": 2.0, "4h": 1.5}      # H 7.2 / W 2
CHAND_MULT = 3.0                                               # H 7.5
START_WALLET = 5000.0                                          # H 10
R_BASE, R_ONE = 0.005, 0.01
SIZING_RS = (0.02, 0.05)                                       # W 7
RISK_CAP = 0.04                                                # H 8
MAX_POS, MAX_DIR, N_ADDS = 6, 3, 3                             # H 8, H 7.4
LIQ_FRAC, LIQ_BARS = 0.001, 288                                # H 7.2 liquidity cut
PRIO_DAYS = 30                                                 # H 8 same-close order, H 3 large group
LARGE_N = 10
B_DIV, LEV_MAX, LIQ_MULT = 6.0, 20, 1.5                        # H 7.3
BUST_FRAC = 0.10                                               # H 10
COSTS = {"base": (0.0005, 0.0002), "x2": (0.0010, 0.0004)}     # H 9: (taker, slippage)
FALLBACK_BRACKETS = ((0.0, 25_000.0, 20, 0.025), (25_000.0, 100_000.0, 10, 0.05), (100_000.0, 250_000.0, 5, 0.10),
                     (250_000.0, 1_000_000.0, 3, 0.125), (1_000_000.0, math.inf, 1, 0.25))
FALLBACK_MIN_NOTIONAL = 5.0
PERIODS = {"select": ("2021-01-01", "2024-01-01"), "test": ("2024-01-01", "2026-10-01"),
           "extra": ("2020-01-01", "2021-01-01")}
OLD_SIX = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
N_SEEDS, N_BOOT = 100, 10_000
POS_PER_MONTH, MONTH_COVER, DD_MAX = 2, 0.80, 0.50             # H 11.2 / H 13
P_ALPHA, BH_Q, K_PICKS = 0.05, 0.10, 10
PICK_FAMILIES = ("F1", "F2", "F3")         # W 5: F4 (numbers chosen after this test period was seen) = select read only
SEED_TAG = {"v1": "hunt", "wide": "hunt-wide"}
MIN_FREE_BYTES = 1024 ** 3                                     # H 2: stop when free disk falls under 1 GB
XCHECK_TOL_PX, XCHECK_TOL_VOL, XCHECK_MAX_SHARE = 1e-6, 1e-3, 0.001   # H 2 cross-check of the old six
CONTENT_KEYS = {"5m": ("ts", "o", "h", "l", "c", "v", "qv"), "funding": ("ts", "rate")}  # H 2 data identity
UNKNOWN, TREND, RANGE, SHOCK, NORMAL = 0, 1, 2, 3, 4          # regime5y codes
GATES = ("G1", "NONE", "TS")                                   # TS = 추세장 or 급변장 (H 14 diagnostic only)

V1_ENTRIES = {"E1": ("channel", 55, (44, 69)), "E2": ("window", 120, (96, 150)),
              "E3": ("threshold", 1.5, (1.4, 1.625))}          # H 5, H 11.1
V1_TFS = ("1h", "4h")

PIN = {"v1": "research/hunt/PREREG_HUNT.sha256", "wide": "research/hunt/PREREG_HUNT_WIDE.sha256"}
PREREGS = {"v1": ("research/hunt/PREREG_HUNT.md",),
           "wide": ("research/hunt/PREREG_HUNT_WIDE.md", "research/hunt/PREREG_HUNT.md")}
UNIVERSE_REL = "research/hunt/universe30.json"
EXCHANGE_REL = "research/hunt/exchange30.json"
DATA_MANIFEST_REL = "research/hunt/data_manifest.json"          # H 2: manifest copy + array content hashes
DATA_CHECK_REL = "research/hunt/data_check.json"                # H 2: 5m vs the full grid's 1m, old six
DATA_BUILD_REL = "research/hunt/data_build"                     # H 2: the data job's scripts (every file pinned)
DATA_BUILDER_REL = "research/hunt/data_hunt.py"                 # the repository copy of the data builder (pinned)
PARITY_REL = "research/hunt/out/wide/parity.json"               # W 8
PARITY_CODE = ("entries_wide.py", "parity_wide.py", "hunt.py")  # parity.json must be made by these exact files
OUT_REL = {"v1": "research/hunt/out/v1", "wide": "research/hunt/out/wide"}
PICKS_REL = {"v1": "research/hunt/out/v1/pick.json", "wide": "research/hunt/out/wide/picks.json"}
_DATA_PINS = (DATA_MANIFEST_REL, DATA_CHECK_REL)
PIN_EXTRA = {"v1": ("tests/test_hunt.py", "tests/test_hunt_entries.py", "paperbot/dash/tools/regime5y.py")
             + _DATA_PINS,                                      # H 16 / W 10: files the pin must list
             "wide": ("tests/test_hunt.py", "tests/test_hunt_entries.py", PARITY_REL,
                      "research/fullgrid/diag/watch_sel.json", "research/fullgrid/PREREG.sha256",
                      "research/entry_study/DEFS_BC.sha256", "third_party/sweep/PREREG.sha256",
                      "paperbot/dash/tools/regime5y.py", "research/deepseek200/lib_c.py",
                      "research/fullgrid/memo.py") + _DATA_PINS}

CHOICES = [
    "H7.6: a 5m bar's entries (fills at its open) are decided first, on the state at the previous 5m close (equity, "
    "open positions, caps); then every open position, the new ones included, runs the bar in the order of H 7.6.",
    "H7.6: a bar whose high (long) reaches the next untried add level fills every add level it reaches first (each "
    "moving the stop and the liquidation price), and only then checks the low against the (moved) stop, also when "
    "the low had reached the old stop; a bar that reaches no add level checks the stop at once.",
    "H7.6: when the liquidation price lies inside the stop (only possible after a gapped add or a fallback leverage), "
    "the low (long) reaching it liquidates before the stop; otherwise the stop exits first.",
    "H7.3: liquidation price = Binance's isolated one-way formula with the bracket's mmr and cum at the position's "
    "entry notional; margin per unit = qty x fill / L; funding is paid from / to the wallet, not the isolated margin.",
    "H7.3: no L in 1..20 meeting (i) and (iii) -> the entry is skipped (counted 'leverage').",
    "H7.2/7.4: U stays r x equity at the entry also after a liquidity or margin cut, so S_req uses that U.",
    "H7.3: an entry or add is cut to what the free wallet (wallet - isolated margins) can pay incl. its taker fee; "
    "minimum notional is checked on every unit.",
    "H7.5: the 'entry bar' of the chandelier is the signal-timeframe bin that holds the fill 5m bar; the signal bar "
    "itself is not included.",
    "H7.6/2: funding at calc_time (rounded to the 5m grid) is charged after the 5m bar ending then; price = the coin's "
    "last 5m close; funding at or after the period end belongs to the next period.",
    "H3: a coin whose bars end for good inside the period (manifest last_nonzero_volume_bar) closes its open position "
    "at its last 5m close (exit costs, counted 'coin end'); open positions at the period end are marked, not closed.",
    "H8: same 5m fill time -> 30-day quote volume before the signal close (largest first), then pick number, then "
    "universe order; a signal whose coin has no 5m bar right after the close fills at the coin's next 5m bar.",
    "H10: months after a bust have M = 1 (account stopped) and are flagged; ln M uses max(M, 1e-12).",
    "H10: 'share of total profit from the top 10% of positions' = sum of the top 10% (ceil) positions' net P&L / sum "
    "of all positive net P&L.",
    "H12(a): per coin the n_long + n_short random bars are drawn together without replacement (so one bar is never "
    "both sides); the first n_long drawn are long. Pool = the coin's bars with close in the period, label known, "
    "ATR14 > 0 and a fill bar inside the period.",
    "H12/H13 seeds: sha256('|'.join(parts)) -> first 8 bytes little-endian -> numpy PCG64; v1 parts (hunt, control, "
    "period, r, seed); wide parts (hunt-wide, system id, control, period, r, seed); bootstrap seed = same with 'boot' "
    "as the seed part; r written with '%g'.",
    "H13 P0: 'a position open in a month' = at least one position open at some 5m step of that month.",
    "H11.2/W5: 72 / 66 positions = 2 x the period's months; positions = entries opened.",
    "W3.2: a bar with a long and a short event gives no entry and is counted 'both'; F2-F4 warm-up of 300 bars is "
    "applied by entries_wide.events_on; the event edge is taken before the gate (a run of True bars that starts on a "
    "bar the gate blocks gives no entry later in the run).",
    "W5: picks come from F1-F3 only; the 76 F4 systems run in select as a labelled read (their numbers were chosen "
    "after this test period was seen) and never in test; the 'no pick' fallback is the best F1-F3 system.",
    "W7: in the wide study the gate diagnostics run in the select period only (the other gate is a non-pick system); "
    "v1 runs them in select and test as H 14 says. In the 'no pick, fail' case the one system's reads run as a pick's.",
    "W7 sizing read: r = 2% / 5% with the total open risk cap and the margin budget B both scaled by r / 0.5% "
    "(B = equity / 6 x r / 0.5%), leverage as H 7.3 (20x cap, brackets, liquidation >= 1.5 x D0); the free wallet "
    "still limits each fill. Realized unit risk (first unit q x D0 / equity at entry), cut shares and add shares are "
    "reported next to every figure.",
    "H10: select runs report the metric set without the daily equity path (by year / side / group included); test "
    "runs include it. DeepSeek rows keep only counts and labels in the repository (W 11).",
    "H2: data identity = sha256 over the arrays the study reads, in order, each as 'name|dtype|shape' newline then its "
    "raw C-order bytes (5m: ts o h l c v qv; funding: ts rate); compared with research/hunt/data_manifest.json at "
    "every select / test. Coin end and missing funding months come from that pinned manifest copy; a coin end at or "
    "after the period end, and missing months outside the loaded span or after the coin end, are not carried into a "
    "step (select keeps nothing about 2024+).",
]


class PinError(RuntimeError):
    pass


# ------------------------------------------------------------------ small helpers
def day_ms(s: str) -> int:
    return int(np.datetime64(s, "ms").astype(np.int64))


def ms_str(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def month_starts(start_ms: int, end_ms: int) -> list:
    """Month starts in [start, end) and end itself (UTC calendar months)."""
    d = dt.datetime.fromtimestamp(start_ms / 1000, dt.timezone.utc)
    out = []
    y, m = d.year, d.month
    cur = int(dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    if cur < start_ms:
        m += 1
        y, m = (y + 1, 1) if m > 12 else (y, m)
        cur = int(dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    out.append(start_ms)
    while cur < end_ms:
        if cur > start_ms:
            out.append(cur)
        m += 1
        y, m = (y + 1, 1) if m > 12 else (y, m)
        cur = int(dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    out.append(end_ms)
    return out


def month_key(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def seed_int(*parts) -> int:
    """sha256 of the parts joined by '|' -> 64-bit seed (H 12; floats written with %g)."""
    s = "|".join(f"{p:g}" if isinstance(p, float) else str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(s.encode()).digest()[:8], "little")


def rng_of(*parts) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(seed_int(*parts)))


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return "unknown"


def _ew():
    from research.hunt import entries_wide
    return entries_wide


# ------------------------------------------------------------------ pin (W 10, H 16)
def read_pin(study: str) -> list:
    path = os.path.join(ROOT, PIN[study])
    if not os.path.exists(path):
        raise PinError(f"{PIN[study]} does not exist: the study is not pinned")
    rows = []
    with open(path) as fh:
        for line in fh:
            if not line.strip():
                continue
            parts = line.rstrip("\n").split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                raise PinError(f"{PIN[study]}: bad line {line!r} (want '<sha256>  <path>')")
            rows.append((parts[0], parts[1].strip()))
    return rows


def hunt_modules() -> list:
    """Repository paths of the research/hunt modules this process imported."""
    out = []
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None) or ""
        if f.endswith(".py") and os.path.dirname(os.path.abspath(f)) == HERE:
            out.append(os.path.relpath(os.path.abspath(f), ROOT))
    return sorted(set(out))


def _repo_py_loaded() -> list:
    """Repository .py files of every loaded module (tests excluded)."""
    out = set()
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None) or ""
        if not f.endswith(".py"):
            continue
        a = os.path.abspath(f)
        if os.path.commonpath([a, ROOT]) != ROOT:
            continue
        rel = os.path.relpath(a, ROOT)
        if rel.startswith(("tests" + os.sep, ".")) or os.sep + "site-packages" + os.sep in a:
            continue
        out.add(rel)
    return sorted(out)


def signal_path_files(study: str) -> list:
    """Every repository Python file the study's signal code loads (W 10, H 16): each entry cell of the study is run
    once on a short synthetic series (no real price), then the loaded modules are listed. A file imported lazily by a
    strategy definition is found this way too."""
    EW = _ew()
    n = 75 * BARS_PER_DAY
    t0 = day_ms("2021-03-01")
    rng = np.random.default_rng(7)

    def five(seed):
        r = np.random.default_rng(seed)
        c = 100.0 * np.exp(np.cumsum(r.normal(0, 0.002, n)))
        o = np.r_[c[0], c[:-1]]
        v = r.lognormal(0, 1, n) * 100.0
        return {"ts": t0 + np.arange(n, dtype=np.int64) * FIVE, "o": o, "h": np.maximum(o, c) * 1.001,
                "l": np.minimum(o, c) * 0.999, "c": c, "v": v, "qv": v * c}
    eth, btc = five(int(rng.integers(1 << 30))), five(int(rng.integers(1 << 30)))
    if study == "v1":
        cells = [dict(s, id="probe") for s in v1_systems()]
    else:
        cells = [dict(c, id="probe", gate="NONE") for c in EW.entry_cells()]
    for spec in cells:
        bars, _ = EW.events(spec, eth, "ETHUSDT", btc)
        EW.regime_code(bars)
        EW.atr14(bars)
    return _repo_py_loaded()


def required_files(study: str) -> list:
    """The files the study's pin must list (``pinlist``), the picks file excluded."""
    need = list(PREREGS[study]) + ["research/hunt/hunt.py", UNIVERSE_REL] + hunt_modules() + list(PIN_EXTRA[study])
    need += signal_path_files(study)
    if os.path.exists(os.path.join(ROOT, EXCHANGE_REL)):
        need.append(EXCHANGE_REL)
    if os.path.exists(os.path.join(ROOT, DATA_BUILDER_REL)):
        need.append(DATA_BUILDER_REL)
    bdir = os.path.join(ROOT, DATA_BUILD_REL)
    if os.path.isdir(bdir):
        for dp, _dn, fns in os.walk(bdir):
            for f in fns:
                if "__pycache__" not in dp and not f.endswith(".pyc"):
                    need.append(os.path.relpath(os.path.join(dp, f), ROOT))
    return sorted(set(need))


def _load_json_rel(rel: str):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return json.load(fh)


def pin_content_problems(study: str) -> list:
    """What the pinned result files must say (H 2, W 8): data_check.json passes on the old six for the data of
    data_manifest.json; for wide, parity.json passes on the hunt 5m files and was made by the current adapter code."""
    bad = []
    dm, dc = _load_json_rel(DATA_MANIFEST_REL), _load_json_rel(DATA_CHECK_REL)
    if dc is not None:
        if dc.get("pass") is not True:
            bad.append(f"{DATA_CHECK_REL} does not say pass")
        if sorted(dc.get("coins", {})) != sorted(OLD_SIX):
            bad.append(f"{DATA_CHECK_REL} is not on the old six")
        if dm is not None:
            for s in OLD_SIX:
                got = (dc.get("coins", {}).get(s) or {}).get("content_sha256")
                if got != ((dm.get("content") or {}).get(s) or {}).get("5m"):
                    bad.append(f"{DATA_CHECK_REL} checked other {s} data than {DATA_MANIFEST_REL}")
    if study == "wide":
        pj = _load_json_rel(PARITY_REL)
        if pj is not None:
            if pj.get("pass") is not True:
                bad.append(f"{PARITY_REL} does not say pass")
            if pj.get("adapter_5m") != "hunt 5m files":
                bad.append(f"{PARITY_REL} was not run on the hunt 5m files (--five)")
            if list(pj.get("syms", [])) != list(OLD_SIX):
                bad.append(f"{PARITY_REL} is not on the old six")
            code = pj.get("code") or {}
            for f in PARITY_CODE:
                if code.get(f) != sha256_file(os.path.join(HERE, f)):
                    bad.append(f"{PARITY_REL} was made by another research/hunt/{f}")
    return bad


def check_pin(study: str, step: str) -> dict:
    """Refuse (PinError) unless every listed file matches, the required files are listed and the pinned result files
    say pass (W 10, H 2, W 8)."""
    _ew()                                         # the modules a run imports are part of the pin
    rows = read_pin(study)
    listed = {p: h for h, p in rows}
    bad = []
    for h, p in rows:
        full = os.path.join(ROOT, p)
        if not os.path.exists(full):
            bad.append(f"missing {p}")
        elif sha256_file(full) != h:
            bad.append(f"changed {p}")
    for p in required_files(study):
        if p not in listed:
            bad.append(f"not pinned {p}")
    bad += pin_content_problems(study)
    picks = PICKS_REL[study]
    if step == "select" and picks in listed:
        bad.append(f"{picks} is already pinned: select ran; the picks do not change")
    if step == "test" and picks not in listed:
        bad.append(f"{picks} is not pinned: run select first")
    if bad:
        raise PinError(f"{PIN[study]} does not match: " + "; ".join(bad))
    return {"pin_file": PIN[study], "pin_sha256": sha256_file(os.path.join(ROOT, PIN[study])), "files": len(rows)}


def append_picks_line(study: str) -> str:
    path = os.path.join(ROOT, PICKS_REL[study])
    h = sha256_file(path)
    with open(os.path.join(ROOT, PIN[study]), "a") as fh:
        fh.write(f"{h}  {PICKS_REL[study]}\n")
    return h


# ------------------------------------------------------------------ data (H 2, W 9)
class Coin:
    """One coin's 5m bars up to (not including) ``end_ms``, cleaned as H 2 (float32 storage, as in the files)."""

    def __init__(self, sym, ts, o, h, lo, c, v, qv, last_ms=None, counts=None):
        self.sym = sym
        self.ts = np.asarray(ts, np.int64)
        self.o, self.h, self.l, self.c, self.v, self.qv = (np.asarray(x, np.float32) for x in (o, h, lo, c, v, qv))
        self.last_ms = int(self.ts[-1]) if last_ms is None and len(self.ts) else last_ms
        self.counts = counts or {}
        self.cq = np.concatenate(([0.0], np.cumsum(self.qv, dtype=np.float64)))

    def f64(self) -> dict:
        return {"ts": self.ts, "o": self.o.astype(np.float64), "h": self.h.astype(np.float64),
                "l": self.l.astype(np.float64), "c": self.c.astype(np.float64), "v": self.v.astype(np.float64),
                "qv": self.qv.astype(np.float64)}


def clean_5m(ts, o, h, lo, c, v, qv):
    """H 2: duplicate open times dropped (last kept), zero-volume bars dropped (quote volume <= 0); rows off the 5m
    grid or with a non-finite price dropped too. Returns (arrays, counts)."""
    ts = np.asarray(ts, np.int64)
    n0 = len(ts)
    order = np.argsort(ts, kind="stable")
    ts_s = ts[order]
    last = np.r_[ts_s[1:] != ts_s[:-1], True]
    idx = order[last]
    n_dup = n0 - len(idx)
    arr = [np.asarray(x)[idx] for x in (o, h, lo, c, v, qv)]
    ts = ts[idx]
    fin = np.isfinite(arr[0]) & np.isfinite(arr[1]) & np.isfinite(arr[2]) & np.isfinite(arr[3])
    grid = ts % FIVE == 0
    vol = np.asarray(arr[5], np.float64) > 0
    keep = fin & grid & vol
    counts = {"rows": int(n0), "duplicates": int(n_dup), "zero_volume": int((fin & grid & ~vol).sum()),
              "off_grid": int((~grid).sum()), "non_finite": int((~fin & grid).sum())}
    return (ts[keep], *[a[keep] for a in arr]), counts


def _manifest(data_dir: str) -> dict:
    p = os.path.join(data_dir, "manifest.json")
    if not os.path.exists(p):
        return {}
    with open(p) as fh:
        m = json.load(fh)
    return {s["symbol"]: s for s in m.get("symbols", [])}


def study_manifest(data_dir: str) -> dict:
    """The coin fields a step reads (coin end, missing funding months): the pinned copy in
    research/hunt/data_manifest.json when it exists (H 2), else the data folder's manifest.json (tests, timing)."""
    dm = _load_json_rel(DATA_MANIFEST_REL)
    if dm is not None and "manifest" in dm:
        return {s["symbol"]: s for s in dm["manifest"].get("symbols", [])}
    return _manifest(data_dir)


def _parse_utc(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def content_sha(arrays: dict, keys) -> str:
    """H 2 data identity: sha256 over the arrays in ``keys`` order, each as 'name|dtype|shape' newline then its raw
    C-order bytes (as stored in the npz; independent of the zip container)."""
    h = hashlib.sha256()
    for k in keys:
        a = np.ascontiguousarray(arrays[k])
        h.update(f"{k}|{a.dtype.str}|{','.join(str(x) for x in a.shape)}\n".encode())
        h.update(a.tobytes())
    return h.hexdigest()


def file_content_sha(path: str, kind: str) -> str | None:
    if not os.path.exists(path):
        return None
    with np.load(path) as z:
        return content_sha({k: z[k] for k in CONTENT_KEYS[kind]}, CONTENT_KEYS[kind])


def load_coin(data_dir: str, sym: str, end_ms: int, manifest: dict | None = None) -> Coin:
    """The coin's 5m bars with open < end_ms. The npz columns are decompressed whole (their content hash is taken,
    H 2) and cut at ``end_ms`` before anything else uses them: no bar at or after ``end_ms`` is kept or used (W 5,
    H 11). Of the manifest only what lies before ``end_ms`` is carried (coin end, missing funding months)."""
    path = os.path.join(data_dir, "5m", f"{sym}.npz")
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} missing: the universe is fixed, select / test stop (W 9)")
    with np.load(path) as z:
        full = {k: z[k] for k in CONTENT_KEYS["5m"]}
    sha = content_sha(full, CONTENT_KEYS["5m"])
    cut = full["ts"] < end_ms
    cols = [full[k][cut] for k in ("o", "h", "l", "c", "v", "qv")]
    ts = full["ts"][cut]
    del full
    (ts, o, h, lo, c, v, qv), counts = clean_5m(ts, *cols)
    counts["content_sha256"] = sha
    info = (manifest or {}).get(sym, {})
    last = info.get("last_nonzero_volume_bar") or info.get("last_bar")
    last_ms = _parse_utc(last) if last else None
    if last_ms is None:
        last_ms = int(ts[-1]) if len(ts) else None
    if last_ms is not None and last_ms >= end_ms - FIVE:
        last_ms = None                           # trades to the end of the loaded span: continuing (nothing later kept)
    end_month = month_key(end_ms)
    mm = info.get("missing_months_funding_while_trading")
    if mm is None:                               # older manifests: cut at the coin end
        stop = month_key(last_ms) if last_ms is not None else "9999-99"
        mm = [m for m in info.get("missing_months_funding", []) if m <= stop]
    counts["missing_months_funding"] = [m for m in mm if m < end_month]
    return Coin(sym, ts, o, h, lo, c, v, qv, last_ms=last_ms if last_ms is not None else 2 ** 62, counts=counts)


def load_funding(data_dir: str, sym: str, end_ms: int, with_sha: bool = False) -> tuple:
    path = os.path.join(data_dir, "funding", f"{sym}.npz")
    if not os.path.exists(path):
        out = (np.zeros(0, np.int64), np.zeros(0))
        return (*out, None) if with_sha else out
    with np.load(path) as z:
        full = {k: z[k] for k in CONTENT_KEYS["funding"]}
    sha = content_sha(full, CONTENT_KEYS["funding"])
    ts, rate = np.asarray(full["ts"], np.int64), np.asarray(full["rate"], np.float64)
    keep = ts < end_ms
    return (ts[keep], rate[keep], sha) if with_sha else (ts[keep], rate[keep])


def disk_check(*paths) -> None:
    """H 2: stop when free disk under any output path falls under 1 GB."""
    for p in paths:
        if not p:
            continue
        q = os.path.abspath(p)
        while not os.path.exists(q):
            q = os.path.dirname(q)
        free = shutil.disk_usage(q).free
        if free < MIN_FREE_BYTES:
            raise SystemExit(f"stopped: free disk under {p} is {free / 1e9:.2f} GB (< 1 GB, H 2)")


def data_identity_problems(counts: dict, fund_sha: dict) -> list:
    """Differences between the data read and research/hunt/data_manifest.json's array hashes (H 2)."""
    dm = _load_json_rel(DATA_MANIFEST_REL)
    if dm is None:
        return [f"{DATA_MANIFEST_REL} missing (python -m research.hunt.hunt datapin --data DIR, before the pin)"]
    want = dm.get("content") or {}
    bad = []
    for s, cnt in counts.items():
        w = want.get(s) or {}
        if cnt.get("content_sha256") != w.get("5m"):
            bad.append(f"{s} 5m arrays differ")
        if fund_sha.get(s) != w.get("funding"):
            bad.append(f"{s} funding arrays differ")
    return bad


def load_universe(data_dir: str | None = None) -> list:
    """research/hunt/universe30.json (H 3); without it (tests, timing) the data folder's universe.json."""
    p = os.path.join(ROOT, UNIVERSE_REL)
    if os.path.exists(p):
        with open(p) as fh:
            return list(json.load(fh)["symbols"])
    if data_dir is None:
        raise FileNotFoundError(UNIVERSE_REL)
    with open(os.path.join(data_dir, "universe.json")) as fh:
        return list(json.load(fh)["universe"])


def write_universe30(data_dir: str) -> dict:
    """Copy the coins30 rule's list into research/hunt/universe30.json with UNIVERSE.md's sha256 (H 3)."""
    with open(os.path.join(data_dir, "universe.json")) as fh:
        syms = list(json.load(fh)["universe"])
    if len(syms) != 30 or len(set(syms)) != 30:
        raise ValueError("universe.json does not hold 30 distinct symbols")
    d = {"symbols": syms, "old_six": [s for s in OLD_SIX if s in syms], "new": [s for s in syms if s not in OLD_SIX],
         "universe_md_sha256": sha256_file(os.path.join(data_dir, "UNIVERSE.md")),
         "universe_json_sha256": sha256_file(os.path.join(data_dir, "universe.json")),
         "rule": "coins30/UNIVERSE.md (top 30 USDT perpetuals by 2023 quote volume with 5m history from 2021-01 or "
                 "earlier; the six current coins included)"}
    with open(os.path.join(ROOT, UNIVERSE_REL), "w") as fh:
        json.dump(d, fh, indent=1)
        fh.write("\n")
    return d


def load_brackets(syms: list) -> dict:
    """Per-coin leverage brackets and minimum notional: research/hunt/exchange30.json (format of
    research/fullgrid/exchange.json) or the fallback table of H 7.3, flagged per coin."""
    ex = {}
    p = os.path.join(ROOT, EXCHANGE_REL)
    if os.path.exists(p):
        with open(p) as fh:
            ex = json.load(fh)
    brs = {b["symbol"]: b["brackets"] for b in ex.get("brackets", [])}
    specs = ex.get("specs", {})
    rows, mins, flags = [], [], {}
    for s in syms:
        if s in brs:
            bl = sorted(brs[s], key=lambda b: b["notionalFloor"])
            rows.append([(float(b["notionalFloor"]), float(b["notionalCap"]), int(b["initialLeverage"]),
                          float(b["maintMarginRatio"]), float(b.get("cum", 0.0))) for b in bl])
            flags[s] = "exchange30"
        else:
            cum, prev, rr = 0.0, None, []
            for fl, cap, lev, mmr in FALLBACK_BRACKETS:
                if prev is not None:
                    cum += fl * (mmr - prev)
                rr.append((fl, cap, lev, mmr, cum))
                prev = mmr
            rows.append(rr)
            flags[s] = "fallback"
        mins.append(float(specs.get(s, {}).get("min_notional", FALLBACK_MIN_NOTIONAL)))
    nb = max(len(r) for r in rows) if rows else 1
    K = len(syms)
    out = {"n": np.zeros(K, np.int64), "cap": np.full((K, nb), np.inf), "lev": np.zeros((K, nb), np.int64),
           "mmr": np.zeros((K, nb)), "cum": np.zeros((K, nb)), "min_notional": np.asarray(mins, np.float64),
           "flags": flags}
    for k, rr in enumerate(rows):
        out["n"][k] = len(rr)
        for i, (fl, cap, lev, mmr, cum) in enumerate(rr):
            out["cap"][k, i], out["lev"][k, i], out["mmr"][k, i], out["cum"][k, i] = cap, lev, mmr, cum
    return out


# ------------------------------------------------------------------ process-wide state (inherited by forked workers)
_COINS: dict = {}          # sym -> Coin (all loaded data of the study)
_FUND: dict = {}           # sym -> (ts, rate)
_SERIES: dict = {}         # (sym, tf) -> Series
_EVENTS: dict = {}         # (cell key, sym) -> (long, short)
_SIGS: dict = {}           # (market key, cell key, gate) -> signals
_BANKS: dict = {}          # (market key, tfs) -> Bank
_POOLS: dict = {}          # (market key, tf, coin) -> control (a) pool


def install(coins: dict, funding: dict | None = None) -> None:
    """Set the study's data (tests and the bench install synthetic coins the same way)."""
    _COINS.clear()
    _COINS.update(coins)
    _FUND.clear()
    _FUND.update(funding or {})
    for d in (_SERIES, _EVENTS, _SIGS, _BANKS, _POOLS):
        d.clear()


def load_study_data(data_dir: str, syms: list, end_ms: int) -> dict:
    """Load and install the universe's data up to ``end_ms``; returns per coin the H 2 counts with the content hashes
    of the 5m and funding arrays read (``content_sha256``, ``funding_content_sha256``)."""
    man = study_manifest(data_dir)
    coins = {s: load_coin(data_dir, s, end_ms, man) for s in syms}
    fund = {}
    for s in syms:
        fts, rate, fsha = load_funding(data_dir, s, end_ms, with_sha=True)
        fund[s] = (fts, rate)
        coins[s].counts["funding_content_sha256"] = fsha
    install(coins, fund)
    return {s: coins[s].counts for s in syms}


class Series:
    """One coin's signal bars on one timeframe (entries_wide.build_bars over the coin's loaded 5m bars), ATR14
    (Wilder) and the 장세 code (H 4, H 6)."""

    def __init__(self, sym: str, tf: str):
        EW = _ew()
        c = _COINS[sym]
        f = c.f64()
        self.sym, self.tf = sym, tf
        self.bars = EW.build_bars(f["ts"], f["o"], f["h"], f["l"], f["c"], f["v"], tf, f["qv"])
        self.atr = np.asarray(EW.atr14(self.bars), np.float64)
        self.code = np.asarray(EW.regime_code(self.bars), np.int8)


def series(sym: str, tf: str) -> Series:
    key = (sym, tf)
    s = _SERIES.get(key)
    if s is None:
        s = _SERIES[key] = Series(sym, tf)
    return s


def prepare_series(syms, tfs) -> None:
    for tf in tfs:
        for s in syms:
            series(s, tf)


# ------------------------------------------------------------------ market: the period's common 5m axis (H 8-10)
class Market:
    """The coins of one universe on one period's 5m axis [start, end): flat per-coin bars with their global step,
    funding steps, coin ends, large group per month (H 3) and brackets."""

    def __init__(self, syms: list, period, name: str | None = None):
        if isinstance(period, str):
            a, b = PERIODS[period]
            self.period = period
            self.start, self.end = day_ms(a), day_ms(b)
        else:
            self.start, self.end = int(period[0]), int(period[1])
            self.period = name or f"{ms_str(self.start)}..{ms_str(self.end)}"
        if (self.end - self.start) % DAY_MS or self.start % DAY_MS:
            raise ValueError("a period starts and ends at 00:00 UTC")
        self.syms = list(syms)
        self.K = len(self.syms)
        self.T = (self.end - self.start) // FIVE
        self.key = f"{self.period}:{self.start}:{self.end}:" + ",".join(self.syms)
        ms = month_starts(self.start, self.end)
        self.month_ms = np.asarray(ms, np.int64)
        self.month_t0 = (self.month_ms - self.start) // FIVE
        self.months = [month_key(x) for x in ms[:-1]]
        off, bt, bo, bh, bl, bc, bq, p0s, p1s, cend = [0], [], [], [], [], [], [], [], [], []
        foff, ft, fr = [0], [], []
        for s in self.syms:
            c = _COINS[s]
            p0 = int(np.searchsorted(c.ts, self.start, "left"))
            p1 = int(np.searchsorted(c.ts, self.end, "left"))
            p0s.append(p0)
            p1s.append(p1)
            bt.append((c.ts[p0:p1] - self.start) // FIVE)
            for dst, src in ((bo, c.o), (bh, c.h), (bl, c.l), (bc, c.c)):
                dst.append(src[p0:p1].astype(np.float64))
            idx = np.arange(p0, p1)
            bq.append(c.cq[idx] - c.cq[np.maximum(0, idx - LIQ_BARS)])
            off.append(off[-1] + (p1 - p0))
            ce = -1
            if c.last_ms is not None and self.start <= c.last_ms < self.end - FIVE:
                ce = int((c.last_ms - self.start) // FIVE)
            cend.append(ce)
            fts, frate = _FUND.get(s, (np.zeros(0, np.int64), np.zeros(0)))
            g = ((np.asarray(fts, np.int64) + 30_000) // FIVE) * FIVE      # calc_time on the 5m grid
            keep = (g > self.start) & (g < self.end)
            order = np.argsort(g[keep], kind="stable")
            ft.append(((g[keep] - self.start) // FIVE - 1)[order])          # charged after the bar ending at calc_time
            fr.append(np.asarray(frate, np.float64)[keep][order])
            foff.append(foff[-1] + int(keep.sum()))
        cat = lambda xs, dt_: np.concatenate(xs).astype(dt_) if xs else np.zeros(0, dt_)  # noqa: E731
        self.b_off = np.asarray(off, np.int64)
        self.b_t = cat(bt, np.int64)
        self.b_o, self.b_h, self.b_l, self.b_c, self.b_qv = (cat(x, np.float64) for x in (bo, bh, bl, bc, bq))
        self.p0, self.p1 = np.asarray(p0s, np.int64), np.asarray(p1s, np.int64)
        self.coin_end_t = np.asarray(cend, np.int64)
        self.f_off = np.asarray(foff, np.int64)
        self.f_t = cat(ft, np.int64)
        self.f_rate = cat(fr, np.float64)
        self.large = self._large()
        br = load_brackets(self.syms)
        self.br = br
        self.funding_missing = {s: [m for m in _COINS[s].counts.get("missing_months_funding", [])
                                    if self.months and self.months[0] <= m <= self.months[-1]] for s in self.syms}

    def qv_window(self, k: int, end_ms, days: int = PRIO_DAYS):
        """Quote volume of the coin's 5m bars with open in [end - days, end) (vectorised over end_ms)."""
        c = _COINS[self.syms[k]]
        a = np.searchsorted(c.ts, np.asarray(end_ms, np.int64) - days * DAY_MS, "left")
        b = np.searchsorted(c.ts, np.asarray(end_ms, np.int64), "left")
        return c.cq[b] - c.cq[a]

    def _large(self) -> np.ndarray:
        n_m = len(self.months)
        out = np.zeros((n_m, self.K), np.int64)
        for m in range(n_m):
            t0 = int(self.month_ms[m])
            vols = []
            for k, s in enumerate(self.syms):
                c = _COINS[s]
                ok = len(c.ts) and c.ts[0] <= t0 - PRIO_DAYS * DAY_MS
                vols.append(float(self.qv_window(k, t0)) if ok else -1.0)
            order = sorted(range(self.K), key=lambda k: (-vols[k], k))
            for k in order[:LARGE_N]:
                if vols[k] > 0:
                    out[m, k] = 1
        return out


class Bank:
    """The signal bars the chandelier reads (H 7.5): per (timeframe, coin) the bins with close in [start, end]:
    step from which the update applies (close step), high, low, ATR14."""

    def __init__(self, mk: Market, tfs):
        self.tfs = tuple(tfs)
        ct, hh, ll, aa, self.off = [], [], [], [], {}
        n = 0
        for tf in self.tfs:
            for k, s in enumerate(mk.syms):
                ser = series(s, tf)
                cm = ser.bars.close_ms
                lo = int(np.searchsorted(cm, mk.start, "left"))
                hi = int(np.searchsorted(cm, mk.end, "right"))
                ct.append((cm[lo:hi] - mk.start) // FIVE)
                hh.append(ser.bars.h[lo:hi])
                ll.append(ser.bars.l[lo:hi])
                aa.append(ser.atr[lo:hi])
                self.off[(tf, k)] = (n, n + (hi - lo), lo)
                n += hi - lo
        cat = lambda xs, dt_: np.concatenate(xs).astype(dt_) if xs else np.zeros(0, dt_)  # noqa: E731
        self.s_ct, self.s_h, self.s_l, self.s_atr = cat(ct, np.int64), cat(hh, float), cat(ll, float), cat(aa, float)


def bank_for(mk: Market, tfs) -> Bank:
    key = (mk.key, tuple(tfs))
    b = _BANKS.get(key)
    if b is None:
        b = _BANKS[key] = Bank(mk, tfs)
    return b


# ------------------------------------------------------------------ entries -> gated signals (H 5-6, W 3)
def cell_key(spec: dict) -> tuple:
    return (spec.get("family"), spec["name"], spec["kind"], spec["tf"], json.dumps(spec["combo"], sort_keys=True))


def entry_events(spec: dict, sym: str, ser: Series, btc: Series | None) -> tuple:
    """Ungated long / short events per signal bar of ``ser`` (entries_wide.events_on; tests replace this)."""
    EW = _ew()
    ev = EW.events_on(spec, ser.bars, sym, btc.bars if btc is not None else None)
    return np.asarray(ev["long"], bool), np.asarray(ev["short"], bool)


def cached_events(spec: dict, sym: str) -> tuple:
    key = (cell_key(spec), sym)
    ev = _EVENTS.get(key)
    if ev is None:
        btc = series("BTCUSDT", spec["tf"]) if spec["kind"] == "ds" and sym != "BTCUSDT" and "BTCUSDT" in _COINS \
            else None
        ev = _EVENTS[key] = entry_events(spec, sym, series(sym, spec["tf"]), btc)
    return ev


def gate_mask(ser: Series, gate: str) -> np.ndarray:
    if gate == "NONE":
        return np.ones(len(ser.code), bool)
    if gate == "G1":
        return ser.code == TREND
    if gate == "TS":
        return (ser.code == TREND) | (ser.code == SHOCK)
    raise ValueError(f"gate {gate!r}")


def fill_index(mk: Market, k: int, ser: Series) -> tuple:
    """(fill index into the coin's 5m arrays, ok) per signal bar: the first 5m bar after the close, inside the
    period's loaded bars."""
    c = _COINS[mk.syms[k]]
    fi = np.asarray(ser.bars.first5, np.int64)
    ok = fi < min(len(c.ts), int(mk.p1[k]))
    ok &= fi >= mk.p0[k]
    return fi, ok


def system_signals(mk: Market, spec: dict, gate: str | None = None) -> dict:
    """The gated signals of one system in the market's period: coin index k, signal bar j, side (+1 / -1), with
    counts (events, both sides, gated out, no ATR, no fill)."""
    gate = gate or spec["gate"]
    key = (mk.key, cell_key(spec), gate)
    if key in _SIGS:
        return _SIGS[key]
    tf = spec["tf"]
    K, J, S = [], [], []
    cnt = {"events": 0, "both": 0, "gated_out": 0, "no_atr": 0, "no_fill": 0, "gated": 0}
    per = {}
    for k, s in enumerate(mk.syms):
        ser = series(s, tf)
        lg, sh = cached_events(spec, s)
        cm = ser.bars.close_ms
        inper = (cm >= mk.start) & (cm < mk.end)
        both = lg & sh & inper
        lg, sh = lg & inper & ~both, sh & inper & ~both
        cnt["events"] += int(lg.sum() + sh.sum() + 2 * both.sum())
        cnt["both"] += int(both.sum())
        g = gate_mask(ser, gate)
        atr_ok = np.isfinite(ser.atr) & (ser.atr > 0)
        _, f_ok = fill_index(mk, k, ser)
        for side, ev in ((1, lg), (-1, sh)):
            cnt["gated_out"] += int((ev & ~g).sum())
            cnt["no_atr"] += int((ev & g & ~atr_ok).sum())
            cnt["no_fill"] += int((ev & g & atr_ok & ~f_ok).sum())
            jj = np.flatnonzero(ev & g & atr_ok & f_ok)
            K.append(np.full(len(jj), k, np.int64))
            J.append(jj.astype(np.int64))
            S.append(np.full(len(jj), side, np.int64))
            per[(s, side)] = len(jj)
    out = {"tf": tf, "k": np.concatenate(K) if K else np.zeros(0, np.int64),
           "j": np.concatenate(J) if J else np.zeros(0, np.int64),
           "side": np.concatenate(S) if S else np.zeros(0, np.int64), "counts": cnt}
    out["counts"]["gated"] = int(len(out["k"]))
    _SIGS[key] = out
    return out


def build_cands(mk: Market, bank: Bank, parts: list) -> dict:
    """Candidate entries for the engine from [(signals, src)] (src = pick number, 0 for one system), sorted by fill
    step, then 30-day quote volume (largest first), then src, then universe order (H 8, W 7)."""
    cols = {x: [] for x in ("t", "bi", "coin", "side", "d0", "s0", "s1", "prio", "src", "close", "j")}
    for sig, src in parts:
        tf = sig["tf"]
        for k in np.unique(sig["k"]):
            sel = sig["k"] == k
            j, side = sig["j"][sel], sig["side"][sel]
            ser = series(mk.syms[k], tf)
            c = _COINS[mk.syms[k]]
            fi = ser.bars.first5[j]
            fill_ms = c.ts[fi]
            close = ser.bars.close_ms[j]
            a, b, lo = bank.off[(tf, int(k))]
            cm = ser.bars.close_ms[lo:lo + (b - a)]
            cols["t"].append((fill_ms - mk.start) // FIVE)
            cols["bi"].append(mk.b_off[k] + fi - mk.p0[k])
            cols["coin"].append(np.full(len(j), k, np.int64))
            cols["side"].append(side)
            cols["d0"].append(D0_MULT[tf] * ser.atr[j])
            cols["s0"].append(a + np.searchsorted(cm, fill_ms, "right"))
            cols["s1"].append(np.full(len(j), b, np.int64))
            cols["prio"].append(mk.qv_window(int(k), close))
            cols["src"].append(np.full(len(j), src, np.int64))
            cols["close"].append(close)
            cols["j"].append(j)
    out = {}
    for x, v in cols.items():
        dt_ = np.float64 if x in ("d0", "prio") else np.int64
        out[x] = np.concatenate(v).astype(dt_) if v else np.zeros(0, dt_)
    return sort_cands(out)


def sort_cands(c: dict) -> dict:
    """Engine order: fill step; then 30-day quote volume, largest first (H 8); then pick number (W 7); then coin."""
    order = np.lexsort((c["coin"], c["src"], -c["prio"], c["t"]))
    return {x: np.asarray(v)[order] for x, v in c.items()}


# ------------------------------------------------------------------ the engine (numba)
# position state (one slot per coin: one position per coin, H 8)
F_Q, F_COST, F_REFQ, F_Q1, F_U, F_D0, F_STOP, F_NEXT, F_MARGIN, F_B, F_LIQ, F_EXT, F_LAST, F_FEES, F_FUND, F_LEV, \
    F_P0 = range(17)
NF = 17
P_OPEN, P_SIDE, P_TRIED, P_FILLED, P_BPTR, P_BEND, P_FPTR, P_FEND, P_SPTR, P_SEND, P_LARGE, P_REC, P_SRC, P_TIN, \
    P_CUT = range(15)
NPI = 15
# records (one per opened position)
RF_U, RF_PNL, RF_FEES, RF_FUND, RF_P0, RF_D0, RF_Q1, RF_XPX, RF_LEV, RF_PRICE, RF_EQ = range(11)
NRF = 11
RI_COIN, RI_SIDE, RI_TIN, RI_TOUT, RI_ADDS, RI_REASON, RI_CAND, RI_SRC, RI_LARGE, RI_CUT, RI_TRIED = range(11)
NRI = 11
# exit reasons, stop sources
EX_STOP, EX_GAP, EX_LIQ, EX_END, EX_COINEND, EX_BUST = range(6)
EXIT_NAMES = ("stop", "stop_gap_open", "liquidation", "period_end_marked", "coin_end", "bust_close")
SRC_INIT, SRC_ADD, SRC_CHAND = range(3)
STOP_SRC_NAMES = ("first_stop", "add_moved_stop", "chandelier")
# counters
SK_BUSY, SK_SIX, SK_DIR, SK_LEV, SK_MARGIN, SK_MINNOT, SK_RISK, SK_BAD = range(8)
SKIP_NAMES = ("coin_has_position", "six_positions", "large_group_direction", "no_leverage", "no_margin",
              "min_notional", "risk_cap", "bad_price")
CUT_LIQ, CUT_MARGIN, CUT_FREE = range(3)
CUT_NAMES = ("liquidity", "margin_budget", "free_wallet")
AS_RISK, AS_MARGIN, AS_FREE, AS_MINNOT = range(4)
ADD_SKIP_NAMES = ("risk_cap", "margin_budget", "free_wallet", "min_notional")
CAP_SIX, CAP_LL, CAP_LS, CAP_RISK = range(4)
CAP_NAMES = ("six_positions", "large_longs_3", "large_shorts_3", "risk_cap")
# parameter vector
PR_START, PR_R, PR_CAP, PR_TAKER, PR_SLIP, PR_LIQF, PR_BUST, PR_CHAND, PR_BDIV, PR_LEVMAX, PR_LIQMULT, PR_MAXPOS, \
    PR_MAXDIR, PR_NADDS = range(14)


@njit(cache=True)
def _choose_lev(N4, B, d0_frac, lev_max, liq_mult, n, cap, lev, mmr):
    """H 7.3: the smallest L in 1..lev_max with (i) L allowed by the bracket at N4, (ii) N4 / L <= B, (iii) 1/L - mmr
    >= liq_mult x D0 / P0; else the largest L meeting (i) and (iii); 0 = none."""
    b = -1
    for i in range(n):
        if N4 < cap[i]:
            b = i
            break
    if b < 0:
        return 0
    best = 0
    for L in range(1, lev_max + 1):
        if L <= lev[b] and (1.0 / L - mmr[b]) >= liq_mult * d0_frac:
            if N4 / L <= B * (1.0 + 1e-12):
                return L
            best = L
    return best


@njit(cache=True)
def _set_liq(k, ps, pi, n, cap, mmr, cum):
    """Binance isolated one-way liquidation price at the bracket of the entry notional."""
    notional = ps[k, F_COST]
    b = n - 1
    for i in range(n):
        if notional < cap[i]:
            b = i
            break
    Q = ps[k, F_Q]
    if pi[k, P_SIDE] > 0:
        ps[k, F_LIQ] = (ps[k, F_COST] - ps[k, F_MARGIN] - cum[b]) / (Q * (1.0 - mmr[b]))
    else:
        ps[k, F_LIQ] = (ps[k, F_COST] + ps[k, F_MARGIN] + cum[b]) / (Q * (1.0 + mmr[b]))


@njit(cache=True)
def _risk(k, ps, pi):
    """Open risk of a position: max(0, sum q_i (ref_i - stop)) (long; short mirror)."""
    v = pi[k, P_SIDE] * (ps[k, F_REFQ] - ps[k, F_Q] * ps[k, F_STOP])
    return v if v > 0.0 else 0.0


@njit(cache=True)
def _try_add(k, ref, ps, pi, acc, others, cap_abs, taker, slip, min_not, askip, acut, n, cap, mmr, cum):
    """H 7.4: one add of q at reference ``ref``; returns True when filled (stop moved, liquidation price updated)."""
    side = pi[k, P_SIDE]
    L = ps[k, F_LEV]
    afill = ref * (1.0 + side * slip)
    qa = ps[k, F_Q1]
    room = (ps[k, F_B] - ps[k, F_MARGIN]) * L / afill
    cutm = False
    if qa > room:
        qa = room
        cutm = True
    free = acc[0] - acc[1]
    cutf = False
    if qa * afill / L + taker * qa * afill > free:
        qa = free / (afill * (1.0 / L + taker))
        cutf = True
    if qa <= 0.0:
        if cutm:
            askip[AS_MARGIN] += 1
        else:
            askip[AS_FREE] += 1
        return False
    if qa * afill < min_not:
        askip[AS_MINNOT] += 1
        return False
    Qn = ps[k, F_Q] + qa
    refqn = ps[k, F_REFQ] + qa * ref
    sreq = (refqn - side * ps[k, F_U]) / Qn
    stop = ps[k, F_STOP]
    nstop = stop
    if side > 0 and sreq > stop:
        nstop = sreq
    if side < 0 and sreq < stop:
        nstop = sreq
    nrisk = side * (refqn - Qn * nstop)
    if nrisk < 0.0:
        nrisk = 0.0
    if others + nrisk > cap_abs * (1.0 + 1e-9):
        askip[AS_RISK] += 1
        return False
    fee = taker * qa * afill
    acc[0] -= fee
    acc[2] += fee
    ps[k, F_FEES] += fee
    mg = qa * afill / L
    ps[k, F_MARGIN] += mg
    acc[1] += mg
    ps[k, F_Q] = Qn
    ps[k, F_COST] += qa * afill
    ps[k, F_REFQ] = refqn
    if nstop != stop:
        ps[k, F_STOP] = nstop
        pi[k, P_SRC] = SRC_ADD
    pi[k, P_FILLED] += 1
    if cutm:
        acut[0] += 1
    if cutf:
        acut[1] += 1
    _set_liq(k, ps, pi, n, cap, mmr, cum)
    return True


@njit(cache=True)
def _bar(k, o, h, lo, ps, pi, acc, others, cap_abs, taker, slip, min_not, askip, acut, n_adds, n, cap, mmr, cum):
    """H 7.6 for one position on one 5m bar (long; short mirror): 1. open at / beyond the liquidation price ->
    liquidated at the open; 2. open at / beyond the stop -> exit at the open; 4. the bar reaches the next untried add
    level -> every add level it reaches fills in order first (each moving the stop and the liquidation price), also
    when the bar had reached the old stop; 3./4. then the low reaching the (moved) stop exits there, or the
    liquidation price when it lies inside the stop (5.). Returns (code, price): -1 none, EX_STOP, EX_GAP, EX_LIQ."""
    side = pi[k, P_SIDE]
    if side > 0:
        if o <= ps[k, F_LIQ]:
            return EX_LIQ, o
        if o <= ps[k, F_STOP]:
            return EX_GAP, o
        while pi[k, P_TRIED] < n_adds and h >= ps[k, F_NEXT]:
            lvl = ps[k, F_NEXT]
            ref = o if o >= lvl else lvl
            ok = _try_add(k, ref, ps, pi, acc, others, cap_abs, taker, slip, min_not, askip, acut, n, cap, mmr, cum)
            pi[k, P_TRIED] += 1
            ps[k, F_NEXT] = (ref if ok else lvl) + ps[k, F_D0]
        stop = ps[k, F_STOP]
        liq = ps[k, F_LIQ]
        if lo <= stop or lo <= liq:
            if liq > stop:
                return EX_LIQ, liq
            return EX_STOP, stop
    else:
        if o >= ps[k, F_LIQ]:
            return EX_LIQ, o
        if o >= ps[k, F_STOP]:
            return EX_GAP, o
        while pi[k, P_TRIED] < n_adds and lo <= ps[k, F_NEXT]:
            lvl = ps[k, F_NEXT]
            ref = o if o <= lvl else lvl
            ok = _try_add(k, ref, ps, pi, acc, others, cap_abs, taker, slip, min_not, askip, acut, n, cap, mmr, cum)
            pi[k, P_TRIED] += 1
            ps[k, F_NEXT] = (ref if ok else lvl) - ps[k, F_D0]
        stop = ps[k, F_STOP]
        liq = ps[k, F_LIQ]
        if h >= stop or h >= liq:
            if liq < stop:
                return EX_LIQ, liq
            return EX_STOP, stop
    return -1, 0.0


@njit(cache=True)
def _close(k, X, reason, t, ps, pi, rf, ri, acc, taker, slip):
    """Close the whole position at ``X`` (slippage against, taker fee) or liquidate it (whole isolated margin lost)."""
    side = pi[k, P_SIDE]
    Q = ps[k, F_Q]
    if reason == EX_LIQ:
        price_pnl = -ps[k, F_MARGIN]
        fee = 0.0
        xf = X
    else:
        xf = X * (1.0 - side * slip)
        price_pnl = side * (Q * xf - ps[k, F_COST])
        fee = taker * Q * xf
    acc[0] += price_pnl - fee
    acc[1] -= ps[k, F_MARGIN]
    acc[2] += fee
    ps[k, F_FEES] += fee
    rec = pi[k, P_REC]
    rf[rec, RF_PNL] = price_pnl - ps[k, F_FEES] + ps[k, F_FUND]
    rf[rec, RF_PRICE] = price_pnl
    rf[rec, RF_FEES] = ps[k, F_FEES]
    rf[rec, RF_FUND] = ps[k, F_FUND]
    rf[rec, RF_XPX] = xf
    ri[rec, RI_TOUT] = t
    ri[rec, RI_ADDS] = pi[k, P_FILLED]
    ri[rec, RI_TRIED] = pi[k, P_TRIED]
    ri[rec, RI_REASON] = reason
    ri[rec, RI_SRC] = pi[k, P_SRC]
    pi[k, P_OPEN] = 0


@njit(cache=True)
def _engine(prm, month_t0, b_off, b_t, b_o, b_h, b_l, b_c, b_qv, f_off, f_t, f_rate, coin_end_t, min_not,
            br_n, br_cap, br_lev, br_mmr, br_cum, large, s_ct, s_h, s_l, s_atr,
            c_t, c_bi, c_coin, c_side, c_d0, c_s0, c_s1):
    start_eq = prm[PR_START]
    r = prm[PR_R]
    risk_cap = prm[PR_CAP]
    taker = prm[PR_TAKER]
    slip = prm[PR_SLIP]
    liq_frac = prm[PR_LIQF]
    bust_eq = prm[PR_BUST] * start_eq
    chand = prm[PR_CHAND]
    b_div = prm[PR_BDIV]
    lev_max = int(prm[PR_LEVMAX])
    liq_mult = prm[PR_LIQMULT]
    max_pos = int(prm[PR_MAXPOS])
    max_dir = int(prm[PR_MAXDIR])
    n_adds = int(prm[PR_NADDS])
    K = len(b_off) - 1
    n_m = len(month_t0) - 1
    T = month_t0[n_m]
    n_days = T // 288
    nc = len(c_t)
    ps = np.zeros((K, NF))
    pi = np.zeros((K, NPI), np.int64)
    rf = np.zeros((max(nc, 1), NRF))
    ri = np.zeros((max(nc, 1), NRI), np.int64)
    month_eq = np.zeros(n_m)
    month_pos = np.zeros(n_m, np.int64)
    day_eq = np.zeros(n_days)
    skip = np.zeros(8, np.int64)
    cut = np.zeros(3, np.int64)
    askip = np.zeros(4, np.int64)
    acut = np.zeros(2, np.int64)
    capt = np.zeros(4, np.int64)
    openl = np.zeros(max_pos + 1, np.int64)
    cur = np.zeros(max_pos + 1, np.int64)
    acc = np.zeros(4)            # wallet, isolated margins, fees, funding
    acc[0] = start_eq
    npos = 0
    nlL = 0
    nlS = 0
    nrec = 0
    ci = 0
    m = 0
    E = start_eq
    E_prev = start_eq
    peak = start_eq
    maxdd = 0.0
    bust_t = -1
    last_t = -1
    for t in range(T):
        last_t = t
        while m < n_m - 1 and t >= month_t0[m + 1]:
            m += 1
        # (a) chandelier updates of signal bars closed at or before this bar's open (H 7.5: from the next 5m bar)
        for ii in range(npos):
            k = openl[ii]
            j = pi[k, P_SPTR]
            while j < pi[k, P_SEND] and s_ct[j] <= t:
                if pi[k, P_SIDE] > 0:
                    if s_h[j] > ps[k, F_EXT]:
                        ps[k, F_EXT] = s_h[j]
                    ch = ps[k, F_EXT] - chand * s_atr[j]
                    if ch > ps[k, F_STOP]:
                        ps[k, F_STOP] = ch
                        pi[k, P_SRC] = SRC_CHAND
                else:
                    if s_l[j] < ps[k, F_EXT]:
                        ps[k, F_EXT] = s_l[j]
                    ch = ps[k, F_EXT] + chand * s_atr[j]
                    if ch < ps[k, F_STOP]:
                        ps[k, F_STOP] = ch
                        pi[k, P_SRC] = SRC_CHAND
                j += 1
            pi[k, P_SPTR] = j
        # (b) entries filling at this bar's open, decided on the state at the previous close (H 7.1-7.3, H 8)
        while ci < nc and c_t[ci] < t:
            ci += 1
        while ci < nc and c_t[ci] == t:
            k = c_coin[ci]
            side = c_side[ci]
            if pi[k, P_OPEN] == 1:
                skip[SK_BUSY] += 1
                ci += 1
                continue
            if npos >= max_pos:
                skip[SK_SIX] += 1
                ci += 1
                continue
            lg = large[m, k]
            if lg == 1 and ((side > 0 and nlL >= max_dir) or (side < 0 and nlS >= max_dir)):
                skip[SK_DIR] += 1
                ci += 1
                continue
            bi = c_bi[ci]
            P0 = b_o[bi]
            D0 = c_d0[ci]
            if not (P0 > 0.0) or not (D0 > 0.0) or not (E_prev > 0.0):
                skip[SK_BAD] += 1
                ci += 1
                continue
            U = r * E_prev
            q = U / D0
            cutf = 0
            lc = liq_frac * b_qv[bi]
            if q * P0 > lc:
                q = lc / P0
                cut[CUT_LIQ] += 1
                cutf |= 1
            N4 = 4.0 * q * P0
            B = E_prev / b_div
            nb = br_n[k]
            L = _choose_lev(N4, B, D0 / P0, lev_max, liq_mult, nb, br_cap[k], br_lev[k], br_mmr[k])
            if L == 0:
                skip[SK_LEV] += 1
                ci += 1
                continue
            fill = P0 * (1.0 + side * slip)
            if q * fill / L > B:
                q = B * L / fill
                cut[CUT_MARGIN] += 1
                cutf |= 2
            free = acc[0] - acc[1]
            if q * fill / L + taker * q * fill > free:
                q = free / (fill * (1.0 / L + taker))
                cut[CUT_FREE] += 1
                cutf |= 4
            if q <= 0.0:
                skip[SK_MARGIN] += 1
                ci += 1
                continue
            if q * fill < min_not[k]:
                skip[SK_MINNOT] += 1
                ci += 1
                continue
            tot = 0.0
            for ii in range(npos):
                tot += _risk(openl[ii], ps, pi)
            if tot + q * D0 > risk_cap * E_prev * (1.0 + 1e-9):
                skip[SK_RISK] += 1
                ci += 1
                continue
            fee = taker * q * fill
            for x in range(NF):
                ps[k, x] = 0.0
            for x in range(NPI):
                pi[k, x] = 0
            pi[k, P_OPEN] = 1
            pi[k, P_SIDE] = side
            ps[k, F_Q] = q
            ps[k, F_Q1] = q
            ps[k, F_COST] = q * fill
            ps[k, F_REFQ] = q * P0
            ps[k, F_U] = U
            ps[k, F_D0] = D0
            ps[k, F_P0] = P0
            ps[k, F_STOP] = P0 - side * D0
            ps[k, F_NEXT] = P0 + side * D0
            ps[k, F_B] = B
            ps[k, F_LEV] = L
            ps[k, F_MARGIN] = q * fill / L
            ps[k, F_FEES] = fee
            ps[k, F_LAST] = P0
            ps[k, F_EXT] = -np.inf if side > 0 else np.inf
            acc[0] -= fee
            acc[1] += ps[k, F_MARGIN]
            acc[2] += fee
            _set_liq(k, ps, pi, nb, br_cap[k], br_mmr[k], br_cum[k])
            pi[k, P_BPTR] = bi
            pi[k, P_BEND] = b_off[k + 1]
            f0 = f_off[k]
            pi[k, P_FPTR] = f0 + np.searchsorted(f_t[f0:f_off[k + 1]], t)
            pi[k, P_FEND] = f_off[k + 1]
            pi[k, P_SPTR] = c_s0[ci]
            pi[k, P_SEND] = c_s1[ci]
            pi[k, P_LARGE] = lg
            pi[k, P_REC] = nrec
            pi[k, P_SRC] = SRC_INIT
            pi[k, P_TIN] = t
            pi[k, P_CUT] = cutf
            rf[nrec, RF_U] = U
            rf[nrec, RF_EQ] = E_prev
            rf[nrec, RF_P0] = P0
            rf[nrec, RF_D0] = D0
            rf[nrec, RF_Q1] = q
            rf[nrec, RF_LEV] = L
            ri[nrec, RI_COIN] = k
            ri[nrec, RI_SIDE] = side
            ri[nrec, RI_TIN] = t
            ri[nrec, RI_TOUT] = -1
            ri[nrec, RI_CAND] = ci
            ri[nrec, RI_LARGE] = lg
            ri[nrec, RI_CUT] = cutf
            nrec += 1
            openl[npos] = k
            npos += 1
            if lg == 1:
                if side > 0:
                    nlL += 1
                else:
                    nlS += 1
            ci += 1
        if npos > 0:
            month_pos[m] = 1
        # (c) every open position on this 5m bar (H 7.6), coin end, funding
        ncur = npos
        for ii in range(npos):
            cur[ii] = openl[ii]
        for ii in range(ncur):
            k = cur[ii]
            if pi[k, P_OPEN] == 0:
                continue
            side = pi[k, P_SIDE]
            bp = pi[k, P_BPTR]
            closed = False
            if bp < pi[k, P_BEND] and b_t[bp] == t:
                pi[k, P_BPTR] = bp + 1
                others = 0.0                       # other positions' open risk: only needed when an add is reached
                if pi[k, P_TRIED] < n_adds and ((side > 0 and b_h[bp] >= ps[k, F_NEXT]) or
                                                (side < 0 and b_l[bp] <= ps[k, F_NEXT])):
                    for jj in range(npos):
                        kk = openl[jj]
                        if kk != k and pi[kk, P_OPEN] == 1:
                            others += _risk(kk, ps, pi)
                code, X = _bar(k, b_o[bp], b_h[bp], b_l[bp], ps, pi, acc, others, risk_cap * E_prev, taker, slip,
                               min_not[k], askip, acut, n_adds, br_n[k], br_cap[k], br_mmr[k], br_cum[k])
                if code >= 0:
                    _close(k, X, code, t, ps, pi, rf, ri, acc, taker, slip)
                    closed = True
                else:
                    ps[k, F_LAST] = b_c[bp]
                    if t == coin_end_t[k]:
                        _close(k, b_c[bp], EX_COINEND, t, ps, pi, rf, ri, acc, taker, slip)
                        closed = True
            if not closed:
                fp = pi[k, P_FPTR]
                while fp < pi[k, P_FEND] and f_t[fp] <= t:
                    cash = -side * f_rate[fp] * ps[k, F_Q] * ps[k, F_LAST]
                    acc[0] += cash
                    acc[3] += cash
                    ps[k, F_FUND] += cash
                    fp += 1
                pi[k, P_FPTR] = fp
            if closed:
                for jj in range(npos):
                    if openl[jj] == k:
                        for kk in range(jj, npos - 1):
                            openl[kk] = openl[kk + 1]
                        npos -= 1
                        break
                if pi[k, P_LARGE] == 1:
                    if side > 0:
                        nlL -= 1
                    else:
                        nlS -= 1
        # (d) mark to market at this 5m close (H 10): drawdown, bust, caps, month and day ends
        E = acc[0]
        tot = 0.0
        for ii in range(npos):
            k = openl[ii]
            E += pi[k, P_SIDE] * (ps[k, F_Q] * ps[k, F_LAST] - ps[k, F_COST])
            tot += _risk(k, ps, pi)
        if E < bust_eq:
            for ii in range(npos):
                k = openl[ii]
                _close(k, ps[k, F_LAST], EX_BUST, t, ps, pi, rf, ri, acc, taker, slip)
            npos = 0
            E = acc[0]
            bust_t = t
        if E > peak:
            peak = E
        if peak > 0.0 and (peak - E) / peak > maxdd:
            maxdd = (peak - E) / peak
        if npos >= max_pos:
            capt[CAP_SIX] += 1
        if nlL >= max_dir:
            capt[CAP_LL] += 1
        if nlS >= max_dir:
            capt[CAP_LS] += 1
        if npos > 0 and tot >= 0.999 * risk_cap * E:
            capt[CAP_RISK] += 1
        if t == month_t0[m + 1] - 1:
            month_eq[m] = E
        if (t + 1) % 288 == 0:
            day_eq[(t + 1) // 288 - 1] = E
        E_prev = E
        if bust_t >= 0:
            for mm in range(m, n_m):
                month_eq[mm] = E
            d0 = (t + 1) // 288
            for dd in range(d0, n_days):
                day_eq[dd] = E
            break
    # open positions at the period end: marked at the last close, flagged (not closed, no exit cost)
    for ii in range(npos):
        k = openl[ii]
        rec = pi[k, P_REC]
        un = pi[k, P_SIDE] * (ps[k, F_Q] * ps[k, F_LAST] - ps[k, F_COST])
        rf[rec, RF_PNL] = un - ps[k, F_FEES] + ps[k, F_FUND]
        rf[rec, RF_PRICE] = un
        rf[rec, RF_FEES] = ps[k, F_FEES]
        rf[rec, RF_FUND] = ps[k, F_FUND]
        rf[rec, RF_XPX] = ps[k, F_LAST]
        ri[rec, RI_TOUT] = last_t
        ri[rec, RI_ADDS] = pi[k, P_FILLED]
        ri[rec, RI_TRIED] = pi[k, P_TRIED]
        ri[rec, RI_REASON] = EX_END
        ri[rec, RI_SRC] = pi[k, P_SRC]
    stats = np.zeros(8)
    stats[0] = maxdd
    stats[1] = bust_t
    stats[2] = acc[2]
    stats[3] = acc[3]
    stats[4] = E
    stats[5] = nrec
    stats[6] = T
    return month_eq, month_pos, day_eq, rf[:nrec], ri[:nrec], skip, cut, askip, acut, capt, stats


def params(r: float = R_BASE, cost: str = "base", risk_cap: float = RISK_CAP, start: float = START_WALLET,
           b_div: float = B_DIV):
    taker, slip = COSTS[cost]
    p = np.zeros(14)
    p[PR_START], p[PR_R], p[PR_CAP], p[PR_TAKER], p[PR_SLIP] = start, r, risk_cap, taker, slip
    p[PR_LIQF], p[PR_BUST], p[PR_CHAND], p[PR_BDIV], p[PR_LEVMAX] = LIQ_FRAC, BUST_FRAC, CHAND_MULT, b_div, LEV_MAX
    p[PR_LIQMULT], p[PR_MAXPOS], p[PR_MAXDIR], p[PR_NADDS] = LIQ_MULT, MAX_POS, MAX_DIR, N_ADDS
    return p


def simulate(mk: Market, bank: Bank, cands: dict, r: float = R_BASE, cost: str = "base",
             risk_cap: float = RISK_CAP, start: float = START_WALLET, prm: np.ndarray | None = None,
             b_div: float = B_DIV) -> tuple:
    br = mk.br
    p = params(r, cost, risk_cap, start, b_div) if prm is None else prm
    return _engine(p, mk.month_t0, mk.b_off, mk.b_t, mk.b_o, mk.b_h, mk.b_l, mk.b_c,
                   mk.b_qv, mk.f_off, mk.f_t, mk.f_rate, mk.coin_end_t, br["min_notional"], br["n"], br["cap"],
                   br["lev"], br["mmr"], br["cum"], mk.large, bank.s_ct, bank.s_h, bank.s_l, bank.s_atr,
                   cands["t"], cands["bi"], cands["coin"], cands["side"], cands["d0"], cands["s0"], cands["s1"])


# ------------------------------------------------------------------ metrics (H 10)
def summarize(mk: Market, raw: tuple, start: float = START_WALLET, detail: bool = True,
              days: bool | None = None) -> dict:
    """The H 10 metric set of one run. ``detail``: the per-year / side / group splits and positions per month;
    ``days`` (default = detail): the daily marked equity path."""
    days = detail if days is None else days
    month_eq, month_pos, day_eq, rf, ri, skip, cut, askip, acut, capt, st = raw
    n_m = len(month_eq)
    eq0 = np.r_[start, month_eq[:-1]]
    with np.errstate(divide="ignore", invalid="ignore"):
        M = np.where(eq0 > 0, month_eq / eq0, 1.0)
    lnM = np.log(np.maximum(M, 1e-12))
    bust_t = int(st[1])
    bust = bust_t >= 0
    bust_m = int(np.searchsorted(mk.month_t0, bust_t, "right") - 1) if bust else None
    n_pos = len(ri)
    out = {"months": n_m, "M": M.tolist(), "lnM": lnM.tolist(),
           "mean_lnM": float(lnM.mean()) if n_m else 0.0, "median_M": float(np.median(M)) if n_m else 1.0,
           "q25_lnM": float(np.quantile(lnM, 0.25)) if n_m else 0.0,
           "median_lnM": float(np.median(lnM)) if n_m else 0.0,
           "q75_lnM": float(np.quantile(lnM, 0.75)) if n_m else 0.0,
           "share_M_ge_2": float((M >= 2).mean()) if n_m else 0.0,
           "share_M_ge_10": float((M >= 10).mean()) if n_m else 0.0,
           "share_M_ge_30": float((M >= 30).mean()) if n_m else 0.0,
           "share_M_lt_0_9": float((M < 0.9).mean()) if n_m else 0.0,
           "worst_month": float(M.min()) if n_m else 1.0, "max_dd": float(st[0]), "bust": bool(bust),
           "bust_month": mk.months[bust_m] if bust else None, "end_multiple": float(st[4] / start),
           "n_positions": int(n_pos), "months_with_position": int(month_pos.sum()),
           "share_months_with_position": float(month_pos.mean()) if n_m else 0.0,
           "fees": float(st[2]), "funding": float(st[3]),
           "skipped": {SKIP_NAMES[i]: int(skip[i]) for i in range(len(SKIP_NAMES))},
           "cut": {CUT_NAMES[i]: int(cut[i]) for i in range(len(CUT_NAMES))},
           "adds_skipped": {ADD_SKIP_NAMES[i]: int(askip[i]) for i in range(len(ADD_SKIP_NAMES))},
           "adds_cut": {"margin_budget": int(acut[0]), "free_wallet": int(acut[1])},
           "time_at_cap": {CAP_NAMES[i]: float(capt[i] / max(st[6], 1)) for i in range(len(CAP_NAMES))},
           "funding_missing_months": {s: v for s, v in mk.funding_missing.items() if v}}
    if n_pos:
        pnl, U = rf[:, RF_PNL], rf[:, RF_U]
        pu = pnl / U
        adds = ri[:, RI_ADDS]
        pos_sorted = np.sort(pnl)[::-1]
        top = pos_sorted[:max(1, int(math.ceil(0.1 * n_pos)))].sum()
        gross = pnl[pnl > 0].sum()
        out.update({"positions_per_month": n_pos / n_m, "adds_per_month": float(adds.sum() / n_m),
                    "share_add_level": [float((adds >= a).mean()) for a in (1, 2, 3)],
                    "mean_pnl_U": float(pu.mean()), "median_pnl_U": float(np.median(pu)),
                    "win_share": float((pnl > 0).mean()),
                    "top10_share_of_profit": float(top / gross) if gross > 0 else None,
                    "exit_reasons": {EXIT_NAMES[i]: int((ri[:, RI_REASON] == i).sum()) for i in range(len(EXIT_NAMES))},
                    "exit_stop_source": {STOP_SRC_NAMES[i]: int((ri[:, RI_SRC] == i).sum())
                                         for i in range(len(STOP_SRC_NAMES))},
                    "open_at_end": int((ri[:, RI_REASON] == EX_END).sum()),
                    "leverage_median": float(np.median(rf[:, RF_LEV]))})
        # the bet actually taken (W 7): first unit's risk q x D0 over the marked equity at its entry, and the cuts
        real = rf[:, RF_Q1] * rf[:, RF_D0] / np.where(rf[:, RF_EQ] > 0, rf[:, RF_EQ], np.nan)
        tried = ri[:, RI_TRIED].sum()
        out.update({"realized_unit_risk": {"median": float(np.nanmedian(real)), "mean": float(np.nanmean(real)),
                                           "q25": float(np.nanquantile(real, 0.25)),
                                           "q75": float(np.nanquantile(real, 0.75))},
                    "share_first_unit_cut": float((ri[:, RI_CUT] != 0).mean()),
                    "share_first_unit_cut_by": {CUT_NAMES[i]: float(((ri[:, RI_CUT] >> i) & 1).mean())
                                                for i in range(len(CUT_NAMES))},
                    "share_adds_filled_of_tried": float(adds.sum() / tried) if tried else None})
        if detail:
            t_in_ms = mk.start + ri[:, RI_TIN] * FIVE
            years = np.asarray([dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc).year for x in t_in_ms])
            sym = np.asarray(mk.syms)[ri[:, RI_COIN]]
            old = np.isin(sym, OLD_SIX)

            def grp(mask):
                return {"n": int(mask.sum()), "pnl": float(pnl[mask].sum()), "pnl_U": float(pu[mask].sum()),
                        "win_share": float((pnl[mask] > 0).mean()) if mask.any() else None}
            out["by_year"] = {int(y): grp(years == y) for y in np.unique(years)}
            out["by_side"] = {"long": grp(ri[:, RI_SIDE] > 0), "short": grp(ri[:, RI_SIDE] < 0)}
            out["by_group"] = {"old_six": grp(old), "new": grp(~old)}
            mi = np.searchsorted(mk.month_t0, ri[:, RI_TIN], "right") - 1
            out["positions_by_month"] = np.bincount(mi, minlength=n_m).tolist()
    else:
        out.update({"positions_per_month": 0.0, "adds_per_month": 0.0, "share_add_level": [0.0, 0.0, 0.0],
                    "mean_pnl_U": None, "median_pnl_U": None, "win_share": None, "top10_share_of_profit": None,
                    "realized_unit_risk": None, "share_first_unit_cut": None, "share_first_unit_cut_by": None,
                    "share_adds_filled_of_tried": None})
    if days:
        out["day_eq"] = [round(float(x), 4) for x in day_eq]
    return out


# ------------------------------------------------------------------ one system / one candidate list
def run_signals(mk: Market, parts: list, r: float = R_BASE, cost: str = "base", risk_cap: float = RISK_CAP,
                detail: bool = False, days: bool | None = None, b_div: float = B_DIV) -> dict:
    tfs = tuple(sorted({sig["tf"] for sig, _ in parts}, key=TF_ORDER.index))
    bank = bank_for(mk, tfs)
    cands = build_cands(mk, bank, parts)
    out = summarize(mk, simulate(mk, bank, cands, r, cost, risk_cap, b_div=b_div), detail=detail, days=days)
    out["candidates"] = int(len(cands["t"]))
    return out


def run_system(mk: Market, spec: dict, r: float = R_BASE, cost: str = "base", gate: str | None = None,
               risk_cap: float = RISK_CAP, detail: bool = False, days: bool | None = None) -> dict:
    sig = system_signals(mk, spec, gate)
    out = run_signals(mk, [(sig, 0)], r, cost, risk_cap, detail, days)
    out["signal_counts"] = dict(sig["counts"])
    return out


# ------------------------------------------------------------------ controls (H 12), bootstrap, seed rank, BH (H 13)
def control_pool(mk: Market, tf: str, k: int) -> np.ndarray:
    """H 12 (a) pool: the coin's signal bars with close in the period, a known 장세 label, ATR14 > 0 and a fill bar."""
    key = (mk.key, tf, k)
    pool = _POOLS.get(key)
    if pool is None:
        ser = series(mk.syms[k], tf)
        cm = ser.bars.close_ms
        _, f_ok = fill_index(mk, k, ser)
        ok = (cm >= mk.start) & (cm < mk.end) & (ser.code != UNKNOWN) & np.isfinite(ser.atr) & (ser.atr > 0) & f_ok
        pool = _POOLS[key] = np.flatnonzero(ok)
    return pool


def control_a(mk: Market, sig: dict, rng: np.random.Generator) -> dict:
    """(a) random times: per coin and side the pick's number of gated signals, drawn without replacement from the
    coin's pool (one joint draw per coin; the first n_long are long). Not gated."""
    K, J, S = [], [], []
    for k in range(mk.K):
        sel = sig["k"] == k
        nl = int((sig["side"][sel] > 0).sum())
        ns = int((sig["side"][sel] < 0).sum())
        if nl + ns == 0:
            continue
        pool = control_pool(mk, sig["tf"], k)
        n = min(nl + ns, len(pool))
        draw = rng.choice(pool, size=n, replace=False) if n else np.zeros(0, np.int64)
        nl_ = min(nl, n)
        K.append(np.full(n, k, np.int64))
        J.append(np.asarray(draw, np.int64))
        S.append(np.r_[np.ones(nl_, np.int64), -np.ones(n - nl_, np.int64)])
    cat = lambda xs: np.concatenate(xs) if xs else np.zeros(0, np.int64)  # noqa: E731
    return {"tf": sig["tf"], "k": cat(K), "j": cat(J), "side": cat(S)}


def control_b(sig: dict, rng: np.random.Generator) -> dict:
    """(b) coin-flip sides: the pick's gated signals, same coins and times, each side by a fair coin."""
    flips = rng.random(len(sig["k"])) < 0.5
    return {"tf": sig["tf"], "k": sig["k"].copy(), "j": sig["j"].copy(), "side": np.where(flips, 1, -1)}


def boot_p(d, seed: int, n_boot: int | None = None) -> float:
    """One-sided month-block bootstrap (H 13): resample the months with replacement; p = (1 + resamples with mean
    d <= 0) / (n_boot + 1)."""
    n_boot = N_BOOT if n_boot is None else n_boot
    d = np.asarray(d, float)
    if not len(d):
        return 1.0
    rng = np.random.Generator(np.random.PCG64(seed))
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    means = d[idx].mean(axis=1)
    return float((1 + int((means <= 0).sum())) / (n_boot + 1))


def seed_rank_p(pick_mean: float, seed_means) -> float:
    """(1 + seeds whose mean monthly ln M >= the pick's) / (n + 1) (H 13 P2 ii)."""
    s = np.asarray(seed_means, float)
    return float((1 + int((s >= pick_mean).sum())) / (len(s) + 1))


def bh(pvals, q: float = BH_Q) -> list:
    """Benjamini-Hochberg (W 6): k* = the largest k with p_(k) <= q k / K; every p <= p_(k*) is significant."""
    p = np.asarray([1.0 if (x is None or not np.isfinite(x)) else x for x in pvals], float)
    K = len(p)
    if not K:
        return []
    order = np.sort(p)
    ok = order <= q * np.arange(1, K + 1) / K
    if not ok.any():
        return [False] * K
    thr = order[np.flatnonzero(ok).max()]
    return [bool(x <= thr) for x in p]


def run_controls(mk: Market, spec: dict, study: str, r: float, procs: int, n_seeds: int | None = None) -> dict:
    """Both controls x n_seeds for one pick on one market (seed parts of H 12 / W 6)."""
    n_seeds = N_SEEDS if n_seeds is None else n_seeds
    sig = system_signals(mk, spec)
    tasks = [(mk.key, spec, study, ctl, s, r) for ctl in ("a", "b") for s in range(1, n_seeds + 1)]
    _G["mk"][mk.key] = mk
    res = pmap(_control_task, tasks, procs, label=f"controls {spec['id']} {mk.period} r={r:g}")
    out = {"a": [], "b": []}
    for (_, _, _, ctl, s, _), lnM in zip(tasks, res):
        out[ctl].append(lnM)
    out["a"], out["b"] = np.asarray(out["a"]), np.asarray(out["b"])
    out["gated"] = int(len(sig["k"]))
    return out


def control_seed_parts(study: str, spec: dict, ctl: str, period: str, r: float, s) -> tuple:
    if study == "v1":
        return (SEED_TAG["v1"], ctl, period, float(r), s)
    return (SEED_TAG["wide"], spec["id"], ctl, period, float(r), s)


def _control_task(task) -> list:
    mkey, spec, study, ctl, s, r = task
    mk = _G["mk"][mkey]
    sig = system_signals(mk, spec)
    rng = rng_of(*control_seed_parts(study, spec, ctl, mk.period, r, s))
    csig = control_a(mk, sig, rng) if ctl == "a" else control_b(sig, rng)
    return run_signals(mk, [(csig, 0)], r)["lnM"]


def judge(base: dict, cost2: dict, ctl: dict | None, study: str, spec: dict, period: str, r: float) -> dict:
    """H 13 checks for one pick (P2 split for wide, W 6)."""
    n_m = base["months"]
    lnM = np.asarray(base["lnM"])
    res = {"P0": bool(base["n_positions"] >= POS_PER_MONTH * n_m and base["share_months_with_position"] >= MONTH_COVER
                      and not base["bust"]),
           "P1": bool(base["median_M"] >= 1.0 and base["mean_lnM"] > 0),
           "P3": bool(cost2["median_M"] >= 1.0 and cost2["mean_lnM"] > 0),     # H 13 (both tests of P1 at cost x2)
           "P4": bool(base["max_dd"] < DD_MAX)}
    if ctl is not None:
        for c in ("a", "b"):
            seeds = ctl[c]
            d = lnM - seeds.mean(axis=0)
            parts = control_seed_parts(study, spec, c, period, r, "boot")
            res[f"p_{c}"] = boot_p(d, seed_int(*parts))
            res[f"mean_d_{c}"] = float(d.mean())
            res[f"rank_p_{c}"] = seed_rank_p(base["mean_lnM"], seeds.mean(axis=1))
            res[f"rank_ok_{c}"] = bool(res[f"rank_p_{c}"] < P_ALPHA)
            res[f"P2_{c}"] = bool(res[f"mean_d_{c}"] > 0 and res[f"p_{c}"] < P_ALPHA and res[f"rank_ok_{c}"])
        res["P2"] = bool(res["P2_a"] and res["P2_b"])
        res["p"] = max(res["p_a"], res["p_b"])
    return res


# ------------------------------------------------------------------ parallel map (fork: workers inherit the data)
_G: dict = {"mk": {}}
MAX_RESTARTS = 5
PROGRESS_EVERY_S = 60.0


def _progress(label: str, done: int, n: int, t0: float, last: float) -> float:
    now = time.time()
    if label and (now - last >= PROGRESS_EVERY_S or (done == n and now - t0 >= 5.0)):
        print(f"[{label}] {done}/{n} done, {now - t0:.0f}s", flush=True)
        return now
    return last


def pmap(fn, tasks: list, procs: int, label: str = "") -> list:
    """``[fn(t) for t in tasks]`` in ``procs`` forked processes (workers inherit the loaded data), results in task
    order. Progress is printed every minute. A worker that dies (out of memory, killed) breaks the pool: the pool is
    rebuilt with fewer workers and only the unfinished tasks are sent again, at most MAX_RESTARTS times, then the
    step stops with a message (it never hangs). An exception inside ``fn`` stops the step at once."""
    n = len(tasks)
    t0 = last = time.time()
    if procs <= 1 or n <= 1:
        out = []
        for i, t in enumerate(tasks):
            out.append(fn(t))
            last = _progress(label, i + 1, n, t0, last)
        return out
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from concurrent.futures.process import BrokenProcessPool
    ctx = mp.get_context("fork")
    res: dict = {}
    workers = min(procs, n)
    for attempt in range(MAX_RESTARTS + 1):
        todo = [i for i in range(n) if i not in res]
        if not todo:
            break
        ex = ProcessPoolExecutor(min(workers, len(todo)), mp_context=ctx)
        futs = {}
        try:
            futs = {ex.submit(fn, tasks[i]): i for i in todo}
            for f in as_completed(futs):
                res[futs[f]] = f.result()
                last = _progress(label, len(res), n, t0, last)
            ex.shutdown(wait=True)
            break
        except BrokenProcessPool:
            for f, i in futs.items():                 # keep what finished before the pool broke
                if f.done() and not f.cancelled() and f.exception() is None:
                    res[i] = f.result()
            ex.shutdown(wait=False, cancel_futures=True)
            workers = max(1, workers * 3 // 4)
            print(f"[{label or 'pmap'}] a worker died; {n - len(res)} of {n} left, restarting with {workers} "
                  f"workers ({attempt + 1}/{MAX_RESTARTS})", flush=True)
        except BaseException:
            ex.shutdown(wait=False, cancel_futures=True)
            raise
    if len(res) < n:
        raise SystemExit(f"[{label or 'pmap'}] workers keep dying (memory?): stopped with {n - len(res)} of {n} "
                         "unfinished")
    return [res[i] for i in range(n)]


# ------------------------------------------------------------------ systems
def v1_spec(name: str, tf: str, value=None) -> dict:
    par, main, _ = V1_ENTRIES[name]
    v = main if value is None else value
    sid = f"v1:{name}:{tf}" + ("" if v == main else f":{par}={v:g}")
    return {"id": sid, "family": "F1", "name": name, "strategy": name, "kind": "hunt", "tf": tf, "gate": "G1",
            "combo": {par: v}}


def v1_systems() -> list:
    """H 5 order: E1-1h, E1-4h, E2-1h, E2-4h, E3-1h, E3-4h."""
    return [v1_spec(n, tf) for n in V1_ENTRIES for tf in V1_TFS]


def wide_systems() -> list:
    return list(_ew().systems())


def is_ds(spec: dict) -> bool:
    return spec.get("kind") == "ds"


# ------------------------------------------------------------------ selection (H 11, W 5)
def v1_choose(rows: dict) -> dict:
    """H 11.2 on {system id: {main, lo, hi, one}} summaries (r = 0.5% main / neighbours, r = 1% main)."""
    table = []
    for i, spec in enumerate(v1_systems()):
        rr = rows[spec["id"]]
        main = rr["main"]
        meds = [0.0 if x["bust"] else x["median_M"] for x in (main, rr["lo"], rr["hi"])]
        means = [x["mean_lnM"] for x in (main, rr["lo"], rr["hi"])]
        elig = bool(main["n_positions"] >= POS_PER_MONTH * main["months"] and main["mean_lnM"] > 0
                    and not main["bust"])
        table.append({"id": spec["id"], "order": i, "eligible": elig, "plateau": float(np.median(meds)),
                      "median_mean_lnM": float(np.median(means))})
    key = lambda x: (-x["plateau"], -x["median_mean_lnM"], x["order"])  # noqa: E731
    elig = sorted([x for x in table if x["eligible"]], key=key)
    if elig:
        return {"pick": elig[0]["id"], "label": "pick", "table": table}
    best = sorted(table, key=key)[0]
    return {"pick": best["id"], "label": "no pick, fail", "table": table}


def wide_eligible(base: dict, cost2: dict) -> tuple:
    why = []
    if base["n_positions"] < POS_PER_MONTH * base["months"]:
        why.append("positions")
    if not base["mean_lnM"] > 0:
        why.append("mean_lnM")
    if base["bust"]:
        why.append("bust")
    if not cost2["mean_lnM"] > 0:
        why.append("cost_x2")
    return (not why), why


def wide_choose(rows: list, k_picks: int = K_PICKS) -> dict:
    """W 5: order the eligible F1-F3 systems by score (mean ln M), ties median M, family, name, timeframe, G1 before
    NONE; take one per strategy name until K. F4 rows are a read only (their numbers were chosen after this test
    period was seen) and never a pick, also not in the 'no pick' fallback."""
    fam = {"F1": 0, "F2": 1, "F3": 2, "F4": 3}
    gate = {"G1": 0, "NONE": 1}

    def key(x):
        return (-x["score"], -x["median_M"], fam[x["family"]], x["name"], TF_ORDER.index(x["tf"]), gate[x["gate"]],
                x.get("rank") or 0)
    cand = [x for x in rows if x["family"] in PICK_FAMILIES]
    elig = sorted([x for x in cand if x["eligible"]], key=key)
    picks, names = [], set()
    for x in elig:
        if x["strategy"] in names:
            continue
        names.add(x["strategy"])
        picks.append(x["id"])
        if len(picks) == k_picks:
            break
    if picks:
        return {"picks": picks, "label": "picks"}
    best = sorted(cand, key=key)[0] if cand else None
    return {"picks": [best["id"]] if best else [], "label": "no pick, fail"}


# ------------------------------------------------------------------ study steps
def _stamp(study: str, pin: dict | None) -> dict:
    return {"study": study, "git_commit": git_commit(), "pin": pin, "written_utc": ms_str(int(time.time() * 1000)),
            "choices": CHOICES}


def _write_json(path: str, obj) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
        fh.write("\n")
    os.replace(tmp, path)
    return sha256_file(path)


def _universe_and_data(args, end_key: str) -> tuple:
    """H 2 before any step: free disk, the universe, the data up to the step's end, and the data identity against
    research/hunt/data_manifest.json (any difference stops the step)."""
    data = args.data or os.environ.get("HUNT_DATA")
    if not data:
        raise SystemExit("--data <coins30 folder> (or $HUNT_DATA) is needed")
    disk_check(os.path.join(ROOT, OUT_REL[args.study]), private_dir(args))
    syms = load_universe(data)
    end = day_ms(PERIODS[end_key][1])
    counts = load_study_data(data, syms, end)
    bad = data_identity_problems(counts, {s: c.get("funding_content_sha256") for s, c in counts.items()})
    if bad:
        raise SystemExit("stopped: the data differ from research/hunt/data_manifest.json (H 2): " + "; ".join(bad))
    return data, syms, counts


COST2_KEYS = ("mean_lnM", "median_M", "q25_lnM", "q75_lnM", "share_M_lt_0_9", "worst_month", "max_dd", "bust",
              "end_multiple", "fees", "funding", "n_positions")
ROLE_READ = "read only: numbers chosen after the test period was seen (W 5)"


def private_dir(args) -> str:
    """The private folder outside the repository (W 11, D11): DeepSeek figures and the resumable parts."""
    base = args.private or os.path.join(args.data or os.environ.get("HUNT_DATA", "."), "hunt_private")
    path = os.path.abspath(base)
    if os.path.commonpath([path, ROOT]) == ROOT:
        raise SystemExit("--private must be outside the repository (D11)")
    return path


def parts_dir(args, study: str, step: str, pin: dict | None) -> str:
    """Finished parts of a long step, keyed by the pin they ran under (a rerun under the same pin resumes)."""
    tag = ((pin or {}).get("pin_sha256") or "nopin")[:16]
    return os.path.join(private_dir(args), "parts", f"{study}_{step}_{tag}")


def _write_part(path: str, obj) -> str:
    disk_check(path)
    return _write_json(path, obj)


def _read_part(path: str):
    with open(path) as fh:
        return json.load(fh)


def cell_sha(spec: dict) -> str:
    return hashlib.sha256(json.dumps(cell_key(spec)).encode()).hexdigest()[:16]


def _row_of(spec: dict, base: dict, cost2: dict, seconds: float) -> dict:
    """One select row: the W 5 fields, the H 10 metric set of the base run, the cost x2 summary."""
    ok, why = wide_eligible(base, cost2)
    row = {k: spec.get(k) for k in ("id", "family", "name", "strategy", "kind", "tf", "gate", "rank", "combo")}
    row.update({"role": "candidate" if spec.get("family") in PICK_FAMILIES else ROLE_READ,
                "eligible": ok, "fail": why, "score": base["mean_lnM"], "median_M": base["median_M"],
                "n_positions": base["n_positions"], "bust": base["bust"], "win_share": base["win_share"],
                "cost2_mean_lnM": cost2["mean_lnM"], "cost2_median_M": cost2["median_M"],
                "max_dd": base["max_dd"], "end_multiple": base["end_multiple"],
                "signal_counts": base["signal_counts"], "metrics": base,
                "cost2_metrics": {k: cost2.get(k) for k in COST2_KEYS}, "seconds": round(seconds, 3)})
    return row


def _sel_task(task) -> list:
    """Wide select unit: one entry cell (events once), both gates x base / cost x2 (W 5). Its rows are written to
    ``part`` (private folder) as soon as they exist, so a rerun under the same pin skips the cell."""
    mkey, specs, part = task
    mk = _G["mk"][mkey]
    _EVENTS.clear()                               # one entry cell per task: no cache grows across tasks
    _SIGS.clear()
    out = []
    for spec in specs:
        t0 = time.time()
        base = run_system(mk, spec, R_BASE, "base", detail=True, days=False)
        cost2 = run_system(mk, spec, R_BASE, "x2")
        out.append(_row_of(spec, base, cost2, time.time() - t0))
    if part:
        _write_part(part, {"rows": out})
    return out


def _group_cells(specs: list) -> list:
    cells = {}
    for s in specs:
        cells.setdefault(cell_key(s), []).append(s)
    return sorted(cells.values(), key=lambda g: (TF_ORDER.index(g[0]["tf"]), cell_key(g[0])))


def cmd_select(args) -> int:
    study = args.study
    pin = check_pin(study, "select")
    _compile_probe()                               # compile once in the parent; forked workers inherit it
    if study == "wide":
        _ew().fullgrid_pins()
    data, syms, counts = _universe_and_data(args, "select")
    mk = Market(syms, "select")
    _G["mk"][mk.key] = mk
    out_dir = os.path.join(ROOT, OUT_REL[study])
    t0 = time.time()
    if study == "v1":
        prepare_series(syms, V1_TFS)
        rows = {}
        kw = {"detail": True, "days": False}
        for spec in v1_systems():
            par, main, (lo, hi) = V1_ENTRIES[spec["name"]]
            rows[spec["id"]] = {
                "main": run_system(mk, spec, R_BASE, **kw),
                "lo": run_system(mk, v1_spec(spec["name"], spec["tf"], lo), R_BASE, **kw),
                "hi": run_system(mk, v1_spec(spec["name"], spec["tf"], hi), R_BASE, **kw),
                "one": run_system(mk, spec, R_ONE, **kw)}
            print(f"v1 select: {spec['id']} done ({time.time() - t0:.0f}s)", flush=True)
        ch = v1_choose(rows)
        sel = {**_stamp(study, pin), "data_counts": counts, "rows": rows, "choice": ch,
               "seconds": round(time.time() - t0, 1)}
        _write_json(os.path.join(out_dir, "select.json"), sel)
        spec = next(s for s in v1_systems() if s["id"] == ch["pick"])
        _write_json(os.path.join(ROOT, PICKS_REL[study]), {**_stamp(study, pin), "pick": spec, "label": ch["label"]})
    else:
        specs = wide_systems()
        prepare_series(syms, TF_ORDER)
        groups = _group_cells(specs)
        pdir = parts_dir(args, study, "select", pin)
        part_of = [os.path.join(pdir, f"cell_{cell_sha(g[0])}.json") for g in groups]
        todo = [i for i, p in enumerate(part_of) if not os.path.exists(p)]
        if len(todo) < len(groups):
            print(f"wide select: {len(groups) - len(todo)} of {len(groups)} entry cells already done under this pin "
                  f"({pdir}); running the other {len(todo)}", flush=True)
        pmap(_sel_task, [(mk.key, groups[i], part_of[i]) for i in todo], args.procs, label="wide select cells")
        rows = [r for p in part_of for r in _read_part(p)["rows"]]
        ch = wide_choose(rows)
        by_id = {s["id"]: s for s in specs}
        picks = [{**by_id[i], "pick_no": n + 1} for n, i in enumerate(ch["picks"])]
        public, private = redact_rows(rows)
        priv_sha = write_private(args, "wide_select_private.json", {"rows": private})
        sel = {**_stamp(study, pin), "data_counts": counts, "rows": public, "label": ch["label"],
               "pick_families": list(PICK_FAMILIES), "picks": [p["id"] for p in picks], "private_sha256": priv_sha,
               "seconds": round(time.time() - t0, 1)}
        _write_json(os.path.join(out_dir, "select.json"), sel)
        _write_json(os.path.join(ROOT, PICKS_REL[study]), {**_stamp(study, pin), "picks": picks, "label": ch["label"]})
    h = append_picks_line(study)
    print(f"{study} select done in {time.time() - t0:.0f}s; picks sha256 {h} appended to {PIN[study]}")
    return 0


def _load_picks(study: str) -> dict:
    with open(os.path.join(ROOT, PICKS_REL[study])) as fh:
        return json.load(fh)


def _pick_block(study: str, spec: dict, mks: dict, procs: int, r: float, with_controls: bool = True,
                period: str = "test") -> dict:
    mk = mks[period]
    base = run_system(mk, spec, r, "base", detail=True)
    cost2 = run_system(mk, spec, r, "x2", detail=True, days=False)
    ctl = run_controls(mk, spec, study, r, procs) if with_controls else None
    res = {"base": base, "cost2": cost2, "checks": judge(base, cost2, ctl, study, spec, mk.period, r)}
    if ctl is not None:
        res["controls"] = {"a_mean_lnM": ctl["a"].mean(axis=1).tolist(), "b_mean_lnM": ctl["b"].mean(axis=1).tolist(),
                           "gated_signals": ctl["gated"]}
    return res


def _reads(study: str, spec: dict, mks: dict, procs: int) -> dict:
    """H 14 / W 7 reads for one pick (never a pass). The gate diagnostics run the pick's entry and timeframe under
    another gate: v1 in select and test (H 14); wide in select only, since the other gate is one of the 730 systems
    and W 6 runs no non-pick system on the test period."""
    rd = {}
    kw = {"detail": True, "days": False}
    rd["r1"] = _pick_block(study, spec, mks, procs, R_ONE)
    rd["select_controls"] = _pick_block(study, spec, mks, procs, R_BASE, True, "select")
    rd["new24"] = {p: run_system(mks[f"new_{p}"], spec, R_BASE, **kw) for p in ("select", "test")}
    rd["extra2020"] = {f"{r:g}": run_system(mks["extra"], spec, r, **kw) for r in (R_BASE, R_ONE)}
    diag = ("NONE", "TS") if spec["gate"] == "G1" else ("G1", "TS")
    periods = ("select", "test") if study == "v1" else ("select",)
    rd["gate_diagnostics"] = {g: {p: run_system(mks[p], spec, R_BASE, gate=g, **kw) for p in periods}
                              for g in diag}
    return rd


def _sizing(mk: Market, parts: list) -> dict:
    """W 7 sizing read: r = 2% and 5%; the total open risk cap and the margin budget B scaled by r / 0.5%, leverage
    as H 7.3 (20x cap); the full H 10 metric set plus the bet actually taken (realized unit risk, cut and add
    shares)."""
    out = {}
    for r in SIZING_RS:
        scale = r / R_BASE
        s = run_signals(mk, parts, r, "base", RISK_CAP * scale, detail=True, days=False, b_div=B_DIV / scale)
        s["requested_r"] = r
        s["risk_cap"] = RISK_CAP * scale
        s["margin_budget_of_equity"] = scale / B_DIV
        out[f"{r:g}"] = s
    return out


def cmd_test(args) -> int:
    study = args.study
    pin = check_pin(study, "test")
    _compile_probe()
    if study == "wide":
        _ew().fullgrid_pins()
    pk = _load_picks(study)
    data, syms, counts = _universe_and_data(args, "test")
    new = [s for s in syms if s not in OLD_SIX]
    mks = {"test": Market(syms, "test"), "select": Market(syms, "select"), "extra": Market(syms, "extra"),
           "new_test": Market(new, "test"), "new_select": Market(new, "select")}
    for m in mks.values():
        _G["mk"][m.key] = m
    out_dir = os.path.join(ROOT, OUT_REL[study])
    t0 = time.time()
    if study == "v1":
        spec = pk["pick"]
        prepare_series(syms, (spec["tf"],))
        blk = _pick_block(study, spec, mks, args.procs, R_BASE)
        ok = all(blk["checks"][p] for p in ("P0", "P1", "P2", "P3", "P4"))
        rd = _reads(study, spec, mks, args.procs)
        one = rd["r1"]["checks"]
        verdict = {"v1_pass": bool(ok and pk["label"] == "pick"), "label": pk["label"],
                   "one_pct_also_passes": bool(all(one[p] for p in ("P0", "P1", "P2", "P3", "P4"))),
                   "carried_by_old_six": bool(ok and rd["new24"]["test"]["mean_lnM"] <= 0)}
        test = {**_stamp(study, pin), "pick": spec, "result": blk, "verdict": verdict, "reads": rd,
                "data_counts": counts, "seconds": round(time.time() - t0, 1)}
        _write_json(os.path.join(out_dir, "test.json"), test)
    else:
        picks = pk["picks"]
        prepare_series(syms, sorted({p["tf"] for p in picks}, key=TF_ORDER.index))
        pdir = parts_dir(args, study, "test", pin)
        blocks, reads = {}, {}
        for p in picks:                             # one part per pick: a rerun under the same pin resumes
            part = os.path.join(pdir, f"pick_{int(p['pick_no']):02d}_"
                                      f"{hashlib.sha256(p['id'].encode()).hexdigest()[:16]}.json")
            if not os.path.exists(part):
                t1 = time.time()
                _write_part(part, {"id": p["id"], "block": _pick_block(study, p, mks, args.procs, R_BASE),
                                   "reads": _reads(study, p, mks, args.procs)})
                print(f"wide test: pick {p['pick_no']}/{len(picks)} {p['id']} done in {time.time() - t1:.0f}s",
                      flush=True)
            d = _read_part(part)
            if d["id"] != p["id"]:
                raise SystemExit(f"{part} holds {d['id']}, not {p['id']}")
            blocks[p["id"]], reads[p["id"]] = d["block"], d["reads"]
        pv = [blocks[p["id"]]["checks"].get("p", 1.0) for p in picks]
        sig = bh(pv, BH_Q)
        passes = []
        for p, s in zip(picks, sig):
            c = blocks[p["id"]]["checks"]
            c["bh_significant"] = bool(s)
            c["PASS"] = bool(pk["label"] == "picks" and all(c[x] for x in ("P0", "P1", "P3", "P4", "rank_ok_a",
                                                                           "rank_ok_b")) and s)
            if c["PASS"]:
                passes.append(p)
        for p in picks:
            c = blocks[p["id"]]["checks"]
            c["carried_by_old_six"] = bool(c["PASS"] and reads[p["id"]]["new24"]["test"]["mean_lnM"] <= 0)
            one = reads[p["id"]]["r1"]["checks"]           # W 7: P0, P1, P3, P4, both seed ranks, p < 0.05 at 1%
            c["one_pct_also_passes"] = bool(all(one[x] for x in ("P0", "P1", "P3", "P4", "rank_ok_a", "rank_ok_b"))
                                            and one["p"] < P_ALPHA)
        basket, sizing = {}, {}
        for p in passes:
            sizing[p["id"]] = _sizing(mks["test"], [(system_signals(mks["test"], p), 0)])
        if len(passes) >= 2:
            for per in ("select", "test"):
                parts = [(system_signals(mks[per], p), p["pick_no"]) for p in passes]
                basket[per] = run_signals(mks[per], parts, R_BASE, detail=True)
            sizing["basket"] = _sizing(mks["test"], [(system_signals(mks["test"], p), p["pick_no"]) for p in passes])
        verdict = {"wide_pass": bool(passes), "label": pk["label"], "passing": [p["id"] for p in passes]}
        full = {"picks": picks, "results": blocks, "reads": reads, "basket": basket, "sizing": sizing,
                "verdict": verdict}
        public = redact_test(full)
        priv_sha = write_private(args, "wide_test_private.json", full)
        test = {**_stamp(study, pin), **public, "private_sha256": priv_sha, "data_counts": counts,
                "seconds": round(time.time() - t0, 1)}
        _write_json(os.path.join(out_dir, "test.json"), test)
    print(f"{study} test done in {time.time() - t0:.0f}s")
    return 0


# ------------------------------------------------------------------ DeepSeek money (W 11, D11)
DS_ALLOWED = {"id", "family", "name", "strategy", "kind", "tf", "gate", "rank", "combo", "eligible", "fail",
              "n_positions", "win_share", "bust", "pick_no", "signal_counts", "seconds", "label", "role"}
DS_ALLOWED_CHECKS = {"P0", "P1", "P2_a", "P2_b", "P3", "P4", "rank_ok_a", "rank_ok_b", "bh_significant", "PASS",
                     "carried_by_old_six", "one_pct_also_passes"}


def redact_rows(rows: list) -> tuple:
    public = []
    for r in rows:
        public.append({k: v for k, v in r.items() if k in DS_ALLOWED} if is_ds(r) else r)
    return public, rows


def _labels_only(d: dict) -> dict:
    keep = ("n_positions", "win_share", "bust", "candidates", "signal_counts", "skipped", "cut", "adds_skipped",
            "adds_cut", "months_with_position", "exit_reasons")
    return {k: d[k] for k in keep if k in d}


def redact_test(full: dict) -> dict:
    out = {"picks": full["picks"], "verdict": full["verdict"], "results": {}, "reads": {}, "basket": {},
           "sizing": {}}
    for p in full["picks"]:
        pid = p["id"]
        blk = full["results"][pid]
        if is_ds(p):
            out["results"][pid] = {"base": _labels_only(blk["base"]), "cost2": _labels_only(blk["cost2"]),
                                   "checks": {k: v for k, v in blk["checks"].items() if k in DS_ALLOWED_CHECKS}}
            rd = full["reads"][pid]
            out["reads"][pid] = {"note": "DeepSeek pick: figures in the private file (D11)",
                                 "r1_checks": {k: v for k, v in rd["r1"]["checks"].items() if k in DS_ALLOWED_CHECKS},
                                 "new24_positions": {p_: rd["new24"][p_]["n_positions"] for p_ in rd["new24"]},
                                 "extra2020_bust": {r_: rd["extra2020"][r_]["bust"] for r_ in rd["extra2020"]}}
        else:
            out["results"][pid] = blk
            out["reads"][pid] = full["reads"][pid]
    any_ds = any(is_ds(p) for p in full["picks"] if p["id"] in full["verdict"]["passing"])
    out["basket"] = "contains a DeepSeek pick: figures in the private file (D11)" if any_ds and full["basket"] \
        else full["basket"]
    for k, v in full["sizing"].items():
        ds = (k == "basket" and any_ds) or (k != "basket" and is_ds(next(p for p in full["picks"] if p["id"] == k)))
        out["sizing"][k] = "DeepSeek: figures in the private file (D11)" if ds else v
    return out


def write_private(args, name: str, obj) -> str:
    path = os.path.join(private_dir(args), name)
    disk_check(path)
    return _write_json(path, obj)


# ------------------------------------------------------------------ data pin and cross-check (H 2), pin list
def cmd_datapin(args) -> int:
    """research/hunt/data_manifest.json: the data folder's manifest.json copied in, plus per coin the H 2 content
    hash of the 5m and funding arrays the study reads. Run once before the pin, on the finished download."""
    data = args.data
    if not data:
        raise SystemExit("--data <coins30 folder> needed")
    with open(os.path.join(data, "manifest.json")) as fh:
        man = json.load(fh)
    syms = load_universe(data)
    content = {}
    for s in syms:
        p5 = os.path.join(data, "5m", f"{s}.npz")
        if not os.path.exists(p5):
            raise SystemExit(f"{p5} missing: the download is not finished")
        content[s] = {"5m": file_content_sha(p5, "5m"),
                      "funding": file_content_sha(os.path.join(data, "funding", f"{s}.npz"), "funding")}
    doc = {"what": "PREREG_HUNT 2 data identity: the coins30 manifest and the content hash of the arrays read",
           "rule": "sha256 over the arrays in order (5m: ts o h l c v qv; funding: ts rate), each as "
                   "'name|dtype|shape' newline then its raw C-order bytes",
           "written_utc": ms_str(int(time.time() * 1000)),
           "manifest_sha256": sha256_file(os.path.join(data, "manifest.json")), "symbols": syms,
           "content": content, "manifest": man}
    print(_write_json(os.path.join(ROOT, DATA_MANIFEST_REL), doc), DATA_MANIFEST_REL)
    return 0


def cross_check_coin(five_path: str, one_path: str) -> dict:
    """H 2 cross-check of one coin: its 5m bars as the study reads them (clean_5m) against the full grid's 1m bars
    binned to 5m, on every bar both have: OHLC within 1e-6 relative, base volume within 0.1%. Counts only."""
    EW = _ew()
    with np.load(five_path) as z:
        full = {k: z[k] for k in CONTENT_KEYS["5m"]}
    sha = content_sha(full, CONTENT_KEYS["5m"])
    (ts, o, h, lo, c, v, _qv), cnt = clean_5m(full["ts"], full["o"], full["h"], full["l"], full["c"], full["v"],
                                               full["qv"])
    del full
    with np.load(one_path) as z:
        t1, o1, h1, l1, c1, v1 = EW.resample_1m_to_5m(z["ts"], z["o"], z["h"], z["l"], z["c"], z["v"])
    common, i5, i1 = np.intersect1d(ts, t1, return_indices=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        px = np.zeros(len(common), bool)
        for a5, a1 in ((o, o1), (h, h1), (lo, l1), (c, c1)):
            x, y = np.asarray(a5, np.float64)[i5], np.asarray(a1, np.float64)[i1]
            px |= ~(np.abs(x - y) <= XCHECK_TOL_PX * np.abs(y))
        x, y = np.asarray(v, np.float64)[i5], np.asarray(v1, np.float64)[i1]
        vol = ~(np.abs(x - y) <= XCHECK_TOL_VOL * np.maximum(np.abs(y), 1e-12))
    bad = px | vol
    return {"content_sha256": sha, "clean_counts": cnt, "bars_5m": int(len(ts)), "bars_1m_to_5m": int(len(t1)),
            "common": int(len(common)), "only_5m": int(len(ts) - len(common)), "only_1m": int(len(t1) - len(common)),
            "ohlc_mismatch": int(px.sum()), "volume_mismatch": int(vol.sum()), "mismatch": int(bad.sum()),
            "mismatch_share": float(bad.mean()) if len(common) else 1.0,
            "first_mismatch": ms_str(int(common[np.flatnonzero(bad)[0]])) if bad.any() else None}


def cmd_datacheck(args) -> int:
    """research/hunt/data_check.json: the H 2 cross-check on the old six (counts only; no outcome). Pass = every
    coin's mismatch share <= 0.1% of the bars both have."""
    if not args.data or not args.fg1m:
        raise SystemExit("--data <coins30 folder> and --fg1m <the full grid's data folder> needed")
    coins = {}
    for s in OLD_SIX:
        coins[s] = cross_check_coin(os.path.join(args.data, "5m", f"{s}.npz"), os.path.join(args.fg1m, "1m",
                                                                                              f"{s}.npz"))
        print(s, coins[s]["mismatch"], "of", coins[s]["common"], flush=True)
    ok = all(x["common"] > 0 and x["mismatch_share"] <= XCHECK_MAX_SHARE for x in coins.values())
    doc = {"what": "PREREG_HUNT 2 cross-check: 5m bars (as read: duplicates, zero volume, off-grid dropped) vs the "
                   "full grid's 1m archive binned to 5m, on the bars both have; counts only",
           "tolerance": {"ohlc_rel": XCHECK_TOL_PX, "volume_rel": XCHECK_TOL_VOL, "max_share": XCHECK_MAX_SHARE},
           "written_utc": ms_str(int(time.time() * 1000)), "pass": bool(ok), "coins": coins,
           "code_sha256": sha256_file(os.path.abspath(__file__))}
    print(_write_json(os.path.join(ROOT, DATA_CHECK_REL), doc), DATA_CHECK_REL, "pass" if ok else "FAIL")
    return 0 if ok else 1


def cmd_pinlist(args) -> int:
    """Print the files the study's pin must list (one per line), for building the pin file before select."""
    for p in required_files(args.study):
        print(p)
    return 0


# ------------------------------------------------------------------ report
def cmd_report(args) -> int:
    study = args.study
    out_dir = os.path.join(ROOT, OUT_REL[study])
    lines = [f"# 추세 사냥 {'v1' if study == 'v1' else '넓게'} 결과", ""]
    sp = os.path.join(out_dir, "select.json")
    tp = os.path.join(out_dir, "test.json")
    if not os.path.exists(sp):
        lines.append("아직 고르기(select)를 돌리지 않았습니다.")
    else:
        with open(sp) as fh:
            sel = json.load(fh)
        lines += [f"* 커밋 `{sel['git_commit'][:10]}`, 고정 파일 sha256 `{(sel.get('pin') or {}).get('pin_sha256', '')[:16]}`",
                  ""]
        if study == "v1":
            ch = sel["choice"]
            lines += ["## 고르기 (2021-01 ~ 2023-12, 위험 0.5%)", "", "| 시스템 | 자격 | 평탄 점수 | 세 값 평균 ln M 중앙 |",
                      "|---|---|---:|---:|"]
            for x in ch["table"]:
                lines.append(f"| {x['id']} | {'예' if x['eligible'] else '아니오'} | {x['plateau']:.3f} | "
                             f"{x['median_mean_lnM']:.4f} |")
            lines += ["", f"고른 것: **{ch['pick']}** ({ch['label']})", ""]
        else:
            n_el = sum(1 for r in sel["rows"] if r.get("eligible"))
            lines += [f"## 고르기: 시스템 {len(sel['rows'])}개, 자격 {n_el}개, 고른 것 {len(sel['picks'])}개 "
                      f"({sel['label']})", ""]
            lines += [f"{i + 1}. {p}" for i, p in enumerate(sel["picks"])] + [""]
    if os.path.exists(tp):
        with open(tp) as fh:
            test = json.load(fh)
        lines += ["## 시험 (2024-01 ~ 2026-09)", ""]
        if study == "v1":
            c = test["result"]["checks"]
            v = test["verdict"]
            lines += [f"* P0 {c['P0']} · P1 {c['P1']} · P2 {c['P2']} (p_a {c['p_a']:.4f}, p_b {c['p_b']:.4f}) · "
                      f"P3 {c['P3']} · P4 {c['P4']}", f"* **v1 통과: {'예' if v['v1_pass'] else '아니오'}** "
                      f"({v['label']}); 1%도 통과: {v['one_pct_also_passes']}; 기존 6개가 끌고 감: "
                      f"{v['carried_by_old_six']}", ""]
        else:
            v = test["verdict"]
            lines += ["| 번호 | 시스템 | P0 | P1 | P3 | P4 | 순위a | 순위b | BH | 통과 |", "|---:|---|---|---|---|---|---|---|---|---|"]
            for p in test["picks"]:
                c = test["results"][p["id"]]["checks"]
                yn = lambda b: "예" if b else "아니오"  # noqa: E731
                lines.append(f"| {p['pick_no']} | {p['id']} | {yn(c.get('P0'))} | {yn(c.get('P1'))} | "
                             f"{yn(c.get('P3'))} | {yn(c.get('P4'))} | {yn(c.get('rank_ok_a'))} | "
                             f"{yn(c.get('rank_ok_b'))} | {yn(c.get('bh_significant'))} | {yn(c.get('PASS'))} |")
            lines += ["", f"**넓게 통과: {'예' if v['wide_pass'] else '아니오'}** ({v['label']})", "",
                      "v1과 넓게는 같은 시험 기간을 씁니다: 둘 중 하나가 운으로 통과할 가능성은 하나일 때보다 큽니다.", ""]
            sz = {k: x for k, x in test.get("sizing", {}).items() if isinstance(x, dict)}
            if sz:
                lines += ["## 크게 걸면 (참고, 통과 조건 아님)", "",
                          "| 시스템 | 요청 위험 | 실제 첫 단위 위험(중앙) | 2배+ 달 | 10배+ 달 | 30배+ 달 | 최악의 달 | 파산 |",
                          "|---|---:|---:|---:|---:|---:|---:|---|"]
                for k, rr in sz.items():
                    for r_, x in rr.items():
                        ru = (x.get("realized_unit_risk") or {}).get("median")
                        lines.append(f"| {k} | {float(r_) * 100:g}% | {'-' if ru is None else f'{ru * 100:.2f}%'} | "
                                     f"{x['share_M_ge_2'] * 100:.0f}% | {x['share_M_ge_10'] * 100:.0f}% | "
                                     f"{x['share_M_ge_30'] * 100:.0f}% | {x['worst_month']:.2f} | "
                                     f"{'예 ' + str(x['bust_month']) if x['bust'] else '아니오'} |")
                lines.append("")
            lines.append("관찰 후보 38개(F4)는 시험 기간을 본 뒤 고른 숫자라서 고르기에서 참고로만 보고, "
                         "시험·통과에는 넣지 않았습니다.")
            lines.append("딥시크 매매법의 돈 숫자는 저장소 밖 파일에만 있습니다(D11).")
    path = os.path.join(out_dir, "RESULTS_KO.md")
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(path)
    return 0


# ------------------------------------------------------------------ timing on synthetic bars (no real price)
def synth_coin(sym: str, start_ms: int, end_ms: int, seed: int, base_price: float = 100.0) -> Coin:
    rng = np.random.default_rng(seed)
    n = (end_ms - start_ms) // FIVE
    ts = start_ms + np.arange(n, dtype=np.int64) * FIVE
    reg = np.repeat(rng.choice([-1.0, 0.0, 0.0, 1.0], size=n // 3000 + 1), 3000)[:n]
    sig = 0.0025 * np.exp(np.repeat(rng.normal(0, 0.35, n // 800 + 1), 800)[:n])
    ret = rng.normal(0, 1, n) * sig + reg * 0.06 * sig
    c = base_price * np.exp(np.cumsum(ret))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 1, n) * sig)
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 1, n) * sig)
    v = rng.lognormal(0, 1, n) * 2000.0
    return Coin(sym, ts, o, h, lo, c, v, v * c)


def synth_funding(start_ms: int, end_ms: int, seed: int) -> tuple:
    rng = np.random.default_rng(seed)
    ts = np.arange(start_ms + 8 * 3_600_000, end_ms, 8 * 3_600_000, dtype=np.int64)
    return ts, rng.normal(0.0001, 0.0002, len(ts))


def synth_signals(mk: Market, tf: str, per_days: float, seed: int) -> dict:
    """Random gated signals at the density of one per coin per ``per_days`` days (timing only)."""
    rng = np.random.default_rng(seed)
    K, J, S = [], [], []
    for k in range(mk.K):
        pool = control_pool(mk, tf, k)
        n = int((mk.end - mk.start) / DAY_MS / per_days)
        j = np.sort(rng.choice(pool, size=min(n, len(pool)), replace=False))
        K.append(np.full(len(j), k, np.int64))
        J.append(j.astype(np.int64))
        S.append(np.where(rng.random(len(j)) < 0.5, 1, -1).astype(np.int64))
    return {"tf": tf, "k": np.concatenate(K), "j": np.concatenate(J), "side": np.concatenate(S),
            "counts": {"gated": int(sum(len(x) for x in K))}}


def _bench_task(task) -> float:
    mkey, tf, seed = task
    mk = _G["mk"][mkey]
    sig = synth_signals(mk, tf, 2.0, seed)
    t0 = time.perf_counter()
    run_signals(mk, [(sig, 0)], R_BASE)
    return time.perf_counter() - t0


def cmd_bench(args) -> int:
    """Seconds per system run on synthetic 30-coin x 36-month 5m bars, numba compile time, and the wall-time
    extrapolation for wide select / test here (2 procs) and on a 32-core server."""
    import tempfile
    res = {"what": "synthetic bars only (seeded random walks), no real price; 30 coins, 5m",
           "machine": {"cpu_count": os.cpu_count()}}
    # cold numba compile (fresh cache folder in a subprocess)
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, NUMBA_CACHE_DIR=td, PYTHONPATH=ROOT)
        code = ("import time;t=time.time();import research.hunt.hunt as H;H._compile_probe();"
                "print(time.time()-t)")
        t_import = subprocess.run([sys.executable, "-c", "import time;t=time.time();import research.hunt.hunt;"
                                   "print(time.time()-t)"], env=env, capture_output=True, text=True, cwd=ROOT)
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=ROOT)
        try:
            res["numba_compile_cold_s"] = round(float(r.stdout.strip().splitlines()[-1])
                                                - float(t_import.stdout.strip().splitlines()[-1]), 2)
        except Exception:
            res["numba_compile_cold_s"] = None
            res["compile_error"] = (r.stderr or "")[-2000:]
    t0 = time.perf_counter()
    _compile_probe()
    res["numba_load_cached_s"] = round(time.perf_counter() - t0, 3)
    # data: 30 coins from 2020-07 (warm-up) to 2024-01 (the select period is 36 months)
    syms = [f"C{i:02d}USDT" for i in range(30)]
    a, b = day_ms("2020-07-01"), day_ms(PERIODS["select"][1])
    t0 = time.perf_counter()
    coins = {s: synth_coin(s, a, b, 1000 + i, 10.0 * (1 + i)) for i, s in enumerate(syms)}
    fund = {s: synth_funding(a, b, 2000 + i) for i, s in enumerate(syms)}
    install(coins, fund)
    res["synth_build_s"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    mk = Market(syms, "select")
    _G["mk"][mk.key] = mk
    res["market_build_s"] = round(time.perf_counter() - t0, 2)
    res["bars_5m_per_coin_in_select"] = int(mk.T)
    ser_t = {}
    for tf in TF_ORDER:
        t0 = time.perf_counter()
        prepare_series(syms, (tf,))
        ser_t[tf] = round(time.perf_counter() - t0, 2)
    res["series_build_s_30_coins"] = ser_t
    per_tf = {}
    for tf in TF_ORDER:
        bank_for(mk, (tf,))
        ts_ = []
        for s in range(5):
            ts_.append(_bench_task((mk.key, tf, 50 + s)))
        sig = synth_signals(mk, tf, 2.0, 7)
        per_tf[tf] = {"s_per_run_1proc": round(float(np.median(ts_)), 4), "signals": sig["counts"]["gated"]}
    res["engine_run_s"] = per_tf
    # 2 procs: 40 runs
    tasks = [(mk.key, TF_ORDER[i % 4], 100 + i) for i in range(40)]
    t0 = time.perf_counter()
    pmap(_bench_task, tasks, 1)
    w1 = time.perf_counter() - t0
    t0 = time.perf_counter()
    pmap(_bench_task, tasks, 2)
    w2 = time.perf_counter() - t0
    res["engine_40_runs_wall_s"] = {"procs_1": round(w1, 2), "procs_2": round(w2, 2)}
    # entry events: F1 real code on synthetic bars, a sample of F2 / F3 definitions on synthetic bars
    EW = _ew()
    ev = {}
    for name in ("E1", "E2", "E3"):
        for tf in ("15m", "4h"):
            spec = {"id": f"bench:{name}:{tf}", "family": "F1", "name": name, "kind": "hunt", "tf": tf,
                    "combo": dict([(V1_ENTRIES[name][0], V1_ENTRIES[name][1])])}
            t0 = time.perf_counter()
            for s in syms[:3]:
                entry_events(spec, s, series(s, tf), None)
            ev[f"F1:{name}:{tf}"] = round((time.perf_counter() - t0) / 3, 4)
    cells = _group_cells(EW.systems())
    cell_s, errs = {}, {}
    for g in cells:                                # every F2 / F3 / F4 cell once, on one coin (BTC context: C00)
        spec = g[0]
        if spec["kind"] == "hunt":
            continue
        key = f"{spec['family']}:{spec['name']}:{spec['tf']}" + (f":r{spec['rank']}" if spec.get("rank") else "")
        t0 = time.perf_counter()
        try:
            btc = series(syms[0], spec["tf"]) if spec["kind"] == "ds" else None
            entry_events(spec, syms[1], series(syms[1], spec["tf"]), btc)
            cell_s[key] = round(time.perf_counter() - t0, 4)
        except Exception as e:  # pragma: no cover - timing only
            errs[key] = repr(e)[:300]
    res["f2_f4_cells_one_coin"] = {"timed": len(cell_s), "errors": errs,
                                   "sum_s": round(sum(cell_s.values()), 1),
                                   "sum_by_tf_s": {tf: round(sum(v for k, v in cell_s.items()
                                                                 if k.split(":")[2] == tf), 1) for tf in TF_ORDER},
                                   "slowest": sorted(((v, k) for k, v in cell_s.items()), reverse=True)[:10]}
    res["events_s_per_coin_series_42_months"] = ev
    # one control run (draw + candidates + engine), as the test step runs 600 of them per pick
    sig = synth_signals(mk, "1h", 2.0, 11)
    t0 = time.perf_counter()
    for s in range(10):
        csig = control_a(mk, sig, rng_of("bench", s))
        run_signals(mk, [(csig, 0)], R_BASE)
    res["control_run_s"] = round((time.perf_counter() - t0) / 10, 4)
    res["extrapolation"] = extrapolate(res, EW)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps(res, indent=1))
    return 0


def extrapolate(res: dict, EW) -> dict:
    """Wall time of wide select and test from the synthetic measurements (all scalings written in ``notes``)."""
    ev = res["events_s_per_coin_series_42_months"]
    f1 = float(np.mean([v for k, v in ev.items() if k.startswith("F1")]))
    cells = res["f2_f4_cells_one_coin"]
    systems = EW.systems()
    n_f1_cells = len({(s["name"], s["tf"]) for s in systems if s["family"] == "F1"})
    sel_len, test_len = 48 / 42, 81 / 42        # data loaded: 2020-01..2024-01 / ..2026-10 vs the bench's 42 months
    ev_sel = 30 * (cells["sum_s"] + n_f1_cells * f1) * sel_len
    run_s = float(np.mean([v["s_per_run_1proc"] for v in res["engine_run_s"].values()]))
    ser = sum(res["series_build_s_30_coins"].values())
    w = res["engine_40_runs_wall_s"]
    speed2 = w["procs_1"] / max(w["procs_2"], 1e-9)
    sel_runs = 2 * len(systems)
    sel_cpu = ev_sel + sel_runs * run_s
    per_pick_runs = 2 + 200 + (2 + 200) + (2 + 200) + 2 + 2 + 2       # test, r=1%, select controls, reads
    test_runs = 10 * per_pick_runs + 2 + 2 * 11
    mean_cell = (cells["sum_s"] + n_f1_cells * f1) / max(cells["timed"] + n_f1_cells, 1)
    worst10 = sum(v for v, _ in cells["slowest"][:10])
    test_ev_typ, test_ev_worst = 10 * 30 * mean_cell * test_len, 30 * worst10 * test_len
    test_cpu = test_runs * max(run_s, res["control_run_s"])
    ser_sel, ser_test = ser * sel_len, ser * test_len

    def wall(cpu, serial_s, procs, eff):
        return round((serial_s + cpu / (procs * eff)) / 3600, 2)
    eff2 = speed2 / 2
    return {"systems": len(systems), "select_engine_runs": sel_runs,
            "engine_s_per_run": round(run_s, 4), "control_s_per_run": res["control_run_s"],
            "speedup_2_procs_measured": round(speed2, 2),
            "select_cpu_s": {"series_once": round(ser_sel), "events": round(ev_sel), "engine": round(sel_runs * run_s),
                             "total": round(ser_sel + sel_cpu)},
            "select_wall_h": {"here_2_procs": wall(sel_cpu, ser_sel, 2, eff2),
                              "server_32_procs": wall(sel_cpu, ser_sel, 32, 0.85)},
            "test_engine_runs": test_runs,
            "test_cpu_s": {"engine": round(test_cpu), "events_typical": round(test_ev_typ),
                           "events_if_the_10_slowest_cells_are_picked": round(test_ev_worst),
                           "series_once": round(ser_test)},
            "test_wall_h": {"here_2_procs": wall(test_cpu, ser_test + test_ev_typ, 2, eff2),
                            "here_2_procs_worst_events": wall(test_cpu, ser_test + test_ev_worst, 2, eff2),
                            "server_32_procs": wall(test_cpu, ser_test + test_ev_typ, 32, 0.85),
                            "server_32_procs_worst_events": wall(test_cpu, ser_test + test_ev_worst, 32, 0.85)},
            "notes": ["engine s/run measured on 36-month select periods with 1 signal per coin per 2 days; "
                      "the test period is 33 months (used as is: slight overestimate)",
                      "events: every F2 / F3 / F4 cell timed once on one synthetic coin of 42 months, x 30 coins, "
                      "scaled linearly to the data loaded (select 48 months, test 81 months); F1 by its real code",
                      "test events: only the picks' cells, computed in the parent (serial, so not divided by the "
                      "process count); typical = mean cell time, worst = the 10 slowest cells",
                      "series (bars + ATR + 장세 label, 30 coins x 4 timeframes) are built once in the parent before "
                      "forking (serial; counted in full in the wall time)",
                      f"test runs = 10 picks x {per_pick_runs} (base, cost x2, 200 controls at 0.5%; the same at 1%; "
                      "the same in the select period; new-24 x2; extra 2020 x2; gate diagnostics x2, select only) + "
                      "basket and sizing reads",
                      "32 procs: 85% parallel efficiency assumed; 2 procs: the measured 40-run speed-up on this "
                      "shared 4-core machine",
                      "not included: loading the 30 coins' npz files (about 0.5 GB) and writing outputs"]}


def _compile_probe() -> None:
    """Compile (or load from cache) every numba function on a tiny synthetic case."""
    z64 = np.zeros(0, np.int64)
    z = np.zeros(0)
    one = np.zeros(2, np.int64)
    one[1] = 288
    _engine(params(), one, np.zeros(2, np.int64), z64, z, z, z, z, z, np.zeros(2, np.int64), z64, z,
            -np.ones(1, np.int64), np.full(1, 5.0), np.ones(1, np.int64), np.full((1, 1), np.inf),
            np.full((1, 1), 20, np.int64), np.full((1, 1), 0.025), np.zeros((1, 1)), np.zeros((1, 1), np.int64),
            z64, z, z, z, z64, z64, z64, z64, z, z64, z64)


# ------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m research.hunt.hunt", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("select", "test", "report", "universe", "bench", "datapin", "datacheck",
                                    "pinlist"))
    ap.add_argument("--study", choices=("v1", "wide"), default=None)
    ap.add_argument("--procs", type=int, default=1)
    ap.add_argument("--data", default=None)
    ap.add_argument("--private", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--fg1m", default=None, help="datacheck: the full grid's data folder (holds 1m/<SYM>.npz)")
    args = ap.parse_args(argv)
    if args.cmd in ("select", "test", "report", "pinlist") and args.study is None:
        ap.error("--study {v1,wide} is required for select, test, report and pinlist")
    try:
        if args.cmd == "select":
            return cmd_select(args)
        if args.cmd == "test":
            return cmd_test(args)
        if args.cmd == "report":
            return cmd_report(args)
        if args.cmd == "universe":
            if not args.data:
                raise SystemExit("--data needed")
            print(json.dumps(write_universe30(args.data), indent=1))
            return 0
        if args.cmd == "datapin":
            return cmd_datapin(args)
        if args.cmd == "datacheck":
            return cmd_datacheck(args)
        if args.cmd == "pinlist":
            return cmd_pinlist(args)
        if args.cmd == "bench":
            if not args.out:
                raise SystemExit("--out <timing.json> needed")
            return cmd_bench(args)
    except PinError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
