"""페이퍼 트레이딩.

- PaperBot: 전략(JSON)을 실시간 캔들에 붙여 자동 매매 (봉 마감 신호 → 현재가 체결)
- ManualAccount: 사용자가 직접 롱/숏 주문 (레버리지, 손절/익절 지정)
백테스트와 동일한 Simulator 를 써서 결과가 일관되게 나온다.
"""
from __future__ import annotations

import asyncio
import pickle
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field

from . import config
from .backtest import needs_derivatives
from .data import market
from .data.synthetic import INTERVAL_SECONDS
from .engine import MAINT_MARGIN_RATE, Position, Simulator, Trade
from .strategy import RiskSpec, StrategySpec, signals, validate

_lock = threading.RLock()


@dataclass
class PaperBot:
    spec: StrategySpec
    initial_equity: float = 10_000.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created: int = field(default_factory=lambda: int(time.time()))
    running: bool = True
    last_bar_time: int | None = None
    last_price: float | None = None
    data_source: str | None = None
    log: list[dict] = field(default_factory=list)
    sim: Simulator = field(init=False)

    def __post_init__(self):
        self.sim = Simulator(risk=self.spec.risk, initial_equity=self.initial_equity,
                             bar_seconds=INTERVAL_SECONDS.get(self.spec.interval, 3600))

    def _log(self, msg: str):
        self.log.append({"time": int(time.time()), "msg": msg})
        self.log = self.log[-200:]

    def tick(self):
        if not self.running:
            return
        step = INTERVAL_SECONDS.get(self.spec.interval, 3600)
        candles, self.data_source = market.candles(self.spec.symbol, self.spec.interval, 400)
        now = int(time.time())
        closed = [c for c in candles if c["time"] + step <= now]
        if not closed:
            return
        live = candles[-1]["close"]
        self.last_price = live
        if self.last_bar_time is None:  # 과거 신호로는 거래하지 않고 지금부터 시작
            self.last_bar_time = closed[-1]["time"]
            self._log(f"시작: {self.spec.symbol} {self.spec.interval}, 기준 봉 {self.last_bar_time}")
            return
        new_idx = [i for i, c in enumerate(closed) if c["time"] > self.last_bar_time]
        n_trades = len(self.sim.trades)
        if new_idx:
            deriv = market.derivatives(self.spec.symbol, self.spec.interval, 200) \
                if needs_derivatives(self.spec) else None
            sig = signals(self.spec, closed, deriv)
            for i in new_idx:
                bar = closed[i]
                if self.sim.position and bar["time"] >= self.sim.position.entry_time:
                    self.sim.check_stops(bar)
                self.sim.accrue_funding(bar["close"])
                self.sim.decide(sig, i)
                self.last_bar_time = bar["time"]
                self.sim.equity_curve.append({"time": bar["time"], "value": self.sim.equity(bar["close"])})
            if self.sim.pending:
                self._log(f"신호: {self.sim.pending} ({self.sim.pending_reason or 'entry'}) @ {live}")
                self.sim.execute_pending(live, now, sig["atr"][new_idx[-1]])
        # 실시간 가격으로 손절/익절/청산 체크
        self.sim.check_stops({"time": now, "open": live, "high": live, "low": live, "close": live})
        for t in self.sim.trades[n_trades:]:
            self._log(f"청산 {t.side} {t.exit_reason}: PnL {t.pnl:+.2f}")

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.spec.name, "symbol": self.spec.symbol,
                "initial_equity": self.initial_equity,
                "interval": self.spec.interval, "running": self.running, "created": self.created,
                "data_source": self.data_source, "last_price": self.last_price,
                "account": self.sim.snapshot(self.last_price), "log": self.log[-50:],
                "equity_curve": self.sim.equity_curve[-500:], "spec": self.spec.model_dump()}


@dataclass
class ManualAccount:
    initial_equity: float = 10_000.0
    fee_pct: float = 0.04
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    prices: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.cash = self.initial_equity

    def _price(self, symbol: str) -> float:
        candles, _ = market.candles(symbol, "1m", 2)
        self.prices[symbol] = candles[-1]["close"]
        return self.prices[symbol]

    def free_margin(self) -> float:
        return self.cash - sum(p.margin for p in self.positions.values())

    def open(self, symbol: str, side: str, margin: float, leverage: float,
             stop_loss_pct: float | None = None, take_profit_pct: float | None = None) -> dict:
        if symbol in self.positions:
            raise ValueError(f"{symbol} 포지션이 이미 있습니다. 먼저 청산하세요.")
        if margin <= 0 or margin > self.free_margin():
            raise ValueError(f"증거금 부족: 사용 가능 {self.free_margin():.2f}")
        price = self._price(symbol)
        s = 1 if side == "long" else -1
        qty = margin * leverage / price
        fee = qty * price * self.fee_pct / 100
        self.cash -= fee
        p = Position(side=s, entry_price=price, qty=qty, margin=margin, leverage=leverage,
                     entry_time=int(time.time()), entry_fee=fee, reason="manual", extreme=price)
        p.liq_price = price * (1 - s * (1 / leverage - MAINT_MARGIN_RATE))
        if stop_loss_pct:
            p.stop = price * (1 - s * stop_loss_pct / 100)
        if take_profit_pct:
            p.take = price * (1 + s * take_profit_pct / 100)
        self.positions[symbol] = p
        return self.snapshot()

    def close(self, symbol: str, reason: str = "manual", price: float | None = None) -> dict:
        p = self.positions.pop(symbol, None)
        if not p:
            raise ValueError(f"{symbol} 포지션이 없습니다.")
        price = price if price is not None else self._price(symbol)
        gross = -p.margin if reason == "liquidation" else p.unrealized(price)
        fee = p.qty * price * self.fee_pct / 100
        self.cash += gross - fee
        net = gross - fee - p.entry_fee
        self.trades.append(Trade(side="long" if p.side == 1 else "short", entry_time=p.entry_time,
                                 exit_time=int(time.time()), entry_price=p.entry_price, exit_price=price,
                                 qty=p.qty, leverage=p.leverage, pnl=net,
                                 pnl_pct_on_margin=net / p.margin * 100, fees=fee + p.entry_fee,
                                 funding=0.0, entry_reason="manual", exit_reason=reason))
        return self.snapshot()

    def tick(self):
        for sym, p in list(self.positions.items()):
            price = self._price(sym)
            adverse = (price <= p.liq_price) if p.side == 1 else (price >= p.liq_price)
            if adverse:
                self.close(sym, "liquidation", p.liq_price)
            elif p.stop and ((price <= p.stop) if p.side == 1 else (price >= p.stop)):
                self.close(sym, "stop_loss", price)
            elif p.take and ((price >= p.take) if p.side == 1 else (price <= p.take)):
                self.close(sym, "take_profit", price)

    def snapshot(self) -> dict:
        pos = []
        upnl = 0.0
        for sym, p in self.positions.items():
            price = self.prices.get(sym, p.entry_price)
            u = p.unrealized(price)
            upnl += u
            pos.append({**asdict(p), "symbol": sym, "side": "long" if p.side == 1 else "short",
                        "mark_price": price, "unrealized_pnl": u, "roe_pct": u / p.margin * 100})
        return {"cash": self.cash, "equity": self.cash + upnl, "free_margin": self.free_margin(),
                "positions": pos, "trades": [asdict(t) for t in self.trades[-100:]]}


class PaperManager:
    def __init__(self):
        self.bots: dict[str, PaperBot] = {}
        self.manual = ManualAccount()
        self._task: asyncio.Task | None = None
        self._path = config.STATE_DIR / "paper.pkl"
        self._load()

    def _load(self):
        try:
            with open(self._path, "rb") as f:
                state = pickle.load(f)
            self.bots, self.manual = state["bots"], state["manual"]
        except Exception:
            pass

    def save(self):
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with _lock, open(self._path, "wb") as f:
            pickle.dump({"bots": self.bots, "manual": self.manual}, f)

    def add_bot(self, spec: StrategySpec, initial_equity: float = 10_000.0) -> PaperBot:
        problems = validate(spec)
        if problems:
            raise ValueError("; ".join(problems))
        bot = PaperBot(spec=spec, initial_equity=initial_equity)
        with _lock:
            self.bots[bot.id] = bot
            bot.tick()
        self.save()
        return bot

    def tick_all(self):
        with _lock:
            for bot in self.bots.values():
                try:
                    bot.tick()
                except Exception as e:
                    bot._log(f"오류: {e}")
            try:
                self.manual.tick()
            except Exception:
                pass
        self.save()

    async def run_forever(self):
        while True:
            await asyncio.to_thread(self.tick_all)
            await asyncio.sleep(config.PAPER_POLL_SECONDS)

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self.run_forever())

    def reset_manual(self, initial_equity: float = 10_000.0, fee_pct: float = 0.04):
        with _lock:
            self.manual = ManualAccount(initial_equity=initial_equity, fee_pct=fee_pct)
        self.save()
