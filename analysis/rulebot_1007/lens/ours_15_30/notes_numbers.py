"""One numbers line per cell for the strategy notes. usage: python3 -I -B notes_numbers.py <out_dir>"""
import os, site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
import numpy as np
import pandas as pd
OUT = sys.argv[1]
C = pd.read_csv(os.path.join(OUT, "cards_15_30.csv"))
def f(x, d=2, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "na"
    return (f"{x:+.{d}f}" if sign else f"{x:.{d}f}")
out = []
for r in C.sort_values(["timeframe", "strategy"]).itertuples():
    s = (f"every-signal n {r.es_n} mean {f(r.es_mean_R)}R"
         + (f" [4h-cluster 95% CI {f(r.es_ci_lo_4h)}, {f(r.es_ci_hi_4h)}]" if np.isfinite(r.es_ci_lo_4h) else "")
         + f"; by run v3a/v3b/v4 {r.sign_v3a_v3b_v4}; later(v3b+v4) n {r.es_later_n} {f(r.es_later_mean_R)}R"
         + f"; account n {int(r.acct_all_n)} mean {f(r.acct_all_mean_R)}R"
         + (f" PF {f(r.acct_all_profit_factor, 2, False)} worstDD {f(100*r.acct_all_worst_realized_dd_any_run, 0, False)}%" if r.acct_all_n > 0 else "")
         + (f"; side-flip excess {f(r.sf_excess_R)}R (n {int(r.sf_n_pairs)}, p {f(r.sf_p_better, 2, False)})" if np.isfinite(r.sf_n_pairs) else "; side-flip na")
         + (f"; coin-flip boot p {f(r.cf_p_one_sided, 3, False)}" if np.isfinite(r.cf_n) else "")
         + f"; 5y {f(100*r.y5_mean_ret_notional, 3)}%/notional t {f(r.y5_mean_roe_t, 1)} IS {f(r.y5_mean_roe_is, 3)} CF {f(r.y5_mean_roe_cf, 3)} ROE"
         + f"; sig/day live {f(r.live_sig_per_day, 1, False)} vs 5y {f(r.y5_per_day, 1, False)}"
         + (f"; cost {f(r.es_median_rt_cost_over_stop, 2, False)}R/rt; MFE {f(r.es_mean_mfe_R)} MAE {f(r.es_mean_mae_R)}R" if r.es_n > 0 else ""))
    out.append(f"{r.cell}\t{r.tier}\t{s}")
open(os.path.join(OUT, "notes_numbers.tsv"), "w").write("\n".join(out) + "\n")
print("\n".join(out))
