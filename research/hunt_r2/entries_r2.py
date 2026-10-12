"""Hunt round 2 (PREREG_HUNT_R2.md 3.1, 3.2, 11): entry events of any lattice combo, for the round-1 machine.

* F1 (E1-E3): ``f1_raw`` takes every number of 3.2; at the defaults (and the v1 neighbours of the main number) it is
  ``entries_wide.hunt_raw`` bit for bit (tests/test_hunt_r2_core.py).
* F2 / F3: the full grid's signal functions, called as ``research/fullgrid/run.signals`` calls them
  (``core_module(name).signals(df, tf, **combo)``, ``ds_module().signals(df, tf, name, ctx, coin, cache, **combo)``),
  through ``SeriesEvents``: the indicator memo (``run.M``) and the DeepSeek cache are cleared once per coin x
  timeframe series (one ``SeriesEvents`` per (name, timeframe, coin) unit), not per combo (11). Names listed in
  ``FRESH_PER_COMBO`` get a fresh memo and cache per combo (11: a name whose kept-cache events differ on synthetic
  bars; none so far).
* F5: ``entries_wide.famous_raw(name, bars, combo)``.
* Events (W 3.2): the edge (true on t, false on t-1) of each side's array; F2-F3 also the full grid's 300-bar warm-up.
  Round 2 never passes a round-2 spec dict to round 1's spec-based path (``hunt.entry_events``, ``system_signals``,
  ``run_system``...): ``entries_wide.events_on`` reads only the first number of an F1 combo (11).
"""

from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import entries_wide as EW  # noqa: E402
from research.hunt_r2 import lattice as L  # noqa: E402

FRESH_PER_COMBO: frozenset = frozenset()       # 11: names whose memo / cache cannot be kept across combos


def f1_raw(name: str, bars, combo: dict) -> tuple:
    """F1 arrays (PREREG_HUNT 5 with every number of 3.2 taken from ``combo``); already events (true on t, false on
    t-1), as ``entries_wide.hunt_raw``, whose operations this repeats in the same order."""
    h, l, c, qv = bars.h, bars.l, bars.c, bars.qv
    with np.errstate(invalid="ignore", divide="ignore"):
        if name == "E1":
            if len(qv) and not np.isfinite(qv).any():
                raise ValueError("E1 needs the quote volume: build_bars(..., qv=the 5m 'qv' array)")
            n = int(combo["channel"])
            hh = EW._roll_prev(h, n, lambda w: w.max(1))
            ll = EW._roll_prev(l, n, lambda w: w.min(1))
            vm = EW._roll_prev(qv, int(combo["vol_len"]), lambda w: w.mean(1))
            vol_ok = qv >= float(combo["vol_mult"]) * vm
            defined = np.isfinite(hh) & np.isfinite(ll) & np.isfinite(vm) & np.isfinite(qv) & np.isfinite(c)
            return EW._event_pair((c > hh) & vol_ok, (c < ll) & vol_ok, defined)
        if name == "E2":
            win, bb_len, k, q = int(combo["window"]), int(combo["bb_len"]), float(combo["bb_k"]), float(combo["pct"])
            mid = EW._roll_now(c, bb_len, lambda w: w.mean(1))
            sd = EW._roll_now(c, bb_len, lambda w: w.std(1))                 # population (ddof 0)
            up, lo = mid + k * sd, mid - k * sd
            bw = (up - lo) / mid
            pct = EW._roll_prev(bw, win, lambda w: np.percentile(w, q, axis=1))
            squeeze = EW._prev(bw) <= pct
            cl = (c > up) & (EW._prev(c) <= EW._prev(up))
            cs = (c < lo) & (EW._prev(c) >= EW._prev(lo))
            defined = np.isfinite(pct) & np.isfinite(EW._prev(bw)) & np.isfinite(up) & np.isfinite(EW._prev(up))
            return EW._event_pair(squeeze & cl, squeeze & cs, defined)
        if name == "E3":
            thr = float(combo["threshold"])
            ratio = EW.wilder_atr(h, l, c, int(combo["fast"])) / EW.wilder_atr(h, l, c, int(combo["slow"]))
            cross = (ratio >= thr) & (EW._prev(ratio) < thr)
            mom = c - EW._prev(c, int(combo["side_len"]))
            defined = np.isfinite(ratio) & np.isfinite(EW._prev(ratio)) & np.isfinite(mom)
            return EW._event_pair(cross & (mom > 0), cross & (mom < 0), defined)
    raise ValueError(f"unknown F1 entry {name!r}")


class SeriesEvents:
    """Events of one name on one coin x timeframe series for any number of combos. The full grid's memo and the
    DeepSeek cache are cleared when the object is made (once per series), and kept across its combos unless the name
    is in ``FRESH_PER_COMBO``."""

    def __init__(self, name: str, bars, sym: str, btc=None, fresh: bool | None = None):
        self.name, self.bars, self.sym, self.btc = name, bars, sym, btc
        self.family = L.family_of(name)
        self.kind = L.KIND_OF[self.family]
        self.fresh = (name in FRESH_PER_COMBO) if fresh is None else bool(fresh)
        self.cache: dict = {}
        if self.kind in ("core", "ds"):
            self.R = EW.fullgrid_run()
            EW.fullgrid_pins()                    # the full grid's pinned files, checked before any F2-F3 signal
            self.R.M.clear()
            if self.kind == "ds" and sym != "BTCUSDT":
                if btc is None:
                    raise ValueError(f"{name} on {sym}: the DeepSeek definitions take BTC bars of the same timeframe")
                if btc.tf != bars.tf:
                    raise ValueError("BTC bars on another timeframe")

    def raw(self, combo: dict) -> tuple:
        """The side arrays (F1: already events; F2-F3: the definitions' arrays; F5: famous_raw's events)."""
        b = self.bars
        if self.kind == "hunt":
            return f1_raw(self.name, b, combo)
        if self.kind == "famous":
            return EW.famous_raw(self.name, b, combo)
        if self.fresh:
            self.R.M.clear()
            self.cache = {}
        args = {k: (list(v) if isinstance(v, tuple) else v) for k, v in combo.items()}
        if self.kind == "core":
            lo, sh = self.R.core_module(self.name).signals(b.df, b.tf, **args)
        else:
            ctx = None if self.sym == "BTCUSDT" else {"BTCUSD": self.btc.df}
            lo, sh = self.R.ds_module().signals(b.df, b.tf, self.name, ctx=ctx, coin=EW.coin_of(self.sym),
                                                cache=self.cache, **args)
        lo, sh = np.asarray(lo, bool), np.asarray(sh, bool)
        if lo.shape != (len(b),) or sh.shape != (len(b),):
            raise ValueError(f"{self.name}: signal arrays of the wrong length")
        return lo, sh

    def events(self, combo: dict) -> tuple:
        """(long events, short events) per bar, ungated (W 3.2 edge; F2-F3 warm-up of run.WARMUP_BARS)."""
        lg, sh = self.raw(combo)
        el, es = EW.rising(lg), EW.rising(sh)
        if self.kind in ("core", "ds"):
            w = self.R.WARMUP_BARS
            el[:w] = False
            es[:w] = False
        return el, es
