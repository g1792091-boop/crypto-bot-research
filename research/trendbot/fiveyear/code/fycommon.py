"""Shared helpers of the five-year trend-bot study: paths, the verified 1m bars on a full minute grid, aggregation.
Run every script with python3 -I (the repo is put on sys.path explicitly; data files are read as arrays/CSV only)."""
import os, sys
sys.path.append("/root/.local/lib/python3.11/site-packages")      # user site (dateutil), dropped by -I
_UP = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
# the repo: this file's checkout when it sits in research/trendbot/fiveyear/code, else the worktree it was run from
REPO = _UP if os.path.isfile(os.path.join(_UP, "deploy", "combo.trend.json")) else \
    "/home/user/crypto-bot-research/.claude/worktrees/agent-a347b3c093866a3ea"
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import glob, hashlib, io, json, os, zipfile
import numpy as np
import pandas as pd

SCR = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
FG = f"{SCR}/fg1m"
ROOT = f"{SCR}/fiveyear"
OUT = f"{ROOT}/out"
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"]
MIN = 60_000
FIVE = 300_000
HOUR = 3_600_000
TF_MS = {"5m": 300_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
T0 = int(pd.Timestamp("2020-01-01", tz="UTC").value // 10**6)
T_FG_END = int(pd.Timestamp("2026-10-01", tz="UTC").value // 10**6)      # fg1m: last minute 2026-09-30 23:59
T_OCT_END = int(pd.Timestamp("2026-10-21", tz="UTC").value // 10**6)     # October daily files: last minute 10-20 23:59


def ms(s):
    return int(pd.Timestamp(s, tz="UTC").value // 10**6)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_oct(coin):
    """The October daily zips (checksums verified at download), read as CSV only."""
    parts = []
    for p in sorted(glob.glob(f"{ROOT}/octdata/{coin}-1m-2026-10-*/{coin}-1m-2026-10-*.zip")):
        with zipfile.ZipFile(p) as z:
            names = [n for n in z.namelist() if n.endswith(".csv")]
            assert len(names) == 1, (p, z.namelist())
            raw = z.read(names[0]).decode("ascii")
        d = pd.read_csv(io.StringIO(raw), header=0 if raw.startswith("open_time") else None, usecols=range(6))
        d.columns = ["ts", "o", "h", "l", "c", "v"]
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    d["ts"] = d["ts"].astype(np.int64)
    return d.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def load_grid(coin, with_oct=False):
    """1m bars on the full minute grid T0 .. end (exclusive): ts implicit (T0 + i minutes). Minutes before the coin's
    first bar are NaN; a minute missing inside the series (the build dropped zero-volume minutes, plus one gap > 1h per
    coin) is a flat bar at the previous close with volume 0 (Binance's own form of a no-trade minute). Mark prices
    likewise; funding rate 0 where none. Returns dict with o h l c v mo mh ml fund (float64) and 'filled' (bool)."""
    z = np.load(f"{FG}/1m/{coin}.npz")
    ts = z["ts"]
    end = T_OCT_END if with_oct else T_FG_END
    n = (end - T0) // MIN
    idx = (ts - T0) // MIN
    assert ((ts - T0) % MIN == 0).all() and (np.diff(ts) > 0).all()
    keep = idx < n
    idx = idx[keep]
    out = {}
    for k in ("o", "h", "l", "c", "v", "mo", "mh", "ml", "mc", "fund"):
        a = np.full(n, np.nan)
        a[idx] = z[k][keep]
        out[k] = a
    if with_oct:
        d = read_oct(coin)
        j = (d["ts"].to_numpy() - T0) // MIN
        ok = (j >= 0) & (j < n)
        for k in ("o", "h", "l", "c", "v"):
            out[k][j[ok]] = d[k].to_numpy(float)[ok]
        for k, src in (("mo", "o"), ("mh", "h"), ("ml", "l"), ("mc", "c")):      # no mark files for October: last price
            out[k][j[ok]] = d[src].to_numpy(float)[ok]
        out["fund"][j[ok]] = 0.0
    have = ~np.isnan(out["c"])
    first = int(np.argmax(have))
    filled = np.zeros(n, bool)
    # forward-fill inside the series
    miss = np.flatnonzero(~have[first:]) + first
    if len(miss):
        last_idx = np.maximum.accumulate(np.where(have, np.arange(n), -1))
        src = last_idx[miss]
        for k in ("o", "h", "l", "c"):
            out[k][miss] = out["c"][src]
        for k in ("mo", "mh", "ml", "mc"):
            out[k][miss] = out["mc"][src]
        out["v"][miss] = 0.0
        out["fund"][miss] = 0.0
        filled[miss] = True
    out["fund"] = np.nan_to_num(out["fund"])
    out["filled"] = filled
    out["first"] = first
    out["n"] = n
    return out


def agg(m, ms_, start=None):
    """Bars of ``ms_`` from the grid: complete bars only (from the first bar boundary at or after the coin's first
    minute). Returns dict ts (open ms), o h l c v."""
    k = ms_ // MIN
    first = m["first"] if start is None else start
    b0 = -(-first // k) * k                  # first bar boundary index at/after first (T0 is on every boundary)
    nb = (m["n"] - b0) // k
    sl = slice(b0, b0 + nb * k)

    def r(a):
        return a[sl].reshape(nb, k)
    return {"ts": T0 + (b0 + np.arange(nb) * k).astype(np.int64) * MIN, "o": r(m["o"])[:, 0].copy(),
            "h": r(m["h"]).max(1), "l": r(m["l"]).min(1), "c": r(m["c"])[:, -1].copy(), "v": r(m["v"]).sum(1)}


def df_of(b):
    return pd.DataFrame({"ts": pd.to_datetime(b["ts"], unit="ms", utc=True), "open": b["o"], "high": b["h"],
                         "low": b["l"], "close": b["c"], "volume": b["v"]})
