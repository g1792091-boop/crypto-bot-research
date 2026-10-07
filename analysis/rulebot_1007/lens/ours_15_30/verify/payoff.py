import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
A=pd.read_csv('my_es_rows_all.csv'); T=A[(A.status=='TRADED')]
for sel in ['later','v3a','all']:
  for tf in ['15m','30m']:
    g=T[T.tf==tf]
    if sel=='later': g=g[g.rn!='v3a']
    elif sel=='v3a': g=g[g.rn=='v3a']
    sl=g[g.exit_reason=='SL'].R; lk=g[g.exit_reason=='LOCK'].R
    w=g[g.R>0].R; l=g[g.R<=0].R
    be_exit=(-sl.mean())/(lk.mean()-sl.mean()); be_win=(-l.mean())/(w.mean()-l.mean())
    cost=((g.fees+g.funding)/(g.qty*g.sf*g.entry_price)).mean() if sel=='later' else np.nan
    slip_med=(2*0.0002/g.sf).mean()
    print(sel,tf,'n',len(g),'SL mean %.3f LOCK mean %.3f  BE(lock vs SL) %.3f  lock share %.3f | win mean %.3f loss mean %.3f BE(win) %.3f win share %.3f | neg LOCK share %.3f | median rt cost/stop %.3f | mean fees+fund R %.3f slipR %.3f | mfe>=.5 %.3f mfe>=1 %.3f | SL with mfe>=.5 %.3f | exits %s'%(
        sl.mean(),lk.mean(),be_exit,(g.exit_reason=='LOCK').mean(),w.mean(),l.mean(),be_win,(g.R>0).mean(),(lk<=0).mean(),(0.0014/g.sf).median(),cost,slip_med,
        (g.mfe_R>=0.5).mean(),(g.mfe_R>=1).mean(),(g[g.exit_reason=='SL'].mfe_R>=0.5).mean(), g.exit_reason.value_counts().to_dict()))
# gross for later
for tf in ['15m','30m']:
    g=T[(T.tf==tf)&(T.rn!='v3a')].copy()
    g['feesR']=(g.fees+g.funding)/(g.qty*g.sf*g.entry_price)
    # slippage estimate: entry slip qty*ref*0.0002 ~ entry*0.0002/(1.0002); exit slip ~ exit*0.0002 ; approx 2*0.0002/sf
    g['slipR']=2*0.0002/g.sf
    g['gross']=g.R+g.feesR+g.slipR
    print(tf,'net %.3f fees+fund %.3f slip %.3f gross %.3f'%(g.R.mean(),g.feesR.mean(),g.slipR.mean(),g.gross.mean()))
