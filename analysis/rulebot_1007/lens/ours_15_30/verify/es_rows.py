"""Build my every-signal rows: v3a (my_v3a_rows.csv) + v3b/v4 replay TRADED (and UNRESOLVED kept with mark_R).
usage: python3 -I es_rows.py <out_real_dir>"""
import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
OR=sys.argv[1]
RN={'run-20261005T014624Z':'v3a','run-20261005T183457Z':'v3b','current':'v4'}
v=pd.read_csv('my_v3a_rows.csv'); v=v[v.tf.isin(['15m','30m'])&v.in_win]
v['status']=np.where(v.R.notna(),'TRADED',np.where(v.resolved==0,'UNRESOLVED','NOTRADE'))
v['mark_R']=np.nan
rp=pd.read_csv(OR+'/replay_signals.csv'); rp=rp[(rp.kind=='strategy')&rp.timeframe.isin(['15m','30m'])].copy()
# recompute R myself from replay primitives
rp['R_me']=rp.pnl/(rp.qty*(rp.entry_price-rp.stop_initial).abs())
print('replay R recompute max diff', (rp.R_me-rp.R).abs().max())
rp=rp.rename(columns={'timeframe':'tf'})
rp['sf']=(rp.entry_price-rp.stop_initial).abs()/rp.entry_price
rp['src']=np.where(rp.acct_status=='ENTERED','replay_entered','replay_other')
rp['lev']=rp.leverage
cols=['run','strategy','tf','symbol','bar_close','side','src','status','R','mark_R','lev','sf','roe','exit_reason','fees','funding','qty','entry_price','mfe_R','mae_R','flip_R','flip_status','hold_min']
A=pd.concat([v.reindex(columns=cols), rp.reindex(columns=cols)],ignore_index=True)
A['rn']=A.run.map(RN)
H=3600000
A['blk4']=A.run+'|'+(A.bar_close//(4*H)).astype('int64').astype(str)
A['blkD']=A.run+'|'+((A.bar_close+9*H)//(24*H)).astype('int64').astype(str)
A['blk1']=A.run+'|'+(A.bar_close//H).astype('int64').astype(str)
A.to_csv('my_es_rows_all.csv',index=False)
print(A.groupby(['rn','tf','status']).size())
