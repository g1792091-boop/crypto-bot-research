import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
import json, math
OUT=sys.argv[0].rsplit("/",1)[0]
TK,SL=0.0005,0.0002; RT=2*(TK+SL); MIN=60000
TFM={'15m':15,'30m':30,'1h':60,'4h':240}
def bars(run):
    b=rd(run,'live_bars.csv',usecols=['ts','symbol','open','high','low','close']).sort_values(['symbol','ts'])
    return {s:(g.ts.to_numpy(np.int64),g.open.to_numpy(),g.high.to_numpy(),g.low.to_numpy(),g.close.to_numpy()) for s,g in b.groupby('symbol')}
def lock_for(best):
    if best<0.12-1e-12: return None
    return 0.10+0.05*math.floor((best-0.12)/0.05+1e-9)
def sim(B,sym,t0,side,ref,stop,lev):
    ts,o,h,l,c=B[sym]; i=int(np.searchsorted(ts,t0))
    if i>=len(ts) or ts[i]-t0>2*MIN: return None
    fill=ref*(1+side*SL); sd=abs(fill-stop); best=fill; lk=None
    for j in range(i,len(ts)):
        ex=None
        if j>i and (o[j]-stop)*side<=0: ex=o[j]
        elif (l[j]<=stop) if side>0 else (h[j]>=stop): ex=stop
        if ex is not None:
            px=ex*(1-side*SL); R=(side*(px-fill)-TK*(fill+px))/sd
            return ('T',R,(TK*(fill+px)+SL*ref+SL*ex)/sd,ts[j]+MIN-1,(ts[j]-t0)/MIN,'LOCK' if lk is not None else 'SL')
        best=max(best,h[j]) if side>0 else min(best,l[j])
        k=lock_for(lev*(side*(best/fill-1)-RT))
        if k is not None and (lk is None or k>lk+1e-12):
            cand=fill*(1+side*(k/lev+RT)); stop=max(stop,cand) if side>0 else min(stop,cand); lk=k
    px=c[-1]; return ('U',(side*(px-fill)-TK*(fill+px))/sd,np.nan,np.nan,(ts[-1]-t0)/MIN,'OPEN')
def sizable(ref,atr,stop_dist,lev,mmr=0.005):
    room=ref*(1/lev-mmr)-stop_dist
    return room>=max(atr,0.002*ref)
val=[];cf=[];sg=[]
for run in ['v3b','v4']:
    B=bars(run); a=rd(run,'accounts.csv')[['account_id','kind']]
    o=rd(run,'outcomes.csv'); t=rd(run,'trades.csv').merge(a,on='account_id')
    # 1) validation vs live trades
    oe=o[o.status=='ENTERED'][['account_id','sig_ts','symbol','ref_price','sig_stop_price','step_ts']]
    tt=t[t.kind.isin(['strategy','ds200','random'])&(t.timeframe!='5m')].merge(oe,left_on=['account_id','signal_ts','symbol'],right_on=['account_id','sig_ts','symbol'])
    for r in tt.itertuples():
        x=sim(B,r.symbol,int(r.step_ts),int(r.side),r.ref_price,r.stop_initial,int(r.leverage))
        if x is None: continue
        val.append(dict(run=run,kind=r.kind,tf=r.timeframe,R_live=r.pnl/(r.qty*abs(r.entry_price-r.stop_initial)),R_my=x[1],st=x[0],same_exit=(x[0]=='T' and abs(x[3]-r.exit_time)<=MIN)))
    # 2) every SUBMITTED signal, own side and flipped, at 30x (also 50x own for best tier)
    s=o.merge(a,on='account_id'); s=s[s.kind.isin(['strategy','ds200'])&(s.sig_timeframe!='5m')]
    for r in s.itertuples():
        sd=r.stop_dist if r.stop_dist==r.stop_dist else 2*r.sig_atr
        for lab,side in (('own',int(r.sig_side)),('flip',-int(r.sig_side))):
            stop=r.ref_price-side*sd
            x=sim(B,r.symbol,int(r.step_ts),side,r.ref_price,stop,30)
            if x is None: continue
            sg.append(dict(run=run,kind=r.kind,strategy=r.sig_strategy_id,tf=r.sig_timeframe,symbol=r.symbol,bc=int(r.step_ts),side=side,which=lab,
                           out=r.status,reason=r.reason,st=x[0],R=x[1],cost_R=x[2],hold=x[4],ok20=sizable(r.ref_price,r.sig_atr,sd,20),ok30=sizable(r.ref_price,r.sig_atr,sd,30)))
    # 3) exhaustive coin flip: every tf bar close x coin x side, ATR from signal_log (any strategy, same coin/tf/bar), 30x->20x
    sl=rd(run,'signal_log.csv'); sl=sl[sl.status.isin(['SUBMITTED','RECORD'])&sl.atr.notna()]
    for tf,m in TFM.items():
        A=sl[sl.timeframe==tf].groupby(['symbol','bar_close']).atr.median()
        step=m*MIN
        for sym in B:
            if sym not in A.index.get_level_values(0): continue
            aa=A.loc[sym]; bca=aa.index.to_numpy(); ata=aa.to_numpy()
            ts,op=B[sym][0],B[sym][1]; om=dict(zip(ts,op))
            bc=(ts[0]//step+1)*step
            while bc<=ts[-1]-2*MIN:
                if bc in om:
                    j=int(np.argmin(np.abs(bca-bc))); atr=ata[j]; ref=om[bc]; sd=2*atr
                    for side in (1,-1):
                        lev=30 if sizable(ref,atr,sd,30) else (20 if sizable(ref,atr,sd,20) else None)
                        if lev is None: cf.append(dict(run=run,tf=tf,symbol=sym,bc=bc,side=side,st='REJ')); continue
                        x=sim(B,sym,bc,side,ref,ref-side*sd,lev)
                        if x: cf.append(dict(run=run,tf=tf,symbol=sym,bc=bc,side=side,lev=lev,st=x[0],R=x[1],cost_R=x[2],hold=x[4],atr_gap_bars=abs(bca[j]-bc)/step))
                bc+=step
pd.DataFrame(val).to_csv(f'{OUT}/val3.csv',index=False); pd.DataFrame(sg).to_csv(f'{OUT}/sig3.csv',index=False); pd.DataFrame(cf).to_csv(f'{OUT}/cf3.csv',index=False)
V_=pd.DataFrame(val); print('validation n',len(V_), V_.groupby('tf').apply(lambda g: pd.Series(dict(n=len(g),same=g.same_exit.mean(),corr=np.corrcoef(g.R_live,g.R_my)[0,1],md=(g.R_my-g.R_live).mean()))).round(3).to_string())
