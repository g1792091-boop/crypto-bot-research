"""Trend hunt (추세 사냥): the one-wallet simulator, selection, test, controls and report of
research/hunt/PREREG_HUNT.md (study ``v1``) and research/hunt/PREREG_HUNT_WIDE.md (study ``wide``).

    python -m research.hunt.hunt select --study {v1,wide} --data <coins30 dir> [--procs N] [--private DIR]
    python -m research.hunt.hunt test   --study {v1,wide} --data <coins30 dir> [--procs N] [--private DIR]
    python -m research.hunt.hunt report --study {v1,wide}
    python -m research.hunt.hunt universe --data <coins30 dir>        (writes research/hunt/universe30.json)
    python -m research.hunt.hunt bench --out <timing.json> [--procs 2] (synthetic bars only, no real price)

``select`` and ``test`` refuse to run unless the study's pin file (PREREG_HUNT.sha256 / PREREG_HUNT_WIDE.sha256, one
line per file ``<sha256>  <path>``) matches every file it lists and lists the prereg(s), this file, every module of
research/hunt the run imports and research/hunt/universe30.json; ``test`` also needs the picks line. ``select``
appends the picks line itself after writing the picks (PREREG_HUNT 11.3, WIDE 5) and refuses when one is already there.

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
import calendar
import datetime as dt
import hashlib
import json
import math
import os
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
SEED_TAG = {"v1": "hunt", "wide": "hunt-wide"}
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
OUT_REL = {"v1": "research/hunt/out/v1", "wide": "research/hunt/out/wide"}
PICKS_REL = {"v1": "research/hunt/out/v1/pick.json", "wide": "research/hunt/out/wide/picks.json"}

CHOICES = [
    "H7.6: a 5m bar's entries (fills at its open) are decided first, on the state at the previous 5m close (equity, "
    "open positions, caps); then every open position, the new ones included, runs the bar in the order of H 7.6.",
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
    "applied by entries_wide.events_on.",
    "Outputs go to research/hunt/out/<study>/ (W10); PREREG_HUNT 11.3 and 16 name research/hunt/out/pick.json for "
    "v1, which this code writes as research/hunt/out/v1/pick.json.",
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


def check_pin(study: str, step: str) -> dict:
    """Refuse (PinError) unless every listed file matches and the required files are listed (W 10)."""
    rows = read_pin(study)
    listed = {p: h for h, p in rows}
    bad = []
    for h, p in rows:
        full = os.path.join(ROOT, p)
        if not os.path.exists(full):
            bad.append(f"missing {p}")
        elif sha256_file(full) != h:
            bad.append(f"changed {p}")
    need = list(PREREGS[study]) + ["research/hunt/hunt.py", UNIVERSE_REL] + hunt_modules()
    for p in need:
        if p not in listed:
            bad.append(f"not pinned {p}")
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

    def __init__(self, sym, ts, o, h, l, c, v, qv, last_ms=None, counts=None):
        self.sym = sym
        self.ts = np.asarray(ts, np.int64)
        self.o, self.h, self.l, self.c, self.v, self.qv = (np.asarray(x, np.float32) for x in (o, h, l, c, v, qv))
        self.last_ms = int(self.ts[-1]) if last_ms is None and len(self.ts) else last_ms
        self.counts = counts or {}
        self.cq = np.concatenate(([0.0], np.cumsum(self.qv, dtype=np.float64)))

    def f64(self) -> dict:
        return {"ts": self.ts, "o": self.o.astype(np.float64), "h": self.h.astype(np.float64),
                "l": self.l.astype(np.float64), "c": self.c.astype(np.float64), "v": self.v.astype(np.float64),
                "qv": self.qv.astype(np.float64)}


def clean_5m(ts, o, h, l, c, v, qv):
    """H 2: duplicate open times dropped (last kept), zero-volume bars dropped (quote volume <= 0); rows off the 5m
    grid or with a non-finite price dropped too. Returns (arrays, counts)."""
    ts = np.asarray(ts, np.int64)
    n0 = len(ts)
    order = np.argsort(ts, kind="stable")
    ts_s = ts[order]
    last = np.r_[ts_s[1:] != ts_s[:-1], True]
    idx = order[last]
    n_dup = n0 - len(idx)
    arr = [np.asarray(x)[idx] for x in (o, h, l, c, v, qv)]
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


def _parse_utc(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def load_coin(data_dir: str, sym: str, end_ms: int, manifest: dict | None = None) -> Coin:
    """The coin's 5m bars with open < end_ms (no later bar is read into the arrays; W 5)."""
    path = os.path.join(data_dir, "5m", f"{sym}.npz")
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} missing: the universe is fixed, select / test stop (W 9)")
    with np.load(path) as z:
        ts = z["ts"]
        cut = ts < end_ms
        cols = [z[k][cut] for k in ("o", "h", "l", "c", "v", "qv")]
        ts = ts[cut]
    (ts, o, h, l, c, v, qv), counts = clean_5m(ts, *cols)
    info = (manifest or {}).get(sym, {})
    last = info.get("last_nonzero_volume_bar") or info.get("last_bar")
    last_ms = _parse_utc(last) if last else None
    if last_ms is None:
        last_ms = int(ts[-1]) if len(ts) else None
        if last_ms is not None and last_ms >= end_ms - FIVE:
            last_ms = None                       # unknown beyond the loaded data: treated as continuing
    counts["missing_months_funding"] = info.get("missing_months_funding", [])
    return Coin(sym, ts, o, h, l, c, v, qv, last_ms=last_ms if last_ms is not None else 2 ** 62, counts=counts)


def load_funding(data_dir: str, sym: str, end_ms: int) -> tuple:
    path = os.path.join(data_dir, "funding", f"{sym}.npz")
    if not os.path.exists(path):
        return np.zeros(0, np.int64), np.zeros(0)
    with np.load(path) as z:
        ts, rate = np.asarray(z["ts"], np.int64), np.asarray(z["rate"], np.float64)
    keep = ts < end_ms
    return ts[keep], rate[keep]


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


def install(coins: dict, funding: dict | None = None) -> None:
    """Set the study's data (tests and the bench install synthetic coins the same way)."""
    _COINS.clear()
    _COINS.update(coins)
    _FUND.clear()
    _FUND.update(funding or {})
    for d in (_SERIES, _EVENTS, _SIGS, _BANKS):
        d.clear()


def load_study_data(data_dir: str, syms: list, end_ms: int) -> dict:
    man = _manifest(data_dir)
    coins = {s: load_coin(data_dir, s, end_ms, man) for s in syms}
    fund = {s: load_funding(data_dir, s, end_ms) for s in syms}
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
            ft.append((g[keep] - self.start) // FIVE - 1)                   # charged after the bar ending at calc_time
            fr.append(np.asarray(frate, np.float64)[keep])
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
    order = np.lexsort((out["coin"], out["src"], -out["prio"], out["t"]))
    return {x: v[order] for x, v in out.items()}


# ------------------------------------------------------------------ the engine (numba)
# position state (one slot per coin: one position per coin, H 8)
F_Q, F_COST, F_REFQ, F_Q1, F_U, F_D0, F_STOP, F_NEXT, F_MARGIN, F_B, F_LIQ, F_EXT, F_LAST, F_FEES, F_FUND, F_LEV, \
    F_P0 = range(17)
NF = 17
P_OPEN, P_SIDE, P_TRIED, P_FILLED, P_BPTR, P_BEND, P_FPTR, P_FEND, P_SPTR, P_SEND, P_LARGE, P_REC, P_SRC, P_TIN, \
    P_CUT = range(15)
NPI = 15
# records (one per opened position)
RF_U, RF_PNL, RF_FEES, RF_FUND, RF_P0, RF_D0, RF_Q1, RF_XPX, RF_LEV, RF_PRICE = range(10)
NRF = 10
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
def _bar(k, o, h, l, ps, pi, acc, others, cap_abs, taker, slip, min_not, askip, acut, n_adds, n, cap, mmr, cum):
    """H 7.6 for one position on one 5m bar. Returns (code, price): 0 none, EX_STOP at the stop, EX_GAP at the open,
    EX_LIQ liquidated."""
    side = pi[k, P_SIDE]
    stop = ps[k, F_STOP]
    liq = ps[k, F_LIQ]
    if side > 0:
        if o <= liq:
            return EX_LIQ, o
        if o <= stop:
            return EX_GAP, o
        if l <= stop or l <= liq:
            if liq > stop:
                return EX_LIQ, liq
            return EX_STOP, stop
        while pi[k, P_TRIED] < n_adds and h >= ps[k, F_NEXT]:
            lvl = ps[k, F_NEXT]
            ref = o if o >= lvl else lvl
            ok = _try_add(k, ref, ps, pi, acc, others, cap_abs, taker, slip, min_not, askip, acut, n, cap, mmr, cum)
            pi[k, P_TRIED] += 1
            ps[k, F_NEXT] = (ref if ok else lvl) + ps[k, F_D0]
            if ok:
                stop = ps[k, F_STOP]
                liq = ps[k, F_LIQ]
                if l <= stop or l <= liq:
                    if liq > stop:
                        return EX_LIQ, liq
                    return EX_STOP, stop
    else:
        if o >= liq:
            return EX_LIQ, o
        if o >= stop:
            return EX_GAP, o
        if h >= stop or h >= liq:
            if liq < stop:
                return EX_LIQ, liq
            return EX_STOP, stop
        while pi[k, P_TRIED] < n_adds and l <= ps[k, F_NEXT]:
            lvl = ps[k, F_NEXT]
            ref = o if o <= lvl else lvl
            ok = _try_add(k, ref, ps, pi, acc, others, cap_abs, taker, slip, min_not, askip, acut, n, cap, mmr, cum)
            pi[k, P_TRIED] += 1
            ps[k, F_NEXT] = (ref if ok else lvl) - ps[k, F_D0]
            if ok:
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
                others = 0.0
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


def params(r: float = R_BASE, cost: str = "base", risk_cap: float = RISK_CAP, start: float = START_WALLET):
    taker, slip = COSTS[cost]
    p = np.zeros(14)
    p[PR_START], p[PR_R], p[PR_CAP], p[PR_TAKER], p[PR_SLIP] = start, r, risk_cap, taker, slip
    p[PR_LIQF], p[PR_BUST], p[PR_CHAND], p[PR_BDIV], p[PR_LEVMAX] = LIQ_FRAC, BUST_FRAC, CHAND_MULT, B_DIV, LEV_MAX
    p[PR_LIQMULT], p[PR_MAXPOS], p[PR_MAXDIR], p[PR_NADDS] = LIQ_MULT, MAX_POS, MAX_DIR, N_ADDS
    return p


def simulate(mk: Market, bank: Bank, cands: dict, r: float = R_BASE, cost: str = "base",
             risk_cap: float = RISK_CAP, start: float = START_WALLET) -> tuple:
    br = mk.br
    return _engine(params(r, cost, risk_cap, start), mk.month_t0, mk.b_off, mk.b_t, mk.b_o, mk.b_h, mk.b_l, mk.b_c,
                   mk.b_qv, mk.f_off, mk.f_t, mk.f_rate, mk.coin_end_t, br["min_notional"], br["n"], br["cap"],
                   br["lev"], br["mmr"], br["cum"], mk.large, bank.s_ct, bank.s_h, bank.s_l, bank.s_atr,
                   cands["t"], cands["bi"], cands["coin"], cands["side"], cands["d0"], cands["s0"], cands["s1"])


# ------------------------------------------------------------------ metrics (H 10)
def summarize(mk: Market, raw: tuple, start: float = START_WALLET, detail: bool = True) -> dict:
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
                    "mean_pnl_U": None, "median_pnl_U": None, "win_share": None, "top10_share_of_profit": None})
    if detail:
        out["day_eq"] = [round(float(x), 4) for x in day_eq]
    return out


# ------------------------------------------------------------------ one system / one candidate list
def run_signals(mk: Market, parts: list, r: float = R_BASE, cost: str = "base", risk_cap: float = RISK_CAP,
                detail: bool = False) -> dict:
    tfs = tuple(sorted({sig["tf"] for sig, _ in parts}, key=TF_ORDER.index))
    bank = bank_for(mk, tfs)
    cands = build_cands(mk, bank, parts)
    out = summarize(mk, simulate(mk, bank, cands, r, cost, risk_cap), detail=detail)
    out["candidates"] = int(len(cands["t"]))
    return out


def run_system(mk: Market, spec: dict, r: float = R_BASE, cost: str = "base", gate: str | None = None,
               risk_cap: float = RISK_CAP, detail: bool = False) -> dict:
    sig = system_signals(mk, spec, gate)
    out = run_signals(mk, [(sig, 0)], r, cost, risk_cap, detail)
    out["signal_counts"] = dict(sig["counts"])
    return out


# ------------------------------------------------------------------ controls (H 12), bootstrap, seed rank, BH (H 13)
def control_pool(mk: Market, tf: str, k: int) -> np.ndarray:
    ser = series(mk.syms[k], tf)
    cm = ser.bars.close_ms
    _, f_ok = fill_index(mk, k, ser)
    ok = (cm >= mk.start) & (cm < mk.end) & (ser.code != UNKNOWN) & np.isfinite(ser.atr) & (ser.atr > 0) & f_ok
    return np.flatnonzero(ok)


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


def boot_p(d, seed: int, n_boot: int = N_BOOT) -> float:
    """One-sided month-block bootstrap (H 13): resample the months with replacement; p = (1 + resamples with mean
    d <= 0) / (n_boot + 1)."""
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


def run_controls(mk: Market, spec: dict, study: str, r: float, procs: int, n_seeds: int = N_SEEDS) -> dict:
    """Both controls x n_seeds for one pick on one market (seed parts of H 12 / W 6)."""
    sig = system_signals(mk, spec)
    tasks = [(mk.key, spec, study, ctl, s, r) for ctl in ("a", "b") for s in range(1, n_seeds + 1)]
    _G["mk"][mk.key] = mk
    res = pmap(_control_task, tasks, procs)
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
           "P3": bool(cost2["median_M"] >= 1.0), "P4": bool(base["max_dd"] < DD_MAX)}
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


def pmap(fn, tasks: list, procs: int) -> list:
    if procs <= 1 or len(tasks) <= 1:
        return [fn(t) for t in tasks]
    import multiprocessing as mp
    ctx = mp.get_context("fork")
    with ctx.Pool(min(procs, len(tasks))) as pool:
        return pool.map(fn, tasks, chunksize=max(1, len(tasks) // (procs * 8)))


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
    """W 5: order eligible systems by score (mean ln M), ties median M, family, name, timeframe, G1 before NONE,
    watch rank; take one per strategy name until K."""
    fam = {"F1": 0, "F2": 1, "F3": 2, "F4": 3}
    gate = {"G1": 0, "NONE": 1}

    def key(x):
        return (-x["score"], -x["median_M"], fam[x["family"]], x["name"], TF_ORDER.index(x["tf"]), gate[x["gate"]],
                x.get("rank") or 0)
    elig = sorted([x for x in rows if x["eligible"]], key=key)
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
    best = sorted(rows, key=key)[0] if rows else None
    return {"picks": [best["id"]] if best else [], "label": "no pick, fail"}


# ------------------------------------------------------------------ study steps
def _stamp(study: str, pin: dict | None) -> dict:
    return {"study": study, "git_commit": git_commit(), "pin": pin, "written_utc": ms_str(int(time.time() * 1000)),
            "choices": CHOICES}


def _write_json(path: str, obj) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
        fh.write("\n")
    os.replace(tmp, path)
    return sha256_file(path)


def _universe_and_data(args, end_key: str) -> tuple:
    data = args.data or os.environ.get("HUNT_DATA")
    if not data:
        raise SystemExit("--data <coins30 folder> (or $HUNT_DATA) is needed")
    syms = load_universe(data)
    end = day_ms(PERIODS[end_key][1])
    counts = load_study_data(data, syms, end)
    return data, syms, counts


def _sel_task(task) -> list:
    """Wide select unit: one entry cell (events once), both gates x base / cost x2 (W 5)."""
    mkey, specs = task
    mk = _G["mk"][mkey]
    out = []
    for spec in specs:
        t0 = time.time()
        base = run_system(mk, spec, R_BASE, "base")
        cost2 = run_system(mk, spec, R_BASE, "x2")
        ok, why = wide_eligible(base, cost2)
        row = {k: spec.get(k) for k in ("id", "family", "name", "strategy", "kind", "tf", "gate", "rank", "combo")}
        row.update({"eligible": ok, "fail": why, "score": base["mean_lnM"], "median_M": base["median_M"],
                    "n_positions": base["n_positions"], "bust": base["bust"], "win_share": base["win_share"],
                    "cost2_mean_lnM": cost2["mean_lnM"], "cost2_median_M": cost2["median_M"],
                    "max_dd": base["max_dd"], "end_multiple": base["end_multiple"],
                    "signal_counts": base["signal_counts"], "seconds": round(time.time() - t0, 3)})
        out.append(row)
    return out


def _group_cells(specs: list) -> list:
    cells = {}
    for s in specs:
        cells.setdefault(cell_key(s), []).append(s)
    return sorted(cells.values(), key=lambda g: (TF_ORDER.index(g[0]["tf"]), cell_key(g[0])))


def cmd_select(args) -> int:
    study = args.study
    pin = check_pin(study, "select")
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
        for spec in v1_systems():
            par, main, (lo, hi) = V1_ENTRIES[spec["name"]]
            rows[spec["id"]] = {
                "main": run_system(mk, spec, R_BASE), "lo": run_system(mk, v1_spec(spec["name"], spec["tf"], lo)),
                "hi": run_system(mk, v1_spec(spec["name"], spec["tf"], hi)), "one": run_system(mk, spec, R_ONE)}
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
        res = pmap(_sel_task, [(mk.key, g) for g in groups], args.procs)
        rows = [r for g in res for r in g]
        ch = wide_choose(rows)
        by_id = {s["id"]: s for s in specs}
        picks = [{**by_id[i], "pick_no": n + 1} for n, i in enumerate(ch["picks"])]
        public, private = redact_rows(rows)
        priv_sha = write_private(args, "wide_select_private.json", {"rows": private})
        sel = {**_stamp(study, pin), "data_counts": counts, "rows": public, "label": ch["label"],
               "picks": [p["id"] for p in picks], "private_sha256": priv_sha, "seconds": round(time.time() - t0, 1)}
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
    cost2 = run_system(mk, spec, r, "x2")
    ctl = run_controls(mk, spec, study, r, procs) if with_controls else None
    res = {"base": base, "cost2": cost2, "checks": judge(base, cost2, ctl, study, spec, mk.period, r)}
    if ctl is not None:
        res["controls"] = {"a_mean_lnM": ctl["a"].mean(axis=1).tolist(), "b_mean_lnM": ctl["b"].mean(axis=1).tolist(),
                           "gated_signals": ctl["gated"]}
    return res


def _reads(study: str, spec: dict, mks: dict, procs: int) -> dict:
    """H 14 / W 7 reads for one pick (never a pass)."""
    rd = {}
    rd["r1"] = _pick_block(study, spec, mks, procs, R_ONE)
    rd["select_controls"] = _pick_block(study, spec, mks, procs, R_BASE, True, "select")
    rd["new24"] = {p: run_system(mks[f"new_{p}"], spec, R_BASE) for p in ("select", "test")}
    rd["extra2020"] = {f"{r:g}": run_system(mks["extra"], spec, r) for r in (R_BASE, R_ONE)}
    diag = ("NONE", "TS") if spec["gate"] == "G1" else ("G1", "TS")
    rd["gate_diagnostics"] = {g: {p: run_system(mks[p], spec, R_BASE, gate=g) for p in ("select", "test")}
                              for g in diag}
    return rd


def _sizing(mk: Market, parts: list) -> dict:
    """W 7 sizing read: r = 2% and 5%, total open risk cap scaled by r / 0.5%."""
    out = {}
    for r in SIZING_RS:
        s = run_signals(mk, parts, r, "base", RISK_CAP * r / R_BASE)
        out[f"{r:g}"] = {k: s[k] for k in ("share_M_ge_2", "share_M_ge_10", "share_M_ge_30", "worst_month", "bust",
                                           "bust_month", "mean_lnM", "median_M", "max_dd", "end_multiple",
                                           "n_positions", "cut", "adds_skipped", "adds_cut", "skipped")}
    return out


def cmd_test(args) -> int:
    study = args.study
    pin = check_pin(study, "test")
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
        blocks = {p["id"]: _pick_block(study, p, mks, args.procs, R_BASE) for p in picks}
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
        reads = {p["id"]: _reads(study, p, mks, args.procs) for p in picks}
        for p in picks:
            c = blocks[p["id"]]["checks"]
            c["carried_by_old_six"] = bool(c["PASS"] and reads[p["id"]]["new24"]["test"]["mean_lnM"] <= 0)
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
              "n_positions", "win_share", "bust", "pick_no", "signal_counts", "seconds", "label"}
DS_ALLOWED_CHECKS = {"P0", "P1", "P2_a", "P2_b", "P3", "P4", "rank_ok_a", "rank_ok_b", "bh_significant", "PASS",
                     "carried_by_old_six"}


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
            out["reads"][pid] = "DeepSeek pick: figures in the private file (D11)"
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
    base = args.private or os.path.join(args.data or os.environ.get("HUNT_DATA", "."), "hunt_private")
    path = os.path.abspath(os.path.join(base, name))
    if os.path.commonpath([path, ROOT]) == ROOT:
        raise SystemExit("--private must be outside the repository (D11)")
    return _write_json(path, obj)


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
    run_s = float(np.mean([v["s_per_run_1proc"] for v in per_tf.values()]))
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
    sample = []
    try:
        for s in EW.systems():
            if s["gate"] != "G1" or s["family"] not in ("F2", "F3"):
                continue
            sample.append(s)
        pick = [x for x in sample if x["tf"] in ("15m", "4h")]
        rng = np.random.default_rng(3)
        pick = [pick[i] for i in sorted(rng.choice(len(pick), size=min(12, len(pick)), replace=False))]
        for spec in pick:
            t0 = time.perf_counter()
            for s in syms[:2]:
                btc = series(syms[0], spec["tf"]) if spec["kind"] == "ds" else None
                entry_events(spec, s, series(s, spec["tf"]), btc)
            ev[f"{spec['family']}:{spec['name']}:{spec['tf']}"] = round((time.perf_counter() - t0) / 2, 4)
    except Exception as e:  # pragma: no cover - timing only
        res["f2f3_error"] = repr(e)[:500]
    res["events_s_per_coin_series_select_length"] = ev
    f1 = [v for k, v in ev.items() if k.startswith("F1")]
    f23_15 = [v for k, v in ev.items() if not k.startswith("F1") and k.endswith(":15m")]
    f23_4h = [v for k, v in ev.items() if not k.startswith("F1") and k.endswith(":4h")]
    # extrapolation
    f23_mean_15 = float(np.mean(f23_15)) if f23_15 else 1.0
    f23_mean_4h = float(np.mean(f23_4h)) if f23_4h else 0.1
    tf_scale = {"15m": 1.0, "30m": 0.5, "1h": 0.25, "4h": f23_mean_4h / f23_mean_15 if f23_15 else 1 / 16}
    cells = _group_cells(EW.systems())
    ev_cpu = 0.0
    for g in cells:
        tf = g[0]["tf"]
        if g[0]["kind"] == "hunt":
            ev_cpu += 30 * (float(np.mean(f1)) if f1 else 0.1)
        else:
            ev_cpu += 30 * f23_mean_15 * tf_scale[tf]
    n_sys = len(EW.systems())
    sel_runs = 2 * n_sys
    eng_cpu = sel_runs * run_s
    ser_cpu = sum(ser_t.values())
    test_runs = 10 * (2 + 200) + 10 * (2 + 200) + 10 * (2 + 200) + 10 * (2 + 2 + 4 * 2) + 3 * 2 + 4
    test_months_ratio = 33 / 36
    test_cpu = test_runs * run_s * (1.0 + 0.25) + 10 * 30 * f23_mean_15 * 1.2 + ser_cpu * 1.7
    sel_cpu = ev_cpu + eng_cpu + ser_cpu
    res["extrapolation"] = {
        "systems": n_sys, "entry_cells": len(cells), "select_engine_runs": sel_runs,
        "select_cpu_s": {"events": round(ev_cpu), "engine": round(eng_cpu), "series": round(ser_cpu),
                         "total": round(sel_cpu)},
        "select_wall_h": {"procs_2": round(sel_cpu / 2 / 3600 * 1.1, 2), "procs_32": round(sel_cpu / 32 / 3600 * 1.2
                                                                                          + ser_cpu / 3600, 2)},
        "test_engine_runs": test_runs,
        "test_cpu_s": round(test_cpu),
        "test_wall_h": {"procs_2": round(test_cpu / 2 / 3600 * 1.1, 2), "procs_32": round(test_cpu / 32 / 3600 * 1.2
                                                                                         + ser_cpu * 1.7 / 3600, 2)},
        "notes": ["engine s/run measured at the select length (36 months); test is 33 months plus reads at other "
                  "lengths, x1.25 applied", f"test months / select months = {test_months_ratio:.3f}",
                  "events: F2/F3 time measured on a random sample of 12 definitions at 15m / 4h on 2 synthetic coins "
                  "of select length; 30m and 1h scaled by bar count", "series = bars + ATR + 장세 label for 30 coins "
                  "x 4 timeframes, built once per process before forking",
                  "test runs = per pick: base + cost x2 + 200 controls at 0.5%, the same at 1%, the same in the "
                  "select period (controls read), new-24 x2, extra x2, gate diagnostics x4; + basket and sizing"]}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps(res, indent=1))
    return 0


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
    ap.add_argument("cmd", choices=("select", "test", "report", "universe", "bench"))
    ap.add_argument("--study", choices=("v1", "wide"), default="v1")
    ap.add_argument("--procs", type=int, default=1)
    ap.add_argument("--data", default=None)
    ap.add_argument("--private", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
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
