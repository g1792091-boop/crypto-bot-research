"""Power from the REAL null sd of each family cell (no synthetic assumptions about timing):
to pass Holm step 1 (m=528) with 80% power a per-signal edge delta must satisfy
delta >= (z_crit + z_0.80) * null_sd  (z test), and also fwd >= mu*.
Report MDE80 in % per signal and relative to mu* per TF x H; and the fraction of cells in which an edge
equal to the hurdle (delta = mu* - null_mean) would be detected with >= 80% / >= 50% power."""
import numpy as np, pandas as pd
from scipy.stats import norm
d = pd.read_csv('out/check1_is_recomputed.csv')
fam = d[(d.n >= 100) & np.isfinite(d.p) & np.isfinite(d.p_vn)].copy()
m = len(fam); zc = norm.isf(0.05/m); z80 = norm.isf(0.2)
fam['mde80'] = (zc + z80) * fam.null_sd
fam['mde80_over_mu'] = fam.mde80 / fam.mu_star
# power for an edge that just lifts fwd to the hurdle: delta_h = mu* - null_mean
delta_h = fam.mu_star - fam.null_mean
fam['power_at_hurdle'] = norm.sf(zc - delta_h / fam.null_sd)
# power for an edge 1.5x hurdle
fam['power_at_1p5_hurdle'] = norm.sf(zc - (1.5*fam.mu_star - fam.null_mean) / fam.null_sd)
# effective independent episodes: per coin admissible bars / H (overlap) - crude upper bound (ignores cross-coin corr)
g = fam.groupby(['tf','H'])
out = g.agg(cells=('n','size'), n_median=('n','median'), mu_star_pct=('mu_star', lambda x: 100*x.median()),
            null_sd_pct=('null_sd', lambda x: 100*x.median()), mde80_pct=('mde80', lambda x: 100*x.median()),
            mde80_over_mu_med=('mde80_over_mu','median'), mde80_over_mu_min=('mde80_over_mu','min'),
            pw_hurdle_med=('power_at_hurdle','median'), frac_pw80_at_hurdle=('power_at_hurdle', lambda x: (x>=0.8).mean()),
            frac_pw50_at_hurdle=('power_at_hurdle', lambda x: (x>=0.5).mean()),
            pw_1p5_med=('power_at_1p5_hurdle','median'), n_min=('n_min','median'))
out['indep_windows_per_coin'] = out.n_min / out.index.get_level_values('H')
order = {'5m':0,'15m':1,'30m':2,'1h':3,'4h':4,'1d':5}
out = out.reset_index().sort_values(['tf','H'], key=lambda s: s.map(order) if s.name=='tf' else s)
pd.set_option('display.width', 250)
print(f'm={m} z_crit={zc:.3f}')
print(out.round(3).to_string(index=False))
out.to_csv('out/check6_power_realnull.csv', index=False)
# per TF summary
t = fam.groupby('tf').agg(cells=('n','size'), frac_pw80=('power_at_hurdle', lambda x: (x>=0.8).mean()),
                          med_mde_over_mu=('mde80_over_mu','median'))
print(t.loc[['5m','15m','30m','1h','4h','1d']].round(3))
# Observed z dispersion by TF (family)
print(fam.groupby('tf').z.agg(['mean','std','max']).loc[['5m','15m','30m','1h','4h','1d']].round(2))
print(fam.groupby('tf').z_vn.agg(['mean','std','max']).loc[['5m','15m','30m','1h','4h','1d']].round(2))
