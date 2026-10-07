VD='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/'
D=pd.read_csv(VD+'verify2/my_signals.csv.gz',low_memory=False)
M=pd.read_csv(VD+'out/signals_master.csv.gz',low_memory=False)[['run','sig_id','R','q_tier']]
J=D.merge(M,on=['run','sig_id'],suffixes=('','_their'))
for r,g in J.groupby('run'):
    ok=g.R.notna()&g.R_their.notna()
    print(r,len(g),ok.sum(),(g.R.notna()!=g.R_their.notna()).sum(),np.abs(g.R-g.R_their)[ok].max(),(g.qtier.fillna('x')!=g.q_tier.fillna('x')).sum())
# v3a leverage vs stop tertile at 15m/30m
x=D[(D.run=='v3a')&D.kind.eq('strategy')&D.timeframe.isin(['15m','30m'])&D.R.notna()]
x['st']=pd.qcut(x.stop_pct,3,labels=['tight','mid','wide'])
print(pd.crosstab([x.timeframe,x.st],x.lev))
v=D[(D.run!='v3a')&D.kind.eq('strategy')&D.timeframe.isin(['15m','30m'])&D.R.notna()]
print(pd.crosstab([v.run,v.timeframe],v.lev))
print(D[D.run=='v3a'].groupby('acct').apply(lambda g: pd.Series({'n':len(g),'R':g.R.notna().sum(),'unres':(g.shres==0).sum()})))
