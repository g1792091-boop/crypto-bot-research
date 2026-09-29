from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

LONG = 1
SHORT = -1


@dataclass(frozen=True)
class Bar:
    """One closed bar. ``mark_*`` are mark-price values used for
    liquidation; when absent, last-price values stand in for them."""

    symbol: str
    open_time: int  # ms since epoch
    close_time: int
    open: float
    high: float
    low: float
    close: float
    mark_open: Optional[float] = None
    mark_high: Optional[float] = None
    mark_low: Optional[float] = None
    mark_close: Optional[float] = None
    # True when an aggregated bar is missing some of its 1m bars.
    partial: bool = False

    @property
    def m_open(self) -> float:
        return self.open if self.mark_open is None else self.mark_open

    @property
    def m_high(self) -> float:
        return self.high if self.mark_high is None else self.mark_high

    @property
    def m_low(self) -> float:
        return self.low if self.mark_low is None else self.mark_low

    @property
    def m_close(self) -> float:
        return self.close if self.mark_close is None else self.mark_close


@dataclass(frozen=True)
class Signal:
    """A strategy's request to enter at the next bar open.

    ``ts`` is the close time of the confirmed bar that produced it.
    ``stop_price`` is absolute. ``tier`` picks the sizing tier; ``score``
    ranks competing signals.
    """

    ts: int
    symbol: str
    timeframe: str
    strategy_id: str
    side: int
    stop_price: float
    tier: str = "base"
    score: float = 0.0
    tp_roe: Optional[float] = None
    atr: Optional[float] = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    signal: Signal
    symbol: str
    side: int
    qty: float
    entry_price: float
    entry_time: int
    leverage: int
    tier: str
    margin: float  # current isolated margin (funding moves it)
    margin_initial: float
    stop_price: float
    tp_price: float
    liq_price: float
    entry_fee: float
    funding_paid: float = 0.0
    mae_price: float = 0.0
    mfe_price: float = 0.0

    @property
    def notional_entry(self) -> float:
        return self.qty * self.entry_price


@dataclass
class TradeRecord:
    strategy_id: str
    symbol: str
    timeframe: str
    side: int
    signal_ts: int
    entry_time: int
    entry_price: float
    exit_time: int
    exit_price: float
    exit_reason: str  # TP / SL / LIQ / HALT / MANUAL
    qty: float
    leverage: int
    tier: str
    margin: float
    stop_price: float
    tp_price: float
    liq_price: float
    fees: float
    funding: float
    pnl: float  # net, account currency
    roe: float  # net pnl / margin
    price_move: float  # side-adjusted (exit/entry - 1)
    mae_price: float
    mfe_price: float
    equity_after: float
    score: float


@dataclass
class SignalOutcome:
    """What happened to every submitted signal."""

    signal: Signal
    status: str  # ENTERED / SKIPPED / REJECTED
    reason: str
    step_ts: int
    detail: dict[str, Any] = field(default_factory=dict)
