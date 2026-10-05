"""The reel's own exits (paper v4, owners' D2 (ii)): the engine of the REEL_H1@5m account and of the three 5m coin
flips RANDOM_k@5m (D4). Part of the REEL hash set (runinfo, D8): a change here restarts the reel's window only.

The shared engine files (engine.py, policy.py, models.py) are NOT changed for this: ``ReelEngine`` overrides three
methods of ``PaperEngine`` (``_try_enter``, ``_handle_exit``, ``_raise_lock``; ``step`` only adds an error fence that halts this
account alone), and its exit state lives inside the
open position's own copy of its signal (``Position.signal.meta["reel_exit"]``), which ``engine_state`` /
``restore_engine`` already save and restore (``dataclasses.asdict`` copies the meta dict). Every other account runs
the unchanged ``PaperEngine`` (accounts.original_engine_cls), so its behaviour and its saved state are byte-identical.

Rules (research/reel5m/PREREG_REEL5M.md section 5, implemented there by ``lib_reel5m.exit_trade``), long only:
- stop: fixed stop-market at ``Signal.stop_price``. Reel: lowest low from the first breach bar through the signal bar
  minus 0.05 x ATR14 (5m, the signal bar's). 5m coin flip: lowest low of the previous 12 closed 5m bars (the signal
  bar included) minus 0.05 x ATR14. The signal carries it; this module never recomputes it from bars.
- target: a resting limit at the PREVIOUS closed 5m bar's upper Bollinger band (20, 2, population std), updated at
  every 5m close. During the first 5m bar at risk (s+1) it is UP[s] = ``Signal.tp_price``; later UP[j] is computed
  here (``upper_band``) from the 19 closes the signal carries and the 5m closes built from the 1m bars stepped
  through. A bar that opens through the target fills at its open.
- the same bar touches stop and target: the stop first.
- time exit: at the close of the 96th 5m bar at risk (the entry bar s+1 counts as bar 1), market, slippage.
- skip (no position, outcome SKIPPED with a "reel:" reason): stop >= the entry fill, or the entry fill >= the first
  target UP[s].
- no ladder, no profit lock. Leverage and size as every account: levrule "normal" tier (30x / 30%, then 20x / 20%;
  config.V3_P_BEST["5m"] == 0.0), the same safety checks (policy.size), liquidation on mark price, funding.

Documented differences from the PREREG (owners' D3; tests/test_engine_reel.py proves that these are the only ones):
1. Exits are checked on 1m bars, not 5m bars. Consequences:
   a. inside one 5m bar the real order of the 1m bars decides: when a 5m bar reaches both the stop and the target the
      PREREG takes the stop; live, a target reached in an earlier minute than the stop is a TP. On a 1m path that
      visits the 5m low before the 5m high the engine equals the PREREG (and ``simulate_exit``) exactly;
   b. a 5m bar (not the entry bar) that OPENS above the target fills the target at that open even when the same 5m
      bar later reaches the stop (PREREG: the stop, "손절 먼저 ... 시가가 이미 목표 위에서 열려도");
   c. on the entry bar the position exists only from the fill on: a stop reached in it fills at the stop, never at
      the bar's open (PREREG: min(open, stop) when the open is below the stop but the fill, open + 0.02%, is not).
2. The target counts as hit only when the high trades THROUGH it (``high > target``, the engine's limit-order
   convention); the PREREG uses ``high >= target``. The fill is the same (the target, or a better gapped open).
3. The entry fills at the house reference price 8-13 s after the 5m boundary (plus 0.02% slippage), not at the next
   bar's open; the skip rules use that fill. As for every house account, the whole entry minute's range counts for
   the stop and the target.
4. The reel signal ignores positions (the account then records SKIPPED "in position"), and one position covers all
   six coins; the PREREG holds one position per coin and does not arm while holding.
5. Bars are counted by the clock: the time exit is at entry 5m bar open + 96 x 5m (the PREREG counts the bars present
   in the data). A 5m bar with no 1m bar at all adds no close to the band (as a bar missing from the PREREG's data);
   a 5m bar whose last 1m bar is missing is closed with the last close seen, at the next 1m bar; a time exit whose
   1m bar is missing happens at the open of the next 1m bar.
6. Costs are the house costs (taker 0.05% on entry, stop and time exits, maker 0.02% on the target, real funding at
   the funding times, liquidation on mark price); the PREREG charges 2 x taker and pro-rata funding.
7. The band of later bars is computed from the 20 closes with exact sums (``upper_band``); the PREREG's pandas rolling
   band differs from it by rounding only (pandas' online rolling sums: about 1e-12 relative).

Signal contract (built by P4 from ``reelsig.signal`` / ``reelsig.flip_levels``):
    Signal(ts=boundary - 1, symbol, timeframe="5m", strategy_id="REEL_H1" or "RANDOM_k", side=+1,
           stop_price=<absolute stop>, tier="best", tp_price=<UP[s]>, atr=<ATR14 of bar s>,
           meta={"ref_price", "ref_time", "delay_ms", "account",
                 "reel": {"stop", "swing_low", "atr14", "up_band", "closes"}})
    No "stop_dist" in meta (the stop is absolute). ``meta["reel"]["closes"]``: the closes of the 5m bars s-18..s
    (19 floats, oldest first). A signal that breaks this contract is REJECTED with a "reel:" reason (never traded
    with other exits), as is one whose next 5m bar has already passed when it reaches the engine.

State (``Position.signal.meta["reel_exit"]``, JSON-safe): {"closes": the last 19 closed 5m closes, "bucket": open
time of the 5m bar now at risk, "last": the last 1m close seen in it (None before the first), "end": the time exit
(entry 5m bar open + 96 x 5m)}; the current target is ``Position.tp_price``. A restart in the middle of a trade
continues exactly (tests).
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Optional

import numpy as np

from .engine import PaperEngine
from .models import Bar, Position, Signal
from .notify import INFO

# PREREG section 5 numbers (must equal research/reel5m/lib_reel5m.py: STOP_BUF_ATR, MAX_HOLD, WAIT, BB_LEN, BB_K).
STOP_BUF_ATR = 0.05          # stop = swing low - 0.05 x ATR14
MAX_HOLD_5M = 96             # 5m bars at risk, the entry bar included
BB_LEN, BB_K = 20, 2.0       # Bollinger(20, 2), population std (ddof=0)
FLIP_LOOKBACK = 12           # 5m coin flips: the swing low is the lowest low of the last 12 closed 5m bars
EXIT_REASONS = ("SL", "TP", "TIME", "EOD", "LIQ")
SKIP_STOP = "reel: stop at or above the entry"
SKIP_TARGET = "reel: entry at or above the first target"
FIVE_MS = 5 * 60_000
STATE_KEY = "reel_exit"      # the exit state, inside the open position's own copy of its signal's meta


def upper_band(closes) -> float:
    """The upper Bollinger band (BB_LEN, BB_K, population std) of exactly BB_LEN closes, oldest first, with exact
    sums. The one formula of the engine and ``simulate_exit``. NaN when a close is NaN."""
    xs = [float(x) for x in closes]
    if len(xs) != BB_LEN:
        raise ValueError(f"upper_band needs {BB_LEN} closes, got {len(xs)}")
    mu = math.fsum(xs) / BB_LEN
    var = math.fsum((x - mu) * (x - mu) for x in xs) / BB_LEN
    return mu + BB_K * math.sqrt(var)


def upper_bands(close) -> np.ndarray:
    """``upper_band`` of every bar of a close series (NaN for the first BB_LEN - 1 bars): the "upper" a caller of
    ``simulate_exit`` may compute once per series."""
    c = np.asarray(close, float)
    out = np.full(len(c), np.nan)
    for k in range(BB_LEN - 1, len(c)):
        out[k] = upper_band(c[k - BB_LEN + 1:k + 1])
    return out


def _bucket(ms: int) -> int:
    return int(ms) - int(ms) % FIVE_MS


def _finite(x) -> bool:
    try:
        return x is not None and not isinstance(x, bool) and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def signal_problem(sig: Signal) -> Optional[str]:
    """Why a signal cannot be traded with the reel's exits (None when it can)."""
    if sig.side != 1:
        return "long only"
    if "stop_dist" in sig.meta:
        return "stop_dist given (the reel's stop is absolute)"
    if not _finite(sig.stop_price):
        return "no stop"
    if not _finite(sig.tp_price):
        return "no first target"
    reel = sig.meta.get("reel")
    closes = reel.get("closes") if isinstance(reel, dict) else None
    if not isinstance(closes, (list, tuple)) or len(closes) != BB_LEN - 1 or not all(_finite(x) for x in closes):
        return f"meta.reel.closes must hold the {BB_LEN - 1} closes of bars s-18..s"
    return None


class ReelEngine(PaperEngine):
    """``PaperEngine`` with the reel's exits for one account (same constructor as ``PaperEngine``; ``AccountBook``
    builds it through ``accounts.original_engine_cls``). Sizing, fees, funding, liquidation, bust, drawdown warnings,
    the trade / outcome callbacks and the store records are inherited unchanged; only the entry checks (the skip
    rules, the target taken from the signal) and the exits (stop, moving target, time exit) differ."""

    def step(self, bars: dict[str, Bar], funding: Optional[dict[str, float]] = None) -> None:
        """``PaperEngine.step``; an unexpected error halts this account only (CRITICAL alert, once) instead of
        stopping the step of every account (AccountBook.step does not isolate engines)."""
        try:
            super().step(bars, funding)
        except Exception as exc:  # noqa: BLE001  the reel's code must never stop the other accounts
            if not getattr(self, "_reel_error", None):
                self._reel_error = f"{type(exc).__name__}: {exc}"[:200]
                self._halt(f"reel engine error {self._reel_error}")

    def _try_enter(self, sig: Signal, bar: Bar) -> bool:
        """Enter at the reference price like ``PaperEngine`` (sizing by policy.size, "normal" leverage group), after
        the skip rules; set the first target ``sig.tp_price`` and start the reel exit state. Returns True when a
        position was opened."""
        side = sig.side
        raw = float(sig.meta.get("ref_price", bar.open))
        fill = raw * (1 + side * self.s.slippage_frac)
        why = signal_problem(sig)
        if why is None and _bucket(bar.open_time) != _bucket(sig.ts + 1):
            why = "the signal's next 5m bar has passed"
        if why is not None:
            self._record(sig, "REJECTED", f"reel: {why}", bar.open_time, fill=fill)
            return False
        stop, target = float(sig.stop_price), float(sig.tp_price)
        if stop >= fill:
            self._record(sig, "SKIPPED", SKIP_STOP, bar.open_time, fill=fill, stop=stop, target=target)
            return False
        if fill >= target:
            self._record(sig, "SKIPPED", SKIP_TARGET, bar.open_time, fill=fill, stop=stop, target=target)
            return False
        spec = self.specs.get(sig.symbol, {})
        dec = self.policy.size(self.wallet, sig, fill, self.brackets[sig.symbol], spec)
        if not dec.ok:
            self._record(sig, "REJECTED", "sizing", bar.open_time, reasons=dec.reasons, fill=fill)
            return False
        notional = dec.qty * fill
        fee = notional * self.s.taker_fee
        self.wallet -= fee
        bucket = _bucket(bar.open_time)
        state = {"closes": [float(x) for x in sig.meta["reel"]["closes"]], "bucket": bucket, "last": None,
                 "end": bucket + MAX_HOLD_5M * FIVE_MS}
        held = replace(sig, meta={**sig.meta, STATE_KEY: state})     # the logged signal itself is not touched
        self.position = Position(
            signal=held, symbol=sig.symbol, side=side, qty=dec.qty,
            entry_price=fill, entry_time=bar.open_time, leverage=dec.leverage,
            tier=dec.tier, margin=dec.margin, margin_initial=dec.margin,
            stop_price=stop, tp_price=target, liq_price=dec.liq_price,
            entry_fee=fee, mae_price=fill, mfe_price=fill, stop_initial=stop)
        self._record(sig, "ENTERED", "ok", bar.open_time, tier=dec.tier,
                     leverage=dec.leverage, margin=dec.margin, fill=fill,
                     downgrades=dec.reasons, stop=stop, target=target)
        self.notifier.send(INFO, (
            f"[{self.book}] ENTRY {sig.symbol} LONG {sig.strategy_id} "
            f"{dec.tier} {dec.leverage}x margin {dec.margin:.2f} @ {fill:.6g} "
            f"SL {stop:.6g} TP {target:.6g} LIQ {dec.liq_price:.6g}"))
        return True

    def _handle_exit(self, bar: Bar, entry_bar: bool) -> None:
        """One 1m bar of the open position: liquidation and gap checks as ``PaperEngine``, then stop first, target
        (high > target, fill at max(open, target), maker), and at the last 1m bar of the 96th 5m bar the time exit at
        its close. At each 5m close (the bar's ``close_time + 1`` on a 5m boundary) update the target to that 5m bar's
        upper band. No ladder."""
        p = self.position
        assert p is not None
        st = p.signal.meta.get(STATE_KEY)
        if not isinstance(st, dict):            # never for a position this engine opened: exits as it was opened
            super()._handle_exit(bar, entry_bar)
            return
        b = _bucket(bar.open_time)
        if b > st["bucket"]:                    # the last 1m bar of an earlier 5m bar never came: close it now
            self._roll(p, st, b)
        if bar.open_time >= st["end"]:          # the time exit fell in a gap of 1m bars: market at this open
            self._close_market(bar.open, bar.open_time, "TIME")
            return
        super()._handle_exit(bar, entry_bar)    # gaps, stop first, liquidation, target; _raise_lock is a no-op
        if self.position is not p:
            return
        st["last"] = float(bar.close)
        end = bar.close_time + 1
        if end % FIVE_MS == 0:
            self._roll(p, st, end)
            if end >= st["end"]:
                self._close_market(bar.close, bar.close_time, "TIME")

    def _raise_lock(self, p: Position) -> None:
        """No ladder for the reel (the book's settings say tp_mode "ladder" for the house accounts)."""
        return None

    @staticmethod
    def _roll(p: Position, st: dict, next_bucket: int) -> None:
        """The 5m bar ``st["bucket"]`` has closed: its last close joins the band, the target becomes its upper band
        (from the next 1m bar on). A 5m bar that had no 1m bar adds nothing."""
        if st["last"] is not None:
            closes = list(st["closes"]) + [st["last"]]
            if len(closes) >= BB_LEN:
                p.tp_price = upper_band(closes[-BB_LEN:])
            st["closes"] = closes[-(BB_LEN - 1):]
        st["last"] = None
        st["bucket"] = int(next_bucket)


def _col(bars5m, name: str):
    try:
        return bars5m[name]
    except (KeyError, IndexError):
        return None


def simulate_exit(bars5m, entry_idx: int, entry_price: float, stop: float,
                  side: int = +1) -> tuple[Optional[int], Optional[float], str]:
    """The reel's exit on 5m bars, as a pure function (the checkpoint's reel and 5m coin-flip bots, daily3 checks).

    ``bars5m``: a mapping (or DataFrame) with equal-length arrays "open", "high", "low", "close" of consecutive closed
    5m bars, and optionally "upper" (the Bollinger(20, 2, ddof=0) upper band of each bar; ``upper_bands(close)`` when
    absent, the engine's own formula). ``entry_idx``: the first bar at risk (signal bar s + 1); its target is
    upper[entry_idx - 1]. ``entry_price``: the entry fill. ``stop``: the absolute stop. ``side``: +1 only (the reel
    and its flips are long-only); anything else raises ValueError.

    Returns ``(exit_idx, exit_price, reason)``. ``exit_price`` is the raw level before slippage and fees (the engine
    takes 0.02% slippage off "SL" and "TIME", none off "TP"). Per bar j at risk, in this order (the engine's order):
    on every bar but the entry bar, an open at or below the stop is "SL" at the open, an open above the target is "TP"
    at the open; then a low at or below the stop is "SL" at the stop (the stop first); a high above the target is
    "TP" at the target (the target counts as hit only when high > target, the live engine's convention); at bar
    entry_idx + 95, "TIME" at its close. "EOD": the bars end before the time exit (the last bar's close). A skipped
    entry returns ``(None, None, "SKIP_STOP")`` (stop >= entry_price) or ``(None, None, "SKIP_TARGET")``
    (entry_price >= upper[entry_idx - 1], or no target). Liquidation is the caller's (it depends on the size).

    This is exactly ``ReelEngine`` stepped on 1m bars that visit each 5m bar's low before its high (module docstring,
    difference 1a; tests/test_engine_reel.py), without liquidation and funding."""
    if side != 1:
        raise ValueError("the reel and its 5m coin flips are long only (side must be +1)")
    cols = {k: _col(bars5m, k) for k in ("open", "high", "low", "close")}
    if any(v is None for v in cols.values()):
        raise ValueError(f"bars5m needs open, high, low and close (missing {[k for k, v in cols.items() if v is None]})")
    o, h, l, c = (np.asarray(cols[k], float) for k in ("open", "high", "low", "close"))
    n = len(c)
    if not len(o) == len(h) == len(l) == n:
        raise ValueError("open, high, low and close must have the same length")
    e = int(entry_idx)
    if not 1 <= e < n:
        raise ValueError(f"entry_idx {e} outside 1..{n - 1} (the signal bar entry_idx - 1 must exist)")
    up_col = _col(bars5m, "upper")
    up = np.asarray(up_col, float) if up_col is not None else None
    if up is not None and len(up) != n:
        raise ValueError("upper must have the same length as close")

    def target(j: int) -> float:                    # resting during bar j: the upper band of bar j - 1
        k = j - 1
        if up is not None:
            return float(up[k])
        return upper_band(c[k - BB_LEN + 1:k + 1]) if k >= BB_LEN - 1 else math.nan

    entry_price, stop = float(entry_price), float(stop)
    tg = target(e)
    if stop >= entry_price:
        return None, None, "SKIP_STOP"
    if not entry_price < tg:
        return None, None, "SKIP_TARGET"
    last = e + MAX_HOLD_5M - 1
    for j in range(e, min(n, last + 1)):
        if j > e:
            tg = target(j)
            if o[j] <= stop:
                return j, float(o[j]), "SL"
            if o[j] > tg:
                return j, float(o[j]), "TP"
        if l[j] <= stop:
            return j, stop, "SL"
        if h[j] > tg:
            return j, tg, "TP"
        if j == last:
            return j, float(c[j]), "TIME"
    return n - 1, float(c[n - 1]), "EOD"


def simulate_exit_1m(bars1m, entry_i: int, entry_price: float, stop: float, target: float, closes,
                     liq: Optional[float] = None, side: int = +1) -> tuple[Optional[int], Optional[float], str]:
    """``ReelEngine``'s exit on the 1m bars of one coin, as a pure function: the same decisions in the same order as
    the engine (for the checkpoint's reel and 5m coin-flip bots on real 1m bars, where ``simulate_exit`` on 5m bars
    is the low-first approximation; module docstring, difference 1a).

    ``bars1m``: a mapping (or DataFrame) with equal-length arrays "open_time" (ms, ascending), "open", "high", "low",
    "close", and optionally "mark_open" / "mark_low" (liquidation on mark price; last price when absent). A row whose
    open is NaN is a missing minute (the engine never sees it). ``entry_i``: the row of the minute in which the entry
    fills (open_time = the 5m boundary after the signal bar). ``entry_price``: the fill. ``stop``: the absolute stop.
    ``target``: the first target UP[s] (``Signal.tp_price``). ``closes``: the 19 closes of the 5m bars s-18..s.
    ``liq``: the position's liquidation price (None: no liquidation check; funding that moves it is the caller's).

    Returns ``(exit_i, exit_price, reason)``, the price raw as in ``simulate_exit`` (the engine takes the slippage off
    "SL" and "TIME"): "LIQ" at ``liq``, "SL", "TP", "TIME", "OPEN" (the bars end first: the last row, its close), or
    ``(None, None, "SKIP_STOP" / "SKIP_TARGET")``."""
    if side != 1:
        raise ValueError("the reel and its 5m coin flips are long only (side must be +1)")
    need = ("open_time", "open", "high", "low", "close")
    cols = {k: _col(bars1m, k) for k in need}
    if any(v is None for v in cols.values()):
        raise ValueError(f"bars1m needs {need} (missing {[k for k, v in cols.items() if v is None]})")
    t = np.asarray(cols["open_time"], np.int64)
    o, h, l, c = (np.asarray(cols[k], float) for k in need[1:])
    mo, ml = _col(bars1m, "mark_open"), _col(bars1m, "mark_low")
    mo = o if mo is None else np.asarray(mo, float)
    ml = l if ml is None else np.asarray(ml, float)
    n = len(t)
    if not all(len(x) == n for x in (o, h, l, c, mo, ml)):
        raise ValueError("all columns must have the same length")
    i0 = int(entry_i)
    if not 0 <= i0 < n or not math.isfinite(o[i0]):
        raise ValueError(f"entry_i {i0} is not a present minute")
    entry_price, stop, tg = float(entry_price), float(stop), float(target)
    buf = [float(x) for x in closes]
    if len(buf) != BB_LEN - 1:
        raise ValueError(f"closes must hold {BB_LEN - 1} closes")
    if stop >= entry_price:
        return None, None, "SKIP_STOP"
    if entry_price >= tg:
        return None, None, "SKIP_TARGET"
    bucket = _bucket(int(t[i0]))
    end = bucket + MAX_HOLD_5M * FIVE_MS
    last: Optional[float] = None

    def roll(nxt: int) -> None:
        nonlocal buf, last, bucket, tg
        if last is not None:
            buf = buf + [last]
            tg = upper_band(buf[-BB_LEN:])
            buf = buf[-(BB_LEN - 1):]
        last = None
        bucket = nxt

    for i in range(i0, n):
        if not math.isfinite(o[i]):
            continue
        ti = int(t[i])
        b = _bucket(ti)
        if b > bucket:
            roll(b)
        if ti >= end:
            return i, float(o[i]), "TIME"
        if i > i0:
            if liq is not None and mo[i] <= liq:
                return i, float(liq), "LIQ"
            if o[i] <= stop:
                return i, float(o[i]), "SL"
            if o[i] > tg:
                return i, float(o[i]), "TP"
        if l[i] <= stop:
            return i, stop, "SL"
        if liq is not None and ml[i] <= liq:
            return i, float(liq), "LIQ"
        if h[i] > tg:
            return i, tg, "TP"
        last = float(c[i])
        nxt = ti + 60_000
        if nxt % FIVE_MS == 0:
            roll(nxt)
            if nxt >= end:
                return i, float(c[i]), "TIME"
    present = [i for i in range(i0, n) if math.isfinite(o[i])]
    return present[-1], float(c[present[-1]]), "OPEN"
