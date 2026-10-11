"""Alt pump and new-listing study (research/altpump/PREREG_ALTPUMP.md; Korean summary README_KO.md).

    python3 research/altpump/altpump.py check     structure only (symbols, exclusions, lives, renames); no price read
    python3 research/altpump/altpump.py select    period 1: 28 variants x 2 cost levels -> out/select.json, pick.json
    python3 research/altpump/altpump.py test      periods 2 and 3, the picks only, 2 x 2,000 controls -> out/test.json
    python3 research/altpump/altpump.py board     goal board (fresh $1,000 months, 5 sizes, coin flip) -> board.json
    python3 research/altpump/altpump.py report    text summary of out/*.json -> out/report.txt
    python3 research/altpump/altpump.py pass2 plan|fetch|run    second pass on 5m bars (PREREG 15), passing picks only
    python3 research/altpump/altpump.py bench     timing on SYNTHETIC data shaped like the real file (no real data)
    python3 research/altpump/altpump.py pin       write PREREG_ALTPUMP.sha256 once (after section 20 is closed)

select, test, board and pass2 refuse to run without a matching PREREG_ALTPUMP.sha256 (PREREG 18). select appends the
sha256 of out/pick.json to it (PREREG 11.4); test, board and pass2 refuse until that line is there. Section numbers in
the comments are PREREG_ALTPUMP.md sections. Read-only research: nothing here touches a bot, an account or a key.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import time
import zipfile

import numpy as np
import pandas as pd
from numba import njit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

DATA_REL = "data/universe/klines_1d.csv.gz"
MANIFEST_REL = "data/universe/MANIFEST.json"
PREREG_REL = "research/altpump/PREREG_ALTPUMP.md"
CODE_REL = "research/altpump/altpump.py"
PIN_REL = "research/altpump/PREREG_ALTPUMP.sha256"
OUT_REL = "research/altpump/out"
PICK_REL = "research/altpump/out/pick.json"
FUNDING_FLAG = "funding assumed 0.03%/8h"                       # 8: on every output
LIQ_NOTE = ("daily bars: a liquidation comes only from an open beyond the liquidation price or a hair-cut stop fill "
            "beyond it (6.7); the 5m pass (15) measures liquidations")

DAY_MS = 86_400_000
COLS = ("symbol", "open_time", "open", "high", "low", "close", "volume", "quote_volume")

# ------------------------------------------------------------------ fixed numbers (sections 3-14)
PERIODS = {"p1": ("2021-08-01", "2024-07-01"),                 # 10: select
           "p2": ("2024-07-01", "2026-09-01"),                 # 10: test
           "p3": ("2020-01-01", "2021-08-01")}                 # 10: test
TEST_PERIODS = ("p2", "p3")
WARMUP_DAYS = 60                                                # 10
RELIST_GAP = 30                                                 # 3.1: >= 30 days without a bar -> a new life, a listing
PAUSE_GAP = 7                                                   # 3.1: 7..29 days without a bar -> new life, no listing
PARTIAL_MIN_MISSING = 10                                        # 3.1: a partial day (archive hole): >= 10 symbols and
PARTIAL_FRAC = 0.10                                             #      >= 10% of the lives covering the day lack a bar
RENAME_DAYS = 60                                                # 3.1
VOL_FLOOR = 5_000_000.0                                         # 3.3 (c)
STABLE_STD = 0.005                                              # 3.3 (d)
STABLE_MIN_BARS = 31                                            # 3.3 (d)
D0_ATR = 2.0                                                    # 6.2
D0_CAP = 0.5                                                    # 6.2
LIQ_FRAC = 0.001                                                # 6.2
MIN_NOTIONAL = 5.0                                              # 6.2
LEV_MAX = 10                                                    # 6.3
LIQ_MULT = 1.5                                                  # 6.3
BRACKETS = ((25_000.0, 10, 0.05), (100_000.0, 5, 0.10), (250_000.0, 3, 0.15), (math.inf, 1, 0.25))  # 6.3
N_ADDS = 3                                                      # 6.4
CHAND = 3.0                                                     # 6.5
STOP_HC = 0.25                                                  # 6.7: a touched stop fills 25% of the way to the
STOP_HC_SENS = (0.0, 0.5)                                       #      bar's extreme beyond it; 16: f = 0, 0.5 reported
START = 1000.0                                                  # 9, 14
BUST_FRAC = 0.10                                                # 9: < $100
COSTS = {"base": (0.0005, 0.0010, 0.0003),                      # 8: (taker, slippage, funding per 8h)
         "x2": (0.0010, 0.0020, 0.0006)}
FUND_SENS = (0.0, 0.0010)                                       # 16: funding 0% and 0.10% per 8h
R_MAIN = 0.02                                                   # 9, 11, 13
R_LOW = 0.005                                                   # 16
BOARD_RS = (0.005, 0.02, 0.05, 0.10, 0.20)                      # 14
BOARD_X = (5, 10, 20, 30, 50, 100)                              # 14
N_SEEDS = 2000                                                  # 12
N_BOOT = 10_000                                                 # 13
BH_Q = 0.10                                                     # 13
K_PICKS = 5                                                     # 11.3
MIN_POS_SELECT = 35                                             # 11.2
MIN_POS_TEST = {"p2": 26, "p3": 19}                             # 13 T0
GOAL50_BASELINE = ("goal-50x baseline (for scale only): coin flip on the big four at 1-minute fills, about 1% of "
                   "months reach x50")

# ------------------------------------------------------------------ 3.2 excluded products (191, suffix USDT)
EXCL_INDEX = ("BTCDOM", "DEFI", "BLUEBIRD", "FOOTBALL", "DOTECO", "ALL")
EXCL_STABLE = ("USDC",)
EXCL_COMMOD = ("XAU", "XAG", "XPT", "XPD", "COPPER", "NATGAS", "BZ", "CL", "PAXG", "XAUT")
EXCL_ETF = ("QQQ", "SPY", "IWM", "SMH", "XLE", "XBI", "GDX", "URNM", "EWJ", "EWY", "EWZ", "EWT", "SLX", "SOXL", "SOXS",
            "TQQQ", "SQQQ", "TZA", "UVXY", "TBT", "TMF", "KORU", "BITO", "DRAM", "KODEX200", "CSOPSAMSUNG2L",
            "CSOPSKHYNIX2L", "MUU", "SNXX", "STXX", "SKUU")
EXCL_US = ("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "MU", "SNDK", "AVGO", "TSM", "ASML",
           "AMAT", "LRCX", "KLAC", "QCOM", "TXN", "MRVL", "SMCI", "DELL", "HPE", "IBM", "CSCO", "ORCL", "CRM", "ADBE",
           "NOW", "SNOW", "NET", "CRWD", "PANW", "SHOP", "UBER", "PYPL", "EBAY", "WMT", "COST", "HD", "KO", "V", "JPM",
           "GS", "BX", "BRKB", "DIS", "NFLX", "TTWO", "RDDT", "ZM", "APP", "LLY", "MRK", "MRNA", "NVO", "HIMS", "TEM",
           "COIN", "HOOD", "MSTR", "STRC", "CRCL", "PLTR", "MARA", "IREN", "BMNR", "FWDI", "CRWV", "NBIS", "ARM",
           "COHR", "WDC", "CIEN", "ALAB", "CRDO", "AAOI", "AXTI", "GLW", "LITE", "ONDS", "ASTS", "RKLB", "IONQ", "SOFI",
           "RIVN", "DKNG", "GME", "DJT", "GEV", "VRT", "VST", "BE", "FLNC", "CAT", "TER", "FLEX", "NOK", "USAR", "PDD",
           "BABA", "SONY", "CBRS")
EXCL_ASIA = ("SAMSUNG", "SAMSUNGEM", "SKHYNIX", "SKHY", "HYUNDAI", "NAVER", "HANMI", "LGELECTRONICS", "HK0700",
             "HK1810", "TENCENT", "MEITUAN", "KUAISHOU", "POPMART", "ZHONGJI", "GIGADEV", "CXMT")
EXCL_PREIPO = ("ANTHROPIC", "OPENAI", "SPCX", "MINIMAX", "ZHIPU", "UNITREE")
EXCL_BATCH = ("BBX", "BNC", "BOT", "BSP", "DOS", "EDGE", "GRAM", "INTW", "INX", "KSTR", "LYTE", "MVLL", "PENG", "PRL",
              "RAM", "SHAZ", "SKDD")
TRADFI = frozenset(x + "USDT" for x in EXCL_COMMOD + EXCL_ETF + EXCL_US + EXCL_ASIA + EXCL_PREIPO + EXCL_BATCH)
INDEX_STABLE = frozenset(x + "USDT" for x in EXCL_INDEX + EXCL_STABLE)
EXCLUDED = INDEX_STABLE | TRADFI                                # 191
RENAMES = (("BTT", "1000BTTC"), ("LEND", "AAVE"), ("COCOS", "COMBO"), ("RNDR", "RENDER"), ("GAL", "G"),
           ("MATIC", "POL"), ("KLAY", "KAIA"), ("FTM", "S"), ("DAR", "D"), ("LIT", "HEI"), ("EOS", "A"),
           ("MKR", "SKY"), ("FXS", "FRAX"), ("OM", "MANTRA"))   # 3.1, old -> new (14)


# ------------------------------------------------------------------ 5: the 28 variants
def _variants() -> list:
    out = []
    for x in (20, 30, 50):
        for ex in ("M", "H7"):
            out.append({"id": f"P1_X{x}_{ex}", "family": "P1", "group": "P1", "side": 1, "x": x / 100.0,
                        "exit": ex[0], "hold": 7 if ex == "H7" else 0})
    for x in (20, 30, 50):
        for ex in ("M", "H7"):
            out.append({"id": f"P2_X{x}_{ex}", "family": "P2", "group": "P2", "side": -1, "x": x / 100.0,
                        "exit": ex[0], "hold": 7 if ex == "H7" else 0})
    for sd, side in (("L", 1), ("S", -1)):
        for k in (1, 7):
            for ex in ("M", "H28"):
                out.append({"id": f"P3{sd}_K{k}_{ex}", "family": "P3", "group": f"P3{sd}", "side": side, "k": k,
                            "exit": ex[0], "hold": 28 if ex == "H28" else 0})
    for sd, side in (("L", 1), ("S", -1)):
        for n in (5, 10):
            for ex in ("M", "H28"):
                out.append({"id": f"P4{sd}_N{n}_{ex}", "family": "P4", "group": f"P4{sd}", "side": side, "n": n,
                            "exit": ex[0], "hold": 28 if ex == "H28" else 0})
    for i, v in enumerate(out):
        v["order"] = i
    return out


VARIANTS = _variants()
VARIANT = {v["id"]: v for v in VARIANTS}


def caps(r: float) -> tuple:
    """Section 7: (n_max, total open-risk cap as a fraction of equity)."""
    if r <= 0.02 + 1e-12:
        return 6, 4.0 * r
    cap = min(4.0 * r, 0.60)
    return int(math.floor(cap / r + 1e-9)), cap


# ------------------------------------------------------------------ small helpers
class PinError(RuntimeError):
    pass


def gday(s: str) -> int:
    return int(np.datetime64(s, "D").astype(np.int64))


def day_str(g: int) -> str:
    return str(np.datetime64(int(g), "D"))


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def seed_int(*parts) -> int:
    """sha256 of the parts joined by '|' -> 64-bit seed (section 12; floats written with %g)."""
    s = "|".join(f"{p:g}" if isinstance(p, float) else str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(s.encode()).digest()[:8], "little")


def rng_of(*parts) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(seed_int(*parts)))


def git_commit(root: str = ROOT) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                              timeout=10).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _write_json(path: str, obj) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, sort_keys=False, default=_json_default)
    os.replace(tmp, path)
    return path


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    raise TypeError(type(o))


def _f(x):
    """JSON-safe float."""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


# ------------------------------------------------------------------ pin (section 18)
def read_pin(root: str = ROOT) -> list:
    path = os.path.join(root, PIN_REL)
    if not os.path.exists(path):
        raise PinError(f"{PIN_REL} does not exist: the study is not pinned (section 18)")
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


def check_pin(step: str, root: str = ROOT) -> dict:
    """Refuse (PinError) unless every listed file matches and the required files are listed. select: pick.json must
    not be pinned yet; test / board / pass2: pick.json must be pinned and unchanged."""
    rows = read_pin(root)
    listed = {p: h for h, p in rows}
    bad = []
    for h, p in rows:
        full = os.path.join(root, p)
        if not os.path.exists(full):
            bad.append(f"missing {p}")
        elif sha256_file(full) != h:
            bad.append(f"changed {p}")
    for p in (PREREG_REL, CODE_REL):
        if p not in listed:
            bad.append(f"not pinned {p}")
    if step == "select" and PICK_REL in listed:
        bad.append(f"{PICK_REL} is already pinned: select ran; the picks do not change (11.4)")
    if step in ("test", "board", "pass2") and PICK_REL not in listed:
        bad.append(f"{PICK_REL} is not pinned: run select first (11.4)")
    if bad:
        raise PinError(f"{PIN_REL} does not match: " + "; ".join(bad))
    return {"pin_file": PIN_REL, "pin_sha256": sha256_file(os.path.join(root, PIN_REL)), "files": len(rows)}


def write_pin(root: str = ROOT) -> str:
    path = os.path.join(root, PIN_REL)
    if os.path.exists(path):
        raise PinError(f"{PIN_REL} already exists; a change after the pin goes to DEVIATIONS.md")
    with open(path, "w") as fh:
        for p in (PREREG_REL, CODE_REL):
            fh.write(f"{sha256_file(os.path.join(root, p))}  {p}\n")
    return path


def append_pick_line(root: str = ROOT) -> str:
    h = sha256_file(os.path.join(root, PICK_REL))
    with open(os.path.join(root, PIN_REL), "a") as fh:
        fh.write(f"{h}  {PICK_REL}\n")
    return h


# ------------------------------------------------------------------ data (section 2) and lives (3.1)
def check_data_sha(path: str, manifest_path: str) -> str:
    """Section 2: the file's sha256 must equal MANIFEST.json's; a mismatch stops the run."""
    man = json.load(open(manifest_path))
    want = man["files"][os.path.basename(path)]["sha256"]
    got = sha256_file(path)
    if got != want:
        raise RuntimeError(f"{path}: sha256 {got} != MANIFEST {want}; stopping (section 2)")
    return got


VALUE_COLS = ("open", "high", "low", "close", "quote_volume")


def read_frame(path: str, structure_only: bool = False, value_windows=None) -> pd.DataFrame:
    """Read the daily file. ``value_windows`` (a list of (first day, end day) as days since 1970-01-01, end
    excluded): the price and quote-volume values of rows outside every window are dropped (NaN) chunk by chunk while
    reading, and ``volume`` keeps only whether it is > 0 (the calendar, section 10). None = keep every value."""
    cols = ["symbol", "open_time", "volume"] if structure_only else list(COLS)
    dtypes = {"symbol": str, "open_time": np.int64}
    if structure_only or value_windows is None:
        return pd.read_csv(path, usecols=cols, dtype=dtypes)
    parts = []
    for ch in pd.read_csv(path, usecols=cols, dtype=dtypes, chunksize=200_000):
        g = ch["open_time"].values // DAY_MS
        keep = np.zeros(len(ch), np.bool_)
        for a, b in value_windows:
            keep |= (g >= a) & (g < b)
        for c in VALUE_COLS:
            ch[c] = np.where(keep, ch[c].values.astype(np.float64), np.nan)
        ch["volume"] = np.where(keep, ch["volume"].values, (ch["volume"].values > 0).astype(np.float64))
        parts.append(ch)
    df = pd.concat(parts, ignore_index=True)
    df.attrs["value_windows"] = [tuple(int(x) for x in w) for w in value_windows]
    return df


def step_windows(step: str, periods: dict = None) -> list | None:
    """Section 10: the days whose values a step may read. select: period 1 with its 60-day warm-up; test and pass2:
    periods 2 (with warm-up) and 3; board (all three periods are shown) and check (structure only): None."""
    periods = periods or PERIODS

    def win(p):
        a, b = periods[p]
        return (gday(a) - WARMUP_DAYS, gday(b))
    if step == "select":
        return [win("p1")]
    if step in ("test", "pass2"):
        return [win("p2"), win("p3")]
    return None


class Raw:
    """The whole file: the traded-day calendar of every symbol (structure, readable for every day, 3.1) and the rows'
    values, which only Market reads, inside its window (section 10). ``value_windows`` (from read_frame or given):
    a Market whose window is not inside one of them refuses to build."""

    def __init__(self, df: pd.DataFrame, renames=RENAMES, value_windows=None):
        syms = sorted(df["symbol"].unique().tolist())
        self.syms = syms
        self.sym_ix = {s: i for i, s in enumerate(syms)}
        if value_windows is None:
            value_windows = df.attrs.get("value_windows")
        self.value_windows = None if value_windows is None else [tuple(int(x) for x in w) for w in value_windows]
        code = pd.Categorical(df["symbol"].values, categories=syms).codes.astype(np.int64)
        day = (df["open_time"].values.astype(np.int64) // DAY_MS).astype(np.int64)
        self.first_day = int(day.min())
        self.last_day = int(day.max())
        self.n_days = self.last_day - self.first_day + 1
        has = df["volume"].values > 0                           # 2: volume = 0 is no bar
        self.code = code[has]
        self.dix = day[has] - self.first_day
        self.cal = np.zeros((len(syms), self.n_days), dtype=np.bool_)
        self.cal[self.code, self.dix] = True
        self.vals = {}
        for c in VALUE_COLS:
            if c in df.columns:
                v = df[c].values[has].astype(np.float64)
                if self.value_windows is not None:                # values outside the windows never enter (10)
                    g = day[has]
                    keep = np.zeros(len(g), np.bool_)
                    for a, b in self.value_windows:
                        keep |= (g >= a) & (g < b)
                    v = np.where(keep, v, np.nan)
                self.vals[c] = v
        self._lives(renames)

    def values_cover(self, g0: int, g1: int) -> bool:
        """True when the values of days g0 .. g1-1 were loaded (section 10)."""
        if self.value_windows is None:
            return True
        return any(a <= g0 and g1 <= b for a, b in self.value_windows)

    def _lives(self, renames) -> None:
        S, T = self.cal.shape
        self.lid = np.full((S, T), -1, np.int64)
        self.lbi = np.full((S, T), -1, np.int64)
        self.pregap = np.zeros((S, T), np.bool_)                   # 6.8: a bar followed by a no-bar day, same life
        lf, ll, ls, lno, lgap = [], [], [], [], []
        for s in range(S):
            bars = np.flatnonzero(self.cal[s])
            if not len(bars):
                continue
            gaps = np.diff(bars) - 1
            new = np.r_[True, gaps >= PAUSE_GAP]                  # 3.1: 7+ days without a bar end a life
            gap_before = np.r_[-1, gaps]
            starts = np.flatnonzero(new)
            ends = np.r_[starts[1:], len(bars)]
            for n, (a, b) in enumerate(zip(starts, ends)):
                li = len(lf)
                seg = bars[a:b]
                self.lid[s, seg] = li
                self.lbi[s, seg] = np.arange(len(seg))
                self.pregap[s, seg[:-1][np.diff(seg) > 1]] = True
                lf.append(int(seg[0]))
                ll.append(int(seg[-1]))
                ls.append(s)
                lno.append(n)
                lgap.append(int(gap_before[a]))
        self.life_first = np.asarray(lf, np.int64)
        self.life_last = np.asarray(ll, np.int64)
        self.life_sym = np.asarray(ls, np.int64)
        self.life_no = np.asarray(lno, np.int64)
        self.life_gap_before = np.asarray(lgap, np.int64)         # days without a bar before the life (-1: first life)
        self.life_delist = self.life_last < T - 1                 # 3.1: a life ending before the file's last day
        # 3.1 partial days (archive holes): many lives covering the day lack a bar on it
        cover = np.zeros(T + 1, np.int64)
        np.add.at(cover, self.life_first, 1)
        np.add.at(cover, self.life_last + 1, -1)
        cover = np.cumsum(cover)[:T]
        lacking = cover - self.cal.sum(axis=0)
        self.partial = (lacking >= PARTIAL_MIN_MISSING) & (lacking >= PARTIAL_FRAC * np.maximum(cover, 1))
        # 3.1: a listing = the first bar of a symbol's first life or of a life after 30+ days without a bar; not a
        # life on the archive's first day, not a life after a 7..29-day pause, not a rename successor (below)
        listing = (self.life_first > 0) & ((self.life_no == 0) | (self.life_gap_before >= RELIST_GAP))
        self.successor = {}
        for old, new in renames:
            o, n_ = old + "USDT", new + "USDT"
            if o not in self.sym_ix or n_ not in self.sym_ix:
                continue
            so, sn = self.sym_ix[o], self.sym_ix[n_]
            nb = np.flatnonzero(self.cal[sn])
            if not len(nb):
                continue
            # the old symbol's life before the new symbol's first bar (a later relisting of the old name, e.g. LIT,
            # is another contract and does not count)
            ol = np.flatnonzero((self.life_sym == so) & (self.life_first < nb[0]))
            if not len(ol):
                continue
            diff = int(nb[0] - self.life_last[ol[-1]])
            if diff <= RENAME_DAYS:                               # first bar within 60 days after the old last bar
                self.successor[n_] = (o, diff)
                first_life = np.flatnonzero((self.life_sym == sn) & (self.life_no == 0))
                listing[first_life] = False
        self.life_listing = listing


def load_raw(path: str, manifest_path: str | None = None, structure_only: bool = False, value_windows=None) -> tuple:
    sha = check_data_sha(path, manifest_path) if manifest_path else sha256_file(path)
    return Raw(read_frame(path, structure_only, value_windows)), sha


# ------------------------------------------------------------------ 4: indicators (numba)
@njit(cache=True)
def _indicators(bar, h, l, c, qv, lid):
    """Per symbol, per life segment inside the window, causal: ATR14 (young mean, then Wilder), 1- and 7-bar returns,
    20-bar mean volume (d excluded), 30-bar high / low (d excluded), 7-day median quote volume (days d-6..d), std of
    the last (up to) 30 log returns (ddof 1)."""
    S, T = bar.shape
    atr = np.full((S, T), np.nan)
    r1 = np.full((S, T), np.nan)
    r7 = np.full((S, T), np.nan)
    vm20 = np.full((S, T), np.nan)
    hh30 = np.full((S, T), np.nan)
    ll30 = np.full((S, T), np.nan)
    med7 = np.full((S, T), np.nan)
    sd30 = np.full((S, T), np.nan)
    idx = np.empty(T, np.int64)
    trs = np.empty(T)
    lr = np.empty(T)
    buf = np.empty(7)
    for s in range(S):
        n = 0
        for t in range(T):
            if bar[s, t]:
                idx[n] = t
                n += 1
        seg = 0
        a = 0.0
        for k in range(n):
            t = idx[k]
            if k > 0 and lid[s, t] != lid[s, idx[k - 1]]:
                seg = k
            j = k - seg
            if j == 0:
                tr = h[s, t] - l[s, t]
                lr[k] = np.nan
            else:
                pc = c[s, idx[k - 1]]
                hi = h[s, t] if h[s, t] > pc else pc
                lo = l[s, t] if l[s, t] < pc else pc
                tr = hi - lo
                lr[k] = np.log(c[s, t] / pc)
                r1[s, t] = c[s, t] / pc - 1.0
            trs[k] = tr
            if j <= 13:
                tot = 0.0
                for m in range(seg, k + 1):
                    tot += trs[m]
                a = tot / (j + 1)
            else:
                a = (13.0 * a + tr) / 14.0
            atr[s, t] = a
            if j >= 7:
                r7[s, t] = c[s, t] / c[s, idx[k - 7]] - 1.0
            if j >= 20:
                tot = 0.0
                for m in range(k - 20, k):
                    tot += qv[s, idx[m]]
                vm20[s, t] = tot / 20.0
            if j >= 30:
                hi = -np.inf
                lo = np.inf
                for m in range(k - 30, k):
                    if h[s, idx[m]] > hi:
                        hi = h[s, idx[m]]
                    if l[s, idx[m]] < lo:
                        lo = l[s, idx[m]]
                hh30[s, t] = hi
                ll30[s, t] = lo
            nb7 = 0
            m = k
            while m >= seg and idx[m] >= t - 6:
                buf[nb7] = qv[s, idx[m]]
                nb7 += 1
                m -= 1
            med7[s, t] = np.median(buf[:nb7])
            lo_k = seg + 1
            if k - 29 > lo_k:
                lo_k = k - 29
            cn = k - lo_k + 1
            if cn >= 2:
                mu = 0.0
                for m in range(lo_k, k + 1):
                    mu += lr[m]
                mu /= cn
                v = 0.0
                for m in range(lo_k, k + 1):
                    v += (lr[m] - mu) ** 2
                sd30[s, t] = np.sqrt(v / (cn - 1))
    return atr, r1, r7, vm20, hh30, ll30, med7, sd30


@njit(cache=True)
def _p4_cond(trad, r7, c, hh30, ll30, N, side, skip):
    """5 P4: on day t, among tradable symbols with a 7-day return (at least 3N of them), the top N (long; bottom N
    short; ties by symbol order) whose close breaks the 30-day high (low). Not ranked on a partial day (skip, 3.1)."""
    S, T = trad.shape
    out = np.zeros((S, T), np.bool_)
    cand = np.empty(S, np.int64)
    key = np.empty(S)
    for t in range(T):
        if skip[t]:
            continue
        n = 0
        for s in range(S):
            if trad[s, t] and np.isfinite(r7[s, t]):
                cand[n] = s
                key[n] = -r7[s, t] if side > 0 else r7[s, t]
                n += 1
        if n < 3 * N:
            continue
        order = np.argsort(key[:n], kind="mergesort")
        for i in range(N):
            s = cand[order[i]]
            if side > 0:
                if np.isfinite(hh30[s, t]) and c[s, t] > hh30[s, t]:
                    out[s, t] = True
            else:
                if np.isfinite(ll30[s, t]) and c[s, t] < ll30[s, t]:
                    out[s, t] = True
    return out


@njit(cache=True)
def _event(cond, bar, lid, skip):
    """True on a bar where cond holds and held not on the symbol's previous bar of the same life. Partial days (skip,
    3.1) are not evaluated: never an event, and never the 'previous bar' (the check looks past them)."""
    S, T = cond.shape
    out = np.zeros((S, T), np.bool_)
    for s in range(S):
        prev = -1
        for t in range(T):
            if not bar[s, t] or skip[t]:
                continue
            was = False
            if prev >= 0 and lid[s, prev] == lid[s, t]:
                was = cond[s, prev]
            out[s, t] = cond[s, t] and not was
            prev = t
    return out


# ------------------------------------------------------------------ 3.3, 4, 10: one period's market
class Market:
    """One period's window (60 days of warm-up before its start, section 10) for the symbols not excluded (3.2).
    Arrays are [symbol, day]; day 0 = the window's first day; the period is days p0 .. p1-1."""

    def __init__(self, raw: Raw, start: str, end: str, excluded=EXCLUDED, warmup: int = WARMUP_DAYS, name: str = ""):
        self.name = name
        self.start, self.end = start, end
        p0g, p1g = gday(start), min(gday(end), raw.last_day + 1)
        w0g = max(raw.first_day, p0g - warmup)
        self.w0g, self.p0g, self.p1g = w0g, p0g, p1g
        if not raw.values_cover(w0g, p1g):
            raise RuntimeError(f"Market {name or start}: days {day_str(w0g)}..{day_str(p1g - 1)} lie outside the "
                               "values this step loaded (section 10)")
        T = p1g - w0g
        self.T = T
        self.p0, self.p1 = p0g - w0g, T
        keep = [i for i, s in enumerate(raw.syms) if s not in excluded]
        self.syms = np.asarray([raw.syms[i] for i in keep])
        S = len(keep)
        self.S = S
        remap = np.full(len(raw.syms), -1, np.int64)
        remap[keep] = np.arange(S)
        a, b = w0g - raw.first_day, p1g - raw.first_day
        self.bar = np.ascontiguousarray(raw.cal[keep, a:b])
        self.lid = np.ascontiguousarray(raw.lid[keep, a:b])
        self.lbi = np.ascontiguousarray(raw.lbi[keep, a:b])
        self.pregap = np.ascontiguousarray(raw.pregap[keep, a:b])  # 6.8: next calendar day has no bar, same life
        self.partial = np.ascontiguousarray(raw.partial[a:b])      # 3.1: archive-hole days (P4 not ranked)
        sel = (raw.dix >= a) & (raw.dix < b) & (remap[raw.code] >= 0)    # only rows inside the window are read
        rs, rt = remap[raw.code[sel]], raw.dix[sel] - a
        arr = {}
        for c in ("open", "high", "low", "close", "quote_volume"):
            x = np.full((S, T), np.nan)
            x[rs, rt] = raw.vals[c][sel]
            arr[c] = x
        self.o, self.h, self.l, self.c, self.qv = arr["open"], arr["high"], arr["low"], arr["close"], arr["quote_volume"]
        # delisting (3.1, 6.8): the last bar of a life that ends before the file's last day
        self.delist = np.zeros((S, T), np.bool_)
        self.lst_off = np.full((S, T), -1, np.int64)              # P3: calendar days since the listing bar
        lids = self.lid
        valid = lids >= 0
        lv = np.where(valid, lids, 0)
        last_g = raw.life_last[lv] + raw.first_day
        first_g = raw.life_first[lv] + raw.first_day
        tg = np.arange(T)[None, :] + w0g
        self.delist = valid & raw.life_delist[lv] & (last_g == tg)
        lst = valid & raw.life_listing[lv]
        self.lst_off = np.where(lst, tg - first_g, -1)
        (self.atr, self.r1, self.r7, self.vm20, self.hh30, self.ll30, self.med7,
         self.sd30) = _indicators(self.bar, self.h, self.l, self.c, self.qv, self.lid)
        stable_ok = (self.lbi + 1 < STABLE_MIN_BARS) | ~(self.sd30 < STABLE_STD)
        self.trad = self.bar & (self.med7 >= VOL_FLOOR) & stable_ok          # 3.3 (a)-(d)
        self.n_ranked = (self.trad & np.isfinite(self.r7)).sum(axis=0)      # 5 P4: symbols with a 7-day return
        # months of the period (UTC calendar)
        days = (np.arange(T) + w0g).astype("datetime64[D]")
        ym = days.astype("datetime64[M]")
        self.month_of_day = np.full(T, -1, np.int64)
        pm = ym[self.p0:]
        uniq, inv = np.unique(pm, return_inverse=True)
        self.month_of_day[self.p0:] = inv
        self.months = [str(u) for u in uniq]
        self.n_months = len(uniq)
        self._masks = {}
        self._daily = None

    def day(self, t: int) -> str:
        return day_str(self.w0g + int(t))

    def universe_size(self) -> dict:
        n = self.trad[:, self.p0:self.p1].sum(axis=0)
        return {"min": int(n.min()) if len(n) else 0, "median": float(np.median(n)) if len(n) else 0.0,
                "max": int(n.max()) if len(n) else 0}

    # ---- 5: entries
    def _in_period(self) -> np.ndarray:
        m = np.zeros(self.T, np.bool_)
        m[self.p0:max(self.p0, self.p1 - 1)] = True                 # signal day and fill day inside the period (6.8)
        return m

    def mask(self, v: dict) -> np.ndarray:
        fam = v["family"]
        key = (fam, v.get("x"), v.get("k"), v.get("n"), v["side"] if fam == "P4" else 0)
        if key in self._masks:
            return self._masks[key]
        ok = self._in_period()[None, :]
        if fam in ("P1", "P2"):
            with np.errstate(invalid="ignore"):
                m = (self.trad & (self.lbi >= 20) & (self.r1 >= v["x"]) & (self.vm20 > 0)
                     & (self.qv >= 3.0 * self.vm20))
        elif fam == "P3":
            m = self.trad & (self.lst_off == v["k"] - 1)
        elif fam == "P4":
            cond = _p4_cond(self.trad, self.r7, self.c, self.hh30, self.ll30, int(v["n"]), int(v["side"]),
                            self.partial)
            m = _event(cond, self.bar, self.lid, self.partial) & (self.lbi >= 30)
        else:
            raise ValueError(fam)
        m = m & ok
        self._masks[key] = m
        return m

    def order(self, day: np.ndarray, sym: np.ndarray) -> np.ndarray:
        """7: same-day signals in order of the 7-day median quote volume (largest first), ties by symbol name."""
        return np.lexsort((sym, -self.med7[sym, day], day))

    def signals(self, v: dict) -> "Sig":
        s, t = np.nonzero(self.mask(v))
        o = self.order(t, s)
        return Sig(t[o].astype(np.int64), s[o].astype(np.int64), np.full(len(o), v["side"], np.int64))

    def control_pools(self, v: dict) -> list:
        """12 (b): per symbol, the days on which variant ``v`` could have fired apart from its event: tradable, in the
        period with the next day in it and holding a bar, and the variant's own non-event conditions (P1 / P2: the
        life has >= 21 bars; P4: >= 31 bars, at least 3N ranked symbols, not a partial day; P3: none)."""
        ok = self.trad.copy()
        ok[:, :self.p0] = False
        ok[:, max(self.p0, self.p1 - 1):] = False
        nxt = np.zeros_like(self.bar)
        nxt[:, :-1] = self.bar[:, 1:]
        ok &= nxt
        fam = v["family"]
        if fam in ("P1", "P2"):
            ok &= self.lbi >= 20
        elif fam == "P4":
            ok &= (self.lbi >= 30) & (self.n_ranked >= 3 * int(v["n"]))[None, :] & ~self.partial[None, :]
        elif fam != "P3":
            raise ValueError(fam)
        return [np.flatnonzero(ok[s]) for s in range(self.S)]

    def daily_sub(self) -> "Sub":
        if self._daily is None:
            self._daily = Sub.daily(self)
        return self._daily


class Sig:
    __slots__ = ("day", "sym", "side")

    def __init__(self, day, sym, side):
        self.day, self.sym, self.side = day, sym, side

    def __len__(self):
        return len(self.day)


class Sub:
    """Intraday fills (6.7, 15): for each symbol-day with sub-bars, ``slen`` slots starting at ``off`` (1 = one bar
    for the whole day; 288 = 5m bars); ``nb`` = the most slots of any day. A day with a daily bar and off < 0 (in the
    5m pass: its 5m bars are missing or do not reach the daily high and low) runs on the daily bar in the engine.
    Price o/h/l and mark o/h/l (liquidation), funding events (fund_mode 1; a symbol-day without events pays the fixed
    charge) or the fixed daily charge (fund_mode 0)."""

    def __init__(self, off, slen, o, h, l, mo, mh, ml, nb, fe_off, fe_cnt, fe_slot, fe_rate, fe_mark, fund_mode):
        self.off, self.slen = off, slen
        self.o, self.h, self.l, self.mo, self.mh, self.ml = o, h, l, mo, mh, ml
        self.nb, self.fund_mode = nb, fund_mode
        self.fe_off, self.fe_cnt, self.fe_slot, self.fe_rate, self.fe_mark = fe_off, fe_cnt, fe_slot, fe_rate, fe_mark

    @classmethod
    def daily(cls, mk: Market) -> "Sub":
        S, T = mk.S, mk.T
        off = np.where(mk.bar, np.arange(S)[:, None] * T + np.arange(T)[None, :], -1).astype(np.int64)
        o, h, l = mk.o.ravel(), mk.h.ravel(), mk.l.ravel()
        return cls(off, mk.bar.astype(np.int64), o, h, l, o, h, l, 1, np.full((S, T), -1, np.int64),
                   np.zeros((S, T), np.int64), np.zeros(0, np.int64), np.zeros(0), np.zeros(0), 0)


# ------------------------------------------------------------------ 6-9: the account engine (numba)
F_Q, F_COST, F_REFQ, F_STOP, F_LIQ, F_LEV, F_MARGIN, F_B, F_U, F_D0, F_Q1, F_NEXT, F_EXT, F_FEES, F_FUND, F_P0, \
    F_LASTC, F_MED7 = range(18)
NF = 18
P_SIDE, P_SYM, P_TRIED, P_FILLED, P_BARS, P_REC, P_SRC = range(7)
NPI = 7
R_PNL, R_PRICE, R_FEES, R_FUND, R_U, R_RISK1, R_LEV, R_P0, R_XPX, R_D0F = range(10)
NRF = 10
RI_TIN, RI_TOUT, RI_SYM, RI_SIDE, RI_ADDS, RI_TRIED, RI_REASON, RI_SRC, RI_D0CAP, RI_MONTH, RI_FLAG = range(11)
NRI = 11
EX_STOP, EX_GAP, EX_LIQ, EX_HOLD, EX_DELIST, EX_PEND, EX_MEND, EX_BUST, EX_HOLE = range(9)
EXIT_NAMES = ("stop", "stop_gap_open", "liquidation", "hold_close", "delisting_close", "period_end_marked",
              "month_end_close", "bust_close", "close_before_no_bar_day")
SRC_FIRST, SRC_ADD, SRC_CHAND = range(3)
SRC_NAMES = ("first_stop", "add_moved_stop", "chandelier")
CNT_NAMES = ("signals_seen", "lapsed_no_next_bar", "skip_has_position", "skip_n_max", "skip_risk_cap",
             "skip_no_leverage", "skip_min_notional", "skip_bad_d0", "skip_after_bust", "pass2_daily_bar_days",
             "cut_liquidity", "cut_margin_budget", "cut_free_wallet", "d0_cap",
             "add_skip_risk_cap", "add_skip_margin_budget", "add_skip_free_wallet", "add_skip_liquidity",
             "add_skip_min_notional", "add_skip_liq_not_beyond_stop", "add_cut_liquidity", "add_cut_margin_budget",
             "add_cut_free_wallet", "adds_filled")
(C_SEEN, C_LAPSE, C_HASPOS, C_NMAX, C_RISK, C_NOLEV, C_MINNOT, C_BADD0, C_STOPPED, C_DAYBAR, C_CUT_LIQ, C_CUT_MARGIN,
 C_CUT_FREE, C_D0CAP, A_RISK, A_MARGIN, A_FREE, A_LIQUIDITY, A_MINNOT, A_LIQBEYOND, A_CUT_LIQ, A_CUT_MARGIN,
 A_CUT_FREE, A_FILLED) = range(24)
NCNT = 24
PR_START, PR_R, PR_CAP, PR_TAKER, PR_SLIP, PR_FUNDDAY, PR_BUST, PR_CHAND, PR_D0ATR, PR_D0CAP, PR_LIQFRAC, \
    PR_MINNOT, PR_LIQMULT, PR_STOPHC = range(14)
NPR = 14
IP_NMAX, IP_LEVMAX, IP_NADDS, IP_HOLD, IP_MONTHLY, IP_FUNDMODE, IP_NB, IP_P0, IP_P1, IP_TRAIL = range(10)
NIP = 10


@njit(cache=True)
def _bracket(notional, br_cap):
    for i in range(len(br_cap)):
        if notional <= br_cap[i]:
            return i
    return len(br_cap) - 1


@njit(cache=True)
def _liq_price(side, avg, L, mmr):
    """6.3: isolated, fees ignored: long avg x (1 - 1/L + mmr), short avg x (1 + 1/L - mmr)."""
    if side > 0:
        return avg * (1.0 - 1.0 / L + mmr)
    return avg * (1.0 + 1.0 / L - mmr)


@njit(cache=True)
def _choose_lev(N4, B, d0_frac, lev_max, liq_mult, br_cap, br_lev, br_mmr):
    """6.3: the smallest L in 1..lev_max with (i) L allowed by the bracket at N4, (ii) N4 / L <= B, (iii) 1/L - mmr
    >= liq_mult x D0 / P0; else the largest L meeting (i) and (iii); 0 = none."""
    b = _bracket(N4, br_cap)
    best = 0
    for L in range(1, lev_max + 1):
        if L <= br_lev[b] and (1.0 / L - br_mmr[b]) >= liq_mult * d0_frac - 1e-12:
            if N4 / L <= B * (1.0 + 1e-12):
                return L
            best = L
    return best


@njit(cache=True)
def _risk(k, ps, pi):
    """7: open risk of a position = max(0, sum q_i (ref_i - stop)) (long; short mirror)."""
    v = pi[k, P_SIDE] * (ps[k, F_REFQ] - ps[k, F_Q] * ps[k, F_STOP])
    return v if v > 0.0 else 0.0


@njit(cache=True)
def _try_add(k, ref, ps, pi, acc, others, cap_abs, taker, slip, min_not, liq_frac, cnt, br_cap, br_mmr):
    """6.4: one add of q at reference ``ref``; True when filled (stop moved to S_req if tighter, liquidation updated)."""
    side = pi[k, P_SIDE]
    L = ps[k, F_LEV]
    afill = ref * (1.0 + side * slip)
    qa = ps[k, F_Q1]
    why = -1
    cl = False
    cm = False
    cf = False
    qmax = liq_frac * ps[k, F_MED7] / ref
    if qa > qmax:
        qa = qmax
        cl = True
        why = A_LIQUIDITY
    room = (ps[k, F_B] - ps[k, F_MARGIN]) * L / afill
    if qa > room:
        qa = room
        cm = True
        why = A_MARGIN
    free = acc[0] - acc[1]
    if qa * afill / L + taker * qa * afill > free:
        qa = free / (afill * (1.0 / L + taker))
        cf = True
        why = A_FREE
    if not (qa > 0.0):
        cnt[why if why >= 0 else A_MARGIN] += 1
        return False
    if qa * afill < min_not:
        cnt[A_MINNOT] += 1
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
        cnt[A_RISK] += 1
        return False
    costn = ps[k, F_COST] + qa * afill
    b = _bracket(costn, br_cap)
    liqn = _liq_price(side, costn / Qn, L, br_mmr[b])
    if (side > 0 and liqn >= nstop) or (side < 0 and liqn <= nstop):
        cnt[A_LIQBEYOND] += 1
        return False
    fee = taker * qa * afill
    acc[0] -= fee
    acc[2] += fee
    ps[k, F_FEES] += fee
    mg = qa * afill / L
    ps[k, F_MARGIN] += mg
    acc[1] += mg
    ps[k, F_Q] = Qn
    ps[k, F_COST] = costn
    ps[k, F_REFQ] = refqn
    if nstop != stop:
        ps[k, F_STOP] = nstop
        pi[k, P_SRC] = SRC_ADD
    ps[k, F_LIQ] = liqn
    pi[k, P_FILLED] += 1
    cnt[A_FILLED] += 1
    if cl:
        cnt[A_CUT_LIQ] += 1
    if cm:
        cnt[A_CUT_MARGIN] += 1
    if cf:
        cnt[A_CUT_FREE] += 1
    return True


@njit(cache=True)
def _close(k, X, reason, t, ps, pi, rf, ri, acc, taker, slip):
    """Close the whole position at ``X``: market / stop fills with slippage against and taker; a liquidation loses
    the whole isolated margin; the period-end mark (EX_PEND) has no costs."""
    side = pi[k, P_SIDE]
    Q = ps[k, F_Q]
    if reason == EX_LIQ:
        xf = X
        price_pnl = -ps[k, F_MARGIN]
        fee = 0.0
    elif reason == EX_PEND:
        xf = X
        price_pnl = side * (Q * xf - ps[k, F_COST])
        fee = 0.0
    else:
        xf = X * (1.0 - side * slip)
        price_pnl = side * (Q * xf - ps[k, F_COST])
        fee = taker * Q * xf
    acc[0] += price_pnl - fee
    acc[1] -= ps[k, F_MARGIN]
    acc[2] += fee
    ps[k, F_FEES] += fee
    rec = pi[k, P_REC]
    rf[rec, R_PNL] = price_pnl - ps[k, F_FEES] - ps[k, F_FUND]
    rf[rec, R_PRICE] = price_pnl
    rf[rec, R_FEES] = ps[k, F_FEES]
    rf[rec, R_FUND] = ps[k, F_FUND]
    rf[rec, R_XPX] = xf
    ri[rec, RI_TOUT] = t
    ri[rec, RI_ADDS] = pi[k, P_FILLED]
    ri[rec, RI_TRIED] = pi[k, P_TRIED]
    ri[rec, RI_REASON] = reason
    ri[rec, RI_SRC] = pi[k, P_SRC]


@njit(cache=True)
def _drop(order, npos, k):
    j = 0
    for i in range(npos):
        if order[i] != k:
            order[j] = order[i]
            j += 1
    return j


@njit(cache=True)
def _equity(acc, ps, pi, order, npos):
    E = acc[0]
    for i in range(npos):
        k = order[i]
        E += pi[k, P_SIDE] * (ps[k, F_Q] * ps[k, F_LASTC] - ps[k, F_COST])
    return E


@njit(cache=True)
def _stop_hit(side, stop, liq, h, l, mh, ml, hc):
    """6.7: the stop or a liquidation inside one (sub-)bar (long; short mirror). The mark reaching liquidation before
    the price reaches the stop is a liquidation. A touched stop fills ``hc`` of the way from the stop to the bar's
    extreme beyond it (stop - hc x (stop - low)); a fill at or beyond the liquidation price is a liquidation (the
    whole isolated margin is lost). Returns (code, price), -1 = neither."""
    if side > 0:
        hs = l <= stop
        if ml <= liq and ((not hs) or liq >= stop):
            return EX_LIQ, liq
        if hs:
            fill = stop - hc * (stop - l)
            if fill <= liq:
                return EX_LIQ, liq
            return EX_STOP, fill
    else:
        hs = h >= stop
        if mh >= liq and ((not hs) or liq <= stop):
            return EX_LIQ, liq
        if hs:
            fill = stop + hc * (h - stop)
            if fill >= liq:
                return EX_LIQ, liq
            return EX_STOP, fill
    return -1, 0.0


@njit(cache=True)
def _slot(k, x, skip_open, sb_o, sb_h, sb_l, sb_mo, sb_mh, sb_ml, ps, pi, acc, others, cap_abs, taker, slip,
          min_not, liq_frac, cnt, br_cap, br_mmr, n_adds, hc):
    """6.7 / PREREG_HUNT 7.6 for one position on one (sub-)bar. Returns (code, price): -1 = still open. Order: open
    beyond liquidation, open at or beyond the stop (fills at the open), the stop (hair-cut fill), then each add level
    the bar reaches (a buy-stop add fills at the open when the open is beyond its level, else hc of the way from the
    level to the bar's extreme), each followed by the moved-stop check."""
    o = sb_o[x]
    h = sb_h[x]
    l = sb_l[x]
    mo = sb_mo[x]
    mh = sb_mh[x]
    ml = sb_ml[x]
    side = pi[k, P_SIDE]
    if not skip_open:
        if side > 0:
            if mo <= ps[k, F_LIQ]:
                return EX_LIQ, ps[k, F_LIQ]
            if o <= ps[k, F_STOP]:
                return EX_GAP, o
        else:
            if mo >= ps[k, F_LIQ]:
                return EX_LIQ, ps[k, F_LIQ]
            if o >= ps[k, F_STOP]:
                return EX_GAP, o
    code, px = _stop_hit(side, ps[k, F_STOP], ps[k, F_LIQ], h, l, mh, ml, hc)
    if code >= 0:
        return code, px
    while pi[k, P_TRIED] < n_adds and ((side > 0 and h >= ps[k, F_NEXT]) or (side < 0 and l <= ps[k, F_NEXT])):
        lvl = ps[k, F_NEXT]
        if side > 0:
            ref = o if o >= lvl else lvl + hc * (h - lvl)
        else:
            ref = o if o <= lvl else lvl - hc * (lvl - l)
        ok = _try_add(k, ref, ps, pi, acc, others, cap_abs, taker, slip, min_not, liq_frac, cnt, br_cap, br_mmr)
        pi[k, P_TRIED] += 1
        ps[k, F_NEXT] = (ref if ok else lvl) + side * ps[k, F_D0]
        if ok:
            code, px = _stop_hit(side, ps[k, F_STOP], ps[k, F_LIQ], h, l, mh, ml, hc)
            if code >= 0:
                return code, px
    if side > 0:
        if h > ps[k, F_EXT]:
            ps[k, F_EXT] = h
    else:
        if l < ps[k, F_EXT]:
            ps[k, F_EXT] = l
    return -1, 0.0


@njit(cache=True)
def _others(order, npos, k, ps, pi):
    tot = 0.0
    for i in range(npos):
        kk = order[i]
        if kk != k:
            tot += _risk(kk, ps, pi)
    return tot


@njit(cache=True)
def _fund_events(k, s, t, jlo, jhi, ps, pi, acc, fe_off, fe_cnt, fe_slot, fe_rate, fe_mark):
    """15: the archived funding events of symbol-day (s, t) at slots jlo .. jhi-1: long pays rate x notional at mark,
    short receives (signed)."""
    a = fe_off[s, t]
    if a < 0:
        return
    for e in range(a, a + fe_cnt[s, t]):
        if fe_slot[e] >= jlo and fe_slot[e] < jhi:
            fee = pi[k, P_SIDE] * fe_rate[e] * ps[k, F_Q] * fe_mark[e]
            acc[0] -= fee
            acc[3] += fee
            ps[k, F_FUND] += fee


@njit(cache=True)
def _fund_fixed(k, rate, px, ps, acc):
    """8: the fixed funding charge, rate x notional at px, against the position whatever its side."""
    fee = rate * ps[k, F_Q] * px
    acc[0] -= fee
    acc[3] += fee
    ps[k, F_FUND] += fee


@njit(cache=True)
def _engine(prm, iprm, br_cap, br_lev, br_mmr, bar, o_d, c_d, atr, med7, delist, pregap, month_of_day,
            od_f, hd_f, ld_f, sb_off, sb_len, sb_o, sb_h, sb_l, sb_mo, sb_mh, sb_ml, fe_off, fe_cnt, fe_slot,
            fe_rate, fe_mark, sig_day, sig_sym, sig_side):
    """One account (sections 6-9): continuous (iprm[IP_MONTHLY] = 0) or a fresh wallet every calendar month (14).
    Day order: (0) funding events at 00:00 (5m pass), (1) existing positions: liquidation / gap at the open, (2) the
    entries of yesterday's signals at the open, (3) the intraday slots (stop first, then adds, moved-stop exit),
    (4) the close: hold exit, delisting close, close before a day without a bar, chandelier, funding, equity, bust,
    month / period end. A day with a daily bar and no sub-bars (sb_off < 0) runs on the daily bar itself (od_f, hd_f,
    ld_f = the daily o/h/l flattened [s * T + t], mark = price): no bar day is ever skipped (15).
    Funding (8), fixed mode (the daily pass, or a 5m-pass symbol-day without archived events): a position open at a
    daily close pays one day (3 x 8h: 08:00 and 16:00 of the day, 00:00 of the next); a position that exits during
    the day or at its close pays 2 x 8h for that day (08:00 and 16:00, the worse case when the exit time is unknown);
    an exit at the open pays nothing more (its 00:00 was charged at the previous close)."""
    start = prm[PR_START]
    r = prm[PR_R]
    cap = prm[PR_CAP]
    taker = prm[PR_TAKER]
    slip = prm[PR_SLIP]
    fund_day = prm[PR_FUNDDAY]
    f8 = fund_day / 3.0
    bust_eq = prm[PR_BUST] * start
    chand = prm[PR_CHAND]
    d0_atr = prm[PR_D0ATR]
    d0_cap = prm[PR_D0CAP]
    liq_frac = prm[PR_LIQFRAC]
    min_not = prm[PR_MINNOT]
    liq_mult = prm[PR_LIQMULT]
    hc = prm[PR_STOPHC]
    n_max = iprm[IP_NMAX]
    lev_max = iprm[IP_LEVMAX]
    n_adds = iprm[IP_NADDS]
    hold = iprm[IP_HOLD]
    monthly = iprm[IP_MONTHLY]
    fund_mode = iprm[IP_FUNDMODE]
    nb = iprm[IP_NB]
    p0 = iprm[IP_P0]
    p1 = iprm[IP_P1]
    trail = iprm[IP_TRAIL]
    S, T = bar.shape
    n_m = month_of_day[p1 - 1] + 1
    ns = len(sig_day)
    ps = np.zeros((n_max, NF))
    pi = np.zeros((n_max, NPI), np.int64)
    used = np.zeros(n_max, np.bool_)
    order = np.zeros(n_max, np.int64)
    snap = np.zeros(n_max, np.int64)
    npos = 0
    has = np.full(S, -1, np.int64)
    rf = np.zeros((max(ns, 1), NRF))
    ri = np.zeros((max(ns, 1), NRI), np.int64)
    nrec = 0
    cnt = np.zeros(NCNT, np.int64)
    m_start = np.zeros(n_m)
    m_end = np.zeros(n_m)
    m_state = np.zeros(n_m, np.int64)
    day_eq = np.full(T, np.nan)
    acc = np.zeros(4)                       # wallet, isolated margins, fees, funding
    acc[0] = start
    E_prev = start
    stopped = False
    dead = False
    si = 0
    m_cur = -1
    for t in range(p0, p1):
        m = month_of_day[t]
        if m != m_cur:
            m_cur = m
            if monthly:
                acc[0] = start
                acc[1] = 0.0
                E_prev = start
                stopped = False
            m_start[m] = E_prev
            if dead:
                m_state[m] = 2
        last_of_month = (t == p1 - 1) or (month_of_day[t + 1] != m)
        if dead or stopped:
            while si < ns and sig_day[si] <= t - 1:
                if sig_day[si] == t - 1:
                    cnt[C_SEEN] += 1
                    cnt[C_STOPPED] += 1
                si += 1
            day_eq[t] = E_prev
            if last_of_month:
                m_end[m] = E_prev
            continue
        cap_abs = cap * E_prev
        # (0) funding events at slot 0, (1) open checks of the positions held overnight
        nsnap = npos
        for i in range(npos):
            snap[i] = order[i]
        for i in range(nsnap):
            k = snap[i]
            s = pi[k, P_SYM]
            if fund_mode == 1 and fe_cnt[s, t] > 0:
                _fund_events(k, s, t, 0, 1, ps, pi, acc, fe_off, fe_cnt, fe_slot, fe_rate, fe_mark)
            if not bar[s, t]:
                continue
            x0 = sb_off[s, t]
            if x0 >= 0:
                op = sb_o[x0]
                mop = sb_mo[x0]
            else:
                op = o_d[s, t]
                mop = op
            if np.isnan(op):
                continue
            side = pi[k, P_SIDE]
            code = -1
            px = 0.0
            if side > 0:
                if mop <= ps[k, F_LIQ]:
                    code, px = EX_LIQ, ps[k, F_LIQ]
                elif op <= ps[k, F_STOP]:
                    code, px = EX_GAP, op
            else:
                if mop >= ps[k, F_LIQ]:
                    code, px = EX_LIQ, ps[k, F_LIQ]
                elif op >= ps[k, F_STOP]:
                    code, px = EX_GAP, op
            if code >= 0:
                _close(k, px, code, t, ps, pi, rf, ri, acc, taker, slip)
                used[k] = False
                has[s] = -1
                npos = _drop(order, npos, k)
        # (2) entries at the open: yesterday's signals, in the order given (6.1-6.3, 7)
        while si < ns and sig_day[si] < t - 1:
            si += 1
        while si < ns and sig_day[si] == t - 1:
            s = sig_sym[si]
            side = sig_side[si]
            d = t - 1
            si += 1
            cnt[C_SEEN] += 1
            if not bar[s, t]:
                cnt[C_LAPSE] += 1
                continue
            if has[s] >= 0:
                cnt[C_HASPOS] += 1
                continue
            if npos >= n_max:
                cnt[C_NMAX] += 1
                continue
            P0 = o_d[s, t]
            D0 = d0_atr * atr[s, d]
            capped = 0
            if D0 > d0_cap * P0:
                D0 = d0_cap * P0
                capped = 1
            if not (D0 > 0.0) or not (P0 > 0.0) or not (E_prev > 0.0):
                cnt[C_BADD0] += 1
                continue
            U = r * E_prev
            q = U / D0
            flag = 0
            m7 = med7[s, d]
            qmax = liq_frac * m7 / P0
            if q > qmax:
                q = qmax
                flag |= 1
            N4 = 4.0 * q * P0
            B = E_prev / n_max
            L = _choose_lev(N4, B, D0 / P0, lev_max, liq_mult, br_cap, br_lev, br_mmr)
            if L == 0:
                cnt[C_NOLEV] += 1
                continue
            fill = P0 * (1.0 + side * slip)
            if q * fill / L > B:
                q = B * L / fill
                flag |= 2
            free = acc[0] - acc[1]
            if q * fill / L + taker * q * fill > free:
                q = free / (fill * (1.0 / L + taker))
                flag |= 4
            if not (q > 0.0) or q * fill < min_not:
                cnt[C_MINNOT] += 1
                continue
            tot = 0.0
            for i in range(npos):
                tot += _risk(order[i], ps, pi)
            if tot + q * D0 > cap_abs * (1.0 + 1e-9):
                cnt[C_RISK] += 1
                continue
            k = 0
            while used[k]:
                k += 1
            for x in range(NF):
                ps[k, x] = 0.0
            for x in range(NPI):
                pi[k, x] = 0
            used[k] = True
            fee = taker * q * fill
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
            ps[k, F_EXT] = P0
            ps[k, F_LASTC] = P0
            ps[k, F_MED7] = m7
            ps[k, F_LIQ] = _liq_price(side, fill, L, br_mmr[_bracket(q * fill, br_cap)])
            acc[0] -= fee
            acc[1] += q * fill / L
            acc[2] += fee
            pi[k, P_SIDE] = side
            pi[k, P_SYM] = s
            pi[k, P_SRC] = SRC_FIRST
            pi[k, P_REC] = nrec
            rf[nrec, R_U] = U
            rf[nrec, R_RISK1] = q * D0 / U
            rf[nrec, R_LEV] = L
            rf[nrec, R_P0] = P0
            rf[nrec, R_D0F] = D0 / P0
            ri[nrec, RI_TIN] = t
            ri[nrec, RI_SYM] = s
            ri[nrec, RI_SIDE] = side
            ri[nrec, RI_D0CAP] = capped
            ri[nrec, RI_MONTH] = m
            ri[nrec, RI_FLAG] = flag
            ri[nrec, RI_TOUT] = -1
            nrec += 1
            if capped:
                cnt[C_D0CAP] += 1
            if flag & 1:
                cnt[C_CUT_LIQ] += 1
            if flag & 2:
                cnt[C_CUT_MARGIN] += 1
            if flag & 4:
                cnt[C_CUT_FREE] += 1
            has[s] = k
            order[npos] = k
            npos += 1
        # (3) intraday slots in time order
        for j in range(nb):
            nsnap = npos
            for i in range(npos):
                snap[i] = order[i]
            for i in range(nsnap):
                k = snap[i]
                if not used[k]:
                    continue
                s = pi[k, P_SYM]
                if not bar[s, t]:
                    continue
                x0 = sb_off[s, t]
                if x0 >= 0:
                    if j >= sb_len[s, t]:
                        continue
                    oneday = sb_len[s, t] == 1
                    x = x0 + j
                    ao, ah, al, amo, amh, aml = sb_o, sb_h, sb_l, sb_mo, sb_mh, sb_ml
                else:
                    if j > 0:
                        continue
                    oneday = True
                    x = s * T + t
                    ao, ah, al, amo, amh, aml = od_f, hd_f, ld_f, od_f, hd_f, ld_f
                fixed = fund_mode == 0 or fe_cnt[s, t] == 0
                if not fixed:
                    if oneday:
                        # one bar stands for the whole day: all its later events first (the worse order)
                        _fund_events(k, s, t, 1, 1 << 30, ps, pi, acc, fe_off, fe_cnt, fe_slot, fe_rate, fe_mark)
                    elif j > 0:
                        _fund_events(k, s, t, j, j + 1, ps, pi, acc, fe_off, fe_cnt, fe_slot, fe_rate, fe_mark)
                if oneday and nb > 1:
                    cnt[C_DAYBAR] += 1
                if np.isnan(ao[x]):
                    continue
                others = _others(order, npos, k, ps, pi)
                code, px = _slot(k, x, j == 0, ao, ah, al, amo, amh, aml, ps, pi, acc, others,
                                 cap_abs, taker, slip, min_not, liq_frac, cnt, br_cap, br_mmr, n_adds, hc)
                if code >= 0:
                    if fixed:
                        _fund_fixed(k, 2.0 * f8, px, ps, acc)
                    _close(k, px, code, t, ps, pi, rf, ri, acc, taker, slip)
                    used[k] = False
                    has[s] = -1
                    npos = _drop(order, npos, k)
        # (4) the close
        nsnap = npos
        for i in range(npos):
            snap[i] = order[i]
        for i in range(nsnap):
            k = snap[i]
            s = pi[k, P_SYM]
            side = pi[k, P_SIDE]
            fixed = fund_mode == 0 or fe_cnt[s, t] == 0
            if bar[s, t]:
                pi[k, P_BARS] += 1
                ps[k, F_LASTC] = c_d[s, t]
                ps[k, F_MED7] = med7[s, t]
                xc = -1
                if hold > 0 and pi[k, P_BARS] >= hold:
                    xc = EX_HOLD
                elif delist[s, t]:
                    xc = EX_DELIST
                elif pregap[s, t]:
                    xc = EX_HOLE
                if xc >= 0:
                    if fixed:
                        _fund_fixed(k, 2.0 * f8, c_d[s, t], ps, acc)
                    _close(k, c_d[s, t], xc, t, ps, pi, rf, ri, acc, taker, slip)
                    used[k] = False
                    has[s] = -1
                    npos = _drop(order, npos, k)
                    continue
                if trail == 1:
                    if side > 0:
                        ch = ps[k, F_EXT] - chand * atr[s, t]
                        if ch > ps[k, F_STOP]:
                            ps[k, F_STOP] = ch
                            pi[k, P_SRC] = SRC_CHAND
                    else:
                        ch = ps[k, F_EXT] + chand * atr[s, t]
                        if ch < ps[k, F_STOP]:
                            ps[k, F_STOP] = ch
                            pi[k, P_SRC] = SRC_CHAND
            if fixed:
                _fund_fixed(k, fund_day, ps[k, F_LASTC], ps, acc)
        E = _equity(acc, ps, pi, order, npos)
        if E < bust_eq:
            nsnap = npos
            for i in range(npos):
                snap[i] = order[i]
            for i in range(nsnap):
                k = snap[i]
                _close(k, ps[k, F_LASTC], EX_BUST, t, ps, pi, rf, ri, acc, taker, slip)
                used[k] = False
                has[pi[k, P_SYM]] = -1
            npos = 0
            E = acc[0]
            m_state[m] = 1
            if monthly:
                stopped = True
            else:
                dead = True
        if npos > 0 and ((monthly and last_of_month) or ((not monthly) and t == p1 - 1)):
            code = EX_MEND if monthly else EX_PEND
            nsnap = npos
            for i in range(npos):
                snap[i] = order[i]
            for i in range(nsnap):
                k = snap[i]
                _close(k, ps[k, F_LASTC], code, t, ps, pi, rf, ri, acc, taker, slip)
                used[k] = False
                has[pi[k, P_SYM]] = -1
            npos = 0
            E = acc[0]
        day_eq[t] = E
        if last_of_month:
            m_end[m] = E
        E_prev = E
    return m_start, m_end, m_state, day_eq, rf[:nrec], ri[:nrec], cnt, acc


BR_CAP = np.asarray([b[0] for b in BRACKETS], np.float64)
BR_LEV = np.asarray([b[1] for b in BRACKETS], np.int64)
BR_MMR = np.asarray([b[2] for b in BRACKETS], np.float64)


class Out:
    __slots__ = ("m_start", "m_end", "m_state", "day_eq", "rf", "ri", "cnt", "acc", "start", "monthly", "p0", "p1")

    def __init__(self, raw, start, monthly, p0, p1):
        (self.m_start, self.m_end, self.m_state, self.day_eq, self.rf, self.ri, self.cnt, self.acc) = raw
        self.start, self.monthly, self.p0, self.p1 = start, monthly, p0, p1


def run_account(mk: Market, sig: Sig, v: dict, r: float = R_MAIN, cost: str = "base", fund8h: float | None = None,
                monthly: bool = False, start: float = START, sub: Sub | None = None,
                stop_hc: float | None = None) -> Out:
    """One account of variant ``v`` (its exit) on ``sig`` (sections 6-9, 14 when monthly). ``stop_hc``: the stop-fill
    haircut of 6.7 (default STOP_HC; 16 reports 0 and 0.5)."""
    taker, slip, f8 = COSTS[cost]
    if fund8h is not None:
        f8 = fund8h
    n_max, cap = caps(r)
    sub = sub or mk.daily_sub()
    prm = np.zeros(NPR)
    prm[PR_START], prm[PR_R], prm[PR_CAP], prm[PR_TAKER], prm[PR_SLIP] = start, r, cap, taker, slip
    prm[PR_FUNDDAY], prm[PR_BUST], prm[PR_CHAND], prm[PR_D0ATR], prm[PR_D0CAP] = 3.0 * f8, BUST_FRAC, CHAND, D0_ATR, D0_CAP
    prm[PR_LIQFRAC], prm[PR_MINNOT], prm[PR_LIQMULT] = LIQ_FRAC, MIN_NOTIONAL, LIQ_MULT
    prm[PR_STOPHC] = STOP_HC if stop_hc is None else stop_hc
    ip = np.zeros(NIP, np.int64)
    is_m = v["exit"] == "M"
    ip[IP_NMAX], ip[IP_LEVMAX], ip[IP_NADDS] = n_max, LEV_MAX, N_ADDS if is_m else 0
    ip[IP_HOLD], ip[IP_MONTHLY], ip[IP_FUNDMODE] = 0 if is_m else v["hold"], int(monthly), sub.fund_mode
    ip[IP_NB], ip[IP_P0], ip[IP_P1], ip[IP_TRAIL] = sub.nb, mk.p0, mk.p1, int(is_m)
    raw = _engine(prm, ip, BR_CAP, BR_LEV, BR_MMR, mk.bar, mk.o, mk.c, mk.atr, mk.med7, mk.delist, mk.pregap,
                  mk.month_of_day, mk.o.ravel(), mk.h.ravel(), mk.l.ravel(), sub.off, sub.slen, sub.o, sub.h, sub.l,
                  sub.mo, sub.mh, sub.ml, sub.fe_off, sub.fe_cnt, sub.fe_slot, sub.fe_rate, sub.fe_mark, sig.day,
                  sig.sym, sig.side)
    return Out(raw, start, monthly, mk.p0, mk.p1)


# ------------------------------------------------------------------ 9: metrics
def month_ln(out: Out) -> np.ndarray:
    """ln M per month of a continuous account; months after a bust (state 2) count 0 (the stopped account is flat).
    Used for the control comparisons of section 12-13."""
    with np.errstate(divide="ignore", invalid="ignore"):
        ln = np.log(np.maximum(out.m_end, 1e-300) / out.m_start)
    ln[out.m_state == 2] = 0.0
    return ln


def summarize(mk: Market, out: Out, detail: bool = True) -> dict:
    """Section 9 metrics. Means over realised months (a bust month as realised, later months excluded)."""
    real = out.m_state != 2
    M = out.m_end[real] / out.m_start[real]
    ln = np.log(np.maximum(M, 1e-300))
    n_m = int(real.sum())
    eq = out.day_eq[out.p0:out.p1]
    eq = eq[np.isfinite(eq)]
    peak = np.maximum.accumulate(eq) if len(eq) else eq
    dd = float(np.max(1.0 - eq / peak)) if len(eq) else 0.0
    rf, ri = out.rf, out.ri
    npos = len(rf)
    d = {
        "months": int(len(out.m_end)), "months_realised": n_m,
        "mean_ln": _f(ln.mean()) if n_m else None, "median_ln": _f(np.median(ln)) if n_m else None,
        "q25_ln": _f(np.quantile(ln, 0.25)) if n_m else None, "q75_ln": _f(np.quantile(ln, 0.75)) if n_m else None,
        "share_ge2": _f((M >= 2).mean()) if n_m else None, "share_ge5": _f((M >= 5).mean()) if n_m else None,
        "share_ge10": _f((M >= 10).mean()) if n_m else None, "share_lt09": _f((M < 0.9).mean()) if n_m else None,
        "worst_month": _f(M.min()) if n_m else None, "best_month": _f(M.max()) if n_m else None,
        "max_dd": _f(dd), "end_multiple": _f(eq[-1] / out.start) if len(eq) else None,
        "bust": bool((out.m_state == 1).any()), "positions": npos,
        "positions_per_month": _f(npos / max(1, len(out.m_end))),
    }
    if not detail:
        return d
    pnl_u = rf[:, R_PNL] / rf[:, R_U] if npos else np.zeros(0)
    pos_pnl = rf[:, R_PNL][rf[:, R_PNL] > 0].sum() if npos else 0.0
    srt = np.sort(rf[:, R_PNL])[::-1] if npos else np.zeros(0)
    top = srt[:max(1, int(math.ceil(0.10 * npos)))] if npos else srt
    reasons = {EXIT_NAMES[i]: int((ri[:, RI_REASON] == i).sum()) for i in range(len(EXIT_NAMES))} if npos else {}
    adds = ri[:, RI_ADDS] if npos else np.zeros(0, np.int64)
    side_rows = {}
    for sd, nm in ((1, "long"), (-1, "short")):
        sel = ri[:, RI_SIDE] == sd if npos else np.zeros(0, bool)
        n = int(sel.sum())
        side_rows[nm] = {"positions": n, "pnl_U_sum": _f(pnl_u[sel].sum()) if n else 0.0,
                         "pnl_U_mean": _f(pnl_u[sel].mean()) if n else None,
                         "win_share": _f((rf[sel, R_PNL] > 0).mean()) if n else None}
    years = {}
    if n_m:
        ym = np.asarray([m[:4] for m in mk.months])[real]
        for y in sorted(set(ym)):
            yy = ym == y
            years[y] = {"months": int(yy.sum()), "mean_ln": _f(ln[yy].mean())}
    price_sum = float(rf[:, R_PRICE].sum()) if npos else 0.0
    fund_sum = float(rf[:, R_FUND].sum()) if npos else 0.0
    d.update({
        "pnl_U_mean": _f(pnl_u.mean()) if npos else None, "pnl_U_median": _f(np.median(pnl_u)) if npos else None,
        "win_share": _f((rf[:, R_PNL] > 0).mean()) if npos else None,
        "top10pct_share_of_profit": _f(top.sum() / pos_pnl) if pos_pnl > 0 else None,
        "best_position_share_of_profit": _f(srt[0] / pos_pnl) if pos_pnl > 0 else None,
        "adds_per_position": _f(adds.mean()) if npos else None,
        "share_reaching_add": [_f((adds >= i).mean()) if npos else None for i in (1, 2, 3)],
        "exits": reasons,
        "stop_source": {SRC_NAMES[i]: int(((ri[:, RI_SRC] == i) & (ri[:, RI_REASON] <= EX_GAP)).sum())
                        for i in range(3)} if npos else {},
        "first_unit_risk_over_U": _f(rf[:, R_RISK1].mean()) if npos else None,
        "leverage_mean": _f(rf[:, R_LEV].mean()) if npos else None,
        "d0_over_p0_median": _f(np.median(rf[:, R_D0F])) if npos else None,
        "counters": {CNT_NAMES[i]: int(out.cnt[i]) for i in range(NCNT)},
        "fees_paid": _f(rf[:, R_FEES].sum()) if npos else 0.0, "funding_paid": _f(fund_sum),
        "price_pnl": _f(price_sum),
        "funding_share_of_gross": _f(fund_sum / abs(price_sum)) if price_sum != 0 else None,
        "per_year": years, "per_side": side_rows, "funding_flag": FUNDING_FLAG,
        "liquidation_note": LIQ_NOTE,
    })
    return d


def month_multiples(out: Out) -> tuple:
    """Monthly wallets (14): multiple of each month (end / start) and the bust flag."""
    return out.m_end / out.m_start, out.m_state == 1


# ------------------------------------------------------------------ 12-13: controls, bootstrap, BH
def ctrl_a(sig: Sig, rng: np.random.Generator) -> Sig:
    """12 (a): the pick's signals (taken or not), same symbols and days, each side by a fair coin."""
    return Sig(sig.day, sig.sym, np.where(rng.random(len(sig)) < 0.5, 1, -1).astype(np.int64))


def ctrl_b(mk: Market, sig: Sig, rng: np.random.Generator, pools: list) -> Sig:
    """12 (b): per symbol, the pick's signals that lie in the symbol's pool (Market.control_pools of the variant),
    moved together by one random circular offset over the pool: position i -> (i + k) mod n, k uniform on 0..n-1, one
    k per symbol (symbols in index order). Keeps each symbol's count, the spacing and clustering of its signals (in
    pool days) and their sides. A pick signal outside the pool (its next day has no bar: it lapsed) is not moved."""
    if not len(sig):
        return sig
    D, Sy, Sd = [], [], []
    for s in np.unique(sig.sym):
        s = int(s)
        pool = pools[s]
        n = len(pool)
        if n == 0:
            continue
        sel = sig.sym == s
        days, sides = sig.day[sel], sig.side[sel]
        pos = np.searchsorted(pool, days)
        inpool = (pos < n) & (pool[np.minimum(pos, n - 1)] == days)
        if not inpool.any():
            continue
        k = int(rng.integers(0, n))
        newpos = (pos[inpool] + k) % n
        D.append(pool[newpos].astype(np.int64))
        Sy.append(np.full(len(newpos), s, np.int64))
        Sd.append(sides[inpool].astype(np.int64))
    if not D:
        return Sig(np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0, np.int64))
    day, sym, side = np.concatenate(D), np.concatenate(Sy), np.concatenate(Sd)
    o = mk.order(day, sym)
    return Sig(day[o], sym[o], side[o])


def ctrl_seed(ctl: str, vid: str, period: str, r: float, n: int) -> np.random.Generator:
    return rng_of("altpump", ctl, vid, period, r, n)


def boot_p(d, rng: np.random.Generator, n_boot: int = N_BOOT) -> float:
    """13: one-sided p for mean d > 0 over the period's months = the larger of (i) a studentized month bootstrap
    (bootstrap-t: resample the months with replacement; t* = (mean* - mean) / se*; p = (1 + #{t* >= t}) /
    (n_boot + 1), t = mean / se) and (ii) a sign-flip test (each month's d times a random sign; p = (1 + #{mean* >=
    mean}) / (n_boot + 1)). The plain percentile bootstrap rejects too often with 19-26 months, most with left-skewed
    d; (i) corrects most of the skew, (ii) is exact for a symmetric null (tests: size under skewed nulls)."""
    d = np.asarray(d, float)
    n = len(d)
    if not n:
        return 1.0
    m = float(d.mean())
    sd = float(d.std(ddof=1)) if n > 1 else 0.0
    if not (sd > 0.0):
        return float(1.0 / (n_boot + 1)) if m > 0 else 1.0
    t_obs = m / (sd / math.sqrt(n))
    x = d[rng.integers(0, n, size=(n_boot, n))]
    num = x.mean(axis=1) - m
    se = x.std(axis=1, ddof=1) / math.sqrt(n)
    with np.errstate(divide="ignore", invalid="ignore"):
        ts = np.where(se > 0, num / se, np.where(num > 0, np.inf, np.where(num < 0, -np.inf, 0.0)))
    p_t = (1 + int((ts >= t_obs).sum())) / (n_boot + 1)
    sg = np.where(rng.random((n_boot, n)) < 0.5, -1.0, 1.0)
    p_f = (1 + int(((sg * d).mean(axis=1) >= m).sum())) / (n_boot + 1)
    return float(max(p_t, p_f))


def rank_p(pick_mean: float, seed_means) -> float:
    """13: (1 + seeds whose mean monthly ln M >= the pick's) / (n_seeds + 1)."""
    s = np.asarray(seed_means, float)
    return float((1 + int((s >= pick_mean).sum())) / (len(s) + 1))


def bh(pvals, q: float = BH_Q) -> list:
    """Benjamini-Hochberg: k* = the largest k with p_(k) <= q k / m; the k* smallest p are rejected."""
    p = np.asarray([1.0 if (x is None or not np.isfinite(x)) else x for x in pvals], float)
    m = len(p)
    if not m:
        return []
    order = np.argsort(p, kind="mergesort")
    kstar = 0
    for i, ix in enumerate(order, 1):
        if p[ix] <= q * i / m:
            kstar = i
    out = [False] * m
    for ix in order[:kstar]:
        out[int(ix)] = True
    return out


def run_controls(mk: Market, sig: Sig, v: dict, period: str, r: float = R_MAIN, n_seeds: int = N_SEEDS,
                 ctl: str = "a", sub: Sub | None = None) -> dict:
    """Section 12: n_seeds accounts of control ``ctl`` -> per-seed monthly ln M (post-bust months 0), the seeds'
    means, per-side P&L in U, and the symbols they traded."""
    pools = mk.control_pools(v) if ctl == "b" else None
    lnm = np.zeros((n_seeds, mk.n_months))
    side_u = np.zeros((n_seeds, 2))
    npos = np.zeros(n_seeds)
    busts = 0
    traded = set()
    for i in range(n_seeds):
        rng = ctrl_seed(ctl, v["id"], period, r, i)
        cs = ctrl_a(sig, rng) if ctl == "a" else ctrl_b(mk, sig, rng, pools)
        out = run_account(mk, cs, v, r=r, sub=sub)
        lnm[i] = month_ln(out)
        npos[i] = len(out.rf)
        busts += int((out.m_state == 1).any())
        if len(out.rf):
            u = out.rf[:, R_PNL] / out.rf[:, R_U]
            sd = out.ri[:, RI_SIDE]
            side_u[i, 0] = u[sd > 0].sum()
            side_u[i, 1] = u[sd < 0].sum()
            traded.update(np.unique(out.ri[:, RI_SYM]).tolist())
    return {"lnm": lnm, "means": lnm.mean(axis=1), "busts": busts, "side_u": side_u, "traded": traded,
            "positions": npos}


def compare(pick_ln: np.ndarray, ctl: dict, vid: str, period: str, ctl_name: str, r: float = R_MAIN,
            n_boot: int = N_BOOT) -> dict:
    """13 T2 for one period and control: d_m, p_boot, p_rank."""
    d = pick_ln - ctl["lnm"].mean(axis=0)
    pb = boot_p(d, rng_of("altpump", "boot", ctl_name, vid, period, r), n_boot)
    pr = rank_p(float(pick_ln.mean()), ctl["means"])
    return {"mean_d": _f(d.mean()), "p_boot": pb, "p_rank": pr, "control_mean_ln": _f(ctl["means"].mean()),
            "control_busts": int(ctl["busts"]),
            "control_positions_mean": _f(np.mean(ctl["positions"])) if "positions" in ctl else None,
            "control_side_U_mean": {"long": _f(ctl["side_u"][:, 0].mean()), "short": _f(ctl["side_u"][:, 1].mean())}}


def judge(rows: dict, test_periods=TEST_PERIODS, min_pos=None, q: float = BH_Q) -> dict:
    """13: T0-T3 for every pick; rows[vid][period] holds 'base' (summary) and 'cmp' {a, b}. Returns per pick the
    verdict and the BH decision over the K picks."""
    min_pos = min_pos or MIN_POS_TEST
    ids = list(rows)
    res = {}
    pvals = []
    for vid in ids:
        t0 = all(rows[vid][p]["base"]["positions"] >= min_pos[p] and not rows[vid][p]["base"]["bust"]
                 for p in test_periods)
        t1 = all((rows[vid][p]["base"]["mean_ln"] or -1.0) > 0 for p in test_periods)
        ps = [rows[vid][p]["cmp"][c][k] for p in test_periods for c in ("a", "b") for k in ("p_boot", "p_rank")]
        p_pick = max(ps) if (t0 and t1) else 1.0
        res[vid] = {"T0": t0, "T1": t1, "p_list": ps, "p_pick": p_pick}
        pvals.append(p_pick)
    rej = bh(pvals, q)
    for vid, rj in zip(ids, rej):
        res[vid]["T3_bh_rejected"] = bool(rj)
        res[vid]["PASS"] = bool(res[vid]["T0"] and res[vid]["T1"] and rj)
    return res


# ------------------------------------------------------------------ 11: selection
def eligible(base: dict, x2: dict, min_pos: int = MIN_POS_SELECT) -> bool:
    return bool(base["positions"] >= min_pos and (base["mean_ln"] or -1) > 0 and not base["bust"]
                and (x2["mean_ln"] or -1) > 0 and not x2["bust"])


def choose(table: dict, k_picks: int = K_PICKS, min_pos: int = MIN_POS_SELECT) -> dict:
    """11.2-11.3: eligible variants ranked by mean monthly ln M (ties: median, then section-5 order), at most one per
    (family, side) group, K = 5. None eligible: the highest mean, labelled 'no pick, fail'."""
    def key(vid):
        b = table[vid]["base"]
        return (-(b["mean_ln"] if b["mean_ln"] is not None else -np.inf),
                -(b["median_ln"] if b["median_ln"] is not None else -np.inf), VARIANT[vid]["order"])
    el = [vid for vid in table if eligible(table[vid]["base"], table[vid]["x2"], min_pos)]
    picks, groups = [], set()
    for vid in sorted(el, key=key):
        g = VARIANT[vid]["group"]
        if g in groups:
            continue
        picks.append(vid)
        groups.add(g)
        if len(picks) == k_picks:
            break
    if picks:
        return {"status": "picked", "picks": picks, "eligible": sorted(el, key=key)}
    best = sorted(table, key=key)[0]
    return {"status": "no_pick_fail", "picks": [best], "eligible": []}


# ------------------------------------------------------------------ 14: goal board
def board_stats(M: np.ndarray, bust: np.ndarray) -> dict:
    M = np.asarray(M, float).ravel()
    bust = np.asarray(bust, bool).ravel()
    n = len(M)
    d = {"months": n, "bust_share": _f(bust.mean()) if n else None,
         "median_multiple": _f(np.median(M)) if n else None, "worst_multiple": _f(M.min()) if n else None}
    for x in BOARD_X:
        d[f"share_ge_x{x}"] = _f((M >= x).mean()) if n else None
    return d


ADD_SKIP_IX = (A_RISK, A_MARGIN, A_FREE, A_LIQUIDITY, A_MINNOT, A_LIQBEYOND)
ENTRY_CUT_IX = (C_CUT_LIQ, C_CUT_MARGIN, C_CUT_FREE)


def adds_stats(outs: list) -> dict:
    """14: how the machine actually ran at this size, pooled over ``outs``: positions, first-unit risk / intended U,
    adds per position, the share of positions reaching each add level, add skips by reason, entry cuts by reason. At
    high r the margin budget B = E / n_max is often used up by the first unit, so few or no adds fill."""
    ri = [o.ri for o in outs if len(o.ri)]
    rf = [o.rf for o in outs if len(o.rf)]
    adds = np.concatenate([x[:, RI_ADDS] for x in ri]) if ri else np.zeros(0, np.int64)
    r1 = np.concatenate([x[:, R_RISK1] for x in rf]) if rf else np.zeros(0)
    cnt = np.sum([o.cnt for o in outs], axis=0) if outs else np.zeros(NCNT, np.int64)
    n = len(adds)
    return {"positions": int(n), "first_unit_risk_over_U": _f(r1.mean()) if n else None,
            "adds_per_position": _f(adds.mean()) if n else None,
            "share_reaching_add": [_f((adds >= i).mean()) if n else None for i in (1, 2, 3)],
            "add_skips": {CNT_NAMES[i]: int(cnt[i]) for i in ADD_SKIP_IX},
            "adds_filled": int(cnt[A_FILLED]),
            "entry_cuts": {CNT_NAMES[i]: int(cnt[i]) for i in ENTRY_CUT_IX}}


def board_block(mk: Market, sig: Sig, v: dict, period: str, r: float, n_seeds: int = N_SEEDS,
                sub: Sub | None = None) -> dict:
    out = run_account(mk, sig, v, r=r, monthly=True, sub=sub)
    M, b = month_multiples(out)
    row = {"pick": board_stats(M, b), "first_unit_risk_over_U": _f(out.rf[:, R_RISK1].mean()) if len(out.rf) else None,
           "pick_machine": adds_stats([out])}
    Ms, Bs, outs = [], [], []
    for i in range(n_seeds):
        cs = ctrl_a(sig, ctrl_seed("a", v["id"], period, r, i))
        o2 = run_account(mk, cs, v, r=r, monthly=True, sub=sub)
        m2, b2 = month_multiples(o2)
        Ms.append(m2)
        Bs.append(b2)
        outs.append(o2)
    row["coin_flip_pooled"] = board_stats(np.concatenate(Ms) if Ms else np.zeros(0),
                                          np.concatenate(Bs) if Bs else np.zeros(0, bool))
    row["coin_flip_machine"] = adds_stats(outs)
    row["caps"] = {"n_max": caps(r)[0], "risk_cap": caps(r)[1], "margin_budget_per_position": f"equity / {caps(r)[0]}"}
    return row


# ------------------------------------------------------------------ steps
def periods_of(args) -> dict:
    return dict(PERIODS)


def stamp(root: str, pin: dict | None, data_sha: str) -> dict:
    return {"commit": git_commit(root), "pin": pin, "data_sha256": data_sha, "funding": FUNDING_FLAG,
            "written_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")}


def step_select(raw: Raw, periods: dict = PERIODS, variants=None, k_picks: int = K_PICKS,
                min_pos: int = MIN_POS_SELECT) -> tuple:
    """11: every variant on period 1 at r = 2%, normal costs and cost x2 (and, reported only, the stop-fill haircut
    f = 0 and 0.5 of section 16). Returns (table, choice, universe size)."""
    variants = variants or VARIANTS
    mk = Market(raw, *periods["p1"], name="p1")
    table = {}
    for v in variants:
        sig = mk.signals(v)
        row = {"signals": len(sig)}
        for cost in ("base", "x2"):
            row[cost] = summarize(mk, run_account(mk, sig, v, r=R_MAIN, cost=cost), detail=(cost == "base"))
        row["stop_fill_sensitivity"] = {f"f={f:g}": summarize(mk, run_account(mk, sig, v, r=R_MAIN, stop_hc=f),
                                                              detail=False) for f in STOP_HC_SENS}   # 16, not a rule
        table[v["id"]] = row
    return table, choose(table, k_picks, min_pos), mk.universe_size()


def step_test(raw: Raw, picks: list, periods: dict = PERIODS, n_seeds: int = N_SEEDS, n_boot: int = N_BOOT,
              min_pos=None, log=print) -> dict:
    """13 and 16 on the test periods for the picks only."""
    rows, extra, traded, usize = {}, {}, {}, {}
    for p in TEST_PERIODS:
        mk = Market(raw, *periods[p], name=p)
        usize[p] = mk.universe_size()
        traded[p] = {}
        mk_all = Market(raw, *periods[p], excluded=INDEX_STABLE, name=p + "_with_tradfi") if p == "p2" else None
        for vid in picks:
            v = VARIANT[vid]
            sig = mk.signals(v)
            t0 = time.time()
            base_out = run_account(mk, sig, v)
            base = summarize(mk, base_out)
            pick_ln = month_ln(base_out)
            ex = {"signals": len(sig),
                  "cost_x2": summarize(mk, run_account(mk, sig, v, cost="x2"), detail=False),
                  "r_0.5pct": summarize(mk, run_account(mk, sig, v, r=R_LOW), detail=False),
                  "funding_sensitivity": {f"{f * 100:.2f}%/8h": summarize(mk, run_account(mk, sig, v, fund8h=f),
                                                                            detail=False) for f in FUND_SENS},
                  "stop_fill_sensitivity": {f"f={f:g}": summarize(mk, run_account(mk, sig, v, stop_hc=f),
                                                                  detail=False) for f in STOP_HC_SENS}}
            if mk_all is not None:
                ex["without_tradfi_exclusion"] = summarize(mk_all, run_account(mk_all, mk_all.signals(v), v),
                                                           detail=False)
            cmp_, syms = {}, set(np.unique(base_out.ri[:, RI_SYM]).tolist()) if len(base_out.ri) else set()
            for c in ("a", "b"):
                ctl = run_controls(mk, sig, v, p, R_MAIN, n_seeds, c)
                cmp_[c] = compare(pick_ln, ctl, vid, p, c, R_MAIN, n_boot)
                syms |= ctl["traded"]
            rows.setdefault(vid, {})[p] = {"base": base, "cmp": cmp_}
            extra.setdefault(vid, {})[p] = ex
            traded[p][vid] = sorted(mk.syms[list(syms)].tolist())
            log(f"  test {p} {vid}: {time.time() - t0:.1f}s")
    verdict = judge(rows, TEST_PERIODS, min_pos)
    return {"rows": rows, "extra": extra, "verdict": verdict, "traded_symbols": traded, "universe_size": usize}


def step_board(raw: Raw, picks: list, periods: dict = PERIODS, n_seeds: int = N_SEEDS, rs=BOARD_RS, log=print) -> dict:
    out = {}
    for p in ("p1", "p2", "p3"):
        mk = Market(raw, *periods[p], name=p)
        for vid in picks:
            v = VARIANT[vid]
            sig = mk.signals(v)
            for r in rs:
                t0 = time.time()
                row = board_block(mk, sig, v, p, r, n_seeds)
                row["label"] = "chosen here" if p == "p1" else "test"
                out.setdefault(vid, {}).setdefault(p, {})[f"r={r:g}"] = row
                log(f"  board {p} {vid} r={r:g}: {time.time() - t0:.1f}s")
    return out


# ------------------------------------------------------------------ 15: second pass on 5m bars
P2_BASE = "https://data.binance.vision/data/futures/um/monthly/"
P2_PATHS = {"klines": "klines/{sym}/5m/{sym}-5m-{ym}.zip",
            "mark": "markPriceKlines/{sym}/5m/{sym}-5m-{ym}.zip",
            "funding": "fundingRate/{sym}/{sym}-fundingRate-{ym}.zip"}
NB5 = 288
FIVE_MS = 300_000


def _months_between(start: str, end: str, before: int = 1) -> list:
    a = np.datetime64(start, "M") - before
    b = np.datetime64(end, "D") - 1
    out, m = [], a
    while m <= b.astype("datetime64[M]"):
        out.append(str(m))
        m += 1
    return out


def pass2_plan(test: dict, periods: dict = PERIODS) -> dict:
    """15: the symbols that a passing pick or its controls traded in each test period; each month of the test period
    plus one month before it; three kinds of monthly files."""
    passing = [vid for vid, r in test["verdict"].items() if r["PASS"]]
    files, syms = [], {}
    for p in TEST_PERIODS:
        ss = sorted({s for vid in passing for s in test["traded_symbols"][p].get(vid, [])})
        syms[p] = ss
        for s in ss:
            for ym in _months_between(*periods[p]):
                for kind in P2_PATHS:
                    files.append({"kind": kind, "sym": s, "ym": ym, "url": P2_BASE + P2_PATHS[kind].format(sym=s, ym=ym)})
    return {"passing": passing, "symbols": syms, "files": files}


def _read_zip_csv(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = [n for n in z.namelist() if n.endswith(".csv")][0]
        raw = z.read(name)
    first = raw.split(b"\n", 1)[0]
    header = 0 if any(ch.isalpha() for ch in first.decode(errors="ignore").replace("e-", "").replace("E-", "")) else None
    return pd.read_csv(io.BytesIO(raw), header=header)


def convert_kline_zip(blob: bytes) -> dict:
    """5m klines or mark-price klines -> open_time (ms), open, high, low, close (float32)."""
    df = _read_zip_csv(blob)
    a = df.iloc[:, :5].to_numpy()
    return {"t": a[:, 0].astype(np.int64), "o": a[:, 1].astype(np.float32), "h": a[:, 2].astype(np.float32),
            "l": a[:, 3].astype(np.float32), "c": a[:, 4].astype(np.float32)}


def convert_funding_zip(blob: bytes) -> dict:
    """fundingRate monthly file -> calc_time (ms), rate."""
    df = _read_zip_csv(blob)
    cols = [str(c).lower() for c in df.columns]
    tcol = next((i for i, c in enumerate(cols) if "time" in c), 0)
    rcol = next((i for i, c in enumerate(cols) if "rate" in c), df.shape[1] - 1)
    return {"t": df.iloc[:, tcol].to_numpy().astype(np.int64), "rate": df.iloc[:, rcol].to_numpy().astype(np.float64)}


def _free_gb(path: str) -> float:
    return shutil.disk_usage(path).free / 1e9


def pass2_fetch(plan: dict, cache: str, min_free_gb: float = 1.0, workers: int = 2, log=print) -> dict:
    """15: download each monthly file with its .CHECKSUM, convert it to a compact .npz, delete the zip. Stops when the
    free disk would fall under ``min_free_gb`` (run it on the rented server then). At most ``workers`` at a time."""
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(cache, exist_ok=True)
    missing = []

    def one(f):
        dst = os.path.join(cache, f"{f['kind']}_{f['sym']}_{f['ym']}.npz")
        if os.path.exists(dst):
            return None
        if _free_gb(cache) < min_free_gb:
            raise RuntimeError(f"free disk under {min_free_gb} GB: run pass2 fetch on the rented server (section 15)")
        try:
            blob = urllib.request.urlopen(f["url"], timeout=120).read()
            want = urllib.request.urlopen(f["url"] + ".CHECKSUM", timeout=60).read().decode().split()[0]
        except Exception as exc:  # noqa: BLE001
            return f"{f['kind']} {f['sym']} {f['ym']}: {exc}"
        if hashlib.sha256(blob).hexdigest() != want:
            return f"{f['kind']} {f['sym']} {f['ym']}: checksum mismatch"
        arr = convert_funding_zip(blob) if f["kind"] == "funding" else convert_kline_zip(blob)
        np.savez_compressed(dst, **arr)
        del blob
        return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(one, plan["files"]):
            if res:
                missing.append(res)
                log("  missing: " + res)
    return {"missing": missing}


def _month_days(mk: Market) -> dict:
    """Window day indexes per UTC calendar month ('YYYY-MM' -> array of t)."""
    ym = (np.arange(mk.T) + mk.w0g).astype("datetime64[D]").astype("datetime64[M]").astype(str)
    return {m: np.flatnonzero(ym == m) for m in sorted(set(ym.tolist()))}


def load_sub5m(mk: Market, cache: str, syms: list, tol: float = 1e-6) -> tuple:
    """15: the 5m price and mark bars of ``syms`` as slot blocks of 288 and their archived funding events. A
    symbol-day of the period with a daily bar but no 5m block, or whose 5m bars do not reach the daily high and low (a
    hole in the 5m file), gets no block: the engine runs it on the daily bar (6.7 worst order), so no move the daily
    file shows is skipped and no position is closed early because data will be missing. Mark missing -> the price bars
    stand in. A symbol-day without an archived funding event pays the fixed charge (8). Returns (Sub, report): the
    symbol-months with a daily bar in the period and no klines / mark / funding file, and day counts."""
    ix = {s: i for i, s in enumerate(mk.syms)}
    S, T = mk.S, mk.T
    day0_ms = mk.w0g * DAY_MS
    blocks = {}
    fe_rows = {}
    rep = {"klines": [], "mark": [], "funding": []}
    mdays = _month_days(mk)
    for s in syms:
        if s not in ix:
            continue
        si = ix[s]
        for ym, tdays in mdays.items():
            need = bool(mk.bar[si, tdays[tdays >= mk.p0]].any())
            pk = os.path.join(cache, f"klines_{s}_{ym}.npz")
            pm = os.path.join(cache, f"mark_{s}_{ym}.npz")
            pf = os.path.join(cache, f"funding_{s}_{ym}.npz")
            for kind, path in (("klines", pk), ("mark", pm), ("funding", pf)):
                if need and not os.path.exists(path):
                    rep[kind].append(f"{s} {ym}")
            if os.path.exists(pk):
                k = dict(np.load(pk))
                mkd = dict(np.load(pm)) if os.path.exists(pm) else None
                tt = (k["t"] - day0_ms) // DAY_MS
                jj = ((k["t"] - day0_ms) % DAY_MS) // FIVE_MS
                for t in np.unique(tt):
                    if t < mk.p0 or t >= T or not mk.bar[si, t]:
                        continue
                    blk = blocks.setdefault((si, int(t)), np.full((6, NB5), np.nan, np.float32))
                    sel = tt == t
                    blk[0, jj[sel]], blk[1, jj[sel]], blk[2, jj[sel]] = k["o"][sel], k["h"][sel], k["l"][sel]
                    if mkd is not None:
                        mt = (mkd["t"] - day0_ms) // DAY_MS
                        ms = mt == t
                        mj = ((mkd["t"][ms] - day0_ms) % DAY_MS) // FIVE_MS
                        blk[3, mj], blk[4, mj], blk[5, mj] = mkd["o"][ms], mkd["h"][ms], mkd["l"][ms]
            if os.path.exists(pf):
                f = dict(np.load(pf))
                for tms, rate in zip(f["t"], f["rate"]):
                    t = int((tms - day0_ms) // DAY_MS)
                    if mk.p0 <= t < T:
                        fe_rows.setdefault((si, t), []).append((int(((tms - day0_ms) % DAY_MS) // FIVE_MS), rate))
    use = {}
    short = 0
    for key, blk in blocks.items():
        si, t = key
        with np.errstate(all="ignore"):
            hi, lo = np.nanmax(blk[1]), np.nanmin(blk[2])
        if np.isfinite(hi) and hi >= mk.h[si, t] * (1.0 - tol) and lo <= mk.l[si, t] * (1.0 + tol):
            use[key] = blk
        else:
            short += 1
    nblk = len(use)
    arr = np.full((6, max(1, nblk) * NB5), np.nan)
    off = np.full((S, T), -1, np.int64)
    slen = np.zeros((S, T), np.int64)
    for n, ((si, t), blk) in enumerate(sorted(use.items())):
        for f in range(3):                                     # mark missing -> the price bars stand in
            bad = np.isnan(blk[3 + f])
            blk[3 + f, bad] = blk[f, bad]
        arr[:, n * NB5:(n + 1) * NB5] = blk
        off[si, t] = n * NB5
        slen[si, t] = NB5
    planned = np.zeros(S, np.bool_)
    planned[[ix[x] for x in syms if x in ix]] = True
    daybar = mk.bar & (off < 0) & planned[:, None]
    daybar[:, :mk.p0] = False
    fe_off = np.full((S, T), -1, np.int64)
    fe_cnt = np.zeros((S, T), np.int64)
    fs, fr, fm = [], [], []
    for (si, t), evs in sorted(fe_rows.items()):
        if not mk.bar[si, t]:
            continue
        fe_off[si, t] = len(fs)
        fe_cnt[si, t] = len(evs)
        for j, rate in sorted(evs):
            x = off[si, t] + j
            mark = arr[3, x] if (off[si, t] >= 0 and np.isfinite(arr[3, x])) else mk.o[si, t]
            fs.append(j)
            fr.append(rate)
            fm.append(float(mark))
    rep["days_on_5m"] = int(nblk)
    rep["days_on_daily_bar"] = int(daybar.sum())
    rep["days_5m_short_of_daily_range"] = int(short)
    sub = Sub(off, slen, arr[0], arr[1], arr[2], arr[3], arr[4], arr[5], NB5, fe_off, fe_cnt,
              np.asarray(fs, np.int64), np.asarray(fr, np.float64), np.asarray(fm, np.float64), 1)
    return sub, rep


def pass2_inventory(raw: Raw, plan: dict, cache: str, periods: dict = PERIODS) -> dict:
    """15: from the traded-day calendar only, the symbol-months of each test period in which a planned symbol has a
    daily bar and the cache has no klines / mark / funding file."""
    inv = {"klines": [], "mark": [], "funding": []}
    for p in TEST_PERIODS:
        g0, g1 = max(gday(periods[p][0]), raw.first_day), min(gday(periods[p][1]), raw.last_day + 1)
        if g1 <= g0:
            continue
        for s in plan["symbols"].get(p, []):
            if s not in raw.sym_ix:
                continue
            days = np.flatnonzero(raw.cal[raw.sym_ix[s], g0 - raw.first_day:g1 - raw.first_day]) + g0
            for ym in sorted(set(days.astype("datetime64[D]").astype("datetime64[M]").astype(str).tolist())):
                for kind in inv:
                    if not os.path.exists(os.path.join(cache, f"{kind}_{s}_{ym}.npz")):
                        inv[kind].append(f"{p} {s} {ym}")
    return inv


def cache_digest(cache: str) -> dict:
    """15: sha256 over the sorted cache file list (name, size, sha256 of each file), written into pass2.json."""
    h = hashlib.sha256()
    n = 0
    if os.path.isdir(cache):
        for name in sorted(os.listdir(cache)):
            path = os.path.join(cache, name)
            if not os.path.isfile(path):
                continue
            h.update(f"{name} {os.path.getsize(path)} {sha256_file(path)}\n".encode())
            n += 1
    return {"files": n, "sha256": h.hexdigest()}


def step_pass2(raw: Raw, test: dict, cache: str, periods: dict = PERIODS, n_seeds: int = N_SEEDS,
               n_boot: int = N_BOOT, log=print) -> dict:
    """15: T0-T3 recomputed on 5m fills for the passing picks (controls on 5m too; BH over the same K picks with the
    first-pass failures at p = 1); the goal board redone on 5m."""
    plan = pass2_plan(test, periods)
    passing = plan["passing"]
    rows, board, report = {}, {}, {}
    for p in TEST_PERIODS:
        mk = Market(raw, *periods[p], name=p)
        sub, rep = load_sub5m(mk, cache, plan["symbols"][p])
        report[p] = rep
        for vid in passing:
            v = VARIANT[vid]
            sig = mk.signals(v)
            out = run_account(mk, sig, v, sub=sub)
            base = summarize(mk, out)
            cmp_ = {c: compare(month_ln(out), run_controls(mk, sig, v, p, R_MAIN, n_seeds, c, sub=sub), vid, p, c,
                               R_MAIN, n_boot) for c in ("a", "b")}
            rows.setdefault(vid, {})[p] = {"base": base, "cmp": cmp_}
            for r in BOARD_RS:
                board.setdefault(vid, {}).setdefault(p, {})[f"r={r:g}"] = board_block(mk, sig, v, p, r, n_seeds, sub)
            log(f"  pass2 {p} {vid} done")
    all_ids = list(test["verdict"])
    full = {}
    for vid in all_ids:
        if vid in rows:
            full[vid] = rows[vid]
    verdict = judge(full, TEST_PERIODS) if full else {}
    # BH over the same K picks: the first-pass failures enter at p = 1
    pv = [verdict[vid]["p_pick"] if vid in verdict else 1.0 for vid in all_ids]
    rej = bh(pv)
    final = {}
    for vid, rj in zip(all_ids, rej):
        if vid in verdict:
            ok = verdict[vid]["T0"] and verdict[vid]["T1"] and rj
            final[vid] = {**verdict[vid], "T3_bh_rejected": bool(rj), "PASS_5m": bool(ok),
                          "label": "pass (5m)" if ok else "failed (5m)"}
        else:
            final[vid] = {"label": "fail (first pass)", "PASS_5m": False}
    return {"plan": {"passing": passing, "symbols": plan["symbols"], "files": len(plan["files"])}, "rows": rows,
            "verdict": final, "board_5m": board, "data_report": report}


# ------------------------------------------------------------------ check (structure only)
def step_check(raw: Raw) -> dict:
    """Structure only (no price or volume value): symbol counts, the exclusion list against the symbol list, lives,
    relistings, rename successors, first bars per period."""
    syms = set(raw.syms)
    not_found = sorted(EXCLUDED - syms)
    relist = sorted({raw.syms[s] for s in raw.life_sym[raw.life_gap_before >= RELIST_GAP]})
    paused = sorted(f"{raw.syms[raw.life_sym[i]]} {day_str(raw.first_day + raw.life_first[i])} after "
                    f"{raw.life_gap_before[i]} days"
                    for i in np.flatnonzero((raw.life_gap_before >= PAUSE_GAP) & (raw.life_gap_before < RELIST_GAP)))
    gaps = int(raw.pregap.sum())
    per = {}
    for p, (a, b) in PERIODS.items():
        lo, hi = gday(a) - raw.first_day, gday(b) - raw.first_day
        first = (raw.life_no == 0) & (raw.life_first >= lo) & (raw.life_first < hi)
        fs = [raw.syms[s] for s in raw.life_sym[first]]
        per[p] = {"first_bars_all": len(fs), "first_bars_kept": len([s for s in fs if s not in EXCLUDED]),
                  "listing_lives_kept": int(sum(1 for i in np.flatnonzero(raw.life_listing & (raw.life_first >= lo)
                                                                         & (raw.life_first < hi))
                                                if raw.syms[raw.life_sym[i]] not in EXCLUDED))}
    return {"symbols": len(syms), "excluded_listed": len(EXCLUDED), "excluded_not_in_file": not_found,
            "kept": len(syms - EXCLUDED), "lives": int(len(raw.life_first)), "relisted_symbols": relist,
            "pause_restarts_not_listings": paused, "bars_before_a_day_without_bar_in_a_life": gaps,
            "partial_days": [day_str(raw.first_day + t) for t in np.flatnonzero(raw.partial)],
            "delisted_lives": int(raw.life_delist.sum()),
            "rename_successors": {k: {"old": o, "days_after_old_last_bar": d} for k, (o, d) in raw.successor.items()},
            "renames_not_matched": [f"{o}->{n}" for o, n in RENAMES if n + "USDT" not in raw.successor],
            "per_period": per, "first_day": day_str(raw.first_day), "last_day": day_str(raw.last_day)}


# ------------------------------------------------------------------ synthetic data (tests and bench only)
def synthetic_frame(n_syms: int = 864, start: str = "2020-01-01", end: str = "2026-08-31", seed: int = 7,
                    pump_rate: float = 0.01) -> pd.DataFrame:
    """A made-up daily file with the real file's columns: listings through the whole range, delistings with zero-volume
    padding, a few relistings after a 40-day gap, pumps with volume spikes. NOT market data."""
    rng = np.random.default_rng(seed)
    d0, d1 = gday(start), gday(end)
    T = d1 - d0 + 1
    S = n_syms
    lst = np.where(rng.random(S) < 0.15, 0, rng.integers(0, max(1, T - 60), S))
    dl = np.where(rng.random(S) < 0.25, lst + 60 + rng.integers(0, T, S), T + 1)
    sig = rng.uniform(0.02, 0.07, S)
    ret = rng.standard_normal((S, T)) * sig[:, None]
    pump = rng.random((S, T)) < pump_rate
    ret += pump * rng.uniform(0.2, 0.9, (S, T))
    logc = np.log(rng.uniform(0.05, 50.0, S))[:, None] + np.cumsum(ret, axis=1)
    c = np.exp(logc)
    pc = np.concatenate([c[:, :1] * np.exp(-ret[:, :1]), c[:, :-1]], axis=1)
    o = pc * np.exp(rng.standard_normal((S, T)) * 0.002)
    up = np.abs(rng.standard_normal((S, T))) * sig[:, None] * 0.6
    dn = np.abs(rng.standard_normal((S, T))) * sig[:, None] * 0.6
    h = np.maximum(o, c) * np.exp(up)
    l = np.minimum(o, c) * np.exp(-dn)
    qv = np.exp(np.log(10 ** rng.uniform(6.0, 8.3, S))[:, None] + rng.standard_normal((S, T)) * 0.5)
    qv *= np.where(pump, rng.uniform(3, 8, (S, T)), 1.0)
    tt = np.arange(T)[None, :]
    live = (tt >= lst[:, None]) & (tt <= dl[:, None])
    relist = rng.random(S) < 0.01
    gap_a = lst + 100
    gap = relist[:, None] & (tt >= gap_a[:, None]) & (tt < gap_a[:, None] + 40)
    row = tt >= lst[:, None]                     # rows exist from the listing on (padding after delisting)
    vol = np.where(live & ~gap, qv / c, 0.0)
    qv = np.where(live & ~gap, qv, 0.0)
    pad = ~(live & ~gap)
    o, h, l = np.where(pad, c, o), np.where(pad, c, h), np.where(pad, c, l)
    s_ix, t_ix = np.nonzero(row)
    names = np.asarray([f"S{i:03d}USDT" for i in range(S)])
    return pd.DataFrame({"symbol": names[s_ix], "open_time": (d0 + t_ix).astype(np.int64) * DAY_MS,
                         "open": o[s_ix, t_ix], "high": h[s_ix, t_ix], "low": l[s_ix, t_ix],
                         "close": c[s_ix, t_ix], "volume": vol[s_ix, t_ix], "quote_volume": qv[s_ix, t_ix],
                         "count": 0, "taker_buy_quote_volume": 0.0})


def bench(n_syms: int, out_path: str, n_seeds: int = N_SEEDS, n_boot: int = N_BOOT, k_picks: int = K_PICKS,
          log=print) -> dict:
    """Timing on synthetic data shaped like the real file: one select run, then a full test (K picks x 2 periods x
    (pick + 2 x n_seeds controls)) and the goal board. The picks are the first K groups' best variants by mean
    (eligibility ignored, so K is reached). No real data, nothing written but ``out_path``."""
    tm = {}
    t0 = time.time()
    df = synthetic_frame(n_syms)
    tm["synthetic_rows"] = int(len(df))
    tm["make_synthetic_s"] = round(time.time() - t0, 2)
    t0 = time.time()
    raw = Raw(df)
    tm["raw_build_s"] = round(time.time() - t0, 2)
    t0 = time.time()
    mk = Market(raw, *PERIODS["p3"], name="p3")
    v = VARIANTS[0]
    run_account(mk, mk.signals(v), v)
    tm["numba_compile_and_warm_s"] = round(time.time() - t0, 2)
    t0 = time.time()
    table, _, _ = step_select(raw)
    tm["select_s"] = round(time.time() - t0, 2)
    tm["select_accounts"] = 2 * len(VARIANTS)
    tm["select_signals_total"] = int(sum(r["signals"] for r in table.values()))
    order = sorted(table, key=lambda vid: -(table[vid]["base"]["mean_ln"] or -9))
    picks, groups = [], set()
    for vid in order:
        if VARIANT[vid]["group"] not in groups:
            picks.append(vid)
            groups.add(VARIANT[vid]["group"])
        if len(picks) == k_picks:
            break
    tm["bench_picks"] = picks
    t0 = time.time()
    step_test(raw, picks, n_seeds=n_seeds, n_boot=n_boot, log=log)
    tm["test_with_controls_s"] = round(time.time() - t0, 2)
    tm["test_accounts"] = len(picks) * 2 * (1 + 4 + 2 * n_seeds) + len(picks)
    t0 = time.time()
    step_board(raw, picks, n_seeds=n_seeds, log=log)
    tm["board_s"] = round(time.time() - t0, 2)
    tm["board_accounts"] = len(picks) * 3 * len(BOARD_RS) * (1 + n_seeds)
    tm["select_plus_test_s"] = round(tm["select_s"] + tm["test_with_controls_s"], 2)
    tm["all_steps_s"] = round(tm["select_s"] + tm["test_with_controls_s"] + tm["board_s"], 2)
    tm["n_syms"], tm["n_seeds"], tm["n_boot"] = n_syms, n_seeds, n_boot
    tm["days"] = int(raw.n_days)
    tm["note"] = "synthetic random-walk data with pumps; no real data read; single process"
    _write_json(out_path, tm)
    return tm


# ------------------------------------------------------------------ report
def step_report(out_dir: str) -> str:
    lines = [f"altpump report ({FUNDING_FLAG})"]
    p = os.path.join(out_dir, "select.json")
    if os.path.exists(p):
        s = json.load(open(p))
        lines.append(f"select (period 1, r = 2%): status {s['choice']['status']}, picks {s['choice']['picks']}")
        lines.append(f"{'variant':<16}{'signals':>8}{'pos':>6}{'mean lnM':>10}{'x2 mean':>10}{'bust':>6}")
        for vid, r in s["table"].items():
            b, x = r["base"], r["x2"]
            lines.append(f"{vid:<16}{r['signals']:>8}{b['positions']:>6}{(b['mean_ln'] or 0):>10.4f}"
                         f"{(x['mean_ln'] or 0):>10.4f}{str(b['bust']):>6}")
    p = os.path.join(out_dir, "test.json")
    if os.path.exists(p):
        t = json.load(open(p))
        lines.append("test (periods 2 and 3):")
        for vid, r in t["verdict"].items():
            lines.append(f"  {vid}: T0 {r['T0']} T1 {r['T1']} p_pick {r['p_pick']:.4f} BH {r['T3_bh_rejected']} "
                         f"PASS {r['PASS']}")
    p = os.path.join(out_dir, "board.json")
    if os.path.exists(p):
        b = json.load(open(p))
        lines.append("goal board (fresh $1,000 months; reported, never a pass rule):")
        for vid, per in b["board"].items():
            for pp, rows in per.items():
                for rk, row in rows.items():
                    pk, cf = row["pick"], row["coin_flip_pooled"]
                    lines.append(f"  {vid} {pp} {rk}: >=x5 {pk['share_ge_x5']} >=x50 {pk['share_ge_x50']} bust "
                                 f"{pk['bust_share']} worst {pk['worst_multiple']} | coin flip >=x5 "
                                 f"{cf['share_ge_x5']} >=x50 {cf['share_ge_x50']}")
        lines.append(GOAL50_BASELINE)
    text = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "report.txt"), "w") as fh:
        fh.write(text)
    return text


# ------------------------------------------------------------------ CLI
def _load_real(root: str, structure_only: bool = False, step: str | None = None) -> tuple:
    """The daily file, checked against MANIFEST.json; values only inside the step's windows (section 10)."""
    return load_raw(os.path.join(root, DATA_REL), os.path.join(root, MANIFEST_REL), structure_only,
                    None if (structure_only or step is None) else step_windows(step))


def _refuse_rerun(root: str, name: str, what: str) -> None:
    path = os.path.join(root, OUT_REL, name)
    if os.path.exists(path):
        raise PinError(f"out/{name} exists: {what} is run once. A rerun after a bug fix needs its DEVIATIONS.md "
                       "entry; move the old file aside first.")


def cmd_select(args) -> int:
    root = args.root
    pin = check_pin("select", root)
    out_dir = os.path.join(root, OUT_REL)
    if os.path.exists(os.path.join(root, PICK_REL)):
        raise PinError(f"{PICK_REL} exists: select ran already")
    raw, sha = _load_real(root, step="select")
    t0 = time.time()
    table, choice, usize = step_select(raw)
    st = stamp(root, pin, sha)
    _write_json(os.path.join(out_dir, "select.json"), {"stamp": st, "period": PERIODS["p1"], "r": R_MAIN,
                                                       "value_windows": raw.value_windows,
                                                       "universe_size": usize, "table": table, "choice": choice,
                                                       "seconds": round(time.time() - t0, 1)})
    groups = {vid: VARIANT[vid]["group"] for vid in choice["picks"]}
    _write_json(os.path.join(root, PICK_REL), {"status": choice["status"], "picks": choice["picks"], "groups": groups,
                                               "K": len(choice["picks"]), "stamp": st})
    h = append_pick_line(root)
    print(f"select: {choice['status']} {choice['picks']}; pick.json pinned ({h[:12]})")
    return 0


def cmd_test(args) -> int:
    root = args.root
    pin = check_pin("test", root)
    path = os.path.join(root, OUT_REL, "test.json")
    _refuse_rerun(root, "test.json", "each test period (11.4)")
    pick = json.load(open(os.path.join(root, PICK_REL)))
    raw, sha = _load_real(root, step="test")
    res = step_test(raw, pick["picks"])
    res["status_select"] = pick["status"]
    res["value_windows"] = raw.value_windows
    if pick["status"] != "picked":
        for vid in res["verdict"]:
            res["verdict"][vid]["PASS"] = False
            res["verdict"][vid]["label"] = "no pick, fail"
    _write_json(path, {"stamp": stamp(root, pin, sha), **res})
    for vid, r in res["verdict"].items():
        print(f"test {vid}: PASS {r['PASS']}")
    return 0


def cmd_board(args) -> int:
    root = args.root
    pin = check_pin("board", root)
    _refuse_rerun(root, "board.json", "the goal board (14)")
    pick = json.load(open(os.path.join(root, PICK_REL)))
    raw, sha = _load_real(root, step="board")
    res = step_board(raw, pick["picks"])
    _write_json(os.path.join(root, OUT_REL, "board.json"), {"stamp": stamp(root, pin, sha), "board": res,
                                                            "baseline": GOAL50_BASELINE,
                                                            "note": "reported, never a pass rule (14)"})
    print("board written")
    return 0


def cmd_pass2(args) -> int:
    root = args.root
    pin = check_pin("pass2", root)
    test = json.load(open(os.path.join(root, OUT_REL, "test.json")))
    cache = args.cache or os.path.join(root, OUT_REL, "pass2_cache")
    plan = pass2_plan(test)
    if args.what == "plan":
        _write_json(os.path.join(root, OUT_REL, "pass2_plan.json"), plan)
        print(f"pass2 plan: {len(plan['passing'])} passing picks, {len(plan['files'])} files")
        return 0
    if not plan["passing"]:
        print("pass2: no pick passed the first pass; nothing to do (section 15)")
        return 0
    _refuse_rerun(root, "pass2.json", "the second pass (15); its cache does not change after the run")
    if args.what == "fetch":
        res = pass2_fetch(plan, cache)
        _write_json(os.path.join(root, OUT_REL, "pass2_fetch.json"), res)
        return 0
    raw, sha = _load_real(root, step="pass2")
    inv = pass2_inventory(raw, plan, cache)
    if inv["klines"]:
        dev = os.path.join(root, "research", "altpump", "DEVIATIONS.md")
        if not (args.accept_missing and os.path.exists(dev)):
            raise PinError(f"pass2: {len(inv['klines'])} symbol-months with daily bars have no 5m klines in the cache "
                           f"(first: {inv['klines'][:5]}). Fetch again; or list them in research/altpump/DEVIATIONS.md "
                           "and rerun with --accept-missing (those days then run on the daily bar, 6.7 and 15).")
    digest = cache_digest(cache)
    res = step_pass2(raw, test, cache)
    _write_json(os.path.join(root, OUT_REL, "pass2.json"), {"stamp": stamp(root, pin, sha), "cache": digest,
                                                           "inventory_missing": inv, **res})
    return 0


def cmd_check(args) -> int:
    raw, sha = _load_real(args.root, structure_only=True)
    print(json.dumps({"data_sha256": sha, **step_check(raw)}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=ROOT)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for c in ("check", "select", "test", "board", "report", "pin"):
        sp.add_parser(c)
    p2 = sp.add_parser("pass2")
    p2.add_argument("what", choices=("plan", "fetch", "run"))
    p2.add_argument("--cache", default="")
    p2.add_argument("--accept-missing", action="store_true",
                    help="run although some needed 5m klines months are missing (needs research/altpump/DEVIATIONS.md)")
    b = sp.add_parser("bench")
    b.add_argument("--out", required=True)
    b.add_argument("--syms", type=int, default=864)
    b.add_argument("--seeds", type=int, default=N_SEEDS)
    b.add_argument("--boot", type=int, default=N_BOOT)
    args = ap.parse_args(argv)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "select":
        return cmd_select(args)
    if args.cmd == "test":
        return cmd_test(args)
    if args.cmd == "board":
        return cmd_board(args)
    if args.cmd == "pass2":
        return cmd_pass2(args)
    if args.cmd == "report":
        print(step_report(os.path.join(args.root, OUT_REL)))
        return 0
    if args.cmd == "pin":
        print(write_pin(args.root))
        return 0
    if args.cmd == "bench":
        print(json.dumps(bench(args.syms, args.out, args.seeds, args.boot), indent=1))
        return 0
    return 2


if __name__ == "__main__":
    # Run through the package module so that the numba cache (cache=True) is written and read under one module name:
    # a cache written by the tests (research.altpump.altpump) could not be loaded by a __main__ run from another
    # directory, and vice versa.
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from research.altpump import altpump as _pkg
    sys.exit(_pkg.main())
