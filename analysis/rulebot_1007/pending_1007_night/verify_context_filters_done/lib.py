import numpy as np, pandas as pd
from scipy import stats
V = '/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify3/'
H = 3600000

def load(kinds=('strategy',), tfs=('15m', '30m')):
    D = pd.read_pickle(V + 'sig.pkl')
    D = D[D.kind.isin(kinds) & D.timeframe.isin(tfs) & D.R.notna() & D.regime.notna()].copy()
    s = D.side.values.astype(float)
    D['long'] = s > 0
    h = D.kst_hour.values
    D['europe'] = (h >= 16) & (h <= 21)
    D['di_with'] = s * (D.di_plus.astype(float) - D.di_minus.astype(float)) > 0
    D['ema_s'] = s * D.ema20_dist_atr.astype(float)
    D['box_s'] = np.where(s > 0, D.box_pos.astype(float), 1 - D.box_pos.astype(float))
    D['htf_s'] = np.where(s > 0, D.htf_box_pos.astype(float), 1 - D.htf_box_pos.astype(float))
    D['rng_s'] = np.where(s > 0, D.range_pct.astype(float), 1 - D.range_pct.astype(float))
    cuts = {'15m': (0.5, 0.7), '30m': (0.74, 1.0)}
    D['stop_b'] = 'mid'
    for tf, (a, b) in cuts.items():
        m = D.timeframe == tf
        D.loc[m & (D.stop_pct < a), 'stop_b'] = 'tight'; D.loc[m & (D.stop_pct >= b), 'stop_b'] = 'wide'
    return D

def clus(bc, mode):
    if mode == 'day': return (bc + 9 * H) // (24 * H)
    return bc // int(mode * H)

def diff_run(y, inb, cl):
    u, inv = np.unique(cl, return_inverse=True); G = len(u)
    ni = np.bincount(inv, inb, G); no = np.bincount(inv, ~inb, G)
    si = np.bincount(inv, np.where(inb, y, 0), G); so = np.bincount(inv, np.where(~inb, y, 0), G)
    mi, mo = si.sum() / ni.sum(), so.sum() / no.sum()
    inf = (si - mi * ni) / ni.sum() - (so - mo * no) / no.sum()
    return mi - mo, G / max(G - 1, 1) * np.sum(inf ** 2), G

def contrast(X, mask, mode=2, y='R', minr=5):
    """n-weighted within-run difference (mask vs rest); cluster SE by time block; t with df=sum(G-1)."""
    ds, ws, vs, df, nin = [], [], [], 0, 0
    for run, g in X.groupby('run'):
        m = mask.loc[g.index].values.astype(bool); yy = g[y].values.astype(float)
        if m.sum() < minr or (~m).sum() < minr: continue
        d, v, G = diff_run(yy, m, clus(g.bar_close.values, mode))
        ds.append(d); ws.append(len(g)); vs.append(v); df += G - 1; nin += m.sum()
    if not ds: return dict(d=np.nan, se=np.nan, p=np.nan, n_in=0, df=0)
    w = np.array(ws, float) / sum(ws); d = float(np.dot(w, ds)); se = float(np.sqrt(np.dot(w ** 2, vs)))
    t = d / se if se > 0 else np.nan
    return dict(d=round(d, 3), se=round(se, 3), p=round(float(2 * stats.t.sf(abs(t), max(df, 1))), 4), n_in=int(nin), df=df)

def bh(p):
    p = np.asarray(p, float); n = len(p)
    if n == 0: return p
    o = np.argsort(p); q = p[o] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]; out = np.empty(n); out[o] = np.minimum(q, 1); return out
