O='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/rb_analyze/out_real/'
r=pd.read_csv(O+'replay_signals.csv')
d=r[r.kind=='ds200']
print(d.shape, d.run.unique())
print(d.status.value_counts())
print(d.groupby('timeframe').status.value_counts().unstack())
print(d[['bar_close','sig_ts','entry_time','exit_time']].head())
print(d.strategy.nunique(), d.groupby(['strategy','timeframe']).size().shape)
print(d.acct_status.value_counts(), d.acct_reason.value_counts())
# duplicates: same signal across accounts? 
print(d.groupby(['strategy','timeframe','symbol','bar_close','side']).size().max())
print(d.columns.tolist())
