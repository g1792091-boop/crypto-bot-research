import sys, os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boot.py')).read())
import numpy as np, pandas as pd
E = sys.argv[1]
F = pd.concat([pd.read_csv(f'{E}/{r}/fill_costs.csv').assign(run=r) for r in ['run-20261005T014624Z','run-20261005T183457Z','current']])
print('events', F.event.value_counts().to_dict(), 'status', F.status.value_counts().to_dict())
f = F[(F.status=='ok') & F.slip_best.notna() & (F.event=='entry')]
g = f.groupby('symbol').agg(n=('slip_best','size'), walk_bp=('slip_best', lambda x: 1e4*x.mean()), gt2=('slip_best', lambda x: (x>2e-4).mean()), notional=('notional','median'))
x = F[(F.status=='ok') & F.slip_best.notna() & (F.event!='entry') & (F.event!='bar')].groupby('symbol').slip_best.agg(lambda x: 1e4*x.mean()).rename('exit_walk_bp')
S_ = pd.read_csv(f'{E}/current/d3_stop_slips.csv'); s = S_[S_.status=='ok']
print('stop slips status', S_.status.value_counts().to_dict())
sl = s[s.exit_reason=='SL'].groupby('symbol').agg(n_sl=('real_bps','size'), real_sl=('real_bps','mean'), paper_sl=('paper_bps','mean'), diff_usd=('diff_usd','sum'))
lk = s[s.exit_reason=='LOCK'].groupby('timeframe').agg(n=('real_bps','size'), real_minus_paper=('real_bps', 'mean'), paper=('paper_bps','mean'))
lk['real_minus_paper'] = lk.real_minus_paper - lk.paper
T = g.join(x).join(sl); T['rt_bp'] = 10 + T.walk_bp + T.real_sl
print(T.round(2).to_string()); print('LOCK real-paper by tf'); print(lk.round(2).to_string())
print('total diff_usd SL', round(sl.diff_usd.sum()), 'all ok rows', round(s.diff_usd.sum()))
