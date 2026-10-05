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
# Traded timeframes of the CORE group (paper v4: the 36 locked strategies and the 12 original coin flips; the V3_*
# names keep their v3 values and mean the core group, the v4 totals are the V4_* names below). 5m was removed for
# the core group by the owners on 2026-10-04 (docs/paper-v3-rules-change-1.md) and NEVER goes into this tuple: the
# v4 5m accounts (the reel and RANDOM_k@5m) run on a separate 5m path. 5m bars stay the signal service's internal base
# bars (the other timeframes are built from them). 1d is record-only.
V3_TRADE_TFS = ("15m", "30m", "1h", "4h")
V3_OBSERVE_TFS = ("4h",)             # addendum Q3: observation only, outside the Q1 verdict family
V3_JUDGED_TFS = tuple(tf for tf in V3_TRADE_TFS if tf not in V3_OBSERVE_TFS)
V3_STRATEGIES = 36                   # locked strategies, DOGE_L + DOGE_S joined as DOGE (sigservice.strategy_names)
V3_RANDOM_SEEDS = (1, 2, 3)          # coin-flip accounts per timeframe
V3_ACCOUNTS = (V3_STRATEGIES + len(V3_RANDOM_SEEDS)) * len(V3_TRADE_TFS)   # 156: core group (144 + 12 coin flips)
V3_Q1_MAIN_FAMILY = V3_STRATEGIES * len(V3_JUDGED_TFS)                      # 108: core group judged (15m / 30m / 1h)


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
V3_P_BEST = {"15m": 0.2155, "30m": 0.2170, "1h": 0.2157, "4h": 0.2095,
             # paper v4: the 5m accounts (the reel and its 3 coin flips) are always "normal". levrule already gave
             # 0.0 for a timeframe without an entry; written out so a later edit cannot change the 5m control silently.
             "5m": 0.0}
# The rule before 2026-10-04 (tests that pin the old world: golden / parity files).
V3_OLD_TIER_WALK = dict(leverage_rule="tier_walk", tiers=DEFAULT_TIERS, max_margin_frac=0.40)


# ==================================================================== paper v4 (docs/paper-v4-rules.md)
# The run shape every module codes against. Four groups of original accounts; every total is computed from the
# tables, never typed in. The V3_* names above keep their values and mean the core group.
#   core   36 locked strategies x 15m/30m/1h/4h          kind "strategy"  house exits (2 ATR stop, ladder)
#   ds200  44 DeepSeek-200 definitions (39 x 4 + 5 x 3)  kind "ds200"     house exits, always "normal" leverage
#   reel   REEL_H1 on 5m (research/reel5m PREREG H1)      kind "reel"      own exits (paperbot/reel_engine.py)
#   flip   RANDOM_1..3 x 5m/15m/30m/1h/4h                kind "random"    house exits; 5m: long-only, reel exits
V4_VERSION = "paper-v4"

# DeepSeek-200 (research/deepseek200/PREREG_DEEPSEEK200.md, pinned lib_c.py): the 44 entry definitions as
# (id, family, timeframes) in PREREG order. A static copy: config never imports lib_c (it changes sys.path and the
# warnings filters at import); tests/test_v4_shape.py checks it equals lib_c.DEFS in a subprocess. The five ET-session
# definitions of F15 trade 15m / 30m / 1h only (F15_ORB and F11_PO3 trade all four).
DS200_TFS = ("15m", "30m", "1h", "4h")
DS200_SESSION_TFS = ("15m", "30m", "1h")
_DS4, _DSS = DS200_TFS, DS200_SESSION_TFS
DS200_DEFS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("F1_RSI_DIV", "F1", _DS4), ("F1_MOM_DIV", "F1", _DS4), ("F1_PVT_DIV", "F1", _DS4),
    ("F2_DEMARK", "F2", _DS4),
    ("F3_BOS", "F3", _DS4), ("F3_BOS_ZONE", "F3", _DS4), ("F3_HHHL", "F3", _DS4),
    ("F4_PULL", "F4", _DS4), ("F4_PULL_RSI", "F4", _DS4), ("F4_FAN", "F4", _DS4),
    ("F5_BOX", "F5", _DS4), ("F5_BOX_RSI", "F5", _DS4), ("F5_BOX_HTF", "F5", _DS4),
    ("F6_VWAP_CROSS", "F6", _DS4), ("F6_VWAP_FAIL", "F6", _DS4),
    ("F7_RF_TRIPLE", "F7", _DS4), ("F7_RF_ONLY", "F7", _DS4),
    ("F8_VWICK", "F8", _DS4),
    ("F9_FVG", "F9", _DS4), ("F9_IFVG", "F9", _DS4), ("F9_OB", "F9", _DS4), ("F9_BREAKER", "F9", _DS4),
    ("F10_M2022", "F10", _DS4), ("F10_OTE", "F10", _DS4),
    ("F11_TSOUP", "F11", _DS4), ("F11_RAID", "F11", _DS4), ("F11_PO3", "F11", _DS4),
    ("F12_MSS", "F12", _DS4), ("F12_MSS_DISP", "F12", _DS4),
    ("F13_FVG_PD", "F13", _DS4), ("F13_RAID_PD", "F13", _DS4),
    ("F14_SMT", "F14", _DS4),
    ("F15_ASIA_BRK", "F15", _DSS), ("F15_ASIA_SWEEP", "F15", _DSS), ("F15_LON_BRK", "F15", _DSS),
    ("F15_OPEN0930", "F15", _DSS), ("F15_OPEN0000", "F15", _DSS), ("F15_ORB", "F15", _DS4),
    ("F16_FIB382", "F16", _DS4), ("F16_FIB500", "F16", _DS4), ("F16_FIB618", "F16", _DS4),
    ("F16_FIB764", "F16", _DS4),
    ("F17_Z", "F17", _DS4), ("F17_Z_HL", "F17", _DS4),
)
DS200_IDS = tuple(d[0] for d in DS200_DEFS)
DS200_FAMILY = {d[0]: d[1] for d in DS200_DEFS}

# The reel (research/reel5m/PREREG_REEL5M.md, H1 = 5m / BB_SMA200_CLOSE_LONG / SWING_BAND): one account, 5m only.
REEL_NAME = "REEL_H1"
REEL_TF = "5m"

# Coin flips: RANDOM_1..3 on every core timeframe as in v3, plus 5m as the reel's control (owners' D4): long-only,
# the reel's exits (stop = lowest low of the previous 12 closed 5m bars - 0.05 x ATR14, target = the previous 5m
# bar's upper band, 96-bar time exit), p_best 0, fire rate per coin per 5m bar below. "label": "matched" = the reel's
# own H1 signal rate, "unmatched" = the fallback (the 36's 5m rate 0.012622).
# Frozen 2026-10-05 from the reel's 5-year H1 run (research/reel5m/out, commit 5bc7e5f; lib_reel5m.py sha a824717e…,
# PREREG sha 835f786a…), lib_reel5m unchanged, the same data and signal-bar windows (periods 1+2+3, six coins):
# 54,239 signals on 4,072,373 coin-bars with the arming independent of positions, as the live reel signals (owners'
# D3) -> 0.013319. With the PREREG's own position rule (no arming while the backtest holds that coin) the same run
# gives 45,138 signals (= out/h1.json skips.signals, reproduced exactly) -> 0.011084; not used, because the live
# reel and its flips both signal regardless of position and the engine then records SKIPPED.
V4_FLIP_TFS = (REEL_TF,) + V3_TRADE_TFS
V4_FLIP5M = {"rate": 0.013319, "long_only": True, "label": "matched",
             "source": "reel H1 5-year signal rate per coin per 5m bar, position-independent: 54,239 / 4,072,373"}

# 5m bars of history each signal job sees (trailing windows; the DeepSeek ones measured start-invariant, plan
# section 1.2: 15m / 30m as today, 1h 3,000 one-hour bars, 4h 2,400 four-hour bars).
DS_WINDOW_5M = {"15m": 17_289, "30m": 17_298, "1h": 36_000, "4h": 115_200}
REEL_WINDOW_5M = 5_000                 # >= 2,000; the reel wrapper's start-invariance test confirms it
FIVE_M_MAX_DELAY_MS = 60_000           # owners' D16: a 5m signal later than this after its boundary is LATE

# Exit rules of an original account: "house" (2 ATR stop + ladder, PaperEngine) or "reel" (paperbot/reel_engine.py).
V4_EXITS = ("house", "reel")


def v4_exits(kind: str, timeframe: str) -> str:
    """The exit rule of an original account: the reel and the 5m coin flips use the reel's own exits (owners' D2 (ii)
    and D4); every other account the house exits."""
    if kind == "reel" or (kind == "random" and timeframe == REEL_TF):
        return "reel"
    return "house"


# group -> kind, names (None for core: the locked library's 36, sigservice.strategy_names), traded timeframes and
# judged timeframes. Per-name timeframes: ``v4_tfs_of``. Observation-only timeframes (core and ds200 4h) are traded
# but not judged; the coin flips are never judged (visual only).
V4_GROUPS: dict[str, dict] = {
    "core": {"kind": "strategy", "names": None, "n_names": V3_STRATEGIES, "tfs": V3_TRADE_TFS,
             "judged": V3_JUDGED_TFS},
    "ds200": {"kind": "ds200", "names": DS200_IDS, "n_names": len(DS200_IDS), "tfs": DS200_TFS,
              "judged": DS200_SESSION_TFS},
    "reel": {"kind": "reel", "names": (REEL_NAME,), "n_names": 1, "tfs": (REEL_TF,), "judged": (REEL_TF,)},
    "flip": {"kind": "random", "names": tuple(f"RANDOM_{k}" for k in V3_RANDOM_SEEDS),
             "n_names": len(V3_RANDOM_SEEDS), "tfs": V4_FLIP_TFS, "judged": ()},
}


def v4_tfs_of(group: str, name: str) -> tuple[str, ...]:
    """The timeframes one name of a group trades."""
    if group == "ds200":
        return dict((d[0], d[2]) for d in DS200_DEFS)[name]
    return V4_GROUPS[group]["tfs"]


def v4_account_defs(core_names) -> list[dict]:
    """Every original account of the v4 run as ``AccountBook.open_accounts`` takes it: strategy, timeframe, kind and
    data {group, family, exits}. ``core_names``: the locked library's 36 (sigservice.strategy_names). The first 156
    are the v3 accounts in v3 order (core timeframe by timeframe, then the coin flips), then DeepSeek, the reel and
    the 5m coin flips."""
    core_names = list(core_names)
    if len(core_names) != V3_STRATEGIES or len(set(core_names)) != V3_STRATEGIES:
        raise ValueError(f"core group needs {V3_STRATEGIES} distinct names, got {len(core_names)}")

    def one(name, tf, group, family=None):
        kind = V4_GROUPS[group]["kind"]
        return {"strategy": name, "timeframe": tf, "kind": kind,
                "data": {"group": group, "family": family, "exits": v4_exits(kind, tf)}}
    flips = V4_GROUPS["flip"]["names"]
    defs = [one(s, tf, "core") for tf in V3_TRADE_TFS for s in core_names]
    defs += [one(f, tf, "flip") for tf in V3_TRADE_TFS for f in flips]
    defs += [one(d, tf, "ds200", fam) for tf in DS200_TFS for d, fam, tfs in DS200_DEFS if tf in tfs]
    defs += [one(REEL_NAME, REEL_TF, "reel")]
    defs += [one(f, tf, "flip") for tf in V4_FLIP_TFS if tf not in V3_TRADE_TFS for f in flips]
    return defs


def _v4_count(judged: bool = False) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for g, spec in V4_GROUPS.items():
        names = spec["names"] or tuple(f"_core{k}" for k in range(spec["n_names"]))
        per: dict[str, int] = {}
        for n in names:
            for tf in (spec["tfs"] if spec["names"] is None else v4_tfs_of(g, n)):
                if not judged or tf in spec["judged"]:
                    per[tf] = per.get(tf, 0) + 1
        out[g] = per
    return out


V4_GROUP_TF_COUNTS = _v4_count()                                       # {group: {tf: accounts}}
V4_GROUP_ACCOUNTS = {g: sum(v.values()) for g, v in V4_GROUP_TF_COUNTS.items()}
V4_ACCOUNTS = sum(V4_GROUP_ACCOUNTS.values())                           # 331
V4_TF_ACCOUNTS = {tf: sum(v.get(tf, 0) for v in V4_GROUP_TF_COUNTS.values()) for tf in V4_FLIP_TFS}
V4_GROUP_JUDGED = {g: sum(v.values()) for g, v in _v4_count(judged=True).items()}
V4_JUDGED_ACCOUNTS = sum(V4_GROUP_JUDGED.values())                      # 241 (108 core + 132 ds200 + 1 reel)


def v3_settings(**over) -> Settings:
    """The live rule set of every original account (paper v4 since the 2026-10 restart: same numbers as v3, the version
    string tells the ledgers which run produced them). ``v4_settings`` is the same function."""
    kw = dict(version=V4_VERSION, symbols=V3_SYMBOLS, symbol_priority=V3_SYMBOLS,
              tp_mode="ladder", dd_halt=None, bust_below=10.0, liq_buffer_atr_mult=1.0,
              initial_equity=V3_INITIAL, leverage_rule=V3_LEVERAGE_RULE, tiers=V3_QUALITY_TIERS,
              best_falls_to_normal=V3_BEST_FALLS_TO_NORMAL, max_margin_frac=0.50)
    kw.update(over)
    return Settings(**kw)


v4_settings = v3_settings
