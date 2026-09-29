"""Pre-fetch power estimate for the full pre-registered rule (PF>=1.2, n>=100, mean>0, 3/3 symbols, null p<0.05).
Bootstrap from in-sample primary trades (demeaned per symbol, then shifted to a target mean);
null distribution approximated as Normal(null_mean, null_sd*sqrt(618/N)) from the IS null run."""
import numpy as np, pandas as pd, json
T=pd.read_csv("../out/IS_validation_primary_trades.csv"); R=json.load(open("../out/IS_validation_result.json"))
nm, nsd = R["null_mean_exp"], R["null_sd_exp"]; real=R["primary"]["exp_pct"]
eff=real-nm
rng=np.random.default_rng(1)
pools={s:(g.net.to_numpy()-g.net.mean()) for s,g in T.groupby("symbol")}
rows=[]
for months,per_sym in ((4.5,206),(9.2,420),(13.9,635)):
    N=3*per_sym; sd=nsd*np.sqrt(618/N); crit=nm+1.645*sd
    for label,frac in (("IS effect",1.0),("half",0.5),("zero",0.0)):
        mu=(nm+frac*eff)/100
        ok=0; okrule=0; okz=0
        for r in range(4000):
            xs=[rng.choice(pools[s],per_sym)+mu for s in pools]
            x=np.concatenate(xs); pf=x[x>0].sum()/-x[x<=0].sum(); pos=sum(v.sum()>0 for v in xs)
            rule=(pf>=1.2)&(x.mean()>0)&(pos==3)
            zz=x.mean()*100>crit
            ok+=rule&zz; okrule+=rule; okz+=zz
        rows.append(dict(months=months,trades=N,true_effect=label,true_mean_pct=round(mu*100,4),P_null_only=okz/4000,P_rule_only=okrule/4000,P_full_pass=ok/4000))
print(pd.DataFrame(rows).to_string(index=False))
