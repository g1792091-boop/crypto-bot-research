"""DeepSeek-200 live signals (paper v4, group "ds200", kind "ds200"): the 44 pinned definitions of
research/deepseek200/lib_c.py on the live closed bars. Part of the DS hash set (runinfo, D8): a change here restarts
the DeepSeek window only.

    python -m paperbot.dssig verify                  check the pins, load lib_c, print the hashes (read-only)
    python -m paperbot.dssig bench [--bars-dir DIR]  time one job per coin and timeframe at the live windows
                                                     (synthetic 5m bars unless DIR holds <coin>-5m.csv.gz)

Interface (fixed by P1, used by P4 sigservice/live3): ``verify``, ``defs_for``, ``ds_job``, ``DsError``,
``DsUnavailable``.

Rules (plan section 4, P2):
- lib_c.py is loaded by path, from the very bytes whose hash was checked, inside ``entry_marks._contained()``; its
  ``env()`` (research/library/lib.py, research/search/search.py, the vendor indicators) runs inside the same
  containment. sys.path and the warnings filters are therefore unchanged afterwards. The locked library
  (``sweepsig.lib()``) is loaded first, outside the containment, exactly as the core group loads it.
- pins: lib_c.py against research/deepseek200/out/summary.json code_sha256["lib_c.py"] AND paperbot/ds_pins.json;
  library/lib.py, search/search.py and the vendor fg_indicators / pine_indicators against ds_pins.json;
  PREREG_DEEPSEEK200.md against PREREG_DEEPSEEK200.sha256. The files are hashed before and again after the load. Any
  mismatch, missing file or load failure raises ``DsUnavailable``: only the DeepSeek signals are refused (P4 sends one
  CRITICAL alert), never the core group's. lib_c.DEFS must equal config.DS200_DEFS.
- frames: closed bars only. A job uses the 5m bars that closed at or before ``boundary`` (anything later is ignored),
  exactly the last config.DS_WINDOW_5M[tf] of them (fewer = warm-up, not ready), resampled with the locked
  ``resample_ohlcv`` as recorder.build_frames does (a partial bin at either end is dropped). 5m bars with exactly
  zero volume (no trades) are left out before resampling, as the 5-year bar files hold no bar without trades (a
  NaN volume is unknown, not zero, and is kept). The signal is the last chart bar, which must close at
  ``boundary``.
- coins: the key drops the T (BTCUSDT -> BTCUSD; lib_c skips F14_SMT only for coin "BTCUSD"); XRP and any other
  symbol outside lib_c.COINS is never computed (not ready). F14_SMT gets the BTC bars of the same boundary (the
  last ``BTC_TF_BARS`` chart bars of the window; F14 at the last bar needs 21) as a frame of BTC's own timestamps;
  lib_c matches them by timestamp (lib_c.py F14 block), so a missing BTC bar only removes F14 on that bar. BTC itself never gets F14 (no BTC context is passed for BTCUSD). If lib_c
  fails with the BTC context, the job is recomputed without it and only F14_SMT is lost (reported in "errors"), as
  shadow200 does.
- every exception inside a job becomes ``DsError`` (``DsUnavailable`` for the pins); nothing else leaves ``ds_job``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pickle
import statistics
import sys
import time
import warnings
from typing import Optional

import numpy as np
import pandas as pd

from .config import DS200_DEFS, DS200_TFS, DS_WINDOW_5M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEEP = os.path.join(ROOT, "research", "deepseek200")
LIB_C = os.path.join(DEEP, "lib_c.py")
SUMMARY = os.path.join(DEEP, "out", "summary.json")
PREREG = os.path.join(DEEP, "PREREG_DEEPSEEK200.md")
PREREG_SHA = os.path.join(DEEP, "PREREG_DEEPSEEK200.sha256")
PINS = os.path.join(ROOT, "paperbot", "ds_pins.json")
MODULE_NAME = "_paperbot_dssig_lib_c"   # private name: never the research or shadow200 module object

FIVE = 300_000
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
SYMBOL_SUFFIX = "T"          # Binance USDT-M symbol -> lib_c coin key (BTCUSDT -> BTCUSD)
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")   # = lib_c.COINS (checked at load); no XRP
# F14_SMT reads BTC only through rolling(20).max/min().shift(1) on BTC's own bars and an exact timestamp match, so the
# last bar's F14 needs the last 21 BTC chart bars; the job builds BTC's frame from its last 100 (the coin frame is
# never shortened). tests/test_dssig.py checks the last-bar sides against the full BTC window.
BTC_TF_BARS = 100

_C = None                    # the verified lib_c module of this process (each Pool worker loads its own)
_PINS: Optional[dict] = None


class DsError(Exception):
    """Any failure of a DeepSeek computation (the caller logs it and skips the DS signals of that job only)."""


class DsUnavailable(DsError):
    """The DeepSeek code cannot be used at all: a pin mismatch, a missing file, an import failure."""


def defs_for(tf: str) -> list[str]:
    """The definition ids traded on timeframe ``tf`` in PREREG order (44 on 15m / 30m / 1h, 39 on 4h, none else)."""
    if tf not in DS200_TFS:
        return []
    return [d for d, _family, tfs in DS200_DEFS if tf in tfs]


def coin_key(symbol: str) -> Optional[str]:
    """lib_c's coin key of a Binance symbol ("BTCUSDT" -> "BTCUSD"); None for a symbol lib_c does not trade (XRP)."""
    key = symbol[:-1] if symbol.endswith("USD" + SYMBOL_SUFFIX) else symbol
    return key if key in COINS else None


# ------------------------------------------------------------------ pins and the contained load
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return _sha256_bytes(fh.read())


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def _wanted() -> dict:
    """{absolute path: wanted sha256} of every pinned file; raises DsUnavailable when a pin source is unreadable."""
    try:
        with open(PINS, encoding="utf-8") as fh:
            pins = json.load(fh)
        with open(SUMMARY, encoding="utf-8") as fh:
            summary_lib_c = json.load(fh)["code_sha256"]["lib_c.py"]
        with open(PREREG_SHA, encoding="utf-8") as fh:
            prereg = fh.read().split()[0]
        files = {os.path.join(ROOT, *rel.split("/")): str(want) for rel, want in pins["files"].items()}
        pin_lib_c = str(pins["lib_c.py"])
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise DsUnavailable(f"DeepSeek pins unreadable: {type(exc).__name__}: {exc}"[:400]) from None
    if pin_lib_c != summary_lib_c:
        raise DsUnavailable(f"DeepSeek pins disagree: ds_pins.json lib_c.py {pin_lib_c[:12]} vs summary.json "
                            f"{str(summary_lib_c)[:12]}")
    return {LIB_C: pin_lib_c, PREREG: prereg, **files}


def _check(want: dict, lib_c_bytes: Optional[bytes] = None) -> dict:
    """{repo path: sha256} of the pinned files; raises DsUnavailable listing every file that differs or is missing."""
    got, bad = {}, []
    for path, sha in want.items():
        try:
            have = _sha256_bytes(lib_c_bytes) if (path == LIB_C and lib_c_bytes is not None) else _sha256(path)
        except OSError:
            bad.append(f"{_rel(path)} (missing)")
            continue
        got[_rel(path)] = have
        if have != sha:
            bad.append(f"{_rel(path)} ({have[:12]} != pinned {sha[:12]})")
    if bad:
        raise DsUnavailable("DeepSeek code changed or missing: " + "; ".join(bad))
    return got


def _shape(got: dict) -> dict:
    """verify()'s return: "lib_c.py" (the key P1's interface names) plus every other pinned file by repo path."""
    out = {"lib_c.py": got[_rel(LIB_C)]}
    out.update({k: v for k, v in got.items() if k != _rel(LIB_C)})
    return out


def _load() -> object:
    """Hash, load (contained) and re-hash; returns the lib_c module. Raises DsUnavailable."""
    global _C, _PINS
    if _C is not None:
        return _C
    from . import sweepsig
    from .entry_marks import _contained
    want = _wanted()
    try:
        with open(LIB_C, "rb") as fh:
            src = fh.read()
    except OSError as exc:
        raise DsUnavailable(f"DeepSeek lib_c.py unreadable: {exc}"[:400]) from None
    _check(want, src)
    try:
        sweepsig.lib()          # the locked library as the core group loads it (lib_c's env() takes it from there)
    except Exception as exc:  # noqa: BLE001
        raise DsUnavailable(f"locked library unavailable: {type(exc).__name__}: {exc}"[:400]) from None
    spec = importlib.util.spec_from_file_location(MODULE_NAME, LIB_C)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = mod
    try:
        with _contained():
            exec(compile(src, LIB_C, "exec"), mod.__dict__)
            mod.env()
    except BaseException as exc:
        sys.modules.pop(MODULE_NAME, None)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise DsUnavailable(f"DeepSeek lib_c failed to load: {type(exc).__name__}: {exc}"[:400]) from None
    try:
        got = _check(want)    # the files did not change while they were loaded
        defs = [(d, f, tuple(t)) for d, f, t in mod.DEFS]
        if defs != [(d, f, tuple(t)) for d, f, t in DS200_DEFS]:
            raise DsUnavailable("lib_c.DEFS differs from config.DS200_DEFS")
        if tuple(mod.COINS) != COINS:
            raise DsUnavailable(f"lib_c.COINS {tuple(mod.COINS)} differs from dssig.COINS")
    except DsUnavailable:
        sys.modules.pop(MODULE_NAME, None)
        raise
    _C, _PINS = mod, _shape(got)
    return _C


def verify() -> dict:
    """Check every pin and load lib_c (contained). Returns {"lib_c.py": sha256, "<repo path>": sha256, ...} of the
    files it checked (lib_c.py under its short key, the others by repo-relative path); raises ``DsUnavailable`` on
    any mismatch or load failure. Called once at start (P4) and recorded in the run record. When lib_c is already
    loaded in this process, the files on disk are re-hashed (a later edit is caught; the loaded code is the one that
    was checked)."""
    if _C is None:
        _load()
        return dict(_PINS)
    return _shape(_check(_wanted()))


# ------------------------------------------------------------------ frames
def _closed(cols: tuple, boundary: int, since: Optional[int] = None) -> tuple:
    """The 5m columns (ts, o, h, l, c, v) restricted to bars that closed at or before ``boundary`` (and opened at or
    after ``since``)."""
    ts = np.asarray(cols[0], dtype=np.int64)
    keep = ts + FIVE <= int(boundary)
    if since is not None:
        keep &= ts >= int(since)
    return (ts[keep],) + tuple(np.asarray(a, dtype=float)[keep] for a in cols[1:6])


def frame(ts, o, h, l, c, v, tf: str, lib=None) -> pd.DataFrame:
    """Chart bars of ``tf`` from 5m bars (ms open times, oldest first): the locked resample_ohlcv, a partial bin at
    either end dropped (recorder.build_frames), 5m bars with exactly zero volume left out first."""
    if lib is None:
        from . import sweepsig
        lib = sweepsig.lib()
    ts = np.asarray(ts, dtype=np.int64)
    cols = {"open": o, "high": h, "low": l, "close": c, "volume": v}
    cols = {k: np.asarray(a, dtype=float) for k, a in cols.items()}
    if not len(ts):
        return pd.DataFrame({"ts": pd.to_datetime(np.array([], np.int64), unit="ms", utc=True, cache=False),
                             **{k: np.array([], float) for k in cols}})
    first_open, last_close = int(ts[0]), int(ts[-1]) + FIVE
    traded = ~(cols["volume"] == 0.0)
    df5 = pd.DataFrame({"ts": pd.to_datetime(ts[traded], unit="ms", utc=True, cache=False),
                        **{k: a[traded] for k, a in cols.items()}})
    r = lib.resample_ohlcv(df5, tf)
    t = (r["ts"].astype("int64") // 1_000_000).to_numpy(np.int64)
    keep = (t >= first_open) & (t + TF_MS[tf] <= last_close)
    df = r.loc[keep].reset_index(drop=True)
    df.attrs["tf"] = tf
    return df


def entries_frame(df: pd.DataFrame, tf: str, coin: str, btc: Optional[pd.DataFrame] = None) -> tuple[dict, list]:
    """({definition: (long, short)} of lib_c on a chart frame for the definitions of ``tf``, notes). ``btc`` is
    BTC's chart frame (its own timestamps) for F14_SMT; ignored for coin BTCUSD."""
    C = _load()
    notes: list = []
    ctx = {"BTCUSD": btc} if (btc is not None and len(btc) and coin != "BTCUSD") else None
    if ctx is None and coin != "BTCUSD":
        notes.append("F14_SMT: no BTC bars")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            R = C.entries(df, tf, ctx, coin)
        except Exception as exc:  # noqa: BLE001
            if ctx is None:
                raise
            notes.append(f"F14_SMT context failed ({type(exc).__name__}: {exc})"[:300])
            R = C.entries(df, tf, None, coin)
    want = defs_for(tf)
    missing = [d for d in want if d not in R]
    if missing:
        raise DsError(f"lib_c gave no {tf} result for {missing}")
    return {d: R[d] for d in want}, notes


# ------------------------------------------------------------------ the Pool job
def ds_job(args: tuple) -> dict:
    """Pool worker (top-level, picklable): the DeepSeek sides of the ``tf`` bar that closes at ``boundary`` for one
    coin.

    ``args`` = (symbol, tf, boundary, ts, o, h, l, c, v, btc): the coin's last config.DS_WINDOW_5M[tf] closed 5m
    bars as arrays (ts = bar open in ms, oldest first; the same layout as sigservice.compute_last's job) and ``btc``
    = the same arrays (ts, o, h, l, c, v) of BTCUSDT for the same window (None when ``symbol`` is BTCUSDT). Bars
    closing after ``boundary`` are ignored; more than the window is trimmed to it; fewer is a warm-up.

    Returns {"symbol", "tf", "ready": bool, "why": str (only when not ready), "bar_open": ms of the last ``tf`` bar,
    "close": its close, "atr": ATR14 of that bar or None, "sides": {def_id: +1 | -1} (only the definitions that fire
    on that bar, ids from ``defs_for(tf)``, in that order), "errors": [str]}. Raises ``DsError`` (never another
    exception)."""
    try:
        return _job(args)
    except DsError:
        raise
    except Exception as exc:  # noqa: BLE001  (nothing but DsError may reach the caller)
        head = ""
        try:
            head = f"{args[0]} {args[1]} "
        except Exception:  # noqa: BLE001
            pass
        raise DsError(f"DeepSeek {head}{type(exc).__name__}: {exc}"[:500]) from None


def _job(args: tuple) -> dict:
    symbol, tf, boundary, ts, o, h, l, c, v, btc = args
    boundary = int(boundary)
    out = {"symbol": symbol, "tf": tf, "ready": False, "errors": []}
    coin = coin_key(symbol)
    if coin is None:
        out["why"] = f"{symbol} is not a DeepSeek coin"
        return out
    if tf not in DS200_TFS:
        out["why"] = f"no DeepSeek definitions on {tf}"
        return out
    if boundary % TF_MS[tf]:
        out["why"] = f"{boundary} is not a {tf} boundary"
        return out
    _load()
    from . import sweepsig
    lib = sweepsig.lib()
    cols = _closed((ts, o, h, l, c, v), boundary)
    need = DS_WINDOW_5M[tf]
    if len(cols[0]) < need:
        out["why"] = f"warm-up: {len(cols[0])} of {need} closed 5m bars"
        return out
    cols = tuple(a[-need:] for a in cols)
    if np.any(np.diff(cols[0]) <= 0):
        out["why"] = "5m bars out of order or repeated"
        return out
    df = frame(*cols, tf=tf, lib=lib)
    if not len(df):
        out["why"] = f"no complete {tf} bar"
        return out
    last_open = int(df["ts"].iloc[-1].value // 1_000_000)
    if last_open + TF_MS[tf] != boundary:
        out["why"] = f"last {tf} bar opens at {last_open}, expected {boundary - TF_MS[tf]}"
        return out
    bdf = None
    if coin != "BTCUSD" and btc is not None:
        since = max(int(cols[0][0]), boundary - BTC_TF_BARS * TF_MS[tf])
        b = _closed(tuple(btc), boundary, since=since)
        if len(b[0]) and not np.any(np.diff(b[0]) <= 0):
            bdf = frame(*b, tf=tf, lib=lib)
        elif len(b[0]):
            out["errors"].append("F14_SMT: BTC 5m bars out of order or repeated")
    R, notes = entries_frame(df, tf, coin, bdf)
    sides = {}
    for d, (lg, sh) in R.items():
        if bool(lg[-1]):
            sides[d] = 1
        elif bool(sh[-1]):
            sides[d] = -1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        atr = float(lib.fg.atr(df, 14).to_numpy(float)[-1])
    out.update(ready=True, bar_open=last_open, close=float(df["close"].iloc[-1]),
               atr=atr if np.isfinite(atr) else None, sides=sides, errors=out["errors"] + notes)
    return out


# ------------------------------------------------------------------ bench (server, read-only)
def _synth5m(n: int, end_ms: int, seed: int) -> tuple:
    """n synthetic 5m bars (random walk) whose last bar closes at ``end_ms``."""
    rng = np.random.default_rng(seed)
    ts = end_ms - FIVE * np.arange(n, 0, -1, dtype=np.int64)
    r = rng.normal(0, 0.002, n)
    c = 100.0 * np.exp(np.cumsum(r))
    o = np.r_[100.0, c[:-1]]
    w = np.abs(rng.normal(0, 0.0015, n))
    h = np.maximum(o, c) * (1 + w)
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0015, n)))
    v = rng.lognormal(3, 1, n)
    return ts, o, h, lo, c, v


def _csv5m(bars_dir: str, coin: str, n: int, boundary: Optional[int]) -> Optional[tuple]:
    p = os.path.join(bars_dir, f"{coin.lower()}-5m.csv.gz")
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p)
    t = (pd.to_datetime(d["ts"], utc=True).astype("int64") // 1_000_000).to_numpy(np.int64)
    if boundary is not None:
        keep = t + FIVE <= boundary
        d, t = d.loc[keep], t[keep]
    d, t = d.iloc[-n:], t[-n:]
    return (t,) + tuple(d[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))


def bench(bars_dir: Optional[str] = None, rep: int = 3, tfs=DS200_TFS) -> dict:
    """Median / max milliseconds of one ``ds_job`` per coin at the live windows, and the pickled job size."""
    pins = verify()
    coins = list(COINS)
    out: dict = {"pins": pins, "source": "synthetic", "tfs": {}}
    for tf in tfs:
        n = DS_WINDOW_5M[tf]
        boundary = None
        data = {}
        if bars_dir:
            probe = _csv5m(bars_dir, "BTCUSD", n, None)
            if probe is not None:
                last = int(probe[0][-1]) + FIVE
                boundary = last - last % TF_MS[tf]
                data = {k: _csv5m(bars_dir, k, n, boundary) for k in coins}
                if all(x is not None for x in data.values()):
                    out["source"] = bars_dir
                else:
                    data = {}
        if not data:
            boundary = 1_790_000_000_000 - 1_790_000_000_000 % TF_MS["4h"]
            data = {k: _synth5m(n, boundary, i) for i, k in enumerate(coins)}
        times, sizes, fired, notready = [], [], 0, 0
        for k in coins:
            job = (k + SYMBOL_SUFFIX, tf, boundary) + tuple(data[k]) + (None if k == "BTCUSD" else data["BTCUSD"],)
            sizes.append(len(pickle.dumps(job, protocol=pickle.HIGHEST_PROTOCOL)))
            ds_job(job)                                   # warm caches once
            for _ in range(rep):
                t0 = time.perf_counter()
                r = ds_job(job)
                times.append(time.perf_counter() - t0)
            fired += len(r.get("sides", {}))
            notready += 0 if r["ready"] else 1
        out["tfs"][tf] = {"window_5m": n, "jobs": len(coins), "median_ms": round(statistics.median(times) * 1000, 1),
                          "max_ms": round(max(times) * 1000, 1), "job_mb": round(max(sizes) / 1e6, 2),
                          "sides_last_bar": fired, "not_ready": notready}
    return out


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m paperbot.dssig", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="check the pins and load lib_c (read-only)")
    b = sub.add_parser("bench", help="time one job per coin and timeframe at the live windows (read-only)")
    b.add_argument("--bars-dir", help="directory with <coin>-5m.csv.gz files (else synthetic bars)")
    b.add_argument("--rep", type=int, default=3)
    a = p.parse_args(argv)
    try:
        res = verify() if a.cmd == "verify" else bench(a.bars_dir, max(1, a.rep))
    except DsError as exc:
        print(f"DeepSeek unavailable: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
