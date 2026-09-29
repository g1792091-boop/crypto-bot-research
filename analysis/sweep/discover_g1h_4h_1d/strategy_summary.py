"""Per strategy x TF: n (H=4), best cell by fwd - mu*, its z / z_vn, and all-H gross fwd; descriptive only.
Also cross-TF consistency (same strategy & H) and the family-size bound needed for any of this group's
cells to be rejected by Holm (indicative; Holm itself is the Combine agent's job)."""
import os
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
g = pd.read_csv(os.path.join(HERE, 'gate_cells.csv'))
rows = []
for (s, tf), d in g.groupby(['strategy', 'tf']):
    d = d.sort_values('H')
    b = d.loc[d['fwd_minus_mu_star'].idxmax()] if d['fwd_minus_mu_star'].notna().any() else d.iloc[0]
    r = dict(strategy=s, tf=tf, group=b['group'], approx=b['approx'], previously_examined=b['previously_examined'],
             n_H4=int(d[d.H == 4]['n'].iloc[0]), best_H=int(b['H']), best_n=int(b['n']), best_fwd_pct=b['fwd_pct'],
             best_mu_star_pct=b['mu_star'] * 100, best_fwd_minus_mu_pct=b['fwd_minus_mu_star'] * 100,
             best_net_time_pct=b['net_time'] * 100, best_z=b['z'], best_z_vn=b['z_vn'],
             best_symbols_pos=b['symbols_pos'], max_z_any_H=d['z'].max(), in_family_any=bool(d['family_candidate'].any()))
    for H in (4, 16, 64):
        x = d[d.H == H].iloc[0]
        r[f'fwd_pct_H{H}'] = x['fwd_pct']
        r[f'z_H{H}'] = x['z']
        r[f'z_vn_H{H}'] = x['z_vn']
    rows.append(r)
t = pd.DataFrame(rows)
t['tf_order'] = t.tf.map({'1h': 0, '4h': 1, '1d': 2})
t = t.sort_values(['tf_order', 'best_fwd_minus_mu_pct'], ascending=[True, False]).drop(columns='tf_order')
t.to_csv(os.path.join(HERE, 'strategy_tf_summary.csv'), index=False)
pd.set_option('display.width', 280)
pd.set_option('display.max_rows', 200)
print(t[['strategy', 'tf', 'approx', 'previously_examined', 'n_H4', 'best_H', 'best_n', 'best_fwd_pct', 'best_mu_star_pct',
         'best_fwd_minus_mu_pct', 'best_z', 'best_z_vn', 'fwd_pct_H4', 'fwd_pct_H16', 'fwd_pct_H64']].round(3).to_string(index=False))

f = g[g.family_candidate]
print('\ncross-TF consistency, same strategy & H, n>=100 in both (Spearman):')
for a, b in (('1h', '4h'), ('4h', '1d'), ('1h', '1d')):
    m = f[f.tf == a][['strategy', 'H', 'fwd_minus_mu_star', 'z', 'z_vn']].merge(
        f[f.tf == b][['strategy', 'H', 'fwd_minus_mu_star', 'z', 'z_vn']], on=['strategy', 'H'], suffixes=('_a', '_b'))
    print(f'  {a} vs {b}: cells {len(m)}  rho(z)={spearmanr(m.z_a, m.z_b)[0]:.3f}  rho(z_vn)={spearmanr(m.z_vn_a, m.z_vn_b)[0]:.3f}'
          f'  [pooled over H; rho(fwd-mu*)={spearmanr(m.fwd_minus_mu_star_a, m.fwd_minus_mu_star_b)[0]:.3f} is confounded by H]')
    for H in (4, 16, 64):
        mh = m[m.H == H]
        print(f'      H={H}: cells {len(mh)}  rho(z)={spearmanr(mh.z_a, mh.z_b)[0]:.3f}  rho(z_vn)={spearmanr(mh.z_vn_a, mh.z_vn_b)[0]:.3f}'
              f'  rho(fwd-mu*)={spearmanr(mh.fwd_minus_mu_star_a, mh.fwd_minus_mu_star_b)[0]:.3f}')
print('gross fwd>0 share (n>=100):', round((f.fwd > 0).mean(), 3), 'of', len(f), '; net_time>0:', int((f.net_time > 0).sum()),
      '; fwd>=mu*:', int((f.fwd >= f.mu_star).sum()))
print('p<0.05:', int((f.p < 0.05).sum()), ' p_vn<0.05:', int((f.p_vn < 0.05).sum()), ' both:', int(((f.p < 0.05) & (f.p_vn < 0.05)).sum()),
      ' expected under null ~', round(0.05 * len(f), 1))
# Holm bound: a cell with p_i can be rejected only if (m - k) * p_i < alpha, where k = number of cells rejected
# before it (all with smaller p).  So the full-family m would have to be < k + alpha / p_i.
pmin = f.p.min()
pvmin = f.p_vn.min()
print(f'smallest in-family p = {pmin:.3g} ({f.loc[f.p.idxmin(), "strategy"]} {f.loc[f.p.idxmin(), "tf"]} H{int(f.loc[f.p.idxmin(), "H"])}); '
      f'alpha/p = {0.05 / pmin:.1f} -> Holm could reject it only if m - (#cells rejected before it) < {0.05 / pmin:.1f}')
print(f'smallest in-family p_vn = {pvmin:.3g}; this group alone has {len(f)} family cells')
both = f[['p', 'p_vn']].max(axis=1)
print(f'smallest in-family max(p, p_vn) = {both.min():.3g} ({f.loc[both.idxmin(), "strategy"]} {f.loc[both.idxmin(), "tf"]} H{int(f.loc[both.idxmin(), "H"])})')
