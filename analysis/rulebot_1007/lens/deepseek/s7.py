C=pd.read_csv('out/cards_deepseek_raw.csv')
print(C[C.rp_bh_q_lt0<0.2][['definition','timeframe','rp_traded','rp_G','rp_mean_R','rp_lo','rp_hi','rp_p_lt0','rp_bh_q_lt0','rp_p_gt0_4h']].sort_values('rp_bh_q_lt0').to_string())
print(C.rp_p_gt0.notna().sum(), (C.rp_p_gt0<0.05).sum(), (C.rp_p_lt0<0.05).sum())
print(C[C.rp_p_gt0<0.10][['definition','timeframe','rp_traded','rp_G','rp_mean_R','rp_p_gt0','rp_bh_q_gt0']])
