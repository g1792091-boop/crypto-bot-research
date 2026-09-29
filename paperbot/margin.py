"""Isolated-margin math for Binance USD-M one-way positions.

Liquidation price (isolated, single position), from Binance's published
formula with the other-position terms set to zero:

    LP = (WB + cum - side * Q * EP) / (Q * MMR - side * Q)

WB is the position's isolated margin, Q its size, EP the entry price, MMR
and cum the maintenance margin rate and amount for the position's notional
bracket. Liquidation triggers on the mark price.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BracketTier:
    notional_cap: float
    max_leverage: int
    mmr: float
    cum: float


class Brackets:
    """Leverage brackets for one symbol, lowest notional first.

    Load real values from GET /fapi/v1/leverageBracket. The example table
    in ``example()`` exists only for tests and offline runs.
    """

    def __init__(self, tiers: list[BracketTier]):
        if not tiers:
            raise ValueError("empty bracket table")
        self.tiers = sorted(tiers, key=lambda t: t.notional_cap)

    def for_notional(self, notional: float) -> BracketTier:
        for t in self.tiers:
            if notional <= t.notional_cap:
                return t
        return self.tiers[-1]

    @classmethod
    def from_binance(cls, payload: dict) -> "Brackets":
        """Build from one element of the leverageBracket response."""
        tiers = [
            BracketTier(
                notional_cap=float(b["notionalCap"]),
                max_leverage=int(b["initialLeverage"]),
                mmr=float(b["maintMarginRatio"]),
                cum=float(b["cum"]),
            )
            for b in payload["brackets"]
        ]
        return cls(tiers)

    @classmethod
    def example(cls) -> "Brackets":
        return cls([
            BracketTier(50_000, 50, 0.005, 0.0),
            BracketTier(250_000, 25, 0.01, 250.0),
            BracketTier(1_000_000, 10, 0.025, 4_000.0),
        ])


def liquidation_price(side: int, qty: float, entry: float, margin: float,
                      bracket: BracketTier) -> float:
    denom = qty * bracket.mmr - side * qty
    lp = (margin + bracket.cum - side * qty * entry) / denom
    return max(lp, 0.0)
