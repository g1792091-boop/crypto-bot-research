import sys, os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'vb.py')).read())
import pandas as pd, numpy as np
EXP=sys.argv[1]
fc=[]; 
for rd in ['run-20261005T014624Z','run-20261005T183457Z','current']:
    f=pd.read_csv(f'{EXP}/{rd}/fill_costs.csv'); f['run']=rd; fc.append(f)
fc=pd.concat(fc)
print(fc.groupby(['event','status']).size())
e=fc[(fc.event=='entry')&(fc.status=='ok')]
# dedupe: same run, ts, symbol, notional -> same book walk counted for several accounts
g=e.groupby('symbol').agg(n=('slip_best','size'),walk_bp=('slip_best',lambda x:1e4*x.mean()),walk_med=('slip_best',lambda x:1e4*x.median()),gt2=('slip_best',lambda x:(x>2e-4).mean()),notl=('notional','median'))
ed=e.drop_duplicates(['run','ts','symbol']); g['n_uniq']=ed.groupby('symbol').size(); g['walk_bp_uniq']=ed.groupby('symbol').slip_best.mean()*1e4
# by notional bucket
e=e.assign(nb=pd.cut(e.notional,[0,25e3,50e3,90e3,2e5]))
print(e.groupby(['symbol','nb']).slip_best.agg(lambda x: round(1e4*x.mean(),2)).unstack())
x=fc[(fc.event=='exit')&(fc.status=='ok')]
g['exit_book_walk_bp']=x.groupby('symbol').slip_best.mean()*1e4
st=pd.read_csv(f'{EXP}/current/d3_stop_slips.csv')
print(st.groupby(['exit_reason','status']).size())
for reason in ['SL','LOCK']:
    s=st[(st.exit_reason==reason)&(st.status=='ok')]
    g[f'{reason}_real_bp']=s.groupby('symbol').real_bps.mean(); g[f'{reason}_n']=s.groupby('symbol').size()
    g[f'{reason}_paper_bp']=s.groupby('symbol').paper_bps.mean()
s=st[(st.status=='ok')&st.exit_reason.isin(['SL','LOCK'])]
g['stop_all_real_bp']=s.groupby('symbol').real_bps.mean()
g['rt_real_SLslip']=10+g.walk_bp+g.SL_real_bp
g['rt_real_allstops']=10+g.walk_bp+g.stop_all_real_bp
print(g.round(3).T.to_string())
print('diff_usd by symbol (SL ok):', st[(st.exit_reason=='SL')&(st.status=='ok')].groupby('symbol').diff_usd.sum().round(0).to_dict(), 'total', round(st[(st.exit_reason=='SL')&(st.status=='ok')].diff_usd.sum()))
print('all stop ok diff_usd', s.groupby('symbol').diff_usd.sum().round(0).to_dict())
