"""Per strategy x TF: n (H=4), best cell by fwd - mu*, its z / z_vn, and all-H gross fwd; descriptive."""
import pandas as pd, numpy as np
from scipy.stats import spearmanr
g = pd.read_csv('gate_cells.csv')
rows = []
for (s, tf), d in g.groupby(['strategy', 'tf']):
    d = d.sort_values('H')
    b = d.loc[d['fwd_minus_mu_star'].idxmax()] if d['fwd_minus_mu_star'].notna().any() else d.iloc[0]
    r = dict(strategy=s, tf=tf, group=b['group'], approx=b['approx'], previously_examined=b['previously_examined'],
             n_H4=int(d[d.H == 4]['n'].iloc[0]), best_H=int(b['H']), best_fwd_pct=b['fwd_pct'], best_mu_star_pct=b['mu_star'] * 100,
             best_fwd_minus_mu_pct=b['fwd_minus_mu_star'] * 100, best_net_time_pct=b['net_time'] * 100, best_z=b['z'], best_z_vn=b['z_vn'],
             best_symbols_pos=b['symbols_pos'], max_z_any_H=d['z'].max())
    for H in (4, 16, 64):
        x = d[d.H == H].iloc[0]
        r[f'fwd_pct_H{H}'] = x['fwd_pct']; r[f'z_H{H}'] = x['z']
    rows.append(r)
t = pd.DataFrame(rows).sort_values(['tf', 'best_fwd_minus_mu_pct'], ascending=[True, False])
t.to_csv('strategy_tf_summary.csv', index=False)
pd.set_option('display.width', 260); pd.set_option('display.max_rows', 100)
print(t[['strategy', 'tf', 'approx', 'previously_examined', 'n_H4', 'best_H', 'best_fwd_pct', 'best_mu_star_pct', 'best_fwd_minus_mu_pct', 'best_net_time_pct', 'best_z', 'best_z_vn', 'fwd_pct_H4', 'fwd_pct_H16', 'fwd_pct_H64']].round(3).to_string(index=False))
# cross-TF consistency (descriptive): same strategy/H at 15m vs 30m
f = g[g.family_candidate]
m = f[f.tf == '15m'][['strategy', 'H', 'fwd_minus_mu_star', 'z']].merge(f[f.tf == '30m'][['strategy', 'H', 'fwd_minus_mu_star', 'z']], on=['strategy', 'H'], suffixes=('_15', '_30'))
print('\n15m vs 30m, same strategy & H, n>=100 both: cells', len(m), ' spearman z:', round(spearmanr(m.z_15, m.z_30)[0], 3),
      ' spearman fwd-mu*:', round(spearmanr(m.fwd_minus_mu_star_15, m.fwd_minus_mu_star_30)[0], 3))
print('gross fwd>0 share (n>=100):', round((f.fwd > 0).mean(), 3), ' of', len(f), '; net_time>0:', int((f.net_time > 0).sum()))
print('long-only vs short-only gross (n>=100, H=16): mean fwd_long', round(f[f.H == 16].fwd_long.mean() * 100, 4), 'pct; mean fwd_short', round(f[f.H == 16].fwd_short.mean() * 100, 4), 'pct')
