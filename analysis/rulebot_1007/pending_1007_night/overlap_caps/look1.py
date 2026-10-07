import sys; sys.path[:0]=['/root/.local/lib/python3.11/site-packages']
import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_rows',300)
df=pd.read_csv('out/pair_shares.csv')
k=['15m_bar','15m_1bar','15m_4h','30m_bar','1h_bar','card_same15','card_1h','card_4h']
rev=df[['A','B']+k+[c+'_chance' for c in k]].rename(columns={'A':'B','B':'A',**{c:c+'_r' for c in k},**{c+'_chance':c+'_chance_r' for c in k}})
s=df.merge(rev,on=['A','B'])
s=s[s.A<s.B].copy()
for c in k:
    s[c+'_max']=np.maximum(s[c],s[c+'_r']); s[c+'_lift']=s[c+'_max']/np.maximum(s[c+'_chance'],s[c+'_chance_r'])
cols=['A','B']+[c+'_max' for c in k]+['15m_bar_lift','card_4h_lift']
print(s.sort_values('15m_bar_max',ascending=False)[cols].head(45).round(3).to_string())
print(s[[c+'_max' for c in k]].describe().round(3).to_string())
s.to_pickle('out/sym.pkl')
