import numpy as np
rng=np.random.default_rng(7)
def sim(mean,tpd=4,days=75,risk=0.01,sims=20000,daycap=-3.0,review=-0.15):
    p=(1.2+mean)/2.0
    hit_rev=np.zeros(sims,bool); day_rev=np.full(sims,np.nan); daycap_days=0; tot_days=0; halved=0
    for s in range(sims):
        eq=1.0
        for d in range(days):
            n=rng.poisson(tpd); dsum=0.0
            for t in range(n):
                if dsum<=daycap: break
                r=0.8 if rng.random()<p else -1.2
                dsum+=r; eq*=1+risk*r
            daycap_days+= dsum<=daycap; tot_days+=1
            if not hit_rev[s] and eq<=1+review: hit_rev[s]=True; day_rev[s]=d+1
        halved+= eq<=0.5
    return hit_rev, day_rev, daycap_days/tot_days, halved/sims
for mean in (-0.17,-0.05,0.0,0.05,0.10):
    h,dr,dc,hv=sim(mean,sims=4000)
    by30=np.mean(dr<=30); by75=h.mean()
    print('mean %+.2f: P(-15%% by d30) %.2f, by d75 %.2f, median day %s; share of days hitting -3R daily cap %.3f; P(eq<=50%% at d75) %.3f'%(mean,by30,by75,np.nanmedian(dr) if h.any() else 'na',dc,hv))
