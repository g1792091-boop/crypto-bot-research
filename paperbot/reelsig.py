"""The reel's live signal (paper v4, group "reel", account REEL_H1@5m): PREREG_REEL5M H1 (5m, Bollinger(20, 2) +
SMA200, close-breach, long only) on the live closed 5m bars, plus the entry levels of the three 5m coin flips. Part
of the REEL hash set (runinfo, D8): a change here restarts the reel's window only.

    python -m paperbot.reelsig verify                  check the pins, load lib_reel5m, print the hashes (read-only)
    python -m paperbot.reelsig bench [--bars-dir DIR]  time signal() and flip_levels() at the live window
                                                       (synthetic 5m bars unless DIR holds <coin>-5m.csv.gz)

Interface (fixed by P1, used by P4 sigservice/live3 and P5 reel_engine): ``verify``, ``signal``, ``flip_levels``,
``ReelError``, ``ReelUnavailable``.

Rules (plan section 4, P3; owners' D2 (ii), D3, D4):
- research/reel5m/lib_reel5m.py is loaded by path, from the very bytes whose hash was checked, under a private module
  name inside ``entry_marks._contained()`` (its import inserts into sys.path and sets warnings filters; both are
  restored), and its ``env()`` (research/library/lib.py, research/search/search.py, the locked vendor indicators)
  runs inside the same containment. The locked library (``sweepsig.lib()``, which checks the vendor hashes) is
  loaded first, outside it, exactly as the core group loads it.
- pins (the hashes are hard-coded below, so a pin change is a change of this file, i.e. of the REEL hash set):
  PREREG_REEL5M.md = PIN_PREREG and = the hash recorded in PREREG_REEL5M.sha256 (committed in ef31879; the 5-year
  run's out/summary.json "prereg_sha256" is the same value); lib_reel5m.py = PIN_LIB_REEL5M and = out/summary.json
  code_sha256["lib_reel5m.py"]; research/library/lib.py and research/search/search.py (imported by lib_reel5m's
  env()) = PIN_FILES. The files are hashed before and again after the load. Any mismatch, missing file or load
  failure raises ``ReelUnavailable``: only the reel's signals (and the 5m coin flips' levels) are refused, never
  another group's.
- ``signal`` runs the PREREG's position-independent machine (``lib_reel5m.simulate(trade=False)``; owners' D3: the
  arming ignores positions live) with H1's settings (SMA200 / CLOSE / LONG) on ``lib_reel5m.indicators`` of exactly
  the last config.REEL_WINDOW_5M closed 5m bars, started flat on the window's first bar, and reports the window's
  last bar only. simulate needs the entry bar s+1 to exist, so the indicator arrays get one NaN entry appended (no
  price is invented: a NaN bar can neither arm nor signal, and the first target it reads, the previous bar's upper
  band, is the upper band of bar s). The stop, swing low and first target are lib_reel5m's own numbers
  (``extreme``, ``stop_px``, ``target0``).
- start invariance (tests/test_reelsig.py, the 5-year 5m files of the six coins, 3.6 million coin-bars): the
  machine never depends on the window. It can differ from the anchored (whole-history) machine only on a setup that
  began before the window's SMA200 warm-up ended, i.e. one longer than REEL_WINDOW_5M - 200 bars; the longest in 5
  years (first breach bar to signal) is 14 bars. The indicators can, but only by rounding at a float tie: a bar whose
  close equals the lower band (four of the 20 closes at the close, sixteen at another price) or whose 20-bar mean
  equals the 200-bar mean on the tick grid, in real numbers or within about 1e-8. lib_reel5m's pandas rolling
  variance carries rounding from every update since the computation started (up to 2e-8 relative after the 5-year
  series, against exact sums; a 5,000-bar window carries far less), so the research's anchored series and a live
  window can decide such a bar differently. No window length removes this. Measured over every bar near every such
  tie (anchored margin below 1e-7: 129 bars in 5 years of six coins): at 5,000 bars 2 differing bars (2023, a
  signal in the anchored series that the window does not give, on the bar after a close = band tie and after a
  middle line = SMA200 tie); 2,000 / 3,000 bars: 4 / 5. Every bar of 2026-07..09 of the six coins is equal.
  tests/test_reelsig.py lists them and repeats the check.
- never side -1; a filter turning off cancels the arming; a setup expires 12 bars after its last breach; the breach
  bar is never the signal (all lib_reel5m's machine). A frame shorter than the window, a non-finite open / high /
  low / close inside the window, or a NaN / non-positive ATR14 or a NaN upper band on the last bar give None.
  Bars must be oldest first, on the 5m grid, strictly increasing (a gap is allowed and treated as lib_reel5m treats
  a bar missing from its data: the bars are counted, not the clock); anything else raises ``ReelError``.
- every exception inside ``signal`` / ``flip_levels`` becomes ``ReelError`` (``ReelUnavailable`` for the pins).

Differences from the PREREG on the signal side (owners' D3; the exits are in paperbot/reel_engine.py):
- the arming ignores positions (the PREREG's trade=True walk does not arm while a trade is open), so the reel
  signals while its account already holds a position (the engine records SKIPPED) and the 5m coin flips fire at the
  same position-independent rate (config.V4_FLIP5M);
- the machine starts flat at the window's first bar instead of at the series start (no difference, see above);
- live, a bar whose open / high / low / close is not finite blanks the next REEL_WINDOW_5M bars (None); the 5-year
  data has none.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import threading
import time
import warnings
from types import SimpleNamespace
from typing import Optional

import numpy as np
import pandas as pd

from .config import REEL_TF, REEL_WINDOW_5M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REEL_DIR = os.path.join(ROOT, "research", "reel5m")
LIB_REEL5M = os.path.join(REEL_DIR, "lib_reel5m.py")
PREREG = os.path.join(REEL_DIR, "PREREG_REEL5M.md")
PREREG_SHA = os.path.join(REEL_DIR, "PREREG_REEL5M.sha256")
SUMMARY = os.path.join(REEL_DIR, "out", "summary.json")
MODULE_NAME = "_paperbot_reelsig_lib_reel5m"   # private name: never the research or test module object

# The pins (sha256). PREREG_REEL5M.md as committed in ef31879 (its .sha256 file and the 5-year run's summary.json
# record the same value); lib_reel5m.py as committed in ef31879 and run for the 5-year results (5bc7e5f).
PIN_PREREG = "835f786a965b8d9a268a99c576128bb7789dc8ddf06212eefcba745f7aca402a"
PIN_LIB_REEL5M = "a824717e50b0a4f7e2890ceb1457a12ee096ebc36e8a56c56e30c7e77dfc0eda"
PIN_FILES = {   # imported by lib_reel5m.env(); the same hashes as paperbot/ds_pins.json
    "research/library/lib.py": "5c3e1083c734e8079df64d3a501ef7c7b0fbb8819c7c67087ba01ff213a999ce",
    "research/search/search.py": "06920240b6f56e954e1896c16fed7c58b8fb8b3d95d73109efa0d1dcced43ce3",
}

# H1 (PREREG section 5) and the numbers this wrapper relies on; checked against the loaded lib_reel5m.
H1_SETTINGS = ("SMA200", "CLOSE", "LONG")
WAIT = 12                    # a setup expires 12 bars after its last breach bar
STOP_BUF_ATR = 0.05          # stop = swing low - 0.05 x ATR14 of the signal bar
BB_LEN = 20                  # Bollinger length: "closes" carries the BB_LEN - 1 closes of bars s-18..s
FLIP_LOOKBACK = 12           # 5m coin flips (owners' D4): swing low = lowest low of the last 12 closed 5m bars
FIVE_MS = 300_000
WINDOW = REEL_WINDOW_5M      # closed 5m bars each computation uses (the last ones of the frame)
_LIB_CONSTANTS = {"WAIT": WAIT, "STOP_BUF_ATR": STOP_BUF_ATR, "BB_LEN": BB_LEN, "BB_K": 2.0, "MA_LEN": 200,
                  "ATR_LEN": 14, "MAX_HOLD": 96}
# simulate(trade=False) reads only cost.slip_side (for entries it never makes); the signal levels do not use it.
_NO_COST = SimpleNamespace(slip_side=0.0)

_R = None                    # the verified lib_reel5m module of this process
_PINS: Optional[dict] = None
_LOCK = threading.Lock()


class ReelError(Exception):
    """Any failure of the reel computation (the caller logs it and skips the 5m reel signal of that boundary)."""


class ReelUnavailable(ReelError):
    """The reel code cannot be used at all: a pin mismatch, a missing file, an import failure."""


# ------------------------------------------------------------------ pins and the contained load
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return _sha256_bytes(fh.read())


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def _wanted() -> dict:
    """{absolute path: pinned sha256} of every pinned file, after checking that the research's own records agree
    with the pins; raises ReelUnavailable."""
    try:
        with open(PREREG_SHA, encoding="utf-8") as fh:
            parts = fh.read().split()
        with open(SUMMARY, encoding="utf-8") as fh:
            summary = json.load(fh)
        summary_lib = str(summary["code_sha256"]["lib_reel5m.py"])
        summary_prereg = str(summary["prereg_sha256"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ReelUnavailable(f"reel pins unreadable: {type(exc).__name__}: {exc}"[:400]) from None
    if len(parts) != 2 or parts[1] != os.path.basename(PREREG):
        raise ReelUnavailable(f"{_rel(PREREG_SHA)} is not '<sha256>  {os.path.basename(PREREG)}'")
    bad = []
    if parts[0] != PIN_PREREG:
        bad.append(f"{_rel(PREREG_SHA)} records {parts[0][:12]} != pinned {PIN_PREREG[:12]}")
    if summary_prereg != PIN_PREREG:
        bad.append(f"out/summary.json prereg_sha256 {summary_prereg[:12]} != pinned {PIN_PREREG[:12]}")
    if summary_lib != PIN_LIB_REEL5M:
        bad.append(f"out/summary.json lib_reel5m.py {summary_lib[:12]} != pinned {PIN_LIB_REEL5M[:12]}")
    if bad:
        raise ReelUnavailable("reel pins disagree: " + "; ".join(bad))
    files = {os.path.join(ROOT, *rel.split("/")): sha for rel, sha in PIN_FILES.items()}
    return {LIB_REEL5M: PIN_LIB_REEL5M, PREREG: PIN_PREREG, **files}


def _check(want: dict, lib_bytes: Optional[bytes] = None) -> dict:
    """{repo path: sha256} of the pinned files; raises ReelUnavailable listing every file that differs or is
    missing."""
    got, bad = {}, []
    for path, sha in want.items():
        try:
            have = _sha256_bytes(lib_bytes) if (path == LIB_REEL5M and lib_bytes is not None) else _sha256(path)
        except OSError:
            bad.append(f"{_rel(path)} (missing)")
            continue
        got[_rel(path)] = have
        if have != sha:
            bad.append(f"{_rel(path)} ({have[:12]} != pinned {sha[:12]})")
    if bad:
        raise ReelUnavailable("reel code changed or missing: " + "; ".join(bad))
    return got


def _shape(got: dict) -> dict:
    """verify()'s return: "PREREG_REEL5M.md" and "lib_reel5m.py" (the keys P1's interface names), then the other
    pinned files by repo path."""
    out = {"PREREG_REEL5M.md": got[_rel(PREREG)], "lib_reel5m.py": got[_rel(LIB_REEL5M)]}
    out.update({k: v for k, v in got.items() if k not in (_rel(PREREG), _rel(LIB_REEL5M))})
    return out


def _check_module(mod) -> None:
    """The loaded lib_reel5m has H1 and the numbers this wrapper (and reel_engine) relies on."""
    bad = [f"{k}={getattr(mod, k, None)!r} (want {v!r})" for k, v in _LIB_CONSTANTS.items()
           if getattr(mod, k, None) != v]
    if tuple(mod.H1[:2]) != (REEL_TF, mod.entry_name(*H1_SETTINGS)) or tuple(mod.parse_entry(mod.H1[1])) != H1_SETTINGS:
        bad.append(f"H1={mod.H1!r}")
    for name in ("indicators", "Prep", "simulate"):
        if not callable(getattr(mod, name, None)):
            bad.append(f"no {name}()")
    if bad:
        raise ReelUnavailable("lib_reel5m differs from what the reel wrapper expects: " + "; ".join(bad))


def _load():
    """Hash, load (contained) and re-hash; returns the lib_reel5m module. Raises ReelUnavailable."""
    global _R, _PINS
    if _R is not None:
        return _R
    with _LOCK:
        if _R is not None:
            return _R
        from . import sweepsig
        from .entry_marks import _contained
        want = _wanted()
        try:
            with open(LIB_REEL5M, "rb") as fh:
                src = fh.read()
        except OSError as exc:
            raise ReelUnavailable(f"lib_reel5m.py unreadable: {exc}"[:400]) from None
        _check(want, src)
        try:
            sweepsig.lib()      # the locked library as the core group loads it (lib_reel5m's env() takes it from there)
        except Exception as exc:  # noqa: BLE001
            raise ReelUnavailable(f"locked library unavailable: {type(exc).__name__}: {exc}"[:400]) from None
        spec = importlib.util.spec_from_file_location(MODULE_NAME, LIB_REEL5M)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = mod
        try:
            with _contained():
                exec(compile(src, LIB_REEL5M, "exec"), mod.__dict__)
                mod.env()
        except BaseException as exc:
            sys.modules.pop(MODULE_NAME, None)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise ReelUnavailable(f"lib_reel5m failed to load: {type(exc).__name__}: {exc}"[:400]) from None
        try:
            got = _check(want)    # the files did not change while they were loaded
            _check_module(mod)
        except ReelUnavailable:
            sys.modules.pop(MODULE_NAME, None)
            raise
        _R, _PINS = mod, _shape(got)
        return _R


def verify() -> dict:
    """Check the pins (PREREG_REEL5M.md against PIN_PREREG and PREREG_REEL5M.sha256, lib_reel5m.py against
    PIN_LIB_REEL5M and out/summary.json, the library files lib_reel5m imports) and load lib_reel5m (contained).
    Returns {"PREREG_REEL5M.md": sha256, "lib_reel5m.py": sha256, "research/library/lib.py": sha256,
    "research/search/search.py": sha256}; raises ``ReelUnavailable``. Called once at start (P4) and recorded in the
    run record. When lib_reel5m is already loaded in this process, the files on disk are re-hashed (a later edit is
    caught; the loaded code is the one that was checked)."""
    if _R is None:
        _load()
        return dict(_PINS)
    return _shape(_check(_wanted()))


# ------------------------------------------------------------------ the window and the indicators
def _ms(ts) -> np.ndarray:
    """Bar open times in ms (int64) from a ts column of datetimes or of ms integers."""
    s = pd.Series(ts)
    if pd.api.types.is_datetime64_any_dtype(s.dtype):
        if getattr(s.dt, "tz", None) is None:
            s = s.dt.tz_localize("UTC")
        return (s.dt.tz_convert("UTC").astype("datetime64[ns, UTC]").astype("int64") // 1_000_000).to_numpy(np.int64)
    if pd.api.types.is_integer_dtype(s.dtype):
        return s.to_numpy(np.int64)
    raise ReelError(f"ts must be datetimes or integer ms, got {s.dtype}")


def _window(df5m_closed) -> Optional[tuple]:
    """(window frame, ms open times) of the last WINDOW bars; None when the frame is shorter or a price inside the
    window is not finite. Raises ReelError for a malformed frame."""
    if not isinstance(df5m_closed, pd.DataFrame):
        raise ReelError(f"expected a DataFrame of closed 5m bars, got {type(df5m_closed).__name__}")
    missing = [k for k in ("ts", "open", "high", "low", "close") if k not in df5m_closed.columns]
    if missing:
        raise ReelError(f"5m frame without {missing}")
    n = len(df5m_closed)
    if n < WINDOW:
        return None
    w = df5m_closed.iloc[n - WINDOW:]
    ts = _ms(w["ts"])
    d = np.diff(ts)
    if (d <= 0).any() or (d % FIVE_MS).any() or ts[-1] % FIVE_MS:
        raise ReelError("5m bars are not oldest first on the 5m grid (unsorted, duplicated or off-grid open times)")
    cols = {k: pd.to_numeric(w[k], errors="coerce").to_numpy(np.float64) for k in ("open", "high", "low", "close")}
    if not all(np.isfinite(a).all() for a in cols.values()):
        return None
    frame = pd.DataFrame({"ts": pd.to_datetime(ts, unit="ms", utc=True), **cols})
    frame.attrs["tf"] = REEL_TF
    return frame, ts


def _indicators(R, frame: pd.DataFrame) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return R.indicators(frame)


def _levels(ind: dict, ts: np.ndarray, swing_low: float, stop: float) -> Optional[dict]:
    """The dict ``signal`` / ``flip_levels`` return for the window's last bar s, or None when ATR14 or the upper band
    of bar s is not usable."""
    s = len(ts) - 1
    atr14, up = float(ind["atr"][s]), float(ind["upper"][s])
    if not (np.isfinite(atr14) and atr14 > 0 and np.isfinite(up)):
        return None
    if not (np.isfinite(swing_low) and np.isfinite(stop)):
        return None
    closes = [float(x) for x in ind["c"][s - (BB_LEN - 2):s + 1]]
    return {"side": 1, "bar_open": int(ts[s]), "atr14": atr14, "swing_low": float(swing_low), "stop": float(stop),
            "up_band": up, "closes": closes}


# ------------------------------------------------------------------ the interface
def signal(df5m_closed) -> Optional[dict]:
    """H1 on the closed 5m bars of one coin (a DataFrame with ts / open / high / low / close, oldest first, the
    forming bar already dropped; the last row is the signal candidate s). Only the last config.REEL_WINDOW_5M rows are
    used.

    None when bar s is not a signal (or the window is short / not finite, or ATR14 / the band of s is NaN). Else
    {"side": +1, "bar_open": ms of bar s, "atr14": ATR14 of bar s, "swing_low": lowest low from the first breach bar
    through s, "stop": swing_low - 0.05 x atr14, "up_band": the upper band of bar s (the first target), "closes": the
    closes of bars s-18..s (19 floats, oldest first)}. Raises ``ReelError`` (never another exception)."""
    try:
        R = _load()
        win = _window(df5m_closed)
        if win is None:
            return None
        frame, ts = win
        n = len(ts)
        ind = _indicators(R, frame)
        # one NaN entry after bar s: simulate needs the entry bar s+1; a NaN bar neither arms nor signals, and the
        # target simulate reads for it (the previous bar's upper band) is the upper band of bar s
        pad = {k: np.r_[np.asarray(v, dtype=np.float64), np.nan] for k, v in ind.items()}
        P = R.Prep(pad, *H1_SETTINGS)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _trades, sigs, _skips = R.simulate(P, _NO_COST, 0, n + 1, "open", False)
        if not sigs or int(sigs[-1]["signal_idx"]) != n - 1:
            return None
        sg = sigs[-1]
        if int(sg["side"]) != 1:
            raise ReelError(f"lib_reel5m gave side {sg['side']} for H1 (long only)")
        out = _levels(ind, ts, float(sg["extreme"]), float(sg["stop_px"]))
        if out is not None and float(sg["target0"]) != out["up_band"]:
            raise ReelError(f"first target {sg['target0']!r} != upper band of bar s {out['up_band']!r}")
        return out
    except ReelError:
        raise
    except Exception as exc:  # noqa: BLE001  nothing but ReelError leaves the wrapper
        raise ReelError(f"reel signal failed: {type(exc).__name__}: {exc}"[:400]) from None


def flip_levels(df5m_closed) -> Optional[dict]:
    """The entry levels of a 5m coin flip on the same frame as ``signal`` (owners' D4: long-only, the reel's exits):
    the same dict as ``signal`` with "swing_low" = the lowest low of the last 12 closed 5m bars (s-11..s) and
    "stop" = swing_low - 0.05 x atr14. None when the frame is too short or an indicator is NaN. Raises ``ReelError``."""
    try:
        R = _load()
        win = _window(df5m_closed)
        if win is None:
            return None
        frame, ts = win
        ind = _indicators(R, frame)
        swing = float(np.min(ind["l"][-FLIP_LOOKBACK:]))
        return _levels(ind, ts, swing, swing - STOP_BUF_ATR * float(ind["atr"][-1]))
    except ReelError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ReelError(f"reel flip levels failed: {type(exc).__name__}: {exc}"[:400]) from None


# ------------------------------------------------------------------ command line
def _synthetic(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.standard_t(3, n) * 0.0015))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, n)))
    t0 = 1_767_225_600_000
    return pd.DataFrame({"ts": t0 + FIVE_MS * np.arange(n, dtype=np.int64), "open": o, "high": h, "low": lo,
                         "close": c, "volume": 1.0})


def _bench(bars_dir: Optional[str], reps: int) -> dict:
    frames = {}
    for coin in ("btcusd", "ethusd", "solusd", "dogeusd", "ltcusd", "bchusd"):
        p = os.path.join(bars_dir, f"{coin}-5m.csv.gz") if bars_dir else ""
        if p and os.path.exists(p):
            df = pd.read_csv(p).iloc[-(WINDOW + 200):].reset_index(drop=True)
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            frames[coin] = df
        else:
            frames[coin] = _synthetic(WINDOW + 200, seed=len(frames))
    verify()
    out = {}
    for name, fn in (("signal", signal), ("flip_levels", flip_levels)):
        times = []
        for _ in range(reps):
            for df in frames.values():
                t = time.perf_counter()
                fn(df)
                times.append(time.perf_counter() - t)
        out[name] = {"median_ms": round(1000 * float(np.median(times)), 2),
                     "max_ms": round(1000 * float(np.max(times)), 2), "calls": len(times)}
    out["window"] = WINDOW
    out["bars"] = "real" if bars_dir else "synthetic"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.reelsig")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify")
    b = sub.add_parser("bench")
    b.add_argument("--bars-dir", default=None)
    b.add_argument("--reps", type=int, default=5)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "verify":
            print(json.dumps(verify(), indent=1))
        else:
            print(json.dumps(_bench(a.bars_dir, a.reps), indent=1))
    except ReelUnavailable as exc:
        print(f"REEL UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
