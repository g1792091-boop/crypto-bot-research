"""DESCRIPTIVE: joint tail of (z, z_vn, fwd>=mu*) under the timing-preserving random-sign null
(same episode definition as run_strategy_timing_controls.py: same-sign signals <= H bars apart)
for the cells whose random-sign z maxima exceeded the first Holm step.  Per-replicate values saved.
usage: python3 tail_check.py --tf 15m --cells S1_EMA_RSI_CHOP:16,N11_BREAKAWAY:4 --reps 500"""
import argparse, sys, os, time, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as L
ap = argparse.ArgumentParser(); ap.add_argument('--tf'); ap.add_argument('--cells'); ap.add_argument('--reps', type=int, default=500)
a = ap.parse_args()
thr_z = float(__import__('scipy.stats', fromlist=['norm']).norm.isf(L.ALPHA / 666))
panel = L.load_panel(a.tf, 'is'); sigs = L.load_signals(f'out/signals_is_{a.tf}.npz')
rng = np.random.default_rng([99, L.tf_minutes(a.tf)])
def episodes(seg, H):
    u = np.flatnonzero(seg); s = seg[u]; new = np.ones(len(u), bool)
    new[1:] = (np.diff(u) > H) | (s[1:] != s[:-1]); return np.cumsum(new) - 1
rows = []; t0 = time.time()
for spec in a.cells.split(','):
    name, H = spec.split(':'); H = int(H)
    prep = L._prep_returns(panel, a.tf, 'is', H); n_min = min(p['N'] for p in prep.values())
    shifts = L.gate_shifts(a.tf, H, n_min, L.B_GATE)
    mu_star = L.cost_h(H, a.tf) + L.HURDLE_K * float(np.mean(np.abs(np.concatenate([p['r'] for p in prep.values()]))))
    ep = {}
    for c, p in prep.items():
        seg = sigs[name][c][p['lo']:p['hi']].astype(np.int8); ep[c] = (np.flatnonzero(seg), episodes(seg, H))
    for b in range(a.reps):
        ds = {}
        for c, p in prep.items():
            d = np.zeros(len(panel[c]), np.int8); u, e = ep[c]
            if len(u):
                sg = rng.choice(np.array([-1, 1], np.int8), size=int(e.max()) + 1); d[p['lo'] + u] = sg[e]
            ds[c] = d
        st = L._cell_stats(ds, prep, shifts, None); per = st['per']
        n10 = [c for c, (k, m) in per.items() if k >= L.MIN_SIG_COIN]; sp = sum(1 for c in n10 if per[c][1] > 0)
        rows.append(dict(strategy=name, tf=a.tf, H=H, rep=b, n=st['n'], fwd=st['fwd'], mu_star=mu_star, z=st['z'], z_vn=st['z_vn'],
                         p=st['p'], p_vn=st['p_vn'], sym_ok=bool(L.sympos_ok([sp], [len(n10)])[0])))
    print(name, a.tf, H, f'{time.time() - t0:.0f}s', flush=True)
r = pd.DataFrame(rows)
r['holm1_raw'] = r.z > thr_z; r['holm1_vn'] = r.z_vn > thr_z
r['gate_spec_m666'] = r.holm1_raw & (r.fwd >= r.mu_star) & r.sym_ok & (r.n >= 100)
r['gate_A1_m666'] = r.gate_spec_m666 & r.holm1_vn
r.to_csv(f'out/tail_check_reps_{a.tf}.csv', index=False)
s = r.groupby(['strategy', 'tf', 'H']).agg(reps=('rep', 'size'), n=('n', 'first'), z_sd=('z', 'std'), zvn_sd=('z_vn', 'std'),
    z_max=('z', 'max'), zvn_max=('z_vn', 'max'), rate_z_gt_thr=('holm1_raw', 'mean'), rate_zvn_gt_thr=('holm1_vn', 'mean'),
    rate_both_gt_thr=('holm1_vn', lambda x: float((x & r.loc[x.index, 'holm1_raw']).mean())),
    rate_fwd_ge_mu=('fwd', lambda x: float((x >= r.loc[x.index, 'mu_star']).mean())),
    gate_spec=('gate_spec_m666', 'mean'), gate_A1=('gate_A1_m666', 'mean'),
    corr_z_zvn=('z', lambda x: float(np.corrcoef(x, r.loc[x.index, 'z_vn'])[0, 1]))).reset_index()
s.to_csv(f'out/tail_check_summary_{a.tf}.csv', index=False)
pd.set_option('display.width', 250); print(s.round(4).to_string(index=False)); print('thr_z', round(thr_z, 3))
