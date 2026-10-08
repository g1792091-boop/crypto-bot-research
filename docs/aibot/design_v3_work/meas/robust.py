# Pass probability of ONE true trader under the full pass rule with an empirical R shape,
# and alternatives for the "top 5%" robustness rule. Usage: python3 -I robust.py <replay_signals.csv>
import sys, csv, math
import numpy as np
rng=np.random.default_rng(1217)
R=[]
with open(sys.argv[1]) as f:
    for r in csv.DictReader(f):
        if r['status']=='TRADED' and r['timeframe'] in ('15m','30m','1h') and r['R'] not in ('','nan'):
            try: R.append(float(r['R']))
            except: pass
R=np.array(R); R=R[np.isfinite(R)]; base=R-R.mean()
top=np.sort(base)[-int(0.05*len(base)):]
print('top5% mean (demeaned)',round(top.mean(),2),'-> mean drop when removed',round(0.05*top.mean()/0.95,3))
COIN=-0.15
def one(mu,n,K,S=4000):
    res={k:0 for k in ('core','top5abs','top3abs','top1pct','top5rel','all_top5abs','all_top5rel','all_top3abs')}
    for s in range(S):
        x=rng.choice(base,n)+mu
        c=rng.choice(base,n*20)+COIN           # coin draws, same shape
        h=n//2; a=x[:h].mean(); b=x[h:].mean(); m=x.mean()
        # day-block-ish SE approximated by iid SE (within-trader clustering minor)
        z=(m-COIN)/(x.std(ddof=1)/math.sqrt(n)); p=0.5*math.erfc(z/math.sqrt(2))
        nulls=rng.random(K-1); ps=np.sort(np.append(nulls,p)); thr=0.05*np.arange(1,K+1)/K
        ok=ps<=thr; kmax=(np.nonzero(ok)[0].max()+1) if ok.any() else 0
        bh= kmax>0 and p<=ps[kmax-1]
        dd=(1-np.cumprod(1+0.01*x)/np.maximum.accumulate(np.cumprod(1+0.01*x))).max()<=0.25
        core= bh and m>0 and a>0 and b>0 and dd
        xs=np.sort(x); cs=np.sort(c)
        k5=max(3,int(round(0.05*n))); t5=xs[:-k5].mean()>0
        t3=xs[:-3].mean()>0; t1=xs[:-max(1,int(round(0.01*n)))].mean()>0
        rel=xs[:-k5].mean()>cs[:-max(3,int(round(0.05*len(cs))))].mean()
        res['core']+=core; res['top5abs']+=t5; res['top3abs']+=t3; res['top1pct']+=t1; res['top5rel']+=rel
        res['all_top5abs']+=core and t5; res['all_top5rel']+=core and rel; res['all_top3abs']+=core and t3
    return {k:round(v/S,2) for k,v in res.items()}
for K,n,lab in ((10,280,'S/w1'),(16,280,'M/w1'),(16,220,'M/w2')):
    for mu in (0.0,0.05,0.10,0.15,0.20):
        print(lab,'K',K,'n',n,'true net',mu,one(mu,n,K))
