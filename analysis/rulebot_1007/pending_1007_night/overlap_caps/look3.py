import sys; sys.path[:0]=['/root/.local/lib/python3.11/site-packages']
import pandas as pd, numpy as np
pd.set_option('display.width',300); pd.set_option('display.max_columns',30); pd.set_option('display.max_rows',300)
df=pd.read_csv('out/pair_shares.csv')
def kap(o,c): return (o-c)/(1-c)
for m in ['card_same15','card_1h','card_4h','15m_bar','15m_1bar','30m_bar','1h_bar']:
    df['k_'+m]=kap(df[m],df[m+'_chance'])
rs=pd.read_csv('out/daily_R_corr.csv',index_col=0); rg=pd.read_csv('out/daily_gross_corr.csv',index_col=0)
rt=pd.read_csv('out/trader_daily_R_corr_CARD.csv',index_col=0)
eh=pd.read_csv('out/entry_coheld_CARD.csv',index_col=0); ehc=pd.read_csv('out/entry_coheld_chance_CARD.csv',index_col=0)
rows=[]
for a in rs.index:
    for b in rs.index:
        if a>=b: continue
        x=df[(df.A==a)&(df.B==b)].iloc[0]; y=df[(df.A==b)&(df.B==a)].iloc[0]
        r=dict(A=a,B=b)
        for m in ['card_same15','card_1h','15m_bar','15m_1bar','30m_bar','1h_bar']:
            r[m]=max(x[m],y[m]); r['k_'+m]=max(x['k_'+m],y['k_'+m])
        r['r_sig']=rs.loc[a,b]; r['r_sig_g']=rg.loc[a,b]; r['r_tr']=rt.loc[a,b]
        r['coheld']=max(eh.loc[a,b],eh.loc[b,a]); r['coheld_lift']=max(eh.loc[a,b]/ehc.loc[a,b],eh.loc[b,a]/ehc.loc[b,a])
        rows.append(r)
P=pd.DataFrame(rows); P.to_csv('out/pairs_all.csv',index=False,float_format='%.4f')
print(P.sort_values('k_card_1h',ascending=False)[['A','B','card_same15','k_card_same15','card_1h','k_card_1h','k_15m_1bar','r_sig','r_sig_g','r_tr','coheld','coheld_lift']].head(40).round(3).to_string())
print(P[['k_card_same15','k_card_1h','r_sig','r_tr','coheld_lift']].corr().round(2))
