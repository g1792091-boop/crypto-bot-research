J=pd.read_csv('/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/out/scan_directional.csv')
x=J[J.carried&J.test_testable&J.primary].sort_values('p_test_1s')
print(x[['direction','tf','feature','bucket','d_disc','se_disc','d_test','se_test','p_test_1s','p_test_1s_4h','test_q','replicated']].head(12).round(4).to_string(index=False))
for d,g in J[J.primary].groupby('direction'):
    print(d,int(g.disc_testable.sum()),int(g.carried.sum()),int((g.carried&g.test_testable).sum()),int((g.p_test_1s<0.05).sum()),int((g.test_q<0.05).sum()),int(g.replicated.sum()))
