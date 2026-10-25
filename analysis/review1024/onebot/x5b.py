import sys, numpy as np
exec(open('/home/user/crypto-bot-research/analysis/review1024/onebot/onebot.py').read().split('res=[]')[0])
mem=[('V39_ALL@1h','B'),('N24_DMI@4h','S'),('N06_MACD_ORB@15m','S'),('N09_ALLIG_AROON@1h','S')]
_,_,n,took=run(mem); rr=r[took]; W=rr[rr>0]
allrows=np.concatenate([rows_of(m) for m in mem]); L=r[allrows][r[allrows]<=0]
print('loss pool (all member signals, not only taken):',len(L),'avg',round(L.mean()*100,2),'worst',round(L.min()*100,2),'| all-signal win',round((r[allrows]>0).mean(),3),'n',len(allrows))
days=(Z0-A0)/864e5; lam=n*30/days; rng=np.random.default_rng(11)
for p in (0.92,0.85,0.80,0.75,0.70):
    row=[]
    for E_ in (9,12,15,20):
        hit=bust=0; N=20000
        for _ in range(N):
            eq=1.0
            for w in rng.random(rng.poisson(lam))<p:
                eq*=max(1+E_*(W[rng.integers(len(W))] if w else L[rng.integers(len(L))]),0)
                if eq>=5: hit+=1; break
                if eq<=0.5: bust+=1; break
        row.append(f"{E_}x {hit/N:.0%}/{bust/N:.0%}")
    print(f"win {p:.0%}: "+' | '.join(row))
