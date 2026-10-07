d=pd.read_csv(args[0])
print(d.shape)
print(d.entry.nunique(), d.groupby('tf').entry.nunique().to_dict(), d.exit.value_counts().to_dict())
for c in ['stage1','stage1_top','stage2','stage3','x20_ok','candidate_20x','stage3_20x','bh12','candidate','weak_candidate','stage3_bonf','all3_positive']:
    print(c, d[c].sum())
print(d[d.stage1][['tf','entry','exit','is_n','is_mean_pct','is_p','cf_n','cf_mean_pct','cf_p','pre_n','pre_mean_pct','p12','boot_p12','stage1_top','stage2','x20_ok','max_lev']].to_string())
print(d[d.all3_positive][['tf','entry','exit','is_n','is_mean_pct','cf_mean_pct','pre_mean_pct','stage1','is_p']].to_string())
print(sorted(d.entry.unique()))
