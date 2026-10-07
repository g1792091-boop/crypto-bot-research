import sys; src=open(sys.argv[0].rsplit("/",1)[0]+"/ai3.py").read(); exec(src.split("rows=[];END")[0])
out=[]
for run in ['v3b','v4']:
    b=rd(run,'live_bars.csv',usecols=['ts','symbol','open','high','low','close']).sort_values(['symbol','ts'])
    B={s:(g.ts.to_numpy(np.int64),g.open.to_numpy(),g.high.to_numpy(),g.low.to_numpy(),g.close.to_numpy()) for s,g in b.groupby('symbol')}
    o=rd(run,'outcomes.csv').merge(rd(run,'accounts.csv')[['account_id','kind']],on='account_id'); o=o[(o.kind=='strategy')&(o.sig_timeframe=='4h')]
    for r in o.itertuples():
        sd=r.stop_dist; side=int(r.sig_side)
        if (r.ref_price*(1/20-0.005)-sd)<max(r.sig_atr,0.002*r.ref_price): continue
        lev=30 if (r.ref_price*(1/30-0.005)-sd)>=max(r.sig_atr,0.002*r.ref_price) else 20
        x=sim(B,r.symbol,int(r.step_ts),side,r.ref_price,r.ref_price-side*sd,lev); x.update(run=run,lev=lev,side=side,strategy=r.sig_strategy_id); out.append(x)
D=pd.DataFrame(out); print(D.groupby('st').R.agg(['mean','size']).round(3).to_string(), D.lev.value_counts().to_dict(), 'by run/side', D[D.st=='T'].groupby(['run','side']).R.agg(['mean','size']).round(3).to_string())
