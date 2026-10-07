import sys
exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
import pandas as pd, sys
E=sys.argv[1]
for r in ['run-20261005T014624Z','run-20261005T183457Z','current']:
    print('#####',r)
    runs=pd.read_csv(f'{E}/{r}/runs.csv'); print(runs.columns.tolist()); print(runs.head(3).to_string()[:1500]); print(len(runs))
    s=pd.read_csv(f'{E}/{r}/signal_log.csv')
    print('sig',len(s), s.status.value_counts().to_dict(), s.timeframe.value_counts().to_dict())
    print('bar_close span', pd.to_datetime(s.bar_close.min(),unit='ms'), pd.to_datetime(s.bar_close.max(),unit='ms'))
    print('dups(bar,tf,strat,sym)', s.duplicated(['bar_close','timeframe','strategy','symbol']).sum(), 'dups incl side', s.duplicated(['bar_close','timeframe','strategy','symbol','side']).sum())
    o=pd.read_csv(f'{E}/{r}/outcomes.csv')
    print('out',len(o), o.status.value_counts().to_dict()); print(o.reason.value_counts().head(15).to_dict())
    a=pd.read_csv(f'{E}/{r}/accounts.csv'); print('acc',len(a), a.kind.value_counts().to_dict(), a.timeframe.value_counts().to_dict())
