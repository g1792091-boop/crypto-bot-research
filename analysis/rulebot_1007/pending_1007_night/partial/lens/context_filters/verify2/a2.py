O='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/rb_analyze/out_real/'
te=pd.read_csv(O+'trades_enriched.csv',low_memory=False)
t=te[te.run=='run-20261005T014624Z']
print(pd.crosstab([t.symbol],[t.timeframe,t.leverage]))
print(t.groupby(['symbol','timeframe']).eq_before.describe()[['min','max']].head(12))
