import sys; sys.path.append('/root/.local/lib/python3.11/site-packages')
import pandas as pd, numpy as np
r=pd.read_csv(sys.argv[1])
print(r['run'].value_counts()); print(r['status'].value_counts())
print(r.groupby(['kind','timeframe','status']).size().unstack(fill_value=0))
t=r[r.status=='TRADED']
print(t.groupby(['kind','tier','leverage']).size())
print(t.groupby(['kind','timeframe']).agg(n=('R','size'),R=('R','mean'),sf=('stop_frac','median'),sfm=('stop_frac','mean')))
