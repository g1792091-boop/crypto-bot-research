import sys
exec(open('vb.py').read())
import pandas as pd, numpy as np
t=pd.read_csv('out/a1_trades.csv')
L=t[(t.exit_reason=='LOCK')&t.kind.isin(['strategy','ds200'])].copy()
L['gap_bp']=1e4*L.side*(L.stop_price-L.exit_raw)/L.stop_price
L['gap_R']=L.side*L.qty*(L.stop_price-L.exit_raw)/L.risk
L['gapped']=L.gap_bp>1e-6
L['lock_step_bp']=1e4*0.02/L.leverage
print(L.groupby('timeframe').agg(n=('R','size'),gapped=('gapped','mean'),gap_bp=('gap_bp','mean'),gap_p90=('gap_bp',lambda x:x.quantile(.9)),gap_R=('gap_R','mean'),gross=('gross_R','mean'),cost=('cost_R','mean'),R=('R','mean')).round(4))
print(L.groupby(['timeframe','leverage']).agg(n=('R','size'),gapped=('gapped','mean'),gap_bp=('gap_bp','mean')).round(3))
print(L.groupby(['run','timeframe']).agg(n=('R','size'),gapped=('gapped','mean'),gap_bp=('gap_bp','mean'),gap_R=('gap_R','mean')).round(3))
# gapped share of SL exits for comparison
S=t[(t.exit_reason=='SL')&t.kind.isin(['strategy','ds200'])]
print('SL gapped share', ((S.side*(S.stop_price-S.exit_raw)/S.stop_price)>1e-9).groupby(S.timeframe).mean().round(4).to_dict())
# per-trade share of all trades
A=t[t.kind.isin(['strategy','ds200'])]
print('lock gap R per trade (all trades):', (L.groupby('timeframe').gap_R.sum()/A.groupby('timeframe').size()).round(4).to_dict())
