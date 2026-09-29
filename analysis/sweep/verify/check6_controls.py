"""Independent controls on the REAL IS panel (own code; verifier).
Signal kinds (random sign => zero edge by construction):
  iid       : Bernoulli(q) on admissible bars
  voltimed  : prob ~ (|close-to-close return| / trailing median)^2, capped
  realtime  : timing of a real strategy (vendor fn), signs randomised
Planted: r' = r + d*delta at signal bars with delta = 1.0*mu* and 1.5*mu* (edge travels with bar, not with shift).
Gate (m=528): z > z_crit and z_vn > z_crit and fwd >= mu* and symbols rule.  Reports z sd, rates, power."""
import sys, time, math, numpy as np, pandas as pd
from scipy.stats import norm
sys.path.insert(0, '.')
import indep as I
TF = sys.argv[1]; REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 200
ZC = norm.isf(0.05/528)
panel = {c: I.myload(c, TF) for c in I.COINS}
NTGT = {'1h': 2500, '4h': 1200, '1d': 230, '30m': 4800, '15m': 9400, '5m': 28000}[TF]
real_names = ['S2_ST_ROC', 'N13_3OUTSIDE', 'N23_HA_ST']
realsig = {nm: {c: I.my_signals(nm, panel[c], TF) for c in I.COINS} for nm in real_names}
rows = []
for H in (4, 16, 64):
    segs = {}
    for c, df in panel.items():
        lo, hi = I.window(df, TF, H); N = hi - lo
        if N < 2*H+4: continue
        o = df.open.to_numpy(float); t = np.arange(lo, hi)
        r = o[t+1+H]/o[t+1] - 1
        lr = np.diff(np.log(o)); cum = np.concatenate([[0], np.cumsum(lr**2)])
        rv = np.sqrt(cum[t+1+H] - cum[t+1])
        cl = df.close.to_numpy(float); ar = np.abs(np.diff(np.log(cl), prepend=np.log(cl[0])))
        med = pd.Series(ar).rolling(max(50, int(30*1440/I.TFM[TF]) if TF != '1d' else 60), min_periods=20).median().to_numpy()
        vol_w = np.nan_to_num((ar/np.where(med > 0, med, np.nan))**2, nan=0.0)[lo:hi]
        segs[c] = dict(N=N, r=r, rv=rv, volw=vol_w, lo=lo, hi=hi)
    n_min = min(s['N'] for s in segs.values())
    Eabs = float(np.mean(np.abs(np.concatenate([s['r'] for s in segs.values()]))))
    mu = 0.0014 + 0.0001*H*I.TFM[TF]/480 + 0.091*Eabs
    shifts = np.random.default_rng([20260929, I.TFM[TF], H, H]).integers(H+1, n_min-H-1, size=600, endpoint=True)
    Ntot = sum(s['N'] for s in segs.values())
    def stat(dd, delta=0.0):
        obs = 0.0; obsv = 0.0; n = 0; nv = np.zeros(len(shifts)); nvv = np.zeros(len(shifts)); per = []
        for c, s in segs.items():
            d = dd[c]; u = np.flatnonzero(d)
            if len(u) == 0: per.append((0, 0.0)); continue
            w = d[u].astype(float)
            r = s['r'].copy(); r[u] = r[u] + w*delta
            rn = np.where(s['rv'] > 0, np.log1p(r)/np.where(s['rv'] > 0, s['rv'], 1), 0.0)
            obs += float(w @ r[u]); obsv += float(w @ rn[u]); n += len(u)
            pos = (u[None, :] + shifts[:, None]) % s['N']
            nv += (r[pos]*w).sum(1); nvv += (rn[pos]*w).sum(1)
            per.append((len(u), float(w @ r[u])/len(u)))
        fwd = obs/n; nv /= n; nvv /= n
        z = (fwd - nv.mean())/nv.std(ddof=1); zv = (obsv/n - nvv.mean())/nvv.std(ddof=1)
        n10 = [m for k, m in per if k >= 10]; sp = sum(1 for m in n10 if m > 0)
        symok = sp >= 4 or (len(n10) >= 1 and sp >= 0.6*len(n10))
        return fwd, z, zv, symok, n
    rng = np.random.default_rng(1000 + H)
    for kind in ['iid', 'voltimed'] + [f'real:{nm}' for nm in real_names]:
        for rep in range(REPS):
            dd = {}
            for c, s in segs.items():
                if kind == 'iid':
                    m = rng.random(s['N']) < NTGT/Ntot
                elif kind == 'voltimed':
                    p = s['volw']; p = np.minimum(p/ p.mean() * NTGT/Ntot, 1.0); m = rng.random(s['N']) < p
                else:
                    m = realsig[kind.split(':')[1]][c][s['lo']:s['hi']] != 0
                dd[c] = np.where(m, rng.choice([-1, 1], size=s['N']), 0).astype(np.int8)
            if sum(np.abs(v).sum() for v in dd.values()) < 20: continue
            for mult in (0.0, 1.0, 1.5):
                fwd, z, zv, symok, n = stat(dd, mult*mu)
                rows.append(dict(tf=TF, H=H, kind=kind, rep=rep, mult=mult, n=n, fwd=fwd, mu=mu, z=z, z_vn=zv,
                                 pass_spec=bool(z > ZC and fwd >= mu and symok and n >= 100),
                                 pass_a1=bool(z > ZC and zv > ZC and fwd >= mu and symok and n >= 100),
                                 nominal=bool(z > 1.645)))
    print(TF, H, 'done', flush=True)
out = pd.DataFrame(rows); out.to_csv(f'out/check6_controls_{TF}.csv', index=False)
g = out.groupby(['H', 'kind', 'mult'])
summ = g.agg(reps=('z', 'size'), n_med=('n', 'median'), z_mean=('z', 'mean'), z_sd=('z', 'std'), zvn_sd=('z_vn', 'std'),
             p05=('nominal', 'mean'), pass_spec=('pass_spec', 'mean'), pass_a1=('pass_a1', 'mean')).reset_index()
pd.set_option('display.width', 200)
print(summ.round(3).to_string(index=False))
summ.to_csv(f'out/check6_controls_summary_{TF}.csv', index=False)
