sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2')
from lib import *
D,cut=load()
for kind in ['strategy','ds200']:
  for tf in ['15m','30m']:
    x=D[(D.kind==kind)&(D.timeframe==tf)].copy(); x['eu']=x.session=='europe'
    g=x.groupby(['run','kst_day']).apply(lambda g: pd.Series({'n_eu':g.eu.sum(),'n_rest':(~g.eu).sum(),'R_eu':g.R[g.eu].mean(),'R_rest':g.R[~g.eu].mean(),
         'long_eu':(g.side[g.eu]>0).mean(),'n_blocks_eu':g.bar_close[g.eu].floordiv(2*H).nunique()}),include_groups=False)
    g['diff']=g.R_eu-g.R_rest
    print(kind,tf); print(g.round(3).to_string())
    oos=g[(g.n_eu>=5)].reset_index()
    for sel,name in [(oos.run.isin(['v3a','v3b']),'v3a+v3b days'),(oos.run.isin(['v3a','v3b','v4']),'all days')]:
        dd=oos.loc[sel,'diff'].values; t=dd.mean()/(dd.std(ddof=1)/np.sqrt(len(dd)))
        print(' ',name,'n days',len(dd),'mean diff',round(dd.mean(),3),'t',round(t,2),'p1',round(stats.t.sf(-t,len(dd)-1),3),'neg days',int((dd<0).sum()))
  # side-stratified europe effect (within run x side)
for tf in ['15m','30m']:
    x=D[(D.kind=='strategy')&(D.timeframe==tf)].copy(); x['run2']=x.run+x.sideb
    c=contrast(x.assign(run=x.run2),'session','europe',2); print(tf,'europe within side',round(c['d'],3),round(c['se'],3),round(c['p'],4))
