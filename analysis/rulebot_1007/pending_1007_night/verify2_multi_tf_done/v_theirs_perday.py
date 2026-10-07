import os, sys
sys.path[:0]=['/root/.local/lib/python3.11/site-packages']
import numpy as np, pandas as pd
res = sys.argv[1]
DAYS = (pd.Timestamp("2026-09-30")-pd.Timestamp("2021-08-01")).days
C = ["A|FC","A|LTF","A|SWH","A|SW","ALL|FC","ALL|LTF","ALL|SWH","ALL|SW","HI|FC","ALLINF|FC"]
rows=[]
for fn in sorted(os.listdir(res)):
    z=np.load(os.path.join(res,fn)); nm=fn[:-4]
    for c in C:
        k=f"{c}|tr|R"
        if k not in z.files: continue
        R=z[k].astype(float); g=z[f"{c}|tr|gross"].astype(float)
        rows.append(dict(s=nm,grp="core" if nm.startswith("C__") else "ds",c=c,n=len(R),mR=R.mean(),Rday=R.sum()/DAYS,cday=(g-R).sum()/DAYS))
d=pd.DataFrame(rows)
print(d.groupby(["grp","c"])[["n","mR","Rday","cday"]].mean().round(3).to_string())
p=d.pivot_table(index=["grp","s"],columns="c",values="Rday")
for a,b in [("ALL|SWH","ALL|LTF"),("ALL|SWH","ALL|FC"),("A|SWH","A|FC"),("ALL|SWH","A|FC"),("ALL|LTF","A|FC")]:
    for grp in ("core","ds"):
        x=(p.loc[grp][a]-p.loc[grp][b]).dropna()
        print(grp,a,"-",b,"R/day diff mean %+.4f, better in %d/%d"%(x.mean(),(x>0).sum(),len(x)))
q=d.pivot_table(index=["grp","s"],columns="c",values="mR")
for grp in ("core","ds"):
    x=(q.loc[grp]["ALL|SWH"]-q.loc[grp]["ALL|LTF"]).dropna(); print(grp,"per-trade SWH-LTF %+.4f better %d/%d"%(x.mean(),(x>0).sum(),len(x)))
