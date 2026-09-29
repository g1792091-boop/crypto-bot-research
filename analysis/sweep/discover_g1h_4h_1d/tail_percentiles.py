"""DESCRIPTIVE: where does each tail-checked cell's OBSERVED z / z_vn / fwd sit inside its own
timing-preserving random-sign zero-edge distribution (500 reps, out/tail_check_reps_<tf>.csv)?
p_rs = (1 + #{rep >= observed}) / (reps + 1).  Not a PREREG statistic; changes no decision."""
import pandas as pd
g = pd.read_csv('gate_cells.csv')
rows = []
for tf in ('1h', '4h', '1d'):
    r = pd.read_csv(f'out/tail_check_reps_{tf}.csv')
    for (s, H), d in r.groupby(['strategy', 'H']):
        o = g[(g.strategy == s) & (g.tf == tf) & (g.H == H)].iloc[0]
        k = len(d)
        rows.append(dict(strategy=s, tf=tf, H=H, n=int(o.n), reps=k, z_obs=o.z, p_normal=o.p, p_rs_z=(1 + (d.z >= o.z).sum()) / (k + 1),
                         z_vn_obs=o.z_vn, p_vn_normal=o.p_vn, p_rs_zvn=(1 + (d.z_vn >= o.z_vn).sum()) / (k + 1),
                         fwd_pct_obs=o.fwd * 100, mu_star_pct=o.mu_star * 100, p_rs_fwd=(1 + (d.fwd >= o.fwd).sum()) / (k + 1),
                         p_emp_all=o.p_emp_all, rs_z_sd=d.z.std(), rs_zvn_sd=d.z_vn.std()))
t = pd.DataFrame(rows).sort_values('p_rs_z')
t.to_csv('out/tail_check_percentiles.csv', index=False)
pd.set_option('display.width', 250)
print(t.round(4).to_string(index=False))
