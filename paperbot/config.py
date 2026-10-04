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
# This is the "tier_walk" rule: every v3 signal requests "best" and walks down 50x, 40x, 30x, 20x until one
# candidate passes the safety checks. The restarted paper v3 run uses "quality_v1" instead (V3_LEVERAGE_RULE).
DEFAULT_TIERS: tuple[Tier, ...] = (
    Tier("best", 0.40, (50, 40)),
    Tier("good", 0.30, (30,)),
    Tier("base", 0.20, (20,)),
)

LEVERAGE_RULES = ("tier_walk", "quality_v1")
QUALITY_GROUPS = ("best", "normal")


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
    # How a signal's candidates are chosen (LEVERAGE_RULES). "tier_walk": from the signal's requested tier down
    # to the lowest tier (tier names unique). "quality_v1" (owners 2026-10-04, paperbot/levrule.py): the tiers are
    # named by group ("best" / "normal"); a signal requests its group and tries that group's tiers in order, and a
    # "best" signal then also tries the "normal" tiers when ``best_falls_to_normal`` is True.
    leverage_rule: str = "tier_walk"
    best_falls_to_normal: bool = True
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
        if self.leverage_rule not in LEVERAGE_RULES:
            raise ValueError(f"unknown leverage_rule {self.leverage_rule!r}")
        if self.leverage_rule == "quality_v1":
            names = {t.name for t in self.tiers}
            if names != set(QUALITY_GROUPS):
                raise ValueError(f"quality_v1 needs tiers named {QUALITY_GROUPS}, got {sorted(names)}")

    @property
    def ladder(self) -> LadderSpec:
        return LadderSpec(self.ladder_first_lock, self.ladder_step, self.ladder_trigger_gap)

    def tier_chain(self, requested: str) -> list[tuple[Tier, int]]:
        """Candidates from the requested tier down to the lowest tier ("tier_walk"); with "quality_v1" the
        requested group's tiers in table order (then the "normal" tiers for "best" if ``best_falls_to_normal``)."""
        if self.leverage_rule == "quality_v1":
            if requested not in QUALITY_GROUPS:
                raise ValueError(f"unknown group {requested!r}")
            groups = (requested, "normal") if requested == "best" and self.best_falls_to_normal else (requested,)
            return [(t, lev) for g in groups for t in self.tiers if t.name == g for lev in t.leverages]
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
# Each account starts with this many USDT (owners' decision 2026-09-30, was 1,000).
V3_INITIAL = 5000.0
# Traded timeframes. 5m was removed by the owners on 2026-10-04 together with the restart from scratch
# (docs/paper-v3-rules-change-1.md): no 5m strategy or coin-flip accounts. 5m bars stay the signal
# service's internal base bars (the other timeframes are built from them). 1d is record-only.
V3_TRADE_TFS = ("15m", "30m", "1h", "4h")
V3_OBSERVE_TFS = ("4h",)             # addendum Q3: observation only, outside the Q1 verdict family
V3_JUDGED_TFS = tuple(tf for tf in V3_TRADE_TFS if tf not in V3_OBSERVE_TFS)
V3_STRATEGIES = 36                   # locked strategies, DOGE_L + DOGE_S joined as DOGE (sigservice.strategy_names)
V3_RANDOM_SEEDS = (1, 2, 3)          # coin-flip accounts per timeframe
V3_ACCOUNTS = (V3_STRATEGIES + len(V3_RANDOM_SEEDS)) * len(V3_TRADE_TFS)   # 156 original accounts
V3_Q1_MAIN_FAMILY = V3_STRATEGIES * len(V3_JUDGED_TFS)                      # 108 (15m / 30m / 1h)


# Leverage and margin of the restarted run (owners 2026-10-04, "B로 가자"; docs/paper-v3-rules-change-1.md section 6,
# paperbot/levrule.py). A signal whose entry-quality tier is "best" (levrule.quality_score, = obsshadows.quality_score:
# mean period-1 quintile of its recorded strength >= 4) tries 50x with 50% of equity as margin, then 40x with 40%;
# every other signal (tier good / base, or no score: no strength recorded, no edges for the strategy x timeframe, no
# usable value, an error) tries 30x with 30%, then 20x with 20%. Margin share = leverage %. Each candidate passes the usual checks in order (exchange bracket,
# stop inside liquidation by max(1 ATR, 0.2%), loss at the stop <= 15% of equity), the first that passes wins.
# V3_BEST_FALLS_TO_NORMAL: a "best" signal whose 50x and 40x both fail then tries 30x / 20x as well, as the tier walk
# always did (False would refuse it): on the 5-year data, of the best-tier signals that the old walk could size only
# 23% (15m), 7% (30m), 1.8% (1h) and 0% (4h) passed at 40x or 50x, so keeping the groups apart would refuse most
# good spots (docs/paper-v3-rules-change-1.md section 6). A signal no candidate of its chain fits is not entered.
V3_LEVERAGE_RULE = "quality_v1"
V3_BEST_FALLS_TO_NORMAL = True
V3_QUALITY_TIERS: tuple[Tier, ...] = (
    Tier("best", 0.50, (50,)),
    Tier("best", 0.40, (40,)),
    Tier("normal", 0.30, (30,)),
    Tier("normal", 0.20, (20,)),
)
# Coin-flip fairness: a coin-flip signal has no strength, so it is "best" with probability V3_P_BEST[timeframe], drawn
# once per signal, seeded by (seed, timeframe, coin, bar) (levrule.coin_flip_best); the checkpoint's Q1 bots draw the
# same share. Computed once on 2026-10-04 (scratch levrule/pbest.py): every strategy signal of the 36 locked strategies
# that the 5-year entry study sized and closed (research/entry_study analysis_bc part B checkpoints, periods 1 and 2 =
# 2021-08-01..2026-09-30, six coins), scored with paperbot/quality_edges.json exactly as live (levrule.quality_group);
# share whose tier is "best", signals of strategies without edges counted as normal:
#   15m 231,908 / 1,075,951   30m 111,710 / 514,899   1h 46,973 / 217,799   4h 2,589 / 12,357
# (period 1 alone 0.2201 / 0.2204 / 0.2191 / 0.2124, period 2 alone 0.2096 / 0.2125 / 0.2115 / 0.2061). Without
# edges (always normal): 15m N14_ICHI_RSI, N21_ST_RSI_ADX (3 signals); 30m N21_ST_RSI_ADX (0); 1h N14_ICHI_RSI,
# N21_ST_RSI_ADX (4); 4h DOGE, N03_ADX_GC, N11_BREAKAWAY, N14_ICHI_RSI, N15_KC_AO, N21_ST_RSI_ADX, S1_EMA_RSI_CHOP
# (21 signals, 0.17%). Frozen: not recomputed during the run.
V3_P_BEST = {"15m": 0.2155, "30m": 0.2170, "1h": 0.2157, "4h": 0.2095}
# The rule before 2026-10-04 (tests that pin the old world: golden / parity files).
V3_OLD_TIER_WALK = dict(leverage_rule="tier_walk", tiers=DEFAULT_TIERS, max_margin_frac=0.40)


def v3_settings(**over) -> Settings:
    kw = dict(version="paper-v3", symbols=V3_SYMBOLS, symbol_priority=V3_SYMBOLS,
              tp_mode="ladder", dd_halt=None, bust_below=10.0, liq_buffer_atr_mult=1.0,
              initial_equity=V3_INITIAL, leverage_rule=V3_LEVERAGE_RULE, tiers=V3_QUALITY_TIERS,
              best_falls_to_normal=V3_BEST_FALLS_TO_NORMAL, max_margin_frac=0.50)
    kw.update(over)
    return Settings(**kw)
