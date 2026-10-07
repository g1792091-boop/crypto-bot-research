"""Average-linkage clustering of the 23 strategies on chance-corrected entry co-occurrence.
python3 -I -B clus.py <pairs_all.csv> [measure] [thresholds...]"""
import sys; sys.path[:0]=['/root/.local/lib/python3.11/site-packages']
import pandas as pd, numpy as np
P=pd.read_csv(sys.argv[1]); meas=sys.argv[2] if len(sys.argv)>2 else 'k_card_1h'
th=[float(x) for x in sys.argv[3:]] or [0.5,0.6,0.7]
names=sorted(set(P.A)|set(P.B)); n=len(names); ix={s:i for i,s in enumerate(names)}
Sm=np.eye(n)
for _,r in P.iterrows(): Sm[ix[r.A],ix[r.B]]=Sm[ix[r.B],ix[r.A]]=r[meas]
def avg_link(S,t):
    cl=[[i] for i in range(len(S))]
    while True:
        best=(-1,None,None)
        for a in range(len(cl)):
            for b in range(a+1,len(cl)):
                v=np.mean([S[i,j] for i in cl[a] for j in cl[b]])
                if v>best[0]: best=(v,a,b)
        if best[0]<t: break
        a,b=best[1],best[2]; cl[a]=cl[a]+cl[b]; del cl[b]
    return cl
for t in th:
    cl=avg_link(Sm,t)
    print('== threshold',t, meas)
    for c in sorted(cl,key=len,reverse=True):
        if len(c)>1:
            sub=Sm[np.ix_(c,c)]; m=sub[np.triu_indices(len(c),1)]
            print('  ',[names[i] for i in c],'avg %.2f min %.2f'%(m.mean(),m.min()))
    print('   singletons:',[names[c[0]] for c in cl if len(c)==1])
