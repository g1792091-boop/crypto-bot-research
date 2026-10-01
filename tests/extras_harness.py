"""Parity harness for the extra paper accounts (copy / new-strategy accounts next to the 195).

Proves that the 195 original accounts behave byte-identically with and without the extras code: the same
synthetic feed, clock model, prices and crash points are run through the live runner (``live3.Runner3``,
the real ``AccountBook`` / ``PaperEngine`` / ``Store3`` and the real ``SignalService``) and a canonical dump
of the 195 is compared. The harness is standalone: it runs on the base commit (no ``paperbot.extras``) and
on the new tree. The golden file ``tests/data/extras_parity_golden.json`` is written on the base commit:

    python -m tests.extras_harness --write-golden            (on the unmodified tree)
    python -m tests.extras_harness --run R0                  (prints one dump)

What is synthetic (design section 11.1)
- Feed: a seeded generator (numpy default_rng(SEED)), seven symbols (the six trade coins plus XRP) at
  realistic price levels, 1m geometric random walk (sigma ~0.15 %/min) with regime drift switches and
  about one jump (2-4 %) per symbol per 6 hours, mark = last x (1 + N(0, 2e-4)), funding at 00/08/16 UTC,
  one injected one-hour zero-volume flat halt. Real 1m ``Bar`` objects with volume, starting 20:00 UTC (one
  UTC midnight, a 1d record boundary, 4h closes). The 5m history the runner bootstraps comes from the same
  generator (the 5m aggregates of the minutes before the feed).
- Signals: the real ``SignalService`` (procs=1) with ``sigservice._LIB = FakeLib``: the real NAMES,
  tf_minutes, resample_ohlcv and fg, small warm-ups, and ``compute_signals`` = per strategy k a cheap
  deterministic cross of the close over SMA(5 + k % 9) thinned by (bar number + k) % 3 == 0 (DOGE_S <= 0,
  DOGE_L >= 0). Entry marks are stubbed to {}.
- Clock: ``now_ms() = last step of the current process() batch + 61.5 s + charged`` (the live edge, as wall
  time is during a real catch-up burst). ``charged`` restarts at every process() call; the logical model
  charges nothing, the timed model charges every ``service.compute`` its COSTS[tf] and, in the new tree,
  every newlab compute 40 s and every activation poll 5 s (deliberately larger than real).
- prices() is a pure function of the batch's last closes.

The dump of the 195 (``dump195``): per original account its trades, outcomes and equity rows (no row ids),
its "[aid]" alerts, its engine state after every process() call, its final saved state and every day:*
snapshot entry; globally the signal_log rows of every strategy that is not a new-strategy account (statuses
and delays included), the alerts that do not start with "[", the 195 digest's items and the texts it sent.
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
from types import SimpleNamespace
from typing import Callable, Optional

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from paperbot import Bar, Brackets, sigservice, sweepsig  # noqa: E402
from paperbot.accounts import AccountBook  # noqa: E402
from paperbot.config import V3_SYMBOLS, v3_settings  # noqa: E402
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
T0 = 1_793_908_800_000                  # 2026-11-05 20:00 UTC
HOURS = 30
CRASH_HOURS = 12
SYMBOLS = tuple(V3_SYMBOLS) + ("XRPUSDT",)
LEVELS = {"BTCUSDT": 68_000.0, "ETHUSDT": 2_600.0, "SOLUSDT": 160.0, "DOGEUSDT": 0.16, "LTCUSDT": 72.0,
          "BCHUSDT": 380.0, "XRPUSDT": 0.55}
HALT = ("SOLUSDT", 10 * 60, 11 * 60)    # symbol, [from, to) minutes after T0: flat bars, volume 0
RANDOM_RATES = {"5m": 0.02, "15m": 0.03, "30m": 0.04, "1h": 0.05, "4h": 0.08}
WARMUP = {"5m": 20, "15m": 12, "30m": 10, "1h": 8, "4h": 6, "1d": 3}
COSTS = {"5m": 6_000, "15m": 7_000, "30m": 8_000, "1h": 9_000, "4h": 12_000, "1d": 15_000}
NEWLAB_COST = 40_000
POLL_COST = 5_000
LIVE_EDGE = 61_500                      # now = last step of the batch + 1 minute + 1.5 s
SPECS = {s: {"qty_step": 0.0, "min_notional": 5.0} for s in V3_SYMBOLS}
RESTART_R = 901                         # logical restart: after this many steps, no outage
RESTART_T = (900, 25)                   # timed restart: after 900 steps, a 25-minute outage, then a burst
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
        out: dict = {}
        for k, name in enumerate(self.NAMES):
            if name not in names:
                continue
            out[name] = {}
            for sym, df in frames.items():
                c = df["close"].to_numpy(float)
                n = 5 + k % 9
                sma = pd.Series(c).rolling(n, min_periods=n).mean().to_numpy()
                above = np.nan_to_num(c - sma, nan=0.0) > 0
                valid = np.isfinite(sma)
                prev = np.r_[False, above[:-1]]
                pvalid = np.r_[False, valid[:-1]]
                num = (df["ts"].astype("int64").to_numpy() // 1_000_000) // span
                keep = ((num + k) % 3 == 0) & valid & pvalid
                s = np.where(above & ~prev & keep, 1, np.where(~above & prev & keep, -1, 0)).astype(np.int8)
                if name == "DOGE_S":
                    s = np.minimum(s, 0).astype(np.int8)
                elif name == "DOGE_L":
                    s = np.maximum(s, 0).astype(np.int8)
                out[name][sym] = s
        return out


_FAKE = None


def fake_lib() -> _FakeLib:
    global _FAKE
    if _FAKE is None:
        _FAKE = _FakeLib()
    return _FAKE


def install_fakes() -> _FakeLib:
    """sigservice computes with FakeLib; entry marks are stubbed (descriptions only)."""
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
        lib = fake_lib()
        keep = max(sigservice.window_5m(lib, tf) for tf in sigservice.TRADE_TFS + sigservice.RECORD_TFS)
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

    @classmethod
    def load(cls, path: str) -> "Recorder":
        r = cls()
        if os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    kind, value = json.loads(line)
                    {"step": r.steps, "item": r.items, "sent": r.sent}[kind].append(value)
        return r


class _RecNotifier:
    def __init__(self, rec: Recorder):
        self.rec = rec

    def send(self, level: str, text: str) -> None:
        self.rec.send(text)


def originals(lib=None) -> list[str]:
    lib = lib or fake_lib()
    return [f"{d['strategy']}@{d['timeframe']}" for d in account_defs(sigservice.strategy_names(lib),
                                                                      sigservice.TRADE_TFS)]


class Session:
    """One process lifetime of the live runner on ``db`` (as live3.cmd_run builds it, without the network)."""

    def __init__(self, db: str, feed: Feed, clock: Clock, rec: Recorder, extras: Optional[dict] = None):
        self.lib = install_fakes()
        self.feed, self.clock, self.rec = feed, clock, rec
        self.settings = v3_settings()
        self.store = Store3(db)
        self.notifier = ListNotifier()
        self.digest = Digest(_RecNotifier(rec))
        add = self.digest.add

        def _add(text, _add=add):
            rec.item(text)
            _add(text)
        self.digest.add = _add
        brackets = {s: Brackets.example() for s in V3_SYMBOLS}
        self.book = AccountBook(self.settings, brackets, self.store, self.notifier, SPECS, digest=self.digest)
        self.service = sigservice.SignalService(V3_SYMBOLS, ("XRPUSDT",), RANDOM_RATES, procs=1, lib=self.lib)
        orig = self.service.compute

        def compute(boundary, tf, now_ms, book, _orig=orig):
            self.clock.charge(COSTS[tf])
            return _orig(boundary, tf, now_ms, book)
        self.service.compute = compute
        self.ext = None
        self.extras_opts = extras
        make_of = None
        if extras is not None and X is not None:
            self.ext = extras_start(self, extras)
            make_of = self.ext.make_of
        restored = self.book.load(make_of=make_of) if make_of is not None else self.book.load()
        if restored and self.book.last_ts is not None:
            resume = self.book.last_ts + MIN
            start = resume - resume % FIVE
        else:
            self.book.open_accounts(account_defs(sigservice.strategy_names(self.lib), sigservice.TRADE_TFS), T0)
            resume = None
            start = T0
        hist_from = start - max(self.service.windows.values()) * FIVE - FIVE
        for s in self.service.symbols:
            self.service.bootstrap(s, feed.hist(s, hist_from, start))
        self.store.commit()
        self.resume, self.start = resume, start
        self.originals = originals(self.lib)
        self.runner = Runner3(self.book, self.service, self.store, self.notifier, V3_SYMBOLS, self.clock.now,
                              self._prices, skip_before=resume, deadman=None, digest=self.digest, fills=None)
        if self.ext is not None:
            extras_bind(self, extras)

    def _prices(self) -> dict:
        c = self.feed.closes(self.clock.batch_last)
        return {s: (c[s] * (1 - 1e-4), c[s] * (1 + 1e-4)) for s in V3_SYMBOLS}

    def process(self, steps) -> None:
        self.clock.batch(steps)
        self.runner.process(steps)
        st = {aid: engine_state(self.book.engines[aid]) for aid in self.originals}
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


# ====================================================================== runs
def run(db: str, *, hours: int = HOURS, timed: bool = False, restart: Optional[tuple] = None,
        extras: Optional[dict] = None, rec_path: Optional[str] = None, crash: Optional[dict] = None,
        stop_after: Optional[int] = None, resume_only: bool = False) -> Recorder:
    """Run the feed through the runner. ``restart`` = (steps before the restart, outage minutes): the first
    process stops there and a fresh one continues from the file (catch-up burst, then single steps).
    ``crash``: {"point", "at"} installs a kill point (os._exit) in this process (subprocess use only).
    ``stop_after``: return after that many single steps without closing (crash runs). ``resume_only``:
    skip the first process (it ran in another process) and continue from the file."""
    feed = Feed(hours)
    clock = Clock(timed)
    rec = Recorder(rec_path)
    end = feed.end
    if not resume_only:
        sess = Session(db, feed, clock, rec, extras)
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
    sess = Session(db, feed, clock, rec, extras)
    t = sess.resume + outage * MIN
    sess.process(feed.steps(sess.start, t))
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


def extras_crash(sess: Session, crash: dict) -> None:
    raise RuntimeError(f"crash point {crash['point']} needs the new tree")


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
           "--hours", str(hours), "--rec", rp]
    if extras is not None:
        cmd += ["--extras", json.dumps(extras)]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1200)
    if r.returncode != 137:
        raise RuntimeError(f"crash child for {point}@{at} exited {r.returncode} (expected 137):\n{r.stderr[-3000:]}")
    rec = run(db, hours=hours, extras=extras, rec_path=rp, resume_only=True)
    full = Recorder.load(rp)
    return dump195(db, full, fake_lib()), full


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
    """A boundary at minute 600 after T0 (session 1 of the crash runs)."""
    return T0 + 600 * MIN


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write-golden", action="store_true")
    ap.add_argument("--out", default=GOLDEN)
    ap.add_argument("--base", help="the base commit id to record (default: git HEAD of this tree)")
    ap.add_argument("--run", help="one named run: R0, R0r, T0")
    ap.add_argument("--child", help=argparse.SUPPRESS)
    ap.add_argument("--point", help=argparse.SUPPRESS)
    ap.add_argument("--at", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--hours", type=int, default=HOURS, help=argparse.SUPPRESS)
    ap.add_argument("--rec", help=argparse.SUPPRESS)
    ap.add_argument("--extras", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.child:
        extras = json.loads(args.extras) if args.extras else None
        run(args.child, hours=args.hours, extras=extras, rec_path=args.rec,
            crash={"point": args.point, "at": args.at})
        return 3                              # the kill point was never reached
    if args.write_golden:
        doc = write_golden(args.out, args.base, log=lambda s: print(s, file=sys.stderr))
        print(json.dumps({k: v["total"] for k, v in doc["runs"].items()}, indent=1))
        return 0
    if args.run:
        work = tempfile.mkdtemp(prefix="extras_run_")
        kw = {"R0": {}, "R0r": {"restart": (RESTART_R, 0)}, "T0": {"timed": True, "restart": RESTART_T}}[args.run]
        db = _p(work, args.run)
        print(json.dumps(dump195(db, run(db, **kw)), indent=1))
        shutil.rmtree(work, ignore_errors=True)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
