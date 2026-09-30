"""Paper engine settings.

Every number here is a rule fixed before looking at results. Changing one
means bumping ``version`` so ledgers record which rule set produced them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .ladder import LadderSpec


@dataclass(frozen=True)
class Tier:
    """A sizing tier: fraction of equity used as isolated margin, and the
    leverage candidates to try, highest first."""

    name: str
    margin_frac: float
    leverages: tuple[int, ...]


# Tiers from the owners' rules: base 20% x 20x, good 30% x 30x,
# best 40% x 50x (falls back to 40x if 50x fails the safety checks).
DEFAULT_TIERS: tuple[Tier, ...] = (
    Tier("best", 0.40, (50, 40)),
    Tier("good", 0.30, (30,)),
    Tier("base", 0.20, (20,)),
)


@dataclass(frozen=True)
class Settings:
    # v2: take-profit is net ROE (after the 0.14% round trip), owners' decision 2026-09-30.
    version: str = "paper-v2"

    symbols: tuple[str, ...] = (
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "LTCUSDT", "BCHUSDT", "DOGEUSDT",
    )

    initial_equity: float = 1000.0

    # Binance USD-M VIP0 defaults. Replace with the account's real rates
    # (GET /fapi/v1/commissionRate) before running against live data.
    taker_fee: float = 0.0005
    maker_fee: float = 0.0002
    # Adverse slippage applied to market and stop-market fills.
    slippage_frac: float = 0.0002

    tiers: tuple[Tier, ...] = DEFAULT_TIERS
    min_leverage: int = 20
    max_leverage: int = 50
    min_margin_frac: float = 0.20
    max_margin_frac: float = 0.40

    # A stop-out may cost at most this fraction of equity, fees included.
    max_loss_frac: float = 0.15

    # The stop must sit inside the liquidation price by at least
    # max(liq_buffer_atr_mult * ATR, liq_buffer_min_frac * entry).
    liq_buffer_atr_mult: float = 3.0
    liq_buffer_min_frac: float = 0.002

    default_tp_roe: float = 0.10  # net of costs, see round_trip_cost

    @property
    def round_trip_cost(self) -> float:
        """Conservative round trip as a fraction of notional: taker fee and
        slippage on both sides (0.14% with the defaults)."""
        return 2 * (self.taker_fee + self.slippage_frac)

    # Only one open position across all symbols.
    single_position: bool = True
    # When several signals compete for the same step, ties on score are
    # broken by this symbol order.
    symbol_priority: tuple[str, ...] = field(default=None)  # type: ignore[assignment]

    # Drawdown from peak equity: warn at each level, halt at dd_halt
    # (None = warnings only, the owners' paper v3 rule).
    dd_warn_levels: tuple[float, ...] = (0.20, 0.30, 0.40)
    dd_halt: Optional[float] = 0.50

    # "fixed": one take-profit at default_tp_roe (paper v2).
    # "ladder": no take-profit; the stop steps up to lock net ROE (ladder.py).
    tp_mode: str = "fixed"
    ladder_first_lock: float = 0.10
    ladder_step: float = 0.05
    ladder_trigger_gap: float = 0.02

    # The account stops for good when its wallet falls below this (0 = never).
    bust_below: float = 0.0

    # When a bar touches both stop and take-profit, assume the stop filled
    # first (conservative). Set False only for sensitivity runs.
    stop_first_on_ambiguous_bar: bool = True

    def __post_init__(self) -> None:
        if self.symbol_priority is None:
            object.__setattr__(self, "symbol_priority", self.symbols)
        for t in self.tiers:
            if not (self.min_margin_frac <= t.margin_frac <= self.max_margin_frac):
                raise ValueError(f"tier {t.name} margin outside owner range")
            for lev in t.leverages:
                if not (self.min_leverage <= lev <= self.max_leverage):
                    raise ValueError(f"tier {t.name} leverage outside owner range")
        if self.tp_mode not in ("fixed", "ladder"):
            raise ValueError(f"unknown tp_mode {self.tp_mode!r}")

    @property
    def ladder(self) -> LadderSpec:
        return LadderSpec(self.ladder_first_lock, self.ladder_step, self.ladder_trigger_gap)

    def tier_chain(self, requested: str) -> list[tuple[Tier, int]]:
        """Candidates from the requested tier down to the lowest tier."""
        names = [t.name for t in self.tiers]
        if requested not in names:
            raise ValueError(f"unknown tier {requested!r}")
        chain = []
        for t in self.tiers[names.index(requested):]:
            for lev in t.leverages:
                chain.append((t, lev))
        return chain


# Paper v3 (docs/paper-v3-rules.md): six coins, entry priority by traded value,
# stepped profit lock, 2 ATR stop (set by the signal), no drawdown halt.
V3_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
V3_STOP_ATR = 2.0


def v3_settings(**over) -> Settings:
    kw = dict(version="paper-v3", symbols=V3_SYMBOLS, symbol_priority=V3_SYMBOLS,
              tp_mode="ladder", dd_halt=None, bust_below=10.0, liq_buffer_atr_mult=1.0)
    kw.update(over)
    return Settings(**kw)
