"""A small live world for 못 탄 신호 성적 (tests/test_livesim.py, tests/test_livemissed.py, tests/test_dash_livebots_missed.py and the
offline screenshots): the combined paper bot (paperbot/combo.py) REALLY runs over it, minute by minute, with its own
``ComboRunner``, ``AccountBook`` and ``ComboEngine``, so every trade, every ENTERED and every SKIPPED outcome in its database
is the bot's own record, never written by hand.

- the rule bot's paper3.db: 1m bars (``live_bars`` through store3's own writer, mark fields = last price) of the six coins,
  each a piecewise-linear price path (``PATHS``), and ``signal_log`` rows (status SUBMITTED) of two default members
  (V39_ALL 15m = order 1, OBV_S 15m = order 2) at their bar closes, the way the rule bot writes them;
- the paper bot's live-ac.db: ``combo.build_book`` + ``ComboRunner.poll`` once per minute (the clock 65 s after the minute
  opened, so no signal is late), its ``combo_run`` record as cmd_run writes it; the leverage brackets and coin specs of
  the repository's saved Binance table (research/fullgrid/exchange.json: what paperbot/livesim.py uses);
- the live config's rules (BTC 40x / others 30x, margin 40 %, stop 3 ATR pulled in to fit, loss cap 35 %, ladder: lock
  10 % at 11 %, then 3 % steps, rank by list order), no weekend / macro pause (no events file needed);
- funding (``funding=True``): one BTC rate (0.01 %) paid at T0 + 20 min, through the runner's funding feed.

The script (T0 = 2026-10-19 00:00 UTC = Monday 09:00 KST; B1 = T0 + 15 min):
  B1      V39_ALL BTC long (entered: 40x)  +  OBV_S ETH short (same minute, order 2: SKIPPED "lower score than entered signal")
  B1+15m  OBV_S SOL long while BTC is open: SKIPPED "in position" (held BTC)
          BTC climbs to +0.67 % by B1+25m (best net ROE ~20 %: lock 19 %), falls back: exit LOCK
          SOL climbs to +0.67 % by B1+75m, falls to -0.67 % by B1+135m: its virtual trade locks and exits LOCK (~+13 %)
          ETH climbs 1.6 % by B1+60m: the ETH short's virtual trade is stopped (SL)
  B1+60m  V39_ALL ETH long (entered: 30x), ETH falls to 2,480 by B1+90m: SL
  B1+120m a BCH long with a research stop (rstop ["pct", 1.0]) submitted to the engine directly (entered), a DOGE long of
          a later setting in the same minute (SKIPPED "lower score"); BCH climbs and locks, DOGE stays flat
"""
from __future__ import annotations

import dataclasses
import os
from typing import Optional

from paperbot import combo as C
from paperbot import livereplay as LR
from paperbot.models import Signal
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

MIN = 60_000
H = 3_600_000
DAY = 86_400_000
T0 = 1_792_368_000_000                     # 2026-10-19 00:00 UTC (09:00 KST, Monday)
B1 = T0 + 15 * MIN
SYMS = C.V3_SYMBOLS
BASE = {"BTCUSDT": 60000.0, "ETHUSDT": 2500.0, "SOLUSDT": 150.0, "DOGEUSDT": 0.2, "LTCUSDT": 80.0, "BCHUSDT": 400.0}
# price knots (ms, price): linear in between, flat before the first and after the last
PATHS = {
    "BTCUSDT": [(T0, 60000.0), (B1, 60000.0), (B1 + 25 * MIN, 60400.0), (B1 + 45 * MIN, 59800.0)],
    "ETHUSDT": [(T0, 2500.0), (B1, 2500.0), (B1 + 60 * MIN, 2540.0), (B1 + 90 * MIN, 2480.0)],
    "SOLUSDT": [(T0, 150.0), (B1 + 15 * MIN, 150.0), (B1 + 75 * MIN, 151.0), (B1 + 135 * MIN, 149.0)],
    "DOGEUSDT": [(T0, 0.2)],
    "LTCUSDT": [(T0, 80.0)],
    "BCHUSDT": [(T0, 400.0), (B1 + 120 * MIN, 400.0), (B1 + 150 * MIN, 403.0), (B1 + 170 * MIN, 398.0)],
}
ATR_FRAC = 0.002
MEMBERS = [{"strategy": "V39_ALL", "tf": "15m"}, {"strategy": "OBV_S", "tf": "15m"}]
CONFIG = {"name": "시험 합본", "initial_equity": 1000.0, "leverage": {"BTCUSDT": 40, "default": 30}, "margin": 0.4,
          "max_loss_frac": 0.35, "loss_cap": "shrink", "stop": {"mode": "atr_fit", "atr": 3.0, "min_atr": 1.0},
          "ladder": {"first_lock": 0.1, "step": 0.03, "trigger_gap": 0.01}, "rank": ["order"], "flip_twin": True,
          "members": MEMBERS, "telegram": False}
# (bar close, strategy, coin, side) logged by the rule bot
SIGNALS = [(B1, "V39_ALL", "BTCUSDT", 1), (B1, "OBV_S", "ETHUSDT", -1), (B1 + 15 * MIN, "OBV_S", "SOLUSDT", 1),
           (B1 + 60 * MIN, "V39_ALL", "ETHUSDT", 1)]
# research-stop signals submitted to the paper engine directly at their minute (the runner's research path needs Binance)
DIRECT_T = B1 + 120 * MIN
FUNDING = {B1 + 5 * MIN: {"BTCUSDT": 0.0001}}
END = B1 + 200 * MIN                       # every trade and virtual trade of the script is closed by then


def price(sym: str, t: int) -> float:
    k = PATHS[sym]
    if t <= k[0][0]:
        return k[0][1]
    for (a, pa), (b, pb) in zip(k, k[1:]):
        if a <= t <= b:
            return pa + (pb - pa) * (t - a) / (b - a)
    return k[-1][1]


def bar_row(sym: str, t: int) -> dict:
    o, c = price(sym, t), price(sym, t + MIN)
    hi, lo = max(o, c) * 1.00005, min(o, c) * 0.99995
    return {"ts": t, "symbol": sym, "open": o, "high": hi, "low": lo, "close": c, "volume": 10.0, "mark_open": o,
            "mark_high": hi, "mark_low": lo, "mark_close": c, "close_time": t + MIN - 1, "processed_at": t + MIN + 5_000}


class _Fund:
    """The funding feed the runner reads (livereplay._Fund's shape): rates paid at the first step at or after them."""

    def __init__(self, rates: dict):
        self.rates = {int(k): dict(v) for k, v in rates.items()}

    def poll(self, now: int) -> None:
        pass

    def take(self, ts: int) -> dict:
        out = {}
        for t in [k for k in self.rates if k <= ts]:
            out.update(self.rates.pop(t))
        return out


def direct_signals() -> list:
    """The two signals handed to the engine at DIRECT_T: a BCH long with a research 1 % stop (order 1, entered) and a DOGE
    long (order 2, the same minute: SKIPPED "lower score than entered signal")."""
    out = []
    for sym, order, member in (("BCHUSDT", 1, "V39_ALL@15m#1~pct1"), ("DOGEUSDT", 2, "OBV_S@15m#2~pct1")):
        ref = price(sym, DIRECT_T)
        atr = ref * ATR_FRAC
        out.append(Signal(ts=DIRECT_T - 1, symbol=sym, timeframe="15m", strategy_id=member.split("@")[0], side=1, stop_price=0.0,
                          tier="best", score=3.0, atr=atr,
                          meta={"stop_dist": 3.0 * atr, "ref_time": DIRECT_T + 20_000, "delay_ms": 20_000, "account": C.ACCOUNT,
                                "member": member, "member_order": order, "source": "custom", "score_raw": None, "ctx": {},
                                "ref_price": ref, "research": True, "rstop": ["pct", 1.0]}))
    return out


class LiveWorld:
    """paper3.db (the rule bot) and live-ac.db (the paper bot) in ``folder``; ``run_to(t)`` steps the paper bot to minute t."""

    def __init__(self, folder: str, funding: bool = True, direct: bool = True):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.rule_db = os.path.join(folder, "paper3.db")
        self.paper_db = os.path.join(folder, "live-ac.db")
        self.rule = Store3(self.rule_db)
        self.cfg = C.ComboConfig.from_dict({**CONFIG, "paper_db": self.rule_db, "db": self.paper_db})
        self.members = C.resolve_members(self.cfg.members, core=["V39_ALL", "OBV_S"])
        self.settings = C.settings_of(self.cfg, taker_fee=0.0005)
        self.brackets, src = LR.file_brackets(SYMS)
        self.specs = LR.file_specs(SYMS)
        self.store = Store3(self.paper_db)
        self.note = ListNotifier()
        self.book = C.build_book(self.cfg, self.settings, self.brackets, self.store, self.note, self.specs)
        self.store.put_state("combo_run", T0 - 10 * MIN, {"version": C.VERSION, "brackets": src, "taker_fee": self.settings.taker_fee,
                                                         "members": [m.describe() for m in self.members],
                                                         "config": dataclasses.asdict(self.cfg)})
        self.store.commit()
        self.now = T0 - 9 * MIN
        self.fund = _Fund(FUNDING if funding else {})
        self.direct = direct
        self.run = C.ComboRunner(self.cfg, self.members, self.book, self.store, self.note, None, now_ms=lambda: self.now,
                                 prices=lambda: {}, funding=self.fund)
        self.t = T0 - 10 * MIN                       # the next minute to write
        self._minute(self.t)                           # the rule bot is already running
        self.t += MIN
        self.run.poll()                                # first start: from the rule bot's latest minute

    def _minute(self, t: int) -> None:
        sigs = [s for s in SIGNALS if s[0] == t]
        if sigs:
            rows = []
            for bc, strat, sym, side in sigs:
                ref = price(sym, bc)
                rows.append({"bar_close": bc, "timeframe": "15m", "strategy": strat, "symbol": sym, "side": side,
                             "atr": ref * ATR_FRAC, "ref_price": ref, "ref_time": bc + 20_000, "delay_ms": 20_000,
                             "status": "SUBMITTED", "data": {"ctx": {}}})
            self.rule.log_signals(rows)
        self.rule.live_bars([bar_row(s, t) for s in SYMS])
        self.rule.commit()

    def run_to(self, t_end: int) -> "LiveWorld":
        """Write and step every minute before ``t_end``."""
        while self.t < t_end:
            t = self.t
            self._minute(t)
            if self.direct and t == DIRECT_T:
                for sig in direct_signals():
                    self.book.engines[C.ACCOUNT].submit(sig)
            self.now = t + 65_000
            self.run.poll()
            self.t += MIN
        return self

    def engine(self, aid: str = C.ACCOUNT):
        return self.book.engines[aid]

    def close(self) -> None:
        self.store.close()
        self.rule.close()


def build(folder: str, until: Optional[int] = END, **kw) -> LiveWorld:
    w = LiveWorld(folder, **kw)
    if until is not None:
        w.run_to(until)
    return w
