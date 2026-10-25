"""The owners' example: V3.9 as the trend judge + an entry strategy. (1) how many 'all wins, >= 30 trades' configs the
real directions give vs coin-flip directions; (2) the best V3.9-filtered entries over 5 years / 2026."""
import os, sys, json
import numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
pre=open(os.path.join(HERE,'hb_eval.py')).read().split('t0 = time.time()')[0]
exec(pre.replace("cache=True","cache=False"))
Gd=pd.DataFrame(groups,columns=['cell','mode','filter']); v39=Gd['filter'].str.startswith('V39').to_numpy()
def perfect(R,mask):
    n=R[:,:,2]; wn=R[:,:,3]; ok=(n>=30)&(wn==n)&(R[:,:,6]>=8)&(R[:,:,7]>=8)
    return int(ok[mask].any(axis=1).sum()), int(ok[mask].sum())
R=np.load(os.path.join(OUTD,'single_R.npy'))
print('real : groups with a >=30-trade all-win exit (V39 filters / all):',perfect(R,v39),perfect(R,np.ones(len(Gd),bool)))
F_=np.load(os.path.join(OUTD,'fwd.npz')); W2=F_['W2'][order]; K2=F_['K2'][order]
for seed in (1,2,3):
    flip=np.random.default_rng(seed).random(len(W))<0.5
    Rn=score(ptr,IDX,t,np.where(flip[:,None],W2,W),np.where(flip[:,None],K2,K),Q)
    print(f'flip{seed}:',perfect(Rn,v39),perfect(Rn,np.ones(len(Gd),bool)),flush=True)
# top V39-filtered entries: >= 25 trades, both halves >= x2, ladder exits only (runs with a filter added in code)
EX=pd.read_csv(os.path.join(OUTD,'exits.csv'))
lad=EX.name.str.contains('익절 없음')&EX.name.str.contains('계단 12')
rows=[]
for g in np.flatnonzero(v39):
    for x in np.flatnonzero(lad.to_numpy()):
        r=R[g,x]
        if r[2]>=25 and r[6]>=8 and r[7]>=8 and min(r[4],r[5])>=2:
            rows.append((g,x,r[0],r[4],r[5],int(r[2]),r[3]/r[2]))
T=pd.DataFrame(rows,columns=['g','x','eq','h1','h2','n','win']).join(Gd,on='g')
T['xname']=EX.name.to_numpy()[T.x]
T=T.sort_values('eq',ascending=False).drop_duplicates('cell')
pd.set_option('display.width',220)
print(T.head(15).round(2).to_string())
T.head(15).to_csv(os.path.join(OUTD,'v39_entries.csv'),index=False)
