"""Leverage feasibility of the house 2 x ATR14 stop per timeframe and coin, at 5-year-typical and current volatility.

    python3 -I -B feas.py <core_sig_dir> <out_csv>

Distribution: ATR14 / close of every bar (2021-08-01..2026-09-30 = '5y'; 2026-08-30..2026-09-29 = 'last30d').
(a) house sizing at one fixed leverage L (margin = L% of equity, as the owners' tiers): paperbot.sizing.size_position
    with v3_settings rules (stop inside liquidation by max(1 ATR, 0.2%), loss at stop incl. costs <= 15% of equity,
    bracket), live-inferred brackets, equity $5,000. Long side.
(b) risk-per-stop sizing: notional so the loss at the stop (fees + slippage incl.) = r x equity, r in {2%, 5%};
    margin = notional / L must be <= 50% of equity (v3_settings max_margin_frac); bracket must allow L; stop inside
    liquidation by max(1 ATR, 0.2%).
"""
import os
import sys

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', '/home/user/crypto-bot-research']
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from paperbot.config import Tier, v3_settings  # noqa: E402
from paperbot.margin import liquidation_price  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from precompute import BR, COINS, EQUITY  # noqa: E402

LEVS = (20, 30, 40, 50)
S0 = v3_settings()


def house_ok(coin, L, atr_frac):
    S = v3_settings(leverage_rule="tier_walk", tiers=(Tier("x", L / 100.0, (L,)),))
    raw = 100.0
    a = atr_frac * raw
    fill = raw * (1 + S.slippage_frac)
    d = size_position(S, EQUITY, 1, fill, raw - 2 * a, "x", BR[coin], atr=a, min_notional=5.0)
    return d.ok


def risk_ok(coin, L, atr_frac, r):
    raw = 100.0
    a = atr_frac * raw
    fill = raw * (1 + S0.slippage_frac)
    stop = raw - 2 * a
    exit_px = stop * (1 - S0.slippage_frac)
    loss_per_qty = (fill - exit_px) + S0.taker_fee * (fill + exit_px)
    qty = r * EQUITY / loss_per_qty
    notional = qty * fill
    margin = notional / L
    if margin > S0.max_margin_frac * EQUITY:
        return False
    br = BR[coin].for_notional(notional)
    if L > br.max_leverage:
        return False
    liq = liquidation_price(1, qty, fill, margin, br)
    buf = max(S0.liq_buffer_atr_mult * a, S0.liq_buffer_min_frac * fill)
    return (stop - liq) >= buf


def main(core_dir, out_csv):
    rows = []
    grid = np.round(np.exp(np.linspace(np.log(0.0003), np.log(0.06), 400)), 7)
    for coin in COINS:
        tabs = {}
        for L in LEVS:
            tabs[("house", L)] = np.array([house_ok(coin, L, g) for g in grid])
            for r in (0.02, 0.05):
                tabs[(f"risk{int(r*100)}", L)] = np.array([risk_ok(coin, L, g, r) for g in grid])
        for tf in ("15m", "30m", "1h", "4h"):
            z = np.load(os.path.join(core_dir, f"sig_{tf}_{coin}.npz"))
            ts, c, atr = z["ts"], z["c"], z["atr"]
            af = atr / c
            for per, (a0, a1) in {"5y": ("2021-08-01", "2026-09-30"), "last30d": ("2026-08-30", "2026-09-30")}.items():
                m = (ts >= pd.Timestamp(a0).value) & (ts < pd.Timestamp(a1).value) & np.isfinite(af)
                x = af[m]
                gi = np.clip(np.searchsorted(grid, x), 0, len(grid) - 1)
                row = dict(coin=coin, tf=tf, period=per, bars=int(m.sum()),
                           stop_pct_median=float(np.median(2 * x) * 100), stop_pct_p25=float(np.percentile(2 * x, 25) * 100),
                           stop_pct_p75=float(np.percentile(2 * x, 75) * 100))
                for (kind, L), ok in tabs.items():
                    row[f"{kind}_{L}x_pass"] = float(ok[gi].mean())
                rows.append(row)
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(pd.DataFrame(rows).to_string())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
