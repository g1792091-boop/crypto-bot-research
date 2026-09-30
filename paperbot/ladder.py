"""Stepped profit lock ("계단식 익절"), the owners' take-profit rule of 2026-09-30.

There is no fixed take-profit. Once the best net ROE of an open position
reaches a trigger, the stop moves to lock a lower net ROE:

    best net ROE >= 12%  ->  lock 10%
    best net ROE >= 17%  ->  lock 15%
    best net ROE >= 22%  ->  lock 20%     ... and so on in 5% steps.

Net ROE is on isolated margin after costs, the same definition as
``sizing.tp_from_roe``: price distance = roe / leverage + round_trip + funding,
where round_trip covers taker fees and slippage on both sides.

The lock only ever tightens. When it is raised on a bar, it applies from the
next bar (the order of the high and the low inside one bar is unknown, so the
conservative reading is that the bar's low came first).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LadderSpec:
    first_lock: float = 0.10     # first locked net ROE
    step: float = 0.05           # each further lock is this much higher
    trigger_gap: float = 0.02    # a lock arms when best net ROE >= lock + gap

    def lock_for(self, best_roe: float) -> Optional[float]:
        """Highest lock armed by ``best_roe`` (net), or None below the first trigger."""
        first_trigger = self.first_lock + self.trigger_gap
        if not best_roe >= first_trigger - 1e-12:
            return None
        n = math.floor((best_roe - first_trigger) / self.step + 1e-9)
        return self.first_lock + self.step * n


def net_roe(side: int, entry: float, price: float, leverage: float,
            round_trip: float, funding: float = 0.0) -> float:
    """Net ROE on margin if the position were closed at ``price``."""
    return leverage * (side * (price / entry - 1.0) - round_trip - funding)


def roe_price(side: int, entry: float, leverage: float, roe: float,
              round_trip: float, funding: float = 0.0) -> float:
    """Price at which the net ROE equals ``roe`` (inverse of ``net_roe``)."""
    return entry * (1.0 + side * (roe / leverage + round_trip + funding))


def tighten(side: int, stop: float, candidate: Optional[float]) -> float:
    """The tighter of the current stop and a candidate lock price."""
    if candidate is None:
        return stop
    return max(stop, candidate) if side == 1 else min(stop, candidate)
