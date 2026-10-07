import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
from scipy.stats import spearmanr
E=sys.argv[1]
rows=[]
for run in ['run-20261005T014624Z','run-20261005T183457Z','current']:
    t=pd.read_csv(f'{E}/{run}/trades.csv'); t=t[~t.account_id.str.startswith('RANDOM')]
    t['tf']=t.account_id.str.split('@').str[1]; t['strategy']=t.account_id.str.split('@').str[0]
    t=t[t.tf.isin(['15m','30m'])]
    acc=pd.read_csv(f'{E}/{run}/accounts.csv').set_index('account_id'); t=t[t.account_id.map(acc['kind']).eq('strategy')]
    t['R']=t.pnl/(t.qty*(t.entry_price-t.stop_initial).abs()); t['run']=run
    rows.append(t)
T=pd.concat(rows)
ag=T.groupby(['strategy','tf']).agg(acct_n=('R','size'),acct_R=('R','mean'),pnl=('pnl','sum'),gw=('pnl',lambda x:x[x>0].sum()),gl=('pnl',lambda x:-x[x<0].sum())).reset_index()
ag['pf']=ag.gw/ag.gl
C=pd.read_csv('my_cells.csv').merge(ag,on=['strategy','tf'],how='left')
print(C[(C.strategy=='S2_ST_ROC')&(C.tf=='15m')][['n','mean','acct_n','acct_R','pf']])
print(C[(C.strategy=='N07_ICHI_CMO')&(C.tf=='30m')][['n','mean','lo','hi','acct_n','acct_R','pf']])
m=C[(C.acct_n>=10)&(C.n>=20)]; print('cells',len(m),spearmanr(m.acct_R,m['mean']))
# coverage: account trades / every-signal n (all signals incl. unresolved)
A=pd.read_csv('my_es_rows_all.csv'); ns=A.groupby(['strategy','tf']).size().rename('n_all').reset_index()
C=C.merge(ns,on=['strategy','tf'],how='left'); C['cov']=C.acct_n/C.n_all
print(C[C.n_all>=20]["cov"].describe(), C[C.n_all>=20][["strategy","tf","acct_n","n_all","cov"]].sort_values("cov").head(5))
# signals submitted count incl rejected: from signal_log
