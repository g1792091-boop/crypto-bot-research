"""Descriptive diagnostic (IS only): why is z_vn so dispersed across strategies?
(1) lag-1..3 autocorrelation of open-to-open log returns per coin/TF (IS signal window);
(2) per cell, 'momentum-ness' of the signal = mean over signals of d * sign(close[t]-close[t-H]);
    Spearman correlation with z_vn and with z (raw)."""
import sys, numpy as np, pandas as pd
from scipy.stats import spearmanr
sys.path.insert(0, '.')
import sweep_lib as L
g = pd.read_csv('gate_cells.csv')
rows = []; acs = []
for tf in ('1h', '4h', '1d'):
    panel = L.load_panel(tf, 'is')
    sigs = L.load_signals(f'out/signals_is_{tf}.npz')
    for c, df in panel.items():
        lo, hi = L.signal_window(df, tf, 'is', 0)
        o = df['open'].to_numpy(float); lr = np.diff(np.log(o))[lo:hi]
        acs.append(dict(tf=tf, coin=c, **{f'ac{k}': float(np.corrcoef(lr[:-k], lr[k:])[0, 1]) for k in (1, 2, 3)}))
    for H in L.HS:
        for name in L.NAMES:
            num = den = 0
            for c, df in panel.items():
                lo, hi = L.signal_window(df, tf, 'is', H)
                cl = df['close'].to_numpy(float)
                d = sigs[name][c][lo:hi].astype(float)
                t = np.arange(lo, hi)
                past = np.sign(cl[t] - cl[np.maximum(t - H, 0)])
                num += float((d * past)[d != 0].sum()); den += int((d != 0).sum())
            rows.append(dict(strategy=name, tf=tf, H=H, momentum=num / den if den else np.nan))
m = g.merge(pd.DataFrame(rows), on=['strategy', 'tf', 'H'])
m = m[m.family_candidate]
ac = pd.DataFrame(acs)
print(ac.round(4).to_string(index=False))
out = []
for (tf, H), d in m.groupby(['tf', 'H']):
    out.append(dict(tf=tf, H=H, cells=len(d), rho_mom_zvn=spearmanr(d.momentum, d.z_vn)[0],
                    rho_mom_z=spearmanr(d.momentum, d.z)[0], rho_z_zvn=spearmanr(d.z, d.z_vn)[0],
                    zvn_sd=d.z_vn.std(), z_sd=d.z.std()))
print(pd.DataFrame(out).round(3).to_string(index=False))
m[['strategy', 'tf', 'H', 'n', 'momentum', 'z', 'z_vn', 'fwd_pct']].sort_values(['tf', 'H', 'z_vn']).to_csv('out/diag_vn_momentum.csv', index=False)
ac.to_csv('out/diag_autocorr_is.csv', index=False)
print(m[(m.H == 4) & (m.tf == '1h')][['strategy', 'momentum', 'z', 'z_vn']].sort_values('z_vn').round(2).to_string(index=False))
