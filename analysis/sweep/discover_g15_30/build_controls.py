"""controls.csv = sweep_lib.controls() on the REAL IS panel (this agent's runs, data='is') for 15m/30m
+ the harness agent's synthetic-panel rows for 15m/30m (data='synthetic', copied, for comparison).
'gate' columns = full PREREG rule with the first Holm step at m=666; '_and_vn' = with A1."""
import pandas as pd, os
SW = os.path.dirname(os.path.abspath(__file__)); H = os.path.join(os.path.dirname(SW), 'harness', 'out')
parts = []
for tf in ('15m', '30m'):
    a = pd.read_csv(os.path.join(SW, 'out', f'controls_is_{tf}.csv')); a['source'] = 'discover_g15_30 run_controls.py --split is --reps 200 (seed 1)'
    b = pd.read_csv(os.path.join(H, f'controls_synthetic_{tf}.csv')); b['source'] = 'harness/out (synthetic panel, harness agent)'
    parts += [a, b]
c = pd.concat(parts, ignore_index=True)
front = ['data', 'source', 'tf', 'H', 'kind', 'n_target', 'reps']
c = c[front + [x for x in c.columns if x not in front]]
c.to_csv(os.path.join(SW, 'controls.csv'), index=False)
# compact summary
s = c.groupby(['data', 'tf', 'kind']).agg(null_rate_p05=('null_rate_p05', 'mean'), null_z_sd_min=('null_z_sd', 'min'),
    null_z_sd_max=('null_z_sd', 'max'), raw_gate_false_pass_max=('null_rate_gate', 'max'),
    raw_gate_false_pass_mean=('null_rate_gate', 'mean'), vn_null_rate_p05=('vn_null_rate_p05', 'mean'),
    vn_z_sd_min=('vn_null_z_sd', 'min'), vn_z_sd_max=('vn_null_z_sd', 'max'),
    A1_gate_false_pass_max=('null_rate_gate_and_vn', 'max'), reps=('reps', 'first'), rows=('H', 'size')).reset_index()
s.to_csv(os.path.join(SW, 'controls_summary.csv'), index=False)
pd.set_option('display.width', 250)
print(s.round(3).to_string(index=False))
# false-pass counts (reps x rate)
c['fp_raw'] = (c['null_rate_gate'] * c['reps']).round().astype(int); c['fp_A1'] = (c['null_rate_gate_and_vn'] * c['reps']).round().astype(int)
print(c.groupby(['data', 'tf'])[['fp_raw', 'fp_A1', 'reps']].sum())
p = c[c.data == 'is'].pivot_table(index=['tf', 'H', 'n_target'], columns='kind', values='power_gate_and_vn')
print('\nplanted 1.5 x mu* power (gate incl. A1, m=666), real IS panel:'); print(p.round(3).to_string())
m = c[(c.data == 'is') & (c.kind == 'iid') & (c.n_target == 2000)][['tf', 'H', 'mde80_over_mu']]
m['n_req_iid_real'] = (2000 * m['mde80_over_mu'] ** 2).round()
mb = c[(c.data == 'is') & (c.kind == 'burst4') & (c.n_target == 2000)][['tf', 'H', 'mde80_over_mu']].rename(columns={'mde80_over_mu': 'mde_b'})
m = m.merge(mb, on=['tf', 'H']); m['n_req_burst4_real'] = (2000 * m['mde_b'] ** 2).round()
ms = c[(c.data == 'synthetic') & (c.kind == 'iid') & (c.n_target == 2000)][['tf', 'H', 'mde80_over_mu']].rename(columns={'mde80_over_mu': 'mde_syn'})
m = m.merge(ms, on=['tf', 'H']); m['n_req_iid_synth'] = (2000 * m['mde_syn'] ** 2).round()
m.to_csv(os.path.join(SW, 'controls_n_required_real_is.csv'), index=False)
print(m.round(3).to_string(index=False))
