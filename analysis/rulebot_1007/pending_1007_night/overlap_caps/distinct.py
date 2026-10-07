"""Distinctness of each strategy vs a staffed set: max chance-corrected 1h co-entry (kappa), max every-signal daily R
corr, max one-position trader daily R corr, max entry co-holding lift.  python3 -I -B distinct.py <pairs_all.csv>"""
import sys; sys.path[:0]=['/root/.local/lib/python3.11/site-packages', '/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/ovl5']
import pandas as pd, numpy as np
import common5 as C
P=pd.read_csv(sys.argv[1])
def get(a,b,col):
    a,b=sorted([a,b]); return float(P[(P.A==a)&(P.B==b)][col].iloc[0])
T17=C.WAVE1+C.WAVE2
rows=[]
for s in C.ALL:
    others=[o for o in T17 if o!=s]
    r=dict(strategy=s,wave=C.WAVE[s])
    for col in ('k_card_1h','r_sig','r_tr','coheld_lift'):
        v=[(get(s,o,col),o) for o in others]; m=max(v)
        r['max_'+col]=round(m[0],3); r['with_'+col]=m[1]
    r['mean_r_tr']=round(np.mean([get(s,o,'r_tr') for o in others]),3)
    rows.append(r)
d=pd.DataFrame(rows); pd.set_option('display.width',250)
print(d.to_string(index=False)); d.to_csv('out/distinct_vs_T17.csv',index=False)
