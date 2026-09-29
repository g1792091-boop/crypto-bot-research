"""Single-account simulation across symbols (one position at a time, 40 % margin)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def single_account(trades: pd.DataFrame, lev: float, margin_frac: float = 0.40, mmr: float = 0.005,
                   start_equity: float = 1000.0) -> dict:
    t = trades.copy()
    t["entry_ts"] = pd.to_datetime(t["entry_ts"], utc=True)
    t["exit_ts"] = pd.to_datetime(t["exit_ts"], utc=True)
    t = t.sort_values(["entry_ts", "symbol"]).reset_index(drop=True)
    liq_dist = 1.0 / lev - mmr
    equity = start_equity
    peak = equity
    mdd = 0.0
    busy_until = pd.Timestamp("1970-01-01", tz="UTC")
    taken, skipped, liq = 0, 0, 0
    curve = []
    for row in t.itertuples(index=False):
        if row.entry_ts < busy_until:
            skipped += 1
            continue
        roe = -1.0 if row.mae <= -liq_dist else max(-1.0, lev * row.net)
        if roe <= -1.0:
            liq += 1
        equity *= (1.0 + margin_frac * roe)
        taken += 1
        busy_until = row.exit_ts
        peak = max(peak, equity)
        mdd = max(mdd, 1.0 - equity / peak)
        curve.append((row.exit_ts, equity))
        if equity <= 1.0:
            break
    days = (t["exit_ts"].max() - t["entry_ts"].min()).total_seconds() / 86400.0 if len(t) else 0.0
    return dict(final=equity, ret_pct=(equity / start_equity - 1.0) * 100.0, mdd=mdd, taken=taken,
                skipped=skipped, liq=liq, per_day=(taken / days if days else 0.0), days=days,
                curve=curve)
