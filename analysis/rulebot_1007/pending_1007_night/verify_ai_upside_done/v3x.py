import sys, site
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
T = pd.read_csv(sys.argv[1], usecols=["run","timeframe","entry_time","exit_time","kind","R"])
T = T[T.run.str.startswith("run-20261005T01")]
nfp = pd.Timestamp("2026-10-02T12:30Z").value // 10**6; H = 3_600_000
w = (T.entry_time >= nfp) & (T.entry_time < nfp + 2*H)
held = (T.entry_time < nfp) & (T.exit_time > nfp)
print("v3a NFP: entered within 2h n", w.sum(), round(T[w].R.mean(),3), "| held through n", held.sum(), round(T[held].R.mean(),3), "| other n", (~w & ~held).sum(), round(T[~w & ~held].R.mean(),3))
print("  excl 5m within2h", round(T[w & (T.timeframe!='5m')].R.mean(),3), (w & (T.timeframe!='5m')).sum())
# skipped vs entered cluster bootstrap (v3sig + outcomes), 15m
R = pd.read_csv(sys.argv[2]); R = R[R.base_st.isin(["T","U"])]
outs=[]
for r,n in (("v3b","run-20261005T183457Z"),("v4","current")):
    o=pd.read_csv(f"{sys.argv[3]}/{n}/outcomes.csv",usecols=["account_id","sig_ts","symbol","status","reason"]); o["run"]=r; outs.append(o)
O=pd.concat(outs).drop_duplicates(["run","account_id","sig_ts","symbol"])
R["account_id"]=R.strategy+"@"+R.timeframe; R["sig_ts"]=R.bar_close-1
R=R.merge(O,on=["run","account_id","sig_ts","symbol"],how="left")
R["grp"]=np.where(R.status=="ENTERED","E",np.where((R.status=="SKIPPED")&(R.reason=="in position"),"S","x"))
R["cl"]=R.run+"|"+(R.bar_close//H).astype(str)
rng=np.random.default_rng(5)
for k in ("strategy","ds200"):
    g=R[(R.kind==k)&(R.timeframe=="15m")&R.grp.isin(["E","S"])]
    gi={c:x for c,x in g.groupby("cl")}; keys=list(gi); bs=[]
    for _ in range(1000):
        s=pd.concat([gi[keys[j]] for j in rng.integers(0,len(keys),len(keys))]); bs.append(s[s.grp=="S"].base_R.mean()-s[s.grp=="E"].base_R.mean())
    print(k,"15m skipped-minus-entered",round(g[g.grp=="S"].base_R.mean()-g[g.grp=="E"].base_R.mean(),3),"CI",np.round(np.percentile(bs,[2.5,97.5]),3),"clusters",len(keys))
