"""Parity harness for the extra paper accounts (copy / new-strategy accounts next to the 195).

Proves that the 195 original accounts behave byte-identically with and without the extras code: the same
synthetic feed, clock model, prices and crash points are run through the live runner (``live3.Runner3``,
the real ``AccountBook`` / ``PaperEngine`` / ``Store3`` and the real ``SignalService``) and a canonical dump
of the 195 is compared. The harness is standalone: it runs on the base commit (no ``paperbot.extras``) and
on the new tree. The golden file ``tests/data/extras_parity_golden.json`` is written on the base commit:

    python -m tests.extras_harness --write-golden            (on the unmodified tree)
    python -m tests.extras_harness --run R0                  (prints one dump)

When the engine's own semantics change for every account (not the extras), the golden is rewritten the same way on
the base commit with that one change applied: ``git archive 7d2bd97 | tar -x -C <dir>``, copy this harness into
<dir>/tests, apply the same paperbot/engine.py change, then in <dir> run
``python -m tests.extras_harness --write-golden --base "7d2bd97...+<change>" --out <repo>/tests/data/...``. Without
the change that command reproduces the previous golden byte for byte. Done once, 2026-10-04: funding is applied at
the start of PaperEngine.step, before the minute's entries and exits (review 3a F2), base
"7d2bd97ff001afd6407ed08ce0fbe6d11d1b5f8b+engine-funding-first".

What is synthetic (design section 11.1)
- Feed: a seeded generator (numpy default_rng(SEED)), seven symbols (the six trade coins plus XRP) at
  realistic price levels, 1m geometric random walk (sigma ~0.15 %/min) with regime drift switches and
  about one jump (2-4 %) per symbol per 6 hours, mark = last x (1 + N(0, 2e-4)), funding at 00/08/16 UTC,
  one injected one-hour zero-volume flat halt. Real 1m ``Bar`` objects with volume, starting 22:00 UTC (a
  UTC midnight and 26 hours, so the UTC day 2..26 h is complete for daily3, 1d record boundaries,
  4h closes). The 5m history the runner bootstraps comes from the same
  generator (the 5m aggregates of the minutes before the feed).
- Signals: the real ``SignalService`` (procs=1) with ``sigservice._LIB = FakeLib``: the real NAMES,
  tf_minutes, resample_ohlcv and fg, small warm-ups, and ``compute_signals`` = per strategy k a cheap
  deterministic cross of the close over SMA(5 + k % 9) thinned by (bar number + k) % 3 == 0, on the
  symbols with (k + symbol index) % 4 == 0 (DOGE_S <= 0, DOGE_L >= 0). Entry marks are stubbed to {}.
- Clock: ``now_ms() = last step of the current process() batch + 61.5 s + charged`` (the live edge, as wall
  time is during a real catch-up burst). ``charged`` restarts at every process() call; the logical model
  charges nothing, the timed model charges every ``service.compute`` its COSTS[tf] and, in the new tree,
  every newlab compute 40 s and every activation poll 5 s (deliberately larger than real).
- prices() is a pure function of the batch's last closes.

The dump of the 195 (``dump195``): per original account its trades, outcomes and equity rows (no row ids),
its "[aid]" alerts, its engine state after every process() call (as the runner last saved it in that call),
its final saved state and every day:* snapshot entry; globally the signal_log rows of every strategy that is
not a new-strategy account (statuses and delays included), the alerts that do not start with "[", the 195
digest's items and the texts it sent.

Runs (the golden file holds the base commit's R0, R0r, T0, K1, K2; tests/test_extras_parity.py runs the rest):
- R: 26 hours, logical clock; R*r restart after 901 steps (no outage, a fresh process from the file).
- T: timed clock, restart after 900 steps with a 30-minute outage, then one catch-up burst (its last boundary
  is live and has signals) and single steps.
- T1c / T2c / T2cx (the step loop, charged): a 10-hour timed feed with a restart after 450 steps and a 25-minute
  outage, where the runner also has a FillProbe whose order-book fetch costs DEPTH_COST and a notifier whose
  every send costs NOTIFY_COST (as a REST call and a Telegram send do). T1c has no extras, T2c the extras
  scenario: the 195 must be equal (the extras fetch no book and send nothing before a 195 compute). T2cx is T2c
  with the step loop before that fix (every engine's fill may fetch a book; negative control, must differ).
- K1..K6: a 10-hour feed in a subprocess killed with os._exit(137) at one boundary (minute 480), then a
  restart from the file to the end. K1 instead of the 195's boundary save, K2 right after it; in the new
  tree K3 phase 1 written before its save, K4 inside the newlab compute after the first job, K5 after a
  creation before the phase-2 save, K6 right after the phase-2 save (K3..K6 are compared with K2).
- The new tree's scenario (``extras``): at minute 358 three copies (stop_atr 2.5 on V45_AMB@15m, lock_start
  0.20 on N23_HA_ST@5m, skip_tag on N12_ICHI_AO@1h, parents that signal at the crash boundary) and nine
  new-strategy accounts are approved by inbox click (created at minute 360), one more new strategy at minute
  476 (created at 480). Parents need no trades here (``min_parent_trades = 0``); new-strategy windows are
  small (NL_WINDOWS, the history kept by FakeLib is 1,440 5m bars). T2x turns the live-boundary gate off: the
  extras' phase 2 then runs during the catch-up burst and must make the 195 late (negative control).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Optional

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from paperbot import Bar, Brackets, sigservice, sweepsig  # noqa: E402
from paperbot.accounts import AccountBook  # noqa: E402
from paperbot.config import V3_SYMBOLS, v3_settings  # noqa: E402
try:                    # the leverage rule the golden file was written with (quality_v1 came on 2026-10-04)
    from paperbot.config import V3_OLD_TIER_WALK as RULE  # noqa: E402
except ImportError:     # the base commit: only the tier walk exists
    RULE = {}
from paperbot.engine import engine_state  # noqa: E402
from paperbot.live3 import Runner3, account_defs  # noqa: E402
from paperbot.notify import Digest, ListNotifier  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

try:                                    # the new tree only
    from paperbot import extras as X    # noqa: E402
except ImportError:                     # the base commit
    X = None

HARNESS_VERSION = 1
SEED = 20261001
MIN = 60_000
FIVE = 300_000
HOUR = 3_600_000
DAY = 86_400_000
T0 = 1_793_916_000_000                  # 2026-11-05 22:00 UTC (00:00 at hour 2, the feed ends at 00:00)
HOURS = 26
CRASH_HOURS = 10
SYMBOLS = tuple(V3_SYMBOLS) + ("XRPUSDT",)
LEVELS = {"BTCUSDT": 68_000.0, "ETHUSDT": 2_600.0, "SOLUSDT": 160.0, "DOGEUSDT": 0.16, "LTCUSDT": 72.0,
          "BCHUSDT": 380.0, "XRPUSDT": 0.55}
HALT = ("SOLUSDT", 10 * 60, 11 * 60)    # symbol, [from, to) minutes after T0: flat bars, volume 0
# The harness's frozen account set: the timeframes the golden file was written with (the live run dropped 5m
# on 2026-10-04, docs/paper-v3-rules-change-1.md; the isolation proof does not depend on the timeframe set).
TRADE_TFS = ("5m", "15m", "30m", "1h", "4h")
RANDOM_RATES = {"5m": 0.02, "15m": 0.03, "30m": 0.04, "1h": 0.05, "4h": 0.08}
WARMUP = {"5m": 20, "15m": 12, "30m": 10, "1h": 8, "4h": 6, "1d": 1}
COSTS = {"5m": 6_000, "15m": 7_000, "30m": 8_000, "1h": 9_000, "4h": 12_000, "1d": 15_000}
NEWLAB_COST = 40_000
POLL_COST = 5_000
DEPTH_COST = 300                        # one order-book REST call (charged runs)
NOTIFY_COST = 2_000                     # one Telegram send (charged runs)
CHARGED_HOURS = 10
RESTART_C = (450, 25)                   # charged runs: restart after 450 steps, a 25-minute outage, then a burst
LIVE_EDGE = 61_500                      # now = last step of the batch + 1 minute + 1.5 s
SPECS = {s: {"qty_step": 0.0, "min_notional": 5.0} for s in V3_SYMBOLS}
RESTART_R = 901                         # logical restart: after this many steps, no outage
RESTART_T = (900, 30)                   # timed restart: after 900 steps, a 30-minute outage, then a burst
GOLDEN = os.path.join(ROOT, "tests", "data", "extras_parity_golden.json")
NL_RE = re.compile(r"^NL[0-9]+$")


# ====================================================================== the fake locked library
class _FakeLib:
    """The locked library's interface with cheap deterministic signals (see the module docstring)."""

    def __init__(self):
        real = sweepsig.lib()
        self.NAMES = list(real.NAMES)
        self.tf_minutes = real.tf_minutes
        self.resample_ohlcv = real.resample_ohlcv
        self.fg = real.fg
        self.pi = real.pi
        self.RESAMPLE_RULE = real.RESAMPLE_RULE

    @staticmethod
    def warmup_bars(tf: str) -> int:
        return WARMUP[tf]

    def compute_signals(self, frames: dict, tf: str, names, strict: bool = False) -> dict:
        span = self.tf_minutes(tf) * MIN
        out: dict = {name: {} for name in self.NAMES if name in names}
        for sym, df in frames.items():
            c = df["close"].to_numpy(float)
            num = (df["ts"].astype("int64").to_numpy() // 1_000_000) // span
            cs = np.r_[0.0, np.cumsum(c)]
            cross = {}
            for n in range(5, 14):
                sma = np.full(len(c), np.nan)
                if len(c) >= n:
                    sma[n - 1:] = (cs[n:] - cs[:-n]) / n
                valid = np.isfinite(sma)
                above = valid & (c > np.where(valid, sma, 0.0))
                prev, pvalid = np.r_[False, above[:-1]], np.r_[False, valid[:-1]]
                ok = valid & pvalid
                cross[n] = (above & ~prev & ok, ~above & prev & ok)
            for k, name in enumerate(self.NAMES):
                if name not in out:
                    continue
                up, dn = cross[5 + k % 9]
                keep = ((num + k) % 3 == 0) & ((k + SYMBOLS.index(sym)) % 4 == 0)
                s = np.where(up & keep, 1, np.where(dn & keep, -1, 0)).astype(np.int8)
                if name == "DOGE_S":
                    s = np.minimum(s, 0).astype(np.int8)
                elif name == "DOGE_L":
                    s = np.maximum(s, 0).astype(np.int8)
                out[name][sym] = s
        return out


_FAKE = None
REAL = {"on": False, "procs": 4}         # --real-lib: the locked library, real windows and entry marks (manual check)


def fake_lib() -> _FakeLib:
    global _FAKE
    if _FAKE is None:
        _FAKE = _FakeLib()
    return _FAKE


def signal_lib():
    return sweepsig.lib() if REAL["on"] else fake_lib()


def install_fakes():
    """sigservice computes with FakeLib; entry marks are stubbed (descriptions only). With --real-lib nothing
    is replaced."""
    if REAL["on"]:
        sigservice._LIB = sweepsig.lib()
        return sigservice._LIB
    from paperbot import entry_marks
    lib = fake_lib()
    sigservice._LIB = lib
    entry_marks.marks = lambda *a, **k: {}
    entry_marks.marks_window_5m = lambda *a, **k: 0
    return lib


# ====================================================================== the feed
class Feed:
    """One continuous seeded 1m series per symbol from ORIGIN (history for any restart) to the feed end."""

    def __init__(self, hours: int = HOURS, seed: int = SEED, hist_5m: Optional[int] = None):
        lib = signal_lib()
        keep = max(sigservice.window_5m(lib, tf) for tf in TRADE_TFS + sigservice.RECORD_TFS)
        self.hist_5m = hist_5m or keep
        self.origin = T0 - (self.hist_5m + 12) * FIVE
        self.end = T0 + hours * HOUR
        self.hours = hours
        n = (self.end - self.origin) // MIN
        self.ts = self.origin + np.arange(n, dtype=np.int64) * MIN
        rng = np.random.default_rng(seed)
        self.data = {}
        for sym in SYMBOLS:
            sig = 0.0015
            drift = np.repeat(rng.normal(0, 0.00012, n // 240 + 1), 240)[:n]
            jumps = np.where(rng.random(n) < 1 / 360, rng.choice([-1, 1], n) * rng.uniform(0.02, 0.04, n), 0.0)
            r = rng.normal(0, sig, n) + drift + jumps
            c = LEVELS[sym] * np.exp(np.cumsum(r))
            o = np.r_[LEVELS[sym], c[:-1]]
            h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, sig / 3, n)))
            lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, sig / 3, n)))
            v = rng.lognormal(3.0, 0.8, n)
            nz = 1 + rng.normal(0, 2e-4, n)
            a = int((T0 + HALT[1] * MIN - self.origin) // MIN)
            b = min(int((T0 + HALT[2] * MIN - self.origin) // MIN), n)
            if sym == HALT[0] and a < n:
                px = c[a - 1]
                o[a:b] = h[a:b] = lo[a:b] = c[a:b] = px
                v[a:b] = 0.0
                nz[a:b] = 1.0
            mo, mh, ml, mc = o * nz, h * nz, lo * nz, c * nz
            fund = rng.normal(1e-4, 3e-4, n)
            self.data[sym] = (o, h, lo, c, v, mo, mh, ml, mc, fund)

    def _bar(self, sym: str, i: int) -> Bar:
        o, h, lo, c, v, mo, mh, ml, mc, _ = self.data[sym]
        t = int(self.ts[i])
        return Bar(sym, t, t + MIN - 1, float(o[i]), float(h[i]), float(lo[i]), float(c[i]),
                   float(mo[i]), float(mh[i]), float(ml[i]), float(mc[i]), volume=float(v[i]))

    def steps(self, lo: int, hi: int) -> list:
        """(ts, bars, funding) for minutes in [lo, hi)."""
        a, b = int((lo - self.origin) // MIN), int((hi - self.origin) // MIN)
        out = []
        for i in range(max(a, 0), min(b, len(self.ts))):
            t = int(self.ts[i])
            bars = {s: self._bar(s, i) for s in SYMBOLS}
            fund = {s: float(self.data[s][9][i]) for s in V3_SYMBOLS} if t % (8 * HOUR) == 0 else {}
            out.append((t, bars, fund))
        return out

    def hist(self, sym: str, lo: int, hi: int) -> list[tuple]:
        """5m rows (open, o, h, l, c, v) with open in [lo, hi), as the aggregator builds them."""
        o, h, l_, c, v = self.data[sym][:5]
        rows = []
        a = int((lo - self.origin) // MIN)
        b = int((hi - self.origin) // MIN)
        for i in range(max(a, 0), b, 5):
            j = i + 5
            rows.append((int(self.ts[i]), float(o[i]), float(h[i:j].max()), float(l_[i:j].min()), float(c[j - 1]),
                         float(v[i:j].sum())))
        return rows

    def closes(self, t: int) -> dict:
        i = int((t - self.origin) // MIN)
        return {s: float(self.data[s][3][i]) for s in SYMBOLS}


# ====================================================================== the clock
class Clock:
    """now = last step of the current process() batch + 61.5 s + charged (see the module docstring)."""

    def __init__(self, timed: bool):
        self.timed = timed
        self.batch_last = T0
        self.charged = 0

    def now(self) -> int:
        return int(self.batch_last + LIVE_EDGE + self.charged)

    def charge(self, ms: int) -> None:
        if self.timed:
            self.charged += int(ms)

    def batch(self, steps) -> None:
        self.batch_last = steps[-1][0] if steps else self.batch_last
        self.charged = 0


# ====================================================================== one process lifetime
class Recorder:
    """What the dump needs from the running process: the 195's engine state after every process() call, the
    195 digest's items and sent texts. ``path``: also appended to a file (crash runs, survives os._exit)."""

    def __init__(self, path: Optional[str] = None):
        self.steps: list[str] = []
        self.items: list[str] = []
        self.sent: list[str] = []
        self.restore: list[str] = []          # new tree: extras whose restored engine differs from the saved state
        self.depth_calls = 0                  # charged runs: order-book fetches (FillProbe)
        self.path = path

    def _write(self, kind: str, value: str) -> None:
        if self.path:
            with open(self.path, "a") as fh:
                fh.write(json.dumps([kind, value]) + "\n")
                fh.flush()

    def step(self, digest: str) -> None:
        self.steps.append(digest)
        self._write("step", digest)

    def item(self, text: str) -> None:
        self.items.append(text)
        self._write("item", text)

    def send(self, text: str) -> None:
        self.sent.append(text)
        self._write("sent", text)

    def restored(self, note: str) -> None:
        self.restore.append(note)
        self._write("restore", note)

    @classmethod
    def load(cls, path: str) -> "Recorder":
        r = cls()
        if os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    kind, value = json.loads(line)
                    {"step": r.steps, "item": r.items, "sent": r.sent, "restore": r.restore}[kind].append(value)
        return r


class _RecNotifier:
    def __init__(self, rec: Recorder):
        self.rec = rec

    def send(self, level: str, text: str) -> None:
        self.rec.send(text)


class _ChargedNotifier(ListNotifier):
    """Every send costs ``ms`` of the clock (a Telegram round trip)."""

    def __init__(self, clock: "Clock", ms: int):
        super().__init__()
        self.clock, self.ms = clock, ms

    def send(self, level: str, text: str) -> None:
        self.clock.charge(self.ms)
        super().send(level, text)


def charged_fills(sess: "Session", ms: int):
    """A FillProbe whose order-book fetch costs ``ms`` of the clock; the book is built from the batch's closes."""
    from paperbot.fillcost import FillProbe

    def depth(sym):
        sess.clock.charge(ms)
        sess.rec.depth_calls += 1
        c = sess.feed.closes(sess.clock.batch_last)[sym]
        return {"bids": [[c * 0.9999, 1e9]], "asks": [[c * 1.0001, 1e9]], "T": sess.clock.now()}
    return FillProbe(depth, sess.settings.slippage_frac, 100)


def leaky_fill_costs(runner) -> None:
    """Negative control (T2cx): the step loop before the fix, where every engine's entry or exit, the extras'
    included, may fetch an order book before the boundary's 195 compute."""
    def _fill_costs(ts, snap, bars):
        rows = runner.fills.after(ts, runner.book.engines, snap, bars, runner.now_ms())
        if rows:
            runner.store.fill_costs(rows)
    runner._fill_costs = _fill_costs


def originals(lib=None) -> list[str]:
    lib = lib or signal_lib()
    return [f"{d['strategy']}@{d['timeframe']}" for d in account_defs(sigservice.strategy_names(lib),
                                                                      TRADE_TFS)]


class Session:
    """One process lifetime of the live runner on ``db`` (as live3.cmd_run builds it, without the network)."""

    def __init__(self, db: str, feed: Feed, clock: Clock, rec: Recorder, extras: Optional[dict] = None,
                 charge: Optional[dict] = None):
        self.lib = install_fakes()
        self.feed, self.clock, self.rec = feed, clock, rec
        self.settings = v3_settings(**RULE)
        self.store_path = db
        self.store = Store3(db)
        self.notifier = _ChargedNotifier(clock, int(charge["notify_ms"])) if charge else ListNotifier()
        self.digest = Digest(_RecNotifier(rec))
        add = self.digest.add

        def _add(text, _add=add):
            rec.item(text)
            _add(text)
        self.digest.add = _add
        brackets = {s: Brackets.example() for s in V3_SYMBOLS}
        self.book = AccountBook(self.settings, brackets, self.store, self.notifier, SPECS, digest=self.digest)
        self.service = sigservice.SignalService(V3_SYMBOLS, ("XRPUSDT",), RANDOM_RATES, trade_tfs=TRADE_TFS,
                                                procs=REAL["procs"] if REAL["on"] else 1, lib=self.lib)
        orig = self.service.compute

        def compute(boundary, tf, now_ms, book, _orig=orig):
            self.clock.charge(COSTS[tf])
            return _orig(boundary, tf, now_ms, book)
        self.service.compute = compute
        self.saved = None
        put = self.store.put_state

        def put_state(key, ts, data, _put=put):
            if key == "accounts":
                self.saved = data
            return _put(key, ts, data)
        self.store.put_state = put_state
        self.ext = None
        self.extras_opts = extras
        make_of = None
        if extras is not None and X is not None:
            self.ext = extras_start(self, extras)
            make_of = self.ext.make_of
        restored = self.book.load(make_of=make_of) if make_of is not None else self.book.load()
        if self.ext is not None and restored:
            saved = self.store.get_state("accounts")[1]["engines"]
            for aid in self.ext.extras:
                a = {k: v for k, v in engine_state(self.book.engines[aid]).items() if k != "n_trades"}
                b = {k: v for k, v in (saved.get(aid) or {}).items() if k != "n_trades"}
                rec.restored(f"{aid}:{'same' if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else 'DIFF'}")
        if restored and self.book.last_ts is not None:
            resume = self.book.last_ts + MIN
            start = resume - resume % FIVE
        else:
            self.book.open_accounts(account_defs(sigservice.strategy_names(self.lib), TRADE_TFS), T0)
            resume = None
            start = T0
        hist_from = start - max(self.service.windows.values()) * FIVE - FIVE
        for s in self.service.symbols:
            self.service.bootstrap(s, feed.hist(s, hist_from, start))
        self.store.commit()
        self.resume, self.start = resume, start
        self.originals = originals(self.lib)
        fills = charged_fills(self, int(charge["depth_ms"])) if charge else None
        self.runner = Runner3(self.book, self.service, self.store, self.notifier, V3_SYMBOLS, self.clock.now,
                              self._prices, skip_before=resume, deadman=None, digest=self.digest, fills=fills)
        if charge and charge.get("leaky"):
            leaky_fill_costs(self.runner)
        if self.ext is not None:
            extras_bind(self, extras)

    def _prices(self) -> dict:
        c = self.feed.closes(self.clock.batch_last)
        return {s: (c[s] * (1 - 1e-4), c[s] * (1 + 1e-4)) for s in V3_SYMBOLS}

    def process(self, steps) -> None:
        self.clock.batch(steps)
        self.runner.process(steps)
        # the 195's engine states as the runner last saved them in this call (book.save serialises every
        # engine after each step, after the boundary's submits and after the extras hook's phases; nothing
        # changes an engine after the last save of a process() call)
        eng = self.saved["engines"] if self.saved is not None else \
            {aid: engine_state(e) for aid, e in self.book.engines.items()}
        st = {aid: eng[aid] for aid in self.originals}
        self.rec.step(hashlib.sha256(json.dumps(st, sort_keys=True).encode()).hexdigest())

    def close(self) -> None:
        self.digest.flush(self.clock.now(), force=True)
        self.store.close()


# ====================================================================== extras (new tree only)
def extras_start(sess: Session, opts: dict):
    """Overridden by the new-tree part below (kept as a hook so the base commit runs this file)."""
    raise RuntimeError("extras need the new tree")


def extras_bind(sess: Session, opts: dict) -> None:
    raise RuntimeError("extras need the new tree")


def extras_hour(sess: Session, opts: dict, t: int) -> None:
    """Called before each single step at time t (approvals at feed hour 6 in the new tree)."""


def extras_crash(sess: Session, crash: dict) -> None:
    raise RuntimeError(f"crash point {crash['point']} needs the new tree")


# ---------------------------------------------------------------------- the new tree's scenario
APPROVE_AT = 358          # minute after T0: three copies and nine new strategies approved (created at 360)
LATE_APPROVE_AT = 476     # one more new strategy (created at minute 480, the crash runs' boundary)
COPIES = (("V45_AMB", "15m", {"template": "stop_atr", "k": 2.5}),
          ("N23_HA_ST", "5m", {"template": "lock_start", "first_lock": 0.2}),
          ("N12_ICHI_AO", "1h", {"template": "skip_tag", "tag": "추세 반대 진입"}))
NEWLAB_SPECS = (
    ("5m", {"family": "ema_cross", "params": {"fast": 9, "slow": 21}}, [], "both"),
    ("1h", {"family": "rsi_reversal", "params": {"length": 14, "low": 30, "high": 70}},
     [{"kind": "session", "window": "us"}], "long"),
    ("15m", {"family": "macd_cross", "params": {"fast": 12, "slow": 26, "signal": 9}}, [], "both"),
    ("15m", {"family": "supertrend_flip", "params": {"length": 10, "mult": 3.0}},
     [{"kind": "trend_ema", "length": 50}], "both"),
    ("30m", {"family": "donchian_break", "params": {"length": 20}}, [], "both"),
    ("30m", {"family": "bb_break", "params": {}}, [{"kind": "adx", "mode": "above", "level": 20}], "both"),
    ("4h", {"family": "ema_cross", "params": {"fast": 9, "slow": 21}}, [], "both"),
    ("4h", {"family": "psar_flip", "params": {}}, [], "both"),
    ("15m", {"family": "obv_cross", "params": {}}, [{"kind": "vol_regime", "mode": "high", "lookback": 100}], "both"),
    ("30m", {"family": "stoch_zone", "params": {}}, [], "both"),          # the late one
)
NL_WINDOWS = {"5m": 600, "15m": 900, "30m": 1200, "1h": 1440, "4h": 1440}
NL_MIN_BARS = {"5m": 300, "15m": 150, "30m": 100, "1h": 60, "4h": 20}
COPY_RESULT = {"ok": True, "template": None, "periods": {
    "1": {"diff": 0.02, "p": 1e-4, "diff_notional": 0.001,
          "variant": {"trades": 600, "mean_roe": 0.05, "mean_pnl_equity": 0.01}},
    "2": {"diff": 0.02, "p": 1e-3, "diff_notional": 0.001,
          "variant": {"trades": 300, "mean_roe": 0.05, "mean_pnl_equity": 0.01}},
    "3": {"available": False}}}
NL_GATE_INPUT = {
    "1": {"available": True, "trades": 900, "mean_roe": 0.04, "p": 1e-5, "coins_pos": 5, "coins_n": 6,
          "mean_pnl_equity": 0.01, "coinflip": {"mean_roe": -0.01, "trades": 9000, "diff": 0.05, "p": 0.001}},
    "2": {"available": True, "trades": 400, "mean_roe": 0.03, "p": 0.001, "coins_pos": 5, "coins_n": 6,
          "mean_pnl_equity": 0.01, "coinflip": {"mean_roe": -0.01, "trades": 4000, "diff": 0.04, "p": 0.001}},
    "3": {"available": False}}


def newlab_spec(i: int) -> dict:
    tf, entry, filters, direction = NEWLAB_SPECS[i]
    return {"v": "newlab-v1", "timeframe": tf, "entry": entry, "filters": filters, "direction": direction}


def copy_account(trial_id: int, strategy: str, tf: str, rule: dict) -> dict:
    """change.account of a copy proposal (the contract literal)."""
    return {"v": 1, "kind": "copy", "trial_id": trial_id, "strategy": strategy, "timeframe": tf,
            "parent": f"{strategy}@{tf}", "rule": rule}


def newlab_account(trial_id: int, spec: dict, h: str) -> dict:
    return {"v": 1, "kind": "newlab", "trial_id": trial_id, "timeframe": spec["timeframe"], "spec": spec,
            "spec_hash": h}


def add_copy_proposal(conn, inbox, strategy: str, tf: str, rule: dict, ts: int, author: str = "A",
                      approve: bool = True, click: bool = True, decided_by: Optional[str] = None) -> tuple[int, int]:
    """A passed copy test, its proposal and (by default) the owners' approve click and the tick's approval,
    written with the agents' and the dashboard's own functions. Returns (proposal id, trial id)."""
    from paperbot.agents import rooms_db as R
    param = [k for k in rule if k != "template"][0]
    spec = {"template": rule["template"], "strategy": strategy, "timeframe": tf, param: rule[param]}
    result = dict(COPY_RESULT, template=rule["template"])
    tid = R.add_trial_with_result(conn, f"strat:{strategy}", strategy, "test", spec, "passed",
                                  {"result": result, "gate": {"pass": True, "n_trials": 1}, "n_trials": 1}, ts=ts)
    change = {"kind": "copy", "account": copy_account(tid, strategy, tf, rule), "strategy": strategy, "test": spec,
              "why": "model text that the runner never reads", "approver": {"approve": True, "reason": "ok"}}
    pid = R.add_proposal(conn, f"strat:{strategy}", strategy, tid, change, {"pass": True, "trial_id": tid,
                                                                             "n_trials": 1}, "awaiting_owner", ts=ts)
    if click:
        R.add_approval(inbox, pid, "approve", author, "note the runner never reads", ts=ts)
    if approve:
        R.set_proposal_status(conn, pid, "approved", decided_by or f"owner:{author}".rstrip(":"), ts=ts)
    return pid, tid


def add_newlab_proposal(conn, inbox, spec: dict, ts: int, author: str = "A", approve: bool = True,
                        click: bool = True, n_then: int = 0, decided_by: Optional[str] = None) -> tuple[int, int]:
    from paperbot.agents import rooms_db as R
    from paperbot.agents import newlab as NL
    h = NL.spec_hash(spec)
    body = {"ledger": {}, "gate": {"pass": True}, "gate_input": NL_GATE_INPUT, "description_ko": "desc",
            "summary_ko": "summary", "notes": {"idea": "model text"}, "test_number": n_then + 1,
            "n_tests_so_far": n_then, "runtime_s": 1.0, "proposal": None}
    tid = R.add_trial_with_result(conn, "team:lab", None, "newlab", spec, "passed", body, ts=ts)
    R.add_trial_result(conn, tid, "proposed", {**body, "proposal": {"kind": "new_paper_account"}}, ts=ts)
    change = {"kind": "newlab", "account": newlab_account(tid, spec, h),
              "proposal": {"description_ko": "desc", "summary_ko": "s", "spec": spec, "gate": {"pass": True}}}
    pid = R.add_proposal(conn, "team:lab", None, tid, change, {"pass": True, "trial_id": tid, "n_tests": 1},
                         "awaiting_owner", ts=ts)
    if click:
        R.add_approval(inbox, pid, "approve", author, None, ts=ts)
    if approve:
        R.set_proposal_status(conn, pid, "approved", decided_by or f"owner:{author}".rstrip(":"), ts=ts)
    return pid, tid


def scenario_paths(db: str) -> tuple[str, str]:
    return db + ".agents3.db", db + ".inbox.db"


if X is not None:
    from paperbot import newlab_live as NLL  # noqa: E402

    def extras_start(sess: Session, opts: dict):   # noqa: F811  (the new tree)
        a, i = scenario_paths(sess.store_path)
        cfg = X.Config(agents_db=a, inbox_db=i, observe_days=0, owner_ok_days=60,
                       budget_s=float(opts.get("budget_s", 20.0)))

        def factory(service):
            src = NLL.NewlabSignals(service, windows=NL_WINDOWS, min_bars=NL_MIN_BARS)
            orig = src.compute

            def compute(boundary, due, deadline, _orig=orig):
                sess.clock.charge(NEWLAB_COST)
                return _orig(boundary, due, deadline)
            src.compute = compute
            return src
        ext = X.Extras.start(sess.store, sess.notifier, sess.store_path, sess.settings, config=cfg,
                             now_ms=sess.clock.now, newlab_factory=factory)
        ext.activator.min_parent_trades = 0
        ext.live_gate = bool(opts.get("live_gate", True))
        orig = ext.activator.poll

        def poll(boundary, j, _orig=orig):
            sess.clock.charge(POLL_COST)
            return _orig(boundary, j)
        ext.activator.poll = poll
        return ext

    def extras_bind(sess: Session, opts: dict) -> None:   # noqa: F811
        sess.ext.bind(sess.runner)

    def extras_hour(sess: Session, opts: Optional[dict], t: int) -> None:   # noqa: F811
        if opts is None or sess.ext is None:
            return
        if t not in (T0 + APPROVE_AT * MIN, T0 + LATE_APPROVE_AT * MIN):
            return
        from paperbot.agents import rooms_db as R
        a, i = scenario_paths(sess.store_path)
        conn, inbox = R.open_agents(a), R.open_inbox_rw(i)
        try:
            if t == T0 + APPROVE_AT * MIN:
                for strategy, tf, rule in COPIES:
                    add_copy_proposal(conn, inbox, strategy, tf, rule, t)
                for k in range(len(NEWLAB_SPECS) - 1):
                    add_newlab_proposal(conn, inbox, newlab_spec(k), t)
            else:
                add_newlab_proposal(conn, inbox, newlab_spec(len(NEWLAB_SPECS) - 1), t)
        finally:
            conn.close()
            inbox.close()

    def extras_crash(sess: Session, crash: dict) -> None:   # noqa: F811
        """K3 phase 1 written, before its save; K4 inside the newlab compute after the first job; K5 after the
        creation and its alert, before the phase-2 save; K6 right after the phase-2 save."""
        point, at = crash["point"], int(crash["at"])
        ext = sess.ext
        cur = {"b": None}
        hook = sess.runner.post_boundary

        def post_boundary(boundary, submitted, timed_out, _hook=hook):
            cur["b"] = boundary
            try:
                return _hook(boundary, submitted, timed_out)
            finally:
                cur["b"] = None
        sess.runner.post_boundary = post_boundary
        commit = ext._commit

        def _commit(phase, _orig=commit):
            if cur["b"] == at:
                if point == "K3" and phase == 1:
                    os._exit(137)
                if point == "K5" and phase == 2 and any(v.get("boundary") == at
                                                        for v in ext.state["created"].values()):
                    os._exit(137)
            _orig(phase)
            if cur["b"] == at and point == "K6" and phase == 2:
                os._exit(137)
        ext._commit = _commit
        if point == "K4":
            orig = NLL.compute_newlab

            def compute_newlab(*a, _orig=orig, **k):
                out = _orig(*a, **k)
                if cur["b"] == at:
                    os._exit(137)
                return out
            NLL.compute_newlab = compute_newlab


# ====================================================================== runs
def run(db: str, *, hours: int = HOURS, timed: bool = False, restart: Optional[tuple] = None,
        extras: Optional[dict] = None, rec_path: Optional[str] = None, crash: Optional[dict] = None,
        stop_after: Optional[int] = None, resume_only: bool = False, charge: Optional[dict] = None) -> Recorder:
    """Run the feed through the runner. ``restart`` = (steps before the restart, outage minutes): the first
    process stops there and a fresh one continues from the file (catch-up burst, then single steps).
    ``crash``: {"point", "at"} installs a kill point (os._exit) in this process (subprocess use only).
    ``stop_after``: return after that many single steps without closing (crash runs). ``resume_only``:
    skip the first process (it ran in another process) and continue from the file. ``charge``: the charged step
    loop ({"depth_ms", "notify_ms", "leaky"}: an order-book FillProbe and a notifier that cost clock time)."""
    feed = Feed(hours)
    clock = Clock(timed)
    rec = Recorder(rec_path)
    end = feed.end
    if not resume_only:
        sess = Session(db, feed, clock, rec, extras, charge)
        if crash is not None:
            install_crash(sess, crash)
        n_first = restart[0] if restart else (end - T0) // MIN
        t = T0
        for i in range(n_first):
            extras_hour(sess, extras, t)
            sess.process(feed.steps(t, t + MIN))
            t += MIN
        if restart is None:
            sess.close()
            return rec
        sess.store.close()                  # the process ends (no flush: a restart, not a clean stop)
        outage = restart[1]
    else:
        outage = 0
    sess = Session(db, feed, clock, rec, extras, charge)
    t = sess.resume + outage * MIN
    burst = feed.steps(sess.start, t)       # every minute missed, in one poll (steps < resume only feed history)
    if burst:
        sess.process(burst)
    while t < end:
        extras_hour(sess, extras, t)
        sess.process(feed.steps(t, t + MIN))
        t += MIN
    sess.close()
    return rec


def install_crash(sess: Session, crash: dict) -> None:
    """Kill points (design 11.4) by monkeypatching; the base tree needs no change.
    K1: at boundary B, instead of the 195's book.save in _signals; K2: right after it. The new-tree points
    K3..K6 are installed by ``extras_crash``."""
    point, at = crash["point"], int(crash["at"])
    runner, book = sess.runner, sess.book
    state = {"in": None, "saves": 0}
    orig_signals = runner._signals

    def _signals(boundary, _orig=orig_signals):
        state["in"], state["saves"] = boundary, 0
        try:
            return _orig(boundary)
        finally:
            state["in"] = None
    runner._signals = _signals
    orig_save = book.save

    def save(ts, _orig=orig_save):
        if state["in"] == at:
            state["saves"] += 1
            if point == "K1" and state["saves"] == 1:
                os._exit(137)
            _orig(ts)
            if point == "K2" and state["saves"] == 1:
                os._exit(137)
            return
        _orig(ts)
    book.save = save
    if point not in ("K1", "K2"):
        extras_crash(sess, crash)


def crash_run(workdir: str, point: str, at: int, extras: Optional[dict] = None, hours: int = CRASH_HOURS) -> tuple:
    """A crash run: a subprocess runs the feed and is killed at ``point`` / boundary ``at`` (os._exit, no
    commit, no cleanup); this process then restarts from the file and runs to the end. Returns
    (dump, recorder)."""
    db = os.path.join(workdir, f"crash_{point}_{at}.db")
    rp = db + ".rec"
    for p in (db, db + "-wal", db + "-shm", rp):
        if os.path.exists(p):
            os.remove(p)
    cmd = [sys.executable, "-m", "tests.extras_harness", "--child", db, "--point", point, "--at", str(at),
           "--hours", str(hours), "--rec", rp] + (["--real-lib"] if REAL["on"] else [])
    if extras is not None:
        cmd += ["--extras", json.dumps(extras)]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1200)
    if r.returncode != 137:
        raise RuntimeError(f"crash child for {point}@{at} exited {r.returncode} (expected 137):\n{r.stderr[-3000:]}")
    run(db, hours=hours, extras=extras, rec_path=rp, resume_only=True)
    full = Recorder.load(rp)
    return dump195(db, full, signal_lib()), full


# ====================================================================== the dump
def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                          .encode()).hexdigest()


def dump195(db: str, rec: Recorder, lib=None) -> dict:
    """The canonical dump of the 195 original accounts (see the module docstring)."""
    ids = originals(lib)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cols = lambda t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})") if r[1] != "id"]  # noqa: E731
        tcols, ocols = cols("trades"), cols("outcomes")
        trades, outs, eq, al = {}, {}, {}, {}
        for r in conn.execute(f"SELECT {', '.join(tcols)} FROM trades ORDER BY id"):
            trades.setdefault(r[0], []).append(list(r))
        for r in conn.execute(f"SELECT {', '.join(ocols)} FROM outcomes ORDER BY id"):
            outs.setdefault(r[0], []).append(list(r))
        for r in conn.execute("SELECT account_id, ts, equity, drawdown FROM equity ORDER BY account_id, ts"):
            eq.setdefault(r[0], []).append(list(r))
        alerts_g = []
        for ts, level, text in conn.execute("SELECT ts, level, text FROM alerts ORDER BY rowid"):
            if text.startswith("["):
                m = re.match(r"^\[([^\]]+)\]", text)
                if m:
                    al.setdefault(m.group(1), []).append([ts, level, text])
            else:
                alerts_g.append([ts, level, text])
        final = json.loads(conn.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()[0])["engines"]
        days = {}
        for k, data in conn.execute("SELECT k, data FROM state WHERE k LIKE 'day:%' ORDER BY k"):
            days[k] = json.loads(data)["engines"]
        scols = [c for c in cols("signal_log")]
        sig = [list(r) for r in conn.execute(f"SELECT {', '.join(scols)} FROM signal_log "
                                             "ORDER BY bar_close, timeframe, strategy, symbol")
               if not NL_RE.match(r[scols.index("strategy")])]
    finally:
        conn.close()
    accounts = {}
    for aid in ids:
        accounts[aid] = _sha({"trades": trades.get(aid, []), "outcomes": outs.get(aid, []), "equity": eq.get(aid, []),
                              "alerts": al.get(aid, []), "final": final.get(aid),
                              "days": {k: v.get(aid) for k, v in days.items()}})
    out = {"accounts": accounts, "steps": _sha(rec.steps), "signal_log": _sha(sig), "alerts": _sha(alerts_g),
           "digest_items": _sha(rec.items), "digest": _sha(rec.sent)}
    out["total"] = _sha({k: v for k, v in out.items()})
    out["counts"] = {"trades": sum(len(trades.get(a, [])) for a in ids), "signal_rows": len(sig),
                     "process_calls": len(rec.steps), "digest_items": len(rec.items), "alerts": len(alerts_g)}
    return out


def keys195(d: dict) -> dict:
    """The keys compared for the 195 (``counts`` is information only)."""
    return {k: v for k, v in d.items() if k != "counts"}


# ====================================================================== the named runs of the golden file
CRASH_AT = None          # boundary of the crash runs (set below; one boundary for every point, design 11.4)


def crash_boundary() -> int:
    """A boundary at minute 480 after T0 (session 1 of the crash runs)."""
    return T0 + 480 * MIN


def base_runs(workdir: str, log=print) -> dict:
    out = {}
    t0 = time.time()
    out["R0"] = dump195(_p(workdir, "R0"), run(_p(workdir, "R0")))
    log(f"R0 {time.time() - t0:.0f}s")
    out["R0r"] = dump195(_p(workdir, "R0r"), run(_p(workdir, "R0r"), restart=(RESTART_R, 0)))
    log(f"R0r {time.time() - t0:.0f}s")
    out["T0"] = dump195(_p(workdir, "T0"), run(_p(workdir, "T0"), timed=True, restart=RESTART_T))
    log(f"T0 {time.time() - t0:.0f}s")
    at = crash_boundary()
    for point in ("K1", "K2"):
        out[f"{point}@{at}"] = crash_run(workdir, point, at)[0]
        log(f"{point} {time.time() - t0:.0f}s")
    return out


SCENARIO = {"scenario": "approve", "budget_s": 20.0}


def new_run(name: str, workdir: str, hours: int = HOURS, crash_hours: int = CRASH_HOURS) -> dict:
    """One named run of the new tree (design 11.3 / 11.4). Returns {"name", "golden", "dump", "db"}: the dump
    of the 195 and the name of the golden run it must equal."""
    at = crash_boundary()
    if name in ("T1c", "T2c", "T2cx"):
        charge = {"depth_ms": DEPTH_COST, "notify_ms": NOTIFY_COST, "leaky": name == "T2cx"}
        db = _p(workdir, name)
        for q in scenario_paths(db):
            for r in (q, q + "-wal", q + "-shm"):
                if os.path.exists(r):
                    os.remove(r)
        rec = run(db, hours=min(hours, CHARGED_HOURS), timed=True, restart=RESTART_C, charge=charge,
                  extras=None if name == "T1c" else SCENARIO)
        return {"name": name, "golden": "T1c", "dump": dump195(db, rec), "db": db, "restore": rec.restore,
                "depth_calls": rec.depth_calls}
    if name in ("R1", "R1r", "R2", "R2r", "T2", "T2x"):
        kw = {"R1": {}, "R1r": {"restart": (RESTART_R, 0)},
              "R2": {"extras": SCENARIO}, "R2r": {"extras": SCENARIO, "restart": (RESTART_R, 0)},
              "T2": {"extras": SCENARIO, "timed": True, "restart": RESTART_T},
              "T2x": {"extras": dict(SCENARIO, live_gate=False), "timed": True, "restart": RESTART_T}}[name]
        db = _p(workdir, name)
        for q in scenario_paths(db):
            for r in (q, q + "-wal", q + "-shm"):
                if os.path.exists(r):
                    os.remove(r)
        rec = run(db, hours=hours, **kw)
        golden = {"R1": "R0", "R1r": "R0r", "R2": "R0", "R2r": "R0r", "T2": "T0", "T2x": "T0"}[name]
        return {"name": name, "golden": golden, "dump": dump195(db, rec), "db": db, "restore": rec.restore}
    point = name[:2]
    extras = None if name in ("K1", "K2") else SCENARIO
    golden = f"{'K1' if point == 'K1' else 'K2'}@{at}"
    sub = os.path.join(workdir, name)
    os.makedirs(sub, exist_ok=True)
    d, rec = crash_run(sub, point, at, extras=extras, hours=crash_hours)
    return {"name": name, "golden": golden, "dump": d, "db": os.path.join(sub, f"crash_{point}_{at}.db"),
            "restore": rec.restore}


NEW_RUNS = ("R1", "R1r", "R2", "R2r", "T2", "T2x", "K1", "K2", "K1x", "K2x", "K3", "K4", "K5", "K6")
CHARGED_RUNS = ("T1c", "T2c", "T2cx")     # compared with each other (T2c == T1c, T2cx != T1c), not with the golden


def _p(workdir: str, name: str) -> str:
    p = os.path.join(workdir, f"{name}.db")
    for q in (p, p + "-wal", p + "-shm"):
        if os.path.exists(q):
            os.remove(q)
    return p


def versions() -> dict:
    return {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__}


def base_commit() -> Optional[str]:
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def write_golden(path: str = GOLDEN, base: Optional[str] = None, log=print) -> dict:
    if X is not None:
        raise SystemExit("the golden file is written on the base commit (paperbot.extras must not exist)")
    work = tempfile.mkdtemp(prefix="extras_golden_")
    try:
        runs = base_runs(work, log)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    doc = {"harness_version": HARNESS_VERSION, "base_commit": base or base_commit(), "versions": versions(),
           "seed": SEED, "t0": T0, "hours": HOURS, "crash_hours": CRASH_HOURS, "crash_at": crash_boundary(),
           "runs": runs}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return doc


def compare_base(base: str, hours: int, real: bool, procs: int) -> int:
    """Old vs new on the same feed (design 11.6 step 3): the base commit exported with git archive (the repository
    is not touched), this harness copied into it, each tree run in its own process."""
    work = tempfile.mkdtemp(prefix="extras_compare_")
    old = os.path.join(work, "old")
    os.makedirs(old)
    arch = subprocess.run(["git", "-C", ROOT, "archive", base], capture_output=True, timeout=300)
    if arch.returncode != 0:
        raise SystemExit(f"git archive {base} failed: {arch.stderr.decode()[-500:]}")
    subprocess.run(["tar", "-x", "-C", old], input=arch.stdout, check=True, timeout=300)
    shutil.copy(os.path.abspath(__file__), os.path.join(old, "tests", "extras_harness.py"))
    flags = ["--hours", str(hours)] + (["--real-lib", "--procs", str(procs)] if real else [])
    pairs = [("R0", "R2")]
    if hours * 60 > crash_boundary() // MIN - T0 // MIN + 10:
        pairs.append(("K2", "K2x"))
    if hours * 60 > RESTART_T[0] + RESTART_T[1] + 10:
        pairs.append(("T0", "T2"))
    out = {}
    for a, b in pairs:
        ja, jb = os.path.join(work, a + ".json"), os.path.join(work, b + ".json")
        pa = subprocess.Popen([sys.executable, "-m", "tests.extras_harness", "--run", a, "--json", ja] + flags, cwd=old,
                              stdout=subprocess.DEVNULL)
        pb = subprocess.Popen([sys.executable, "-m", "tests.extras_harness", "--new-run", b, "--work",
                               os.path.join(work, b), "--json", jb] + flags, cwd=ROOT, stdout=subprocess.DEVNULL)
        if pa.wait() != 0 or pb.wait() != 0:
            raise SystemExit(f"{a}/{b} failed")
        with open(ja) as fh:
            da = json.load(fh)["dump"]
        with open(jb) as fh:
            db = json.load(fh)["dump"]
        diff = [k for k in ("accounts", "steps", "signal_log", "alerts", "digest_items", "digest") if da[k] != db[k]]
        out[f"{a} vs {b}"] = {"equal": not diff, "differs": diff, "old": da["counts"], "new": db["counts"]}
    print(json.dumps({"base": base, "hours": hours, "real_lib": real, "result": out}, indent=1))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if all(v["equal"] for v in out.values()) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write-golden", action="store_true")
    ap.add_argument("--out", default=GOLDEN)
    ap.add_argument("--base", help="the base commit id to record (default: git HEAD of this tree)")
    ap.add_argument("--run", help="one named run: R0, R0r, T0")
    ap.add_argument("--new-run", help="one named run of the new tree: " + ", ".join(NEW_RUNS + CHARGED_RUNS))
    ap.add_argument("--work", help="work directory of --new-run (databases are kept there)")
    ap.add_argument("--json", help="write the --new-run result here")
    ap.add_argument("--child", help=argparse.SUPPRESS)
    ap.add_argument("--point", help=argparse.SUPPRESS)
    ap.add_argument("--at", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--hours", type=int, default=HOURS, help="feed hours (default 26)")
    ap.add_argument("--real-lib", action="store_true",
                    help="the locked library with its real windows and entry marks (slow; a manual check)")
    ap.add_argument("--procs", type=int, default=4, help="signal workers with --real-lib")
    ap.add_argument("--compare-base", metavar="COMMIT",
                    help="old vs new: export COMMIT (git archive) to a scratch folder, run the base tree (R0, and K2 / "
                         "T0 when --hours allows) and this tree (R2 / K2x / T2 with extras) each in its own process, and "
                         "compare the dumps of the 195")
    ap.add_argument("--rec", help=argparse.SUPPRESS)
    ap.add_argument("--extras", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.real_lib:
        REAL.update(on=True, procs=args.procs)
    if args.compare_base:
        return compare_base(args.compare_base, args.hours, args.real_lib, args.procs)
    if args.child:
        extras = json.loads(args.extras) if args.extras else None
        run(args.child, hours=args.hours, extras=extras, rec_path=args.rec,
            crash={"point": args.point, "at": args.at})
        return 3                              # the kill point was never reached
    if args.new_run:
        work = args.work or tempfile.mkdtemp(prefix="extras_new_")
        os.makedirs(work, exist_ok=True)
        res = new_run(args.new_run, work, hours=args.hours,
                      crash_hours=min(CRASH_HOURS, args.hours) if args.hours != HOURS else CRASH_HOURS)
        if args.json:
            with open(args.json, "w") as fh:
                json.dump(res, fh)
        print(json.dumps({"name": res["name"], "total": res["dump"]["total"], "counts": res["dump"]["counts"]}))
        return 0
    if args.write_golden:
        doc = write_golden(args.out, args.base, log=lambda s: print(s, file=sys.stderr))
        print(json.dumps({k: v["total"] for k, v in doc["runs"].items()}, indent=1))
        return 0
    if args.run:
        work = tempfile.mkdtemp(prefix="extras_run_")
        at = crash_boundary()
        if args.run in ("K1", "K2"):
            d = crash_run(work, args.run, at, hours=min(CRASH_HOURS, args.hours))[0]
        else:
            kw = {"R0": {}, "R0r": {"restart": (RESTART_R, 0)}, "T0": {"timed": True, "restart": RESTART_T}}[args.run]
            db = _p(work, args.run)
            d = dump195(db, run(db, hours=args.hours, **kw))
        if args.json:
            with open(args.json, "w") as fh:
                json.dump({"name": args.run, "dump": d}, fh)
        print(json.dumps(d, indent=1))
        shutil.rmtree(work, ignore_errors=True)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
