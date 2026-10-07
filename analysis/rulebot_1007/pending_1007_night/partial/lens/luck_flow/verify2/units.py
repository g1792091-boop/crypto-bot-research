import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
OUT=os.path.dirname(os.path.abspath(__file__))
D=pd.read_csv(f"{OUT}/replay_sig_rows.csv"); C=pd.read_csv(f"{OUT}/cf_mine_rows.csv")
C=C[C.status=="TRADED"]
base=C.groupby(["run","tf","symbol","side"]).R.mean().rename("ss_cf").reset_index()
base2=C.groupby(["run","tf"]).R.mean().rename("uncond_cf").reset_index()
D=D.merge(base,on=["run","tf","symbol","side"],how="left").merge(base2,on=["run","tf"],how="left")
rng=np.random.default_rng(11)
def signflip_p(d,cl,nb=20000):
    g=pd.Series(d).groupby(cl).sum().to_numpy(); obs=g.sum()
    sims=(rng.choice([-1,1],size=(nb,len(g)))*g).sum(1); return (np.sum(sims>=obs)+1)/(nb+1)
def boot(d,cl,nb=4000):
    s=pd.DataFrame({"d":d,"c":cl}); gs=[x.d.to_numpy() for _,x in s.groupby("c")]
    if len(gs)<2: return (np.nan,np.nan)
    m=[np.concatenate([gs[i] for i in rng.integers(0,len(gs),len(gs))]).mean() for _ in range(nb)]
    return tuple(np.percentile(m,[2.5,97.5]))
def evaluate(g):
    p=g[(g.status=="TRADED")&(g.flip_status=="TRADED")]
    t=g[g.status=="TRADED"]
    if len(p)==0: return dict(n_pairs=0,n_traded=len(t))
    cl=(p.bc//3600000).to_numpy()
    d=(p.R-p.flip_R).to_numpy()/2   # half difference = chosen minus pair mean? use full excess as chosen - flip mean
    ex=(p.R-p.flip_R)
    tm=(t.R-t.ss_cf)
    out=dict(n_pairs=len(p),clusters=len(set(cl)),long=(p.side>0).mean(),chosen=p.R.mean(),flip=p.flip_R.mean(),
             excess=ex.mean(),p_excess=signflip_p(ex.to_numpy(),cl),
             n_traded=len(t),timing=tm.mean())
    lo,hi=boot(tm.to_numpy(),(t.bc//3600000).to_numpy()); out.update(timing_lo=lo,timing_hi=hi)
    for lab in ["v3b","v4"]:
        q=p[p.run==lab]; out["excess_"+lab]=(q.R-q.flip_R).mean() if len(q) else np.nan
        q=t[t.run==lab]; out["timing_"+lab]=(q.R-q.ss_cf).mean() if len(q) else np.nan
    return out
res=[]
for (k,s),g in D[D.tf.isin(["15m","30m"])].groupby(["kind","strategy"]):
    res.append(dict(kind=k,strategy=s,unit="15m+30m",**evaluate(g)))
for (k,s,tf),g in D[D.tf.isin(["1h","4h"])].groupby(["kind","strategy","tf"]):
    res.append(dict(kind=k,strategy=s,unit=tf,**evaluate(g)))
U=pd.DataFrame(res)
def bh(p):
    p=np.asarray(p,float); n=len(p); o=np.argsort(p); q=p[o]*n/np.arange(1,n+1); q=np.minimum.accumulate(q[::-1])[::-1]; out=np.empty(n); out[o]=np.minimum(q,1); return out
for unit in ["15m+30m"]:
    m=(U.unit==unit)&U.kind.isin(["strategy","ds200"])&U.p_excess.notna()
    U.loc[m,"bh_q"]=bh(U.loc[m,"p_excess"])
m=U.unit.isin(["1h","4h"])&U.kind.isin(["strategy","ds200"])&U.p_excess.notna()
U.loc[m,"bh_q"]=bh(U.loc[m,"p_excess"])
U.to_csv(f"{OUT}/units_v.csv",index=False)
pd.set_option("display.width",300); pd.set_option("display.max_rows",400)
cols=["kind","strategy","unit","n_pairs","clusters","long","chosen","flip","excess","p_excess","bh_q","timing","timing_lo","timing_hi","excess_v3b","excess_v4","timing_v3b","timing_v4"]
print(U[U.unit=="15m+30m"].sort_values("p_excess")[cols].round(3).to_string())
print(U[U.unit!="15m+30m"].sort_values("p_excess")[cols].head(15).round(3).to_string())
