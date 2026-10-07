import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
pd.set_option('display.width',250)
OUT=sys.argv[0].rsplit("/",1)[0]
kt=[];acc_all=[]
for run in RUNS:
    a=rd(run,'accounts.csv'); s=rd(run,'signal_log.csv'); o=rd(run,'outcomes.csv'); t=rd(run,'trades.csv')
    start=a.created_ts.min(); end=max(o.step_ts.max(), s.bar_close.max())
    days=(end-start)/86400000
    s['account_id']=s.strategy+'@'+s.timeframe
    print(run,'days',round(days,4),'RECORD symbols',s[s.status=='RECORD'].symbol.value_counts().to_dict(), 'RECORD tf for non-XRP', s[(s.status=='RECORD')&(s.symbol!='XRPUSDT')].timeframe.value_counts().to_dict())
    # does every SUBMITTED signal map to an account?
    sub=s[s.status=='SUBMITTED']
    miss=set(sub.account_id)-set(a.account_id); print(' submitted w/o account', len(miss), list(miss)[:5])
    # outcome-signal 1:1?
    o['reason2']=o.status+':'+o.reason.str.replace(r'^reel:.*','reel',regex=True).str.replace('lower score than entered signal','lower')
    oc=o.pivot_table(index='account_id',columns='reason2',values='id',aggfunc='count',fill_value=0)
    A=a[['account_id','kind','strategy','timeframe']].set_index('account_id')
    A['sub']=sub.groupby('account_id').size(); A['rec']=s[s.status=='RECORD'].groupby('account_id').size()
    A=A.join(oc).fillna(0)
    A['trades']=t.groupby('account_id').size(); A['trades']=A.trades.fillna(0)
    A['run']=run; A['days']=days
    acc_all.append(A.reset_index())
    g=A.groupby(['kind','timeframe'])
    K=g.agg(acc=('sub','size'),sub=('sub','sum'),med_sub=('sub','median'),ent=('ENTERED:ok','sum'),inpos=('SKIPPED:in position','sum'),lower=('SKIPPED:lower','sum'),rej=('REJECTED:sizing','sum'),trades=('trades','sum'))
    K['per_acct_day']=K['sub']/K.acc/days; K['med_per_acct_day']=K.med_sub/days
    for c in ['ent','inpos','lower','rej']: K['sh_'+c]=(K[c]/K['sub']).round(3)
    K['run']=run; kt.append(K.reset_index())
KT=pd.concat(kt); print(KT[['run','kind','timeframe','acc','sub','per_acct_day','med_per_acct_day','sh_ent','sh_inpos','sh_lower','sh_rej','trades']].round(2).to_string())
AA=pd.concat(acc_all).fillna(0); AA.to_csv(f'{OUT}/flow_accounts3.csv',index=False)
# zero-trade causes
Z=AA[AA.trades==0].copy()
def cause(r):
    if r['sub']==0: return 'no_signal'+('(record-only rows)' if r['rec']>0 else '')
    if r['ENTERED:ok']>0: return 'open_at_end'
    if r['REJECTED:sizing']==r['sub']: return 'all_rejected_sizing'
    if r['REJECTED:sizing']>0: return 'rejected+lower'
    return 'other'
Z['cause']=Z.apply(cause,axis=1)
print(Z.groupby(['run','kind','cause']).size().to_string())
print('4h share', Z.groupby(['run','kind']).apply(lambda x: f"{(x.timeframe=='4h').sum()}/{len(x)}").to_dict())
print(Z[Z.cause.isin(['other','rejected+lower','no_signal(record-only rows)'])][['run','account_id','sub','rec','ENTERED:ok','REJECTED:sizing','SKIPPED:lower','SKIPPED:in position']].to_string())
Z.to_csv(f'{OUT}/zero3.csv',index=False)
