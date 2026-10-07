import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from mysim import *
OUT=os.path.dirname(os.path.abspath(__file__))
TFM={"15m":15,"30m":30,"1h":60,"4h":240}
rows=[]
for lab in ["v3b","v4"]:
    B=bars_by_symbol(lab); s=load(lab,"signal_log"); s=s[(s.status=="SUBMITTED")&s.atr.notna()]
    chk=s.groupby(["timeframe","symbol","bar_close"]).atr.agg(lambda x: x.max()/x.min()-1)
    print(lab,"ATR shared across strategies? max rel spread",chk.max())
    t0=min(v[0][0] for v in B.values()); t1=max(v[0][-1] for v in B.values())
    for tf,m in TFM.items():
        step=m*MIN; a=s[s.timeframe==tf].groupby(["symbol","bar_close"]).atr.median().reset_index()
        for sym in B:
            aa=a[a.symbol==sym].sort_values("bar_close")
            if not len(aa): continue
            bca,ata=aa.bar_close.to_numpy(),aa.atr.to_numpy()
            ts,o,_,_,_=B[sym]; om=dict(zip(ts,o))
            bc=(t0//step+1)*step
            while bc<=t1-2*MIN:
                if bc in om:
                    j=int(np.argmin(np.abs(bca-bc))); atr=ata[j]; ref=om[bc]; sd=2*atr
                    for side in (1,-1):
                        lev=None
                        for L in (30,20):
                            liqd=1/L-0.005; room=(liqd*ref - sd)
                            if room>=max(1.0*atr,0.002*ref): lev=L;break
                        if lev is None:
                            rows.append(dict(run=lab,tf=tf,symbol=sym,bc=bc,side=side,status="REJECTED")); continue
                        x=sim(B,sym,bc,side,ref,sd,lev)
                        if x: x.update(run=lab,tf=tf,symbol=sym,bc=bc,side=side,lev=lev,atr_gap=abs(bca[j]-bc)/MIN); rows.append(x)
                bc+=step
D=pd.DataFrame(rows); D.to_csv(f"{OUT}/cf_mine_rows.csv",index=False)
D["blk"]=D.bc//(4*3600*1000)
rng=np.random.default_rng(1)
def bootci(g,col="R",nb=2000):
    blks=g.blk.unique(); gs={b:g[g.blk==b][col].to_numpy() for b in blks}
    ms=[]
    for _ in range(nb):
        pick=rng.choice(blks,len(blks)); v=np.concatenate([gs[b] for b in pick]); ms.append(v.mean())
    return np.percentile(ms,[2.5,97.5])
out=[]
for key,g in list(D.groupby(["tf"]))+list(D.groupby(["run","tf"])):
    tr=g[g.status=="TRADED"]
    ci=bootci(tr) if tr.blk.nunique()>1 else [np.nan,np.nan]
    out.append(dict(key=str(key),n_rows=len(g),n_traded=len(tr),n_unres=(g.status=="UNRESOLVED").sum(),n_rej=(g.status=="REJECTED").sum(),blocks=tr.blk.nunique(),
        mean_R=tr.R.mean(),ci_lo=ci[0],ci_hi=ci[1],sd=tr.R.std(),cost_R=tr.cost_R.mean(),gross=(tr.R+tr.cost_R).mean(),
        long=tr[tr.side>0].R.mean(),short=tr[tr.side<0].R.mean(),incl_unres=g[g.status!="REJECTED"].R.mean()))
O=pd.DataFrame(out); print(O.round(3).to_string()); O.to_csv(f"{OUT}/cf_mine_summary.csv",index=False)
