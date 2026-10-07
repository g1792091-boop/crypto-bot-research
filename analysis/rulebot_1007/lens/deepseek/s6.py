C=pd.read_csv('out/cards_deepseek_raw.csv')
C['def']=C.definition.str.slice(0,14)
cols=['def','sig_d','an','aR','n','unr','mR','G','lo','hi','p','q','p4','mRm','gR','xb','h1','h2','cp','sfx','sfp','y12','yr','dup','ov']
C=C.rename(columns={'live_signals_per_day':'sig_d','acct_n':'an','acct_mean_R':'aR','rp_traded':'n','rp_unresolved':'unr','rp_mean_R':'mR','rp_G':'G','rp_lo':'lo','rp_hi':'hi','rp_p_gt0':'p','rp_bh_q_gt0':'q','rp_p_gt0_4h':'p4','rp_mean_R_incl_marked':'mRm','rp_mean_gross_R':'gR','rp_mean_R_ex_best':'xb','rp_H1_mean_R':'h1','rp_H2_mean_R':'h2','rp_coins_pos':'cp','sf_excess_R':'sfx','sf_p_better':'sfp','y_best_mean12_pct':'y12','y_rank_in_tf':'yr','dup_partner':'dup','dup_overlap_min':'ov'})
C['dup']=C.dup.astype(str).str.slice(0,13)
for tf in args:
    x=C[C.timeframe==tf].sort_values('mR',ascending=False)
    print(tf); print(x[cols].round(2).to_string(index=False))
