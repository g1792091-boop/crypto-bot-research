F5='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/out5y/fiveyear_signals.csv.gz'
X=pd.read_csv(F5)
X.to_parquet if False else None
print(len(X), X.columns.tolist()); print(X.R.notna().mean())
print(X.groupby(['tf']).agg(n=('R','size'),R=('R','mean'),roe=('roe','mean')))
print(X.groupby('reason').R.describe())
print(X.lev.value_counts().head())
z=np.load('/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/binance/signals/sig_30m_BTCUSD.npz')
ts=z['ts']; 
x=X[(X.tf=='30m')&(X.coin=='BTCUSD')]
k='s__'+x.strategy.iloc[0]; sg=z[k]; idx=x[x.strategy==x.strategy.iloc[0]].bar.values
print('side match',np.mean(sg[idx]==x[x.strategy==x.strategy.iloc[0]].side.values), 'stop_pct match',np.nanmax(np.abs(200*z['atr'][idx]/z['c'][idx]-x[x.strategy==x.strategy.iloc[0]].stop_pct.values)))
print('first/last date',pd.to_datetime(X.close_t.min(),unit='ms'),pd.to_datetime(X.close_t.max(),unit='ms'))
X[['strategy','coin','tf','close_t','side','R','roe','lev','n_same','n_opp','ema_dist','age','dip','dim','adx','box_pos','range_pos','er','htf_pos','kst_hour','stop_pct']].to_pickle('/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2/fy.pkl')
