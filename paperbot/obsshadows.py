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

Nothing here touches a real account: rows go to daily3.db ``shadows`` only.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Optional

import numpy as np

from .aggregate import TF_MS
from .config import Settings, Tier
from .engine import PaperEngine
from .models import Signal

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


def variant_settings(settings: Settings, name: str) -> Settings:
    if name in LOCKS:
        return replace(settings, ladder_first_lock=LOCKS[name])
    if name in FIXED_LEVERAGE:
        lev = FIXED_LEVERAGE[name]
        # one tier named "best" (the tier every v3 signal requests), so there is no fallback
        return replace(settings, tiers=(Tier("best", FIXED_MARGIN_FRAC, (lev,)),),
                       min_leverage=min(lev, settings.min_leverage), max_leverage=max(lev, settings.max_leverage))
    if name in ("base", "timestop"):
        return settings
    raise ValueError(f"unknown variant {name!r}")


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
              time_stop_ms: Optional[int] = None) -> tuple[Optional[object], bool]:
    """``daily3._alone`` with an optional time stop: once ``time_stop_ms`` has passed since entry
    and the lock never armed, close at the 1m bar close (market, with slippage), reason "TIME".
    Returns (trade or None, resolved)."""
    e = PaperEngine(settings, brackets, symbol_specs=specs, book="shadow")
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


def first_signal(conn, start: int, end: int) -> Optional[int]:
    """Earliest signal bar close (within LOOKBACK_MS) among the day's closed trades, if before ``start``."""
    bcs = [t["signal_ts"] + 1 for _, t in closed_trades(conn, start, end)]
    bcs = [b for b in bcs if start - LOOKBACK_MS <= b < start]
    return min(bcs) if bcs else None


def _signal_row(conn, t: dict) -> Optional[dict]:
    r = conn.execute(
        "SELECT bar_close, timeframe, strategy, symbol, side, atr, ref_price, ref_time, delay_ms FROM signal_log "
        "WHERE timeframe = ? AND bar_close = ? AND strategy = ? AND symbol = ? AND side = ? AND status = 'SUBMITTED' "
        "ORDER BY id LIMIT 1",
        (t["timeframe"], t["signal_ts"] + 1, t["strategy_id"], t["symbol"], int(t["side"]))).fetchone()
    if r is None:
        return None
    return dict(zip(("bar_close", "timeframe", "strategy", "symbol", "side", "atr", "ref_price", "ref_time",
                     "delay_ms"), r))


def trade_shadows(settings: Settings, brackets, specs, conn, day: str, start: int, end: int, steps,
                  make_signal) -> tuple[list[dict], dict]:
    """Rows for the shadows table (one per closed trade and variant) and counts of trades left out.
    ``steps`` must reach back to the earliest signal (``first_signal``); ``make_signal`` is daily3's."""
    idx = {ts: k for k, (ts, _, _) in enumerate(steps)}
    per_symbol: dict[str, list] = {}
    vs = {v: variant_settings(settings, v) for v in VARIANTS}
    rows: list[dict] = []
    info = {"closed": 0, "no_signal": 0, "no_steps": 0}
    for aid, t in closed_trades(conn, start, end):
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
            rows.append({"key": f"{v}|{aid}|{t['symbol']}|{bc}", "day": day, "kind": v, "account_id": aid,
                         "symbol": t["symbol"], "timeframe": t["timeframe"], "side": int(t["side"]),
                         "filled": None, "roe": None if tr is None else tr.roe,
                         "exit_reason": None if tr is None else tr.exit_reason, "resolved": int(resolved),
                         "data": json.dumps(data)})
    return rows, info


def _mean(xs) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return float(np.mean(xs)) if xs else None


def summarize(rows: list[dict], info: dict) -> dict:
    """report["shadows"]["trade_variants"]: per variant, over the trades it resolved, the variant's and
    the actual trades' mean ROE and mean P&L on equity, and how often the variant did better/worse
    than the actual trade (P&L on equity; equal counts as neither)."""
    out: dict = dict(info)
    for v in VARIANTS:
        rs = [r for r in rows if r["kind"] == v]
        done = [(r, json.loads(r["data"])) for r in rs if r["resolved"] and r["roe"] is not None]
        pairs = [(d.get("pnl_equity"), d.get("actual_pnl_equity")) for _, d in done]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        out[v] = {
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
    return out
