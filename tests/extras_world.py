"""A small live-runner world for the extras runtime tests: a real AccountBook / Store3 / Runner3 with a few
accounts, a fake signal service that fires chosen signals, and agents3.db / inbox.db fixtures written with the
agents' and the dashboard's own functions (tests/extras_harness.py add_copy_proposal / add_newlab_proposal)."""

from __future__ import annotations

import os
from collections import deque
from typing import Optional

import numpy as np

from paperbot import Bar, Brackets, Signal
from paperbot.accounts import AccountBook
from paperbot.config import V3_SYMBOLS, v3_settings
from paperbot.live3 import Runner3
from paperbot.notify import Digest, ListNotifier
from paperbot.sigservice import SignalTimeout
from paperbot.store3 import Store3

from tests.extras_harness import add_copy_proposal, add_newlab_proposal, newlab_spec  # noqa: F401

MIN = 60_000
FIVE = 300_000
HOUR = 3_600_000
DAY = 86_400_000
T0 = 1_800_000_000_000 - 1_800_000_000_000 % DAY          # a UTC midnight (2027-01-15)
S = v3_settings()
BR = {s: Brackets.example() for s in V3_SYMBOLS}
TF_MS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": HOUR, "4h": 4 * HOUR}
STRATS = ("V45_AMB", "N17_KC_RSI", "S2_ST_ROC")
TFS = ("5m", "15m", "1h")
NL_WINDOWS = {"5m": 400, "15m": 600, "30m": 900, "1h": 1200, "4h": 1400}
NL_MIN_BARS = {"5m": 100, "15m": 60, "30m": 40, "1h": 30, "4h": 10}


def names36() -> list[str]:
    from paperbot.agents.roster3 import STRATEGY_KO
    return list(STRATEGY_KO)


class FakeService:
    """The SignalService interface the runner and the extras use; ``fire[(B, tf)]`` = [(aid, side, symbol, ctx)]."""

    def __init__(self, names, maxlen: int = 1500, symbols=V3_SYMBOLS):
        self.names = list(names)
        self.trade_symbols = list(symbols)
        self.symbols = list(symbols)
        self.hist = {s: deque(maxlen=maxlen) for s in self.symbols}
        self.max_delay_ms = 180_000
        self.fire: dict = {}
        self.timeout_at: set = set()
        self.computed: list = []
        self.atr = 0.2

    def add_5m(self, b: Bar) -> None:
        h = self.hist[b.symbol]
        if h and b.open_time <= h[-1][0]:
            return
        h.append((b.open_time, b.open, b.high, b.low, b.close, b.volume if b.volume is not None else np.nan))

    def complete(self, boundary: int) -> bool:
        return True

    def due(self, boundary: int) -> list[str]:
        return [tf for tf in ("5m", "15m", "30m", "1h", "4h") if boundary % TF_MS[tf] == 0]

    def compute(self, boundary, tf, now_ms, book):
        self.computed.append((boundary, tf))
        if (boundary, tf) in self.timeout_at:
            raise SignalTimeout("signal workers did not answer within 1s")
        rows, subs = [], []
        ready_at = now_ms()
        prices = book()
        for aid, side, sym, ctx in self.fire.get((boundary, tf), []):
            name = aid.split("@")[0]
            bid, ask = prices[sym]
            ref = ask if side > 0 else bid
            rows.append({"bar_close": boundary, "timeframe": tf, "strategy": name, "symbol": sym, "side": side,
                         "atr": self.atr, "ref_price": ref, "ref_time": ready_at, "delay_ms": ready_at - boundary,
                         "status": "SUBMITTED", "data": {"close": 100.0, "bid": bid, "ask": ask, "ctx": ctx}})
            subs.append((aid, Signal(ts=boundary - 1, symbol=sym, timeframe=tf, strategy_id=name, side=side,
                                     stop_price=0.0, tier="best", atr=self.atr,
                                     meta={"stop_dist": 2.0 * self.atr, "ref_price": ref, "ref_time": ready_at,
                                           "delay_ms": ready_at - boundary, "account": aid, "ctx": ctx})))
        return rows, subs, []


def bootstrap(service: FakeService, start: int, n: int = 1500, seed: int = 3) -> None:
    """Random-walk 5m history ending just before ``start`` for every symbol."""
    rng = np.random.default_rng(seed)
    for sym in service.symbols:
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
        o = np.r_[100.0, c[:-1]]
        h = np.maximum(o, c) * 1.001
        lo = np.minimum(o, c) * 0.999
        v = rng.lognormal(3, 0.5, n)
        t0 = start - n * FIVE
        for i in range(n):
            service.hist[sym].append((t0 + i * FIVE, float(o[i]), float(h[i]), float(lo[i]), float(c[i]), float(v[i])))


class World:
    """One runner process on ``tmp/paper3.db`` with extras. ``start_at``: when the extras feature starts
    (``since``); the original accounts are created at T0 (the run start)."""

    def __init__(self, tmp, *, observe_days: float = 0, owner_ok_days: float = 60, start_at: int = T0,
                 config_path: Optional[str] = None, strategies=STRATS, tfs=TFS, min_parent_trades: Optional[int] = 0,
                 hist: bool = False, skip_before: Optional[int] = None, reopen: bool = False, extras: bool = True):
        from paperbot import extras as X
        from paperbot.agents import rooms_db as R
        self.X, self.R = X, R
        self.tmp = str(tmp)
        self.db = os.path.join(self.tmp, "paper3.db")
        self.agents_path = os.path.join(self.tmp, "agents3.db")
        self.inbox_path = os.path.join(self.tmp, "inbox.db")
        self.now = start_at
        self.store = Store3(self.db)
        self.notifier = ListNotifier()
        self.digest = Digest(ListNotifier())
        self.book = AccountBook(S, BR, self.store, self.notifier, digest=self.digest)
        self.service = FakeService(names36())
        if hist:
            bootstrap(self.service, start_at)
        self.ext = None
        make_of = None
        if extras:
            cfg = None if config_path else X.Config(agents_db=self.agents_path, inbox_db=self.inbox_path,
                                                    observe_days=observe_days, owner_ok_days=owner_ok_days)
            self.ext = X.Extras.start(self.store, self.notifier, self.db, S, config=cfg,
                                      config_path=config_path, now_ms=lambda: self.now,
                                      newlab_factory=self._newlab_factory)
            make_of = self.ext.make_of
        restored = self.book.load(make_of=make_of)
        if not restored:
            defs = [{"strategy": s, "timeframe": tf, "kind": "strategy"} for tf in tfs for s in strategies]
            defs += [{"strategy": "RANDOM_1", "timeframe": tf, "kind": "random"} for tf in tfs]
            self.book.open_accounts(defs, T0)
        self.store.commit()
        self.runner = Runner3(self.book, self.service, self.store, self.notifier, V3_SYMBOLS, lambda: self.now,
                              self.prices, skip_before=skip_before, digest=self.digest)
        if self.ext is not None:
            self.ext.bind(self.runner)
            self.ext.activator.min_parent_trades = min_parent_trades
        self.agents = R.open_agents(self.agents_path)
        self.inbox = R.open_inbox_rw(self.inbox_path)
        self.px = 100.0

    def _newlab_factory(self, service):
        from paperbot.newlab_live import NewlabSignals
        return NewlabSignals(service, windows=NL_WINDOWS, min_bars=NL_MIN_BARS)

    # ------------------------------------------------------------ market
    def prices(self) -> dict:
        return {s: (self.px * 0.9999, self.px * 1.0001) for s in V3_SYMBOLS}

    def bars(self, ts: int, px: Optional[float] = None, hi: float = 0.0005, lo: float = 0.0005) -> dict:
        p = self.px if px is None else px
        return {s: Bar(s, ts, ts + MIN - 1, p, p * (1 + hi), p * (1 - lo), p, volume=1.0)
                for s in list(V3_SYMBOLS) + ["XRPUSDT"] if s in self.service.hist or s in V3_SYMBOLS}

    def process(self, ts: int, px: Optional[float] = None, live: bool = True, **kw) -> None:
        """One 1m step at ``ts`` through the real runner (the boundary ts + 1m is live when ``live``)."""
        if px is not None:
            self.px = px
        self.now = ts + 61_500 if live else ts + 10 * MIN
        self.runner.process([(ts, self.bars(ts, **kw), {})])

    def run(self, t0: int, t1: int, **kw) -> None:
        t = t0
        while t < t1:
            self.process(t, **kw)
            t += MIN

    def boundary(self, b: int, submitted=None, timed_out: bool = False, age_ms: int = 1_500) -> None:
        """Only the hook at boundary ``b`` (the book's last step is b - 1m)."""
        if self.book.last_ts is None or self.book.last_ts < b - MIN:
            self.book.step(b - MIN, self.bars(b - MIN))
        self.now = b + age_ms
        self.ext.post_boundary(b, submitted or [], timed_out)

    # ------------------------------------------------------------ fixtures
    def copy_proposal(self, strategy="V45_AMB", tf="15m", rule=None, ts=None, **kw) -> tuple[int, int]:
        rule = rule or {"template": "stop_atr", "k": 2.5}
        return add_copy_proposal(self.agents, self.inbox, strategy, tf, rule, self.now if ts is None else ts, **kw)

    def newlab_proposal(self, i: int = 0, ts=None, **kw) -> tuple[int, int]:
        return add_newlab_proposal(self.agents, self.inbox, newlab_spec(i), self.now if ts is None else ts, **kw)

    def extras_rows(self) -> list[dict]:
        return [a for a in self.store.accounts() if a["kind"] not in ("strategy", "random")]

    def state(self) -> dict:
        return self.ext.state

    def refused(self, pid: int) -> Optional[dict]:
        return self.ext.state["refused"].get(str(pid))

    def close(self) -> None:
        for c in (self.agents, self.inbox):
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        self.store.close()
