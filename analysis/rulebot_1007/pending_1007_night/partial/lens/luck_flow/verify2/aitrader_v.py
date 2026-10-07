"""Own simulation of one AI trader per strategy (one position at a time, takes the first executable signal while flat).
Variants: A=15m+30m, B=15m+30m+1h, C=B+4h signals executable at <=30x/20x. Exit = my own house-exit sim of that signal."""
import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
OUT=os.path.dirname(os.path.abspath(__file__))
D=pd.read_csv(f"{OUT}/replay_sig_rows.csv")
D=D[D.kind.isin(["strategy","ds200"])]
DAYS={"v3b":0.6979,"v4":1.5}
END={}
for lab in ["v3b","v4"]:
    b=load(lab,"live_bars"); END[lab]=int(b.ts.max())+60000
TFR={"4h":0,"1h":1,"30m":2,"15m":3}; TFM={"15m":15,"30m":30,"1h":60,"4h":240}
H=3600000; FUND=8*H
def run(g,lab,dedup):
    g=g.assign(r=g.tf.map(TFR)).sort_values(["bc","r","symbol"])
    free=-1; held=None; n=0; sigw=0; sw=0; ev=0; fu=0; busy=0; chk=0; last={}
    for bc,grp in g.groupby("bc",sort=True):
        if bc>=free:
            fresh=[r for r in grp.itertuples() if not (dedup and (r.symbol,r.side,r.tf) in last and bc-last[(r.symbol,r.side,r.tf)]<=dedup*TFM[r.tf]*60000)]
            for r in grp.itertuples(): last[(r.symbol,r.side,r.tf)]=bc
            if not fresh: continue
            sigw+=1
            ent=[r for r in fresh if r.status in ("TRADED","UNRESOLVED")]
            if not ent: continue
            r=ent[0]; n+=1
            xt=int(r.exit_time) if r.status=="TRADED" else END[lab]
            free=xt; held=(r.symbol,r.side); busy+=xt-bc
            ev+=int(max(abs(r.mfe_R),abs(r.mae_R))>=0.5)+int(r.mae_R<=-0.7)
            fu+=len(range((bc-600000)//FUND+1,(xt-600000)//FUND+1))
            chk+=(xt-bc)//(15*60000)
        else:
            for r in grp.itertuples():
                last[(r.symbol,r.side,r.tf)]=bc
            if any(r.symbol==held[0] and r.side==-held[1] for r in grp.itertuples()): sw+=1
    return dict(trades=n,sigw=sigw,sw=sw,ev=ev,fu=fu,busy_ms=busy,chk=chk)
VAR={"A_15m30m":["15m","30m"],"B_+1h":["15m","30m","1h"],"C_+1h+4h20x":["15m","30m","1h","4h"]}
rows=[]
names={k:sorted(D[D.kind==k].strategy.unique()) for k in ["strategy","ds200"]}
for k,runs in [("strategy",["v3b","v4"]),("ds200",["v4"])]:
    for s in names[k]:
        for vn,tfs in VAR.items():
            for dd in (0,4):
                tot=dict(trades=0,sigw=0,sw=0,ev=0,fu=0,busy_ms=0,chk=0); days=0
                for lab in runs:
                    days+=DAYS[lab]
                    g=D[(D.kind==k)&(D.strategy==s)&(D.run==lab)&D.tf.isin(tfs)&(D.status!="REJECTED")]
                    if len(g)==0: continue
                    x=run(g,lab,dd)
                    for c in tot: tot[c]+=x[c]
                rows.append(dict(kind=k,strategy=s,variant=vn,dedup=dd,days=days,**tot))
S=pd.DataFrame(rows)
S["trades_d"]=S.trades/S.days; S["busy"]=S.busy_ms/(S.days*86400000)
S["scan_ub_d"]=6*(1-S.busy.clip(0,1))
S["event_driven_d"]=(S.sigw+S.sw+S.ev+S.fu)/S.days
S["big_model_d"]=(S.sigw+S.sw+S.fu)/S.days   # events go to small model first per design 6-2
S["with_scans_d"]=S.event_driven_d+S.scan_ub_d
S["with_15mchk_d"]=S.with_scans_d+S.chk/S.days
S.to_csv(f"{OUT}/aitrader_v.csv",index=False)
pd.set_option("display.width",250)
for dd in (0,4):
    print("== dedup",dd)
    q=S[S.dedup==dd].groupby(["kind","variant"]).agg(n=("strategy","size"),med_trades=("trades_d","median"),p10=("trades_d",lambda x:x.quantile(.1)),p90=("trades_d",lambda x:x.quantile(.9)),
        share_ge1=("trades_d",lambda x:(x>=1).mean()),med_busy=("busy","median"),med_event=("event_driven_d","median"),med_big=("big_model_d","median"),med_scans=("with_scans_d","median"),med_chk=("with_15mchk_d","median"))
    print(q.round(2).to_string())
