import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
import math
OUT=sys.argv[0].rsplit("/",1)[0]
TK,SL=0.0005,0.0002; RT=2*(TK+SL); MIN=60000; FUND=8*3600000
def lock_for(best):
    if best<0.12-1e-12: return None
    return 0.10+0.05*math.floor((best-0.12)/0.05+1e-9)
def sim(B,sym,t0,side,ref,stop,lev):
    ts,o,h,l,c=B[sym]; i=int(np.searchsorted(ts,t0))
    if i>=len(ts) or ts[i]-t0>2*MIN: return None
    fill=ref*(1+side*SL); sd=abs(fill-stop); best=fill; worst=fill; lk=None
    for j in range(i,len(ts)):
        ex=None
        if j>i and (o[j]-stop)*side<=0: ex=o[j]
        elif (l[j]<=stop) if side>0 else (h[j]>=stop): ex=stop
        worst=min(worst,l[j]) if side>0 else max(worst,h[j])
        if ex is not None:
            px=ex*(1-side*SL)
            return dict(st='T',R=(side*(px-fill)-TK*(fill+px))/sd,xt=int(ts[j]+MIN),mfe=side*(best-fill)/sd,mae=side*(worst-fill)/sd)
        best=max(best,h[j]) if side>0 else min(best,l[j])
        k=lock_for(lev*(side*(best/fill-1)-RT))
        if k is not None and (lk is None or k>lk+1e-12):
            cand=fill*(1+side*(k/lev+RT)); stop=max(stop,cand) if side>0 else min(stop,cand); lk=k
    return dict(st='U',R=(side*(c[-1]-fill)-TK*(fill+c[-1]))/sd,xt=int(ts[-1]+MIN),mfe=side*(best-fill)/sd,mae=side*(worst-fill)/sd)
rows=[];END={};START={}
for run in ['v3b','v4']:
    b=rd(run,'live_bars.csv',usecols=['ts','symbol','open','high','low','close']).sort_values(['symbol','ts'])
    B={s:(g.ts.to_numpy(np.int64),g.open.to_numpy(),g.high.to_numpy(),g.low.to_numpy(),g.close.to_numpy()) for s,g in b.groupby('symbol')}
    START[run]=int(b.ts.min()); END[run]=int(b.ts.max())+MIN
    o=rd(run,'outcomes.csv').merge(rd(run,'accounts.csv')[['account_id','kind']],on='account_id')
    o=o[o.kind.isin(['strategy','ds200'])&o.sig_timeframe.isin(['15m','30m','1h','4h'])]
    for r in o.itertuples():
        sd=r.stop_dist if r.stop_dist==r.stop_dist else 2*r.sig_atr; side=int(r.sig_side)
        x=sim(B,r.symbol,int(r.step_ts),side,r.ref_price,r.ref_price-side*sd,30)
        if x is None: continue
        ok20=(r.ref_price*(1/20-0.005)-sd)>=max(r.sig_atr,0.002*r.ref_price)
        x.update(run=run,kind=r.kind,strategy=r.sig_strategy_id,tf=r.sig_timeframe,symbol=r.symbol,bc=int(r.step_ts),side=side,ok20=ok20,status=r.status,reason=r.reason)
        rows.append(x)
D=pd.DataFrame(rows); D.to_csv(f'{OUT}/ai_sig3.csv',index=False)
# calibrate ok20 against live 4h sizing outcomes (ENTERED vs REJECTED)
c=D[(D.tf=='4h')&D.status.isin(['ENTERED','REJECTED'])]; print('4h ok20 vs live', pd.crosstab(c.ok20,c.status).to_dict())
print('4h share ok20 by kind', D[D.tf=='4h'].groupby('kind').ok20.mean().round(3).to_dict())
DAYS={r:(END[r]-START[r])/86400000 for r in END}; TD=sum(DAYS.values()); print('days',DAYS)
TFR={'4h':0,'1h':1,'30m':2,'15m':3}
def trader(g,run):
    g=g.sort_values(['bc']).assign(r=g.tf.map(TFR)).sort_values(['bc','r'])
    free=-1; held=None; n=0; wf=0; wh_any=0; wh_opp=0; ev=0; busy=0
    for bc,grp in g.groupby('bc',sort=True):
        if bc>=free:
            wf+=1; x=grp.iloc[0]; n+=1; free=x.xt; held=(x.symbol,x.side)
            busy+=min(x.xt,END[run])-bc
            ev+=int(max(abs(x.mfe),abs(x.mae))>=0.5)+int(x.mae<=-0.7)+len(range((bc-10*MIN)//FUND+1,(x.xt-10*MIN)//FUND+1))
        else:
            wh_any+=1; wh_opp+=int(((grp.symbol==held[0])&(grp.side==-held[1])).any())
    return dict(n=n,wf=wf,wh_any=wh_any,wh_opp=wh_opp,ev=ev,busy=busy)
SC={'A_15m30m':lambda d:d.tf.isin(['15m','30m']),'B_15m30m1h':lambda d:d.tf.isin(['15m','30m','1h']),
    'C_15m30m1h+4h20x':lambda d:d.tf.isin(['15m','30m','1h'])|((d.tf=='4h')&d.ok20)}
res=[]
for sc,f in SC.items():
    for (k,s),g in D[f(D)].groupby(['kind','strategy']):
        tot=dict(n=0,wf=0,wh_any=0,wh_opp=0,ev=0,busy=0)
        for run,gg in g.groupby('run'):
            for kk,v in trader(gg,run).items(): tot[kk]+=v
        tot.update(sc=sc,kind=k,strategy=s); res.append(tot)
R=pd.DataFrame(res); R['TD']=np.where(R.kind=='ds200',DAYS['v4'],TD)
for c_ in ['n','wf','wh_any','wh_opp','ev']: R[c_+'_d']=R[c_]/R.TD
R['busy_sh']=R.busy/(R.TD*86400000)
R['calls_event']=R.wf_d+R.wh_opp_d+R.ev_d
R['calls_event_anysig']=R.wf_d+R.wh_any_d+R.ev_d
R['calls_scan']=R.calls_event+6*(1-R.busy_sh)
R['calls_15mchk']=R.calls_scan+96*R.busy_sh
R.to_csv(f'{OUT}/ai_trader3.csv',index=False)
for sc in SC:
    for k in ['strategy','ds200']:
        x=R[(R.sc==sc)&(R.kind==k)&(R.n>0)]
        q=lambda c_: f"{x[c_].median():.1f} [{x[c_].quantile(.1):.1f}-{x[c_].quantile(.9):.1f}]"
        print(sc,k,'units',len(x),'trades/d',q('n_d'),'>=1/d',int((x.n_d>=1).sum()),'busy',round(x.busy_sh.median(),2),'calls/d event',q('calls_event'),'event+anysig',q('calls_event_anysig'),'+scan',q('calls_scan'),'+15mchk',q('calls_15mchk'))
        for lab,cc in [('event','calls_event'),('event_anysig','calls_event_anysig'),('scan','calls_scan'),('15mchk','calls_15mchk')]:
            m=x[cc].median()*30.4; print('   ',lab,'calls/month/trader',round(m),'30 traders $',round(30*m*0.016),'-',round(30*m*0.030))
