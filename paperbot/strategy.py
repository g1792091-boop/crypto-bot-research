"""Strategy plug-in interface.

A strategy sees only confirmed bars of its own timeframe and returns the
signals it wants to take at the next bar open. It never places orders and
never sees future bars.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from .models import Bar, Signal


class Strategy(Protocol):
    strategy_id: str
    timeframe: str
    warmup_bars: int

    def on_bar(self, symbol: str, history: Sequence[Bar]) -> list[Signal]:
        """``history`` ends with the bar that just closed."""
        ...


class StrategyRunner:
    """Feeds each strategy its own confirmed-bar history per symbol and
    enforces the warm-up rule."""

    def __init__(self, strategies: Sequence[Strategy], max_history: int = 2000):
        self.strategies = list(strategies)
        self.max_history = max_history
        self.history: dict[tuple[str, str], list[Bar]] = {}

    def on_closed_bar(self, timeframe: str, bar: Bar) -> list[Signal]:
        key = (bar.symbol, timeframe)
        hist = self.history.setdefault(key, [])
        if hist and bar.open_time <= hist[-1].open_time:
            raise ValueError(f"out-of-order bar for {key}")
        hist.append(bar)
        if len(hist) > self.max_history:
            del hist[: len(hist) - self.max_history]
        out: list[Signal] = []
        for strat in self.strategies:
            if strat.timeframe != timeframe or len(hist) < strat.warmup_bars:
                continue
            for sig in strat.on_bar(bar.symbol, hist):
                if sig.ts != bar.close_time:
                    raise ValueError(
                        f"{strat.strategy_id} emitted a signal not stamped "
                        f"with the closed bar's time")
                out.append(sig)
        return out
