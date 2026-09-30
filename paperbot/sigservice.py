"""Live signals for the paper v3 run (docs/paper-v3-rules.md).

At every 5m boundary the service holds the closed 5m bars of every coin. For
each timeframe that closes at that boundary it builds the chart bars with the
backtest's ``resample_ohlcv`` (``recorder.build_frames``, forming bar dropped),
runs the locked ``compute_signals`` for all strategies and keeps the signal of
the bar that just closed.

- Trading timeframes (5m..4h) and coins (six): one Signal per strategy account,
  stop distance 2 x ATR14 of the signal bar, reference price = best ask (long)
  or best bid (short) right after the computation. The engine adds slippage.
- Coin-flip accounts: per timeframe, coin and bar a seeded draw with the rate
  fixed in research/paper_rules/out/summary.json.
- Daily bars and XRP: signals are logged only (status RECORD).
- A signal ready more than ``max_delay_ms`` after its bar closed (catch-up after
  a restart) is logged as LATE and not traded.

Indicators run on a trailing window of 2 x warm-up bars per timeframe; the
replay check in research/paper_rules/parity_live.py compares this with the
full-history backtest signals.
"""

from __future__ import annotations

import warnings
from collections import deque
from multiprocessing import Pool, TimeoutError as PoolTimeout
from typing import Callable, Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from . import sweepsig
from .aggregate import TF_MS
from .models import Bar, Signal

TRADE_TFS = ("5m", "15m", "30m", "1h", "4h")
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
    """Worker: signals of the TF bar that closes at ``boundary`` for one coin."""
    symbol, tf, boundary, ts, o, h, l, c, v = job
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
    return out


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


class SignalTimeout(RuntimeError):
    pass


class SignalService:
    def __init__(self, trade_symbols: Sequence[str], record_symbols: Sequence[str] = (),
                 random_rates: Optional[dict] = None, seeds: Sequence[int] = (1, 2, 3),
                 stop_atr: float = 2.0, max_delay_ms: int = 180_000, procs: int = 4,
                 trade_tfs: Sequence[str] = TRADE_TFS, record_tfs: Sequence[str] = RECORD_TFS,
                 lib=None, pool=None, timeout_s: float = 120.0):
        self.lib = lib or _lib()
        self.trade_symbols = list(trade_symbols)
        self.symbols = self.trade_symbols + [s for s in record_symbols if s not in trade_symbols]
        self.random_rates = dict(random_rates or {})
        self.seeds = tuple(seeds)
        self.stop_atr = stop_atr
        self.max_delay_ms = max_delay_ms
        self.trade_tfs = tuple(trade_tfs)
        self.record_tfs = tuple(record_tfs)
        self.names = strategy_names(self.lib)
        keep = max(window_5m(self.lib, tf) for tf in self.trade_tfs + self.record_tfs)
        self.hist = {s: deque(maxlen=keep) for s in self.symbols}
        self.windows = {tf: window_5m(self.lib, tf) for tf in self.trade_tfs + self.record_tfs}
        self._pool = pool
        self._procs = procs
        self.timeout_s = timeout_s  # a signal later than max_delay_ms is not traded anyway
        self.pool_restarts = 0

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
        jobs = []
        for s in self.symbols:
            a = np.array(list(self.hist[s])[-n:], dtype=float)
            jobs.append((s, tf, boundary, a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]))
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
                rows.append({"bar_close": boundary, "timeframe": tf, "strategy": name, "symbol": sym,
                             "side": int(side), "atr": r["atr"], "ref_price": ref, "ref_time": ready_at,
                             "delay_ms": delay, "status": status,
                             "data": {"close": r["close"], "bid": bid, "ask": ask, "ctx": r.get("ctx")}})
                if status == "SUBMITTED":
                    aid = f"{name}@{tf}"
                    subs.append((aid, Signal(
                        ts=boundary - 1, symbol=sym, timeframe=tf, strategy_id=name, side=int(side),
                        stop_price=0.0, tier="best", atr=r["atr"],
                        meta={"stop_dist": self.stop_atr * r["atr"], "ref_price": ref,
                              "ref_time": ready_at, "delay_ms": delay, "account": aid,
                              "ctx": r.get("ctx") or {}})))
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

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool.join()
            self._pool = None
