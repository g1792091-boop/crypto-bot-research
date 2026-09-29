"""Pick margin and leverage for a signal within the owners' rules.

Order of checks for each candidate (requested tier first, then lower):
1. leverage allowed by the symbol's bracket for this notional
2. stop sits inside liquidation by the required buffer
3. loss at the stop, fees and slippage included, <= max_loss_frac of equity
The first candidate that passes wins. If none pass, the entry is rejected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .config import Settings
from .margin import Brackets, liquidation_price


@dataclass
class SizeDecision:
    ok: bool
    tier: str = ""
    leverage: int = 0
    margin: float = 0.0
    qty: float = 0.0
    liq_price: float = 0.0
    loss_at_stop: float = 0.0
    reasons: list[str] = field(default_factory=list)


def _round_down(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step + 1e-9) * step


def size_position(settings: Settings, equity: float, side: int, entry: float,
                  stop: float, requested_tier: str, brackets: Brackets,
                  atr: Optional[float] = None, qty_step: float = 0.0,
                  min_notional: float = 0.0) -> SizeDecision:
    reasons: list[str] = []
    if equity <= 0:
        return SizeDecision(False, reasons=["no equity"])
    if (entry - stop) * side <= 0:
        return SizeDecision(False, reasons=["stop on wrong side of entry"])

    buffer = settings.liq_buffer_min_frac * entry
    if atr is not None:
        buffer = max(buffer, settings.liq_buffer_atr_mult * atr)

    stop_dist = abs(entry - stop)
    for tier, lev in settings.tier_chain(requested_tier):
        margin = equity * tier.margin_frac
        qty = _round_down(margin * lev / entry, qty_step)
        notional = qty * entry
        tag = f"{tier.name}/{lev}x"
        if qty <= 0 or notional < min_notional:
            reasons.append(f"{tag}: below minimum order size")
            continue
        margin = notional / lev
        bracket = brackets.for_notional(notional)
        if lev > bracket.max_leverage:
            reasons.append(f"{tag}: bracket allows {bracket.max_leverage}x")
            continue
        liq = liquidation_price(side, qty, entry, margin, bracket)
        room = (stop - liq) * side
        if room < buffer:
            reasons.append(f"{tag}: stop {stop:.6g} too close to liq {liq:.6g}")
            continue
        exit_px = stop * (1 - side * settings.slippage_frac)
        loss = (qty * stop_dist + qty * abs(stop - exit_px)
                + notional * settings.taker_fee
                + qty * exit_px * settings.taker_fee)
        if loss > settings.max_loss_frac * equity:
            reasons.append(
                f"{tag}: stop loss {loss:.2f} > {settings.max_loss_frac:.0%} of equity")
            continue
        return SizeDecision(True, tier.name, lev, margin, qty, liq, loss, reasons)
    return SizeDecision(False, reasons=reasons)


def tp_from_roe(side: int, entry: float, leverage: int, roe: float,
                round_trip: float = 0.0, funding: float = 0.0) -> float:
    """Take-profit price for an ROE target on isolated margin.

    With ``round_trip`` (and expected ``funding``) as fractions of notional the
    target is net of costs: price distance = roe / leverage + round_trip +
    funding. The owners set 10% net ROE (2026-09-30); with the conservative
    0.14% round trip this is 0.64% at 20x, 0.47% at 30x, 0.39% at 40x and
    0.34% at 50x, the same figures the backtest session used."""
    return entry * (1 + side * (roe / leverage + round_trip + funding))
