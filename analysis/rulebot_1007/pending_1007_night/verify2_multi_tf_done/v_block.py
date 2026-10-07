import os, sys
sys.path[:0]=['/root/.local/lib/python3.11/site-packages']
import numpy as np, pandas as pd
V=sys.argv[1]
bl=pd.read_csv(os.path.join(V,"v_blocked.csv.gz")); tr=pd.read_csv(os.path.join(V,"v_trades.csv.gz"))
for grp,pre in (("core",False),("ds",True)):
    b=bl[(bl.strat.str.startswith("F"))==pre]; t=tr[(tr.strat.str.startswith("F"))==pre]
    x=b[(b.combo=="ALL|FC|coin_short")&(~b.tie)&(b.tf<=1)]
    print(grp,"ALL|FC low-tf blocked n",len(x),"share by 1h/4h holds %.3f"%(x.held_tf>=2).mean())
    y=x[x.tf==0]
    print("  15m blocked R by held tf:", y.groupby("held_tf").R.agg(["mean","size"]).round(3).to_dict())
    for c in ("A|FC|coin_short","ALL|SWH|long_first","HI|FC|coin_short"):
        bb=b[(b.combo==c)&(~b.tie)]; tt=t[t.combo==c]
        s=" ".join(f"tf{k}: blocked {bb[bb.tf==k].R.mean():+.3f} taken {tt[tt.tf==k].aloneR.mean():+.3f}" for k in sorted(tt.tf.unique()))
        print(" ",c,s)
    # cluster-aware MDE: design effect from weekly sums
    for c in ("A|FC|coin_short","ALL|SWH|long_first","HI|FC|coin_short"):
        effs=[]; sds=[]
        for nm,g in t[t.combo==c].groupby("strat"):
            g=g.assign(wk=g.e//(96*7)); r=g.R-g.R.mean()
            ws=r.groupby(g.wk).sum(); nw=g.groupby("wk").size()
            deff=(ws**2).sum()/(r**2).sum()
            effs.append(deff); sds.append(g.R.std())
        tpd=t[t.combo==c].groupby("strat").size().mean()/1094
        n=tpd*60; sd=np.mean(sds); de=np.mean(effs)
        print("  MDE60",c,"tpd %.2f sd %.2f iid %.3f deff %.2f clustered %.3f"%(tpd,sd,2.80*sd/np.sqrt(n),de,2.80*sd*np.sqrt(de)/np.sqrt(n)))
