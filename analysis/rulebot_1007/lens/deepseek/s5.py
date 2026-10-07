o='out/'
t=pd.read_csv(o+'tf_summary_ds.csv'); print(t.round(4).to_string())
f=pd.read_csv(o+'family_tf.csv'); f=f[f.basis=='unique_signals']
print(f[['family','timeframe','definitions','n','mean_R','G','lo','hi','p_gt0','bh_q_gt0','p_gt0_4h','win_pct','mean_gross_R','mean_cost_R','H1_mean_R','H2_mean_R','H1_n','H2_n','sf_n','sf_excess_R','sf_p_better','signals_per_day','y_is_mean_pct_w','y_cf_mean_pct_w','y_pre_mean_pct_w','y_is_gross_pct_w','y_best_config_mean12','y_stage1','y_all3_positive']].sort_values(['timeframe','mean_R'],ascending=[True,False]).round(3).to_string())
