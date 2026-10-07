import numpy as np, glob, os, sys, json, itertools
d=sys.argv[1]; tf=sys.argv[2]; out=sys.argv[3]; W=int(sys.argv[4])
S={}
for ci,f in enumerate(sorted(glob.glob(os.path.join(d,'out_%s_*.npz'%tf)))):
    z=np.load(f,allow_pickle=True); I=z['i'].astype(np.int64); sd=z['side'].astype(np.int64)
    for k in z.files:
        if not k.startswith('m__'): continue
        m=z[k]
        if len(m)==0: continue
        key=(ci*10_000_000+I[m])*2+(sd[m]>0)
        S.setdefault(k[3:],[]).append(key)
S={k:np.unique(np.concatenate(v)) for k,v in S.items()}
names=[k for k in S if len(S[k])>2000]
res={}
for a,b in itertools.combinations(names,2):
    A=S[a];B=S[b]
    if W==0: c=len(np.intersect1d(A,B,assume_unique=True))
    else:
        # B-element within +-W bars same side/coin of some A element: count A elements matched
        Bs=np.sort(B); hits=0
        for off in range(-W,W+1):
            pass
        sh=np.concatenate([B+2*o for o in range(-W,W+1)])
        c=len(np.intersect1d(A,np.unique(sh)))
        c=min(c,len(A))
    res[a+'|'+b]=round(c/min(len(A),len(B)),3)
json.dump(res,open(out,'w'))
top=sorted(res.items(),key=lambda x:-x[1])[:60]
for k,v in top: print(v,k)
