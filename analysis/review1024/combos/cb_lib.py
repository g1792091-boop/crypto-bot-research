"""Shared helpers for the combinations review of 2026-10-24 (analysis/review1024/combos).

Only READS the two export zips (untrusted data): ``safe_extract`` unpacks the members we need into a new, empty
folder (no absolute paths, no '..', no links, only known file types); sqlite files are opened read-only and immutable.
No code from the zips is ever run.

Units
- roe        : net profit / margin (fees, slippage and funding included), as the engines store it.
- wallet_ret : net profit / the account's wallet just before the trade closed (pnl / (equity_after - pnl)).
- ret_not    : net profit / notional (= roe / leverage). The "price" return after costs.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import zipfile
from typing import Optional

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

DAY_MS = 86_400_000
MIN_MS = 60_000
SEED = 20261024
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
TF_ORDER = {"15m": 1, "30m": 2, "1h": 3, "4h": 4, "5m": 0}

# house costs (paperbot/config.py Settings): taker 0.05 %, slippage 0.02 % per side, round trip for the ladder 0.14 %
TAKER, SLIP = 0.0005, 0.0002
RT = 2 * (TAKER + SLIP)
LAD_FIRST, LAD_STEP, LAD_GAP = 0.10, 0.05, 0.02


def safe_extract(zip_path: str, dest: str, only: set) -> dict:
    """Unpack only the listed members of ``zip_path`` into ``dest`` (must be missing or empty)."""
    if os.path.exists(dest) and os.listdir(dest):
        raise SystemExit(f"extract folder is not empty: {dest} (give a new empty folder)")
    os.makedirs(dest, exist_ok=True)
    root = os.path.realpath(dest)
    out = {}
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if info.is_dir() or name not in only:
                continue
            if name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") or ":" in name:
                raise SystemExit(f"suspicious member name, stopping: {name!r}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise SystemExit(f"link member, stopping: {name!r}")
            if not name.endswith((".csv", ".jsonl", ".json", ".db", ".txt")):
                raise SystemExit(f"unexpected file type, stopping: {name!r}")
            target = os.path.realpath(os.path.join(root, name))
            if not target.startswith(root + os.sep):
                raise SystemExit(f"member escapes the folder, stopping: {name!r}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            h = hashlib.sha256()
            with z.open(info) as src, open(target, "wb") as dst:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    h.update(b)
                    dst.write(b)
            out[name] = h.hexdigest()
    missing = set(only) - set(out)
    if missing:
        raise SystemExit(f"members missing from {zip_path}: {sorted(missing)}")
    return out


def open_ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro&immutable=1", uri=True)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def repo_imports():
    """The repo's own sizing / leverage-group code (trusted, not from the zips)."""
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from paperbot.config import v3_settings          # noqa: E402
    from paperbot import levrule, sizing             # noqa: E402
    from paperbot.margin import Brackets             # noqa: E402
    ex = json.load(open(os.path.join(REPO, "research", "fullgrid", "exchange.json")))
    br = {p["symbol"]: Brackets.from_binance(p) for p in ex["brackets"] if p["symbol"] in SYMS}
    specs = {s: dict(ex["specs"][s]) for s in SYMS}
    return v3_settings(), levrule, sizing, br, specs


# ---------------------------------------------------------------------------------------------- house exit replay
class Bars:
    """1-minute bars per coin (live_bars.csv of the rule bot export)."""

    def __init__(self, df: pd.DataFrame):
        self.d = {}
        for s, g in df.groupby("symbol"):
            g = g.sort_values("ts").drop_duplicates("ts")
            self.d[s] = dict(ts=g.ts.to_numpy(np.int64), o=g.open.to_numpy(float), h=g.high.to_numpy(float),
                             l=g.low.to_numpy(float), c=g.close.to_numpy(float), ct=g.close_time.to_numpy(np.int64))
        self.end = min(int(v["ct"][-1]) for v in self.d.values())

    def idx(self, sym: str, ts: int) -> int:
        a = self.d[sym]["ts"]
        i = int(np.searchsorted(a, ts))
        return i

    def close_at(self, sym: str, t_ms: int) -> float:
        """Last close at or before t_ms."""
        a = self.d[sym]
        i = int(np.searchsorted(a["ts"], t_ms, side="right")) - 1
        return float(a["c"][max(i, 0)])


def sim_house(bars: Bars, sym: str, t_entry: int, side: int, fill: float, stop0: float, lev: float):
    """Replay of paperbot.engine house exits for one position (2 ATR stop + net-ROE ladder lock, stop-market exits
    with slippage, taker fees both sides). Funding is not modelled (the export has no funding rates).
    Returns (exit_time, exit_price, reason, ret_not, roe) or None when the entry minute is missing."""
    a = bars.d[sym]
    n = len(a["ts"])
    i0 = int(np.searchsorted(a["ts"], t_entry))
    if i0 >= n or a["ts"][i0] != t_entry:
        # the engine enters on the first minute at/after the bar close; a missing minute shifts it
        if i0 >= n:
            return None
    W = 512
    while True:
        j1 = min(i0 + W, n)
        H, L, O = a["h"][i0:j1], a["l"][i0:j1], a["o"][i0:j1]
        if side > 0:
            fav = np.maximum.accumulate(H)
            best = lev * ((fav / fill - 1.0) - RT)
        else:
            fav = np.minimum.accumulate(L)
            best = lev * ((1.0 - fav / fill) - RT)
        first_trig = LAD_FIRST + LAD_GAP
        lock = np.where(best >= first_trig - 1e-12,
                        LAD_FIRST + LAD_STEP * np.floor((best - first_trig) / LAD_STEP + 1e-9), np.nan)
        lockpx = fill * (1.0 + side * (lock / lev + RT))
        m = j1 - i0
        s = np.full(m, stop0, dtype=float)
        if m > 2:
            lp = lockpx[1:m - 1]
            if side > 0:
                s[2:] = np.where(np.isfinite(lp), np.maximum(stop0, lp), stop0)
            else:
                s[2:] = np.where(np.isfinite(lp), np.minimum(stop0, lp), stop0)
        if side > 0:
            hit = L <= s
            gap = O <= s
        else:
            hit = H >= s
            gap = O >= s
        gap[0] = False
        ev = hit | gap
        k = int(np.argmax(ev)) if ev.any() else -1
        if k >= 0:
            locked = s[k] != stop0
            if gap[k]:
                px = O[k] * (1 - side * SLIP)
                t = int(a["ts"][i0 + k])
            else:
                px = s[k] * (1 - side * SLIP)
                t = int(a["ct"][i0 + k])
            reason = "LOCK" if locked else "SL"
            break
        if j1 >= n:
            px = float(a["c"][n - 1])
            t = int(a["ct"][n - 1])
            reason = "END"
            break
        W *= 4
    r = side * (px / fill - 1.0) - TAKER * (1.0 + px / fill)
    return t, float(px), reason, float(r), float(r * lev)


# ---------------------------------------------------------------------------------------------- small stats
def tstat(x) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 3 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x)))


def kst(ms) -> str:
    return pd.to_datetime(int(ms), unit="ms", utc=True).tz_convert("Asia/Seoul").strftime("%m/%d %H:%M")
