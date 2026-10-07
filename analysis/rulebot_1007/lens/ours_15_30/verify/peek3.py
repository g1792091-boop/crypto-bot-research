import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
E=sys.argv[1]; R='run-20261005T014624Z'
o=pd.read_csv(E+f'/{R}/outcomes.csv'); print(o.columns.tolist()); print(o.head(3).to_string())
s=pd.read_csv(E+f'/{R}/signal_log.csv'); print(s.status.value_counts())
d=pd.read_csv(E+f'/{R}/d3_shadows.csv')
sk=d[d.kind=='skipped'].copy()
sk['bc']=sk.key.str.split('|').str[-1].astype('int64')
print(sk.groupby('day').bc.agg(['min','max','size']))
for c in ['min','max']:
    pass
print(pd.to_datetime(sk.bc.min()+9*3600000,unit='ms'), pd.to_datetime(sk.bc.max()+9*3600000,unit='ms'))
print('sig range', pd.to_datetime(s.bar_close.min()+9*3600000,unit='ms'), pd.to_datetime(s.bar_close.max()+9*3600000,unit='ms'))
