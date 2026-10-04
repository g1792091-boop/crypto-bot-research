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
from .config import Settings, Tier
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
# share of equity put up as margin at each leverage (paper v3 tiers; 10x is the lev10 shadow)
MARGIN_FRAC = {50: 0.40, 40: 0.40, 30: 0.30, 20: 0.20, 10: 0.20}

# ------------------------------------------------------------------ docs/observation-shadows-3.md
VARIANTS3 = ("lev30", "lev40", "lev50", "stopw1.5", "stopw2.5", "stopw3")
FIXED_LEVERAGE3 = {"lev30": 30, "lev40": 40, "lev50": 50}          # margin share: MARGIN_FRAC (30%, 40%, 40%)
STOP_WIDTHS = {"stopw1.5": 1.5, "stopw2.5": 2.5, "stopw3": 3.0}     # x ATR, at the real trade's leverage

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


def variant_settings(settings: Settings, name: str) -> Settings:
    if name in LOCKS:
        return replace(settings, ladder_first_lock=LOCKS[name])
    if name in FIXED_LEVERAGE:
        lev = FIXED_LEVERAGE[name]
        # one tier named "best" (the tier every v3 signal requests), so there is no fallback
        return replace(settings, tiers=(Tier("best", FIXED_MARGIN_FRAC, (lev,)),),
                       min_leverage=min(lev, settings.min_leverage), max_leverage=max(lev, settings.max_leverage))
    if name in FIXED_LEVERAGE3:
        lev = FIXED_LEVERAGE3[name]
        # the tier table's margin share for that leverage (30x 30%, 40x / 50x 40%); one tier, no fallback
        return replace(settings, tiers=(Tier("best", MARGIN_FRAC[lev], (lev,)),),
                       min_leverage=min(lev, settings.min_leverage), max_leverage=max(lev, settings.max_leverage))
    if name in ("base", "timestop") or name in STOP_WIDTHS:
        return settings                 # stopw: the stop is the signal's, the size SameLeveragePolicy's
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
        self.margin_frac = MARGIN_FRAC[self.leverage]

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


def stop_beyond_liq(tr) -> Optional[bool]:
    """True when the trade's initial stop sat at or beyond its liquidation price (the stop could never fill)."""
    stop, liq, side = getattr(tr, "stop_initial", None), getattr(tr, "liq_price", None), getattr(tr, "side", None)
    if stop is None or liq is None or not side:
        return None
    return bool((stop - liq) * side <= 0)


def pnl_equity(roe: Optional[float], leverage) -> Optional[float]:
    """P&L as a share of equity: ROE x the tier's margin share (labtests ``mean_pnl_equity``)."""
    if roe is None or leverage is None:
        return None
    f = MARGIN_FRAC.get(int(round(float(leverage))))
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
                  make_signal, quality: bool = False, extra3: bool = False) -> tuple[list[dict], dict]:
    """Rows for the shadows table (one per closed trade and variant) and counts of trades left out.
    ``steps`` must reach back to the earliest signal (``first_signal``); ``make_signal`` is daily3's.
    Trades of copy accounts are left out (counted in info["copy_trades"]); new-strategy accounts' trades are
    shadowed like the others (their signal rows are their own).
    ``quality``: also run the quality variant (docs/observation-shadows-2.md) for every trade whose
    signal has a usable strength record; the others are counted in info["no_quality"] (by reason in
    info["no_quality_reasons"]).
    ``extra3``: also run VARIANTS3 (docs/observation-shadows-3.md) for every trade, after the others; a trade
    whose real leverage is not in the tier table gets no stopw rows (counted in info["no_leverage"])."""
    idx = {ts: k for k, (ts, _, _) in enumerate(steps)}
    per_symbol: dict[str, list] = {}
    vs = {v: variant_settings(settings, v) for v in VARIANTS + (VARIANTS3 if extra3 else ())}
    rows: list[dict] = []
    info = {"closed": 0, "no_signal": 0, "no_steps": 0}
    if quality:
        info.update(no_quality=0, no_quality_reasons={})
    if extra3:
        info.update(extra3=True, no_leverage=0)
    copies = copy_accounts(conn)
    for aid, t in closed_trades(conn, start, end):
        if aid in copies:                       # a copy repeats its parent's signal: the parent's shadow is it
            info["copy_trades"] = info.get("copy_trades", 0) + 1
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
                  "actual_pnl_equity": pnl_equity(t["roe"], t["leverage"])}
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
                data.update(leverage=tr.leverage, pnl_equity=pnl_equity(tr.roe, tr.leverage),
                            exit_time=tr.exit_time)
            rows.append(_shadow_row(v, day, aid, t, bc, tr, resolved, data))
        if extra3:
            rows += _extra3_rows(vs, brackets, specs, d, sig, ss, i0, day, aid, t, bc, actual, make_signal, info)
        if quality:
            q = quality_score(signal_strength(d), t["strategy_id"], t["timeframe"])
            if q["tier"] is None:
                info["no_quality"] += 1
                r = info["no_quality_reasons"]
                r[q["reason"]] = r.get(q["reason"], 0) + 1
                continue
            tr, resolved = run_alone(settings, brackets, specs, replace(sig, tier=q["tier"]), ss, i0)
            data = dict(actual, quality_score=q["score"], quality_tier=q["tier"], quintiles=q["quintiles"])
            if tr is not None:
                data.update(leverage=tr.leverage, pnl_equity=pnl_equity(tr.roe, tr.leverage),
                            exit_time=tr.exit_time, tier=tr.tier)
            rows.append(_shadow_row(QUALITY, day, aid, t, bc, tr, resolved, data))
    return rows, info


def _extra3_rows(vs: dict, brackets, specs, d: dict, sig: Signal, ss, i0: int, day: str, aid: str, t: dict,
                 bc: int, actual: dict, make_signal, info: dict) -> list[dict]:
    """The docs/observation-shadows-3.md rows of one closed trade: lev30 / lev40 / lev50 (fixed leverage, the
    tier's margin share, the usual sizing checks, no fallback) and stopw1.5 / 2.5 / 3 (k x ATR stop at the real
    trade's leverage, SameLeveragePolicy)."""
    out = []
    for v in FIXED_LEVERAGE3:
        tr, resolved = run_alone(vs[v], brackets, specs, sig, ss, i0)
        data = dict(actual)
        if tr is not None:
            data.update(leverage=tr.leverage, pnl_equity=pnl_equity(tr.roe, tr.leverage), exit_time=tr.exit_time)
        out.append(_shadow_row(v, day, aid, t, bc, tr, resolved, data))
    try:
        lev = int(round(float(t.get("leverage"))))
    except (TypeError, ValueError):
        lev = None
    if lev not in MARGIN_FRAC:
        info["no_leverage"] = info.get("no_leverage", 0) + 1
        return out
    for v, k in STOP_WIDTHS.items():
        policy = SameLeveragePolicy(vs[v], lev)
        tr, resolved = run_alone(vs[v], brackets, specs, make_signal(d, stop_atr=k), ss, i0, policy=policy)
        data = dict(actual, stop_atr=k, same_leverage=lev)
        if tr is not None:
            data.update(leverage=tr.leverage, pnl_equity=pnl_equity(tr.roe, tr.leverage), exit_time=tr.exit_time,
                        stop_beyond_liq=stop_beyond_liq(tr))
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
