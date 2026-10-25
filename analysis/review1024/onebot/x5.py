import sys, numpy as np
sys.argv=['x']; exec(open('/home/user/crypto-bot-research/analysis/review1024/onebot/onebot.py').read().split('res=[]')[0])
BOTS={'V39+숏3':[('V39_ALL@1h','B'),('N24_DMI@4h','S'),('N06_MACD_ORB@15m','S'),('N09_ALLIG_AROON@1h','S')],
      'V39혼자':[('V39_ALL@1h','B')]}
days=(Z0-A0)/864e5; rng=np.random.default_rng(7)
for name,mem in BOTS.items():
    _,_,n,took=run(mem); rr=r[took]; W=rr[rr>0]; L=rr[rr<=0]; lam=n*30/days
    print(name,'trades',n,'win',round(len(W)/n,3),'per30d',round(lam,1),'avg win',round(W.mean()*100,2),'avg loss',round(L.mean()*100,2) if len(L) else None)
    for p in (len(W)/n,0.85,0.80,0.75):
        row=[]
        for E_ in (9,12,15,20):
            hit=bust=0; N=20000
            for _ in range(N):
                k=rng.poisson(lam); eq=1.0
                wins=rng.random(k)<p
                for w in wins:
                    x_=W[rng.integers(len(W))] if w else (L[rng.integers(len(L))] if len(L) else 0)
                    eq*=max(1+E_*x_,0)
                    if eq>=5: hit+=1; break
                    if eq<=0.5: bust+=1; break
            row.append(f"{E_}x ×5 {hit/N:.0%} / -50% {bust/N:.0%}")
        print(f"  win {p:.0%}: "+' | '.join(row))
