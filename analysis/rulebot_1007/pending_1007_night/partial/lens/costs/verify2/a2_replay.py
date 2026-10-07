# Every-signal replay gross/cost from the pipeline's replay_signals.csv (own accounting, own clustering, dedup checks)
import sys, os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'vb.py')).read())
import pandas as pd, numpy as np
src, out = sys.argv[1:3]
r=pd.read_csv(src)
r=r[r.status.isin(['TRADED','UNRESOLVED'])].copy()
r['k2']=r.kind.map({'strategy':'core36','ds200':'ds200','random':'coinflip'})
slip=2e-4
s=r.side; q=r.qty
r['risk']=q*(r.entry_price-r.stop_initial).abs()
r['notl']=q*r.entry_price
r['stop_pct']=100*(r.entry_price-r.stop_initial).abs()/r.entry_price
tr=r.status=='TRADED'
# exit fill from pnl identity: pnl = s*q*(x-e) - fees - funding
r['exit_fill']=r.entry_price+s*(r.pnl+r.fees+r.funding.fillna(0))/q
r['exit_raw']=r.exit_fill/(1-s*slip)
r['entry_ref']=r.entry_price/(1+s*slip)
r['cost_usd']=r.fees+r.funding.fillna(0)+q*(r.entry_price-r.entry_ref).abs()+q*(r.exit_fill-r.exit_raw).abs()
r['Rn']=np.where(tr, r.pnl/r.risk, np.nan)
r['cost_R']=np.where(tr, r.cost_usd/r.risk, np.nan)
r['gross_R']=r.Rn+r.cost_R
# marked (unresolved): mark_R is net at mark incl. what? treat gross_mark = mark_R + full paper round trip in R
rt=2*(5e-4+2e-4)
r['cost_rt_R']=rt/(r.stop_pct/100)
r['gross_R_all']=np.where(tr, r.gross_R, r.mark_R + r.cost_rt_R)
r['net_R_all']=np.where(tr, r.Rn, r.mark_R)
print('chk R vs pipeline R (traded):', (r.loc[tr,'Rn']-r.loc[tr,'R']).abs().max())
r['bar_min']=(r.bar_close//60000).astype('int64')
def boot(v,c,B=4000,seed=1):
    v=np.asarray(v,float); c=np.asarray(c); ok=np.isfinite(v); v=v[ok]; c=c[ok]
    u,inv=np.unique(c,return_inverse=True); S=np.bincount(inv,weights=v); N=np.bincount(inv)
    rng=np.random.default_rng(seed); d=rng.integers(0,len(u),(B,len(u)))
    m=S[d].sum(1)/N[d].sum(1); return np.percentile(m,2.5),np.percentile(m,97.5),len(u)
rows=[]
for tf in ['15m','30m','1h','4h']:
  for grp,mask in [('core36',r.k2=='core36'),('ds200',r.k2=='ds200'),('core+ds',r.k2.isin(['core36','ds200'])),('coinflip',r.k2=='coinflip')]:
    g=r[mask&(r.timeframe==tf)].copy()
    if len(g)==0: continue
    for cl_h in [1,4,24]:
        g['cl']=g.run+'|'+(g.bar_min//(60*cl_h)).astype(str)
        gr=g[g.status=='TRADED']
        lo,hi,k=boot(gr.gross_R,gr.cl)
        lo2,hi2,k2=boot(g.gross_R_all,g.cl)
        # dedup: same run,symbol,bar,side,leverage -> identical path
        d=g.drop_duplicates(['run','symbol','bar_close','side','leverage'])
        dr=d[d.status=='TRADED']
        rows.append(dict(tf=tf,grp=grp,clust_h=cl_h,n_all=len(g),n_res=len(gr),clusters=k,
            net_res=gr.Rn.mean(),gross_res=gr.gross_R.mean(),ci_res=f'[{lo:+.3f},{hi:+.3f}]',cost_res=gr.cost_R.mean(),
            net_all=g.net_R_all.mean(),gross_all=g.gross_R_all.mean(),ci_all=f'[{lo2:+.3f},{hi2:+.3f}]',
            n_dedup=len(d),gross_dedup_res=dr.gross_R.mean(),net_dedup_res=dr.Rn.mean(),
            unres_share=(g.status=='UNRESOLVED').mean(), med_stop=g.stop_pct.median(), cost_rt_med=g.cost_rt_R.median()))
o=pd.DataFrame(rows); pd.set_option('display.width',250)
print(o.round(3).to_string()); o.to_csv(f'{out}/a2_replay_by_tf.csv',index=False)
r.to_csv(f'{out}/a2_replay_rows.csv',index=False)
# per run
print(r[r.status=='TRADED'].groupby(['run','k2','timeframe']).agg(n=('Rn','size'),net=('Rn','mean'),gross=('gross_R','mean'),cost=('cost_R','mean')).round(3))
