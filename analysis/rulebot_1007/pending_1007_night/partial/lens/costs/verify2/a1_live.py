# Independent live-trade cost decomposition from RAW trades.csv (3 runs)
import sys, os, json
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'vb.py')).read())
import pandas as pd, numpy as np
EXP=sys.argv[1]; OUT=sys.argv[2]
runs={'v3a':'run-20261005T014624Z','v3b':'run-20261005T183457Z','v4':'current'}
rows=[]
for rk,rd in runs.items():
    t=pd.read_csv(f'{EXP}/{rd}/trades.csv'); a=pd.read_csv(f'{EXP}/{rd}/accounts.csv')
    a['grp']=a.data.apply(lambda s: json.loads(s).get('group') if isinstance(s,str) else None)
    a['exits']=a.data.apply(lambda s: json.loads(s).get('exits') if isinstance(s,str) else None)
    t=t.merge(a[['account_id','kind','grp','exits']],on='account_id',how='left')
    t['run']=rk; rows.append(t)
t=pd.concat(rows,ignore_index=True)
print('kinds',t.groupby(['run','kind','grp'],dropna=False).size())
s=t.side.astype(float); q=t.qty
slip=0.0002
t['entry_ref']=t.entry_price/(1+s*slip)
# exit raw: for stop-market exits fill=raw*(1-side*slip)
stopx=t.exit_reason.isin(['SL','LOCK','LIQ'])
t['exit_raw']=np.where(stopx, t.exit_price/(1-s*slip), t.exit_price)
t['risk']=q*(t.entry_price-t.stop_initial).abs()
t['R']=t.pnl/t.risk
t['chk']=s*q*(t.exit_price-t.entry_price)-t.fees-t.funding - t.pnl
t['entry_slip_usd']=q*(t.entry_price-t.entry_ref).abs()
t['exit_slip_usd']=np.where(stopx,q*(t.exit_price-t.exit_raw).abs(),0.0)
t['gross_usd']=s*q*(t.exit_raw-t.entry_ref)
t['cost_usd']=t.fees+t.funding+t.entry_slip_usd+t.exit_slip_usd
t['gross_R']=t.gross_usd/t.risk; t['cost_R']=t.cost_usd/t.risk
t['fee_R']=t.fees/t.risk; t['fund_R']=t.funding/t.risk
t['eslip_R']=t.entry_slip_usd/t.risk; t['xslip_R']=t.exit_slip_usd/t.risk
t['ident']=t.gross_R-t.cost_R-t.R
t['stop_pct']=100*(t.entry_price-t.stop_initial).abs()/t.entry_price
t['notional']=q*t.entry_price
print('pnl identity max abs',t.chk.abs().max(),' R identity max',t.ident.abs().max())
print('exit reasons by kind', t.groupby(['kind','exit_reason']).size())
t.to_csv(f'{OUT}/a1_trades.csv',index=False)
t['k2']=np.where(t.kind=='strategy','core36',t.kind)
g=t.groupby(['k2','timeframe']).agg(n=('R','size'),net=('R','mean'),gross=('gross_R','mean'),cost=('cost_R','mean'),fee=('fee_R','mean'),es=('eslip_R','mean'),xs=('xslip_R','mean'),fund=('fund_R','mean'),stop_med=('stop_pct','median'),liq=('exit_reason',lambda x:(x=='LIQ').sum()))
print(g.round(4).to_string())
g.to_csv(f'{OUT}/a1_by_tf.csv')
# per-run
print(t.groupby(['run','k2','timeframe']).agg(n=('R','size'),net=('R','mean'),gross=('gross_R','mean'),cost=('cost_R','mean')).round(3).to_string())
# SL decomposition
sl=t[(t.exit_reason=='SL')&t.kind.isin(['strategy','ds200'])].copy()
sl['gap_R']=s[sl.index]*q[sl.index]*(sl.stop_price-sl.exit_raw)/sl.risk  # positive = gap through stop beyond initial
print(sl.groupby('timeframe').agg(n=('R','size'),R=('R','mean'),fee=('fee_R','mean'),xs=('xslip_R','mean'),gap=('gap_R','mean'),fund=('fund_R','mean'),at_stop=('gap_R',lambda x:(x.abs()<1e-6).mean())).round(4))
# notional/equity relation
t['eq_before']=t.equity_after-t.pnl
t['marg_frac']=t.margin/t.eq_before
print(t.groupby('leverage').agg(n=('R','size'),mf=('marg_frac','median'),notl=('notional','median')))
