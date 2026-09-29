"""Descriptive: distribution of family z / z_vn vs what a calibrated null (and the Discover agents'
real-timing null sd ~1.2-1.35) would give.  No decision."""
import numpy as np, pandas as pd
from scipy.stats import norm
g = pd.read_csv("out/gate_all_is_applied.csv"); f = g[g.in_family]
rows = []
for tf in ["ALL", "5m", "15m", "30m", "1h", "4h", "1d"]:
    x = f if tf == "ALL" else f[f.tf == tf]
    m = len(x)
    rows.append(dict(tf=tf, m=m, z_mean=x.z.mean(), z_sd=x.z.std(ddof=1), z_max=x.z.max(),
                     n_z_gt2=int((x.z > 2).sum()), exp_z_gt2_sd1=m * norm.sf(2), exp_z_gt2_sd125=m * norm.sf(2 / 1.25),
                     n_p_lt05=int((x.p < 0.05).sum()), exp_p_lt05=0.05 * m,
                     frac_fwd_gt0=(x.fwd > 0).mean(), n_fwd_ge_mu=int((x.fwd >= x.mu_star).sum()),
                     median_fwd_over_mu=float(np.median(x.fwd / x.mu_star)), max_fwd_over_mu=float((x.fwd / x.mu_star).max())))
d = pd.DataFrame(rows); d.to_csv("out/diag_zdist.csv", index=False)
pd.set_option("display.width", 250); print(d.round(3).to_string())
