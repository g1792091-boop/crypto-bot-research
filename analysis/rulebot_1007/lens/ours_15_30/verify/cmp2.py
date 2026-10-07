import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
K=pd.read_csv('../cards_15_30.csv'); M=pd.read_csv('my_cells.csv')
m=M.merge(K[['strategy','timeframe','tier','es_n','es_mean_R','es_ci_lo_4h','es_ci_hi_4h','es_bh_q_neg_4h','es_bh_q_pos_4h','sign_v3a_v3b_v4']].rename(columns={'timeframe':'tf','tier':'tier_k'}),on=['strategy','tf'])
print('tier mismatch', (m.tier!=m.tier_k).sum(), ' n mismatch',(m.n!=m.es_n).sum(), ' mean max diff', (m['mean']-m.es_mean_R).abs().max())
x=m[(m.q_neg<0.05)|(m.es_bh_q_neg_4h<0.05)][['strategy','tf','n','mean','q_neg','es_bh_q_neg_4h']]
print(x.round(3).to_string())
