"""Independent re-implementation (verifier). Uses ONLY the original vendor strategy functions
(byte-identical to /home/user/crypto-bot-research), NOT sweep_lib. Own loader, windows, HTF mapping,
DOGE scaling, forward returns, hurdle and shift null."""
import sys, math, numpy as np, pandas as pd
SW = '/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep'
sys.path.insert(0, SW + '/verify/lib/vendor')
import strategies as S, ports12, doge_strategy as ds  # noqa
COINS = ['BTCUSD','ETHUSD','SOLUSD','XRPUSD','DOGEUSD','LTCUSD','BCHUSD']
TFM = {'5m':5,'15m':15,'30m':30,'1h':60,'2h':120,'4h':240,'1d':1440,'1w':10080}
WIN = {'is': ('2021-08-01','2024-07-01'), 'oos': ('2024-07-01','2025-08-07'), 'final': ('2025-08-07','2026-09-30')}
HTF = {'5m':'15m','15m':'1h','30m':'2h','1h':'4h','4h':'1d','1d':'1w'}

def myload(sym, tf, split='is'):
    assert split == 'is', 'verifier discipline: IS only'
    d = pd.read_csv(f"{SW}/data/is/{sym.lower()}-{tf}.csv")
    d['ts'] = pd.to_datetime(d['ts'], utc=True)
    d = d[d.ts < pd.Timestamp(WIN[split][1], tz='UTC')].sort_values('ts').reset_index(drop=True)
    return d

def my_resample_from_5m(d5, htf):
    """own resampler: floor-based groupby; weekly = Monday-start bins"""
    ts = d5.ts
    if htf == '1w':
        day = ts.dt.floor('1D')
        key = day - pd.to_timedelta(day.dt.weekday, unit='D')
    else:
        key = ts.dt.floor(f"{TFM[htf]}min")
    g = d5.groupby(key.values)
    out = pd.DataFrame({'open': g.open.first(), 'high': g.high.max(), 'low': g.low.min(),
                        'close': g.close.last(), 'volume': g.volume.sum()})
    out.index.name = 'ts'
    out = out.reset_index()
    out['ts'] = pd.to_datetime(out.ts, utc=True)
    return out

def warm(tf):
    return 200 if tf == '1d' else max(300, math.ceil(30*1440/TFM[tf]))

def tobool(x, n):
    a = np.asarray(x.to_numpy() if hasattr(x, 'to_numpy') else x)
    if a.dtype == object: a = pd.Series(a).fillna(False).astype(bool).to_numpy()
    if a.dtype != bool: a = np.nan_to_num(a.astype(float)) != 0
    assert a.shape == (n,)
    return a

def my_signals(name, df, tf, d5=None):
    n = len(df)
    if name in S.CANDIDATES_15M and name not in ('OBV_S','OBV_B'):
        L, Sh = S.CANDIDATES_15M[name](df)
    elif name in ports12.PORTS12:
        p = ports12.PORTS12[name](df); L, Sh = p['L'], p['S']
    elif name == 'V39_ALL': L, Sh = S.v39_all(df)
    elif name == 'OBV_S': L, Sh = S.obv_s(df)
    elif name == 'OBV_B': L, Sh = S.obv_b(df)
    elif name == 'V45_AMB':
        htf = HTF[tf]
        dh = my_resample_from_5m(d5, htf)
        # keep only HTF bins that are complete in time before the chart data end (a bin containing
        # the last chart bar is only used after its close, which lies beyond the data anyway)
        fake = dh.copy()
        fake['ts'] = dh.ts + pd.Timedelta(minutes=TFM[htf]) - pd.Timedelta(minutes=15)
        L, Sh = S.v45_exact_amb(df, fake)      # original vendor fn; its '+15m' now yields true close
    elif name in ('DOGE_L','DOGE_S'):
        ratio = TFM[tf]/5
        p = dict(ds.DEFAULT)
        for k in ['ema_fast','ema_slow','ema_trend','ema_short','stoch_rsi_len','stoch_len','k_smooth','d_smooth','rsi_len','chop_len']:
            if ratio > 1: p[k] = max(2, int(math.floor(ds.DEFAULT[k]/ratio + 0.5)))
        dd = df.set_index(pd.DatetimeIndex(df.ts))[['open','high','low','close','volume']]
        ind = ds.compute_indicators(dd, p); sg = ds.compute_signals(dd, ind, p)
        if name == 'DOGE_L': L, Sh = sg['long_entry'].to_numpy(), np.zeros(n, bool)
        else: L, Sh = np.zeros(n, bool), sg['short_entry'].to_numpy()
    else:
        raise KeyError(name)
    L = tobool(L, n); Sh = tobool(Sh, n) & ~L
    return L.astype(int) - Sh.astype(int)

def window(df, tf, H, split='is'):
    s, e = WIN[split]
    ts = df.ts
    n_in = int((ts < pd.Timestamp(e, tz='UTC')).sum())
    i0 = int((ts < pd.Timestamp(s, tz='UTC')).sum())
    lo = max(i0, warm(tf)); hi = n_in - 1 - H
    return lo, max(lo, hi)

def cell(name, tf, H, panel, sigs, B=600, extra_B=0, extra_seed=7):
    o = {c: panel[c].open.to_numpy(float) for c in panel}
    segs = {}
    for c in panel:
        lo, hi = window(panel[c], tf, H)
        N = hi - lo
        if N < 2*H + 4: continue
        t = np.arange(lo, hi)
        r = o[c][t+1+H]/o[c][t+1] - 1
        lo_ = np.log(o[c]); lr = np.diff(lo_)
        rv = np.array([math.sqrt(float(np.sum(lr[i+1:i+1+H]**2))) for i in t]) if H*N < 3e7 else None
        segs[c] = dict(lo=lo, hi=hi, N=N, r=r, d=sigs[c][lo:hi].astype(float), rv=rv)
    n_min = min(s['N'] for s in segs.values())
    allr = np.concatenate([s['r'] for s in segs.values()])
    Eabs = float(np.mean(np.abs(allr)))
    cost = 0.0014 + 0.0001*H*TFM[tf]/480
    mu = cost + 0.091*Eabs
    n = int(sum(np.abs(s['d']).sum() for s in segs.values()))
    tot = sum(float(s['d'] @ s['r']) for s in segs.values())
    fwd = tot/n if n else np.nan
    per = {c: (int(np.abs(s['d']).sum()), float(s['d'] @ s['r'])/max(1, np.abs(s['d']).sum())) for c, s in segs.items()}
    def nullstats(shifts):
        vals = np.zeros(len(shifts)); valsvn = np.zeros(len(shifts))
        for c, s in segs.items():
            u = np.flatnonzero(s['d']); w = s['d'][u]
            if len(u) == 0: continue
            rn = None
            if s['rv'] is not None:
                rn = np.where(s['rv'] > 0, np.log1p(s['r'])/np.where(s['rv']>0, s['rv'], 1), 0.0)
            for j0 in range(0, len(shifts), 50):
                sh = shifts[j0:j0+50]
                pos = (u[None, :] + sh[:, None]) % s['N']   # roll of d by k == d[u] meets r[u+k]
                vals[j0:j0+50] += (s['r'][pos]*w).sum(1)
                if rn is not None: valsvn[j0:j0+50] += (rn[pos]*w).sum(1)
        return vals/n, valsvn/n
    out = dict(strategy=name, tf=tf, H=H, n=n, fwd=fwd, E_abs_r=Eabs, cost_H=cost, mu_star=mu, n_min=n_min,
               symbols_pos=sum(1 for c,(k,m) in per.items() if k>=10 and m>0), n_coins_ge10=sum(1 for c,(k,m) in per.items() if k>=10))
    for c in COINS:
        out[f'n_{c}'] = per.get(c,(0,np.nan))[0]; out[f'fwd_{c}'] = per.get(c,(0,np.nan))[1] if per.get(c,(0,0))[0] else np.nan
    if n:
        rng = np.random.default_rng([20260929, TFM[tf], H, H])
        shifts = rng.integers(H+1, n_min-H-1, size=B, endpoint=True)
        nv, nvn = nullstats(shifts)
        out.update(z=(fwd-nv.mean())/nv.std(ddof=1))
        if all(s['rv'] is not None for s in segs.values()):
            fvn = sum(float(s['d'] @ np.where(s['rv']>0, np.log1p(s['r'])/np.where(s['rv']>0,s['rv'],1), 0.0)) for s in segs.values())/n
            out.update(z_vn=(fvn-nvn.mean())/nvn.std(ddof=1), fwd_vn=fvn)
        if extra_B:
            rng2 = np.random.default_rng(extra_seed)
            sh2 = rng2.integers(H+1, n_min-H-1, size=extra_B, endpoint=True)
            nv2, _ = nullstats(sh2)
            out.update(z_ownnull=(fwd-nv2.mean())/nv2.std(ddof=1), p_emp_ownnull=(1+(nv2>=fwd).sum())/(extra_B+1))
    return out
