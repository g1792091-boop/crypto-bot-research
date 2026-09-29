"""Power with clustering: the null SD of the mean (0.0703% at 618 trades) exceeds the iid SE,
so add a common random mean shift per replicate with variance sd_null^2 - se_iid^2 (scaled 1/N)."""
import numpy as np, pandas as pd, json
T=pd.read_csv("../out/IS_validation_primary_trades.csv"); R=json.load(open("../out/IS_validation_result.json"))
nm, nsd = R["null_mean_exp"], R["null_sd_exp"]; real=R["primary"]["exp_pct"]; eff=real-nm
sig=T.net.std()*100; se618=sig/np.sqrt(618); extra618=np.sqrt(max(nsd**2-se618**2,0))
print(f"per-trade sd {sig:.3f}%  iid SE@618 {se618:.4f}%  null SD@618 {nsd:.4f}%  design effect {(nsd/se618)**2:.2f}")
rng=np.random.default_rng(2)
pools={s:(g.net.to_numpy()-g.net.mean()) for s,g in T.groupby("symbol")}
rows=[]
for months,per_sym in ((4.5,206),(9.2,420),(13.9,635)):
    N=3*per_sym; sd=nsd*np.sqrt(618/N); crit=nm+1.645*sd; extra=extra618*np.sqrt(618/N)
    for label,frac in (("IS effect",1.0),("3/4",0.75),("half",0.5),("zero",0.0)):
        mu=(nm+frac*eff)/100; ok=okr=okz=0
        for r in range(4000):
            c=rng.normal(0,extra)/100
            xs=[rng.choice(pools[s],per_sym)+mu+c for s in pools]
            x=np.concatenate(xs); pf=x[x>0].sum()/-x[x<=0].sum(); pos=sum(v.sum()>0 for v in xs)
            rule=(pf>=1.2)&(x.mean()>0)&(pos==3); zz=x.mean()*100>crit
            ok+=rule&zz; okr+=rule; okz+=zz
        rows.append(dict(months=months,trades=N,effect=label,mean_pct=round(mu*100,4),P_null=okz/4000,P_rule=okr/4000,P_full=ok/4000))
print(pd.DataFrame(rows).to_string(index=False))
