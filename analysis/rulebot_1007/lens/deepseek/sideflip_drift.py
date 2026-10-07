# drift-neutral side-flip: excess among long signals and among short signals separately; equal-weight average
# args: replay_signals.csv out_csv
RNG=np.random.default_rng(7)
P=pd.read_csv(args[0]); P=P[(P.kind.isin(['ds200','strategy']))&(P.run=='current')]
x=P[(P.status=='TRADED')&(P.flip_status=='TRADED')].copy()
x=x[np.isfinite(x.R)&np.isfinite(x.flip_R)]
x['h']=0.5*(x.R-x.flip_R)
TFM={'15m':15,'30m':30,'1h':60,'4h':240}
blk=np.maximum(x.timeframe.map(TFM).to_numpy()*60000,3600000)
x['cl']=(x.bar_close.to_numpy()//blk)
x['fam']=x.strategy.str.split('_').str[0]
def flip_p(h,cl,B=4000):
    s=pd.Series(h).groupby(cl).sum().to_numpy(); n=len(h); obs=h.mean()
    if len(s)<5: return np.nan
    sims=(s[None,:]*RNG.choice((-1.0,1.0),size=(B,len(s)))).sum(1)/n
    return (1+np.sum(sims>=obs-1e-12))/(B+1)
rows=[]
def one(g,keys):
    d=dict(keys); d['n']=len(g); d['long_share']=(g.side>0).mean()
    d['excess_all']=g.h.mean(); d['p_all']=flip_p(g.h.to_numpy(),g.cl.to_numpy())
    for s,lab in ((1,'long'),(-1,'short')):
        gg=g[g.side==s]; d[f'n_{lab}']=len(gg); d[f'excess_{lab}']=gg.h.mean() if len(gg) else np.nan
        d[f'meanR_{lab}']=gg.R.mean() if len(gg) else np.nan
    d['excess_drift_neutral']=np.nanmean([d['excess_long'],d['excess_short']]) if d['n_long'] and d['n_short'] else np.nan
    # drift-neutral p: flip within side, combine with equal weights: statistic = 0.5*(mean_long + mean_short)
    if d['n_long']>=3 and d['n_short']>=3:
        hl=g.side.to_numpy()>0
        w=np.where(hl,0.5/d['n_long'],0.5/d['n_short'])
        v=g.h.to_numpy()*w
        s=pd.Series(v).groupby(g.cl.to_numpy()).sum().to_numpy()
        obs=v.sum()
        if len(s)>=5:
            sims=(s[None,:]*RNG.choice((-1.0,1.0),size=(4000,len(s)))).sum(1)
            d['p_drift_neutral']=(1+np.sum(sims>=obs-1e-12))/4001
    return d
for (k,tf),g in x.groupby(['kind','timeframe']): rows.append(one(g,{'level':'kind_tf','kind':k,'family':'*','timeframe':tf}))
for (k,f,tf),g in x[x.kind=='ds200'].groupby(['kind','fam','timeframe']): rows.append(one(g,{'level':'family_tf','kind':k,'family':f,'timeframe':tf}))
for k,g in x.groupby('kind'): rows.append(one(g,{'level':'kind','kind':k,'family':'*','timeframe':'*'}))
D=pd.DataFrame(rows); D.to_csv(args[1],index=False)
print(D[D.level!='family_tf'].round(4).to_string())
print(D[(D.level=='family_tf')&(D.timeframe.isin(['15m','30m']))].round(3).to_string())
