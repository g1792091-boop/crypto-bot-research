import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
from scipy.stats import spearmanr
OR,E=sys.argv[1:3]
F=pd.read_csv(OR+'/fiveyear_ref.csv'); print(F.columns.tolist()); print(F.source.value_counts())
F=F[(F.source=='profiles_binance')&F.timeframe.isin(['15m','30m'])]
print('cells',len(F),' with signals',(F.n_signals>0).sum())
f=F[F.n_signals>0]
print('mean_ret_notional<0:',(f.mean_ret_notional<0).sum(),' t<-2:',(f.mean_roe_t<-2).sum(),' IS<0&CF<0:',((f.mean_roe_is<0)&(f.mean_roe_cf<0)).sum())
print('not negative cells:',f[f.mean_ret_notional>=0][['strategy','timeframe','n_signals','mean_ret_notional','mean_roe_t']].to_string())
print('t>=-2 cells:',f[f.mean_roe_t>=-2][['strategy','timeframe','n_signals','per_day','mean_ret_notional','mean_roe_t']].to_string())
print('median 5y net notional %', 100*f.mean_ret_notional.median(), ' median gross (+0.14%)', 100*(f.mean_ret_notional+0.0014).median())
# live per-notional by cell
A=pd.read_csv('my_es_rows_all.csv'); T=A[A.status=='TRADED'].copy()
T['rpl']=T.roe/T.lev
g=T.groupby(['strategy','tf']).agg(n=('R','size'),rpl=('rpl','mean')).reset_index()
m=g[g.n>=20].merge(F.rename(columns={'timeframe':'tf'}),on=['strategy','tf'])
print('cells n>=20:',len(m),' median live notional %',100*m.rpl.median(),' median 5y %',100*m.mean_ret_notional.median())
print('spearman live vs 5y notional',spearmanr(m.rpl,m.mean_ret_notional))
print('sd of 5y notional across those cells %',100*m.mean_ret_notional.std(),' sd live %',100*m.rpl.std())
# signals per day
RM=pd.read_csv(OR+'/runs_meta.csv').set_index('run')
cnt={}
for run in ['run-20261005T014624Z','run-20261005T183457Z','current']:
    s=pd.read_csv(f'{E}/{run}/signal_log.csv'); s=s[s.status=='SUBMITTED']
    cnt[run]=s.groupby(['strategy','timeframe']).size()
days=sum(RM.loc[r,'days'] for r in cnt)
print('days total',days)
tot=sum(c for c in cnt.values()).reindex(pd.MultiIndex.from_frame(F[['strategy','timeframe']]),fill_value=0) if False else None
rows=[]
for r_ in F.itertuples():
    n=sum(cnt[run].get((r_.strategy,r_.timeframe),0) for run in cnt)
    rows.append(dict(strategy=r_.strategy,tf=r_.timeframe,live=n/days,y5=r_.per_day))
S=pd.DataFrame(rows); s5=S[S.y5>0.5]
print('cells y5>0.5/day',len(s5),'spearman',spearmanr(s5.live,s5.y5)[0],' median ratio',(s5.live/s5.y5).median())
S.to_csv('my_sigperday.csv',index=False)
print(S.sort_values('live').head(18).round(2).to_string())
