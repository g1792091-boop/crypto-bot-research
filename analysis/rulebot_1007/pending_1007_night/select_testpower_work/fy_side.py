import numpy as np, glob, sys, os, json, collections
d=sys.argv[1]; out=sys.argv[2]
acc=collections.defaultdict(lambda: dict(n=0,nl=0,s=0.0,ss=0.0,g=0.0,feas=0,sl=0.0,ssh=0.0,nsh=0))
for f in sorted(glob.glob(os.path.join(d,'out_*.npz'))):
    tf=os.path.basename(f).split('_')[1]
    z=np.load(f,allow_pickle=True)
    side=z['side']; R=z['R']; G=z['gross']; fe=z['feasible']
    for k in z.files:
        if not k.startswith('m__'): continue
        m=z[k]
        if len(m)==0: continue
        key=(k[3:],tf); a=acc[key]
        r=R[m]; ok=np.isfinite(r); s=side[m]
        a['n']+=int(ok.sum()); a['nl']+=int((s[ok]==1).sum())
        a['s']+=float(r[ok].sum()); a['ss']+=float((r[ok]**2).sum()); a['g']+=float(G[m][ok].sum()); a['feas']+=int(fe[m].sum())
        a['sl']+=float(r[ok][s[ok]==1].sum()); a['ssh']+=float(r[ok][s[ok]==-1].sum()); a['nsh']+=int((s[ok]==-1).sum())
res={}
for (st,tf),a in acc.items():
    n=a['n']
    if n==0: continue
    mu=a['s']/n; sd=max(0.0,a["ss"]/n-mu*mu)**0.5
    res[st+'@'+tf]=dict(n=n,long=round(a['nl']/n,3),meanR=round(mu,4),sdR=round(sd,3),gross=round(a['g']/n,4),feas=round(a['feas']/n,3),
       longR=round(a['sl']/max(1,a['nl']),4),shortR=round(a['ssh']/max(1,a['nsh']),4))
json.dump(res,open(out,'w'))
print(len(res))
