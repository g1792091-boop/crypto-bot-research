"""Live signals for the paper run (docs/paper-v3-rules.md; paper v4: docs/paper-v4-rules.md).

At every 5m boundary the service holds the closed 5m bars of every coin. For each core timeframe that closes at
that boundary it builds the chart bars with the backtest's ``resample_ohlcv`` (``recorder.build_frames``, forming
bar dropped), runs the locked ``compute_signals`` for all strategies and keeps the signal of the bar that just
closed.

- Core timeframes (config.V3_TRADE_TFS: 15m, 30m, 1h, 4h; 5m was removed for the core group on 2026-10-04,
  docs/paper-v3-rules-change-1.md, and never enters this tuple) and coins (six): one Signal per strategy account,
  stop distance 2 x ATR14 of the signal bar, reference price = best ask (long) or best bid (short) right after the
  computation. The engine adds slippage.
- Coin-flip accounts: per timeframe, coin and bar a seeded draw with the rate fixed in
  research/paper_rules/out/summary.json.
- Daily bars and XRP: signals are logged only (status RECORD).
- A signal ready more than ``max_delay_ms`` after its bar closed (catch-up after a restart) is logged as LATE and
  not traded.

Indicators run on a trailing window of 2 x warm-up bars per timeframe; the replay check in
research/paper_rules/parity_live.py compares this with the full-history backtest signals.

When a strategy signals, the worker also records descriptive entry marks (entry_marks.py: support / resistance and
the strategy's entry strength, as measured by research/entry_study, which found no edge in them) into each signal's
``ctx``. Where the levels need more history than the signal window (4h), the job carries the older 5m bars
separately; the signal frame is the same either way.

Paper v4 groups (config.V4_GROUPS; switched on by the runner, ``ds_tfs`` / ``five_m``; a service built without them
is exactly the v3 service). The core path above (``compute``, ``compute_last``, ``_jobs``, ``_map``, ``_random``) is
unchanged: tests/test_sigservice_v4.py recomputes the v3 rows captured before this edit
(tests/data/v3_locked_signals.json) and requires them byte-identical.

- DeepSeek-200 (group "ds200", ``compute_ds``): the definitions of ``dssig.defs_for(tf)`` on 15m / 30m / 1h / 4h,
  a separate Pool map (``ds_last``, the worker that never raises) submitted AFTER the core map of every due
  timeframe, with its own timeout (``ds_timeout_s``, 60 s) and error class (``DsTimeout``). Windows
  config.DS_WINDOW_5M; each non-BTC job carries BTC's bars of the same boundary for F14_SMT (the last
  (dssig.BTC_TF_BARS + 2) chart bars' worth, all F14 reads; tests check the frames equal the full window's). House
  exits as the core group (stop distance 2 x ATR14 of the DeepSeek frame's signal bar). XRP is never computed.
- 5m path (``compute_5m``, run FIRST at every 5m boundary, in this process, never through the Pool): the reel
  REEL_H1@5m (``reelsig.signal`` on the last config.REEL_WINDOW_5M closed 5m bars) and the 5m coin flips
  RANDOM_k@5m (config.V4_FLIP5M: long only, a seeded draw per coin and bar from the stream
  [seed, 5, coin index, bar close in minutes], fire when the first draw < rate; levels ``reelsig.flip_levels``).
  Both carry the reel's exit basis to paperbot/reel_engine.py: absolute ``stop_price``, ``tp_price`` = the upper
  band of the signal bar, ``meta["reel"]`` = {stop, swing_low, atr14, up_band, closes (19), bar_open}, no
  "stop_dist". LATE after config.FIVE_M_MAX_DELAY_MS (60 s, owners' D16).
- A group's code that fails its pins (``verify_groups`` at start, or later in a worker) is refused: that group's
  signals stop, the others run on, and the runner sends one CRITICAL line (``pop_refusals``). Every error of these
  paths is caught inside them or by the runner's fence: nothing they do can stop the core group's submits. The
  DeepSeek map starts only after them, so it never delays them; the 5m path runs before them, in this process, and
  costs them its compute time (measured on the real bars, 2026-10-05: about 0.12 s at a boundary without a 5m
  signal, plus about 0.1 s per coin with one for its chart context; 0.83 s with all six coins signalling).
- signal_log rows of the v4 groups carry data["group"] ("ds200", "reel", "flip"); the core rows are unchanged.
  DeepSeek rows: strategy = the definition id, timeframe, symbol = the Binance symbol (BTCUSDT), side +1 / -1,
  bar_close = the boundary; one row per definition that fired on a coin the job answered for, whatever the account's
  position (statuses SUBMITTED / LATE / NO_PRICE / NO_ATR); paperbot/dscheck.py recomputes them. Which coins the job
  answered for at each boundary: live3's "dsrun:<day>" state record.
- chart context (G10): a DeepSeek row and a 5m row (reel, 5m coin flip) carry the chart context of their coin's
  signal bar in data["ctx"] and in the Signal's meta["ctx"], as a core row does (loss cards, 진입 순간, the
  market-condition maps), with the support / resistance marks of its side (ctx["sr"], entry_marks; the loss cards'
  S/R tags read them). DeepSeek: computed in the DeepSeek worker by ``chart_context`` and ``entry_marks.marks`` on the
  core group's frames of that timeframe, so it equals the ctx of a core row of the same coin, timeframe, bar and
  side (``_group_ctx``); 5m: on the reel window's 5m bars (higher timeframe 30m). Only for a coin with a signal.
  Never strength numbers (ctx["strength"]): no strength definition exists for the v4 groups, so their leverage group
  stays "normal". A failure leaves the part that failed out (data["ctx_error"] for the chart context, ctx
  ["marks_error"] for the marks); it never blocks a signal.
- alert texts: frozen below (``DS_TIMEOUT_TEXT`` and the rest, with patterns for their readers).
"""

from __future__ import annotations

import importlib
import itertools
import warnings
from collections import deque
from multiprocessing import Pool, TimeoutError as PoolTimeout
from typing import Callable, Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from . import sweepsig
from .aggregate import TF_MS
from .config import (DS200_DEFS, DS_WINDOW_5M, FIVE_M_MAX_DELAY_MS, REEL_NAME, REEL_TF, REEL_WINDOW_5M,
                     V3_RANDOM_SEEDS, V3_TRADE_TFS)
from .models import Bar, Signal

TRADE_TFS = V3_TRADE_TFS
RECORD_TFS = ("1d",)
FIVE = TF_MS["5m"]
DOGE_PARTS = ("DOGE_L", "DOGE_S")

_LIB = None


def _lib():
    global _LIB
    if _LIB is None:
        _LIB = sweepsig.lib()
    return _LIB


def strategy_names(lib) -> list[str]:
    """The 36 account strategies: every locked strategy, DOGE_L and DOGE_S joined as DOGE."""
    return [n for n in lib.NAMES if n not in DOGE_PARTS] + ["DOGE"]


def doge_join(long_part, short_part):
    """The friend's DOGE bot as one long/short account.

    The locked compute_signals returns long - short per registry entry, so DOGE_L is +1 on its
    long bars and DOGE_S is ALREADY -1 on its short bars (sweep_lib.doge_short returns
    (zeros, short)). The account side is therefore their SUM: +1 long, -1 short, 0 when both
    fire on the same bar. (Until 2026-09-30 this was DOGE_L - DOGE_S, which turned every short
    signal into a long; found by the entry study, research/entry_study.)
    Works on ints and on int arrays."""
    return np.sign(np.asarray(long_part, dtype=np.int16) + np.asarray(short_part, dtype=np.int16)).astype(np.int8)


def window_5m(lib, tf: str) -> int:
    """5m bars kept for a timeframe: two warm-ups plus a few bars of slack."""
    per = lib.tf_minutes(tf) // 5
    return int((2 * lib.warmup_bars(tf) + 3) * per)


def compute_last(job: tuple) -> dict:
    """Worker: signals of the TF bar that closes at ``boundary`` for one coin.
    ``job[9]``, when present, holds older 5m bars (ts, o, h, l, c, v) for the entry marks only."""
    symbol, tf, boundary, ts, o, h, l, c, v = job[:9]
    from .recorder import build_frames
    lib = _lib()
    df5 = pd.DataFrame({"ts": pd.to_datetime(ts, unit="ms", utc=True), "open": o, "high": h,
                        "low": l, "close": c, "volume": v})
    df = build_frames(lib, df5, [tf])[tf]
    span = TF_MS[tf]
    out = {"symbol": symbol, "tf": tf, "ready": False, "errors": []}
    if len(df) <= lib.warmup_bars(tf):
        out["why"] = f"warm-up: {len(df)} bars"
        return out
    last_open = int(df["ts"].iloc[-1].value // 1_000_000)
    if last_open + span != boundary:
        out["why"] = f"last {tf} bar opens at {last_open}, expected {boundary - span}"
        return out
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sigs = lib.compute_signals({symbol: df}, tf, list(lib.NAMES), strict=False)
    out["errors"] = [str(w.message)[:300] for w in caught if str(w.message).split(" ", 1)[0] in lib.NAMES]
    sides = {}
    for n in lib.NAMES:
        arr = sigs.get(n, {}).get(symbol)
        sides[n] = int(arr[-1]) if arr is not None else 0
    sides["DOGE"] = int(doge_join(sides.pop("DOGE_L", 0), sides.pop("DOGE_S", 0))) if "DOGE_L" in sides else 0
    atr = lib.fg.atr(df, 14).to_numpy(float)[-1]
    out.update(ready=True, bar_open=last_open, close=float(df["close"].iloc[-1]),
               atr=float(atr) if np.isfinite(atr) else None, sides=sides)
    if any(sides.values()):
        try:
            out["ctx"] = chart_context(lib, symbol, df5, df, tf)
        except Exception as exc:  # the chart description must never block a signal
            out["ctx_error"] = f"{type(exc).__name__}: {exc}"[:300]
        try:
            from .entry_marks import marks
            pre = job[9] if len(job) > 9 else None
            out["marks"] = marks(df, tf, sides, _marks_frame(lib, pre, df5, df, tf) if pre is not None else None)
        except Exception as exc:  # descriptions only: never block a signal
            out["marks"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    return out


def _marks_frame(lib, pre: tuple, df5: pd.DataFrame, df: pd.DataFrame, tf: str) -> Optional[pd.DataFrame]:
    """The chart bars of the older 5m bars plus the signal window, ending at the same bar as
    ``df`` (None when they do not, so the marks fall back to ``df``)."""
    from .recorder import build_frames
    pts = np.asarray(pre[0], dtype=np.int64)
    keep = pts < int(df5["ts"].iloc[0].value // 1_000_000)
    old = pd.DataFrame({"ts": pd.to_datetime(pts[keep], unit="ms", utc=True), "open": pre[1][keep],
                        "high": pre[2][keep], "low": pre[3][keep], "close": pre[4][keep], "volume": pre[5][keep]})
    if not len(old):
        return None
    long = build_frames(lib, pd.concat([old, df5], ignore_index=True), [tf])[tf]
    return long if len(long) and long["ts"].iloc[-1] == df["ts"].iloc[-1] else None


def _bars(df: pd.DataFrame, symbol: str, tf: str) -> list[Bar]:
    ms = df["ts"].astype("int64").to_numpy() // 1_000_000 if str(df["ts"].dtype).startswith("datetime") \
        else df["ts"].to_numpy()
    span = TF_MS[tf]
    return [Bar(symbol, int(t), int(t) + span - 1, float(o), float(h), float(lo), float(c))
            for t, o, h, lo, c in zip(ms, df["open"], df["high"], df["low"], df["close"])]


def chart_context(lib, symbol: str, df5: pd.DataFrame, df: pd.DataFrame, tf: str) -> dict:
    """Chart situation on the signal bar (confirmed bars only), for loss cards and the
    specialists: regime of this and the higher timeframe (context.py), ADX and DI."""
    from .context import HTF, REGIME_N, entry_context
    from .recorder import build_frames
    n = REGIME_N.get(tf, 60)
    bars = _bars(df.iloc[-(n + 60):], symbol, tf)
    htf = HTF.get(tf)
    hbars = []
    if htf:
        h = build_frames(lib, df5, [htf])[htf]
        hbars = _bars(h.iloc[-(REGIME_N.get(htf, 30) + 5):], symbol, htf) if len(h) else []
    ctx = entry_context(tf, bars, hbars)
    adx, pdi, mdi = lib.fg.adx_dmi(df, 14)
    for k, ser in (("adx", adx), ("di_plus", pdi), ("di_minus", mdi)):
        v = float(ser.iloc[-1])
        ctx[k] = v if np.isfinite(v) else None
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in ctx.items()}


def _marks_window(lib, tf: str) -> int:
    """5m bars the entry marks want (entry_marks.marks_window_5m); 0 when unavailable."""
    try:
        from .entry_marks import marks_window_5m
        return marks_window_5m(lib, tf)
    except Exception:  # descriptions only: the service runs without them
        return 0


def attach(ctx: Optional[dict], m: Optional[dict], name: str, side: int) -> Optional[dict]:
    """The signal's ctx with its entry marks (entry_marks.attach); the bar's ctx if that fails."""
    try:
        from .entry_marks import attach as _attach
        return _attach(ctx, m, name, side)
    except Exception as exc:  # descriptions only: never block a signal
        return {**(ctx or {}), "marks_error": f"{type(exc).__name__}: {exc}"[:300]}


class SignalTimeout(RuntimeError):
    pass


# ---------------------------------------------------------------- paper v4 groups
GROUP_MODULES = {"ds200": ".dssig", "reel": ".reelsig"}   # loaded lazily: a broken group module refuses that group only
FLIP_NAMES = tuple(f"RANDOM_{k}" for k in V3_RANDOM_SEEDS)


class DsTimeout(RuntimeError):
    """The DeepSeek map did not answer within ``ds_timeout_s`` (the core group's signals of that boundary are already
    submitted; the pool is replaced). Its message is ``DS_TIMEOUT_HEAD``."""


# The v4 groups' alert texts, FROZEN with this file (it is in the shared hash set and cannot change after day 0; owners'
# G27). Readers match them: notify.Router (Telegram routing), agents/triggers.INCIDENT_ALERTS, paperbot/dscheck.py and
# the dashboards. Every text starts with its group in brackets ("[ds200] ", "[reel] "; never an "[id@tf] " account
# prefix) and none contains "did not answer within" or starts with "signal workers" / "signal error": those are the
# core group's texts (its timeout counter, incident kind and digest count read them) and stay byte-identical.
#   DS_TIMEOUT_TEXT  WARN, alerts + Telegram, once per boundary: the DeepSeek map timed out; the DeepSeek timeframes
#                    from the one that timed out on are skipped at that boundary (counted in health "ds_timeouts")
#   DS_ERROR_TEXT    WARN, alerts only: one coin's DeepSeek job failed or reported a problem (health "ds_errors")
#   DS_FAILED_TEXT   WARN, alerts (Telegram for the first one of a run): the DeepSeek path itself failed at a boundary
#   REEL_ERROR_TEXT  WARN, alerts only: one coin's reel / 5m coin-flip computation failed (health "reel_errors")
#   REEL_FAILED_TEXT WARN, alerts (Telegram for the first one of a run): the 5m path itself failed at a boundary
#   REFUSED_TEXT     CRITICAL, alerts + Telegram, once per group and start: the group's code failed its pins / import
DS_TIMEOUT_HEAD = "[ds200] DeepSeek signal workers timed out after {secs}s"
DS_TIMEOUT_TEXT = DS_TIMEOUT_HEAD + "; DeepSeek signals skipped at {boundary} for {tfs}"
DS_ERROR_TEXT = "[ds200] DeepSeek signal error {tf} {symbol}: {error}"
DS_FAILED_TEXT = "[ds200] DeepSeek signals failed at {boundary} ({error}); the other groups run on"
REEL_ERROR_TEXT = "[reel] 5m signal error {tf} {symbol}: {error}"
REEL_FAILED_TEXT = "[reel] 5m signals (reel and 5m coin flips) failed at {boundary} ({error}); the other groups run on"
REFUSED_TEXT = "[{group}] signal code refused, this group's signals stop (the other groups run on): {why}"
# the same texts as patterns (for the readers above; tests/test_sigservice_v4.py checks each against its text)
DS_TIMEOUT_RE = r"^\[ds200\] DeepSeek signal workers timed out after (\d+)s; DeepSeek signals skipped at (\d+) for (.+)$"
DS_ERROR_RE = r"^\[ds200\] DeepSeek signal error (\S+) (\S+): (.*)$"
DS_FAILED_RE = r"^\[ds200\] DeepSeek signals failed at (\d+) \((.*)\); the other groups run on$"
REEL_ERROR_RE = r"^\[reel\] 5m signal error (\S+) (\S+): (.*)$"
REEL_FAILED_RE = r"^\[reel\] 5m signals \(reel and 5m coin flips\) failed at (\d+) \((.*)\); the other groups run on$"
REFUSED_RE = r"^\[(ds200|reel)\] signal code refused, this group's signals stop \(the other groups run on\): (.*)$"


def ds_names(tf: str) -> list[str]:
    """The DeepSeek definitions traded on ``tf`` in PREREG order (config.DS200_DEFS; = dssig.defs_for, checked by
    ``SignalService.verify_groups``)."""
    return [d for d, _family, tfs in DS200_DEFS if tf in tfs]


def ds_last(job: tuple) -> dict:
    """Pool worker of the DeepSeek group: ``dssig.ds_job`` with every failure returned as a not-ready report, never
    raised, so one coin's error costs no other coin and no other group anything. ``"unavailable": True`` when the
    DeepSeek code itself cannot be used (pins, import): the service then refuses the group."""
    head = {"symbol": job[0], "tf": job[1], "ready": False, "group": "ds200"}
    try:
        dssig = importlib.import_module(GROUP_MODULES["ds200"], __package__)
    except Exception as exc:  # noqa: BLE001
        return {**head, "unavailable": True, "why": "DeepSeek code failed to import",
                "errors": [f"DeepSeek import: {type(exc).__name__}: {exc}"[:300]]}
    try:
        out = dssig.ds_job(job)
    except dssig.DsUnavailable as exc:
        return {**head, "unavailable": True, "why": "DeepSeek pins", "errors": [f"DsUnavailable: {exc}"[:300]]}
    except Exception as exc:  # noqa: BLE001  DsError, or anything else: this coin only
        return {**head, "why": "DeepSeek error", "errors": [f"{type(exc).__name__}: {exc}"[:300]]}
    out["group"] = "ds200"
    if out.get("ready") and any((out.get("sides") or {}).values()):
        _group_ctx(out, job[0], job[1], job[3:9])
    return out


def one_line(text, n: int = 300) -> str:
    """``text`` on one line (newlines and tabs as spaces), at most ``n`` characters: the error part of a v4 alert text,
    so the frozen patterns above always match the whole line."""
    return " ".join(str(text).split())[:n]


def _group_ctx(out: dict, symbol: str, tf: str, cols, lib=None, n: Optional[int] = None) -> None:
    """The descriptions of a v4 group's signal bar into ``out``: ``out["ctx"]`` (``chart_context``) and ``out["marks"]``
    (entry_marks.marks with no strategy: the support / resistance marks of both sides), or ``out["ctx_error"]`` /
    ``out["marks"] = {"error": ...}``. Never raises (descriptions only: they never block a signal). ``cols`` = the 5m
    arrays (ts, o, h, l, c, v) whose last bar closes at the signal boundary.
    DeepSeek (``n`` None): on the core group's frames of ``tf`` (the signal window ``window_5m`` and, where the levels
    need more, the 5m bars of ``_marks_window``, as ``compute_last`` / ``_marks_frame`` build them), so a DeepSeek row
    carries exactly the ctx and the S/R marks a core row of the same coin, timeframe, bar and side carries. The 5m path
    (``n`` = the reel window): on those 5m bars themselves (higher timeframe 30m)."""
    lib = lib or _lib()
    try:
        m = int(n) if n is not None else window_5m(lib, tf)
        df5 = _frame5(cols, m)
        if tf == "5m":
            df = df5
            df.attrs["tf"] = tf
        else:
            from .recorder import build_frames
            df = build_frames(lib, df5, [tf])[tf]
        if not len(df):
            raise ValueError(f"no complete {tf} bar")
        last_open = int(df["ts"].iloc[-1].value // 1_000_000)
        want = out.get("bar_open")
        if want is not None and last_open != int(want):
            raise ValueError(f"context frame ends at {last_open}, the signal bar opens at {want}")
    except Exception as exc:  # noqa: BLE001  the chart description must never block a signal
        out["ctx_error"] = one_line(f"{type(exc).__name__}: {exc}")
        return
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")              # a flat stretch's 0/0 in ADX: a None in ctx, no log line
            out["ctx"] = chart_context(lib, symbol, df5, df, tf)
    except Exception as exc:  # noqa: BLE001
        out["ctx_error"] = one_line(f"{type(exc).__name__}: {exc}")
    try:
        from .entry_marks import marks
        sr_df = None
        mw = _marks_window(lib, tf) if n is None else 0
        if mw > m and len(cols[0]) > m:                  # the core's _marks_frame: the last mw 5m bars, same last bar
            from .recorder import build_frames
            long = build_frames(lib, _frame5(cols, mw), [tf])[tf]
            sr_df = long if len(long) and long["ts"].iloc[-1] == df["ts"].iloc[-1] else None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out["marks"] = marks(df, tf, {}, sr_df)
    except Exception as exc:  # noqa: BLE001
        out["marks"] = {"error": one_line(f"{type(exc).__name__}: {exc}")}


def _frame5(cols, m: int) -> pd.DataFrame:
    """The last ``m`` 5m bars of ``cols`` as compute_last's 5m frame (ts as UTC datetimes)."""
    ts, o, h, lo, c, v = (np.asarray(x)[-m:] for x in cols)
    return pd.DataFrame({"ts": pd.to_datetime(np.asarray(ts, dtype=np.int64), unit="ms", utc=True),
                         "open": np.asarray(o, float), "high": np.asarray(h, float), "low": np.asarray(lo, float),
                         "close": np.asarray(c, float), "volume": np.asarray(v, float)})


class SignalService:
    def __init__(self, trade_symbols: Sequence[str], record_symbols: Sequence[str] = (),
                 random_rates: Optional[dict] = None, seeds: Sequence[int] = V3_RANDOM_SEEDS,
                 stop_atr: float = 2.0, max_delay_ms: int = 180_000, procs: int = 4,
                 trade_tfs: Sequence[str] = TRADE_TFS, record_tfs: Sequence[str] = RECORD_TFS,
                 lib=None, pool=None, timeout_s: float = 120.0,
                 ds_tfs: Sequence[str] = (), ds_timeout_s: float = 60.0, five_m: bool = False,
                 flip5m: Optional[dict] = None, max_delay_ms_5m: int = FIVE_M_MAX_DELAY_MS):
        """``ds_tfs`` (paper v4: config.DS200_TFS) switches the DeepSeek group on for those timeframes, ``five_m`` the
        5m path (the reel and, with ``flip5m`` = config.V4_FLIP5M, the 5m coin flips). Without them the service is
        the v3 service."""
        self.lib = lib or _lib()
        self.trade_symbols = list(trade_symbols)
        self.symbols = self.trade_symbols + [s for s in record_symbols if s not in trade_symbols]
        self.random_rates = dict(random_rates or {})
        self.seeds = tuple(seeds)
        self.stop_atr = stop_atr
        self.max_delay_ms = max_delay_ms
        self.trade_tfs = tuple(trade_tfs)
        self.record_tfs = tuple(record_tfs)
        if REEL_TF in self.trade_tfs:
            raise ValueError("5m never joins the core timeframes: the 5m accounts run on the separate 5m path")
        self.ds_tfs = tuple(ds_tfs)
        bad = [tf for tf in self.ds_tfs if tf not in DS_WINDOW_5M]
        if bad:
            raise ValueError(f"no DeepSeek window for {bad}")
        self.five_m = bool(five_m)
        self.flip5m = dict(flip5m or {})
        if self.flip5m.get("rate") and not self.flip5m.get("long_only", False):
            raise ValueError("the 5m coin flips are long only (they trade the reel's exits)")
        self.max_delay_ms_5m = int(max_delay_ms_5m)
        self.ds_timeout_s = float(ds_timeout_s)
        self.names = strategy_names(self.lib)
        self.ds_names = {tf: ds_names(tf) for tf in self.ds_tfs}
        keep = max([window_5m(self.lib, tf) for tf in self.trade_tfs + self.record_tfs]
                   + [DS_WINDOW_5M[tf] for tf in self.ds_tfs] + ([REEL_WINDOW_5M] if self.five_m else []))
        self.keep = keep
        self.hist = {s: deque(maxlen=keep) for s in self.symbols}
        self.windows = {tf: window_5m(self.lib, tf) for tf in self.trade_tfs + self.record_tfs}
        self.mark_windows = {tf: _marks_window(self.lib, tf) for tf in self.trade_tfs + self.record_tfs}
        self._pool = pool
        self._procs = procs
        self.timeout_s = timeout_s  # a signal later than max_delay_ms is not traded anyway
        self.pool_restarts = 0
        self.ds_timeouts = 0
        self.refused: dict[str, str] = {}      # group -> why its signals are refused (until the next start)
        self._new_refusals: list[tuple[str, str]] = []
        self._mods: dict[str, object] = {}     # group -> its verified signal module
        self._pins: dict[str, dict] = {}       # group -> what its module's verify() returned

    # ------------------------------------------------------------ data
    def add_5m(self, bar: Bar) -> None:
        h = self.hist.get(bar.symbol)
        if h is None:
            return
        if h and bar.open_time <= h[-1][0]:
            return
        h.append((bar.open_time, bar.open, bar.high, bar.low, bar.close,
                  bar.volume if bar.volume is not None else np.nan))

    def bootstrap(self, symbol: str, rows: Iterable[tuple]) -> None:
        """rows: (open_ms, open, high, low, close, volume), oldest first."""
        h = self.hist[symbol]
        for r in rows:
            if not h or r[0] > h[-1][0]:
                h.append(tuple(float(x) if k else int(x) for k, x in enumerate(r)))

    def complete(self, boundary: int) -> bool:
        return all(h and h[-1][0] + FIVE == boundary for h in self.hist.values())

    def due(self, boundary: int) -> list[str]:
        return [tf for tf in self.trade_tfs + self.record_tfs if boundary % TF_MS[tf] == 0]

    # ------------------------------------------------------------ compute
    def _jobs(self, boundary: int, tf: str) -> list[tuple]:
        n = self.windows[tf]
        m = self.mark_windows.get(tf, 0)
        jobs = []
        for s in self.symbols:
            rows = list(self.hist[s])
            a = np.array(rows[-n:], dtype=float)
            job = (s, tf, boundary, a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])
            if m > n and len(rows) > n:   # older bars for the entry marks only (the signal window is above)
                p = np.array(rows[-m:-n], dtype=float)
                job += ((p[:, 0].astype(np.int64), p[:, 1], p[:, 2], p[:, 3], p[:, 4], p[:, 5]),)
            jobs.append(job)
        return jobs

    def _map(self, jobs):
        if self._procs <= 1:
            return [compute_last(j) for j in jobs]
        if self._pool is None:
            self._pool = Pool(self._procs)
        try:
            return self._pool.map_async(compute_last, jobs).get(self.timeout_s)
        except PoolTimeout:
            # a hung worker would otherwise block every account forever: kill the
            # pool (a fresh one is made on the next call) and let the caller skip
            self._pool.terminate()
            self._pool.join()
            self._pool = None
            self.pool_restarts += 1
            raise SignalTimeout(f"signal workers did not answer within {self.timeout_s:.0f}s")

    def compute(self, boundary: int, tf: str, now_ms: Callable[[], int],
                book: Callable[[], dict]) -> tuple[list[dict], list[tuple[str, Signal]], list[dict]]:
        """Signals for ``tf`` bars closing at ``boundary``.
        Returns (signal_log rows, [(account_id, Signal)], per-coin worker reports)."""
        results = self._map(self._jobs(boundary, tf))
        ready_at = now_ms()
        prices = book() if tf in self.trade_tfs else {}
        delay = ready_at - boundary
        trade_tf = tf in self.trade_tfs
        rows, subs = [], []
        for r in results:
            if not r["ready"]:
                continue
            sym = r["symbol"]
            tradable = trade_tf and sym in self.trade_symbols
            draws = self._random(boundary, tf, sym) if tradable else {}
            items = [(n, r["sides"].get(n, 0)) for n in self.names] + list(draws.items())
            for name, side in items:
                if not side:
                    continue
                bid, ask = prices.get(sym, (None, None))
                ref = (ask if side > 0 else bid) if tradable else None
                if not tradable:
                    status = "RECORD"
                elif delay > self.max_delay_ms:
                    status = "LATE"
                elif ref is None or r["atr"] is None:
                    status = "NO_PRICE" if ref is None else "NO_ATR"
                else:
                    status = "SUBMITTED"
                ctx = attach(r.get("ctx"), r.get("marks"), name, side)   # + this signal's entry marks
                rows.append({"bar_close": boundary, "timeframe": tf, "strategy": name, "symbol": sym,
                             "side": int(side), "atr": r["atr"], "ref_price": ref, "ref_time": ready_at,
                             "delay_ms": delay, "status": status,
                             "data": {"close": r["close"], "bid": bid, "ask": ask, "ctx": ctx}})
                if status == "SUBMITTED":
                    aid = f"{name}@{tf}"
                    subs.append((aid, Signal(
                        ts=boundary - 1, symbol=sym, timeframe=tf, strategy_id=name, side=int(side),
                        stop_price=0.0, tier="best", atr=r["atr"],
                        meta={"stop_dist": self.stop_atr * r["atr"], "ref_price": ref,
                              "ref_time": ready_at, "delay_ms": delay, "account": aid,
                              "ctx": ctx or {}})))
        return rows, subs, results

    def _random(self, boundary: int, tf: str, sym: str) -> dict:
        p = self.random_rates.get(tf)
        if not p:
            return {}
        out = {}
        k = self.trade_symbols.index(sym)
        for seed in self.seeds:
            rng = np.random.default_rng([seed, TF_MS[tf] // 60_000, k, boundary // 60_000])
            fire, coin = rng.random(), rng.random()
            if fire < p:
                out[f"RANDOM_{seed}"] = 1 if coin < 0.5 else -1
        return out

    # ------------------------------------------------------------ paper v4 groups
    def groups_on(self) -> list[str]:
        return (["ds200"] if self.ds_tfs else []) + (["reel"] if self.five_m else [])

    def _refuse(self, group: str, why: str) -> None:
        if group not in self.refused:
            self.refused[group] = str(why)[:300]
            self._new_refusals.append((group, self.refused[group]))

    def pop_refusals(self) -> list[tuple[str, str]]:
        """Groups refused since the last call, as (group, why): the runner sends one CRITICAL line for each."""
        out, self._new_refusals = self._new_refusals, []
        return out

    def _module(self, group: str):
        """The group's verified signal module (dssig / reelsig), or None when the group is refused. The first call
        imports it and checks its pins (``verify``); any failure refuses the group."""
        if group in self.refused:
            return None
        mod = self._mods.get(group)
        if mod is None:
            try:
                mod = importlib.import_module(GROUP_MODULES[group], __package__)
                self._pins[group] = mod.verify()
                if group == "ds200":
                    for tf in self.ds_tfs:
                        if list(mod.defs_for(tf)) != self.ds_names[tf]:
                            raise ValueError(f"dssig.defs_for({tf}) differs from config.DS200_DEFS")
            except Exception as exc:  # noqa: BLE001  this group only
                self._refuse(group, f"{type(exc).__name__}: {exc}")
                return None
            self._mods[group] = mod
        return mod

    def verify_groups(self) -> dict:
        """Check the pins of every switched-on v4 group at start (dssig.verify, reelsig.verify). Returns
        {group: the module's verify() result, or {"refused": why}} for the run record; a refused group is also queued
        for ``pop_refusals``."""
        out = {}
        for g in self.groups_on():
            mod = self._module(g)
            out[g] = dict(self._pins[g]) if mod is not None else {"refused": self.refused.get(g)}
        return out

    def due_5m(self, boundary: int) -> bool:
        return self.five_m and boundary % FIVE == 0

    def due_ds(self, boundary: int) -> list[str]:
        return [tf for tf in self.ds_tfs if boundary % TF_MS[tf] == 0]

    def _arrays(self, symbol: str, n: int) -> Optional[np.ndarray]:
        """The last ``n`` 5m rows of ``symbol`` (ts, o, h, l, c, v) as one float array (None when there are none)."""
        h = self.hist[symbol]
        rows = list(itertools.islice(h, max(0, len(h) - n), None))
        return np.array(rows, dtype=float) if rows else None

    # ---- DeepSeek
    def _ds_jobs(self, boundary: int, tf: str) -> list[tuple]:
        n = DS_WINDOW_5M[tf]
        per = TF_MS[tf] // FIVE
        mod = self._mods.get("ds200")
        btc_rows = (int(getattr(mod, "BTC_TF_BARS", 100)) + 2) * per   # F14 reads the last BTC_TF_BARS chart bars only
        btc = None
        if "BTCUSDT" in self.hist:
            b = self._arrays("BTCUSDT", min(n, btc_rows))
            if b is not None:
                btc = (b[:, 0].astype(np.int64), b[:, 1], b[:, 2], b[:, 3], b[:, 4], b[:, 5])
        jobs = []
        for s in self.trade_symbols:
            a = self._arrays(s, n)
            if a is None:
                continue
            jobs.append((s, tf, boundary, a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5],
                         None if s == "BTCUSDT" else btc))
        return jobs

    def _ds_map(self, jobs):
        if self._procs <= 1:
            return [ds_last(j) for j in jobs]
        if self._pool is None:
            self._pool = Pool(self._procs)
        try:
            return self._pool.map_async(ds_last, jobs).get(self.ds_timeout_s)
        except PoolTimeout:
            self._pool.terminate()
            self._pool.join()
            self._pool = None
            self.pool_restarts += 1
            self.ds_timeouts += 1
            raise DsTimeout(DS_TIMEOUT_HEAD.format(secs=f"{self.ds_timeout_s:.0f}"))

    def compute_ds(self, boundary: int, tf: str, now_ms: Callable[[], int],
                   book: Callable[[], dict]) -> tuple[list[dict], list[tuple[str, Signal]], list[dict]]:
        """The DeepSeek signals of the ``tf`` bars closing at ``boundary``: (signal_log rows, [(account_id, Signal)],
        per-coin reports), as ``compute``. Nothing when the group is refused or ``tf`` is not a DeepSeek timeframe.
        Raises only ``DsTimeout``."""
        if tf not in self.ds_tfs or self._module("ds200") is None:
            return [], [], []
        results = self._ds_map(self._ds_jobs(boundary, tf))
        for r in results:
            if r.get("unavailable"):
                self._refuse("ds200", "; ".join(r.get("errors") or [r.get("why", "unavailable")]))
        if "ds200" in self.refused:
            return [], [], results
        ready_at = now_ms()
        prices, price_error = _prices(book)
        delay = ready_at - boundary
        rows, subs = [], []
        if price_error:
            results = list(results) + [{"symbol": "*", "tf": tf, "ready": False, "errors": [price_error],
                                        "group": "ds200"}]
        for r in results:
            sym = r.get("symbol")
            if not r.get("ready") or sym not in self.trade_symbols:
                continue
            for name in self.ds_names[tf]:
                side = int((r.get("sides") or {}).get(name, 0))
                if not side:
                    continue
                bid, ask = prices.get(sym, (None, None))
                ref = ask if side > 0 else bid
                atr = r.get("atr")
                if delay > self.max_delay_ms:
                    status = "LATE"
                elif ref is None or atr is None:
                    status = "NO_PRICE" if ref is None else "NO_ATR"
                else:
                    status = "SUBMITTED"
                data = {"close": r.get("close"), "bid": bid, "ask": ask, "ctx": _ctx_of(r, name, side),
                        "group": "ds200"}
                if r.get("ctx_error"):
                    data["ctx_error"] = r["ctx_error"]
                rows.append({"bar_close": boundary, "timeframe": tf, "strategy": name, "symbol": sym,
                             "side": side, "atr": atr, "ref_price": ref, "ref_time": ready_at,
                             "delay_ms": delay, "status": status, "data": data})
                if status == "SUBMITTED":
                    aid = f"{name}@{tf}"
                    subs.append((aid, Signal(
                        ts=boundary - 1, symbol=sym, timeframe=tf, strategy_id=name, side=side,
                        stop_price=0.0, tier="best", atr=atr,
                        meta={"stop_dist": self.stop_atr * atr, "ref_price": ref, "ref_time": ready_at,
                              "delay_ms": delay, "account": aid, "ctx": _ctx_of(r, name, side)})))
        return rows, subs, results

    # ---- the 5m path: the reel and the 5m coin flips
    def _frame_5m(self, symbol: str) -> Optional[pd.DataFrame]:
        a = self._arrays(symbol, REEL_WINDOW_5M)
        if a is None or len(a) < REEL_WINDOW_5M:
            return None
        return pd.DataFrame({"ts": a[:, 0].astype(np.int64), "open": a[:, 1], "high": a[:, 2], "low": a[:, 3],
                             "close": a[:, 4]})

    def _random_5m(self, boundary: int, sym: str) -> dict:
        """{RANDOM_k: +1} of the 5m coin flips that fire for ``sym`` on the 5m bar closing at ``boundary``: the draw
        of ``_random`` (stream [seed, 5, coin index, bar close in minutes], fire when the first draw < rate), long
        only (config.V4_FLIP5M, owners' D4)."""
        p = self.flip5m.get("rate")
        if not p:
            return {}
        out = {}
        k = self.trade_symbols.index(sym)
        for seed in self.seeds:
            rng = np.random.default_rng([seed, FIVE // 60_000, k, boundary // 60_000])
            fire = rng.random()
            if fire < p:
                out[f"RANDOM_{seed}"] = 1
        return out

    def compute_5m(self, boundary: int, now_ms: Callable[[], int],
                   book: Callable[[], dict]) -> tuple[list[dict], list[tuple[str, Signal]], list[dict]]:
        """The 5m accounts' signals of the 5m bar closing at ``boundary`` (REEL_H1@5m, RANDOM_k@5m): (signal_log
        rows, [(account_id, Signal)], per-coin reports), as ``compute``. Never raises: a reel error is reported
        per coin, a refused reel code refuses the 5m group (the reel and its coin flips) only."""
        rows, subs, reports = [], [], []
        if not self.due_5m(boundary):
            return rows, subs, reports
        R = self._module("reel")
        if R is None:
            return rows, subs, reports
        found = []                                    # (symbol, name, group, levels, close)
        for sym in self.trade_symbols:
            rep = {"symbol": sym, "tf": REEL_TF, "ready": False, "errors": [], "group": "reel"}
            reports.append(rep)
            try:
                df = self._frame_5m(sym)
                if df is None:
                    rep["why"] = f"warm-up: {len(self.hist[sym])} of {REEL_WINDOW_5M} 5m bars"
                    continue
                last_open = int(df["ts"].iloc[-1])
                if last_open + FIVE != boundary:
                    rep["why"] = f"last 5m bar opens at {last_open}, expected {boundary - FIVE}"
                    continue
                rep.update(ready=True, bar_open=last_open, close=float(df["close"].iloc[-1]))
                try:
                    lv = R.signal(df)
                except R.ReelUnavailable as exc:
                    self._refuse("reel", f"ReelUnavailable: {exc}")
                    return [], [], reports
                except Exception as exc:  # noqa: BLE001  ReelError: this coin's reel signal only
                    rep["errors"].append(f"reel {type(exc).__name__}: {exc}"[:300])
                    lv = None
                if lv is not None and _levels_ok(lv, last_open):
                    found.append((sym, REEL_NAME, "reel", lv, rep["close"]))
                elif lv is not None:
                    rep["errors"].append(f"reel levels unusable: {lv!r}"[:300])
                draws = self._random_5m(boundary, sym)
                if draws:
                    try:
                        fl = R.flip_levels(df)
                    except R.ReelUnavailable as exc:
                        self._refuse("reel", f"ReelUnavailable: {exc}")
                        return [], [], reports
                    except Exception as exc:  # noqa: BLE001
                        rep["errors"].append(f"flip levels {type(exc).__name__}: {exc}"[:300])
                        fl = None
                    if fl is not None and not _levels_ok(fl, last_open):
                        rep["errors"].append(f"flip levels unusable: {fl!r}"[:300])
                        fl = None
                    for name in sorted(draws):
                        found.append((sym, name, "flip", fl, rep["close"]))
            except Exception as exc:  # noqa: BLE001  never past this coin
                rep["ready"] = False
                rep["errors"].append(f"5m path {type(exc).__name__}: {exc}"[:300])
        if not found:
            return rows, subs, reports
        rep_of = {r["symbol"]: r for r in reports}
        for sym in dict.fromkeys(f[0] for f in found):     # the chart context of each coin with a 5m signal
            try:
                a = self._arrays(sym, REEL_WINDOW_5M)
                cols = (a[:, 0].astype(np.int64),) + tuple(a[:, k] for k in range(1, 6))
            except Exception as exc:  # noqa: BLE001  a description only
                rep_of[sym]["ctx_error"] = one_line(f"{type(exc).__name__}: {exc}")
                continue
            _group_ctx(rep_of[sym], sym, REEL_TF, cols, lib=self.lib, n=REEL_WINDOW_5M)
        ready_at = now_ms()
        prices, price_error = _prices(book)
        if price_error:
            reports.append({"symbol": "*", "tf": REEL_TF, "ready": False, "errors": [price_error], "group": "reel"})
        delay = ready_at - boundary
        for sym, name, group, lv, close in found:
            bid, ask = prices.get(sym, (None, None))
            ref = ask                                 # long only
            if delay > self.max_delay_ms_5m:
                status = "LATE"
            elif lv is None:
                status = "NO_ATR"
            elif ref is None:
                status = "NO_PRICE"
            else:
                status = "SUBMITTED"
            basis = None if lv is None else {k: lv[k] for k in ("stop", "swing_low", "atr14", "up_band", "bar_open")}
            if basis is not None:
                basis["closes"] = [float(x) for x in lv["closes"]]
            data = {"close": close, "bid": bid, "ask": ask, "ctx": _ctx_of(rep_of[sym], name, 1), "group": group,
                    "exits": "reel", "reel": basis}
            if rep_of[sym].get("ctx_error"):
                data["ctx_error"] = rep_of[sym]["ctx_error"]
            rows.append({"bar_close": boundary, "timeframe": REEL_TF, "strategy": name, "symbol": sym,
                         "side": 1, "atr": None if lv is None else lv["atr14"], "ref_price": ref,
                         "ref_time": ready_at, "delay_ms": delay, "status": status, "data": data})
            if status == "SUBMITTED":
                aid = f"{name}@{REEL_TF}"
                subs.append((aid, Signal(
                    ts=boundary - 1, symbol=sym, timeframe=REEL_TF, strategy_id=name, side=1,
                    stop_price=float(lv["stop"]), tier="best", tp_price=float(lv["up_band"]), atr=float(lv["atr14"]),
                    meta={"ref_price": ref, "ref_time": ready_at, "delay_ms": delay, "account": aid,
                          "ctx": _ctx_of(rep_of[sym], name, 1), "reel": {**basis, "closes": list(basis["closes"])}})))
        return rows, subs, reports

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool.join()
            self._pool = None


def _prices(book: Callable[[], dict]) -> tuple[dict, Optional[str]]:
    """The book prices for a v4 group's signals; a failing price read is an error report and NO_PRICE rows (the v4
    groups never let an exception through to the runner)."""
    try:
        return dict(book() or {}), None
    except Exception as exc:  # noqa: BLE001
        return {}, f"book prices failed: {type(exc).__name__}: {exc}"[:300]


def _ctx_of(r: dict, name: str, side: int) -> dict:
    """A v4 row's own ctx: its coin's chart context with the S/R marks of its side (``attach``, as a core row gets
    them; ``_group_ctx``), {} when there is none. A fresh dict per row and Signal. Never entry-strength numbers: no
    strength definition exists for the v4 groups, so levrule sizes them "normal" (owners' D2 / D7)."""
    ctx = r.get("ctx") if isinstance(r.get("ctx"), dict) else None
    m = r.get("marks") if isinstance(r.get("marks"), dict) else None
    out = attach(ctx, {"sr": m["sr"]} if m and "sr" in m else m, name, side)
    return {k: v for k, v in out.items() if k != "strength"} if isinstance(out, dict) else {}


def _levels_ok(lv: dict, bar_open: int) -> bool:
    """A reel / flip levels dict the engine can take: the signal bar is the bar just closed, long, every level finite,
    ATR14 > 0, 19 closes. The PREREG's skip rules (stop >= the fill, the fill >= the first target) are the engine's
    (paperbot/reel_engine.py records SKIPPED), never applied here."""
    try:
        if int(lv["bar_open"]) != int(bar_open) or int(lv.get("side", 1)) != 1:
            return False
        vals = [float(lv[k]) for k in ("stop", "swing_low", "atr14", "up_band")]
        closes = [float(x) for x in lv["closes"]]
    except (KeyError, TypeError, ValueError):
        return False
    return all(np.isfinite(vals)) and len(closes) == 19 and all(np.isfinite(closes)) and vals[2] > 0
