E='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/export_1007'
o=pd.read_csv(E+'/run-20261005T014624Z/outcomes.csv',low_memory=False)
print(o.status.value_counts()); print(o[o.status=='SKIPPED'][['reason','sig_tier','detail']].head(5).to_string())
print(o[o.status=='SKIPPED'].reason.value_counts().head())
print(o.sig_tier.value_counts(dropna=False))
d=pd.read_csv(E+'/run-20261005T014624Z/d3_shadows.csv',low_memory=False)
s=d[d.kind=='skipped']; print(s.groupby('resolved').roe.describe()); print(s.data.value_counts().head(3)); print(s.day.value_counts())
