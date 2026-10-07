"""Cross-cell summary numbers for the report. usage: python3 -I -B summary_stats.py <out_dir>"""
import os, site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
import numpy as np
import pandas as pd
from scipy import stats
OUT = sys.argv[1]
C = pd.read_csv(os.path.join(OUT, "cards_15_30.csv"))
lines = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)
for tf in ["15m", "30m", "both"]:
    c = C if tf == "both" else C[C.timeframe == tf]
    say(f"== {tf}: cells {len(c)}; tiers {c.tier.value_counts().to_dict()}")
    e = c[c.es_n >= 20]
    say(f"  every-signal n>=20: {len(e)}; mean>0: {(e.es_mean_R>0).sum()}; mean<0: {(e.es_mean_R<0).sum()}; "
        f"CI(4h) above 0: {(e.es_ci_lo_4h>0).sum()}; CI below 0: {(e.es_ci_hi_4h<0).sum()}")
    say(f"  BH q<0.05 positive: {(c.es_bh_q_pos_4h<0.05).sum()}; BH q<0.05 negative: {(c.es_bh_q_neg_4h<0.05).sum()}; "
        f"BH q<0.10 negative: {(c.es_bh_q_neg_4h<0.10).sum()}; tested: {c.es_bh_q_pos_4h.notna().sum()}")
    say(f"  zero live every-signal rows: {(c.es_n==0).sum()}; n<10: {(c.es_n<10).sum()}")
    # persistence: v3a vs later
    p = c[(c.es_v3a_n >= 10) & (c.es_later_n >= 10)]
    if len(p) > 3:
        rho, pr = stats.spearmanr(p.es_v3a_mean_R, p.es_later_mean_R)
        same = (np.sign(p.es_v3a_mean_R) == np.sign(p.es_later_mean_R)).mean()
        say(f"  persistence v3a -> v3b+v4 (cells n>=10 both, {len(p)}): spearman {rho:.3f} (p {pr:.3f}); same sign share {same:.2f}; "
            f"v3a>0: {(p.es_v3a_mean_R>0).sum()}, of those later>0: {((p.es_v3a_mean_R>0)&(p.es_later_mean_R>0)).sum()}")
    p2 = c[(c.es_v3b_n >= 10) & (c.es_v4_n >= 10)]
    if len(p2) > 3:
        rho, pr = stats.spearmanr(p2.es_v3b_mean_R, p2.es_v4_mean_R)
        say(f"  persistence v3b -> v4 (cells n>=10 both, {len(p2)}): spearman {rho:.3f} (p {pr:.3f}); same sign "
            f"{(np.sign(p2.es_v3b_mean_R)==np.sign(p2.es_v4_mean_R)).mean():.2f}")
    # account vs every signal
    a = c[(c.acct_all_n >= 10) & (c.es_n >= 20)]
    if len(a) > 3:
        rho, pr = stats.spearmanr(a.acct_all_mean_R, a.es_mean_R)
        say(f"  account mean R vs every-signal mean R (acct n>=10, es n>=20; {len(a)} cells): spearman {rho:.3f} (p {pr:.3f}); "
            f"acct>0: {(a.acct_all_mean_R>0).sum()}, of those every-signal<0: {((a.acct_all_mean_R>0)&(a.es_mean_R<0)).sum()}")
    # live vs 5y
    l = c[(c.es_n >= 20) & c.y5_mean_ret_notional.notna()]
    if len(l) > 3:
        rho, pr = stats.spearmanr(l.es_mean_roe_per_lev, l.y5_mean_ret_notional)
        say(f"  live every-signal ret/notional vs 5y (es n>=20, {len(l)} cells): spearman {rho:.3f} (p {pr:.3f}); live<0: "
            f"{(l.es_mean_roe_per_lev<0).sum()}, 5y<0: {(l.y5_mean_ret_notional<0).sum()}; median live {l.es_mean_roe_per_lev.median():.5f} "
            f"5y {l.y5_mean_ret_notional.median():.5f}")
    y = c[c.y5_n_signals > 0]
    say(f"  5y: cells with signals {len(y)}; mean_ret_notional<0: {(y.y5_mean_ret_notional<0).sum()}; t<-2: {(y.y5_mean_roe_t<-2).sum()}; "
        f"IS<0 & CF<0: {((y.y5_mean_roe_is<0)&(y.y5_mean_roe_cf<0)).sum()}; gross ret/notional median {y.y5_gross_ret_notional.median():.5f} "
        f"range {y.y5_gross_ret_notional.min():.5f}..{y.y5_gross_ret_notional.max():.5f}")
    s = c[(c.y5_per_day > 0.5)]
    rho, pr = stats.spearmanr(s.live_sig_per_day, s.y5_per_day)
    say(f"  signals/day live vs 5y (5y>0.5/day, {len(s)} cells): spearman {rho:.3f}; median ratio live/5y {(s.live_sig_per_day/s.y5_per_day).median():.2f}")
    sf = c[c.sf_n_pairs >= 20]
    say(f"  side-flip cells n_pairs>=20: {len(sf)}; raw p_better<0.05: {(sf.sf_p_better<0.05).sum()}; their long_share: "
        f"{sf.loc[sf.sf_p_better<0.05, ['cell','es_long_share','sf_excess_R','sf_adj_excess_R']].round(3).values.tolist()}")
open(os.path.join(OUT, "summary_stats.txt"), "w").write("\n".join(lines) + "\n")
