import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
C=pd.read_csv('my_cells.csv'); S=pd.read_csv('my_sigperday.csv'); X=pd.read_csv('my_sameside.csv')[['strategy','tf','ex','lo','hi']].rename(columns={'ex':'ss_ex','lo':'ss_lo','hi':'ss_hi'})
A=pd.read_csv('my_es_rows_all.csv'); T=A[A.status=='TRADED']
extra=T.groupby(['strategy','tf']).agg(mfe=('mfe_R','mean'),mae=('mae_R','mean'),mfe1=('mfe_R',lambda x:(x>=1).mean() if x.notna().any() else np.nan),long=('side',lambda s:(s>0).mean())).reset_index()
C=C.merge(S,on=['strategy','tf'],how='left').merge(X,on=['strategy','tf'],how='left').merge(extra,on=['strategy','tf'],how='left')
pd.set_option('display.width',250)
cells=[('N10_HA_PSAR','30m'),('N10_HA_PSAR','15m'),('S4_BB_BBP','15m'),('S4_BB_BBP','30m'),('N20_EMA9_CHOP','30m'),('N24_DMI','30m'),('N13_3OUTSIDE','15m'),('N17_KC_RSI','15m'),('N23_HA_ST','15m'),('S2_ST_ROC','15m'),('N01_ST_EMA','15m'),('N09_ALLIG_AROON','15m'),('N12_ICHI_AO','15m'),('V39_ALL','15m'),('V45_AMB','15m'),('DOGE','15m'),('N02_ST_KST','15m'),('N07_ICHI_CMO','15m'),('N18_VWMA_MACD','15m'),('N19_FIB_CHOP','15m'),('N22_VORTEX_PSAR','15m'),('N20_EMA9_CHOP','15m'),('N07_ICHI_CMO','30m'),('OBV_S','30m'),('N23_HA_ST','30m'),('N01_ST_EMA','30m'),('DOGE','30m'),('N16_BBRSI','15m'),('N06_MACD_ORB','30m'),('N03_ADX_GC','30m'),('N15_KC_AO','30m'),('S1_EMA_RSI_CHOP','30m'),('N05_PSAR_POC','15m'),('S3_CMO_SANDWICH','15m'),('OBV_S','15m'),('N02_ST_KST','30m'),('N16_BBRSI','30m')]
cols=['strategy','tf','tier','n','mean','lo','hi','signs','m_later','sf_excess','sf_p','sf_n','ss_ex','y5_notional','y5_t','y5_n','live','y5','mfe','mae','mfe1','long','win']
out=pd.concat([C[(C.strategy==a)&(C.tf==b)][cols] for a,b in cells])
out['y5_notional']=out.y5_notional*100
print(out.round(3).to_string())
