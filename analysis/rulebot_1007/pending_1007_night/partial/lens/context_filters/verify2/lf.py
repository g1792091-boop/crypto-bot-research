sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2')
from lib import *
D,cut=load(); D=D[D.timeframe.isin(['15m','30m'])].reset_index(drop=True)
ALL=list(FEAT.keys()); CH=[f for f in ALL if f not in ('sideb','coin','session')]
MOM=('ema_s','di_s','boxpos_s','rangepos_s','htfpos_s','adx_b'); CHNM=[f for f in CH if f not in MOM]
def X_of(x,feats,cols=None):
    P=[pd.get_dummies(x[f].fillna('NA').astype(str),prefix=f,dtype=float) for f in feats]
    P.append(pd.get_dummies(x.timeframe,prefix='tf',dtype=float)); P.append(pd.get_dummies(x.kind,prefix='k',dtype=float))
    X=pd.concat(P,axis=1)
    return X if cols is None else X.reindex(columns=cols,fill_value=0.0)
def fit(X,y,lam):
    mu=X.mean(0); Xc=X-mu; w=np.linalg.solve(Xc.T@Xc+lam*np.eye(X.shape[1]),Xc.T@(y-y.mean())); return w,mu,y.mean()
def pred(m,X): return (X-m[1])@m[0]+m[2]
def cvlam(X,y,t):
    o=np.argsort(t); f=np.array_split(o,5); best=None
    for lam in [3,30,300,3000,30000]:
        e=0
        for k in range(5):
            tr=np.concatenate([f[j] for j in range(5) if j!=k]); m=fit(X[tr],y[tr],lam); e+=((pred(m,X[f[k]])-y[f[k]])**2).sum()
        if best is None or e<best[0]: best=(e,lam)
    return best[1]
rng=np.random.default_rng(5)
def evalf(tr,te,feats,by=('run','timeframe')):
    Xd=X_of(tr,feats); cols=Xd.columns; Xt=Xd.values; y=tr.R.values
    lam=cvlam(Xt,y,tr.bar_close.values); m=fit(Xt,y,lam)
    te=te.reset_index(drop=True); p=pred(m,X_of(te,feats,cols).values); yt=te.R.values
    keep=np.zeros(len(te),bool)
    for _,g in te.assign(p=p).groupby(list(by)):
        keep[g.index[g.p>=g.p.quantile(2/3)]]=True
    up=yt[keep].mean()-yt.mean()
    out={'lam':lam,'uplift':up,'kept':yt[keep].mean(),'all':yt.mean()}
    for mode in [2,'day']:
        cl=te.run+'_'+clus(te.bar_close.values,mode).astype(str); u,inv=np.unique(cl,return_inverse=True); G=len(u)
        a=np.bincount(inv,yt*keep,G);b=np.bincount(inv,keep.astype(float),G);c=np.bincount(inv,yt,G);d=np.bincount(inv,None,G).astype(float)
        bs=[]
        for _ in range(2000):
            i=rng.integers(0,G,G); bs.append(a[i].sum()/b[i].sum()-c[i].sum()/d[i].sum())
        out['ci_'+str(mode)]=f'{np.percentile(bs,2.5):.3f}..{np.percentile(bs,97.5):.3f} G={G}'
    return out
core=D[D.kind=='strategy']
cases=[('v3a->v3b+v4 core',core[core.run=='v3a'],core[core.run.isin(['v3b','v4'])]),
       ('v3a->v4 ds200',core[core.run=='v3a'],D[(D.run=='v4')&(D.kind=='ds200')]),
       ('v4 all->v3a+v3b core',D[D.run=='v4'],core[core.run.isin(['v3a','v3b'])])]
for fn,feats in [('all',ALL),('chart',CH),('chart-no-mom',CHNM)]:
    for name,tr,te in cases:
        r=evalf(tr,te,feats); r2=evalf(tr,te,feats,by=('run','timeframe','side'))
        print(fn,'|',name,'| top3rd uplift',round(r['uplift'],3),'kept',round(r['kept'],3),'all',round(r['all'],3),r['ci_2'],'day',r['ci_day'],'| within-side uplift',round(r2['uplift'],3),r2['ci_2'])
