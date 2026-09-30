"""선물 포지션 시뮬레이터 — 백테스트와 페이퍼 트레이딩이 같은 코드를 쓴다.

체결 규칙 (룩어헤드 방지):
  - 신호는 봉 마감(close) 시점에 판단 → 다음 봉 시가(open)에 체결
  - 손절/익절/추적손절/청산은 봉 내부 고가·저가로 판정.
    같은 봉에서 손절과 익절이 모두 닿으면 보수적으로 손절 먼저.
  - 격리 마진 가정. 유지증거금률 0.5% 로 청산가 계산.
  - 펀딩비: 보유 시간에 비례해 가정 펀딩비를 부과 (롱 지불 / 숏 수령)
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .strategy import RiskSpec

MAINT_MARGIN_RATE = 0.005


@dataclass
class Position:
    side: int                 # +1 롱, -1 숏
    entry_price: float
    qty: float
    margin: float
    leverage: float
    entry_time: int
    stop: float | None = None
    take: float | None = None
    liq_price: float = 0.0
    extreme: float = 0.0      # 추적손절용 최고가(롱)/최저가(숏)
    funding_paid: float = 0.0
    entry_fee: float = 0.0
    reason: str = ""

    @property
    def notional(self) -> float:
        return self.qty * self.entry_price

    def unrealized(self, price: float) -> float:
        return self.side * self.qty * (price - self.entry_price)


@dataclass
class Trade:
    side: str
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    qty: float
    leverage: float
    pnl: float                # 수수료·펀딩 포함 순손익
    pnl_pct_on_margin: float
    fees: float
    funding: float
    entry_reason: str
    exit_reason: str


@dataclass
class Simulator:
    risk: RiskSpec
    initial_equity: float = 10_000.0
    bar_seconds: int = 3600
    cash: float = field(init=False)
    position: Position | None = field(default=None, init=False)
    pending: str | None = field(default=None, init=False)   # 'long' | 'short' | 'close'
    pending_reason: str = field(default="", init=False)
    trades: list[Trade] = field(default_factory=list, init=False)
    equity_curve: list[dict] = field(default_factory=list, init=False)
    blown: bool = field(default=False, init=False)

    def __post_init__(self):
        self.cash = self.initial_equity

    # ------------------------------------------------------------------ 체결
    def _slip(self, price: float, side: int) -> float:
        return price * (1 + side * self.risk.slippage_pct / 100)

    def open_position(self, side: int, price: float, time: int, atr: float | None = None,
                      reason: str = "", margin: float | None = None, leverage: float | None = None,
                      stop_pct: float | None = None, take_pct: float | None = None) -> Position | None:
        if self.position or self.blown or self.cash <= 0:
            return None
        r = self.risk
        lev = leverage or r.leverage
        margin = min(margin if margin is not None else self.cash * r.position_pct / 100, self.cash)
        if margin <= 0:
            return None
        fill = self._slip(price, side)
        qty = margin * lev / fill
        fee = qty * fill * r.fee_pct / 100
        self.cash -= fee
        p = Position(side=side, entry_price=fill, qty=qty, margin=margin, leverage=lev,
                     entry_time=time, extreme=fill, entry_fee=fee, reason=reason)
        p.liq_price = fill * (1 - side * (1 / lev - MAINT_MARGIN_RATE))
        sl_pct = stop_pct if stop_pct is not None else r.stop_loss_pct
        tp_pct = take_pct if take_pct is not None else r.take_profit_pct
        stops, takes = [], []
        if sl_pct:
            stops.append(fill * (1 - side * sl_pct / 100))
        if r.atr_stop_mult and atr:
            stops.append(fill - side * atr * r.atr_stop_mult)
        if tp_pct:
            takes.append(fill * (1 + side * tp_pct / 100))
        if r.atr_tp_mult and atr:
            takes.append(fill + side * atr * r.atr_tp_mult)
        # 여러 손절 기준이 있으면 진입가에 더 가까운(타이트한) 쪽
        if stops:
            p.stop = max(stops) if side == 1 else min(stops)
        if takes:
            p.take = min(takes) if side == 1 else max(takes)
        self.position = p
        return p

    def close_position(self, price: float, time: int, reason: str, slip: bool = True) -> Trade | None:
        p = self.position
        if not p:
            return None
        fill = self._slip(price, -p.side) if slip else price
        pnl_gross = p.unrealized(fill)
        fee = p.qty * fill * self.risk.fee_pct / 100
        if reason == "liquidation":
            pnl_gross = -p.margin  # 격리 마진 전액 손실
        self.cash += pnl_gross - fee
        net = pnl_gross - fee - p.entry_fee - p.funding_paid
        t = Trade(side="long" if p.side == 1 else "short", entry_time=p.entry_time, exit_time=time,
                  entry_price=p.entry_price, exit_price=fill, qty=p.qty, leverage=p.leverage,
                  pnl=net, pnl_pct_on_margin=net / p.margin * 100 if p.margin else 0.0,
                  fees=fee + p.entry_fee, funding=p.funding_paid,
                  entry_reason=p.reason, exit_reason=reason)
        self.trades.append(t)
        self.position = None
        if self.cash <= 0:
            self.blown = True
        return t

    def execute_pending(self, price: float, time: int, atr: float | None = None):
        action, reason = self.pending, self.pending_reason
        self.pending, self.pending_reason = None, ""
        if not action:
            return
        want = {"long": 1, "short": -1}.get(action)
        if self.position and (action == "close" or (want and want != self.position.side)):
            self.close_position(price, time, reason or "signal_exit")
        if want and not self.position:
            self.open_position(want, price, time, atr, reason=action + "_entry")

    # ------------------------------------------------------------------ 봉 처리
    def check_stops(self, bar: dict) -> Trade | None:
        """봉 내부 가격으로 청산/손절/익절/추적손절 판정."""
        p = self.position
        if not p:
            return None
        hi, lo, t = bar["high"], bar["low"], bar["time"]
        r = self.risk
        stop = p.stop
        if r.trailing_stop_pct:
            trail = p.extreme * (1 - p.side * r.trailing_stop_pct / 100)
            stop = trail if stop is None else (max(stop, trail) if p.side == 1 else min(stop, trail))
        adverse = lo if p.side == 1 else hi
        favorable = hi if p.side == 1 else lo

        def hit(level):  # 불리한 방향 레벨 도달 여부
            return level is not None and (adverse <= level if p.side == 1 else adverse >= level)

        # 청산가가 손절가보다 먼저 닿는 경우 → 강제청산
        liq_first = stop is None or (p.liq_price >= stop if p.side == 1 else p.liq_price <= stop)
        if hit(p.liq_price) and liq_first:
            return self.close_position(p.liq_price, t, "liquidation", slip=False)
        if hit(stop):
            # 갭으로 시가가 이미 손절가를 넘었으면 시가 체결
            px = min(stop, bar["open"]) if p.side == 1 else max(stop, bar["open"])
            return self.close_position(px, t, "trailing_stop" if stop != p.stop else "stop_loss")
        if p.take is not None and (favorable >= p.take if p.side == 1 else favorable <= p.take):
            px = max(p.take, bar["open"]) if p.side == 1 else min(p.take, bar["open"])
            return self.close_position(px, t, "take_profit", slip=False)
        p.extreme = max(p.extreme, hi) if p.side == 1 else min(p.extreme, lo)
        return None

    def accrue_funding(self, price: float):
        p = self.position
        if not p or not self.risk.funding_rate_8h_pct:
            return
        cost = p.side * p.qty * price * self.risk.funding_rate_8h_pct / 100 * self.bar_seconds / 28800
        p.funding_paid += cost
        self.cash -= cost

    def equity(self, price: float) -> float:
        return self.cash + (self.position.unrealized(price) if self.position else 0.0)

    def decide(self, sig: dict, i: int):
        """봉 i 마감 시점의 신호로 다음 봉에 실행할 주문을 예약."""
        p = self.position
        le, se = sig["long_entry"][i], sig["short_entry"][i]
        lx, sx = sig["long_exit"][i], sig["short_exit"][i]
        if p is None:
            if le and not se:
                self.pending = "long"
            elif se and not le:
                self.pending = "short"
        elif p.side == 1:
            if se and self.risk.allow_reverse:
                self.pending, self.pending_reason = "short", "reverse_signal"
            elif lx or se:
                self.pending, self.pending_reason = "close", "exit_signal"
        else:
            if le and self.risk.allow_reverse:
                self.pending, self.pending_reason = "long", "reverse_signal"
            elif sx or le:
                self.pending, self.pending_reason = "close", "exit_signal"

    def step(self, bar: dict, sig: dict, i: int):
        """백테스트 1봉: 시가 체결 → 봉중 손절/익절 → 펀딩 → 종가 신호 판단 → 에쿼티 기록."""
        atr_prev = sig["atr"][i - 1] if i > 0 else None
        self.execute_pending(bar["open"], bar["time"], atr_prev)
        self.check_stops(bar)
        self.accrue_funding(bar["close"])
        if not self.blown:
            self.decide(sig, i)
        self.equity_curve.append({"time": bar["time"], "value": round(self.equity(bar["close"]), 4)})

    def snapshot(self, price: float | None = None) -> dict:
        pos = None
        if self.position:
            p = self.position
            pos = {**asdict(p), "side": "long" if p.side == 1 else "short"}
            if price is not None:
                pos["mark_price"] = price
                pos["unrealized_pnl"] = p.unrealized(price)
                pos["roe_pct"] = p.unrealized(price) / p.margin * 100
        return {"cash": self.cash, "equity": self.equity(price) if price else self.cash,
                "position": pos, "pending": self.pending, "blown": self.blown,
                "trades": [asdict(t) for t in self.trades[-200:]]}


def metrics(sim: Simulator, bar_seconds: int) -> dict:
    eq = [p["value"] for p in sim.equity_curve]
    trades = sim.trades
    if not eq:
        return {}
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100 if peak > 0 else 100.0)
    rets = [(eq[i] - eq[i - 1]) / eq[i - 1] for i in range(1, len(eq)) if eq[i - 1] > 0]
    sharpe = None
    if len(rets) > 2:
        mu = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
        if sd > 0:
            sharpe = mu / sd * math.sqrt(365 * 86400 / bar_seconds)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_win, gross_loss = sum(t.pnl for t in wins), -sum(t.pnl for t in losses)
    in_market = sum(t.exit_time - t.entry_time for t in trades)
    span = sim.equity_curve[-1]["time"] - sim.equity_curve[0]["time"] or 1
    return {
        "initial_equity": sim.initial_equity,
        "final_equity": round(eq[-1], 2),
        "total_return_pct": round((eq[-1] / sim.initial_equity - 1) * 100, 2),
        "max_drawdown_pct": round(mdd, 2),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "avg_trade_pnl": round(sum(t.pnl for t in trades) / len(trades), 2) if trades else None,
        "long_trades": sum(1 for t in trades if t.side == "long"),
        "short_trades": sum(1 for t in trades if t.side == "short"),
        "liquidations": sum(1 for t in trades if t.exit_reason == "liquidation"),
        "fees_paid": round(sum(t.fees for t in trades), 2),
        "funding_paid": round(sum(t.funding for t in trades), 2),
        "exposure_pct": round(in_market / span * 100, 1),
        "blown_up": sim.blown,
    }
