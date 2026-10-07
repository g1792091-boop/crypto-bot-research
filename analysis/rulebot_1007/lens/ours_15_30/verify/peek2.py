import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd
O=sys.argv[1]
r=pd.read_csv(O+'/replay_signals.csv')
print(r.columns.tolist()); print(r.shape)
print(r.head(2).T.to_string())
s=r[(r.kind=='strategy')&r.timeframe.isin(['15m','30m'])]
print(s.groupby(['run','timeframe','status']).size())
print('dups', s.duplicated(['run','strategy','timeframe','symbol','bar_close']).sum())
t=pd.read_csv(O+'/trades_enriched.csv'); print(t.columns.tolist())
