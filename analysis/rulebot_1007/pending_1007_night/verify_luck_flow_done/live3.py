import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
OUT=sys.argv[0].rsplit("/",1)[0]; rng=np.random.default_rng(3)
T=[]
for run in RUNS:
    t=rd(run,'trades.csv').merge(rd(run,'accounts.csv')[['account_id','kind']],on='account_id'); t['run']=run
    t['R']=t.pnl/(t.qty*(t.entry_price-t.stop_initial).abs()); T.append(t.drop(columns=['context']))
T=pd.concat(T); T['blk']=T.entry_time//(4*3600000); T['minute']=T.entry_time//60000
T.to_csv(f'{OUT}/trades3.csv',index=False)
def deff(v,cl):
    v=np.asarray(v,float); r=v-v.mean(); s=pd.Series(r).groupby(np.asarray(cl)).sum(); return float((s**2).sum()/(r**2).sum())
print('== mean R by kind x tf (all runs)'); print(T[T.timeframe!='5m'].groupby(['kind','timeframe']).R.agg(['mean','size','std']).round(3).to_string())
for k in ['strategy','ds200']:
    for tf in ['15m','30m']:
        g=T[(T.kind==k)&(T.timeframe==tf)]
        print(k,tf,'n',len(g),'deff coin-min',round(deff(g.R,g.run+g.symbol+g.minute.astype(str)),2),'min',round(deff(g.R,g.run+g.minute.astype(str)),2),'4h',round(deff(g.R,g.run+g.blk.astype(str)),2))
# clusters v4
v=T[(T.run=='v4')&T.kind.isin(['strategy','ds200'])]
c=v.groupby(['symbol','minute']).account_id.transform('size')
for k in ['ds200','strategy']:
    m=v.kind==k; print('v4',k,'share sharing coin-minute',round((c[m]>=2).mean(),3),'>=6 accounts (>=5 others)',round((c[m]>=6).mean(),3))
print('largest cluster', v.groupby(['symbol','minute']).size().max())
# coin-flip accounts
R=T[T.kind=='random']
for tf in ['15m','30m','1h','4h']:
    g=R[R.timeframe==tf]
    bs=g.groupby('blk').R.apply(list); 
    ms=[np.concatenate([bs.iloc[i] for i in rng.integers(0,len(bs),len(bs))]).mean() for _ in range(2000)]
    s=g.R.sort_values(ascending=False)
    print('RANDOM',tf,'n',len(g),'mean',round(g.R.mean(),3),'CI',np.percentile(ms,[2.5,97.5]).round(3),'blocks',len(bs),'by run',g.groupby('run').R.agg(['mean','size']).round(3).values.tolist(),
          'top2/sum',round(s.iloc[:2].sum()/g.R.sum(),2), 'exit',g.exit_reason.value_counts().to_dict())
g=R[(R.timeframe=='15m')&(R.run=='v4')]; print('v4 15m flips by side', g.groupby('side').R.agg(['mean','size']).round(3).values.tolist())
# profitable coin-flip account-runs & best-trade
A=T[T.kind=='random'].groupby(['run','account_id']).agg(s=('pnl','sum'),best=('pnl','max'),n=('pnl','size'))
P=A[A.s>0]; print('profitable flip acct-runs',len(P),'gone w/o best',int((P.s-P.best<=0).sum()), 'median best share', round((P.best/P.s).median(),2))
A=T[T.kind.isin(['strategy','ds200'])].groupby(['run','account_id']).agg(s=('pnl','sum'),best=('pnl','max'))
P=A[A.s>0]; print('profitable non-random acct-runs',len(P),'gone w/o best',int((P.s-P.best<=0).sum()))
# 15m sd for MDE
for tf in ['15m','30m']:
    g=T[T.kind.isin(['strategy','ds200'])&(T.timeframe==tf)]; print('sd R',tf,round(g.R.std(),3),'n',len(g))
