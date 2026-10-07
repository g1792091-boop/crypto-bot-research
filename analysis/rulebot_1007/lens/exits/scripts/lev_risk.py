#!/usr/bin/env python3
"""Equity at risk per stop-out and sizing pass rates by leverage (margin = leverage % of equity, the rule bot's
quality_v1 tiers), on the live 15m / 30m / 1h / 4h house signals (exitlab base rows: the 2 ATR stop actually used).

    python3 -I lev_risk.py <exitlab_rows.csv> <out_dir>

loss_eq(L) = (L/100) x L x (stop_frac + slippage + 2 x taker)   [fraction of equity lost at the stop]
passes(L) = loss_eq <= 15% (max_loss_frac) and stop + max(1 ATR, 0.2%) inside the liquidation distance
           (isolated, liq distance ~ 1/L - mmr; mmr 0.5% used as a middle value of the inferred brackets).
Also the R-geometry of the ROE ladder at each L (first trigger / lock in R of the signal's own stop).
"""
import os
import site
import sys

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

TAKER, SLIP, MMR, RT = 0.0005, 0.0002, 0.005, 0.0014


def main():
    X = pd.read_csv(sys.argv[1], usecols=["run", "sig_id", "flip", "variant", "timeframe", "entry_price", "stop_initial",
                                          "status", "atr"], low_memory=False)
    out = sys.argv[2]
    b = X[(X.variant == "base") & (X.flip == 0) & X.status.isin(["CLOSED", "OPEN_END"])].copy()
    b["sf"] = (b.entry_price - b.stop_initial).abs() / b.entry_price
    b["atr_f"] = b["atr"] / b["entry_price"]
    rows = []
    for tf, g in b.groupby("timeframe"):
        for L in (10, 20, 30, 40, 50):
            mf = 0.2 if L == 10 else L / 100
            loss = mf * L * (g.sf + SLIP + 2 * TAKER)
            liq = 1.0 / L - MMR
            buf = np.maximum(g.atr_f, 0.002)
            ok = (loss <= 0.15) & (g.sf + buf <= liq)
            rows.append({"tf": tf, "lev": L, "margin_frac": mf, "notional_x_equity": mf * L, "n": len(g),
                         "median_stop_pct": 100 * g.sf.median(), "median_loss_eq_pct": 100 * loss.median(),
                         "p90_loss_eq_pct": 100 * loss.quantile(0.9), "share_pass_rules": ok.mean(),
                         "trig_R_median": ((0.12 / L + RT) / g.sf).median(),
                         "lock_R_median": ((0.10 / L + RT) / g.sf).median(),
                         "trail_gap_R_range": f"{(0.02 / L / g.sf).median():.2f}-{(0.07 / L / g.sf).median():.2f}",
                         "dd_after_7_losses_pct": 100 * (1 - (1 - loss.median()) ** 7)})
    D = pd.DataFrame(rows)
    D.to_csv(os.path.join(out, "lev_risk.csv"), index=False)
    pd.set_option("display.width", 250)
    print(D.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
