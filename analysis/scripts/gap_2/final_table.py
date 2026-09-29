import glob, numpy as np, pandas as pd
pd.set_option("display.width",300)
D=pd.concat([pd.read_csv(f) for f in glob.glob("../out/sign_*.csv")+glob.glob("../out/drift_*.csv")],ignore_index=True)
D["fwdk"]=np.where(D.k==16,D.fwd16_pct,D.fwd64_pct); D["zk"]=np.where(D.k==16,D.fwd16_z,D.fwd64_z)
D["grp"]=np.where(D.family.isin(["FIXED9","TRAIL2","LADDER2"]),"GRID13",D.family)
A=pd.read_csv("../out/analytic.csv")
def first50(g, col):
    g=g.sort_values("dial"); ok=g[g[col]>=0.5]
    return ok.fwdk.iloc[0] if len(ok) else np.nan
def last0(g,col):
    g=g.sort_values("dial"); z=g[g[col]==0]
    # largest planted drift with 0 passes that is below first50
    f=first50(g,col)
    z=z[z.fwdk<f] if np.isfinite(f) else z
    return z.fwdk.iloc[-1] if len(z) else np.nan
rows=[]
for (tf,orc,k),g in D.groupby(["tf","oracle","k"]):
    cell=g.groupby("dial").agg(fwdk=("fwdk","mean"),zk=("zk","mean")).reset_index()
    for grp in ["FIXED9","TRAIL2","LADDER2","GRID13","TIME16","TIME64"]:
        col="family" if grp!="GRID13" else "grp"
        pr=g[g[col]==grp].groupby(["dial","seed"]).passed.max().groupby("dial").mean().rename(grp)
        cell=cell.merge(pr.reset_index(),on="dial")
    r=dict(tf=tf,oracle=orc,k=k,hours=k*{"5m":5,"15m":15,"1h":60}[tf]/60,
           cost=0.14+0.01*k*{"5m":5,"15m":15,"1h":60}[tf]/480,
           analytic_TIME=A[(A.tf==tf)&(A.H==k)].mu_star_pct.iloc[0])
    for grp in ["TIME16" if k==16 else "TIME64","GRID13","FIXED9","TRAIL2","LADDER2"]:
        r[("TIMEk" if grp.startswith("TIME") else grp)+"_50"]=first50(cell,grp)
        r[("TIMEk" if grp.startswith("TIME") else grp)+"_last0"]=last0(cell,grp)
    ok=cell[cell.zk>=3.2].sort_values("dial"); r["gate_z3.2"]=ok.fwdk.iloc[0] if len(ok) else np.nan
    r["max_tested"]=cell.fwdk.max()
    rows.append(r)
T=pd.DataFrame(rows)
T["grid_over_time"]=T.GRID13_50/T.TIMEk_50
T.to_csv("../out/final_thresholds.csv",index=False)
c=["tf","oracle","k","hours","cost","gate_z3.2","analytic_TIME","TIMEk_last0","TIMEk_50","GRID13_last0","GRID13_50","FIXED9_50","TRAIL2_50","LADDER2_50","max_tested","grid_over_time"]
print(T[c].round(3).to_string(index=False))
