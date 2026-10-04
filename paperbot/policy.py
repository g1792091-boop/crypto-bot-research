"""Sizing and exit policies, one per ledger ("book").

OwnerPolicy       the owners' rules: 20-50x, 20-50% margin tiers, ROE take-profit,
                  15% stop-loss cap. See config.Settings (``leverage_rule``: the old
                  tier walk, or the restarted paper v3 run's "quality_v1", levrule.py).
RecommendedPolicy the analysis session's rules (handover 4.5 / 5.3): risk a fixed
                  share of equity per trade, size = risk / stop distance, leverage
                  is the result (capped), take-profit in R multiples or the
                  strategy's own target.

Both books receive the same signals, so their difference is the rules alone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Protocol

from .config import Settings
from .levrule import requested_tier
from .margin import Brackets, liquidation_price
from .models import Signal, TradeRecord
from .sizing import SizeDecision, size_position, tp_from_roe


class Policy(Protocol):
    name: str

    def size(self, equity: float, sig: Signal, entry: float, brackets: Brackets,
             spec: dict) -> SizeDecision: ...

    def take_profit(self, sig: Signal, entry: float, dec: SizeDecision) -> float: ...


class OwnerPolicy:
    name = "owner"

    def __init__(self, settings: Settings):
        self.s = settings

    def size(self, equity, sig, entry, brackets, spec):
        # "tier_walk": the signal's own tier; "quality_v1": its group (levrule.signal_group)
        return size_position(self.s, equity, sig.side, entry, sig.stop_price, requested_tier(self.s, sig),
                             brackets, atr=sig.atr, qty_step=spec.get("qty_step", 0.0),
                             min_notional=spec.get("min_notional", 0.0))

    def take_profit(self, sig, entry, dec):
        roe = sig.tp_roe if sig.tp_roe is not None else self.s.default_tp_roe
        return tp_from_roe(sig.side, entry, dec.leverage, roe, round_trip=self.s.round_trip_cost)


@dataclass(frozen=True)
class RecommendedSettings:
    """Initial values for the recommended book. Fixed before results; change
    only by bumping ``version``."""

    version: str = "recommended-v1"
    risk_frac: float = 0.01
    # 2% only for the top tier, and only after the setup score has passed
    # its validation (handover 4.4-4). Stays False until then.
    best_risk_frac: float = 0.02
    best_tier_validated: bool = False
    max_leverage: int = 10
    # Take-profit when the strategy gives no target: this many R.
    default_rr: float = 2.0
    liq_buffer_atr_mult: float = 3.0
    liq_buffer_min_frac: float = 0.002
    # Guards (handover 5.3). Numbers are initial values; the handover names
    # the controls but not the values.
    daily_loss_frac: float = 0.03
    max_consecutive_losses: int = 5
    cooldown_ms: int = 24 * 3_600_000


class RecommendedPolicy:
    name = "recommended"

    def __init__(self, base: Settings, rec: RecommendedSettings = RecommendedSettings()):
        self.s = base  # fees and slippage are shared with the owner book
        self.r = rec

    def size(self, equity, sig, entry, brackets, spec):
        side, stop = sig.side, sig.stop_price
        reasons: list[str] = []
        if equity <= 0:
            return SizeDecision(False, reasons=["no equity"])
        if (entry - stop) * side <= 0:
            return SizeDecision(False, reasons=["stop on wrong side of entry"])
        risk_frac = self.r.risk_frac
        if sig.tier == "best" and self.r.best_tier_validated:
            risk_frac = self.r.best_risk_frac
        risk = equity * risk_frac

        exit_px = stop * (1 - side * self.s.slippage_frac)
        per_unit = (abs(entry - exit_px) + entry * self.s.taker_fee
                    + exit_px * self.s.taker_fee)
        step = spec.get("qty_step", 0.0)
        qty = risk / per_unit
        cap_qty = self.r.max_leverage * equity / entry
        if qty > cap_qty:
            reasons.append(f"capped at {self.r.max_leverage}x (risk below {risk_frac:.0%})")
            qty = cap_qty
        if step > 0:
            qty = math.floor(qty / step + 1e-9) * step
        notional = qty * entry
        if qty <= 0 or notional < spec.get("min_notional", 0.0):
            return SizeDecision(False, reasons=reasons + ["below minimum order size"])

        # Lowest whole leverage whose margin fits the wallet.
        lev = max(1, math.ceil(notional / equity - 1e-9))
        bracket = brackets.for_notional(notional)
        if lev > bracket.max_leverage:
            return SizeDecision(False, reasons=reasons + [
                f"needs {lev}x, bracket allows {bracket.max_leverage}x"])
        margin = notional / lev
        liq = liquidation_price(side, qty, entry, margin, bracket)
        buffer = self.r.liq_buffer_min_frac * entry
        if sig.atr is not None:
            buffer = max(buffer, self.r.liq_buffer_atr_mult * sig.atr)
        if (stop - liq) * side < buffer:
            return SizeDecision(False, reasons=reasons + [
                f"stop {stop:.6g} too close to liq {liq:.6g} at {lev}x"])
        loss = qty * per_unit
        return SizeDecision(True, tier=sig.tier, leverage=lev, margin=margin, qty=qty,
                            liq_price=liq, loss_at_stop=loss, reasons=reasons)

    def take_profit(self, sig, entry, dec):
        if sig.tp_price is not None and (sig.tp_price - entry) * sig.side > 0:
            return sig.tp_price
        return entry + sig.side * self.r.default_rr * abs(entry - sig.stop_price)


class RiskGuards:
    """Daily loss limit and consecutive-loss pause for the recommended book.
    The trading day resets at 00:00 UTC (09:00 KST)."""

    DAY_MS = 86_400_000

    def __init__(self, rec: RecommendedSettings):
        self.r = rec
        self.day: Optional[int] = None
        self.day_start_equity = 0.0
        self.consecutive_losses = 0
        self.paused_until = 0
        self.day_blocked = False

    def check(self, ts: int, equity: float) -> Optional[str]:
        day = ts // self.DAY_MS
        if day != self.day:
            self.day = day
            self.day_start_equity = equity
            self.day_blocked = False
        if ts < self.paused_until:
            return (f"paused after {self.r.max_consecutive_losses} consecutive losses "
                    f"until {self.paused_until}")
        if equity <= self.day_start_equity * (1 - self.r.daily_loss_frac):
            self.day_blocked = True
        if self.day_blocked:
            return f"daily loss limit {self.r.daily_loss_frac:.0%} reached"
        return None

    def on_trade(self, rec: TradeRecord) -> None:
        if rec.pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.r.max_consecutive_losses:
                self.paused_until = rec.exit_time + self.r.cooldown_ms
                self.consecutive_losses = 0
        else:
            self.consecutive_losses = 0
