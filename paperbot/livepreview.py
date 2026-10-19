"""미리 보기: every live Telegram message type of paperbot/livecheck.py, built from a hand-made world.

    python -m paperbot.livecheck preview

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
from dataclasses import asdict
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
BTC, SOL = "BTCUSDT", "SOLUSDT"
LON = ("F15_LON_BRK", "1h", 88)                  # strategy, tf, setting number (member_order) in the live config
ASIA = ("F15_ASIA_BRK", "30m", 37)


# ====================================================================== the world
class Collect:
    """A notifier that keeps what would be sent."""

    def __init__(self):
        self.items: list = []

    def send(self, level: str, text: str) -> bool:
        self.items.append((level, text))
        return True


def _units(_unit: str) -> tuple:
    return ("active", "enabled")


NO_TG = {"base": None, "over": None, "over_exists": False, "over_mtime": None}


class World:
    """One paper bot, the rule bot's bars, two executors (Bybit $100 light 20 / 85%, MEXC $100 light 20 / 90%)."""

    def __init__(self, root: str):
        self.root = root
        self.paper = os.path.join(root, "live-ac.db")
        self.rule = os.path.join(root, "paper3.db")
        self.dbs = {"bybit": os.path.join(root, "bybit.db"), "mexc": os.path.join(root, "mexc.db")}
        for p in self.dbs.values():
            c = sqlite3.connect(p)
            c.executescript(EXEC_SCHEMA)
            c.commit()
            c.close()
        Store3(self.paper).conn.close()
        Store3(self.rule).conn.close()
        self.position: Optional[dict] = None
        self.infos = [LC.ExecInfo("bybit", "/etc/paperbot/executor.json", "paperbot-executor", self.dbs["bybit"], 20,
                                  0.85, exchange="bybit", budget=100.0, kill_file="/nonexistent/STOP"),
                      LC.ExecInfo("mexc", "/etc/paperbot/executor-mexc.json", "paperbot-executor-mexc",
                                  self.dbs["mexc"], 20, 0.90, exchange="mexc", budget=100.0,
                                  kill_file="/nonexistent/STOP")]

    def src(self) -> LC.Sources:
        return LC.Sources(db=os.path.join(self.root, "livecheck.db"), paper_db=self.paper, rule_db=self.rule,
                          combo_config=os.path.join(LC.ROOT, "deploy", "combo.live-ac.json"),
                          shadow_glob=os.path.join(self.root, "shadow-*.db"), executors=self.infos)

    # ---- the paper bot
    def paper_trade(self, entry: int, exit_: int, roe: float, symbol=BTC, side=1, strat=LON, price=67_250.0,
                    reason=None, lock=None, mfe=None, lev=40, stop=None, reg5=1, hr=None):
        margin = 400.0
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
        meta = {"member": f"{strat[0]}@{strat[1]}#{strat[2]}~x", "member_order": strat[2],
                "rdims": {"reg5": reg5, "hr": hour}, "rstop": ["atr", 3.0]}
        s.outcome(LC.ACCOUNT, SignalOutcome(Signal(ts=entry - 1, symbol=symbol, timeframe=strat[1],
                                                   strategy_id=strat[0], side=side, stop_price=stop, meta=meta),
                                            "ENTERED", "", entry))
        s.commit()
        s.conn.close()
        return pnl

    def open_position(self, entry: int, symbol=BTC, side=1, strat=LON, price=67_250.0, stop=66_420.0, lev=40,
                      lock=None):
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


def _history(w: World, start: int, wins: int, losses_at=(3, 9, 15), n: int = 20, strat=LON):
    """``n`` closed paper trades before ``start``, losses at the given positions."""
    t = start - n * 12 * H1
    for k in range(n):
        w.paper_trade(t, t + H1, -0.35 if k in losses_at else 0.12, strat=strat, lock=None if k in losses_at else 0.10)
        t += 12 * H1


# ====================================================================== the scenes
def scenes() -> list:
    """[(title, level, text)] of every message type, in the order an owner would meet them."""
    out: list = []
    tmp = tempfile.mkdtemp(prefix="livepreview_")
    try:
        out += _trade_scene(os.path.join(tmp, "a"))
        out += _alarm_scene(os.path.join(tmp, "b"))
        out += _drift_scene(os.path.join(tmp, "c"))
        out += _halt_scene(os.path.join(tmp, "d"))
        out += _checkpoint_scene(os.path.join(tmp, "e"))
        out += _morning_scene(os.path.join(tmp, "f"))
        out += _setup_scene(os.path.join(tmp, "g"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _mk(path: str) -> World:
    os.makedirs(path, exist_ok=True)
    return World(path)


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


def _alarm_scene(path: str) -> list:
    w = _mk(path)
    out = []
    now = T0 + 5 * H1
    _history(w, now - 6 * H1, 18, losses_at=(4, 12), n=20)
    w.x_state("bybit", now - MIN, last_equity=79.5, peak_equity=107.87)
    w.x_state("mexc", now - MIN, last_equity=151.2, peak_equity=151.2)
    w.tick(now - 3 * MIN)
    out += [("", lv, t) for lv, t in w.watch(now - 3 * MIN)]
    # an entry Bybit did not follow, a position without a stop at MEXC, MEXC quiet, equity alarms
    key = f"{LC.ACCOUNT}|{BTC}|{now - 5 * MIN}"
    w.open_position(now - 5 * MIN)
    w.x_open("mexc", key, BTC, 1, now - 5 * MIN + 2000, 67_260.0, 0.0238, 66_430.0)
    w.x_state("mexc", now - MIN, last_equity=151.2, peak_equity=151.2,
              trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": 0.0238,
                     "entry_ts": now - 5 * MIN + 2000, "stop_initial": 66_430.0, "stop": 66_430.0,
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


def _checkpoint_scene(path: str) -> list:
    w = _mk(path)
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


def _morning_scene(path: str) -> list:
    out = []
    for name, day, diff in (("q", "2026-10-28", False), ("l", "2026-10-29", True)):
        w = _mk(os.path.join(path, name))
        w0, w1 = LC.window_of(day)
        _history(w, w0 + 10 * H1, 17, n=20)
        e = w0 + 10 * H1 + 30 * MIN
        key = f"{LC.ACCOUNT}|{BTC}|{e}"
        w.paper_trade(e, e + H1, 0.18, lock=0.16)
        lo = w0 + 20 * H1                                # a loss at 05:00 KST: its card line in the morning
        w.paper_trade(lo, lo + H1, -0.36, symbol=SOL, strat=ASIA, price=182.35, lev=30, stop=180.02)
        w.x_open("bybit", key, BTC, 1, e + 2000, 67_262.0, 0.0238, 66_431.0)
        w.x_close("bybit", key, e + H1 + 2000, 7.1, 67_262.0, 67_560.0, 0.0238, 0.00055)
        w.x_equity("bybit", w1 - MIN, 107.1)
        w.x_state("bybit", w1 + 9 * MIN, last_equity=107.1)
        w.x_state("mexc", w1 + 9 * MIN, last_equity=100.0)
        w.x_equity("mexc", w1 - MIN, 100.0)
        s = Store3(w.paper)
        s.put_state("combo_run", w0 - DAY, {"config": {"members": [], "macro_blackout_min": 30, "no_weekend": True},
                                            "taker_fee": 0.0005})
        for sig_t in (w0 + 4 * H1, e):
            s.log_signals([{"bar_close": sig_t, "timeframe": "1h", "strategy": "F15_LON_BRK@1h#88~x",
                            "symbol": BTC, "side": 1, "atr": 1.0, "ref_price": 1.0, "ref_time": sig_t,
                            "delay_ms": 0, "status": "SUBMITTED", "data": {"strategy": "F15_LON_BRK"}}])
        s.commit()
        s.conn.close()
        w.tick(w1 + 9 * MIN)
        rs = [{"bar_close": t, "tf": "1h", "strategy": "F15_LON_BRK@1h#88~x", "symbol": BTC, "side": 1,
               "status": "SUBMITTED", "why": "", "name": "F15_LON_BRK"} for t in (w0 + 4 * H1, e)]
        if diff:
            rs.append(dict(rs[0], bar_close=w0 + 14 * H1, symbol=SOL))
        rt = [{"entry_time": e, "exit_time": e + H1, "symbol": BTC, "side": 1, "strategy": "F15_LON_BRK",
               "tf": "1h", "member": None, "reason": "LOCK", "roe": 0.18, "pnl": 72.0, "entry_price": 67_250.0,
               "exit_price": 67_550.0, "fees": 0.4, "funding": 0.0, "qty": 0.2},
              {"entry_time": lo, "exit_time": lo + H1, "symbol": SOL, "side": 1, "strategy": "F15_ASIA_BRK",
               "tf": "30m", "member": None, "reason": "SL", "roe": -0.36, "pnl": -144.0, "entry_price": 182.35,
               "exit_price": 180.2, "fees": 0.4, "funding": 0.0, "qty": 60.0}]
        res = LR.ReplayResult(w0=w0, w1=w1, end=w1 + MIN, source="live", seeded=True, signals=rs, trades=rt)
        got = Collect()
        r = LC.run_check(w.src(), day=day, now_ms=w1 + 10 * MIN, replay=lambda *a, _r=res: _r, notifier=got)
        out.append(("📋 아침 점검" + (" (확인할 것 있음, 금요일)" if diff else ""), r["level"], r["text"]))
    return out


def _setup_scene(path: str) -> list:
    """The live bot's token put in /etc/paperbot/live-telegram.env without its chat lines: said once, through
    live.env's bot (the rule bot's room), after 10 minutes; ✅ from the live bot once the chat lines are in."""
    w = _mk(path)
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
KINDS = (("▶️", "실행기 켜짐"), ("⏹", "실행기 꺼짐(사람이 끔)"), ("🟢 진입", "진입"), ("🔒", "잠금 시작"),
         ("✅ 청산", "청산(이김)"), ("✅ 텔레그램", "텔레그램 설정 맞춰짐"), ("🚨 ❌", "손실 카드(소리)"),
         ("❌", "손실 카드"), ("🚦", "신호등 바뀜"), ("🏁", "40번 도달"), ("📉", "참고"), ("🎉", "좋은 소식"), ("✅", "다시 정상"), ("📋", "아침 점검"),
         ("🚨 실거래 일일 점검", "아침 점검(확인할 것 있음)"))


ALARMS = (("페이퍼를 따라가지 않았습니다", "따라가지 않음"), ("기록을 남기지 않습니다", "실행기 조용함"),
          ("손절 기록이 없습니다", "손절 기록 없음"), ("디스크 부족", "디스크 부족"), ("메모리 부족", "메모리 부족"),
          ("페이퍼 봇이 10분", "페이퍼 봇 멈춤"), ("규칙봇 1분봉", "1분봉 멈춤"), ("최고점보다", "잔고 25% 하락"),
          ("페이퍼가 이긴 거래에서", "실거래만 짐"), ("기대 범위 밑", "기대 범위 밑"), ("실행기가 멈췄습니다", "멈춤 요약"),
          ("텔레그램 설정", "텔레그램 설정"))


def kind_of(body: str) -> str:
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


def main() -> int:
    print(render(scenes()))
    return 0
