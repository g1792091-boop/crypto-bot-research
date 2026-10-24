"""미리 보기: every live Telegram message type of paperbot/livecheck.py, built from a hand-made world.

    python -m paperbot.livecheck preview          the running bot's world: 규칙봇 15 (deploy/combo.live15.json, both
                                                  executors without the signal light and without the loss-streak and
                                                  drawdown halts, owners 10-19)
    python -m paperbot.livecheck preview --old    the A+C bot's world (deploy/combo.live-ac.json: the light, the halts,
                                                  the 5-year reference, the 40-trade checkpoint, the break waits)
    python -m paperbot.livecheck preview --two    two paper bots (docs/live15-mexc-ko.md): Bybit follows 규칙봇 15
                                                  (-50 %), MEXC its -35 % twin (deploy/combo.live15-mexc.json): the
                                                  switch, one entry in both, the -35 % stop alone, the morning check
    python -m paperbot.livecheck preview --vwap   two different paper bots (docs/vwap-bot-ko.md): the 추세판단 봇 and
                                                  'VWAP 개선판' ITSELF (VwapBot: the real bot on deploy/combo.vwap.json),
                                                  paper-only first, then Bybit follows it and WOO X Pro the trend bot
    python -m paperbot.livecheck preview --deepcoin  three executors (docs/deepcoin-ko.md): Bybit and WOO X Pro follow the
                                                  추세판단 봇, the third, 딥코인, follows 'VWAP 개선판' ITSELF: its
                                                  start, one minute both bots enter, both win, the morning check

It writes small databases in the real schemas into a temporary folder (the paper bot's paperbot.store3, the rule
bot's 1m bars, and the executors' own tables, copied here as ``EXEC_SCHEMA`` so this module never imports the
executor; tests/test_livecheck.py keeps it equal to paperbot/executor.py), steps the clock, and runs the real code
paths (the watcher's ``run_watch``, the morning check's ``run_check`` with a replay result injected). Nothing goes to
the network, nothing is sent, nothing outside the temporary folder is written. Each message is printed as Telegram
shows it (notify.telegram_text), with "소리" / "무음" as TELEGRAM_SOUND=critical (the live chats) rings it.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import asdict, dataclass
from typing import Optional

from . import livecheck as LC
from . import livereplay as LR
from .models import Signal, SignalOutcome, TradeRecord
from .store3 import Store3

MIN, H1, DAY = LC.MIN, LC.H1, LC.DAY
EXEC_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, level TEXT NOT NULL,
    kind TEXT NOT NULL, text TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, method TEXT NOT NULL,
    path TEXT NOT NULL, status INTEGER, code INTEGER, error TEXT, params TEXT NOT NULL, data TEXT);
CREATE TABLE IF NOT EXISTS trades (key TEXT PRIMARY KEY, symbol TEXT NOT NULL, side INTEGER NOT NULL, qty REAL NOT NULL,
    leverage INTEGER NOT NULL, entry_ts INTEGER NOT NULL, entry_price REAL, stop_initial REAL, exit_ts INTEGER,
    exit_reason TEXT, pnl REAL, data TEXT NOT NULL DEFAULT '{}', mode TEXT, pnl_source TEXT, realized REAL,
    commission REAL, funding REAL, slippage REAL, real_cost REAL, assumed_cost REAL, cost_ok INTEGER);
CREATE TABLE IF NOT EXISTS halts (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, action TEXT NOT NULL,
    reason TEXT NOT NULL, who TEXT, note TEXT, planned INTEGER);
CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fills (symbol TEXT NOT NULL, id INTEGER NOT NULL, trade_key TEXT NOT NULL,
    ts INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (symbol, id));
CREATE TABLE IF NOT EXISTS funding (symbol TEXT NOT NULL, tran_id INTEGER NOT NULL, trade_key TEXT NOT NULL,
    ts INTEGER NOT NULL, income REAL NOT NULL, data TEXT NOT NULL, PRIMARY KEY (symbol, tran_id));
CREATE TABLE IF NOT EXISTS equity (ts INTEGER PRIMARY KEY, equity REAL NOT NULL, wallet REAL NOT NULL,
    transfers REAL);
"""
BTC, SOL, ETH = "BTCUSDT", "SOLUSDT", "ETHUSDT"
LON = ("F15_LON_BRK", "1h", 88)                  # strategy, tf, setting number (member_order) in the A+C config
ASIA = ("F15_ASIA_BRK", "30m", 37)
V39 = ("V39_ALL", "1h", 1)                       # ... in the 규칙봇 15 config (deploy/combo.live15.json)
CMO = ("S3_CMO_SANDWICH", "30m", 2)
BOS = ("F3_BOS", "30m", 12)


@dataclass(frozen=True)
class Profile:
    """The configs a preview world runs: the paper bot's config file, each executor's light (N, share) and halts."""
    key: str
    config: str                      # deploy/<file>
    lights: tuple                    # ((N, share) Bybit, (N, share) MEXC); N 0 = no light
    streak: Optional[int]            # the executors' loss-streak halt (None: none)
    dd: Optional[float]              # ... and drawdown halt
    main: tuple                      # the strategy of most trades
    alt: tuple


LIVE15 = Profile("live15", "combo.live15.json", ((0, 0.85), (0, 0.90)), None, None, V39, CMO)
AC = Profile("ac", "combo.live-ac.json", ((20, 0.85), (20, 0.90)), 3, 0.5, LON, ASIA)
# the 추세판단 봇 (deploy/combo.trend.json; owners 10-22: both executors follow it, no light) for the 'VWAP 개선판' scene
TREND = Profile("trend", "combo.trend.json", ((0, 0.85), (0, 0.90)), None, None, ("S3_CMO_SANDWICH", "30m", 2),
                ("V39_ALL", "1h", 5))


# ====================================================================== the world
class Collect:
    """A notifier that keeps what would be sent; like the Telegram notifier it gives message ids (``send_ids``), so a
    message edited later (the ⏳ wait turned into its result, ``edit``) is kept too, in its new form."""

    def __init__(self):
        self.items: list = []

    def send(self, level: str, text: str) -> bool:
        self.items.append((level, text))
        return True

    def send_ids(self, level: str, text: str) -> dict:
        self.items.append((level, text))
        return {"preview": len(self.items)}

    def edit(self, level: str, ids: dict, text: str) -> bool:
        self.items.append((level, text))
        return True


def _units(_unit: str) -> tuple:
    return ("active", "enabled")


NO_TG = {"base": None, "over": None, "over_exists": False, "over_mtime": None}


class World:
    """One paper bot, the rule bot's bars, two executors (Bybit $100, MEXC $100) as ``prof`` sets them up: 규칙봇 15 (no
    light, no loss-streak or drawdown halt) or the A+C bot (light 20 / 85% and 20 / 90%, 3 losses, 50%). ``three``: the
    third executor too (딥코인 $100, owners 10-24: its own config and database, the VWAP bot's light 20 / 75 %; the
    scene points it at its paper bot)."""

    def __init__(self, root: str, prof: Profile = None, three: bool = False):
        self.root = root
        self.prof = prof = prof or LIVE15
        self.paper = os.path.join(root, "live-ac.db")
        self.rule = os.path.join(root, "paper3.db")
        self.dbs = {"bybit": os.path.join(root, "bybit.db"), "mexc": os.path.join(root, "mexc.db")}
        if three:
            self.dbs["deepcoin"] = os.path.join(root, "deepcoin.db")
        for p in self.dbs.values():
            c = sqlite3.connect(p)
            c.executescript(EXEC_SCHEMA)
            c.commit()
            c.close()
        Store3(self.paper).conn.close()
        Store3(self.rule).conn.close()
        self.position: Optional[dict] = None
        (bn, bs), (mn, ms) = prof.lights
        kill = "/nonexistent/STOP" if prof is AC else "/var/lib/paperbot/STOP"     # 규칙봇 15's words name the file
        self.infos = [LC.ExecInfo("bybit", "/etc/paperbot/executor.json", "paperbot-executor", self.dbs["bybit"], bn,
                                  bs, exchange="bybit", budget=100.0, kill_file=kill,
                                  max_dd=prof.dd, max_streak=prof.streak, max_loss=0.35),
                      LC.ExecInfo("mexc", "/etc/paperbot/executor-mexc.json", "paperbot-executor-mexc",
                                  self.dbs["mexc"], mn, ms, exchange="mexc", budget=100.0,
                                  kill_file=kill, max_dd=prof.dd, max_streak=prof.streak,
                                  max_loss=0.35)]
        if three:
            self.infos.append(LC.ExecInfo("deepcoin", "/etc/paperbot/executor-deepcoin.json", "paperbot-executor-deepcoin",
                                          self.dbs["deepcoin"], 20, 0.75, exchange="deepcoin", budget=100.0,
                                          kill_file=kill, max_loss=0.2))

    def src(self) -> LC.Sources:
        # the second paper bot's file is this world's own (none unless a scene makes it): never the server's real one
        return LC.Sources(db=os.path.join(self.root, "livecheck.db"), paper_db=self.paper, rule_db=self.rule,
                          combo_config=os.path.join(LC.ROOT, "deploy", self.prof.config),
                          shadow_glob=os.path.join(self.root, "shadow-*.db"), executors=self.infos,
                          paper2_db=os.path.join(self.root, "vwap.db"))

    # ---- the paper bot
    def paper_trade(self, entry: int, exit_: int, roe: float, symbol=BTC, side=1, strat=None, price=67_250.0,
                    reason=None, lock=None, mfe=None, lev=40, stop=None, reg5=1, hr=None):
        strat = strat or self.prof.main
        margin = 400.0 if self.prof is AC else 300.0
        pnl = roe * margin
        stop = stop if stop is not None else price * (1 - side * 0.0123)
        exit_price = price * (1 + side * roe / lev)
        rec = TradeRecord(strategy_id=strat[0], symbol=symbol, timeframe=strat[1], side=side, signal_ts=entry - 1,
                          entry_time=entry, entry_price=price, exit_time=exit_, exit_price=exit_price,
                          exit_reason=reason or ("LOCK" if roe > 0 else "SL"), qty=margin * lev / price,
                          leverage=lev, tier="best", margin=margin, stop_price=stop, tp_price=float("nan"),
                          liq_price=price * (1 - side / lev), fees=0.4, funding=0.0, pnl=pnl, roe=roe,
                          price_move=roe / lev, mae_price=price, mfe_price=mfe or price * (1 + side * 0.003),
                          equity_after=1000 + pnl, score=3.0, stop_initial=stop, lock_roe=lock)
        s = Store3(self.paper)
        s.trade(LC.ACCOUNT, rec)
        hour = hr if hr is not None else int(LC.kst(entry, "%H"))
        if self.prof is AC:                              # the A+C bot's research settings
            meta = {"member": f"{strat[0]}@{strat[1]}#{strat[2]}~x", "member_order": strat[2],
                    "rdims": {"reg5": reg5, "hr": hour}, "rstop": ["atr", 3.0]}
        else:                                            # 규칙봇 15: the rule bot's default numbers, the -50% net stop
            meta = {"member": f"{strat[0]}@{strat[1]}", "member_order": strat[2], "stop_rule": f"ROE -50% net at {lev}x"}
        s.outcome(LC.ACCOUNT, SignalOutcome(Signal(ts=entry - 1, symbol=symbol, timeframe=strat[1],
                                                   strategy_id=strat[0], side=side, stop_price=stop, meta=meta),
                                            "ENTERED", "", entry))
        s.commit()
        s.conn.close()
        return pnl

    def open_position(self, entry: int, symbol=BTC, side=1, strat=None, price=67_250.0, stop=66_420.0, lev=40,
                      lock=None):
        strat = strat or self.prof.main
        sig = asdict(Signal(ts=entry - 1, symbol=symbol, timeframe=strat[1], strategy_id=strat[0], side=side,
                            stop_price=stop, meta={"member_order": strat[2]}))
        self.position = {"signal": sig, "symbol": symbol, "side": side, "qty": 400 * lev / price, "entry_price": price,
                         "entry_time": entry, "leverage": lev, "tier": "best", "margin": 400.0,
                         "margin_initial": 400.0, "stop_price": stop, "tp_price": None, "liq_price": 0.0,
                         "entry_fee": 0.2, "stop_initial": stop, "lock_roe": lock}

    def tick(self, now: int, heartbeat: Optional[int] = None, bars: bool = True):
        """The paper bot's state at ``now`` (its position, its heartbeat) and the rule bot's bars."""
        s = Store3(self.paper)
        s.put_state("accounts", now - MIN, {"last_ts": now - MIN, "engines": {
            LC.ACCOUNT: {"wallet": 1000.0, "position": self.position},
            LC.FLIP_ACCOUNT: {"wallet": 1000.0, "position": None}}})
        s.put_state("heartbeat", heartbeat if heartbeat is not None else now - 2000, {})
        s.commit()
        s.conn.close()
        for name in self.dbs:                            # the executors keep running: their state is fresh
            c = self._x(name)
            c.execute("UPDATE state SET ts = ? WHERE k = 'bot'", (now - 2000,))
            c.commit()
            c.close()
        if bars:
            r = Store3(self.rule)
            r.live_bars([{"ts": now - 2 * MIN, "symbol": BTC, "open": 1, "high": 1, "low": 1, "close": 1,
                          "processed_at": now - MIN}])
            r.commit()
            r.conn.close()

    # ---- an executor
    def _x(self, name: str):
        return sqlite3.connect(self.dbs[name])

    def x_state(self, name: str, ts: int, trade=None, **risk):
        r = {"halted": False, "halt_reason": "", "peak_equity": 107.87, "last_equity": 107.87, "transfers": 0.0}
        r.update(risk)
        c = self._x(name)
        c.execute("INSERT OR REPLACE INTO state VALUES ('bot', ?, ?)", (ts, json.dumps({
            "trade": trade, "done": [], "loops": 1, "mode": "mainnet", "account": LC.ACCOUNT, "risk": r})))
        c.execute("INSERT OR REPLACE INTO state VALUES ('meta', ?, ?)", (ts, json.dumps({
            "mode": "mainnet", "account": LC.ACCOUNT, "exchange": name, "live_since": ts - 30 * DAY})))
        c.commit()
        c.close()

    def x_event(self, name: str, ts: int, kind: str, text: str, data: Optional[dict] = None):
        c = self._x(name)
        c.execute("INSERT INTO events (ts, level, kind, text, data) VALUES (?,?,?,?,?)",
                  (ts, "INFO", kind, text, json.dumps(data or {}, ensure_ascii=False)))
        c.commit()
        c.close()

    def x_open(self, name: str, key: str, symbol: str, side: int, entry_ts: int, price: float, qty: float,
               stop: float, lev: int = 40):
        c = self._x(name)
        c.execute("INSERT OR REPLACE INTO trades (key, symbol, side, qty, leverage, entry_ts, entry_price, "
                  "stop_initial, data, mode) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (key, symbol, side, qty, lev, entry_ts, price, stop,
                   json.dumps({"key": key, "stop_initial": stop, "stop": stop, "qty": qty}), "mainnet"))
        c.commit()
        c.close()

    def x_close(self, name: str, key: str, exit_ts: int, pnl: float, entry_px: float, exit_px: float, qty: float,
                fee: float, side: int = 1):
        c = self._x(name)
        c.execute("UPDATE trades SET exit_ts = ?, exit_reason = ?, pnl = ?, commission = ? WHERE key = ?",
                  (exit_ts, "paper 청산", pnl, qty * (entry_px + exit_px) * fee, key))
        sym = c.execute("SELECT symbol FROM trades WHERE key = ?", (key,)).fetchone()[0]
        for i, (sd, px, ts) in enumerate((("BUY" if side > 0 else "SELL", entry_px, exit_ts - H1),
                                          ("SELL" if side > 0 else "BUY", exit_px, exit_ts))):
            c.execute("INSERT OR REPLACE INTO fills VALUES (?,?,?,?,?)",
                      (sym, (exit_ts // 1000) * 10 + i, key, ts, json.dumps({
                          "side": sd, "qty": qty, "price": px, "commission": qty * px * fee,
                          "commissionAsset": "USDT", "time": ts})))
        c.commit()
        c.close()

    def x_equity(self, name: str, ts: int, eq: float):
        c = self._x(name)
        c.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?,0)", (ts, eq, eq))
        c.commit()
        c.close()

    def watch(self, now: int, host: Optional[LC.Host] = None, units=_units, tg: Optional[dict] = None) -> list:
        """``tg``: the Telegram files as the watcher would read them (none by default: the server's real
        /etc/paperbot files never enter the preview)."""
        got = Collect()
        LC.run_watch(self.src(), now_ms=now, notifier=got, units=units, exists=lambda p: False,
                     host=host or LC.Host(disk_free=lambda p: 40 * 1024 ** 3, mem_available=lambda: 3 * 1024 ** 3,
                                          unit_memory=lambda: []),
                     tg=tg if tg is not None else NO_TG)
        return got.items


# ====================================================================== 'VWAP 개선판' itself (owners 10-23)
VWAP_CONFIG = "combo.vwap.json"
VWAP_PX = {"BTCUSDT": 67_250.0, "ETHUSDT": 2_415.0, "SOLUSDT": 182.35, "DOGEUSDT": 0.2045, "LTCUSDT": 92.4, "BCHUSDT": 512.0}


def gate_read(side: int, tf: str, up: int = 3, down: int = 0, atr_pct: float = 0.45, q_pct: float = 0.62) -> dict:
    """What the VWAP bot's entry gates read at a signal (paperbot/entrygates.py EntryGates.check's ``info``: the 4h vote
    and the signal bar's ATR% against its 30-day 80 % point, PERCENT numbers), in the gates' own words."""
    from .entrygates import vol_words, vote_words
    raw = 1 if up >= 3 else -1 if down >= 3 else 0
    return {"vote": {"tf": "4h", "bar_close": None, "votes": None, "up": up, "down": down, "raw": raw, "with_side": raw * side,
                     "text": vote_words("4h", raw, up, down)},
            "vol": {"tf": tf, "atr_pct": atr_pct, "q_pct": q_pct, "days": 30, "q": 0.8,
                    "text": vol_words(tf, atr_pct / 100, q_pct / 100, {"days": 30, "q": 0.8})}}


class ScriptGates:
    """The VWAP bot's entry gates answering from a script instead of Binance (paperbot/entrygates.EntryGates.check's
    shape): ``set(symbol, bar_close, why, info)``; anything else passes with gate_read's numbers."""

    def __init__(self):
        self.script: dict = {}
        self.asked: list = []

    def set(self, symbol: str, bar_close: int, why: str = "", info: Optional[dict] = None) -> None:
        self.script[(symbol, int(bar_close))] = (why, info)

    def check(self, symbol: str, tf: str, side: int, bar_close: int) -> tuple:
        self.asked.append((symbol, tf, int(side), int(bar_close)))
        why, info = self.script.get((symbol, int(bar_close)), ("", None))
        return why, (info if info is not None else gate_read(int(side), tf))

    def block(self, symbol: str, tf: str, side: int, bar_close: int) -> str:
        return self.check(symbol, tf, side, bar_close)[0]


class VwapBot:
    """'VWAP 개선판' itself (docs/vwap-bot-ko.md): paperbot/combo.py's ComboRunner with the owners' config
    (deploy/combo.vwap.json: VWAP 복귀 실패 30분 and CMO·샌드위치 캔들 1시간, 2 ATR stop, its ladder, 30x, margin 40 %, the
    96-bar hold limit) and its own database (combo_run as the bot writes it), over a rule-bot database written here
    (store3's writers: 1m bars of the coins in ``px`` and the rule bot's signal_log rows). Every entry, lock, exit
    ("TIME" with its "96봉(48시간) 지남"), outcome and FILTERED row is the bot's own; its entry gates answer from a script
    (ScriptGates: no network). ``move(symbol, t, price)``: the price walks there linearly by minute t."""

    def __init__(self, db: str, rule_db: str, start: int, px: Optional[dict] = None, cfg_over: Optional[dict] = None):
        import dataclasses
        from . import combo as C
        from .notify import ListNotifier
        with open(os.path.join(LC.ROOT, "deploy", VWAP_CONFIG), encoding="utf-8") as fh:
            raw = json.load(fh)
        raw.update(paper_db=rule_db, db=db, telegram=False, **(cfg_over or {}))
        self.C = C
        self.cfg = C.ComboConfig.from_dict(raw)
        self.members = C.resolve_members(self.cfg.members, self.cfg.picks_file)
        self.settings = C.settings_of(self.cfg, taker_fee=0.0005)
        syms = list(self.cfg.symbols)
        brackets, src = LR.file_brackets(syms)
        self.store = Store3(db)
        self.book = C.build_book(self.cfg, self.settings, brackets, self.store, ListNotifier(), LR.file_specs(syms))
        self.store.put_state("combo_run", start - 10 * MIN, {"version": C.VERSION, "brackets": src,
                                                             "taker_fee": self.settings.taker_fee,
                                                             "members": [m.describe() for m in self.members],
                                                             "config": dataclasses.asdict(self.cfg)})
        self.store.commit()
        self.rule = Store3(rule_db)
        self.px = dict(px or VWAP_PX)
        self.knots = {s: [(start - 10 * MIN, p)] for s, p in self.px.items()}
        self.gates = ScriptGates()
        self.now = start - 10 * MIN
        self.run = C.ComboRunner(self.cfg, self.members, self.book, self.store, ListNotifier(), None,
                                 now_ms=lambda: self.now, prices=lambda: {}, gates=self.gates)
        self.t = start - 10 * MIN                 # the next minute to write
        self.run_to(start)

    def price(self, sym: str, t: int) -> float:
        k = self.knots[sym]
        if t <= k[0][0]:
            return k[0][1]
        for (a, pa), (b, pb) in zip(k, k[1:]):
            if a <= t <= b:
                return pa + (pb - pa) * (t - a) / (b - a)
        return k[-1][1]

    def move(self, sym: str, t: int, price: float) -> None:
        """From the last knot (or now) the price walks linearly to ``price`` at minute ``t``."""
        last = self.knots[sym][-1]
        if last[0] < self.t:
            self.knots[sym].append((self.t, self.price(sym, self.t)))
        self.knots[sym].append((int(t), float(price)))

    def signal(self, strategy: str, symbol: str, side: int, bar_close: int, tf: Optional[str] = None,
               atr_frac: float = 0.008) -> None:
        """The rule bot's signal_log row of a bar closing at ``bar_close`` (reference price 20 s after it)."""
        tf = tf or {"F6_VWAP_FAIL": "30m", "S3_CMO_SANDWICH": "1h"}.get(strategy, "30m")
        ref = self.price(symbol, bar_close)
        self.rule.log_signals([{"bar_close": bar_close, "timeframe": tf, "strategy": strategy, "symbol": symbol,
                                "side": side, "atr": ref * atr_frac, "ref_price": ref, "ref_time": bar_close + 20_000,
                                "delay_ms": 20_000, "status": "SUBMITTED", "data": {"ctx": {}}}])
        self.rule.commit()

    def run_to(self, t_end: int) -> "VwapBot":
        """Write the 1m bars of every minute before ``t_end`` and let the bot step them (its clock 65 s after the last
        minute opened: a signal whose bar closed at the last minute's open is on time)."""
        rows = []
        while self.t < t_end:
            t = self.t
            for s in self.px:
                o, c = self.price(s, t), self.price(s, t + MIN)
                hi, lo = max(o, c) * 1.00005, min(o, c) * 0.99995
                rows.append({"ts": t, "symbol": s, "open": o, "high": hi, "low": lo, "close": c, "volume": 10.0,
                             "mark_open": o, "mark_high": hi, "mark_low": lo, "mark_close": c, "close_time": t + MIN - 1,
                             "processed_at": t + MIN + 5_000})
            self.t += MIN
        if rows:
            self.rule.live_bars(rows)
            self.rule.commit()
        self.now = self.t - MIN + 65_000
        for _ in range(20):
            if not self.run.poll():
                break
        return self

    def engine(self, aid: Optional[str] = None):
        return self.book.engines[aid or self.C.ACCOUNT]

    def close(self) -> None:
        self.store.close()
        self.rule.close()


def _history(w: World, start: int, wins: int, losses_at=(3, 9, 15), n: int = 20, strat=None, loss: Optional[float] = None):
    """``n`` closed paper trades before ``start``, losses at the given positions (``loss``: their net ROE)."""
    t = start - n * 12 * H1
    loss = loss if loss is not None else -0.35 if w.prof is AC else -0.50
    for k in range(n):
        w.paper_trade(t, t + H1, loss if k in losses_at else 0.12, strat=strat, lock=None if k in losses_at else 0.10)
        t += 12 * H1


# ====================================================================== the scenes
def scenes(world: str = "live15") -> list:
    """[(title, level, text)] of every message type, in the order an owner would meet them. ``world``: "live15" (the
    running bot from 10-20, 규칙봇 15) or "ac" (the A+C bot before it)."""
    out: list = []
    tmp = tempfile.mkdtemp(prefix="livepreview_")
    try:
        if world == "two":
            out += _two_paper_scene(os.path.join(tmp, "m"))
        elif world == "vwap":
            out += _vwap_scene(os.path.join(tmp, "v"))
        elif world == "deepcoin":
            out += _deepcoin_scene(os.path.join(tmp, "d"))
        elif world == "ac":
            out += _trade_scene(os.path.join(tmp, "a"))
            out += _pause_scene(os.path.join(tmp, "p"), AC)
            out += _alarm_scene(os.path.join(tmp, "b"), AC)
            out += _drift_scene(os.path.join(tmp, "c"))
            out += _halt_scene(os.path.join(tmp, "d"))
            out += _checkpoint_scene(os.path.join(tmp, "e"), AC)
            out += _morning_scene(os.path.join(tmp, "f"), AC)
            out += _setup_scene(os.path.join(tmp, "g"), AC)
        else:
            out += _trade_scene15(os.path.join(tmp, "a"))
            out += _pause_scene(os.path.join(tmp, "p"), LIVE15)
            out += _alarm_scene(os.path.join(tmp, "b"), LIVE15)
            out += _halt_scene15(os.path.join(tmp, "d"))
            out += _checkpoint_scene(os.path.join(tmp, "e"), LIVE15)
            out += _morning_scene(os.path.join(tmp, "f"), LIVE15)
            out += _setup_scene(os.path.join(tmp, "g"), LIVE15)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _mk(path: str, prof: Profile = None, three: bool = False) -> World:
    os.makedirs(path, exist_ok=True)
    return World(path, prof or AC, three)


T0 = LC.window_of("2026-10-20")[0] + 8 * H1          # Tuesday 10/20 17:00 KST


def _trade_scene(path: str) -> list:
    w = _mk(path)
    out = []
    _history(w, T0, 17)                                  # 17 of 20: Bybit green (85%), MEXC red (90%)
    w.x_state("bybit", T0 - MIN)
    w.x_state("mexc", T0 - MIN)
    w.x_event("bybit", T0 - 2 * DAY, "start", "시작")
    w.x_event("mexc", T0 - 2 * DAY, "start", "시작")
    w.tick(T0 - MIN)
    w.watch(T0 - MIN)                                    # the first look: lights and runs recorded, nothing sent
    # ▶️ Bybit restarted
    w.x_event("bybit", T0 - 30 * MIN, "start", "시작")
    w.tick(T0 - 29 * MIN)
    out += [("▶️ 실행기 켜짐", lv, t) for lv, t in w.watch(T0 - 29 * MIN)]
    # ⏳ a break signal waits one bar for the price to trade below its signal bar's low (it lapses at T0: no entry)
    t0 = T0 - 30 * MIN
    s = Store3(w.paper)
    s.log_signals([{"bar_close": t0, "timeframe": "30m", "strategy": "N02_ST_KST@30m#3~x", "symbol": SOL, "side": -1,
                    "atr": 1.0, "ref_price": 182.1, "ref_time": t0, "delay_ms": 800, "status": "WAITING",
                    "data": {"source": "custom", "strategy": "N02_ST_KST", "why": "돌파 확인 대기"}}])
    s.commit()
    s.conn.close()
    r = Store3(w.rule)
    r.live_bars([{"ts": ts, "symbol": SOL, "open": 182.0, "high": 182.4, "low": 181.2 if ts == t0 - 7 * MIN else 181.6,
                  "close": 182.0 if ts < t0 else 182.1, "processed_at": ts + MIN} for ts in range(t0 - 30 * MIN, T0 - 26 * MIN, MIN)])
    r.commit()
    r.conn.close()
    w.tick(T0 - 25 * MIN)
    out += [("⏳ 진입 대기", lv, t) for lv, t in w.watch(T0 - 25 * MIN)]
    # ... the bar ends without the break: the paper bot restates the wait (combo.py _restate) and the same message
    # gets its result line (edited in place)
    s = Store3(w.paper)
    s.conn.execute("UPDATE signal_log SET status = 'FILTERED', data = ? WHERE bar_close = ? AND strategy = ? AND symbol = ?",
                   (json.dumps({"source": "custom", "strategy": "N02_ST_KST", "why": "돌파 없음(신호봉 시간 안에)"}),
                    t0, "N02_ST_KST@30m#3~x", SOL))
    s.commit()
    s.conn.close()
    w.tick(T0)
    out += [("⏳ 진입 대기 → 결과(같은 메시지가 바뀜)", lv, t) for lv, t in w.watch(T0)]
    # 🟢 entry: Bybit followed, MEXC's light blocked it
    key = f"{LC.ACCOUNT}|{BTC}|{T0}"
    w.open_position(T0)
    w.x_open("bybit", key, BTC, 1, T0 + 3000, 67_262.0, 0.0238, 66_431.0)
    w.x_state("bybit", T0 + MIN, trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": 0.0238,
                                        "entry_ts": T0 + 3000, "stop_initial": 66_431.0, "stop": 66_431.0,
                                        "stop_algo_id": "a1"})
    w.x_event("mexc", T0 + 2000, "light_red", "신호등 빨강", {"key": key})
    w.tick(T0 + MIN)
    out += [("🟢 진입", lv, t) for lv, t in w.watch(T0 + MIN)]
    # 🔒 the first lock
    w.position["lock_roe"], w.position["stop_price"] = 0.10, 67_430.0
    w.x_state("bybit", T0 + 62 * MIN, trade={"key": key, "symbol": BTC, "side": 1, "status": "open",
                                             "qty": 0.0238, "entry_ts": T0 + 3000, "stop_initial": 66_431.0,
                                             "stop": 67_430.0, "stop_algo_id": "a2"})
    w.tick(T0 + 62 * MIN)
    out += [("🔒 잠금 시작", lv, t) for lv, t in w.watch(T0 + 62 * MIN)]
    # ✅ a winning exit (and MEXC's light turns green with it: 🚦)
    x = T0 + 2 * H1 + 6 * MIN
    w.position = None
    w.paper_trade(T0, x, 0.234, lock=0.22, mfe=67_250 * (1 + 0.26 / 40))
    w.x_close("bybit", key, x + 2000, 9.36, 67_262.0, 67_655.0, 0.0238, 0.00055)
    w.x_state("bybit", x + MIN, trade=None, last_equity=117.23, peak_equity=117.23)
    w.tick(x + MIN)
    out += [("✅ 청산(이김) / 🚦 신호등 바뀜", lv, t) for lv, t in w.watch(x + MIN)]
    # ❌ two losses in a row: a quiet card, then a loud one
    for k, (e, roe) in enumerate(((x + 2 * H1, -0.38), (x + 5 * H1, -0.41))):
        skey = f"{LC.ACCOUNT}|{SOL}|{e}"
        w.x_open("bybit", skey, SOL, 1, e + 2000, 182.39, 2.19, 180.05, lev=30)
        w.paper_trade(e, e + 90 * MIN, roe, symbol=SOL, strat=ASIA, price=182.35, lev=30, reg5=3,
                      mfe=182.35 * (1 + 0.10 / 30), stop=180.02)
        w.x_close("bybit", skey, e + 90 * MIN + 2000, -5.18 if k == 0 else -5.6, 182.39, 180.0, 2.19, 0.00055)
        w.x_state("bybit", e + 92 * MIN, trade=None, last_equity=112.0 - 5 * k, peak_equity=117.23)
        w.x_event("mexc", e + 2000, "light_red", "신호등 빨강", {"key": skey})
        w.tick(e + 92 * MIN)
        out += [("❌ 청산 = 손실 카드" + (" (소리)" if k else ""), lv, t) for lv, t in w.watch(e + 92 * MIN)]
    # ⏹ MEXC stopped by hand
    w.x_event("mexc", x + 8 * H1, "sigterm", "끄라는 신호(SIGTERM)를 받아 멈춥니다")
    w.tick(x + 8 * H1 + MIN)
    out += [("⏹ 실행기 꺼짐", lv, t) for lv, t in w.watch(x + 8 * H1 + MIN, units=lambda u: (
        ("inactive", "disabled") if u == "paperbot-executor-mexc" else ("active", "enabled")))]
    return out


def _trade_scene15(path: str) -> list:
    """규칙봇 15: both executors follow every paper entry (no light), the first lock, a winning exit, a quick exit on the
    strategy's own reverse signal before the first lock (a small loss: a quiet card), then a -50% stop as the second
    loss in a row (the loud card: no executor halts by itself any more), and MEXC stopped by hand."""
    w = _mk(path, LIVE15)
    out = []
    _history(w, T0, 18, losses_at=(6, 14))
    w.x_state("bybit", T0 - MIN)
    w.x_state("mexc", T0 - MIN)
    w.x_event("bybit", T0 - 2 * DAY, "start", "시작")
    w.x_event("mexc", T0 - 2 * DAY, "start", "시작")
    w.tick(T0 - MIN)
    w.watch(T0 - MIN)                                    # the first look: runs recorded, nothing sent
    # ▶️ Bybit restarted (an update)
    w.x_event("bybit", T0 - 30 * MIN, "start", "시작")
    w.tick(T0 - 29 * MIN)
    out += [("▶️ 실행기 켜짐", lv, t) for lv, t in w.watch(T0 - 29 * MIN)]
    # 🟢 entry: V39_ALL 1h BTC long at 40x, the stop at -50% net ROE (price -1.11%); both executors follow it with 30% of
    # their own balance (the paper's share)
    eqs = {"bybit": 107.87, "mexc": 107.87}
    gap = {"bybit": (1.0002, 0.006, 0.00055), "mexc": (1.0003, 0.011, 0.0008)}     # fill, ROE given up, fee rate

    def follow(name: str, k: str, sym: str, t: int, price: float, lev: int) -> tuple:
        px = round(price * gap[name][0], 2)
        qty = round(eqs[name] * 0.3 * lev / px, 4)
        stop_ = round(px * (1 - (0.0111 if lev == 40 else 0.0153)), 2)
        w.x_open(name, k, sym, 1, t + 3000, px, qty, stop_, lev=lev)
        return px, qty, stop_

    def settle(name: str, k: str, t: int, px: float, qty: float, roe: float, lev: int) -> None:
        live = roe - gap[name][1]
        pnl = round(qty * px / lev * live, 2)
        w.x_close(name, k, t, pnl, px, px * (1 + live / lev), qty, gap[name][2])
        eqs[name] = round(eqs[name] + pnl, 2)

    key = f"{LC.ACCOUNT}|{BTC}|{T0}"
    stop = round(67_250.0 * (1 - 0.0111), 1)
    w.open_position(T0, stop=stop)
    held = {}
    for name in eqs:
        px, qty, xstop = held[name] = follow(name, key, BTC, T0, 67_250.0, 40)
        w.x_state(name, T0 + MIN, trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": qty,
                                         "entry_ts": T0 + 3000, "stop_initial": xstop, "stop": xstop,
                                         "stop_algo_id": "a1"})
    w.tick(T0 + MIN)
    out += [("🟢 진입", lv, t) for lv, t in w.watch(T0 + MIN)]
    # 🔒 the first lock: +11% net ROE reached, +10% locked
    w.position["lock_roe"], w.position["stop_price"] = 0.10, 67_430.0
    for name, (px, qty, xstop) in held.items():
        w.x_state(name, T0 + 62 * MIN, trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": qty,
                                              "entry_ts": T0 + 3000, "stop_initial": xstop,
                                              "stop": round(px * (1 + 0.145 / 40), 1), "stop_algo_id": "a2"})
    w.tick(T0 + 62 * MIN)
    out += [("🔒 잠금 시작", lv, t) for lv, t in w.watch(T0 + 62 * MIN)]
    # ✅ a winning exit: +20% reached (lock 17%), then back to the lock
    x = T0 + 2 * H1 + 6 * MIN
    w.position = None
    w.paper_trade(T0, x, 0.171, lock=0.17, mfe=67_250 * (1 + 0.205 / 40))
    for name, (px, qty, _s) in held.items():
        settle(name, key, x + 2000, px, qty, 0.171, 40)
        w.x_state(name, x + MIN, trade=None, last_equity=eqs[name], peak_equity=eqs[name])
    w.tick(x + MIN)
    out += [("✅ 청산(이김)", lv, t) for lv, t in w.watch(x + MIN)]
    # ❌ a quick exit on the reverse signal before the first lock (-8%), then a -50% stop: two losses in a row
    peak = dict(eqs)
    for k, (e, roe, reason, sym, strat, price) in enumerate((
            (x + 2 * H1, -0.081, "REV", SOL, CMO, 182.35), (x + 5 * H1, -0.50, "SL", ETH, BOS, 2_415.0))):
        skey = f"{LC.ACCOUNT}|{sym}|{e}"
        legs = {name: follow(name, skey, sym, e, price, 30) for name in eqs}
        w.paper_trade(e, e + 90 * MIN, roe, symbol=sym, strat=strat, price=price, lev=30, reason=reason,
                      mfe=price * (1 + 0.06 / 30), stop=round(price * (1 - 0.0153), 2))
        for name, (px, qty, _s) in legs.items():
            settle(name, skey, e + 90 * MIN + 2000, px, qty, roe, 30)
            w.x_state(name, e + 92 * MIN, trade=None, last_equity=eqs[name], peak_equity=peak[name])
        w.tick(e + 92 * MIN)
        out += [("❌ 청산 = 손실 카드" + (" (소리)" if k else ""), lv, t) for lv, t in w.watch(e + 92 * MIN)]
    # ⏹ MEXC stopped by hand
    w.x_event("mexc", x + 8 * H1, "sigterm", "끄라는 신호(SIGTERM)를 받아 멈춥니다")
    w.tick(x + 8 * H1 + MIN)
    out += [("⏹ 실행기 꺼짐", lv, t) for lv, t in w.watch(x + 8 * H1 + MIN, units=lambda u: (
        ("inactive", "disabled") if u == "paperbot-executor-mexc" else ("active", "enabled")))]
    return out


def _two_paper_scene(path: str) -> list:
    """Two paper bots (owners 10-19): 규칙봇 15 (-50 %) followed by Bybit, its -35 % twin followed by MEXC since MEXC's
    restart with the new paper_db (its start record names it). One entry both bots make: ONE 🟢 with a line per paper
    bot; the price falls past -0.73 %: the -35 % bot stops alone (its loss card names MEXC only), the -50 % bot holds and
    wins later (its ✅ names Bybit only); the morning check lists both paper bots."""
    w = _mk(path, LIVE15)
    out = []
    second = os.path.join(path, "live15-mexc.db")
    Store3(second).conn.close()
    main_path = w.paper
    cfgs = {}
    for f, at in (("combo.live15.json", main_path), ("combo.live15-mexc.json", second)):
        with open(os.path.join(LC.ROOT, "deploy", f), encoding="utf-8") as fh:
            cfgs[at] = json.load(fh)
        st = Store3(at)
        st.put_state("combo_run", T0 - 3 * DAY, {"config": cfgs[at], "taker_fee": 0.0005})
        st.commit()
        st.conn.close()
    w.infos[1].paper_db = second                         # /etc/paperbot/executor-mexc.json after the switch

    def on(path_: str):
        w.paper = path_
    for at in (main_path, second):
        on(at)
        _history(w, T0, 18, losses_at=(6, 14), loss=-0.50 if at == main_path else -0.352)
    on(main_path)
    for name in ("bybit", "mexc"):
        w.x_state(name, T0 - MIN)
        w.x_event(name, T0 - 2 * DAY, "start", "시작", {"paper_db": main_path} if name == "bybit" else None)
    for at in (second, main_path):
        on(at)
        w.tick(T0 - MIN)
    w.watch(T0 - MIN)                                    # the first look: runs recorded, nothing sent
    # ▶️ the switch: MEXC started with the -35 % bot's database (docs/live15-mexc-ko.md)
    w.x_event("mexc", T0 - 30 * MIN, "start", f"시작: paper 계좌 COMBO@mix 따라 하기 (페이퍼 DB {second})", {"paper_db": second})
    for at in (second, main_path):
        on(at)
        w.tick(T0 - 29 * MIN)
    out += [("▶️ 실행기 켜짐 (페이퍼 바꿈)", lv, t) for lv, t in w.watch(T0 - 29 * MIN)]
    # 🟢 one entry, both bots: BTC long 40x; the -50 % stop 1.11 % under, the -35 % stop 0.73 % under
    key = f"{LC.ACCOUNT}|{BTC}|{T0}"
    px = 67_250.0
    stops = {main_path: round(px * (1 - (0.50 / 40 - 0.0014)), 1), second: round(px * (1 - (0.35 / 40 - 0.0014)), 1)}
    legs = {"bybit": (round(px * 1.0002, 1), 0.0144, main_path), "mexc": (round(px * 1.0003, 1), 0.0144, second)}
    for name, (fill, qty, at) in legs.items():
        xs = round(fill * (1 - (0.50 if at == main_path else 0.35) / 40 + 0.0014), 1)
        w.x_open(name, key, BTC, 1, T0 + 3000, fill, qty, xs)
        w.x_state(name, T0 + MIN, trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": qty, "entry_ts": T0 + 3000,
                                         "stop_initial": xs, "stop": xs, "stop_algo_id": "a1"})
    for at in (second, main_path):
        on(at)
        w.open_position(T0, stop=stops[at])
        w.tick(T0 + MIN)
    out += [("🟢 진입 (두 페이퍼)", lv, t) for lv, t in w.watch(T0 + MIN)]
    # ❌ the price dips 0.8 %: the -35 % bot and MEXC stop out, the -50 % bot and Bybit hold
    x1 = T0 + 40 * MIN
    on(second)
    w.position = None
    w.paper_trade(T0, x1, -0.352, stop=stops[second], mfe=px * 1.001)
    w.tick(x1 + MIN)
    on(main_path)
    w.open_position(T0, stop=stops[main_path])
    w.tick(x1 + MIN)
    fill, qty, _a = legs["mexc"]
    w.x_close("mexc", key, x1 + 2000, round(-0.362 * fill * qty / 40, 2), fill, round(fill * (1 - 0.362 / 40), 1), qty, 0.0008)
    w.x_state("mexc", x1 + MIN, trade=None, last_equity=98.8, peak_equity=107.87)
    out += [("❌ 청산 = 손실 카드 (−35% 봇만)", lv, t) for lv, t in w.watch(x1 + 2 * MIN)]
    # ✅ the -50 % bot comes back and locks +12 % (Bybit with it)
    x2 = T0 + 3 * H1
    on(main_path)
    w.position = None
    w.paper_trade(T0, x2, 0.121, lock=0.12, mfe=px * (1 + 0.155 / 40), stop=stops[main_path])
    w.tick(x2 + MIN)
    on(second)
    w.tick(x2 + MIN)
    on(main_path)
    fill, qty, _a = legs["bybit"]
    w.x_close("bybit", key, x2 + 2000, round(0.115 * fill * qty / 40, 2), fill, round(fill * (1 + 0.115 / 40), 1), qty, 0.00055)
    w.x_state("bybit", x2 + MIN, trade=None, last_equity=108.3, peak_equity=108.3)
    out += [("✅ 청산(이김, −50% 봇만)", lv, t) for lv, t in w.watch(x2 + 2 * MIN)]
    # 📋 the morning check: a line per paper bot, each saying which executor follows it
    day = LC.default_day(T0 + DAY)
    w0, w1 = LC.window_of(day)
    for at in (second, main_path):
        on(at)
        w.tick(w1 + 9 * MIN)
    got = Collect()
    r = LC.run_check(w.src(), day=day, now_ms=w1 + 10 * MIN, no_replay=True, notifier=got)
    out.append(("📋 아침 점검 (두 페이퍼)", r["level"], r["text"]))
    return out


def live_close(w: World, name: str, key: str, t, fill: float, qty: float, fee: float = 0.00055) -> float:
    """An executor closes with its paper trade ``t`` (a TradeRecord): 2 bps worse than the paper's exit price, its fees
    paid; returns its pnl."""
    side = int(t.side)
    px = round(float(t.exit_price) * (1 - side * 0.0002), 6)
    pnl = round(side * qty * (px - fill) - qty * (fill + px) * fee, 2)
    w.x_close(name, key, int(t.exit_time) + 2000, pnl, fill, px, qty, fee, side=side)
    return pnl


def _vwap_scene(path: str) -> list:
    """Two different paper bots (owners 10-23, docs/vwap-bot-ko.md): the 추세판단 봇 (deploy/combo.trend.json, the main
    paper) and 'VWAP 개선판' itself (VwapBot: the real bot on its own config). The VWAP bot runs paper-only first (its
    trades before the watcher first saw its file are never told; then "페이퍼만"), Bybit switches to it (WOO X Pro stays on
    the trend bot), one minute both bots enter BTC (two 🟢, each with its own executor), the VWAP bot's lock, win, loss
    card and 96-bar hold-limit exit, the signals its gates kept out, the morning check's VWAP part, its stalled-bot alarm
    and the weekend pause of both bots."""
    w = _mk(path, TREND)
    out = []
    w.infos[1].exchange = "wooxpro"                       # the second slot trades WOO X Pro (owners 10-20)
    with open(os.path.join(LC.ROOT, "deploy", TREND.config), encoding="utf-8") as fh:
        tcfg = json.load(fh)
    st = Store3(w.paper)
    st.put_state("combo_run", T0 - 3 * DAY, {"config": tcfg, "taker_fee": 0.0005})
    st.commit()
    st.conn.close()
    vpath = os.path.join(path, "vwap.db")
    day0 = T0 - 41 * H1                                    # Monday 10/19 00:00 KST
    vb = VwapBot(vpath, w.rule, day0 + 9 * H1)
    coins = (BTC, ETH, SOL, "DOGEUSDT", "LTCUSDT", "BCHUSDT")
    # its first 20 trades, paper-only (16 won: its light, 20 / 75 %, is green at the switch)
    slots = [day0 + h * H1 for h in range(10, 22)] + [day0 + 24 * H1 + h * H1 for h in range(0, 8)]
    for k, b in enumerate(slots):
        sym = coins[k % 6]
        p0 = vb.price(sym, b)
        vb.run_to(b)
        vb.signal("S3_CMO_SANDWICH" if k % 3 == 2 else "F6_VWAP_FAIL", sym, 1, b)
        vb.run_to(b + MIN)                                # entered on time (a signal stepped later is "late")
        if k in (3, 9, 13, 17):
            vb.move(sym, b + 30 * MIN, p0 * 0.98)                       # 2 ATR stop (1.6 %)
        else:
            vb.move(sym, b + 20 * MIN, p0 * 1.007)                      # the first lock (+10 %), then back to it
            vb.move(sym, b + 40 * MIN, p0 * 1.004)
        vb.move(sym, b + 55 * MIN, vb.price(sym, b + 55 * MIN))
        vb.run_to(b + 55 * MIN)
    _history(w, T0, 18, losses_at=(6, 14))
    st = Store3(w.paper)
    hist = st.conn.execute("SELECT entry_time, symbol FROM trades WHERE account_id = ? ORDER BY entry_time DESC LIMIT 3",
                           (LC.ACCOUNT,)).fetchall()
    st.conn.close()
    for et, sym in hist:                                  # Bybit followed the trend bot before the switch
        k = f"{LC.ACCOUNT}|{sym}|{et}"
        w.x_open("bybit", k, sym, 1, int(et) + 3000, 67_262.0, 0.0144, 66_517.0)
        w.x_close("bybit", k, int(et) + H1, 2.1, 67_262.0, 67_655.0, 0.0144, 0.00055)
    for name in ("bybit", "mexc"):
        w.x_state(name, T0 - 3 * H1)
        w.x_event(name, T0 - 2 * DAY, "start", "시작", {"paper_db": w.paper})
    vb.run_to(T0 - 2 * H1)
    w.tick(T0 - 2 * H1, bars=False)
    w.watch(T0 - 2 * H1)                                 # the first look: its file is new, nothing of it is sent
    # 🟢 🔒 ✅ paper-only: no executor follows it yet
    b = T0 - 90 * MIN
    vb.run_to(b)
    p0 = vb.price(SOL, b)
    vb.signal("F6_VWAP_FAIL", SOL, 1, b)
    vb.run_to(b + MIN)
    w.tick(b + MIN, bars=False)
    out += [("🟢 진입 (VWAP · 페이퍼만)", lv, t) for lv, t in w.watch(b + MIN)]
    vb.move(SOL, b + 20 * MIN, p0 * 1.007)
    vb.run_to(b + 21 * MIN)
    w.tick(b + 21 * MIN, bars=False)
    out += [("🔒 잠금 시작 (VWAP · 페이퍼만)", lv, t) for lv, t in w.watch(b + 21 * MIN)]
    vb.move(SOL, b + 40 * MIN, p0 * 1.004)
    vb.move(SOL, b + 50 * MIN, p0 * 1.004)
    vb.run_to(b + 50 * MIN)
    w.tick(b + 50 * MIN, bars=False)
    out += [("✅ 청산 (VWAP · 페이퍼만)", lv, t) for lv, t in w.watch(b + 50 * MIN)]
    # ▶️ the switch: Bybit started with the VWAP bot's database (deploy/vwap_switch.py: light 20 / 75 %)
    w.infos[0].paper_db, w.infos[0].light_n, w.infos[0].light_min = vpath, 20, 0.75
    w.x_event("bybit", T0 - 30 * MIN, "start", f"시작: paper 계좌 COMBO@mix 따라 하기 (페이퍼 DB {vpath})", {"paper_db": vpath})
    vb.run_to(T0 - 29 * MIN)
    w.tick(T0 - 29 * MIN, bars=False)
    out += [("▶️ 실행기 켜짐 (VWAP 개선판으로 바꿈)", lv, t) for lv, t in w.watch(T0 - 29 * MIN)]
    # 🟢 🟢 the same minute, the same coin, two bots: two messages, each with its own executor
    vb.run_to(T0)
    p0 = vb.price(BTC, T0)
    vb.signal("F6_VWAP_FAIL", BTC, 1, T0)
    vb.run_to(T0 + MIN)
    vp = vb.engine().position
    key = f"{LC.ACCOUNT}|{BTC}|{T0}"
    fill = round(vp.entry_price * 1.0002, 1)
    bqty = round(107.87 * 0.4 * 30 / fill, 4)
    bstop = round(fill * vp.stop_price / vp.entry_price, 1)
    w.x_open("bybit", key, BTC, 1, T0 + 3000, fill, bqty, bstop, lev=30)
    w.x_state("bybit", T0 + MIN, trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": bqty,
                                        "entry_ts": T0 + 3000, "stop_initial": bstop, "stop": bstop, "stop_algo_id": "b1"})
    tstop = round(p0 * (1 - 0.0111), 1)
    w.open_position(T0, symbol=BTC, price=p0, stop=tstop, strat=TREND.main, lev=40)
    wfill = round(p0 * 1.0003, 1)
    w.x_open("mexc", key, BTC, 1, T0 + 4000, wfill, 0.0144, round(wfill * (1 - 0.0111), 1))
    w.x_state("mexc", T0 + MIN, trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": 0.0144,
                                       "entry_ts": T0 + 4000, "stop_initial": round(wfill * (1 - 0.0111), 1),
                                       "stop": round(wfill * (1 - 0.0111), 1), "stop_algo_id": "w1"})
    w.tick(T0 + MIN, bars=False)
    out += [("🟢 진입 (같은 분 두 봇)", lv, t) for lv, t in w.watch(T0 + MIN)]
    # 🔒 the VWAP bot's first lock (Bybit's stop follows it)
    vb.move(BTC, T0 + 20 * MIN, p0 * 1.007)
    vb.run_to(T0 + 21 * MIN)
    vp = vb.engine().position
    w.x_state("bybit", T0 + 21 * MIN, trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": bqty,
                                             "entry_ts": T0 + 3000, "stop_initial": bstop,
                                             "stop": round(fill * vp.stop_price / vp.entry_price, 1), "stop_algo_id": "b2"})
    w.tick(T0 + 21 * MIN, bars=False)
    out += [("🔒 잠금 시작 (VWAP)", lv, t) for lv, t in w.watch(T0 + 21 * MIN)]
    # ✅ back to the lock: the VWAP bot and Bybit close
    vb.move(BTC, T0 + 40 * MIN, p0 * 1.004)
    vb.move(BTC, T0 + 50 * MIN, p0 * 1.004)
    vb.run_to(T0 + 50 * MIN)
    vt = vb.engine().trades[-1]
    eqs = {"bybit": 107.87}
    pnl = live_close(w, "bybit", key, vt, fill, bqty)
    eqs["bybit"] = round(eqs["bybit"] + pnl, 2)
    w.x_state("bybit", T0 + 50 * MIN, trade=None, last_equity=eqs["bybit"], peak_equity=eqs["bybit"])
    w.tick(T0 + 50 * MIN, bars=False)
    out += [("✅ 청산 (VWAP)", lv, t) for lv, t in w.watch(T0 + 50 * MIN)]
    # ✅ the trend bot's own win (WOO X Pro with it)
    x = T0 + 2 * H1
    w.position = None
    w.paper_trade(T0, x, 0.171, symbol=BTC, price=p0, lock=0.17, mfe=p0 * (1 + 0.205 / 40), stop=tstop, lev=40)
    w.x_close("mexc", key, x + 2000, round(0.0144 * wfill / 40 * 0.165, 2), wfill, round(wfill * (1 + 0.165 / 40), 1), 0.0144, 0.00042)
    w.x_state("mexc", x + MIN, trade=None, last_equity=108.9, peak_equity=108.9)
    vb.run_to(x + 2 * MIN)
    w.tick(x + 2 * MIN, bars=False)
    out += [("✅ 청산 (추세판단 봇)", lv, t) for lv, t in w.watch(x + 2 * MIN)]
    # ❌ the VWAP bot's 2 ATR stop (Bybit with it): its loss card
    b = T0 + 3 * H1
    vb.run_to(b)
    p1 = vb.price(ETH, b)
    vb.signal("F6_VWAP_FAIL", ETH, 1, b)
    vb.run_to(b + MIN)
    vp = vb.engine().position
    ekey = f"{LC.ACCOUNT}|{ETH}|{b}"
    efill = round(vp.entry_price * 1.0002, 2)
    eqty = round(eqs["bybit"] * 0.4 * 30 / efill * 0.95, 3)
    w.x_open("bybit", ekey, ETH, 1, b + 3000, efill, eqty, round(efill * vp.stop_price / vp.entry_price, 2), lev=30)
    vb.move(ETH, b + 30 * MIN, p1 * 0.98)
    vb.run_to(b + 40 * MIN)
    vt = vb.engine().trades[-1]
    pnl = live_close(w, "bybit", ekey, vt, efill, eqty)
    eqs["bybit"] = round(eqs["bybit"] + pnl, 2)
    w.x_state("bybit", b + 40 * MIN, trade=None, last_equity=eqs["bybit"], peak_equity=111.9)
    w.tick(b + 40 * MIN, bars=False)
    out += [("❌ 청산 = 손실 카드 (VWAP)", lv, t) for lv, t in w.watch(b + 40 * MIN)]
    # ✅ the 96-bar hold limit: LTC long at 21:00 KST, 48 hours below its first lock; meanwhile the gates keep signals out
    b = T0 + 4 * H1
    vb.run_to(b)
    p2 = vb.price("LTCUSDT", b)
    vb.signal("F6_VWAP_FAIL", "LTCUSDT", 1, b)
    vb.run_to(b + MIN)
    vp = vb.engine().position
    lkey = f"{LC.ACCOUNT}|LTCUSDT|{b}"
    lfill = round(vp.entry_price * 1.0002, 2)
    lqty = round(eqs["bybit"] * 0.4 * 30 / lfill, 2)
    w.x_open("bybit", lkey, "LTCUSDT", 1, b + 3000, lfill, lqty, round(lfill * vp.stop_price / vp.entry_price, 2), lev=30)
    w.x_state("bybit", b + MIN, trade={"key": lkey, "symbol": "LTCUSDT", "side": 1, "status": "open", "qty": lqty,
                                       "entry_ts": b + 3000, "stop_initial": round(lfill * vp.stop_price / vp.entry_price, 2),
                                       "stop": round(lfill * vp.stop_price / vp.entry_price, 2), "stop_algo_id": "b3"})
    w.tick(b + MIN, bars=False)
    w.watch(b + MIN)                                      # its 🟢 (shown above already: one is enough)
    vb.move("LTCUSDT", b + 3 * H1, p2 * 1.0025)
    d3 = day0 + 3 * DAY                                   # Thursday 10/22 00:00 KST
    # (when, strategy, coin, side, the gate's why ('' = passes, then one position holds it), what it read, would win)
    blocked = ((d3 + 11 * H1, "F6_VWAP_FAIL", BTC, 1, "4시간 추세 반대: 상승 0·하락 3·중립 1",
                gate_read(1, "30m", up=0, down=3), True),
               (d3 + 12 * H1, "F6_VWAP_FAIL", ETH, -1, "변동성 높음: ATR 0.512% > 지난 30일 80% 위치 0.433%",
                gate_read(-1, "30m", atr_pct=0.512, q_pct=0.433), False),
               (d3 + 13 * H1, "S3_CMO_SANDWICH", SOL, 1, "4시간 추세 판단을 못 읽음(진입 안 함): 바이낸스 응답 없음",
                {"vote": {"tf": "4h", "error": "바이낸스 응답 없음"}}, True),
               (d3 + 14 * H1, "F6_VWAP_FAIL", "DOGEUSDT", 1, "", None, True))
    for t, strat, sym, side, why, info, won in blocked:
        vb.run_to(t)
        if why:
            vb.gates.set(sym, t, why, info)
        q = vb.price(sym, t)
        vb.signal(strat, sym, side, t)
        if won:                                           # what each would have done (the 못 탄 신호 pass simulates it)
            vb.move(sym, t + 25 * MIN, q * (1 + side * 0.007))
            vb.move(sym, t + 50 * MIN, q * (1 + side * 0.004))
        else:
            vb.move(sym, t + 30 * MIN, q * (1 - side * 0.02))
        vb.run_to(t + MIN)
    vb.run_to(b + 48 * H1 + 5 * MIN)
    vt = vb.engine().trades[-1]
    pnl = live_close(w, "bybit", lkey, vt, lfill, lqty)
    eqs["bybit"] = round(eqs["bybit"] + pnl, 2)
    w.x_state("bybit", vt.exit_time + MIN, trade=None, last_equity=eqs["bybit"], peak_equity=111.9)
    w.x_equity("bybit", vt.exit_time + MIN, eqs["bybit"])
    w.x_equity("mexc", vt.exit_time + MIN, 108.9)
    w.tick(b + 48 * H1 + 5 * MIN, bars=False)
    out += [("✅ 청산 = 보유 한도 (VWAP)", lv, t) for lv, t in w.watch(b + 48 * H1 + 5 * MIN)]
    # 📋 the morning check of Thursday 10/22 09:00 ~ Friday 09:00 (its VWAP part)
    d4 = d3 + DAY + 9 * H1                                # Friday 10/23 09:00 KST
    vb.run_to(d4 + 9 * MIN)
    w.tick(d4 + 9 * MIN, bars=False)
    w.watch(d4 + 9 * MIN)                                 # the watcher's last pass before it (못 탄 신호 included)
    got = Collect()
    r = LC.run_check(w.src(), day=LC.default_day(d4 + 10 * MIN), now_ms=d4 + 10 * MIN, no_replay=True, notifier=got)
    out.append(("📋 아침 점검 (VWAP 개선판 부분)", r["level"], r["text"]))
    # 🚨 the VWAP bot stopped writing while Bybit follows it
    now = d4 + 2 * H1
    vb.run_to(now)
    st = Store3(vpath)
    st.put_state("heartbeat", now - 15 * MIN, {})
    st.commit()
    st.conn.close()
    w.tick(now, bars=False)
    out += [("🚨 알람(VWAP 페이퍼 멈춤)", lv, t) for lv, t in w.watch(now) if "VWAP 개선판 페이퍼 봇" in t]
    # ⏸ the weekend: both bots' rules are the same (deploy/combo.trend.json and combo.vwap.json): one message
    sat = d3 + 2 * DAY                                    # Saturday 10/24 00:00 KST
    vb.run_to(sat + MIN)
    w.tick(sat + MIN, bars=False)
    out += [("⏸ 진입 쉼 (두 봇)", lv, t) for lv, t in w.watch(sat + MIN) if t.startswith(("⏸", "🔔"))]
    vb.close()
    return out


def _deepcoin_scene(path: str) -> list:
    """Three executors (owners 10-24, docs/deepcoin-ko.md): 바이비트 and WOO X Pro follow the 추세판단 봇 (deploy/combo.trend.json,
    the main paper), the third, 딥코인, follows 'VWAP 개선판' itself (VwapBot: the real bot on its own config). 딥코인
    starts on the VWAP bot (▶️), one minute both bots enter BTC (two 🟢: the VWAP one with 딥코인 alone, the trend one with
    바이비트 and WOO X Pro), both win (✅, each with its own executors) and the morning check has the three executors."""
    w = _mk(path, TREND, three=True)
    out = []
    w.infos[1].exchange = "wooxpro"                       # the second slot trades WOO X Pro (owners 10-20)
    with open(os.path.join(LC.ROOT, "deploy", TREND.config), encoding="utf-8") as fh:
        tcfg = json.load(fh)
    st = Store3(w.paper)
    st.put_state("combo_run", T0 - 3 * DAY, {"config": tcfg, "taker_fee": 0.0005})
    st.commit()
    st.conn.close()
    vpath = os.path.join(path, "vwap.db")
    day0 = T0 - 41 * H1                                    # Monday 10/19 00:00 KST
    vb = VwapBot(vpath, w.rule, day0 + 9 * H1)
    coins = (BTC, ETH, SOL, "DOGEUSDT", "LTCUSDT", "BCHUSDT")
    for k, b in enumerate(day0 + h * H1 for h in range(10, 16)):         # its first trades, paper-only
        sym = coins[k % 6]
        p0 = vb.price(sym, b)
        vb.run_to(b)
        vb.signal("F6_VWAP_FAIL", sym, 1, b)
        vb.run_to(b + MIN)
        if k == 3:
            vb.move(sym, b + 30 * MIN, p0 * 0.98)                       # 2 ATR stop (1.6 %)
        else:
            vb.move(sym, b + 20 * MIN, p0 * 1.007)                      # the first lock (+10 %), then back to it
            vb.move(sym, b + 40 * MIN, p0 * 1.004)
        vb.move(sym, b + 55 * MIN, vb.price(sym, b + 55 * MIN))
        vb.run_to(b + 55 * MIN)
    _history(w, T0, 18, losses_at=(6, 14))
    for name in ("bybit", "mexc", "deepcoin"):
        w.x_state(name, T0 - 3 * H1)
    for name in ("bybit", "mexc"):                        # the two follow the trend bot as before
        w.x_event(name, T0 - 2 * DAY, "start", "시작", {"paper_db": w.paper})
    vb.run_to(T0 - 2 * H1)
    w.tick(T0 - 2 * H1, bars=False)
    w.watch(T0 - 2 * H1)                                 # the first look: the VWAP bot's file is new, nothing of it is sent
    # ▶️ 딥코인 started on the VWAP bot (its config: deploy/executor.live-deepcoin.json, vwap.db)
    w.infos[2].paper_db = vpath
    w.x_event("deepcoin", T0 - 30 * MIN, "start", f"시작: paper 계좌 COMBO@mix 따라 하기 (페이퍼 DB {vpath})", {"paper_db": vpath})
    vb.run_to(T0 - 29 * MIN)
    w.tick(T0 - 29 * MIN, bars=False)
    out += [("▶️ 실행기 켜짐 (딥코인 · VWAP 개선판)", lv, t) for lv, t in w.watch(T0 - 29 * MIN)]
    # 🟢 🟢 the same minute, the same coin, two bots: the VWAP one with 딥코인, the trend one with 바이비트 and WOO X Pro
    vb.run_to(T0)
    p0 = vb.price(BTC, T0)
    vb.signal("F6_VWAP_FAIL", BTC, 1, T0)
    vb.run_to(T0 + MIN)
    vp = vb.engine().position
    key = f"{LC.ACCOUNT}|{BTC}|{T0}"
    ffill = round(vp.entry_price * 1.0003, 1)
    fqty = round(107.87 * 0.4 * 30 / ffill, 4)
    fstop = round(ffill * vp.stop_price / vp.entry_price, 1)
    w.x_open("deepcoin", key, BTC, 1, T0 + 3000, ffill, fqty, fstop, lev=30)
    w.x_state("deepcoin", T0 + MIN, trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": fqty,
                                           "entry_ts": T0 + 3000, "stop_initial": fstop, "stop": fstop, "stop_algo_id": "d1"})
    tstop = round(p0 * (1 - 0.0111), 1)
    w.open_position(T0, symbol=BTC, price=p0, stop=tstop, strat=TREND.main, lev=40)
    fills = {"bybit": round(p0 * 1.0002, 1), "mexc": round(p0 * 1.0003, 1)}
    for name, fill in fills.items():
        stop = round(fill * (1 - 0.0111), 1)
        w.x_open(name, key, BTC, 1, T0 + 4000, fill, 0.0144, stop)
        w.x_state(name, T0 + MIN, trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": 0.0144,
                                         "entry_ts": T0 + 4000, "stop_initial": stop, "stop": stop, "stop_algo_id": name[0] + "1"})
    w.tick(T0 + MIN, bars=False)
    out += [("🟢 진입 (같은 분 두 봇 · 실행기 셋)", lv, t) for lv, t in w.watch(T0 + MIN)]
    # ✅ the VWAP bot's lock and exit: 딥코인 closes with it
    vb.move(BTC, T0 + 20 * MIN, p0 * 1.007)
    vb.move(BTC, T0 + 40 * MIN, p0 * 1.004)
    vb.move(BTC, T0 + 50 * MIN, p0 * 1.004)
    vb.run_to(T0 + 50 * MIN)
    vt = vb.engine().trades[-1]
    feq = round(107.87 + live_close(w, "deepcoin", key, vt, ffill, fqty, fee=LC.ASSUMED_FEE["deepcoin"]), 2)
    w.x_state("deepcoin", T0 + 50 * MIN, trade=None, last_equity=feq, peak_equity=feq)
    w.tick(T0 + 50 * MIN, bars=False)
    out += [("✅ 청산 (VWAP · 딥코인)", lv, t) for lv, t in w.watch(T0 + 50 * MIN)]
    # ✅ the trend bot's own win: 바이비트 and WOO X Pro close with it
    x = T0 + 2 * H1
    w.position = None
    w.paper_trade(T0, x, 0.171, symbol=BTC, price=p0, lock=0.17, mfe=p0 * (1 + 0.205 / 40), stop=tstop, lev=40)
    for name, fill in fills.items():
        fee = 0.00055 if name == "bybit" else 0.00042
        w.x_close(name, key, x + 2000, round(0.0144 * fill / 40 * 0.165, 2), fill, round(fill * (1 + 0.165 / 40), 1), 0.0144, fee)
        w.x_state(name, x + MIN, trade=None, last_equity=108.9, peak_equity=108.9)
    vb.run_to(x + 2 * MIN)
    w.tick(x + 2 * MIN, bars=False)
    out += [("✅ 청산 (추세판단 봇 · 바이비트 · WOO X Pro)", lv, t) for lv, t in w.watch(x + 2 * MIN)]
    # 📋 the morning check of Tuesday 10/20 09:00 ~ Wednesday 09:00: the three executors, each with its own paper bot
    w0, w1 = LC.window_of("2026-10-20")
    for name, eq in (("bybit", 108.9), ("mexc", 108.9), ("deepcoin", feq)):
        w.x_equity(name, w1 - MIN, eq)
    vb.run_to(w1 + 9 * MIN)
    w.tick(w1 + 9 * MIN, bars=False)
    w.watch(w1 + 9 * MIN)                                 # the watcher's last pass before it
    got = Collect()
    r = LC.run_check(w.src(), day="2026-10-20", now_ms=w1 + 10 * MIN, no_replay=True, notifier=got)
    out.append(("📋 아침 점검 (실행기 셋)", r["level"], r["text"]))
    vb.close()
    return out


def _halt_scene15(path: str) -> list:
    """규칙봇 15: no halt for a losing run or a drawdown; a halt still comes from an executor's own safety stop (here a
    position found on the wrong side: loud) or from the STOP file (a person's stop: quiet ⏹)."""
    w = _mk(path, LIVE15)
    out = []
    now = T0 + 9 * H1
    _history(w, now - 6 * H1, 17, n=17)
    for k in range(2):
        e = now - (5 - k) * H1
        key = f"{LC.ACCOUNT}|{SOL}|{e}"
        w.paper_trade(e, e + 30 * MIN, 0.12, symbol=SOL, strat=CMO, price=182.35, lev=30, lock=0.10)
        w.x_open("bybit", key, SOL, 1, e + 2000, 182.39, 5.43, 179.6, lev=30)
        w.x_close("bybit", key, e + 30 * MIN + 2000, round(5.43 * (183.05 - 182.39), 2), 182.39, 183.05, 5.43, 0.00055)
    w.x_state("bybit", now - MIN, halted=True, halt_reason="방향이 반대인 포지션 발견", halted_ts=now - 2 * H1,
              halt_kinds=["wrong_side"], last_equity=111.2, peak_equity=114.6)
    w.x_state("mexc", now - MIN, halted=True, halt_reason="비상 정지 파일이 있습니다(/var/lib/paperbot/STOP)",
              halted_ts=now - H1, halt_kinds=["kill"], last_equity=101.3)
    w.tick(now)
    out += [("🚨 멈춤 요약 / ⏹ STOP 파일", lv, t) for lv, t in w.watch(now)
            if "실행기가 멈췄습니다" in t or "사람이 끔" in t]
    return out


def _pause_scene(path: str, prof: Profile = None) -> list:
    """⏸ / 🔔 the paper bot's entry pauses by the live config's rules (deploy/combo.live-ac.json: ±30 minutes around a
    US macro release, the KST weekend), from a release file of its own (paperbot/events.py reads it for this scene
    only): a CPI on Thursday with a paper position open, then the weekend and a PCE on Monday evening."""
    from . import events as EV
    w = _mk(path, prof)
    cpi = LC.window_of("2026-10-22")[0] + 12 * H1 + 30 * MIN          # Thursday 10/22 21:30 KST
    sat = LC.window_of("2026-10-23")[0] + 15 * H1                     # Saturday 10/24 00:00 KST
    pce = sat + 2 * DAY + 21 * H1 + 30 * MIN                          # the Monday after, 21:30 KST
    csv = os.path.join(path, "macro_events.csv")
    with open(csv, "w", encoding="utf-8") as fh:
        fh.write("ts_utc,kind,source_url\n")
        for ms, kind, url in ((cpi, "CPI", "https://www.bls.gov/schedule/news_release/cpi.htm"),
                              (pce, "PCE", "https://www.bea.gov/news/schedule")):
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ms / 1000))},{kind},{url}\n")
    old = EV.PATH
    EV.PATH = csv
    EV.reset()
    out = []
    try:
        w.open_position(cpi - 3 * H1)
        for now, pos in ((cpi - 29 * MIN, True), (cpi + 31 * MIN, True), (sat + MIN, False), (sat + 2 * DAY + MIN, False)):
            if not pos:
                w.position = None
            w.tick(now)
            out += [("⏸ 🔔 진입 쉼", lv, t) for lv, t in w.watch(now) if t.startswith(("⏸", "🔔"))]
    finally:
        EV.PATH = old
        EV.reset()
    return out


def _alarm_scene(path: str, prof: Profile = None) -> list:
    w = _mk(path, prof)
    out = []
    now = T0 + 5 * H1
    _history(w, now - 6 * H1, 18, losses_at=(4, 12), n=20)
    if w.prof is not AC:                                 # 규칙봇 15: Bybit lost twice where the paper won (no drift scene)
        a = now - 50 * MIN
        for e, pp, xp in ((a - 3 * H1, 0.12, -1.1), (a - 2 * H1, 0.11, -0.9)):
            key = f"{LC.ACCOUNT}|{BTC}|{e}"
            w.paper_trade(e, e + 40 * MIN, pp, strat=w.prof.alt)
            w.x_open("bybit", key, BTC, 1, e + 2000, 67_300.0, 0.0192, 66_553.0)
            w.x_close("bybit", key, e + 41 * MIN, xp, 67_300.0, 67_200.0, 0.0192, 0.00055)
    w.x_state("bybit", now - MIN, last_equity=79.5, peak_equity=107.87)
    w.x_state("mexc", now - MIN, last_equity=151.2, peak_equity=151.2)
    w.tick(now - 3 * MIN)
    out += [("", lv, t) for lv, t in w.watch(now - 3 * MIN)]
    # an entry Bybit did not follow, a position without a stop at MEXC, MEXC quiet, equity alarms
    key = f"{LC.ACCOUNT}|{BTC}|{now - 5 * MIN}"
    pstop, xstop = (66_420.0, 66_430.0) if w.prof is AC else (66_504.0, 66_513.0)
    w.open_position(now - 5 * MIN, stop=pstop)
    w.x_open("mexc", key, BTC, 1, now - 5 * MIN + 2000, 67_260.0, 0.0238, xstop)
    w.x_state("mexc", now - MIN, last_equity=151.2, peak_equity=151.2,
              trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": 0.0238,
                     "entry_ts": now - 5 * MIN + 2000, "stop_initial": xstop, "stop": xstop,
                     "stop_algo_id": None})
    w.tick(now)
    c = w._x("mexc")                                     # MEXC has gone quiet for 15 minutes
    c.execute("UPDATE state SET ts = ? WHERE k = 'bot'", (now - 15 * MIN,))
    c.commit()
    c.close()
    host = LC.Host(disk_free=lambda p: int(1.6 * 1024 ** 3), mem_available=lambda: 410 * 1024 ** 2,
                   unit_memory=lambda: [("paperbot-live3.service", 1_350 * 1024 ** 2),
                                        ("paperbot-agents.service", 880 * 1024 ** 2),
                                        ("paperbot-combo.service", 690 * 1024 ** 2),
                                        ("paperbot-combo-shadow@b.service", 270 * 1024 ** 2),
                                        ("demobot-live.service", 240 * 1024 ** 2),
                                        ("paperbot-executor.service", 95 * 1024 ** 2)], paths=("/",))
    out += [("🚨 알람", lv, t) for lv, t in w.watch(now, host=host)]
    # the paper bot and its bars go quiet; later they come back (✅)
    w.tick(now + 15 * MIN, heartbeat=now + MIN, bars=False)
    out += [("🚨 알람(페이퍼 멈춤)", lv, t) for lv, t in w.watch(now + 15 * MIN, host=host)
            if "페이퍼 봇" in t or "1분봉" in t]
    w.tick(now + 20 * MIN)
    out += [("✅ 다시 정상", lv, t) for lv, t in w.watch(now + 20 * MIN, host=host)
            if "페이퍼 봇" in t or "1분봉" in t]
    return out


def _drift_scene(path: str) -> list:
    w = _mk(path)
    out = []
    now = T0 + 8 * H1
    _history(w, now - 6 * H1, 10, losses_at=(1, 3, 5, 7, 9, 11, 13, 15, 17, 19), n=20)
    a = now - 50 * MIN
    for k, (e, pp, xp) in enumerate(((a - 5 * H1, 0.12, -1.1), (a - 4 * H1, 0.11, -0.9))):
        key = f"{LC.ACCOUNT}|{BTC}|{e}"
        w.paper_trade(e, e + 40 * MIN, pp, strat=ASIA)
        w.x_open("bybit", key, BTC, 1, e + 2000, 67_300.0, 0.0238, 66_431.0)
        w.x_close("bybit", key, e + 41 * MIN, xp, 67_300.0, 67_200.0, 0.0238, 0.00055)
    w.x_state("bybit", now - MIN)
    w.x_state("mexc", now - MIN)
    w.tick(now)
    out += [("", lv, t) for lv, t in w.watch(now)
            if t.startswith(("기대 범위", "📉", "바이비트 실거래가 페이퍼가"))]
    w2 = _mk(path + "2")
    _history(w2, now, 15, losses_at=(2, 7, 11, 16, 18), n=20)
    w2.x_state("bybit", now - MIN)
    w2.x_state("mexc", now - MIN)
    w2.tick(now)
    out += [("📉 참고(맞춘 범위 밑)", lv, t) for lv, t in w2.watch(now) if t.startswith("📉 참고: 페이퍼")]
    return out


def _halt_scene(path: str) -> list:
    w = _mk(path)
    out = []
    now = T0 + 9 * H1
    _history(w, now - 6 * H1, 17, n=17)
    for k in range(3):
        e = now - (5 - k) * H1
        key = f"{LC.ACCOUNT}|{SOL}|{e}"
        w.paper_trade(e, e + 30 * MIN, -0.38, symbol=SOL, strat=ASIA, price=182.35, lev=30, stop=180.02)
        w.x_open("bybit", key, SOL, 1, e + 2000, 182.39, 2.19, 180.05, lev=30)
        w.x_close("bybit", key, e + 30 * MIN + 2000, -5.2, 182.39, 180.0, 2.19, 0.00055)
    w.x_state("bybit", now - MIN, halted=True, halt_reason="연속 손실 3번", halted_ts=now - 2 * H1,
              halt_kinds=["streak"], last_equity=84.4, peak_equity=107.87)
    w.x_state("mexc", now - MIN, halted=True, halt_reason="비상 정지 파일이 있습니다(/var/lib/paperbot/STOP)",
              halted_ts=now - H1, halt_kinds=["kill"], last_equity=101.3)
    w.tick(now)
    out += [("🚨 멈춤 요약 / ⏹ STOP 파일", lv, t) for lv, t in w.watch(now)
            if "실행기가 멈췄습니다" in t or "사람이 끔" in t]
    return out


def _checkpoint_scene(path: str, prof: Profile = None) -> list:
    """🏁 the 40th paper trade: the A+C bot's verdict; nothing for 규칙봇 15 (no 5-year reference, no 40-trade rule)."""
    w = _mk(path, prof)
    now = T0 + 10 * H1
    _history(w, now - H1, 36, losses_at=(5, 17, 26, 33), n=39)
    w.x_state("bybit", now - MIN)
    w.x_state("mexc", now - MIN)
    for name, n, wins in (("bybit", 39, 35), ("mexc", 31, 29)):
        for k in range(n):
            key = f"x|{name}|{k}"
            w.x_open(name, key, BTC, 1, now - 100 * H1 + k * H1, 67_000.0, 0.0238, 66_000.0)
            w.x_close(name, key, now - 100 * H1 + k * H1 + 30 * MIN, 1.0 if k >= n - wins else -2.0, 67_000.0,
                      67_100.0, 0.0238, 0.00055)
    w.tick(now - 2 * MIN)
    w.watch(now - 2 * MIN)
    w.paper_trade(now - 50 * MIN, now - 5 * MIN, 0.12)
    w.tick(now)
    return [("🏁 40번 도달", lv, t) for lv, t in w.watch(now) if t.startswith(("🏁", "🚨 🏁"))]


def _morning_scene(path: str, prof: Profile = None) -> list:
    prof = prof or AC
    main, alt = prof.main, prof.alt
    label = (lambda st: f"{st[0]}@{st[1]}#{st[2]}~x") if prof is AC else (lambda st: f"{st[0]}@{st[1]}")
    if prof is AC:
        run_cfg = {"members": [], "macro_blackout_min": 30, "no_weekend": True}
    else:
        with open(os.path.join(LC.ROOT, "deploy", prof.config), encoding="utf-8") as fh:
            run_cfg = json.load(fh)
    loss = -0.36 if prof is AC else -0.50
    out = []
    for name, day, diff in (("q", "2026-10-28", False), ("l", "2026-10-29", True)):
        w = _mk(os.path.join(path, name), prof)
        w0, w1 = LC.window_of(day)
        _history(w, w0 + 10 * H1, 17, n=20)
        e = w0 + 10 * H1 + 30 * MIN
        key = f"{LC.ACCOUNT}|{BTC}|{e}"
        w.paper_trade(e, e + H1, 0.18, lock=0.16)
        lo = w0 + 20 * H1                                # a loss at 05:00 KST: its card line in the morning
        w.paper_trade(lo, lo + H1, loss, symbol=SOL, strat=alt, price=182.35, lev=30, stop=180.02)
        w.x_open("bybit", key, BTC, 1, e + 2000, 67_262.0, 0.0238, 66_431.0)
        w.x_close("bybit", key, e + H1 + 2000, 7.1, 67_262.0, 67_560.0, 0.0238, 0.00055)
        w.x_equity("bybit", w1 - MIN, 107.1)
        w.x_state("bybit", w1 + 9 * MIN, last_equity=107.1)
        w.x_state("mexc", w1 + 9 * MIN, last_equity=100.0)
        w.x_equity("mexc", w1 - MIN, 100.0)
        s = Store3(w.paper)
        s.put_state("combo_run", w0 - DAY, {"config": run_cfg, "taker_fee": 0.0005})
        for sig_t in (w0 + 4 * H1, e):
            s.log_signals([{"bar_close": sig_t, "timeframe": main[1], "strategy": label(main),
                            "symbol": BTC, "side": 1, "atr": 1.0, "ref_price": 1.0, "ref_time": sig_t,
                            "delay_ms": 0, "status": "SUBMITTED", "data": {"strategy": main[0]}}])
        s.commit()
        s.conn.close()
        w.tick(w1 + 9 * MIN)
        rs = [{"bar_close": t, "tf": main[1], "strategy": label(main), "symbol": BTC, "side": 1,
               "status": "SUBMITTED", "why": "", "name": main[0]} for t in (w0 + 4 * H1, e)]
        if diff:
            rs.append(dict(rs[0], bar_close=w0 + 14 * H1, symbol=SOL))
        rt = [{"entry_time": e, "exit_time": e + H1, "symbol": BTC, "side": 1, "strategy": main[0],
               "tf": main[1], "member": None, "reason": "LOCK", "roe": 0.18, "pnl": 72.0, "entry_price": 67_250.0,
               "exit_price": 67_550.0, "fees": 0.4, "funding": 0.0, "qty": 0.2},
              {"entry_time": lo, "exit_time": lo + H1, "symbol": SOL, "side": 1, "strategy": alt[0],
               "tf": alt[1], "member": None, "reason": "SL", "roe": loss, "pnl": 400.0 * loss, "entry_price": 182.35,
               "exit_price": 180.2, "fees": 0.4, "funding": 0.0, "qty": 60.0}]
        res = LR.ReplayResult(w0=w0, w1=w1, end=w1 + MIN, source="live", seeded=True, signals=rs, trades=rt)
        got = Collect()
        r = LC.run_check(w.src(), day=day, now_ms=w1 + 10 * MIN, replay=lambda *a, _r=res: _r, notifier=got)
        out.append(("📋 아침 점검" + (" (확인할 것 있음, 금요일)" if diff else ""), r["level"], r["text"]))
    return out


def _setup_scene(path: str, prof: Profile = None) -> list:
    """The live bot's token put in /etc/paperbot/live-telegram.env without its chat lines: said once, through
    live.env's bot (the rule bot's room), after 10 minutes; ✅ from the live bot once the chat lines are in."""
    w = _mk(path, prof)
    now = T0 + 9 * H1
    w.tick(now)
    base = {"TELEGRAM_BOT_TOKEN": "rule-bot", "TELEGRAM_CHAT_CRITICAL": "-1001234567890"}
    half = {"base": base, "over": {"TELEGRAM_BOT_TOKEN": "live-bot"}, "over_exists": True,
            "over_mtime": now - 15 * MIN}
    done = {"base": base, "over": {"TELEGRAM_BOT_TOKEN": "live-bot", "TELEGRAM_CHAT_CRITICAL": "111,222",
                                   "TELEGRAM_SOUND": "critical", "PAPERBOT_COMBO_TRADE_MSGS": "0"},
            "over_exists": True, "over_mtime": now}
    out = [("🚨 텔레그램 설정", lv, t) for lv, t in w.watch(now, tg=half) if "텔레그램 설정" in t]
    w.tick(now + MIN)
    out += [("✅ 텔레그램 설정", lv, t) for lv, t in w.watch(now + MIN, tg=done) if "텔레그램 설정" in t]
    return out


# ====================================================================== print
KINDS = (("▶️", "실행기 켜짐"), ("⏹", "실행기 꺼짐(사람이 끔)"), ("⏳", "진입 대기"), ("🟢 진입", "진입"), ("🔒", "잠금 시작"),
         ("⚠", "참고(따라가는 실행기 없는 페이퍼)"),
         ("✅ 청산", "청산(이김)"), ("✅ 텔레그램", "텔레그램 설정 맞춰짐"), ("🚨 ❌", "손실 카드(소리)"),
         ("❌", "손실 카드"), ("🚦", "신호등 바뀜"), ("🏁", "40번 도달"), ("📉", "참고"), ("🎉", "좋은 소식"), ("✅", "다시 정상"), ("📋", "아침 점검"),
         ("🚨 실거래 일일 점검", "아침 점검(확인할 것 있음)"), ("⏸", "진입 쉼 시작"), ("🔔", "진입 쉼 끝"))
# a message edited in place: (its start, what the edit adds, kind) — the ⏳ wait with its result line
EDITED = (("⏳", "\n\n→ ", "진입 대기 → 결과(같은 메시지가 바뀜)"),)


ALARMS = (("페이퍼를 따라가지 않았습니다", "따라가지 않음"), ("기록을 남기지 않습니다", "실행기 조용함"),
          ("손절 기록이 없습니다", "손절 기록 없음"), ("디스크 부족", "디스크 부족"), ("메모리 부족", "메모리 부족"),
          ("페이퍼 봇이 10분", "페이퍼 봇 멈춤"), ("규칙봇 1분봉", "1분봉 멈춤"), ("최고점보다", "잔고 25% 하락"),
          ("페이퍼가 이긴 거래에서", "실거래만 짐"), ("기대 범위 밑", "기대 범위 밑"), ("실행기가 멈췄습니다", "멈춤 요약"),
          ("텔레그램 설정", "텔레그램 설정"))


def kind_of(body: str) -> str:
    for start, mark, name in EDITED:
        if body.startswith(start) and mark in body:
            return name
    for start, name in KINDS:
        if body.startswith(start):
            return name
    first = body.split("\n")[0]
    return "알람: " + next((name for frag, name in ALARMS if frag in first), first.removeprefix("🚨 ")[:20])


def shown(level: str, text: str) -> tuple:
    """(Telegram body, rings) as TelegramNotifier sends it with TELEGRAM_SOUND=critical."""
    from .notify import silent, telegram_text
    lvl, body = telegram_text(level, text)
    return body, not silent(lvl, "critical")


def render(items: list) -> str:
    """Each message as Telegram shows it, with whether it rings (TELEGRAM_SOUND=critical). The Telegram setup alarm
    goes through live.env's bot to the rule bot's room (the live chats cannot carry it)."""
    blocks = []
    for i, (scene, level, text) in enumerate(items, 1):
        body, rings = shown(level, text)
        where = " · 규칙봇 방으로" if scene.startswith("🚨 텔레그램") else ""
        blocks.append(f"━━ {i}. {kind_of(body)}{where} · {'소리' if rings else '무음'} ━━\n{body}")
    return "\n\n".join(blocks)


def main(world: str = "live15") -> int:
    print(render(scenes(world)))
    return 0
