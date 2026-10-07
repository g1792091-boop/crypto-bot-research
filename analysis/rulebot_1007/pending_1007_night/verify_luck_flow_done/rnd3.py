import sys; src=open(sys.argv[0].rsplit("/",1)[0]+"/ai3.py").read(); exec(src.split("rows=[];END")[0])
rng=np.random.default_rng(2); out=[]
for run in ['v3b','v4']:
    b=rd(run,'live_bars.csv',usecols=['ts','symbol','open','high','low','close']).sort_values(['symbol','ts'])
    B={s:(g.ts.to_numpy(np.int64),g.open.to_numpy(),g.high.to_numpy(),g.low.to_numpy(),g.close.to_numpy()) for s,g in b.groupby('symbol')}
    o=rd(run,'outcomes.csv'); o=o[o.sig_strategy_id.str.startswith('RANDOM')&(o.sig_timeframe=='15m')]
    for r in o.itertuples():
        sd=r.stop_dist if r.stop_dist==r.stop_dist else 2*r.sig_atr; s=int(r.sig_side)
        a=sim(B,r.symbol,int(r.step_ts),s,r.ref_price,r.ref_price-s*sd,30); f=sim(B,r.symbol,int(r.step_ts),-s,r.ref_price,r.ref_price+s*sd,30)
        if a and f and a['st']=='T': out.append(dict(run=run,h1=r.step_ts//3600000,d=(a['R']-f['R'])/2,side=s))
D=pd.DataFrame(out); s_=D.groupby('h1').d.sum().to_numpy(); o_=s_.sum()
sims=np.array([(s_*rng.choice([-1,1],len(s_))).sum() for _ in range(4000)])
print('random 15m pairs n',len(D),'half-excess',round(D.d.mean(),3),'p2',(np.abs(sims)>=abs(o_)).mean(),'long share',round((D.side>0).mean(),2), D.groupby('run').d.agg(['mean','size']).round(3).values.tolist())
