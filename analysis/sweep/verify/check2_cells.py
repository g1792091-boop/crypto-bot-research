import sys, time, numpy as np, pandas as pd
sys.path.insert(0, '.')
import indep as I
SW = I.SW
cb = pd.read_csv(SW + '/combine/out/gate_all_is_applied.csv')
fam = cb[cb.in_family]
rng = np.random.default_rng(424242)
pick = []
for tf in ['5m','15m','30m','1h','4h','1d']:
    sub = fam[fam.tf == tf]
    idx = rng.choice(len(sub), size=2, replace=False)
    pick += [tuple(sub.iloc[i][['strategy','tf','H']]) for i in idx]
extra = [('N13_3OUTSIDE','4h',64), ('N13_3OUTSIDE','4h',16), ('DOGE_L','1h',64), ('V45_AMB','1h',16),
         ('V45_AMB','15m',64), ('N04_ST_KLINGER','1d',64), ('V45_AMB','1d',64)]
cells = pick + [e for e in extra if e not in pick]
print('cells:', cells, flush=True)
tfs = sorted(set(c[1] for c in cells), key=lambda t: I.TFM[t])
rows = []
for tf in tfs:
    t0 = time.time()
    panel = {c: I.myload(c, tf) for c in I.COINS}
    need5 = any(c[0] == 'V45_AMB' and c[1] == tf for c in cells)
    d5 = {c: I.myload(c, '5m') for c in I.COINS} if need5 else {}
    for name in sorted(set(c[0] for c in cells if c[1] == tf)):
        sigs = {c: I.my_signals(name, panel[c], tf, d5.get(c)) for c in I.COINS}
        for H in sorted(c[2] for c in cells if c[0] == name and c[1] == tf):
            r = I.cell(name, tf, int(H), panel, sigs, extra_B=2000)
            rows.append(r)
            ref = cb[(cb.strategy == name) & (cb.tf == tf) & (cb.H == H)].iloc[0]
            print(f"{name:16s} {tf:>3s} H{H:<3d} n {r['n']}/{ref.n}  fwd {r['fwd']:.6e}/{ref.fwd:.6e}  z {r.get('z',np.nan):.4f}/{ref.z:.4f}  "
                  f"z_vn {r.get('z_vn',np.nan):.4f}/{ref.z_vn:.4f}  mu* {r['mu_star']:.6e}/{ref.mu_star:.6e}  z_own(B2000) {r.get('z_ownnull',np.nan):.3f} "
                  f"p_emp_own {r.get('p_emp_ownnull',np.nan):.4f}  sym {r['symbols_pos']}/{ref.symbols_pos}", flush=True)
    print(f'-- {tf} done {time.time()-t0:.0f}s', flush=True)
out = pd.DataFrame(rows)
m = out.merge(cb, on=['strategy','tf','H'], suffixes=('_v','_h'))
for k in ['n','fwd','z','z_vn','mu_star','E_abs_r','cost_H','symbols_pos','n_coins_ge10'] + [f'fwd_{c}' for c in I.COINS] + [f'n_{c}' for c in I.COINS]:
    a, b = m[k+'_v'].astype(float), m[k+'_h'].astype(float)
    both_nan = a.isna() & b.isna()
    diff = np.where(both_nan, 0, np.abs(a-b))
    print(f'{k:14s} max abs diff {np.nanmax(diff):.3e}  nan-mismatch {int((a.isna()!=b.isna()).sum())}')
m.to_csv('out/check2_cells.csv', index=False)
