O='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/rb_analyze/out_real/'
f=pd.read_csv(O+'fiveyear_ref.csv')
print(f.source.value_counts())
d=f[f.source.str.contains('deep',case=False)]
print(d.shape); print(d.variant.value_counts())
print(d.iloc[0].to_string())
v=pd.read_csv(O+'vs_fiveyear.csv'); vd=v[v.kind=='ds200']
print(vd.shape); print(vd.head(3).T)
