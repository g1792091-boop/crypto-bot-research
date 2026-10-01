"""Live signals of the new-strategy accounts (``NL<n>@<tf>``, docs/extra-accounts.md).

A new-strategy account runs a strategy of the new-strategy lab's grammar (docs/newlab-prereg.md) with
the paper v3 exits, sizing and costs. Its entry signal is ``newlab_signals.signals_for_frame`` on the
same chart bars the lab tested on, computed here at every boundary where its timeframe closes:

- In the live runner's own process (no pool, no threads) and only at live boundaries, after the 195's
  work at that boundary was committed (paperbot/extras.py, hook phase 2), under a wall-time budget:
  before each (coin, timeframe) job the deadline is checked and systemd's watchdog is pinged; jobs
  past the deadline are skipped and counted.
- From the signal service's 5m history (``service.hist``, read only): the last ``NEWLAB_WINDOW_5M[tf]``
  5m bars. Zero-volume bars are handled as the lab cache handles them (research/binance_data/build.py
  ``drop_no_trade``): 5m drops 5m rows with volume <= 0; 30m is resampled from the dropped 5m; 15m, 1h
  and 4h are resampled from the undropped 5m (equal to the native klines) and then lose the bars whose
  summed volume is <= 0. Frames come from ``recorder.build_frames`` with the hash-checked library (the
  bar still forming and a partial first bin are dropped, as for the 195 and the lab).
- Window lengths (EMA200 residual on the seed below e^-22 everywhere, RMA14 below e^-170; finite windows
  are exact) and the warm-up below which an account is not ready yet: ``NEWLAB_WINDOW_5M`` and
  ``NEWLAB_MIN_BARS``. Readiness is reported, never asserted.
- ``newlab_signals`` (and scipy with it) is imported only when the first new-strategy account exists.
  The code that makes the signals is pinned per account (``code_pin``: newlab_signals.py, context.py,
  recorder.py and the locked library's PREREG hash); paperbot/extras.py compares the pin at start.

Everything returned is plain Python (ints, floats, strings, dicts), so it can go into the state JSON.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Callable, Optional

import numpy as np
import pandas as pd

from .aggregate import TF_MS
from .config import V3_STOP_ATR
from .health import sd_notify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADE_TFS = ("5m", "15m", "30m", "1h", "4h")
FIVE = TF_MS["5m"]

# 5m bars per job (tf bars: 6,000 / 6,000 / 8,000 / 4,000 / 2,400) and the bars needed to be ready
NEWLAB_WINDOW_5M = {"5m": 6_000, "15m": 18_000, "30m": 48_000, "1h": 48_000, "4h": 115_200}
NEWLAB_MIN_BARS = {"5m": 5_900, "15m": 5_900, "30m": 7_900, "1h": 3_950, "4h": 2_350}

# files whose code makes a new-strategy account's signals (the pin), besides the locked library
PIN_FILES = {"newlab_signals": "paperbot/agents/newlab_signals.py", "context": "paperbot/context.py",
             "recorder": "paperbot/recorder.py"}
PIN_KEYS = ("newlab_signals", "context", "recorder", "lib")


def file_sha(rel: str, root: str = ROOT) -> Optional[str]:
    p = os.path.join(root, rel)
    try:
        with open(p, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def code_pin(root: str = ROOT) -> dict:
    """{"newlab_signals", "context", "recorder": sha256 of the file, "lib": the locked library's
    PREREG.sha256 hash (sweepsig.verify)}."""
    from . import sweepsig
    out = {k: file_sha(rel, root) for k, rel in PIN_FILES.items()}
    out["lib"] = sweepsig.verify()["prereg_sha256_file"]
    return out


def pin_text(pin: Optional[dict]) -> str:
    """Short form for alerts and ``accept_code`` in extras.json: '<first 12 of each hash>' joined by '-'."""
    if not isinstance(pin, dict):
        return "none"
    return "-".join(str(pin.get(k) or "none")[:12] for k in PIN_KEYS)


def _df5(rows) -> pd.DataFrame:
    a = np.asarray(rows, dtype=float).reshape(-1, 6)
    return pd.DataFrame({"ts": pd.to_datetime(a[:, 0].astype(np.int64), unit="ms", utc=True), "open": a[:, 1],
                         "high": a[:, 2], "low": a[:, 3], "close": a[:, 4], "volume": a[:, 5]})


def lab_frame(lib, df5: pd.DataFrame, tf: str) -> pd.DataFrame:
    """The ``tf`` chart bars of a 5m window with the lab cache's zero-volume rules (module docstring)."""
    from .recorder import build_frames
    if tf in ("5m", "30m"):
        keep = ~(df5["volume"].to_numpy(float) <= 0)          # NaN volume (unknown) is kept, as the lab keeps it
        d = df5.loc[keep].reset_index(drop=True)
        if not len(d):
            return d
        return build_frames(lib, d, [tf])[tf]
    df = build_frames(lib, df5, [tf])[tf]
    keep = ~(df["volume"].to_numpy(float) <= 0)
    out = df.loc[keep].reset_index(drop=True)
    out.attrs["tf"] = tf
    return out


def compute_newlab(lib, signals_for_frame: Callable, symbol: str, tf: str, boundary: int, rows,
                   specs: list[tuple[str, dict]], min_bars: int) -> dict:
    """One (coin, timeframe) job: the side of every registered spec on the bar that closes at ``boundary``.
    Returns {symbol, tf, ready, why, bars, bar_open, close, atr_last, sides: {aid: int}, ctx, errors}."""
    out: dict = {"symbol": symbol, "tf": tf, "ready": False, "why": None, "bars": 0, "bar_open": None,
                 "close": None, "atr_last": None, "sides": {}, "ctx": None, "errors": []}
    if not len(rows):
        out["why"] = "no history"
        return out
    df5 = _df5(rows)
    df = lab_frame(lib, df5, tf)
    out["bars"] = int(len(df))
    if len(df) < min_bars:
        out["why"] = f"warm-up: {len(df)} bars"
        return out
    span = TF_MS[tf]
    last_open = int(df["ts"].iloc[-1].value // 1_000_000)
    if last_open + span != boundary:
        out["why"] = f"last {tf} bar opens at {last_open}, expected {boundary - span}"
        return out
    atr = lib.fg.atr(df, 14).to_numpy(float)
    sides = {}
    for aid, spec in specs:
        try:
            sides[aid] = int(signals_for_frame(spec, df, atr)[-1])
        except Exception as exc:  # noqa: BLE001  one account's signal error never blocks the others
            sides[aid] = 0
            out["errors"].append(f"{aid}: {type(exc).__name__}: {exc}"[:300])
    a = float(atr[-1]) if len(atr) else float("nan")
    out.update(ready=True, bar_open=last_open, close=float(df["close"].iloc[-1]),
               atr_last=a if np.isfinite(a) and a > 0 else None, sides=sides)
    if any(sides.values()):
        try:
            from .sigservice import chart_context
            out["ctx"] = json.loads(json.dumps(chart_context(lib, symbol, df5, df, tf)))
        except Exception as exc:  # noqa: BLE001  the chart description never blocks a signal
            out["ctx_error"] = f"{type(exc).__name__}: {exc}"[:300]
    return out


class NewlabSignals:
    """The new-strategy accounts' signal source (module docstring)."""

    def __init__(self, service, windows: Optional[dict] = None, min_bars: Optional[dict] = None,
                 stop_atr: float = V3_STOP_ATR, clock: Callable[[], float] = time.monotonic, lib=None,
                 notify: Callable[[str], object] = sd_notify):
        self.service = service
        self.windows = dict(NEWLAB_WINDOW_5M if windows is None else windows)
        self.min_bars = dict(NEWLAB_MIN_BARS if min_bars is None else min_bars)
        self.stop_atr = stop_atr
        self.clock = clock
        self.notify = notify
        self._lib = lib
        self.lib = None
        self._ns = None
        self._pin: Optional[dict] = None
        self._why: Optional[str] = None
        self.specs: dict[str, tuple[str, str, dict]] = {}
        self.jobs = 0
        self.budget_skips = 0

    # ------------------------------------------------------------ code
    def available(self) -> tuple[bool, Optional[str]]:
        """Import newlab_signals (and the hash-checked library) once and pin the code; (False, why) when
        that fails (the accounts are then suspended, never the runner)."""
        if self._ns is not None:
            return True, None
        if self._why is not None:
            return False, self._why
        try:
            from . import sweepsig
            from .agents import newlab_signals as ns
            lib = self._lib if self._lib is not None else sweepsig.lib()
            pin = code_pin()
        except Exception as exc:  # noqa: BLE001  import errors, a changed locked library ...
            self._why = f"{type(exc).__name__}: {exc}"[:300]
            return False, self._why
        self._ns, self.lib, self._pin = ns, lib, pin
        return True, None

    def pin(self) -> dict:
        """The code pin taken when the code was imported (``available`` first)."""
        return dict(self._pin or {})

    # ------------------------------------------------------------ accounts
    def maxlen(self) -> int:
        lens = [h.maxlen for h in self.service.hist.values() if getattr(h, "maxlen", None)]
        return min(lens) if lens else 0

    def register(self, aid: str, name: str, tf: str, spec: dict) -> Optional[str]:
        """None when ``aid`` will be computed; else why not (code unavailable, window longer than the
        history the signal service keeps)."""
        ok, why = self.available()
        if not ok:
            return f"새 매매법 코드를 불러오지 못함: {why}"
        if tf not in self.windows:
            return f"timeframe {tf} not supported"
        if self.windows[tf] > self.maxlen():
            return f"5분봉 {self.windows[tf]:,}개가 필요한데 기록은 {self.maxlen():,}개까지 (warm-up 부족)"
        self.specs[aid] = (name, tf, spec)
        return None

    def unregister(self, aid: str) -> None:
        self.specs.pop(aid, None)

    def tfs(self) -> list[str]:
        return [tf for tf in TRADE_TFS if any(t == tf for _, t, _ in self.specs.values())]

    def due(self, boundary: int) -> list[str]:
        return [tf for tf in self.tfs() if boundary % TF_MS[tf] == 0]

    # ------------------------------------------------------------ compute
    def compute(self, boundary: int, due: list[str], deadline: float) -> tuple[list[dict], list[str]]:
        """Jobs for the timeframes in ``due`` with registered accounts, one per (coin, timeframe), until
        ``deadline`` (monotonic seconds). Returns (job results, skipped "<symbol>@<tf>")."""
        results: list[dict] = []
        skipped: list[str] = []
        if self._ns is None:
            return results, skipped
        for tf in TRADE_TFS:
            if tf not in due:
                continue
            specs = [(aid, spec) for aid, (_n, t, spec) in self.specs.items() if t == tf]
            if not specs:
                continue
            n = self.windows[tf]
            for sym in self.service.trade_symbols:
                if self.clock() >= deadline:
                    skipped.append(f"{sym}@{tf}")
                    self.budget_skips += 1
                    continue
                self.notify("WATCHDOG=1")
                rows = list(self.service.hist[sym])[-n:]
                results.append(compute_newlab(self.lib, self._ns.signals_for_frame, sym, tf, boundary, rows,
                                              specs, self.min_bars[tf]))
                self.jobs += 1
        return results, skipped
