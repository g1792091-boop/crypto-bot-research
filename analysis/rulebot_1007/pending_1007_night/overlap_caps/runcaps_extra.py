"""Sensitivity: a broad 'trend hub' cluster = connected component of pairs passing both pair conditions
(kappa_1h >= 0.5 and every-signal daily R corr >= 0.5) inside the swapped 17 (T17S):
{N23_HA_ST, F4_FAN, F7_RF_TRIPLE, N18_VWMA_MACD, DOGE, V39_ALL}.
    python3 -I -B runcaps_extra.py <sig23.npz> <out_dir>"""
import os, sys
sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', os.path.dirname(os.path.abspath(__file__))]
import pandas as pd  # noqa: E402
import runcaps as RC  # noqa: E402

RC.CLS["HUB"] = {"TREND": ["N23_HA_ST", "F4_FAN", "F7_RF_TRIPLE", "N18_VWMA_MACD", "DOGE", "V39_ALL"]}
if __name__ == "__main__":
    path, out = sys.argv[1:3]
    cfgs = [(0, "off", 0), (0, "HUB", 0), (4, "HUB", 10), (3, "HUB", 8), (4, "REC", 10)]
    b, t, _, _ = RC.job((path, "T17S", "CARD", 1.0, cfgs))
    pd.DataFrame(b).to_csv(os.path.join(out, "runs_book_hub.csv"), index=False, float_format="%.5g")
    pd.DataFrame(t).to_csv(os.path.join(out, "runs_trader_hub.csv"), index=False, float_format="%.5g")
    x = pd.DataFrame(b)
    x["dtr"] = x.dTrades / (x.trades - x.dTrades)
    print(x[["cs_cap", "cluster", "book_cap", "blocked_share", "dtr", "book_sd_day", "diversification_ratio", "meanG", "blocked_meanG", "dG_book", "dG_book_ci_lo", "dG_book_ci_hi"]].round(4).to_string())
    y = pd.DataFrame(t)
    y = y[(y.cluster == "HUB") & (y.cs_cap == 0)]
    print(y[["trader", "blocked_share", "d_trades_pct"]].round(3).to_string())
