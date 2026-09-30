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
    auto_improve: bool = False          # 거래가 쌓이면 스스로 복기·개선
    improve_every: int = 10             # 새 거래 N건마다 개선 시도
    improved_at_trades: int = 0
    journal: list[dict] = field(default_factory=list)    # 거래별 복기 노트
    versions: list[dict] = field(default_factory=list)   # 전략 변경 이력
    sim: Simulator = field(init=False)

    def __post_init__(self):
        self.sim = Simulator(risk=self.spec.risk, initial_equity=self.initial_equity,
                             bar_seconds=INTERVAL_SECONDS.get(self.spec.interval, 3600))
        self.versions.append({"time": int(time.time()), "reason": "시작", "spec": self.spec.model_dump()})

    def __setstate__(self, state):
        # 예전 버전에서 저장한 봇도 새 필드 기본값으로 불러온다
        defaults = {"auto_improve": False, "improve_every": 10, "improved_at_trades": 0, "journal": [], "versions": []}
        self.__dict__.update({**defaults, **state})

    def _review(self, trades: list[Trade], candles: list[dict]):
        """새로 끝난 거래를 복기 노트에 남긴다."""
        from . import improve
        fs = improve.feature_series(candles)
        for t in trades:
            td = asdict(t)
            note = improve.explain(td, improve.trade_features(candles, fs, td))
            self.journal.append(note)
            self._log(("익절 복기: " if note["win"] else "손실 복기: ") + note["note"])
        self.journal = self.journal[-300:]

    def maybe_improve(self, force: bool = False) -> dict | None:
        from . import improve
        n = len(self.sim.trades)
        if not force and (not self.auto_improve or n - self.improved_at_trades < self.improve_every):
            return None
        self.improved_at_trades = n
        rep = improve.run_for(self.spec, 1500)
        if rep["applied"]:
            new = StrategySpec(**rep["spec"])
            new.name = self.spec.name
            self.spec = new
            self.sim.risk = new.risk
            self.versions.append({"time": int(time.time()), "reason": " / ".join(rep["changes"]), "spec": new.model_dump(),
                                  "before": rep["baseline"], "after": rep["after"]})
            self._log("자동 개선 적용: " + " / ".join(rep["changes"]))
        else:
            self._log("자동 개선 검토: 검증 구간에서 나아지는 변경이 없어 전략 유지")
        return rep

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
            if self.sim.pending in ("long", "short"):
                from .team.engine import gate_allows
                if not gate_allows(self.spec.symbol, self.sim.pending):   # 에이전트 팀 허용범위 밖 (봇 관문이 켜졌을 때만)
                    self._log(f"신호 {self.sim.pending} — 에이전트 팀 오늘의 허용범위 밖이라 진입 안 함")
                    self.sim.pending, self.sim.pending_reason = ("close" if self.sim.position else None), ""
            if self.sim.pending:
                self._log(f"신호: {self.sim.pending} ({self.sim.pending_reason or 'entry'}) @ {live}")
                self.sim.execute_pending(live, now, sig["atr"][new_idx[-1]])
        # 실시간 가격으로 손절/익절/청산 체크
        self.sim.check_stops({"time": now, "open": live, "high": live, "low": live, "close": live})
        if len(self.sim.trades) > n_trades:
            try:
                self._review(self.sim.trades[n_trades:], candles)
                self.maybe_improve()
            except Exception as e:
                self._log(f"복기/개선 오류: {e}")
        for t in self.sim.trades[n_trades:]:
            self._log(f"청산 {t.side} {t.exit_reason}: PnL {t.pnl:+.2f}")

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.spec.name, "symbol": self.spec.symbol,
                "initial_equity": self.initial_equity,
                "interval": self.spec.interval, "running": self.running, "created": self.created,
                "data_source": self.data_source, "last_price": self.last_price,
                "account": self.sim.snapshot(self.last_price), "log": self.log[-50:],
                "equity_curve": self.sim.equity_curve[-500:], "spec": self.spec.model_dump(),
                "auto_improve": self.auto_improve, "improve_every": self.improve_every,
                "journal": self.journal[-30:], "versions": [{k: v for k, v in x.items() if k != "spec"} for x in self.versions[-20:]]}

    def markers(self) -> dict:
        """차트 표시용: 진입·청산 지점과 현재 포지션."""
        p = self.sim.position
        return {"id": self.id, "name": self.spec.name, "interval": self.spec.interval,
                "trades": [asdict(t) for t in self.sim.trades[-300:]],
                "position": None if not p else {"side": "long" if p.side == 1 else "short", "entry_price": p.entry_price,
                                                "entry_time": p.entry_time, "stop": p.stop, "take": p.take,
                                                "liq_price": p.liq_price}}


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

    def modify(self, symbol: str, stop: float | None, take: float | None) -> dict:
        """열린 포지션의 손절가·익절가 수정 (None 이면 해제)."""
        p = self.positions.get(symbol)
        if not p:
            raise ValueError(f"{symbol} 포지션이 없습니다.")
        price = self._price(symbol)
        long_ = p.side == 1
        if stop is not None:
            if (long_ and stop >= price) or (not long_ and stop <= price):
                raise ValueError(f"손절가는 현재가({price:,.2f})보다 {'낮아야' if long_ else '높아야'} 합니다.")
            if (long_ and stop <= p.liq_price) or (not long_ and stop >= p.liq_price):
                raise ValueError(f"손절가가 강제청산가({p.liq_price:,.2f})를 넘어갑니다.")
        if take is not None and ((long_ and take <= price) or (not long_ and take >= price)):
            raise ValueError(f"익절가는 현재가({price:,.2f})보다 {'높아야' if long_ else '낮아야'} 합니다.")
        p.stop, p.take = stop, take
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
                                 funding=0.0, entry_reason="manual", exit_reason=reason, symbol=symbol))
        return self.snapshot()

    def reduce(self, symbol: str, fraction: float) -> dict:
        """포지션 일부만 청산 (fraction = 0~1). 1 이상이면 전부 청산."""
        p = self.positions.get(symbol)
        if not p:
            raise ValueError(f"{symbol} 포지션이 없습니다.")
        if fraction >= 0.999:
            return self.close(symbol)
        if fraction <= 0:
            raise ValueError("청산 비율은 0보다 커야 합니다.")
        price = self._price(symbol)
        q = p.qty * fraction
        gross = p.side * q * (price - p.entry_price)
        fee, efee, m = q * price * self.fee_pct / 100, p.entry_fee * fraction, p.margin * fraction
        self.cash += gross - fee
        net = gross - fee - efee
        self.trades.append(Trade(side="long" if p.side == 1 else "short", entry_time=p.entry_time, exit_time=int(time.time()),
                                 entry_price=p.entry_price, exit_price=price, qty=q, leverage=p.leverage, pnl=net,
                                 pnl_pct_on_margin=net / m * 100, fees=fee + efee, funding=0.0, entry_reason="manual",
                                 exit_reason=f"partial_{round(fraction * 100)}", symbol=symbol))
        p.qty -= q
        p.margin -= m
        p.entry_fee -= efee
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
