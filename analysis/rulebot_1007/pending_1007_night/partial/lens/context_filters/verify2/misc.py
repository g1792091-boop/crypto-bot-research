sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2')
from lib import *
A=pd.read_csv(VD+'my_signals.csv.gz',low_memory=False)
x=A[A.kind.eq('strategy')&A.run.isin(['v3b','v4'])&A.R.notna()&A.timeframe.isin(['15m','30m'])]
print('lev by qtier (replay, v3b/v4 15m/30m core)'); print(pd.crosstab([x.run,x.qtier.fillna('NA')],x.lev))
y=A[A.kind.isin(['strategy','ds200'])&A.timeframe.isin(['15m','30m'])&A.regime.notna()]
print(pd.crosstab([y.run,y.kind,y.timeframe],y.htf_regime.fillna('NA')))
print(pd.crosstab([y.run,y.kind,y.timeframe],y.regime.fillna('NA')))
for c in ['sr_level_before_lock','sr_support_before_stop']:
    print(c); print(y.groupby(['run','timeframe'])[c].mean().round(3).to_string())
print(y.groupby(['run','timeframe']).sr_room.median().round(3).to_string())
# trades: real leverage of tier best in v3b/v4
TE=pd.read_csv('/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/rb_analyze/out_real/trades_enriched.csv',low_memory=False)
t=TE[TE.kind.eq('strategy')&(TE.run!='run-20261005T014624Z')]; print(pd.crosstab([t.run,t.tier],t.leverage))
