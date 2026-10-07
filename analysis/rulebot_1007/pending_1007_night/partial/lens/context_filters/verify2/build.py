# Independent build of the live signal table. usage: python3 -I q.py build.py  (paths hard-coded below)
import json, os
SC='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad'
E=SC+'/export_1007'; O=SC+'/rb_analyze/out_real/'; REPO='/home/user/crypto-bot-research'
VD=SC+'/lens/context_filters/verify2'
sys.path.append(REPO); sys.path.insert(0, SC+'/rb_analyze')
import analyze as A
from paperbot.config import v3_settings, DEFAULT_TIERS
from paperbot.sizing import size_position
from paperbot.levrule import quality_score
brackets,_=A.make_brackets(None)
TE=pd.read_csv(O+'trades_enriched.csv',low_memory=False)
RP=pd.read_csv(O+'replay_signals.csv',low_memory=False)
specs=A.infer_specs(TE)
SW=v3_settings(leverage_rule='tier_walk',tiers=DEFAULT_TIERS,max_margin_frac=0.40,taker_fee=0.0005)
RUNS={'run-20261005T014624Z':'v3a','run-20261005T183457Z':'v3b','current':'v4'}
out=[]
for run,tag in RUNS.items():
    rd=E+'/'+run
    s=pd.read_csv(rd+'/signal_log.csv'); s=s[s.status=='SUBMITTED'].rename(columns={'id':'sig_id'})
    rows=[]
    for line in open(rd+'/signal_ctx.jsonl'):
        d=json.loads(line); c=d.get('ctx') or {}; sr=c.get('sr') if isinstance(c.get('sr'),dict) else {}
        r={'sig_id':int(d['id'])}
        for k in ['regime','htf_regime','er','box_pos','htf_box_pos','ema20_dist_atr','trend_age','range_pct','adx','di_plus','di_minus']:
            r[k]=c.get(k)
        for k in ['room','floor','level_before_lock','support_before_stop','breakout']:
            r['sr_'+k]=sr.get(k)
        st=c.get('strength')
        r['qtier']=quality_score(st,s.loc[s.sig_id==int(d['id']),'strategy'].iloc[0] if False else None,None).get('tier') if False else None
        r['_st']=json.dumps(st) if isinstance(st,dict) else None
        rows.append(r)
    cx=pd.DataFrame(rows)
    s=s.merge(cx,on='sig_id',how='left')
    s['qtier']=[quality_score(json.loads(x),a,b).get('tier') if isinstance(x,str) else None for x,a,b in zip(s._st,s.strategy,s.timeframe)]
    s=s.drop(columns='_st')
    s['account_id']=s.strategy+'@'+s.timeframe
    acc=pd.read_csv(rd+'/accounts.csv').set_index('account_id')
    s['kind']=[acc.at[a,'kind'] if a in acc.index else ('random' if a.startswith('RANDOM') else ('ds200' if a[0]=='F' and a[1].isdigit() else 'strategy')) for a in s.account_id]
    s['sig_ts']=s.bar_close-1
    oc=pd.read_csv(rd+'/outcomes.csv',low_memory=False)[['account_id','sig_ts','symbol','status']].rename(columns={'status':'acct'})
    oc=oc.drop_duplicates(['account_id','sig_ts','symbol'])
    s=s.merge(oc,on=['account_id','sig_ts','symbol'],how='left')
    s['run']=tag
    if tag=='v3a':
        te=TE[TE.run==run][['account_id','signal_ts','symbol','R','leverage']].rename(columns={'signal_ts':'sig_ts','R':'trR','leverage':'trlev'}).drop_duplicates(['account_id','sig_ts','symbol'])
        s=s.merge(te,on=['account_id','sig_ts','symbol'],how='left')
        sh=pd.read_csv(rd+'/d3_shadows.csv',low_memory=False); sh=sh[(sh.kind=='skipped')].drop_duplicates('key')
        p=sh.key.str.split('|',expand=True)
        sh=pd.DataFrame({'account_id':p[1].values,'symbol':p[2].values,'bar_close':p[3].astype('int64').values,'shroe':sh.roe.values,'shres':sh.resolved.values})
        s=s.merge(sh,on=['account_id','symbol','bar_close'],how='left')
        levs=[];Rs=[]
        for r in s.itertuples():
            lev=R=np.nan
            if r.acct=='SKIPPED' and r.shroe==r.shroe and r.symbol in brackets:
                fill=r.ref_price*(1+r.side*SW.slippage_frac); stop=r.ref_price-r.side*2*r.atr
                sp=specs.get(r.symbol,{})
                dd=size_position(SW,5000.0,int(r.side),fill,stop,'best',brackets[r.symbol],atr=r.atr,qty_step=sp.get('qty_step',0.0),min_notional=sp.get('min_notional',0.0))
                if dd.ok:
                    lev=dd.leverage; R=r.shroe*dd.margin/(dd.qty*abs(fill-stop))
            levs.append(lev); Rs.append(R)
        s['shlev']=levs; s['shR']=Rs
        s['R']=np.where(s.acct=='ENTERED',s.trR,np.where(s.acct=='SKIPPED',s.shR,np.nan))
        s['lev']=np.where(s.acct=='ENTERED',s.trlev,s.shlev)
        s['flipR']=np.nan
        s['src']=np.where(s.acct=='ENTERED','trade','shadow')
    else:
        rp=RP[RP.run==run][['sig_id','status','R','flip_R','flip_status','leverage']]
        s=s.merge(rp,on='sig_id',how='left',suffixes=('','_rp'))
        s['R']=np.where(s.status_rp=='TRADED',s.R,np.nan) if 'status_rp' in s else np.where(s['status_y']=='TRADED',s.R,np.nan)
        s['flipR']=np.where((s.flip_status=='TRADED'),s.flip_R,np.nan)
        s['lev']=s.leverage; s['src']='replay'
    out.append(s)
D=pd.concat(out,ignore_index=True)
D['stop_pct']=200*D.atr/D.ref_price
D['kst_hour']=((D.bar_close//3600000+9)%24).astype(int)
D['kst_day']=pd.to_datetime(D.bar_close+9*3600000,unit='ms').dt.strftime('%m-%d')
# evening id: KST date of the bar (sessions all within a day)
D.to_csv(VD+'/my_signals.csv.gz',index=False)
print(D.groupby(['run','kind','timeframe']).agg(n=('sig_id','size'),R=('R','count'),meanR=('R','mean')).to_string())
