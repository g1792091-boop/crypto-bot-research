"""All paper v3 accounts in one process: one ``PaperEngine`` per account.

An account is one strategy on one timeframe (``"V45_AMB@15m"``), a coin-flip
account (``"RANDOM_1@15m"``), or later an improved copy approved by the agent
team (its own id, ``parent`` set). Every engine sees the same 1m bars; each
receives only its own signals.

After every step the book writes each engine's state to the store, so a
restart continues exactly where it stopped (``AccountBook.load``).
"""

from __future__ import annotations

from typing import Iterable, Optional

from .config import Settings
from .engine import PaperEngine, engine_state, restore_engine
from .margin import Brackets
from .models import Bar, Signal
from .notify import CRITICAL, NullNotifier, Notifier
from .store3 import Store3

STATE_KEY = "accounts"


def account_id(strategy: str, timeframe: str) -> str:
    return f"{strategy}@{timeframe}"


class _StoreNotifier:
    """Per-account messages go to the store; only CRITICAL ones (liquidation,
    operator action) are forwarded, so 195 accounts do not flood Telegram."""

    def __init__(self, store: Store3, forward: Notifier, clock):
        self.store, self.forward, self.clock = store, forward, clock

    def send(self, level: str, text: str) -> None:
        self.store.alert(self.clock(), level, text)
        if level == CRITICAL:
            self.forward.send(level, text)


class AccountBook:
    def __init__(self, settings: Settings, brackets: dict[str, Brackets], store: Store3,
                 notifier: Optional[Notifier] = None, specs: Optional[dict] = None,
                 equity_every_ms: int = 300_000):
        self.s = settings
        self.brackets = brackets
        self.store = store
        self.notifier = notifier or NullNotifier()
        self.specs = specs or {}
        self.equity_every_ms = equity_every_ms
        self.engines: dict[str, PaperEngine] = {}
        self.meta: dict[str, dict] = {}
        self.last_ts: Optional[int] = None
        self._now = 0

    # ------------------------------------------------------------ setup
    def _make(self, aid: str) -> PaperEngine:
        def on_trade(rec, aid=aid):
            self.store.trade(aid, rec)

        def on_outcome(out, aid=aid):
            self.store.outcome(aid, out)

        return PaperEngine(self.s, self.brackets, notifier=_StoreNotifier(self.store, self.notifier,
                                                                        lambda: self._now),
                           symbol_specs=self.specs, on_trade=on_trade, on_outcome=on_outcome,
                           book=aid)

    def open_accounts(self, defs: Iterable[dict], now_ms: int) -> None:
        """defs: dicts with strategy, timeframe, kind and optional account_id / parent / data.
        Existing accounts keep their state; new ones start at the initial equity."""
        for d in defs:
            aid = d.get("account_id") or account_id(d["strategy"], d["timeframe"])
            self.store.add_account(aid, d["strategy"], d["timeframe"], d["kind"], now_ms,
                                   self.s.version, d.get("parent"), d.get("data"))
            if aid not in self.engines:
                self.engines[aid] = self._make(aid)
                self.meta[aid] = {"strategy": d["strategy"], "timeframe": d["timeframe"], "kind": d["kind"]}
        self.store.commit()

    def load(self) -> bool:
        """Rebuild every account listed in the store and restore its state.
        Returns False when the store holds no saved state (a fresh start)."""
        for a in self.store.accounts():
            if a["account_id"] not in self.engines:
                self.engines[a["account_id"]] = self._make(a["account_id"])
                self.meta[a["account_id"]] = {k: a[k] for k in ("strategy", "timeframe", "kind")}
        got = self.store.get_state(STATE_KEY)
        if got is None:
            return False
        ts, data = got
        for aid, st in data["engines"].items():
            if aid in self.engines:
                restore_engine(self.engines[aid], st)
        self.last_ts = data.get("last_ts")
        return True

    # ------------------------------------------------------------ run
    def submit(self, aid: str, sig: Signal) -> None:
        self.engines[aid].submit(sig)

    def step(self, ts: int, bars: dict[str, Bar], funding: Optional[dict[str, float]] = None) -> None:
        """One aligned 1m step for every account. ``ts`` is the bar open time."""
        self._now = ts
        for aid, e in self.engines.items():
            e.step(bars, funding)
            e.outcomes.clear()  # already written to the store
        close = max(b.close_time for b in bars.values()) + 1 if bars else ts
        if close % self.equity_every_ms == 0:
            for aid, e in self.engines.items():
                eq = e.equity()
                dd = 1 - eq / e.peak_equity if e.peak_equity > 0 else 0.0
                self.store.equity(aid, close, eq, dd)
        self.last_ts = ts
        self.save(ts)

    def save(self, ts: int) -> None:
        self.store.put_state(STATE_KEY, ts, {
            "last_ts": self.last_ts,
            "engines": {aid: engine_state(e) for aid, e in self.engines.items()},
        })
        self.store.commit()

    # ------------------------------------------------------------ report
    def board(self) -> list[dict]:
        rows = []
        for aid, e in self.engines.items():
            p = e.position
            rows.append({
                "account_id": aid, **self.meta[aid], "equity": e.equity(), "wallet": e.wallet,
                "max_drawdown": e.max_drawdown, "bust": e.bust, "halted": e.halted,
                "position": None if p is None else {
                    "symbol": p.symbol, "side": p.side, "leverage": p.leverage, "entry": p.entry_price,
                    "stop": p.stop_price, "lock_roe": p.lock_roe, "liq": p.liq_price},
            })
        return rows
