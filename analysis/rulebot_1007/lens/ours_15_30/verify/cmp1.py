import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
L=sys.argv[1]
es=pd.read_csv(L+'/every_signal_rows_15_30.csv')
print(es.groupby(['run','timeframe']).agg(n=('R','size'),meanR=('R','mean')))
my=pd.read_csv('my_v3a_rows.csv'); my=my[my.tf.isin(['15m','30m'])&my.in_win&my.R.notna()]
print(my.groupby('tf').agg(n=('R','size'),meanR=('R','mean')))
a=es[es.run=='run-20261005T014624Z'][['strategy','timeframe','symbol','bar_close','R']].rename(columns={'timeframe':'tf'})
m=my.merge(a,on=['strategy','tf','symbol','bar_close'],how='outer',suffixes=('_me','_them'),indicator=True)
print(m._merge.value_counts())
b=m[m._merge=='both']; print('max abs diff R', (b.R_me-b.R_them).abs().max())
