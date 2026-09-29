"""Standard performance metrics (the eight the performance analyst reads)."""

from __future__ import annotations

from typing import Optional, Sequence

from .models import TradeRecord


def standard_metrics(trades: Sequence[TradeRecord], start_equity: Optional[float] = None) -> dict:
    n = len(trades)
    if not n:
        return {"trades": 0}
    pnl = [t.pnl for t in trades]
    wins = [x for x in pnl if x > 0]
    gross_loss = -sum(x for x in pnl if x <= 0)
    rs = [t.pnl / (abs(t.entry_price - t.stop_price) * t.qty)
          for t in trades if abs(t.entry_price - t.stop_price) * t.qty > 0]
    eq0 = start_equity if start_equity is not None else trades[0].equity_after - trades[0].pnl
    # Drawdown on closed-trade equity (the equity table adds open-position swings).
    peak = eq0
    mdd = 0.0
    for t in trades:
        peak = max(peak, t.equity_after)
        if peak > 0:
            mdd = max(mdd, 1 - t.equity_after / peak)
    run = worst = 0
    for x in pnl:
        run = run + 1 if x <= 0 else 0
        worst = max(worst, run)
    return {
        "trades": n,
        "win_rate": len(wins) / n,
        "profit_factor": sum(wins) / gross_loss if gross_loss > 0 else None,
        "expectancy_r": sum(rs) / len(rs) if rs else None,
        "net_pnl": sum(pnl),
        "net_return": sum(pnl) / eq0 if eq0 > 0 else None,
        "max_drawdown_closed": mdd,
        "avg_hold_min": sum(t.exit_time - t.entry_time for t in trades) / n / 60_000,
        "max_consecutive_losses": worst,
        "liquidations": sum(t.exit_reason == "LIQ" for t in trades),
        "fees": sum(t.fees for t in trades),
        "funding": sum(t.funding for t in trades),
        "start_equity": eq0,
        "end_equity": trades[-1].equity_after,
    }
