O='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/rb_analyze/out_real/'
t=pd.read_csv(O+'trades_enriched.csv')
d=t[t.kind=='ds200']
print(d.shape)
x=d[['pnl','fees','funding','gross','cost_usd','slip_est_usd','R','cost_R','cost_all_R','risk_usd']].head()
print(x)
print(np.allclose(d.gross, d.pnl+d.fees+d.funding), np.allclose(d.gross, d.pnl+d.fees-d.funding))
print(np.allclose(d.cost_R, (d.fees+d.funding)/d.risk_usd))
r=pd.read_csv(O+'replay_signals.csv'); r=r[r.kind=='ds200']
print(r.symbol.value_counts())
print(r[r.status=='TRADED'].groupby('timeframe').leverage.value_counts())
print(r.exit_reason.value_counts())
