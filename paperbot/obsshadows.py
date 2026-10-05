"""Observation-period what-if shadows (pre-registered in docs/observation-shadows.md).

For every trade that closed in the day (wins and losses), the nightly job (daily3) re-runs the
trade's signal alone on a fresh account (settings.initial_equity), the same way ``daily3._alone``
does (same reference price, same 1m steps, same costs and funding), once per fixed variant:

  base      the current rules unchanged (control: the real account may size differently)
  lock15    first profit lock 0.15 instead of 0.10 (step 0.05 and trigger gap 0.02 unchanged)
  lock20    first lock 0.20
  lock30    first lock 0.30      (the values paperbot/agents/labtests.py lock_start allows)
  timestop  close at market once TIME_STOP_BARS bars of the trade's timeframe have passed
            without the lock ever arming (done here, in the shadow runner; engine.py unchanged)
  lev10     fixed 10x, margin 20% of equity (the base tier's share); no fallback tier
  lev20     fixed 20x, margin 20%

and, added by docs/observation-shadows-2.md (the owners' "best setup 50x, unclear 20x"):

  quality   the requested sizing tier set by the signal's entry-strength score (``quality_tier``):
            mean period-1 quintile of the strategy's strength features recorded live, >= 4 -> "best"
            (40% x 50x, then the usual fallback), 2 < score < 4 -> "good" (30% x 30x), <= 2 -> "base"
            (20% x 20x). No usable strength recorded -> not run, counted as no_quality.

and, added by docs/observation-shadows-3.md (``trade_shadows(..., extra3=True)``, ``VARIANTS3``):

  lev30     fixed 30x, margin 30% of equity (the tier table's share); sizing checks as lev10 / lev20, no fallback
  lev40     fixed 40x, margin 40%
  lev50     fixed 50x, margin 40%
  stopw1.5  initial stop 1.5 ATR (stopw2.5: 2.5, stopw3: 3) at the REAL trade's leverage and its tier margin
            share (``SameLeveragePolicy``): only the exchange bracket and the minimum order size are checked
            (not the 15% stop-loss cap nor the stop-inside-liquidation buffer); liquidation still applies, so
            a stop at or beyond the liquidation price exits as LIQ (counted as ``stop_beyond_liq``). Named
            ``stopw`` because daily3.db already holds ``stop1.5`` / ``stop2.5`` / ``stop3.0`` loss-card rows.

and, added by docs/observation-shadows-4.md (``trade_shadows(..., extra4=True)``, ``VARIANTS4``; the 5-year
comparison research/exitstyle found no fixed take-profit that beat the ladder, these are records only):

  tp1R      fixed take-profit at the reference price + side x 1 x R (R = the initial stop distance, 2 ATR), the
            same 2 ATR stop to the end, no ladder (tp1.5R / tp2R / tp3R: 1.5 / 2 / 3 R), at the REAL trade's
            leverage and its tier margin share (``SameLeveragePolicy``, as stopw)
  ladder_cap2R  the ladder as now plus an exit at 2R, whichever comes first
            The take-profit is watched here, in the shadow runner (``run_alone_tp``; engine.py unchanged): a 1m bar
            whose favourable extreme touches it exits at it (market: taker fee and slippage), a bar opening beyond
            it exits at the open (slippage, taker), a bar that also hits the stop / lock / liquidation is a stop
            (the engine's exit comes first), and the entry bar (filled at ref_price mid-bar) is not watched.

  lev20m20  fixed 20x with margin 20% of equity (lev30m30 / lev40m40 / lev50m50: 30x 30%, 40x 40%, 50x 50%): the
            2 ATR stop and the ladder; the usual sizing checks (bracket, stop inside liquidation by the buffer, stop
            loss <= 15% of equity); a failed check is "not entered" (no fallback). lev30 / lev40 / lev50 of
            docs/observation-shadows-3.md (30 / 40 / 40% margin) are unchanged.

The owners made the entry-strength leverage the real rule the same day, so the base shadow is that rule (no separate
quality-leverage shadow). Margin shares of the rule's leverages are read from the settings' tiers
(``rule_margin_fracs``; equal to ``MARGIN_FRAC`` with the tier table of 2026-10-04).

Shadow equity curves (docs/observation-shadows-4.md section 5, ``write_curves`` / ``curve_view``): per account and
leverage variant (``CURVE_VARIANTS``), $5,000 compounded by each resolved shadow trade's P&L on equity in exit order,
stopped at a bust (< $10); daily3.db ``shadow_curves`` gets one row per account x variant with a trade that night.

The added variants never change the rows of the others (each runs on its own fresh engine).
Nothing here touches a real account: rows go to daily3.db ``shadows`` only.
"""

from __future__ import annotations

import bisect
import json
import math
import os
from dataclasses import replace
from typing import Optional

import numpy as np

from .aggregate import TF_MS
from .config import DEFAULT_TIERS, Settings, Tier
from .engine import PaperEngine
from .margin import liquidation_price
from .models import Signal
from .sizing import SizeDecision, _round_down, tp_from_roe

MIN = 60_000
DAY_MS = 86_400_000

VARIANTS = ("base", "lock15", "lock20", "lock30", "timestop", "lev10", "lev20")
LOCKS = {"lock15": 0.15, "lock20": 0.20, "lock30": 0.30}
FIXED_LEVERAGE = {"lev10": 10, "lev20": 20}
FIXED_MARGIN_FRAC = 0.20
# 2 x the median holding time (in bars of the timeframe) across the strategy cards of
# research/strategy_profiles/out_binance/cards.json (sha256 1fa469ab...), frozen 2026-10-01.
TIME_STOP_BARS = {"5m": 14, "15m": 12, "30m": 10, "1h": 8, "4h": 6}
# trades entered more than this before the day are left out (only counted)
LOOKBACK_MS = 7 * DAY_MS
# share of equity put up as margin at each leverage: the restarted run's rule (config.V3_QUALITY_TIERS, owners
# 2026-10-04: margin = leverage %; before it 50x also used 40%); 10x is the lev10 shadow
MARGIN_FRAC = {50: 0.50, 40: 0.40, 30: 0.30, 20: 0.20, 10: 0.20}

# ------------------------------------------------------------------ docs/observation-shadows-3.md
VARIANTS3 = ("lev30", "lev40", "lev50", "stopw1.5", "stopw2.5", "stopw3")
FIXED_LEVERAGE3 = {"lev30": 30, "lev40": 40, "lev50": 50}
# their registered margin shares (the tier table when docs/observation-shadows-3.md was frozen), kept as they were
FIXED_MARGIN3 = {30: 0.30, 40: 0.40, 50: 0.40}
STOP_WIDTHS = {"stopw1.5": 1.5, "stopw2.5": 2.5, "stopw3": 3.0}     # x ATR, at the real trade's leverage

# ------------------------------------------------------------------ docs/observation-shadows-4.md
TP_R = {"tp1R": 1.0, "tp1.5R": 1.5, "tp2R": 2.0, "tp3R": 3.0, "ladder_cap2R": 2.0}   # k: take-profit at k x R
TP_LADDER = ("ladder_cap2R",)                                     # keeps the ladder; the others have none
TP_VARIANTS = ("tp1R", "tp1.5R", "tp2R", "tp3R", "ladder_cap2R")
MARGIN_LEVERAGE4 = {"lev20m20": 20, "lev30m30": 30, "lev40m40": 40, "lev50m50": 50}   # margin = leverage %
VARIANTS4 = TP_VARIANTS + tuple(MARGIN_LEVERAGE4)
# shadow equity curves: the leverage variants and the base
CURVE_VARIANTS = ("base", "lev10", "lev20", "lev30", "lev40", "lev50", *MARGIN_LEVERAGE4)
CURVE_START = 5_000.0
CURVE_BUST_BELOW = 10.0

# ------------------------------------------------------------------ quality (docs/observation-shadows-2.md)
QUALITY = "quality"
QUALITY_TIERS = ("best", "good", "base")
# Period-1 quintile edges of research/entry_study/out/bc_B_quintiles.csv, frozen with the CSV's sha256 so the
# server does not read research outputs at run time (tests check the copy against the CSV when it is there).
QUALITY_EDGES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quality_edges.json")
_QUALITY_EDGES: Optional[dict] = None


def quality_edges() -> dict:
    """{"<strategy>|<tf>": {feature: {"higher_is_stronger": bool, "edges": [4 floats]}}} (loaded once)."""
    global _QUALITY_EDGES
    if _QUALITY_EDGES is None:
        with open(QUALITY_EDGES_PATH) as fh:
            _QUALITY_EDGES = json.load(fh)["cells"]
    return _QUALITY_EDGES


def quintile(value, edges, higher_is_stronger: bool) -> Optional[int]:
    """1..5 (5 = strongest) of ``value`` against the study's period-1 edges. The edges are those of the
    SIGNED feature (x -1 when lower is stronger), so the value is signed the same way: the result equals
    6 - (raw quintile) for those features, and a value equal to an edge goes to the upper quintile
    (analysis_bc: numpy searchsorted side="right"). None when the value is missing or not finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return 1 + bisect.bisect_right(list(edges), v if higher_is_stronger else -v)


def quality_score(strength, strategy: str, timeframe: str, edges: Optional[dict] = None) -> dict:
    """{"score", "tier", "quintiles", "reason"} for one signal's recorded strength (ctx["strength"]).
    score = mean quintile over the strategy's features that have a value and edges; tier None (and a
    reason) when there is nothing to score: no_strength / strength_error / no_edges / no_values."""
    if not isinstance(strength, dict) or not strength:
        return {"score": None, "tier": None, "quintiles": {}, "reason": "no_strength"}
    if "error" in strength:
        return {"score": None, "tier": None, "quintiles": {}, "reason": "strength_error"}
    cell = (quality_edges() if edges is None else edges).get(f"{strategy}|{timeframe}")
    if not cell:
        return {"score": None, "tier": None, "quintiles": {}, "reason": "no_edges"}
    qs: dict = {}
    for f in strength.get("features") or []:
        e = cell.get(f.get("name"))
        if e is None:
            continue
        q = quintile(f.get("value"), e["edges"], bool(e["higher_is_stronger"]))
        if q is not None:
            qs[f["name"]] = q
    if not qs:
        return {"score": None, "tier": None, "quintiles": {}, "reason": "no_values"}
    score = sum(qs.values()) / len(qs)
    return {"score": score, "tier": quality_tier(score), "quintiles": qs, "reason": None}


def quality_tier(score: float) -> str:
    """>= 4 best (40% x 50x), 2 < score < 4 good (30% x 30x), <= 2 base (20% x 20x)."""
    if score >= 4:
        return "best"
    if score > 2:
        return "good"
    return "base"


def signal_strength(d: dict):
    """ctx["strength"] of a signal_log row's data (as written by sigservice / entry_marks.attach)."""
    try:
        data = json.loads(d.get("data") or "{}")
    except (TypeError, ValueError):
        return None
    ctx = data.get("ctx") if isinstance(data, dict) else None
    return ctx.get("strength") if isinstance(ctx, dict) else None


def quality_settings(settings: Settings) -> Settings:
    """The quality shadow's sizing (docs/observation-shadows-2.md): the tier table it was registered with (best 40% x
    50x / 40x, good 30% x 30x, base 20% x 20x, requested tier then lower), also under the restarted run's quality_v1
    rule (config.V3_QUALITY_TIERS), where the live accounts' own sizing already follows the quality tier."""
    return replace(settings, leverage_rule="tier_walk", tiers=DEFAULT_TIERS,
                   max_margin_frac=max(settings.max_margin_frac, 0.40))


def variant_settings(settings: Settings, name: str) -> Settings:
    if name in LOCKS:
        return replace(settings, ladder_first_lock=LOCKS[name])
    if name in FIXED_LEVERAGE:
        lev = FIXED_LEVERAGE[name]
        # one tier named "best" (the tier every v3 signal requests), so there is no fallback
        return replace(settings, tiers=(Tier("best", FIXED_MARGIN_FRAC, (lev,)),), leverage_rule="tier_walk",
                       min_leverage=min(lev, settings.min_leverage), max_leverage=max(lev, settings.max_leverage))
    if name in FIXED_LEVERAGE3:
        lev = FIXED_LEVERAGE3[name]
        # the tier table's margin share for that leverage (30x 30%, 40x / 50x 40%); one tier, no fallback
        return replace(settings, tiers=(Tier("best", FIXED_MARGIN3[lev], (lev,)),), leverage_rule="tier_walk",
                       min_leverage=min(lev, settings.min_leverage), max_leverage=max(lev, settings.max_leverage))
    if name in ("base", "timestop") or name in STOP_WIDTHS or name in TP_LADDER:
        return settings                 # stopw: the stop is the signal's, the size SameLeveragePolicy's
    if name in MARGIN_LEVERAGE4:
        lev = MARGIN_LEVERAGE4[name]
        f = lev / 100.0
        # one tier at lev x and lev % margin, the usual sizing checks, no fallback (the owner range is widened for it)
        return replace(settings, tiers=(Tier("best", f, (lev,)),), leverage_rule="tier_walk",
                       min_leverage=min(lev, settings.min_leverage),
                       max_leverage=max(lev, settings.max_leverage), min_margin_frac=min(f, settings.min_margin_frac),
                       max_margin_frac=max(f, settings.max_margin_frac))
    if name in TP_R:
        # no ladder: "fixed" take-profit mode with NoTakeProfitPolicy's NaN, so the engine neither locks nor takes
        # profit; run_alone_tp watches the k x R take-profit
        return replace(settings, tp_mode="fixed")
    raise ValueError(f"unknown variant {name!r}")


class SameLeveragePolicy:
    """Sizing of the stop-width shadows (docs/observation-shadows-3.md section 4): the real trade's leverage and
    that leverage's tier margin share of the (fresh) equity; only the exchange bracket and the minimum order size
    are checked. The 15% stop-loss cap and the stop-inside-liquidation buffer of sizing.size_position are NOT
    applied (a wider stop would otherwise mostly be refused at a high leverage); the liquidation price is the
    exchange formula's, and the engine liquidates on it as always (a stop beyond it never fills first).
    The engine and sizing.py are unchanged: this is passed to PaperEngine as its ``policy``."""

    name = "same_leverage"

    def __init__(self, settings: Settings, leverage: int):
        self.s = settings
        self.leverage = int(leverage)
        self.margin_frac = rule_margin_fracs(settings)[self.leverage]

    def size(self, equity, sig, entry, brackets, spec):
        lev, side = self.leverage, sig.side
        if equity <= 0:
            return SizeDecision(False, reasons=["no equity"])
        if (entry - sig.stop_price) * side <= 0:
            return SizeDecision(False, reasons=["stop on wrong side of entry"])
        qty = _round_down(equity * self.margin_frac * lev / entry, spec.get("qty_step", 0.0))
        notional = qty * entry
        tag = f"same/{lev}x"
        if qty <= 0 or notional < spec.get("min_notional", 0.0):
            return SizeDecision(False, reasons=[f"{tag}: below minimum order size"])
        margin = notional / lev
        bracket = brackets.for_notional(notional)
        if lev > bracket.max_leverage:
            return SizeDecision(False, reasons=[f"{tag}: bracket allows {bracket.max_leverage}x"])
        liq = liquidation_price(side, qty, entry, margin, bracket)
        exit_px = sig.stop_price * (1 - side * self.s.slippage_frac)
        loss = (qty * abs(entry - sig.stop_price) + qty * abs(sig.stop_price - exit_px)
                + notional * self.s.taker_fee + qty * exit_px * self.s.taker_fee)
        return SizeDecision(True, "best", lev, margin, qty, liq, min(loss, margin), [])

    def take_profit(self, sig, entry, dec):
        roe = sig.tp_roe if sig.tp_roe is not None else self.s.default_tp_roe
        return tp_from_roe(sig.side, entry, dec.leverage, roe, round_trip=self.s.round_trip_cost)


class NoTakeProfitPolicy(SameLeveragePolicy):
    """SameLeveragePolicy whose engine take-profit is NaN (none): with ``tp_mode="fixed"`` the engine then neither
    raises a lock nor takes profit, and ``run_alone_tp`` handles the docs/observation-shadows-4.md take-profit."""

    name = "same_leverage_no_tp"

    def take_profit(self, sig, entry, dec):
        return math.nan


def stop_beyond_liq(tr) -> Optional[bool]:
    """True when the trade's initial stop sat at or beyond its liquidation price (the stop could never fill)."""
    stop, liq, side = getattr(tr, "stop_initial", None), getattr(tr, "liq_price", None), getattr(tr, "side", None)
    if stop is None or liq is None or not side:
        return None
    return bool((stop - liq) * side <= 0)


def rule_margin_fracs(settings: Settings) -> dict:
    """{leverage: margin share of equity} of the settings' tiers (the first tier listing a leverage wins), over
    ``MARGIN_FRAC`` for the leverages the tiers do not list (10x). With the tier table of 2026-10-04 this equals
    ``MARGIN_FRAC``; a variant's own settings give its own share (lev10 / lev20 20%, lev30 30%, lev50m50 50%)."""
    out = dict(MARGIN_FRAC)
    seen = set()
    for t in settings.tiers:
        for lev in t.leverages:
            if lev not in seen:
                seen.add(lev)
                out[int(lev)] = t.margin_frac
    return out


def pnl_equity(roe: Optional[float], leverage, fracs: Optional[dict] = None) -> Optional[float]:
    """P&L as a share of equity: ROE x the tier's margin share (labtests ``mean_pnl_equity``); ``fracs``: the
    {leverage: share} to use (``rule_margin_fracs``), default ``MARGIN_FRAC``."""
    if roe is None or leverage is None:
        return None
    f = (MARGIN_FRAC if fracs is None else fracs).get(int(round(float(leverage))))
    return None if f is None else roe * f


def symbol_steps(steps, symbol: str) -> list:
    """The steps with only one symbol's bar and funding (the engine of a lone trade reads nothing
    else, so results equal a run on all symbols; it is just faster)."""
    out = []
    for ts, bars, funding in steps:
        b = bars.get(symbol)
        f = funding.get(symbol)
        out.append((ts, {symbol: b} if b is not None else {}, {symbol: f} if f is not None else {}))
    return out


def run_alone(settings: Settings, brackets, specs, sig: Signal, ssteps, i0: int,
              time_stop_ms: Optional[int] = None, policy=None) -> tuple[Optional[object], bool]:
    """``daily3._alone`` with an optional time stop: once ``time_stop_ms`` has passed since entry
    and the lock never armed, close at the 1m bar close (market, with slippage), reason "TIME".
    ``policy``: another sizing policy for the engine (the stop-width shadows' SameLeveragePolicy).
    Returns (trade or None, resolved)."""
    e = PaperEngine(settings, brackets, symbol_specs=specs, book="shadow", policy=policy)
    e.submit(sig)
    for k in range(i0, len(ssteps)):
        ts, bars, funding = ssteps[k]
        e.step(bars, funding)
        if e.trades:
            return e.trades[0], True
        p = e.position
        if p is None:
            if not e.pending:
                return None, True          # rejected by sizing
            continue
        if time_stop_ms is not None and p.lock_roe is None and ts + MIN >= p.entry_time + time_stop_ms:
            bar = bars.get(p.symbol)
            if bar is not None:
                e._close_market(bar.close, bar.close_time, "TIME")
                return e.trades[0], True
    return None, False


def tp_price(p, k: float, entry_open: Optional[float] = None) -> float:
    """The take-profit of an open position at k x R: the reference price (``meta["ref_price"]``, before slippage;
    else the entry bar's open) + side x k x R, R = |reference - initial stop| (= 2 ATR, ``meta["stop_dist"]``)."""
    ref = p.signal.meta.get("ref_price")
    ref = float(ref) if ref is not None else float(entry_open if entry_open is not None else p.entry_price)
    return ref + p.side * k * abs(ref - p.stop_initial)


def run_alone_tp(settings: Settings, brackets, specs, sig: Signal, ssteps, i0: int, k: float,
                 policy=None) -> tuple[Optional[object], bool, Optional[float]]:
    """``run_alone`` with a fixed take-profit at k x R watched outside the engine (docs/observation-shadows-4.md
    section 4). Per 1m bar, once a position is open:
      - from the bar after the entry, a bar OPENING at or beyond the take-profit exits at the open (market: slippage
        and taker fee) before the engine sees the bar (unless the mark opens at or beyond liquidation: the engine's);
      - the engine steps the bar (its stop / lock / liquidation exits come first: a bar that hits both is a stop);
      - if still open and not the entry bar filled at ``ref_price``, a bar whose favourable extreme touches the
        take-profit exits at it (market: slippage and taker fee, exit time the bar close);
      - funding comes first, as in the engine (engine.step): a position held at the bar open pays that open's
        funding before any exit of the bar (the take-profit gap included); the entry bar pays none.
    Returns (trade or None, resolved, take-profit price or None)."""
    e = PaperEngine(settings, brackets, symbol_specs=specs, book="shadow", policy=policy)
    e.submit(sig)
    tp: Optional[float] = None
    for k_ in range(i0, len(ssteps)):
        ts, bars, funding = ssteps[k_]
        p = e.position
        bar = bars.get(p.symbol) if p is not None else None
        rate = (funding or {}).get(p.symbol) if p is not None else None
        if rate is not None and bar is not None:
            e._apply_funding(rate, bar.m_open)
        if p is not None and tp is not None and bar is not None and (bar.open - tp) * p.side >= 0 \
                and (bar.m_open - p.liq_price) * p.side > 0:
            e._close_market(bar.open, bar.open_time, "TP")
            return e.trades[0], True, tp
        entered_before = p is not None
        e.step(bars, {})
        if e.trades:
            return e.trades[0], True, tp
        p = e.position
        if p is None:
            if not e.pending:
                return None, True, None        # rejected by sizing
            continue
        bar = bars.get(p.symbol)
        if tp is None:
            tp = tp_price(p, k, None if bar is None else bar.open)
        entry_bar = not entered_before
        if bar is not None and not (entry_bar and "ref_price" in p.signal.meta):
            if (bar.high >= tp) if p.side > 0 else (bar.low <= tp):
                e._close_market(tp, bar.close_time, "TP")
                return e.trades[0], True, tp
    return None, False, tp


def closed_trades(conn, start: int, end: int) -> list[tuple[str, dict]]:
    return [(aid, json.loads(data)) for aid, data in conn.execute(
        "SELECT account_id, data FROM trades WHERE exit_time >= ? AND exit_time < ? ORDER BY id", (start, end))]


def copy_accounts(conn) -> set:
    """Ids of the copy accounts (paperbot/extras.py): their trades repeat the parent's signal, so they get no
    trade shadows of their own (the parent's are the same signal)."""
    try:
        return {r[0] for r in conn.execute("SELECT account_id FROM accounts WHERE kind = 'copy'")}
    except Exception:  # noqa: BLE001  a database without the accounts table
        return set()


def own_exit_accounts(conn) -> set:
    """Ids of the original accounts that do not run the house exits (paper v4: the reel and the three 5m coin flips,
    paperbot/reel_engine.py; ``accounts.exits_of`` from the accounts row). Every variant here changes one house
    exit or sizing rule (2 ATR stop, ladder lock, time stop, leverage) and ``base`` is the house rules, so none of
    them describes these accounts' trades: they get no trade shadows (counted in info["own_exit_trades"])."""
    from .accounts import ORIGINAL_KINDS, exits_of
    try:
        rows = conn.execute("SELECT account_id, kind, timeframe, data FROM accounts").fetchall()
    except Exception:  # noqa: BLE001  a database without the accounts table
        return set()
    return {aid for aid, kind, tf, data in rows if kind in ORIGINAL_KINDS and exits_of(kind, tf, data) != "house"}


def first_signal(conn, start: int, end: int) -> Optional[int]:
    """Earliest signal bar close (within LOOKBACK_MS) among the day's closed trades, if before ``start``."""
    bcs = [t["signal_ts"] + 1 for _, t in closed_trades(conn, start, end)]
    bcs = [b for b in bcs if start - LOOKBACK_MS <= b < start]
    return min(bcs) if bcs else None


def _signal_row(conn, t: dict) -> Optional[dict]:
    r = conn.execute(
        "SELECT bar_close, timeframe, strategy, symbol, side, atr, ref_price, ref_time, delay_ms, data FROM signal_log "
        "WHERE timeframe = ? AND bar_close = ? AND strategy = ? AND symbol = ? AND side = ? AND status = 'SUBMITTED' "
        "ORDER BY id LIMIT 1",
        (t["timeframe"], t["signal_ts"] + 1, t["strategy_id"], t["symbol"], int(t["side"]))).fetchone()
    if r is None:
        return None
    return dict(zip(("bar_close", "timeframe", "strategy", "symbol", "side", "atr", "ref_price", "ref_time",
                     "delay_ms", "data"), r))


def trade_shadows(settings: Settings, brackets, specs, conn, day: str, start: int, end: int, steps,
                  make_signal, quality: bool = False, extra3: bool = False,
                  extra4: bool = False) -> tuple[list[dict], dict]:
    """Rows for the shadows table (one per closed trade and variant) and counts of trades left out.
    ``steps`` must reach back to the earliest signal (``first_signal``); ``make_signal`` is daily3's.
    Trades of copy accounts are left out (counted in info["copy_trades"]); new-strategy accounts' trades are
    shadowed like the others (their signal rows are their own). Trades of accounts with their own exits (paper v4's
    reel and 5m coin flips, ``own_exit_accounts``) are left out (counted in info["own_exit_trades"]); the DeepSeek
    accounts run the house exits and are shadowed like the 36.
    ``quality``: also run the quality variant (docs/observation-shadows-2.md) for every trade whose
    signal has a usable strength record; the others are counted in info["no_quality"] (by reason in
    info["no_quality_reasons"]).
    ``extra3``: also run VARIANTS3 (docs/observation-shadows-3.md) for every trade, after the others; a trade
    whose real leverage is not in the tier table gets no stopw rows (counted in info["no_leverage"]).
    ``extra4``: also run VARIANTS4 (docs/observation-shadows-4.md, fixed take-profits) for every trade, after the
    others; a trade whose real leverage is not in the tier table gets none (counted in info["no_leverage4"])."""
    idx = {ts: k for k, (ts, _, _) in enumerate(steps)}
    per_symbol: dict[str, list] = {}
    vs = {v: variant_settings(settings, v) for v in VARIANTS + (VARIANTS3 if extra3 else ()) + (VARIANTS4 if extra4 else ())}
    vf = {v: rule_margin_fracs(x) for v, x in vs.items()}       # each variant's margin shares (base: the rule's)
    rows: list[dict] = []
    info = {"closed": 0, "no_signal": 0, "no_steps": 0}
    if quality:
        info.update(no_quality=0, no_quality_reasons={})
    if extra3:
        info.update(extra3=True, no_leverage=0)
    if extra4:
        info.update(extra4=True, no_leverage4=0)
    copies = copy_accounts(conn)
    own = own_exit_accounts(conn)
    for aid, t in closed_trades(conn, start, end):
        if aid in copies:                       # a copy repeats its parent's signal: the parent's shadow is it
            info["copy_trades"] = info.get("copy_trades", 0) + 1
            continue
        if aid in own:                          # the reel's own exits: the house-exit variants do not apply
            info["own_exit_trades"] = info.get("own_exit_trades", 0) + 1
            continue
        info["closed"] += 1
        bc = t["signal_ts"] + 1
        i0 = idx.get(bc)
        if i0 is None or t["symbol"] not in brackets:
            info["no_steps"] += 1
            continue
        d = _signal_row(conn, t)
        if d is None:
            info["no_signal"] += 1
            continue
        if t["symbol"] not in per_symbol:
            per_symbol[t["symbol"]] = symbol_steps(steps, t["symbol"])
        ss = per_symbol[t["symbol"]]
        sig = make_signal(d)
        actual = {"actual_roe": t["roe"], "actual_leverage": t["leverage"], "actual_reason": t["exit_reason"],
                  "actual_pnl_equity": pnl_equity(t["roe"], t["leverage"], vf["base"])}
        for v in VARIANTS:
            tstop = None
            if v == "timestop":
                n = TIME_STOP_BARS.get(t["timeframe"])
                if n is None:
                    continue
                tstop = n * TF_MS[t["timeframe"]]
            tr, resolved = run_alone(vs[v], brackets, specs, sig, ss, i0, time_stop_ms=tstop)
            data = dict(actual)
            if tr is not None:
                data.update(leverage=tr.leverage, pnl_equity=pnl_equity(tr.roe, tr.leverage, vf[v]),
                            exit_time=tr.exit_time)
            rows.append(_shadow_row(v, day, aid, t, bc, tr, resolved, data))
        if extra3:
            rows += _extra3_rows(vs, vf, brackets, specs, d, sig, ss, i0, day, aid, t, bc, actual, make_signal, info)
        if extra4:
            rows += _extra4_rows(vs, vf, brackets, specs, sig, ss, i0, day, aid, t, bc, actual, info)
        if quality:
            q = quality_score(signal_strength(d), t["strategy_id"], t["timeframe"])
            if q["tier"] is None:
                info["no_quality"] += 1
                r = info["no_quality_reasons"]
                r[q["reason"]] = r.get(q["reason"], 0) + 1
                continue
            # the shadow's own tier table (40% x 50/40x, 30% x 30x, 20% x 20x, tier walk), whatever the live rule
            qs = quality_settings(settings)
            tr, resolved = run_alone(qs, brackets, specs, replace(sig, tier=q["tier"]), ss, i0)
            data = dict(actual, quality_score=q["score"], quality_tier=q["tier"], quintiles=q["quintiles"])
            if tr is not None:
                data.update(leverage=tr.leverage, pnl_equity=pnl_equity(tr.roe, tr.leverage, rule_margin_fracs(qs)),
                            exit_time=tr.exit_time, tier=tr.tier)
            rows.append(_shadow_row(QUALITY, day, aid, t, bc, tr, resolved, data))
    return rows, info


def _extra3_rows(vs: dict, vf: dict, brackets, specs, d: dict, sig: Signal, ss, i0: int, day: str, aid: str, t: dict,
                 bc: int, actual: dict, make_signal, info: dict) -> list[dict]:
    """The docs/observation-shadows-3.md rows of one closed trade: lev30 / lev40 / lev50 (fixed leverage, the
    tier's margin share, the usual sizing checks, no fallback) and stopw1.5 / 2.5 / 3 (k x ATR stop at the real
    trade's leverage, SameLeveragePolicy)."""
    out = []
    for v in FIXED_LEVERAGE3:
        tr, resolved = run_alone(vs[v], brackets, specs, sig, ss, i0)
        data = dict(actual)
        if tr is not None:
            data.update(leverage=tr.leverage, pnl_equity=pnl_equity(tr.roe, tr.leverage, vf[v]), exit_time=tr.exit_time)
        out.append(_shadow_row(v, day, aid, t, bc, tr, resolved, data))
    try:
        lev = int(round(float(t.get("leverage"))))
    except (TypeError, ValueError):
        lev = None
    if lev not in vf["base"]:
        info["no_leverage"] = info.get("no_leverage", 0) + 1
        return out
    for v, k in STOP_WIDTHS.items():
        policy = SameLeveragePolicy(vs[v], lev)
        tr, resolved = run_alone(vs[v], brackets, specs, make_signal(d, stop_atr=k), ss, i0, policy=policy)
        data = dict(actual, stop_atr=k, same_leverage=lev)
        if tr is not None:
            data.update(leverage=tr.leverage, pnl_equity=pnl_equity(tr.roe, tr.leverage, vf[v]), exit_time=tr.exit_time,
                        stop_beyond_liq=stop_beyond_liq(tr))
        out.append(_shadow_row(v, day, aid, t, bc, tr, resolved, data))
    return out


def _extra4_rows(vs: dict, vf: dict, brackets, specs, sig: Signal, ss, i0: int, day: str, aid: str, t: dict,
                 bc: int, actual: dict, info: dict) -> list[dict]:
    """The docs/observation-shadows-4.md rows of one closed trade: tp1R / tp1.5R / tp2R / tp3R (the 2 ATR stop, no
    ladder, a take-profit at k x R) and ladder_cap2R (the ladder plus 2R), at the real trade's leverage and the
    rule's margin share for it (none when that leverage is not in the tiers: info["no_leverage4"]); then
    lev20m20 / lev30m30 / lev40m40 / lev50m50 (fixed leverage, margin = leverage %, the usual checks, no fallback)."""
    out = []
    try:
        lev = int(round(float(t.get("leverage"))))
    except (TypeError, ValueError):
        lev = None
    if lev in vf["base"]:
        for v in TP_VARIANTS:
            policy = (SameLeveragePolicy if v in TP_LADDER else NoTakeProfitPolicy)(vs[v], lev)
            tr, resolved, tp = run_alone_tp(vs[v], brackets, specs, sig, ss, i0, TP_R[v], policy=policy)
            data = dict(actual, tp_r=TP_R[v], same_leverage=lev, ladder=v in TP_LADDER)
            if tr is not None:
                data.update(leverage=tr.leverage, pnl_equity=pnl_equity(tr.roe, tr.leverage, vf["base"]),
                            exit_time=tr.exit_time, tp_price=tp)
            out.append(_shadow_row(v, day, aid, t, bc, tr, resolved, data))
    else:
        info["no_leverage4"] = info.get("no_leverage4", 0) + 1
    msig = sig if sig.tier == "best" else replace(sig, tier="best")      # the variant's one tier
    for v, mlev in MARGIN_LEVERAGE4.items():
        tr, resolved = run_alone(vs[v], brackets, specs, msig, ss, i0)
        data = dict(actual, margin_frac=vf[v][mlev])
        if tr is not None:
            data.update(leverage=tr.leverage, pnl_equity=pnl_equity(tr.roe, tr.leverage, vf[v]), exit_time=tr.exit_time)
        out.append(_shadow_row(v, day, aid, t, bc, tr, resolved, data))
    return out


def _shadow_row(kind: str, day: str, aid: str, t: dict, bc: int, tr, resolved: bool, data: dict) -> dict:
    return {"key": f"{kind}|{aid}|{t['symbol']}|{bc}", "day": day, "kind": kind, "account_id": aid,
            "symbol": t["symbol"], "timeframe": t["timeframe"], "side": int(t["side"]),
            "filled": None, "roe": None if tr is None else tr.roe,
            "exit_reason": None if tr is None else tr.exit_reason, "resolved": int(resolved),
            "data": json.dumps(data)}


def _mean(xs) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return float(np.mean(xs)) if xs else None


def summarize(rows: list[dict], info: dict) -> dict:
    """report["shadows"]["trade_variants"]: per variant, over the trades it resolved, the variant's and
    the actual trades' mean ROE and mean P&L on equity, and how often the variant did better/worse
    than the actual trade (P&L on equity; equal counts as neither)."""
    out: dict = dict(info)
    for v in VARIANTS:
        out[v] = _metrics([r for r in rows if r["kind"] == v])
    if info.get("extra3") or any(r["kind"] in VARIANTS3 for r in rows):
        base = {r["key"].split("|", 1)[1]: r for r in rows if r["kind"] == "base"}
        for v in VARIANTS3:
            rs = [r for r in rows if r["kind"] == v]
            out[v] = _with_base(rs, base)
            out[v]["base"].update(_vs_base(rs, base))
            if v in STOP_WIDTHS:
                out[v]["stop_beyond_liq"] = sum(1 for r in rs if json.loads(r["data"]).get("stop_beyond_liq"))
    if info.get("extra4") or any(r["kind"] in VARIANTS4 for r in rows):
        base = {r["key"].split("|", 1)[1]: r for r in rows if r["kind"] == "base"}
        for v in VARIANTS4:
            rs = [r for r in rows if r["kind"] == v]
            out[v] = _with_base(rs, base)
            out[v]["base"].update(_vs_base(rs, base))
            if v in TP_R:
                out[v]["tp_exits"] = sum(1 for r in rs if r["resolved"] and r["exit_reason"] == "TP")
                out[v]["leverage_differs"] = _leverage_differs(rs, base)
    if "no_quality" in info or any(r["kind"] == QUALITY for r in rows):
        out[QUALITY] = quality_summary(rows, info)
    return out


def _metrics(rs: list[dict]) -> dict:
    done = [(r, json.loads(r["data"])) for r in rs if r["resolved"] and r["roe"] is not None]
    pairs = [(d.get("pnl_equity"), d.get("actual_pnl_equity")) for _, d in done]
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    return {
        "trades": len(rs), "resolved": len(done),
        "rejected": sum(1 for r in rs if r["resolved"] and r["roe"] is None),
        "open_at_horizon": sum(1 for r in rs if not r["resolved"]),
        "mean_roe": _mean(r["roe"] for r, _ in done),
        "mean_pnl_equity": _mean(d.get("pnl_equity") for _, d in done),
        "liquidations": sum(1 for r, _ in done if r["exit_reason"] == "LIQ"),
        "better_share": sum(1 for a, b in pairs if a > b + 1e-12) / len(pairs) if pairs else None,
        "worse_share": sum(1 for a, b in pairs if a < b - 1e-12) / len(pairs) if pairs else None,
        "actual": {"mean_roe": _mean(d["actual_roe"] for _, d in done),
                   "mean_pnl_equity": _mean(d["actual_pnl_equity"] for _, d in done),
                   "liquidations": sum(1 for _, d in done if d["actual_reason"] == "LIQ")},
    }


def _with_base(rs: list[dict], base: dict) -> dict:
    """_metrics plus the base shadow (same fresh account, current rules) over the same resolved trades."""
    m = _metrics(rs)
    b = [base.get(r["key"].split("|", 1)[1]) for r in rs if r["resolved"] and r["roe"] is not None]
    b = [x for x in b if x is not None and x["resolved"] and x["roe"] is not None]
    m["base"] = {"trades": len(b), "mean_roe": _mean(x["roe"] for x in b),
                 "mean_pnl_equity": _mean(json.loads(x["data"]).get("pnl_equity") for x in b)}
    return m


def _vs_base(rs: list[dict], base: dict) -> dict:
    """Against the base shadow of the same trades (both resolved and entered), on P&L on equity: the mean
    difference and how often the variant did better / worse (equal counts as neither)."""
    pairs = []
    for r in rs:
        b = base.get(r["key"].split("|", 1)[1])
        if not (r["resolved"] and r["roe"] is not None and b is not None and b["resolved"] and b["roe"] is not None):
            continue
        a, c = json.loads(r["data"]).get("pnl_equity"), json.loads(b["data"]).get("pnl_equity")
        if a is not None and c is not None:
            pairs.append((a, c))
    n = len(pairs)
    return {"paired": n, "vs_base_pnl_equity": _mean(a - c for a, c in pairs),
            "better_than_base": sum(1 for a, c in pairs if a > c + 1e-12) / n if n else None,
            "worse_than_base": sum(1 for a, c in pairs if a < c - 1e-12) / n if n else None}


def _leverage_differs(rs: list[dict], base: dict) -> int:
    """Pairs (both entered) where the variant's leverage is not the base shadow's (docs/observation-shadows-4.md:
    the take-profit shadows use the real trade's leverage, the base re-picks it on the fresh account)."""
    n = 0
    for r in rs:
        b = base.get(r["key"].split("|", 1)[1])
        if r["roe"] is None or b is None or b["roe"] is None:
            continue
        lv, lb = json.loads(r["data"]).get("leverage"), json.loads(b["data"]).get("leverage")
        if lv is not None and lb is not None and int(lv) != int(lb):
            n += 1
    return n


def quality_summary(rows: list[dict], info: dict) -> dict:
    """report["shadows"]["trade_variants"]["quality"]: the variant metrics, the base shadow over the same
    trades, the requested-tier mix, the entered-leverage mix, the same metrics per requested tier, and the
    trades not scored (no_quality, by reason)."""
    rs = [r for r in rows if r["kind"] == QUALITY]
    base = {r["key"].split("|", 1)[1]: r for r in rows if r["kind"] == "base"}
    tiers = {r["key"]: json.loads(r["data"]).get("quality_tier") for r in rs}
    out = _with_base(rs, base)
    out["tier_mix"] = {t: sum(1 for r in rs if tiers[r["key"]] == t) for t in QUALITY_TIERS}
    levs: dict = {}
    for r in rs:
        lev = json.loads(r["data"]).get("leverage") if r["roe"] is not None else None
        if lev is not None:
            levs[str(int(lev))] = levs.get(str(int(lev)), 0) + 1
    out["leverage_mix"] = dict(sorted(levs.items(), key=lambda kv: -int(kv[0])))
    out["by_tier"] = {t: _with_base([r for r in rs if tiers[r["key"]] == t], base) for t in QUALITY_TIERS}
    out["no_quality"] = int(info.get("no_quality", 0))
    out["no_quality_reasons"] = dict(info.get("no_quality_reasons", {}))
    return out


# ---------------------------------------------------------------- shadow equity curves (docs/observation-shadows-4.md)
CURVES_SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_curves (
    day TEXT NOT NULL, account_id TEXT NOT NULL, variant TEXT NOT NULL, equity_end REAL NOT NULL,
    bust_day TEXT, n_trades INTEGER NOT NULL, PRIMARY KEY (day, account_id, variant)
);
"""


def curve_rows(prev: dict, day: str, rows: list[dict], start: float = CURVE_START,
               bust_below: float = CURVE_BUST_BELOW) -> list[tuple]:
    """The night's shadow_curves rows (day, account_id, variant, equity_end, bust_day, n_trades) from the night's
    shadow rows (``trade_shadows``). ``prev``: {(account_id, variant): (equity_end, bust_day, n_trades)} as of the
    day before (missing: ``start``, no bust, 0 trades). Per account and CURVE_VARIANTS variant, the resolved shadow
    trades that entered (roe and pnl_equity known) are applied in order of their exit time (then key), compounding
    equity x (1 + pnl_equity); once equity < ``bust_below`` the curve stops (bust_day = ``day``, later trades are not
    applied). A curve already bust gets no more rows; an account x variant without a trade that night gets none."""
    per: dict = {}
    for r in rows:
        if r["kind"] not in CURVE_VARIANTS or not r["resolved"] or r["roe"] is None:
            continue
        d = json.loads(r["data"])
        pe = d.get("pnl_equity")
        if pe is None:
            continue
        per.setdefault((r["account_id"], r["kind"]), []).append((d.get("exit_time") or 0, r["key"], float(pe)))
    out = []
    for (aid, v), ts in sorted(per.items()):
        eq, bust, n = prev.get((aid, v), (start, None, 0))
        if bust:
            continue
        for _t, _k, pe in sorted(ts):
            eq = max(0.0, eq * (1.0 + pe))
            n += 1
            if eq < bust_below:
                bust = day
                break
        out.append((day, aid, v, eq, bust, n))
    return out


def write_curves(out_conn, day: str, rows: list[dict], start: float = CURVE_START,
                 bust_below: float = CURVE_BUST_BELOW) -> dict:
    """Append the night's shadow equity curves to daily3.db ``shadow_curves``. Re-running a day replaces its rows and
    starts from the latest rows before it; then every LATER day already present is recomputed in order from its
    stored shadow rows (daily3.db ``shadows``), so a missed night re-run afterwards reaches the curves of the days
    after it, and the result is the same as running the nights in order (review 2026-10-04, M-3). Returns a small
    summary for the report: {"rows": n, "busts": [[account_id, variant], ...] that busted this night,
    "recomputed": [later days rewritten]}."""
    out_conn.executescript(CURVES_SCHEMA)
    new = _write_curve_day(out_conn, day, rows, start, bust_below)
    later: list = []
    if _has_shadows(out_conn):                  # without stored shadow rows the later days are left as they are
        later = sorted({d for (d,) in out_conn.execute("SELECT DISTINCT day FROM shadow_curves WHERE day > ?", (day,))}
                       | set(_shadow_days_after(out_conn, day)))
    for d in later:
        _write_curve_day(out_conn, d, _stored_shadow_rows(out_conn, d), start, bust_below)
    return {"rows": len(new), "busts": [[aid, v] for _d, aid, v, _e, b, _n in new if b == day], "recomputed": later}


def _write_curve_day(out_conn, day: str, rows: list[dict], start: float, bust_below: float) -> list[tuple]:
    out_conn.execute("DELETE FROM shadow_curves WHERE day = ?", (day,))
    prev = {}
    for aid, v, eq, bust, n in out_conn.execute(
            "SELECT c.account_id, c.variant, c.equity_end, c.bust_day, c.n_trades FROM shadow_curves c JOIN "
            "(SELECT account_id, variant, MAX(day) AS d FROM shadow_curves WHERE day < ? GROUP BY account_id, variant) m "
            "ON c.account_id = m.account_id AND c.variant = m.variant AND c.day = m.d", (day,)):
        prev[(aid, v)] = (float(eq), bust, int(n))
    new = curve_rows(prev, day, rows, start, bust_below)
    out_conn.executemany("INSERT INTO shadow_curves VALUES (?,?,?,?,?,?)", new)
    return new


def _has_shadows(out_conn) -> bool:
    return out_conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'shadows'").fetchone() is not None


def _shadow_days_after(out_conn, day: str) -> list[str]:
    """Days after ``day`` with stored shadow rows of a curve variant (none without the ``shadows`` table)."""
    if not _has_shadows(out_conn):
        return []
    q = ",".join("?" * len(CURVE_VARIANTS))
    return [d for (d,) in out_conn.execute(f"SELECT DISTINCT day FROM shadows WHERE day > ? AND kind IN ({q})",
                                           (day, *CURVE_VARIANTS))]


def _stored_shadow_rows(out_conn, day: str) -> list[dict]:
    """A night's stored shadow rows of the curve variants, as ``curve_rows`` reads them."""
    if not _has_shadows(out_conn):
        return []
    q = ",".join("?" * len(CURVE_VARIANTS))
    return [{"key": k, "kind": kind, "account_id": aid, "resolved": res, "roe": roe, "data": data}
            for k, kind, aid, res, roe, data in out_conn.execute(
                f"SELECT key, kind, account_id, resolved, roe, data FROM shadows WHERE day = ? AND kind IN ({q})",
                (day, *CURVE_VARIANTS))]


def curve_view(daily_ro, account: Optional[str] = None, accounts=None, include_random: bool = False,
               start: float = CURVE_START) -> dict:
    """The shadow equity curves for the dashboard (read-only on daily3.db). Output::

        {"variants": [CURVE_VARIANTS present, in that order],
         "days": ["YYYY-MM-DD", ...],                 # every day with a shadow_curves row, ascending
         "start": 5000.0, "bust_below": 10.0,
         "by_variant": {variant: {
             "accounts": int,                          # accounts in the view (any variant has a row by the last day)
             "median": [float|None per day],           # median equity over the accounts started by that day
             "mean":   [float|None per day],           # mean of the same
             "busts":  [int per day],                  # accounts of this variant bust on or before that day
             "bust_accounts": [[account_id, bust_day], ...]}},
         "account": {"account_id": str,                # only when ``account`` is given
                     "curves": {variant: [float|None per day]},     # None before the account's first row
                     "bust_day": {variant: "YYYY-MM-DD"|None},
                     "n_trades": {variant: int}}}

    An account counts from the first day it has a row of any variant; on a day it has no row of a variant its last
    equity carries forward (``start`` before its first trade there; a bust curve stays at its last value).
    ``accounts``: only these account ids (e.g. the strategy accounts from paper3.db); otherwise every account except
    the coin flips (ids starting "RANDOM", unless ``include_random``). No table / no rows: empty lists, never raises
    for a missing table ({"error": ...} only when the read fails otherwise)."""
    empty = {"variants": [], "days": [], "start": start, "bust_below": CURVE_BUST_BELOW, "by_variant": {}}
    try:
        got = daily_ro.execute("SELECT day, account_id, variant, equity_end, bust_day, n_trades FROM shadow_curves "
                               "ORDER BY day").fetchall()
    except Exception as exc:  # noqa: BLE001
        if "no such table" in str(exc):
            return empty
        return {**empty, "error": f"{type(exc).__name__}"}
    want = set(accounts) if accounts is not None else None
    got = [g for g in got if (g[1] in want if want is not None else (include_random or not str(g[1]).startswith("RANDOM")))]
    if not got:
        return empty
    days = sorted({g[0] for g in got})
    di = {d: i for i, d in enumerate(days)}
    first: dict = {}
    series: dict = {}                                   # (account, variant) -> {day index: (equity, bust, n)}
    for d, aid, v, eq, bust, n in got:
        first[aid] = min(first.get(aid, di[d]), di[d])
        series.setdefault((aid, v), {})[di[d]] = (float(eq), bust, int(n))
    variants = [v for v in CURVE_VARIANTS if any(k[1] == v for k in series)]
    accs = sorted(first)

    def path(aid, v):
        pts, cur, out = series.get((aid, v), {}), start, []
        for i in range(len(days)):
            if i in pts:
                cur = pts[i][0]
            out.append(cur if i >= first[aid] else None)
        return out

    by_variant = {}
    for v in variants:
        paths = {a: path(a, v) for a in accs}
        busts = sorted(((a, b) for (a, vv), pts in series.items() if vv == v
                        for b in {p[1] for p in pts.values() if p[1]}), key=lambda x: (x[1], x[0]))
        med, mean, nb = [], [], []
        for i, d in enumerate(days):
            xs = [p[i] for p in paths.values() if p[i] is not None]
            med.append(float(np.median(xs)) if xs else None)
            mean.append(float(np.mean(xs)) if xs else None)
            nb.append(sum(1 for _a, b in busts if b <= d))
        by_variant[v] = {"accounts": len(accs), "median": med, "mean": mean, "busts": nb,
                         "bust_accounts": [[a, b] for a, b in busts]}
    out = {"variants": variants, "days": days, "start": start, "bust_below": CURVE_BUST_BELOW,
           "by_variant": by_variant}
    if account is not None:
        if account in first:
            out["account"] = {"account_id": account, "curves": {v: path(account, v) for v in variants},
                              "bust_day": {v: next((p[1] for p in series.get((account, v), {}).values() if p[1]), None)
                                           for v in variants},
                              "n_trades": {v: max((p[2] for p in series.get((account, v), {}).values()), default=0)
                                           for v in variants}}
        else:
            out["account"] = {"account_id": account, "curves": {}, "bust_day": {}, "n_trades": {}}
    return out
