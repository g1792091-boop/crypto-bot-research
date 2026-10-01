"""All paper v3 accounts in one process: one ``PaperEngine`` per account.

An account is one strategy on one timeframe (``"V45_AMB@15m"``), a coin-flip
account (``"RANDOM_1@15m"``), or an extra account started by the runtime from an
approved proposal (paperbot/extras.py: a copy ``"S@15m~c1"`` with ``parent`` set, or
a new strategy ``"NL1@1h"``). Every engine sees the same 1m bars; each receives
only its own signals.

After every step the book writes each engine's state to the store, so a
restart continues exactly where it stopped (``AccountBook.load``).

The original accounts (kinds in ``ORIGINAL_KINDS``) always get the book's own
settings object, ``PaperEngine`` and the book's digest. Only an extra account may
be built differently: ``load(make_of)`` and ``add_extra`` take per-account
settings / engine class / digest, and ``HeldEngine`` keeps an account frozen.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

from .config import Settings
from .engine import PaperEngine, engine_state, restore_engine
from .margin import Brackets
from .models import Bar, Signal
from .notify import CRITICAL, WARN, Digest, NullNotifier, Notifier
from .store3 import Store3

STATE_KEY = "accounts"
DAY_MS = 86_400_000
ORIGINAL_KINDS = ("strategy", "random")


def day_key(ts: int) -> str:
    import datetime as _dt
    return "day:" + _dt.datetime.fromtimestamp(ts / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")


def account_id(strategy: str, timeframe: str) -> str:
    return f"{strategy}@{timeframe}"


class _StoreNotifier:
    """Per-account messages go to the store. CRITICAL ones (liquidation, operator
    action) are forwarded at once; WARN ones (bust, drawdown levels) go to the
    digest, which sends them as one silent message per hour, so 195 accounts do
    not flood Telegram. INFO stays on the dashboard."""

    def __init__(self, store: Store3, forward: Notifier, clock, digest: Optional[Digest] = None):
        self.store, self.forward, self.clock, self.digest = store, forward, clock, digest

    def send(self, level: str, text: str) -> None:
        self.store.alert(self.clock(), level, text)
        if level == CRITICAL:
            self.forward.send(level, text)
        elif level == WARN and self.digest is not None:
            self.digest.add(text)


class HeldEngine(PaperEngine):
    """An account kept exactly as saved: ``step`` and ``submit`` do nothing (no stop checks, no fills,
    equity flat at the saved state). Used for an extra account whose rules cannot be known."""

    def step(self, bars, funding=None) -> None:
        return None

    def submit(self, signal: Signal) -> None:
        return None


def hold_others(row: dict) -> Optional[dict]:
    """``load(make_of=...)`` when the extras code is unavailable: the originals as always, every other
    account held at its saved state."""
    return None if row.get("kind") in ORIGINAL_KINDS else {"cls": HeldEngine}


class AccountBook:
    def __init__(self, settings: Settings, brackets: dict[str, Brackets], store: Store3,
                 notifier: Optional[Notifier] = None, specs: Optional[dict] = None,
                 equity_every_ms: int = 300_000, save_every: int = 1, digest: Optional[Digest] = None):
        self.s = settings
        self.digest = digest
        self.brackets = brackets
        self.store = store
        self.notifier = notifier or NullNotifier()
        self.specs = specs or {}
        self.equity_every_ms = equity_every_ms
        self.save_every = save_every  # steps between state snapshots (1 = every step, the live setting)
        self._steps = 0
        self.engines: dict[str, PaperEngine] = {}
        self.meta: dict[str, dict] = {}
        self.last_ts: Optional[int] = None
        self._now = 0

    # ------------------------------------------------------------ setup
    def _make(self, aid: str, settings: Optional[Settings] = None, cls=None,
              digest: Optional[Digest] = None) -> PaperEngine:
        """One engine. The defaults (the book's settings object, PaperEngine, the book's digest) are
        what every original account gets; an extra account may pass its own."""
        def on_trade(rec, aid=aid):
            self.store.trade(aid, rec)

        def on_outcome(out, aid=aid):
            self.store.outcome(aid, out)

        settings = self.s if settings is None else settings
        cls = PaperEngine if cls is None else cls
        digest = self.digest if digest is None else digest
        return cls(settings, self.brackets, notifier=_StoreNotifier(self.store, self.notifier,
                                                                   lambda: self._now, digest),
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

    def load(self, make_of: Optional[Callable[[dict], Optional[dict]]] = None) -> bool:
        """Rebuild every account listed in the store and restore its state.
        Returns False when the store holds no saved state (a fresh start).
        ``make_of(row)``: how to build an account (None = the defaults; else keyword arguments of
        ``_make``: settings, cls, digest). It is asked for every row; an exception holds that extra account
        (``HeldEngine``) instead of stopping the load (an original account always gets the defaults)."""
        for a in self.store.accounts():
            if a["account_id"] not in self.engines:
                how = None
                if make_of is not None:
                    try:
                        how = make_of(a)
                    except Exception:  # noqa: BLE001  an extra the runtime cannot build is held, never fatal
                        how = None if a.get("kind") in ORIGINAL_KINDS else {"cls": HeldEngine}
                self.engines[a["account_id"]] = self._make(a["account_id"], **(how or {}))
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

    def add_extra(self, d: dict, created_ts: int, settings: Optional[Settings] = None, cls=None,
                  digest: Optional[Digest] = None) -> PaperEngine:
        """Add one extra account (accounts row + a fresh engine at the initial equity) inside the
        caller's transaction (no commit). ``d``: account_id, strategy, timeframe, kind, parent, data.
        Raises ValueError when the id is already a running engine or an accounts row."""
        aid = d["account_id"]
        if aid in self.engines:
            raise ValueError(f"account {aid} is already running")
        if self.store.conn.execute("SELECT 1 FROM accounts WHERE account_id = ?", (aid,)).fetchone():
            raise ValueError(f"account {aid} already exists")
        self.store.add_account(aid, d["strategy"], d["timeframe"], d["kind"], created_ts, self.s.version,
                               d.get("parent"), d.get("data"))
        e = self._make(aid, settings=settings, cls=cls, digest=digest)
        self.engines[aid] = e
        self.meta[aid] = {"strategy": d["strategy"], "timeframe": d["timeframe"], "kind": d["kind"]}
        return e

    def remove(self, aid: str) -> None:
        """Forget an engine (only to undo an extra whose creation was rolled back)."""
        self.engines.pop(aid, None)
        self.meta.pop(aid, None)

    # ------------------------------------------------------------ run
    def submit(self, aid: str, sig: Signal) -> None:
        self.engines[aid].submit(sig)

    def step(self, ts: int, bars: dict[str, Bar], funding: Optional[dict[str, float]] = None) -> None:
        """One aligned 1m step for every account. ``ts`` is the bar open time.
        At 00:00 UTC the state before the step is kept as ``day:<YYYY-MM-DD>`` so the
        nightly check (daily3.py) can replay the day from it."""
        self._now = ts
        if ts % DAY_MS == 0:
            self.store.put_state(day_key(ts), ts, {
                "engines": {aid: engine_state(e) for aid, e in self.engines.items()}})
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
        self._steps += 1
        if self._steps % self.save_every == 0:
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
