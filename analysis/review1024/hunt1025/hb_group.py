"""Group level (entry cell x side mode x filter): how many of its 330 exits work in both halves (plateau) and the
median result over exits, for the real directions and for 3 coin-flip direction runs. A lone lucky exit scores low."""
import os, sys, numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
pre=open(os.path.join(HERE,'hb_eval.py')).read().split('t0 = time.time()')[0]
exec(pre.replace("cache=True","cache=False"))
F_=np.load(os.path.join(OUTD,'fwd.npz')); W2=F_['W2'][order]; K2=F_['K2'][order]
def gstats(R):
    eq,dd,n,wn,e1,e2,n1,n2=(R[:,:,k] for k in range(8)); q=R[:,:,8:12]
    ok=(n>=10)&(n1>=4)&(n2>=4)
    both=(e1>=1)&(e2>=1)&ok; allq=ok&(q.min(axis=2)>=1)
    le=np.where(ok,np.log(np.maximum(eq,1e-6)),np.nan)
    with np.errstate(all='ignore'):
        med=np.nanmedian(le,axis=1)
    return pd.DataFrame({'plat':both.mean(1),'platq':allq.mean(1),'med':np.exp(med),'nref':n[:,100],'okfrac':ok.mean(1)})
R=np.load(os.path.join(OUTD,'single_R.npy')); real=gstats(R); del R
real.to_csv(os.path.join(OUTD,'group_real.csv'),index=False)
nulls=[]
for seed in (1,2,3):
    flip=np.random.default_rng(seed).random(len(W))<0.5
    Rn=score(ptr,IDX,t,np.where(flip[:,None],W2,W),np.where(flip[:,None],K2,K),Q)
    g=gstats(Rn); g['seed']=seed; nulls.append(g); del Rn
N=pd.concat(nulls); N.to_csv(os.path.join(OUTD,'group_null.csv'),index=False)
def tail(D,lab):
    m=D.okfrac>0.5
    print(lab, 'groups', int(m.sum()), '| plateau>=0.3:', int((m&(D.plat>=0.3)).sum()), '>=0.5:', int((m&(D.plat>=0.5)).sum()),
          '>=0.7:', int((m&(D.plat>=0.7)).sum()), '| every-quarter plateau>=0.3:', int((m&(D.platq>=0.3)).sum()),
          '| median-over-exits >= x2:', int((m&(D.med>=2)).sum()), '>= x3:', int((m&(D.med>=3)).sum()), '| max med', round(float(D.med[m].max()),2))
tail(real,'real ')
for s in (1,2,3): tail(N[N.seed==s],f'flip{s}')
