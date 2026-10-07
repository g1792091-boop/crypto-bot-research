import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
A=pd.read_csv('my_es_rows_all.csv'); T=A[A.status=='TRADED']
g=T[(T.strategy=='N17_KC_RSI')&(T.tf=='15m')&(T.rn=='v4')]
print('N17@15m v4 n',len(g),'long share %.2f'%(g.side>0).mean(), g.groupby('side').R.agg(['size','mean']).round(3).to_dict())
# MFE ranking (replay rows only, v3b+v4), cells with >=20 replay rows
L=T[T.rn!='v3a']
m=L.groupby(['strategy','tf']).agg(n=('mfe_R','size'),mfe=('mfe_R','mean'),r1=('mfe_R',lambda x:(x>=1).mean())).reset_index()
print(m[m.n>=20].sort_values('mfe',ascending=False).head(6).round(3).to_string())
# their every_signal rows mfe for S4 15m
E=pd.read_csv('../every_signal_rows_15_30.csv')
for c in [('S4_BB_BBP','15m'),('S3_CMO_SANDWICH','15m'),('N01_ST_EMA','15m')]:
    x=E[(E.strategy==c[0])&(E.timeframe==c[1])]
    print(c,'rows',len(x),'mfe rows',x.mfe_R.notna().sum(),'mean mfe %.3f'%x.mfe_R.mean(),'share>=1 (of all rows) %.3f'%(x.mfe_R>=1).mean())
