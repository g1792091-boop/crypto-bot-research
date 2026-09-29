"""What-if lab: replay each closed trade's exit under alternative policies.

For every trade the entry is kept exactly (same time, fill price, quantity,
leverage, isolated margin, liquidation price) and only the exit rule
changes. Exits are simulated on 1m bars with the engine's fill rules:
stop-market with slippage (open on a gap), take-profit limit needing a
trade-through (maker fee), liquidation on mark price, stop first when a bar
touches both.

Limits of this method (reported with every result):
- Funding is left out of every policy, including C0, so C0 is compared to
  the ledger's P&L before funding.
- Paired per-trade comparison. With one position at a time, a different
  exit would also change which later signals could be taken; that
  sequence effect is not modelled.
- A policy that widens the stop keeps the original quantity. Trades whose
  loss at the new stop would exceed the 15% account cap are flagged
  ``over_cap``; under the owner rules they would have been sized smaller or
  rejected.
- This is a description of past trades. A policy is only adopted after
  confirmation on data the policy was not chosen on (after 2026-09-30).

Statistics: per-trade account return r = net P&L / equity before the trade.
Differences against C0 are resampled by UTC entry day (day-block bootstrap,
fixed seed). Multiple policies are corrected with Holm (p-values) and
Bonferroni (interval width). Fewer than ``min_n`` trades gives
"insufficient".
"""

from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .config import Settings
from .models import Bar, TradeRecord

DAY_MS = 86_400_000


@dataclass(frozen=True)
class ExitPolicy:
    """Exit rule. Unset fields keep the trade's original value.

    sl_roe: stop distance as gross ROE on margin (price move = roe / leverage).
    tp_roe: take-profit as net ROE (price move = roe / leverage + 0.14% round trip),
        the owners' take-profit definition since 2026-09-30.
    tp_r: take-profit at this multiple of the original stop distance.
    be_at_r: move the stop to entry (plus round-trip fees) after the price
        has moved this many R in favour (checked on bar close).
    time_bars: close at the bar close after this many 1m bars.
    trail_atr: trailing stop this many ATRs behind the best close.
    """

    pid: str
    group: str
    sl_roe: Optional[float] = None
    tp_roe: Optional[float] = None
    tp_r: Optional[float] = None
    be_at_r: Optional[float] = None
    time_bars: Optional[int] = None
    trail_atr: Optional[float] = None
    note: str = ""


def default_catalog() -> list[ExitPolicy]:
    cat = [ExitPolicy("C0", "baseline", note="original stop and target (reproduction)")]
    for x in (10, 20, 30, 40, 50):
        cat.append(ExitPolicy(f"SL_ROE{x}", "stop", sl_roe=x / 100))
    for x in (10, 15, 20, 30, 50):
        cat.append(ExitPolicy(f"TP_ROE{x}", "target", tp_roe=x / 100))
    for x in (1.5, 2.0, 3.0):
        cat.append(ExitPolicy(f"TP_{x:g}R", "target", tp_r=x))
    cat.append(ExitPolicy("BE_1R", "manage", be_at_r=1.0))
    for n in (60, 240, 1440):
        cat.append(ExitPolicy(f"TIME_{n}m", "manage", time_bars=n))
    for k in (1.5, 3.0):
        cat.append(ExitPolicy(f"TRAIL_{k:g}ATR", "manage", trail_atr=k))
    return cat


@dataclass
class SimResult:
    status: str  # closed / open_at_end / no_bars
    reason: str = ""
    exit_price: float = 0.0
    exit_time: int = 0
    pnl: float = 0.0  # net of fees, before funding
    fees: float = 0.0
    bars: int = 0
    flags: list[str] = field(default_factory=list)


def _levels(t: TradeRecord, pol: ExitPolicy, settings: Settings) -> tuple[float, float]:
    e, s = t.entry_price, t.side
    stop, tp = t.stop_price, t.tp_price
    if pol.sl_roe is not None:
        stop = e * (1 - s * pol.sl_roe / t.leverage)
    if pol.tp_roe is not None:
        tp = e * (1 + s * (pol.tp_roe / t.leverage + settings.round_trip_cost))  # net ROE
    if pol.tp_r is not None:
        tp = e + s * pol.tp_r * abs(t.entry_price - t.stop_price)
    return stop, tp


def simulate(t: TradeRecord, pol: ExitPolicy, bars: Sequence[Bar], settings: Settings,
             max_bars: int = 10_080) -> SimResult:
    """``bars``: the symbol's 1m bars; the first used is the entry bar."""
    s = t.side
    e = t.entry_price
    q = t.qty
    slip = settings.slippage_frac
    entry_fee = q * e * settings.taker_fee
    stop, tp = _levels(t, pol, settings)
    liq = t.liq_price
    d0 = abs(e - t.stop_price)
    atr = t.context.get("atr") if t.context else None
    flags: list[str] = []
    if pol.trail_atr is not None and not atr:
        return SimResult("no_bars", "no ATR in trade context")
    if (stop - liq) * s < 0:
        flags.append("stop_beyond_liq")

    i0 = bisect.bisect_left([b.open_time for b in bars], t.entry_time) if bars else 0
    run = list(bars[i0:i0 + max_bars + 1])
    if not run or run[0].open_time != t.entry_time:
        return SimResult("no_bars", "entry bar missing")

    def close(price: float, ts: int, reason: str, maker: bool, n: int) -> SimResult:
        gross = s * q * (price - e)
        if gross < -t.margin:
            return SimResult("closed", "LIQ", liq, ts, -t.margin - entry_fee,
                             entry_fee, n, flags + ["LIQ"])
        fee = q * price * (settings.maker_fee if maker else settings.taker_fee)
        return SimResult("closed", reason, price, ts, gross - entry_fee - fee,
                         entry_fee + fee, n, flags)

    def liquidate(ts: int, n: int) -> SimResult:
        return SimResult("closed", "LIQ", liq, ts, -t.margin - entry_fee, entry_fee, n,
                         flags + ["LIQ"])

    best = e
    for i, b in enumerate(run):
        n = i + 1
        if i > 0:
            if (b.m_open - liq) * s <= 0:
                return liquidate(b.open_time, n)
            if (b.open - stop) * s <= 0:
                return close(b.open * (1 - s * slip), b.open_time, "SL", False, n)
            if (b.open - tp) * s > 0:
                return close(b.open, b.open_time, "TP", True, n)
        hit_stop = (b.low <= stop) if s > 0 else (b.high >= stop)
        hit_tp = (b.high > tp) if s > 0 else (b.low < tp)
        hit_liq = (b.m_low <= liq) if s > 0 else (b.m_high >= liq)
        if hit_liq and "stop_beyond_liq" in flags:
            return liquidate(b.close_time, n)
        if hit_stop and hit_tp and not settings.stop_first_on_ambiguous_bar:
            return close(tp, b.close_time, "TP", True, n)
        if hit_stop:
            return close(stop * (1 - s * slip), b.close_time, "SL", False, n)
        if hit_liq:
            return liquidate(b.close_time, n)
        if hit_tp:
            return close(tp, b.close_time, "TP", True, n)
        # Management rules act on the close; new levels apply from the next bar.
        if pol.time_bars is not None and n >= pol.time_bars:
            return close(b.close * (1 - s * slip), b.close_time, "TIME", False, n)
        if pol.be_at_r is not None and d0 > 0 and s * (b.close - e) >= pol.be_at_r * d0:
            be = e * (1 + s * 2 * settings.taker_fee)
            if (be - stop) * s > 0:
                stop = be
        if pol.trail_atr is not None:
            best = max(best, b.close) if s > 0 else min(best, b.close)
            trail = best - s * pol.trail_atr * atr
            if (trail - stop) * s > 0:
                stop = trail
    last = run[-1]
    if len(run) > max_bars:
        return close(last.close * (1 - s * slip), last.close_time, "MAXBARS", False, len(run))
    res = close(last.close * (1 - s * slip), last.close_time, "OPEN", False, len(run))
    res.status = "open_at_end"
    return res


# ------------------------------------------------------------------ stats
def _equity_before(t: TradeRecord) -> float:
    return t.equity_after - t.pnl


def _day(ts: int) -> int:
    return ts // DAY_MS


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def day_block_bootstrap(diffs: list[tuple[int, float]], b: int = 2000,
                        alpha: float = 0.05, seed: int = 7) -> dict:
    """Mean of per-trade differences, resampling whole UTC days."""
    days: dict[int, list[float]] = {}
    for day, x in diffs:
        days.setdefault(day, []).append(x)
    keys = sorted(days)
    n = len(diffs)
    mean = sum(x for _, x in diffs) / n if n else 0.0
    if len(keys) < 2:
        return {"mean": mean, "lo": None, "hi": None, "p": None, "days": len(keys)}
    rng = random.Random(seed)
    means = []
    for _ in range(b):
        tot = cnt = 0
        for _k in keys:
            xs = days[keys[rng.randrange(len(keys))]]
            tot += sum(xs)
            cnt += len(xs)
        means.append(tot / cnt)
    means.sort()
    lo = means[int(math.floor(alpha / 2 * (b - 1)))]
    hi = means[int(math.ceil((1 - alpha / 2) * (b - 1)))]
    # Two-sided p from the share of resamples on the other side of zero.
    below = sum(m <= 0 for m in means) / b
    above = sum(m >= 0 for m in means) / b
    p = min(1.0, 2 * min(below, above))
    p = max(p, 1 / b)
    return {"mean": mean, "lo": lo, "hi": hi, "p": p, "days": len(keys)}


def holm(pvals: dict[str, Optional[float]]) -> dict[str, Optional[float]]:
    items = sorted(((p, k) for k, p in pvals.items() if p is not None))
    m = len(items)
    out: dict[str, Optional[float]] = {k: None for k in pvals}
    running = 0.0
    for i, (p, k) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def policy_stats(rows: list[dict]) -> dict:
    rs = [r["ret"] for r in rows]
    n = len(rs)
    if not n:
        return {"n": 0}
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x <= 0]
    comp = 1.0
    worst_run = run = 0
    for x in rs:
        comp *= 1 + x
        run = run + 1 if x <= 0 else 0
        worst_run = max(worst_run, run)
    gl = -sum(losses)
    return {
        "n": n,
        "win_rate": len(wins) / n,
        "mean_ret": sum(rs) / n,
        "compounded": comp - 1,
        "profit_factor": (sum(wins) / gl) if gl > 0 else None,
        "max_consecutive_losses": worst_run,
        "mean_r": (sum(r["r"] for r in rows if r["r"] is not None)
                   / max(1, sum(r["r"] is not None for r in rows))),
        "liquidations": sum("LIQ" in r["flags"] for r in rows),
        "over_cap": sum("over_cap" in r["flags"] for r in rows),
        "exit_reasons": _count(r["reason"] for r in rows),
    }


def _count(xs) -> dict:
    out: dict = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def run_lab(trades: Sequence[TradeRecord], bars_by_symbol: dict[str, list[Bar]],
            settings: Settings, catalog: Optional[list[ExitPolicy]] = None,
            min_n: int = 30, alpha: float = 0.05, boot: int = 2000,
            repro_tol: float = 1e-6) -> dict:
    catalog = catalog or default_catalog()
    if catalog[0].pid != "C0":
        catalog = [ExitPolicy("C0", "baseline")] + list(catalog)
    per: dict[str, dict[int, dict]] = {p.pid: {} for p in catalog}
    keys = {sym: [b.open_time for b in bs] for sym, bs in bars_by_symbol.items()}
    skipped: dict[str, int] = {}
    repro_bad = []
    for i, t in enumerate(trades):
        if t.exit_reason in ("HALT", "MANUAL"):
            skipped["operator/halt exit"] = skipped.get("operator/halt exit", 0) + 1
            continue
        allbars = bars_by_symbol.get(t.symbol, [])
        j = bisect.bisect_left(keys.get(t.symbol, []), t.entry_time)
        bars = allbars[j:j + 10_082]
        eq0 = _equity_before(t)
        unit = abs(t.entry_price - t.stop_price) * t.qty
        for pol in catalog:
            res = simulate(t, pol, bars, settings)
            if res.status != "closed":
                key = f"{pol.pid}: {res.status} ({res.reason})"
                skipped[key] = skipped.get(key, 0) + 1
                continue
            flags = list(res.flags)
            stop, _ = _levels(t, pol, settings)
            loss_at_stop = (t.qty * abs(t.entry_price - stop)
                            + t.qty * (t.entry_price + stop) * settings.taker_fee)
            if eq0 > 0 and loss_at_stop > settings.max_loss_frac * eq0 * (1 + 1e-9):
                flags.append("over_cap")
            per[pol.pid][i] = {"ret": res.pnl / eq0 if eq0 > 0 else 0.0,
                               "r": res.pnl / unit if unit > 0 else None,
                               "pnl": res.pnl, "reason": res.reason, "flags": flags,
                               "day": _day(t.entry_time)}
            if pol.pid == "C0":
                ref = t.pnl + t.funding
                if abs(res.pnl - ref) > repro_tol * max(1.0, abs(ref)) or res.reason != t.exit_reason:
                    repro_bad.append({"trade": i, "symbol": t.symbol, "ledger_pnl_before_funding": ref,
                                      "sim_pnl": res.pnl, "ledger_exit": t.exit_reason,
                                      "sim_exit": res.reason})
    base = per["C0"]
    others = [p for p in catalog if p.pid != "C0"]
    alpha_b = alpha / max(1, len(others))
    results = []
    pvals = {}
    for pol in catalog:
        rows_map = per[pol.pid]
        stats = policy_stats([rows_map[k] for k in sorted(rows_map)])
        entry = {"policy": pol.pid, "group": pol.group, "note": pol.note, **stats}
        if pol.pid != "C0":
            common = sorted(set(rows_map) & set(base))
            diffs = [(rows_map[k]["day"], rows_map[k]["ret"] - base[k]["ret"]) for k in common]
            entry["paired_n"] = len(diffs)
            if len(diffs) < min_n:
                entry["delta"] = None
                entry["verdict"] = f"insufficient (n<{min_n})"
            else:
                bs = day_block_bootstrap(diffs, boot, alpha_b)
                entry["delta"] = bs
                pvals[pol.pid] = bs["p"]
        results.append(entry)
    adj = holm(pvals)
    for entry in results:
        pid = entry["policy"]
        if pid in adj and entry.get("delta"):
            entry["p_holm"] = adj[pid]
            d = entry["delta"]
            sig = adj[pid] is not None and adj[pid] < alpha
            if all(abs(per[pid][k]["ret"] - base[k]["ret"]) < 1e-12
                   for k in set(per[pid]) & set(base)):
                entry["verdict"] = "identical to C0 on these trades"
            elif d["lo"] is None:
                entry["verdict"] = "insufficient (one day)"
            elif sig and d["lo"] > 0:
                entry["verdict"] = "better than C0 (hypothesis; confirm forward)"
            elif sig and d["hi"] < 0:
                entry["verdict"] = "worse than C0"
            else:
                entry["verdict"] = "no clear difference"
    return {
        "trades": len(trades),
        "policies": results,
        "reproduction": {"checked": len(base), "mismatches": repro_bad,
                         "ok": not repro_bad},
        "skipped": skipped,
        "method": {"alpha": alpha, "bonferroni_alpha": alpha_b, "bootstrap": boot,
                   "block": "UTC day", "min_n": min_n, "funding": "excluded",
                   "sequence_effect": "not modelled"},
    }
