# Measurement-spec arithmetic (design only). Usage: python3 -I calc.py <replay_signals.csv>
import sys, math, datetime as dt
import numpy as np
from statistics import NormalDist
N=NormalDist()
KST=dt.timezone(dt.timedelta(hours=9))
d0=dt.datetime(2026,10,17,21,0,tzinfo=KST); end=dt.datetime(2026,12,26,9,0,tzinfo=KST)
w2=dt.datetime(2026,10,31,21,0,tzinfo=KST)
for name,s in (('wave1',d0),('wave2',w2)):
    L=(end-s).total_seconds()/86400; mid=s+(end-s)/2
    print(name,'days',round(L,2),'midpoint',mid.strftime('%m/%d %H:%M KST'),'day30',(s+dt.timedelta(days=30)).strftime('%m/%d %H:%M'))
print('BH rank thresholds (one-sided):')
for K in (10,16,18):
    print(K,[round(0.05*i/K,4) for i in (1,2,3)],'z1',round(N.inv_cdf(1-0.05/K),3))
zb=N.inv_cdf(0.8)
def mde(sd,n,za): return (za+zb)*sd/math.sqrt(n)
print('MDE table sd=1.0, paired sd=0.71 (assumed)')
for days,lab in ((69.5,'w1'),(55.5,'w2')):
    for tpd in (2,3,4,5,6,7):
        n=days*tpd
        row=[lab,tpd,int(n)]
        for K in (10,16,18):
            row.append(round(mde(1.0,n,N.inv_cdf(1-0.05/K)),3))
        row.append(round(mde(0.71,n,N.inv_cdf(0.95)),3))   # paired AI-rule, single one-sided 5%
        row.append(round(mde(0.71,n,N.inv_cdf(1-0.05/16)),3))
        print(row)
# day-30 per-trader MDE (single one-sided 5%) sd 1
for tpd in (4,6):
    n=30*tpd; print('day30 tpd',tpd,'n',n,'MDE unpaired',round(mde(1.0,n,1.645),3),'paired',round(mde(0.71,n,1.645),3))
# cohort pooled paired MDE (sd .71, deff 3/9), decisions/day 6
for T in (10,18):
    for days in (30,69.5):
        n=T*days*6
        print('cohort',T,'days',days,[round(mde(0.71*math.sqrt(de),n,1.645),3) for de in (3,9)])
# global futility operating characteristics at 11/16: 10 traders x 30 d x 6 dec
for de in (3,9):
    se=0.71*math.sqrt(de/(10*30*6))
    thr=min(-1.645*se,-0.05)   # need upper90<0 and mean<=-0.05 -> mean < min(...)
    for true in (0.0,-0.05,-0.10,0.05):
        p=N.cdf((thr-true)/se)
        print('global futility deff',de,'se',round(se,3),'true',true,'P(stop)',round(p,3))
# per-trader day-30 futility (>=30 trades and 90% upper bound <0): n=120, sd 1 (two-sided 90% -> 1.645)
for tpd in (4,6):
    n=30*tpd; se=1/math.sqrt(n)
    for true in (-0.17,-0.10,0.0,0.05,0.10):
        print('d30 trader tpd',tpd,'true',true,'P(stop)',round(N.cdf((-1.645*se-true)/se),3))
# ---- calibrated sim: trader-level half means, equicorrelated across traders
rng=np.random.default_rng(20261017)
def sim(K,n,mu_true,rho,coin=-0.15,null_mu=-0.15,sims=20000,sd=1.0):
    h=n/2; se_h=sd/math.sqrt(h)
    # correlated errors per half: common factor
    def draw():
        c=rng.standard_normal((sims,1)); e=rng.standard_normal((sims,K))
        return (math.sqrt(rho)*c+math.sqrt(1-rho)*e)*se_h
    mu=np.full(K,null_mu); 
    if mu_true is not None: mu[0]=mu_true
    a=mu+draw(); b=mu+draw(); m=(a+b)/2
    z=(m-coin)/(sd/math.sqrt(n)); p=1-np.vectorize(N.cdf)(z) if False else 0.5*np.vectorize(math.erfc)(z/math.sqrt(2))
    # BH
    order=np.argsort(p,axis=1); ps=np.take_along_axis(p,order,axis=1)
    thr=0.05*np.arange(1,K+1)/K; ok=ps<=thr
    kmax=np.where(ok.any(axis=1),K-np.argmax(ok[:,::-1],axis=1),0)
    rej=np.zeros_like(p,bool)
    for i in range(sims):
        if kmax[i]: rej[i,order[i,:kmax[i]]]=True
    passed=rej&(m>0)&(a>0)&(b>0)
    return passed
for K in (10,16,18):
    for lab,n in (('w1',280),('w2',220)):
        out=[]
        for mt in (0.05,0.10,0.15):
            out.append(round(sim(K,n,mt,0.3)[:,0].mean(),2))
        print('K',K,lab,'n',n,'P(pass true +.05/.10/.15, rho .3)',out)
    for rho in (0.0,0.3,0.6):
        f1=sim(K,280,None,rho,null_mu=0.0,coin=0.0).sum(axis=1).mean()  # verified-sim convention (null at 0)
        f2=sim(K,280,None,rho).sum(axis=1).mean()                       # realistic null (mean = coin = -0.15)
        print('K',K,'rho',rho,'E[false passes] null-at-0 conv',round(f1,4),'realistic null',round(f2,5))
# ---- shape effect of top-5% and 1%-curve DD rules, empirical R shape
import csv
R=[]
with open(sys.argv[1]) as f:
    for r in csv.DictReader(f):
        if r['status']=='TRADED' and r['timeframe'] in ('15m','30m','1h') and r['R'] not in ('','nan'):
            try: R.append(float(r['R']))
            except: pass
R=np.array(R); R=R[np.isfinite(R)]
print('empirical R n',len(R),'mean',round(R.mean(),3),'sd',round(R.std(),3),'p95',round(np.quantile(R,0.95),2),'max',round(R.max(),2))
base=R-R.mean()
for mt in (0.05,0.10,0.15):
    ok5=okdd=okall=0; S=4000
    for s in range(S):
        x=rng.choice(base,280)+mt
        k=max(3,int(round(0.05*len(x)))); y=np.sort(x)[:-k]
        eq=np.cumprod(1+0.01*x); dd=1-eq/np.maximum.accumulate(eq)
        c1=y.mean()>0; c2=dd.max()<=0.25
        ok5+=c1; okdd+=c2; okall+=(c1 and c2 and x.mean()>0)
    print('true net',mt,'P(mean w/o top5%>0)',round(ok5/S,3),'P(DD<=25%)',round(okdd/S,3),'P(mean>0 & both)',round(okall/S,3))
# paired-sd sanity: random 30%/50% skipper on empirical R: d=-1[skip]*R
for q in (0.3,0.5):
    sk=rng.random(len(R))<q; d=np.where(sk,-R,0.0); print('random skipper',q,'sd(d)/sd(R)',round(d.std()/R.std(),2))
