"""Sanity check: exhaustive coin-flip rows vs the pipeline replay of real signals at the same run/bar/coin/side/tf
(leverage group normal vs tier normal). Differences come from the reference price (1m open vs the live ref price)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
O, W = sys.argv[1], sys.argv[2]
X = pd.read_csv(os.path.join(W, "cf_exhaustive_rows.csv"), low_memory=False)
X = X[(X.lev_group == "normal") & (X.status == "TRADED")]
R = pd.read_csv(os.path.join(O, "replay_signals.csv"), low_memory=False)
R = R[(R.status == "TRADED") & (R.tier == "normal")]
m = R.merge(X, on=["run", "bar_close", "timeframe", "symbol", "side"], suffixes=("_real", "_cf"))
m = m.drop_duplicates(["run", "bar_close", "timeframe", "symbol", "side", "strategy"])
print("matched", len(m), "corr R", round(np.corrcoef(m.R_real, m.R_cf)[0, 1], 3),
      "mean R real", round(m.R_real.mean(), 3), "mean R cf", round(m.R_cf.mean(), 3),
      "same exit reason", round((m.exit_reason_real == m.exit_reason_cf).mean(), 3),
      "median |ref diff| bps", round((1e4 * (m.ref_price_real / m.ref_price_cf - 1)).abs().median(), 2),
      "atr rel diff median", round(((m.atr_real / m.atr_cf) - 1).abs().median(), 4))
