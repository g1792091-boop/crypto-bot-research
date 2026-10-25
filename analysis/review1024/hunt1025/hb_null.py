"""Luck baseline for the single-member search: same configs, but each signal's direction is a coin flip (own side or
the opposite side at the same entry). How many configs pass the same bars by chance?"""
import os, sys, numpy as np
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
src=open(os.path.join(HERE,'hb_eval.py')).read()
pre=src.split('t0 = time.time()')[0]
exec(pre.replace("cache=True", "cache=False"))
W2=np.load(os.path.join(OUTD,'fwd.npz'))['W2'][order]; K2=np.load(os.path.join(OUTD,'fwd.npz'))['K2'][order]
def summ(R):
    eq,dd,n,wn,e1,e2,n1,n2=(R[:,:,k] for k in range(8)); q=R[:,:,8:12]
    ok=(n>=10)&(n1>=4)&(n2>=4); allq=ok&(q.min(axis=2)>=1.0)
    return dict(x6=int((ok&(eq>=6)).sum()), both245=int((ok&(e1>=2.45)&(e2>=2.45)).sum()), allq=int(allq.sum()),
                allq_x6=int((allq&(eq>=6)).sum()), allq_x10=int((allq&(eq>=10)).sum()), best_weak=float(np.minimum(e1,e2)[allq].max()) if allq.any() else 0)
R=np.load(os.path.join(OUTD,'single_R.npy')); print('real      ',summ(R)); del R
for seed in (1,2,3):
    flip=np.random.default_rng(seed).random(len(W))<0.5
    Wr=np.where(flip[:,None],W2,W); Kr=np.where(flip[:,None],K2,K)
    print(f'coin flip {seed}',summ(score(ptr,IDX,t,Wr,Kr,Q)),flush=True)
