"""Descriptive robustness of the two most-cited near-miss cells, IS ONLY (nothing was carried/confirmed)."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, '.')
import indep as I
def run(name, tf, H):
    panel = {c: I.myload(c, tf) for c in I.COINS}
    sigs = {c: I.my_signals(name, panel[c], tf) for c in I.COINS}
    base = I.cell(name, tf, H, panel, sigs)
    print(f"\n=== {name} {tf} H{H}: n={base['n']} fwd={100*base['fwd']:.3f}% mu*={100*base['mu_star']:.3f}% z={base['z']:.2f} z_vn={base['z_vn']:.2f}")
    # per-signal list
    recs = []
    for c, df in panel.items():
        lo, hi = I.window(df, tf, H); o = df.open.to_numpy(float)
        for t in np.flatnonzero(sigs[c][lo:hi]) + lo:
            d = sigs[c][t]; recs.append(dict(coin=c, ts=df.ts.iloc[t], d=d, r=d*(o[t+1+H]/o[t+1]-1)))
    R = pd.DataFrame(recs); R['month'] = R.ts.dt.strftime('%Y-%m')
    print(' per-coin fwd%:', {c: round(100*g.r.mean(),2) for c, g in R.groupby('coin')}, ' n:', R.coin.value_counts().to_dict())
    # leave one coin out (full null recomputed)
    for c in I.COINS:
        p2 = {k: v for k, v in panel.items() if k != c}; s2 = {k: v for k, v in sigs.items() if k != c}
        r = I.cell(name, tf, H, p2, s2)
        print(f'  drop {c:8s}: n={r["n"]:4d} fwd={100*r["fwd"]:.3f}% fwd/mu*={r["fwd"]/r["mu_star"]:.2f} z={r["z"]:.2f} z_vn={r["z_vn"]:.2f}')
    mb = R.groupby('month').r.sum().sort_values(ascending=False)
    print(' best months (sum of signed r):', mb.head(3).round(3).to_dict())
    for k in (1, 3):
        drop = set(mb.index[:k]); x = R[~R.month.isin(drop)]
        print(f'  excl best {k} month(s): n={len(x)} fwd={100*x.r.mean():.3f}%  fwd/mu*={x.r.mean()/base["mu_star"]:.2f}')
    mid = pd.Timestamp('2023-04-01', tz='UTC')
    for lab, x in [('IS first half (<2023-04)', R[R.ts < mid]), ('IS second half (>=2023-04)', R[R.ts >= mid])]:
        print(f'  {lab}: n={len(x)} fwd={100*x.r.mean():.3f}%  fwd/mu*={x.r.mean()/base["mu_star"]:.2f}')
    yr = R.groupby(R.ts.dt.year).r.agg(['size', 'mean'])
    print(' by year:', {int(y): (int(a), round(100*b, 2)) for y, (a, b) in yr.iterrows()})
    top10 = R.r.sort_values(ascending=False).head(10).sum() / R.r.sum()
    print(f'  share of total from top-10 signals: {top10:.2f};  median signal r: {100*R.r.median():.3f}%')
    for extra in (0.0002*2, 0.0005*2):
        print(f'  net after cost_H + extra {100*extra:.2f}% RT: {100*(base["fwd"]-base["cost_H"]-extra):.3f}%  (vs hurdle margin {100*(base["fwd"]-base["mu_star"]-extra):.3f}%)')
    # entry at close[t+1] instead of open[t+1] (one bar later fill) -> r from close[t+1] to open[t+1+H]
    tot = []; 
    for c, df in panel.items():
        lo, hi = I.window(df, tf, H); o = df.open.to_numpy(float); cl = df.close.to_numpy(float)
        for t in np.flatnonzero(sigs[c][lo:hi]) + lo:
            tot.append(sigs[c][t]*(o[t+1+H]/cl[t+1]-1))
    print(f'  delayed fill (close of t+1, i.e. one bar late): fwd={100*np.mean(tot):.3f}%  fwd/mu*={np.mean(tot)/base["mu_star"]:.2f}')
run('N13_3OUTSIDE', '4h', 16)
run('N13_3OUTSIDE', '4h', 64)
run('DOGE_L', '1h', 64)
