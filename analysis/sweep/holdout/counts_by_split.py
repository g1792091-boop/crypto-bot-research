"""DESCRIPTIVE counts per split (IS from combine, OOS/FINAL from this agent), each over its own n>=100 family."""
import os, sys
import numpy as np, pandas as pd
from scipy.stats import norm
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as L
S = os.path.dirname(HERE); O = os.path.join(HERE, "out")
sp = {"IS": pd.read_csv(os.path.join(S, "combine", "out", "gate_all_is_applied.csv")),
      "OOS": pd.read_csv(os.path.join(O, "gate_all_oos_applied.csv")),
      "FINAL": pd.read_csv(os.path.join(O, "gate_all_final_applied.csv"))}
rows = []
for lab, g in sp.items():
    for tf in ("ALL",) + L.TFS:
        f = g[g.in_family] if tf == "ALL" else g[g.in_family & (g.tf == tf)]
        m = len(f)
        rows.append(dict(split=lab, tf=tf, family=m, fwd_pos=int((f.fwd > 0).sum()), z_gt2=int((f.z > 2).sum()),
                         z_gt2_expected_N01=round(m * norm.sf(2), 1), p_lt05=int((f.p < 0.05).sum()), p_lt05_expected=round(0.05 * m, 1),
                         p_vn_lt05=int((f.p_vn < 0.05).sum()), p_and_pvn_lt05=int(((f.p < 0.05) & (f.p_vn < 0.05)).sum()),
                         raw_z2_but_zvn_neg=int(((f.z > 2) & (f.z_vn < 0)).sum()),
                         fwd_gt_cost=int((f.fwd > f.cost_H).sum()), fwd_ge_mu=int((f.fwd >= f.mu_star).sum()),
                         fwd_ge_mu_and_p05=int(((f.fwd >= f.mu_star) & (f.p < 0.05)).sum()),
                         fwd_ge_mu_and_p05_and_pvn05=int(((f.fwd >= f.mu_star) & (f.p < 0.05) & (f.p_vn < 0.05)).sum()),
                         z_mean=round(f.z.mean(), 3), z_sd=round(f.z.std(), 3), z_max=round(f.z.max(), 3),
                         min_p=f.p.min(), holm_sig_p=int((f.p_holm < 0.05).sum()), holm_sig_pvn=int((f.p_vn_holm < 0.05).sum()),
                         holm_sig_both=int(((f.p_holm < 0.05) & (f.p_vn_holm < 0.05)).sum())))
C = pd.DataFrame(rows)
C.to_csv(os.path.join(O, "counts_by_split.csv"), index=False)
pd.set_option("display.width", 300)
print(C.to_string())
for lab in ("OOS", "FINAL"):
    g = sp[lab]; f = g[g.in_family]
    print(f"\n{lab}: Holm-significant p cells (own family, descriptive):")
    print(f[f.p_holm < 0.05][["strategy", "tf", "H", "n", "fwd", "mu_star", "cost_H", "z", "p", "p_holm", "z_vn", "p_vn", "p_vn_holm", "symbols_pos"]].to_string())
    print(f"{lab}: Holm-significant p_vn cells:")
    print(f[f.p_vn_holm < 0.05][["strategy", "tf", "H", "n", "fwd", "mu_star", "z", "p", "z_vn", "p_vn", "p_vn_holm"]].to_string())
    print(f"{lab}: fwd>=mu* & p<.05 & p_vn<.05:")
    print(f[(f.fwd >= f.mu_star) & (f.p < 0.05) & (f.p_vn < 0.05)][["strategy", "tf", "H", "n", "fwd", "mu_star", "z", "p", "z_vn", "p_vn", "symbols_pos", "prev_examined", "approx"]].to_string())
